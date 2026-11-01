"""MCP control preparation never receives tool output or executes a tool."""
import json

import httpx
import pytest

from tests.test_edge_gateway import edge, catalog
from tests.test_edge_gateway_catalog import enable, bridge, mcp_resource
from tests.test_mcp_proxy import WEATHER_TOOL


@pytest.mark.parametrize('failure', [None, 'schema', 'session', 'deadline'])
def test_control_only_metadata_and_cleanup_on_failed_handoff(edge, catalog, monkeypatch, failure):
    from agent_market.edge_gateway import mcp_control
    from agent_market.concierge.http_security import bounded_client
    enable(edge, monkeypatch); rid = mcp_resource(edge, catalog)
    with edge.store.tx() as db:
        db.execute('UPDATE resources SET usage_guide=? WHERE id=?', (json.dumps({'protocol_version': '2025-06-18'}), rid))
    methods = []

    def handle(request):
        assert not request.headers.get('cookie') and not request.headers.get('authorization')
        if request.method == 'DELETE':
            methods.append('DELETE'); return httpx.Response(204)
        wire = json.loads(request.content); methods.append(wire['method'])
        assert wire['method'] not in ('tools/call', 'server/discover')
        if wire['method'] == 'initialize':
            result = {'protocolVersion': '2025-06-18'}
        elif wire['method'] == 'notifications/initialized':
            return httpx.Response(202, headers={'Set-Cookie': 'provider=private'})
        else:
            assert wire['method'] == 'tools/list'
            result = {'tools': [] if failure == 'schema' else [WEATHER_TOOL]}
            if failure == 'deadline': edge.clock[0] += 9
        return httpx.Response(200, json={'jsonrpc': '2.0', 'id': wire['id'], 'result': result},
                              headers={'Mcp-Session-Id': 'invalid session' if failure == 'session' else 'private-session'})

    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        monkeypatch.setattr(mcp_control, 'bounded_client', lambda _http, **kw: bounded_client(http, **kw))
        response = bridge(edge, rid, {'tool': 'get_weather', 'arguments': {'city': 'Tokyo'}})
        if failure is None:
            binding = response.json()['binding']; capsule = binding['mcp_prepared']['cleanup']
            run = response.json()['run_id']; attempt = binding['attempt_id']
            before = list(methods)
            assert not mcp_control.close(edge.service, run, attempt, {**capsule, 'endpoint': 'https://attacker.example/'})
            assert not mcp_control.close(edge.service, run + '0', attempt, capsule)
            assert not mcp_control.close(edge.service, run, attempt, {**capsule, 'expires': 0})
            assert methods == before
            assert mcp_control.close(edge.service, run, attempt, capsule)
    assert response.status_code == (200 if failure is None else 409 if failure == 'schema' else 410 if failure == 'deadline' else 503)
    if failure is None:
        prepared = response.json()['binding']['mcp_prepared']
        assert prepared['protocol_version'] == '2025-06-18' and prepared['session_id'] == 'private-session'
        assert prepared['deadline_ms'] > edge.clock[0] * 1000
        assert methods == ['initialize', 'notifications/initialized', 'tools/list', 'DELETE']
    elif failure in ('schema', 'deadline'):
        assert methods[-1] == 'DELETE'
    assert not edge.calls
