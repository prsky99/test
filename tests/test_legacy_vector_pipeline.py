"""Native sqlite-vec consumer and bounded fake embedding transport regressions."""

import json
import sqlite3

import httpx
import pytest

from agent_market.gateway.rag import (
    MAX_EMBED_RESPONSE_BYTES, RagEngine, RagPipeline, load_sqlite_vec,
)
from agent_market.legacy_vector_index import VectorError, lookup, validate_vector


def vector(position=0):
    values = [0.0] * 768
    values[position] = 1.0
    return values


def embedding_response(request):
    return httpx.Response(200, json={'embeddings': [vector() for _ in json.loads(request.content)['input']]})


@pytest.fixture
def native_store(tmp_path):
    from agent_market.gateway.admin_auth import ADMIN_SCHEMA, create_admin_user
    from agent_market.gateway.store import Store

    path = tmp_path / 'synthetic-vector-consumer.sqlite3'
    with sqlite3.connect(path) as db:
        db.executescript(ADMIN_SCHEMA)
        create_admin_user(db, 'sadmin', 'Synthetic-vector-consumer-password-42',
                          'Synthetic consumer fixture', 'superadmin')
    store = Store(str(path))
    rid = store.upsert_resource({
        'key': 'synthetic:vector-consumer', 'source': 'synthetic-consumer', 'kind': 'mcp',
        'url': 'https://vector-consumer.example/mcp', 'name': 'Climate archive',
        'description': 'Search historical climate documentation', 'category': 'research',
        'networks': [], 'details': {},
    }, now=10)
    with store.tx() as db:
        db.execute("UPDATE resources SET health_status='healthy',eval_security='ok' WHERE id=?", (rid,))
    try:
        assert store.query('SELECT vec_version()')[0][0]
        yield store, rid, path
    finally:
        store._db.close()


@pytest.mark.parametrize('texts', [
    ['text'] * 51, ['\0'], ['\ud800'], ['é' * 4097], [''], ('text',),
    ['"' * 8192] * 50,
])
def test_invalid_or_oversized_embedding_input_never_contacts_transport(texts):
    calls = []
    with httpx.Client(transport=httpx.MockTransport(lambda request: calls.append(request))) as client:
        assert RagEngine(http=client).embed_texts(texts) is None
    assert calls == []


@pytest.mark.parametrize('body', [
    {'embeddings': []}, {'embeddings': [vector(), vector()]},
    {'embeddings': [[1.0] * 767]}, {'embeddings': [[True] * 768]},
    {'embeddings': [[0.0] * 768]}, {'embeddings': [[1e40] * 768]},
    {'embeddings': [[float('nan')] * 768]}, {'embeddings': [[float('inf')] * 768]},
    {'embeddings': [[1e-30] * 768]}, {'embeddings': [[1e20] * 768]},
])
def test_invalid_embedding_response_is_not_accepted(body):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
            200, content=json.dumps(body), headers={'content-type': 'application/json'}))) as client:
        assert RagEngine(http=client).embed_texts(['synthetic query']) is None


@pytest.mark.parametrize('response', [
    lambda: httpx.Response(302, headers={'location': 'https://outside.example/private'}),
    lambda: httpx.Response(200, content='{}', headers={'content-type': 'text/html'}),
    lambda: httpx.Response(200, content=b'\xff', headers={'content-type': 'application/json'}),
    lambda: httpx.Response(200, content='{"embeddings":[],"embeddings":[]}', headers={'content-type': 'application/json'}),
    lambda: httpx.Response(200, content='{"embeddings":[]}', headers={'content-type': 'application/json', 'content-encoding': 'identity, gzip'}),
])
def test_non_json_redirect_duplicate_or_encoded_response_is_rejected(response):
    calls = []
    def handler(request):
        calls.append(request)
        return response()
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert RagEngine(http=client).embed_texts(['synthetic query']) is None
    assert len(calls) == 1
    assert calls[0].headers['accept-encoding'] == 'identity'


class ChunkStream(httpx.SyncByteStream):
    def __init__(self, count, chunk):
        self.count, self.chunk, self.reads, self.closed = count, chunk, 0, False

    def __iter__(self):
        for _ in range(self.count):
            self.reads += 1
            yield self.chunk

    def close(self):
        self.closed = True


def test_streamed_response_size_limit_stops_and_closes_transport():
    stream = ChunkStream(1000, b'x' * 16384)
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
            200, stream=stream, headers={'content-type': 'application/json'}))) as client:
        assert RagEngine(http=client).embed_texts(['synthetic query']) is None
    assert stream.closed
    assert stream.reads == MAX_EMBED_RESPONSE_BYTES // 16384 + 1


