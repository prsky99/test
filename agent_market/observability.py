"""Bounded operational metadata, not an execution queue or visitor analytics."""
from contextlib import contextmanager
from contextvars import ContextVar
from collections import deque
import hashlib
import logging
import re
import secrets
import sqlite3
import threading
import time

from .concierge.execution_errors import MESSAGES, failure_code, reference

log = logging.getLogger('agent_market.gateway.observability')
KINDS = ('recommendation','execution','workflow','delivery')
SOURCES = ('agent_discovery','chat','testbench','managed','legacy','workflow_public','workflow_admin','workflow_automation',
           'workflow_schedule','workflow_event','workflow_deployment','workflow_verification','task_delivery','workflow_delivery')
STATES = ('running','pending','succeeded','failed','denied','unknown','timed_out',
          'cancelled','matched','no_match','accepted')
REF = re.compile(r'ex_[0-9a-f]{24}\Z')
ATT = re.compile(r'at_[0-9a-f]{24}\Z')
RETENTION_SECONDS = 7 * 86400
MAX_OPERATIONS = 20000
MAX_PENDING_WRITES = 256
MAX_PENDING_AGE = 60.0
MAX_FLUSH_WRITES = 32
MAX_FLUSH_SECONDS = 0.1
_WRITE_FAILED = object()
STALE_SECONDS = {'recommendation':30,'execution':120,'workflow':300,'delivery':172800}
_current = ContextVar('operational_attempt', default=None)
SCHEMA = '''
CREATE TABLE IF NOT EXISTS platform_operations (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, source TEXT NOT NULL, protocol TEXT,
 resource_id INTEGER, workflow_id INTEGER, parent_id TEXT, status TEXT NOT NULL,
 error_code TEXT, created REAL NOT NULL, finished REAL, elapsed_ms REAL);
CREATE INDEX IF NOT EXISTS platform_operations_recent ON platform_operations(created DESC);
CREATE TABLE IF NOT EXISTS platform_attempts (
 id TEXT PRIMARY KEY, operation_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
 resource_id INTEGER, protocol TEXT, status TEXT NOT NULL, error_code TEXT,
 created REAL NOT NULL, dispatched REAL, finished REAL, elapsed_ms REAL,
 dispatch_to_result_ms REAL, transport_ok INTEGER, protocol_valid INTEGER,
 UNIQUE(operation_id,ordinal));
CREATE INDEX IF NOT EXISTS platform_attempts_operation ON platform_attempts(operation_id,ordinal);
CREATE TABLE IF NOT EXISTS platform_observation_events (
 id INTEGER PRIMARY KEY, event_key TEXT UNIQUE NOT NULL, operation_id TEXT NOT NULL,
 attempt_id TEXT, event TEXT NOT NULL, status TEXT NOT NULL, error_code TEXT, created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS platform_observation_events_operation ON platform_observation_events(operation_id,id);
'''


def number(value):
    return value if type(value) is int and 0 < value < 2**31 else None


def protocol(value):
    return value if value in ('a2a','mcp','x402') else None


def stable_reference(namespace, identity):
    # Only internal run/event IDs may be supplied by application code, never HTTP trace headers.
    return 'ex_' + hashlib.sha256((namespace+':'+identity).encode()).hexdigest()[:24]


def journal_for(store):
    with store._lock:
        journal = getattr(store, '_observation_journal', None)
        if journal is None:
            journal = Journal(store)
            store._observation_journal = journal
        return journal


