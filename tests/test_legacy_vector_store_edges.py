"""Full Store producer and startup compatibility checks, using synthetic data."""

import json

import pytest

from agent_market.gateway.store import FTS_TOOLS_VERSION, Store, extract_tool_search_text


@pytest.mark.parametrize('tags,expected', [
    (['orbitmarker', None, 42, {'x': 'bad'}], 'orbitmarker'),
    ('orbitmarker', 'orbitmarker'),
    (None, ''),
    (42, ''),
])
def test_malformed_tool_tags_preserve_searchable_name(tags, expected):
    text = extract_tool_search_text(json.dumps([
        {'name': 'lookup_item', 'description': 'Find a document', 'tags': tags},
    ]))
    assert 'lookup_item' in text and 'Find a document' in text
    assert expected in text


def test_existing_tag_fts_is_rebuilt_once(tmp_path):
    path = str(tmp_path / 'store.sqlite3')
    store = Store(path)
    rid = store.upsert_resource({
        'key': 'mcp:synthetic', 'source': 'registered', 'kind': 'mcp',
        'url': 'https://vector.example/mcp', 'name': 'Document finder',
        'description': 'Look up documentation', 'category': 'docs_knowledge',
        'networks': [], 'price_usdc': 0, 'details': {},
    })
    with store.tx() as db:
        db.execute('UPDATE resources SET usage_tools=? WHERE id=?',
                   (json.dumps([{'name': 'lookup_item', 'tags': ['orbitmarker', None]}]), rid))
        db.execute("UPDATE meta SET value='1' WHERE key='fts_tools_version'")
        # Force a migration that fires persisted vec0 triggers before late setup.
        db.execute("UPDATE resources SET host=NULL WHERE id=?", (rid,))
        db.execute("UPDATE meta SET value='6' WHERE key='classifier_version'")
    store._db.close()
    reopened = Store(path)
    try:
        assert reopened.query('SELECT rowid FROM resources_fts WHERE resources_fts MATCH ?',
                              ('orbitmarker',))[0][0] == rid
        assert json.loads(reopened.query("SELECT value FROM meta WHERE key='fts_tools_version'")[0][0]) == FTS_TOOLS_VERSION
        assert reopened._vector_index.db is reopened._db
    finally:
        reopened._db.close()


def test_stats_distinguish_unverified_storage_and_current_model():
    from agent_market.legacy_vector_index import ModelDescriptor, validate_vector
    store = Store()
    try:
        rid = store.upsert_resource({
            'key': 'mcp:stats', 'source': 'registered', 'kind': 'mcp',
            'url': 'https://stats.example/mcp', 'name': 'Document finder',
            'description': 'Find documentation', 'category': 'docs_knowledge',
            'networks': [], 'details': {},
        })
        model = ModelDescriptor('synthetic-stats')
        values = [1.0] + [0.0] * 767
        with store.tx() as db:
            db.execute('INSERT INTO vec_resources(rowid,embedding) VALUES(?,?)',
                       (rid, validate_vector(values, model)[0]))
        assert store.vec_stats()['vector_count'] == 0
        assert store.vec_stats()['raw_vector_count'] == 1
        claim = store._vector_index.claim_batch(model, resource_ids=[rid])[0]
        assert store._vector_index.publish(claim, values, model) == 'indexed'
        assert store.vec_stats(model)['vector_count'] == 1
        assert store.vec_stats(ModelDescriptor('different-model'))['vector_count'] == 0
    finally:
        store._db.close()


def test_store_query_embedding_does_not_hold_database_lock(monkeypatch):
    import threading
    from agent_market.gateway.rag import RagEngine
    store = Store()
    engine = RagEngine()
    workers = []
    completed = threading.Event()

    def embed(_query):
        worker = threading.Thread(target=lambda: (store.query('SELECT 1'), completed.set()))
        workers.append(worker)
        worker.start()
        assert completed.wait(2), 'Embedding must run outside the Store database lock.'
        return None

    monkeypatch.setattr(engine, 'embed_query', embed)
    try:
        assert store.search('nonexistent', 'unrelated', None, [], ['mcp'], rag_engine=engine) == []
        assert completed.is_set()
    finally:
        for worker in workers:
            worker.join(2)
        engine.http.close()
        store._db.close()


def test_updated_keywords_advance_persisted_classifier_revision(tmp_path):
    from agent_market.gateway.classify import VERSION, classify
    path = str(tmp_path / 'classifier.sqlite3')
    store = Store(path)
    rid = store.upsert_resource({
        'key': 'mcp:classification', 'source': 'synthetic-registry', 'kind': 'mcp',
        'url': 'https://classification.example/mcp', 'name': 'Weather forecast',
        'description': 'Weather forecast temperature', 'category': 'other',
        'networks': [], 'details': {},
    })
    with store.tx() as db:
        db.execute("UPDATE meta SET value='7' WHERE key='classifier_version'")
        db.execute("UPDATE resources SET category='other' WHERE id=?", (rid,))
    store._db.close()
    reopened = Store(path)
    try:
        assert VERSION > 7
        assert json.loads(reopened.query("SELECT value FROM meta WHERE key='classifier_version'")[0][0]) == VERSION
        assert reopened.resource(rid)['category'] == classify('Weather forecast Weather forecast temperature') != 'other'
    finally:
        reopened._db.close()
