"""Synthetic supported-source shape, reservation and strict mapping contracts."""
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from agent_market.catalog_copy import COPY_SCHEMA, CatalogCopy, CopyError, source_snapshot
from agent_market.catalog_copy_fixtures import (
    EXCLUSION_DOMAINS, LEGACY_HASHES, SOURCE_EPOCH, SOURCE_PROFILE,
    mutate_source, private_source_state, seed_source, source_rows,
)
from agent_market.catalog_shadow import RESOURCE_FIELDS
from agent_market.storage_adapter import SQLiteAdapter, StorageError, Statement


@pytest.fixture
def source():
    connection = sqlite3.connect(':memory:')
    adapter = SQLiteAdapter(connection)
    seed_source(adapter)
    try:
        yield connection, adapter
    finally:
        connection.close()


def code(call, expected):
    with pytest.raises(CopyError) as caught:
        call()
    assert caught.value.code == expected
    return caught.value


def open_source(adapter):
    with source_snapshot(adapter) as value:
        return value.summary()


def test_synthetic_source_declares_exact_selected_columns_and_excluded_domains(source):
    connection, adapter = source
    state = private_source_state(adapter)
    tables = connection.execute("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name").fetchall()
    assert {row[0] for row in tables} == set(state)
    columns = tuple(row[1] for row in connection.execute('PRAGMA table_info(resources)'))
    assert columns == RESOURCE_FIELDS and len(columns) == 44
    assert tuple(row['id'] for row in state['resources']) == (7, 41)
    assert tuple(row['content_hash'] for row in state['resources']) == LEGACY_HASHES
    assert state['catalog_copy_source_control'] == ({'id': 1, 'epoch': SOURCE_EPOCH, 'profile': SOURCE_PROFILE},)
    assert {row['domain']: row['records'] for row in state['catalog_copy_source_exclusions']} == dict.fromkeys(EXCLUSION_DOMAINS, 0)
    assert state['catalog_copy_source_clocks'] == (
        {'resource_id': 7, 'owner': 'evaluation', 'observed_at': 140.0, 'outcome': 'recorded'},
        {'resource_id': 7, 'owner': 'health', 'observed_at': 120.0, 'outcome': 'reachable'},
        {'resource_id': 7, 'owner': 'survey', 'observed_at': 150.0, 'outcome': 'failed'},
    )


def test_fixture_retains_null_unknown_and_failed_survey_tombstones(source):
    _, adapter = source
    first, inactive = private_source_state(adapter)['resources']
    assert first['first_seen'] == 0 and first['last_seen'] == 100
    assert first['cap_checked_at'] is None and first['eval_at'] is None
    assert first['usage_full_tools'] and first['eval_score'] == 88.5 and first['eval_grade'] == 'B'
    assert all(first[key] is None for key in ('auth_declared', 'auth_observed', 'auth_info'))
    assert inactive['active'] == 0
    assert all(inactive[key] is None for key in ('health_status', 'last_check_at', 'last_ok_at',
        'usage_tools', 'usage_full_tools', 'cap_checked_at', 'eval_score', 'eval_grade', 'eval_at'))
    separate = source_rows()
    separate[0]['name'] = 'Only a private copy'
    assert source_rows()[0]['name'] == first['name']


def test_source_summary_is_aggregate_and_honest_about_fence_scope(source):
    connection, adapter = source
    before = private_source_state(adapter)
    changes = connection.total_changes
    summary = open_source(adapter)
    assert summary['supported_subset_complete'] is True and summary['resources'] == 2
    assert summary['source_epoch'] == 5 and summary['participating_source_writers_fenced'] is True
    assert summary['all_runtime_writers_excluded'] is False
    assert summary['source_native_read_only_transaction'] is False
    assert summary['source_rows_mutated'] is False
    assert summary['cross_database_atomic'] is False and summary['operating_cutover_authorized'] is False
    assert summary['fence'] == 'sqlite_write_reservation'
    output = json.dumps(summary)
    for raw in ('synthetic:owned-copy', 'copy-source.example', 'Stock News', LEGACY_HASHES[0], 'SELECT '):
        assert raw not in output
    assert private_source_state(adapter) == before and connection.total_changes == changes


def test_source_lifetime_is_not_a_detached_reusable_import_authority(source):
    _, adapter = source
    with source_snapshot(adapter) as value:
        assert repr(value) == '<CopySource private>'
        assert value.summary()['source_epoch'] == 5
    code(value.summary, 'source_closed')


