"""Independent atomic writer, replay, index-head, and private-data boundaries."""
import json
import sqlite3

import pytest


MODEL = 'a' * 64


def operation(number):
    return 'co_' + format(number, '032x')


def command(**changes):
    from agent_market.catalog_writer import RegistryUpsert
    return RegistryUpsert(**({
        'key': 'mcp:synthetic-one', 'source': 'synthetic-review', 'kind': 'mcp',
        'url': 'https://provider.example/project', 'name': 'Synthetic reader',
        'description': 'Call https://provider.example/project/tools; docs https://provider.example/docs',
        'category': 'research', 'details_json': '{"endpoint":"https://provider.example/project/tools","token":"synthetic-private-token"}',
    } | changes))


def seed(db):
    from agent_market.capability_registry import SCHEMA
    from agent_market.catalog_writer import RESOURCE_SCHEMA, WRITE_SCHEMA, CatalogWriter
    from agent_market.catalog_index_outbox import INDEX_SCHEMA
    from agent_market.storage_adapter import SQLiteAdapter, Statement
    db.executescript(SCHEMA)
    adapter = SQLiteAdapter(db)
    with adapter.transaction() as session:
        for statement in RESOURCE_SCHEMA + WRITE_SCHEMA + INDEX_SCHEMA:
            session.execute(statement)
        session.execute(Statement('review.enable_writer', 'UPDATE catalog_write_controls SET enabled=1,revision=1 WHERE id=1',
                                  'UPDATE catalog_write_controls SET enabled=1,revision=1 WHERE id=1'))
    return adapter, CatalogWriter(adapter, model_hash=MODEL)


@pytest.fixture
def writer():
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    adapter, current = seed(db)
    try:
        yield current, db, adapter
    finally:
        db.close()


def logical_state(db):
    tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return {name: sorted((tuple(row) for row in db.execute('SELECT * FROM "' + name.replace('"', '""') + '"')), key=repr)
            for name in tables}


def add_history(db, resource_id):
    db.execute('INSERT INTO connection_agents VALUES (?,?,?)', (resource_id, 'ag_synthetic_history', 1.0))
    db.execute('INSERT INTO connection_versions VALUES (?,?,?,?,?,?,?)',
               ('cv_synthetic_history', resource_id, 'b' * 64, 'c' * 64, 'synthetic-history-only', 1, 1.0))
    db.execute('INSERT INTO capability_approvals VALUES (?,?,?,?)',
               ('cv_synthetic_history', 'synthetic.history.v1', 'synthetic_tool', 1.0))
    db.execute('INSERT INTO capability_evidence VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
               ('ce_synthetic_history', 'cv_synthetic_history', 'execution', 'unknown', 1.0, 1.0, 1.0, 2.0,
                'synthetic_history_only', None, '', 'synthetic', 'synthetic', 1, 0, None))
    db.execute('INSERT INTO capability_eligibility VALUES (?,?,?,?,?)',
               (resource_id, 'cv_synthetic_history', 'unknown', 1.0, 2.0))
    db.commit()


def test_success_atomically_commits_resource_revision_receipt_invalidation_and_index_intent(writer):
    current, db, _adapter = writer
    first = current.upsert(command(), operation_id=operation(1), expected_revision=0, observed_at=10)
    assert (first.status, first.change, first.revision, first.replayed) == ('committed', 'new', 1, False)
    identity = first.resource_id
    add_history(db, identity)
    history = {name: rows for name, rows in logical_state(db).items()
               if name in ('connection_agents', 'connection_versions', 'capability_approvals', 'capability_evidence')}
    second = current.upsert(command(name='Changed registry text'), operation_id=operation(2), expected_revision=1, observed_at=20)
    row = db.execute('SELECT id,name,first_seen,last_seen FROM resources').fetchone()
    assert tuple(row) == (identity, 'Changed registry text', 10.0, 20.0)
    assert second.revision == 2
    assert db.execute('SELECT revision FROM catalog_resource_revisions').fetchone()[0] == 2
    assert db.execute('SELECT COUNT(*) FROM catalog_write_operations').fetchone()[0] == 2
    assert db.execute('SELECT COUNT(*) FROM capability_eligibility').fetchone()[0] == 0
    assert db.execute('SELECT COUNT(*) FROM catalog_index_jobs').fetchone()[0] == 2
    assert db.execute('SELECT revision FROM catalog_index_heads').fetchone()[0] == 2
    assert {name: logical_state(db)[name] for name in history} == history


