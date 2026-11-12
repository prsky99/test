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
                                   'server_ms': 991}
    assert p.summary(httpx.Response(200))['server_ms'] is None


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


def test_connect_follows_the_answer_path_of_the_first_recommendation():
    """11-12 PM (via 검색과 RAG): a gateway endpoint goes through the gateway, a direct-connection line to the provider."""
    gateway = ('1. Paper Finder (mcp)\n   Endpoint: https://agentconcierge.biz/api/gateway/mcp/34807\n'
               '2. Other\n   Direct connection: https://other.example/mcp\n')
    direct = ('1. Palmyr (mcp)\n   connection_available: false\n   Direct connection: https://mcp.palmyr.example/mcp.\n'
              '2. Next\n   Endpoint: https://agentconcierge.biz/api/gateway/mcp/2\n')
    assert user_slo.connection_route(gateway) == ('gateway', 'https://agentconcierge.biz/api/gateway/mcp/34807')
    assert user_slo.connection_route(direct) == ('direct', 'https://mcp.palmyr.example/mcp')
    assert user_slo.connection_route('no connection lines') == (None, None)
    assert user_slo.connection_route('   Direct connection: http://plain.example/mcp') == (None, None)   # https only


def test_a_direct_connection_to_a_private_address_is_refused_before_any_request():
    import pytest
    with pytest.raises(Exception):
        user_slo.connector('direct', 'https://127.0.0.1/mcp')
