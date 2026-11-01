"""Native read-only repeatable captures on disposable caller-owned adapters."""
import json
import sqlite3

import pytest

from agent_market.catalog_capture import capture_snapshot, compare_adapters, CaptureError
from agent_market.catalog_shadow import RESOURCE_FIELDS
from agent_market.catalog_writer import CatalogWriter
from agent_market.catalog_writer_fixtures import seed, command, operation, MODEL_HASH, URL
from agent_market.storage_adapter import SQLiteAdapter


def initialize(db):
    adapter = SQLiteAdapter(db)
    seed(adapter)
    CatalogWriter(adapter, model_hash=MODEL_HASH).upsert(command(), operation_id=operation(1),
                                                       expected_revision=0, observed_at=0)
    return adapter


@pytest.fixture
def catalog():
    db = sqlite3.connect(':memory:')
    adapter = initialize(db)
    try:
        yield db, adapter
    finally:
        db.close()


def assert_incomplete(value, issue):
    assert value.complete is False and value.issue == issue
    assert value.as_private_snapshot() is None
    assert value.summary()['row_counts'] is None
    assert value.summary()['repeatable_snapshot'] is False
    assert repr(value) == '<CapturedCatalog private>'


def test_private_capture_is_bounded_consistent_and_explicitly_minimized(catalog):
    db, adapter = catalog
    before = db.total_changes
    captured = capture_snapshot(adapter, role='candidate')
    assert captured.complete and captured.issue is None
    assert db.total_changes == before and not db.in_transaction
    rows = captured.as_private_snapshot()
    assert set(rows['resources'][0]) == set(RESOURCE_FIELDS)
    assert set(rows['jobs'][0]) == {'job_id', 'resource_id', 'revision', 'corpus_hash', 'model_hash', 'state', 'projection_hash'}
    assert captured.summary()['native_read_only'] is True
    assert captured.summary()['worker_tokens_captured'] is False
    assert captured.summary()['observation_owner_clocks_or_journal_captured'] is False
    assert captured.summary()['authority_or_evidence_verified'] is False
    assert captured.summary()['bounds_after_driver_decode'] is True
    assert captured.summary()['cpu_or_latency_guaranteed'] is False
    assert repr(captured) == '<CapturedCatalog private>'
    rows['resources'][0]['url'] = 'changed-only-in-private-copy'
    assert captured.as_private_snapshot()['resources'][0]['url'] == URL


def test_legacy_role_reads_only_resource_fields_without_metadata(catalog):
    db, adapter = catalog
    for table in ('catalog_resource_revisions', 'catalog_index_heads', 'catalog_index_jobs', 'catalog_index_projections'):
        db.execute('DROP TABLE ' + table)
    db.commit()
    captured = capture_snapshot(adapter, role='legacy')
    assert captured.complete and captured.as_private_snapshot()['resources'][0]['url'] == URL
    assert all(not captured.as_private_snapshot()[name] for name in ('revisions', 'heads', 'jobs', 'projections'))
    assert_incomplete(capture_snapshot(adapter, role='candidate'), 'unsupported_schema')


def test_schema_and_data_reads_cannot_mutate_rows(catalog):
    db, adapter = catalog
    before = db.total_changes
    writes = {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE,
              sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_DROP_TABLE, sqlite3.SQLITE_ALTER_TABLE}

    def authorize(action, _first, _second, _database, _source):
        return sqlite3.SQLITE_DENY if action in writes else sqlite3.SQLITE_OK

    db.set_authorizer(authorize)
    try:
        assert capture_snapshot(adapter, role='candidate').complete
    finally:
        db.set_authorizer(None)
    assert db.total_changes == before


@pytest.mark.parametrize('setting', [0, 1])
def test_native_read_only_setting_is_preserved(catalog, setting):
    db, adapter = catalog
    db.execute('PRAGMA query_only=' + str(setting))
    assert capture_snapshot(adapter, role='candidate').complete
    assert db.execute('PRAGMA query_only').fetchone()[0] == setting