def test_equal_command_is_explicit_new_revision_and_replay_is_not_another_write(writer):
    current, db, _adapter = writer
    first = current.upsert(command(), operation_id=operation(1), expected_revision=0, observed_at=10)
    second = current.upsert(command(), operation_id=operation(2), expected_revision=1, observed_at=20)
    assert second.change == 'unchanged' and second.revision == 2 and second.resource_id == first.resource_id
    before = logical_state(db)
    replay = current.upsert(command(), operation_id=operation(2), expected_revision=1, observed_at=20)
    assert replay.replayed is True and replay.revision == 2 and replay.status == 'committed'
    assert logical_state(db) == before
    assert db.execute('SELECT COUNT(*) FROM catalog_index_jobs').fetchone()[0] == 2


def test_same_operation_id_cannot_change_payload_or_preconditions(writer):
    from agent_market.catalog_writer import WriterError
    current, db, _adapter = writer
    current.upsert(command(), operation_id=operation(1), expected_revision=0, observed_at=10)
    baseline = logical_state(db)
    for altered, expected, observed in ((command(name='Changed'), 0, 10), (command(), 1, 10), (command(), 0, 11)):
        with pytest.raises(WriterError) as captured:
            current.upsert(altered, operation_id=operation(1), expected_revision=expected, observed_at=observed)
        assert captured.value.code == 'operation_conflict'
        assert logical_state(db) == baseline


def test_cas_conflict_receipt_is_stable_even_after_a_later_success(writer):
    current, db, _adapter = writer
    current.upsert(command(), operation_id=operation(1), expected_revision=0, observed_at=10)
    conflict = current.upsert(command(name='Stale candidate'), operation_id=operation(2), expected_revision=0, observed_at=20)
    assert (conflict.status, conflict.revision) == ('conflict', 1)
    current.upsert(command(name='Current candidate'), operation_id=operation(3), expected_revision=1, observed_at=30)
    before = logical_state(db)
    replay = current.upsert(command(name='Stale candidate'), operation_id=operation(2), expected_revision=0, observed_at=20)
    assert replay.status == 'conflict' and replay.revision == 1 and replay.replayed is True
    assert logical_state(db) == before


def test_registry_update_preserves_observation_owned_fields_and_immutable_history(writer):
    current, db, _adapter = writer
    first = current.upsert(command(), operation_id=operation(1), expected_revision=0, observed_at=10)
    add_history(db, first.resource_id)
    values = ('healthy', 1, '{"secret":"synthetic-survey-secret"}', '[]', 'synthetic-full-hash',
              '[]', 'synthetic-compact-hash', '{"method":"synthetic"}', 'A', 91.0, 7.0, 8.0, 2, 5, 6)
    db.execute('''UPDATE resources SET health_status=?,auth_observed=?,auth_info=?,usage_full_tools=?,usage_full_hash=?,
        usage_tools=?,usage_tools_hash=?,usage_guide=?,eval_grade=?,eval_score=?,last_check_at=?,last_ok_at=?,
        consecutive_failures=?,health_ok_24h=?,health_n_24h=?,cap_checked_at=9,eval_at=9''', values)
    db.commit()
    names = ('health_status', 'auth_observed', 'auth_info', 'usage_full_tools', 'usage_full_hash', 'usage_tools',
             'usage_tools_hash', 'usage_guide', 'eval_grade', 'eval_score', 'last_check_at', 'last_ok_at',
             'consecutive_failures', 'health_ok_24h', 'health_n_24h')
    baseline = tuple(db.execute('SELECT ' + ','.join(names) + ' FROM resources').fetchone())
    current.upsert(command(name='Registry-only edit', auth_declared=0), operation_id=operation(2), expected_revision=1, observed_at=20)
    assert tuple(db.execute('SELECT ' + ','.join(names) + ' FROM resources').fetchone()) == baseline
    assert tuple(db.execute('SELECT cap_checked_at,eval_at FROM resources').fetchone()) == (None, None)
    assert db.execute('SELECT COUNT(*) FROM capability_eligibility').fetchone()[0] == 0
    assert db.execute('SELECT COUNT(*) FROM capability_evidence').fetchone()[0] == 1


