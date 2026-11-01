"""Serialize and pace Crossref list requests without hidden network retries.

The source remains authoritative. Local pacing reduces bursts in one process;
429 responses across other processes still require alternative routing or failure.
"""
from contextlib import contextmanager
import math
import re
import threading
import time


class SourceBusy(ValueError):
    pass


class SourcePacer:
    def __init__(self,clock=time.monotonic,sleep=time.sleep):
        self.clock,self.sleep=clock,sleep
        self.lock=threading.Lock();self.next_at=0.;self.spacing=1.1

    @contextmanager
    def slot(self,budget):
        if not self.lock.acquire(timeout=min(4.,budget.remaining())):raise SourceBusy('Source concurrency limit reached.')
        try:
            delay=max(0.,self.next_at-self.clock())
            if delay+0.1>=budget.remaining():raise SourceBusy('Source is cooling down.')
            if delay:self.sleep(delay)
            budget.remaining();self.next_at=self.clock()+self.spacing
            yield
        finally:self.lock.release()

    def observed(self,response):
        # Called only while the slot lock is held. Never increase request speed
        # from advertised limits; the public list default is one request/second.
        headers=response.headers
        try:
            count=int(headers.get('x-rate-limit-limit','1'))
            interval=headers.get('x-rate-limit-interval','1s')
            if not re.fullmatch(r'[0-9]{1,4}(?:\.[0-9]{1,3})?s',interval):raise ValueError()
            seconds=float(interval[:-1])
            if 1<=count<=10000 and math.isfinite(seconds) and seconds>0:
                self.spacing=min(60.,max(1.1,seconds/count+.1))
        except (ValueError,TypeError,OverflowError):pass
        self.next_at=max(self.next_at,self.clock()+self.spacing)
        if response.status_code==429:
            retry=headers.get('retry-after','')
            cooldown=min(60.,max(2.,float(retry))) if re.fullmatch(r'[0-9]{1,6}',retry) else 2.
            self.next_at=max(self.next_at,self.clock()+cooldown)


CROSSREF=SourcePacer()


class WindowLimiter:
    """At most COUNT requests per WINDOW seconds, plus the source's own reset and retry signals.

    GitHub's unauthenticated search allows ten requests a minute; a request that would
    exceed it is refused locally so a cached answer can be used instead.
    """
    def __init__(self, count=10, window=60.0, clock=time.monotonic):
        self.count, self.window, self.clock = count, window, clock
        self.lock = threading.Lock(); self.sent = []; self.blocked_until = 0.

    @contextmanager
    def slot(self, budget):
        if not self.lock.acquire(timeout=min(4., budget.remaining())):raise SourceBusy('Source concurrency limit reached.')
        try:
            now = self.clock()
            self.sent = [at for at in self.sent if now - at < self.window]
            if now < self.blocked_until or len(self.sent) >= self.count:raise SourceBusy('Source request limit reached.')
            self.sent.append(now)
            yield
        finally:self.lock.release()

    def observed(self, response):
        headers = response.headers
        now = self.clock()
        remaining, reset, retry = headers.get('x-ratelimit-remaining', ''), headers.get('x-ratelimit-reset', ''), headers.get('retry-after', '')
        if re.fullmatch(r'[0-9]{1,6}', retry):
            self.blocked_until = max(self.blocked_until, now + min(600., float(retry)))
        if remaining == '0' and re.fullmatch(r'[0-9]{9,11}', reset):
            # The reset is epoch seconds; never wait longer than one window here.
            self.blocked_until = max(self.blocked_until, now + min(self.window, max(1., int(reset) - time.time())))
        if response.status_code in (403, 429) and now >= self.blocked_until:
            self.blocked_until = now + self.window

    def reset_remaining(self):
        with self.lock:
            now = self.clock()
            self.sent = [at for at in self.sent if now - at < self.window]
            if now < self.blocked_until:
                return max(1, int(math.ceil(self.blocked_until - now)))
            if len(self.sent) >= self.count:
                oldest = min(self.sent)
                return max(1, int(math.ceil(oldest + self.window - now)))
            return 0


GITHUB_SEARCH = WindowLimiter()
