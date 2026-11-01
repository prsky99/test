"""Public search task fidelity, safe suggestions and non-overlapping payload pages."""
import json
from agent_market.concierge.explore_search import identity, suggestions, task_advertised, page
from tests.test_fast_single_recommendation import catalog  # noqa: F401


def test_assistance_is_explicit_bounded_and_does_not_invent_protocols():
    assert suggestions('wether') == ['weather']
    assert suggestions('gihtub') == ['github']
    assert suggestions('clima') == ['weather']
    assert suggestions('MCP wether') == ['MCP weather']
    assert suggestions('x402 wether') == ['x402 weather']
    assert not suggestions('"Wether"')
    assert not suggestions('<img src=x onerror=alert(1)>')
    assert not suggestions('a' * 501)


def test_translation_requires_one_advertised_task_not_marketplace_marketing():
    prose = {'id': 1, 'kind': 'a2a', 'name': 'Payments marketplace',
             'description': 'A marketplace with text generation, translation and payments.'}
    assert not task_advertised('translate', prose)
    assert not task_advertised('\ubc88\uc5ed', prose)
    tool = {'name': 'translate_text', 'description': 'Translate text between languages.',
            'inputSchema': {'type': 'object', 'properties': {'text': {'type': 'string'}}}}
    actual = {**prose, 'name': 'Translator', 'description': 'Text translation service.',
              'usage_tools': json.dumps([tool])}
    assert task_advertised('translate', actual)
    assert task_advertised('\ubc88\uc5ed', actual)
    assert task_advertised('Payments marketplace', prose)


def test_identity_compares_full_endpoints_not_host_or_names():
    assert identity({'kind': 'mcp', 'url': 'https://EXAMPLE.org:443/mcp'}) == identity({'kind': 'mcp', 'url': 'https://example.org/mcp'})
    assert identity({'kind': 'mcp', 'url': 'https://example.org/one'}) != identity({'kind': 'mcp', 'url': 'https://example.org/two'})


def test_pages_do_not_repeat_prior_payload_and_report_exhaustion():
    result = {'query': 'weather', 'items': [{'id': n} for n in range(91)], 'total': 120}
    first, second = page(result, 0, 45), page(result, 45, 45)
    assert not ({r['id'] for r in first['items']} & {r['id'] for r in second['items']})
    assert first['next_offset'] == 45 and second['next_offset'] == 90
    assert not page(result, 90, 45)['has_more']


def test_public_api_exposes_bound_offset_pages(catalog):
    _, _, client, add, _ = catalog
    for n in range(7):add('Forecast '+str(n))
    first = client.get('/api/explore', params={'q': 'weather', 'limit': 3}).json()
    second = client.get('/api/explore', params={'q': 'weather', 'limit': 3, 'offset': 3}).json()
    assert first['next_offset'] == 3 and len(second['items']) == 3
    assert not ({r['id'] for r in first['items']} & {r['id'] for r in second['items']})
    assert client.get('/api/explore', params={'offset': -1}).status_code == 422
    assert client.get('/api/explore', params={'offset': 300}).status_code == 422


def test_same_endpoint_aliases_do_not_occupy_two_search_cards(catalog):
    store, _, client, add, _ = catalog
    first=add('Forecast source')
    alias=add('Forecast alias')
    with store.tx() as db:
        db.execute('UPDATE resources SET url=? WHERE id=?',(store.resource(first)['url'],alias))
    result=client.get('/api/explore',params={'q':'weather'}).json()
    assert len(result['items'])==1
