"""게이트웨이 HTTP 서버 + 백그라운드 스케줄러(수집·재평가).

클라이언트(에이전트) 흐름:
  POST /needs            작업을 알려주면 가장 좋은 에이전트를 찾아 첫 소개는 무료로 공개
                         (클라이언트 지갑 서명 필요: X-Client, X-Signature)
  GET  /needs/{id}       현재 소개받은 에이전트, 대기 중인 재소개 제안 확인 (need_id가 접근 토큰)
  POST /offers/accept    {"offer_id", "need_id"} → 더 좋은 에이전트로 교체 (무료 정책)
                         유료 정책이면 {"offer_id"} + 수수료 결제 헤더
  POST /offers/decline   {"offer_id", "need_id"}
  POST /needs/{id}/feedback  {"success", "rating"?} 현재 에이전트 평가 → 이후 추천에 반영
  POST /needs/{id}/cancel
"""

import dataclasses
import hmac
import json
import logging
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ..broker.categories import CATEGORIES
from ..broker.discovery import CardFetcher, DiscoveryError, check_public_url, public_client
from ..broker.server import RateLimiter
from ..chain import RPC, normalize
from ..config import GatewayConfig
from ..ledger import Ledger
from ..payments import PaymentError, PaymentVerifier, recover_signer
from ..collector.agent import CollectorAgent, build_agent_sources
from ..collector.auth_discovery import AuthDiscoverer
from ..collector.capabilities import CapabilityProber
from ..collector.health import HealthChecker, Schedule
from ..concierge import front as concierge_front
from ..concierge.front import Front, create_front_app
from .crawler import Crawler, Prober
from . import sns
from .dashboard import dashboard_router
from .admin_security import AdminRoute
from .rag import RagEngine, RagPipeline
from .service import KINDS, GatewayService, NeedError, Policy
from .sanitizer import sanitize_text
from .store import Store, host_of

log = logging.getLogger("agent_market.gateway.server")

NEED_PURPOSE = "agent-gateway-need"
SNS_PURPOSE = "agent-gateway-sns"
SNS_PER_MINUTE = 10
MAX_TASK_CHARS = 4000
REGISTER_PER_MINUTE = 5
MAX_REGISTERED_PER_HOST = 50  # 한 호스트가 직접 등록할 수 있는 서비스 수


class Scheduler(threading.Thread):
    """정보 수집 에이전트(연속 수집 + 지속 헬스체크)를 띄우고, 고객 요청 재평가를 주기적으로 돌린다."""

    def __init__(self, collector: CollectorAgent, service: GatewayService, rescan_interval: float, digest=None, workflows=None, summaries=None):
        super().__init__(daemon=True, name="gateway-scheduler")
        self.collector, self.service, self.digest = collector, service, digest
        self.summaries = summaries  # console maintenance steps (summaries, approved retention); idle until migrated
        self.workflows = workflows
        self.rescan_interval = rescan_interval
        self.stop_event = threading.Event()
        self.workflow_thread = None

    def _run_workflows(self):
        while not self.stop_event.is_set():
            try:self.workflows.run_due()
            except Exception:log.exception('workflow scheduler failed')
            self._flush_observations()
            self.stop_event.wait(5)

    def _flush_observations(self):
        journal=getattr(getattr(self.service,'store',None),'_observation_journal',None)
        if journal is not None:
            try:journal.flush()
            except Exception:log.exception('operational metadata flush failed')

    def run(self) -> None:
        self.collector.start()
        if self.workflows is not None:
            self.workflow_thread = threading.Thread(target=self._run_workflows,daemon=True,name='workflow-scheduler')
            self.workflow_thread.start()
        next_rescan = 0.0
        while not self.stop_event.is_set():
            if time.monotonic() >= next_rescan:
                try:
                    log.info("rescan: %s", self.service.rescan())
                except Exception:
                    log.exception("rescan failed")
                next_rescan = time.monotonic() + self.rescan_interval
            if self.digest is not None:  # Purpose-scoped watches run independently of catalog rescans.
                try:
                    stats = self.digest.run_due()
                    if stats["checked"]:
                        log.info("concierge digest: %s", stats)
                except Exception:
                    log.exception("concierge digest failed")
            for task in self.summaries or ():  # each step is self-throttled and logs its own failures
                result = task.run_due()
                if result and result.get('agents') is not None:
                    log.info("admin health summary: %s", result)
            if self.workflows is None:
                self._flush_observations()
            self.stop_event.wait(min(30,max(1,self.rescan_interval)))
        self.collector.stop()

    def close(self, timeout=30):
        """Drain scheduler threads before a selected Store can be detached."""
        self.stop_event.set()
        self.collector.stop_event.set()
        deadline = time.monotonic() + timeout
        if self.ident is not None:
            self.join(max(0, deadline-time.monotonic()))
        if self.workflow_thread is not None:
            self.workflow_thread.join(max(0, deadline-time.monotonic()))
        collector_drained = self.collector.stop(max(0, deadline-time.monotonic()))
        return (not self.is_alive() and collector_drained
                and (self.workflow_thread is None or not self.workflow_thread.is_alive()))


