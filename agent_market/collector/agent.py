"""수집 에이전트 본체: 두 개의 백그라운드 루프.

- 수집 루프: 한 바퀴 수집이 끝나면 min_gap(기본 60초) 쉬고 바로 다음 바퀴를 시작한다 (연속 수집).
  요청 속도는 페이지 간격으로 고정돼 있어 에이전트가 늘어도 순간 부하는 늘지 않는다.
  MCP는 바뀐 것만, x402는 전체를 훑고, 바뀌지 않은 항목은 DB에 다시 쓰지 않는다 (crawler.Crawler 참고).
- 헬스체크 루프: 점검 시각이 된 에이전트를 계속 점검 (기본 매시간, 소개 중인 에이전트는 15분, down은 점점 드물게)
  하루에 한 번 7일이 지난 점검 기록을 정리한다.
- 기능 조사 루프: 인증 없이 응답하는 MCP의 도구 목록을 하루 한 번 받아 지원 언어·나라·통화를 기록하고,
  인증이 필요한 MCP는 일주일에 한 번 인증 방법(OAuth 메타데이터·API 키 발급처 등)을 조사한다.
  A2A 에이전트는 하루 한 번 agent card·인증·엔드포인트·안전한 시험 메시지·평가를 한 번에 조사한다 (collector/a2a.py).
- AI 에이전트 수집 루프: ERC-8004 온체인 등록부(체인별 tokenURI 배치 조회 → 등록 파일 → A2A·MCP 엔드포인트)와
  이미 아는 호스트의 /.well-known/agent-card.json 탐색을 쉬지 않고 천천히 돈다 (collector/registries.py).
"""

import logging
import os
import threading
import time

from ..gateway.crawler import Crawler
from ..gateway.store import Store
from .a2a import AgentProber
from .auth_discovery import AuthDiscoverer
from .capabilities import CapabilityProber
from .health import HealthChecker
from .registries import DEFAULT_CHAINS, Erc8004Crawler, WellKnownDiscoverer

log = logging.getLogger("agent_market.collector")

HISTORY_DAYS = 7
# 11-10 사용자 결정: x402는 결제 실행 시험이 가능해질 때(AD Coin 보유 10만 코인 이상, 보유량의 1/1000만 사용)까지
# 새로 수집·점검·평가하지 않는다. 연결 확인만으로는 정확한 시험이 안 되기 때문이다. 다시 켤 때: COLLECT_X402=1.
COLLECT_X402 = os.environ.get("COLLECT_X402", "0") == "1"
COLLECT_KINDS = ("a2a", "mcp", "x402") if COLLECT_X402 else ("a2a", "mcp")


