"""New customer transports remain frontend-only and distinct from staff login."""
from pathlib import Path
import re
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from agent_market.gateway.dashboard import dashboard_router
from agent_market.workspace_platform import platform_for, public_router_for
from agent_market.workspace_service import BASE
from tests.test_workspace_execution_api import private_api


@pytest.fixture
def surfaces(private_api, monkeypatch):
    w = private_api
    for name in ('GOOGLE_OIDC_CLIENT_ID', 'GOOGLE_OIDC_CLIENT_SECRET', 'GOOGLE_OIDC_REDIRECT_URI',
                 'GITHUB_OAUTH_CLIENT_ID', 'GITHUB_OAUTH_CLIENT_SECRET', 'GITHUB_OAUTH_REDIRECT_URI'):
        monkeypatch.delenv(name, raising=False)
    from agent_market.concierge.proxy import McpProxy
    from agent_market.workflows import runtime_for
    proxy = McpProxy(w.store)
    runtime = runtime_for(w.store, proxy)
    front = SimpleNamespace(store=w.store, workflows=runtime, proxy=proxy)
    public = FastAPI()
    public.include_router(public_router_for(front, workspace_access_enabled=True))
    admin = FastAPI()
    admin.include_router(dashboard_router(w.store, w.store._path, 'synthetic-machine-token', None,
                                         front=front, ssl_manager=Mock(get_status=lambda: {})))
    with TestClient(public, base_url='https://agentconcierge.biz') as customer, \
         TestClient(admin, base_url='https://admin.test') as staff:
        yield w, front, customer, staff


