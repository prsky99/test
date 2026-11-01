"""Explicit AX component rehearsal in a short-lived schema on the configured PG.

No initdb, new server, public table mutations, migrations or Provider calls.
Real consumer methods and the production SQL executor run on three synthetic
tables. This is component/locking proof, not a fresh full-profile install test.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import inspect
import json
from pathlib import Path
import re
import secrets
import threading
import time

from agent_market.application_store_consumers import PostgresConsumerMixin
from agent_market.application_store_postgres import PostgresApplicationStore, ApplicationStoreError
from agent_market.concierge.recommendation_circuit import controls_for, remediate_sqlite

SCHEMA_PREFIX = 'ax_circuit_check_'
REPORT = Path('reports/ax-postgres-alternative-2026-10-25')


def require_schema(name):
    if type(name) is not str or not re.fullmatch(SCHEMA_PREFIX+r'[0-9a-f]{24}', name):
        raise ValueError('invalid_rehearsal_schema')
    return name


class ScopedConsumer(PostgresConsumerMixin):
    # These execute the production parameter checks and real psycopg cursor IO.
    # No simulated query results and no alteration of production Store gates.
    _native = PostgresApplicationStore._native
    _execute = PostgresApplicationStore._execute

    def __init__(self, connection, schema):
        self.schema = require_schema(schema)
        self._connection = connection
        self._lock = threading.RLock()
        self._depth = 0
        self._owner = None
        self._failed = self._broken = False

    @contextmanager
    def tx(self, *, readonly=False):
        from psycopg import sql
        with self._lock:
            if self._depth:
                self._depth += 1
                try:
                    yield self
                except BaseException:
                    self._failed = True
                    raise
                finally:
                    self._depth -= 1
                return
            if self._broken or self._connection.info.transaction_status != 0:
                raise RuntimeError('rehearsal_connection_not_idle')
            self._depth, self._owner, self._failed = 1, threading.get_ident(), False
            try:
                self._connection.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY' if readonly else 'BEGIN')
                self._connection.execute(sql.SQL('SET LOCAL search_path TO pg_catalog,{},pg_temp').format(sql.Identifier(self.schema)))
                self._connection.execute("SET LOCAL statement_timeout='5000ms'")
                self._connection.execute("SET LOCAL lock_timeout='1000ms'")
                self._connection.execute("SET LOCAL synchronous_commit='on'")
                resolved = self._connection.execute(
                    "SELECT c.relnamespace=n.oid FROM pg_class c JOIN pg_namespace n ON n.nspname=%s WHERE c.oid=to_regclass('meta')",
                    (self.schema,),
                ).fetchone()
                if resolved != (True,):
                    raise RuntimeError('rehearsal_schema_resolution_failed')
                yield self
                if self._failed:
                    raise RuntimeError('rehearsal_transaction_failed')
                self._connection.commit()
            except BaseException:
                self._connection.rollback()
                raise
            finally:
                self._depth, self._owner = 0, None

    def get_meta(self, key, default=None):
        with self.tx(readonly=True):
            row = self._execute('SELECT value FROM meta WHERE key=%s', (key,)).fetchone()
        return json.loads(row['value']) if row else default

    def close(self):
        if self._connection.info.transaction_status != 0:
            self._connection.rollback()
        self._connection.close()


def contracts(native, connect_peer, checks=None):
    from agent_market.gateway.store import Store
    from agent_market.concierge.memory import VisitorBook
    from agent_market.infra.redis_hub import RedisHub
    offline = RedisHub(); offline._closed = True; RedisHub._instance = offline
    reference = Store()
    checks = {} if checks is None else checks

    def record(store, visitor, rid, ok, at):
        if store is native:
            with native.tx():
                native._execute('INSERT INTO agent_outcomes VALUES (%s,%s,%s,%s)', (visitor, rid, int(ok), at))
        else:
            with store.tx() as db:
                db.execute('INSERT INTO agent_outcomes VALUES (?,?,?,?)', (visitor, rid, int(ok), at))

    def rows(store):
        if store is native:
            with native.tx(readonly=True):
                return [dict(r) for r in native._execute('SELECT * FROM agent_outcomes ORDER BY visitor_id').fetchall()]
        return [dict(r) for r in store.query('SELECT * FROM agent_outcomes ORDER BY visitor_id')]

    def change(store, action):
        if store is native:
            return native.remediate_agent_telemetry(action, resource_id=1, now=time.time())
        return remediate_sqlite(store, 1, action, time.time())

    try:
        for number in range(1, 5):
            with native.tx():
                native._execute('INSERT INTO resources(id,name,kind,active) VALUES (%s,%s,%s,1)',
                                (number, 'Circuit '+str(number), 'mcp'))
            assert reference.upsert_resource({'key': 'circuit-'+str(number), 'source': 'fixture', 'kind': 'mcp',
                'url': 'https://fixture-'+str(number)+'.invalid/mcp', 'name': 'Circuit '+str(number),
                'description': 'Synthetic circuit', 'category': 'research', 'networks': []}) == number
        for store in (native, reference):
            for i in range(10):
                record(store, 'success-'+str(i), 1, True, time.time()-60)
            before = rows(store)
            assert change(store, 'trip_circuit')['circuit_open'] is True
            assert 1 in VisitorBook(store).global_failing_resources()
            assert rows(store) == before
            assert change(store, 'reset_circuit')['circuit_open'] is False
            assert 1 not in VisitorBook(store).global_failing_resources()
            assert rows(store) == before
            for i in range(3):
                record(store, 'new-failure-'+str(i), 1, False, time.time())
            assert 1 in VisitorBook(store).global_failing_resources()
            before = rows(store)
            assert change(store, 'reset_circuit')['history_preserved'] is True
            assert len(before) == 13 and rows(store) == before
        checks['manual_open_overrides_ten_successes_without_fake_failures'] = True
        checks['reset_preserves_thirteen_outcome_rows'] = True
        checks['new_epoch_failures_reopen_without_old_success_dilution'] = True
        checks['sqlite_postgres_exclusions_match'] = (
            VisitorBook(native).global_failing_resources() == VisitorBook(reference).global_failing_resources() == set())

        barrier = threading.Barrier(2)
        spans = []
        def trip(rid):
            peer = native if rid == 2 else connect_peer()
            try:
                with peer.tx():
                    started = time.monotonic()
                    # Both database transactions must be open before either writes.
                    barrier.wait(timeout=10)
                    response = peer.remediate_agent_telemetry('trip_circuit', resource_id=rid, now=time.time())
                spans.append((started,time.monotonic()))
                return response
            finally:
                if peer is not native: peer.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(trip, (2, 3)))
        assert all(row['circuit_open'] for row in results)
        assert {'2', '3'} <= controls_for(native).keys()
        assert {2, 3} <= native.global_failing_resources()
        checks['concurrent_staff_controls_do_not_overwrite_other_resources'] = True
        assert len(spans) == 2 and max(start for start, end in spans) < min(end for start, end in spans)
        checks['two_real_postgres_transactions_overlap'] = True
        # Confirm forced states survive a fresh real connection and commit.
        peer = connect_peer()
        try:
            assert {2, 3} <= peer.global_failing_resources()
        finally:
            peer.close()
        checks['committed_controls_visible_in_new_connection'] = True
        # An actual failed write transaction must leave the control row intact.
        previous = controls_for(native)
        try:
            with native.tx():
                native._execute('UPDATE meta SET value=%s', ('{}',))
                raise RuntimeError('synthetic_rollback')
        except RuntimeError as exc:
            if str(exc) != 'synthetic_rollback':
                raise
        assert controls_for(native) == previous
        checks['real_postgres_rollback_preserves_previous_controls'] = True
        return checks
    finally:
        reference._db.close()


def run(root=None):
    from psycopg import sql
    from scripts.agentcon_config import read_settings
    from agent_market.application_runtime import _private_bytes, _connect
    root = Path.cwd() if root is None else Path(root).resolve()
    folder = root/REPORT; folder.mkdir(parents=True, exist_ok=True)
    values = read_settings(str(root/'gateway-data/agentcon.env'))
    path = Path(values['APPLICATION_POSTGRES_DSN_FILE'])
    if not path.is_absolute(): path = root/path
    dsn = _private_bytes(str(path), 16384).decode().strip()
    schema = require_schema(SCHEMA_PREFIX+secrets.token_hex(12))
    marker = 'agentconcierge:ax-component-rehearsal:'+secrets.token_hex(16)
    admin = _connect(dsn)
    native = None
    created = False
    result = {'mode': 'configured_postgres_isolated_schema', 'new_server_started': False,
              'initdb_calls': 0, 'operating_schema_writes': 0, 'provider_calls': 0,
              'full_application_profile_install_test': False, 'checks': {}}
    result['method_hashes'] = {name: hashlib.sha256(inspect.getsource(getattr(PostgresConsumerMixin,name)).encode()).hexdigest()
                               for name in ('global_failing_resources','remediate_agent_telemetry')}
    try:
        admin.execute("SET statement_timeout='10000ms'")
        admin.execute("SET lock_timeout='1000ms'")
        result['server_version_num'] = admin.execute("SHOW server_version_num").fetchone()[0]
        admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        created = True
        admin.execute(sql.SQL('COMMENT ON SCHEMA {} IS {}').format(sql.Identifier(schema),sql.Literal(marker)))
        for table, definition in (
            ('resources', 'id BIGINT PRIMARY KEY,name TEXT NOT NULL,kind TEXT NOT NULL,active INTEGER NOT NULL'),
            ('agent_outcomes', 'visitor_id TEXT NOT NULL,resource_id BIGINT NOT NULL,success INTEGER NOT NULL,at DOUBLE PRECISION NOT NULL,PRIMARY KEY(visitor_id,resource_id)'),
            ('meta', 'key TEXT PRIMARY KEY,value TEXT NOT NULL'),
        ):
            admin.execute(sql.SQL('CREATE TABLE {}.{} ('+definition+')').format(sql.Identifier(schema),sql.Identifier(table)))
        def connect_peer():
            return ScopedConsumer(_connect(dsn),schema)
        # Reuse the setup session; at most one extra live connection is needed.
        native = ScopedConsumer(admin,schema)
        result['maximum_test_connections'] = 2
        contracts(native,connect_peer,result['checks'])
        result['passed'] = all(result['checks'].values())
        return result
    except Exception as exc:
        result['passed'] = False
        result['error_type'] = type(exc).__name__
        if isinstance(exc,ApplicationStoreError): result['error_code'] = str(exc)
        result['sqlstate'] = getattr(exc,'sqlstate',None)
        message = str(exc).lower()
        result['error_category'] = next((label for phrase,label in (
            ('too many clients','connection_limit'),('remaining connection slots','connection_limit'),
            ('timeout','timeout'),('shared memory','shared_memory'),('ssl','tls'),
            ('password authentication','authentication')) if phrase in message), 'other')
        raise
    finally:
        try:
            if admin.info.transaction_status != 0: admin.rollback()
            if created:
                ownership = admin.execute(
                    "SELECT nspowner=(SELECT oid FROM pg_roles WHERE rolname=current_user),obj_description(oid,'pg_namespace') FROM pg_namespace WHERE nspname=%s",
                    (schema,),
                ).fetchone()
                if ownership != (True,marker):
                    raise RuntimeError('rehearsal_cleanup_ownership_mismatch')
                admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(require_schema(schema))))
                result['schema_removed'] = admin.execute('SELECT 1 FROM pg_namespace WHERE nspname=%s',(schema,)).fetchone() is None
            else:
                result['schema_removed'] = True
        except Exception as cleanup:
            result['passed'] = False
            result['schema_removed'] = False
            result['cleanup_error_type'] = type(cleanup).__name__
            raise
        finally:
            admin.close()
            (folder/'existing-schema-result.json').write_text(json.dumps(result,indent=2)+'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--existing-runtime',action='store_true',required=True)
    parser.parse_args()
    try:
        result = run()
    except Exception as exc:
        print(json.dumps({'passed':False,'error_type':type(exc).__name__}))
        raise SystemExit(1)
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
