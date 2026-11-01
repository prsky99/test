"""Explicit disposable lexical-artifact/index/shadow SQLite/PostgreSQL rehearsal.

No operating database, DSN, provider, application server, embedding model or
legacy FTS/vector engine is accepted. PostgreSQL cleanup uses the existing
private Unix-socket cluster contract. All source records are synthetic.
"""
import argparse
from contextlib import contextmanager
import copy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time

PROFILE = 'catalog-index-postgres-rehearsal-v1'
CHECKS = frozenset(('unix_socket_only', 'actual_artifact_bodies_and_postings', 'exact_and_stable_id_search',
    'kind_and_limit_filters', 'private_text_not_materialized', 'tool_text_outside_declared_corpus',
    'current_resource_search_gates', 'stale_revision_publish_refused', 'removed_terms_not_searchable',
    'expired_claim_fenced', 'stale_model_publish_refused', 'unsupported_model_not_materialized',
    'atomic_body_postings_ack_rollback', 'commit_unknown_reconciled_read_only', 'reopen_preserves_artifacts',
    'tampered_artifact_refused', 'forged_posting_not_returned', 'shadow_assessed_declared_hash_replacement',
    'shadow_drift_and_malformed_explicit', 'shadow_private_inputs_unchanged', 'shadow_output_aggregate_only',
    'sqlite_postgres_artifact_and_search_equal'))


class RehearsalError(ValueError):
    def __init__(self, code='rehearsal_failed'):
        self.code = code if code in ('dependency_unavailable', 'tools_unavailable', 'rehearsal_failed', 'invariant_failed') else 'rehearsal_failed'
        super().__init__(self.code)


def _harness():
    from scripts import rehearse_storage_adapter_postgres
    return rehearse_storage_adapter_postgres