def test_source_summary_refuses_another_thread_before_database_access(source):
    _, adapter = source
    with source_snapshot(adapter) as value:
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(lambda: code(value.summary, 'thread_violation')).result()
        assert result.code == 'thread_violation'
        assert value.summary()['resources'] == 2


def test_sqlite_held_source_reservation_excludes_other_connections_then_releases(tmp_path):
    path = tmp_path / 'owned-copy.sqlite'
    connection = sqlite3.connect(path)
    connection.execute('PRAGMA journal_mode=WAL')
    adapter = SQLiteAdapter(connection)
    seed_source(adapter)
    competing = sqlite3.connect(path, timeout=0.02)
    other = SQLiteAdapter(competing)
    try:
        with source_snapshot(adapter) as value:
            with pytest.raises(StorageError) as caught:
                mutate_source(other, description='A cooperating blocked writer')
            assert caught.value.code == 'transaction_failed'
            assert value.summary()['source_epoch'] == 5
        assert mutate_source(other, description='A later cooperating writer') == 6
        state = private_source_state(adapter)
        assert state['catalog_copy_source_control'][0]['epoch'] == 6
        assert state['resources'][0]['description'] == 'A later cooperating writer'
        assert open_source(adapter)['source_epoch'] == 6
    finally:
        competing.close()
        connection.close()


@pytest.mark.parametrize('domain', EXCLUSION_DOMAINS)
@pytest.mark.parametrize('records', [1, None])
def test_nonempty_or_unknown_excluded_domain_is_refused_without_silent_import(domain, records):
    connection = sqlite3.connect(':memory:')
    adapter = SQLiteAdapter(connection)
    seed_source(adapter, unsupported={domain: records})
    before = private_source_state(adapter)
    try:
        error = code(lambda: open_source(adapter), 'unsupported_data')
        assert error.summary()['unsupported_domains'][domain] == records
        assert error.summary()['complete'] is False
        assert private_source_state(adapter) == before
    finally:
        connection.close()


@pytest.mark.parametrize('statement', [
    "DELETE FROM catalog_copy_source_exclusions WHERE domain='history'",
    "INSERT INTO catalog_copy_source_exclusions VALUES ('undeclared',0)",
])
def test_manifest_requires_every_supported_declaration_and_no_additions(source, statement):
    connection, adapter = source
    connection.execute(statement)
    connection.commit()
    code(lambda: open_source(adapter), 'invalid_source')


def test_duplicate_manifest_rows_cannot_collapse_into_one_accepted_declaration(source):
    connection, adapter = source
    connection.execute('ALTER TABLE catalog_copy_source_exclusions RENAME TO old_exclusions')
    connection.execute('CREATE TABLE catalog_copy_source_exclusions(domain TEXT,records BIGINT)')
    connection.execute('INSERT INTO catalog_copy_source_exclusions SELECT domain,records FROM old_exclusions')
    connection.execute('DROP TABLE old_exclusions')
    connection.execute("INSERT INTO catalog_copy_source_exclusions VALUES ('auth',0)")
    connection.commit()
    assert connection.execute('SELECT COUNT(*) FROM catalog_copy_source_exclusions').fetchone()[0] == 8
    code(lambda: open_source(adapter), 'invalid_source')


@pytest.mark.parametrize('statement', [
    'CREATE TABLE unpublished_credentials (value TEXT)',
    'ALTER TABLE resources ADD COLUMN trial_info TEXT',
    'CREATE TEMP TABLE resources (id INTEGER)',
])
def test_source_extra_or_shadowed_schema_is_not_treated_as_absent_data(source, statement):
    connection, adapter = source
    connection.execute(statement)
    connection.commit()
    code(lambda: open_source(adapter), 'unsupported_schema')


@pytest.mark.parametrize('table', ['catalog_copy_source_control', 'catalog_copy_source_clocks', 'catalog_copy_source_exclusions'])
def test_every_source_table_is_exact_not_only_the_resource_columns(source, table):
    connection, adapter = source
    connection.execute('ALTER TABLE ' + table + ' ADD COLUMN private_credential TEXT')
    connection.commit()
    code(lambda: open_source(adapter), 'unsupported_schema')