def front_url(config: GatewayConfig) -> str:
    """에이전트 전용 프론트의 주소 (공개 주소를 지정하지 않았으면 같은 호스트의 프론트 포트). 포트 8080은 제거하고 https로 통일한다."""
    if config.agent_front_url:
        u = config.agent_front_url.rstrip("/")
        if "oneheartall.iptime.org" in u:
            u = u.replace("oneheartall.iptime.org", "agentconcierge.biz")
        if ":8080" in u:
            u = u.replace(":8080", "")
        if u.startswith("http://agentconcierge.biz"):
            u = "https://" + u[7:]
        return u
    import os
    host = config.agent_front_host or os.environ.get("HOST", "127.0.0.1")
    target_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    port = config.agent_front_port
    if port == 8080:
        scheme = "https"
        port_part = ""
    else:
        scheme = "https" if (port == 443 or config.ssl_enabled) else "http"
        port_part = f":{port}" if (scheme == "https" and port != 443) or (scheme == "http" and port != 80) else ""
    res = f"{scheme}://{target_host}{port_part}"
    if ":8080" in res:
        res = res.replace(":8080", "")
        if res.startswith("http://"):
            res = "https://" + res[7:]
    return res


def concierge_llm(config: GatewayConfig):
    """컨시어지용 로컬 LLM. auto면 Ollama에 모델이 있을 때만 쓰고, 없으면 규칙만으로 대화한다."""
    if config.concierge_llm == "off":
        return None
    from ..concierge.llm import LocalLLM
    llm = LocalLLM(config.workspace_model_url if config.workspace_model_enabled else config.ollama_url,
                   config.workspace_model_name if config.workspace_model_enabled else config.concierge_model,
                   config.concierge_llm_timeout, lead=config.concierge_llm_lead,
                   provider=config.workspace_model_provider if config.workspace_model_enabled else 'ollama',
                   fallback_url=config.workspace_model_fallback_url if config.workspace_model_enabled else '',
                   allow_http=config.workspace_model_allow_http)
    if config.concierge_llm == "auto" and not llm.available():
        log.info("concierge LLM: %s not found at %s — using rules only", config.concierge_model, config.ollama_url)
        return None
    log.info("concierge LLM: %s via %s", config.concierge_model, config.ollama_url)
    return llm


def make_notifier(allow_private: bool):
    http = public_client(allow_private, timeout=5.0, follow_redirects=False)

    def notify(url: str, payload: dict) -> None:
        try:
            if not allow_private:
                check_public_url(url)
            http.post(url, json=payload)
        except Exception as exc:  # 알림 실패는 치명적이지 않음 (클라이언트는 GET /needs 로도 확인 가능)
            log.warning("webhook %s failed: %s", url, exc)

    return notify


async def json_body(request: Request) -> tuple[bytes, dict]:
    body = await request.body()
    try:
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError
    except ValueError:
        raise HTTPException(400, "JSON 객체 body가 필요합니다.")
    return body, data


