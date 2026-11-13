"""Approved retention for large operating tables (design 4.3 and 6.1).

Nothing is deleted by default. A period becomes active only through a reviewed command
(workspace_admin_reviewed, kind `retention_policy`). The runner then removes rows older than the
period in short batches; health checks are removed only for days already kept in
admin_health_daily, so agent history survives shorter raw retention.
"""
import json
import logging
import time

from .workspace_admin_events import execute, rows, transaction
from .workspace_admin_summaries import DAY, STATE as SUMMARY_STATE

log = logging.getLogger(__name__)
POLICY = 'admin_retention:policy'
LAST = 'admin_retention:last'
BATCH = 5000
BUDGET = 2.0  # seconds of deletion per scheduler step
# Rows one scheduler step may remove from a table, on top of the time budget (11-11 user decision:
# security_events keeps 90 days and each run removes at most 10,000 rows).
STEP_LIMIT = {'security_events': 10000}
# Periods applied by code without a reviewed command (PM 11-14, carrying out the 11-11 user decision of 90 days).
# A reviewed policy for the same table wins, and a reviewed None stops it.
DEFAULT_DAYS = {'security_events': 90}
# table -> (time column, shortest period in days, label, extra condition, required index or None).
# A table qualifies only with a time index, so each batch reads a bounded range.
TABLES = {
    'health_checks': ('at', 3, '상태 확인 원본', None, None),
    'security_events': ('at', 30, '보안 이벤트', None, None),
    'crawl_runs': ('at', 7, '수집 실행 기록', None, None),
    'legacy_vector_jobs': ('finished', 3, '완료된 벡터 작업', "status IN ('indexed','failed','superseded')", 'legacy_vector_jobs_finished_done'),
    'platform_observation_events': ('created', 30, '실행 관측 이벤트', None, 'platform_observation_events_created'),
}
_DELETE = {
    'postgresql': 'DELETE FROM {t} WHERE ctid IN (SELECT ctid FROM {t} WHERE {c}<%s{w} LIMIT {n})',
    'sqlite': 'DELETE FROM {t} WHERE rowid IN (SELECT rowid FROM {t} WHERE {c}<?{w} LIMIT {n})',
}


def validate(payload):
    """A reviewed policy change: one table, a period at or above its floor (or None to stop), backup confirmed."""
    if (not isinstance(payload, dict) or set(payload) != {'table', 'days', 'backup_confirmed'}
            or payload['table'] not in TABLES or payload['backup_confirmed'] is not True):
        raise ValueError('Retention changes need a supported table and a confirmed verified backup.')
    days = payload['days']
    if days is not None and (type(days) is not int or not TABLES[payload['table']][1] <= days <= 3650):
        raise ValueError('Retention period is below the minimum for this table.')
    return payload


class Retention:
    def __init__(self, store, clock=time.time, every=300):
        self.store, self.clock, self.every = store, clock, every
        self.next_run = 0.0

    def ready(self):
        return bool(getattr(self.store, '_workspace_admin_events_enabled', False))

    def _get(self, key):
        with transaction(self.store, True) as db:
            found = rows(db, 'state', (key,))
        try:
            return json.loads(found[0]['value']) if found else {}
        except (ValueError, TypeError):
            return {}

    def _put(self, key, value):
        with transaction(self.store) as db:
            execute(db, 'put_state', (key, json.dumps(value, sort_keys=True)))

    def effective(self):
        """The code defaults overlaid by the reviewed policy (a reviewed None stops a default)."""
        return {**DEFAULT_DAYS, **self._get(POLICY)}

    def policy(self):
        return {name: self.effective().get(name) for name in TABLES} if self.ready() else {}

    def apply(self, payload, user_id):
        """Reviewed command applier: store the approved period; deletion happens in later steps."""
        validate(payload)
        if not self.ready():
            raise ValueError('The workspace administration store is not migrated.')
        current = self._get(POLICY)
        current[payload['table']] = payload['days']
        self._put(POLICY, current)
        return {'table': payload['table'], 'days': payload['days'], 'approved_by': user_id}

    def cutoff(self, table, days, now):
        cutoff = now - days * DAY
        if table == 'health_checks':
            # Raw checks go only after their day is summarized.
            done = self._get(SUMMARY_STATE).get('completed_through')
            cutoff = min(cutoff, done + DAY) if done is not None else 0
        return cutoff

    def indexed(self, table):
        """Whether the table's batch deletes are index-bounded. PostgreSQL indexes come from
        scripts.admin_console_indexes; SQLite development stores build theirs here."""
        name = TABLES[table][4]
        if name is None:
            return True
        if getattr(self.store, 'backend', '') == 'postgresql':
            with self.store.tx(readonly=True):
                found = self.store._execute('''SELECT i.indisvalid FROM pg_class c JOIN pg_index i ON i.indexrelid=c.oid
                    JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=current_schema() AND c.relname=%s''', (name,)).fetchone()
            return bool(found and found[0])
        from .admin_query_indexes import RETENTION_INDEXES, retention_index_sql
        with transaction(self.store) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                return False
            for (index, _, _, _), statement in zip(RETENTION_INDEXES, retention_index_sql()):
                if index == name:
                    db.execute(statement)
        return True

    def _delete_batch(self, table, column, cutoff):
        backend = 'postgresql' if getattr(self.store, 'backend', '') == 'postgresql' else 'sqlite'
        extra = TABLES[table][3]
        sql = _DELETE[backend].format(t=table, c=column, n=BATCH, w=' AND ' + extra if extra else '')
        if backend == 'postgresql':
            with self.store.tx():
                return self.store._execute(sql, (cutoff,)).rowcount
        with transaction(self.store) as db:
            return db.execute(sql, (cutoff,)).rowcount

    def run_due(self, force=False):
        now = self.clock()
        if not force and now < self.next_run:
            return None
        self.next_run = now + self.every
        try:
            if not self.ready():
                return {'ready': False}
            reviewed = self._get(POLICY)
            policy, removed, started = {**DEFAULT_DAYS, **reviewed}, {}, time.monotonic()
            for table, (column, *_rest) in TABLES.items():
                days = policy.get(table)
                if days is None:
                    continue
                if not self.indexed(table):
                    removed[table] = 'index_missing'
                    continue
                cutoff = self.cutoff(table, days, now)
                removed[table] = 0
                limit = STEP_LIMIT.get(table)
                while cutoff > 0 and time.monotonic() - started < BUDGET and (limit is None or removed[table] < limit):
                    count = self._delete_batch(table, column, cutoff)
                    removed[table] += count
                    if count < BATCH:
                        break
                if removed[table] == 0 and table not in reviewed:
                    del removed[table]  # a quiet code default is not reported as a run
            if removed:
                self._put(LAST, {'at': now, 'removed': removed})
                if any(isinstance(v, int) and v for v in removed.values()):
                    log.info('admin retention removed %s', removed)
            return {'ready': True, 'removed': removed}
        except Exception:
            log.exception('admin retention step failed')
            return {'ready': True, 'failed': True}

    def status(self):
        return {'policy': self.policy(), 'last': self._get(LAST) if self.ready() else {},
                'tables': {name: {'column': c, 'minimum_days': m, 'label': label, 'indexed': self.indexed(name)}
                           for name, (c, m, label, _, _) in TABLES.items()}}
