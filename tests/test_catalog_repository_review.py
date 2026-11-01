"""Independent private catalog reads, isolation, and existing projection parity."""
import copy
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest


def build_catalog(db):
    from agent_market.gateway.store import SCHEMA, HEALTH_COLUMNS
    db.executescript(SCHEMA.split('CREATE INDEX IF NOT EXISTS resources_cat')[0])
    for column, declaration in HEALTH_COLUMNS.items():
        db.execute('ALTER TABLE resources ADD COLUMN ' + column + ' ' + declaration)
    tools = [
        {'name': 'lookup', 'description': 'Read public references',
         'inputSchema': {'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']},
         'annotations': {'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True}},
        {'name': 'private_constraint', 'inputSchema': {'type': 'object', 'properties': {
            'target': {'const': 'https://provider.example/project'}}}},
    ]
    rows = [
        (1, 'mcp:one', 'synthetic-source', 'mcp', 'First', 'data', 1, 'healthy', 20.0, 'a' * 64),
        (2, 'a2a:two', 'synthetic-source', 'a2a', 'Second', 'research', 1, 'reachable', 30.0, 'b' * 64),
        (3, 'x402:three', 'other-source', 'x402', 'Third', 'data', 0, 'down', 40.0, 'c' * 64),
        (4, 'mcp:four', 'other-source', 'mcp', 'Fourth', 'data', 1, 'unknown', 50.0, 'd' * 64),
    ]
    for identity, key, source, kind, name, category, active, health, last_seen, digest in rows:
        db.execute('''INSERT INTO resources
            (id,key,source,kind,url,name,description,category,networks,details,first_seen,last_seen,
             active,health_status,content_hash,usage_tools,usage_full_tools,usage_guide,auth_info,eval_security)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (identity, key, source, kind, 'https://provider.example/project', name,
             'Call https://provider.example/project/tools; docs https://provider.example/docs',
             category, ',base,', json.dumps({'endpoint': 'https://provider.example/project/tools',
                'source_url': 'https://provider.example/project/docs/reference', 'token': 'synthetic-private-token'}),
             10.0, last_seen, active, health, digest, json.dumps(tools), json.dumps(tools),
             json.dumps({'endpoint': 'https://provider.example/project/tools'}),
             json.dumps({'authorization': 'Bearer synthetic-private-bearer'}),
             'quarantine' if identity == 3 else 'ok'))
    db.commit()


@pytest.fixture
def catalog():
    from agent_market.storage_adapter import SQLiteAdapter
    from agent_market.catalog_repository import CatalogRepository
    from agent_market.gateway.store import Store
    db = sqlite3.connect(':memory:', check_same_thread=False)
    db.row_factory = sqlite3.Row
    build_catalog(db)
    raw = Store.__new__(Store)
    raw._path, raw._db, raw._lock = ':memory:', db, threading.RLock()
    repository = CatalogRepository(SQLiteAdapter(db))
    try:
        yield repository, db, raw
    finally:
        db.close()


def ids(records):
    return [record.as_private_dict()['id'] for record in records]


def test_private_record_preserves_selected_raw_values_without_enrichment_or_filtering(catalog):
    repository, db, raw = catalog
    before = db.total_changes
    for identity in (1, 2, 3, 4):
        record = repository.get(identity)
        private = record.as_private_dict()
        original = raw.resource(identity)
        assert private and set(private) <= set(original)
        assert private == {name: original[name] for name in private}
        assert private['id'] == identity
        assert type(private['details']) is str
        assert 'synthetic-private-token' in private['details']
    assert repository.get(999) is None
    assert db.total_changes == before


def test_private_record_repr_and_copy_do_not_implicitly_disclose_or_mutate_raw_payload(catalog):
    repository, _db, _raw = catalog
    record = repository.get(1)
    rendered = repr(record)
    for private in ('synthetic-private-token', 'synthetic-private-bearer', 'provider.example', 'mcp:one'):
        assert private not in rendered
    modified = record.as_private_dict()
    modified['name'] = 'Changed only in private copy'
    assert record.as_private_dict()['name'] == 'First'
    assert repository.get(1).as_private_dict()['name'] == 'First'


def test_batch_preserves_first_occurrence_input_order_and_missing_ids(catalog):
    repository, _db, _raw = catalog
    result = repository.batch((4, 99, 1, 4, 99, 3, 88))
    assert ids(result.found) == [4, 1, 3]
    assert result.missing == (99, 88)
    empty = repository.batch(())
    assert empty.found == () and empty.missing == ()


def test_list_keyset_paging_is_ascending_and_count_ignores_cursor(catalog):
    from agent_market.catalog_repository import CatalogFilter
    repository, _db, _raw = catalog
    filtered = CatalogFilter(category='data')
    assert ids(repository.list(filters=filtered, limit=2)) == [1, 3]
    assert ids(repository.list(filters=filtered, limit=2, after_id=3)) == [4]
    assert ids(repository.list(filters=filtered, limit=2, after_id=4)) == []
    assert repository.count(filters=filtered) == 3
    assert ids(repository.list(filters=CatalogFilter(active=False))) == [3]
    assert ids(repository.list(filters=CatalogFilter(kind='mcp', active=True, min_last_seen=30.0))) == [4]
    assert ids(repository.list(filters=CatalogFilter(source='synthetic-source', health_status='reachable'))) == [2]


def test_unrestricted_get_does_not_promote_quarantined_or_inactive_resource(catalog):
    repository, _db, raw = catalog
    record = repository.get(3).as_private_dict()
    assert record['active'] == 0 and record['health_status'] == 'down'
    if 'eval_security' in record:
        assert record['eval_security'] == raw.resource(3)['eval_security'] == 'quarantine'


def test_content_hash_guard_is_exact_and_is_not_a_connection_version_claim(catalog):
    from agent_market.catalog_repository import CatalogError
    repository, _db, _raw = catalog
    assert repository.get(1, expected_hash='a' * 64).as_private_dict()['id'] == 1
    for identity, expected in ((1, 'b' * 64), (999, 'a' * 64)):
        with pytest.raises(CatalogError) as captured:
            repository.get(identity, expected_hash=expected)
        assert captured.value.code == 'stale_resource'


def test_existing_public_projection_is_identical_after_explicit_private_materialization(catalog, monkeypatch):
    from agent_market.concierge.connections import public_agent
    from agent_market.capability_registry import Registry
    repository, db, original_store = catalog
    def forbid_registry(*_args, **_kwargs):
        pytest.fail('Read-only compatibility projection must not create registry rows')
    monkeypatch.setattr(Registry, 'current', forbid_registry)
    original = original_store.resource(1)
    selected = repository.get(1).as_private_dict()
    def public_value(raw):
        return {name: raw[name] for name in ('id', 'kind', 'name', 'url', 'description')} | {
            'usage_endpoint': raw['url'], 'tools': ['lookup', 'private_constraint'],
            'tools_schema': json.loads(raw['usage_full_tools'])}
    before = db.total_changes
    public_before = public_agent(public_value(original), resource=original)
    public_after = public_agent(public_value(selected), resource=selected)
    assert public_after == public_before
    assert public_after['url'] == 'https://agentconcierge.biz/api/gateway/mcp/1'
    assert 'https://provider.example/docs' in public_after['description']
    assert public_after['tools'] == ['lookup']
    assert 'synthetic-private-token' not in json.dumps(public_after)
    assert selected == repository.get(1).as_private_dict()
    assert db.total_changes == before


def test_snapshot_is_closed_after_context_exit_and_owner_bound(catalog):
    from agent_market.catalog_repository import CatalogError
    repository, _db, _raw = catalog
    with repository.snapshot() as view:
        assert view.get(1).as_private_dict()['id'] == 1
        with ThreadPoolExecutor(max_workers=1) as pool:
            with pytest.raises(CatalogError) as captured:
                pool.submit(view.get, 1).result(timeout=3)
        assert captured.value.code == 'thread_violation'
        assert view.get(2).as_private_dict()['id'] == 2
    with pytest.raises(CatalogError) as closed:
        view.get(1)
    assert closed.value.code == 'session_closed'


@pytest.mark.parametrize('full_text', [None, '', '{malformed-json', '[]'])
def test_raw_schema_null_empty_and_malformed_states_keep_existing_binding_semantics(catalog, full_text):
    from agent_market.capability_registry import version_parts
    repository, db, original_store = catalog
    db.execute('UPDATE resources SET usage_full_tools=? WHERE id=1', (full_text,))
    db.commit()
    private = repository.get(1).as_private_dict()
    original = original_store.resource(1)
    assert private['usage_full_tools'] == full_text
    assert private['usage_tools'] == original['usage_tools']
    assert version_parts(private) == version_parts(original)
    assert version_parts(private)[3] is (full_text is not None)


def test_exact_key_and_filter_values_are_bound_data_not_sql(catalog):
    from agent_market.catalog_repository import CatalogFilter
    repository, db, _raw = catalog
    key = "synthetic' OR 1=1 --"
    source = "source' OR 1=1 --"
    db.execute('UPDATE resources SET key=?,source=? WHERE id=4', (key, source))
    db.commit()
    before = db.total_changes
    assert repository.get_by_key(key).as_private_dict()['id'] == 4
    assert repository.get_by_key("different' OR 1=1 --") is None
    assert ids(repository.list(filters=CatalogFilter(source=source))) == [4]
    assert repository.count(filters=CatalogFilter(source=source)) == 1
    assert repository.count() == 4
    assert db.total_changes == before


def test_repository_and_snapshot_never_initialize_or_write_schema(catalog):
    repository, db, _raw = catalog
    denied = []
    write_actions = {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE,
                     sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_CREATE_INDEX,
                     sqlite3.SQLITE_ALTER_TABLE, sqlite3.SQLITE_DROP_TABLE,
                     sqlite3.SQLITE_CREATE_TRIGGER, sqlite3.SQLITE_DROP_TRIGGER}
    def authorizer(action, *_args):
        if action in write_actions:
            denied.append(action)
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    db.set_authorizer(authorizer)
    with repository.snapshot() as view:
        assert view.get(1).as_private_dict()['id'] == 1
        assert view.get_by_key('a2a:two').as_private_dict()['id'] == 2
        assert ids(view.batch((3, 1)).found) == [3, 1]
        assert ids(view.list()) == [1, 2, 3, 4]
        assert view.count() == 4
    assert denied == []
    assert not db.in_transaction


def test_actual_wal_snapshot_is_consistent_across_separate_committed_writer(tmp_path):
    from agent_market.catalog_repository import CatalogRepository, CatalogFilter
    from agent_market.storage_adapter import SQLiteAdapter
    path = tmp_path / 'isolated-catalog.sqlite3'
    reader = sqlite3.connect(path)
    writer = None
    try:
        assert reader.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
        build_catalog(reader)
        repository = CatalogRepository(SQLiteAdapter(reader))
        writer = sqlite3.connect(path)
        with repository.snapshot() as view:
            assert view.get(2).as_private_dict()['name'] == 'Second'
            writer.execute('UPDATE resources SET name=?,last_seen=? WHERE id=2', ('Committed external edit', 200.0))
            writer.commit()
            assert view.get(2).as_private_dict()['name'] == 'Second'
            assert view.count(filters=CatalogFilter(min_last_seen=100.0)) == 0
            assert ids(view.list()) == [1, 2, 3, 4]
        assert repository.get(2).as_private_dict()['name'] == 'Committed external edit'
        assert repository.count(filters=CatalogFilter(min_last_seen=100.0)) == 1
    finally:
        if writer is not None:
            writer.close()
        reader.close()


def test_snapshot_caller_cancellation_releases_read_transaction(catalog):
    repository, db, _raw = catalog
    with pytest.raises(KeyboardInterrupt):
        with repository.snapshot() as view:
            view.get(1)
            raise KeyboardInterrupt()
    assert db.in_transaction is False
    assert repository.get(1).as_private_dict()['name'] == 'First'


def test_read_uncommitted_connection_is_refused_without_changing_caller_configuration():
    from agent_market.catalog_repository import CatalogRepository, CatalogError
    from agent_market.storage_adapter import SQLiteAdapter
    db = sqlite3.connect(':memory:')
    db.execute('PRAGMA read_uncommitted=ON')
    try:
        repository = CatalogRepository(SQLiteAdapter(db))
        with pytest.raises(CatalogError) as captured:
            with repository.snapshot():
                pass
        assert captured.value.code == 'isolation_required'
        assert db.in_transaction is False
        assert db.execute('PRAGMA read_uncommitted').fetchone()[0] == 1
        assert db.execute('PRAGMA query_only').fetchone()[0] == 0
    finally:
        db.close()


@pytest.mark.parametrize('namespace', ['main', 'temp'])
def test_schema_object_cannot_forge_native_isolation_probe(namespace):
    from agent_market.catalog_repository import CatalogRepository, CatalogError
    from agent_market.storage_adapter import SQLiteAdapter, StorageError
    db = sqlite3.connect(':memory:')
    db.execute('PRAGMA read_uncommitted=ON')
    create = 'CREATE TEMP TABLE' if namespace == 'temp' else 'CREATE TABLE'
    db.execute(create + ' pragma_read_uncommitted(read_uncommitted INTEGER)')
    db.execute('INSERT INTO pragma_read_uncommitted VALUES (0)')
    db.commit()
    try:
        repository = CatalogRepository(SQLiteAdapter(db))
        with pytest.raises((CatalogError, StorageError)) as captured:
            with repository.snapshot():
                pass
        assert captured.value.code in {'isolation_required', 'statement_failed'}
        assert db.in_transaction is False
        assert db.execute('PRAGMA read_uncommitted').fetchone()[0] == 1
    finally:
        db.close()
