"""Durable daily health summaries for the administrator console (design 5.3).

`admin_health_daily` keeps one row per agent per UTC day (checks, successes, latency p50/p95) so
agent history and retention decisions no longer depend on raw health_checks. The table belongs to
the explicitly migrated workspace-admin store; without it the worker stays idle. Writes are short
batches so the global writer lock is held briefly (design 5.3, Chat 503 lesson).
"""
import json
import logging
import time

from .workspace_admin_events import execute, register, rows, transaction

log = logging.getLogger(__name__)
DAY = 86400
BATCH = 500
PAGE = 1000            # agents per read; the PostgreSQL store caps one result at 2000 rows
BACKFILL_DAYS = 7      # raw health checks are kept about a week
TODAY_EVERY = 3600     # refresh the current day hourly
STATE = 'admin_summary:health_daily'

register({
    'health_daily_upsert': '''INSERT INTO admin_health_daily VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(day,resource_id) DO UPDATE SET checks=excluded.checks,ok=excluded.ok,
        latency_p50=excluded.latency_p50,latency_p95=excluded.latency_p95,updated=excluded.updated''',
    'health_daily_agent': '''SELECT day,checks,ok,latency_p50,latency_p95 FROM admin_health_daily
        WHERE resource_id=? AND day>=? ORDER BY day''',
    'health_daily_span': 'SELECT MIN(day) AS oldest,MAX(day) AS newest,COUNT(*) AS n FROM admin_health_daily',
})
# Read-only source aggregates. PostgreSQL computes percentiles natively, one keyset page of agents
# at a time along health_checks(resource_id, at) (measured: about 0.4 s per page, 4.7 s per day);
# SQLite fixtures compute them in Python.
_DAY_PG = '''SELECT resource_id, COUNT(*) AS checks,
    COUNT(*) FILTER (WHERE outcome IN ('healthy','reachable')) AS ok,
    percentile_disc(0.5) WITHIN GROUP (ORDER BY latency_ms) AS p50,
    percentile_disc(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95
    FROM health_checks WHERE at>=%s AND at<%s AND resource_id>%s
    GROUP BY resource_id ORDER BY resource_id LIMIT %s'''
_DAY_SQLITE = 'SELECT resource_id, outcome, latency_ms FROM health_checks WHERE at>=? AND at<?'


def day_key(at):
    return time.strftime('%Y-%m-%d', time.gmtime(at))


def _percentile(values, share):
    ordered = sorted(v for v in values if v is not None)
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))] if ordered else None


class HealthSummaries:
    def __init__(self, store, clock=time.time, every=600):
        self.store, self.clock, self.every = store, clock, every
        self.next_run = 0.0

    def ready(self):
        if not getattr(self.store, '_workspace_admin_events_enabled', False):
            return False
        with transaction(self.store, True) as db:
            native = getattr(db, '_store', None)
            if native is not None:
                return native._execute("SELECT to_regclass('admin_health_daily')").fetchone()[0] is not None
            return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='admin_health_daily'").fetchone() is not None

    def _state(self):
        with transaction(self.store, True) as db:
            found = rows(db, 'state', (STATE,))
        try:
            return json.loads(found[0]['value']) if found else {}
        except (ValueError, TypeError):
            return {}

    def _save_state(self, value):
        with transaction(self.store) as db:
            execute(db, 'put_state', (STATE, json.dumps(value, sort_keys=True)))

    def aggregate(self, start):
        """Per-agent aggregates for the UTC day starting at `start`, yielded page by page (read only)."""
        end = start + DAY
        if getattr(self.store, 'backend', '') == 'postgresql':
            after = -1
            while True:
                with self.store.tx(readonly=True):
                    found = self.store._execute(_DAY_PG, (start, end, after, PAGE)).fetchall()
                if not found:
                    return
                yield [(row[0], row[1], row[2], row[3], row[4]) for row in found]
                if len(found) < PAGE:
                    return
                after = found[-1][0]
        with transaction(self.store, True) as db:
            raw = db.execute(_DAY_SQLITE, (start, end)).fetchall()
        groups = {}
        for resource_id, outcome, latency in raw:
            groups.setdefault(resource_id, []).append((outcome, latency))
        found = [(rid, len(items), sum(1 for o, _ in items if o in ('healthy', 'reachable')),
                  _percentile([l for _, l in items], .5), _percentile([l for _, l in items], .95))
                 for rid, items in sorted(groups.items())]
        for offset in range(0, len(found), PAGE):
            yield found[offset:offset + PAGE]

    def summarize_day(self, start):
        day, now, total = day_key(start), self.clock(), 0
        for page in self.aggregate(start):
            for offset in range(0, len(page), BATCH):
                with transaction(self.store) as db:
                    for rid, checks, ok, p50, p95 in page[offset:offset + BATCH]:
                        execute(db, 'health_daily_upsert', (day, rid, checks, ok, p50, p95, now))
            total += len(page)
        return total

    def run_due(self, force=False):
        """One bounded step: the oldest unsummarized completed day, else a stale current day.

        `force` skips only the call interval; the current day still refreshes at most hourly."""
        now = self.clock()
        if not force and now < self.next_run:
            return None
        self.next_run = now + self.every
        try:
            if not self.ready():
                return {'ready': False}
            state = self._state()
            today = int(now // DAY) * DAY
            done = state.get('completed_through')
            start = max(today - BACKFILL_DAYS * DAY, (done + DAY) if done is not None else 0)
            if start < today:
                n = self.summarize_day(start)
                state['completed_through'] = start
                self._save_state(state)
                return {'ready': True, 'day': day_key(start), 'agents': n}
            if now - state.get('today_at', 0) >= TODAY_EVERY:
                n = self.summarize_day(today)
                state['today_at'] = now
                self._save_state(state)
                return {'ready': True, 'day': day_key(today), 'agents': n, 'partial': True}
            return {'ready': True, 'idle': True}
        except Exception:
            log.exception('admin health summary step failed')
            return {'ready': True, 'failed': True}

    def agent(self, resource_id, days=30):
        since = day_key(self.clock() - days * DAY)
        with transaction(self.store, True) as db:
            return rows(db, 'health_daily_agent', (resource_id, since))

    def span(self):
        with transaction(self.store, True) as db:
            found = rows(db, 'health_daily_span')
        return found[0] if found else {'oldest': None, 'newest': None, 'n': 0}
