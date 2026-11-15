"""Collector agent runtime: background crawler and health loops.

- Crawl loop: Upon completing a full crawl pass, rests for min_gap (default 60s) before starting the next pass.
  Request rates are throttled per page interval to prevent traffic spikes as catalog size grows.
  Only changed records are updated; unchanged records are not re-written to the database.
- Health check loop: Regularly validates eligible agent endpoints according to scheduling policy.
  Prunes historical check records older than 7 days daily.
- Capability investigation loop: Queries tool definitions and authentication metadata.
  A2A agents are probed for agent card, auth, endpoints, safe trial invocation, and evaluation daily.
- AI agent discovery loop: Scans ERC-8004 on-chain registries and queries known host /.well-known/agent-card.json endpoints.
- RAG index loop: Incrementally updates vector index for catalog changes and backfills listings.
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
PRUNE_SECONDS = 3600   # hourly, in time slices (store.prune_health); was daily in one DELETE until 11-15


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
        self.health_lanes = max(1, health_lanes)  # Number of concurrent health check lanes to isolate slow hosts
        self.stop_event = threading.Event()
        self.paused = threading.Event()  # Administrator pause: halts loops between batches while preserving progress
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
        """Pause execution briefly if paused flag is set, returning True to restart loop."""
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
        """Process outbox updates and incrementally index existing catalog listings for RAG."""
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
            except Exception as exc:
                self.rag_status = {**self.rag_status, 'state': 'error', 'last_finished_at': time.time(),
                                   'reason': 'index_step_error'}
                log.warning("rag index loop transient error: %s", exc)
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
            # Resume next round; wait longer on failure to reduce registry burden
            self.stop_event.wait(self.min_gap * (5 if failed else 1))

    _inactive_policy_last = 0.0

    def _inactive_policy_due(self, now: float | None = None) -> bool:
        """At most once a minute, never in the measurement minutes (:55-:10) or 03:50-05:10 local."""
        now = time.time() if now is None else now
        local = time.localtime(now)
        hm = local.tm_hour * 100 + local.tm_min
        if local.tm_min >= 55 or local.tm_min < 10 or 350 <= hm <= 510 or now - self._inactive_policy_last < 60:
            return False
        self._inactive_policy_last = now
        return True

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
                try:  # Servers requiring authentication: static origin evaluation without network dispatch
                    stats["checked"] += self.capabilities.evaluate_static_due()
                except Exception:
                    log.exception("static evaluation error")
            if self.store is not None:
                try:  # Paid x402 API quality evaluation (unassessed or older than 24h)
                    stats["checked"] += self.store.evaluate_x402_batch(limit=1000)
                except Exception:
                    log.exception("x402 evaluation error")
                try:  # Apply quality policy to existing evaluations without network calls
                    stats["checked"] += self.store.quality_policy_batch(limit=500)
                except Exception:
                    log.exception("quality policy batch error")
                if self._inactive_policy_due():
                    try:  # PM 11-14: inactive x402 grade A -> policy cap B, a small batch a minute outside measurement times
                        stats["checked"] += self.store.quality_policy_inactive_x402_batch(limit=50)
                    except Exception:
                        log.exception("inactive x402 quality policy error")
            if not stats["checked"]:
                self.stop_event.wait(300)  # Sleep 5 minutes if no items are due
            elif stats.get("local_network_problem"):
                self.stop_event.wait(120)

    def erc8004_scan_round(self) -> dict:
        """Scan new registrations per chain sequentially, reusing remaining budget for updates."""
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
        """Resolve registration files in parallel by host and discover known well-known agent cards."""
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
            self.stop_event.wait(5 if busy else 120)  # Check every 2 minutes once caught up

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
        if lanes >= 3:
            # 3 or more lanes: dedicated threads for A2A, MCP, and x402
            loops.append(("collector-health-a2a", lambda: self._health_loop(kinds="a2a", prune=False, scavenge=False)))
            loops.append(("collector-health-mcp", lambda: self._health_loop(kinds="mcp", prune=False, scavenge=False)))
            loops.append(("collector-health-x402", lambda: self._health_loop(kinds="x402", prune=True, scavenge=True)))
            # Extra lanes beyond 3 are assigned to high-volume x402 workers
            for i in range(4, lanes + 1):
                loops.append((f"collector-health-x402-{i - 2}", lambda: self._health_loop(kinds="x402", prune=False, scavenge=False)))
        elif lanes == 2:
            # 2 lanes: [A2A, MCP] combined lane and dedicated [x402] lane
            loops.append(("collector-health-a2a-mcp", lambda: self._health_loop(kinds=("a2a", "mcp"), prune=False, scavenge=False)))
            loops.append(("collector-health-x402", lambda: self._health_loop(kinds="x402", prune=True, scavenge=True)))
        else:
            # 1 lane: sequential round-robin across all kinds
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
                    # Configure batch sizes per kind (A2A and MCP are small-batch, x402 is high-volume)
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

                if prune and (time.time() - last_prune > PRUNE_SECONDS):
                    removed = self.store.prune_health(time.time() - HISTORY_DAYS * 86400)
                    log.info("pruned %d old health checks", removed)
                    last_prune = time.time()

                # Scavenger: lightweight re-checking and revival detection for retired agents failing 7+ days
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
                self.stop_event.wait(self.idle_wait)  # Sleep if no agents are due for check
            elif any_outage:
                self.stop_event.wait(60)  # Local network issue: wait briefly and retry with fresh connection


def chains_from(value: str | None) -> dict:
    """Parse comma-separated chains string. Empty string disables ERC-8004 collection."""
    if value is None:
        return dict(DEFAULT_CHAINS)
    return {c.strip(): DEFAULT_CHAINS[c.strip()] for c in value.split(",") if c.strip() in DEFAULT_CHAINS}


def build_agent_sources(store: Store, allow_private: bool, workers: int, max_age: float, trials: bool,
                        trial_max_age: float, chains: str | None = None, discovery: bool = True):
    """Construct A2A prober and discovery sources (ERC-8004, well-known)."""
    prober = AgentProber(store, allow_private=allow_private, max_age=max_age, workers=workers, trials=trials,
                         trial_max_age=trial_max_age)
    if not discovery:
        return prober, None, None
    picked = chains_from(chains)
    erc = Erc8004Crawler(store, chains=picked, allow_private=allow_private) if picked else None
    return prober, erc, WellKnownDiscoverer(store, allow_private=allow_private)
