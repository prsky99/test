"""Independent exact-source, identity, fencing and atomic copy boundaries."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from tests.test_catalog_writer_review import FaultConnection, logical_state


def copy_operation(number=1):
    return 'cp_' + format(number, '032x')


def target_components(db):
    from agent_market.catalog_copy import COPY_SCHEMA, CatalogCopy
    from agent_market.catalog_observation_fixtures import seed
    from agent_market.storage_adapter import SQLiteAdapter, Statement
    adapter = SQLiteAdapter(db)
    seed(adapter)
    with adapter.transaction() as session:
        for statement in COPY_SCHEMA:
            session.execute(statement)
        session.execute(Statement('copy.review.disable_target',
            'UPDATE catalog_write_controls SET enabled=0 WHERE id=1',
            'UPDATE catalog_write_controls SET enabled=0 WHERE id=1'))
    return adapter, CatalogCopy(adapter)


@pytest.fixture
def copying():
    from agent_market.catalog_copy_fixtures import seed_source
    from agent_market.storage_adapter import SQLiteAdapter
    source_db = sqlite3.connect(':memory:')
    target_db = sqlite3.connect(':memory:')
    source_db.row_factory = target_db.row_factory = sqlite3.Row
    source = SQLiteAdapter(source_db)
    seed_source(source)
    target, copier = target_components(target_db)
    try:
        yield SimpleNamespace(source_db=source_db, target_db=target_db, source=source, target=target, copier=copier)
    finally:
        target_db.close()
        source_db.close()


@pytest.mark.parametrize('table', ['catalog_copy_source_control', 'catalog_copy_source_clocks', 'catalog_copy_source_exclusions'])
def test_source_extra_metadata_columns_are_not_silently_excluded(copying, table):
    from agent_market.catalog_copy import CopyError, source_snapshot
    copying.source_db.execute('ALTER TABLE ' + table + ' ADD COLUMN unselected_private_value TEXT')
    copying.source_db.execute('UPDATE ' + table + " SET unselected_private_value='synthetic-private-unselected'")
    copying.source_db.commit()
    before = logical_state(copying.target_db)
    with pytest.raises(CopyError) as captured:
        with source_snapshot(copying.source) as held:
            copying.copier.apply(held, operation_id=copy_operation())
    assert captured.value.code == 'unsupported_schema'
    assert logical_state(copying.target_db) == before


def test_source_additional_control_row_is_not_hidden_by_id_one_filter(copying):
    from agent_market.catalog_copy import CopyError, source_snapshot
    copying.source_db.execute("INSERT INTO catalog_copy_source_control VALUES (2,999,'owned-legacy-subset-v1')")
    copying.source_db.commit()
    before = logical_state(copying.target_db)
    with pytest.raises(CopyError) as captured:
        with source_snapshot(copying.source) as held:
            copying.copier.apply(held, operation_id=copy_operation())
    assert captured.value.code == 'invalid_source'
    assert logical_state(copying.target_db) == before


def test_stable_identity_original_hashes_unknown_values_and_clock_tombstones_survive(copying):
    from agent_market.catalog_copy import source_snapshot
    from agent_market.catalog_copy_fixtures import LEGACY_HASHES
    from agent_market.catalog_observations import CatalogObservations
    source_before = logical_state(copying.source_db)
    with source_snapshot(copying.source) as held:
        result = copying.copier.apply(held, operation_id=copy_operation())
        summary = held.summary()
    assert (result.status, result.resources, result.initial_revision, result.source_epoch, result.replayed) == ('committed', 2, 6, 5, False)
    assert summary['participating_source_writers_fenced'] is True
    assert summary['cross_database_atomic'] is summary['operating_cutover_authorized'] is False
    rows = [dict(row) for row in copying.target_db.execute('SELECT * FROM resources ORDER BY id')]
    assert [row['id'] for row in rows] == [7, 41]
    assert [row['first_seen'] for row in rows] == [0, 5]
    assert [row['last_seen'] for row in rows] == [100, 80]
    assert rows[1]['health_status'] is None and rows[1]['active'] == 0
    for field in ('auth_declared', 'auth_observed', 'auth_info', 'usage_tools', 'usage_full_tools', 'eval_grade', 'eval_at'):
        assert rows[1][field] is None, field
    mappings = [dict(row) for row in copying.target_db.execute('SELECT * FROM catalog_copy_mappings ORDER BY resource_id')]
    assert [row['source_hash'] for row in mappings] == list(LEGACY_HASHES)
    assert [row['proposed_hash'] for row in mappings] == [row['content_hash'] for row in rows]
    assert all(row['initial_revision'] == 6 for row in mappings)
    assert all(row['proposed_hash'] != row['source_hash'] for row in mappings)
    observations = CatalogObservations(copying.target)
    assert observations.current(7, 'survey').observed_at == 150
    assert observations.current(7, 'survey').outcome == 'failed'
    assert observations.current(7, 'evaluation').observed_at == 140
    assert rows[0]['cap_checked_at'] is rows[0]['eval_at'] is None
    assert observations.current(41, 'health') is None
    for table in ('catalog_observation_operations', 'catalog_write_operations', 'capability_evidence',
                  'capability_eligibility', 'capability_approvals', 'connection_versions'):
        assert copying.target_db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] == 0, table
    assert copying.target_db.execute('SELECT enabled FROM catalog_write_controls').fetchone()[0] == 0
    assert logical_state(copying.source_db) == source_before


@pytest.mark.parametrize('domain,value', [('history', 1), ('authority', 1), ('uncoordinated_writers', None)])
def test_unsupported_or_unassessed_manifest_refuses_without_partial_copy(copying, domain, value):
    from agent_market.catalog_copy import CopyError, source_snapshot
    copying.source_db.execute('UPDATE catalog_copy_source_exclusions SET records=? WHERE domain=?', (value, domain))
    copying.source_db.commit()
    before = logical_state(copying.target_db)
    with pytest.raises(CopyError) as captured:
        with source_snapshot(copying.source) as held:
            copying.copier.apply(held, operation_id=copy_operation())
    assert captured.value.code == 'unsupported_data'
    summary = captured.value.summary()
    assert summary['complete'] is False and summary['unsupported_domains'][domain] == value
    assert 'copy-source.example' not in str(summary)
    assert logical_state(copying.target_db) == before


@pytest.mark.parametrize('sql', [
    "INSERT INTO capability_eligibility VALUES (7,'cv_synthetic_old','succeeded',1,99999)",
    "INSERT INTO capability_approvals VALUES ('cv_synthetic_old','synthetic.contract.v1','old_tool',1)",
    "INSERT INTO catalog_observation_operations VALUES ('ob_00000000000000000000000000000001','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa','health','committed',7,1,1,'healthy','{}')",
])
def test_existing_private_cache_history_or_receipt_is_not_overwritten(copying, sql):
    from agent_market.catalog_copy import CopyError, source_snapshot
    copying.target_db.execute(sql)
    copying.target_db.commit()
    before = logical_state(copying.target_db)
    with pytest.raises(CopyError) as captured:
        with source_snapshot(copying.source) as held:
            copying.copier.apply(held, operation_id=copy_operation())
    assert captured.value.code == 'target_not_empty'
    assert logical_state(copying.target_db) == before


def test_source_lifetime_and_thread_scope_are_required_before_target_writes(copying):
    from agent_market.catalog_copy import CopyError, source_snapshot
    with source_snapshot(copying.source) as held:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(copying.copier.apply, held, operation_id=copy_operation())
            with pytest.raises(CopyError) as captured:
                future.result(timeout=3)
            assert captured.value.code == 'thread_violation'
    before = logical_state(copying.target_db)
    with pytest.raises(CopyError) as captured:
        copying.copier.apply(held, operation_id=copy_operation())
    assert captured.value.code == 'source_closed'
    assert logical_state(copying.target_db) == before


def test_replay_is_an_original_receipt_not_permission_to_restore_changed_target(copying):
    from agent_market.catalog_copy import source_snapshot
    with source_snapshot(copying.source) as held:
        copying.copier.apply(held, operation_id=copy_operation())
    copying.target_db.execute("UPDATE resources SET name='Edited after import' WHERE id=7")
    copying.target_db.commit()
    before = logical_state(copying.target_db)
    with source_snapshot(copying.source) as held:
        replay = copying.copier.apply(held, operation_id=copy_operation())
    assert replay.replayed is True and replay.resources == 2
    assert copying.target_db.execute('SELECT name FROM resources WHERE id=7').fetchone()[0] == 'Edited after import'
    assert logical_state(copying.target_db) == before


def test_old_observer_generation_and_materializer_token_are_fenced_after_explicit_enable(copying):
    from dataclasses import replace
    from agent_market.catalog_copy import source_snapshot
    from agent_market.catalog_observations import CatalogObservations, HealthObservation, ObservationError
    from agent_market.catalog_index import CatalogIndex
    from agent_market.catalog_index_outbox import CatalogIndexOutbox
    with source_snapshot(copying.source) as held:
        copying.copier.apply(held, operation_id=copy_operation())
    copying.target_db.execute('UPDATE catalog_write_controls SET enabled=1,revision=1 WHERE id=1')
    copying.target_db.commit()
    observations = CatalogObservations(copying.target)
    stale = observations.record(7, HealthObservation('healthy'), operation_id='ob_' + '1' * 32,
        expected_revision=5, observed_at=200)
    assert stale.status == 'conflict' and stale.revision == 6
    before = logical_state(copying.target_db)
    with pytest.raises(ObservationError) as captured:
        observations.record(7, HealthObservation('healthy'), operation_id='ob_' + '2' * 32,
            expected_revision=6, observed_at=119)
    assert captured.value.code == 'stale_observation'
    assert logical_state(copying.target_db) == before
    outbox = CatalogIndexOutbox(copying.target)
    index = CatalogIndex(copying.target)
    current = outbox.claim('fresh-copy-worker', now=201)
    artifact = index.build(current)
    wrong_token = replace(current, token='0' * 32)
    before = logical_state(copying.target_db)
    assert index.publish(wrong_token, artifact, now=202) == 'stale_claim'
    assert logical_state(copying.target_db) == before
    assert index.publish(current, artifact, now=203) == 'indexed'
    fresh = observations.record(7, HealthObservation('healthy'), operation_id='ob_' + '3' * 32,
        expected_revision=6, observed_at=204)
    assert fresh.status == 'committed' and fresh.revision == 7


@pytest.mark.parametrize('prefix', [
    'INSERT INTO resources ', 'INSERT INTO catalog_resource_revisions ',
    'INSERT INTO catalog_index_jobs ', 'INSERT INTO catalog_copy_mappings ',
    'INSERT INTO catalog_observation_heads ', 'INSERT INTO catalog_copy_imports ',
])
def test_accepted_target_sql_failure_leaves_no_partial_copy_or_receipt(copying, prefix):
    from agent_market.catalog_copy import source_snapshot
    from agent_market.storage_adapter import StorageError
    db = sqlite3.connect(':memory:', factory=FaultConnection)
    db.row_factory = sqlite3.Row
    try:
        _adapter, copier = target_components(db)
        source_before = logical_state(copying.source_db)
        before = logical_state(db)
        db.fail_prefix = prefix
        with pytest.raises(StorageError) as captured:
            with source_snapshot(copying.source) as held:
                copier.apply(held, operation_id=copy_operation())
        assert captured.value.code == 'statement_failed'
        assert db.failures == 1, 'The target SQL must have been accepted before failure.'
        db.fail_prefix = None
        assert logical_state(db) == before
        assert copier.reconcile(copy_operation()) is None
        assert logical_state(copying.source_db) == source_before
    finally:
        db.close()


def test_commit_unknown_is_reconciled_after_reopening_without_copying_twice(copying, tmp_path):
    from agent_market.catalog_copy import CatalogCopy, source_snapshot
    from agent_market.storage_adapter import SQLiteAdapter, StorageError
    class CommitLost(sqlite3.Connection):
        armed = False
        attempts = 0
        def commit(self):
            super().commit()
            if self.armed:
                self.attempts += 1
                raise RuntimeError('synthetic-private-copy-commit-acknowledgement-lost')
    path = tmp_path / 'private-copy-target.sqlite3'
    db = sqlite3.connect(path, factory=CommitLost)
    db.row_factory = sqlite3.Row
    try:
        _adapter, copier = target_components(db)
        db.armed = True
        with pytest.raises(StorageError) as captured:
            with source_snapshot(copying.source) as held:
                copier.apply(held, operation_id=copy_operation())
        assert captured.value.code == 'commit_unknown' and db.attempts == 1
    finally:
        db.close()
    fresh = sqlite3.connect(path)
    fresh.row_factory = sqlite3.Row
    try:
        copier = CatalogCopy(SQLiteAdapter(fresh))
        receipt = copier.reconcile(copy_operation())
        assert receipt.status == 'committed' and receipt.resources == 2 and receipt.initial_revision == 6
        before = logical_state(fresh)
        with source_snapshot(copying.source) as held:
            replay = copier.apply(held, operation_id=copy_operation())
        assert replay.replayed is True
        assert logical_state(fresh) == before
        assert fresh.execute('SELECT COUNT(*) FROM resources').fetchone()[0] == 2
        assert fresh.execute('SELECT COUNT(*) FROM catalog_index_jobs').fetchone()[0] == 2
        assert fresh.execute('SELECT COUNT(*) FROM catalog_copy_imports').fetchone()[0] == 1
    finally:
        fresh.close()


def test_sqlite_held_source_excludes_real_independent_writer_and_releases_it(tmp_path):
    from agent_market.catalog_copy import source_snapshot
    from agent_market.catalog_copy_fixtures import seed_source
    from agent_market.storage_adapter import SQLiteAdapter
    path = tmp_path / 'private-owned-source.sqlite3'
    source = sqlite3.connect(path)
    source.row_factory = sqlite3.Row
    adapter = SQLiteAdapter(source)
    seed_source(adapter)
    before = logical_state(source)
    def try_write():
        writer = sqlite3.connect(path, timeout=0.02)
        try:
            writer.execute("UPDATE resources SET name='Concurrent synthetic writer' WHERE id=7")
            writer.rollback()
            return 'accepted'
        except sqlite3.OperationalError as exc:
            assert 'locked' in str(exc)
            return 'locked'
        finally:
            writer.close()
    try:
        with source_snapshot(adapter) as held:
            assert held.summary()['fence'] == 'sqlite_write_reservation'
            with ThreadPoolExecutor(max_workers=1) as executor:
                assert executor.submit(try_write).result(timeout=3) == 'locked'
        assert logical_state(source) == before
        with ThreadPoolExecutor(max_workers=1) as executor:
            assert executor.submit(try_write).result(timeout=3) == 'accepted'
        assert logical_state(source) == before
    finally:
        source.close()


def test_mutating_cached_copy_source_cannot_change_receipt_bound_resource(copying):
    from agent_market.catalog_copy import source_snapshot
    with source_snapshot(copying.source) as held:
        held._mapped[0][0]['first_seen'] = 99
        copying.copier.apply(held, operation_id=copy_operation())
    assert copying.target_db.execute('SELECT first_seen FROM resources WHERE id=7').fetchone()[0] == 0
    assert copying.source_db.execute('SELECT first_seen FROM resources WHERE id=7').fetchone()[0] == 0


@pytest.mark.parametrize('table,before_type,after_type', [
    ('catalog_copy_mappings', 'source_hash TEXT', 'source_hash BIGINT'),
    ('resources', 'id INTEGER PRIMARY KEY', 'id TEXT PRIMARY KEY'),
])
def test_target_affinity_cannot_silently_coerce_preserved_hash_or_stable_id(copying, table, before_type, after_type):
    from agent_market.catalog_copy import CopyError, source_snapshot
    definition = copying.target_db.execute('SELECT sql FROM sqlite_schema WHERE name=?', (table,)).fetchone()[0]
    assert before_type in definition
    copying.target_db.execute('DROP TABLE ' + table)
    copying.target_db.execute(definition.replace(before_type, after_type, 1))
    copying.target_db.commit()
    before = logical_state(copying.target_db)
    with pytest.raises(CopyError) as captured:
        with source_snapshot(copying.source) as held:
            copying.copier.apply(held, operation_id=copy_operation())
    assert captured.value.code == 'invalid_record'
    assert logical_state(copying.target_db) == before
    assert copying.copier.reconcile(copy_operation()) is None