class FaultCursor(sqlite3.Cursor):
    def execute(self, sql, *args, **kwargs):
        result = super().execute(sql, *args, **kwargs)
        target = getattr(self.connection, 'fail_prefix', None)
        if target and sql.startswith(target):
            self.connection.failures += 1
            raise RuntimeError('synthetic-private-database-failure')
        return result


class FaultConnection(sqlite3.Connection):
    fail_prefix = None
    failures = 0
    def cursor(self, *args, **kwargs):
        kwargs.setdefault('factory', FaultCursor)
        return super().cursor(*args, **kwargs)


@pytest.mark.parametrize('prefix', [
    'UPDATE resources SET source=',
    'UPDATE catalog_resource_revisions SET revision=',
    'DELETE FROM capability_eligibility',
    'UPDATE catalog_index_heads SET revision=',
    'INSERT INTO catalog_index_jobs',
    'INSERT INTO catalog_write_operations',
])
def test_each_accepted_sql_failure_rolls_back_the_entire_write_unit(prefix):
    from agent_market.storage_adapter import StorageError
    db = sqlite3.connect(':memory:', factory=FaultConnection)
    try:
        _adapter, current = seed(db)
        first = current.upsert(command(), operation_id=operation(1), expected_revision=0, observed_at=10)
        add_history(db, first.resource_id)
        before = logical_state(db)
        db.fail_prefix = prefix
        with pytest.raises(StorageError) as captured:
            current.upsert(command(name='Must roll back'), operation_id=operation(2), expected_revision=1, observed_at=20)
        db.fail_prefix = None
        assert captured.value.code == 'statement_failed'
        assert 'synthetic-private' not in str(captured.value)
        assert db.failures == 1 and not db.in_transaction
        assert logical_state(db) == before
        assert current.reconcile(operation(2)) is None
    finally:
        db.close()


@pytest.mark.parametrize('prefix', ['INSERT INTO resources ', 'INSERT INTO catalog_resource_revisions'])
def test_first_identity_or_revision_failure_leaves_no_partial_creation(prefix):
    from agent_market.storage_adapter import StorageError
    db = sqlite3.connect(':memory:', factory=FaultConnection)
    try:
        _adapter, current = seed(db)
        before = logical_state(db)
        db.fail_prefix = prefix
        with pytest.raises(StorageError):
            current.upsert(command(), operation_id=operation(1), expected_revision=0, observed_at=10)
        db.fail_prefix = None
        assert db.failures == 1 and not db.in_transaction
        assert logical_state(db) == before
        assert current.reconcile(operation(1)) is None
        explicit_new_attempt = current.upsert(command(), operation_id=operation(1), expected_revision=0, observed_at=10)
        assert explicit_new_attempt.status == 'committed' and explicit_new_attempt.replayed is False
        assert db.execute('SELECT COUNT(*) FROM resources').fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM catalog_index_jobs').fetchone()[0] == 1
    finally:
        db.close()


def test_unversioned_legacy_resource_is_not_silently_rehashed_or_adopted(writer):
    from agent_market.catalog_writer import WriterError
    current, db, _adapter = writer
    current.upsert(command(), operation_id=operation(1), expected_revision=0, observed_at=10)
    existing = db.execute('SELECT * FROM resources').fetchone()
    columns = tuple(existing.keys())
    legacy = dict(existing)
    legacy.update(id=2, key='mcp:unversioned-legacy', content_hash='historical-legacy-hash', first_seen=1.0, last_seen=1.0)
    db.execute('INSERT INTO resources (' + ','.join(columns) + ') VALUES (' + ','.join('?' for _ in columns) + ')',
               tuple(legacy[name] for name in columns))
    db.commit()
    before = logical_state(db)
    with pytest.raises(WriterError) as captured:
        current.upsert(command(key='mcp:unversioned-legacy'), operation_id=operation(2), expected_revision=0, observed_at=20)
    assert captured.value.code == 'unversioned_resource'
    assert logical_state(db) == before
    assert db.execute('SELECT content_hash FROM resources WHERE id=2').fetchone()[0] == 'historical-legacy-hash'