@pytest.mark.parametrize('field,value', [
    ('first_seen', -1), ('last_seen', 1e300), ('name', 'n' * 201),
    ('description', 'd' * 2001), ('content_hash', 'not-a-content-hash'),
    ('details', '{"duplicate":1,"duplicate":2}'),
    ('first_seen', 101), ('health_ok_24h', 2), ('consecutive_failures', -1),
])
def test_selected_field_limits_are_not_silently_truncated_or_normalized(source, field, value):
    connection, adapter = source
    connection.execute('UPDATE resources SET ' + field + '=? WHERE id=7', (value,))
    connection.commit()
    before = private_source_state(adapter)
    code(lambda: open_source(adapter), 'invalid_source')
    assert private_source_state(adapter) == before


@pytest.mark.parametrize('field,value', [('auth_declared', 0), ('auth_observed', 0), ('auth_info', '{}'),
    ('url', 'https://synthetic:password@copy-source.example/agent')])
def test_auth_values_and_credentialed_connection_urls_are_unsupported(source, field, value):
    connection, adapter = source
    connection.execute('UPDATE resources SET ' + field + '=? WHERE id=7', (value,))
    connection.commit()
    code(lambda: open_source(adapter), 'unsupported_data')


@pytest.mark.parametrize('field,value', [
    ('url', 'https://copy-source.example/agent?api_key=synthetic-secret'),
    ('details', '{"token":"synthetic-secret"}'),
    ('usage_guide', '{"authorization":"Bearer synthetic-secret"}'),
    ('description', 'Use password=synthetic-secret for this resource'),
    ('source', 'password=synthetic-secret'),
])
def test_known_credentials_in_selected_metadata_are_refused_not_copied(source, field, value):
    connection, adapter = source
    connection.execute('UPDATE resources SET ' + field + '=? WHERE id=7', (value,))
    connection.commit()
    code(lambda: open_source(adapter), 'unsupported_data')


@pytest.mark.parametrize('value', ['operating.sqlite', None, object(), sqlite3.connect])
def test_source_requires_exact_caller_owned_adapter_without_opening_paths(value):
    code(lambda: open_source(value), 'invalid_request')


@pytest.mark.parametrize('value', [0, -1, 1.5, 'invalid', None])
def test_source_epoch_must_be_positive_integral(source, value):
    connection, adapter = source
    if value is None:
        connection.execute('DELETE FROM catalog_copy_source_control')
    else:
        connection.execute('UPDATE catalog_copy_source_control SET epoch=?', (value,))
    connection.commit()
    code(lambda: open_source(adapter), 'invalid_source')


def test_null_legacy_hash_is_distinct_from_reconstructed_profile_hash(source):
    connection, adapter = source
    connection.execute('UPDATE resources SET content_hash=NULL WHERE id=41')
    connection.commit()
    assert open_source(adapter)['resources'] == 2
    assert private_source_state(adapter)['resources'][1]['content_hash'] is None


def test_null_old_hash_is_retained_in_import_mapping_without_fabricating_a_legacy_hash(source):
    from agent_market.catalog_observation_fixtures import seed
    connection, adapter = source
    connection.execute('UPDATE resources SET content_hash=NULL WHERE id=41')
    connection.commit()
    before = private_source_state(adapter)
    target = sqlite3.connect(':memory:')
    target_adapter = SQLiteAdapter(target)
    seed(target_adapter)
    try:
        with target_adapter.transaction() as session:
            for statement in COPY_SCHEMA:
                session.execute(statement)
            session.execute(Statement('copy.test.disable_target',
                'UPDATE catalog_write_controls SET enabled=0 WHERE id=1',
                'UPDATE catalog_write_controls SET enabled=0 WHERE id=1'))
        with source_snapshot(adapter) as held:
            result = CatalogCopy(target_adapter).apply(held, operation_id='cp_' + '1' * 32)
        mapping = target.execute('SELECT source_hash,proposed_hash FROM catalog_copy_mappings WHERE resource_id=41').fetchone()
        assert mapping[0] is None and len(mapping[1]) == 64
        assert target.execute('SELECT content_hash FROM resources WHERE id=41').fetchone()[0] == mapping[1]
        assert result.initial_revision == 6 and result.resources == 2
        assert private_source_state(adapter) == before
    finally:
        target.close()


