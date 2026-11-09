"""Registry refreshes must not flip categories or re-embed the same text (2026-11-09).

46% of 175k daily embeddings repeated text already embedded: the A2A registry's own labels
overwrote our categories every ~30 minutes, and every invalidation deleted and re-inserted
the same vector in the HNSW-indexed table.
"""
from pathlib import Path

import pytest

from agent_market.broker.categories import CATEGORIES
from agent_market.gateway.crawler import parse_a2a_item
from agent_market.gateway.store import Store


def _item(**extra):
    return {'url': 'https://agent.example/a2a', 'name': 'Deploy helper',
            'description': 'Deploys static sites to a CDN and reports build status', **extra}


def test_registry_labels_outside_our_categories_are_reclassified():
    record = parse_a2a_item(_item(category='developer-tools'))
    assert record['category'] in CATEGORIES
    assert parse_a2a_item(_item(category='finance_crypto'))['category'] == 'finance_crypto'


def _row(**extra):
    return {'key': 'a2a:https://agent.example/a2a', 'source': 'a2a-registry', 'kind': 'a2a',
            'url': 'https://agent.example/a2a', 'name': 'Deploy helper', 'description': 'Deploys sites',
            'category': 'dev_tools', 'networks': [], 'details': {}, 'last_called': 100.0, **extra}


def test_a_registry_refresh_keeps_the_collector_category(tmp_path):
    store = Store(str(tmp_path / 'churn.sqlite3'))
    rid = store.upsert_resource(_row(), now=10)
    store.set_category(rid, 'agent_infra')  # the agent-card check knows better
    # Only the registry's updated_at moved: the text is the same, so the category stays.
    store.upsert_resource(_row(last_called=200.0), now=20)
    assert store.resource(rid)['category'] == 'agent_infra'
    # New text is classified again from the crawler's record.
    store.upsert_resource(_row(last_called=300.0, description='Sends SMS messages'), now=30)
    assert store.resource(rid)['category'] == 'dev_tools'


def test_a_registry_activity_refresh_keeps_the_capability_check_and_evaluation(tmp_path):
    # 2026-11-10: 613 A2A listings were re-checked and re-evaluated every ~30 minutes.
    store = Store(str(tmp_path / 'activity.sqlite3'))
    rid = store.upsert_resource(_row(price_usdc=0.0), now=10)
    with store.tx() as db:
        db.execute('UPDATE resources SET cap_checked_at=50, eval_at=60 WHERE id=?', (rid,))
    store.upsert_resource(_row(price_usdc=0.0, last_called=200.0, calls_30d=7), now=20)
    assert (store.resource(rid)['cap_checked_at'], store.resource(rid)['eval_at']) == (50, 60)
    # A new version in the registry entry is checked again.
    store.upsert_resource(_row(price_usdc=0.0, last_called=300.0, details={'version': '2'}), now=30)
    assert (store.resource(rid)['cap_checked_at'], store.resource(rid)['eval_at']) == (None, None)


def test_a_stored_label_outside_our_categories_is_replaced(tmp_path):
    store = Store(str(tmp_path / 'label.sqlite3'))
    rid = store.upsert_resource(_row(category='developer-tools'), now=10)
    store.upsert_resource(_row(last_called=200.0), now=20)
    assert store.resource(rid)['category'] == 'dev_tools'