def test_dirty_read_policy_is_refused_without_changing_it(catalog):
    db, adapter = catalog
    db.execute('PRAGMA read_uncommitted=1')
    assert_incomplete(capture_snapshot(adapter, role='candidate'), 'isolation_required')
    assert db.execute('PRAGMA read_uncommitted').fetchone()[0] == 1
    assert db.execute('PRAGMA query_only').fetchone()[0] == 0
    assert not db.in_transaction


@pytest.mark.parametrize('namespace', ['main', 'temp'])
@pytest.mark.parametrize('name', ['pragma_read_uncommitted', 'pragma_query_only'])
def test_native_setting_function_shadow_fails_closed(catalog, namespace, name):
    db, adapter = catalog
    column = 'read_uncommitted' if name == 'pragma_read_uncommitted' else 'query_only'
    db.execute('CREATE TABLE ' + namespace + '.' + name + '(' + column + ' INTEGER)')
    db.execute('INSERT INTO ' + namespace + '.' + name + ' VALUES (0)')
    db.commit()
    assert_incomplete(capture_snapshot(adapter, role='candidate'), 'isolation_unavailable')


@pytest.mark.parametrize('object_type', ['TABLE', 'VIEW'])
def test_temp_shadow_of_fixed_table_is_refused(catalog, object_type):
    db, adapter = catalog
    if object_type == 'TABLE':
        db.execute('CREATE TEMP TABLE resources (id INTEGER)')
    else:
        db.execute('CREATE TEMP VIEW resources AS SELECT 1 AS id')
    db.commit()
    assert_incomplete(capture_snapshot(adapter, role='candidate'), 'shadowed_table')
    assert_incomplete(capture_snapshot(adapter, role='legacy'), 'shadowed_table')


def test_capture_never_substitutes_a_view_for_a_supported_base_table(catalog):
    db, adapter = catalog
    db.execute('DROP TABLE resources')
    db.execute('CREATE VIEW resources AS SELECT 1 AS id')
    db.commit()
    assert_incomplete(capture_snapshot(adapter, role='candidate'), 'unsupported_schema')


def test_missing_selected_columns_are_fixed_incomplete_not_empty():
    db = sqlite3.connect(':memory:')
    db.execute('CREATE TABLE resources (id INTEGER PRIMARY KEY)')
    db.execute('INSERT INTO resources VALUES (1)')
    db.commit()
    try:
        captured = capture_snapshot(SQLiteAdapter(db), role='legacy')
        assert_incomplete(captured, 'schema_unavailable')
        assert all(text not in json.dumps(captured.summary()) for text in ('no such column', 'SELECT ', 'INTEGER PRIMARY KEY'))
    finally:
        db.close()


def test_capture_stays_at_one_wal_snapshot_across_resource_and_metadata_reads(tmp_path, monkeypatch):
    path = tmp_path / 'private-capture.sqlite'
    reader = sqlite3.connect(path)
    reader.execute('PRAGMA journal_mode=WAL')
    adapter = initialize(reader)
    other = sqlite3.connect(path)
    writer = CatalogWriter(SQLiteAdapter(other), model_hash=MODEL_HASH)
    original = adapter._execute
    changed = []

    def execute(statement, values):
        result = original(statement, values)
        if statement.name == 'catalog.capture.resources' and not changed:
            changed.append(writer.upsert(command(name='Changed synthetic resource'),
                operation_id=operation(2), expected_revision=1, observed_at=1))
        return result

    monkeypatch.setattr(adapter, '_execute', execute)
    try:
        captured = capture_snapshot(adapter, role='candidate')
        assert captured.complete and changed
        rows = captured.as_private_snapshot()
        assert rows['resources'][0]['last_seen'] == 0
        assert rows['revisions'][0]['revision'] == rows['heads'][0]['revision'] == 1
        assert len(rows['jobs']) == 1 and rows['jobs'][0]['revision'] == 1
        later = capture_snapshot(adapter, role='candidate').as_private_snapshot()
        assert later['resources'][0]['last_seen'] == 1
        assert later['revisions'][0]['revision'] == later['heads'][0]['revision'] == 2
        assert len(later['jobs']) == 2
    finally:
        other.close()
        reader.close()


