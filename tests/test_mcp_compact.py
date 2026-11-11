"""11-11 PM: smaller find_agents answers; only exact repeats are removed, every value stays once."""
import json

from agent_market.concierge.connections import gateway_mcp_steps
from agent_market.concierge.mcp_compact import compact_discovery

GW = 'https://agentconcierge.biz/api/gateway/%s/%d'


def mcp_card(rid, tool):
    url = GW % ('mcp', rid)
    return {'id': rid, 'kind': 'mcp', 'name': 'Weather %d' % rid, 'display_name': 'Weather %d' % rid, 'url': url,
            'usage_endpoint': url, 'connect_steps': gateway_mcp_steps(url, tool), 'revalidate_after_sec': 3600,
            'capability_contracts': [], 'tools': [tool],
            'tools_schema': [{'name': tool, 'inputSchema': {'type': 'object', 'properties': {'city': {'type': 'string'}}}}],
            'capability_contract': {'protocol': 'mcp', 'fingerprint': 'f' * 64}, 'reason': {'text': 'Chosen.'}}


def answer():
    a2a_url = GW % ('a2a', 9)
    a2a = {'id': 9, 'kind': 'a2a', 'name': 'Redeye', 'display_name': 'Redeye: stocks', 'url': a2a_url,
           'usage_endpoint': 'https://other.example/a2a', 'connect_steps': ['1) Fetch the agent card', '2) SendMessage'],
           'revalidate_after_sec': 600, 'capability_contracts': [{'id': 'c1', 'verified': True}]}
    schema = {'type': 'object', 'properties': {'symbol': {'type': 'string'}}}
    return {'intent': 'find', 'text': '1. Weather 1 [MCP]', 'revalidate_after_sec': 3600,
            'recommendations': [mcp_card(1, 'forecast'), mcp_card(2, 'alerts'), a2a],
            'next_steps': [{'resource_id': 3, 'revalidate_after_sec': 3600,
                            'tool': {'name': 'quote', 'inputSchema': schema, 'parameters': schema['properties']}},
                           {'resource_id': 4, 'revalidate_after_sec': 60,
                            'tool': {'name': 'old', 'inputSchema': schema, 'parameters': {'ticker': {}}}}]}


def test_exact_repeats_go_and_everything_else_stays():
    before = answer()
    after = compact_discovery(before)
    one, two, a2a = after['recommendations']
    for card in (one, two):
        assert 'display_name' not in card and 'usage_endpoint' not in card
        assert 'revalidate_after_sec' not in card and 'capability_contracts' not in card
        assert card['tools_schema'] and card['capability_contract']['fingerprint'] and card['reason']
    # Values that differ are kept: an A2A card with its own name, endpoint, revalidation and contracts.
    assert a2a == before['recommendations'][2]
    assert [c['id'] for c in after['recommendations']] == [1, 2, 9]
    assert after['text'] == before['text'] and after['revalidate_after_sec'] == 3600
    assert before['recommendations'][0]['display_name']  # the input is not changed
    assert len(json.dumps(after)) < len(json.dumps(before))


def test_mcp_cards_keep_their_call_line_and_example_and_the_shared_notes_appear_once():
    after = compact_discovery(answer())
    one = after['recommendations'][0]
    assert one['connect_steps'][0].startswith('POST ' + GW % ('mcp', 1))
    example = json.loads(one['connect_steps'][1].split(': ', 1)[1])
    assert example['params']['name'] == 'forecast'
    shared = gateway_mcp_steps('')
    assert after['connect_notes'] == [shared[1], shared[3]]
    assert all(note not in c['connect_steps'] for c in after['recommendations'] for note in after['connect_notes'])
    assert after['recommendations'][2]['connect_steps'] == ['1) Fetch the agent card', '2) SendMessage']


def test_next_steps_drop_only_a_parameters_map_equal_to_the_schema():
    first, second = compact_discovery(answer())['next_steps']
    assert 'parameters' not in first['tool'] and first['tool']['inputSchema']['properties'] == {'symbol': {'type': 'string'}}
    assert 'revalidate_after_sec' not in first
    assert second['tool']['parameters'] == {'ticker': {}} and second['revalidate_after_sec'] == 60


def test_answers_without_mcp_cards_get_no_notes_and_odd_values_pass_through():
    assert 'connect_notes' not in compact_discovery({'text': 'none', 'recommendations': []})
    assert compact_discovery({'text': 'x', 'recommendations': [None], 'next_steps': 'n'}) == \
        {'text': 'x', 'recommendations': [None], 'next_steps': 'n'}
    assert compact_discovery(None) is None
