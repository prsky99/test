"""Daily task-page snapshot refresh inside the jobs service (11-09 PM decision).

The jobs maintenance slot is shared with retention and the once-a-minute availability check, so
the refresh runs in short slices (about 20 seconds of searches each) and only while it is quiet:
between 03:00 and 07:00 KST, once a day. Searches use the service's own store through the same
Explore functions as /api/explore; nothing goes through the public site. The finished snapshot
is written atomically to <project root>/logs/service-frontend/public-pages/task-pages.json,
where both frontend slots read it.

After a new snapshot is written, pages whose facts changed are sent to IndexNow once (indexnow.py).
That notice is retried every 15 minutes while IndexNow answers 403 (key not yet fetched), at most
eight times; unsent changes stay in the next day's difference.
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
NOTICE_RETRY = 900
NOTICE_ATTEMPTS = 8
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
        self.notice = None   # {'urls': [...], 'pages': {...}, 'attempts': n} waiting to be sent
        self.submit = None   # injectable for tests; defaults to indexnow.submit

    def _age(self):
        try:
            return self.clock() - self.out.stat().st_mtime
        except (OSError, AttributeError):
            return float('inf')

    def due(self):
        if self.out is None or self.clock() < self.retry_at:
            return False
        if self.notice is not None:
            return True
        now = datetime.fromtimestamp(self.clock(), ZONE)
        if self.steps is not None:
            return now.hour in QUIET_HOURS
        return now.hour in QUIET_HOURS and self.attempted_day != now.date() and self._age() >= MIN_AGE

    def run(self):
        """One bounded slice. Errors pause the build for ten minutes and keep what was collected."""
        if self.notice is not None:
            return self.send_notice()
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
                from .agent_check import add_url_keys
                log.info('Task page snapshot: %d URL keys', add_url_keys(self.front.store, snapshot))
            except Exception:  # the check API falls back to indexed key lookups
                log.exception('Task page snapshot URL keys failed')
            try:
                write(str(self.out), snapshot)
            except (OSError, ValueError):
                log.exception('Task page snapshot was not written')
                return
            log.info('Task page snapshot: %d task pages, %d agents', len(snapshot['tasks']), len(snapshot['catalog']))
            self.publish_weekly(snapshot)
            self.aggregate_feedback(snapshot)
            self.record_usage()
            self.prepare_notice(snapshot)

    def record_usage(self):
        """Yesterday's (UTC) real-use line from the anonymous traffic counts: logs/growth/usage-daily.jsonl."""
        try:
            import json
            from datetime import timedelta, timezone as tz
            from . import traffic
            logs = self.out.parent.parent.parent        # <root>/logs/service-frontend/public-pages -> <root>/logs
            day = (datetime.fromtimestamp(self.clock(), tz.utc).date() - timedelta(days=1)).isoformat()
            target = logs / 'growth' / 'usage-daily.jsonl'
            if target.exists() and ('"day": "' + day + '"') in target.read_text(encoding='utf-8'):
                return
            row = {'day': day, **traffic.usage(traffic.load_day(logs / 'service-frontend' / 'traffic', day))}
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, 'a', encoding='utf-8') as out:
                out.write(json.dumps(row) + '\n')
            log.info('Usage line for %s: %s', day, row)
        except Exception:
            log.exception('Usage line was not written')

    def aggregate_feedback(self, snapshot):
        """Daily per-agent report counts for the agents with evidence (registered per-resource statistics)."""
        store = getattr(self.front, 'store', None)
        if store is None:
            return
        from . import feedback
        try:
            ids = [a['id'] for a in snapshot.get('catalog') or [] if isinstance(a, dict) and a.get('id')]
            value = feedback.write_stats(self.out.parent, feedback.aggregate(store, ids), self.clock)
            log.info('Feedback stats: %d reports on %d agents', value['totals']['reports'], value['totals']['agents'])
        except Exception:
            log.exception('Feedback stats were not written')

    def publish_weekly(self, snapshot):
        """Monday (KST): the weekly evidence issue for the week that just ended, once."""
        if datetime.fromtimestamp(self.clock(), ZONE).weekday() != 0:
            return
        from . import weekly_report
        from .growth_pages import clean
        try:
            week = weekly_report.publish(self.out.parent / weekly_report.FOLDER, clean(snapshot))
        except Exception:
            log.exception('Weekly evidence issue was not written')
            return
        if week:
            log.info('Weekly evidence issue %s written', week)

    def prepare_notice(self, snapshot):
        from . import indexnow
        from .growth_pages import clean
        try:
            pages = indexnow.fingerprints(clean(snapshot))
        except Exception:
            log.exception('IndexNow fingerprints failed; no notice today')
            return
        state_path = self.out.parent / 'indexnow-state.json'
        previous = indexnow.read_state(state_path)
        if previous is None:
            indexnow.write_state(state_path, {'pages': pages, 'submitted_at': None})
            log.info('IndexNow baseline recorded for %d pages; nothing sent', len(pages))
            return
        urls = [indexnow.ORIGIN + p for p in indexnow.changed(previous['pages'], pages)]
        if not urls:
            indexnow.write_state(state_path, {'pages': pages, 'submitted_at': previous.get('submitted_at')})
            return
        self.notice = {'urls': urls, 'pages': pages, 'attempts': 0}
        self.send_notice()

    def send_notice(self):
        from . import indexnow
        from .growth_pages import indexnow_key
        notice = self.notice
        key = indexnow_key(lambda: self.out.parent)
        if not key:
            log.warning('IndexNow key file missing; %d changed pages not sent', len(notice['urls']))
            self.notice = None
            return
        notice['attempts'] += 1
        try:
            done, statuses = (self.submit or indexnow.submit)(key, notice['urls'])
        except Exception:
            done, statuses = False, ['error']
            log.exception('IndexNow notice failed')
        if done:
            indexnow.write_state(self.out.parent / 'indexnow-state.json',
                                 {'pages': notice['pages'], 'submitted_at': self.clock()})
            log.info('IndexNow: sent %d changed pages (%s)', len(notice['urls']), statuses)
            self.notice = None
        elif notice['attempts'] >= NOTICE_ATTEMPTS:
            log.warning('IndexNow: giving up today after %s; changes stay in tomorrow\'s difference', statuses)
            self.notice = None
        else:
            self.retry_at = self.clock() + NOTICE_RETRY
            log.info('IndexNow: %s; retrying in %d s', statuses, NOTICE_RETRY)
