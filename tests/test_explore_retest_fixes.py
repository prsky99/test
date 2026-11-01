"""Explore retest (2026-10-27): ignored queries, short result reuse, suggestions and UI wording."""
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from agent_market.concierge.explore_search import searchable, suggestions

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('query,expected', [
    ('*', False), ('?', False), ('-', False), ('\\', False), ('\U0001f326️', False), ('the and of', False), ('a', False),
    ('weather', True), ('8004', True), ('天气', True), ('날씨', True), ('ai agent', True),
])
def test_only_symbols_or_stopwords_are_not_searched(query, expected):
    assert searchable(query) is expected


def test_common_typos_offer_the_intended_word():
    assert suggestions('translte') == ['translate']
    assert suggestions('gihtub') == ['github'] and suggestions('clima') == ['weather']


@pytest.fixture
def client(monkeypatch):
    from agent_market.gateway.store import Store
    from agent_market.concierge import front as front_module
    from agent_market.concierge.front import Front, create_front_app, clear_front_caches
    calls, listing = [], {}
    def fake_explore(store, engine, query, kind, category, verified, no_auth, limit):
        calls.append(query)
        return {'query': query, 'terms': [], 'total': 1, 'total_is_estimate': True,
                'items': [{'id': listing['id'], 'name': 'Agent'}], 'verified': False, 'captured_at': 0}
    monkeypatch.setattr('agent_market.concierge.hybrid_explore.explore', fake_explore)
    monkeypatch.setattr('agent_market.concierge.discovery.enabled', lambda engine: True)
    clear_front_caches()
    store = Store(':memory:')
    listing['id'] = store.upsert_resource({'key': 'agent', 'source': 'fixture', 'kind': 'mcp', 'url': 'https://agent.example/mcp',
                                           'name': 'Agent', 'description': 'Weather forecasts', 'category': 'travel_maps_weather'})
    with store.tx() as db:
        db.execute("UPDATE resources SET health_status='healthy' WHERE id=?", (listing['id'],))
    front = Front(store)
    monkeypatch.setattr(front.store, 'backend', 'postgresql', raising=False)
    with TestClient(create_front_app(front)) as value:
        value.listing_id = listing['id']
        yield value, calls
    clear_front_caches()
    assert front_module._explore_result_cache.values == {}


def test_general_query_explicitly_browses_catalog(client):
    c, calls = client
    body = c.get('/api/explore', params={'q': '*'}).json()
    assert body['query_ignored'] is True and body['query'] == '*' and body['suggestions'] == []
    assert calls == ['']
    assert body['items'] and body['total']==1 and body['status']=='browsing'
    assert 'broad' in body['search_notice']


def test_known_misspelling_searches_the_intended_word(client):
    c, calls = client
    body = c.get('/api/explore', params={'q': 'translte'}).json()
    assert calls == ['translate'] and body['items']
    assert body['query'] == 'translte' and body['corrected_query'] == 'translate' and body['suggestions'] == []
    assert body['search_notice'] == 'Showing results for "translate" instead of "translte".'
    # A correctly spelled query is searched as written, with no notice.
    body = c.get('/api/explore', params={'q': 'weather'}).json()
    assert calls[-1] == 'weather' and 'corrected_query' not in body and 'search_notice' not in body


def test_repeated_search_reuses_one_result_and_reports_server_timing(client):
    c, calls = client
    first = c.get('/api/explore', params={'q': 'weather'})
    again = c.get('/api/explore', params={'q': '  Weather '})
    assert first.status_code == again.status_code == 200 and [i['id'] for i in first.json()['items']] == [i['id'] for i in again.json()['items']]
    assert calls == ['weather'] and first.headers['server-timing'].startswith('explore;dur=')
    c.get('/api/explore', params={'q': 'weather', 'kind': 'mcp'})
    assert calls == ['weather', 'weather']  # a different filter is a different search
    with c.app.state.front.store.tx() as db:  # a cached page re-reads listings: removal applies at once
        db.execute("UPDATE resources SET eval_security='quarantine' WHERE id=?", (c.listing_id,))
    assert c.get('/api/explore', params={'q': 'weather'}).json()['items'] == [] and calls == ['weather', 'weather']


def test_public_chips_use_plain_task_words_and_one_count_style():
    html = (ROOT / 'extracted_html.txt').read_text()
    for internal in ('web search SERP', 'news headlines article', 'translate language text', 'image generation flux'):
        assert internal not in html
    assert '`${fmt(items.length)}+`' in html
    assert "['Web Search','Research','research papers']" in (ROOT / 'new/live-assets/pearl-ui.js').read_text()
    from agent_market.concierge.front import HTML
    assert HTML == html


@pytest.mark.parametrize('query,expected', [
    ('8004', True), ('ERC-8004', True), ('erc 8004 agents', True), ('ERC8004 registry', True),
    ('weather 8004', False), ('80045', False), ('x402', False),
])
def test_erc8004_queries_list_the_registry(query, expected):
    from agent_market.concierge.hybrid_explore import ERC8004_QUERY
    assert bool(ERC8004_QUERY.fullmatch(query)) is expected
