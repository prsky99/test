"""Additive explicit schema and fixed SQLite/PostgreSQL transaction templates."""
from contextlib import contextmanager
import time

from .config import EdgeError

SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS edge_gateway_policy (
      id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, mode TEXT NOT NULL,
      cpu_blocked INTEGER NOT NULL, usage_day TEXT NOT NULL, reported_usage INTEGER NOT NULL,
      observed_at REAL NOT NULL, health_day TEXT NOT NULL, health_at REAL NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS edge_gateway_days (
      day TEXT PRIMARY KEY, reservations INTEGER NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS edge_gateway_runs (
      id TEXT PRIMARY KEY, principal TEXT NOT NULL, idempotency TEXT NOT NULL,
      input_hash TEXT NOT NULL, resource_id INTEGER NOT NULL, version_id TEXT NOT NULL,
      origin TEXT NOT NULL, state TEXT NOT NULL, backend TEXT NOT NULL, attempt TEXT,
      created REAL NOT NULL, expires REAL NOT NULL, finished REAL, error_code TEXT,
      UNIQUE(principal,idempotency))''',
    'CREATE INDEX IF NOT EXISTS edge_gateway_runs_state ON edge_gateway_runs(state,created)',
    'CREATE INDEX IF NOT EXISTS edge_gateway_runs_recent ON edge_gateway_runs(created)',
    '''CREATE TABLE IF NOT EXISTS edge_gateway_events (
      run_id TEXT NOT NULL, event_id TEXT NOT NULL, outcome TEXT NOT NULL,
      recorded REAL NOT NULL, output_bytes INTEGER NOT NULL, PRIMARY KEY(run_id,event_id))''',
    '''CREATE TABLE IF NOT EXISTS edge_gateway_nonces (
      id TEXT PRIMARY KEY, created REAL NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS edge_gateway_host_audit (
      revision INTEGER PRIMARY KEY, action TEXT NOT NULL, actor TEXT NOT NULL,
      reason TEXT NOT NULL, created REAL NOT NULL)''',
)
Q = {
    'policy': 'SELECT * FROM edge_gateway_policy WHERE id=1',
    'policy_lock': 'SELECT * FROM edge_gateway_policy WHERE id=1 FOR UPDATE',
    'init': "INSERT INTO edge_gateway_policy VALUES(1,0,'auto',0,'',0,0,'',0) ON CONFLICT(id) DO NOTHING",
    'observe': 'UPDATE edge_gateway_policy SET revision=revision+1,usage_day=?,reported_usage=?,observed_at=? WHERE id=1',
    'health': 'UPDATE edge_gateway_policy SET revision=revision+1,health_day=?,health_at=? WHERE id=1',
    'block_cpu': 'UPDATE edge_gateway_policy SET revision=revision+1,cpu_blocked=1 WHERE id=1',
    'mode': 'UPDATE edge_gateway_policy SET revision=revision+1,mode=? WHERE id=1 AND revision=?',
    'clear_block': "UPDATE edge_gateway_policy SET revision=revision+1,cpu_blocked=0,health_day='',health_at=0 WHERE id=1 AND revision=?",
    'audit': 'INSERT INTO edge_gateway_host_audit VALUES(?,?,?,?,?)',
    'audit_monitor_last': "SELECT revision,action,created FROM edge_gateway_host_audit WHERE actor='edge-monitor' ORDER BY revision DESC LIMIT 1",
    'day': 'SELECT reservations FROM edge_gateway_days WHERE day=?',
    'day_init': 'INSERT INTO edge_gateway_days VALUES(?,0) ON CONFLICT(day) DO NOTHING',
    'reserve': 'UPDATE edge_gateway_days SET reservations=reservations+1 WHERE day=?',
    'run': 'SELECT * FROM edge_gateway_runs WHERE id=?',
    'idempotency': 'SELECT * FROM edge_gateway_runs WHERE principal=? AND idempotency=?',
    'insert': "INSERT INTO edge_gateway_runs VALUES(?,?,?,?,?,?,?,'prepared',?,NULL,?,?,NULL,NULL)",
    'claim': "UPDATE edge_gateway_runs SET state='dispatch_reserved',backend=?,attempt=? WHERE id=? AND state='prepared' AND expires>?",
    'active': "SELECT COUNT(*) AS n FROM edge_gateway_runs WHERE state='dispatch_reserved'",
    'finish': "UPDATE edge_gateway_runs SET state=?,finished=?,error_code=? WHERE id=? AND attempt=? AND state='dispatch_reserved'",
    'event': 'INSERT INTO edge_gateway_events VALUES(?,?,?,?,?) ON CONFLICT(run_id,event_id) DO NOTHING',
    'nonce': 'INSERT INTO edge_gateway_nonces VALUES(?,?) ON CONFLICT(id) DO NOTHING',
    'prune_nonces': 'DELETE FROM edge_gateway_nonces WHERE id IN (SELECT id FROM edge_gateway_nonces WHERE created<? ORDER BY created LIMIT 1000)',
    'summary': '''SELECT r.backend,r.state,COUNT(*) AS n,COALESCE(SUM(e.output_bytes),0) AS body_bytes
        FROM edge_gateway_runs r LEFT JOIN edge_gateway_events e ON e.run_id=r.id AND e.event_id=r.attempt
        WHERE r.created>? GROUP BY r.backend,r.state''',
    'expire_unknown': "UPDATE edge_gateway_runs SET state='outcome_unknown',finished=?,error_code='OUTCOME_UNKNOWN' WHERE state='dispatch_reserved' AND created<?",
    'prune_events': "DELETE FROM edge_gateway_events WHERE run_id IN (SELECT id FROM edge_gateway_runs WHERE created<? AND state<>'dispatch_reserved' ORDER BY created,id LIMIT 100)",
    'prune_runs': "DELETE FROM edge_gateway_runs WHERE id IN (SELECT id FROM edge_gateway_runs WHERE created<? AND state<>'dispatch_reserved' ORDER BY created,id LIMIT 100)",
}


@contextmanager
def transaction(store, *, readonly=False):
    with (store.tx(readonly=readonly) if getattr(store, 'backend', '') == 'postgresql' else store.tx()) as db:
        yield db


def execute(db, name, values=()):
    sql = Q[name]
    native = getattr(db, '_store', None)
    return native._execute(sql.replace('?', '%s'), values) if native is not None else db.execute(sql, values)


def rows(db, name, values=()):
    cursor = execute(db, name, values)
    names = [item[0] for item in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def migrate(store):
    """Operator-invoked only: never initialize tables on a public request."""
    with transaction(store) as db:
        native = getattr(db, '_store', None)
        for sql in SCHEMA:
            if native is not None:
                native._execute(sql.replace(' REAL', ' DOUBLE PRECISION').replace(' INTEGER', ' BIGINT'))
            else:
                db.execute(sql)
        execute(db, 'init')


def ready(store):
    try:
        with transaction(store, readonly=True) as db:
            return bool(rows(db, 'policy'))
    except Exception:
        return False


def nonce(store, identity, now=None):
    now = time.time() if now is None else now
    with transaction(store) as db:
        execute(db, 'prune_nonces', (now - 90,))
        if execute(db, 'nonce', (identity, now)).rowcount != 1:
            raise EdgeError('AUTH_REQUIRED', 401)


def host_control(store, action, revision, reason, *, actor='host-operator', now=None):
    import re
    now = time.time() if now is None else now
    if (action not in ('origin', 'auto', 'clear-runtime-block') or type(revision) is not int or revision < 0
            or type(reason) is not str or not 4 <= len(reason) <= 300
            or re.search(r'https?://|vt_|[\x00-\x1f<>@]', reason) or not re.fullmatch(r'[a-z0-9-]{1,40}', actor)):
        raise EdgeError('INVALID_INPUT', 400)
    with transaction(store) as db:
        if action == 'clear-runtime-block':
            changed = execute(db, 'clear_block', (revision,)).rowcount
        else:
            changed = execute(db, 'mode', (action, revision)).rowcount
        if changed != 1:
            raise EdgeError('REVISION_CHANGED', 409)
        execute(db, 'audit', (revision + 1, action, actor, reason, now))
