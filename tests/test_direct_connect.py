"""Write tasks are judged on the direct-connect notice (PM 11-18, reports/write-action-measurement-2026-11-18):
(a) a fitting write tool, (b) an accurate notice, (c) the provider lists the tool, (d) nothing executed.
No outside call: the provider is a fake client, the ledger and the URL check are fakes."""
import contextlib

import pytest

from scripts import direct_connect as D
from scripts import user_slo

NOTE = "Our gateway does not run this tool. Connect through the provider's own documentation: https://x711.io"
CARD = {'connection_available': False, 'connection_reason': 'action_tool', 'connection_note': NOTE,
        'usage_endpoint': 'https://agentconcierge.biz/api/gateway/mcp/43775', 'direct_endpoint': 'https://x711.io/mcp'}


class Response:
    def __init__(self, body, status=200, session='s1'):
        import json
        self.text = json.dumps(body)
        self.status_code = status
        self.headers = {'mcp-session-id': session}


class Provider:
    """A fake MCP server: answers the three read methods; any other method is a test failure if it ever arrives."""

    def __init__(self, tools=('x711_email_send', 'x711_web_search'), status=200):
        self.tools, self.status, self.sent = tools, status, []

    def post(self, url, json=None, headers=None):
        self.sent.append(json['method'])
        assert json['method'] in D.READ_METHODS, 'a write tool was executed'
        if json['method'] == 'initialize':
            return Response({'jsonrpc': '2.0', 'id': 1, 'result': {}}, self.status)
        if json['method'] == 'tools/list':
            return Response({'jsonrpc': '2.0', 'id': 2, 'result': {'tools': [{'name': n} for n in self.tools]}})
        return Response({}, 202)


def ledger(ok=True):
    calls = []

    def reserve(url, system, n=1):
        calls.append((url, system, n))
        return (True, 'ok') if ok else (False, 'system_share')
    return reserve, calls


def judge(provider, reserve=None, card=CARD, wanted='x711_email_send', task='send email today 427'):
    reserve = reserve or ledger()[0]
    return D.judge(task, card, wanted, '', lambda: contextlib.nullcontext(provider), reserve, lambda url: None)


def test_write_topics_come_from_the_task_list():
    assert D.write_topic('send email today 427') == 'send email'
    assert D.write_topic('이메일 보내기 for my team 12') == '이메일 보내기'
    assert D.write_topic('stock quotes api 799') is None
    assert D.write_topic('sending email api 1') is None          # only the marked topics, not a word match
    assert set(D.WRITE_TOPICS) <= {t for t in user_slo.TOPICS}    # every write topic is a real user_slo topic


def test_all_four_hold_passes_and_only_reads_were_sent():
    provider = Provider()
    reserve, calls = ledger()
    out = judge(provider, reserve)
    assert out['passed'] and out['a_tool_fits'] and out['b_direct_notice'] and out['c_provider_lists_tool']
    assert out['d_nothing_executed'] and provider.sent == list(D.READ_METHODS) and out['resource_id'] == 43775
    assert calls == [('https://x711.io/mcp', 'fingerprints', 3)]    # one budgeted read of 3 calls


@pytest.mark.parametrize('wanted', ['x711_email_send', 'comms_send_message', 'send_email', 'iliad_transactional_email'])
def test_a_passes_for_send_tools(wanted):
    assert D.fits(wanted, D.WRITE_TOPICS['send email'])[0]


@pytest.mark.parametrize('wanted', ['verify_email', 'email_validate', 'get_inbox', None])
def test_a_fails_for_tools_that_do_not_send(wanted):
    out = judge(Provider(tools=(wanted or 'x',)), wanted=wanted)
    assert not out['a_tool_fits'] and not out['passed']


@pytest.mark.parametrize('card', [
    {**CARD, 'connection_available': True},                                  # says it runs through us
    {**CARD, 'connection_reason': 'not_verified_read_only'},                 # not the reason we stand behind
    {**CARD, 'connection_note': 'Unavailable.'},                             # no direct-connect notice
])
def test_b_fails_without_an_accurate_direct_notice(card):
    out = judge(Provider(), card=card)
    assert not out['b_direct_notice'] and not out['passed']


def test_b_accepts_the_terms_restricted_reason_for_11_19():
    assert D.guidance({**CARD, 'connection_reason': 'terms_restricted'})[0]


def test_b_fails_and_nothing_is_called_without_a_direct_endpoint_on_the_card():
    """PM 11-18: the address measured is the one the caller receives; a notice without it is incomplete."""
    provider = Provider()
    reserve, calls = ledger()
    card = {k: v for k, v in CARD.items() if k != 'direct_endpoint'}
    out = judge(provider, reserve, card=card)
    assert not out['b_direct_notice'] and 'no_direct_endpoint' in out['why'] and not out['passed']
    assert provider.sent == [] and calls == []


def test_c_fails_when_the_provider_does_not_list_the_tool():
    out = judge(Provider(tools=('x711_web_search',)))
    assert not out['c_provider_lists_tool'] and 'tool_not_listed_by_provider' in out['why'] and not out['passed']


def test_c_fails_without_any_call_when_the_ledger_refuses():
    provider = Provider()
    out = judge(provider, ledger(ok=False)[0])
    assert provider.sent == [] and not out['c_provider_lists_tool'] and 'ledger_system_share' in out['why']


def test_c_fails_when_the_provider_errors():
    out = judge(Provider(status=401))
    assert not out['c_provider_lists_tool'] and 'initialize_401' in out['why']


def test_d_a_write_call_can_never_be_sent():
    guarded = D.ReadOnlyClient(Provider())
    with pytest.raises(PermissionError):
        guarded.post('https://x711.io/mcp', json={'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                                                 'params': {'name': 'x711_email_send', 'arguments': {}}})
    out = D.verdict('send email', CARD, 'x711_email_send', ['x711_email_send'], ['initialize', 'tools/call'],
                    D.WRITE_TOPICS['send email'])
    assert not out['d_nothing_executed'] and not out['passed'] and 'executed:tools/call' in out['why']


def test_user_slo_counts_write_tasks_on_the_verdict_with_the_same_denominator():
    passed = {'write_task': True, 'tools': 0, 'error': 'tool_unlisted', 'direct': {'passed': True}}
    failed = {'write_task': True, 'tools': 27, 'error': None, 'direct': {'passed': False}}
    read_ok = {'tools': 3, 'error': None}
    read_bad = {'tools': 27, 'error': 'tool_unlisted'}
    conn = [passed, failed, read_ok, read_bad]
    assert user_slo.connect_bad(conn) == [failed, read_bad] and len(conn) == 4