class Journal:
    def __init__(self, store):
        self.store = store
        self.write_failures = 0
        self.dropped_writes = 0
        self.flushed_writes = 0
        self._pending = deque()
        self._pending_lock = threading.Lock()
        self._flush_lock = threading.Lock()
        self._closed = False
        self.enabled = True
        try:
            with store._lock:
                if store._db.in_transaction:
                    raise sqlite3.OperationalError('Observation initialization requires its own transaction.')
                store._db.executescript(SCHEMA)
        except sqlite3.Error:
            self.enabled = False
            self._unavailable()

    def _unavailable(self):
        with self._pending_lock:
            self.write_failures += 1
            first = self.write_failures == 1
        if first:
            log.warning('Operational metadata recording is unavailable; observed metrics may be incomplete.')

    def _start_write(self, action):
        # Creating an operation/attempt remains best effort: a queued start
        # without a usable identity would leave an invented unfinished record.
        self.flush()
        with self._pending_lock:
            unavailable = self._closed or not self.enabled or bool(self._pending)
            if unavailable:
                self.dropped_writes += 1
        if unavailable:
            return None
        result = self._write(action)
        if result is _WRITE_FAILED or result is None:
            with self._pending_lock:
                self.dropped_writes += 1
            return None
        return result

    def _record(self, action):
        # Only sanitized, idempotent metadata for persisted identities is
        # retained. This queue never contains a business execution callback.
        with self._pending_lock:
            self._expire_pending(time.monotonic())
            if self._closed or not self.enabled or len(self._pending) >= MAX_PENDING_WRITES:
                self.dropped_writes += 1
                return
            self._pending.append((time.monotonic(), action))
        self.flush()

    def _expire_pending(self, now):
        while self._pending and now - self._pending[0][0] >= MAX_PENDING_AGE:
            self._pending.popleft()
            self.dropped_writes += 1

    def flush(self):
        """Try a bounded FIFO drain, without a worker thread or business retry."""
        if not self._flush_lock.acquire(blocking=False):
            return 0
        flushed = 0
        deadline = time.monotonic() + MAX_FLUSH_SECONDS
        try:
            while flushed < MAX_FLUSH_WRITES and time.monotonic() < deadline:
                with self._pending_lock:
                    self._expire_pending(time.monotonic())
                    if self._closed or not self.enabled or not self._pending:
                        break
                    entry = self._pending[0]
                if self._write(entry[1]) is _WRITE_FAILED:
                    break
                with self._pending_lock:
                    if self._pending and self._pending[0] is entry:
                        self._pending.popleft()
                        self.flushed_writes += 1
                flushed += 1
            return flushed
        finally:
            self._flush_lock.release()

    def health(self):
        """Process-local recording completeness; does not inspect visitor data."""
        with self._pending_lock:
            now = time.monotonic()
            self._expire_pending(now)
            return {'process_local': True, 'enabled': self.enabled, 'closed': self._closed,
                    'complete': self.enabled and not self._pending and not self.dropped_writes,
                    'pending_writes': len(self._pending), 'dropped_writes': self.dropped_writes,
                    'write_failures': self.write_failures, 'flushed_writes': self.flushed_writes,
                    'oldest_pending_seconds': max(0.0, now-self._pending[0][0]) if self._pending else 0.0}

    def close(self):
        self.flush()
        with self._pending_lock:
            self._closed = True
            self.dropped_writes += len(self._pending)
            self._pending.clear()

    def _write(self, action):
        if not self.enabled:
            return _WRITE_FAILED
        if getattr(self.store, 'backend', 'sqlite') == 'postgresql':
            # Use the caller-owned native transaction boundary. Never open a
            # SQLite file or commit an unrelated in-flight application write.
            if not self.store._lock.acquire(timeout=0.02):
                self._unavailable()
                return _WRITE_FAILED
            try:
                if self.store._db.in_transaction:
                    self._unavailable()
                    return _WRITE_FAILED
                with self.store.tx() as db:
                    return action(db)
            except sqlite3.Error:
                self._unavailable()
                return _WRITE_FAILED
            finally:
                self.store._lock.release()
        if self.store._path != ':memory:':
            # Catalog workers can hold the Store lock while an HTTP request
            # finishes. A short-lived independent writer avoids dropping final
            # observations merely because an unrelated reader owns that lock.
            try:
                db=sqlite3.connect(self.store._path,timeout=0.05)
                db.row_factory=sqlite3.Row
                try:
                    with db:return action(db)
                finally:
                    db.close()
            except sqlite3.Error:
                self._unavailable()
                return _WRITE_FAILED
        # Observability must not commit a caller's transaction or wait behind a
        # busy writer for the business connection's normal long timeout.
        if not self.store._lock.acquire(timeout=0.02):
            self._unavailable()
            return _WRITE_FAILED
        try:
            db=self.store._db
            if db.in_transaction:
                self._unavailable()
                return _WRITE_FAILED
            previous_timeout=db.execute('PRAGMA busy_timeout').fetchone()[0]
            db.execute('PRAGMA busy_timeout=50')
            try:
                with db:return action(db)
            finally:
                db.execute('PRAGMA busy_timeout='+str(int(previous_timeout)))
        except sqlite3.Error:
            self._unavailable()
            return _WRITE_FAILED
        finally:
            self.store._lock.release()

    @staticmethod
    def _event(db, op, event, status, attempt=None, code=None, at=None):
        key=(attempt or op)+':'+event
        db.execute('INSERT OR IGNORE INTO platform_observation_events '
                   '(event_key,operation_id,attempt_id,event,status,error_code,created) VALUES (?,?,?,?,?,?,?)',
                   (key,op,attempt,event,status,code,time.time() if at is None else at))

    def begin(self, kind, source, *, identity=None, resource_id=None, workflow_id=None, proto=None, parent_id=None):
        if kind not in KINDS or source not in SOURCES:
            raise ValueError('Unsupported observation category.')
        op=identity if isinstance(identity,str) and REF.fullmatch(identity) else reference()
        def create(db):
            if db.execute('SELECT 1 FROM platform_operations WHERE id=?',(op,)).fetchone():return True
            # Pruning is bounded and removes child metadata in the same transaction.
            expired=db.execute('SELECT id FROM platform_operations WHERE created<? ORDER BY created LIMIT 200',
                               (time.time()-RETENTION_SECONDS,)).fetchall()
            if db.execute('SELECT COUNT(*) FROM platform_operations').fetchone()[0] >= MAX_OPERATIONS:
                expired+=db.execute('SELECT id FROM platform_operations WHERE finished IS NOT NULL ORDER BY created LIMIT 200').fetchall()
            for row in expired:
                db.execute('DELETE FROM platform_observation_events WHERE operation_id=?',(row[0],))
                db.execute('DELETE FROM platform_attempts WHERE operation_id=?',(row[0],))
                db.execute('DELETE FROM platform_operations WHERE id=?',(row[0],))
            if db.execute('SELECT COUNT(*) FROM platform_operations').fetchone()[0] >= MAX_OPERATIONS:return _WRITE_FAILED
            db.execute('INSERT INTO platform_operations '
                '(id,kind,source,protocol,resource_id,workflow_id,parent_id,status,created) VALUES (?,?,?,?,?,?,?,\'running\',?)',
                (op,kind,source,protocol(proto),number(resource_id),number(workflow_id),
                 parent_id if isinstance(parent_id,str) and REF.fullmatch(parent_id) else None,time.time()))
            self._event(db,op,'operation.started','running')
            return True
        if not self._start_write(create):return Operation(self,None,kind)
        return Operation(self,op,kind)


