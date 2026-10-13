"""수집 에이전트 본체: 두 개의 백그라운드 루프.

- 수집 루프: crawl_interval(기본 1시간)마다 x402 Bazaar·MCP Registry 전체를 다시 수집
  (새 에이전트 추가, 정보 갱신, 목록에서 사라진 에이전트 비활성화)
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
                 crawl_interval: float = 3600, idle_wait: float = 15, batch: int = 500):
        self.store, self.crawler, self.checker = store, crawler, checker
        self.crawl_interval = crawl_interval
        self.idle_wait = idle_wait
        self.batch = batch
        self.stop_event = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        for name, target in (("collector-crawl", self._crawl_loop), ("collector-health", self._health_loop)):
            t = threading.Thread(target=target, name=name, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self.stop_event.set()

    def crawl_due(self) -> bool:
        last = (self.store.get_meta("last_crawl") or {}).get("at", 0)
        return time.time() - last >= self.crawl_interval

    def _crawl_loop(self) -> None:
        while not self.stop_event.is_set():
            if self.crawl_due():
                log.info("crawl start")
                try:
                    log.info("crawl done: %s", self.crawler.crawl_all())
                except Exception:
                    log.exception("crawl failed")
            self.stop_event.wait(60)

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
