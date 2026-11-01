"""Explicit public customer launch, first sign-in and secure failure handling."""
from urllib.parse import parse_qs, urlsplit
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from agent_market.config import GatewayConfig
from agent_market.concierge.front import create_front_app
from agent_market.customer_identity_service import COOKIE, FLOW_COOKIE, router_for
from agent_market.customer_identity_view import sign_in_page, workspaces_page
from scripts.agentcon_config import check_identity_settings, read_settings
from tests.test_customer_identity import customer, github_world, login
from tests.test_front_about import about_client


def test_enabled_frontend_exposes_workspace_navigation_home_metadata_and_customer_pages(about_client):
    with TestClient(create_front_app(about_client.app.state.front, workspace_access_enabled=True,
                                    workspace_link_enabled=True,
                                    manage_book_lifecycle=False), base_url='https://agentconcierge.biz') as client:
        page = client.get('/', headers={'Accept': 'text/html'})
        assert 'id="workspaceAccessLink" href="/customer/sign-in"' in page.text
        assert page.text.index('data-tab="about"') < page.text.index('id="workspaceAccessLink"')
        assert 'id="homeWorkspaceIntro"' in page.text
        assert 'Sign in with Google or GitHub to manage your workspaces.' in page.text
        assert '<!-- WORKSPACE_ACCESS_LINK -->' not in page.text
        assert client.get('/customer/sign-in').status_code == 200
        # Signed-out visitors are sent to sign-in, as for the organizations page.
        workflows = client.get('/customer/workflows', follow_redirects=False)
        assert workflows.status_code in (302, 303, 307) and workflows.headers['location'].startswith('/customer/sign-in')
        from agent_market.customer_identity_view import workflows_page
        signed_in = workflows_page()
        assert signed_in.headers['cache-control'] == 'no-store'
        assert 'id="workflow-workspaces"' in signed_in.body.decode()
        assert 'data-workspace-section="flows" aria-current="page"' in signed_in.body.decode()
        options = client.get('/api/customer-auth/options')
        assert options.status_code == 200
        assert client.get('/api/customer-auth/session').status_code == 401
        assert client.get('/admin/ui').status_code == 404
        assert client.post('/api/customer-auth/begin', json={'provider': 'github'},
                           headers={'Origin': 'https://unrelated.example'}).status_code == 403
        assert client.get('/customer/sign-in').headers['cache-control'] == 'no-store'


def test_direct_customer_testing_does_not_advertise_public_workspace_link(about_client):
    with TestClient(create_front_app(about_client.app.state.front, workspace_access_enabled=True,
                                    workspace_link_enabled=False, manage_book_lifecycle=False),
                    base_url='https://agentconcierge.biz') as client:
        page=client.get('/',headers={'Accept':'text/html'}).text
        assert 'id="workspaceAccessLink"' not in page and 'id="homeWorkspaceIntro"' not in page
        assert 'Workspace: Google or GitHub sign-in' not in page
        assert client.get('/customer/sign-in').status_code==200
        assert client.get('/api/customer-auth/options').status_code==200


def test_workspace_startup_setting_is_explicit_and_private_file_supported(monkeypatch, tmp_path):
    monkeypatch.delenv('CUSTOMER_WORKSPACE_ACCESS_ENABLED', raising=False)
    monkeypatch.delenv('CUSTOMER_WORKSPACE_LINK_ENABLED', raising=False)
    assert not GatewayConfig.from_env().customer_workspace_access
    assert not GatewayConfig.from_env().customer_workspace_link
    monkeypatch.setenv('CUSTOMER_WORKSPACE_ACCESS_ENABLED', '1')
    assert GatewayConfig.from_env().customer_workspace_access
    assert not GatewayConfig.from_env().customer_workspace_link
    monkeypatch.setenv('CUSTOMER_WORKSPACE_LINK_ENABLED','1')
    assert GatewayConfig.from_env().customer_workspace_link
    monkeypatch.setenv('CUSTOMER_WORKSPACE_LINK_ENABLED','true')
    with pytest.raises(ValueError):
        GatewayConfig.from_env()
    monkeypatch.setenv('CUSTOMER_WORKSPACE_LINK_ENABLED','0')
    monkeypatch.setenv('CUSTOMER_WORKSPACE_ACCESS_ENABLED', 'true')
    with pytest.raises(ValueError):
        GatewayConfig.from_env()
    path = tmp_path / 'launch.env'
    path.write_text('CUSTOMER_WORKSPACE_ACCESS_ENABLED=1\n')
    path.chmod(0o600)
    assert read_settings(path) == {'CUSTOMER_WORKSPACE_ACCESS_ENABLED': '1'}
    assert check_identity_settings(read_settings(path)) == {'google_configured': False, 'github_configured': False}


def test_customer_pages_use_nonce_csp_local_icons_and_no_identity_or_diagnostics():
    for response in (sign_in_page(), workspaces_page()):
        assert response.status_code == 200
        html = response.body.decode()
        assert 'lang="en"' in html and 'lucide' in html
        assert '<meta name="description"' in html and 'noindex,nofollow' in html
        assert not any(value in html for value in ('Customer ID:', 'session_ref', 'innerHTML', '/admin/', '/Users/'))
        # Only the public theme preference may use persistent browser storage.
        assert set(re.findall(r"localStorage\.[a-zA-Z]+\([^)]*\)", html)) <= {"localStorage.getItem('pearl-theme')", "localStorage.setItem('pearl-theme',value)"}
        policy = response.headers['content-security-policy']
        directives={parts[0]:parts[1:] for field in policy.split(';') if (parts:=field.split())}
        scripts=directives['script-src']
        assert len(scripts)==1 and re.fullmatch(r"'nonce-[A-Za-z0-9_-]+'",scripts[0])
        assert set(directives['style-src'])=={"'self'",scripts[0]}
        assert "frame-ancestors 'none'" in policy and "form-action 'self'" in policy
        assert "'unsafe-inline'" not in policy and "'unsafe-eval'" not in policy
        assert response.headers['cache-control'] == 'no-store'