def test_resource_overflow_is_detected_with_one_extra_row_and_no_partial(catalog):
    db, adapter = catalog
    writer = CatalogWriter(adapter, model_hash=MODEL_HASH)
    for number in range(2, 102):
        writer.upsert(command(key='synthetic:capture:' + str(number)),
            operation_id=operation(number), expected_revision=0, observed_at=number)
    before = db.total_changes
    assert_incomplete(capture_snapshot(adapter, role='candidate'), 'row_limit')
    assert db.total_changes == before
    result = compare_adapters(adapter, adapter, expected_model_hash=MODEL_HASH)
    assert result['complete'] is False and result['issues'] == ['source_capture_incomplete']
    assert all(value is None for value in result['counts'].values())
    assert result['captures']['candidate'] is None


def test_metadata_overflow_is_not_silently_truncated(catalog):
    db, adapter = catalog
    template = db.execute('SELECT * FROM catalog_index_jobs').fetchone()
    for number in range(500):
        row = list(template)
        row[0] = 'cij_' + format(number, '064x')
        row[2] = number + 2
        db.execute('INSERT INTO catalog_index_jobs VALUES (' + ','.join('?' for _ in row) + ')', row)
    db.commit()
    assert_incomplete(capture_snapshot(adapter, role='candidate'), 'row_limit')


def test_total_rows_bound_is_separate_from_each_metadata_table(catalog):
    db, adapter = catalog
    template = list(db.execute('SELECT * FROM catalog_index_jobs').fetchone())
    for number in range(499):
        row = list(template); row[0] = 'cij_' + format(number, '064x'); row[2] = number + 2
        db.execute('INSERT INTO catalog_index_jobs VALUES (' + ','.join('?' for _ in row) + ')', row)
    for number in range(500):
        db.execute('INSERT INTO catalog_index_projections VALUES (?,?,?,?,?,?,?)',
            (number + 1, MODEL_HASH, 1, 'a' * 64, 'b' * 64, 'cij_' + format(number, '064x'), 0))
    db.commit()
    assert_incomplete(capture_snapshot(adapter, role='candidate'), 'row_limit')


def test_cumulative_snapshot_bytes_are_bounded_across_separate_results(catalog):
    db, adapter = catalog
    writer = CatalogWriter(adapter, model_hash=MODEL_HASH)
    for number in range(2, 51):
        writer.upsert(command(key='synthetic:bytes:' + str(number)),
            operation_id=operation(number), expected_revision=0, observed_at=number)
    # Each native result remains below the adapter's1MiB bound. Their combined
    # private values exceed the snapshot2MiB bound before semantic assessment.
    db.execute('UPDATE resources SET auth_info=?', ('x' * 16384,))
    db.execute('UPDATE catalog_index_heads SET model_hash=?', ('y' * 16384,))
    db.execute('UPDATE catalog_index_jobs SET model_hash=?', ('z' * 16384,))
    db.commit()
    before = db.total_changes
    assert_incomplete(capture_snapshot(adapter, role='candidate'), 'byte_limit')
    assert db.total_changes == before


def test_schema_function_shadow_is_not_replaced_with_unvalidated_fallback(catalog):
    db, adapter = catalog
    db.execute('CREATE TEMP TABLE pragma_table_list (name TEXT)')
    db.commit()
    assert_incomplete(capture_snapshot(adapter, role='candidate'), 'schema_unavailable')


def test_empty_but_supported_capture_is_explicitly_empty_not_ready():
    db = sqlite3.connect(':memory:')
    adapter = SQLiteAdapter(db)
    seed(adapter)
    try:
        result = compare_adapters(adapter, adapter, expected_model_hash=MODEL_HASH)
        assert result['complete'] and result['assessment'] == 'empty_snapshots'
        assert result['captures']['source']['row_counts']['resources'] == 0
        assert result['captures']['cross_source_atomic'] is False
        assert result['scope']['operating_cutover_authorized'] is False
    finally:
        db.close()


