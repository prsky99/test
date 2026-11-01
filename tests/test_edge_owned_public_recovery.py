"""Regression for the two historical first-party MCP 403 failures at the Edge."""
import secrets
from types import SimpleNamespace

from tests.test_edge_gateway import edge, service_request, ORIGIN
from tests.test_fast_single_recommendation import catalog
from tests.test_owned_data_agents_activation import operating
from tests.test_owned_data_agents import engine
from agent_market.owned_data_agents.catalog import SPECS


def test_public_prepare_keeps_owned_computation_local_without_remote_claim(edge):
    with edge.store.tx() as db:
        db.execute("UPDATE resources SET source='agentconcierge-owned' WHERE id=?", (edge.rid,))
    before = edge.store.query('SELECT id FROM edge_gateway_runs')
    response = service_request(edge, 'public-prepare', {
        'resource_id': edge.rid, 'input': {'message': 'Weather?'}, 'origin': ORIGIN,
        'idempotency_key': 'owned-'+secrets.token_hex(8), 'testbench': True})
    assert response.status_code == 200, response.text
    assert response.json() == {'backend': 'origin'}
    assert edge.store.query('SELECT id FROM edge_gateway_runs') == before
    assert not edge.calls


def test_public_gateway_owned_tool_does_not_reenter_a_banned_worker_ip(operating, monkeypatch):
    front, client, core, calls, _ = operating
    # Keep this ban in the isolated SQLite fixture; never change shared Redis.
    monkeypatch.setattr(front.security, 'redis', SimpleNamespace(is_available=lambda: False))
    shared = '2a06:98c0:3600::103'
    front.security.ban_ip(shared, 'Isolated shared Worker IP regression', duration_seconds=900)
    assert front.security.is_blocked(shared)[0]
    def forbidden(*args, **kwargs):
        raise AssertionError('First-party execution must not fetch its own public MCP URL')
    monkeypatch.setattr(front.proxy, '_client', forbidden)
    identity = 'technology-news'
    rid = next(rid for rid, binding in front.proxy._owned_data_dispatch.bindings.items() if binding[0] == identity)
    response = client.post('/api/gateway/mcp/'+str(rid), json={
        'jsonrpc': '2.0', 'id': 'owned-public-regression', 'method': 'tools/call',
        'params': {'name': SPECS[identity]['tool'], 'arguments': SPECS[identity]['example']}},
        headers={'X-Forwarded-For': '203.0.113.70'})
    assert response.status_code == 200, response.text
    body = response.json()
    assert 'error' not in body, body
    assert body['result']['isError'] is False
    assert front.security.is_blocked(shared)[0]
    assert not any(request.url.host == 'agentconcierge.biz' for request in calls)
