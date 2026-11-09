"""Explicit PostgreSQL application Store with a reviewed legacy SQL registry.

The connection is supplied by the caller. No DSN, configuration, environment,
server, migration or cutover is inferred. Persistent catalog and staff/session
data live in PostgreSQL. The exact legacy FTS5 engine is an ephemeral, bounded
read projection, rather than an unannounced substitute ranking algorithm.
Unsupported legacy SQL and vector paths fail closed.
"""
from contextlib import contextmanager
import hashlib
import json
import logging
import math
from decimal import Decimal
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time

from .gateway.store import Store
from .application_store_collector import PostgresCollectorMixin
from .application_store_finance import PostgresFinanceMixin
from .application_store_consumers import PostgresConsumerMixin
from .application_store_selection import PostgresSelectionMixin
from .storage_adapter import Row, StorageError

PROFILE = 'application-postgres-store-v1'
MAX_ROWS = 2000
MAX_BYTES = 8 * 1024 * 1024
MAX_CORPUS_ROWS = 200000
MAX_CORPUS_BYTES = 128 * 1024 * 1024
WRITER_LOCK = 71498241526018
_CATALOG = json.loads(Path(__file__).with_name('application_store_sql.json').read_text())
log = logging.getLogger(__name__)
RECONNECT_BACKOFF = 1.0


def _normalized(sql):
    # Resolve formatting-only variants of a registered statement. Literal and
    # identifier bytes remain exact; comments deliberately retain exact bytes.
    # This selects a fixed dialect pair and never translates incoming SQL.
    result, quote, pending, position = [], None, False, 0
    while position < len(sql):
        char = sql[position]
        if quote:
            result.append(char)
            if char == quote:
                if position + 1 < len(sql) and sql[position + 1] == quote:
                    result.append(quote); position += 1
                else: quote = None
        elif sql[position:position + 2] in ('--', '/*'):
            return sql.strip()
        elif char.isspace(): pending = bool(result)
        else:
            if pending: result.append(' '); pending = False
            result.append(char)
            if char in ("'", '"'): quote = char
        position += 1
    return ''.join(result)


_STATEMENTS = {_normalized(item['sqlite']): item for item in _CATALOG['statements']}


def _invariant_ddl(namespace='public'):
    if namespace != 'public' and not re.fullmatch(r'ac_b2a_[0-9a-f]{24}', namespace):
        raise ValueError('Invalid rehearsal namespace.')
    report_claims = ('public' if namespace == 'public' else '"'+namespace+'"') + '.test_report_subject_claims'
    """Exact trigger/function definitions attested again on every attachment."""
    commands = []
    commands.append('''CREATE FUNCTION application_catalog_epoch() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN UPDATE application_store_state SET catalog_epoch=catalog_epoch+1 WHERE id=1;
        RETURN NULL; END $$''')
    commands.append('''CREATE TRIGGER application_catalog_epoch AFTER INSERT OR UPDATE OR DELETE
        ON resources_fts FOR EACH STATEMENT EXECUTE FUNCTION application_catalog_epoch()''')
    from .observation_guards import FIELDS
    fields = tuple(dict.fromkeys(FIELDS + ('cap_checked_at', 'cap_error', 'auth_checked_at',
        'health_status', 'trial_info', 'trial_ok')))
    # Identifiers come exclusively from the source field allowlist.
    changed = ' OR '.join('OLD."' + name + '" IS DISTINCT FROM NEW."' + name + '"' for name in fields)
    commands.append('''CREATE FUNCTION application_observation_generation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN IF TG_OP='INSERT' THEN
          INSERT INTO resource_observation_generations VALUES(NEW.id,1)
            ON CONFLICT(resource_id) DO UPDATE SET generation=resource_observation_generations.generation+1;
          DELETE FROM resource_observation_owners WHERE resource_id=NEW.id;
        ELSIF ''' + changed + ''' THEN
          UPDATE resource_observation_generations SET generation=generation+1 WHERE resource_id=NEW.id;
          DELETE FROM capability_eligibility WHERE resource_id=NEW.id;
        END IF; RETURN NEW; END $$''')
    commands.append('''CREATE TRIGGER application_observation_generation AFTER INSERT OR UPDATE
        ON resources FOR EACH ROW EXECUTE FUNCTION application_observation_generation()''')
    commands.append('''CREATE FUNCTION application_vector_enqueue() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE identity TEXT; BEGIN
          INSERT INTO legacy_vector_generations VALUES(NEW.resource_id,1) ON CONFLICT(resource_id) DO NOTHING;
          UPDATE legacy_vector_generations SET generation=generation+1 WHERE resource_id=NEW.resource_id;
          UPDATE legacy_vector_jobs SET status='superseded',finished=EXTRACT(EPOCH FROM clock_timestamp())
            WHERE resource_id=NEW.resource_id AND status IN ('pending','claimed');
          identity := 'lvj_'||md5(random()::text||clock_timestamp()::text||pg_backend_pid()::text);
          INSERT INTO legacy_vector_heads VALUES(NEW.resource_id,identity)
            ON CONFLICT(resource_id) DO UPDATE SET job_id=EXCLUDED.job_id;
          INSERT INTO legacy_vector_jobs(job_id,resource_id,generation,status,created)
            SELECT identity,NEW.resource_id,generation,'pending',EXTRACT(EPOCH FROM clock_timestamp())
            FROM legacy_vector_generations WHERE resource_id=NEW.resource_id;
          RETURN NEW; END $$''')
    commands.append('''CREATE TRIGGER application_vector_enqueue AFTER INSERT OR UPDATE
        ON vec_outbox FOR EACH ROW EXECUTE FUNCTION application_vector_enqueue()''')
    vector_fields = tuple(dict.fromkeys(FIELDS + ('health_status', 'eval_security')))
    vector_changed = ' OR '.join('OLD."' + name + '" IS DISTINCT FROM NEW."' + name + '"' for name in vector_fields)
    commands.append('''CREATE FUNCTION application_vector_invalidate() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN IF TG_OP='DELETE' THEN
          UPDATE legacy_vector_generations SET generation=generation+1 WHERE resource_id=OLD.id;
          DELETE FROM legacy_vector_provenance WHERE resource_id=OLD.id;
          DELETE FROM vec_resources WHERE rowid=OLD.id;
          DELETE FROM vec_outbox WHERE resource_id=OLD.id;
          DELETE FROM legacy_vector_heads WHERE resource_id=OLD.id;
          UPDATE legacy_vector_jobs SET status='superseded',finished=EXTRACT(EPOCH FROM clock_timestamp())
            WHERE resource_id=OLD.id AND status IN ('pending','claimed');
          RETURN OLD;
        ELSIF TG_OP='INSERT' THEN
          INSERT INTO legacy_vector_generations VALUES(NEW.id,1)
            ON CONFLICT(resource_id) DO UPDATE SET generation=legacy_vector_generations.generation+1;
        ELSIF ''' + vector_changed + ''' THEN
          UPDATE legacy_vector_generations SET generation=generation+1 WHERE resource_id=NEW.id;
          DELETE FROM legacy_vector_provenance WHERE resource_id=NEW.id;
          DELETE FROM vec_resources WHERE rowid=NEW.id;
          UPDATE legacy_vector_jobs SET status='superseded',finished=EXTRACT(EPOCH FROM clock_timestamp())
            WHERE resource_id=NEW.id AND status IN ('pending','claimed');
          DELETE FROM vec_outbox WHERE resource_id=NEW.id;
        ELSE RETURN NEW; END IF;
        IF NEW.active=1 AND COALESCE(NEW.health_status,'unknown')!='retired'
            AND COALESCE(NEW.eval_security,'')!='quarantine' THEN
          INSERT INTO vec_outbox VALUES(NEW.id,EXTRACT(EPOCH FROM clock_timestamp()),'source')
            ON CONFLICT(resource_id) DO UPDATE SET enqueued_at=EXCLUDED.enqueued_at,reason=EXCLUDED.reason;
        END IF; RETURN NEW; END $$''')
    commands.append('''CREATE TRIGGER application_vector_invalidate AFTER INSERT OR UPDATE OR DELETE
        ON resources FOR EACH ROW EXECUTE FUNCTION application_vector_invalidate()''')
    commands.append('''CREATE FUNCTION application_report_creation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN IF NEW.creation_subject_key IS NULL OR NOT EXISTS(
          SELECT 1 FROM ''' + report_claims + '''
          WHERE subject_key=NEW.creation_subject_key AND report_id IS NULL) THEN
          RAISE EXCEPTION 'report_creation_reservation_required';
        END IF; RETURN NEW; END $$''')
    commands.append('''CREATE TRIGGER application_report_creation BEFORE INSERT
        ON agent_test_reports FOR EACH ROW EXECUTE FUNCTION application_report_creation()''')
    return tuple(commands)


