"""Private entry, return navigation and error boundaries with isolated identities."""
import json
import re
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.openapi.utils import get_openapi
from fastapi.testclient import TestClient

from agent_market.customer_identity_service import COOKIE, FLOW_COOKIE, customer_entry_guard, router_for
from agent_market.customer_navigation import DEFAULT, destination
from agent_market.workspace_service import WorkspaceRoute
from tests.test_customer_identity import customer, github_world, login  # noqa: F401
from tests.test_workspace_platform_integration import surfaces, private_api  # noqa: F401


@pytest.mark.parametrize('value', [None, 42, '//evil.test', '//[', 'https://evil.test/customer/plan',
    '/customer/sign-in', '/api/customer-auth/logout', '/customer/../admin', '/customer/%2e%2e/admin',
    '/customer/plan?workspace=x', '/customer/plan?workspace=ws_'+'a'*32+'&workspace=ws_'+'b'*32,
    '/customer/plan#javascript:alert(1)', '/customer/plan\r\nLocation:evil', '/customer/plan\\evil'])
def test_return_destination_fails_closed(value):
    assert destination(value) == DEFAULT


@pytest.mark.parametrize('provider', ['google', 'github'])
def test_oauth_return_is_bound_to_one_use_flow_and_not_callback_query(customer, provider):
    w = customer
    github_world(w)
    app = FastAPI(); app.include_router(router_for(w.store, b'synthetic-customer-key-32bytes!!!', identity=w.core))
    target = '/customer/organizations/ws_'+'a'*32+'/flows#templates'
    with TestClient(app, base_url='https://agentconcierge.biz') as client:
        assert client.get('/api/customer-auth/status').json()['authenticated'] is False
        prepared = client.post('/api/customer-auth/begin', json={'provider': provider, 'next': target})
        assert prepared.status_code == 200
        flow_cookie = prepared.headers['set-cookie'].lower()
        assert all(part in flow_cookie for part in ('__host-ac_oidc_flow', 'httponly', 'secure', 'samesite=lax', 'max-age=300'))
        query = parse_qs(urlsplit(prepared.json()['authorization_url']).query)
        if provider == 'google': w.state['nonce'] = query['nonce'][0]
        assert target not in prepared.json()['authorization_url']
        callback = '/api/customer-auth/'+('callback' if provider == 'google' else 'github/callback')
        params = {'state': query['state'][0], 'code': 'synthetic-code'}
        response = client.get(callback, params=params, headers={'Accept': 'text/html'}, follow_redirects=False)
        assert response.status_code == 303 and response.headers['location'] == target
        assert client.get('/api/customer-auth/status').json()['authenticated'] is True
        assert 'session_token' not in response.text and 'return_to' not in response.text
        assert COOKIE in client.cookies and FLOW_COOKIE not in client.cookies
        assert client.get(callback, params=params, headers={'Accept': 'text/html'}, follow_redirects=False).headers['location'] == '/customer/sign-in?result=failed'


def test_authentication_precedes_csrf_and_input_validation(customer):
    w = customer
    app = FastAPI()
    gate = APIRouter(dependencies=[Depends(customer_entry_guard(w.core))])
    gate.include_router(router_for(w.store, b'synthetic-customer-key-32bytes!!!', identity=w.core))
    @gate.post('/api/customer-support/validation')
    def invalid_query(request: Request, count: int):
        raise AssertionError('An unauthenticated endpoint must never execute.')
    app.include_router(gate)
    with TestClient(app, base_url='https://agentconcierge.biz') as client:
        for path in ('/api/customer-auth/logout', '/api/customer-organizations', '/api/customer-support/validation?count=bad'):
            response = client.post(path, content=b'{invalid')
            assert response.status_code == 401, (path, response.text)
            assert response.headers.get('www-authenticate') == 'Session realm="customer"'
        assert client.post('/api/customer-organizations', headers={'Origin': 'https://evil.test'}, json={}).status_code == 403
        auth = login(w); client.cookies.set(COOKIE, auth['session_token'], domain='agentconcierge.biz', path='/')
        assert client.post('/api/customer-auth/logout', json={}).status_code == 403


