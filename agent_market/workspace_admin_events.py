"""Explicitly migrated, transactional and bounded workspace operating events.

Only source-owned SQL templates enter this module. Native PostgreSQL statements
are selected from the same closed registry, never from request-supplied SQL.
"""
from contextlib import contextmanager
import hashlib
import hmac
import json
import math
import re
import secrets
import time
from functools import wraps

from .workspace_access import WorkspaceConflict, WorkspaceInvalid

VERSION = 'workspace-admin-control-v1'
SCHEMA = (
    'CREATE TABLE IF NOT EXISTS workspace_admin_state(id TEXT PRIMARY KEY,value TEXT NOT NULL)',
    '''CREATE TABLE IF NOT EXISTS workspace_admin_outbox(id TEXT PRIMARY KEY,event_key TEXT UNIQUE NOT NULL,
       customer_id TEXT,workspace_id TEXT,created REAL NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL,
       status TEXT NOT NULL,attempts INTEGER NOT NULL,fence INTEGER NOT NULL,lease_until REAL NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS workspace_admin_events(id TEXT PRIMARY KEY,event_key TEXT UNIQUE NOT NULL,
       customer_id TEXT,workspace_id TEXT,event_type TEXT NOT NULL,object_id TEXT,outcome TEXT NOT NULL,
       occurred REAL NOT NULL,recorded REAL NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    'CREATE INDEX IF NOT EXISTS workspace_admin_event_customer ON workspace_admin_events(customer_id,occurred,id)',
    'CREATE INDEX IF NOT EXISTS workspace_admin_event_workspace ON workspace_admin_events(workspace_id,occurred,id)',
    'CREATE INDEX IF NOT EXISTS workspace_admin_event_recent ON workspace_admin_events(occurred,event_type)',
    'CREATE INDEX IF NOT EXISTS workspace_admin_event_object ON workspace_admin_events(object_id,occurred,id)',
    'CREATE INDEX IF NOT EXISTS workspace_admin_outbox_pending ON workspace_admin_outbox(status,lease_until,created)',
    '''CREATE TABLE IF NOT EXISTS workspace_admin_cases(id TEXT PRIMARY KEY,customer_id TEXT NOT NULL,
       workspace_id TEXT,status TEXT NOT NULL,priority TEXT NOT NULL,assigned_to INTEGER,revision INTEGER NOT NULL,
       created REAL NOT NULL,updated REAL NOT NULL,source_ref TEXT,subject TEXT NOT NULL)''',
    'CREATE INDEX IF NOT EXISTS workspace_admin_case_status ON workspace_admin_cases(status,updated,id)',
    'CREATE INDEX IF NOT EXISTS workspace_admin_case_customer ON workspace_admin_cases(customer_id,id)',
    '''CREATE TABLE IF NOT EXISTS workspace_admin_messages(id TEXT PRIMARY KEY,case_id TEXT NOT NULL,
       author TEXT NOT NULL,visibility TEXT NOT NULL,body TEXT NOT NULL,created REAL NOT NULL,request_id TEXT UNIQUE NOT NULL,request_digest TEXT NOT NULL)''',
    'CREATE INDEX IF NOT EXISTS workspace_admin_message_case ON workspace_admin_messages(case_id,created,id)',
    '''CREATE TABLE IF NOT EXISTS workspace_admin_commands(id TEXT PRIMARY KEY,customer_id TEXT NOT NULL,
       kind TEXT NOT NULL,revision INTEGER NOT NULL,status TEXT NOT NULL,requested_by INTEGER NOT NULL,
       approved_by INTEGER,created REAL NOT NULL,updated REAL NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    'CREATE INDEX IF NOT EXISTS workspace_admin_command_recent ON workspace_admin_commands(created,id)',
    '''CREATE TABLE IF NOT EXISTS workspace_admin_incidents(id TEXT PRIMARY KEY,status TEXT NOT NULL,
       revision INTEGER NOT NULL,assigned_to INTEGER,created REAL NOT NULL,updated REAL NOT NULL,
       category TEXT NOT NULL,reason TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS workspace_admin_disclosures(id TEXT PRIMARY KEY,customer_id TEXT NOT NULL,
       case_id TEXT NOT NULL,workspace_id TEXT NOT NULL,object_id TEXT NOT NULL,expires REAL NOT NULL,
       revoked REAL,created REAL NOT NULL,revision INTEGER NOT NULL,object_revision INTEGER NOT NULL,binding TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS workspace_admin_audit(id TEXT PRIMARY KEY,actor TEXT NOT NULL,
       action TEXT NOT NULL,object_id TEXT NOT NULL,created REAL NOT NULL,reason TEXT NOT NULL)''',
    'CREATE INDEX IF NOT EXISTS workspace_admin_audit_recent ON workspace_admin_audit(created,id)',
    '''CREATE TABLE IF NOT EXISTS workspace_admin_case_links(case_id TEXT NOT NULL,source_kind TEXT NOT NULL,
       source_ref TEXT NOT NULL,linked_by INTEGER NOT NULL,created REAL NOT NULL,reason TEXT NOT NULL,
       PRIMARY KEY(case_id,source_kind,source_ref),UNIQUE(source_kind,source_ref))''',
    '''CREATE TABLE IF NOT EXISTS workspace_admin_operation_links(operation_id TEXT PRIMARY KEY,
       object_id TEXT NOT NULL,workspace_id TEXT NOT NULL,customer_id TEXT,created REAL NOT NULL)''',
    'CREATE INDEX IF NOT EXISTS workspace_admin_operation_object ON workspace_admin_operation_links(object_id)',
    # Reviewed commands that are not tied to one customer (workspace_admin_reviewed).
    '''CREATE TABLE IF NOT EXISTS admin_reviewed_commands(id TEXT PRIMARY KEY,kind TEXT NOT NULL,
       target TEXT NOT NULL,revision INTEGER NOT NULL,status TEXT NOT NULL,requested_by INTEGER NOT NULL,
       approved_by INTEGER,created REAL NOT NULL,updated REAL NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL,
       result TEXT)''',
    'CREATE INDEX IF NOT EXISTS admin_reviewed_command_recent ON admin_reviewed_commands(created,id)',
    # Daily per-agent health summaries for the console (workspace_admin_summaries).
    '''CREATE TABLE IF NOT EXISTS admin_health_daily(day TEXT NOT NULL,resource_id INTEGER NOT NULL,
       checks INTEGER NOT NULL,ok INTEGER NOT NULL,latency_p50 INTEGER,latency_p95 INTEGER,updated REAL NOT NULL,
       PRIMARY KEY(day,resource_id))''',
    'CREATE INDEX IF NOT EXISTS admin_health_daily_agent ON admin_health_daily(resource_id,day)',
)

# Names and SQL are compile-time constants. Only parameter values cross the API.
Q = {
    'state': 'SELECT value FROM workspace_admin_state WHERE id=?',
    'put_state': 'INSERT INTO workspace_admin_state VALUES(?,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value',
    'outbox_insert': '''INSERT INTO workspace_admin_outbox VALUES(?,?,?,?,?,?,?,'pending',0,0,0)
        ON CONFLICT(event_key) DO NOTHING''',
    'outbox_pending': "SELECT * FROM workspace_admin_outbox WHERE status='pending' OR (status='claimed' AND lease_until<?) ORDER BY created,id LIMIT ?",
    'outbox_claim': "UPDATE workspace_admin_outbox SET status='claimed',fence=fence+1,attempts=attempts+1,lease_until=? WHERE id=? AND fence=? AND status IN ('pending','claimed')",
    'event_insert': 'INSERT INTO workspace_admin_events VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(event_key) DO NOTHING',
    'outbox_done': "DELETE FROM workspace_admin_outbox WHERE id=? AND fence=? AND status='claimed'",
    'outbox_bad': "UPDATE workspace_admin_outbox SET status='quarantined',lease_until=0 WHERE id=? AND fence=?",
    'pending_count': 'SELECT status,COUNT(*) AS n,MIN(created) AS oldest FROM workspace_admin_outbox GROUP BY status',
    'event_prune': 'DELETE FROM workspace_admin_events WHERE id IN (SELECT id FROM workspace_admin_events WHERE occurred<? ORDER BY occurred,id LIMIT ?)',
    'event_prune_auth': '''DELETE FROM workspace_admin_events WHERE id IN (SELECT id FROM workspace_admin_events
        WHERE event_type LIKE 'auth.%' AND customer_id IS NULL AND occurred<? ORDER BY occurred,id LIMIT ?)''',
    'audit_insert': 'INSERT INTO workspace_admin_audit VALUES(?,?,?,?,?,?)',
    'observation_link': 'INSERT INTO workspace_admin_operation_links VALUES(?,?,?,?,?) ON CONFLICT(operation_id) DO NOTHING',
}


def register(values):
    """Register fixed module templates during import, never on a request path."""
    for name, statement in values.items():
        if name in Q:
            raise ValueError('Duplicate workspace operations query')
        Q[name] = statement


def execute(db, name, params=()):
    statement = Q[name]
    native = getattr(db, '_store', None)
    if native is not None:
        return native._execute(statement.replace('%', '%%').replace('?', '%s'), params)
    return db.execute(statement, params)


def rows(db, name, params=()):
    cur = execute(db, name, params)
    return [dict(zip([c[0] for c in cur.description], row)) for row in cur.fetchall()]


@contextmanager
def transaction(store, readonly=False):
    with (store.tx(readonly=readonly) if getattr(store, 'backend', '') == 'postgresql' else store.tx()) as db:
        yield db


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def source_present(db,table):
    if table not in ('customer_organizations','workspace_private_runs','workspace_typed_flow_runs',
                     'workspace_drafts','workspace_typed_flows','workspace_executable_releases','workspace_release_deployments',
                     'customer_credit_events','customer_organization_audit','customer_workspace_audit'):
        raise WorkspaceInvalid()
    native=getattr(db,'_store',None)
    if native is not None:
        return native._execute('SELECT to_regclass(%s)',(table,)).fetchone()[0] is not None
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone() is not None


def signature(key, value):
    return hmac.new(key, canonical(value).encode(), hashlib.sha256).hexdigest()


def activate(store, key):
    """Inspect readiness without creating tables or enabling a missing migration."""
    with transaction(store, True) as db:
        native = getattr(db, '_store', None)
        if native is not None:
            present = native._execute("SELECT to_regclass('workspace_admin_state')").fetchone()[0] is not None
        else:
            present = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workspace_admin_state'").fetchone() is not None
        marker=rows(db,'state',(VERSION,)) if present else []
        ready=bool(marker)
        if marker:
            try:
                value=json.loads(marker[0]['value'])
                expected=hmac.new(key,b'workspace-admin-migration-key-v1',hashlib.sha256).hexdigest()
                if value['schema_version']!=1 or not hmac.compare_digest(value['key_binding'],expected):
                    raise WorkspaceConflict()
            except (ValueError,KeyError,TypeError):
                raise WorkspaceConflict() from None
    store._workspace_admin_event_key = hmac.new(key, VERSION.encode(), hashlib.sha256).digest()
    store._workspace_admin_identity_key = key
    store._workspace_admin_events_enabled = ready
    return ready


def migrate(store, key):
    """Additive, idempotent migration; called only by an explicit operator CLI."""
    with transaction(store) as db:
        native = getattr(db, '_store', None)
        for statement in SCHEMA:
            if native is not None:
                native._execute(statement.replace(' REAL ', ' DOUBLE PRECISION ').replace(' INTEGER', ' BIGINT'))
            else:
                db.execute(statement)
        marker=rows(db,'state',(VERSION,))
        binding=hmac.new(key,b'workspace-admin-migration-key-v1',hashlib.sha256).hexdigest()
        if marker:
            try:
                value=json.loads(marker[0]['value'])
                if value['schema_version']!=1 or not hmac.compare_digest(value['key_binding'],binding):raise WorkspaceConflict()
            except (ValueError,KeyError,TypeError):raise WorkspaceConflict() from None
        else:
            execute(db, 'put_state', (VERSION, canonical({'schema_version': 1, 'created': time.time(),'key_binding':binding})))
    return activate(store, key)


def emit(store, db, event_type, *, customer=None, workspace=None, object_id=None,
         outcome='recorded', event_key=None, occurred=None, error_code=None, provider=None):
    """Required atomic metadata after migration; no best-effort exception swallow."""
    if not getattr(store, '_workspace_admin_events_enabled', False):
        return None
    if not re.fullmatch(r'[a-z][a-z0-9_.]{1,95}', event_type):
        raise WorkspaceInvalid()
    for value in (customer, workspace, object_id):
        if value is not None and (type(value) is not str or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,120}', value)):
            raise WorkspaceInvalid()
    if outcome not in ('recorded', 'succeeded', 'failed', 'unknown', 'denied', 'requested'):
        raise WorkspaceInvalid()
    if error_code is not None and (type(error_code) is not str or not re.fullmatch('[A-Z_]{1,64}',error_code)):
        raise WorkspaceInvalid()
    if provider not in (None,'google','github','local','chatgpt','configured'): raise WorkspaceInvalid()
    now = time.time() if occurred is None else occurred
    if type(now) not in (float, int) or not math.isfinite(now) or now < 0:
        raise WorkspaceInvalid()
    identity = 'wae_' + secrets.token_hex(16)
    key = event_key or identity
    if type(key) is not str or not 1 <= len(key) <= 180:
        raise WorkspaceInvalid()
    value = {'id': identity, 'type': event_type, 'customer_id': customer, 'workspace_id': workspace,
             'object_id': object_id, 'outcome': outcome, 'occurred_at': now, 'schema_version': 1,
             'source': VERSION, 'source_event_key': key}
    if error_code is not None:
        value['safe_error_code']=error_code
    if provider is not None:
        value['provider']=provider
    execute(db, 'outbox_insert', (identity, key, customer, workspace, now, canonical(value),
                                 signature(store._workspace_admin_event_key, value)))
    return identity


def drain(store, limit=100):
    if type(limit) is not int or not 1 <= limit <= 500:
        raise WorkspaceInvalid()
    completed = quarantined = 0
    with transaction(store) as db:
        now = time.time()
        for row in rows(db, 'outbox_pending', (now, limit)):
            if execute(db, 'outbox_claim', (now+30, row['id'], row['fence'])).rowcount != 1:
                continue
            fence = row['fence'] + 1
            try:
                value = json.loads(row['payload'])
                valid = (hmac.compare_digest(signature(store._workspace_admin_event_key, value), row['signature'])
                    and value['id'] == row['id'] and value['customer_id'] == row['customer_id']
                    and value['workspace_id'] == row['workspace_id'] and value['occurred_at'] == row['created']
                    and value['source_event_key'] == row['event_key'])
            except (ValueError, KeyError, TypeError):
                valid = False
            if not valid:
                execute(db, 'outbox_bad', (row['id'], fence))
                quarantined += 1
                continue
            execute(db, 'event_insert', (row['id'], row['event_key'], row['customer_id'], row['workspace_id'],
                value['type'], value['object_id'], value['outcome'], value['occurred_at'], now, row['payload'], row['signature']))
            execute(db, 'outbox_done', (row['id'], fence))
            completed += 1
        execute(db, 'put_state', ('last_projection', str(now)))
    return {'projected': completed, 'quarantined': quarantined}


def audit(db, actor, action, identity, reason):
    execute(db, 'audit_insert', ('waa_'+secrets.token_hex(16), str(actor), action, identity, time.time(), reason))


def link_observation(store,db,operation,identity,workspace,customer=None):
    if getattr(store,'_workspace_admin_events_enabled',False) and operation and operation.id:
        execute(db,'observation_link',(operation.id,identity,workspace,customer,time.time()))


def track_generation(method):
    @wraps(method)
    def tracked(self, ws, body, actor, *args, **kwargs):
        if not getattr(self.store, '_workspace_admin_events_enabled', False):
            return method(self, ws, body, actor, *args, **kwargs)
        identity='wgen_'+secrets.token_hex(16)
        customer=getattr(actor,'customer_id',None)
        provider={'OllamaGraphProposer':'local','ChatGPTGraphProposer':'chatgpt'}.get(type(self.model_proposer).__name__,'configured')
        def record(kind,outcome):
            # Completion is a fact about the already-authorized attempt, not a
            # renewed permission to read customer data after session revocation.
            with transaction(self.store) as db:
                emit(self.store,db,kind,customer=customer,workspace=ws,object_id=identity,outcome=outcome,provider=provider)
        with self.access._tx(actor) as (db,_):
            self.access._access(ws,actor,write=True)
            emit(self.store,db,'generation.requested',customer=customer,workspace=ws,object_id=identity,outcome='requested',provider=provider)
        try:
            value=method(self,ws,body,actor,*args,**kwargs)
        except Exception:
            # A failed local return never proves a remote model did not run.
            record('generation.unknown','unknown')
            raise
        record('generation.completed','succeeded' if value.get('state')=='review_required' else 'denied')
        return value
    return tracked


def track_auth_failure(method):
    @wraps(method)
    def tracked(self,*args,**kwargs):
        try:
            return method(self,*args,**kwargs)
        except Exception:
            if getattr(self.store,'_workspace_admin_events_enabled',False):
                with self.tx() as db:
                    provider=args[3] if len(args)>3 else kwargs.get('provider','google')
                    emit(self.store,db,'auth.failed',outcome='denied',provider=provider if provider in ('google','github') else None)
            raise
    return tracked
