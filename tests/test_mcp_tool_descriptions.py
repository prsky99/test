"""Tool descriptions say what each tool is for, and hints match behaviour (PM 11-14 04:1x, Glama TDQS).

search = browse a list, find_agents = recommend and connect, chat = conversation. Names never change.
"""
from agent_market.collector import usage
from agent_market.concierge.mcp_contract import mcp_tools
from tests.test_concierge import w  # noqa: F401 - fixture

NAMES = ['hello', 'chat', 'search', 'find_agents', 'check_agent', 'whats_new', 'verify_contact', 'call',
         'report', 'credit', 'adapt_rest', 'search_workflows', 'workflow_details', 'verify_agent', 'best_for_role',
         'run_workflow']


def by_name():
    return {t['name']: t for t in mcp_tools()}


def first_sentence(tool):
    return tool['description'].split(':', 1)[0] if ':' in tool['description'][:40] else tool['description'].split('.')[0]


def test_tool_names_are_unchanged():
    assert [t['name'] for t in mcp_tools()] == NAMES


def test_search_find_agents_and_chat_open_with_their_own_purpose():
    tools = by_name()
    assert tools['search']['description'].startswith('Browse:')
    assert tools['find_agents']['description'].startswith('Recommend and connect:')
    assert tools['chat']['description'].startswith('Converse:')
    leads = [first_sentence(t) for t in mcp_tools()]
    assert len(set(leads)) == len(leads)          # no two tools open with the same words


def test_hints_follow_what_the_tools_do():
    tools = by_name()
    for name in ('search', 'find_agents', 'check_agent', 'search_workflows', 'workflow_details'):
        hints = tools[name]['annotations']
        assert hints['readOnlyHint'] and not hints['destructiveHint'] and not hints['openWorldHint'], name
    call = tools['call']['annotations']
    assert not call['readOnlyHint'] and not call['destructiveHint'] and call['openWorldHint']
    rest = tools['adapt_rest']['annotations']
    assert rest['destructiveHint'] and rest['openWorldHint'] and not rest['readOnlyHint']
    assert not tools['chat']['annotations']['readOnlyHint']   # keeps the conversation


def test_call_is_not_destructive_because_the_gateway_relays_only_read_only_tools():
    assert not usage.is_relay_safe_tool({'name': 'delete_file', 'annotations': {'destructiveHint': True}})
    assert not usage.is_relay_safe_tool({'name': 'send_message', 'annotations': {'readOnlyHint': False}})
    assert 'Only tools classified read-only are relayed' in by_name()['call']['description']
    assert 'POST, PUT or DELETE' in by_name()['adapt_rest']['description']


def test_subscribe_is_not_listed_but_still_answers_and_is_counted(w, monkeypatch):  # noqa: F811
    """PM 11-14 04:5x: out of tools/list and /.well-known/mcp.json; the handler stays and each call is counted."""
    from agent_market.concierge import traffic
    recorder = traffic.Traffic(root=None)
    recorder.internal_ips = set()
    monkeypatch.setattr(traffic, 'recorder', lambda: recorder)
    _, client, _ = w
    listed = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}).json()['result']['tools']
    assert 'subscribe' not in [t['name'] for t in listed] and 'verify_contact' in [t['name'] for t in listed]
    assert 'subscribe' not in [t['name'] for t in client.get('/.well-known/mcp.json').json()['tools']]
    r = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {
        'name': 'subscribe', 'arguments': {'contact_url': 'https://example.org/hook'}}}).json()
    assert 'result' in r and 'Unknown tool' not in str(r)
    assert recorder.snapshot()['funnel']['hidden_tool|subscribe'] == 1