def test_cancel_preserves_only_the_reviewed_local_destination(customer):
    w = customer
    app = FastAPI(); app.include_router(router_for(w.store, b'synthetic-customer-key-32bytes!!!', identity=w.core))
    target = '/customer/plan?workspace=ws_'+'a'*32
    with TestClient(app, base_url='https://agentconcierge.biz') as client:
        start = client.post('/api/customer-auth/begin', json={'next': target}).json()
        state = parse_qs(urlsplit(start['authorization_url']).query)['state'][0]
        response = client.get('/api/customer-auth/callback', params={'state':state, 'error':'access_denied'},
                              headers={'Accept':'text/html'}, follow_redirects=False)
        assert response.status_code == 303
        assert parse_qs(urlsplit(response.headers['location']).query) == {'result':['cancelled'], 'next':[target]}
        assert COOKIE not in client.cookies and FLOW_COOKIE not in client.cookies


def test_composed_customer_surface_rejects_guests_before_validation(surfaces, tmp_path):
    w, front, client, _ = surfaces
    full = get_openapi(title='Isolated inventory', version='test', routes=client.app.routes)
    from agent_market.concierge.public_api_schema import install
    install(client.app)
    assert not any(path.startswith(('/api/customer-', '/customer/', '/api/workspace-apps-v2/')) for path in client.app.openapi()['paths'])
    before = w.store._db.total_changes
    checked = []
    exempt = {'/api/customer-auth/options', '/api/customer-auth/status', '/api/customer-auth/begin',
              '/api/customer-auth/callback', '/api/customer-auth/github/callback'}
    for template, operations in full['paths'].items():
        if not template.startswith('/api/customer-') or template in exempt or re.fullmatch(r'/api/customer-provider-oauth/(?:clients/\{rid\}\.json|\{rid\}/callback)', template):
            continue
        path = re.sub(r'\{[^}]+\}', 'missing', template)
        for method in ('get', 'post'):
            if method not in operations: continue
            response = client.request(method.upper(), path, content=b'{invalid' if method=='post' else None)
            assert response.status_code == 401, (method, template, response.status_code, response.text)
            assert response.headers['cache-control'] == 'no-store'
            checked.append({'method': method, 'path': template, 'status': response.status_code})
    assert checked
    assert w.store._db.total_changes == before
    pages = ('/customer/organizations?workspace=ws_'+'a'*32, '/customer/support', '/customer/plan',
             '/customer/workflows', '/customer/provider-connections', '/customer/organizations/ws_'+'a'*32+'/flows')
    for path in pages:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303, (path, response.status_code)
        target = parse_qs(urlsplit(response.headers['location']).query)['next'][0]
        assert target == path
        assert 'result=expired' not in response.headers['location']
    # No runtime data is retained outside the isolated fixture; report only the route inventory.
    report = __import__('pathlib').Path('reports/workspace-entry-repair-2026-10-27')
    report.mkdir(parents=True, exist_ok=True)
    (report/'anonymous-route-matrix.json').write_text(json.dumps(checked, indent=2))


def test_unhandled_private_error_has_safe_correlation_reference(caplog):
    app = FastAPI(); router = APIRouter(route_class=WorkspaceRoute)
    @router.get('/api/customer-support/synthetic-error')
    def fail():
        raise RuntimeError('SYNTHETIC_SECRET_MUST_NOT_APPEAR')
    app.include_router(router)
    with TestClient(app) as client:
        result = client.get('/api/customer-support/synthetic-error')
    assert result.status_code == 500 and result.headers['cache-control'] == 'no-store'
    reference = result.headers['x-request-id']
    assert re.fullmatch('[a-f0-9]{32}', reference) and reference in caplog.text
    assert 'RuntimeError' in caplog.text
    assert 'SYNTHETIC_SECRET_MUST_NOT_APPEAR' not in result.text+caplog.text