def test_compressed_stream_is_refused_before_any_body_iteration():
    stream = ChunkStream(1000, b'not-a-compressed-body')
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
            200, stream=stream, headers={'content-type': 'application/json', 'content-encoding': 'gzip'}))) as client:
        assert RagEngine(http=client).embed_texts(['synthetic query']) is None
    assert stream.closed and stream.reads == 0


def test_pipeline_makes_one_request_per_claim_and_publishes_native_vector(native_store):
    store, rid, _path = native_store
    calls = []
    def handler(request):
        assert not store._db.in_transaction
        calls.append(json.loads(request.content))
        return embedding_response(request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        engine = RagEngine(http=client)
        result = RagPipeline(engine, batch_size=1000).step(store)
        assert result['count'] == 1 and result['stale'] == 0 and result['failed'] == 0
        assert len(calls) == 1 and len(calls[0]['input']) == 1
        assert store._vector_index.current_ids([rid], engine.model_descriptor()) == {rid}
        assert store.vec_stats()['outbox_count'] == 0
        assert store.query('SELECT count(*) FROM vec_resources')[0][0] == 1
        assert RagPipeline(engine).step(store)['type'] == 'idle'


def test_source_mutation_during_http_keeps_replacement_pending(native_store):
    store, rid, _path = native_store
    def handler(request):
        assert not store._db.in_transaction
        with store.tx() as db:
            db.execute("UPDATE resources SET category='replacement' WHERE id=?", (rid,))
        return embedding_response(request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = RagPipeline(RagEngine(http=client), batch_size=1).step(store)
    assert result['count'] == 0 and result['stale'] == 1
    assert store.query('SELECT count(*) FROM vec_resources')[0][0] == 0
    assert store.query('SELECT 1 FROM vec_outbox WHERE resource_id=?', (rid,))


@pytest.mark.parametrize('attribute,replacement', [('embed_revision', 'changed-v2'), ('ollama_url', 'https://changed.example')])
def test_engine_binding_change_during_http_never_publishes(native_store, attribute, replacement):
    store, _rid, _path = native_store
    engine = None
    def handler(request):
        setattr(engine, attribute, replacement)
        return embedding_response(request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        engine = RagEngine(http=client)
        result = RagPipeline(engine, batch_size=1).step(store)
    assert result['count'] == 0 and result['failed'] == 1
    assert store.query('SELECT count(*) FROM vec_resources')[0][0] == 0
    assert store.vec_stats()['outbox_count'] == 1


def test_query_http_runs_before_native_snapshot_and_none_never_retries(native_store):
    store, rid, path = native_store
    calls = []
    with httpx.Client(transport=httpx.MockTransport(embedding_response)) as client:
        engine = RagEngine(http=client)
        assert RagPipeline(engine).step(store)['count'] == 1
    def query_handler(request):
        assert not store._db.in_transaction
        calls.append(request)
        with sqlite3.connect(path, timeout=.1) as other:
            other.execute("UPDATE resources SET description='Replacement archive information' WHERE id=?", (rid,))
        return embedding_response(request)
    with httpx.Client(transport=httpx.MockTransport(query_handler)) as client:
        engine.http = client
        result = engine.hybrid_search(store._db, 'climate')
        assert all(not row['dense_match'] for row in result)
        assert len(calls) == 1
        result = engine.hybrid_search(store._db, 'archive', query_embedding=None)
        assert result and all(row['bm25_match'] and not row['dense_match'] for row in result)
        assert len(calls) == 1


def test_dense_vector_needs_matching_model_descriptor_and_current_provenance(native_store):
    store, rid, _path = native_store
    with httpx.Client(transport=httpx.MockTransport(embedding_response)) as client:
        engine = RagEngine(http=client)
        assert RagPipeline(engine).step(store)['count'] == 1
        assert engine.hybrid_search(store._db, 'unrelatedterm', query_embedding=vector()) == []
        rows = engine.hybrid_search(store._db, 'unrelatedterm', query_embedding=vector(), query_descriptor=engine.model_descriptor())
        assert rows[0]['id'] == rid and rows[0]['dense_match'] and not rows[0]['bm25_match']
        with store.tx() as db:
            db.execute('DELETE FROM legacy_vector_provenance WHERE resource_id=?', (rid,))
        assert engine.hybrid_search(store._db, 'unrelatedterm', query_embedding=vector(), query_descriptor=engine.model_descriptor()) == []


def test_store_loader_is_inside_same_native_read_snapshot(native_store):
    store, rid, _path = native_store
    with httpx.Client(transport=httpx.MockTransport(embedding_response)) as client:
        engine = RagEngine(http=client)
        assert RagPipeline(engine).step(store)['count'] == 1
        def loader(db, ranked):
            assert db is store._db and db.in_transaction
            assert ranked[0]['id'] == rid and ranked[0]['dense_match']
            return [dict(db.execute('SELECT * FROM resources WHERE id=?', (rid,)).fetchone())]
        rows = engine.hybrid_search(store._db, 'unrelatedterm', query_embedding=vector(),
                                   query_descriptor=engine.model_descriptor(), _store_filter=loader)
        assert rows[0]['key'] == 'synthetic:vector-consumer'
        assert not store._db.in_transaction


def test_read_only_query_handles_are_not_cached_or_bootstrapped(native_store):
    _store, _rid, path = native_store
    engine = RagEngine(http=httpx.Client(transport=httpx.MockTransport(embedding_response)))
    try:
        for _ in range(35):
            with sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True) as db:
                db.row_factory = sqlite3.Row
                assert load_sqlite_vec(db)
                before = tuple(db.execute('SELECT name,sql FROM sqlite_master'))
                assert engine.hybrid_search(db, 'climate', query_embedding=None)
                assert tuple(db.execute('SELECT name,sql FROM sqlite_master')) == before
        assert engine._vector_indexes == {}
    finally:
        engine.http.close()


def test_raw_bootstrap_commit_uncertainty_poison_is_not_reinitialized(native_store):
    store, rid, path = native_store
    class AcceptedCommit(sqlite3.Connection):
        reject_commit = False
        commit_calls = 0

        def commit(self):
            self.commit_calls += 1
            super().commit()
            if self.reject_commit:
                self.reject_commit = False
                raise sqlite3.OperationalError('synthetic post-acceptance failure')

    raw = sqlite3.connect(path, factory=AcceptedCommit)
    calls = []
    with httpx.Client(transport=httpx.MockTransport(lambda request: calls.append(request))) as client:
        engine = RagEngine(http=client)
        current = dict(store.query('SELECT * FROM resources WHERE id=?', (rid,))[0])
        expected = {key: current[key] for key in ('id', 'name', 'description', 'category')}
        raw.reject_commit = True
        with pytest.raises(VectorError, match='commit_unknown'):
            engine.index_resources(raw, [expected])
        assert lookup(raw).broken and raw.commit_calls == 1
        with pytest.raises(VectorError, match='broken'):
            engine.index_resources(raw, [expected])
        assert raw.commit_calls == 1 and calls == []
    raw.close()


def test_missing_legacy_metadata_allows_only_lexical_search_without_ddl():
    db = sqlite3.connect(':memory:')
    db.execute('''CREATE TABLE resources(id INTEGER PRIMARY KEY,kind TEXT,source TEXT,name TEXT,url TEXT,
        description TEXT,category TEXT,active INTEGER,health_status TEXT,price_usdc INTEGER,
        probe_latency_ms INTEGER,eval_grade TEXT,eval_score REAL,eval_security TEXT,trial_ok INTEGER,
        payers_30d INTEGER,calls_30d INTEGER)''')
    db.execute('CREATE VIRTUAL TABLE resources_fts USING fts5(name,description)')
    db.execute("INSERT INTO resources VALUES(1,'mcp','synthetic','Climate archive','https://archive.example',"
               "'Historical climate documents','research',1,'healthy',0,10,'A',90,'ok',1,0,0)")
    db.execute("INSERT INTO resources_fts(rowid,name,description) VALUES(1,'Climate archive','Historical climate documents')")
    db.commit()
    before = tuple(db.execute('SELECT name,sql FROM sqlite_master'))
    with httpx.Client(transport=httpx.MockTransport(embedding_response)) as client:
        rows = RagEngine(http=client).hybrid_search(db, 'climate', query_embedding=None)
    assert len(rows) == 1 and rows[0]['bm25_match'] and not rows[0]['dense_match']
    assert tuple(db.execute('SELECT name,sql FROM sqlite_master')) == before
    db.close()


def test_transport_errors_do_not_log_raw_response_or_endpoint(caplog):
    def handler(request):
        raise httpx.ConnectError('synthetic-private-response-secret', request=request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert RagEngine(http=client, ollama_url='https://private-synthetic-host.example').embed_texts(['synthetic query']) is None
    assert 'Embedding response unavailable or invalid.' in caplog.text
    assert 'synthetic-private-response-secret' not in caplog.text
    assert 'private-synthetic-host' not in caplog.text