class CollectorAgent:
    def __init__(self, store: Store, crawler: Crawler, checker: HealthChecker,
                 min_gap: float = 60, idle_wait: float = 15, batch: int = 500, capabilities: CapabilityProber | None = None,
                 auth: AuthDiscoverer | None = None, agents: AgentProber | None = None,
                 erc8004: Erc8004Crawler | None = None, wellknown: WellKnownDiscoverer | None = None, health_lanes: int = 3,
                 rag_pipeline=None):
        self.store, self.crawler, self.checker = store, crawler, checker
        self.capabilities = capabilities
        self.auth = auth
        self.agents = agents
        self.erc8004 = erc8004
        self.wellknown = wellknown
        self.rag_pipeline = rag_pipeline
        self.rag_status = {"state": "starting" if rag_pipeline is not None else "unavailable", "last_count": 0}
        self.min_gap = min_gap
        self.idle_wait = idle_wait
        self.batch = batch
        self.health_lanes = max(1, health_lanes)  # 동시에 도는 헬스체크 묶음 수 (느린 호스트 하나가 전체를 붙잡지 않게)
        self.stop_event = threading.Event()
        self.paused = threading.Event()  # 관리 화면에서 일시정지: 모든 루프가 쉬고, 수집은 페이지 사이에서 멈춤 (진행 위치 저장)
        self.crawler.should_stop = lambda: self.stop_event.is_set() or self.paused.is_set()
        self._threads: list[threading.Thread] = []
        self.started_at: float | None = None

    def pause(self) -> None:
        self.paused.set()
        log.info("collector paused")

    def resume(self) -> None:
        self.paused.clear()
        log.info("collector resumed")

    def _idle_if_paused(self) -> bool:
        """일시정지 중이면 잠깐 기다리고 True (루프는 다시 처음으로)."""
        if self.paused.is_set():
            self.stop_event.wait(2)
            return True
        return False

    def thread_status(self) -> list[dict]:
        return [{"name": t.name, "alive": t.is_alive()} for t in self._threads]

    def start(self) -> None:
        if any(thread.is_alive() for thread in self._threads):
            return
        self.stop_event.clear()
        self._threads.clear()
        for prober in (self.capabilities, self.agents):
            if prober is not None:
                try:
                    prober.requeue_outdated_evaluations()
                except Exception:
                    log.exception("evaluation requeue failed")
        self.started_at = time.time()
        loops = [("collector-crawl", self._crawl_loop)]
        loops.extend(self._build_health_loops())
        if self.capabilities is not None or self.auth is not None or self.agents is not None:
            loops.append(("collector-capabilities", self._capability_loop))
        if self.erc8004 is not None:
            loops.append(("collector-erc8004-scan", self._erc8004_scan_loop))
        if self.erc8004 is not None or self.wellknown is not None:
            loops.append(("collector-agent-resolve", self._agent_resolve_loop))
        if self.rag_pipeline is not None:
            loops.append(("collector-rag-index", self._rag_index_loop))
        for name, target in loops:
            t = threading.Thread(target=target, name=name, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self, timeout: float = 30) -> bool:
        """Stop admission and wait before the owner detaches persistent storage."""
        if type(timeout) not in (int, float) or not 0 <= timeout <= 300:
            raise ValueError('invalid_collector_shutdown_timeout')
        self.stop_event.set()
        deadline = time.monotonic() + timeout
        current = threading.current_thread()
        for thread in self._threads:
            if thread is not current:
                thread.join(max(0, deadline - time.monotonic()))
        return not any(thread.is_alive() for thread in self._threads)

    def _rag_index_loop(self) -> None:
        """에이전트 정보 갱신(outbox) 실시간 반영 및 기존 데이터(backfill)를 점진적으로 색인하는 루프."""
        while not self.stop_event.is_set():
            if self._idle_if_paused():
                continue
            try:
                started = time.time()
                previous = self.rag_status
                self.rag_status = {**previous, 'state': 'running', 'last_started_at': started,
                                   'enabled': bool(self.rag_pipeline.engine.embeddings_enabled)}
                res = self.rag_pipeline.step(self.store)
                finished = time.time()
                self.rag_status = {'state': res.get('type', 'idle'), 'enabled': bool(self.rag_pipeline.engine.embeddings_enabled),
                                   'last_started_at': started, 'last_finished_at': finished,
                                   'last_count': res.get('count', 0), 'last_failed': res.get('failed', 0),
                                   'reason': res.get('reason'),
                                   'last_success_at': finished if res.get('count', 0) > 0 else previous.get('last_success_at')}

                res_type = res.get("type", "idle")
                count = res.get("count", 0)
                if res_type in ("outbox", "backfill") and count > 0:
                    self.stop_event.wait(0.05)
                elif res_type == "error":
                    self.stop_event.wait(5.0)
                else:
                    self.stop_event.wait(5.0)
            except Exception:
                self.rag_status = {**self.rag_status, 'state': 'error', 'last_finished_at': time.time(),
                                   'reason': 'index_step_error'}
                log.exception("rag index loop error")
                self.stop_event.wait(5.0)

    def _crawl_loop(self) -> None:
        while not self.stop_event.is_set():
            if self._idle_if_paused():
                continue
            log.info("crawl pass start")
            try:
                report = self.crawler.crawl_all()
                log.info("crawl pass done: %s", report)
                failed = any(isinstance(v, dict) and not v.get("ok", True) for v in report.values())
            except Exception:
                log.exception("crawl failed")
                failed = True
            # 다음 바퀴 바로 시작. 실패했으면 레지스트리 부담을 줄이려고 더 오래 쉼
            self.stop_event.wait(self.min_gap * (5 if failed else 1))

    def _capability_loop(self) -> None:
        while not self.stop_event.is_set():
            if self._idle_if_paused():
                continue
            stats = {"checked": 0}
            for name, prober in (("capabilities", self.capabilities), ("auth", self.auth), ("agents", self.agents)):
                if prober is None:
                    continue
                try:
                    s = prober.run_due()
                except Exception:
                    log.exception("%s loop error", name)
                    continue
                if s["checked"]:
                    log.info("%s: %s", name, s)
                    self.store.set_meta(f"last_{name}_batch", {"at": time.time(), **s})
                    stats["checked"] += s["checked"]
                    stats["local_network_problem"] = stats.get("local_network_problem") or s.get("local_network_problem")
            if self.capabilities is not None:
                try:  # 인증이 필요한 서버: 네트워크 요청 없이 출처 정적 평가
                    stats["checked"] += self.capabilities.evaluate_static_due()
                except Exception:
                    log.exception("static evaluation error")
            if self.store is not None:
                if COLLECT_X402:
                    try:  # x402 유료 API 품질 평가 (미평가 또는 24시간 경과분)
                        stats["checked"] += self.store.evaluate_x402_batch(limit=1000)
                    except Exception:
                        log.exception("x402 evaluation error")
                try:  # 기존 평가에 품질 정책 입히기 (정책 버전마다 한 바퀴, 네트워크 요청 없음)
                    stats["checked"] += self.store.quality_policy_batch(limit=500)
                except Exception:
                    log.exception("quality policy batch error")
            if not stats["checked"]:
                self.stop_event.wait(300)  # 조사할 게 없으면 5분 쉼
            elif stats.get("local_network_problem"):
                self.stop_event.wait(120)

    def erc8004_scan_round(self) -> dict:
        """체인마다 새 등록을 이어서 읽고, 남는 배치로 기존 등록을 다시 읽는다 (agentURI 변경 반영)."""
        report = {}
        for chain in self.erc8004.chains:
            if self.stop_event.is_set():
                break
            try:
                report[chain] = self.erc8004.scan(chain)
            except Exception as exc:
                log.warning("erc8004 scan %s failed: %r", chain, exc)
                report[chain] = {"error": str(exc)[:200]}
        return report

    def agent_resolve_round(self) -> dict:
        """등록 파일 받기(호스트별로 나눠 병렬) + 아는 호스트의 well-known agent card 탐색."""
        report = {}
        if self.erc8004 is not None:
            try:
                report["erc8004_resolve"] = self.erc8004.resolve_pending()
            except Exception:
                log.exception("erc8004 resolve failed")
        if self.wellknown is not None:
            try:
                report["well_known"] = self.wellknown.run_due()
            except Exception:
                log.exception("well-known discovery failed")
        return report

    def _erc8004_scan_loop(self) -> None:
        while not self.stop_event.is_set():
            if self._idle_if_paused():
                continue
            report = self.erc8004_scan_round()
            busy = any(v.get("batches", 0) > 2 or v.get("rescan_batches") for v in report.values())
            if any(v.get("new") or v.get("changed") or v.get("error") for v in report.values()):
                log.info("erc8004 scan: %s", report)
            self.store.set_meta("last_erc8004_scan", {"at": time.time(), **report})
            self.stop_event.wait(5 if busy else 120)  # 따라잡은 뒤에는 2분마다 새 등록 확인

    def _agent_resolve_loop(self) -> None:
        while not self.stop_event.is_set():
            if self._idle_if_paused():
                continue
            report = self.agent_resolve_round()
            busy = any(v.get("resolved") or v.get("checked") for v in report.values() if isinstance(v, dict))
            if busy:
                log.info("agent discovery: %s", report)
                self.store.set_meta("last_agent_discovery", {"at": time.time(), **report})
            self.stop_event.wait(2 if busy else 120)

    def _build_health_loops(self) -> list[tuple[str, any]]:
        lanes = self.health_lanes
        loops = []
        if not COLLECT_X402:
            # x402 paused: A2A and MCP only; pruning and retired-agent scavenging move to the A2A lane.
            if lanes >= 2:
                loops.append(("collector-health-a2a", lambda: self._health_loop(kinds="a2a", prune=True, scavenge=True)))
                loops.append(("collector-health-mcp", lambda: self._health_loop(kinds="mcp", prune=False, scavenge=False)))
            else:
                loops.append(("collector-health", lambda: self._health_loop(kinds=("a2a", "mcp"), prune=True, scavenge=True)))
            return loops
        if lanes >= 3:
            # 3개 이상의 레인이면 A2A, MCP, x402 각각 전용 스레드로 완전 분리
            loops.append(("collector-health-a2a", lambda: self._health_loop(kinds="a2a", prune=False, scavenge=False)))
            loops.append(("collector-health-mcp", lambda: self._health_loop(kinds="mcp", prune=False, scavenge=False)))
            loops.append(("collector-health-x402", lambda: self._health_loop(kinds="x402", prune=True, scavenge=True)))
            # 3개를 초과하는 추가 레인은 데이터 양이 압도적인 x402(11,000+개)에 추가 분산 워커로 배정
            for i in range(4, lanes + 1):
                loops.append((f"collector-health-x402-{i - 2}", lambda: self._health_loop(kinds="x402", prune=False, scavenge=False)))
        elif lanes == 2:
            # 2개 레인이면 [A2A, MCP] 묶음 1개, [x402] 전용 1개
            loops.append(("collector-health-a2a-mcp", lambda: self._health_loop(kinds=("a2a", "mcp"), prune=False, scavenge=False)))
            loops.append(("collector-health-x402", lambda: self._health_loop(kinds="x402", prune=True, scavenge=True)))
        else:
            # 1개 레인이면 모든 종류를 순차 라운드로빈으로 점검
            loops.append(("collector-health", lambda: self._health_loop(kinds=("a2a", "mcp", "x402"), prune=True, scavenge=True)))
        return loops

    def _health_loop(self, kinds: str | list[str] | tuple[str, ...] | None = None,
                     prune: bool = True, scavenge: bool = True) -> None:
        last_prune = 0.0 if prune else float("inf")
        last_scavenge = 0.0 if scavenge else float("inf")
        targets = [kinds] if isinstance(kinds, str) or kinds is None else list(kinds)

        while not self.stop_event.is_set():
            if self._idle_if_paused():
                continue
            total_checked = 0
            any_outage = False
            try:
                for k in targets:
                    if self.stop_event.is_set():
                        break
                    # kind별 적절한 배치 크기 설정 (A2A, MCP는 소량 분산, x402는 대량)
                    batch_size = min(self.batch, 100) if k in ("a2a", "mcp") else self.batch
                    stats = self.checker.run_due(batch_size, kind=k)
                    if stats.get("checked"):
                        total_checked += stats["checked"]
                        k_name = k or "all"
                        log.info("health [%s]: %s", k_name, stats)
                        self.store.set_meta(f"last_health_batch_{k_name}", {"at": time.time(), "kind": k_name, **stats})
                        self.store.set_meta("last_health_batch", {"at": time.time(), "kind": k_name, **stats})
                    if stats.get("local_network_problem"):
                        any_outage = True

                if prune and (time.time() - last_prune > 86400):
                    removed = self.store.prune_health(time.time() - HISTORY_DAYS * 86400)
                    log.info("pruned %d old health checks", removed)
                    last_prune = time.time()

                # 스캐빈저 (7일 이상 실패한 retired 에이전트 초경량 재점검 및 부활 탐지)
                if scavenge and (time.time() - last_scavenge > 600 or total_checked == 0):
                    scav_stats = self.checker.scavenge_retired(limit=25)
                    if scav_stats.get("scavenged"):
                        log.info("scavenger revival check: %s", scav_stats)
                        self.store.set_meta("last_scavenge_batch", {"at": time.time(), **scav_stats})
                    last_scavenge = time.time()
            except Exception:
                log.exception("health loop error for kinds=%s", kinds)
                total_checked = 0

            if not total_checked:
                self.stop_event.wait(self.idle_wait)  # 점검할 대상이 없으면 잠시 쉼
            elif any_outage:
                self.stop_event.wait(60)  # 우리 쪽 네트워크 문제: 잠시 쉬었다가 새 연결로 재시도


def chains_from(value: str | None) -> dict:
    """'base,ethereum,bsc' → 체인 설정. 빈 문자열이면 ERC-8004 수집을 끈다."""
    if value is None:
        return dict(DEFAULT_CHAINS)
    return {c.strip(): DEFAULT_CHAINS[c.strip()] for c in value.split(",") if c.strip() in DEFAULT_CHAINS}


def build_agent_sources(store: Store, allow_private: bool, workers: int, max_age: float, trials: bool,
                        trial_max_age: float, chains: str | None = None, discovery: bool = True):
    """A2A 조사기와 수집 출처 (ERC-8004, well-known)."""
    prober = AgentProber(store, allow_private=allow_private, max_age=max_age, workers=workers, trials=trials,
                         trial_max_age=trial_max_age)
    if not discovery:
        return prober, None, None
    picked = chains_from(chains)
    erc = Erc8004Crawler(store, chains=picked, allow_private=allow_private) if picked else None
    return prober, erc, WellKnownDiscoverer(store, allow_private=allow_private)