def test_same_text_reuses_the_stored_vector_without_ollama(monkeypatch):
    import psycopg
    from scripts.rehearse_storage_adapter_postgres import _private_cluster, PORT
    from agent_market.storage_adapter import open_store
    from agent_market.legacy_vector_index import ModelDescriptor
    from agent_market.postgres_ann import install, cleanup
    from agent_market.gateway.rag import RagEngine
    binary = Path('/opt/homebrew/opt/postgresql@18/bin')
    if not (binary / 'initdb').is_file():
        pytest.skip('PostgreSQL 18 fixture tools unavailable')
    with _private_cluster({name: str(binary / name) for name in ('initdb', 'pg_ctl')}) as cluster:
        with psycopg.connect(host=cluster['socket'], port=PORT, dbname='postgres', user='postgres', autocommit=True) as conn:
            conn.execute('CREATE EXTENSION vector')
            store = open_store('postgresql', connection=conn, initialize=True, workflow_key=b'a' * 32)
            descriptor = ModelDescriptor('synthetic-reuse', revision='fixture-v1')
            vector = [0.25] + [0.0] * 766 + [0.5]
            row = {'key': 'fixture:reuse', 'source': 'fixture', 'kind': 'mcp', 'name': 'Reuse fixture',
                   'url': 'https://reuse.example/mcp', 'description': 'Synthetic text', 'category': 'dev_tools',
                   'networks': [], 'details': {}}
            rid = store.upsert_resource(row, now=10)
            index = store._vector_index
            index.ensure_jobs(descriptor, limit=1, resource_ids=(rid,))
            claim = index.claim_batch(descriptor, limit=1, resource_ids=(rid,))[0]
            assert index.publish(claim, vector, descriptor) == 'indexed'
            assert install(store)['indexed'] == 1
            engine = RagEngine(embed_model='synthetic-reuse', embed_revision='fixture-v1')
            monkeypatch.setattr(engine, 'model_descriptor', lambda: descriptor)
            calls = []
            monkeypatch.setattr(engine, 'embed_texts', lambda texts, **_: calls.append(texts) or [vector])

            def stats():
                with store.tx(readonly=True):
                    store._execute('SELECT pg_stat_force_next_flush()')
                with store.tx(readonly=True):
                    return store._execute("SELECT n_tup_ins+n_tup_upd+n_tup_del FROM pg_stat_user_tables "
                                          "WHERE schemaname='agentcon_search' AND relname='embeddings'").fetchone()[0]

            # A registry refresh (registered SQL on PostgreSQL) keeps the collector's category.
            with store.tx():
                store._execute("UPDATE resources SET category='agent_infra' WHERE id=%s", (rid,))
            with store.tx():
                store._execute("UPDATE resources SET cap_checked_at=50, eval_at=60 WHERE id=%s", (rid,))
            store.upsert_resource(row | {'last_called': 5.0, 'price_usdc': 0.01, 'details': {'skills': ['a']}}, now=15)
            assert store.resource(rid)['category'] == 'agent_infra'
            store.upsert_resource(row | {'last_called': 6.0, 'price_usdc': 0.01, 'details': {'skills': ['a']}}, now=16)
            assert (store.resource(rid)['cap_checked_at'], store.resource(rid)['eval_at']) == (None, None)  # details changed at 15
            with store.tx():
                store._execute("UPDATE resources SET cap_checked_at=50, eval_at=60 WHERE id=%s", (rid,))
            store.upsert_resource(row | {'last_called': 7.0, 'price_usdc': 0.01, 'details': {'skills': ['a']}}, now=17)
            assert (store.resource(rid)['cap_checked_at'], store.resource(rid)['eval_at']) == (50, 60)
            index.ensure_jobs(descriptor, limit=1, resource_ids=(rid,))
            claim = index.claim_batch(descriptor, limit=1, resource_ids=(rid,))[0]
            assert engine._publish_claim(index, claim, descriptor) == 'indexed'
            calls.clear()
            # A health change invalidates the vector, but the text is the same.
            with store.tx():
                store._execute("UPDATE resources SET health_status='healthy' WHERE id=%s", (rid,))
            before = stats()
            assert cleanup(store) == 0  # the waiting listing keeps its row
            index.ensure_jobs(descriptor, limit=1, resource_ids=(rid,))
            claim = index.claim_batch(descriptor, limit=1, resource_ids=(rid,))[0]
            assert engine._publish_claim(index, claim, descriptor) == 'indexed'
            assert calls == [] and stats() == before  # no Ollama call, no write to the HNSW table
            assert index.current_ids([rid], descriptor) == {rid}
            # Changed text is embedded again.
            store.upsert_resource(row | {'description': 'Different text'}, now=20)
            index.ensure_jobs(descriptor, limit=1, resource_ids=(rid,))
            claim = index.claim_batch(descriptor, limit=1, resource_ids=(rid,))[0]
            assert engine._publish_claim(index, claim, descriptor) == 'indexed'
            assert len(calls) == 1
            # The live 402 quote survives a refresh of the same bazaar entry (registered SQL on PostgreSQL).
            paid = {'key': 'x402:https://reuse.example/pay', 'source': 'fixture', 'kind': 'x402', 'name': 'Paid fixture',
                    'url': 'https://reuse.example/pay', 'description': 'Paid text', 'category': 'data_utility',
                    'networks': ['base'], 'price_usdc': 3000, 'details': {'accepts': [{'amount': '3000'}]}}
            pid = store.upsert_resource(paid, now=30)
            store.record_observed_quote(pid, 10000)
            quoted = store.resource(pid)['content_hash']
            store.upsert_resource(paid, now=40)
            assert (store.resource(pid)['price_usdc'], store.resource(pid)['content_hash']) == (10000, quoted)
            store.close()


def test_a_zero_quote_from_a_dynamic_price_api_keeps_the_listed_price(tmp_path):
    # 2026-11-10: three x402 batch APIs answer an empty probe with amount 0; they are not free.
    import time
    store = Store(str(tmp_path / 'quote.sqlite3'))
    row = {'key': 'x402:https://pay.example/batch', 'source': 'x402-bazaar', 'kind': 'x402',
           'url': 'https://pay.example/batch', 'name': 'Batch scorer', 'description': 'Scores a batch',
           'category': 'data_utility', 'networks': ['base'], 'price_usdc': 10000, 'details': {}}
    rid = store.upsert_resource(row, now=10)
    result = store.record_health(rid, 'healthy', 402, 10, None, time.time() + 3600, observed_price=0)
    assert store.resource(rid)['price_usdc'] == 10000 and not result['price_changed']
    # A real positive quote still replaces the listed price.
    store.record_health(rid, 'healthy', 402, 10, None, time.time() + 3600, observed_price=20000)
    assert store.resource(rid)['price_usdc'] == 20000


