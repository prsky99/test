"""PM 11-17 06:3x: a task that sends gets no tool that only checks or reads, in the recommendation and in user_slo.

user_slo "send email" passed three times (11-16 01:06, 06:01, 11-17 00:05) on a2a/87188's verify-email, a check of an
address. The recommendation (gateway_exposure, fast_chat) and the measurement (user_slo, slo_targets) share one rule.
"""
# ruff: noqa: F401,F811 -- reuse the isolated catalog fixture
import json
import types

import pytest

from agent_market.concierge.fast_chat import relayable, relayable_only
from agent_market.concierge.gateway_exposure import tool_direction_fits, wrong_direction
from agent_market.concierge.task_action import action_mismatch
from scripts import slo_targets, user_slo
from tests.test_fast_single_recommendation import catalog, ask
from tests.test_user_slo_connections import Client, Response


@pytest.mark.parametrize('task,tool,expected', [
    ('send email in real time 278', 'verify-email', True),      # the false pass
    ('send email', 'domain-intel', True),
    ('send an email to my team', 'getStatus', True),             # camelCase verbs count
    ('send sms', 'lookup_number', True),
    ('send email in real time', 'x711_email_send', False),       # the sending tool
    ('send sms', 'sendSms', False),
    ('send email', 'email', False),                              # a name that states no check
    ('verify an email address before I send it', 'verify-email', False),   # the task asks for the check
    ('email verification', 'verify-email', False),               # nothing sent
    ('forward geocode an address', 'lookup_address', False),     # 'forward' is no sending verb
    ('weather forecast', 'get_forecast', False),
    ('send email', '', False),
    (None, 'verify-email', False),
])
def test_action_mismatch(task, tool, expected):
    assert action_mismatch(task, tool) is expected


def test_gateway_exposure_treats_it_as_the_wrong_direction():
    item = {'id': 87188, 'kind': 'a2a', 'tools': ['verify-email']}
    assert wrong_direction('send email in real time', item)
    assert not wrong_direction('verify email addresses', item)
    assert not tool_direction_fits('send email', {'name': 'verify-email', 'description': 'send "verify-email <email>"'})
    assert tool_direction_fits('send email', {'name': 'send_email', 'description': 'Send an email.'})


def test_chat_leaves_a_check_tool_out_of_a_sending_answer():
    check = {'id': 87188, 'kind': 'a2a', 'action_mismatch': True}
    sender = {'id': 43775, 'kind': 'mcp', 'tool_unlisted': True}       # the action tool the gateway does not relay
    other = {'id': 5, 'kind': 'mcp'}
    assert not relayable(check)
    assert relayable_only([check, other]) == [other]
    # Nothing relayed: the honest unrelayed answer names the sending tool, never the check tool.
    assert relayable_only([check, sender]) == [sender]
    assert relayable_only([check]) == []


def _skills_agent(add, now):
    # A relayed read-only check tool whose text says 'send' for its own call, as 87188's skill does.
    tools = {'tools': [{'name': 'verify_email', 'annotations': {'readOnlyHint': True},
                        'description': 'Live email verification: syntax + MX. Send "verify_email <email>" to check an address.',
                        'inputSchema': {'type': 'object', 'properties': {'email': {'type': 'string'}}}}]}
    return add('Email Skills Agent', kind='mcp', report_at=now - 10, category='communication',
               description='Email intelligence skills for agents: verify email addresses before you send email.',
               usage_guide=json.dumps(tools))


def test_find_agents_does_not_answer_send_email_with_a_verifier(catalog):
    _, _, client, add, now = catalog
    verifier = _skills_agent(add, now)
    ids = [item['id'] for item in ask(client, 'send email to my team')['data']['recommendations']]
    assert verifier not in ids
    ids = [item['id'] for item in ask(client, 'verify an email address')['data']['recommendations']]
    assert verifier in ids          # the same agent still answers its own task


@pytest.mark.parametrize('tool,error', [('verify-email', 'action_mismatch'), ('send_email', None)])
def test_user_slo_does_not_count_a_check_tool_as_a_sent_email(monkeypatch, tool, error):
    class Card(Client):
        def post(self, url, json=None, headers=None):
            self.calls.append(url)
            if json['method'] == 'tools/call':
                text = '1. Pick one [A2A]\nEndpoint: https://agentconcierge.biz/api/gateway/mcp/87188'
                return Response(url, {'result': {'content': [{'text': text}], 'structuredContent': {
                    'recommendations': [{'connection_available': True, 'tools': [tool]}]}}})
            return Response(url, {'result': {'tools': [{'name': tool}]}})
    monkeypatch.setattr(user_slo, 'httpx', types.SimpleNamespace(Client=Card, HTTPTransport=user_slo.httpx.HTTPTransport))
    monkeypatch.setattr(user_slo, 'TOOL_LISTED_FROM', 0)
    monkeypatch.setattr(user_slo, 'unseen', lambda n: ['send email in real time 278'][:n])
    _, connect = user_slo.check_recommend_and_connect(1)
    sample = connect['samples'][0]
    assert sample['error'] == error and sample['reason'] == error
    assert connect['ok'] is (error is None) and slo_targets.connect_ok(sample) is (error is None)


def test_unrelayed_card_says_so_first_and_gives_no_call_sequence():
    # The public answer to 'send a newsletter email' (11-17 07:52) gave 'Call: initialize → tools/list → tools/call'
    # for x711_email_send, a tool the gateway does not relay.
    from agent_market.concierge.fast_chat import FastConcierge
    from agent_market.concierge.gateway_exposure import unrelayed_note
    note = unrelayed_note('x711', 'https://x711.io')
    item = {'id': 43775, 'kind': 'mcp', 'name': 'x711', 'url': 'https://x711.io/mcp', 'tool_unlisted': True,
            'usage_endpoint': 'https://agentconcierge.biz/api/gateway/mcp/43775', 'connection_note': note, 'active_checked_at': 1763337554}
    lines = FastConcierge._brief(item).splitlines()
    assert lines[1] == 'Connection: ' + note
    assert lines[2] == 'Endpoint: https://agentconcierge.biz/api/gateway/mcp/43775'   # user_slo reads this line
    assert not any(line.startswith('Call: ') or line.startswith('Run here') for line in lines)
    relayed = FastConcierge._brief({**item, 'tool_unlisted': False, 'connection_note': None}, first=False)
    assert relayed.splitlines()[2] == 'Call: initialize → tools/list → tools/call'


def test_a_skill_that_states_a_price_per_call_is_paid():
    # Real task a13 (11-17 15:10): Agent Revenue Network 424591's JSON Schema skill.
    from agent_market.concierge.gateway_exposure import access_note, PAID_NOTE, order_key
    paid = {'id': 424591, 'kind': 'a2a', 'tools': ['Recursive JSON Schema Checking'], 'description': 'Agent utilities.',
            'tools_schema': [{'name': 'Recursive JSON Schema Checking', 'description':
                              'Validate JSON values against a JSON Schema subset. Execution costs 0.003 USDC per call through x402 on Base.'}]}
    free = {'id': 1, 'kind': 'mcp', 'tools': ['validate_json'], 'description': 'Validate JSON against a schema.',
            'tools_schema': [{'name': 'validate_json', 'description': 'Free. $0 per call. Validates JSON.'}]}
    assert access_note(paid) == PAID_NOTE and access_note(free) is None
    paid['access_note'] = access_note(paid)
    assert sorted([paid, free], key=order_key)[0] is free
