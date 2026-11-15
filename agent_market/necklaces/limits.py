"""Limits for public necklace runs (PM R21, 11-15).

Before this, one person running a necklace 60 times a minute sent 60 calls a minute to every pearl's provider. The
public run entry (service.run_for_surface) now applies, in this order and before any member is called:

1. RunLimiter: runs per client address, per necklace and in total per minute; over a limit the run is refused
   ("rate_limited") and nothing is sent
2. ResultCache: the same necklace version and the same input within CACHE_SECONDS gets the earlier answer again,
   marked cached, without calling anyone
3. DomainCap (inside the caller): calls per provider domain per minute and per day; over a cap that member is skipped
   with error "provider_cap" and the runner moves to the next member of the chain. AgentValCon's own fallbacks run
   on our host and are not counted

Counts live in this process (each frontend worker keeps its own); the limits are set per worker accordingly.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import deque

PER_CLIENT_PER_MINUTE = 6
PER_NECKLACE_PER_MINUTE = 30
TOTAL_PER_MINUTE = 60
DOMAIN_PER_MINUTE = 10
DOMAIN_PER_DAY = 300
CACHE_SECONDS = 600
CACHE_ENTRIES = 256


class Refused(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code
        self.error_code = code


class _Window:
    """Sliding window of event times."""

    def __init__(self):
        self.times: deque = deque()

    def count(self, now: float, span: float) -> int:
        while self.times and self.times[0] <= now - span:
            self.times.popleft()
        return len(self.times)


class RunLimiter:
    def __init__(self, clock=time.monotonic, per_client=PER_CLIENT_PER_MINUTE, per_necklace=PER_NECKLACE_PER_MINUTE,
                 total=TOTAL_PER_MINUTE):
        self.clock, self.limits = clock, {"client": per_client, "necklace": per_necklace, "total": total}
        self.windows: dict[tuple, _Window] = {}
        self.lock = threading.Lock()

    def admit(self, slug: str, client: str | None):
        """Count one run or raise Refused('rate_limited'); a run without a known client counts as one client."""
        now = self.clock()
        keys = [("client", client or "unknown"), ("necklace", slug), ("total", "")]
        with self.lock:
            windows = [self.windows.setdefault(k, _Window()) for k in keys]
            if any(w.count(now, 60) >= self.limits[k[0]] for k, w in zip(keys, windows)):
                raise Refused("rate_limited")
            for w in windows:
                w.times.append(now)
            if len(self.windows) > 10_000:          # forget idle clients
                for key in [k for k, w in self.windows.items() if not w.count(now, 60)]:
                    del self.windows[key]


class ResultCache:
    def __init__(self, clock=time.monotonic, seconds=CACHE_SECONDS, entries=CACHE_ENTRIES):
        self.clock, self.seconds, self.entries = clock, seconds, entries
        self.items: dict[str, tuple[float, dict]] = {}
        self.lock = threading.Lock()

    @staticmethod
    def key(slug: str, version, digest: str, values: dict) -> str:
        text = json.dumps([slug, version, digest, values], sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(text.encode()).hexdigest()

    def get(self, key: str) -> dict | None:
        with self.lock:
            found = self.items.get(key)
            if found and self.clock() - found[0] < self.seconds:
                return found[1]
            self.items.pop(key, None)
            return None

    def put(self, key: str, result: dict):
        """Only completed runs are kept: a failure is retried, never served again."""
        if not result.get("ok"):
            return
        with self.lock:
            self.items[key] = (self.clock(), result)
            if len(self.items) > self.entries:
                for old in sorted(self.items, key=lambda k: self.items[k][0])[:len(self.items) - self.entries]:
                    del self.items[old]


class DomainCap:
    def __init__(self, clock=time.time, per_minute=DOMAIN_PER_MINUTE, per_day=DOMAIN_PER_DAY):
        self.clock, self.per_minute, self.per_day = clock, per_minute, per_day
        self.minute: dict[str, _Window] = {}
        self.day: dict[str, tuple[str, int]] = {}
        self.lock = threading.Lock()

    def take(self, domain: str) -> bool:
        now = self.clock()
        today = time.strftime("%Y%m%d", time.localtime(now))
        with self.lock:
            window = self.minute.setdefault(domain, _Window())
            day, used = self.day.get(domain, (today, 0))
            used = used if day == today else 0
            if window.count(now, 60) >= self.per_minute or used >= self.per_day:
                return False
            window.times.append(now)
            self.day[domain] = (today, used + 1)
            return True

    def wrap(self, caller):
        """A caller that skips a member whose provider domain is over its cap (the runner tries the next one)."""
        def call(member, args, timeout_s):
            domain = member.get("registrable_domain")
            if member.get("kind") == "external" and domain and not self.take(domain):
                raise Refused("provider_cap")
            return caller(member, args, timeout_s)
        return call


LIMITER = RunLimiter()
CACHE = ResultCache()
DOMAINS = DomainCap()


def reset():
    """Forget every count and cached answer (tests and a deliberate operator reset)."""
    with LIMITER.lock:
        LIMITER.windows.clear()
    with CACHE.lock:
        CACHE.items.clear()
    with DOMAINS.lock:
        DOMAINS.minute.clear()
        DOMAINS.day.clear()
