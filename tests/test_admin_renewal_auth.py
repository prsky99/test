"""P1 individual identity and bootstrap rotation, isolated from operating data."""
# ruff: noqa: F811 -- shared isolated fixtures
import hashlib
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.gateway import admin_auth
from agent_market.gateway.dashboard import dashboard_router
from agent_market.gateway.store import Store
from agent_market.gateway.admin_policy import MACHINE_READS, VIEWER_READS

D = {'X-Dashboard': '1'}
PASSWORD = 'Personal-synthetic-password'


@pytest.fixture
def identity_app(tmp_path, monkeypatch):
    monkeypatch.delenv('ADMIN_BOOTSTRAP_PASSWORD', raising=False)
    monkeypatch.delenv('DEPLOYMENT_MODE', raising=False)
    monkeypatch.delenv('AGENTCON_ADMIN_DEV', raising=False)
    store = Store(str(tmp_path / 'identity.sqlite3'))
    app = FastAPI()
    app.include_router(dashboard_router(store, store._path, 'machine-fixture', None, ssl_manager=Mock(get_status=lambda: {})))
    with TestClient(app, base_url='https://admin.test') as client:
        yield store, client
    store._db.close()


def auth(client, password='sadmin', username='sadmin'):
    result = client.post('/admin/api/auth/login', headers=D, json={'username': username, 'password': password})
    assert result.status_code == 200, result.text
    return {**D, 'Authorization': 'Bearer ' + result.json()['token']}, result.json()


def rotate(client):
    headers, _ = auth(client)
    assert client.post('/admin/api/auth/change-password', headers=headers,
        json={'current_password': 'sadmin', 'new_password': PASSWORD}).status_code == 200
    return auth(client, PASSWORD)[0]


def test_bootstrap_can_only_change_password_and_all_sessions_end(identity_app):
    store, client = identity_app
    headers, result = auth(client)
    other, _ = auth(client)
    assert result['user']['password_change_required'] is True
    assert client.get('/admin/api/auth/me', headers=headers).json()['user']['password_change_required']
    for route in ('/admin/api/overview', '/admin/api/v2/home/bootstrap', '/admin/api/users'):
        assert client.get(route, headers=headers).status_code == 428
    with store.tx() as db:
        assert admin_auth.get_session_user(db, result['token']) is None
    assert client.post('/admin/api/auth/change-password', headers=headers,
        json={'current_password': 'wrong', 'new_password': PASSWORD}).status_code == 400
    assert client.post('/admin/api/auth/change-password', headers=headers,
        json={'current_password': 'sadmin', 'new_password': PASSWORD}).status_code == 200
    for old in (headers, other):
        assert client.get('/admin/api/auth/me', headers=old).status_code == 401
    new, result = auth(client, PASSWORD)
    assert not result['user']['password_change_required']
    assert client.get('/admin/api/v2/home/bootstrap', headers=new).status_code == 200
    assert client.post('/admin/api/auth/change-password', headers=new,
        json={'current_password': PASSWORD, 'new_password': PASSWORD}).status_code == 400


def test_unmarked_historical_default_session_is_blocked(identity_app):
    store, client = identity_app
    with store.tx() as db:
        digest = hashlib.pbkdf2_hmac('sha256', b'sadmin', b'legacy', 100000).hex()
        db.execute('UPDATE admin_users SET password_hash=?,salt=? WHERE id=1', (digest, 'legacy'))
        token = admin_auth.create_session(db, 1, 'sadmin', 'superadmin', 'Fixture')
    headers = {**D, 'Authorization': 'Bearer ' + token}
    assert client.get('/admin/api/v2/home/bootstrap', headers=headers).status_code == 428
    _, result = auth(client)
    assert result['user']['password_change_required']
    assert store.query('SELECT password_hash FROM admin_users WHERE id=1')[0][0].startswith('bootstrap$')


def test_machine_is_explicit_aggregate_get_only(identity_app):
    _, client = identity_app
    headers = {**D, 'Authorization': 'Bearer machine-fixture'}
    for path in MACHINE_READS:
        response = client.get(path, headers=headers)
        assert response.status_code == 200
    body = client.get('/admin/api/overview', headers=headers).json()
    assert not {'crawl', 'loops', 'actions', 'rag', 'ssl', 'collector', 'by_source'} & body.keys()
    for path in ('/admin/api/auth/me', '/admin/api/session', '/admin/api/users', '/admin/api/visitors',
                 '/admin/api/v2/home/bootstrap', '/admin/api/workspace-admin/options'):
        assert client.get(path, headers=headers).status_code in (401, 404)
    assert client.post('/admin/api/actions/pause', headers=headers, json={}).status_code == 401
    assert client.post('/admin/api/auth/change-password', headers=headers,
        json={'current_password': 'sadmin', 'new_password': PASSWORD}).status_code == 401


