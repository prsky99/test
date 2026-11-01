"""Independent native sqlite-vec fencing, rollback, and uncertainty checks."""

from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import json
import sqlite3
from threading import Event, RLock

import pytest

from agent_market.legacy_vector_index import (
    ModelDescriptor, VectorError, register, validate_vector,
)


MODEL = ModelDescriptor('synthetic-review-embedding', revision='fixture-v1')


def vector(position=0):
    values = [0.0] * 768
    values[position] = 1.0
    return values


def state(db):
    names = ['vec_resources', 'vec_outbox', 'legacy_vector_generations',
             'legacy_vector_heads', 'legacy_vector_jobs',
             'legacy_vector_provenance', 'legacy_vector_control']
    return {name: tuple(sorted((tuple(row) for row in db.execute('SELECT * FROM ' + name)), key=repr))
            for name in names}


@pytest.fixture
def native_store(tmp_path):
    from agent_market.gateway.admin_auth import ADMIN_SCHEMA, create_admin_user
    from agent_market.gateway.store import Store

    path = tmp_path / 'synthetic-native-vector.sqlite3'
    with sqlite3.connect(path) as db:
        db.executescript(ADMIN_SCHEMA)
        create_admin_user(db, 'sadmin', 'Synthetic-vector-review-password-42',
                          'Synthetic reviewer', 'superadmin')
    store = Store(str(path))
    rid = store.upsert_resource({
        'key': 'synthetic:vector-review', 'source': 'synthetic-review', 'kind': 'mcp',
        'url': 'https://vector-review.example/mcp', 'name': 'Document reader',
        'description': 'Search historical climate documentation', 'category': 'research',
        'networks': [], 'details': {},
    }, now=10)
    try:
        assert store.query('SELECT vec_version()')[0][0]
        yield store, rid
    finally:
        store._db.close()


def claim_one(store, rid, descriptor=MODEL):
    claims = store._vector_index.claim_batch(descriptor, resource_ids=[rid])
    assert len(claims) == 1
    return claims[0]


def test_same_timestamp_outbox_replacement_aba_cannot_ack_newest_job(native_store):
    store, rid = native_store
    index = store._vector_index
    with store.tx() as db:
        db.execute("UPDATE vec_outbox SET enqueued_at=100,reason='same' WHERE resource_id=?", (rid,))
    first = claim_one(store, rid)
    original_source = first.source_hash
    with store.tx() as db:
        db.execute("UPDATE vec_outbox SET reason='middle' WHERE resource_id=?", (rid,))
        db.execute("UPDATE vec_outbox SET reason='same' WHERE resource_id=?", (rid,))
    before = state(store._db)
    assert store.query('SELECT enqueued_at,reason FROM vec_outbox WHERE resource_id=?', (rid,))[0][:] == (100, 'same')
    assert index.publish(first, vector(), MODEL) == 'stale'
    assert index.fail(first, MODEL) == 'stale'
    assert state(store._db) == before
    current = claim_one(store, rid)
    assert current.source_hash == original_source
    assert current.job_id != first.job_id and current.generation > first.generation
    assert index.publish(current, vector(1), MODEL) == 'indexed'
    assert not store.query('SELECT * FROM vec_outbox WHERE resource_id=?', (rid,))
    assert index.current_ids([rid], MODEL) == {rid}


@pytest.mark.parametrize('field,value', [
    ('source', 'synthetic-replacement'), ('category', 'docs_knowledge'), ('active', 0),
    ('auth_declared', 'required'), ('auth_info', '{"scope":"changed"}'),
    ('usage_full_hash', '8' * 64), ('usage_tools', '[{"name":"replacement"}]'),
])
def test_source_binding_and_schema_changes_fence_an_in_flight_claim(native_store, field, value):
    store, rid = native_store
    index = store._vector_index
    claim = claim_one(store, rid)
    with store.tx() as db:
        db.execute('UPDATE resources SET ' + field + '=? WHERE id=?', (value, rid))
    before = state(store._db)
    assert index.publish(claim, vector(), MODEL) == 'stale'
    assert index.fail(claim, MODEL, 'invalid_response') == 'stale'
    assert state(store._db) == before
    assert not index.current_ids([rid], MODEL)
    assert not store.query('SELECT * FROM legacy_vector_provenance WHERE resource_id=?', (rid,))


