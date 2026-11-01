"""Explicit owned-copy catalog import on disposable SQLite/PostgreSQL targets.

Only fixed synthetic source copies and a fresh private Unix-socket cluster are
accepted. This CLI accepts no operating database, DSN, path or backend switch.
"""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time

PROFILE = 'catalog-copy-postgres-rehearsal-v1'
CHECKS = frozenset(('unix_socket_only', 'exact_subset_and_unsupported_domain_gate',
    'participating_source_writer_fenced', 'source_unchanged_by_import', 'source_capability_closed',
    'stable_ids_keys_and_times', 'strict_hash_and_legacy_provenance_distinct',
    'nulls_and_owner_tombstones_preserved', 'prospective_revision_and_index_heads',
    'no_authority_evidence_or_cache_restored', 'target_stays_disabled_after_import',
    'logical_rows_rollback_at_accepted_sql_boundaries', 'commit_unknown_fresh_reconcile',
    'exact_import_replay_unchanged', 'new_operation_existing_target_refused',
    'owner_revision_and_clock_stale_refused', 'fenced_actual_artifact_build',
    'inactive_source_not_searchable', 'typed_writer_generated_id_above_imports',
    'stale_artifact_cannot_replace_changed_registry', 'reopened_repeatable_capture',
    'changed_source_replay_refused', 'source_and_target_not_cross_database_atomic',
    'sqlite_postgres_copy_semantics_equal'))


class RehearsalError(ValueError):
    def __init__(self, code='rehearsal_failed'):
        self.code = code if code in ('dependency_unavailable', 'tools_unavailable', 'rehearsal_failed', 'invariant_failed') else 'rehearsal_failed'
        super().__init__(self.code)


def _harness():
    from scripts import rehearse_storage_adapter_postgres
    return rehearse_storage_adapter_postgres


