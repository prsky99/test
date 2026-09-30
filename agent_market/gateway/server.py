"""게이트웨이 HTTP 서버 + 백그라운드 스케줄러(수집·재평가).

클라이언트(에이전트) 흐름:
  POST /needs            작업을 알려주면 가장 좋은 에이전트를 찾아 첫 소개는 무료로 공개
                         (클라이언트 지갑 서명 필요: X-Client, X-Signature)
  GET  /needs/{id}       현재 소개받은 에이전트, 대기 중인 재소개 제안 확인 (need_id가 접근 토큰)
  POST /offers/accept    {"offer_id"} + 수수료 결제 헤더 → 더 좋은 에이전트 공개
  POST /offers/decline   {"offer_id", "need_id"}
  POST /needs/{id}/feedback  {"success", "rating"?} 현재 에이전트 평가 → 이후 추천에 반영
  POST /needs/{id}/cancel
"""

import hmac
import json
import logging
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from ..broker.categories import CATEGORIES
from ..broker.discovery import CardFetcher, DiscoveryError, check_public_url
from ..broker.server import RateLimiter
from ..chain import RPC, normalize
from ..config import GatewayConfig
from ..ledger import Ledger
from ..payments import PaymentError, PaymentVerifier, recover_signer
from .crawler import Crawler, Prober
from .service import KINDS, GatewayService, NeedError, Policy
from .store import Store

log = logging.getLogger("agent_market.gateway.server")

NEED_PURPOSE = "agent-gateway-need"
MAX_TASK_CHARS = 4000


class Scheduler(threading.Thread):
    def __init__(self, crawler: Crawler, service: GatewayService, store: Store, crawl_interval: float, rescan_interval: float):
        super().__init__(daemon=True, name="gateway-scheduler")
        self.crawler, self.service, self.store = crawler, service, store
        self.crawl_interval, self.rescan_interval = crawl_interval, rescan_interval
        self.stop_event = threading.Event()

    def run(self) -> None:
        next_rescan = 0.0
        while not self.stop_event.is_set():
            last = (self.store.get_meta("last_crawl") or {}).get("at", 0)
            if time.time() - last >= self.crawl_interval:
                log.info("crawl start")
                log.info("crawl done: %s", self.crawler.crawl_all())
            if time.time() >= next_rescan:
                try:
                    log.info("rescan: %s", self.service.rescan())
                except Exception:
                    log.exception("rescan failed")
                next_rescan = time.time() + self.rescan_interval
            self.stop_event.wait(30)


def make_notifier(allow_private: bool):
    http = httpx.Client(timeout=5.0, follow_redirects=False)

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


