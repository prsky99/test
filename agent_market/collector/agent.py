"""수집 에이전트 본체: 두 개의 백그라운드 루프.

- 수집 루프: 한 바퀴 수집이 끝나면 min_gap(기본 60초) 쉬고 바로 다음 바퀴를 시작한다 (연속 수집).
  요청 속도는 페이지 간격으로 고정돼 있어 에이전트가 늘어도 순간 부하는 늘지 않는다.
  MCP는 바뀐 것만, x402는 전체를 훑고, 바뀌지 않은 항목은 DB에 다시 쓰지 않는다 (crawler.Crawler 참고).
- 헬스체크 루프: 점검 시각이 된 에이전트를 계속 점검 (기본 매시간, 소개 중인 에이전트는 15분, down은 점점 드물게)
  하루에 한 번 7일이 지난 점검 기록을 정리한다.
"""

import logging
import threading
import time

from ..gateway.crawler import Crawler
from ..gateway.store import Store
from .health import HealthChecker

log = logging.getLogger("agent_market.collector")

HISTORY_DAYS = 7


class CollectorAgent:
    def __init__(self, store: Store, crawler: Crawler, checker: HealthChecker,
                 min_gap: float = 60, idle_wait: float = 15, batch: int = 500):
        self.store, self.crawler, self.checker = store, crawler, checker
        self.min_gap = min_gap
        self.idle_wait = idle_wait
        self.batch = batch
        self.stop_event = threading.Event()
        self.crawler.should_stop = self.stop_event.is_set  # 종료 요청 시 페이지 사이에서 멈춤 (진행 위치는 저장됨)
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        for name, target in (("collector-crawl", self._crawl_loop), ("collector-health", self._health_loop)):
            t = threading.Thread(target=target, name=name, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self.stop_event.set()

    def _crawl_loop(self) -> None:
        while not self.stop_event.is_set():
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

    def _health_loop(self) -> None:
        last_prune = 0.0
        while not self.stop_event.is_set():
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