def _contracts(connect):
    """Fixed source/target pairs; no operating Store or arbitrary connection input."""
    import sqlite3
    from agent_market.catalog_copy import CatalogCopy, CopyError, COPY_SCHEMA, TARGET_TABLES, source_snapshot
    from agent_market.catalog_copy_fixtures import seed_source, private_source_state, mutate_source, SOURCE_EPOCH
    from agent_market.catalog_observation_fixtures import seed as target_seed
    from agent_market.catalog_writer_fixtures import command, operation as writer_operation
    from agent_market.catalog_writer import CatalogWriter
    from agent_market.catalog_observations import CatalogObservations, HealthObservation, SurveyObservation, ObservationError
    from agent_market.catalog_index import CatalogIndex, MODEL_HASH
    from agent_market.catalog_index_outbox import CatalogIndexOutbox
    from agent_market.catalog_capture import capture_snapshot, compare_adapters
    from agent_market.storage_adapter import SQLiteAdapter, PostgresAdapter, Statement, StorageError
    from agent_market.catalog_shadow import RESOURCE_FIELDS, _proposed

    def op(number): return 'cp_' + format(number, '032x')
    def statement(name, sqlite, postgres=None, *, readonly=False):
        return Statement(name, sqlite, sqlite if postgres is None else postgres, readonly=readonly)
    def execute(adapter, stmt, params=(), *, readonly=False):
        with adapter.transaction(readonly=readonly) as session:
            return session.execute(stmt, params)
    def refused(action, codes):
        try: action()
        except (CopyError, ObservationError, StorageError) as exc: return exc.code in codes
        return False
    orders = ('id', 'resource_id', 'operation_id', 'id', 'resource_id', 'job_id', 'resource_id,model_hash',
        'resource_id', 'resource_id,term', 'resource_id,owner', 'operation_id', 'id', 'id',
        'version_id,contract_id', 'resource_id', 'operation_id', 'resource_id')
    reads = tuple(statement('fixture.copy_state' + str(number), 'SELECT * FROM ' + table + ' ORDER BY ' + order, readonly=True)
        for number, (table, order) in enumerate(zip(TARGET_TABLES, orders)))
    def state(adapter):
        with adapter.transaction(readonly=True) as session:
            return tuple(tuple(tuple(row) for row in session.execute(stmt).rows) for stmt in reads)
    def read(adapter, table, order):
        # Only internal fixed callsites supply these source-owned identifiers.
        return tuple(dict(row) for row in execute(adapter, statement('fixture.copy_read',
            'SELECT * FROM ' + table + ' ORDER BY ' + order, readonly=True), readonly=True).rows)
    control = statement('fixture.copy_control', 'UPDATE catalog_write_controls SET enabled=?,revision=revision+1 WHERE id=1',
        'UPDATE catalog_write_controls SET enabled=%s,revision=revision+1 WHERE id=1')
    exclusion = statement('fixture.copy_exclusion', "UPDATE catalog_copy_source_exclusions SET records=? WHERE domain='authority'",
        "UPDATE catalog_copy_source_exclusions SET records=%s WHERE domain='authority'")

    class FaultySQLite(sqlite3.Connection):
        armed = False
        def commit(self):
            super().commit()
            if self.armed:
                self.armed = False
                raise RuntimeError('Synthetic committed import acknowledgement fault')
    class FaultyPostgres:
        def __init__(self, connection): self._connection, self.armed = connection, True
        def __getattr__(self, name): return getattr(self._connection, name)
        def commit(self):
            self._connection.commit()
            if self.armed:
                self.armed = False
                raise RuntimeError('Synthetic committed import acknowledgement fault')

    def exercise(source_adapter, target_adapter, source_connector, target_connector):
        original_rows = seed_source(source_adapter)
        target_seed(target_adapter)
        with target_adapter.transaction() as session:
            for stmt in COPY_SCHEMA: session.execute(stmt)
            session.execute(control, (0,))
        target = CatalogCopy(target_adapter)
        unsupported = []
        for count in (1, None):
            execute(source_adapter, exclusion, (count,))
            try:
                with source_snapshot(source_adapter): pass
            except CopyError as exc:
                summary = exc.summary()
                unsupported.append(exc.code == 'unsupported_data' and summary['unsupported_domains']['authority'] == count
                    and summary['complete'] is False and summary['operating_cutover_authorized'] is False)
            else: unsupported.append(False)
        execute(source_adapter, exclusion, (0,))
        original_source = private_source_state(source_adapter)
        checks = {'exact_subset_and_unsupported_domain_gate': len(unsupported) == 2 and all(unsupported)
            and set(original_source) == {'resources', 'catalog_copy_source_control', 'catalog_copy_source_clocks', 'catalog_copy_source_exclusions'}}
        with source_snapshot(source_adapter) as source:
            summary = source.summary()
            other_connection, other_adapter = source_connector(short_lock=True)
            try:
                checks['participating_source_writer_fenced'] = refused(lambda: mutate_source(other_adapter),
                    ('statement_failed', 'transaction_failed')) and summary['participating_source_writers_fenced'] is True
            finally: other_connection.close()
            checks['source_and_target_not_cross_database_atomic'] = (summary['cross_database_atomic'] is False
                and summary['all_runtime_writers_excluded'] is False and summary['source_native_read_only_transaction'] is False
                and summary['source_rows_mutated'] is False)
        checks['source_capability_closed'] = refused(lambda: target.apply(source, operation_id=op(1)), ('source_closed',))

        boundaries = ('catalog.copy_insert_resource', 'catalog.copy_insert_revision', 'catalog.index_enqueue',
            'catalog.copy_insert_mapping', 'catalog.copy_insert_baseline', 'catalog.copy_sequence', 'catalog.copy_insert_receipt')
        original_transaction = target_adapter.transaction
        rollbacks = []
        for boundary in boundaries:
            before, fired = state(target_adapter), [False]
            @contextmanager
            def fault_transaction(*args, **kwargs):
                with original_transaction(*args, **kwargs) as session:
                    original_execute = session.execute
                    def fault_execute(stmt, params=()):
                        value = original_execute(stmt, params)
                        if stmt.name == boundary:
                            fired[0] = True
                            raise RuntimeError('Synthetic accepted import SQL boundary fault')
                        return value
                    session.execute = fault_execute
                    yield session
            target_adapter.transaction = fault_transaction
            raised = False
            try:
                with source_snapshot(source_adapter) as source:
                    target.apply(source, operation_id=op(1))
            except RuntimeError: raised = True
            finally: del target_adapter.transaction
            rollbacks.append(raised and fired[0] and state(target_adapter) == before
                and private_source_state(source_adapter) == original_source and target.reconcile(op(1)) is None)
        checks['logical_rows_rollback_at_accepted_sql_boundaries'] = len(rollbacks) == 7 and all(rollbacks)

        uncertain_connection, uncertain_adapter = target_connector(True)
        try:
            with source_snapshot(source_adapter) as source:
                unknown = refused(lambda: CatalogCopy(uncertain_adapter).apply(source, operation_id=op(1)), ('commit_unknown',))
            unusable = refused(lambda: CatalogCopy(uncertain_adapter).reconcile(op(1)), ('connection_unusable',))
            fresh_connection, fresh_adapter = target_connector(False)
            try:
                receipt = CatalogCopy(fresh_adapter).reconcile(op(1))
                checks['commit_unknown_fresh_reconcile'] = (unknown and unusable and uncertain_connection.armed is False
                    and receipt.status == 'committed' and receipt.replayed is False and receipt.resources == 2
                    and receipt.initial_revision == SOURCE_EPOCH + 1 and receipt.source_epoch == SOURCE_EPOCH)
            finally: fresh_connection.close()
        finally: uncertain_connection.close()
        imported = read(target_adapter, 'resources', 'id')
        mappings = read(target_adapter, 'catalog_copy_mappings', 'resource_id')
        versions = read(target_adapter, 'catalog_resource_revisions', 'resource_id')
        heads = read(target_adapter, 'catalog_observation_heads', 'resource_id,owner')
        checks['stable_ids_keys_and_times'] = (tuple(row['id'] for row in imported) == (7, 41)
            and all(tuple(row[key] for key in ('id', 'key', 'first_seen', 'last_seen', 'active')) ==
                tuple(raw[key] for key in ('id', 'key', 'first_seen', 'last_seen', 'active')) for row, raw in zip(imported, original_rows)))
        checks['strict_hash_and_legacy_provenance_distinct'] = (len(mappings) == 2 and all(
            mapping['source_hash'] == raw['content_hash'] and mapping['proposed_hash'] == row['content_hash']
            and mapping['source_hash'] != mapping['proposed_hash'] and _proposed(raw, hashes=True)[1] == row['content_hash']
            and mapping['initial_revision'] == SOURCE_EPOCH+1 for mapping, row, raw in zip(mappings, imported, original_rows)))
        checks['nulls_and_owner_tombstones_preserved'] = (all(row[key] is None for row in imported for key in ('auth_declared', 'auth_observed', 'auth_info'))
            and imported[0]['cap_checked_at'] is None and imported[0]['eval_at'] is None
            and imported[1]['health_status'] is None and imported[1]['eval_grade'] is None
            and tuple((head['owner'], head['observed_at'], head['outcome'], head['revision'], head['operation_id']) for head in heads) ==
                (('evaluation', 140.0, 'recorded', SOURCE_EPOCH+1, op(1)), ('health', 120.0, 'reachable', SOURCE_EPOCH+1, op(1)),
                 ('survey', 150.0, 'failed', SOURCE_EPOCH+1, op(1))))
        index_heads = read(target_adapter, 'catalog_index_heads', 'resource_id')
        checks['prospective_revision_and_index_heads'] = (len(versions) == len(index_heads) == 2
            and all(version['revision'] == head['revision'] == SOURCE_EPOCH+1
                and version['content_hash'] == row['content_hash'] and version['updated_at'] == row['last_seen']
                and version['corpus_hash'] == head['corpus_hash'] and version['model_hash'] == head['model_hash'] == MODEL_HASH
                for version, head, row in zip(versions, index_heads, imported)))
        excluded_tables = ('catalog_write_operations', 'catalog_observation_operations', 'connection_versions',
            'capability_evidence', 'capability_approvals', 'capability_eligibility')
        checks['no_authority_evidence_or_cache_restored'] = all(not read(target_adapter, table, '1') for table in excluded_tables)
        checks['target_stays_disabled_after_import'] = read(target_adapter, 'catalog_write_controls', 'id')[0]['enabled'] == 0
        before = state(target_adapter)
        with source_snapshot(source_adapter) as source:
            replay = target.apply(source, operation_id=op(1))
            new_operation_refused = refused(lambda: target.apply(source, operation_id=op(2)), ('target_not_empty',))
        checks['exact_import_replay_unchanged'] = replay.replayed is True and replay.initial_revision == SOURCE_EPOCH+1 and state(target_adapter) == before
        checks['new_operation_existing_target_refused'] = new_operation_refused and state(target_adapter) == before
        checks['source_unchanged_by_import'] = private_source_state(source_adapter) == original_source

        execute(target_adapter, control, (1,))
        observations = CatalogObservations(target_adapter)
        old = observations.record(7, HealthObservation('healthy'), operation_id='ob_' + '1' * 32,
            expected_revision=SOURCE_EPOCH, observed_at=200)
        stale_before = state(target_adapter)
        checks['owner_revision_and_clock_stale_refused'] = (old.status == 'conflict' and old.revision == SOURCE_EPOCH+1
            and refused(lambda: observations.record(7, SurveyObservation(), operation_id='ob_'+'2'*32,
                expected_revision=SOURCE_EPOCH+1, observed_at=149), ('stale_observation',)) and state(target_adapter) == stale_before)
        outbox, index = CatalogIndexOutbox(target_adapter), CatalogIndex(target_adapter)
        artifacts = []
        for number in range(2):
            claim = outbox.claim('synthetic-copy-indexer', now=200+number, lease_seconds=60)
            artifact = index.build(claim)
            if index.publish(claim, artifact, now=200.5+number) != 'indexed': raise RehearsalError('invariant_failed')
            artifacts.append(artifact)
        checks['fenced_actual_artifact_build'] = (len(artifacts) == 2 and {artifact.resource_id for artifact in artifacts} == {7, 41}
            and all(artifact.revision == SOURCE_EPOCH+1 and index.artifact(artifact.resource_id) == artifact for artifact in artifacts)
            and tuple(hit.resource_id for hit in index.search('news')) == (7,))
        checks['inactive_source_not_searchable'] = not index.search('archived') and not index.search('documentation')
        writer = CatalogWriter(target_adapter, model_hash=MODEL_HASH)
        new_row = writer.upsert(command(key='synthetic:owned-copy:new', name='New Synthetic Resource', description='New reference'),
            operation_id=writer_operation(4000), expected_revision=0, observed_at=200)
        checks['typed_writer_generated_id_above_imports'] = new_row.status == 'committed' and new_row.resource_id > 41 and len(read(target_adapter, 'resources', 'id')) == 3
        # Consume the new resource job before reserving the changed source job.
        new_claim = outbox.claim('synthetic-copy-new-row', now=202, lease_seconds=60)
        if new_claim.resource_id != new_row.resource_id or index.publish(new_claim, index.build(new_claim), now=202.1) != 'indexed':
            raise RehearsalError('invariant_failed')
        base = original_rows[0]
        from agent_market.catalog_writer import RegistryUpsert
        normalized = _proposed(base, hashes=True)[0]
        def replacement(description):
            return RegistryUpsert(key=base['key'], source=base['source'], kind=base['kind'], url=base['url'], name=base['name'],
                description=description, category=base['category'], networks=(), details_json=normalized['details'],
                calls_30d=base['calls_30d'], payers_30d=base['payers_30d'], desc_lang=base['desc_lang'])
        first_update = writer.upsert(replacement('Intermediate reference removedterm'), operation_id=writer_operation(4001),
            expected_revision=SOURCE_EPOCH+1, observed_at=210)
        old_claim = outbox.claim('synthetic-copy-old-index', now=211, lease_seconds=60)
        old_artifact = index.build(old_claim)
        writer.upsert(replacement('Current research reference'), operation_id=writer_operation(4002),
            expected_revision=first_update.revision, observed_at=212)
        checks['stale_artifact_cannot_replace_changed_registry'] = (index.publish(old_claim, old_artifact, now=212.1) == 'superseded'
            and not index.search('removedterm') and index.artifact(7) is None)
        fresh_claim = outbox.claim('synthetic-copy-current-index', now=213, lease_seconds=60)
        if index.publish(fresh_claim, index.build(fresh_claim), now=213.1) != 'indexed': raise RehearsalError('invariant_failed')
        checks['stale_artifact_cannot_replace_changed_registry'] = checks['stale_artifact_cannot_replace_changed_registry'] and not index.search('removedterm')
        reopened_connection, reopened = target_connector(False, repeatable=True)
        try:
            captured = capture_snapshot(reopened, role='candidate')
            checks['reopened_repeatable_capture'] = (captured.complete and captured.summary()['native_read_only'] is True
                and tuple(row['id'] for row in captured.as_private_snapshot()['resources']) == (7, 41, new_row.resource_id)
                and captured.summary()['authority_or_evidence_verified'] is False
                and CatalogCopy(reopened).reconcile(op(1)).resources == 2)
        finally: reopened_connection.close()
        before = state(target_adapter)
        mutate_source(source_adapter)
        with source_snapshot(source_adapter) as source:
            checks['changed_source_replay_refused'] = refused(lambda: target.apply(source, operation_id=op(1)), ('operation_conflict',))
        checks['changed_source_replay_refused'] = checks['changed_source_replay_refused'] and state(target_adapter) == before
        return checks, tuple(tuple(row[key] for key in RESOURCE_FIELDS) for row in imported), tuple(tuple(row.values()) for row in versions)

    with tempfile.TemporaryDirectory(prefix='catalog-copy-contract-', dir=connect.fixture_root) as directory:
        source_path = str(Path(directory) / 'source.sqlite3')
        target_path = str(Path(directory) / 'target.sqlite3')
        def sqlite_source_connector(*, short_lock=False):
            connection = sqlite3.connect(source_path, timeout=.1 if short_lock else 2)
            return connection, SQLiteAdapter(connection)
        def sqlite_target_connector(fault, *, repeatable=False):
            connection = sqlite3.connect(target_path, timeout=2, factory=FaultySQLite if fault else sqlite3.Connection)
            if fault: connection.armed = True
            return connection, SQLiteAdapter(connection)
        def postgres_source_connector(*, short_lock=False):
            connection = connect.source()
            if short_lock: connection.execute('SET lock_timeout=100')
            return connection, PostgresAdapter(connection)
        def postgres_target_connector(fault, *, repeatable=False):
            connection = connect()
            if repeatable: connection.execute('SET SESSION CHARACTERISTICS AS TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            if fault: connection = FaultyPostgres(connection)
            return connection, PostgresAdapter(connection)
        creator = connect()
        try: creator.execute('CREATE DATABASE catalog_copy_source')
        finally: creator.close()
        sqlite_source, left_source = sqlite_source_connector()
        sqlite_target, left_target = sqlite_target_connector(False)
        postgres_source, right_source = postgres_source_connector()
        postgres_target, right_target = postgres_target_connector(False)
        try:
            sqlite_source.execute('PRAGMA journal_mode=WAL')
            sqlite_target.execute('PRAGMA journal_mode=WAL')
            left_checks, left_rows, left_versions = exercise(left_source, left_target, sqlite_source_connector, sqlite_target_connector)
            right_checks, right_rows, right_versions = exercise(right_source, right_target, postgres_source_connector, postgres_target_connector)
            special = {'unix_socket_only', 'sqlite_postgres_copy_semantics_equal'}
            checks = {name: left_checks.get(name) is True and right_checks.get(name) is True for name in CHECKS - special}
            left_connection, left_capture = sqlite_target_connector(False, repeatable=True)
            right_connection, right_capture = postgres_target_connector(False, repeatable=True)
            try:
                compared = compare_adapters(left_capture, right_capture, expected_model_hash=MODEL_HASH, source_role='candidate', candidate_role='candidate')
                checks['sqlite_postgres_copy_semantics_equal'] = (left_rows == right_rows and left_versions == right_versions
                    and compared['complete'] is True and not compared['issues']
                    and compared['counts']['candidate_hash_mismatch_rows'] == compared['counts']['revision_mismatch_rows'] == 0
                    and compared['captures']['cross_source_atomic'] is False)
            finally:
                left_connection.close()
                right_connection.close()
            with right_target.transaction(readonly=True) as session:
                transport = session.execute(statement('fixture.copy_transport', "SELECT '' AS listeners,NULL AS server_address,NULL AS client_address",
                    "SELECT current_setting('listen_addresses') AS listeners,inet_server_addr() AS server_address,inet_client_addr() AS client_address", readonly=True)).rows[0]
            checks['unix_socket_only'] = transport['listeners'] == '' and transport['server_address'] is None and transport['client_address'] is None
            return checks, postgres_target.info.server_version
        finally:
            postgres_target.close()
            postgres_source.close()
            sqlite_target.close()
            sqlite_source.close()


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
        def private_connect(database):
            if database not in ('postgres', 'catalog_copy_source'): raise ValueError
            return driver.connect(host=str(socket), port=pg.PORT, user='postgres', dbname=database,
                                  password='synthetic-unused-local-trust', connect_timeout=5,
                                  passfile=str(socket.parent / 'no-password-file'),
                                  options='-c statement_timeout=3000 -c lock_timeout=2000', autocommit=True)
        def connect(): return private_connect('postgres')
        connect.source = lambda: private_connect('catalog_copy_source')
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
                      'from scripts.rehearse_catalog_copy_postgres import _worker_main; raise SystemExit(_worker_main())'],
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
                           'synthetic_source_resources': 2, 'cross_database_atomic_snapshot': False,
                           'full_store_import_supported': False, 'authority_restored': False,
                           'rollback_fault_boundaries': 7, 'sequence_rollback_or_gap_free_ids_claimed': False,
                           'source_fence_scope': 'sqlite_write_reservation_or_postgres_cooperating_control_row',
                           'commit_fault_scope': 'injected_after_actual_commit'}}
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
    parser = Parser(prog='rehearse_catalog_copy_postgres', description=__doc__, allow_abbrev=False)
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
