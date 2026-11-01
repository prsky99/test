"""Real native search pages retain large contracts within each query limit."""
import json
import os

import pytest


def _checks(store, monkeypatch, *, provision_native_index=True):
    from agent_market.postgres_lexical import install
    from agent_market.application_store_resource_batches import resources
    from agent_market.application_store_postgres import ApplicationStoreError
    from agent_market.application_store_vector import hybrid_search
    from agent_market.gateway.rag import RagEngine
    payload = 'x' * (1600 * 1024)
    ids = [store.upsert_resource({'key': 'fixture:large:' + str(i), 'source': 'fixture', 'kind': 'mcp',
        'name': 'Bounded photonics ' + str(i), 'description': 'Synthetic photonics search fixture',
        'url': 'https://large.example/' + str(i), 'category': 'research', 'details': {'contract': payload}, 'price_usdc': 0,
        'networks': []}, now=10 + i) for i in range(6)]
    if provision_native_index:
        install(store)
    found = store.search('photonics', '', None, [], ['mcp'], limit=45)
    assert {row['id'] for row in found} == set(ids)
    assert all(json.loads(row['details'])['contract'] == payload for row in found)
    assert store.search('photonics', '', None, [], ['a2a'], limit=45) == []
    filtered = store.search('photonics', 'research', 0, ["network' OR 1=1 --"] * 20,
                            ['a2a', 'mcp', 'x402'], limit=45, region="region' OR 1=1 --",
                            auth_free=True, agent_usable=True, min_grade='F')
    assert {row['id'] for row in filtered} == set(ids)
    with store.tx(readonly=True):
        ordered = resources(store, list(reversed(ids)), 'active=1', [])
        assert [row['id'] for row in ordered] == list(reversed(ids))
        assert resources(store, ids, 'active=1 AND category=%s', ["research' OR 1=1 --"]) == []
    fallback = store.search('', 'research', None, [], ['mcp'], limit=45)
    assert {row['id'] for row in fallback} == set(ids)
    engine = RagEngine(embed_model='synthetic-bounded-resources', embed_revision='fixture-v1')
    ranked = hybrid_search(engine, store, 'photonics', embedding_supplied=True)
    assert {row['id'] for row in ranked} == set(ids)
    with pytest.raises(ApplicationStoreError, match='invalid_parameters'):
        resources(store, [True], 'active=1', [])
    # A ranking read names trusted catalog columns only and never carries other contracts.
    with store.tx(readonly=True):
        narrow = resources(store, ids, 'active=1', [], columns=('name', 'usage_tools'))
        assert [row['id'] for row in narrow] == ids and set(dict(narrow[0])) == {'id', 'name', 'usage_tools'}
    for columns in [('name; DROP TABLE resources',), (), ['name'], ('no_such_column',)]:
        with pytest.raises(ApplicationStoreError, match='invalid_parameters'):
            resources(store, ids, 'active=1', [], columns=columns)
    with pytest.raises(ApplicationStoreError, match='invalid_parameters'):
        resources(store, ids, 'active=1', [], columns=('name',), hydrate_contracts=True)
    # The aggregate operation stays bounded even when several native
    # queries are needed; a failed page does not poison future reads.
    monkeypatch.setattr('agent_market.application_store_resource_batches.MAX_RESOURCE_BYTES', 2 * 1024 * 1024)
    with pytest.raises(ApplicationStoreError, match='result_limit'):
        store.search('photonics', '', None, [], ['mcp'], limit=45)
    assert store.resource(ids[0])['id'] == ids[0]
    with store.tx(readonly=True):
        partial = resources(store, list(reversed(ids)), 'active=1', [], allow_partial=True)
        assert len(partial) == 1 and partial[0]['id'] == ids[-1]
        assert json.loads(partial[0]['details'])['contract'] == payload
        assert resources(store, ids, 'active=1', [], allow_partial=True)


def test_large_provider_contracts_search_hybrid_filters_and_category_keep_complete_rows(monkeypatch):
    if os.environ.get('AC_TEST_POSTGRES_OWNED_SCHEMA') == '1':
        from scripts import rehearse_b2a_retention_postgres as harness
        def contracts(connect, factory):
            conn = connect()
            store = factory(conn, initialize=True, workflow_key=b'a' * 32)
            try:
                # Owned-schema fixtures never install or use operating indexes.
                # The byte-bounded resource reader is identical in both paths.
                _checks(store, monkeypatch, provision_native_index=False)
                return {'checks': {'large_resource_contracts': True}}
            finally:
                store.close()
                conn.close()
        monkeypatch.setattr(harness, '_contracts', contracts)
        result = harness.schema_rehearsal()
        assert result['owned_schemas_removed'] and result['checks']['large_resource_contracts']
        return
    import psycopg
    from scripts.rehearse_storage_adapter_postgres import _private_cluster, _tools, PORT
    from agent_market.storage_adapter import open_store
    with _private_cluster(_tools()) as cluster:
        conn = psycopg.connect(host=cluster['socket'], port=PORT, dbname='postgres', user='postgres', autocommit=True)
        store = open_store('postgresql', connection=conn, initialize=True, workflow_key=b'a' * 32)
        try:
            _checks(store, monkeypatch)
        finally:
            store.close()
            conn.close()