def test_customer_identity_routes_exist_only_on_frontend(surfaces):
    _, _, customer, staff = surfaces
    options = customer.get('/api/customer-auth/options')
    assert options.status_code == 200 and options.json()['configured'] is False
    assert staff.get('/api/customer-auth/options').status_code == 404
    assert staff.get('/customer/sign-in').status_code == 404
    assert customer.get(BASE).status_code == 404
    assert customer.get(BASE + '/options').status_code == 404
    assert customer.post('/admin/api/auth/login', json={}).status_code == 404
    assert customer.get('/customer/sign-in', headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 200


def test_disabled_identity_never_accepts_staff_or_machine_credentials(surfaces):
    w, _, customer, _ = surfaces
    for headers in (w.headers['owner'], {'Authorization': 'Bearer synthetic-machine-token'}):
        response = customer.get('/api/customer-auth/session', headers=headers)
        assert response.status_code == 401
    for provider in ('google', 'github'):
        response = customer.post('/api/customer-auth/begin', json={'provider': provider})
        assert response.status_code in (400, 401, 409, 503)
        assert 'authorization_url' not in response.json()


def test_current_staff_can_manage_workspace_without_customer_sso(surfaces):
    w, _, _, staff = surfaces
    response = staff.get(BASE + '/' + w.ws['id'] + '/customers', headers=w.headers['owner'])
    assert response.status_code == 200 and response.json()['customers'] == []
    current = staff.get(BASE + '/' + w.ws['id'], headers=w.headers['owner'])
    assert current.status_code == 200 and current.json()['workspace']['can_manage']
    assert staff.get(BASE + '/' + w.ws['id'] + '/customers').status_code in (401, 403)


def test_graph_shares_components_and_app_executor_requires_purpose_guard(surfaces):
    _, front, _, _ = surfaces
    platform = platform_for(front)
    assert platform is platform_for(front)
    assert platform.execution.access is platform.access
    assert platform.app_execution.access.identity is platform.identity
    assert platform.app_execution.authority_guard == platform.releases.guard_ticket
    assert platform.execution.authority_guard == platform.products.guard_ticket


def test_dashboard_fixed_extension_scripts_keep_exact_nonce_and_no_oidc_login(surfaces):
    _, _, _, staff = surfaces
    response = staff.get('/admin/ui')
    assert response.status_code == 200
    nonce = re.search(r"script-src 'nonce-([^']+)'", response.headers['content-security-policy']).group(1)
    for asset in ('workspace-admin.js', 'workspace-identity-admin.js',
                  'workspace-release-admin.js', 'advancement-admin.js', 'workflow-quality-admin.js', 'workspace-product-admin.js',
                  'workspace-typed-evidence-admin.js', 'workspace-reliability-research-admin.js',
                  'workspace-research-controls-admin.js', 'workspace-protocol-conformance-admin.js'):
        assert response.text.count(f'<script nonce="{nonce}" src="/admin/assets/{asset}"></script>') == 1
        loaded = staff.get('/admin/assets/' + asset)
        assert loaded.status_code == 200 and 'no-store' in loaded.headers['cache-control']
    assert '/api/customer-auth/begin' not in response.text
    assert staff.get('/admin/assets/customer_identity.py').status_code == 404


def test_public_auth_copy_and_embedded_frontend_remain_english_and_synchronized(surfaces):
    _, _, customer, _ = surfaces
    page = customer.get('/customer/sign-in')
    assert page.status_code == 200
    assert 'Google' in page.text and 'GitHub' in page.text
    assert not re.search('[\uac00-\ud7a3]', page.text)
    assert 'nonce-' in page.headers['content-security-policy']
    assert 'no-store' in page.headers['cache-control']
    from agent_market.concierge.front import HTML
    assert HTML == Path('extracted_html.txt').read_text()
    assert 'href="/customer/sign-in"' not in HTML


def test_restore_revokes_customer_and_deployment_authorities_without_resending(surfaces):
    w, front, _, _ = surfaces
    from agent_market.workflow_backup import quarantine
    platform = platform_for(front)
    with w.store.tx() as db:
        db.execute("INSERT INTO customer_identities VALUES('cu_fixture','https://github.com','opaque',1,1,1,1)")
        db.execute("INSERT INTO customer_sessions VALUES('session','cu_fixture','config',1,9999999999,NULL)")
        db.execute('INSERT INTO customer_workspace_links VALUES(?,?,?,1,1,1)',
                   (w.ws['id'], 'cu_fixture', 'runner'))
        db.execute("INSERT INTO workspace_app_codes VALUES('code','wap_fixture','{}','signed',NULL)")
        db.execute("INSERT INTO workspace_app_tokens VALUES('token','wap_fixture','app-run','{}','signed')")
        quarantine(db)
    assert w.store.query('SELECT revoked FROM customer_sessions')[0][0] is not None
    assert tuple(w.store.query('SELECT active,revision FROM customer_workspace_links')[0]) == (0, 2)
    assert w.store.query('SELECT COUNT(*) FROM workspace_app_codes')[0][0] == 0
    assert w.store.query('SELECT COUNT(*) FROM workspace_app_tokens')[0][0] == 0
    assert platform.execution.authority_guard == platform.products.guard_ticket
    assert not w.calls


def test_explicit_intervention_lifecycle_reuses_graph_and_never_inherits_pending_watches(surfaces):
    w, original, _, _ = surfaces
    from agent_market.workspace_integrations import PrivateIntegrations
    from agent_market.workspace_platform import start_for, close_for
    front = SimpleNamespace(store=w.store, workflows=original.workflows, proxy=original.proxy,
                            _workspace_integrations=PrivateIntegrations(early_stop_enabled=True))
    platform = platform_for(front)
    assert platform.early_stop.remote is platform.remote_tasks
    assert platform.evaluation_worker.circuit_automation is platform.circuit_automation
    assert not platform.trust_publication.enabled and platform.stripe_sandbox.client is None
    assert platform.early_stop.tick() == {'advanced': 0}
    assert start_for(front) and platform.early_stop._thread.is_alive()
    assert close_for(front) and not platform.early_stop._thread.is_alive()
    assert not w.calls
