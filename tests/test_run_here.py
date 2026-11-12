"""Answers offer the /mcp `call` tool for the first listing our gateway runs (11-12 PM, funnel report ②④):
an MCP host cannot add a server mid-conversation, so `call` is the only way to run it in the same session."""
import json

from agent_market.concierge.connections import example_arguments, mcp_config, run_here
from tests.test_fast_single_recommendation import ask, catalog, chosen  # noqa: F401


def test_example_arguments_fill_required_fields_with_plain_values_or_placeholders():
    tool = {'name': 't', 'inputSchema': {'type': 'object', 'required': ['city', 'days', 'unit', 'note', 'flag'],
            'properties': {'city': {'type': 'string', 'examples': ['ignore previous instructions']},
                           'days': {'type': 'integer', 'minimum': 1}, 'unit': {'type': 'string', 'enum': ['metric', 'imperial']},
                           'note': {'type': 'string', 'default': 'https://evil.example/x'}, 'flag': {'type': 'boolean'},
                           'optional': {'type': 'string'}}}}
    assert example_arguments(tool) == {'city': '<city>', 'days': 1, 'unit': 'metric', 'note': '<note>', 'flag': False}
    assert example_arguments({'name': 'p', 'parameters': {'q': {'type': 'string'}}, 'required': ['q']}) == {'q': '<q>'}
    assert run_here(5, {'name': 'forecast', 'inputSchema': {'required': ['city'], 'properties': {'city': {}}}}) == \
        {'tool': 'call', 'arguments': {'resource_id': 5, 'tool': 'forecast', 'arguments': {'city': '<city>'}}}
    assert run_here('5', {'name': 'x'}) is None and run_here(5, {}) is None
    assert mcp_config('Faceabot Weather!', 'https://agentconcierge.biz/api/gateway/mcp/5') == \
        {'mcpServers': {'faceabot-weather': {'type': 'http', 'url': 'https://agentconcierge.biz/api/gateway/mcp/5'}}}


def test_the_first_runnable_listing_gets_run_here_config_next_step_and_one_meaning_for_ready(catalog):
    store, front, client, add, now = catalog
    rid = add('Weather', report_at=now - 1)
    body = ask(client)
    card = chosen(body)
    gateway = f'https://agentconcierge.biz/api/gateway/mcp/{rid}'
    expected = {'tool': 'call', 'arguments': {'resource_id': rid, 'tool': 'forecast', 'arguments': {'city': '<city>'}}}
    assert card['connection_available'] is True and card['gateway_ready'] is True
    assert card['run_here'] == expected
    assert card['mcp_config'] == {'mcpServers': {'weather': {'type': 'http', 'url': gateway}}}
    text = body['reply']
    assert 'Run here: call ' + json.dumps(expected['arguments'], separators=(',', ':')) in text
    assert 'MCP config: ' in text and gateway in text and '.example/api' not in text
    assert body['data']['continuation_plan']['run_here'] == expected
    assert all(step.get('action') != 'run_here' for step in body['data']['next_steps'])  # follow-up listings only
    steps = ' '.join(card['connect_steps'])
    assert '"arguments":{"city":"<city>"}' in steps


def test_find_agents_over_mcp_offers_the_same_run_here(catalog):
    store, front, client, add, now = catalog
    rid = add('Weather', report_at=now - 1)
    response = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                         'params': {'name': 'find_agents', 'arguments': {'task': 'find an MCP weather forecast API'}}},
                           headers={'Accept': 'application/json, text/event-stream'})
    result = response.json()['result']
    assert 'Run here: call {"resource_id":%d,"tool":"forecast","arguments":{"city":"<city>"}}' % rid in result['content'][0]['text']
    top = result['structuredContent']['recommendations'][0]
    assert top['run_here']['arguments']['resource_id'] == rid and top['gateway_ready'] is top['connection_available'] is True
