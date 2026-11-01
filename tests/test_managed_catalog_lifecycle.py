"""Discovery never owns local availability, operator controls, or search history."""
import json
import time

import httpx
import pytest

from agent_market.gateway.crawler import Crawler, parse_x402_item
from agent_market.gateway.store import Store
from tests.test_gateway import x402_item
from tests.test_collector import PagedRegistries, mcp_item


def resource(url='https://managed.example/api'):
    return parse_x402_item(x402_item(url, 'web search', 1000, 5))


def test_missing_upstream_retains_health_schedule_and_search_outbox():
    store = Store()
    rid = store.upsert_resource(resource(), now=time.time() - 100)
    store.record_health(rid, 'healthy', 402, 10, None, next_check_at=time.time() - 1)
    before = store.resource(rid)
    assert store.deactivate_unseen('x402-bazaar', time.time()) == 0
    after = store.resource(rid)
    assert after['active'] == 1 and after['registry_missing_since']
    assert after['health_status'] == before['health_status']
    assert after['managed_at'] and after['next_check_at'] == before['next_check_at']
    assert rid in [r['id'] for r in store.due_for_check(time.time(), 10)]
    assert store.query('SELECT * FROM vec_outbox WHERE resource_id=?', (rid,))


@pytest.mark.parametrize('changed', [False, True])
def test_external_refresh_cannot_reverse_operator_disable(changed):
    store = Store()
    data = resource()
    rid = store.upsert_resource(data)
    with store.tx() as db:
        db.execute("UPDATE resources SET active=0,inactive_reason='operator' WHERE id=?", (rid,))
    store.mark_registry_unseen('x402-bazaar', time.time() + 1)
    if changed:
        data['description'] = 'Updated registry description'
    store.upsert_resource(data)
    after = store.resource(rid)
    assert after['active'] == 0 and after['inactive_reason'] == 'operator'
    assert after['registry_missing_since'] is None


def test_metadata_updates_do_not_clear_local_retirement():
    store = Store()
    data = resource()
    rid = store.upsert_resource(data)
    with store.tx() as db:
        db.execute("UPDATE resources SET health_status='retired',failing_since=10,consecutive_failures=50,next_check_at=900000 WHERE id=?", (rid,))
    data['description'] = 'New source description'
    store.upsert_resource(data)
    row = store.resource(rid)
    assert (row['health_status'], row['failing_since'], row['consecutive_failures'], row['next_check_at']) == ('retired', 10, 50, 900000)


def test_health_quote_does_not_forge_registry_reappearance():
    store = Store()
    rid = store.upsert_resource(resource(), now=time.time() - 100)
    store.mark_registry_unseen('x402-bazaar', time.time())
    before = store.resource(rid)
    store.record_health(rid, 'healthy', 402, 10, None, time.time() + 7200,
                        observed_price=2000)
    row = store.resource(rid)
    assert row['registry_missing_since'] == before['registry_missing_since']
    assert row['last_seen'] == before['last_seen']
    assert row['health_status'] == 'healthy' and row['price_usdc'] == 2000


@pytest.mark.parametrize('payload', [{'items': []}, {'items': [], 'pagination': {'total': 200}},
                                    {'items': {}, 'pagination': {'total': 0}},
                                    {'items': [], 'pagination': {'total': True}}])
def test_malformed_full_discovery_cannot_change_membership(payload):
    store = Store()
    rid = store.upsert_resource(resource(), now=time.time() - 100)
    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload))) as http:
        crawler = Crawler(store, http=http, page_delay=0)
        with pytest.raises(ValueError):
            crawler._pass('x402-bazaar', force_full=True)
    assert store.resource(rid)['registry_missing_since'] is None
    assert store.get_meta('crawl_last_full:x402-bazaar') is None


def test_full_page_budget_exhaustion_preserves_membership():
    store = Store()
    rid = store.upsert_resource(resource(), now=time.time() - 100)
    registry = PagedRegistries([x402_item(f'https://r{i}.example/api', 'web search', 1000, 5)
                               for i in range(300)], [])
    with httpx.Client(transport=registry) as http:
        report = Crawler(store, http=http, page_delay=0, max_pages=1)._pass('x402-bazaar', force_full=True)
    assert not report['ok'] and report['incomplete']
    assert store.resource(rid)['registry_missing_since'] is None
    assert store.get_meta('crawl_last_full:x402-bazaar') is None


def test_offset_incremental_rotation_discovers_changes_after_unchanged_prefix():
    store = Store()
    items = [x402_item(f'https://r{i}.example/api', 'web search', 1000, 5) for i in range(500)]
    registry = PagedRegistries(items, [])
    with httpx.Client(transport=registry) as http:
        crawler = Crawler(store, http=http, page_delay=0)
        crawler._pass('x402-bazaar', force_full=True)
        registry.x402[350] = x402_item('https://new-tail.example/api', 'web search', 1000, 5)
        assert crawler._pass('x402-bazaar')['pages'] == 2
        assert crawler._pass('x402-bazaar')['new'] == 1
    assert store.query("SELECT id FROM resources WHERE url='https://new-tail.example/api'")


def test_bounded_mcp_changes_resume_original_since_until_drained():
    store = Store()
    registry = PagedRegistries([], [mcp_item(i) for i in range(250)])
    store.set_meta('crawl_last_full:mcp-registry', time.time())
    with httpx.Client(transport=registry) as http:
        crawler = Crawler(store, http=http, page_delay=0, incremental_mcp_max_pages=1)
        first = crawler._pass('mcp-registry')
        second = crawler._pass('mcp-registry')
        third = crawler._pass('mcp-registry')
    assert first['pending'] and second['pending'] and not third.get('pending')
    assert len({p['updated_since'] for p in registry.mcp_params}) == 1
    assert store.query("SELECT COUNT(*) n FROM resources WHERE source='mcp-registry'")[0]['n'] == 250


@pytest.mark.parametrize("active",[0,1])
def test_withdrawn_erc8004_token_keeps_local_agent_and_removes_membership(active):
    from agent_market.collector.registries import Erc8004Crawler
    store = Store()
    data = resource()
    data.update(key='a2a:https://managed.example/api', source='erc8004', kind='a2a',
                details={'erc8004': [{'chain': 'base', 'agent_id': 1}]})
    rid = store.upsert_resource(data)
    with store.tx() as db:
        db.execute("INSERT INTO erc8004_tokens(chain,agent_id,uri,status,services) VALUES('base',1,'https://example.com/card','ok',?)",
                   (json.dumps([{'kind': 'a2a', 'endpoint': data['url']}]),))
    with store.tx() as db:db.execute('UPDATE resources SET active=? WHERE id=?',(active,rid))
    collector = object.__new__(Erc8004Crawler)
    collector.store = store
    stats = {'withdrawn': 0}
    collector._withdraw('base', 1, [], stats)
    row = store.resource(rid)
    assert row['active'] == active and row['registry_missing_since']
    assert json.loads(row['details'])['erc8004'] == []