def test_additional_target_write_control_row_cannot_be_hidden_by_id_one_filter(source):
    from agent_market.catalog_observation_fixtures import seed
    _, adapter = source
    target = sqlite3.connect(':memory:')
    target_adapter = SQLiteAdapter(target)
    seed(target_adapter)
    try:
        with target_adapter.transaction() as session:
            for statement in COPY_SCHEMA:
                session.execute(statement)
            session.execute(Statement('copy.test.ambiguous_target_controls',
                'UPDATE catalog_write_controls SET enabled=0 WHERE id=1',
                'UPDATE catalog_write_controls SET enabled=0 WHERE id=1'))
            session.execute(Statement('copy.test.extra_target_control',
                'INSERT INTO catalog_write_controls VALUES (2,0,1)',
                'INSERT INTO catalog_write_controls VALUES (2,0,1)'))
        with source_snapshot(adapter) as held:
            with pytest.raises(CopyError) as caught:
                CatalogCopy(target_adapter).apply(held, operation_id='cp_' + '4' * 32)
        assert caught.value.code in ('invalid_record', 'target_not_disabled')
        assert target.execute('SELECT COUNT(*) FROM resources').fetchone()[0] == 0
        assert target.execute('SELECT COUNT(*) FROM catalog_copy_imports').fetchone()[0] == 0
    finally:
        target.close()


@pytest.mark.parametrize('operation', [None, True, 'cp_' + 'A' * 32, 'cp_' + '1' * 31, 'co_' + '1' * 32])
def test_invalid_operation_identity_is_refused_before_target_schema_io(source, operation):
    _, adapter = source
    target = sqlite3.connect(':memory:')
    try:
        with source_snapshot(adapter) as held:
            code(lambda: CatalogCopy(SQLiteAdapter(target)).apply(held, operation_id=operation), 'invalid_request')
        assert not target.execute('SELECT name FROM sqlite_schema').fetchall()
    finally:
        target.close()


def test_unsupported_model_cannot_import_to_an_uninitialized_target(source):
    _, adapter = source
    target = sqlite3.connect(':memory:')
    try:
        with source_snapshot(adapter) as held:
            code(lambda: CatalogCopy(SQLiteAdapter(target)).apply(held, operation_id='cp_' + '2' * 32,
                model_hash='a' * 64), 'unsupported_model')
        assert not target.execute('SELECT name FROM sqlite_schema').fetchall()
    finally:
        target.close()


def test_source_cannot_be_its_own_target(source):
    _, adapter = source
    with source_snapshot(adapter) as held:
        code(lambda: CatalogCopy(adapter).apply(held, operation_id='cp_' + '3' * 32), 'invalid_request')


def test_source_refuses_overflow_instead_of_truncating_a_partial_catalog(source):
    connection, adapter = source
    fields = ','.join(RESOURCE_FIELDS)
    statement = 'INSERT INTO resources (' + fields + ') VALUES (' + ','.join('?' for _ in RESOURCE_FIELDS) + ')'
    first = source_rows()[0]
    for number in range(99):
        row = dict(first, id=100 + number, key='synthetic:copy:overflow:' + str(number))
        connection.execute(statement, tuple(row[field] for field in RESOURCE_FIELDS))
    connection.commit()
    assert connection.execute('SELECT COUNT(*) FROM resources').fetchone()[0] == 101
    code(lambda: open_source(adapter), 'invalid_source')


def test_source_clock_names_and_finite_high_watermarks_are_explicit(source):
    connection, adapter = source
    connection.execute("UPDATE catalog_copy_source_clocks SET owner='unowned' WHERE owner='survey'")
    connection.commit()
    code(lambda: open_source(adapter), 'invalid_source')


def test_fixture_source_mutation_is_parameterized_and_does_not_change_identity(source):
    _, adapter = source
    text = "Synthetic ' description; DROP TABLE resources; --"
    before = private_source_state(adapter)
    assert mutate_source(adapter, description=text) == 6
    after = private_source_state(adapter)
    assert after['resources'][0]['description'] == text
    assert after['resources'][0]['id'] == 7 and after['resources'][0]['key'] == before['resources'][0]['key']
    assert after['catalog_copy_source_clocks'] == before['catalog_copy_source_clocks']
    assert after['catalog_copy_source_exclusions'] == before['catalog_copy_source_exclusions']


@pytest.mark.parametrize('value', [{'unknown': 0}, {'auth': -1}, {'auth': True}, {'auth': '0'}, []])
def test_invalid_fixture_manifest_arguments_fail_before_creating_schema(value):
    connection = sqlite3.connect(':memory:')
    try:
        with pytest.raises(ValueError):
            seed_source(SQLiteAdapter(connection), unsupported=value)
        assert not connection.execute('SELECT name FROM sqlite_schema').fetchall()
    finally:
        connection.close()
