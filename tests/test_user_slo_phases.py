"""user_slo records where each sample's time went (11-11 PM); the verdict still uses the whole time."""
import importlib.util
from pathlib import Path

import httpx

spec = importlib.util.spec_from_file_location('user_slo', Path(__file__).resolve().parents[1] / 'scripts/user_slo.py')
user_slo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(user_slo)


def test_phases_come_from_trace_events_and_server_timing():
    p = user_slo._Phases()
    p.dns_s = 0.002
    for event, at in (('connection.connect_tcp.complete', 0.15), ('connection.start_tls.complete', 0.5),
                      ('http11.receive_response_headers.complete', 2.1), ('http11.receive_response_body.complete', 9.8)):
        p.at[event.split('.', 1)[-1]] = at
    p.trace('connection.connect_tcp.complete', None)          # a repeat keeps the first time
    response = httpx.Response(200, headers={'server-timing': 'explore;dur=985, server;dur=991.4, ann;dur=688'})
    assert p.summary(response) == {'dns_s': 0.002, 'tcp_s': 0.15, 'tls_s': 0.5, 'first_byte_s': 2.1, 'body_s': 9.8,
                                   'server_ms': 991, 'stages': {'explore': 985, 'ann': 688}}
    assert p.summary(httpx.Response(200))['server_ms'] is None
    assert p.summary(httpx.Response(200))['stages'] == {}


def test_only_the_eight_slowest_stages_are_kept():
    p = user_slo._Phases()
    p.dns_s = None
    timing = 'server;dur=900, ' + ', '.join(f's{i};dur={i * 10}' for i in range(1, 13))
    stages = p.summary(httpx.Response(200, headers={'server-timing': timing}))['stages']
    assert list(stages) == [f's{i}' for i in range(12, 4, -1)]


def test_the_traced_transport_hands_each_request_the_trace_hook(monkeypatch):
    seen = []

    def handle(self, request):
        seen.append(request.extensions.get('trace'))
        return httpx.Response(200, headers={'server-timing': 'server;dur=12'}, request=request)
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', handle)
    phases = user_slo._Phases()
    phases.dns_s = 0.001
    with user_slo.fresh(phases) as client:
        response = client.get('https://example.test/')
    assert seen == [phases.trace] and phases.summary(response)['server_ms'] == 12


def test_connect_follows_the_gateway_endpoint_of_the_first_recommendation_only():
    """11-12 PM (나-1): only gateway endpoints exist; a first recommendation without one is a failed connection."""
    first = ('1. x711 — Universal Agent Gas Station [MCP]\nEndpoint: https://agentconcierge.biz/api/gateway/mcp/43775\n'
             'Call: initialize → tools/list → tools/call\n2. Other [MCP]\nEndpoint: https://agentconcierge.biz/api/gateway/mcp/2\n')
    second_only = ('1. Palmyr [MCP]\nconnection_available: false\nDocs: https://palmyr.example/docs\n'
                   '2. Next [MCP]\nEndpoint: https://agentconcierge.biz/api/gateway/mcp/2\n')
    assert user_slo.connection_route(first) == 'https://agentconcierge.biz/api/gateway/mcp/43775'
    assert user_slo.connection_route(second_only) is None           # not the second recommendation's endpoint
    assert user_slo.connection_route('no recommendations') is None


def test_a_documentation_link_is_never_a_connection_path():
    """01982678's line for an action tool names documentation, not an address to connect to (검색과 RAG 11-12)."""
    answer = ('1. Palmyr email_send [MCP]\nConnection: This tool performs an action, so the Agent Concierge gateway does '
              'not relay it. Connect through the provider\'s own documentation: https://palmyr.example/docs\n')
    assert user_slo.connection_route(answer) is None


def test_the_first_card_connection_available_is_recorded_as_given():
    def body(cards):
        return {'result': {'structuredContent': {'recommendations': cards}}}
    assert user_slo.first_card_available(body([{'connection_available': False}, {'connection_available': True}])) is False
    assert user_slo.first_card_available(body([{'connection_available': True}])) is True
    assert user_slo.first_card_available(body([{}])) is None
    assert user_slo.first_card_available(body([])) is None
    assert user_slo.first_card_available({'result': {'content': []}}) is None
    assert user_slo.first_card_available(None) is None


def test_breaches_keep_the_exact_number_of_failed_samples():
    """11-12 PM: 'bad' holds at most three examples; bad_count and n are exact."""
    bad = [{'s': 2.5 + i} for i in range(5)]
    record = {'explore': {'ok': False, 'bad': bad, 'samples': bad + [{'s': 0.4}] * 5},
              'recommend': {'ok': True, 'bad': [], 'samples': [{}, {}]},
              'connect': {'ok': False, 'bad': [{'error': 'no_gateway_endpoint'}], 'samples': [{}, {}]},
              'pages': {'ok': True, 'bad': [], 'samples': [{}]}}
    out = user_slo.breaches(record)
    assert out['explore']['bad'] == bad[:3] and out['explore']['bad_count'] == 5 and out['explore']['n'] == 10
    assert out['connect']['bad_count'] == 1 and out['connect']['n'] == 2 and set(out) == {'explore', 'connect'}