class ApplicationStoreError(StorageError, sqlite3.DatabaseError):
    def __init__(self, code='unsupported_application_sql'):
        self.code = code
        ValueError.__init__(self, code)


WRITER_RETRY_SECONDS = 0.25


class WriterBusy(ApplicationStoreError):
    """The writer lock was not granted within lock_timeout; nothing was written.

    The code stays 'statement_failed' for every existing caller; a caller that can
    safely start the same transaction again may catch this subclass."""
    def __init__(self):
        super().__init__('statement_failed')


class _Cursor:
    def __init__(self, rows=(), rowcount=0, lastrowid=None, columns=None):
        self._rows, self._offset = tuple(rows), 0
        self.rowcount, self.lastrowid = rowcount, lastrowid
        names = columns if columns is not None else self._rows[0].keys() if self._rows else ()
        self.description = tuple((name, None, None, None, None, None, None) for name in names) if names else None

    def fetchone(self):
        rows = self.fetchmany(1)
        return rows[0] if rows else None

    def fetchmany(self, count=1):
        result = self._rows[self._offset:self._offset + count]
        self._offset += len(result)
        return list(result)

    def fetchall(self):
        return self.fetchmany(len(self._rows))

    def __iter__(self):
        return iter(self.fetchall())

    def close(self):
        self._rows = (); self._offset = 0


def _values(params):
    if not isinstance(params, (tuple, list)) or len(params) > 256:
        raise ApplicationStoreError('invalid_parameters')
    size = 0
    for value in params:
        if value is None: size += 1
        elif type(value) is bool: size += 1
        elif type(value) is int and -(2 ** 63) <= value < 2 ** 63: size += 8
        elif type(value) is float and math.isfinite(value): size += 8
        elif type(value) in (str, bytes):
            if type(value) is str and '\0' in value:
                raise ApplicationStoreError('invalid_parameters')
            size += len(value.encode() if type(value) is str else value)
        else: raise ApplicationStoreError('invalid_parameters')
    if size > MAX_BYTES: raise ApplicationStoreError('parameter_limit')
    return tuple(int(value) if type(value) is bool else value for value in params)


class _LegacyConnection:
    """Scoped DB-API view; arbitrary SQL is never translated or executed."""
    def __init__(self, store): self._store = store

    def sns_resources_by_id(self, ids):
        from .application_store_sns import resources_by_id
        return resources_by_id(self._store, ids)

    def sns_engagement(self, keys, client_id):
        from .application_store_sns import engagement
        return engagement(self._store, keys, client_id)

    @property
    def in_transaction(self): return self._store._depth > 0

    def execute(self, sql, params=()):
        try: return self._execute_registered(sql, params)
        except BaseException:
            self._poison_current()
            raise

    def _poison_current(self):
        if (self.in_transaction and
                getattr(self._store, '_owner', threading.get_ident()) == threading.get_ident()):
            self._store._failed = True

    def _execute_registered(self, sql, params=()):
        if sql == 'BEGIN IMMEDIATE' and params == ():
            # Nothing has been written when the writer lock times out, so one more try is safe.
            # 11-10 05:24: a health check lost its observation ticket to a 1 s lock_timeout.
            try: self._store._begin_direct()
            except WriterBusy:
                time.sleep(WRITER_RETRY_SECONDS)
                self._store._begin_direct()
            return _Cursor()
        if type(sql) is str and sql.startswith('PRAGMA table_info(') and sql.endswith(')') and not params:
            table = sql[len('PRAGMA table_info('):-1]
            metadata = _CATALOG.get('metadata', {}).get(table)
            if metadata is None: raise ApplicationStoreError('unsupported_application_sql')
            self._store._validate_native_table(table)
            names = ('cid', 'name', 'type', 'notnull', 'dflt_value', 'pk')
            return _Cursor(tuple(Row(names, tuple(value)) for value in metadata))
        if sql == 'PRAGMA database_list' and not params:
            return _Cursor((Row(('seq', 'name', 'file'), (0, 'main', None)),))
        item = _STATEMENTS.get(_normalized(sql)) if type(sql) is str else None
        if item is None:
            self._poison_current()
            raise ApplicationStoreError()
        if not self.in_transaction:
            with self._store.tx(readonly=item['readonly']):
                if item.get('adapter') in ('explore-fts5-v1','explore-fts5-page-v1','explore-fts5-count-v1'):
                    return self._store._legacy_fts_select(item, params)
                return self._store._execute(item['postgres'], params, generated=item['generated_id'])
        if item.get('adapter') in ('explore-fts5-v1','explore-fts5-page-v1','explore-fts5-count-v1'):
            return self._store._legacy_fts_select(item, params)
        return self._store._execute(item['postgres'], params, generated=item['generated_id'])

    def executemany(self, sql, parameters):
        count = 0
        try:
            for index, params in enumerate(parameters):
                if index >= 5000: raise ApplicationStoreError('result_limit')
                count += max(0, self.execute(sql, params).rowcount)
                if count > MAX_CORPUS_ROWS: raise ApplicationStoreError('result_limit')
        except BaseException:
            self._poison_current()
            raise
        return _Cursor(rowcount=count)

    def executescript(self, sql):
        parts = _CATALOG.get('scripts', {}).get(sql) if type(sql) is str else None
        if parts is None:
            self._poison_current()
            raise ApplicationStoreError('unregistered_schema')
        with self._store.tx():
            for statement in parts: self.execute(statement)
        return self

    def commit(self): self._store._finish_direct(True)
    def rollback(self):
        # BEGIN that failed already rolled its connection back; there is no session to end.
        # Raising session_required here hid the real error (11-10 05:24 health check crash).
        if not self._store._direct and not self._store._depth: return
        self._store._finish_direct(False)


