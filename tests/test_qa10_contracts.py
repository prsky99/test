"""QA10 reproducers: scoped relevance, follow-ups, truthful reports and public safety."""
# ruff: noqa: F811 -- shared disposable catalog fixture.
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from agent_market.concierge.selection import _weather_scope_matches
from agent_market.concierge.report_projection import public_report
from tests.test_fast_single_recommendation import catalog  # noqa: F401


def test_sixteen_concurrent_search_misses_share_one_retrieval():
    from agent_market.concierge.front import _ExploreResultCache
    cache = _ExploreResultCache()
    barrier = threading.Barrier(16)
    release = threading.Event()
    started = threading.Event()
    calls = []

    def retrieve():
        calls.append(1)
        started.set()
        assert release.wait(3)
        return {'items': [{'id': 7}]}

    def request_page():
        barrier.wait()
        return cache.load(('public', 'weather'), retrieve)

    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(request_page) for _ in range(16)]
        assert started.wait(3)
        release.set()
        values = [future.result(3) for future in futures]
    assert len(calls) == 1
    assert all(result['items'][0]['id'] == 7 for result, _ in values)
    assert sum(not reused for _, reused in values) == 1
    assert not cache.inflight


def test_failed_search_releases_its_flight_and_does_not_cache_a_false_success():
    from agent_market.concierge.front import _ExploreResultCache
    cache = _ExploreResultCache()
    with pytest.raises(ValueError):
        cache.load('query', lambda: (_ for _ in ()).throw(ValueError('synthetic retrieval failure')))
    assert cache.get('query') is None and not cache.inflight
    assert cache.load('query', lambda: {'items': []}) == ({'items': []}, False)


@pytest.mark.parametrize('task,description,expected', [
    ('weather', 'Aviation and space data: METAR/TAF, airports, space weather, aurora, asteroids, satellite passes.', False),
    ('space weather', 'Space weather, aurora and solar storms.', True),
    ('aviation weather', 'Aviation METAR and TAF reports.', True),
    ('weather', 'Global current weather and daily forecasts, plus optional aviation observations.', True),
    ('weather in Seoul', 'Current weather in any city. Global coverage.', True),
])
def test_terrestrial_and_specialist_weather_have_distinct_scope(task, description, expected):
    assert _weather_scope_matches(task.split(), description) is expected


def test_compound_follow_up_filters_before_selecting_an_ordinal(catalog):
    _, _, client, add, now = catalog
    add('Weather A', report_at=now, price=100)
    free = [add('Weather B', report_at=now-10), add('Weather C', report_at=now-20)]
    first = client.post('/chat', json={'message': 'MCP weather forecast'}).json()
    headers = {'X-Visitor-Token': first['visitor']['token']}
    result = client.post('/chat', headers=headers, json={'message': 'only free ones, and tell me about the second one'}).json()
    assert result['intent'] == 'details'
    assert result['data']['recommendations'][0]['id'] == free[1]
    again = client.post('/chat', headers=headers, json={'message': 'how do I connect to it?'}).json()
    assert again['data']['recommendations'][0]['id'] == free[1]


def test_details_cannot_revive_a_dead_listing_outside_the_current_top_three(catalog):
    store, _, client, add, now = catalog
    ids = [add('Weather '+str(n), report_at=now-n) for n in range(5)]
    first = client.post('/chat', json={'message': 'MCP weather forecast'}).json()
    second = first['data']['recommendations'][1]['id']
    with store.tx() as db:
        db.execute("UPDATE resources SET health_status='dead' WHERE id=?", (second,))
    result = client.post('/chat', headers={'X-Visitor-Token': first['visitor']['token']}, json={'message': 'the second one'}).json()
    assert second not in [item['id'] for item in result['data'].get('recommendations', [])]
    assert ids


def test_missing_resource_call_names_the_problem_and_does_not_forge_feedback(catalog):
    store, _, client, _, _ = catalog
    before = store.query('SELECT COUNT(*) FROM feedback')[0][0]
    body = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
        'params': {'name': 'call', 'arguments': {'resource_id': 2147483646, 'tool': 'forecast'}}}).json()['result']
    assert body['isError']
    assert any(reason in body['content'][0]['text'].lower() for reason in ('unavailable','not found'))
    assert 'refused or failed' not in body['content'][0]['text']
    assert store.query('SELECT COUNT(*) FROM feedback')[0][0] == before


def test_public_adapter_refuses_private_targets_even_when_private_runtime_is_enabled(catalog):
    _, front, client, _, _ = catalog
    front.proxy.allow_private = True
    front.proxy._http = Mock(side_effect=AssertionError('No private network access'))
    body = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
        'params': {'name': 'adapt_rest', 'arguments': {'spec_url': 'http://127.0.0.1/openapi.json'}}}).json()
    assert body['error']['code'] == -32602
    assert 'Private or internal addresses' in body['error']['message']


@pytest.mark.parametrize('tags,expected', [('['+'"weather","test"'+']', ['weather', 'test']),
    ('{"unexpected":"shape"}', []), ('legacy-tag', ['legacy-tag'])])
def test_historical_report_tags_have_one_array_contract(tags, expected):
    resource = {'id': 1, 'kind': 'mcp', 'url': 'https://provider.example/mcp'}
    row = {'resource_id': 1, 'kind': 'mcp', 'agent_url': resource['url'], 'tags': tags}
    frozen = dict(row)
    report = public_report(row, resource)
    assert report['tags'] == expected and row == frozen
    assert report['execution_measured'] is False


def test_machine_discovery_openapi_documents_its_public_entry_badge_and_schema(catalog):
    _, _, client, _, _ = catalog
    document = client.get('/api/agent/v1/openapi.json').json()
    paths = document['paths']
    for path in ('/api/agent/v1/entry', '/api/agent/v1/badge/{resource_id}.svg', '/api/agent/v1/openapi.json'):
        assert 'get' in paths[path]
    assert '/admin' not in json.dumps(document) and '/customer/' not in json.dumps(document)
    response = client.options('/api/explore', headers={'Origin': 'https://browser-agent.example',
        'Access-Control-Request-Method': 'GET', 'Access-Control-Request-Headers': 'If-None-Match'})
    assert response.status_code == 204 and response.headers['access-control-allow-origin'] == '*'
    response = client.get('/robots.txt', headers={'Origin': 'https://browser-agent.example'})
    assert response.headers['access-control-allow-origin'] == '*'
    assert 'etag' in response.headers['access-control-expose-headers'].lower()