@pytest.mark.parametrize('changes', [
    {'model_id': 'another-embedding'}, {'revision': 'fixture-v2'},
    {'weights_digest': 'a' * 64},
])
def test_a_different_declared_model_never_reuses_or_acknowledges_a_claim(native_store, changes):
    store, rid = native_store
    index = store._vector_index
    claim = claim_one(store, rid)
    other = replace(MODEL, **changes)
    before = state(store._db)
    assert other.digest != MODEL.digest
    assert index.publish(claim, vector(), other) == 'stale'
    with pytest.raises(VectorError) as error:
        index.claim_batch(other, resource_ids=[rid])
    assert error.value.code == 'model_mismatch'
    assert state(store._db) == before


@pytest.mark.parametrize('values', [
    [], [1.0] * 767, [0.0] * 768, [float('nan')] + [1.0] * 767,
    [float('inf')] + [1.0] * 767, [1e100] + [1.0] * 767,
    [True] + [1.0] * 767, [1e-100] * 768, [10**1000] + [1.0] * 767,
    [1e-30] * 768, [1e38] * 768,
])
def test_invalid_native_vectors_cannot_delete_vectors_or_acknowledge_work(native_store, values):
    store, rid = native_store
    claim = claim_one(store, rid)
    before = state(store._db)
    with pytest.raises(VectorError) as error:
        store._vector_index.publish(claim, values, MODEL)
    assert error.value.code == 'invalid_vector'
    assert state(store._db) == before
    assert not store._db.in_transaction


class AcceptedFault(sqlite3.Connection):
    fail_prefix = None
    failures = 0
    commit_failure = False

    def execute(self, sql, parameters=()):
        result = super().execute(sql, parameters)
        if self.fail_prefix and sql.lstrip().startswith(self.fail_prefix):
            self.failures += 1
            raise RuntimeError('synthetic-private-native-vector-fault')
        return result

    def commit(self):
        result = super().commit()
        if self.commit_failure:
            self.commit_failure = False
            self.failures += 1
            raise sqlite3.DatabaseError('synthetic-private-commit-response-loss')
        return result


def fault_connection(store):
    from agent_market.gateway.rag import ensure_vec_table
    store._db.close()
    db = sqlite3.connect(store._path, check_same_thread=False, factory=AcceptedFault)
    db.row_factory = sqlite3.Row
    assert ensure_vec_table(db)
    db.commit()
    store._db = db
    store._vector_index = register(db, store._lock)
    return db


@pytest.mark.parametrize('prefix', [
    'DELETE FROM vec_resources', 'INSERT INTO vec_resources',
    'INSERT INTO legacy_vector_provenance',
    "UPDATE legacy_vector_jobs SET status='indexed'", 'DELETE FROM vec_outbox',
])
def test_statement_accepted_failure_rolls_back_vector_proof_and_exact_ack(native_store, prefix):
    store, rid = native_store
    db = fault_connection(store)
    index = store._vector_index
    claim = claim_one(store, rid)
    existing, _ = validate_vector(vector(3), MODEL)
    db.execute('INSERT INTO vec_resources(rowid,embedding) VALUES(?,?)', (rid, existing))
    db.commit()
    before = state(db)
    db.fail_prefix = prefix
    with pytest.raises(VectorError) as error:
        index.publish(claim, vector(4), MODEL)
    assert error.value.code == 'database_error'
    db.fail_prefix = None
    assert db.failures == 1, 'The target SQL must have been accepted before fault injection.'
    assert state(db) == before
    assert not db.in_transaction
    assert not index.current_ids([rid], MODEL), 'A raw pre-existing vector is not current proof.'
    assert index.publish(claim, vector(4), MODEL) == 'indexed'
    assert index.current_ids([rid], MODEL) == {rid}