@pytest.mark.parametrize('field,value,issue', [
    ('auth_info', 'synthetic-private-' + 'x' * 16384, 'value_limit'),
    ('auth_info', b'synthetic-private-bytes', 'invalid_scalar'),
    ('active', 2, 'invalid_resource_state'),
])
def test_unsupported_values_never_return_partial_private_data(catalog, field, value, issue):
    db, adapter = catalog
    db.execute('UPDATE resources SET ' + field + '=?', (value,)); db.commit()
    captured = capture_snapshot(adapter, role='candidate')
    assert_incomplete(captured, issue)
    assert 'synthetic-private' not in json.dumps(captured.summary())


def test_aggregate_compare_has_no_raw_binding_values_and_no_cross_source_claim(catalog):
    _db, adapter = catalog
    result = compare_adapters(adapter, adapter, expected_model_hash=MODEL_HASH)
    assert result['complete'] and result['captures']['source']['complete']
    assert result['captures']['candidate']['complete']
    assert result['captures']['cross_source_atomic'] is False
    assert result['captures']['sequential_independent_transactions'] is True
    assert result['scope']['individual_snapshots_repeatable'] is True
    assert result['scope']['atomic_capture_verified'] is False
    assert result['scope']['database_or_source_capture_performed'] is True
    encoded = json.dumps(result)
    for value in (URL, MODEL_HASH, 'synthetic-private-token', 'synthetic:catalog:one'):
        assert value not in encoded


@pytest.mark.parametrize('value', [None, ':memory:', '/private/synthetic.sqlite',
                                  'postgresql://private.invalid/catalog', object()])
def test_paths_connections_and_arbitrary_objects_are_not_accepted(value):
    with pytest.raises(CaptureError) as caught:
        capture_snapshot(value, role='candidate')
    assert str(caught.value) == 'invalid_request'


@pytest.mark.parametrize('role', [None, [], 'candidate; DROP TABLE resources', 'Candidate'])
def test_invalid_role_is_refused_before_any_statement(catalog, role):
    db, adapter = catalog
    calls = []
    db.set_trace_callback(calls.append)
    try:
        with pytest.raises(CaptureError) as caught:
            capture_snapshot(adapter, role=role)
        assert str(caught.value) == 'invalid_request' and not calls
    finally:
        db.set_trace_callback(None)


def test_invalid_model_or_adapter_skips_capture_with_fixed_aggregate(catalog):
    db, adapter = catalog
    calls = []
    db.set_trace_callback(calls.append)
    try:
        for source, target, model, issue in (
                (adapter, adapter, 'synthetic-private-model', 'invalid_model_hash'),
                (adapter, '/private/synthetic.sqlite', MODEL_HASH, 'capture_invalid_request')):
            result = compare_adapters(source, target, expected_model_hash=model)
            assert result['complete'] is False and result['issues'] == [issue]
            assert all(value is None for value in result['counts'].values())
        assert not calls
    finally:
        db.set_trace_callback(None)


def test_cancellation_propagates_after_read_only_transaction_cleanup(catalog, monkeypatch):
    db, adapter = catalog
    original = adapter._execute

    def interrupted(statement, values):
        if statement.name == 'catalog.capture.resources':
            raise KeyboardInterrupt()
        return original(statement, values)

    monkeypatch.setattr(adapter, '_execute', interrupted)
    with pytest.raises(KeyboardInterrupt):
        capture_snapshot(adapter, role='candidate')
    assert not db.in_transaction
    assert db.execute('PRAGMA query_only').fetchone()[0] == 0


def test_read_commit_uncertainty_returns_no_rows_and_disables_reuse():
    class LostAcknowledgement(sqlite3.Connection):
        armed = False
        def commit(self):
            super().commit()
            if self.armed:
                self.armed = False
                raise RuntimeError('Synthetic private read commit acknowledgement fault')

    db = sqlite3.connect(':memory:', factory=LostAcknowledgement)
    adapter = initialize(db)
    db.armed = True
    try:
        assert_incomplete(capture_snapshot(adapter, role='candidate'), 'commit_unknown')
        assert_incomplete(capture_snapshot(adapter, role='candidate'), 'connection_unusable')
    finally:
        db.close()
