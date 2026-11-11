"""11-11 find_agents wording: MCP connect steps describe our stateless JSON gateway, with a real example."""
import json

from agent_market.concierge.connections import gateway_mcp_steps, public_agent

UPSTREAM = 'https://provider.example/mcp'
STORED = [f"POST {UPSTREAM} with headers 'Content-Type: application/json' and 'Accept: application/json, text/event-stream'.",
          "2) If the response has an 'Mcp-Session-Id' header, send it on every later request.",
          "4) tools/call with one of the example requests below. Responses may be JSON or Server-Sent Events.",
          "5) When done, DELETE the endpoint with the Mcp-Session-Id header to close the session."]


def test_public_mcp_card_gets_gateway_steps_without_session_or_missing_examples():
    item = {'id': 7, 'kind': 'mcp', 'url': UPSTREAM, 'usage_endpoint': UPSTREAM, 'connect_steps': STORED,
            'tools_schema': [{'name': 'get_weather', 'description': 'Weather'}], 'tools': ['get_weather']}
    card = public_agent(item, {'id': 7, 'kind': 'mcp', 'url': UPSTREAM})
    text = '\n'.join(card['connect_steps'])
    assert card['usage_endpoint'] in text and UPSTREAM not in text
    for stale in ('Mcp-Session-Id', 'DELETE', 'event-stream', 'below', 'Server-Sent'):
        assert stale not in text
    example = json.loads(card['connect_steps'][2].split(': ', 1)[1])
    assert example['method'] == 'tools/call' and example['params']['name'] == 'get_weather'


def test_steps_name_a_placeholder_when_no_tool_is_known():
    assert '<tool name from tools_schema>' in gateway_mcp_steps('https://agentconcierge.biz/api/gateway/mcp/1')[2]


def test_a2a_cards_keep_their_steps():
    steps = ['Read the Agent Card', 'message/send']
    card = public_agent({'id': 8, 'kind': 'a2a', 'url': 'https://a.example', 'connect_steps': steps}, {'id': 8, 'kind': 'a2a', 'url': 'https://a.example'})
    assert card['connect_steps'] == steps