class PostgresApplicationStore(PostgresCollectorMixin, PostgresFinanceMixin, PostgresConsumerMixin, PostgresSelectionMixin, Store):
    """Store-compatible catalog and staff/privacy repositories, explicitly scoped.

    Initialization is opt-in and accepts only a new empty caller-owned database.
    Closing detaches this Store; the caller retains connection ownership.
    """
    backend = 'postgresql'
    capabilities = frozenset(('catalog_read', 'catalog_write', 'fts5_search',
        'staff_auth', 'staff_sessions', 'customer_requests', 'test_reports',
        'workflow_definitions', 'metadata', 'health_observations', 'vector_publication', 'hybrid_search',
        'collector_scheduling', 'collector_statistics', 'credential_vault', 'virtual_credit_ledger',
        'customer_workspace_execution', 'customer_sdk_bff', 'durable_workflow_runtime',
        'service_runtime', 'payment_replay', 'persistent_writer_lifecycle', 'full_application'))
    unsupported = frozenset((
        'raw_unregistered_sql', 'implicit_worker_connection',
        'sqlite_path_only_utilities'))

    _connection_factory, _reconnect_after = None, 0.0

    def __init__(self, connection, *, initialize=False, workflow_key=None):
        if type(initialize) is not bool:
            raise ApplicationStoreError('invalid_configuration')
        try:
            if connection.autocommit is not True or int(connection.info.transaction_status) != 0:
                raise ApplicationStoreError('connection_busy')
        except (AttributeError, TypeError, ValueError):
            raise ApplicationStoreError('invalid_configuration') from None
        self._connection = connection
        if workflow_key is not None and (type(workflow_key) is not bytes or len(workflow_key) != 32):
            raise ApplicationStoreError('invalid_configuration')
        self.workflow_key = workflow_key
        self._lock = threading.RLock()
        self._depth, self._failed, self._broken, self._closed = 0, False, False, False
        self._owner, self._direct = None, False
        # Runtime sessions set a factory; operator tools holding session locks never reconnect.
        self._connection_factory, self._reconnect_after = None, 0.0
        self._path = None
        self._db = _LegacyConnection(self)
        self._vector_index = None
        self._observation_context = None
        self._observation_issuer = secrets.token_hex(16)
        self._observation_broken, self._observation_savepoint = False, 0
        self._search_db, self._search_epoch = None, None
        self._bootstrapping = initialize
        try:
            if initialize: self._initialize()
        finally: self._bootstrapping = False
        self._verify_profile()
        from .application_store_vector import PostgresVectorIndex
        self._vector_index = PostgresVectorIndex(self)
        self._native_lexical = self._lexical_available()

    def _lexical_available(self):
        from .postgres_lexical import available
        return available(self)

    def _ann_available(self):
        from .postgres_ann import available
        return available(self)

    def _schema_namespace(self):
        return 'public'

    def _writer_identity(self):
        return WRITER_LOCK

    def _writer_lock(self):
        try:
            self._native('SELECT pg_advisory_xact_lock(%s)', (self._writer_identity(),)).close()
        except ApplicationStoreError as error:
            # Only lock_timeout (or a cancel) stops this statement; the caller rolls back.
            if error.code == 'statement_failed':
                raise WriterBusy() from None
            raise

    def _connection_lost(self):
        connection = self._connection
        return bool(connection.closed or getattr(connection, 'broken', False))

    def _reconnect(self, *, starting=False):
        """Replace a lost session between transactions; work in flight is never replayed."""
        factory = self._connection_factory
        if (factory is None or self._closed or self._depth > (1 if starting else 0)
                or time.monotonic() < self._reconnect_after):
            raise ApplicationStoreError('connection_unusable')
        try: self._connection.close()
        except Exception: pass
        try:
            fresh = factory()
            if fresh.autocommit is not True or int(fresh.info.transaction_status) != 0:
                fresh.close()
                raise ValueError('connection_busy')
        except Exception:
            # A database that is still down is retried at most once per backoff interval.
            self._reconnect_after = time.monotonic() + RECONNECT_BACKOFF
            raise ApplicationStoreError('connection_unusable') from None
        self._connection, self._broken, self._failed, self._search_epoch = fresh, False, False, None
        log.warning('PostgreSQL session re-established after a lost connection')

    def _begin(self, statement, *, starting=False):
        """Open a transaction, reconnecting once if the session died before any work ran."""
        if self._connection_factory is not None and (self._broken or self._connection_lost()):
            self._reconnect(starting=starting)
        try:
            self._native(statement).close()
        except ApplicationStoreError:
            if self._connection_factory is None or not self._connection_lost(): raise
            self._reconnect(starting=starting)
            self._native(statement).close()

    def _begin_direct(self):
        if self._connection_factory is not None and not self._depth and (self._broken or self._connection_lost()):
            self._reconnect()
        if self._depth or self._closed or self._broken or int(self._connection.info.transaction_status) != 0:
            raise ApplicationStoreError('connection_busy')
        self._begin('BEGIN')
        try:
            self._transaction_controls()
            self._writer_lock()
            self._assert_deployment_gates()
            self._native('LOCK TABLE resources,resources_fts,vec_outbox IN ROW EXCLUSIVE MODE').close()
        except BaseException:
            try: self._connection.rollback()
            except BaseException: self._broken = True
            raise
        self._owner, self._depth, self._direct, self._failed = threading.get_ident(), 1, True, False
        try: self._validate_native_invariants()
        except BaseException:
            self._finish_direct(False)
            raise

    def _finish_direct(self, commit):
        if not self._direct or self._owner != threading.get_ident():
            raise ApplicationStoreError('session_required')
        try:
            if commit and self._failed:
                try: self._connection.rollback()
                except BaseException:
                    self._broken = True
                    raise ApplicationStoreError('rollback_unknown') from None
                raise ApplicationStoreError('transaction_failed')
            if commit:
                try: self._connection.commit()
                except Exception:
                    self._broken = True
                    raise ApplicationStoreError('commit_unknown') from None
            else:
                try: self._connection.rollback()
                except BaseException:
                    self._broken = True
                    raise ApplicationStoreError('rollback_unknown') from None
        finally:
            if not commit or self._failed: self._search_epoch = None
            self._owner, self._depth, self._direct = None, 0, False

    def _native(self, sql, params=()):
        cursor = self._connection.cursor(row_factory=lambda _cursor: tuple)
        try:
            cursor.execute(sql, params)
            return cursor
        except BaseException as error:
            try: cursor.close()
            except BaseException as cleanup:
                self._broken, self._failed = True, True
                if not isinstance(error, Exception): raise error
                if not isinstance(cleanup, Exception): raise
                raise ApplicationStoreError('connection_unusable') from None
            if not isinstance(error, Exception): raise
            raise ApplicationStoreError('statement_failed') from None

    def _initialize(self):
        with self.tx():
            cur = self._native("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=current_schema() AND table_type='BASE TABLE'")
            try: count = cur.fetchone()[0]
            finally: cur.close()
            if count: raise ApplicationStoreError('empty_database_required')
            for sql in _CATALOG['schema']:
                self._native(sql).close()
            for sql in _invariant_ddl(self._schema_namespace()): self._native(sql).close()
            from .admin_query_indexes import ensure_postgres
            ensure_postgres(self)
            self._db.execute('INSERT OR IGNORE INTO execution_controls VALUES (1,1,1,1,0,0)')

    def _verify_profile(self):
        try:
            with self.tx(readonly=True):
                cur = self._native('SELECT profile FROM application_store_state WHERE id=1')
                try: row = cur.fetchone()
                finally: cur.close()
                if row != (PROFILE,): raise ApplicationStoreError('schema_profile_mismatch')
                self._validate_native_schema()
                self._validate_native_invariants()
        except ApplicationStoreError: raise
        except Exception: raise ApplicationStoreError('schema_profile_mismatch') from None

    def _transaction_controls(self):
        # Transaction-local controls never mutate a caller's persistent session
        # settings or infer a database address. The profile owns public tables.
        self._native("SET LOCAL search_path TO public,pg_temp").close()
        self._native("SET LOCAL statement_timeout TO '5000ms'").close()
        self._native("SET LOCAL lock_timeout TO '1000ms'").close()
        self._native("SET LOCAL synchronous_commit TO 'on'").close()

    def _assert_deployment_gates(self):
        from .postgres_restore_guard import assert_attach_allowed, RestoreGateDenied
        from .application_store_migration import assert_attach_allowed as migration_allowed, MigrationDenied
        try: assert_attach_allowed(self)
        except RestoreGateDenied as error:
            raise ApplicationStoreError(error.code) from None
        try: migration_allowed(self)
        except MigrationDenied as error:
            raise ApplicationStoreError(error.code) from None

    def _validate_native_invariants(self):
        definitions = _invariant_ddl(self._schema_namespace())
        functions = {}
        for sql in definitions:
            match = re.match(r'CREATE FUNCTION ([a-z_]+)\(\)', sql)
            if match: functions[match[1]] = sql.split('$$')[1]
        expected = {
            'application_catalog_epoch': ('resources_fts', 28),
            'application_observation_generation': ('resources', 21),
            'application_vector_enqueue': ('vec_outbox', 21),
            'application_vector_invalidate': ('resources', 29),
            'application_report_creation': ('agent_test_reports', 7),
        }
        mode = self._execute("SELECT current_setting('session_replication_role')").fetchone()[0]
        if mode != 'origin': raise ApplicationStoreError('schema_invariants_mismatch')
        rows = self._execute('''SELECT t.tgname,c.relname,t.tgtype,t.tgenabled,p.proname,
            p.prosrc,p.prosecdef,p.provolatile,p.proconfig,l.lanname,t.tgnargs,t.tgqual IS NULL,
            t.tgattr::text,t.tgdeferrable,t.tginitdeferred,pn.nspname
            FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_proc p ON p.oid=t.tgfoid
            JOIN pg_namespace pn ON pn.oid=p.pronamespace
            JOIN pg_language l ON l.oid=p.prolang WHERE n.nspname=%s AND NOT t.tgisinternal''', (self._schema_namespace(),)).fetchall()
        actual = {row[0]: tuple(row) for row in rows}
        if set(actual) != set(expected): raise ApplicationStoreError('schema_invariants_mismatch')
        for name, (table, events) in expected.items():
            row = actual.get(name)
            if row != (name, table, events, 'O', name, functions[name], False, 'v', None, 'plpgsql', 0, True, '', False, False, self._schema_namespace()):
                raise ApplicationStoreError('schema_invariants_mismatch')

    def _expected_columns(self, table):
        result = []
        for cid, name, kind, required, default, primary in _CATALOG.get('metadata', {}).get(table, ()):
            mixed = (table in ('workspace_private_tickets', 'workspace_private_runs') and name == 'actor_user_id'
                or table in ('workspace_drafts', 'workspace_versions') and name == 'created_by')
            native = 'text' if mixed else {'INTEGER': 'bigint', 'REAL': 'double precision', 'TEXT': 'text', 'BLOB': 'bytea'}[kind.upper()]
            result.append((name, native, 'NO' if required or primary else 'YES'))
        extras = {
            'resources_fts': [('rowid', 'bigint', 'NO'), ('name', 'text', 'NO'), ('description', 'text', 'NO')],
            'vec_resources': [('rowid', 'bigint', 'NO'), ('embedding', 'bytea', 'NO')],
            'application_store_state': [('id', 'bigint', 'NO'), ('profile', 'text', 'NO'), ('catalog_epoch', 'bigint', 'NO')],
        }
        if table in _CATALOG.get('rowid_tables', ()): result.append(('_ac_rowid', 'bigint', 'NO'))
        return tuple(result or extras.get(table, ()))

    def _validate_native_table(self, table):
        if table not in _CATALOG['tables']: raise ApplicationStoreError('schema_profile_mismatch')
        owned = self._depth > 0
        if not owned:
            with self.tx(readonly=True): return self._validate_native_table(table)
        rows = self._execute('SELECT column_name,data_type,is_nullable FROM information_schema.columns '
            'WHERE table_schema=current_schema() AND table_name=%s ORDER BY ordinal_position', (table,)).fetchall()
        if tuple(tuple(row) for row in rows) != self._expected_columns(table):
            raise ApplicationStoreError('schema_profile_mismatch')

    def _validate_native_schema(self):
        rows = self._execute('SELECT table_name,column_name,data_type,is_nullable FROM information_schema.columns '
            'WHERE table_schema=current_schema() ORDER BY table_name,ordinal_position', max_rows=8192).fetchall()
        actual = {}
        for table, name, kind, nullable in rows: actual.setdefault(table, []).append((name, kind, nullable))
        for table in _CATALOG['tables']:
            if tuple(actual.get(table, ())) != self._expected_columns(table):
                raise ApplicationStoreError('schema_profile_mismatch')
        rows = self._execute('''SELECT t.relname,c.contype,
            ARRAY(SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY AS k(number,position)
                JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=k.number ORDER BY k.position),
            CASE WHEN c.contype='c' THEN pg_get_expr(c.conbin,c.conrelid) ELSE NULL END
            FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid
            JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname=current_schema()''', max_rows=4096).fetchall()
        keys, checks = {}, {}
        for table, kind, columns, expression in rows:
            if kind in ('p', 'u'): keys.setdefault(table, set()).add((kind, tuple(columns)))
            elif kind == 'c': checks.setdefault(table, set()).add(re.sub(r'[\s()"]', '', expression).lower())
        for table, item in _CATALOG.get('constraints', {}).items():
            expected = ({('p', tuple(item['primary']))} if item['primary'] else set()) | {('u', tuple(v)) for v in item['unique']}
            if keys.get(table, set()) != expected: raise ApplicationStoreError('schema_profile_mismatch')
            expected_checks = {re.sub(r'[\s()"]', '', value).lower() for value in item['checks']}
            if checks.get(table, set()) != expected_checks: raise ApplicationStoreError('schema_profile_mismatch')
        for table, primary, expression in (('resources_fts', 'rowid', None), ('vec_resources', 'rowid', 'octet_lengthembedding=3072'),
                ('application_store_state', 'id', 'id=1')):
            if keys.get(table) != {('p', (primary,))} or checks.get(table, set()) != ({expression} if expression else set()):
                raise ApplicationStoreError('schema_profile_mismatch')

    @contextmanager
    def tx(self, *, readonly=False):
        with self._lock:
            if self._closed or self._broken and (self._depth or self._connection_factory is None):
                raise ApplicationStoreError('connection_unusable')
            nested = self._depth > 0
            if nested:
                if self._owner != threading.get_ident(): raise ApplicationStoreError('thread_violation')
                self._depth += 1
                try: yield self._db
                except BaseException: self._failed = True; raise
                finally: self._depth -= 1
                return
            if self._connection_factory is not None and (self._broken or self._connection_lost()):
                self._reconnect()
            if int(self._connection.info.transaction_status) != 0:
                raise ApplicationStoreError('connection_busy')
            self._owner, self._depth, self._failed = threading.get_ident(), 1, False
            try:
                for attempt in (0, 1):
                    self._begin('BEGIN ISOLATION LEVEL REPEATABLE READ' if readonly else 'BEGIN', starting=True)
                    self._transaction_controls()
                    if readonly:
                        self._native('SET TRANSACTION READ ONLY').close()
                        break
                    try: self._writer_lock()
                    except WriterBusy:
                        # The body has not run, so one more try is safe (11-10 00:36 edge observation 503).
                        if attempt: raise
                        self._connection.rollback()
                        time.sleep(WRITER_RETRY_SECONDS)
                        continue
                    break
                if not readonly and not self._bootstrapping:
                    self._native('LOCK TABLE resources,resources_fts,vec_outbox IN ROW EXCLUSIVE MODE').close()
                self._assert_deployment_gates()
                if not self._bootstrapping: self._validate_native_invariants()
                yield self._db
                if self._failed: raise ApplicationStoreError('transaction_failed')
                try: self._connection.commit()
                except Exception:
                    self._broken = True
                    raise ApplicationStoreError('commit_unknown') from None
            except BaseException:
                self._search_epoch = None
                try: self._connection.rollback()
                except Exception:
                    self._broken, self._failed = True, True
                    raise ApplicationStoreError('connection_unusable') from None
                raise
            finally:
                self._owner, self._depth = None, 0

    def _execute(self, sql, params=(), *, generated=None, max_rows=MAX_ROWS, max_bytes=MAX_BYTES):
        if not self._depth or self._owner != threading.get_ident():
            raise ApplicationStoreError('session_required')
        cursor = None
        try:
            # Unknown text parameter OIDs let PostgreSQL infer each registered
            # target's native integer/text type. This is needed for the explicit
            # mixed staff/customer principal columns, never SQL interpolation.
            values = tuple(str(v) if type(v) is int else v for v in _values(params))
            cursor = self._native(sql, values)
            count, rows, size = cursor.rowcount, [], 0
            columns = tuple(item[0] for item in cursor.description) if cursor.description else ()
            if columns:
                while True:
                    batch = cursor.fetchmany(256)
                    if not batch: break
                    for values in batch:
                        values = tuple(int(v) if isinstance(v, Decimal) and v.is_finite() and v == v.to_integral_value()
                            else float(v) if isinstance(v, Decimal) and v.is_finite() else v for v in values)
                        size += sum(len(v.encode() if type(v) is str else v) if isinstance(v, (str, bytes)) else 8 for v in values)
                        if len(rows) >= max_rows or size > max_bytes:
                            raise ApplicationStoreError('result_limit')
                        values = tuple(int(v) if name in ('actor_user_id', 'created_by') and type(v) is str
                            and re.fullmatch(r'0|[1-9][0-9]{0,18}', v) and int(v) < 2**63 else v
                            for name, v in zip(columns, values))
                        selected = tuple((name, value) for name, value in zip(columns, values) if name != '_ac_rowid')
                        rows.append(Row(tuple(name for name, _ in selected), tuple(value for _, value in selected)))
            lastrowid = rows[0][generated] if generated and rows else None
            return _Cursor(() if generated else rows, count, lastrowid,
                tuple(name for name in columns if name != '_ac_rowid'))
        except BaseException as error:
            self._failed = True
            if isinstance(error, ApplicationStoreError) or not isinstance(error, Exception): raise
            raise ApplicationStoreError('statement_failed') from None
        finally:
            if cursor is not None:
                try: cursor.close()
                except Exception:
                    self._broken, self._failed = True, True
                    raise ApplicationStoreError('connection_unusable') from None

    def query(self, sql, params=()):
        try:
            item = _STATEMENTS.get(_normalized(sql)) if type(sql) is str else None
            if item is None or not item['readonly']: raise ApplicationStoreError()
            with self.tx(readonly=True): return self._db.execute(sql, params).fetchall()
        except BaseException:
            if self._depth and getattr(self, '_owner', threading.get_ident()) == threading.get_ident():
                self._failed = True
            raise

    def insight_price_medians(self):
        """Consumer projection: one upper median per kind, never a full price list."""
        with self.tx(readonly=True):
            return [dict(row) for row in self._execute('''SELECT kind,price_usdc FROM (
                SELECT kind,price_usdc,ROW_NUMBER() OVER(PARTITION BY kind ORDER BY price_usdc) AS position,
                COUNT(*) OVER(PARTITION BY kind) AS total FROM resources
                WHERE active=1 AND health_status!='retired' AND price_usdc>0
                ) AS ranked WHERE position=total/2+1 ORDER BY price_usdc''').fetchall()]

    def record_probe(self, rid, ok, latency_ms):
        field = 'probe_ok' if ok else 'probe_fail'
        with self.tx():
            self._execute('UPDATE resources SET ' + field + '=' + field +
                '+1,probe_latency_ms=%s,probed_at=%s WHERE id=%s', (latency_ms, time.time(), rid))

    def feedback_stats_many(self, rids):
        if not isinstance(rids, list) or len(rids) > 256:
            raise ApplicationStoreError('invalid_parameters')
        if not rids: return {}
        with self.tx(readonly=True):
            rows = self._execute('SELECT resource_id,COUNT(*) AS n,COALESCE(SUM(success),0) AS s,AVG(rating) AS r '
                'FROM feedback WHERE resource_id IN (' + ','.join(['%s'] * len(rids)) + ') GROUP BY resource_id', rids).fetchall()
        return {r['resource_id']: (r['n'], r['s'], float(r['r']) if r['r'] is not None else None) for r in rows}

    def update_workflow(self, workflow_id, data):
        if type(data) is not dict: raise ApplicationStoreError('invalid_parameters')
        allowed = ('name', 'description', 'category', 'trigger_type', 'tags', 'is_active',
            'is_template', 'author', 'author_wallet', 'parent_workflow_id', 'forks_count',
            'likes_count', 'runs_count', 'rating_avg')
        fields = {name: data[name] for name in allowed if name in data}
        if any(name in data for name in ('steps', 'nodes', 'graph_data')):
            from .gateway.store import _graph_to_steps, _steps_to_graph
            graph = data.get('graph_data')
            nodes, edges = data.get('nodes'), data.get('edges')
            if isinstance(graph, dict): nodes, edges = graph.get('nodes', nodes), graph.get('edges', edges)
            if nodes is not None:
                nodes = nodes if isinstance(nodes, list) else []
                edges = edges if isinstance(edges, list) else []
                packed = {'nodes': nodes, 'edges': edges, 'steps': _graph_to_steps(nodes, edges)}
            elif isinstance(data.get('steps'), list):
                nodes, edges = _steps_to_graph(data['steps'], data.get('trigger_type', 'manual'))
                packed = {'nodes': nodes, 'edges': edges, 'steps': data['steps']}
            else: packed = data.get('steps') if isinstance(data.get('steps'), (str, dict)) else []
            fields['steps'] = packed if type(packed) is str else json.dumps(packed)
        if not fields: return False
        fields['updated_at'] = time.time()
        with self.tx():
            return self._execute('UPDATE agent_workflows SET ' + ','.join('"' + name + '"=%s' for name in fields)
                + ' WHERE id=%s', list(fields.values()) + [workflow_id]).rowcount > 0

    @staticmethod
    def _page(limit, offset):
        if type(limit) is not int or not 1 <= limit <= 1000 or type(offset) is not int or offset < 0:
            raise ApplicationStoreError('invalid_parameters')

    def list_workflows(self, limit=50, offset=0, active_only=False, is_template=None,
                       author=None, category=None, q=None, sort_by='updated_at'):
        self._page(limit, offset)
        clauses, params = [], []
        if active_only: clauses.append('is_active=1')
        for field, value in (('is_template', is_template), ('author', author), ('category', category)):
            if value is not None and (field == 'is_template' or value and value != 'all'):
                clauses.append(field + '=%s'); params.append(int(value) if field == 'is_template' else value)
        if q:
            clauses.append('(name ILIKE %s OR description ILIKE %s OR tags ILIKE %s)')
            params.extend(['%' + q + '%'] * 3)
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        order = {'popular': 'forks_count DESC,likes_count DESC,id DESC',
            'rating': 'rating_avg DESC,forks_count DESC,id DESC', 'runs': 'runs_count DESC,id DESC',
            'created': 'created_at DESC,id DESC'}.get(sort_by, 'updated_at DESC,id DESC')
        with self.tx(readonly=True):
            total = self._execute('SELECT COUNT(*) FROM agent_workflows' + where, params).fetchone()[0]
            ids = self._execute('SELECT id FROM agent_workflows' + where + ' ORDER BY ' + order + ' LIMIT %s OFFSET %s',
                params + [limit, offset]).fetchall()
            rows = [self.get_workflow(row['id']) for row in ids]
        return rows, total

    def find_existing_test_report(self, resource_id=None, kind=None, agent_url=None):
        from .report_creation import find_existing, subject
        return find_existing(self, subject(self, resource_id, kind, agent_url))

    def list_test_reports(self, limit=50, offset=0, kind=None, category=None, grade=None,
                          q=None, is_success=None, tag=None):
        self._page(limit, offset)
        clauses, params = [], []
        for field, value in (('kind', kind), ('category', category), ('eval_grade', grade), ('is_success', is_success)):
            if value is not None and (field == 'is_success' or value):
                clauses.append(field + '=%s'); params.append(int(value) if field == 'is_success' else value)
        if tag: clauses.append('tags ILIKE %s'); params.append('%' + tag + '%')
        if q:
            clauses.append('(title ILIKE %s OR agent_name ILIKE %s OR summary ILIKE %s OR tags ILIKE %s)')
            params.extend(['%' + q.strip() + '%'] * 4)
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        columns = ('id,resource_id,title,slug,kind,source,agent_name,agent_url,category,eval_grade,eval_score,'
            'status_code,latency_ms,is_success,test_method,tool_name,summary,pros,cons,workflow_recommendation,tags,author,created_at,updated_at,'
            'executed_at,execution_finished_at,connection_version_id,evidence_scope')
        with self.tx(readonly=True):
            total = self._execute('SELECT COUNT(*) FROM agent_test_reports' + where, params).fetchone()[0]
            rows = self._execute('SELECT ' + columns + ' FROM agent_test_reports' + where +
                ' ORDER BY created_at DESC LIMIT %s OFFSET %s', params + [limit, offset]).fetchall()
        result = [dict(row) for row in rows]
        from .concierge.report_evidence import measured_report
        now = time.time()
        for row in result:
            resource = self.resource(row['resource_id']) if row.get('resource_id') is not None else None
            row['execution_measured'] = bool(resource and measured_report(row, resource, self, now))
            for field in ('pros', 'cons'):
                if row.get(field):
                    try: row[field] = json.loads(row[field])
                    except (ValueError, TypeError): pass
        return result, total

    def add_workflow_review(self, workflow_id, reviewer, rating, comment=''):
        if type(rating) is not int or not 1 <= rating <= 5: raise ValueError('Rating must be between 1 and 5.')
        with self.tx():
            result = self._execute('INSERT INTO workflow_reviews(workflow_id,reviewer,rating,comment,created_at) '
                'VALUES(%s,%s,%s,%s,%s) RETURNING id', (workflow_id, reviewer, rating, comment, time.time()), generated='id')
            average = self._execute('SELECT AVG(rating)::double precision AS n FROM workflow_reviews WHERE workflow_id=%s',
                (workflow_id,)).fetchone()['n']
            self._execute('UPDATE agent_workflows SET rating_avg=%s WHERE id=%s', (average, workflow_id))
            return result.lastrowid

    def list_workflow_reviews(self, workflow_id):
        with self.tx(readonly=True):
            return [dict(row) for row in self._execute('SELECT * FROM workflow_reviews WHERE workflow_id=%s ORDER BY created_at DESC',
                (workflow_id,)).fetchall()]

    def vec_stats(self, descriptor=None, *, read_db=None):
        if read_db is not None:
            return read_db._store.vec_stats(descriptor)
        with self.tx(readonly=True):
            if descriptor is None:
                row = self._execute('SELECT descriptor_hash FROM legacy_vector_control WHERE id=1').fetchone()
                descriptor_hash = row[0] if row else None
            else: descriptor_hash = descriptor.digest
            raw = self._execute('SELECT COUNT(*) FROM vec_resources').fetchone()[0]
            active = self._execute('SELECT COUNT(*) FROM resources WHERE active=1').fetchone()[0]
            queued = self._execute('SELECT COUNT(*) FROM vec_outbox').fetchone()[0]
            # The byte-hash check reads every stored vector (about 1 GB, 26 s on 2026-11-01),
            # so this read-only statistic alone exceeds the 5 s request limit. Callers cache it.
            self._native("SET LOCAL statement_timeout TO '120s'").close()
            # Keep correlated publication fences out of join selectivity estimates.
            # Their near-perfect correlation otherwise produces one-row estimates
            # and hundreds of thousands of random nested-loop lookups. Materialize
            # metadata first, retaining the generation, owner and byte-hash checks.
            count = self._execute('''WITH publications AS MATERIALIZED (
                SELECT p.resource_id,p.vector_hash,
                (p.generation=g.generation AND p.job_id=h.job_id AND j.status='indexed'
                 AND r.active=1 AND r.health_status!='retired'
                 AND COALESCE(r.eval_security,'')!='quarantine') AS eligible
                FROM legacy_vector_provenance p
                JOIN legacy_vector_generations g USING(resource_id) JOIN legacy_vector_heads h USING(resource_id)
                JOIN legacy_vector_jobs j ON j.job_id=p.job_id JOIN resources r ON r.id=p.resource_id
                WHERE p.descriptor_hash=%s)
                SELECT COUNT(*) FROM publications p JOIN vec_resources v ON v.rowid=p.resource_id
                WHERE p.eligible AND encode(sha256(v.embedding),'hex')=p.vector_hash''',
                (descriptor_hash,)).fetchone()[0]
        return {'vector_count': count, 'raw_vector_count': raw, 'outbox_count': queued, 'active_count': active,
                'pct': round(count / active * 100, 1) if active else 0.0}

    def _request_list(self, table, filters, search, limit, offset):
        if table not in ('customer_inquiries', 'cancellation_requests', 'privacy_requests'):
            raise ApplicationStoreError('invalid_parameters')
        if type(limit) is not int or not 1 <= limit <= 1000 or type(offset) is not int or offset < 0:
            raise ApplicationStoreError('invalid_parameters')
        allowed = {'customer_inquiries': ('inquiry_id', 'name', 'email', 'subject', 'message'),
            'cancellation_requests': ('request_id', 'token_masked', 'reason', 'source', 'ip'),
            'privacy_requests': ('request_id', 'email', 'visitor_token_masked', 'details', 'proof_hash')}[table]
        clauses, params = [], []
        for key, value in filters.items():
            if key not in ('status', 'category', 'request_type'): raise ApplicationStoreError('invalid_parameters')
            if value and value != 'all': clauses.append(key + '=%s'); params.append(value)
        if search:
            clauses.append('(' + ' OR '.join(name + ' LIKE %s' for name in allowed) + ')')
            params.extend(['%' + search.strip() + '%'] * len(allowed))
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        with self.tx(readonly=True):
            total = self._execute('SELECT COUNT(*) AS n FROM ' + table + where, params).fetchone()['n']
            rows = self._execute('SELECT * FROM ' + table + where + ' ORDER BY created_at DESC LIMIT %s OFFSET %s',
                params + [limit, offset]).fetchall()
        return [dict(row) for row in rows], total

    def list_customer_inquiries(self, status=None, category=None, search=None, limit=50, offset=0):
        return self._request_list('customer_inquiries', {'status': status, 'category': category}, search, limit, offset)

    def list_cancellation_requests(self, status=None, search=None, limit=50, offset=0):
        return self._request_list('cancellation_requests', {'status': status}, search, limit, offset)

    def list_privacy_requests(self, status=None, request_type=None, search=None, limit=50, offset=0):
        return self._request_list('privacy_requests', {'status': status, 'request_type': request_type}, search, limit, offset)

    def close(self):
        with self._lock:
            if self._depth: raise ApplicationStoreError('connection_busy')
            self._closed = True
            if self._search_db is not None: self._search_db.close(); self._search_db = None

    def require_capabilities(self, required):
        if not isinstance(required, (tuple, frozenset)) or any(x not in self.capabilities for x in required):
            raise ApplicationStoreError('unsupported_application_capability')
        if 'full_application' in required and (type(self.workflow_key) is not bytes or len(self.workflow_key) != 32):
            raise ApplicationStoreError('explicit_workflow_key_required')
        return self

    def _fts(self, match=None):
        epoch = self._execute('SELECT catalog_epoch FROM application_store_state WHERE id=1').fetchone()[0]
        cache_key = (epoch, match) if self._native_lexical else epoch
        if self._search_db is not None and self._search_epoch == cache_key: return self._search_db
        if getattr(self, '_native_lexical', False):
            if type(match) is not str or not 1 <= len(match) <= 4096 or '\0' in match:
                raise ApplicationStoreError('bounded_search_query_required')
            from .postgres_lexical import QUERY
            rows = self._execute(QUERY + """SELECT f.rowid,f.name,f.description FROM public.resources_fts f
                JOIN resources r ON r.id=f.rowid CROSS JOIN ac_query q
                WHERE agentcon_search.lexical_document(f.name,f.description) @@ q.terms
                AND r.active=1 AND r.health_status IN ('healthy','reachable')
                AND COALESCE(r.eval_security,'') NOT IN ('quarantine','review')
                ORDER BY f.rowid LIMIT %s""", (match, MAX_CORPUS_ROWS + 1),
                max_rows=MAX_CORPUS_ROWS, max_bytes=MAX_CORPUS_BYTES).fetchall()
        else:
            rows = self._execute('SELECT rowid,name,description FROM resources_fts ORDER BY rowid',
                max_rows=MAX_CORPUS_ROWS, max_bytes=MAX_CORPUS_BYTES).fetchall()
        candidate = sqlite3.connect(':memory:', check_same_thread=False)
        try:
            candidate.execute('CREATE VIRTUAL TABLE documents USING fts5(name,description)')
            candidate.execute("CREATE VIRTUAL TABLE vocabulary USING fts5vocab(documents,'row')")
            candidate.executemany('INSERT INTO documents(rowid,name,description) VALUES(?,?,?)', [tuple(row) for row in rows])
            candidate.commit()
        except BaseException:
            candidate.close(); raise
        if self._search_db is not None: self._search_db.close()
        self._search_db, self._search_epoch = candidate, cache_key
        return candidate

    def _legacy_fts_select(self, item, params):
        values = _values(params)
        if (len(values) != item['parameter_count'] or not values
                or type(values[0]) is not str or len(values[0]) > 4096):
            raise ApplicationStoreError('invalid_parameters')
        adapter = item.get('adapter')
        if adapter == 'explore-fts5-page-v1':
            if (type(params[-2]) is not int or not 0 < values[-2] <= MAX_ROWS
                    or type(params[-1]) is not int or not 0 <= values[-1] <= 10000):
                raise ApplicationStoreError('invalid_parameters')
        elif adapter == 'explore-fts5-v1':
            if type(values[-1]) is not int or not 0 < values[-1] <= MAX_ROWS:
                raise ApplicationStoreError('invalid_parameters')
        elif adapter != 'explore-fts5-count-v1':
            raise ApplicationStoreError('invalid_parameters')
        if getattr(self, '_native_lexical', False):
            return self._execute(item['postgres_lexical'], values)
        # The lexical rank comes from the same native FTS5 engine. PostgreSQL
        # applies current visibility/quality/trial weighting in one read snapshot;
        # the JSON match array is bound data, not SQL or a persistent side table.
        rows = self._fts().execute('SELECT rowid,bm25(documents) FROM documents WHERE documents MATCH ?', (values[0],))
        matches = [[row[0], row[1]] for row in rows]
        if len(matches) > MAX_CORPUS_ROWS: raise ApplicationStoreError('result_limit')
        packed = json.dumps(matches, separators=(',', ':'), allow_nan=False)
        return self._execute(item['postgres'], (packed, *values[1:]))

    def search(self, text, category, max_price, networks, kinds, limit=200,
               region=None, auth_free=False, agent_usable=False, min_grade=None, rag_engine=None):
        if (type(limit) is not int or not 1 <= limit <= 1000 or not isinstance(kinds, list)
                or not kinds or len(kinds) > 3 or any(k not in ('a2a', 'mcp', 'x402') for k in kinds)
                or not isinstance(networks, list) or len(networks) > 20):
            raise ApplicationStoreError('invalid_parameters')
        from .gateway.classify import query_terms
        terms = query_terms(text)
        conditions = ["active=1", "health_status NOT IN ('down','retired')",
            "COALESCE(eval_security,'')!='quarantine'", 'kind IN (' + ','.join(['%s'] * len(kinds)) + ')']
        params = list(kinds)
        if min_grade and min_grade.upper() in 'ABCDF':
            allowed = 'ABCDF'[:'ABCDF'.index(min_grade.upper()) + 1]
            conditions.append('(eval_grade IS NULL OR eval_grade IN (' + ','.join(['%s'] * len(allowed)) + '))')
            params.extend(allowed)
        if region:
            conditions.append('((regions IS NULL AND cap_regions IS NULL) OR regions LIKE %s OR cap_regions LIKE %s)')
            params.extend([f'%,{region},%'] * 2)
        if auth_free: conditions.append('COALESCE(auth_observed,auth_declared,0)=0')
        if agent_usable: conditions.append("(COALESCE(auth_observed,auth_declared,0)=0 OR auth_autonomy='agent_autonomous')")
        if max_price is not None:
            conditions.append('price_usdc IS NOT NULL AND price_usdc<=%s'); params.append(max_price)
        if networks:
            conditions.append("(kind!='x402' OR " + ' OR '.join(['networks LIKE %s'] * len(networks)) + ')')
            params.extend(f'%,{n},%' for n in networks)
        where = ' AND '.join(conditions)
        found = {}
        with self.tx(readonly=True):
            if terms:
                match = ' OR '.join('"' + term.replace('"', '') + '"' for term in terms)
                # Filter before LIMIT, matching the legacy FTS JOIN semantics.
                if getattr(self, '_native_lexical', False):
                    from .postgres_lexical import ids as lexical_ids
                    ids = lexical_ids(self, match, where, params, limit)
                else:
                    ids = [row[0] for row in self._fts().execute('SELECT rowid FROM documents WHERE documents MATCH ? ORDER BY bm25(documents)', (match,))]
                for start in range(0, len(ids), 128):
                    chunk = ids[start:start + 128]
                    from .application_store_resource_batches import resources as resource_batch
                    rows = resource_batch(self, chunk, where, params)
                    by_id = {row['id']: dict(row) for row in rows}
                    for rid in chunk:
                        if rid in by_id: found[rid] = by_id[rid]
                        if len(found) == limit: break
                    if len(found) == limit: break
        if rag_engine is not None and text:
            def current_filter(_db, ranked):
                ids = [item['id'] for item in ranked if item['id'] not in found]
                if not ids: return []
                from .application_store_resource_batches import resources as resource_batch
                rows = resource_batch(self, ids, where, params)
                rows_by_id = {row['id']: dict(row) for row in rows}
                return [rows_by_id[rid] for rid in ids if rid in rows_by_id]
            items = rag_engine.hybrid_search(self._db, text, limit=min(limit, 50),
                kind=kinds[0] if len(kinds) == 1 else None, _store_filter=current_filter)
            for row in items: found.setdefault(row['id'], row)
        if len(found) < limit:
            with self.tx(readonly=True):
                ids = [row[0] for row in self._execute('SELECT id FROM resources WHERE category=%s AND ' + where +
                    ' ORDER BY COALESCE(payers_30d,0) DESC LIMIT %s', [category] + params + [limit - len(found)]).fetchall()]
                from .application_store_resource_batches import resources as resource_batch
                rows = resource_batch(self, ids, where, params)
                for row in rows: found.setdefault(row['id'], dict(row))
        return list(found.values())

    def idf(self, terms):
        if not terms: return {}
        if not isinstance(terms, list) or len(terms) > 128: raise ApplicationStoreError('invalid_parameters')
        with self.tx(readonly=True):
            if getattr(self, '_native_lexical', False):
                count = self._execute('SELECT COUNT(*) FROM resources_fts').fetchone()[0] or 1
                rows = self._execute("""SELECT value AS term,(SELECT COUNT(*) FROM resources_fts f WHERE
                    agentcon_search.lexical_document(f.name,f.description) @@ plainto_tsquery('simple'::regconfig,
                        public.unaccent('public.unaccent'::regdictionary,value))) AS doc
                    FROM jsonb_array_elements_text(%s::jsonb)""", (json.dumps(terms),)).fetchall()
                return {row['term']: math.log((count + 1) / (row['doc'] + 1)) + 1 for row in rows}
            fts = self._fts()
            count = fts.execute('SELECT COUNT(*) FROM documents').fetchone()[0] or 1
            rows = fts.execute('SELECT term,doc FROM vocabulary WHERE term IN (' + ','.join(['?'] * len(terms)) + ')', terms)
            docs = dict(rows)
            return {term: math.log((count + 1) / (docs.get(term, 0) + 1)) + 1 for term in terms}

    def coverage(self):
        return {'profile': PROFILE, 'capabilities': sorted(self.capabilities),
            'unsupported': sorted(self.unsupported), 'registered_statements': len(_STATEMENTS),
            'tables': list(_CATALOG['tables']), 'full_application_ready': False,
            'full_application_source_supported': True, 'service_runtime_supported': True,
            'operating_ha_load_dr_acceptance_established': False,
            'search_engine': 'postgresql-gin-with-bounded-query-validation' if self._native_lexical else 'ephemeral-native-fts5', 'persistent_backend': 'postgresql'}


# Only reviewed Store entry points are inherited. Missing domains cannot reach
# a misleading partial implementation through an inherited SQLite helper.
_PUBLIC_METHODS = frozenset(_CATALOG['methods'])
for _name in vars(Store):
    if (not _name.startswith('_') and callable(getattr(Store, _name)) and _name not in _PUBLIC_METHODS
            and _name not in vars(PostgresApplicationStore) and getattr(PostgresApplicationStore, _name) is getattr(Store, _name)):
        def _unsupported(self, *_args, **_kwargs):
            raise ApplicationStoreError('unsupported_application_capability')
        setattr(PostgresApplicationStore, _name, _unsupported)