def test_commit_accepted_response_loss_requires_fresh_inspection_without_replay(native_store):
    from agent_market.gateway.rag import ensure_vec_table
    store, rid = native_store
    db = fault_connection(store)
    index = store._vector_index
    claim = claim_one(store, rid)
    db.commit_failure = True
    with pytest.raises(VectorError) as error:
        index.publish(claim, vector(5), MODEL)
    assert error.value.code == 'commit_unknown'
    assert db.failures == 1 and index.broken
    with pytest.raises(VectorError) as unusable:
        index.publish(claim, vector(5), MODEL)
    assert unusable.value.code == 'broken'

    fresh = sqlite3.connect(store._path)
    try:
        assert ensure_vec_table(fresh)
        fresh.commit()
        inspected = register(fresh, RLock())
        assert inspected.current_ids([rid], MODEL) == {rid}
        assert inspected.inspect(claim.job_id, MODEL)['status'] == 'indexed'
        before = state(fresh)
        assert inspected.publish(claim, vector(6), MODEL) == 'stale'
        assert state(fresh) == before
        assert not fresh.execute('SELECT * FROM vec_outbox WHERE resource_id=?', (rid,)).fetchall()
    finally:
        fresh.close()


@pytest.mark.parametrize('aba', [False, True])
def test_raw_engine_helper_cannot_publish_a_binding_changed_during_embedding(native_store, aba):
    import httpx
    from agent_market.gateway.rag import RagEngine
    store, rid = native_store
    initial = store.resource(rid)
    requests = []

    def delayed_embedding(request):
        requests.append(json.loads(request.content))
        with store.tx() as db:
            db.execute('UPDATE resources SET url=? WHERE id=?',
                       ('https://vector-review.example/other', rid))
            if aba:
                db.execute('UPDATE resources SET url=? WHERE id=?', (initial['url'], rid))
        return httpx.Response(200, json={'embeddings': [vector()]})

    with httpx.Client(transport=httpx.MockTransport(delayed_embedding)) as client:
        engine = RagEngine(http=client)
        assert engine.index_resources(store._db, [initial]) == 0
    assert len(requests) == 1
    assert not store.query('SELECT rowid FROM vec_resources WHERE rowid=?', (rid,))
    assert not store.query('SELECT * FROM legacy_vector_provenance WHERE resource_id=?', (rid,))
    assert store.query('SELECT * FROM vec_outbox WHERE resource_id=?', (rid,))


def test_raw_engine_helper_refuses_caller_transaction_without_http_or_commit(native_store):
    import httpx
    from agent_market.gateway.rag import RagEngine
    store, rid = native_store
    initial = store.resource(rid)
    requests = []
    before = store.resource(rid)['name']

    def forbidden_embedding(request):
        requests.append(request)
        return httpx.Response(200, json={'embeddings': [vector()]})

    store._db.execute('UPDATE resources SET name=? WHERE id=?', ('Uncommitted reader', rid))
    assert store._db.in_transaction
    try:
        with httpx.Client(transport=httpx.MockTransport(forbidden_embedding)) as client:
            engine = RagEngine(http=client)
            with pytest.raises(VectorError) as error:
                engine.index_resources(store._db, [initial])
        assert error.value.code == 'caller_transaction'
        assert not requests and store._db.in_transaction
    finally:
        store._db.rollback()
    assert store.resource(rid)['name'] == before


def test_foreign_thread_current_read_waits_for_the_shared_snapshot_lock(native_store):
    store, rid = native_store
    index = store._vector_index
    claim = claim_one(store, rid)
    assert index.publish(claim, vector(), MODEL) == 'indexed'
    started = Event()

    def current_from_other_thread():
        started.set()
        return index.current_ids([rid], MODEL)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with index.read_snapshot():
            future = pool.submit(current_from_other_thread)
            assert started.wait(2)
            with pytest.raises(FutureTimeout):
                future.result(timeout=.05)
            assert index.current_ids([rid], MODEL) == {rid}
        assert future.result(timeout=2) == {rid}