def test_google_documented_issuer_alias_maps_to_the_same_account(customer):
    first = login(customer)
    customer.core.logout(first['session_token'])
    customer.state['claims']['iss'] = 'accounts.google.com'
    second = login(customer)
    assert first['customer_id'] == second['customer_id']
    assert customer.store._db.execute('SELECT COUNT(*) FROM customer_identities').fetchone()[0] == 1


@pytest.mark.parametrize('provider', ['google', 'github'])
def test_first_verified_login_registers_once_then_logout_and_return_reuse_account(customer, provider):
    w = customer
    github_world(w)
    def complete():
        query = parse_qs(urlsplit(w.core.begin('b' * 64, provider)['authorization_url']).query)
        if provider == 'google':
            w.state['nonce'] = query['nonce'][0]
        return w.core.complete(query['state'][0], 'synthetic-code', 'b' * 64, provider)
    first = complete()
    w.core.logout(first['session_token'])
    second = complete()
    assert first['customer_id'] == second['customer_id']
    assert first['session_token'] != second['session_token']
    assert w.store._db.execute('SELECT COUNT(*) FROM customer_identities').fetchone()[0] == 1
    assert w.core.session(second['session_token'])['workspaces'] == []
    w.github_http.close()


@pytest.mark.parametrize('provider,issuer',[
    ('google','https://accounts.google.com'),('github','https://github.com/login/oauth'),
])
def test_provider_authorization_issuer_is_validated_before_exchange(customer,provider,issuer):
    w=customer;github_world(w)
    app=FastAPI();app.include_router(router_for(w.store,b'synthetic-customer-key-32bytes!!!',identity=w.core,admin=False))
    path='/api/customer-auth/'+('callback' if provider=='google' else 'github/callback')
    with TestClient(app,base_url='https://agentconcierge.biz') as client:
        query=parse_qs(urlsplit(client.post('/api/customer-auth/begin',json={'provider':provider}).json()['authorization_url']).query)
        if provider=='google':w.state['nonce']=query['nonce'][0]
        result=client.get(path,params={'state':query['state'][0],'code':'synthetic-code','iss':issuer})
        assert result.status_code==200 and result.json()['authenticated']
        assert client.get('/api/customer-auth/session').status_code==200
        assert w.store._db.execute('SELECT issuer FROM customer_identities').fetchone()[0]==('https://accounts.google.com' if provider=='google' else 'https://github.com')
    w.github_http.close()


@pytest.mark.parametrize('provider,issuer',[
    ('github','https://accounts.google.com'),('google','https://github.com/login/oauth'),
    ('github','https://github.com'),('github','https://github.com/login/oauth/'),
    ('github','https://github.com.attacker.invalid/login/oauth'),
])
def test_wrong_or_cross_provider_callback_issuer_never_consumes_or_exchanges(customer,provider,issuer):
    w=customer;github_world(w)
    app=FastAPI();app.include_router(router_for(w.store,b'synthetic-customer-key-32bytes!!!',identity=w.core,admin=False))
    path='/api/customer-auth/'+('callback' if provider=='google' else 'github/callback')
    with TestClient(app,base_url='https://agentconcierge.biz') as client:
        query=parse_qs(urlsplit(client.post('/api/customer-auth/begin',json={'provider':provider}).json()['authorization_url']).query)
        result=client.get(path,params={'state':query['state'][0],'code':'synthetic-code','iss':issuer})
        assert result.status_code==400 and COOKIE not in client.cookies
        assert w.store._db.execute('SELECT COUNT(*) FROM customer_oidc_flows WHERE consumed IS NOT NULL').fetchone()[0]==0
        assert not w.state['calls']
    w.github_http.close()


@pytest.mark.parametrize('provider', ['google', 'github'])
def test_browser_cancel_and_invalid_callback_return_safe_retry_page(customer, provider):
    w = customer
    github_world(w)
    app = FastAPI()
    app.include_router(router_for(w.store, b'synthetic-customer-key-32bytes!!!', identity=w.core, admin=False))
    path = '/api/customer-auth/' + ('callback' if provider == 'google' else 'github/callback')
    with TestClient(app, base_url='https://agentconcierge.biz') as client:
        query = parse_qs(urlsplit(client.post('/api/customer-auth/begin', json={'provider': provider}).json()['authorization_url']).query)
        response = client.get(path, params={'state': query['state'][0], 'error': 'access_denied',
                              'error_description': 'private-untrusted-diagnostic'},
                              headers={'Accept': 'text/html'}, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers['location'] == '/customer/sign-in?result=cancelled'
        assert FLOW_COOKIE not in client.cookies and COOKIE not in client.cookies
        assert 'private-untrusted-diagnostic' not in response.text
        replay = client.get(path, params={'state': query['state'][0], 'code': 'synthetic-code'},
                            headers={'Accept': 'text/html'}, follow_redirects=False)
        assert replay.status_code == 303
        assert replay.headers['location'] == '/customer/sign-in?result=failed'
        assert COOKIE not in client.cookies and not w.state['calls']
    w.github_http.close()
