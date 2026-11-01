"""Private native PostgreSQL control plane for independently managed services.

Commands are durable, signed and claimed once. Unknown external outcomes are
never automatically replayed. This schema is installed explicitly, not at web
startup. The legacy application schema and its integrity guards are unchanged.
"""
from contextlib import ExitStack, contextmanager
import hashlib
import hmac
import json
import os
import secrets
import threading
import time

SCHEMA = '''
CREATE SCHEMA IF NOT EXISTS service_runtime;
CREATE TABLE IF NOT EXISTS service_runtime.commands (
 id text PRIMARY KEY, kind text NOT NULL, payload text NOT NULL,
 signature text NOT NULL, created double precision NOT NULL,
 state text NOT NULL DEFAULT 'queued', owner text, started double precision,
 finished double precision, result text,
 CHECK (state IN ('queued','running','succeeded','failed','unknown'))
);
CREATE UNIQUE INDEX IF NOT EXISTS service_command_pending_kind
 ON service_runtime.commands(kind) WHERE state IN ('queued','running');
CREATE TABLE IF NOT EXISTS service_runtime.heartbeats (
 role text PRIMARY KEY, owner text NOT NULL, updated double precision NOT NULL,
 status text NOT NULL
);
CREATE TABLE IF NOT EXISTS service_runtime.typed_claims (
 run_id text PRIMARY KEY, owner text NOT NULL, claimed double precision NOT NULL
);
'''
KINDS = frozenset(('pause', 'resume', 'crawl', 'rescan', 'scavenge', 'rag_index'))
OWNER_LOCK = 71498241526019


