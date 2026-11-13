"""Per-host pacing: spacing, a rolling window, and rest after 429.

A request that cannot be sent inside the caller's time budget is refused
locally (``SourceBusy``) instead of queueing; the caller may then answer from
cache. After HTTP 429 the host rests for Retry-After (30 s to 1 h, 5 min when the
header is missing); after 503 it rests 60 s. No request is retried here.
"""
from __future__ import annotations

import re
import threading
import time
from contextlib import contextmanager


class SourceBusy(RuntimeError):
    """The source is resting or its request allowance is used up."""


class HostLimiter:
    def __init__(self, spacing: float, count: int | None = None, window: float | None = None,
                 clock=time.monotonic, sleep=time.sleep):
        self.spacing, self.count, self.window = spacing, count, window
        self.clock, self.sleep = clock, sleep
        self.lock = threading.Lock()
        self.next_at = 0.0
        self.rest_until = 0.0
        self.sent: list[float] = []

    @contextmanager
    def slot(self, remaining: float):
        """Hold the host for one request; ``remaining`` is the caller's budget in seconds."""
        if not self.lock.acquire(timeout=max(0.0, min(remaining, 4.0))):
            raise SourceBusy("Source is busy.")
        try:
            now = self.clock()
            if now < self.rest_until:
                raise SourceBusy("Source asked us to slow down; resting.")
            if self.window:
                self.sent = [t for t in self.sent if now - t < self.window]
                if len(self.sent) >= (self.count or 1):
                    raise SourceBusy("Source request allowance is used up for now.")
            delay = max(0.0, self.next_at - now)
            if delay + 0.2 >= remaining:
                raise SourceBusy("Source spacing does not fit the time budget.")
            if delay:
                self.sleep(delay)
            start = self.clock()
            self.next_at = start + self.spacing
            if self.window:
                self.sent.append(start)
            yield
        finally:
            self.lock.release()

    def observed(self, status: int, headers) -> None:
        """Record the response; call while still inside ``slot``."""
        now = self.clock()
        retry = (headers.get("retry-after") or "").strip() if headers is not None else ""
        if status == 429:
            wait = float(retry) if re.fullmatch(r"[0-9]{1,6}", retry) else 300.0
            self.rest_until = max(self.rest_until, now + min(3600.0, max(30.0, wait)))
        elif status == 503:
            self.rest_until = max(self.rest_until, now + 60.0)
        if headers is not None and headers.get("x-ratelimit-remaining") == "0":
            reset = headers.get("x-ratelimit-reset") or ""
            if re.fullmatch(r"[0-9]{9,11}", reset):
                self.rest_until = max(self.rest_until, now + min(3600.0, max(1.0, int(reset) - time.time())))

    def resting(self) -> float:
        return max(0.0, self.rest_until - self.clock())


def limiters(clock=time.monotonic, sleep=time.sleep) -> dict[str, HostLimiter]:
    return {
        # NVD: 5 requests per rolling 30 s without a key; NIST suggests about 6 s between requests.
        "services.nvd.nist.gov": HostLimiter(6.5, 5, 30.0, clock, sleep),
        "nvd.nist.gov": HostLimiter(6.5, None, None, clock, sleep),
        "cveawg.mitre.org": HostLimiter(1.0, 60, 60.0, clock, sleep),
        "www.cisa.gov": HostLimiter(60.0, None, None, clock, sleep),
        "api.first.org": HostLimiter(0.5, 60, 60.0, clock, sleep),
        "api.github.com": HostLimiter(1.0, 50, 3600.0, clock, sleep),
        "registry.npmjs.org": HostLimiter(0.2, 300, 60.0, clock, sleep),
        "pypi.org": HostLimiter(0.2, 300, 60.0, clock, sleep),
        "api.deps.dev": HostLimiter(0.2, 300, 60.0, clock, sleep),
        "api.gleif.org": HostLimiter(1.0, 50, 60.0, clock, sleep),      # GLEIF: 60 per minute
        "www.sec.gov": HostLimiter(0.2, 300, 60.0, clock, sleep),       # SEC: at most 10 per second
        "data.sec.gov": HostLimiter(0.2, 300, 60.0, clock, sleep),
        "en.wikipedia.org": HostLimiter(0.2, 300, 60.0, clock, sleep),
        "export.arxiv.org": HostLimiter(3.0, None, None, clock, sleep),  # arXiv: one request every 3 s
        "api.worldbank.org": HostLimiter(0.2, 300, 60.0, clock, sleep),
        "api.met.no": HostLimiter(0.2, 300, 60.0, clock, sleep),  # MET Norway: under 20 per second in total
        "api.scorecard.dev": HostLimiter(0.2, 300, 60.0, clock, sleep),
    }