def test_viewer_projection_does_not_reuse_privileged_cached_body(identity_app):
    store, client = identity_app
    owner = rotate(client)
    assert client.get('/admin/api/v2/home/bootstrap', headers=owner).status_code == 200
    with store.tx() as db:
        user = admin_auth.create_admin_user(db, 'read-only', PASSWORD, 'Viewer', 'viewer')
    viewer, _ = auth(client, PASSWORD, 'read-only')
    for path in VIEWER_READS:
        response = client.get(path, headers=viewer)
        assert response.status_code == 200, (path, response.text)
    body = client.get('/admin/api/v2/home/bootstrap', headers=viewer).json()
    assert body['me']['role'] == 'viewer'
    assert body['gateway']['agents'] == []
    assert not {'crawl', 'actions', 'rag', 'ssl', 'collector'} & body['overview'].keys()
    for path in ('/admin/api/agents/1', '/admin/api/visitors', '/admin/api/users',
                 '/admin/api/v2/catalog/agents', '/admin/api/v2/gateway/controls'):
        assert client.get(path, headers=viewer).status_code == 403
    assert client.post('/admin/api/actions/pause', headers=viewer, json={}).status_code == 403
    with store.tx() as db:
        admin_auth.update_admin_user(db, user['id'], role='admin')
    assert client.get('/admin/api/auth/me', headers=viewer).status_code == 401


def test_no_local_automatic_access_without_explicit_development_flag(identity_app, monkeypatch):
    store, _ = identity_app
    app = FastAPI(); app.include_router(dashboard_router(store, store._path, None, None, ssl_manager=Mock()))
    with TestClient(app, base_url='http://localhost:8200', client=('127.0.0.1', 1234)) as client:
        assert client.get('/admin/api/session', headers=D).status_code == 401
        monkeypatch.setenv('AGENTCON_ADMIN_DEV', '1')
        assert '개발 모드 · 로컬 조회' in client.get('/admin/next').text
        assert '개발 모드 · 로컬 조회' in client.get('/admin/ui').text
        assert client.get('/admin/api/session', headers=D).status_code == 200
        assert client.post('/admin/api/actions/pause', headers=D, json={}).status_code == 401
        monkeypatch.setenv('DEPLOYMENT_MODE', 'production')
        assert '개발 모드 · 로컬 조회' not in client.get('/admin/next').text
        assert client.get('/admin/api/session', headers=D).status_code == 401


def test_final_superadmin_is_protected_but_bootstrap_can_be_disabled_after_handover(identity_app):
    from agent_market.workspace_admin_events import migrate
    from tests.test_admin_reviewed_commands import act
    store, client = identity_app
    migrate(store, getattr(store, '_workspace_admin_identity_key', b'isolated-handover-review-key-32b'))
    owner = rotate(client)
    assert client.put('/admin/api/users/1', headers=owner, json={'active': 0, 'reason': 'Synthetic disable owner'}).status_code == 400
    created = client.post('/admin/api/users', headers=owner,
        json={'username': 'replacement', 'password': PASSWORD, 'name': 'New owner', 'role': 'superadmin', 'reason': 'Synthetic owner handover'})
    assert created.status_code == 202
    assert act(client, owner, created.json()['item'], acknowledge=True).json()['item']['status'] == 'applied'
    replacement, _ = auth(client, PASSWORD, 'replacement')
    queued = client.put('/admin/api/users/1', headers=replacement, json={'active': 0, 'reason': 'Synthetic handover completed'})
    assert queued.status_code == 202
    assert act(client, owner, queued.json()['item']).json()['item']['status'] == 'applied'
    assert client.get('/admin/api/auth/me', headers=owner).status_code == 401


def test_viewer_browser_only_shows_aggregate_navigation(dash, browser):
    from playwright.sync_api import expect
    from tests.test_admin_next_browser import open_console
    store = dash[0].store
    with store.tx() as db:
        admin_auth.create_admin_user(db, 'read-only', PASSWORD, 'Viewer', 'viewer')
    context, page, errors, external = open_console(dash, browser)
    try:
        page.locator('#adm-user').fill('read-only'); page.locator('#adm-pass').fill(PASSWORD)
        page.get_by_role('button', name='로그인', exact=True).click()
        expect(page.get_by_role('heading', name='운영 요약', exact=True)).to_be_visible()
        expect(page.locator('#adm-nav>li>a')).to_have_count(4)
        expect(page.locator('#adm-search')).to_be_hidden()
        expect(page.locator('a[href^="/admin/ui"]')).to_have_count(0)
        page.screenshot(path='reports/admin-renewal-design-2026-10-21/auth/viewer.png', full_page=True)
        page.evaluate("location.hash='#/customers/customers'")
        expect(page.get_by_role('heading', name='접근 권한 확인', exact=True)).to_be_visible()
        expect(page.locator('#adm-main')).not_to_have_attribute('data-screen', 'U01')
        page.get_by_role('button', name='로그아웃', exact=True).click()
        expect(page.locator('#adm-login')).to_be_visible()
        assert not errors and not external
    finally:
        context.close()


from tests.test_dashboard import dash  # noqa: E402,F401
from tests.test_front_workflow_browser import browser  # noqa: E402,F401


def test_custom_bootstrap_secret_also_requires_rotation(tmp_path, monkeypatch):
    monkeypatch.setenv('ADMIN_BOOTSTRAP_PASSWORD', PASSWORD)
    store = Store(str(tmp_path / 'custom-bootstrap.sqlite3'))
    try:
        user = admin_auth.authenticate_user(store._db, 'sadmin', PASSWORD)
        assert user['password_change_required']
        assert user['password_hash'].startswith('bootstrap$')
    finally:
        store._db.close()
