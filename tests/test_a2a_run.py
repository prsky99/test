"""A2A "run N {arguments}" (PM 11-14 04:0x): the MCP `call` tool's scope, no wider.

Only item N of the list we recommended last in this conversation; only a relayed MCP tool, through the same
gateway path; never payments, x402, priced listings, credentials, action tools or tools that need the provider's
own authorization. The provider's answer comes back with its source and, on failure, a code.
"""
import json

import pytest

from agent_market.collector import usage
from agent_market.concierge import a2a_run
from tests.test_fast_single_recommendation import catalog  # noqa: F401 - fixture used by managed
from tests.test_managed_agent_gateway import managed  # noqa: F401 - fixture
from tests.test_mcp_proxy import DESTRUCTIVE_TOOL, WEATHER_TOOL


def send(client, text, ctx=None, method='message/send'):
    message = {'role': 'user', 'messageId': 'm-' + text[:8], 'parts': [{'kind': 'text', 'text': text}]}
    if ctx:
        message['contextId'] = ctx
    r = client.post('/a2a', json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': {'message': message}})
    assert r.status_code == 200, r.text
    result = r.json()['result']
    result = result.get('message', result)          # SendMessage (v1.0) wraps the message
    parts = result['parts']
    data = parts[1]['data']
    return result['contextId'], parts[0]['text'], data.get('data', data)


def item(rid, tool, kind='mcp', **extra):
    return {'id': rid, 'kind': kind, 'name': 'Listing %d' % rid, 'tools': [tool['name']], 'tools_schema': [tool], **extra}


def mcp_listing(store, add, name, tool, **fields):
    rid = add(name, **fields)
    store.record_usage(rid, tools=usage.compact_tools([tool]), digest=usage.tools_hash(usage.compact_tools([tool])),
                       guide={'tools': [tool]}, changes=None, trial={'ok': True})
    return rid


@pytest.fixture
def conversation(managed, monkeypatch):  # noqa: F811
    store, front, client, add, rid, calls, remote = managed
    ctx, _, _ = send(client, 'find a weather agent')
    listed = {'items': []}
    monkeypatch.setattr(front.book, 'last_results', lambda vid: (listed['items'], 0))
    return store, front, client, add, rid, calls, ctx, listed


def test_parse_reads_only_run_commands():
    assert a2a_run.parse('run 1 {"city": "Paris"}') == (1, {'city': 'Paris'})
    assert a2a_run.parse('Run #2') == (2, None)
    assert a2a_run.parse('run 1 [1,2]') == (1, 'invalid') and a2a_run.parse('run 1 {oops') == (1, 'invalid')
    assert a2a_run.parse('find a weather agent') is None and a2a_run.parse('rerun 1') is None


def test_a_recommended_tool_runs_through_the_gateway_with_its_source(conversation):
    store, front, client, add, rid, calls, ctx, listed = conversation
    listed['items'] = [item(rid, WEATHER_TOOL)]
    before = len(calls)
    _, text, data = send(client, 'run 1 {"city": "Paris"}', ctx)
    assert data['ok'] is True and data['source']['agent_id'] == rid and data['source']['tool'] == 'get_weather'
    assert data['source']['at'] and text.startswith('Ran get_weather on Listing %d (agent %d)' % (rid, rid))
    assert len(calls) > before                                  # the provider was really called, through the gateway
    _, _, again = send(client, 'run 1 {"city": "Paris"}', ctx, method='SendMessage')
    assert again['ok'] is True


def test_without_arguments_it_shows_the_command_to_send_and_runs_nothing(conversation):
    store, front, client, add, rid, calls, ctx, listed = conversation
    listed['items'] = [item(rid, WEATHER_TOOL)]
    before = len(calls)
    _, text, data = send(client, 'run 1', ctx)
    assert data['error_code'] == 'needs_arguments' and 'run 1 {"city":' in text and len(calls) == before


@pytest.mark.parametrize('text, code', [('run 2 {"city": "Paris"}', 'not_recommended'),
                                        ('run 1 {"city": "Paris", "api_key": "sk-123"}', 'credentials_not_accepted'),
                                        ('run 1 {"city": ', 'bad_arguments')])
def test_numbers_we_did_not_recommend_bad_arguments_and_credentials_are_refused(conversation, text, code):
    store, front, client, add, rid, calls, ctx, listed = conversation
    listed['items'] = [item(rid, WEATHER_TOOL)]
    before = len(calls)
    _, _, data = send(client, text, ctx)
    assert data['ok'] is False and data['error_code'] == code and len(calls) == before


def test_without_a_conversation_nothing_runs(managed):  # noqa: F811
    store, front, client, add, rid, calls, remote = managed
    _, _, data = send(client, 'run 1 {"city": "Paris"}')
    assert data['error_code'] == 'no_conversation'


def test_paid_x402_unrelayed_and_non_mcp_listings_are_refused_before_any_call(conversation):
    store, front, client, add, rid, calls, ctx, listed = conversation
    paid = mcp_listing(store, add, 'Paid Weather', WEATHER_TOOL, price=0.01)
    x402 = add('Pay Per Call', kind='x402', price=0.01)
    a2a = add('Talking Agent', kind='a2a')
    before = len(calls)
    for entry, code in ((item(paid, WEATHER_TOOL), 'payment_not_supported'),
                        (item(x402, WEATHER_TOOL, kind='x402'), 'payment_not_supported'),
                        (item(rid, WEATHER_TOOL, tool_unlisted=True), 'not_relayed'),
                        (item(a2a, WEATHER_TOOL, kind='a2a'), 'not_runnable_kind')):
        listed['items'] = [entry]
        _, _, data = send(client, 'run 1 {"city": "Paris"}', ctx)
        assert data['ok'] is False and data['error_code'] == code, entry
    assert len(calls) == before


def test_action_tools_and_tools_needing_provider_authorization_are_refused_by_the_gateway(conversation):
    store, front, client, add, rid, calls, ctx, listed = conversation
    wiper = mcp_listing(store, add, 'Wiper', DESTRUCTIVE_TOOL)
    private = mcp_listing(store, add, 'Private Weather', WEATHER_TOOL, auth_observed=1)
    for entry, args in ((item(wiper, DESTRUCTIVE_TOOL), {}), (item(private, WEATHER_TOOL), {'city': 'Paris'})):
        listed['items'] = [entry]
        _, text, data = send(client, 'run 1 ' + json.dumps(args), ctx)
        assert data['ok'] is False and data['error_code'] and 'Failure code:' in text, entry
    assert not any(c.url.host.startswith(('wiper', 'private')) for c in calls)  # neither provider was contacted


def test_a2a_answers_show_the_run_command_instead_of_the_mcp_call_tool():
    from agent_market.concierge.engine import Reply
    reply = Reply('1. Weather [MCP]\nRun here: call {"resource_id":7,"tool":"get_weather","arguments":{"city":"<city>"}}\nGrade: A',
                  'results', {'recommendations': [{'id': 7}, {'id': 8}]})
    out = a2a_run.a2a_wording(reply)
    assert 'Run here: run 1 {"city":"<city>"}' in out.text and 'call {' not in out.text and out.intent == 'results'
    other = Reply('Run here: call {"resource_id":99,"tool":"x","arguments":{}}', 'results', {'recommendations': [{'id': 7}]})
    assert a2a_run.a2a_wording(other).text == other.text   # not one of ours: left as it was
