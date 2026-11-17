"""PM 11-17: subscribe and verify_contact are a closed legacy path. Task updates go through POST /api/task-updates,
which checks scope and authorization; the old path could not grant permission. Both tools stay listed (verify_contact)
or answerable (subscribe, hidden) and answer with the closed message; nothing is registered and no code is sent.
"""
# ruff: noqa: F401,F811 -- reuse the concierge world
from agent_market.concierge.mcp_contract import mcp_tools
from tests.test_concierge import w, chat

CLOSED = 'This legacy command is closed. Use POST /api/task-updates with an explicit task scope.'


def _call(c, name, args):
    body = {'jsonrpc': '2.0', 'id': 7, 'method': 'tools/call', 'params': {'name': name, 'arguments': args}}
    return c.post('/mcp', json=body).json()['result']


def test_subscribe_and_verify_contact_answer_closed_and_register_nothing(w):
    world, c, courier = w
    token = chat(c, 'hi')['visitor']['token']
    before = world.store.query('SELECT COUNT(*) AS n FROM agent_contacts')[0]['n']
    sub = _call(c, 'subscribe', {'contact_url': 'https://someone-else.example/inbox', 'contact_type': 'webhook', 'visitor_token': token})
    ver = _call(c, 'verify_contact', {'code': '123456', 'visitor_token': token})
    for result in (sub, ver):
        assert result['content'][0]['text'] == CLOSED
        assert result['structuredContent']['status'] == 'permission_required'
    assert world.store.query('SELECT COUNT(*) AS n FROM agent_contacts')[0]['n'] == before
    assert courier.sent == []                              # no verification code went to anyone's address


def test_the_tool_descriptions_say_it_is_closed():
    tools = {t['name']: t for t in mcp_tools()}
    assert tools['verify_contact']['description'].startswith('This legacy contact check is closed. Use POST /api/task-updates')
