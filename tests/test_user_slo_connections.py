"""11-11 PM: user_slo measures every sample on its own connection and records the edge state.

The hour's samples used to share one keep-alive httpx Client, so every sample after the first skipped DNS, TCP
and TLS. Now each explore, recommendation and page sample opens a new client (a connect check keeps one client
for its initialize + tools/list pair), and page and explore samples carry cf-cache-status and the airport.
"""
import json

import pytest

from scripts import user_slo


class Response:
    def __init__(self, url, body):
        self.status_code = 200
        self.headers = {'cf-cache-status': 'MISS', 'cf-ray': '8f00aa-LAX', 'mcp-session-id': 's1'}
        self.text = json.dumps(body)

    def json(self):
        return json.loads(self.text)


class Client:
    made = []

    def __init__(self, **kwargs):
        self.calls = []
        Client.made.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, **kwargs):
        self.calls.append(url)
        return Response(url, {'total': 3})

    def post(self, url, json=None, headers=None):
        self.calls.append(url)
        if json['method'] == 'tools/call':
            text = '1. Pick one [MCP]\nEndpoint: https://agentconcierge.biz/api/gateway/mcp/12'   # the real answer format
            return Response(url, {'result': {'content': [{'text': text}],
                                             'structuredContent': {'recommendations': [{'connection_available': True}]}}})
        return Response(url, {'result': {'tools': [{'name': 'x'}]}})


def test_every_sample_has_its_own_connection(monkeypatch, tmp_path):
    Client.made = []
    # Only user_slo's own reference: patching the shared httpx module also caught clients that background
    # threads of earlier tests opened meanwhile (11-12: 8 extra clients in a 51-file run).
    import types
    monkeypatch.setattr(user_slo, 'httpx', types.SimpleNamespace(Client=Client, HTTPTransport=user_slo.httpx.HTTPTransport))
    monkeypatch.setattr(user_slo, 'OUT', tmp_path / 'slo.jsonl')
    user_slo.main()
    record = json.loads((tmp_path / 'slo.jsonl').read_text())
    sizes = sorted(len(c.calls) for c in Client.made)
    # 6 explore + 2 recommend + 3 pages alone; 2 connect checks with initialize + tools/list each
    assert sizes == [1] * 11 + [2, 2]
    assert record['connection'] == 'new per sample'
    assert [c['connection_available'] for c in record['connect']['samples']] == [True, True]
    for kind in ('explore', 'pages'):
        assert all(s['cache'] == 'MISS' and s['colo'] == 'LAX' for s in record[kind]['samples'])


@pytest.mark.parametrize('listed_names,active,expect_ok', [(['x'], True, False), (['x', 'wanted'], True, True),
                                                           (['x'], False, True)])
def test_connect_needs_the_recommended_tool_on_the_gateway_list(monkeypatch, listed_names, active, expect_ok):
    """PM 11-12: 16:01 mcp/43775 connected (27 tools) while the recommended tool was not relayed."""
    import types

    class Card(Client):
        def post(self, url, json=None, headers=None):
            self.calls.append(url)
            if json['method'] == 'tools/call':
                text = '1. Pick one [MCP]\nEndpoint: https://agentconcierge.biz/api/gateway/mcp/43775'
                return Response(url, {'result': {'content': [{'text': text}], 'structuredContent': {
                    'recommendations': [{'connection_available': False, 'tools': ['wanted']}]}}})
            return Response(url, {'result': {'tools': [{'name': n} for n in listed_names]}})
    monkeypatch.setattr(user_slo, 'httpx', types.SimpleNamespace(Client=Card, HTTPTransport=user_slo.httpx.HTTPTransport))
    monkeypatch.setattr(user_slo, 'TOOL_LISTED_FROM', 0 if active else float('inf'))
    monkeypatch.setattr(user_slo, 'unseen', lambda n: ['weather in Seoul'][:n])
    _, connect = user_slo.check_recommend_and_connect(1)
    sample = connect['samples'][0]
    assert sample['recommended_tool'] == 'wanted' and sample['tool_listed'] is ('wanted' in listed_names)
    assert sample['tools'] == len(listed_names) and connect['ok'] is expect_ok
    assert (sample['error'] == 'tool_unlisted') is (not expect_ok)


@pytest.mark.parametrize('cards,expected', [([], 'no_recommendation'), ([{'connection_available': None}], 'no_gateway_endpoint')])
def test_a_no_match_answer_is_no_recommendation(monkeypatch, cards, expected):
    """PM 11-13 22:2x: 22:07 'customer support bulk 926' answered "No currently active, relevant agent found."
    and was recorded as a card without a gateway path. It still fails; the reason names what happened."""
    import types

    class NoMatch(Client):
        def post(self, url, json=None, headers=None):
            self.calls.append(url)
            text = 'No currently active, relevant agent found.' if not cards else '1. Pick one [MCP]\nDocs: https://example.org'
            return Response(url, {'result': {'content': [{'text': text}], 'structuredContent': {'recommendations': cards}}})
    monkeypatch.setattr(user_slo, 'httpx', types.SimpleNamespace(Client=NoMatch, HTTPTransport=user_slo.httpx.HTTPTransport))
    monkeypatch.setattr(user_slo, 'unseen', lambda n: ['customer support bulk'][:n])
    _, connect = user_slo.check_recommend_and_connect(1)
    sample = connect['samples'][0]
    assert sample['error'] == expected and sample['reason'] == expected and connect['ok'] is False


def test_a_failed_connect_step_keeps_its_cause_and_names_the_reason():
    """11-14 PM 03:1x: connection failures are counted by cause; the gateway's answer is kept, not thrown away."""
    from types import SimpleNamespace
    from scripts import user_slo as u
    auth = u.failure_detail('initialize', SimpleNamespace(status_code=400), {
        'type': 'https://agentconcierge.biz/errors/bad-request', 'status': 400, 'error_code': 'HTTP_400',
        'detail': 'This connection requires separate provider authorization.'})
    assert auth == {'stage': 'initialize', 'status': 400, 'error_code': 'HTTP_400', 'cause': None,
                    'detail': 'This connection requires separate provider authorization.'}
    assert u.failure_reason({'tools': 0, 'failure': auth}, None) == 'provider_auth_required'
    empty = u.failure_detail('tools/list', SimpleNamespace(status_code=200), {'jsonrpc': '2.0', 'id': 2, 'result': {'tools': []}})
    assert u.failure_reason({'tools': 0, 'failure': empty}, None) == 'no_relayed_tools'
    edge = u.failure_detail('initialize', SimpleNamespace(status_code=200), {'jsonrpc': '2.0', 'id': 1, 'error': {
        'code': -32000, 'message': 'The execution is unavailable.',
        'data': {'error_code': 'gateway_unavailable', 'cause': 'provider_timeout'}}})
    assert edge['cause'] == 'provider_timeout' and u.failure_reason({'tools': 0, 'failure': edge}, None) == 'gateway:provider_timeout'
    assert u.failure_reason({'tools': 0}, None) == 'connect_failed'
    assert u.failure_reason({'tools': 3, 'failure': edge}, None) is None
