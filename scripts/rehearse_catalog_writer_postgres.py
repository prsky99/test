"""Explicit disposable atomic catalog-writer and index-outbox rehearsal.

No operating database, DSN, provider, application server or index engine is
accepted. The established private PostgreSQL harness owns cluster shutdown.
Only the new private write contract is compared, never a production cutover.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import time

PROFILE = 'catalog-writer-postgres-rehearsal-v1'
CHECKS = frozenset(('unix_socket_only', 'new_and_replay_parity', 'explicit_zero_first_seen',
    'equal_content_advances_revision', 'health_survey_ownership_preserved', 'eligibility_invalidated_history_retained',
    'conflict_receipt_replayed', 'operation_reuse_refused', 'stale_observation_refused',
    'changed_url_resets_current_health', 'private_original_binding_and_public_projection',
    'outbox_superseded_ack_safe', 'expired_claim_fenced', 'failed_job_not_reclaimed',
    'model_revision_hides_old_projection', 'same_key_cas_single_winner', 'same_key_create_single_identity', 'rollback_all_write_boundaries',
    'commit_unknown_reconciled_without_new_write', 'unversioned_resource_refused',
    'disabled_write_refused_reconcile_available', 'sqlite_postgres_semantics_equal'))


class RehearsalError(ValueError):
    def __init__(self, code='rehearsal_failed'):
        self.code = code if code in ('dependency_unavailable', 'tools_unavailable', 'rehearsal_failed', 'invariant_failed') else 'rehearsal_failed'
        super().__init__(self.code)


def _harness():
    from scripts import rehearse_storage_adapter_postgres
    return rehearse_storage_adapter_postgres


def _contracts(connect):
    """Fixed synthetic writer comparison; never initialize the operating Store."""
    import sqlite3
    from agent_market.catalog_writer import CatalogWriter, WriterError
    from agent_market.catalog_writer_fixtures import seed, seed_history, history_state, command, operation, MODEL_HASH, URL
    from agent_market.catalog_index_outbox import CatalogIndexOutbox
    from agent_market.concierge.connections import public_agent, gateway_agent_url
    from agent_market.storage_adapter import SQLiteAdapter, PostgresAdapter, Statement, StorageError

    projection_hash = hashlib.sha256(b'synthetic-index-projection').hexdigest()
    other_model = hashlib.sha256(b'synthetic-model-version-two').hexdigest()
    changed_url = 'https://new-synthetic-provider.example/projects/catalog/mcp'

    def statement(name, sqlite, postgres=None, *, readonly=False):
        return Statement(name, sqlite, sqlite if postgres is None else postgres, readonly=readonly)

    def execute(adapter, stmt, parameters=(), *, readonly=False):
        with adapter.transaction(readonly=readonly) as session:
            return session.execute(stmt, parameters)

    resource = statement('fixture.writer_resource', 'SELECT * FROM resources WHERE id=?', 'SELECT * FROM resources WHERE id=%s', readonly=True)
    cache = statement('fixture.writer_cache', 'SELECT COUNT(*) AS n FROM capability_eligibility', readonly=True)
    enable = statement('fixture.writer_enable', 'UPDATE catalog_write_controls SET enabled=?,revision=revision+1 WHERE id=1', 'UPDATE catalog_write_controls SET enabled=%s,revision=revision+1 WHERE id=1')
    read_tables = (
        ('resources', 'id'), ('catalog_resource_revisions', 'resource_id'),
        ('catalog_write_operations', 'operation_id'), ('catalog_index_heads', 'resource_id'),
        ('catalog_index_jobs', 'job_id'), ('catalog_index_projections', 'resource_id,model_hash'),
        ('capability_eligibility', 'resource_id'))
    state_statements = tuple(statement('fixture.writer_state' + str(index), 'SELECT * FROM ' + table + ' ORDER BY ' + order, readonly=True)
        for index, (table, order) in enumerate(read_tables))

    def state(adapter):
        with adapter.transaction(readonly=True) as session:
            values = tuple(tuple(tuple(row) for row in session.execute(stmt).rows) for stmt in state_statements)
        return values + history_state(adapter)

    def row(adapter, rid):
        return dict(execute(adapter, resource, (rid,), readonly=True).rows[0])

    def refused(action, code):
        try:
            action()
        except (WriterError, StorageError) as exc:
            return exc.code == code
        return False

    def result(value):
        return value.status, value.change, value.resource_id, value.revision, value.replayed

    class FaultySQLite(sqlite3.Connection):
        armed = False
        def commit(self):
            super().commit()
            if self.armed:
                self.armed = False
                raise RuntimeError('Synthetic commit acknowledgement fault')

    class FaultyPostgres:
        def __init__(self, connection):
            self._connection, self.armed = connection, True
        def __getattr__(self, name):
            return getattr(self._connection, name)
        def commit(self):
            self._connection.commit()
            if self.armed:
                self.armed = False
                raise RuntimeError('Synthetic commit acknowledgement fault')

    def exercise(adapter, connector):
        seed(adapter, enabled=False)
        writer = CatalogWriter(adapter, model_hash=MODEL_HASH)
        base = command()
        checks = {'disabled_write_refused_reconcile_available': refused(lambda: writer.upsert(base,
            operation_id=operation(1), expected_revision=0, observed_at=0), 'write_disabled')}
        execute(adapter, enable, (1,))
        created = writer.upsert(base, operation_id=operation(1), expected_revision=0, observed_at=0)
        replay = writer.upsert(base, operation_id=operation(1), expected_revision=0, observed_at=0)
        initial = row(adapter, created.resource_id)
        checks['new_and_replay_parity'] = result(created) == ('committed', 'new', created.resource_id, 1, False) and result(replay) == ('committed', 'new', created.resource_id, 1, True)
        checks['explicit_zero_first_seen'] = initial['first_seen'] == initial['last_seen'] == 0
        seed_history(adapter, created.resource_id)
        history = history_state(adapter)
        observed = statement('fixture.writer_observations',
            "UPDATE resources SET active=0,health_status='failing',consecutive_failures=3,last_check_at=5,last_ok_at=4,auth_observed=1,auth_info='synthetic-private-auth',usage_tools='[]',usage_full_tools=NULL,cap_checked_at=3,eval_at=2,eval_grade='A',eval_score=99 WHERE id=?",
            "UPDATE resources SET active=0,health_status='failing',consecutive_failures=3,last_check_at=5,last_ok_at=4,auth_observed=1,auth_info='synthetic-private-auth',usage_tools='[]',usage_full_tools=NULL,cap_checked_at=3,eval_at=2,eval_grade='A',eval_score=99 WHERE id=%s")
        execute(adapter, observed, (created.resource_id,))
        outbox = CatalogIndexOutbox(adapter)
        old_claim = outbox.claim('synthetic-worker-old', now=.5, lease_seconds=10)
        equal = writer.upsert(base, operation_id=operation(2), expected_revision=1, observed_at=1)
        equal_row = row(adapter, created.resource_id)
        checks['equal_content_advances_revision'] = equal.change == 'unchanged' and equal.revision == 2 and equal_row['first_seen'] == 0 and equal_row['last_seen'] == 1 and equal_row['active'] == 1
        checks['health_survey_ownership_preserved'] = (equal_row['health_status'] == 'failing' and equal_row['consecutive_failures'] == 3
            and equal_row['auth_observed'] == 1 and equal_row['usage_full_tools'] is None
            and equal_row['cap_checked_at'] == 3 and equal_row['eval_at'] == 2)
        checks['eligibility_invalidated_history_retained'] = execute(adapter, cache, readonly=True).rows[0][0] == 0 and history_state(adapter) == history and all(history)
        superseded = outbox.complete(old_claim, projection_hash, now=1.1)
        fresh_claim = outbox.claim('synthetic-worker-new', now=2, lease_seconds=10)
        indexed = outbox.complete(fresh_claim, projection_hash, now=2.1)
        indexed_before = outbox.indexed_projection(created.resource_id, MODEL_HASH)
        checks['outbox_superseded_ack_safe'] = (superseded == 'superseded' and fresh_claim.revision == 2 and indexed == 'indexed'
            and outbox.complete(old_claim, projection_hash, now=2.2) == 'superseded'
            and outbox.indexed_projection(created.resource_id, MODEL_HASH) == indexed_before)

        counters = command(calls_30d=1)
        changed = writer.upsert(counters, operation_id=operation(3), expected_revision=2, observed_at=3)
        changed_row = row(adapter, created.resource_id)
        checks['health_survey_ownership_preserved'] = checks['health_survey_ownership_preserved'] and changed.change == 'changed' and changed.revision == 3 and changed_row['cap_checked_at'] is None and changed_row['eval_at'] is None and changed_row['eval_grade'] == 'A' and changed_row['usage_full_tools'] is None and changed_row['health_status'] == 'failing'
        checks['eligibility_invalidated_history_retained'] = checks['eligibility_invalidated_history_retained'] and history_state(adapter) == history
        expiring = outbox.claim('synthetic-expiring-worker', now=4, lease_seconds=1)
        renewed = outbox.claim('synthetic-recovery-worker', now=6, lease_seconds=10)
        checks['expired_claim_fenced'] = (renewed.job_id == expiring.job_id and renewed.fence == expiring.fence + 1
            and renewed.token != expiring.token and outbox.complete(expiring, projection_hash, now=6.1) == 'stale_claim')
        checks['failed_job_not_reclaimed'] = outbox.fail(renewed, 'index_failed', now=6.2) == 'failed' and outbox.claim('synthetic-no-auto-retry', now=7) is None

        conflict = writer.upsert(counters, operation_id=operation(4), expected_revision=2, observed_at=4)
        conflict_replay = writer.upsert(counters, operation_id=operation(4), expected_revision=2, observed_at=4)
        checks['conflict_receipt_replayed'] = conflict.status == 'conflict' and conflict.revision == 3 and conflict_replay.status == 'conflict' and conflict_replay.replayed is True and writer.reconcile(operation(4)).status == 'conflict'
        checks['operation_reuse_refused'] = refused(lambda: writer.upsert(counters, operation_id=operation(4), expected_revision=3, observed_at=4), 'operation_conflict')
        before_stale = state(adapter)
        checks['stale_observation_refused'] = refused(lambda: writer.upsert(counters, operation_id=operation(5), expected_revision=3, observed_at=2), 'stale_observation') and state(adapter) == before_stale
        new_url = command(calls_30d=1, url=changed_url)
        updated_url = writer.upsert(new_url, operation_id=operation(6), expected_revision=3, observed_at=10)
        url_row = row(adapter, created.resource_id)
        checks['changed_url_resets_current_health'] = (updated_url.revision == 4 and url_row['health_status'] == 'unknown'
            and url_row['consecutive_failures'] == url_row['health_ok_24h'] == url_row['health_n_24h'] == 0
            and url_row['next_check_at'] is None and url_row['failing_since'] is None and url_row['last_ok_at'] == 4)
        url_claim = outbox.claim('synthetic-url-worker', now=10.1, lease_seconds=10)
        outbox.complete(url_claim, projection_hash, now=10.2)
        alternate = CatalogWriter(adapter, model_hash=other_model)
        model_update = alternate.upsert(new_url, operation_id=operation(7), expected_revision=4, observed_at=11)
        checks['model_revision_hides_old_projection'] = model_update.revision == 5 and outbox.indexed_projection(created.resource_id, MODEL_HASH) is None
        model_claim = outbox.claim('synthetic-model-worker', now=11.1, lease_seconds=10)
        checks['model_revision_hides_old_projection'] = checks['model_revision_hides_old_projection'] and model_claim.model_hash == other_model and outbox.complete(model_claim, projection_hash, now=11.2) == 'indexed' and outbox.indexed_projection(created.resource_id, other_model).revision == 5
        private = row(adapter, created.resource_id)
        dto = {name: private[name] for name in ('id', 'kind', 'url', 'name', 'description')}
        dto['sources'] = ['https://sources.example/catalog-writer']
        projected = public_agent(dto, private, store=None)
        checks['private_original_binding_and_public_projection'] = (private['url'] == changed_url and private['auth_info'] == 'synthetic-private-auth'
            and projected['url'] == gateway_agent_url(created.resource_id, 'mcp')
            and projected['sources'] == ['https://sources.example/catalog-writer']
            and URL not in json.dumps(projected) and changed_url not in json.dumps(projected)
            and 'synthetic-private' not in json.dumps(projected))

        concurrent_command = command(key='synthetic:concurrent')
        concurrent = writer.upsert(concurrent_command, operation_id=operation(20), expected_revision=0, observed_at=0)
        barrier = threading.Barrier(4)
        def contender(number):
            connection, current_adapter = connector(False)
            try:
                current = CatalogWriter(current_adapter, model_hash=MODEL_HASH)
                barrier.wait(timeout=3)
                return current.upsert(command(key='synthetic:concurrent', name='Synthetic contender ' + str(number)), operation_id=operation(21 + number), expected_revision=1, observed_at=10)
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=4) as pool:
            races = list(pool.map(contender, range(4)))
        checks['same_key_cas_single_winner'] = (sum(value.status == 'committed' for value in races) == 1
            and sum(value.status == 'conflict' for value in races) == 3
            and all(value.resource_id == concurrent.resource_id and value.revision == 2 for value in races))

        create_barrier = threading.Barrier(4)
        def creator(number):
            connection, current_adapter = connector(False)
            try:
                current = CatalogWriter(current_adapter, model_hash=MODEL_HASH)
                create_barrier.wait(timeout=3)
                return current.upsert(command(key='synthetic:create-race', name='Synthetic creator ' + str(number)),
                    operation_id=operation(60 + number), expected_revision=0, observed_at=0)
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=4) as pool:
            creations = list(pool.map(creator, range(4)))
        winners = [value for value in creations if value.status == 'committed']
        creation_count = execute(adapter, statement('fixture.writer_create_count',
            'SELECT COUNT(*) AS n FROM resources WHERE key=?', 'SELECT COUNT(*) AS n FROM resources WHERE key=%s', readonly=True),
            ('synthetic:create-race',), readonly=True).rows[0][0]
        checks['same_key_create_single_identity'] = (len(winners) == 1 and winners[0].change == 'new'
            and sum(value.status == 'conflict' for value in creations) == 3 and creation_count == 1
            and all(value.resource_id == winners[0].resource_id and value.revision == 1 for value in creations)
            and all(result(writer.reconcile(operation(60 + index))) == result(value) for index, value in enumerate(creations)))

        original_transaction = adapter.transaction
        rollback_checks = []
        for number, boundary in enumerate(('catalog.writer_insert', 'catalog.writer_invalidate', 'catalog.index_enqueue', 'catalog.writer_receipt')):
            if boundary == 'catalog.writer_invalidate':
                execute(adapter, statement('fixture.writer_rollback_cache',
                    'INSERT INTO capability_eligibility VALUES (?,?,?,?,?)', 'INSERT INTO capability_eligibility VALUES (%s,%s,%s,%s,%s)'),
                    (created.resource_id, 'fixture-version-' + str(created.resource_id), 'failed', 0.0, 0.0))
            baseline = state(adapter)
            fault_fired = [False]
            @contextmanager
            def fault_transaction(*args, **kwargs):
                with original_transaction(*args, **kwargs) as session:
                    original_execute = session.execute
                    def fault_execute(stmt, params=()):
                        value = original_execute(stmt, params)
                        if stmt.name == boundary:
                            fault_fired[0] = True
                            raise RuntimeError('Synthetic write-boundary fault')
                        return value
                    session.execute = fault_execute
                    yield session
            adapter.transaction = fault_transaction
            raised = False
            try:
                if boundary == 'catalog.writer_invalidate':
                    alternate.upsert(new_url, operation_id=operation(40 + number), expected_revision=5, observed_at=20)
                else:
                    writer.upsert(command(key='synthetic:rollback:' + str(number)), operation_id=operation(40 + number), expected_revision=0, observed_at=20)
            except RuntimeError:
                raised = True
            finally:
                del adapter.transaction
            rollback_checks.append(raised and fault_fired[0] and state(adapter) == baseline)
        checks['rollback_all_write_boundaries'] = all(rollback_checks) and len(rollback_checks) == 4

        uncertain_connection, uncertain_adapter = connector(True)
        try:
            uncertain = CatalogWriter(uncertain_adapter, model_hash=MODEL_HASH)
            uncertain_command = command(key='synthetic:commit-uncertain')
            unknown = refused(lambda: uncertain.upsert(uncertain_command, operation_id=operation(90), expected_revision=0, observed_at=30), 'commit_unknown')
            unusable = refused(lambda: uncertain.reconcile(operation(90)), 'connection_unusable')
            reconciled = writer.reconcile(operation(90))
            before_replay = state(adapter)
            replayed = writer.upsert(uncertain_command, operation_id=operation(90), expected_revision=0, observed_at=30)
            checks['commit_unknown_reconciled_without_new_write'] = (unknown and uncertain_connection.armed is False and unusable and reconciled.status == 'committed'
                and replayed.replayed is True and replayed.resource_id == reconciled.resource_id and state(adapter) == before_replay)
        finally:
            uncertain_connection.close()

        legacy = writer.upsert(command(key='synthetic:unversioned'), operation_id=operation(95), expected_revision=0, observed_at=0)
        execute(adapter, statement('fixture.writer_remove_revision', 'DELETE FROM catalog_resource_revisions WHERE resource_id=?', 'DELETE FROM catalog_resource_revisions WHERE resource_id=%s'), (legacy.resource_id,))
        checks['unversioned_resource_refused'] = refused(lambda: writer.upsert(command(key='synthetic:unversioned'), operation_id=operation(96), expected_revision=1, observed_at=1), 'unversioned_resource')
        execute(adapter, enable, (0,))
        checks['disabled_write_refused_reconcile_available'] = checks['disabled_write_refused_reconcile_available'] and refused(lambda: writer.upsert(base, operation_id=operation(1), expected_revision=0, observed_at=0), 'write_disabled') and writer.reconcile(operation(1)).status == 'committed'
        return checks, private, result(created), result(equal), result(conflict)

    with tempfile.TemporaryDirectory(prefix='catalog-writer-contract-', dir=connect.fixture_root) as directory:
        sqlite_path = str(Path(directory) / 'catalog.sqlite3')
        def sqlite_connector(fault):
            connection = sqlite3.connect(sqlite_path, timeout=2, factory=FaultySQLite if fault else sqlite3.Connection)
            if fault: connection.armed = True
            return connection, SQLiteAdapter(connection)
        def postgres_connector(fault):
            connection = connect()
            if fault: connection = FaultyPostgres(connection)
            return connection, PostgresAdapter(connection)
        sqlite, sqlite_adapter = sqlite_connector(False)
        postgres, postgres_adapter = postgres_connector(False)
        try:
            sqlite.execute('PRAGMA journal_mode=WAL')
            sql_checks, sql_private, *sql_results = exercise(sqlite_adapter, sqlite_connector)
            pg_checks, pg_private, *pg_results = exercise(postgres_adapter, postgres_connector)
            checks = {key: sql_checks.get(key) is True and pg_checks.get(key) is True for key in CHECKS - {'unix_socket_only', 'sqlite_postgres_semantics_equal'}}
            checks['sqlite_postgres_semantics_equal'] = sql_private == pg_private and sql_results == pg_results
            with postgres_adapter.transaction(readonly=True) as session:
                transport = session.execute(statement('fixture.writer_transport',
                    "SELECT '' AS listeners,NULL AS server_address,NULL AS client_address",
                    "SELECT current_setting('listen_addresses') AS listeners,inet_server_addr() AS server_address,inet_client_addr() AS client_address", readonly=True)).rows[0]
            checks['unix_socket_only'] = transport['listeners'] == '' and transport['server_address'] is None and transport['client_address'] is None
            return checks, postgres.info.server_version
        finally:
            postgres.close()
            sqlite.close()


def _worker_main():
    """Private fixed-code child, never a public database-selecting CLI."""
    try:
        raw = sys.stdin.read(1025)
        if len(raw) > 1024:
            raise ValueError
        descriptor = json.loads(raw)
        if not isinstance(descriptor, dict) or set(descriptor) != {'socket'} or type(descriptor['socket']) is not str:
            raise ValueError
        pg = _harness()
        socket = Path(descriptor['socket'])
        if not socket.is_absolute() or socket.name != 'socket' or not socket.parent.name.startswith(pg.TEMP_PREFIX) or socket.parent.parent != Path('/private/tmp'):
            raise ValueError
        driver = pg._driver()
        def connect():
            return driver.connect(host=str(socket), port=pg.PORT, user='postgres', dbname='postgres',
                                  password='synthetic-unused-local-trust', connect_timeout=5,
                                  passfile=str(socket.parent / 'no-password-file'),
                                  options='-c statement_timeout=3000 -c lock_timeout=2000', autocommit=True)
        connect.fixture_root = socket.parent
        checks, server_version = _contracts(connect)
        print(json.dumps({'checks': checks, 'versions': {'postgresql_version_number': server_version,
                                                       'psycopg': driver.__version__}}, sort_keys=True, allow_nan=False))
        return 0
    except Exception:
        print(json.dumps({'error': 'rehearsal_failed'}))
        return 1


def _contract_child(descriptor, driver):
    pg = _harness()
    root = Path(__file__).resolve().parents[1]
    driver_root = Path(driver.__file__).resolve().parent.parent
    environment = dict(descriptor['environment'])
    environment['PYTHONPATH'] = os.pathsep.join((str(root), str(driver_root)))
    result = pg._run([sys.executable, '-B', '-c',
                      'from scripts.rehearse_catalog_writer_postgres import _worker_main; raise SystemExit(_worker_main())'],
                     environment, input=json.dumps({'socket': descriptor['socket']}), timeout=30)
    if result.stderr or len(result.stdout) > 8192:
        raise RehearsalError('invariant_failed')
    try:
        value = json.loads(result.stdout)
        if not isinstance(value, dict) or set(value) != {'checks', 'versions'}:
            raise ValueError
        versions = value['versions']
        if (not isinstance(versions, dict) or set(versions) != {'postgresql_version_number', 'psycopg'}
                or type(versions['postgresql_version_number']) is not int or not 100000 <= versions['postgresql_version_number'] <= 999999
                or type(versions['psycopg']) is not str or not re.fullmatch(r'[0-9]{1,2}\.[0-9]{1,2}\.[0-9]{1,3}', versions['psycopg'])):
            raise ValueError
        return value
    except (ValueError, TypeError):
        raise RehearsalError('invariant_failed') from None


def rehearse():
    """Run one fixed private fixture with no operating backend selection."""
    pg = _harness()
    started = time.monotonic()
    try:
        driver = pg._driver()
        tools = pg._tools()
        with pg._private_cluster(tools) as descriptor:
            contract = _contract_child(descriptor, driver)
        checks = contract['checks']
        if not CHECKS or not isinstance(checks, dict) or set(checks) != CHECKS or not all(value is True for value in checks.values()):
            raise RehearsalError('invariant_failed')
        return {'ok': True, 'profile': PROFILE, 'checks': checks, 'versions': contract['versions'],
                'elapsed_ms': round((time.monotonic() - started) * 1000, 3),
                'transport': 'private_unix_socket_only', 'cluster_stopped_and_removed': True,
                'limits': {'application_store_integrated': False, 'production_cutover': False,
                           'production_db_writes': 0, 'provider_calls': 0,
                           'search_or_embedding_engine_executed': False, 'same_key_contenders_per_backend': 4,
                           'rollback_fault_boundaries': 4, 'commit_fault_scope': 'injected_after_actual_commit',
                           'gap_free_generated_ids_asserted': False}}
    except pg.RehearsalError as exc:
        raise RehearsalError(exc.code) from None
    except RehearsalError:
        raise
    except Exception:
        raise RehearsalError() from None


class UsageError(ValueError):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError


class Once(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if getattr(namespace, self.dest, False):
            raise UsageError
        setattr(namespace, self.dest, True)


def main(argv=None):
    parser = Parser(prog='rehearse_catalog_writer_postgres', description=__doc__, allow_abbrev=False)
    parser.add_argument('--run', action=Once, nargs=0, default=False)
    status = 0
    try:
        args = parser.parse_args(argv)
        if args.run is not True:
            raise UsageError
        result = rehearse()
    except UsageError:
        result = {'ok': False, 'profile': PROFILE, 'error': 'invalid_arguments'}
        status = 2
    except RehearsalError as exc:
        result = {'ok': False, 'profile': PROFILE, 'error': exc.code}
        status = 1
    except Exception:
        result = {'ok': False, 'profile': PROFILE, 'error': 'rehearsal_failed'}
        status = 1
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return status


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
