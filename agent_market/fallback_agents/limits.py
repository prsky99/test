"""Per-host pacing: spacing, a rolling window, and rest after 429.

A request that cannot be sent inside the caller's time budget is refused
locally (``SourceBusy``) instead of queueing; the caller may then answer from
cache. After HTTP 429 the host rests for Retry-After (30 s to 1 h, 5 min when the
header is missing); after 503 it rests 60 s. No request is retried here.

With ``shared`` (a file per host, R30 PM 11-15) the spacing, the window and the rest are kept across processes:
the frontend, jobs and execution processes each used to pace a host on their own, so together they could call it
three times as often. The file holds wall-clock times under an exclusive ``flock``; a request reserves its start
time inside the lock and then waits outside it.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path


class SourceBusy(RuntimeError):
    """The source is resting or its request allowance is used up."""


class HostLimiter:
    def __init__(self, spacing: float, count: int | None = None, window: float | None = None,
                 clock=time.monotonic, sleep=time.sleep, shared: Path | str | None = None, wall=time.time):
        self.spacing, self.count, self.window = spacing, count, window
        self.clock, self.sleep, self.wall = clock, sleep, wall
        self.shared = Path(shared) if shared else None
        self.lock = threading.Lock()
        self.next_at = 0.0
        self.rest_until = 0.0
        self.sent: list[float] = []

    @contextmanager
    def _state(self):
        """The shared host state, locked across processes; written back when the block ends."""
        self.shared.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.shared, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            raw = b""
            while chunk := os.read(fd, 65536):
                raw += chunk
            try:
                state = json.loads(raw) if raw else {}
            except ValueError:
                state = {}
            state = {"next_at": float(state.get("next_at") or 0.0), "rest_until": float(state.get("rest_until") or 0.0),
                     "sent": [float(t) for t in state.get("sent") or [] if isinstance(t, (int, float))]}
            yield state
            data = json.dumps(state, separators=(",", ":")).encode()
            os.lseek(fd, 0, os.SEEK_SET)
            os.ftruncate(fd, 0)
            os.write(fd, data)
        finally:
            os.close(fd)   # closing releases the flock

    def _reserve_shared(self, remaining: float) -> float:
        """Reserve this process's next start in the shared file; returns the wait before sending."""
        with self._state() as state:
            now = self.wall()
            if now < state["rest_until"]:
                raise SourceBusy("Source asked us to slow down; resting.")
            if self.window:
                state["sent"] = [t for t in state["sent"] if now - t < self.window]
                if len(state["sent"]) >= (self.count or 1):
                    raise SourceBusy("Source request allowance is used up for now.")
            delay = max(0.0, state["next_at"] - now)
            if delay + 0.2 >= remaining:
                raise SourceBusy("Source spacing does not fit the time budget.")
            start = now + delay
            state["next_at"] = start + self.spacing
            if self.window:
                state["sent"].append(start)
            return delay

    @contextmanager
    def slot(self, remaining: float):
        """Hold the host for one request; ``remaining`` is the caller's budget in seconds."""
        if not self.lock.acquire(timeout=max(0.0, min(remaining, 4.0))):
            raise SourceBusy("Source is busy.")
        try:
            if self.shared is not None:
                delay = self._reserve_shared(remaining)
                if delay:
                    self.sleep(delay)
                yield
                return
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
        if self.shared is not None and self.rest_until > now:   # every process rests, not just this one
            rest_for = self.rest_until - now
            with self._state() as state:
                state["rest_until"] = max(state["rest_until"], self.wall() + rest_for)

    def resting(self) -> float:
        own = max(0.0, self.rest_until - self.clock())
        if self.shared is None or not self.shared.exists():
            return own
        with self._state() as state:
            return max(own, state["rest_until"] - self.wall())


def limiters(clock=time.monotonic, sleep=time.sleep, shared_dir: Path | str | None = None,
             wall=time.time) -> dict[str, HostLimiter]:
    """Per-host limiters; with ``shared_dir`` each host's state is one file there, shared by every process."""
    table = _table(clock, sleep)
    if shared_dir:
        for host, limiter in table.items():
            limiter.shared, limiter.wall = Path(shared_dir) / f"{host}.json", wall
    return table


def _table(clock, sleep) -> dict[str, HostLimiter]:
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
        "www.ecb.europa.eu": HostLimiter(2.0, 60, 3600.0, clock, sleep),
        "earthquake.usgs.gov": HostLimiter(1.0, 60, 3600.0, clock, sleep),
        "davidmegginson.github.io": HostLimiter(60.0, 4, 86400.0, clock, sleep),  # airport CSV: a few a day
        "en.wiktionary.org": HostLimiter(0.2, 300, 60.0, clock, sleep),
        "data.iana.org": HostLimiter(10.0, 24, 86400.0, clock, sleep),
        "api.gdeltproject.org": HostLimiter(5.0, 200, 86400.0, clock, sleep),  # GDELT DOC API: one every 5 s (ours)
        "www.wikidata.org": HostLimiter(0.2, 300, 60.0, clock, sleep),  # sequential requests only
        "query.wikidata.org": HostLimiter(0.5, 60, 60.0, clock, sleep),  # WDQS: few parallel, 60 s of query time a minute
    }