def test_paused_writer_allows_read_only_reconciliation_but_no_replay_mutation(writer):
    from agent_market.catalog_writer import WriterError
    current, db, _adapter = writer
    first = current.upsert(command(), operation_id=operation(1), expected_revision=0, observed_at=10)
    db.execute('UPDATE catalog_write_controls SET enabled=0,revision=revision+1 WHERE id=1')
    db.commit()
    before = logical_state(db)
    receipt = current.reconcile(operation(1))
    assert receipt.status == 'committed' and receipt.resource_id == first.resource_id
    with pytest.raises(WriterError) as captured:
        current.upsert(command(), operation_id=operation(1), expected_revision=0, observed_at=10)
    assert captured.value.code == 'write_disabled'
    assert logical_state(db) == before


def test_commit_unknown_is_reconciled_from_fresh_connection_without_automatic_reexecution(tmp_path):
    from agent_market.catalog_writer import CatalogWriter
    from agent_market.storage_adapter import SQLiteAdapter, StorageError
    class LostCommitAcknowledgement(sqlite3.Connection):
        armed = False
        commit_attempts = 0
        def commit(self):
            super().commit()
            if self.armed:
                self.commit_attempts += 1
                raise RuntimeError('synthetic-private-commit-acknowledgement')
    path = tmp_path / 'isolated-writer.sqlite3'
    db = sqlite3.connect(path, factory=LostCommitAcknowledgement)
    _adapter, current = seed(db)
    db.armed = True
    try:
        with pytest.raises(StorageError) as captured:
            current.upsert(command(), operation_id=operation(1), expected_revision=0, observed_at=10)
        assert captured.value.code == 'commit_unknown' and db.commit_attempts == 1
    finally:
        db.close()
    fresh = sqlite3.connect(path)
    try:
        replacement = CatalogWriter(SQLiteAdapter(fresh), model_hash=MODEL)
        receipt = replacement.reconcile(operation(1))
        assert receipt.status == 'committed' and receipt.revision == 1
        before = logical_state(fresh)
        replay = replacement.upsert(command(), operation_id=operation(1), expected_revision=0, observed_at=10)
        assert replay.replayed is True and replay.resource_id == receipt.resource_id
        assert logical_state(fresh) == before
        assert fresh.execute('SELECT COUNT(*) FROM resources').fetchone()[0] == 1
        assert fresh.execute('SELECT COUNT(*) FROM catalog_index_jobs').fetchone()[0] == 1
    finally:
        fresh.close()


def test_stale_index_completion_cannot_publish_over_new_writer_revision(writer):
    from agent_market.catalog_index_outbox import CatalogIndexOutbox
    current, db, adapter = writer
    first = current.upsert(command(), operation_id=operation(1), expected_revision=0, observed_at=10)
    outbox = CatalogIndexOutbox(adapter)
    old = outbox.claim('synthetic-worker', now=11, lease_seconds=30)
    assert old.resource_id == first.resource_id and old.revision == 1
    current.upsert(command(name='New corpus'), operation_id=operation(2), expected_revision=1, observed_at=20)
    assert outbox.complete(old, 'f' * 64, now=21) in {'superseded', 'stale_claim'}
    assert outbox.indexed_projection(first.resource_id, MODEL) is None
    new = outbox.claim('new-worker', now=22, lease_seconds=30)
    assert new.revision == 2
    assert outbox.complete(new, 'e' * 64, now=23) == 'indexed'
    assert outbox.indexed_projection(first.resource_id, MODEL).revision == 2
    assert db.execute('SELECT COUNT(*) FROM catalog_index_projections').fetchone()[0] == 1


def test_new_private_resource_still_requires_existing_public_projection(writer):
    from agent_market.catalog_repository import CatalogRepository
    from agent_market.concierge.connections import public_agent
    current, _db, adapter = writer
    result = current.upsert(command(), operation_id=operation(1), expected_revision=0, observed_at=10)
    private = CatalogRepository(adapter).get(result.resource_id).as_private_dict()
    assert 'synthetic-private-token' in private['details']
    assert 'synthetic-private-token' not in repr(result)
    public = public_agent(private, resource=private)
    assert public['url'] == 'https://agentconcierge.biz/api/gateway/mcp/' + str(result.resource_id)
    rendered = json.dumps(public)
    assert 'synthetic-private-token' not in rendered
    assert 'https://provider.example/project/tools' not in rendered
    assert 'https://provider.example/docs' in public['description']
