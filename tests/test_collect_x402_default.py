"""PM 11-16 decision, applied 11-18: the x402 Bazaar list is collected again by default (COLLECT_X402 unset means on);
COLLECT_X402=0 still turns it off. No request is made here: the crawler is only built, never run."""
from agent_market.gateway import crawler as crawler_module
from agent_market.gateway.crawler import Crawler
from agent_market.gateway.store import Store


def test_x402_is_collected_by_default(monkeypatch):
    monkeypatch.delenv('COLLECT_X402', raising=False)
    assert crawler_module.collect_x402() is True
    assert Crawler(Store()).sources == ('x402-bazaar', 'mcp-registry', 'a2a-registry')


def test_x402_collection_can_still_be_turned_off(monkeypatch):
    monkeypatch.setenv('COLLECT_X402', '0')
    assert crawler_module.collect_x402() is False
    assert Crawler(Store()).sources == ('mcp-registry', 'a2a-registry')


def test_a_retired_x402_listing_stays_inactive_when_the_bazaar_lists_it_again():
    """market.datapackvibe.com (HTTP 530 since 11-05): 32,279 retired rows must not come back with the list."""
    store = Store()
    row = {'key': 'x402:https://market.datapackvibe.com/x', 'source': 'x402-bazaar', 'kind': 'x402',
           'url': 'https://market.datapackvibe.com/x', 'name': 'x', 'description': 'd', 'category': 'other',
           'networks': [], 'price_usdc': 1000, 'details': {}}
    store.upsert_resource(row)
    rid = store.query("SELECT id FROM resources WHERE key=?", (row['key'],))[0]['id']
    with store.tx() as db:
        db.execute("UPDATE resources SET health_status='retired', active=0 WHERE id=?", (rid,))
    store.upsert_resource({**row, 'description': 'listed again'})
    again = store.resource(rid)
    assert again['health_status'] == 'retired' and not again['active']