def test_a_zero_quote_without_a_listed_price_is_stored_as_unknown_not_free(tmp_path):
    import time
    from agent_market.gateway.crawler import parse_x402_item
    store = Store(str(tmp_path / 'unknown.sqlite3'))
    row = {'key': 'x402:https://pay.example/dyn', 'source': 'x402-bazaar', 'kind': 'x402',
           'url': 'https://pay.example/dyn', 'name': 'Dynamic scorer', 'description': 'Prices per batch',
           'category': 'data_utility', 'networks': ['base'], 'price_usdc': 0, 'details': {}}
    rid = store.upsert_resource(row, now=10)
    store.record_health(rid, 'healthy', 402, 10, None, time.time() + 3600, observed_price=0)
    assert store.resource(rid)['price_usdc'] is None
    store.record_health(rid, 'healthy', 402, 10, None, time.time() + 3600, observed_price=0)
    assert store.resource(rid)['price_usdc'] is None  # stays unknown
    usdc = '0x833589fcd6edb6e08f4c7c32d4f71b54bda02913'
    item = {'resource': 'https://pay.example/dyn', 'accepts': [
        {'network': 'eip155:8453', 'asset': usdc, 'amount': '0', 'payTo': '0xabc'}]}
    assert parse_x402_item(item)['price_usdc'] is None
    item['accepts'][0]['amount'] = '5000'
    assert parse_x402_item(item)['price_usdc'] == 5000


def test_a_registry_refresh_keeps_the_live_quote_for_the_same_entry(tmp_path):
    # 2026-11-10: the bazaar amount and the provider's 402 quote overwrote each other.
    import time
    store = Store(str(tmp_path / 'pingpong.sqlite3'))
    row = {'key': 'x402:https://pay.example/q', 'source': 'x402-bazaar', 'kind': 'x402',
           'url': 'https://pay.example/q', 'name': 'Quote API', 'description': 'Answers questions',
           'category': 'data_utility', 'networks': ['base'], 'price_usdc': 3000, 'pay_to': '0xAA',
           'details': {'accepts': [{'amount': '3000'}]}}
    rid = store.upsert_resource(row, now=10)
    store.record_health(rid, 'healthy', 402, 10, None, time.time() + 3600, observed_price=10000, observed_pay_to='0xBB')
    hash_after_quote = store.resource(rid)['content_hash']
    assert store.upsert_resource(row, now=20) == rid
    stored = store.resource(rid)
    assert (stored['price_usdc'], stored['pay_to'], stored['content_hash']) == (10000, '0xbb', hash_after_quote)
    assert stored['last_seen'] == 20
    # The quote stays, so the next health check sees no change.
    assert not store.record_health(rid, 'healthy', 402, 10, None, time.time() + 3600, observed_price=10000)['price_changed']
    # A changed registry entry brings its own price until the next quote.
    store.upsert_resource(row | {'price_usdc': 5000, 'details': {'accepts': [{'amount': '5000'}]}}, now=30)
    assert store.resource(rid)['price_usdc'] == 5000


def test_an_unknown_price_from_a_zero_quote_survives_the_registry_refresh(tmp_path):
    import time
    store = Store(str(tmp_path / 'keepnull.sqlite3'))
    row = {'key': 'x402:https://pay.example/z', 'source': 'x402-bazaar', 'kind': 'x402',
           'url': 'https://pay.example/z', 'name': 'Dyn', 'description': 'Dynamic', 'category': 'data_utility',
           'networks': ['base'], 'price_usdc': 0, 'details': {'accepts': [{'amount': '0'}]}}
    rid = store.upsert_resource(row, now=10)
    store.record_health(rid, 'healthy', 402, 10, None, time.time() + 3600, observed_price=0)
    store.upsert_resource(row | {'price_usdc': None}, now=20)  # the crawler reads a listed 0 as unknown
    assert store.resource(rid)['price_usdc'] is None


def test_a_listed_price_replaces_an_unknown_left_by_an_old_zero_quote(tmp_path):
    # 32172: the bazaar lists $0.06, an old zero quote had replaced it, and the zero rule then made it unknown.
    store = Store(str(tmp_path / 'relist.sqlite3'))
    row = {'key': 'x402:https://pay.example/r', 'source': 'x402-bazaar', 'kind': 'x402',
           'url': 'https://pay.example/r', 'name': 'Relist', 'description': 'Relisted', 'category': 'data_utility',
           'networks': ['base'], 'price_usdc': 60000, 'details': {'accepts': [{'amount': '60000'}]}}
    rid = store.upsert_resource(row, now=10)
    store.record_observed_quote(rid, None)
    store.upsert_resource(row, now=20)
    assert store.resource(rid)['price_usdc'] == 60000
