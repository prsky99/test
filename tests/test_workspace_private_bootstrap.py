"""Private composition never discovers targets or opens public Workspace."""
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from agent_market.workspace_access import WorkspaceConflict, WorkspaceInvalid
from agent_market.workspace_integrations import PrivateIntegrations
from agent_market.workspace_private_bootstrap import PrivateDeployment, configure_private, receiver_app, compose_private
from agent_market.workspace_platform import close_for
from tests.test_workspace_execution_api import private_api  # noqa: F401
from tests.test_workspace_platform_integration import surfaces  # noqa: F401
from tests.test_workspace_machine_adapters import integrated  # noqa: F401
from tests.test_workspace_machine_updates import machine  # noqa: F401
from tests.test_provider_claims import provider  # noqa: F401


@pytest.mark.parametrize('value', [None, {}, {'integrations': {}}, 'enabled'])
def test_untyped_or_ambiguous_private_configuration_is_refused(value):
    with pytest.raises(WorkspaceInvalid):
        configure_private(SimpleNamespace(), value)


@pytest.mark.parametrize('origin', ['http://private.example', 'https://private.example/path',
    'https://user:secret@private.example', 'https://private.example?x=1'])
def test_private_origin_requires_exact_https_without_credentials_or_path(origin):
    with pytest.raises(WorkspaceInvalid):
        PrivateDeployment(PrivateIntegrations(), customer_origin=origin)


def test_trusted_config_installs_before_graph_and_reconfiguration_refused(surfaces):
    w, front, public, _ = surfaces
    other = SimpleNamespace(store=w.store, workflows=front.workflows)
    graph = configure_private(other, PrivateDeployment(PrivateIntegrations()))
    try:
        assert not graph.evaluation_worker.enabled and not graph.machine_receiver.enabled
        with pytest.raises(WorkspaceConflict):
            configure_private(other, PrivateDeployment(PrivateIntegrations()))
        from fastapi import FastAPI
        from agent_market.workspace_platform import public_router_for
        closed = FastAPI(); closed.include_router(public_router_for(other))
        with TestClient(closed, base_url='https://agentconcierge.biz') as client:
            assert client.get('/customer/sign-in').status_code == 404
        assert not w.calls
    finally:
        assert close_for(other)


def test_protected_receiver_factory_is_separate_exact_https_and_machine_only(integrated):
    w = integrated
    config = PrivateDeployment(PrivateIntegrations(receiver_enabled=True),
        receiver_origin='https://delivery.synthetic.invalid')
    app = receiver_app(SimpleNamespace(machine_receiver=w.durable_receiver), config)
    with TestClient(app, base_url='https://delivery.synthetic.invalid', raise_server_exceptions=False) as client:
        assert client.get('/customer/sign-in').status_code == 404
        assert client.get('/admin/api/workflow-workspaces').status_code == 404
        assert client.post('/private/machine-inbox/' + w.receiver_authority['id'], json={}).status_code in (401, 403, 415)
        assert client.post('/private/machine-inbox/' + w.receiver_authority['id'], json={}, headers={'Host': 'other.invalid'}).status_code == 404
    with TestClient(app, base_url='http://delivery.synthetic.invalid') as client:
        assert client.post('/private/machine-inbox/' + w.receiver_authority['id'], json={}).status_code == 404


def test_composed_private_apps_share_one_lifespan_and_do_not_create_authority(surfaces):
    w, front, _, _ = surfaces
    other = SimpleNamespace(store=w.store, workflows=front.workflows)
    config = PrivateDeployment(PrivateIntegrations(receiver_enabled=True),
        customer_origin='https://customer.synthetic.invalid', receiver_origin='https://inbox.synthetic.invalid')
    runtime = compose_private(other, config)
    with TestClient(runtime.customer, base_url=config.customer_origin) as customer:
        assert runtime._leases == 1
        assert customer.get('/customer/sign-in').status_code == 200
        with TestClient(runtime.receiver, base_url=config.receiver_origin) as receiver:
            assert runtime._leases == 2
            assert receiver.get('/customer/sign-in').status_code == 404
        assert runtime._leases == 1
    assert runtime._leases == 0 and not w.calls


def test_refused_private_callback_redacts_one_use_query_before_access_scope():
    from agent_market.workspace_private_bootstrap import _app
    app = _app('https://customer.synthetic.invalid')
    captured = []
    async def access_scope(scope, receive, send):
        async def record(message):
            if message['type'] == 'http.response.start':
                captured.append(scope.get('query_string', b''))
            await send(message)
        await app(scope, receive, record)
    with TestClient(access_scope, base_url='https://wrong.synthetic.invalid') as client:
        response = client.get('/api/customer-auth/callback?state=synthetic-one-use&code=synthetic-code')
        assert response.status_code == 404 and response.headers['cache-control'] == 'no-store'
    assert captured == [b'']


@pytest.mark.parametrize('raises', [False, True])
def test_partial_private_startup_closes_all_workers_and_refuses_reentry(surfaces, raises):
    w, front, _, _ = surfaces
    other = SimpleNamespace(store=w.store, workflows=front.workflows)
    config = PrivateDeployment(PrivateIntegrations(), customer_origin='https://customer.synthetic.invalid')
    runtime = compose_private(other, config)
    calls = []
    def worker(name, failing=False):
        def start():
            calls.append('start:' + name)
            if failing and raises:
                raise RuntimeError('synthetic startup failure')
            return not failing
        return SimpleNamespace(enabled=True, start=start, close=lambda: calls.append('close:' + name) or True)
    runtime.graph.evaluation_worker = worker('evaluation')
    runtime.graph.machine_update_automation = worker('machine', failing=True)
    runtime.graph.early_stop = worker('intervention')
    with pytest.raises(RuntimeError if raises else WorkspaceConflict):
        with TestClient(runtime.customer, base_url=config.customer_origin):
            pytest.fail('A failed startup cannot serve requests.')
    assert calls == ['start:evaluation', 'start:machine', 'close:intervention', 'close:machine', 'close:evaluation']
    assert runtime._leases == 0 and runtime._closed
    with pytest.raises(WorkspaceConflict):
        with TestClient(runtime.customer, base_url=config.customer_origin):
            pytest.fail('The closed runtime cannot restart workers.')
    assert len(calls) == 5 and not w.calls


def test_completed_private_runtime_cannot_reopen_and_shutdown_drains_after_error(surfaces):
    w, front, _, _ = surfaces
    other = SimpleNamespace(store=w.store, workflows=front.workflows)
    config = PrivateDeployment(PrivateIntegrations(), customer_origin='https://customer.synthetic.invalid')
    runtime = compose_private(other, config)
    calls = []
    def close_failure():
        calls.append('intervention')
        raise RuntimeError('synthetic shutdown failure')
    runtime.graph.early_stop = SimpleNamespace(enabled=False, close=close_failure)
    runtime.graph.machine_update_automation = SimpleNamespace(enabled=False, close=lambda: calls.append('machine') or True)
    runtime.graph.evaluation_worker = SimpleNamespace(enabled=False, close=lambda: calls.append('evaluation') or True)
    with pytest.raises(WorkspaceConflict):
        with TestClient(runtime.customer, base_url=config.customer_origin) as client:
            assert client.get('/customer/sign-in').status_code == 200
    assert calls == ['intervention', 'machine', 'evaluation']
    with pytest.raises(WorkspaceConflict):
        with TestClient(runtime.customer, base_url=config.customer_origin):
            pytest.fail('A terminated lifecycle cannot restart permanent workers.')
    assert len(calls) == 3 and not w.calls
