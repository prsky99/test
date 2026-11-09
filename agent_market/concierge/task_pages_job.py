"""Daily task-page snapshot refresh inside the jobs service (11-09 PM decision).

The jobs maintenance slot is shared with retention and the once-a-minute availability check, so
the refresh runs in short slices (about 20 seconds of searches each) and only while it is quiet:
between 03:00 and 07:00 KST, once a day. Searches use the service's own store through the same
Explore functions as /api/explore; nothing goes through the public site. The finished snapshot
is written atomically to <project root>/logs/service-frontend/public-pages/task-pages.json,
where both frontend slots read it.
"""
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .task_catalog import Assembler, plan, write

log = logging.getLogger(__name__)
ZONE = ZoneInfo('Asia/Seoul')
QUIET_HOURS = range(3, 7)   # start only in this window; an unfinished build waits for the next night
MIN_AGE = 20*3600           # rebuild once a day
SLICE_SECONDS = 20.0
PAUSE = 0.5                 # seconds between searches inside a slice


def default_output():
    root = os.environ.get('AGENTCON_PROJECT_ROOT')
    return Path(root) / 'logs/service-frontend/public-pages/task-pages.json' if root else None


def internal_search(front, step):
    """The same search path as /api/explore, without its HTTP layer, caches or rate limits."""
    from .explore_search import page
    from .discovery import enabled
    kind, category, verified, limit = (None, None, step[3], step[4]) if step[0] == 'task' else (step[2], step[1], step[3], step[4])
    query = step[2] if step[0] == 'task' else ''
    window = min(300, limit+1)
    store = front.store
    if getattr(store, 'backend', None) == 'postgresql' or (query.strip() and enabled(front.rag_engine)):
        from .hybrid_explore import scoped_explore
        result = scoped_explore(store, front.rag_engine, query, kind, category, verified, False, window)
    else:
        from .front import get_front_explore
        result = get_front_explore(store, query, kind, category, verified, False, window)
    return page(result, 0, limit).get('items') or []


def catalog_counts(front):
    """The published daily catalog counts (the same figures as /status.json), when available."""
    try:
        from .daily_statistics import valid
        value = front.daily_statistics.peek() if hasattr(front, 'daily_statistics') else None
        if valid(value):
            return {k: value[k] for k in ('day', 'cataloged', 'reachable', 'with_status_check', 'a2a', 'mcp', 'x402')}
    except Exception:
        log.debug('Daily catalog counts unavailable for the task snapshot', exc_info=True)
    return None


class TaskPagesRefresher:
    def __init__(self, front, *, out=None, clock=time.time, monotonic=time.monotonic, sleep=time.sleep,
                 search=internal_search, categories=None):
        self.front, self.clock, self.monotonic, self.sleep, self.search = front, clock, monotonic, sleep, search
        self.out = Path(out) if out else default_output()
        if categories is None:
            from ..broker.categories import CATEGORIES
            categories = CATEGORIES
        self.categories = list(categories)
        self.steps = None
        self.position = 0
        self.assembler = None
        self.attempted_day = None
        self.retry_at = 0.

    def _age(self):
        try:
            return self.clock() - self.out.stat().st_mtime
        except (OSError, AttributeError):
            return float('inf')

    def due(self):
        if self.out is None or self.clock() < self.retry_at:
            return False
        now = datetime.fromtimestamp(self.clock(), ZONE)
        if self.steps is not None:
            return now.hour in QUIET_HOURS
        return now.hour in QUIET_HOURS and self.attempted_day != now.date() and self._age() >= MIN_AGE

    def run(self):
        """One bounded slice. Errors pause the build for ten minutes and keep what was collected."""
        if self.steps is None:
            self.steps, self.position, self.assembler = plan(self.categories), 0, Assembler()
            self.attempted_day = datetime.fromtimestamp(self.clock(), ZONE).date()
            log.info('Task page snapshot: starting %d searches', len(self.steps))
        started = self.monotonic()
        try:
            while self.position < len(self.steps) and self.monotonic()-started < SLICE_SECONDS:
                step = self.steps[self.position]
                if self.assembler.needs(step):
                    self.assembler.add(step, self.search(self.front, step))
                    self.sleep(PAUSE)
                self.position += 1
        except Exception:
            self.retry_at = self.clock() + 600
            log.exception('Task page snapshot slice failed at step %d; retrying later', self.position)
            return
        if self.position >= len(self.steps):
            snapshot = self.assembler.snapshot(catalog_counts(self.front))
            self.steps, self.assembler = None, None
            try:
                write(str(self.out), snapshot)
            except (OSError, ValueError):
                log.exception('Task page snapshot was not written')
                return
            log.info('Task page snapshot: %d task pages, %d agents', len(snapshot['tasks']), len(snapshot['catalog']))