def _compose_app(
    config: GatewayConfig,
    store: Store | None = None,
    verifier: PaymentVerifier | None = None,
    crawler: Crawler | None = None,
    prober: Prober | None = None,
    fetcher: CardFetcher | None = None,
    policy: Policy = Policy(),
    courier=None,
    runtime_storage=None,
    service_role='legacy',
) -> FastAPI:
    if service_role not in ('legacy', 'frontend', 'admin', 'jobs', 'execution'):
        raise ValueError('invalid_service_role')
    net = config.network
    policy = dataclasses.replace(policy, free=config.free)
    ledger = Ledger(store=store)
    if verifier is None and config.pay_to:  # 지갑이 없으면(무료 정책) 수수료 결제를 받지 않는다
        verifier = PaymentVerifier(RPC(net.rpc_url), net.token, config.pay_to, config.min_confirmations)
    crawler = crawler or Crawler(store, page_delay=config.crawl_page_delay, full_interval=config.crawl_full_interval)
    checker = HealthChecker(store, allow_private=config.allow_private_urls, workers=config.health_workers,
                            schedule=Schedule(interval=config.health_interval))
    caps = CapabilityProber(store, allow_private=config.allow_private_urls, max_age=config.capability_max_age,
                            workers=config.capability_workers, trials=config.trials, trial_max_age=config.trial_max_age)
    auth = AuthDiscoverer(store, allow_private=config.allow_private_urls, max_age=config.auth_max_age,
                          workers=config.capability_workers)
    agents, erc, wellknown = build_agent_sources(store, config.allow_private_urls, config.capability_workers,
                                                 config.capability_max_age, config.trials, config.trial_max_age,
                                                 config.erc8004_chains, config.agent_discovery)
    rag_engine = RagEngine(ollama_url=config.embedding_ollama_url or config.ollama_url)
    rag_engine.embeddings_enabled = (config.local_ollama_enabled if config.embedding_enabled is None else config.embedding_enabled)
    rag_pipeline = RagPipeline(rag_engine, batch_size=50)
    collector = CollectorAgent(store, crawler, checker, min_gap=config.crawl_min_gap, capabilities=caps, auth=auth,
                               agents=agents, erc8004=erc, wellknown=wellknown, health_lanes=config.health_lanes,
                               rag_pipeline=rag_pipeline)
    prober = prober or Prober(store, checker=checker)
    fetcher = fetcher or CardFetcher(allow_private=config.allow_private_urls, network={"chain_id": net.chain_id, "token": net.token})
    service = GatewayService(store, prober, ledger, policy, notifier=make_notifier(config.allow_private_urls))
    need_limit = RateLimiter(30)
    register_limit = RateLimiter(REGISTER_PER_MINUTE)
    sns_limit = RateLimiter(SNS_PER_MINUTE)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from ..workspace_platform import start_for
        if service_role in ('legacy', 'jobs'):
            start_for(front)
        scheduler = None
        if config.scheduler and service_role in ('legacy', 'jobs'):
            from ..workspace_admin_summaries import HealthSummaries
            from ..workspace_admin_retention import Retention
            from ..workflow_retention_schedule import WorkflowRetention
            from ..nvd_snapshot_schedule import NvdSnapshotRefresh
            from ..fallback_schedule import AirportIndexRefresh, FallbackWatchStep
            from ..necklace_schedule import NecklaceStep  # PM 11-14 14:2x: hourly necklace watch + judge, daily summary
            scheduler = Scheduler(collector, service, config.rescan_interval, front.digest,
                                  front.workflows if service_role == 'legacy' else None,
                                  summaries=[HealthSummaries(store), Retention(store), WorkflowRetention(front.workflows),
                                             NvdSnapshotRefresh(), FallbackWatchStep(), AirportIndexRefresh(),
                                             NecklaceStep(store)])
            scheduler.start()
        try:
            yield
        finally:
            # Each drain step is timed so a slow stop names the step that held it.
            started = time.monotonic()
            def took(step, began):
                log.info("shutdown: %s finished in %.1fs (total %.1fs)", step, time.monotonic() - began, time.monotonic() - started)
            storage_drained = True
            if scheduler:
                began = time.monotonic()
                storage_drained = await run_in_threadpool(scheduler.close)
                took("collector and scheduler", began)
            from ..workspace_platform import close_for
            began = time.monotonic()
            if not await run_in_threadpool(close_for, front):
                log.warning("Private evaluation worker shutdown timed out")
                storage_drained = False
            took("workspace workers", began)
            began = time.monotonic()
            drained = await run_in_threadpool(front.book.close)
            if not drained:
                log.warning("Anonymous visit worker shutdown timed out")
                storage_drained = False
            took("visit worker", began)
            from ..workflow_worker import drain_worker
            began = time.monotonic()
            if not await run_in_threadpool(drain_worker, front.workflows):
                log.warning("Workflow worker shutdown timed out; storage remains attached")
                storage_drained = False
            took("workflow worker", began)
            journal=getattr(store,'_observation_journal',None)
            if journal is not None:
                await run_in_threadpool(journal.close)
            if runtime_storage is not None and storage_drained:
                await run_in_threadpool(runtime_storage.close)

    app = FastAPI(title="Agent Introduction Gateway", lifespan=lifespan)
    app.router.route_class = AdminRoute

    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-XSS-Protection", "1; mode=block")
        if request.url.path.startswith("/admin") or request.url.path in ("/needs", "/offers/accept"):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.state.service = service
    app.state.runtime_storage = runtime_storage
    app.state.service_role = service_role
    app.state.collector = collector
    app.state.rag_engine = rag_engine
    app.state.rag_pipeline = rag_pipeline
    # 에이전트 전용 프론트: 이 앱(관리·게이트웨이 API)에는 경로를 붙이지 않고, main()이 별도 포트의 별도 앱으로 띄운다
    front_rag = rag_engine
    front = Front(store, allow_private=config.allow_private_urls, courier=courier, llm=None,
                  public_url=config.agent_front_url, rag_engine=front_rag)
    from ..edge_gateway.output_relay import install as install_edge_output_relay
    install_edge_output_relay(app,front)
    if config.workspace_model_enabled:
        from ..concierge.llm import LocalLLM
        from .. import model_slots
        # Only unrecognized language takes this bounded path. Known tasks never
        # invoke generation, and recommendations remain current catalog facts.
        front.language_model = LocalLLM(config.workspace_model_url, config.workspace_model_name,
            # 11-11: the model server runs 4 at a time; agent_market.model_slots shares that budget
            # across processes, so this process's own bound is simply the whole budget.
            timeout=2, lead=False, http=rag_engine.http, concurrency=model_slots.total(),
            provider=config.workspace_model_provider, allow_http=config.workspace_model_allow_http)
        front.concierge.query_rewriter = front.language_model.rewrite_task
        front.concierge.query_summarizer = front.language_model.summarize_task
        from ..workflow_model_proposer import OllamaGraphProposer
        from ..workspace_integrations import PrivateIntegrations
        front._workspace_integrations = PrivateIntegrations(model_proposer=OllamaGraphProposer(
            config.workspace_model_url, config.workspace_model_name,
            provider=config.workspace_model_provider, allow_http=config.workspace_model_allow_http,
            fallback_endpoint=config.workspace_model_fallback_url))
        rag_engine.generation_url = config.workspace_model_url
        rag_engine.generation_fallback_url = config.workspace_model_fallback_url
        rag_engine.generation_provider = config.workspace_model_provider
        rag_engine.generation_allow_http = config.workspace_model_allow_http
        rag_engine.generation_model = config.workspace_model_name
    app.state.front = front
    from .ssl_manager import get_ssl_manager
    ssl_mgr = get_ssl_manager()
    app.state.ssl_manager = ssl_mgr
    if service_role in ('legacy', 'admin'):
        app.include_router(dashboard_router(store, config.db_path, config.admin_token, collector, service, crawler, front,
                                            front_url=front_url(config), rag_engine=rag_engine, ssl_manager=ssl_mgr))
    else:
        from ..workspace_platform import platform_for
        platform_for(front)

    def fee_requirements(amount: int) -> dict:
        return {
            "scheme": "erc20-transfer", "network": net.name, "chain_id": net.chain_id, "token": net.token,
            "decimals": 6, "amount": amount, "pay_to": config.pay_to,
            "headers": ["X-Payment-Tx", "X-Payment-Signature"],
            "signature_message": "agent-market:{tx_hash}:{sha256(request_body)}",
        }

    def fail(exc: NeedError):
        return JSONResponse({"error": str(exc)}, status_code=exc.status)

    @app.get("/.well-known/agent.json")
    def agent_card():
        return {
            "name": "agent-intro-gateway",
            "role": "gateway",
            "audience": concierge_front.AUDIENCE,
            "notice": concierge_front.NOTICE,
            "concierge": {"url": front_url(config), "chat": "POST /chat", "a2a_card": "/.well-known/agent-card.json",
                          "mcp": "POST /mcp", "guide": "/llms.txt"} if config.agent_front else None,
            "description": (
                "필요한 작업을 알려주면 x402 Bazaar·MCP Registry 등에서 가장 좋은 AI 에이전트를 찾아 소개하고, "
                "관계를 유지하면서 더 좋은 에이전트가 나타나면 다시 소개합니다. "
                + ("모든 소개는 무료입니다." if policy.free else "첫 소개는 무료, 재소개는 수수료(USDC)를 받습니다.")
            ),
            "categories": [{"id": c.id, "name": c.name} for c in CATEGORIES.values()],
            "pricing": {"model": "free"} if policy.free else {
                "model": "paid", "first_intro": 0, "upgrade_fee": {c: service.fee_for(c) for c in CATEGORIES}, "currency": "USDC(6 decimals)"},
            "network": {"name": net.name, "chain_id": net.chain_id, "token": net.token, "pay_to": config.pay_to},
            "endpoints": {"create_need": "POST /needs", "need": "GET /needs/{need_id}", "accept": "POST /offers/accept",
                          "decline": "POST /offers/decline", "feedback": "POST /needs/{need_id}/feedback",
                          "review": "POST /sns/posts (A2A·MCP·x402·에이전트에 대한 의견·평가)"},
            "auth": {"create_need": "X-Client: <wallet>, X-Signature: sign('agent-gateway-need:{client}:{sha256(body)}')",
                     "review": "X-Client: <wallet>, X-Signature: sign('agent-gateway-sns:{client}:{sha256(body)}')"},
            "need_options": {
                "task": "필요한 작업 설명 (필수)", "category": "카테고리 ID (생략 시 자동 분류)", "max_price": "USDC 최소 단위",
                "language": "원하는 언어 (ko, en, ja ...): 지원하는 에이전트를 우선",
                "region": "대상 나라·지역 (kr, us, eu, br ...): 다른 나라 전용 에이전트는 제외, 전 세계 공통은 포함",
                "auth": "'none': 계정·API 키 없이 바로 쓸 수 있는 것만, 'agent': 사람 없이 에이전트 혼자 쓸 수 있는 것만"
                        " (인증 불필요 또는 OAuth client_credentials + 자동 등록), 'any'(기본)",
                "min_grade": "최소 품질 등급 A~F (규칙 기반 MCP 평가: 가용성·도구 정의·보안·컨텍스트·프로토콜·출처)."
                             " 평가가 없는 에이전트는 포함, 보안 격리된 MCP는 항상 제외",
                "kinds": "['x402','mcp','a2a'] 중 일부", "networks": "x402 결제 네트워크", "webhook": "알림 받을 URL",
            },
        }

    @app.get("/health")
    def health():
        crawl = store.get_meta("last_crawl") or {}
        return {"ok": True, "resources": sum(sum(v.values()) for v in store.resource_counts().values()),
                "last_crawl_at": crawl.get("at"), "last_rescan": store.get_meta("last_rescan")}

    @app.post("/needs")
    async def create_need(request: Request, x_client: str | None = Header(default=None), x_signature: str | None = Header(default=None)):
        body, data = await json_body(request)
        ip = request.client.host if request.client else "unknown"
        if not need_limit.allow(ip):
            raise HTTPException(429, "요청이 너무 많습니다.")
        if not x_client or not x_signature:
            raise HTTPException(401, "X-Client(지갑 주소)와 X-Signature가 필요합니다.")
        try:
            signer = recover_signer(NEED_PURPOSE, x_client, body, x_signature)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if signer != normalize(x_client):
            raise HTTPException(403, "서명자가 X-Client와 다릅니다.")

        task = data.get("task")
        if not isinstance(task, str) or not task.strip() or len(task) > MAX_TASK_CHARS:
            raise HTTPException(400, f"task(1~{MAX_TASK_CHARS}자)가 필요합니다.")
        task = sanitize_text(task, max_length=MAX_TASK_CHARS)
        if not task:
            raise HTTPException(400, "유효한 task 내용이 필요합니다.")
        max_price = data.get("max_price")
        if max_price is not None and (not isinstance(max_price, int) or isinstance(max_price, bool) or max_price < 0):
            raise HTTPException(400, "max_price는 USDC 최소 단위 정수입니다.")
        networks = data.get("networks")
        if networks is not None and (not isinstance(networks, list) or not all(isinstance(n, str) for n in networks)):
            raise HTTPException(400, 'networks는 ["eip155:8453"] 같은 문자열 목록입니다.')
        kinds = data.get("kinds")
        if kinds is not None and (not isinstance(kinds, list) or not all(k in KINDS for k in kinds)):
            raise HTTPException(400, f"kinds는 {list(KINDS)}의 부분집합입니다.")
        webhook = data.get("webhook")
        if webhook is not None:
            if not isinstance(webhook, str):
                raise HTTPException(400, "webhook은 URL 문자열입니다.")
            if not config.allow_private_urls:
                try:
                    check_public_url(webhook)
                except DiscoveryError as exc:
                    raise HTTPException(400, f"webhook: {exc}")
        try:
            from ..concierge.memory import fingerprint  # 11-10: a same-day pseudonym, never the address itself
            result = service.create_need(signer, task.strip(), data.get("category"), max_price, networks, kinds, webhook, fingerprint(ip, None),
                                         language=data.get("language"), region=data.get("region"), auth=data.get("auth"),
                                         min_grade=data.get("min_grade"))
        except NeedError as exc:
            return fail(exc)
        if result.get("status") == "offer_pending" and result["offer"]["fee"] > 0:
            result["offer"]["payment"] = fee_requirements(result["offer"]["fee"])
        return result

    @app.get("/needs/{need_id}")
    def get_need(need_id: str):
        try:
            result = service.get_need(need_id)
        except NeedError as exc:
            return fail(exc)
        for o in result["pending_offers"]:
            if o["fee"] > 0:
                o["payment"] = fee_requirements(o["fee"])
        return result

    @app.post("/offers/accept")
    async def accept(request: Request, x_payment_tx: str | None = Header(default=None), x_payment_signature: str | None = Header(default=None)):
        body, data = await json_body(request)
        offer_id = str(data.get("offer_id", ""))
        rows = store.query("SELECT fee, status FROM offers WHERE offer_id=?", (offer_id,))
        if not rows:
            raise HTTPException(404, "없는 제안입니다.")
        fee = rows[0]["fee"]
        if fee == 0:  # 무료 제안: 결제 없이 need_id로 소유자 확인
            try:
                return service.accept_offer(offer_id, None, need_id=str(data.get("need_id", "")))
            except NeedError as exc:
                return fail(exc)
        if verifier is None:  # 예전 유료 정책 때 만든 제안이 남아 있지만 지금은 지갑이 없음
            return JSONResponse({'error':'Payment handling is being prepared for this offer.',
                'error_code':'PAYMENT_UNAVAILABLE','retryable':False},status_code=503)
        if not x_payment_tx or not x_payment_signature:
            return JSONResponse({"error": "payment required", "payment": fee_requirements(fee)}, status_code=402)
        try:
            payment = await run_in_threadpool(verifier.verify, x_payment_tx, x_payment_signature, body, fee)
        except PaymentError as exc:
            return JSONResponse({"error": str(exc), "error_code": exc.error_code, "validation_stage": exc.stage, "retryable": exc.retryable, "payment": fee_requirements(fee)}, status_code=exc.status)
        try:
            return service.accept_offer(offer_id, payment)
        except NeedError as exc:
            return fail(exc)

    @app.post("/offers/decline")
    async def decline(request: Request):
        _, data = await json_body(request)
        try:
            service.decline_offer(str(data.get("offer_id", "")), str(data.get("need_id", "")))
        except NeedError as exc:
            return fail(exc)
        return {"ok": True}

    @app.post("/needs/{need_id}/feedback")
    async def feedback(need_id: str, request: Request):
        _, data = await json_body(request)
        success, rating = data.get("success"), data.get("rating")
        if not isinstance(success, bool):
            raise HTTPException(400, "success(bool)가 필요합니다.")
        if rating is not None and (not isinstance(rating, int) or isinstance(rating, bool) or not 1 <= rating <= 5):
            raise HTTPException(400, "rating은 1~5 정수입니다.")
        try:
            res = service.feedback(need_id, success, rating)
        except NeedError as exc:
            return fail(exc)
        return {"ok": True, **(res or {})}

    @app.post("/needs/{need_id}/cancel")
    def cancel(need_id: str):
        try:
            service.cancel(need_id)
        except NeedError as exc:
            return fail(exc)
        return {"ok": True}

    @app.post("/sns/posts")
    async def sns_post(request: Request, x_client: str | None = Header(default=None), x_signature: str | None = Header(default=None)):
        """에이전트가 A2A·MCP·x402나 특정 에이전트에 대한 의견·평가를 남긴다 (관리 화면 SNS에 '에이전트' 글로 보임).

        body: {"body", "protocol"?, "rating"? 1~5, "resource_id"?, "author"? 표시 이름, "parent_key"? 댓글}
        서명: X-Client: <지갑>, X-Signature: sign('agent-gateway-sns:{client}:{sha256(body)}')
        """
        if not sns_limit.allow(request.client.host if request.client else "unknown"):
            raise HTTPException(429, "요청이 너무 많습니다.")
        body, data = await json_body(request)
        if not x_client or not x_signature:
            raise HTTPException(401, "X-Client(지갑 주소)와 X-Signature가 필요합니다.")
        try:
            signer = recover_signer(SNS_PURPOSE, x_client, body, x_signature)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if signer != normalize(x_client):
            raise HTTPException(403, "서명자가 X-Client와 다릅니다.")
        author = str(data.get("author") or "")[:40] or f"에이전트 {signer[:6]}…{signer[-4:]}"
        try:
            return sns.create_post(store, data.get("body"), author, "agent", f"wallet:{signer}", data.get("protocol") or None,
                                   data.get("rating"), data.get("parent_key"), data.get("resource_id"), handle=signer)
        except sns.SnsError as exc:
            raise HTTPException(400, str(exc))

    @app.post("/agents/register")
    async def register(request: Request):
        """에이전트가 직접 등록할 수도 있다 (agent card 형식, 기존 브로커와 같음).

        인증 없이 열려 있으므로 IP당 요청 수와 호스트당 등록 수를 제한한다. 등록된 에이전트는 수집 에이전트가
        계속 헬스체크한다. Card membership is separate from local operation.
        """
        if not register_limit.allow(request.client.host if request.client else "unknown"):
            raise HTTPException(429, "요청이 너무 많습니다.")
        _, data = await json_body(request)
        url = data.get("url")
        if not isinstance(url, str):
            raise HTTPException(400, '{"url": "<에이전트 base URL>"}')
        try:
            card = fetcher.fetch(url)
        except DiscoveryError as exc:
            raise HTTPException(422, str(exc))
        card_url = url.rstrip("/") + "/.well-known/agent.json"
        rows = store.query("SELECT id, key, details FROM resources WHERE source='registered' AND active=1 AND host=?",
                           (host_of(url),))
        same_card = {}
        for r in rows:
            try:
                d = json.loads(r["details"] or "{}")
                if isinstance(d, dict) and d.get("agent_card") == card_url:
                    same_card[r["key"]] = r["id"]
            except Exception:
                pass
        if len(rows) - len(same_card) + len(card["services"]) > MAX_REGISTERED_PER_HOST:
            raise HTTPException(422, f"한 호스트에서 등록할 수 있는 서비스는 최대 {MAX_REGISTERED_PER_HOST}개입니다.")
        ids, keys = [], set()
        for s in card["services"]:
            keys.add(key := f"a2a:{s['endpoint']}")
            ids.append(store.upsert_resource({
                "key": key, "source": "registered", "kind": "a2a", "url": s["endpoint"],
                "name": f"{card['name']}/{s['name']}", "description": s["description"], "category": s["category"],
                "networks": [f"eip155:{net.chain_id}"], "price_usdc": s["price"], "pay_to": card["pay_to"],
                "method": "POST", "details": {"agent_card": card_url},
            }))
        removed = [rid for key, rid in same_card.items() if key not in keys]  # card에서 빠진 서비스
        if removed:
            with store.tx() as db:
                from ..managed_catalog import mark_ids_missing
                mark_ids_missing(db, removed)
        return {"registered": len(ids), "resource_ids": ids, "deactivated": 0,
                "registry_missing": len(removed)}

    def require_admin(authorization: str | None):
        expected = f"Bearer {config.admin_token}" if config.admin_token else None
        if expected is None or authorization is None or not hmac.compare_digest(authorization.encode(), expected.encode()):
            raise HTTPException(401, "ADMIN_TOKEN 필요")

    @app.get("/admin/report")
    def report(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return service.report()

    @app.post("/admin/crawl")
    def crawl_now(authorization: str | None = Header(default=None), full: bool = True):
        require_admin(authorization)
        if getattr(store, '_service_control', None) is not None:
            return store._service_control.enqueue('crawl', {'force_full': full})
        return crawler.crawl_all(force_full=full)

    @app.post("/admin/rescan")
    def rescan_now(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        if getattr(store, '_service_control', None) is not None:
            return store._service_control.enqueue('rescan')
        return service.rescan()

    return app


def create_app(
    config: GatewayConfig,
    store: Store | None = None,
    verifier: PaymentVerifier | None = None,
    crawler: Crawler | None = None,
    prober: Prober | None = None,
    fetcher: CardFetcher | None = None,
    policy: Policy = Policy(),
    courier=None,
    service_role='legacy',
) -> FastAPI:
    """Compose one explicitly selected Store and clean up failed construction."""
    storage = None
    if store is None:
        from ..application_runtime import open_runtime_storage
        storage = open_runtime_storage(config.db_path)
        store = storage.store
    try:
        return _compose_app(config,store,verifier,crawler,prober,fetcher,policy,courier,
                            runtime_storage=storage, service_role=service_role)
    except BaseException:
        if storage is not None:
            storage.close()
        raise


def main() -> None:
    """관리·게이트웨이 API(:PORT, 기본 8200)와 에이전트 전용 프론트(:AGENT_FRONT_PORT, 기본 8400)를 한 프로세스에서 다른 포트로 띄운다.
    두 앱은 경로를 공유하지 않는다 (프론트에는 /admin이 없고, 관리 쪽에는 에이전트 대화 창구가 없다)."""
    import asyncio
    import contextlib
    import os
    import signal

    import uvicorn
    from .startup import prefer_patched_macos_sqlite, reserve_listeners
    prefer_patched_macos_sqlite()
    from .ssl_manager import get_ssl_manager
    from ..logger import setup_logging, shutdown_logging
    config = GatewayConfig.from_env()
    setup_logging(
        log_dir=config.log_dir,
        archive_dir=config.log_archive_dir,
        default_level=config.log_level,
        compress_months=config.log_compress_months,
        log_to_console=config.log_to_console,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)  # 요청마다 찍히는 로그는 끔
    if not config.network.is_testnet:
        log.warning("메인넷(%s)에서 실제 USDC 수수료를 받습니다.", config.network.name)
    host = os.environ.get("HOST", "127.0.0.1")
    from .deployment_security import TrustedIngressMiddleware, trusted_proxy_options, validate_production_runtime
    proxy = trusted_proxy_options()
    admin_port = int(os.environ.get("PORT", "8200"))
    front_port = config.agent_front_port
    endpoints = [("admin", host, admin_port)]
    if config.agent_front:
        endpoints.append(("agent-front", config.agent_front_host or host, front_port))
    try:
        with reserve_listeners(endpoints) as listeners:
            app = create_app(config)
            validate_production_runtime(config, app.state.front.store)
            ssl_mgr = get_ssl_manager()
            if os.environ.get("DEPLOYMENT_MODE") != "production":
                ssl_mgr.start_scheduler()  # Development-only self-signed certificate lifecycle.

            if app.state.front.llm is not None:
                app.state.front.llm.warm()  # 첫 에이전트가 모델 로딩을 기다리지 않게
            servers = [uvicorn.Server(uvicorn.Config(TrustedIngressMiddleware(app), host=host, port=admin_port,
                                                    timeout_keep_alive=75, log_config=None, **proxy))]
            if config.agent_front:
                front_app = create_front_app(app.state.front,
                    workspace_access_enabled=config.customer_workspace_access,
                    workspace_link_enabled=config.customer_workspace_link,
                    owned_data_agents_enabled=True, manage_book_lifecycle=False)
                ssl_opts = {}
                if config.ssl_enabled:
                    domain = None
                    if config.agent_front_url:
                        from urllib.parse import urlparse
                        domain = urlparse(config.agent_front_url).hostname
                    sans = None
                    if domain and domain not in ("localhost", "127.0.0.1", "0.0.0.0"):
                        sans = [f"DNS:{domain}", "DNS:localhost", "IP:127.0.0.1", "IP:0.0.0.0", "IP:192.168.0.4"]
                    if os.environ.get("DEPLOYMENT_MODE") != "production":
                        ssl_mgr.check_and_auto_renew(common_name=domain or "localhost", sans=sans)
                    if os.path.exists(config.ssl_certfile) and os.path.exists(config.ssl_keyfile):
                        ssl_opts = {
                            "ssl_certfile": config.ssl_certfile,
                            "ssl_keyfile": config.ssl_keyfile,
                        }
                def _prewarm_front():
                    try:
                        app.state.front.bootstrap_snapshot()
                        app.state.front.bootstrap_snapshot_json()
                        app.state.front.live_counts()
                    except Exception as e:
                        log.warning("Frontend prewarm failed: %s", e)
                threading.Thread(target=_prewarm_front, daemon=True, name="front-startup-prewarm").start()
                servers.append(uvicorn.Server(uvicorn.Config(TrustedIngressMiddleware(front_app), host=config.agent_front_host or host, port=front_port,
                                                             lifespan="off", timeout_keep_alive=75, log_config=None, **ssl_opts, **proxy)))
                log.info("agent-only front on %s (port %d, SSL: %s, admin stays on its own port)",
                         front_url(config), front_port, bool(ssl_opts))

            async def serve():
                for s in servers:  # Ctrl+C 한 번에 두 서버가 함께 멈추도록 신호는 여기서 처리
                    s.capture_signals = contextlib.nullcontext
                    s.install_signal_handlers = lambda: None
                loop = asyncio.get_running_loop()
                for sig in (signal.SIGINT, signal.SIGTERM):
                    loop.add_signal_handler(sig, lambda: [setattr(s, "should_exit", True) for s in servers])
                await asyncio.gather(*(server.serve(sockets=[listener]) for server, listener in zip(servers, listeners)))

            asyncio.run(serve())

    except RuntimeError as exc:
        log.error("Gateway startup stopped: %s", exc)
        raise SystemExit(1) from exc
    finally:
        shutdown_logging()

if __name__ == "__main__":
    main()