class Operation:
    def __init__(self,journal,identity,kind=None):
        self.journal,self.id=journal,identity
        self.kind=kind
        self._attempts=[]

    def detach_attempts(self):
        # Abandoned managed workers must not access storage after their request
        # scope has completed (including application/test database shutdown).
        for attempt in self._attempts:attempt.detached=True

    def selected(self,resource_id,proto=None):
        if not self.id:return
        observed = time.time()
        def select(db):
            db.execute('UPDATE platform_operations SET resource_id=?,protocol=COALESCE(?,protocol) WHERE id=? AND finished IS NULL',
                       (number(resource_id),protocol(proto),self.id))
            self.journal._event(db,self.id,'selection.recorded','running',at=observed)
        self.journal._record(select)

    def attempt(self,resource_id=None,proto=None):
        attempt=Attempt(self,None)
        self._attempts.append(attempt)
        if not self.id:return attempt
        identity='at_'+secrets.token_hex(12)
        def create(db):
            row=db.execute('SELECT finished FROM platform_operations WHERE id=?',(self.id,)).fetchone()
            if not row or row['finished'] is not None:return False
            changed=db.execute('INSERT INTO platform_attempts '
                       '(id,operation_id,ordinal,resource_id,protocol,status,created) '
                       'SELECT ?,?,COALESCE(MAX(ordinal),0)+1,?,?,\'running\',? FROM platform_attempts '
                       'WHERE operation_id=? HAVING COALESCE(MAX(ordinal),0)<100',
                       (identity,self.id,number(resource_id),protocol(proto),time.time(),self.id)).rowcount
            if not changed:return False
            self.journal._event(db,self.id,'attempt.started','running',identity)
            return True
        if self.journal._start_write(create):attempt.id=identity
        return attempt

    def finish(self,status,code=None):
        if not self.id:return
        if status not in STATES:status='failed'
        code=failure_code(code) if code else None
        observed = time.time()
        dispatched_ids = {attempt.id for attempt in self._attempts if attempt.was_dispatched}
        def close(db):
            now=observed
            if status in ('unknown','timed_out','cancelled'):
                for a in db.execute('SELECT id,dispatched FROM platform_attempts WHERE operation_id=? AND finished IS NULL',(self.id,)).fetchall():
                    state='unknown' if a['dispatched'] or a['id'] in dispatched_ids else status
                    db.execute('UPDATE platform_attempts SET status=?,error_code=?,finished=?,elapsed_ms=(?-created)*1000 WHERE id=? AND finished IS NULL',
                               (state,code,now,now,a['id']))
                    self.journal._event(db,self.id,'attempt.finished',state,a['id'],code,at=now)
            final=status
            if status in ('failed','timed_out') and db.execute("SELECT 1 FROM platform_attempts WHERE operation_id=? AND status='unknown'",(self.id,)).fetchone():final='unknown'
            finished=None if final in ('running','pending') else now
            changed=db.execute('UPDATE platform_operations SET status=?,error_code=?,finished=?,elapsed_ms=(?-created)*1000 '
                               'WHERE id=? AND finished IS NULL',(final,code,finished,now,self.id)).rowcount
            if changed:self.journal._event(db,self.id,'operation.pending' if final=='pending' else 'operation.finished',final,code=code,at=now)
        self.journal._record(close)