class ServiceUnavailable(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


class ServiceControl:
    def __init__(self, connection, key, *, reopen=None):
        if type(key) is not bytes or len(key) != 32:
            raise ServiceUnavailable('service_key_required')
        self.connection, self.key = connection, key
        # Web roles may replace a lost session. Owners never do: their session advisory
        # lock dies with the connection, so they exit and are restarted by launchd.
        self.reopen = reopen
        self.lock = threading.RLock()
        self.owner = secrets.token_hex(16)

    @classmethod
    def open(cls, *, reconnect=False):
        from .application_runtime import _connect, _private_bytes
        dsn = _private_bytes(os.environ.get('APPLICATION_POSTGRES_DSN_FILE'), 16384).decode().strip()
        key = _private_bytes(os.environ.get('APPLICATION_WORKFLOW_KEY_FILE'), 32)
        return cls(_connect(dsn), key, reopen=(lambda: _connect(dsn)) if reconnect else None)

    def close(self):
        self.connection.close()

    def _lost(self):
        return bool(self.connection.closed or getattr(self.connection, 'broken', False))

    def _replace(self):
        try: self.connection.close()
        except Exception: pass
        self.connection = self.reopen()

    @contextmanager
    def tx(self):
        import psycopg
        with self.lock, ExitStack() as stack:
            for attempt in (0, 1):
                if self.reopen is not None and self._lost():
                    self._replace()
                try:
                    stack.enter_context(self.connection.transaction())
                    break
                except psycopg.OperationalError:
                    # Retry only a lost session, and only before any statement ran.
                    if attempt or self.reopen is None or not self._lost():
                        raise
            self.connection.execute("SET LOCAL statement_timeout='5000ms'")
            self.connection.execute("SET LOCAL lock_timeout='1000ms'")
            yield self.connection

    def install(self):
        with self.tx() as db:
            db.execute('SELECT pg_advisory_xact_lock(%s)', (OWNER_LOCK + 1,))
            db.execute(SCHEMA)

    def ready(self):
        with self.tx() as db:
            return all(db.execute('SELECT to_regclass(%s)', ('service_runtime.' + name,)).fetchone()[0]
                       for name in ('commands', 'heartbeats', 'typed_claims'))

    def sign(self, identity, kind, payload, created):
        return hmac.new(self.key, canonical([identity, kind, payload, created]).encode(), hashlib.sha256).hexdigest()

    def enqueue(self, kind, payload=None):
        payload = payload or {}
        if kind not in KINDS or type(payload) is not dict:
            raise ValueError('unsupported_service_command')
        if (kind == 'crawl' and (set(payload) != {'force_full'} or type(payload['force_full']) is not bool)
                or kind != 'crawl' and payload):
            raise ValueError('invalid_service_command')
        identity = 'cmd_' + secrets.token_hex(16)
        with self.tx() as db:
            created = float(db.execute('SELECT extract(epoch from clock_timestamp())').fetchone()[0])
            encoded = canonical(payload)
            row = db.execute('''INSERT INTO service_runtime.commands(id,kind,payload,signature,created)
                VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id''',
                (identity, kind, encoded, self.sign(identity, kind, encoded, created), created)).fetchone()
            if row is None:
                row = db.execute("SELECT id FROM service_runtime.commands WHERE kind=%s AND state IN ('queued','running')", (kind,)).fetchone()
            if row is None:
                raise ServiceUnavailable('command_admission_conflict')
            return {'started': row[0] == identity, 'queued': True, 'command_id': row[0]}

    def claim(self):
        with self.tx() as db:
            row = db.execute("""SELECT id,kind,payload,signature,created FROM service_runtime.commands
                WHERE state='queued' ORDER BY created FOR UPDATE SKIP LOCKED LIMIT 1""").fetchone()
            if row is None:
                return None
            identity, kind, payload, signature, created = row
            if kind not in KINDS or not hmac.compare_digest(signature, self.sign(identity, kind, payload, created)):
                db.execute("UPDATE service_runtime.commands SET state='failed',result='invalid_signature' WHERE id=%s", (identity,))
                return None
            db.execute("""UPDATE service_runtime.commands SET state='running',owner=%s,
                started=extract(epoch from clock_timestamp()) WHERE id=%s""", (self.owner, identity))
            return {'id': identity, 'kind': kind, 'payload': json.loads(payload)}

    def finish(self, identity, success):
        with self.tx() as db:
            return db.execute('''UPDATE service_runtime.commands SET state=%s,
                finished=extract(epoch from clock_timestamp()),result=%s
                WHERE id=%s AND owner=%s AND state='running' ''',
                ('succeeded' if success else 'failed', 'completed' if success else 'action_failed', identity, self.owner)).rowcount == 1

    def acquire_owner(self, role='jobs'):
        if role not in ('jobs', 'execution'):
            raise ValueError('invalid_owner_role')
        with self.lock:
            self.reopen = None  # the ownership lock lives exactly as long as this session
            if not self.connection.execute('SELECT pg_try_advisory_lock(%s)', (OWNER_LOCK + (2 if role == 'execution' else 0),)).fetchone()[0]:
                raise ServiceUnavailable('jobs_owner_already_running')
        # A previous owner's side effects are uncertain; never replay them.
        if role == 'jobs':
            with self.tx() as db:
                db.execute("UPDATE service_runtime.commands SET state='unknown',result='owner_interrupted' WHERE state='running' AND owner<>%s", (self.owner,))

    def heartbeat(self, role, status):
        with self.tx() as db:
            db.execute('''INSERT INTO service_runtime.heartbeats VALUES(%s,%s,
                extract(epoch from clock_timestamp()),%s) ON CONFLICT(role) DO UPDATE SET
                owner=excluded.owner,updated=excluded.updated,status=excluded.status''',
                (role, self.owner, canonical(status)))

    def status(self, role='jobs'):
        with self.tx() as db:
            row = db.execute('''SELECT owner,updated,status,
                extract(epoch from clock_timestamp())-updated FROM service_runtime.heartbeats WHERE role=%s''', (role,)).fetchone()
            if row is None:
                return {'available': False}
            status = json.loads(row[2])
            return {**status, 'available': float(row[3]) < 15 and status.get('running', True), 'updated': row[1]}

    def actions(self):
        with self.tx() as db:
            rows = db.execute('''SELECT DISTINCT ON(kind) kind,id,state,created,finished,result
                FROM service_runtime.commands ORDER BY kind,created DESC''').fetchall()
            return {r[0]: {'command_id': r[1], 'running': r[2] in ('queued', 'running'),
                          'state': r[2], 'started_at': r[3], 'finished_at': r[4], 'result': r[5]} for r in rows}

    def claim_typed(self):
        with self.tx() as db:
            row = db.execute('''SELECT r.id,r.workspace_id,r.flow_id FROM public.workspace_typed_flow_runs r
                WHERE r.status='running' AND r.deadline>extract(epoch from clock_timestamp())
                  AND r.payload::jsonb->>'worker_execution'='true'
                  AND NOT EXISTS(SELECT 1 FROM service_runtime.typed_claims c WHERE c.run_id=r.id)
                ORDER BY r.created FOR UPDATE OF r SKIP LOCKED LIMIT 1''').fetchone()
            if row is None:
                return None
            inserted = db.execute('''INSERT INTO service_runtime.typed_claims VALUES(%s,%s,
                extract(epoch from clock_timestamp())) ON CONFLICT DO NOTHING RETURNING run_id''', (row[0], self.owner)).fetchone()
            return row if inserted else None

    def claim_private(self):
        with self.tx() as db:
            row = db.execute('''SELECT r.id,r.workspace_id,r.draft_id,r.snapshot_id
                FROM public.workspace_private_runs r
                WHERE r.status='prepared' AND r.deadline>extract(epoch from clock_timestamp())
                  AND r.payload::jsonb->>'worker_execution'='true'
                  AND NOT EXISTS(SELECT 1 FROM service_runtime.typed_claims c WHERE c.run_id=r.id)
                ORDER BY r.created FOR UPDATE OF r SKIP LOCKED LIMIT 1''').fetchone()
            if row is None:
                return None
            inserted = db.execute('''INSERT INTO service_runtime.typed_claims VALUES(%s,%s,
                extract(epoch from clock_timestamp())) ON CONFLICT DO NOTHING RETURNING run_id''', (row[0], self.owner)).fetchone()
            return row if inserted else None

    def expired_runs(self):
        with self.tx() as db:
            typed = db.execute('''SELECT id,workspace_id,flow_id FROM public.workspace_typed_flow_runs
                WHERE status='running' AND deadline<=extract(epoch from clock_timestamp())
                AND payload::jsonb->>'worker_execution'='true' ORDER BY deadline LIMIT 20''').fetchall()
            private = db.execute('''SELECT id,workspace_id,draft_id,snapshot_id FROM public.workspace_private_runs
                WHERE status IN ('prepared','dispatched') AND deadline<=extract(epoch from clock_timestamp())
                AND payload::jsonb->>'worker_execution'='true' ORDER BY deadline LIMIT 20''').fetchall()
            return typed, private