def _contracts(connect):
    """Fixed actual-artifact comparison, with no operating Store initializer."""
    import sqlite3
    from agent_market.catalog_index import CatalogIndex, IndexArtifactError, MODEL_HASH
    from agent_market.catalog_index_outbox import CatalogIndexOutbox
    from agent_market.catalog_writer import CatalogWriter
    from agent_market.catalog_writer_fixtures import operation, URL
    from agent_market.catalog_index_fixtures import seed, populate, commands, snapshot, declared_legacy_snapshot
    from agent_market.catalog_shadow import compare_snapshots
    from agent_market.storage_adapter import SQLiteAdapter, PostgresAdapter, Statement, StorageError

    def statement(name, sqlite, postgres=None, *, readonly=False):
        return Statement(name, sqlite, sqlite if postgres is None else postgres, readonly=readonly)
    def execute(adapter, stmt, params=(), *, readonly=False):
        with adapter.transaction(readonly=readonly) as session:
            return session.execute(stmt, params)
    tables = (('resources', 'id'), ('catalog_resource_revisions', 'resource_id'),
              ('catalog_index_heads', 'resource_id'), ('catalog_index_jobs', 'job_id'),
              ('catalog_index_projections', 'resource_id,model_hash'), ('catalog_write_operations', 'operation_id'),
              ('catalog_index_artifacts', 'resource_id'), ('catalog_index_terms', 'resource_id,term'))
    read_state = tuple(statement('fixture.index_state' + str(number), 'SELECT * FROM ' + table + ' ORDER BY ' + order, readonly=True)
                       for number, (table, order) in enumerate(tables))
    bodies = statement('fixture.index_bodies', 'SELECT * FROM catalog_index_artifacts ORDER BY resource_id', readonly=True)
    postings = statement('fixture.index_postings', 'SELECT resource_id,term FROM catalog_index_terms ORDER BY resource_id,term', readonly=True)
    def state(adapter):
        with adapter.transaction(readonly=True) as session:
            return tuple(tuple(tuple(row) for row in session.execute(stmt).rows) for stmt in read_state)
    def actual_rows(adapter):
        with adapter.transaction(readonly=True) as session:
            return (tuple(tuple(row) for row in session.execute(bodies).rows),
                    tuple(tuple(row) for row in session.execute(postings).rows))
    def ids(hits):
        return tuple(hit.resource_id for hit in hits)
    def rejected(action, code):
        try:
            action()
        except (IndexArtifactError, StorageError) as exc:
            return exc.code == code
        return False

    class FaultySQLite(sqlite3.Connection):
        armed = False
        def commit(self):
            super().commit()
            if self.armed:
                self.armed = False
                raise RuntimeError('Synthetic committed-artifact acknowledgement fault')
    class FaultyPostgres:
        def __init__(self, connection): self._connection, self.armed = connection, True
        def __getattr__(self, name): return getattr(self._connection, name)
        def commit(self):
            self._connection.commit()
            if self.armed:
                self.armed = False
                raise RuntimeError('Synthetic committed-artifact acknowledgement fault')

    def exercise(adapter, connector):
        seed(adapter)
        resources = populate(adapter)
        originals = commands()
        writer = CatalogWriter(adapter, model_hash=MODEL_HASH)
        outbox = CatalogIndexOutbox(adapter)
        index = CatalogIndex(adapter)
        built = []
        for number in range(4):
            claim = outbox.claim('synthetic-materializer', now=110, lease_seconds=60)
            artifact = index.build(claim)
            if index.publish(claim, artifact, now=111 + number) != 'indexed':
                raise RehearsalError('invariant_failed')
            built.append(artifact)
        actual_bodies, actual_terms = actual_rows(adapter)
        checks = {'actual_artifact_bodies_and_postings': len(actual_bodies) == 4 and bool(actual_terms)
            and all(index.artifact(artifact.resource_id) == artifact
                    and tuple(row[1] for row in actual_terms if row[0] == artifact.resource_id) == artifact.terms for artifact in built)}
        checks['exact_and_stable_id_search'] = (ids(index.search('research')) == (1, 2, 4)
            and ids(index.search('SCIENCE research')) == (1, 4)
            and ids(index.search('documentation agent')) == (2,)
            and not index.search('research OR missing') and not index.search('missing'))
        checks['kind_and_limit_filters'] = ids(index.search('research', kind='mcp')) == (1,) and ids(index.search('research', limit=1)) == (1,)
        document_text = json.dumps([artifact.document for artifact in built])
        forbidden = (URL, 'syntheticsecret', 'private@example.invalid', 'synthetic-private-auth', 'private_tool_label', 'https://', '@')
        checks['private_text_not_materialized'] = all(value not in document_text for value in forbidden) and not index.search('syntheticsecret') and not index.search('provider')
        before_tool = index.artifact(1)
        execute(adapter, statement('fixture.index_tool_change',
            "UPDATE resources SET usage_tools='[{\"name\":\"replacement_tool\"}]' WHERE id=?",
            "UPDATE resources SET usage_tools='[{\"name\":\"replacement_tool\"}]' WHERE id=%s"), (1,))
        checks['tool_text_outside_declared_corpus'] = index.artifact(1) == before_tool and not index.search('replacement') and not index.search('tool')
        gate = statement('fixture.index_gates', 'UPDATE resources SET active=?,health_status=?,eval_security=? WHERE id=?',
                         'UPDATE resources SET active=%s,health_status=%s,eval_security=%s WHERE id=%s')
        gated = []
        for active, health, security in ((0, 'healthy', 'unknown'), (1, 'down', 'unknown'), (1, 'healthy', 'quarantine')):
            execute(adapter, gate, (active, health, security, 1))
            gated.append(ids(index.search('research')) == (2, 4))
        execute(adapter, gate, (1, 'healthy', 'unknown', 1))
        checks['current_resource_search_gates'] = all(gated) and ids(index.search('research')) == (1, 2, 4)

        intermediate = replace(originals[2], name='Intermediate Field', description='intermediate reference manual')
        writer.upsert(intermediate, operation_id=operation(2000), expected_revision=1, observed_at=200)
        old_claim = outbox.claim('synthetic-obsolete-revision', now=200.1, lease_seconds=60)
        old_artifact = index.build(old_claim)
        current = replace(originals[2], name='Current Field', description='current reference manual')
        writer.upsert(current, operation_id=operation(2001), expected_revision=2, observed_at=201)
        checks['stale_revision_publish_refused'] = index.publish(old_claim, old_artifact, now=201.1) == 'superseded' and index.artifact(3) is None
        checks['removed_terms_not_searchable'] = not index.search('removedterm')
        expiring = outbox.claim('synthetic-expiring-claim', now=210, lease_seconds=1)
        expired_artifact = index.build(expiring)
        fresh = outbox.claim('synthetic-reclaimed-claim', now=212, lease_seconds=20)
        fresh_artifact = index.build(fresh)
        checks['expired_claim_fenced'] = (fresh.job_id == expiring.job_id and fresh.fence == expiring.fence + 1
            and fresh.token != expiring.token and index.publish(expiring, expired_artifact, now=212.1) == 'stale_claim'
            and index.publish(fresh, fresh_artifact, now=212.2) == 'indexed')
        checks['removed_terms_not_searchable'] = checks['removed_terms_not_searchable'] and not index.search('removedterm') and ids(index.search('current')) == (3,) and 'removedterm' not in index.artifact(3).terms

        writer.upsert(originals[0], operation_id=operation(2010), expected_revision=1, observed_at=220)
        model_claim = outbox.claim('synthetic-old-model', now=220.1, lease_seconds=60)
        model_artifact = index.build(model_claim)
        other_model = hashlib.sha256(b'synthetic-unsupported-model').hexdigest()
        CatalogWriter(adapter, model_hash=other_model).upsert(originals[0], operation_id=operation(2011), expected_revision=2, observed_at=221)
        checks['stale_model_publish_refused'] = index.publish(model_claim, model_artifact, now=221.1) == 'superseded' and index.artifact(1) is None and ids(index.search('news')) == (4,)
        unsupported = outbox.claim('synthetic-unsupported-model', now=222, lease_seconds=60)
        checks['unsupported_model_not_materialized'] = rejected(lambda: index.build(unsupported), 'unsupported_model') and outbox.fail(unsupported, 'invalid_projection', now=222.1) == 'failed'
        writer.upsert(originals[0], operation_id=operation(2012), expected_revision=3, observed_at=223)
        restored_claim = outbox.claim('synthetic-supported-model', now=224, lease_seconds=60)
        checks['unsupported_model_not_materialized'] = checks['unsupported_model_not_materialized'] and index.publish(restored_claim, index.build(restored_claim), now=224.1) == 'indexed'

        rollback_checks = []
        original_transaction = adapter.transaction
        for number, boundary in enumerate(('catalog.index_publish_metadata', 'catalog.artifact_save', 'catalog.artifact_clear_terms', 'catalog.artifact_add_term')):
            revision = 1 + number
            update = replace(originals[1], description='atomic rollback marker ' + str(number) + ' research guides')
            writer.upsert(update, operation_id=operation(2100 + number), expected_revision=revision, observed_at=300 + number)
            claim = outbox.claim('synthetic-rollback-worker', now=310 + number, lease_seconds=60)
            artifact = index.build(claim)
            before = state(adapter)
            fired = [False]
            @contextmanager
            def fault_transaction(*args, **kwargs):
                with original_transaction(*args, **kwargs) as session:
                    original_execute = session.execute
                    def fault_execute(stmt, params=()):
                        value = original_execute(stmt, params)
                        if stmt.name == boundary:
                            fired[0] = True
                            raise RuntimeError('Synthetic atomic artifact boundary fault')
                        return value
                    session.execute = fault_execute
                    yield session
            adapter.transaction = fault_transaction
            raised = False
            try:
                index.publish(claim, artifact, now=310 + number + .1)
            except RuntimeError:
                raised = True
            finally:
                del adapter.transaction
            rollback_checks.append(raised and fired[0] and state(adapter) == before and outbox.job(claim.job_id).state == 'claimed')
            if index.publish(claim, artifact, now=310 + number + .2) != 'indexed':
                raise RehearsalError('invariant_failed')
        checks['atomic_body_postings_ack_rollback'] = len(rollback_checks) == 4 and all(rollback_checks)

        uncertain = replace(originals[3], description='uncertain committed research artifact')
        writer.upsert(uncertain, operation_id=operation(2200), expected_revision=1, observed_at=400)
        claim = outbox.claim('synthetic-commit-ack-worker', now=401, lease_seconds=60)
        artifact = index.build(claim)
        uncertain_connection, uncertain_adapter = connector(True)
        try:
            uncertain_index = CatalogIndex(uncertain_adapter)
            unknown = rejected(lambda: uncertain_index.publish(claim, artifact, now=402), 'commit_unknown')
            unusable = rejected(lambda: uncertain_index.artifact(4), 'connection_unusable')
            before = state(adapter)
            checks['commit_unknown_reconciled_read_only'] = (unknown and uncertain_connection.armed is False and unusable
                and index.artifact(4) == artifact and outbox.job(claim.job_id).state == 'indexed'
                and ids(index.search('uncertain')) == (4,) and state(adapter) == before)
        finally:
            uncertain_connection.close()
        reopened, reopened_adapter = connector(False)
        try:
            before = state(adapter)
            reader = CatalogIndex(reopened_adapter)
            checks['reopen_preserves_artifacts'] = reader.artifact(4) == artifact and ids(reader.search('current')) == (3,) and ids(reader.search('uncertain')) == (4,) and state(adapter) == before
        finally:
            reopened.close()
        corrupt = statement('fixture.index_corrupt_document', 'UPDATE catalog_index_artifacts SET document=? WHERE resource_id=?',
                            'UPDATE catalog_index_artifacts SET document=%s WHERE resource_id=%s')
        execute(adapter, corrupt, (artifact.document + ' ', 4))
        checks['tampered_artifact_refused'] = rejected(lambda: index.artifact(4), 'invalid_record')
        execute(adapter, corrupt, (artifact.document, 4))
        execute(adapter, statement('fixture.index_forge_posting', 'INSERT INTO catalog_index_terms VALUES (?,?)',
            'INSERT INTO catalog_index_terms VALUES (%s,%s)'), (4, 'forged'))
        checks['forged_posting_not_returned'] = rejected(lambda: index.search('forged'), 'invalid_record')
        execute(adapter, statement('fixture.index_clear_forgery', 'DELETE FROM catalog_index_terms WHERE resource_id=? AND term=?',
            'DELETE FROM catalog_index_terms WHERE resource_id=%s AND term=%s'), (4, 'forged'))

        candidate = snapshot(adapter)
        source = declared_legacy_snapshot(candidate)
        source_before, candidate_before = copy.deepcopy(source), copy.deepcopy(candidate)
        report = compare_snapshots(source, candidate, expected_model_hash=MODEL_HASH)
        counts = report['counts']
        checks['shadow_assessed_declared_hash_replacement'] = (report['complete'] is True and not report['issues']
            and counts['matched_identity_rows'] == counts['expected_profile_hash_replacement_rows'] == 4
            and counts['candidate_hash_mismatch_rows'] == counts['revision_mismatch_rows'] == counts['corpus_mismatch_rows'] == 0
            and counts['model_mismatch_rows'] == counts['head_mismatch_rows'] == counts['current_projection_mismatch_rows'] == 0
            and counts['current_job_indexed_rows'] == 4 and report['scope']['legacy_hash_recomputed'] is False)
        drifted = copy.deepcopy(candidate)
        drifted['resources'][0]['url'] = 'https://synthetic-drift.example/mcp'
        drift = compare_snapshots(source, drifted, expected_model_hash=MODEL_HASH)
        malformed = copy.deepcopy(candidate)
        malformed['resources'] = ({'id': 1},)
        incomplete = compare_snapshots(source, malformed, expected_model_hash=MODEL_HASH)
        checks['shadow_drift_and_malformed_explicit'] = (drift['complete'] is True and drift['counts']['candidate_hash_mismatch_rows'] == 1
            and incomplete['complete'] is False and incomplete['issues'] and all(value is None for value in incomplete['counts'].values()))
        checks['shadow_private_inputs_unchanged'] = source == source_before and candidate == candidate_before and snapshot(adapter) == candidate
        rendered = json.dumps((report, drift, incomplete))
        checks['shadow_output_aggregate_only'] = (all(raw['key'] not in rendered and raw['url'] not in rendered for raw in candidate['resources'])
            and MODEL_HASH not in rendered and 'syntheticsecret' not in rendered and report['scope']['writes_performed'] == 0
            and report['scope']['artifact_body_or_search_quality_assessed'] is False and report['scope']['atomic_capture_verified'] is False)
        final_rows = actual_rows(adapter)
        final_search = tuple((query, tuple((hit.resource_id, hit.revision, hit.kind, hit.matched_terms) for hit in index.search(query)))
                             for query in ('research', 'news', 'current', 'uncertain', 'removedterm'))
        return checks, final_rows, final_search

    with tempfile.TemporaryDirectory(prefix='catalog-index-contract-', dir=connect.fixture_root) as directory:
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
            left_checks, left_rows, left_search = exercise(sqlite_adapter, sqlite_connector)
            right_checks, right_rows, right_search = exercise(postgres_adapter, postgres_connector)
            checks = {name: left_checks.get(name) is True and right_checks.get(name) is True
                      for name in CHECKS - {'unix_socket_only', 'sqlite_postgres_artifact_and_search_equal'}}
            checks['sqlite_postgres_artifact_and_search_equal'] = left_rows == right_rows and left_search == right_search
            with postgres_adapter.transaction(readonly=True) as session:
                transport = session.execute(statement('fixture.index_transport',
                    "SELECT '' AS listeners,NULL AS server_address,NULL AS client_address",
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
                      'from scripts.rehearse_catalog_index_postgres import _worker_main; raise SystemExit(_worker_main())'],
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
                           'legacy_fts_bm25_vector_parity_established': False, 'synthetic_resources_per_backend': 4,
                           'rollback_fault_boundaries': 4, 'commit_fault_scope': 'injected_after_actual_commit',
                           'shadow_scope': 'caller_supplied_synthetic_snapshots_only'}}
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
    parser = Parser(prog='rehearse_catalog_index_postgres', description=__doc__, allow_abbrev=False)
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