def create_app(
    config: GatewayConfig,
    store: Store | None = None,
    verifier: PaymentVerifier | None = None,
    crawler: Crawler | None = None,
    prober: Prober | None = None,
    fetcher: CardFetcher | None = None,
    policy: Policy = Policy(),
) -> FastAPI:
    net = config.network
    if store is None:
        Path(config.db_path).parent.mkdir(parents=True, exist_ok=True)
        store = Store(config.db_path)
    ledger = Ledger(config.db_path if config.db_path != ":memory:" else ":memory:")
    verifier = verifier or PaymentVerifier(RPC(net.rpc_url), net.token, config.pay_to, config.min_confirmations)
    crawler = crawler or Crawler(store)
    prober = prober or Prober(store, allow_private=config.allow_private_urls)
    fetcher = fetcher or CardFetcher(allow_private=config.allow_private_urls, network={"chain_id": net.chain_id, "token": net.token})
    service = GatewayService(store, prober, ledger, policy, notifier=make_notifier(config.allow_private_urls))
    need_limit = RateLimiter(30)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        scheduler = None
        if config.scheduler:
            scheduler = Scheduler(crawler, service, store, config.crawl_interval, config.rescan_interval)
            scheduler.start()
        yield
        if scheduler:
            scheduler.stop_event.set()

    app = FastAPI(title="Agent Introduction Gateway", lifespan=lifespan)
    app.state.service = service

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
            "description": (
                "필요한 작업을 알려주면 x402 Bazaar·MCP Registry 등에서 가장 좋은 AI 에이전트를 찾아 소개합니다. "
                "첫 소개는 무료이고, 이후 더 좋은 에이전트가 나타나면 재소개하며 수수료(USDC)를 받습니다."
            ),
            "categories": [{"id": c.id, "name": c.name} for c in CATEGORIES.values()],
            "pricing": {"first_intro": 0, "upgrade_fee": {c: service.fee_for(c) for c in CATEGORIES}, "currency": "USDC(6 decimals)"},
            "network": {"name": net.name, "chain_id": net.chain_id, "token": net.token, "pay_to": config.pay_to},
            "endpoints": {"create_need": "POST /needs", "need": "GET /needs/{need_id}", "accept": "POST /offers/accept",
                          "decline": "POST /offers/decline", "feedback": "POST /needs/{need_id}/feedback"},
            "auth": {"create_need": "X-Client: <wallet>, X-Signature: sign('agent-gateway-need:{client}:{sha256(body)}')"},
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
            result = service.create_need(signer, task.strip(), data.get("category"), max_price, networks, kinds, webhook, ip)
        except NeedError as exc:
            return fail(exc)
        if result.get("status") == "offer_pending":
            result["offer"]["payment"] = fee_requirements(result["offer"]["fee"])
        return result

    @app.get("/needs/{need_id}")
    def get_need(need_id: str):
        try:
            result = service.get_need(need_id)
        except NeedError as exc:
            return fail(exc)
        for o in result["pending_offers"]:
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
        if not x_payment_tx or not x_payment_signature:
            return JSONResponse({"error": "payment required", "payment": fee_requirements(fee)}, status_code=402)
        try:
            payment = verifier.verify(x_payment_tx, x_payment_signature, body, fee)
        except PaymentError as exc:
            return JSONResponse({"error": str(exc), "retryable": exc.retryable, "payment": fee_requirements(fee)}, status_code=exc.status)
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
            service.feedback(need_id, success, rating)
        except NeedError as exc:
            return fail(exc)
        return {"ok": True}

    @app.post("/needs/{need_id}/cancel")
    def cancel(need_id: str):
        try:
            service.cancel(need_id)
        except NeedError as exc:
            return fail(exc)
        return {"ok": True}

    @app.post("/agents/register")
    async def register(request: Request):
        """에이전트가 직접 등록할 수도 있다 (agent card 형식, 기존 브로커와 같음)."""
        _, data = await json_body(request)
        url = data.get("url")
        if not isinstance(url, str):
            raise HTTPException(400, '{"url": "<에이전트 base URL>"}')
        try:
            card = fetcher.fetch(url)
        except DiscoveryError as exc:
            raise HTTPException(422, str(exc))
        ids = []
        for s in card["services"]:
            ids.append(store.upsert_resource({
                "key": f"a2a:{s['endpoint']}", "source": "registered", "kind": "a2a", "url": s["endpoint"],
                "name": f"{card['name']}/{s['name']}", "description": s["description"], "category": s["category"],
                "networks": [f"eip155:{net.chain_id}"], "price_usdc": s["price"], "pay_to": card["pay_to"],
                "method": "POST", "details": {"agent_card": url.rstrip("/") + "/.well-known/agent.json"},
            }))
        return {"registered": len(ids), "resource_ids": ids}

    def require_admin(authorization: str | None):
        expected = f"Bearer {config.admin_token}" if config.admin_token else None
        if expected is None or authorization is None or not hmac.compare_digest(authorization, expected):
            raise HTTPException(401, "ADMIN_TOKEN 필요")

    @app.get("/admin/report")
    def report(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return service.report()

    @app.post("/admin/crawl")
    def crawl_now(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return crawler.crawl_all()

    @app.post("/admin/rescan")
    def rescan_now(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return service.rescan()

    return app


def main() -> None:
    import os

    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = GatewayConfig.from_env()
    if not config.network.is_testnet:
        log.warning("메인넷(%s)에서 실제 USDC 수수료를 받습니다.", config.network.name)
    uvicorn.run(
        create_app(config), host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8200")),
        proxy_headers=True, forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
    )


if __name__ == "__main__":
    main()