class Attempt:
    def __init__(self,operation,identity):
        self.operation,self.id=operation,identity
        self.detached=False
        self.was_dispatched=False

    def dispatch(self):
        if not self.id or self.detached:return
        self.was_dispatched=True
        observed = time.time()
        def mark(db):
            changed=db.execute('UPDATE platform_attempts SET dispatched=? WHERE id=? AND dispatched IS NULL AND finished IS NULL',
                               (observed,self.id)).rowcount
            if changed:self.operation.journal._event(db,self.operation.id,'attempt.dispatched','running',self.id,at=observed)
        self.operation.journal._record(mark)

    def finish(self,status,code=None,transport=None,valid=None):
        if not self.id or self.detached:return
        code=failure_code(code) if code else None
        status=status if status in STATES else 'failed'
        observed = time.time()
        was_dispatched = self.was_dispatched
        def close(db):
            a=db.execute('SELECT * FROM platform_attempts WHERE id=?',(self.id,)).fetchone()
            if not a:return
            if a['finished'] is not None:
                if a['status']==status and a['error_code']==code:return
                self.operation.journal._event(db,self.operation.id,'attempt.late_result',status,self.id,code,at=observed)
                return
            state=status
            dispatched = bool(a['dispatched']) or was_dispatched
            if status=='failed' and dispatched and (code in ('UPSTREAM_NETWORK','UPSTREAM_TIMEOUT') or code=='UPSTREAM_PROTOCOL' and valid is not True):state='unknown'
            if status=='failed' and not dispatched and code in ('INVALID_INPUT','SCHEMA_CHANGED','POLICY_DENIED','AUTH_REQUIRED','UNSAFE_TOOL','UNSUPPORTED_SCHEMA','TOOL_UNAVAILABLE'):state='denied'
            now=observed
            db.execute('UPDATE platform_attempts SET status=?,error_code=?,finished=?,elapsed_ms=?,dispatch_to_result_ms=?,transport_ok=?,protocol_valid=? WHERE id=? AND finished IS NULL',
                       (state,code,now,max(0,(now-a['created'])*1000),max(0,(now-a['dispatched'])*1000) if a['dispatched'] else None,
                        int(transport) if type(transport) is bool else None,int(valid) if type(valid) is bool else None,self.id))
            self.operation.journal._event(db,self.operation.id,'attempt.finished',state,self.id,code,at=now)
        self.operation.journal._record(close)


@contextmanager
def attempt_scope(attempt,*,finish_errors=True):
    token=_current.set(attempt)
    try:
        yield attempt
    except Exception as exc:
        code=getattr(exc,'error_code',None)
        if code is None:
            import httpx
            code='UPSTREAM_TIMEOUT' if isinstance(exc,TimeoutError) or isinstance(exc,httpx.TimeoutException) else 'UPSTREAM_NETWORK' if isinstance(exc,httpx.HTTPError) else 'EXECUTION_FAILED'
        if finish_errors:attempt.finish('failed',code)
        raise
    finally:
        _current.reset(token)


def current_attempt(store=None):
    attempt=_current.get()
    return attempt if attempt and (store is None or attempt.operation.journal.store is store) else None


def provider_dispatch():
    attempt=current_attempt()
    if attempt:
        if attempt.detached:
            from .concierge.execution_policy import ExecutionDenied
            raise ExecutionDenied('Execution is no longer active.',error_code='POLICY_DENIED')
        from .execution_authority import require_enabled
        store=attempt.operation.journal.store
        if attempt.operation.kind=='workflow':require_enabled(store,'workflow')
        require_enabled(store,'delivery' if attempt.operation.kind=='delivery' else 'invoke')
    from .workflow_persistence import before_dispatch
    before_dispatch()
    if attempt:attempt.dispatch()