@pytest.mark.parametrize('tamper', ['native-vector', 'provenance-hash'])
def test_current_read_rejects_a_vector_or_proof_changed_outside_the_publisher(native_store, tamper):
    store, rid = native_store
    index = store._vector_index
    claim = claim_one(store, rid)
    assert index.publish(claim, vector(), MODEL) == 'indexed'
    with store.tx() as db:
        if tamper == 'native-vector':
            blob, _ = validate_vector(vector(3), MODEL)
            db.execute('UPDATE vec_resources SET embedding=? WHERE rowid=?', (blob, rid))
        else:
            db.execute('UPDATE legacy_vector_provenance SET vector_hash=? WHERE resource_id=?', ('0' * 64, rid))
    assert not index.current_ids([rid], MODEL)
    assert index.inspect(claim.job_id, MODEL)['current'] is False


def test_install_handles_501_existing_queue_rows_and_lazily_adopts_the_tail():
    from agent_market.gateway.rag import ensure_vec_table
    from agent_market.legacy_vector_index import install

    db = sqlite3.connect(':memory:')
    try:
        assert ensure_vec_table(db)
        db.execute('''CREATE TABLE resources(id INTEGER PRIMARY KEY,name TEXT,description TEXT,
                   category TEXT,active INTEGER,kind TEXT,url TEXT,health_status TEXT,eval_security TEXT)''')
        db.execute('CREATE TABLE vec_outbox(resource_id INTEGER PRIMARY KEY,enqueued_at REAL NOT NULL,reason TEXT NOT NULL)')
        for rid in range(1, 502):
            db.execute('INSERT INTO resources VALUES(?,?,?,?,?,?,?,?,?)',
                       (rid, 'Reader', 'Synthetic document search', 'research', 1, 'mcp',
                        'https://vector-review.example/mcp', 'healthy', 'ok'))
            db.execute('INSERT INTO vec_outbox VALUES(?,?,?)', (rid, 100, 'existing'))
        db.commit()
        with db:
            install(db)
        index = register(db, RLock())
        assert db.execute('SELECT COUNT(*) FROM vec_outbox').fetchone()[0] == 501
        assert db.execute('SELECT COUNT(*) FROM legacy_vector_heads').fetchone()[0] == 500
        claims = index.claim_batch(MODEL, resource_ids=[501])
        assert len(claims) == 1 and claims[0].resource_id == 501
        assert index.publish(claims[0], vector(), MODEL) == 'indexed'
        assert db.execute('SELECT COUNT(*) FROM vec_outbox').fetchone()[0] == 500
        assert index.current_ids([501], MODEL) == {501}
    finally:
        db.close()


def test_store_default_search_merges_dense_candidates_but_rejects_changed_final_details(native_store, monkeypatch):
    import httpx
    from agent_market.gateway.rag import RagEngine
    store, rid = native_store
    calls = []

    def embedding_response(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={'embeddings': [vector()]})

    with httpx.Client(transport=httpx.MockTransport(embedding_response)) as client:
        engine = RagEngine(http=client)
        assert engine.index_resources(store._db, [store.resource(rid)]) == 1
        original = engine.hybrid_search
        kwargs = dict(text='quasarnebula', category='translation', max_price=None,
                      networks=[], kinds=['mcp'], rag_engine=engine)
        first = store.search(**kwargs)
        assert [item['id'] for item in first] == [rid], 'The default 200 limit must still merge dense results.'
        snapshot_description = first[0]['description']
        assert not store.query("SELECT rowid FROM resources_fts WHERE resources_fts MATCH 'quasarnebula'")
        assert first[0]['category'] != 'translation'

        def changed_after_ranking(*args, **options):
            items = original(*args, **options)
            assert len(items) == 1 and items[0]['id'] == rid
            with store.tx() as db:
                db.execute('UPDATE resources SET description=? WHERE id=?', ('Unrelated replacement record', rid))
            return items

        monkeypatch.setattr(engine, 'hybrid_search', changed_after_ranking)
        second = store.search(**kwargs)
        assert not second or (len(second) == 1 and second[0]['id'] == rid
                              and second[0]['description'] == snapshot_description)
    assert len(calls) == 3, 'One index embedding and one embedding per explicit query are expected.'
