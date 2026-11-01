"""Renewal-compatible aggregate reads require individual staff sessions."""
from types import SimpleNamespace

from tests.test_dashboard import dash
from tests.test_admin_next import login

PATH = '/admin/api/v2/gateway/edge-delivery'


def test_renewal_edge_summary_does_not_accept_machine_or_development_auth(dash):
    _, client = dash
    assert client.get(PATH, headers={'X-Dashboard': '1'}).status_code == 401
    assert client.get(PATH, headers={'X-Dashboard': '1', 'Authorization': 'Bearer secret'}).status_code == 401
    staff = login(client)
    reply = client.get(PATH, headers=staff)
    assert reply.status_code == 200 and reply.json()['available'] is False
    assert 'no-store' in reply.headers['cache-control']
    assert client.get(PATH, headers={'Authorization': staff['authorization']}).status_code == 403


def test_renewal_edge_summary_exposes_aggregate_policy_not_configuration(dash):
    world, client = dash
    world.store._edge_gateway_service = SimpleNamespace(summary=lambda: {
        'available': True, 'preferred_backend': 'origin', 'reason': 'daily_reserve',
        'worker_plan': 'free', 'daily_limit': 100000, 'automatic_paid_upgrade': False})
    reply = client.get(PATH, headers=login(client))
    assert reply.status_code == 200 and reply.json()['preferred_backend'] == 'origin'
    assert not {'endpoint', 'shared_secret', 'providers', 'input', 'output'} & set(reply.json())


def test_admin_process_initializes_its_own_delivery_state(dash, monkeypatch):
    from agent_market.edge_gateway.config import Config, Provider
    from agent_market.edge_gateway.state import migrate
    from agent_market.gateway.dashboard import dashboard_router
    world, _ = dash
    store = world.store
    migrate(store)
    config = Config(b'e' * 32, 'https://agentconcierge.biz',
                    (Provider(1, 'cv_' + 'a' * 32, 'https://provider.example/a2a'),), False)
    monkeypatch.setattr('agent_market.edge_gateway.bootstrap.load', lambda: config)
    # A separate admin process never installs the public Front router.
    front = SimpleNamespace(store=store)
    dashboard_router(store, ':memory:', 'secret', None, front=front)
    assert front.edge_gateway is store._edge_gateway_service
    assert front.edge_gateway.summary()['reason'] == 'worker_not_ready'