def result_state(result):
    succeeded=result.get('execution_succeeded') is True if 'execution_succeeded' in result else result.get('ok') is True
    if succeeded:return 'succeeded'
    if result.get('task_status')=='timeout':return 'timed_out'
    if result.get('task_status') in ('submitted','working','input-required'):return 'pending'
    if result.get('task_status')=='authorization-required':return 'denied'
    return 'failed'


def snapshot(db,*,hours=24,identity=None,limit=50,journal=None):
    """Administrator-only projection from a read-only snapshot connection."""
    available=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='platform_operations'").fetchone()
    recording = journal.health() if journal is not None else {'process_local': False, 'complete': None,
        'pending_writes': None, 'dropped_writes': None, 'write_failures': None,
        'flushed_writes': None, 'oldest_pending_seconds': None}
    if not available:return {'available':False,'operations':[],'definitions':DEFINITIONS,'recording':recording}
    now=time.time();since=now-hours*3600
    def observed_status(row):
        return 'unknown' if row['finished'] is None and now-row['created']>STALE_SECONDS[row['kind']] else row['status']
    if identity:
        rows=db.execute('SELECT * FROM platform_operations WHERE id=?',(identity,)).fetchall()
    else:
        rows=db.execute('SELECT * FROM platform_operations WHERE created>=? ORDER BY created DESC,id DESC LIMIT ?', (since,limit)).fetchall()
    operations=[dict(row) for row in rows]
    for op in operations:
        op['stored_status']=op['status'];op['status']=observed_status(op)
        op['observation_stale']=op['status']!=op['stored_status']
        op['attempts']=[dict(r) for r in db.execute('SELECT * FROM platform_attempts WHERE operation_id=? ORDER BY ordinal',(op['id'],))]
        if op['observation_stale']:
            for a in op['attempts']:
                if a['finished'] is None:a['status']='unknown' if a['dispatched'] else 'timed_out'
        op['events']=[dict(r) for r in db.execute('SELECT id,event,status,error_code,attempt_id,created FROM platform_observation_events WHERE operation_id=? ORDER BY id LIMIT 500',(op['id'],))]
    counts={kind:{} for kind in KINDS}
    for row in db.execute('SELECT kind,status,created,finished FROM platform_operations WHERE created>=?',(since,)):
        state=observed_status(row);bucket=counts[row['kind']];bucket[state]=bucket.get(state,0)+1
    attempts=db.execute('''SELECT COUNT(*) prepared,COALESCE(SUM(a.dispatched IS NOT NULL),0) dispatched,
        COALESCE(SUM(a.status='unknown' OR (a.finished IS NULL AND a.dispatched IS NOT NULL AND
        ?-o.created > CASE o.kind WHEN 'recommendation' THEN 30 WHEN 'execution' THEN 120 WHEN 'workflow' THEN 300 ELSE 172800 END)),0) unknown_count
        FROM platform_attempts a JOIN platform_operations o ON o.id=a.operation_id WHERE o.created>=?''',(now,since)).fetchone()
    return {'available':True,'hours':hours,'retention_days':7,'scope':'recorded server operations only; no visitor funnel or client analytics',
            'counts':counts,'attempt_counts':dict(attempts),'operations':operations,'definitions':DEFINITIONS,'recording':recording,
            'coverage_complete':False,'limits':['Missing records during storage failure or retention pruning cannot be counted.','Only instrumented paths are included; legacy history is not reconstructed.','Transport acceptance is not recipient receipt; timing is not provider CPU time.','Overdue unfinished observations are projected as unknown without rewriting or resuming business execution.']}


DEFINITIONS = {
    'recommendation':'One executed task search; matched and no_match are separate. Greetings/details are excluded.',
    'execution':'One selected registered-agent execution request; admission denials have zero dispatched attempts. Format demos and protocol discovery are excluded.',
    'workflow':'One accepted saved run; idempotent replay/status polling is not another operation. Provider steps share that operation.',
    'delivery':'One event/destination delivery operation. Retries add attempts. Accepted means transport acceptance, not receipt or advertising consent.',
    'attempt':'One prepared provider step/send. Dispatched means the tool/message/probe/send boundary was entered, not proof of network bytes or provider receipt; handshake/poll HTTP exchanges are not extra attempts.',
    'unknown':'A dispatched attempt has no confirmed result; timeout/late response does not retroactively turn the operation into success.',
    'elapsed_ms':'Operation elapsed wall time; dispatch_to_result_ms is observed adapter round trip, not provider-only computation.',
}
