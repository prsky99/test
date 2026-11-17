"""The MCP instructions lead with one call that works right now (PM 11-17 22:xx, growth item 1)."""
import json

from agent_market.concierge import try_now
from agent_market.concierge.front import NOTICE
from tests.test_fast_single_recommendation import catalog  # noqa: F401

H = {'Accept': 'application/json, text/event-stream'}


def test_the_line_names_one_ready_call():
    text = try_now.line()
    payload = text.split('with ', 1)[1].split('}', 1)[0] + '}'
    assert json.loads(payload) == {'task': try_now.TASK}
    assert '`find_agents`' in text and '`call`' in text and 'Run here' in text
    assert all(ord(ch) < 128 for ch in text)


def test_initialize_and_discover_carry_it_right_after_the_notice(catalog):  # noqa: F811
    _, _, client, _, _ = catalog
    for rid, method in ((1, 'initialize'), (2, 'server/discover')):
        params = {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '0'}}
        body = client.post('/mcp', json={'jsonrpc': '2.0', 'id': rid, 'method': method, 'params': params}, headers=H).json()
        text = body['result']['instructions']
        assert text.startswith(NOTICE + '\n\n' + try_now.line() + '\n\n'), method


def test_the_example_task_gets_a_run_here_line(catalog):  # noqa: F811
    _, _, client, _, _ = catalog
    found = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                                      'params': {'name': 'find_agents', 'arguments': {'task': try_now.TASK}}}, headers=H).json()
    assert 'result' in found and found['result']['content'][0]['text'].strip()
