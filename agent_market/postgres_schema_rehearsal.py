"""Explicit, owned-schema functional rehearsals on an existing PostgreSQL 18.

Not a tenant security boundary or a production storage configuration. The public
Store factory never selects this class. No SQL is rewritten at execution time.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import re
import secrets

from .application_store_postgres import PostgresApplicationStore, ApplicationStoreError

NAME = re.compile(r'ac_b2a_[0-9a-f]{24}\Z')


@dataclass(frozen=True)
class OwnedSchema:
    name: str
    oid: int
    owner: int
    database: int
    forbidden_namespaces: tuple


def _identity(connection, name):
    with connection.cursor() as cur:
        cur.execute('''SELECT n.oid,n.nspowner,d.oid,
            n.nspowner=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=current_user),
            NOT EXISTS(SELECT 1 FROM pg_catalog.aclexplode(COALESCE(n.nspacl,pg_catalog.acldefault('n',n.nspowner))) a
                       WHERE a.grantee<>n.nspowner AND a.privilege_type IN ('CREATE','USAGE'))
            FROM pg_catalog.pg_namespace n CROSS JOIN pg_catalog.pg_database d
            WHERE n.nspname=%s AND d.datname=current_database()''', (name,))
        return cur.fetchone()


def _verify_identity(connection, schema):
    if type(schema) is not OwnedSchema or not NAME.fullmatch(schema.name):
        raise ApplicationStoreError('rehearsal_schema_invalid')
    row = _identity(connection, schema.name)
    if row != (schema.oid, schema.owner, schema.database, True, True):
        raise ApplicationStoreError('rehearsal_schema_identity_changed')


def _external_dependents(connection, schema):
    with connection.cursor() as cur:
        cur.execute('''WITH owned(classid,objid) AS (
            SELECT 'pg_namespace'::regclass::oid,%s::oid UNION ALL
            SELECT 'pg_class'::regclass::oid,oid FROM pg_catalog.pg_class WHERE relnamespace=%s UNION ALL
            SELECT 'pg_proc'::regclass::oid,oid FROM pg_catalog.pg_proc WHERE pronamespace=%s UNION ALL
            SELECT 'pg_type'::regclass::oid,oid FROM pg_catalog.pg_type WHERE typnamespace=%s)
            SELECT 1 FROM pg_catalog.pg_depend d JOIN owned o ON o.classid=d.refclassid AND o.objid=d.refobjid
            CROSS JOIN LATERAL pg_catalog.pg_identify_object(d.classid,d.objid,d.objsubid) p
            WHERE (p.schema IS NOT NULL AND p.schema NOT IN (%s,'pg_toast')) OR p.type='extension' LIMIT 1''',
            (schema.oid, schema.oid, schema.oid, schema.oid, schema.name))
        return cur.fetchone() is not None


@contextmanager
def owned_schema(connection):
    """Create once, revoke other access, and drop only the exact owned identity."""
    from psycopg import sql
    if connection.autocommit is not True or int(connection.info.transaction_status) != 0:
        raise ApplicationStoreError('connection_busy')
    name = 'ac_b2a_' + secrets.token_hex(12)
    schema = None
    try:
        with connection.transaction():
            with connection.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout='1000ms'")
                cur.execute("SET LOCAL statement_timeout='10000ms'")
                cur.execute("SELECT current_setting('server_version_num')::integer>=180000,has_database_privilege(current_database(),'CREATE'),EXISTS(SELECT 1 FROM pg_catalog.pg_event_trigger WHERE evtenabled<>'D')")
                if cur.fetchone() != (True, True, False):
                    raise ApplicationStoreError('schema_rehearsal_precondition_failed')
                cur.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(name)))
                cur.execute(sql.SQL('REVOKE ALL ON SCHEMA {} FROM PUBLIC').format(sql.Identifier(name)))
                row = _identity(connection, name)
                if not row or row[3:] != (True, True):
                    raise ApplicationStoreError('schema_rehearsal_acl_failed')
                cur.execute("SELECT nspname FROM pg_catalog.pg_namespace WHERE nspname<>%s AND nspname NOT IN ('pg_catalog','information_schema') AND nspname NOT LIKE 'pg_temp_%%' AND nspname NOT LIKE 'pg_toast%%'", (name,))
                candidate = OwnedSchema(name, row[0], row[1], row[2], tuple(r[0] for r in cur.fetchall()))
        schema = candidate
        yield schema
    finally:
        if schema is not None:
            with connection.transaction():
                with connection.cursor() as cur:
                    cur.execute("SET LOCAL lock_timeout='1000ms'")
                    cur.execute("SET LOCAL statement_timeout='10000ms'")
                    _verify_identity(connection, schema)
                    if _external_dependents(connection, schema):
                        raise ApplicationStoreError('rehearsal_cleanup_external_dependency')
                    cur.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema.name)))
            if _identity(connection, schema.name) is not None:
                raise ApplicationStoreError('rehearsal_cleanup_incomplete')


class SchemaRehearsalStore(PostgresApplicationStore):
    """Actual native Store, pinned to one private schema and its own writer lock."""
    def __init__(self, connection, schema, *, initialize=False, workflow_key=None):
        _verify_identity(connection, schema)
        self._rehearsal = schema
        self._forbidden_schema_refs = tuple(re.compile(r'(?i)(?<![A-Za-z0-9_])"?'+re.escape(n)+r'"?\s*\.')
            for n in schema.forbidden_namespaces)
        self._scope_lock = -1 - (int.from_bytes(hashlib.sha256(schema.name.encode()).digest()[:8], 'big') & ((1 << 63)-1))
        super().__init__(connection, initialize=initialize, workflow_key=workflow_key)

    def _schema_namespace(self):
        return self._rehearsal.name

    def _writer_identity(self):
        return self._scope_lock

    def _lexical_available(self):
        # A production extension/index must never service fixture data. This is
        # the existing bounded FTS projection path backed by real PG rows.
        return False

    def _ann_available(self):
        return False

    def _transaction_controls(self):
        # Name is minted by owned_schema and checked again before every tx.
        self._native('SET LOCAL search_path TO "'+self._rehearsal.name+'",pg_temp').close()
        self._native("SET LOCAL statement_timeout='5000ms'").close()
        self._native("SET LOCAL lock_timeout='1000ms'").close()
        self._native("SET LOCAL synchronous_commit='on'").close()

    def _assert_deployment_gates(self):
        # This namespace is not an operating migration/restore target. It has
        # its own immutable ownership gate, never permission to attach public.
        _verify_identity(self._connection, self._rehearsal)

    def _native(self, text, parameters=()):
        if any(pattern.search(text) for pattern in self._forbidden_schema_refs):
            raise ApplicationStoreError('rehearsal_schema_escape')
        return super()._native(text, parameters)


def is_owned_store(store):
    """Only the explicit rehearsal class with its still-owned schema qualifies."""
    if type(store) is not SchemaRehearsalStore:
        return False
    _verify_identity(store._connection, store._rehearsal)
    return True
