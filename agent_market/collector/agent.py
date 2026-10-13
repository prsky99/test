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


class CollectorAgent:
    def __init__(self, store: Store, crawler: Crawler, checker: HealthChecker,
                 min_gap: float = 60, idle_wait: float = 15, batch: int = 500, capabilities: CapabilityProber | None = None,
                 auth: AuthDiscoverer | None = None, agents: AgentProber | None = None,
                 erc8004: Erc8004Crawler | None = None, wellknown: WellKnownDiscoverer | None = None):
        self.store, self.crawler, self.checker = store, crawler, checker
        self.capabilities = capabilities
        self.auth = auth
        self.agents = agents
        self.erc8004 = erc8004
        self.wellknown = wellknown
        self.min_gap = min_gap
        self.idle_wait = idle_wait
        self.batch = batch
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
        for prober in (self.capabilities, self.agents):
            if prober is not None:
                try:
                    prober.requeue_outdated_evaluations()
                except Exception:
                    log.exception("evaluation requeue failed")
        self.started_at = time.time()
        loops = [("collector-crawl", self._crawl_loop), ("collector-health", self._health_loop)]
        if self.capabilities is not None or self.auth is not None or self.agents is not None:
            loops.append(("collector-capabilities", self._capability_loop))
        if self.erc8004 is not None:
            loops.append(("collector-erc8004-scan", self._erc8004_scan_loop))
        if self.erc8004 is not None or self.wellknown is not None:
            loops.append(("collector-agent-resolve", self._agent_resolve_loop))
        for name, target in loops:
            t = threading.Thread(target=target, name=name, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self.stop_event.set()

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

    def _health_loop(self) -> None:
        last_prune = 0.0
        while not self.stop_event.is_set():
            if self._idle_if_paused():
                continue
            try:
                stats = self.checker.run_due(self.batch)
                if stats["checked"]:
                    log.info("health: %s", stats)
                    self.store.set_meta("last_health_batch", {"at": time.time(), **stats})
                if time.time() - last_prune > 86400:
                    removed = self.store.prune_health(time.time() - HISTORY_DAYS * 86400)
                    log.info("pruned %d old health checks", removed)
                    last_prune = time.time()
            except Exception:
                log.exception("health loop error")
                stats = {"checked": 0}
            if not stats["checked"]:
                self.stop_event.wait(self.idle_wait)  # 할 일이 없으면 잠시 쉼
            elif stats.get("local_network_problem"):
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
