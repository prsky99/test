"""Explicit bounded application transfer and cutover preparation.

Caller-owned SQLite and PostgreSQL Stores only. No address or environment is
inferred. Preparation and bounded binding remain distinct from explicit native
service activation. Activation durably retires SQLite first; fresh independent
approval can reconcile current target state back before releasing that source.
Ingress, external effects and worker drain require independent current evidence.
"""
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
import hashlib
import hmac
import json
import math
import re
import secrets
import sqlite3
import threading
import time

PROFILE = 'application-transfer-preparation-v1'
MAX_TABLE_ROWS = 200000
MAX_TOTAL_ROWS = 1000000
MAX_BYTES = 512 * 1024 * 1024
MAX_CELL_BYTES = 8 * 1024 * 1024
MAX_SECONDS = 120
_owner = ContextVar('application_transfer_owner', default=None)
_ID = re.compile(r'apm_[0-9a-f]{32}\Z')
_REF = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z')
_DDL = (
    'CREATE SCHEMA agent_migration_control',
    '''CREATE TABLE agent_migration_control.gate(id BIGINT PRIMARY KEY CHECK(id=1),
       operation_id TEXT NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    '''CREATE TABLE agent_migration_control.events(operation_id TEXT NOT NULL,revision BIGINT NOT NULL,
       payload TEXT NOT NULL,signature TEXT NOT NULL,PRIMARY KEY(operation_id,revision))''',
    'GRANT USAGE ON SCHEMA agent_migration_control TO PUBLIC',
    'GRANT SELECT ON agent_migration_control.gate TO PUBLIC',
)
_TRIGGERS = (('resources_fts', 'application_catalog_epoch'),
    ('resources', 'application_observation_generation'), ('vec_outbox', 'application_vector_enqueue'),
    ('resources', 'application_vector_invalidate'),
    ('agent_test_reports', 'application_report_creation'))


class MigrationDenied(ValueError):
    def __init__(self, code='invalid_migration_request'):
        self.code = code
        super().__init__(code)


_bulk = ContextVar('application_bulk_transfer', default=False)
_progress = ContextVar('application_transfer_progress', default=None)


@contextmanager
def bulk_catalog_transfer(*, progress=None):
    """Explicit offline transfer profile; never enabled by service settings.

    Retains ownership fences and typed verification while using streaming COPY.
    Only an owned snapshot or stopped source may be used by the operator CLI.
    """
    if progress is not None and not callable(progress):
        raise MigrationDenied('invalid_transfer_progress')
    marker = _bulk.set(True)
    progress_marker = _progress.set(progress)
    try:
        yield
    finally:
        _bulk.reset(marker)
        _progress.reset(progress_marker)


def _report_progress(table, phase, count):
    callback = _progress.get()
    if callback is not None:
        callback({'table': table, 'phase': phase, 'rows': count})


def _limit(name):
    if _bulk.get():
        return {'MAX_TABLE_ROWS': 20000000, 'MAX_TOTAL_ROWS': 40000000,
                'MAX_BYTES': 32 * 1024 ** 3, 'MAX_SECONDS': 21600}[name]
    return globals()[name]


class _RowHashes:
    """Bounded keyed multiset digest for bulk transfer, independent of row order."""
    def __init__(self):
        self.values = [] if not _bulk.get() else None
        self.count = self.total = self.squares = 0

    def append(self, value):
        if self.values is not None:
            self.values.append(value)
        else:
            # Secret keyed row hashes prevent chosen-row algebraic attacks.
            number = int.from_bytes(value, 'big')
            prime = 2 ** 521 - 1
            self.total = (self.total + number) % prime
            self.squares = (self.squares + number * number) % prime
            self.count += 1

    def digest(self):
        if self.values is not None:
            return hashlib.sha256(b''.join(sorted(self.values))).hexdigest()
        data = self.count.to_bytes(16, 'big') + self.total.to_bytes(66, 'big') + self.squares.to_bytes(66, 'big')
        return hashlib.sha256(b'keyed-multiset-v2:' + data).hexdigest()


@contextmanager
def _bulk_writer(target, table, fields):
    # Both identifiers come only from the checked-in schema, never request input.
    if table not in _columns() or fields != _columns()[table]:
        raise MigrationDenied('unknown_source_schema')
    sql = 'COPY public."' + table + '" (' + ','.join('"' + col + '"' for col, _ in fields) + ') FROM STDIN'
    with target._connection.cursor() as cursor:
        cursor.execute("SET LOCAL statement_timeout TO '21600s'")
        with cursor.copy(sql) as writer:
            yield writer.write_row
        cursor.execute("SET LOCAL statement_timeout TO '5000ms'")


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def _key(store):
    value = getattr(store, 'workflow_key', None)
    if type(value) is not bytes or len(value) != 32: raise MigrationDenied('explicit_workflow_key_required')
    return hmac.new(value, PROFILE.encode(), hashlib.sha256).digest()


def _tag(key, value): return hmac.new(key, _json(value).encode(), hashlib.sha256).hexdigest()


def _sql(connection, sql, params=()):
    with connection.cursor(row_factory=lambda _: tuple) as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall() if cursor.description else ()


def _anchor(store):
    rows = _sql(store._connection, """SELECT c.system_identifier::text,d.oid::text,d.datname
        FROM pg_catalog.pg_control_system() c CROSS JOIN pg_catalog.pg_database d
        WHERE d.datname=pg_catalog.current_database()""")
    if len(rows) != 1: raise MigrationDenied('target_identity_unavailable')
    return _tag(_key(store), {'system':rows[0][0],'database_oid':rows[0][1],'database_name':rows[0][2]})


def _load(store):
    connection = store._connection
    if _sql(connection, "SELECT pg_catalog.to_regnamespace('agent_migration_control') IS NOT NULL") == [(False,)]: return None
    if _sql(connection, "SELECT pg_catalog.to_regclass('agent_migration_control.gate') IS NOT NULL") != [(True,)]:
        raise MigrationDenied('migration_target_quarantined')
    rows = _sql(connection, 'SELECT operation_id,payload,signature FROM agent_migration_control.gate WHERE id=1')
    if len(rows) != 1: raise MigrationDenied('migration_target_quarantined')
    operation, raw, signature = rows[0]
    try:
        if type(raw) is not str or len(raw.encode()) > 256 * 1024: raise ValueError()
        def exact(pairs):
            result = {}
            for name, value in pairs:
                if name in result: raise ValueError()
                result[name] = value
            return result
        value = json.loads(raw, object_pairs_hook=exact, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if (type(value) is not dict or value.get('profile') != PROFILE or value.get('operation_id') != operation
                or type(signature) is not str or not hmac.compare_digest(_tag(_key(store), value), signature)
                or value.get('target_anchor') != _anchor(store)):
            raise ValueError()
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise MigrationDenied('migration_target_quarantined') from None


def _owns(store):
    from .application_store_postgres import WRITER_LOCK
    return _sql(store._connection, '''SELECT COUNT(*) FROM pg_catalog.pg_locks WHERE pid=pg_catalog.pg_backend_pid()
        AND locktype='advisory' AND granted AND mode='ExclusiveLock' AND classid=%s AND objid=%s AND objsubid=1''',
        (WRITER_LOCK >> 32, WRITER_LOCK & 0xffffffff)) == [(1,)]


def assert_attach_allowed(store):
    """A transferred target has no automatic activation path in this profile."""
    connection = store._connection
    try:
        value = _load(store)
        if value is None: return
        if value['state'] == 'service_active':
            return
        owner = _owner.get()
        if (owner and owner['connection'] is connection and owner['thread'] == threading.get_ident()
                and owner['operation_id'] == value['operation_id'] and owner['expires'] > time.monotonic()
                and _owns(store)):
            return
        raise MigrationDenied('migration_target_quarantined')
    except MigrationDenied: raise
    except Exception: raise MigrationDenied('migration_target_quarantined') from None


def _stores(source, target, source_workflow_key):
    from .gateway.store import Store
    from .application_store_postgres import PostgresApplicationStore
    if (type(source) is not Store or type(source._db) is not sqlite3.Connection
            or type(target) is not PostgresApplicationStore or source._db.in_transaction
            or target._depth or target._closed or target._broken
            or target._connection.autocommit is not True or int(target._connection.info.transaction_status) != 0):
        raise MigrationDenied('idle_owned_stores_required')
    if type(source_workflow_key) is not bytes or len(source_workflow_key) != 32:
        raise MigrationDenied('explicit_workflow_key_required')
    _key(target)
    if not hmac.compare_digest(source_workflow_key, target.workflow_key):
        raise MigrationDenied('workflow_key_custody_mismatch')
    return _key(target)


@contextmanager
def _fence(source, target, operation_id, source_workflow_key, *, commit_source_after_target=False):
    from .application_store_postgres import WRITER_LOCK
    key = _stores(source, target, source_workflow_key)
    if type(operation_id) is not str or not _ID.fullmatch(operation_id): raise MigrationDenied()
    started = time.monotonic()
    with source._lock, target._lock:
        previous = source._db.execute('PRAGMA busy_timeout').fetchone()[0]
        previous_sync = source._db.execute('PRAGMA synchronous').fetchone()[0]
        previous_fullsync = source._db.execute('PRAGMA fullfsync').fetchone()[0]
        locked = False
        marker = None
        try:
            source._db.execute('PRAGMA busy_timeout=1000')
            # Source retirement must survive a power loss before PostgreSQL
            # accepts writes. NORMAL WAL durability is insufficient for this
            # cross-database ownership boundary; restore settings after exit.
            source._db.execute('PRAGMA synchronous=FULL')
            source._db.execute('PRAGMA fullfsync=ON')
            # SQLite's writer reservation excludes every writer connection, not
            # merely callers which know this module's protocol.
            source._db.execute('BEGIN IMMEDIATE')
            try: acquired = _sql(target._connection, 'SELECT pg_catalog.pg_try_advisory_lock(%s)', (WRITER_LOCK,))
            except BaseException:
                target._broken = True
                raise MigrationDenied('target_ownership_unknown') from None
            if acquired != [(True,)]: raise MigrationDenied('target_writer_ownership_conflict')
            locked = True
            marker = _owner.set({'connection': target._connection, 'operation_id': operation_id,
                'thread': threading.get_ident(), 'expires': started + _limit('MAX_SECONDS')})
            with target.tx():
                from .application_store_postgres import _CATALOG
                # Bound identifiers derive only from the checked-in native
                # schema. ACCESS EXCLUSIVE also excludes direct SQL writers.
                target._execute('LOCK TABLE ' + ','.join('public."' + name + '"' for name in _CATALOG['tables']) + ' IN ACCESS EXCLUSIVE MODE')
                target._validate_native_schema()
                yield key, started
                if time.monotonic() - started > _limit('MAX_SECONDS'): raise MigrationDenied('migration_time_limit')
            # Rollback activates the fully reconciled source only after the
            # target stop receipt is known committed. Unknown commits leave the
            # source's previously committed retirement gate in place.
            if commit_source_after_target:
                source._db.commit()
        finally:
            if marker is not None: _owner.reset(marker)
            try:
                if source._db.in_transaction: source._db.rollback()
            finally:
                source._db.execute('PRAGMA busy_timeout=' + str(int(previous)))
                source._db.execute('PRAGMA synchronous=' + str(int(previous_sync)))
                source._db.execute('PRAGMA fullfsync=' + str(int(previous_fullsync)))
                if locked:
                    try:
                        if _sql(target._connection, 'SELECT pg_catalog.pg_advisory_unlock(%s)', (WRITER_LOCK,)) != [(True,)]:
                            target._broken = True
                            raise MigrationDenied('target_ownership_unknown')
                    except BaseException:
                        target._broken = True
                        raise


def _columns():
    from .application_store_postgres import _CATALOG
    result = {table: [(row[1], row[2].upper()) for row in metadata] for table, metadata in _CATALOG['metadata'].items()}
    result['resources_fts'] = [('rowid', 'INTEGER'), ('name', 'TEXT'), ('description', 'TEXT')]
    result['vec_resources'] = [('rowid', 'INTEGER'), ('embedding', 'BLOB')]
    for table, column in (('workspace_private_tickets','actor_user_id'), ('workspace_private_runs','actor_user_id'),
            ('workspace_drafts','created_by'), ('workspace_versions','created_by')):
        result[table] = [(col, 'TEXT' if col == column else kind) for col, kind in result[table]]
    for table in _CATALOG['rowid_tables']: result[table].append(('_ac_rowid', 'INTEGER'))
    return result


def _source_tables(db):
    from .application_store_postgres import _CATALOG
    rows = db.execute("SELECT name,type FROM main.sqlite_schema WHERE type IN ('table','view') ORDER BY name LIMIT 1025").fetchall()
    if len(rows) > 1024: raise MigrationDenied('migration_schema_limit')
    ignored = {'application_source_writer_fence', 'sqlite_sequence', 'resources_vocab', 'resources_fts_data', 'resources_fts_idx',
        'resources_fts_content', 'resources_fts_docsize', 'resources_fts_config', 'vec_resources_info',
        'vec_resources_chunks', 'vec_resources_rowids', 'vec_resources_vector_chunks00'}
    names = {row[0] for row in rows if row[0] not in ignored and not row[0].startswith('sqlite_')}
    known = set(_columns())
    if names - known: raise MigrationDenied('unknown_source_schema')
    if db.execute("SELECT 1 FROM temp.sqlite_schema WHERE type IN ('table','view') LIMIT 1").fetchone():
        raise MigrationDenied('temporary_source_schema')
    for name, kind in rows:
        if name not in known: continue
        if kind != 'table': raise MigrationDenied('source_schema_mismatch')
        actual = list(db.execute('PRAGMA table_info("' + name + '")'))
        if name in ('resources_fts', 'vec_resources'):
            expected = [(col, kind) for col, kind in _columns()[name] if col != '_ac_rowid']
            # Virtual FTS excludes its implicit rowid from table_info().
            if name == 'resources_fts': expected = expected[1:]
            if [(r[1], r[2].upper()) for r in actual] != [(col, '') for col, _ in expected]: raise MigrationDenied('source_schema_mismatch')
        else:
            expected = _CATALOG['metadata'][name]
            actual_columns = {r[1]: (r[2].upper(), r[3], r[5]) for r in actual}
            expected_columns = {r[1]: (r[2].upper(), r[3], r[5]) for r in expected}
            # Historical ALTER used nullable TEXT; native copy still rejects NULL.
            if name == 'agent_visitors' and actual_columns.get('nurture_stage') == ('TEXT', 0, 0):
                actual_columns['nurture_stage'] = ('TEXT', 1, 0)
            if actual_columns != expected_columns:
                raise MigrationDenied('source_schema_mismatch')
    if 'resources' not in names or 'resources_fts' not in names: raise MigrationDenied('source_schema_incomplete')
    return names


def _cell(value, kind, table, column):
    if value is None: return None
    if kind == 'INTEGER':
        if type(value) is not int or not -(2 ** 63) <= value < 2 ** 63: raise MigrationDenied('unsupported_source_affinity')
        return value
    if kind == 'REAL':
        if table == 'agent_test_reports' and column in ('created_at','updated_at') and type(value) is str:
            from .report_time import report_timestamp
            try: return report_timestamp(value, legacy_utc=True)
            except ValueError: raise MigrationDenied('unsupported_source_affinity') from None
        if type(value) not in (int, float) or not math.isfinite(value): raise MigrationDenied('unsupported_source_affinity')
        return float(value)
    if kind == 'TEXT':
        # Provider descriptions are plain text; NUL has no representable PG text value.
        if table in ('resources','resources_fts') and column in ('name','description') and type(value) is str:
            value = value.replace('\0','')
        mixed = table in ('workspace_private_tickets', 'workspace_private_runs') and column == 'actor_user_id' or table in ('workspace_drafts', 'workspace_versions') and column == 'created_by'
        if mixed and type(value) is int: value = str(value)
        if type(value) is not str or '\0' in value: raise MigrationDenied('unsupported_source_affinity')
        try: size = len(value.encode())
        except UnicodeError: raise MigrationDenied('unsupported_source_affinity') from None
        if size > MAX_CELL_BYTES: raise MigrationDenied('migration_byte_limit')
        return value
    if kind == 'BLOB':
        if type(value) not in (bytes, memoryview): raise MigrationDenied('unsupported_source_affinity')
        value = bytes(value)
        if len(value) > MAX_CELL_BYTES: raise MigrationDenied('migration_byte_limit')
        return value
    raise MigrationDenied('unsupported_source_affinity')


def _canonical(row):
    return [{'blob_length': len(v), 'blob_sha256': hashlib.sha256(v).hexdigest()} if type(v) is bytes else v for v in row]


def _rows(source, table, columns, *, native=False):
    identifiers = ','.join(('rowid' if col == '_ac_rowid' and not native else '"' + col + '"') for col, _ in columns)
    sql = 'SELECT ' + identifiers + ' FROM ' + ('public.' if native else 'main.') + '"' + table + '"'
    if native and _bulk.get():
        cursor = source._connection.cursor(name='ac_transfer_' + secrets.token_hex(8))
        cursor.execute(sql)
    else:
        cursor = source._native(sql) if native else source._db.execute(sql)
    try:
        while True:
            batch = cursor.fetchmany(128 if _bulk.get() else 8)
            if not batch: break
            for row in batch:
                value = tuple(_cell(v, kind, table, col) for v, (col, kind) in zip(row, columns))
                if sum(len(v.encode() if type(v) is str else v) if isinstance(v, (str, bytes)) else 8 for v in value) > MAX_CELL_BYTES:
                    raise MigrationDenied('migration_byte_limit')
                yield value
    finally: cursor.close()


@contextmanager
def _managed_rows(source, table, columns, *, native=False):
    rows = _rows(source, table, columns, native=native)
    try:
        yield rows
    finally:
        # A consumer can fail while a yielded row is being copied or checked.
        # Close before the owning database/transaction leaves its scope.
        rows.close()


def _receipt(store, value, *, first=False):
    signature = _tag(_key(store), value)
    raw = _json(value)
    if first:
        for sql in _DDL: store._execute(sql)
        store._execute('INSERT INTO agent_migration_control.gate VALUES(1,%s,%s,%s)', (value['operation_id'], raw, signature))
    else:
        updated = store._execute('UPDATE agent_migration_control.gate SET payload=%s,signature=%s WHERE id=1 AND operation_id=%s',
            (raw, signature, value['operation_id']))
        if updated.rowcount != 1: raise MigrationDenied('migration_revision_conflict')
    store._execute('INSERT INTO agent_migration_control.events VALUES(%s,%s,%s,%s)',
        (value['operation_id'], value['revision'], raw, signature))
    return {'receipt': value, 'signature': signature}


def _measure(source, target, names, key, *, copy=False, source_vault=None, started=None):
    columns = _columns()
    total, size, actual_size, target_size, tables = 0, 0, 0, 0, []
    target_vault = target._vault() if 'platform_credentials' in names else None
    for table, fields in sorted(columns.items()):
        hashes, count = _RowHashes(), 0
        with (_bulk_writer(target, table, fields) if copy and _bulk.get() else nullcontext(None)) as write_row, \
             (_managed_rows(source, table, fields) if table in names else nullcontext(())) as iterable:
            for row in iterable:
                total += 1; count += 1
                if count % 100000 == 0: _report_progress(table, 'copy' if copy else 'source-verify', count)
                if count > _limit('MAX_TABLE_ROWS') or total > _limit('MAX_TOTAL_ROWS'): raise MigrationDenied('migration_row_limit')
                normalized = list(row)
                transferred = list(row)
                if table == 'platform_credentials':
                    from .credential_vault import CredentialVault
                    if type(source_vault) is not CredentialVault: raise MigrationDenied('source_vault_required')
                    index = next(i for i, item in enumerate(fields) if item[0] == 'key_value')
                    name_index = next(i for i, item in enumerate(fields) if item[0] == 'key_name')
                    try: plaintext = source_vault.open(row[name_index], row[index])
                    except (ValueError, TypeError, UnicodeError): raise MigrationDenied('invalid_source_credential') from None
                    if not plaintext: raise MigrationDenied('invalid_source_credential')
                    normalized[index] = _tag(key, {'credential': plaintext})
                    transferred[index] = target_vault.seal(row[name_index], plaintext)
                actual_size += sum(len(v.encode() if type(v) is str else v) if isinstance(v,(str,bytes)) else 8 for v in row)
                if actual_size > _limit('MAX_BYTES'): raise MigrationDenied('migration_byte_limit')
                encoded = _json(_canonical(normalized)).encode()
                size += len(encoded)
                if size > _limit('MAX_BYTES'): raise MigrationDenied('migration_byte_limit')
                hashes.append(hmac.new(key, encoded, hashlib.sha256).digest())
                if write_row is not None:
                    write_row(tuple(transferred))
                elif copy:
                    params = tuple(str(v) if type(v) is int else v for v in transferred)
                    target._execute('INSERT INTO public."' + table + '" (' + ','.join('"' + col + '"' for col, _ in fields)
                        + ') OVERRIDING SYSTEM VALUE VALUES(' + ','.join('%s' for _ in fields) + ')', params)
                if started is not None and time.monotonic() - started > _limit('MAX_SECONDS'): raise MigrationDenied('migration_time_limit')
        _report_progress(table, 'source-complete', count)
        source_hash = hashes.digest()
        hashes, native_count = _RowHashes(), 0
        native_bytes = 0
        with _managed_rows(target, table, fields, native=True) as native_rows:
            for row in native_rows:
                if started is not None and time.monotonic() - started > _limit('MAX_SECONDS'): raise MigrationDenied('migration_time_limit')
                native_count += 1
                if native_count % 100000 == 0: _report_progress(table, 'target-verify', native_count)
                target_size += sum(len(v.encode() if type(v) is str else v) if isinstance(v,(str,bytes)) else 8 for v in row)
                if target_size > _limit('MAX_BYTES'): raise MigrationDenied('migration_byte_limit')
                if native_count > _limit('MAX_TABLE_ROWS'): raise MigrationDenied('migration_row_limit')
                normalized = list(row)
                if table == 'platform_credentials':
                    index = next(i for i, item in enumerate(fields) if item[0] == 'key_value')
                    name_index = next(i for i, item in enumerate(fields) if item[0] == 'key_name')
                    try: plaintext = target_vault.open(row[name_index], row[index])
                    except (ValueError, TypeError, UnicodeError): raise MigrationDenied('invalid_target_credential') from None
                    if not plaintext: raise MigrationDenied('invalid_target_credential')
                    normalized[index] = _tag(key, {'credential': plaintext})
                encoded = _json(_canonical(normalized)).encode()
                native_bytes += len(encoded)
                if native_bytes > _limit('MAX_BYTES'): raise MigrationDenied('migration_byte_limit')
                hashes.append(hmac.new(key, encoded, hashlib.sha256).digest())
        _report_progress(table, 'target-complete', native_count)
        native_hash = hashes.digest()
        tables.append({'table': table, 'rows': count, 'digest': source_hash,
            'target_rows': native_count, 'match': count == native_count and source_hash == native_hash})
    return {**({'digest_profile': 'keyed-multiset-v2'} if _bulk.get() else {}), 'tables': tables, 'rows': total, 'semantic_bytes': size, 'transfer_bytes': actual_size,
        'equal': all(item['match'] for item in tables), 'schema_absent_empty': sorted(set(columns) - names)}


def _fresh(target):
    from .application_store_postgres import _CATALOG
    if _load(target) is not None: raise MigrationDenied('target_already_claimed')
    actual = target._execute("""SELECT c.relname,c.relkind::text FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'
        AND c.relkind IN ('r','p','v','m','f')""", max_rows=512).fetchall()
    if {(row[0],row[1]) for row in actual} != {(name,'r') for name in _CATALOG['tables']}:
        raise MigrationDenied('target_schema_not_owned')
    for table in _CATALOG['tables']:
        rows = target._execute('SELECT COUNT(*) FROM public."' + table + '"').fetchone()[0]
        if table == 'application_store_state':
            if rows != 1: raise MigrationDenied('target_not_empty')
        elif table == 'execution_controls':
            if rows != 1 or tuple(target._execute('SELECT * FROM execution_controls').fetchone()) != (1, 1, 1, 1, 0, 0):
                raise MigrationDenied('target_not_empty')
        elif table == 'legacy_vector_control':
            from .legacy_vector_index import PROFILE as VECTOR_PROFILE
            if rows != 1 or tuple(target._execute('SELECT * FROM legacy_vector_control').fetchone()) != (1, VECTOR_PROFILE, None, None):
                raise MigrationDenied('target_not_empty')
        elif rows: raise MigrationDenied('target_not_empty')


def _sequences(source, target, names):
    from .application_store_postgres import _CATALOG
    sequence_rows = source._db.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name='sqlite_sequence'").fetchone()
    source_sequences = dict(source._db.execute('SELECT name,seq FROM sqlite_sequence')) if sequence_rows else {}
    for table, fields in _columns().items():
        for column, kind in fields:
            if kind != 'INTEGER': continue
            sequence = target._execute('SELECT pg_get_serial_sequence(%s,%s)', ('public."' + table + '"', column)).fetchone()[0]
            if not sequence: continue
            maximum = target._execute('SELECT MAX("' + column + '") FROM public."' + table + '"').fetchone()[0] or 0
            if column != '_ac_rowid':
                high_water = source_sequences.get(table, 0)
                if type(high_water) is not int or high_water < 0: raise MigrationDenied('identity_sequence_mismatch')
                maximum = max(maximum, high_water)
            if type(maximum) is not int or maximum < 0 or maximum >= 2 ** 63 - 1: raise MigrationDenied('identity_sequence_exhausted')
            if not re.fullmatch(r'public\.[a-z_][a-z0-9_]*', sequence): raise MigrationDenied('identity_sequence_mismatch')
            # Unlike setval(), RESTART participates in this copy transaction.
            target._execute('ALTER SEQUENCE ' + sequence + ' RESTART WITH ' + str(maximum + 1))


def copy_application(source, target, *, operation_id, source_workflow_key, source_vault=None):
    """Transfer all present known tables atomically into a fresh quarantined target.

    Missing optional source tables represent empty tables and are explicitly
    listed. Unknown/changed tables, limits, key mismatch and nonempty targets
    abort without changing the source or committing target application rows.
    """
    with _fence(source, target, operation_id, source_workflow_key) as (key, started):
        _fresh(target)
        names = _source_tables(source._db)
        target._execute('DELETE FROM execution_controls')
        target._execute('DELETE FROM legacy_vector_control')
        for table, trigger in _TRIGGERS:
            target._execute('ALTER TABLE public."' + table + '" DISABLE TRIGGER "' + trigger + '"')
        summary = _measure(source, target, names, key, copy=True, source_vault=source_vault, started=started)
        if not summary['equal']: raise MigrationDenied('application_reconciliation_failed')
        for table, trigger in _TRIGGERS:
            target._execute('ALTER TABLE public."' + table + '" ENABLE TRIGGER "' + trigger + '"')
        _sequences(source, target, names)
        target._validate_native_invariants()
        summary['identities'] = _identity_inventory(source, target, names)
        value = {'profile': PROFILE, 'operation_id': operation_id, 'revision': 1, 'state': 'staged',
            'created': time.time(), 'schema_profile': _CATALOG_HASH(), 'target_anchor': _anchor(target), 'summary': summary,
            'cutover_authorized': False, 'source_mutated': False, 'operating_enabled': False,
            'source_writer_fence': 'sqlite-begin-immediate-held', 'target_writer_fence': 'native-table-and-session-held',
            'external_dispatch_excluded': False, 'workflow_key_custody': 'explicit-equal-key',
            'credential_transfer': 'explicit-decrypt-and-reseal', 'full_application_ready': False}
        return _receipt(target, value, first=True)


def _CATALOG_HASH():
    from .application_store_postgres import _CATALOG
    return hashlib.sha256(_json(_CATALOG).encode()).hexdigest()


def reconcile_application(source, target, *, operation_id, source_workflow_key, source_vault=None):
    with _fence(source, target, operation_id, source_workflow_key) as (key, started):
        value = _load(target)
        if not value or value['operation_id'] != operation_id or value['schema_profile'] != _CATALOG_HASH():
            raise MigrationDenied('migration_receipt_mismatch')
        summary = _measure(source, target, _source_tables(source._db), key, source_vault=source_vault, started=started)
        summary['identities'] = _identity_inventory(source, target, _source_tables(source._db))
        summary['equal'] = summary['equal'] and all(item['match'] for item in summary['identities'])
        return {'profile': PROFILE, 'operation_id': operation_id, 'summary': summary,
            'matches_staged_baseline': summary == value['summary'], 'cutover_authorized': False,
            'operating_enabled': False, 'full_application_ready': False}



def _challenge(value, phase, history_policy=None):
    if phase not in ('cutover', 'rollback', 'binding', 'activation', 'rollback_activation'): raise MigrationDenied()
    result = {'profile': PROFILE, 'operation_id': value['operation_id'], 'revision': value['revision'],
        'phase': phase, 'baseline': hashlib.sha256(_json(value['summary']).encode()).hexdigest(),
        'schema_profile': value['schema_profile'], 'target_anchor':value['target_anchor']}
    policy = history_policy if history_policy is not None else value.get('history_policy')
    if policy is not None:
        from .migration_terminal_custody import PROFILE as CUSTODY_PROFILE
        if policy != CUSTODY_PROFILE: raise MigrationDenied('invalid_history_custody_policy')
        result['history_policy'] = policy
    return result


class PreparationAuthority:
    """Independent owner proof boundary, with no built-in approval or activation."""
    def __init__(self, key, *, verifier):
        if type(key) is not bytes or len(key) != 32 or not callable(verifier): raise MigrationDenied()
        self.key, self.verifier = key, verifier

    def issue(self, challenge, proof):
        # The verifier must resolve proof against current independent records.
        # It does not receive stored rows, keys, tokens or database addresses.
        verified = self.verifier(dict(challenge), proof)
        fields = ('owner_ref', 'ingress_stop_ref', 'workers_stop_ref', 'external_reconciliation_ref',
            'compatibility_ref', 'rollback_point_ref')
        if (type(verified) is not dict or set(verified) != set(fields)
                or any(type(verified[name]) is not str or not _REF.fullmatch(verified[name]) for name in fields)):
            raise MigrationDenied('independent_current_owner_proof_required')
        now = time.time()
        payload = {'profile': PROFILE, 'challenge': dict(challenge),
            'evidence': {name: hashlib.sha256(verified[name].encode()).hexdigest() for name in fields},
            'issued': now, 'expires': now + 300, 'nonce': secrets.token_hex(16)}
        return {'payload': payload, 'signature': _tag(self.key, payload)}

    def verify(self, approval, challenge, proof=None):
        try:
            if type(approval) is not dict or set(approval) != {'payload', 'signature'}: raise ValueError()
            value, signature = approval['payload'], approval['signature']
            if (value.get('profile') != PROFILE or value.get('challenge') != challenge
                    or type(value.get('issued')) not in (int, float) or type(value.get('expires')) not in (int, float)
                    or not value['issued'] <= time.time() < value['expires'] <= value['issued'] + 300
                    or not hmac.compare_digest(_tag(self.key, value), signature)):
                raise ValueError()
            started = time.monotonic()
            current = self.issue(challenge, proof)['payload']['evidence']
            if (current != value.get('evidence') or not value['issued'] <= time.time() < value['expires']
                    or time.monotonic() - started > 5): raise ValueError()
            return value
        except (ValueError, TypeError, AttributeError, UnicodeError):
            raise MigrationDenied('independent_current_owner_proof_required') from None


def preparation_challenge(target, *, operation_id, phase, history_policy=None):
    if type(operation_id) is not str or not _ID.fullmatch(operation_id): raise MigrationDenied()
    with target._lock:
        if target._depth or int(target._connection.info.transaction_status) != 0: raise MigrationDenied('idle_owned_stores_required')
        value = _load(target)
        if not value or value['operation_id'] != operation_id: raise MigrationDenied('migration_receipt_mismatch')
        return _challenge(value, phase, history_policy)


def _transition_quiescent(target, history_policy=None):
    if history_policy is None:
        return _quiescent(target)
    from .migration_terminal_custody import quiescent
    return quiescent(target, history_policy)


def _quiescent(target):
    # Unknown external effects are preserved by copy and block preparation.
    # No retry, refund, dispatch, cancellation or permission rewrite occurs.
    checks = (
        "SELECT COUNT(*) FROM workflow_runs WHERE status IN ('queued','running') OR execution_outcome='unknown'",
        "SELECT COUNT(*) FROM workflow_result_outbox WHERE status IN ('pending','claimed','dispatched','unknown')",
        "SELECT COUNT(*) FROM workspace_private_runs WHERE status IN ('prepared','dispatched','unknown')",
        "SELECT COUNT(*) FROM workspace_typed_flow_runs WHERE status IN ('running','unknown')",
        "SELECT COUNT(*) FROM workflow_execution_attempts WHERE status IN ('prepared','dispatched','unknown')",
        "SELECT COUNT(*) FROM workspace_meter_operations WHERE status='admitted'",
        "SELECT COUNT(*) FROM agent_task_events WHERE status IN ('pending','ready','sending')",
        "SELECT COUNT(*) FROM clearing_ledger WHERE status='held'",
    )
    return (all(target._execute(sql).fetchone()[0] == 0 for sql in checks)
        and _signed_effects_quiescent(target))


def _signed_effects_quiescent(target):
    """Validate every signed effect row, including terminal SQL locators.

    Filtering only on an unsigned state column could conceal an in-flight or
    uncertain effect. A bad signature, changed locator, unknown state or bounded
    inspection limit therefore blocks handoff without rewriting any history.
    """
    from .private_artifact_keys import ArtifactSigner
    from .workspace_access import PROFILE as ACCESS_PROFILE, _tree
    runtime_key = hmac.new(target.workflow_key, b'workflow-results-v1', hashlib.sha256).digest()
    access_key = hmac.new(runtime_key, ACCESS_PROFILE.encode('ascii'), hashlib.sha256).digest()
    domains = (
        ('private-a2a03-task-poll-v1', 'SELECT * FROM public.workspace_remote_tasks',
            ('id','workspace_id','logical_id','expires'), 'status',
            frozenset(('completed','canceled','failed','rejected'))),
        ('bounded-continuous-evaluation-v1', 'SELECT * FROM public.reliability_eval_jobs',
            ('id','workspace_id','logical_key','state','host_key','window_start','expires'), 'state',
            frozenset(('completed','failed','expired'))),
        ('workspace-machine-evidence-updates-v1', 'SELECT * FROM public.workspace_machine_update_events',
            ('id','workspace_id','subscription_id','dedupe_hash','state','created'), 'state',
            frozenset(('accepted','superseded'))),
        ('stripe-connect-test-usd-gross-v1', 'SELECT * FROM public.stripe_sandbox_commands',
            ('id','workspace_id','order_id'), None, frozenset(('accepted','failed'))),
    )
    count, size, started = 0, 0, time.monotonic()
    for profile, statement, locators, state_column, terminal in domains:
        signer = ArtifactSigner(hmac.new(access_key,profile.encode('ascii'),hashlib.sha256).digest(),profile)
        cursor = target._native(statement)
        try:
            names = tuple(item[0] for item in cursor.description)
            while True:
                batch = cursor.fetchmany(128 if _bulk.get() else 8)
                if not batch:
                    break
                for fields in batch:
                    count += 1
                    if count > MAX_TABLE_ROWS or time.monotonic()-started > MAX_SECONDS:
                        return False
                    row = dict(zip(names,fields))
                    raw = row.get('payload')
                    if type(raw) is not str or len(raw.encode()) > MAX_CELL_BYTES:
                        return False
                    size += len(raw.encode())
                    if size > MAX_BYTES:
                        return False
                    try:
                        value = json.loads(raw, object_pairs_hook=_unique_object,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                        _tree(value)
                        if (type(value) is not dict or not signer.verify(value,row.get('signature'))
                                or any(value.get(name)!=row[name] for name in locators)
                                or state_column is not None and value.get('state')!=row[state_column]
                                or value.get('state') not in terminal):
                            return False
                    except (ValueError,TypeError,KeyError,UnicodeError,RecursionError):
                        return False
        finally:
            cursor.close()
    return True


def _unique_object(pairs):
    value = {}
    for name, item in pairs:
        if name in value:
            raise ValueError()
        value[name] = item
    return value


def prepare_transition(source, target, *, operation_id, source_workflow_key, phase, authority, approval, source_vault=None, proof=None,
                       history_policy=None):
    """Commit an independently approved preparation receipt; never change service.

    Rollback preparation requires equality to the original baseline. Any target
    divergence therefore needs a new external reconciliation, not a blind copy
    back or resurrection of stale authorization from the source.
    """
    if phase not in ('cutover', 'rollback') or type(authority) is not PreparationAuthority: raise MigrationDenied()
    if hmac.compare_digest(authority.key, getattr(target, 'workflow_key', b'')):
        raise MigrationDenied('independent_authority_key_required')
    with _fence(source, target, operation_id, source_workflow_key) as (key, started):
        value = _load(target)
        if not value or value['operation_id'] != operation_id or value['schema_profile'] != _CATALOG_HASH():
            raise MigrationDenied('migration_receipt_mismatch')
        policy = history_policy if history_policy is not None else value.get('history_policy')
        challenge = _challenge(value, phase, policy)
        verified = authority.verify(approval, challenge, proof)
        summary = _measure(source, target, _source_tables(source._db), key, source_vault=source_vault, started=started)
        summary['identities'] = _identity_inventory(source, target, _source_tables(source._db))
        summary['equal'] = summary['equal'] and all(item['match'] for item in summary['identities'])
        if not summary['equal'] or summary != value['summary']: raise MigrationDenied('application_baseline_diverged')
        if not _transition_quiescent(target, policy): raise MigrationDenied('external_outcome_reconciliation_required')
        if phase == 'cutover' and value['state'] != 'staged' or phase == 'rollback' and value['state'] not in ('staged', 'cutover_prepared', 'binding_completed'):
            raise MigrationDenied('transition_already_prepared')
        updated = {**value, 'revision': value['revision'] + 1, 'state': phase + '_prepared',
            'prepared': time.time(), 'independent_evidence': verified['evidence'],
            'approval_hash': hashlib.sha256(_json(approval).encode()).hexdigest(),
            'live_source_writer_reservation': True, 'live_target_table_and_session_reservation': True,
            'external_dispatch_excluded': 'independent-attestation-only',
            'cutover_authorized': False, 'operating_enabled': False}
        if policy is not None:
            from .migration_terminal_custody import inspect
            updated.update(history_policy=policy, preserved_terminal_history=inspect(target))
        return _receipt(target, updated)


@contextmanager
def bind_application(source, target, *, operation_id, source_workflow_key,
                     authority, approval, source_vault=None, proof=None):
    """Use an approved transferred Store in one bounded native transaction.

    This is an actual caller-supplied repository binding, not another readiness
    receipt. Existing Store consumers can read/write the yielded target. Source
    BEGIN IMMEDIATE and target table/session fences remain held until commit or
    rollback. Cross-thread workers and external dispatch are outside this narrow
    transactional profile; compose_worker requires an idle Store and rejects it.
    No server setting changes and normal attachment remains quarantined on exit.
    A subsequent rollback still requires exact baseline equality and fresh proof.
    """
    if type(authority) is not PreparationAuthority:
        raise MigrationDenied()
    if hmac.compare_digest(authority.key, getattr(target, 'workflow_key', b'')):
        raise MigrationDenied('independent_authority_key_required')
    with _fence(source, target, operation_id, source_workflow_key) as (key, started):
        value = _load(target)
        if (not value or value['operation_id'] != operation_id
                or value['schema_profile'] != _CATALOG_HASH()
                or value['state'] != 'cutover_prepared'):
            raise MigrationDenied('cutover_preparation_required')
        challenge = _challenge(value, 'binding')
        verified = authority.verify(approval, challenge, proof)
        summary = _measure(source, target, _source_tables(source._db), key,
            source_vault=source_vault, started=started)
        summary['identities'] = _identity_inventory(source, target, _source_tables(source._db))
        summary['equal'] = summary['equal'] and all(item['match'] for item in summary['identities'])
        if not summary['equal'] or summary != value['summary']:
            raise MigrationDenied('application_baseline_diverged')
        if not _transition_quiescent(target, value.get('history_policy')):
            raise MigrationDenied('external_outcome_reconciliation_required')
        yield target
        # Expiry/revocation during application work aborts the same transaction.
        authority.verify(approval, challenge, proof)
        if not _transition_quiescent(target, value.get('history_policy')):
            raise MigrationDenied('external_outcome_reconciliation_required')
        _receipt(target, {**value, 'revision': value['revision'] + 1,
            'state': 'binding_completed', 'bound': time.time(),
            'binding_profile': 'fenced-transactional-application-v1',
            'independent_evidence': verified['evidence'],
            'approval_hash': hashlib.sha256(_json(approval).encode()).hexdigest(),
            'source_mutated': False, 'cutover_authorized': False,
            'operating_enabled': False, 'full_application_ready': False})


def activate_application(source, target, *, operation_id, source_workflow_key,
                         authority, approval, source_vault=None, proof=None):
    """Retire the source durably before committing a persistent target writer.

    Both ingress and workers must already be drained and independently proven.
    The committed native gate survives service restart; every Store transaction
    checks it. A failure after the source commit leaves both writers stopped.
    This operation does not switch DNS, processes, public features or traffic.
    """
    from .application_writer_fence import install, verify
    from .application_store_postgres import _CATALOG
    if (type(authority) is not PreparationAuthority
            or hmac.compare_digest(authority.key, getattr(target, 'workflow_key', b''))):
        raise MigrationDenied('independent_authority_key_required')
    with _fence(source, target, operation_id, source_workflow_key) as (key, started):
        value = _load(target)
        if (not value or value['operation_id'] != operation_id or value['state'] != 'cutover_prepared'
                or value['schema_profile'] != _CATALOG_HASH()):
            raise MigrationDenied('cutover_preparation_required')
        verified = authority.verify(approval, _challenge(value, 'activation'), proof)
        names = _source_tables(source._db)
        definitions = _CATALOG.get('sqlite_tables')
        if type(definitions) is not dict or set(definitions)!=set(_CATALOG['metadata']):
            raise MigrationDenied('reviewed_source_schema_required')
        materialized = sorted(set(value['summary']['schema_absent_empty']) & set(definitions))
        retirement = {'profile': 'application-source-writer-v1', 'operation_id': operation_id,
            'target_anchor': value['target_anchor'], 'baseline': _challenge(value, 'activation')['baseline'],
            'materialized_tables': materialized}
        prior_retirement = source._db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='application_source_writer_fence'").fetchone()
        if prior_retirement and not verify(source._db,retirement,key):
            raise MigrationDenied('source_retirement_mismatch')
        summary = _measure(source, target, names, key,
            source_vault=source_vault, started=started)
        if prior_retirement:
            expected_absent = sorted(set(value['summary']['schema_absent_empty'])-set(materialized))
            if summary['schema_absent_empty']!=expected_absent:
                raise MigrationDenied('source_retirement_mismatch')
            # Empty optional tables materialized by the committed retirement
            # change no data or identity; retain the independently pinned copy
            # baseline across an interrupted target activation.
            summary['schema_absent_empty'] = value['summary']['schema_absent_empty']
        summary['identities'] = _identity_inventory(source, target, names)
        summary['equal'] = summary['equal'] and all(item['match'] for item in summary['identities'])
        if not summary['equal'] or summary != value['summary']:
            raise MigrationDenied('application_baseline_diverged')
        if not _transition_quiescent(target, value.get('history_policy')):
            raise MigrationDenied('external_outcome_reconciliation_required')
        if prior_retirement:
            # A lost/failed target commit may follow a known source retirement.
            # Fresh independent approval can complete that same transfer; a
            # different or tampered retirement can never be adopted.
            if not verify(source._db, retirement, key):
                raise MigrationDenied('source_retirement_mismatch')
            prior = source._db.execute('SELECT payload,signature FROM application_source_writer_fence WHERE id=1').fetchone()
            source_proof = {'source_gate_sha256':hashlib.sha256(prior[0].encode()).hexdigest(),'signature':prior[1]}
        else:
            source_proof = install(source._db, retirement, key, schema_definitions=definitions)
            _source_tables(source._db)
        authority.verify(approval, _challenge(value, 'activation'), proof)
        # No target activation can commit before every old source write path is
        # stopped. SQLite commit uncertainty is a stop; no automatic retry runs.
        try:
            source._db.commit()
        except Exception:
            raise MigrationDenied('source_retirement_commit_unknown') from None
        return _receipt(target, {**value, 'revision': value['revision']+1,
            'state': 'service_active', 'activated': time.time(), 'source_retirement': retirement,
            'source_retirement_proof': source_proof, 'independent_evidence': verified['evidence'],
            'approval_hash': hashlib.sha256(_json(approval).encode()).hexdigest(),
            'source_mutated': True, 'persistent_writer_binding': True,
            'cutover_authorized': True, 'operating_enabled': True,
            'ingress_switched_by_operation': False, 'external_acceptance_established': False})


def _capture_target(source, target, names, *, source_vault, started):
    """Copy current target state back under both writer fences, with no replay."""
    from .application_store_postgres import _CATALOG
    from .credential_vault import CredentialVault
    db = source._db
    source_definitions = _CATALOG.get('sqlite_tables')
    if type(source_definitions) is not dict or set(source_definitions) != set(_CATALOG['metadata']):
        raise MigrationDenied('reviewed_reverse_schema_required')
    if db.execute('SELECT COUNT(*) FROM platform_credentials').fetchone()[0] if 'platform_credentials' in names else False:
        if type(source_vault) is not CredentialVault:
            raise MigrationDenied('source_vault_required')
    # Trigger definitions belong to the held source snapshot. Removing them is
    # transactional: a failed capture restores every old fence automatically.
    triggers = db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'").fetchall()
    for name, sql in triggers:
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
            raise MigrationDenied('source_schema_mismatch')
        db.execute('DROP TRIGGER "'+name+'"')
    for table, definition in source_definitions.items():
        if table not in names:
            db.execute(definition)
    db.execute('PRAGMA defer_foreign_keys=ON')
    for table in _columns():
        db.execute('DELETE FROM "'+table+'"')
    total, size = 0, 0
    target_vault = target._vault()
    for table, fields in _columns().items():
        inserted = 0
        identifiers = ','.join('rowid' if column == '_ac_rowid' else '"'+column+'"' for column, _ in fields)
        statement = 'INSERT INTO "'+table+'"('+identifiers+') VALUES('+','.join('?' for _ in fields)+')'
        with _managed_rows(target, table, fields, native=True) as native_rows:
            for row in native_rows:
                total += 1; inserted += 1
                if inserted > MAX_TABLE_ROWS or total > MAX_TOTAL_ROWS:
                    raise MigrationDenied('migration_row_limit')
                transferred = list(row)
                size += sum(len(item.encode() if type(item) is str else item) if isinstance(item,(str,bytes)) else 8 for item in row)
                if size > MAX_BYTES:
                    raise MigrationDenied('migration_byte_limit')
                if table == 'platform_credentials':
                    if type(source_vault) is not CredentialVault:
                        raise MigrationDenied('source_vault_required')
                    at = next(i for i,item in enumerate(fields) if item[0] == 'key_value')
                    key_at = next(i for i,item in enumerate(fields) if item[0] == 'key_name')
                    try:
                        plaintext = target_vault.open(row[key_at], row[at])
                        transferred[at] = source_vault.seal(row[key_at], plaintext)
                    except (ValueError, TypeError, UnicodeError):
                        raise MigrationDenied('invalid_target_credential') from None
                db.execute(statement, transferred)
                if time.monotonic()-started > MAX_SECONDS:
                    raise MigrationDenied('migration_time_limit')
    from .application_writer_fence import PREFIX
    for name, sql in triggers:
        if not name.startswith(PREFIX):
            db.execute(sql)
    # Preserve deleted-ID high water marks; current maximum rows alone cannot
    # prove that an authorization/audit ID has never existed before rollback.
    autoincrement = {name for name, sql in source_definitions.items() if 'AUTOINCREMENT' in sql.upper()}
    for table in autoincrement:
        columns = [item[1] for item in _CATALOG['metadata'][table] if item[5]]
        if len(columns) != 1:
            raise MigrationDenied('identity_sequence_mismatch')
        sequence = target._execute('SELECT pg_get_serial_sequence(%s,%s)', ('public."'+table+'"', columns[0])).fetchone()[0]
        if not sequence or not re.fullmatch(r'public\.[a-z_][a-z0-9_]*', sequence):
            raise MigrationDenied('identity_sequence_mismatch')
        high, called = target._execute('SELECT last_value,is_called FROM '+sequence).fetchone()
        high = int(high) if called else max(0, int(high)-1)
        previous = db.execute('SELECT seq FROM sqlite_sequence WHERE name=?',(table,)).fetchone()
        high = max(high, previous[0] if previous else 0)
        if previous:
            db.execute('UPDATE sqlite_sequence SET seq=? WHERE name=?',(high,table))
        else:
            db.execute('INSERT INTO sqlite_sequence VALUES(?,?)',(table,high))
    if db.execute('PRAGMA foreign_key_check').fetchone() is not None:
        raise MigrationDenied('reverse_foreign_key_mismatch')
    return {'captured_rows': total, 'captured_bytes': size, 'replayed_operations': 0}


def rollback_activation(source, target, *, operation_id, source_workflow_key,
                        authority, approval, capture_changes=False, source_vault=None, proof=None):
    """Stop the target, optionally capture its changes, then release the source.

    Refusing divergence is the default. Explicit capture copies the latest
    authorization, revocations, idempotency and financial rows as data; it never
    executes a workflow, sends a notification or creates a payment. An uncertain
    target commit leaves the source retired for independent review.
    """
    from .application_writer_fence import verify, remove
    if (type(capture_changes) is not bool or type(authority) is not PreparationAuthority
            or hmac.compare_digest(authority.key, getattr(target, 'workflow_key', b''))):
        raise MigrationDenied()
    with _fence(source, target, operation_id, source_workflow_key,
                commit_source_after_target=True) as (key, started):
        value = _load(target)
        if (not value or value['operation_id'] != operation_id or value['state'] not in ('service_active','service_rolled_back')
                or value['schema_profile'] != _CATALOG_HASH()
                or not verify(source._db, value['source_retirement'], key)):
            raise MigrationDenied('active_writer_binding_required')
        challenge = _challenge(value, 'rollback_activation')
        verified = authority.verify(approval, challenge, proof)
        if not _transition_quiescent(target, value.get('history_policy')):
            raise MigrationDenied('external_outcome_reconciliation_required')
        names = _source_tables(source._db)
        before = _measure(source, target, names, key, source_vault=source_vault, started=started)
        capture = {'captured_rows': 0, 'captured_bytes': 0, 'replayed_operations': 0}
        if not before['equal']:
            if not capture_changes:
                raise MigrationDenied('application_baseline_diverged')
            capture = _capture_target(source,target,names,source_vault=source_vault,started=started)
        after = _measure(source, target, _source_tables(source._db), key, source_vault=source_vault, started=started)
        if not after['equal']:
            raise MigrationDenied('application_reconciliation_failed')
        authority.verify(approval, challenge, proof)
        remove(source._db)
        result = _receipt(target, {**value, 'revision': value['revision']+1,
            'state': 'service_rolled_back', 'rolled_back': time.time(),
            'cutover_authorized': False, 'operating_enabled': False,
            'independent_evidence': verified['evidence'], 'change_capture': capture,
            'rollback_summary': after, 'ingress_switched_by_operation': False})
    return result


@contextmanager
def review_application(connection, *, workflow_key, operation_id):
    """Explicitly inspect a staged target after reconnect or lost commit reply.

    This never retries a transfer, removes quarantine, approves a deployment or
    returns an activated Store. The scoped Store cannot be used after exit.
    """
    from .application_store_postgres import WRITER_LOCK, PostgresApplicationStore
    if (type(operation_id) is not str or not _ID.fullmatch(operation_id)
            or type(workflow_key) is not bytes or len(workflow_key) != 32
            or connection.autocommit is not True or int(connection.info.transaction_status) != 0):
        raise MigrationDenied()
    if _sql(connection, 'SELECT pg_catalog.pg_try_advisory_lock(%s)', (WRITER_LOCK,)) != [(True,)]:
        raise MigrationDenied('target_writer_ownership_conflict')
    store, marker = None, _owner.set({'connection': connection, 'operation_id': operation_id,
        'thread': threading.get_ident(), 'expires': time.monotonic() + _limit('MAX_SECONDS')})
    try:
        store = PostgresApplicationStore(connection, workflow_key=workflow_key)
        value = _load(store)
        if not value or value['operation_id'] != operation_id: raise MigrationDenied('migration_receipt_mismatch')
        yield store
    finally:
        if store is not None: store.close()
        _owner.reset(marker)
        if _sql(connection, 'SELECT pg_catalog.pg_advisory_unlock(%s)', (WRITER_LOCK,)) != [(True,)]:
            raise MigrationDenied('target_ownership_unknown')


def _identity_inventory(source, target, names):
    sequence_rows = source._db.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name='sqlite_sequence'").fetchone()
    source_sequences = dict(source._db.execute('SELECT name,seq FROM sqlite_sequence')) if sequence_rows else {}
    result = []
    for table, fields in _columns().items():
        for column, kind in fields:
            if kind != 'INTEGER': continue
            sequence = target._execute('SELECT pg_catalog.pg_get_serial_sequence(%s,%s)',
                ('public."' + table + '"', column)).fetchone()[0]
            if not sequence: continue
            if not re.fullmatch(r'public\.[a-z_][a-z0-9_]*', sequence): raise MigrationDenied('identity_sequence_mismatch')
            source_column = 'rowid' if column == '_ac_rowid' else '"' + column + '"'
            maximum = source._db.execute('SELECT MAX(' + source_column + ') FROM "' + table + '"').fetchone()[0] if table in names else 0
            high_water = source_sequences.get(table, 0) if column != '_ac_rowid' else 0
            if type(high_water) is not int or high_water < 0: raise MigrationDenied('identity_sequence_mismatch')
            maximum = max(maximum or 0, high_water)
            if type(maximum) is not int or maximum < 0 or maximum >= 2 ** 63 - 1: raise MigrationDenied('identity_sequence_exhausted')
            last, called = target._execute('SELECT last_value,is_called FROM ' + sequence).fetchone()
            actual = last + int(called)
            result.append({'table': table, 'column': column, 'next': maximum + 1,
                'target_next': actual, 'match': actual == maximum + 1})
    return result
