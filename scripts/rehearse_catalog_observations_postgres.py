"""Explicit disposable observation/capture SQLite/PostgreSQL rehearsal.

Only synthetic rows in a fresh private Unix-socket cluster are used. No
operating database, DSN, application Store, provider or server is accepted.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import time

PROFILE = 'catalog-observations-postgres-rehearsal-v1'
CHECKS = frozenset(('unix_socket_only', 'legacy_owner_stamps_respected',
    'independent_owner_clocks', 'health_failure_and_recovery', 'health_receipt_window_counts',
    'survey_failure_preserves_tools', 'survey_without_full_clears_old_schema',
    'survey_invalidates_evaluation_freshness', 'evaluation_before_survey_refused',
    'registry_and_corpus_unchanged', 'revision_and_index_head_advance',
    'cache_invalidated_history_preserved', 'replay_and_conflict_receipts_stable',
    'operation_reuse_refused', 'same_revision_four_connection_single_winner',
    'accepted_sql_rollback_atomic', 'commit_unknown_fresh_reconcile',
    'disabled_write_reconcile_retained', 'consistent_native_capture_under_writer',
    'capture_excludes_owner_journal_and_worker_tokens', 'read_committed_capture_refused',
    'cross_database_comparison_aggregate_only', 'sqlite_postgres_observation_semantics_equal'))


class RehearsalError(ValueError):
    def __init__(self, code='rehearsal_failed'):
        self.code = code if code in ('dependency_unavailable', 'tools_unavailable', 'rehearsal_failed', 'invariant_failed') else 'rehearsal_failed'
        super().__init__(self.code)


def _harness():
    from scripts import rehearse_storage_adapter_postgres
    return rehearse_storage_adapter_postgres


def _contracts(connect):
    """Actual owner writes/capture transactions on explicit fixture connections."""
    import sqlite3
    from agent_market.catalog_observations import (CatalogObservations, ObservationError,
        HealthObservation, SurveyObservation, EvaluationObservation)
    from agent_market.catalog_observation_fixtures import seed, populate, operation, survey, private_state
    from agent_market.catalog_writer_fixtures import history_state
    from agent_market.catalog_index import CatalogIndex, MODEL_HASH
    from agent_market.catalog_index_outbox import CatalogIndexOutbox
    from agent_market.catalog_capture import capture_snapshot, compare_adapters
    from agent_market.storage_adapter import SQLiteAdapter, PostgresAdapter, Statement, StorageError

    def statement(name, sqlite, postgres=None, *, readonly=False):
        return Statement(name, sqlite, sqlite if postgres is None else postgres, readonly=readonly)
    def execute(adapter, stmt, params=(), *, readonly=False):
        with adapter.transaction(readonly=readonly) as session:
            return session.execute(stmt, params)
    resource = statement('fixture.observation_resource', 'SELECT * FROM resources WHERE id=?',
                         'SELECT * FROM resources WHERE id=%s', readonly=True)
    revision = statement('fixture.observation_revision', 'SELECT * FROM catalog_resource_revisions WHERE resource_id=?',
                         'SELECT * FROM catalog_resource_revisions WHERE resource_id=%s', readonly=True)
    cache = statement('fixture.observation_cache', 'SELECT COUNT(*) AS n FROM capability_eligibility', readonly=True)
    enable = statement('fixture.observation_enable', 'UPDATE catalog_write_controls SET enabled=?,revision=revision+1 WHERE id=1',
                         'UPDATE catalog_write_controls SET enabled=%s,revision=revision+1 WHERE id=1')
    def row(adapter, rid): return dict(execute(adapter, resource, (rid,), readonly=True).rows[0])
    def version(adapter, rid): return dict(execute(adapter, revision, (rid,), readonly=True).rows[0])
    def refused(action, code):
        try: action()
        except (ObservationError, StorageError) as exc: return exc.code == code
        return False

    class FaultySQLite(sqlite3.Connection):
        armed = False
        def commit(self):
            super().commit()
            if self.armed:
                self.armed = False
                raise RuntimeError('Synthetic committed observation acknowledgement fault')
    class FaultyPostgres:
        def __init__(self, connection): self._connection, self.armed = connection, True
        def __getattr__(self, name): return getattr(self._connection, name)
        def commit(self):
            self._connection.commit()
            if self.armed:
                self.armed = False
                raise RuntimeError('Synthetic committed observation acknowledgement fault')

    def exercise(adapter, connector):
        seed(adapter)
        created = populate(adapter)
        rid = created.resource_id
        observations = CatalogObservations(adapter)
        initial, initial_version = row(adapter, rid), version(adapter, rid)
        immutable = ('id', 'key', 'source', 'kind', 'url', 'name', 'description', 'category', 'active',
            'first_seen', 'last_seen', 'content_hash', 'auth_declared', 'auth_observed', 'auth_info', 'details',
            'networks', 'price_usdc', 'pay_to', 'method', 'calls_30d', 'payers_30d', 'last_called', 'host', 'desc_lang', 'regions')
        history = history_state(adapter)
        before_stale = private_state(adapter)
        checks = {'legacy_owner_stamps_respected': all((
            refused(lambda: observations.record(rid, HealthObservation('healthy'), operation_id=operation(1), expected_revision=1, observed_at=119), 'stale_observation'),
            refused(lambda: observations.record(rid, survey(), operation_id=operation(2), expected_revision=1, observed_at=129), 'stale_observation'),
            refused(lambda: observations.record(rid, EvaluationObservation(90, 'A', 'unknown'), operation_id=operation(3), expected_revision=1, observed_at=139), 'stale_observation')))
            and private_state(adapter) == before_stale}
        first = observations.record(rid, HealthObservation('healthy', 220), operation_id=operation(10), expected_revision=1, observed_at=200)
        after_health = row(adapter, rid)
        checks['cache_invalidated_history_preserved'] = (execute(adapter, cache, readonly=True).rows[0]['n'] == 0
            and all(history) and history_state(adapter) == history)
        observations.record(rid, survey(), operation_id=operation(11), expected_revision=2, observed_at=131)
        after_survey = row(adapter, rid)
        observations.record(rid, EvaluationObservation(88, 'B', 'review'), operation_id=operation(12), expected_revision=3, observed_at=150)
        after_eval = row(adapter, rid)
        checks['independent_owner_clocks'] = (first.revision == 2 and observations.current(rid, 'health').observed_at == 200
            and observations.current(rid, 'survey').observed_at == 131 and observations.current(rid, 'evaluation').observed_at == 150
            and after_health['cap_checked_at'] == 130 and after_health['eval_at'] == 140
            and after_survey['last_check_at'] == after_eval['last_check_at'] == 200)
        checks['survey_invalidates_evaluation_freshness'] = (after_survey['eval_at'] is None
            and after_survey['eval_grade'] == 'A' and after_survey['eval_score'] == 90
            and after_eval['eval_at'] == 150 and after_eval['cap_checked_at'] == 131)

        before_replay = private_state(adapter)
        replay = observations.record(rid, HealthObservation('healthy', 220), operation_id=operation(10), expected_revision=1, observed_at=200)
        conflict = observations.record(rid, HealthObservation('healthy'), operation_id=operation(13), expected_revision=1, observed_at=201)
        after_conflict = private_state(adapter)
        conflict_replay = observations.record(rid, HealthObservation('healthy'), operation_id=operation(13), expected_revision=1, observed_at=201)
        checks['replay_and_conflict_receipts_stable'] = (replay.replayed is True and replay.revision == 2
            and before_replay[0:7] == after_conflict[0:7] and conflict.status == 'conflict' and conflict.revision == 4
            and conflict_replay.replayed is True and private_state(adapter) == after_conflict)
        checks['operation_reuse_refused'] = refused(lambda: observations.record(rid, HealthObservation('fail'),
            operation_id=operation(10), expected_revision=1, observed_at=200), 'operation_conflict')
        current_revision = 4
        health_rows = []
        for number, outcome in enumerate(('fail', 'fail', 'fail', 'reachable')):
            value = observations.record(rid, HealthObservation(outcome), operation_id=operation(20+number),
                expected_revision=current_revision, observed_at=201+number)
            current_revision = value.revision
            health_rows.append(row(adapter, rid))
        checks['health_failure_and_recovery'] = (tuple(item['health_status'] for item in health_rows) == ('failing', 'failing', 'down', 'reachable')
            and tuple(item['consecutive_failures'] for item in health_rows) == (1, 2, 3, 0)
            and all(item['last_ok_at'] == 200 and item['failing_since'] == 201 for item in health_rows[:3])
            and health_rows[-1]['last_ok_at'] == 204 and health_rows[-1]['failing_since'] is None)
        checks['health_receipt_window_counts'] = health_rows[-1]['health_ok_24h'] == 2 and health_rows[-1]['health_n_24h'] == 5

        old_tools = row(adapter, rid)
        observations.record(rid, SurveyObservation(error_code='survey_failed'), operation_id=operation(30), expected_revision=current_revision, observed_at=151)
        current_revision += 1
        failed = row(adapter, rid)
        checks['survey_failure_preserves_tools'] = (failed['cap_checked_at'] is None and failed['eval_at'] is None
            and all(failed[key] == old_tools[key] for key in ('usage_tools', 'usage_tools_hash', 'usage_guide', 'usage_full_tools', 'usage_full_hash', 'eval_grade', 'eval_security'))
            and observations.current(rid, 'evaluation').observed_at == 150)
        rejected_before = private_state(adapter)
        checks['evaluation_before_survey_refused'] = refused(lambda: observations.record(rid, EvaluationObservation(80, 'B', 'ok'),
            operation_id=operation(31), expected_revision=current_revision, observed_at=150.5), 'stale_observation') and private_state(adapter) == rejected_before
        observations.record(rid, survey(full=False), operation_id=operation(32), expected_revision=current_revision, observed_at=152)
        current_revision += 1
        no_full = row(adapter, rid)
        checks['survey_without_full_clears_old_schema'] = (bool(old_tools['usage_full_tools']) and no_full['usage_full_tools'] is None
            and no_full['usage_full_hash'] is None and no_full['usage_tools'] == old_tools['usage_tools'] and no_full['eval_at'] is None)
        observations.record(rid, EvaluationObservation(85, 'B', 'unknown'), operation_id=operation(33), expected_revision=current_revision, observed_at=153)
        current_revision += 1

        barrier = threading.Barrier(4)
        def contender(number):
            connection, other = connector(False)
            try:
                barrier.wait(timeout=3)
                return CatalogObservations(other).record(rid, HealthObservation('healthy'), operation_id=operation(100+number),
                    expected_revision=current_revision, observed_at=500)
            finally: connection.close()
        with ThreadPoolExecutor(max_workers=4) as pool:
            races = list(pool.map(contender, range(4)))
        current_revision += 1
        checks['same_revision_four_connection_single_winner'] = (sum(value.status == 'committed' for value in races) == 1
            and sum(value.status == 'conflict' for value in races) == 3
            and all(value.resource_id == rid and value.revision == current_revision for value in races)
            and observations.current(rid, 'health').observed_at == 500)

        original_transaction = adapter.transaction
        rollback = []
        boundaries = ('catalog.observation_health', 'catalog.observation_revision', 'catalog.writer_invalidate',
            'catalog.index_enqueue', 'catalog.observation_clock', 'catalog.observation_receipt')
        for number, boundary in enumerate(boundaries):
            before, fired = private_state(adapter), [False]
            @contextmanager
            def fault_transaction(*args, **kwargs):
                with original_transaction(*args, **kwargs) as session:
                    original_execute = session.execute
                    def fault_execute(stmt, params=()):
                        result = original_execute(stmt, params)
                        if stmt.name == boundary:
                            fired[0] = True
                            raise RuntimeError('Synthetic accepted observation boundary fault')
                        return result
                    session.execute = fault_execute
                    yield session
            adapter.transaction = fault_transaction
            raised = False
            try:
                observations.record(rid, HealthObservation('healthy'), operation_id=operation(200+number), expected_revision=current_revision, observed_at=550)
            except RuntimeError: raised = True
            finally: del adapter.transaction
            rollback.append(raised and fired[0] and private_state(adapter) == before)
        checks['accepted_sql_rollback_atomic'] = len(rollback) == len(boundaries) and all(rollback)

        uncertain_connection, uncertain_adapter = connector(True)
        try:
            unknown = refused(lambda: CatalogObservations(uncertain_adapter).record(rid, EvaluationObservation(82, 'B', 'unknown'),
                operation_id=operation(300), expected_revision=current_revision, observed_at=154), 'commit_unknown')
            unusable = refused(lambda: CatalogObservations(uncertain_adapter).reconcile(operation(300)), 'connection_unusable')
            current_revision += 1
            before = private_state(adapter)
            fresh_connection, fresh_adapter = connector(False)
            try:
                fresh = CatalogObservations(fresh_adapter)
                receipt = fresh.reconcile(operation(300))
                head = fresh.current(rid, 'evaluation')
                checks['commit_unknown_fresh_reconcile'] = (unknown and unusable and uncertain_connection.armed is False
                    and receipt.status == 'committed' and receipt.revision == current_revision and head.observed_at == 154
                    and private_state(adapter) == before)
            finally: fresh_connection.close()
        finally: uncertain_connection.close()
        execute(adapter, enable, (0,))
        checks['disabled_write_reconcile_retained'] = (refused(lambda: observations.record(rid, HealthObservation('healthy'),
            operation_id=operation(301), expected_revision=current_revision, observed_at=551), 'write_disabled')
            and observations.reconcile(operation(300)).status == 'committed')
        execute(adapter, enable, (1,))

        if adapter.dialect == 'postgresql':
            ordinary_connection, ordinary = connector(False)
            try:
                denied = capture_snapshot(ordinary, role='candidate')
                checks['read_committed_capture_refused'] = not denied.complete and denied.issue == 'isolation_required' and denied.as_private_snapshot() is None
            finally: ordinary_connection.close()
        else:
            checks['read_committed_capture_refused'] = True
        reader_connection, reader = connector(False, repeatable=True)
        try:
            baseline = capture_snapshot(reader, role='candidate')
            original_reader_transaction = reader.transaction
            fired = [False]
            @contextmanager
            def writer_interleaving(*args, **kwargs):
                with original_reader_transaction(*args, **kwargs) as session:
                    original_execute = session.execute
                    def capture_execute(stmt, params=()):
                        value = original_execute(stmt, params)
                        if stmt.name == 'catalog.capture.resources' and not fired[0]:
                            fired[0] = True
                            observations.record(rid, HealthObservation('reachable'), operation_id=operation(400),
                                expected_revision=current_revision, observed_at=600)
                        return value
                    session.execute = capture_execute
                    yield session
            reader.transaction = writer_interleaving
            captured = capture_snapshot(reader, role='candidate')
            del reader.transaction
            newer = capture_snapshot(reader, role='candidate')
            current_revision += 1
            checks['consistent_native_capture_under_writer'] = (fired[0] and baseline.complete and captured.complete and newer.complete
                and captured.as_private_snapshot() == baseline.as_private_snapshot()
                and newer.as_private_snapshot()['resources'][0]['last_check_at'] == 600
                and newer.as_private_snapshot()['revisions'][0]['revision'] == current_revision)
            safe = newer.summary()
            private = newer.as_private_snapshot()
            checks['capture_excludes_owner_journal_and_worker_tokens'] = (safe['native_read_only'] is True and safe['repeatable_snapshot'] is True
                and safe['worker_tokens_captured'] is False and safe['observation_owner_clocks_or_journal_captured'] is False
                and safe['authority_or_evidence_verified'] is False and set(private) == {'resources', 'revisions', 'heads', 'jobs', 'projections'}
                and all('token' not in job and 'worker_id' not in job for job in private['jobs']))
        finally: reader_connection.close()

        final, final_version = row(adapter, rid), version(adapter, rid)
        checks['registry_and_corpus_unchanged'] = (all(final[key] == initial[key] for key in immutable)
            and all(final_version[key] == initial_version[key] for key in ('content_hash', 'hash_profile', 'corpus_hash', 'model_hash', 'updated_at'))
            and final_version['updated_at'] == final['last_seen'] == 100)
        outbox, index = CatalogIndexOutbox(adapter), CatalogIndex(adapter)
        claim = outbox.claim('synthetic-observation-indexer', now=610, lease_seconds=60)
        built = index.build(claim)
        checks['revision_and_index_head_advance'] = (final_version['revision'] == current_revision and claim.revision == current_revision
            and claim.corpus_hash == initial_version['corpus_hash'] and claim.model_hash == initial_version['model_hash']
            and index.publish(claim, built, now=611) == 'indexed' and tuple(hit.resource_id for hit in index.search('research')) == (rid,))
        checks['cache_invalidated_history_preserved'] = checks['cache_invalidated_history_preserved'] and history_state(adapter) == history and execute(adapter, cache, readonly=True).rows[0]['n'] == 0
        return checks, (tuple(final[key] for key in initial), tuple(final_version.values()),
            tuple((owner, observations.current(rid, owner).observed_at, observations.current(rid, owner).revision,
                   observations.current(rid, owner).outcome) for owner in ('health', 'survey', 'evaluation')))

    with tempfile.TemporaryDirectory(prefix='catalog-observations-contract-', dir=connect.fixture_root) as directory:
        sqlite_path = str(Path(directory) / 'catalog.sqlite3')
        def sqlite_connector(fault, *, repeatable=False):
            connection = sqlite3.connect(sqlite_path, timeout=2, factory=FaultySQLite if fault else sqlite3.Connection)
            if fault: connection.armed = True
            return connection, SQLiteAdapter(connection)
        def postgres_connector(fault, *, repeatable=False):
            connection = connect()
            if repeatable: connection.execute('SET SESSION CHARACTERISTICS AS TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            if fault: connection = FaultyPostgres(connection)
            return connection, PostgresAdapter(connection)
        sqlite, sqlite_adapter = sqlite_connector(False)
        postgres, postgres_adapter = postgres_connector(False)
        try:
            sqlite.execute('PRAGMA journal_mode=WAL')
            left_checks, left_state = exercise(sqlite_adapter, sqlite_connector)
            right_checks, right_state = exercise(postgres_adapter, postgres_connector)
            special = {'unix_socket_only', 'cross_database_comparison_aggregate_only', 'sqlite_postgres_observation_semantics_equal'}
            checks = {name: left_checks.get(name) is True and right_checks.get(name) is True for name in CHECKS - special}
            left_connection, left_reader = sqlite_connector(False, repeatable=True)
            right_connection, right_reader = postgres_connector(False, repeatable=True)
            try:
                report = compare_adapters(left_reader, right_reader, expected_model_hash=MODEL_HASH, source_role='candidate', candidate_role='candidate')
                text = json.dumps(report)
                counts = report['counts']
                checks['cross_database_comparison_aggregate_only'] = (report['complete'] is True and not report['issues']
                    and counts['candidate_hash_mismatch_rows'] == counts['revision_mismatch_rows'] == counts['head_mismatch_rows'] == 0
                    and counts['model_mismatch_rows'] == counts['current_projection_mismatch_rows'] == 0
                    and report['captures']['cross_source_atomic'] is False and report['captures']['sequential_independent_transactions'] is True
                    and all(marker not in text for marker in (MODEL_HASH, 'synthetic-private', 'synthetic:index:docs', 'https://', '/private/')))
            finally:
                left_connection.close()
                right_connection.close()
            checks['sqlite_postgres_observation_semantics_equal'] = left_state == right_state
            with postgres_adapter.transaction(readonly=True) as session:
                transport = session.execute(statement('fixture.observation_transport', "SELECT '' AS listeners,NULL AS server_address,NULL AS client_address",
                    "SELECT current_setting('listen_addresses') AS listeners,inet_server_addr() AS server_address,inet_client_addr() AS client_address", readonly=True)).rows[0]
            checks['unix_socket_only'] = transport['listeners'] == '' and transport['server_address'] is None and transport['client_address'] is None
            return checks, postgres.info.server_version
        finally:
            postgres.close()
            sqlite.close()

def _worker_main():
    """Private fixed-code clean-env child, not a database-selecting CLI."""
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
                      'from scripts.rehearse_catalog_observations_postgres import _worker_main; raise SystemExit(_worker_main())'],
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
    """Run one fixed private fixture, never choose an operating backend."""
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
                           'production_db_writes': 0, 'provider_or_embedding_calls': 0,
                           'observation_clocks_attested': False, 'synthetic_resources_per_backend': 1,
                           'rollback_fault_boundaries': 6, 'commit_fault_scope': 'injected_after_actual_commit',
                           'capture_scope': 'individually_repeatable_synthetic_database_snapshots',
                           'cross_database_atomic_snapshot': False, 'observation_owner_journal_captured': False}}
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
    parser = Parser(prog='rehearse_catalog_observations_postgres', description=__doc__, allow_abbrev=False)
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
