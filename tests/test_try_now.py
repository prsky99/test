"""The MCP instructions lead with one call that works right now (PM 11-17 22:xx; example changed PM 11-18)."""
import json

from agent_market.concierge import try_now
from agent_market.concierge.front import NOTICE
from agent_market.provider_budget import CLOSED_DOMAINS, TERMS_PATH
from tests.test_fast_single_recommendation import catalog  # noqa: F401

H = {'Accept': 'application/json, text/event-stream'}


def test_the_line_names_one_ready_call():
    text = try_now.line()
    payload = text.split('`call` with ', 1)[1].split(' for ', 1)[0]
    assert json.loads(payload) == try_now.CALL
    assert all(value and '<' not in str(value) for value in try_now.CALL['arguments'].values())
    assert '`find_agents`' in text and 'Run here' in text
    assert all(ord(ch) < 128 for ch in text)


def test_the_example_member_is_not_prohibited():
    """PM 11-18: the example must never lead to a member whose terms verdict is prohibits (fixed data, no network)."""
    members = json.loads(TERMS_PATH.read_text(encoding='utf-8'))['members']
    row = members.get(str(try_now.CALL['resource_id']))
    assert row and row.get('status') in ('allowed', 'silent'), row
    assert 'faceabot' not in json.dumps(row) and not any(domain in (row.get('source') or '') for domain in CLOSED_DOMAINS)


def test_initialize_and_discover_carry_it_right_after_the_notice(catalog):  # noqa: F811
    _, _, client, _, _ = catalog
    for rid, method in ((1, 'initialize'), (2, 'server/discover')):
        params = {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '0'}}
        body = client.post('/mcp', json={'jsonrpc': '2.0', 'id': rid, 'method': method, 'params': params}, headers=H).json()
        text = body['result']['instructions']
        assert text.startswith(NOTICE + '\n\n' + try_now.line() + '\n\n'), method
