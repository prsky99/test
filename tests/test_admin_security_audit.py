"""Adversarial probes use isolated admin databases and never contact production."""
import hashlib
import json
import time
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.gateway import admin_auth
from agent_market.gateway.dashboard import dashboard_router
from agent_market.gateway.store import Store

H = {"X-Dashboard": "1", "Authorization": "Bearer system-test-secret"}

@pytest.fixture
def admin(tmp_path, monkeypatch):
    path = str(tmp_path / "admin.sqlite3")
    store = Store(path)
    with store.tx() as db:
        assert admin_auth.change_user_password(db, 1, 'sadmin', 'Audit-fixture-password')
        raw = admin_auth.create_session(db, 1, "sadmin", "superadmin", "Fixture")
    monkeypatch.setitem(H, "Authorization", "Bearer " + raw)
    app = FastAPI()
    app.include_router(dashboard_router(store, path, "system-test-secret", None, ssl_manager=Mock()))
    from agent_market.workspace_admin_events import migrate
    migrate(store, getattr(store, '_workspace_admin_identity_key', b'isolated-admin-security-key-32b'))
    with TestClient(app, raise_server_exceptions=False) as client:
        yield store, client
    store._db.close()


def login(client, username="sadmin", password="Audit-fixture-password"):
    return client.post("/admin/api/auth/login", headers={"X-Dashboard": "1"}, json={"username": username, "password": password})


def session_headers(token):
    return {"X-Dashboard": "1", "Authorization": "Bearer " + token}


def test_legacy_session_migrates_on_file_database(admin):
    store, client = admin
    token = "a" * 64
    with store.tx() as db:
        db.execute("INSERT INTO admin_sessions VALUES(?,1,'sadmin','superadmin','Legacy',?,?,NULL,NULL)", (token, time.time(), time.time()+3600))
    res = client.get("/admin/api/auth/me", headers=session_headers(token))
    assert res.status_code == 200
    assert store.query("SELECT token FROM admin_sessions WHERE token=?", (admin_auth.session_reference(token),))[0][0] == admin_auth.session_reference(token)


def test_role_demotion_revokes_existing_sessions(admin):
    store, client = admin
    with store.tx() as db:
        user = admin_auth.create_admin_user(db, "other", "very-long-password-123", "Other", "superadmin")
    token = login(client, "other", "very-long-password-123").json()["token"]
    assert client.get("/admin/api/users", headers=session_headers(token)).status_code == 200
    from tests.test_admin_reviewed_commands import act
    queued = client.put(f'/admin/api/users/{user["id"]}', headers=H, json={"role":"operator", "reason": "Synthetic demotion request"})
    assert queued.status_code == 202
    done = act(client, session_headers(token), queued.json()['item'])
    assert done.json()['item']['status'] == 'applied' 
    assert client.get("/admin/api/users", headers=session_headers(token)).status_code in (401,403)


def test_password_reset_revokes_sessions(admin):
    _, client = admin
    token = login(client).json()["token"]
    from tests.test_admin_reviewed_commands import act
    queued = client.put("/admin/api/users/1", headers=H, json={"new_password":"replacement-password-123", "reason": "Synthetic password reset"})
    assert queued.status_code == 202
    assert act(client, H, queued.json()['item'], acknowledge=True).json()['item']['status'] == 'applied' 
    assert client.get("/admin/api/auth/me", headers=session_headers(token)).status_code == 401


@pytest.mark.parametrize("path,payload", [
    ("/admin/api/payments/deposit", {"account_id":"victim","amount":100}),
    ("/admin/api/security/under-attack", {"enabled":True}),
    ("/admin/api/credentials", {"key_name":"key","key_value":"secret"}),
    ("/admin/api/ssl/renew", {}),
])
def test_operator_cannot_modify_privileged_state(admin, path, payload):
    store, client = admin
    with store.tx() as db:
        admin_auth.create_admin_user(db, "viewer", "viewer-password-123", "Viewer", "operator")
    token = login(client,"viewer","viewer-password-123").json()["token"]
    assert client.post(path, headers=session_headers(token), json=payload).status_code == 403
    assert store.get_credit("victim")["balance"] == 0


@pytest.mark.parametrize("body", ['[]','null','{"username":[],"password":{}}','{"username":"sadmin","password":23}','{"username":"sadmin","password":"x","x":NaN}'])
def test_login_malformed_json_is_client_error(admin, body):
    _, client = admin
    assert client.post("/admin/api/auth/login", headers={"X-Dashboard":"1"}, content=body).status_code == 400


def test_request_body_limit_and_origin_boundary(admin):
    _, client = admin
    res = client.post("/admin/api/auth/login", headers={"X-Dashboard":"1"}, content=b'x' * (256*1024+1))
    assert res.status_code == 413
    res = client.post("/admin/api/auth/login", headers={"X-Dashboard":"1","Origin":"https://evil.example"}, json={"username":"sadmin","password":"sadmin"})
    assert res.status_code == 403


def test_login_throttling_and_failed_audit_commit(admin):
    store, client = admin
    codes = [login(client,password="incorrect").status_code for _ in range(12)]
    assert codes[0] == 401 and 429 in codes
    assert store.query("SELECT COUNT(*) FROM admin_audit_logs WHERE action='LOGIN_FAIL'")[0][0] > 0


@pytest.mark.parametrize("amount", [True, 1.5, "10", 2**63, -1])
def test_financial_amounts_must_be_positive_bounded_integers(admin, amount):
    store, client = admin
    res = client.post("/admin/api/payments/deposit", headers=H, json={"account_id":"target","amount":amount})
    assert res.status_code == 400
    assert store.get_credit("target")["balance"] == 0


def test_privilege_names_are_allowlisted(admin):
    _, client = admin
    assert client.post("/admin/api/users", headers=H, json={"username":"injected","password":"a-strong-password-123","role":"root"}).status_code == 400


def test_admin_page_uses_unique_script_nonces(admin):
    _, client = admin
    a, b = client.get("/admin/ui"), client.get("/admin/ui")
    policy = a.headers["content-security-policy"]
    assert "script-src 'nonce-" in policy
    assert "script-src-attr 'none'" in policy
    assert policy != b.headers["content-security-policy"]


def test_password_storage_upgrades_legacy_hashes(admin):
    store, client = admin
    legacy_hash = hashlib.pbkdf2_hmac("sha256", b"Audit-fixture-password", b"old-salt", 100_000).hex()
    with store.tx() as db:
        db.execute("UPDATE admin_users SET password_hash=?,salt='old-salt' WHERE id=1", (legacy_hash,))
    assert login(client).status_code == 200
    assert store.query("SELECT password_hash FROM admin_users WHERE id=1")[0][0].startswith("pbkdf2_sha256$600000$")


def test_every_management_route_requires_authentication(admin):
    _, client = admin
    checked = 0
    for path, operations in client.app.openapi()['paths'].items():
        if not path.startswith('/admin/api/') or path == '/admin/api/auth/login':
            continue
        import re
        target = re.sub(r'\{[^}]+\}', '1', path)
        for method in operations:
            if method.upper() not in ('GET','POST','PUT','PATCH','DELETE'):
                continue
            res = client.request(method.upper(), target, headers={'X-Dashboard':'1'}, json={} if method.upper() in ('POST','PUT','PATCH','DELETE') else None)
            assert res.status_code in (401,403), (method, target, res.status_code)
            checked += 1
    assert checked >= 80


def test_sql_injection_does_not_change_query_structure(admin):
    store, client = admin
    attack = "' OR 1=1; DROP TABLE admin_users; --"
    assert login(client, attack, 'wrong').status_code == 401
    for path in ('/admin/api/agents','/admin/api/needs','/admin/api/workflows','/admin/api/test-reports','/admin/api/explore'):
        response = client.get(path, params={'q':attack,'sort':attack,'category':attack}, headers=H)
        assert response.status_code in (200,400,422), (path,response.text[:100])
    assert store.query('SELECT COUNT(*) FROM admin_users')[0][0] == 1


@pytest.mark.parametrize('target', ['http://127.0.0.1:8200/admin/report','http://169.254.169.254/latest/meta-data','http://[::1]/'])
def test_admin_testbench_rejects_internal_urls(admin, target):
    store, client = admin
    rid = store.upsert_resource({'key':'private','source':'audit','kind':'mcp','url':target,'name':'Internal','description':'test','category':'ai_models','networks':[]})
    response = client.post('/admin/api/test/execute', headers=H, json={'resource_id':rid,'tool':'test'})
    assert response.status_code == 400


def test_rebinding_is_blocked_at_actual_socket_connection(monkeypatch):
    import asyncio
    import httpx
    import httpcore
    from agent_market.concierge import http_security
    monkeypatch.setattr(http_security, '_resolve_addresses', lambda *args: ['127.0.0.1'])
    async def forbidden(*args, **kwargs):
        pytest.fail('An internal socket must never be opened')
    monkeypatch.setattr(httpcore.AnyIOBackend, 'connect_tcp', forbidden)
    async def probe():
        async with http_security.public_async_client() as client:
            with pytest.raises(httpx.ConnectError, match='Blocked non-public'):
                await client.get('https://rebound.example/')
    asyncio.run(probe())


def test_card_endpoint_cannot_override_destination_validation(admin, monkeypatch):
    import agent_market.gateway.dashboard as dashboard
    from agent_market.broker.discovery import DiscoveryError
    store, client = admin
    rid = store.upsert_resource({'key':'card','source':'audit','kind':'a2a','url':'https://example.com/agent','name':'Card','description':'test','category':'ai_models','networks':[], 'details':{'endpoints':[{'binding':'JSONRPC','url':'http://127.0.0.1/admin/report'}]}})
    seen = []
    def validate(url):
        seen.append(url)
        if '127.0.0.1' in url:
            raise DiscoveryError('Blocked destination')
    monkeypatch.setattr(dashboard, 'check_public_url', validate)
    async def forbidden(*args, **kwargs):
        pytest.fail('Card endpoint must be validated before a request')
    monkeypatch.setattr(dashboard, 'bounded_request', forbidden)
    response = client.post('/admin/api/test/execute', headers=H, json={'resource_id':rid,'message':'hello'})
    assert response.status_code == 200 and response.json()['is_error']
    assert seen == ['https://example.com/agent','http://127.0.0.1/admin/report']


@pytest.mark.parametrize('value', [True, 0.5, -5, 2**63])
def test_money_storage_defends_internal_callers(admin, value):
    store, _ = admin
    for action in (lambda:store.deposit_credit('internal',value), lambda:store.hold_credit('internal',value,1,'x'), lambda:store.withdraw_credit('internal',value,'0x'+'1'*40)):
        with pytest.raises(ValueError):
            action()


def test_refund_replay_and_concurrent_withdrawal_preserve_balance(admin):
    from concurrent.futures import ThreadPoolExecutor
    store, _ = admin
    store.deposit_credit('race',100)
    hold = store.hold_credit('race',20,1,'test')
    store.refund_credit(hold)
    with pytest.raises(ValueError):
        store.refund_credit(hold)
    def withdraw(_):
        try:
            store.withdraw_credit('race',80,'0x'+'1'*40)
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(withdraw, range(8))) == 1
    assert store.get_credit('race')['balance'] == 20


def test_production_cannot_generate_self_signed_certificates(admin, monkeypatch, tmp_path):
    from agent_market.gateway.ssl_manager import SSLManager
    _, client = admin
    monkeypatch.setenv('DEPLOYMENT_MODE','production')
    assert client.post('/admin/api/ssl/renew', headers=H).status_code == 403
    with pytest.raises(ValueError, match='Production TLS'):
        SSLManager(str(tmp_path/'uncreated')).renew_certificate()
    assert not (tmp_path/'uncreated').exists()


def test_sqlite_files_have_private_permissions(admin):
    import os
    store, _ = admin
    path = store.query('PRAGMA database_list')[0]['file']
    assert os.stat(path).st_mode & 0o777 == 0o600
    for suffix in ('-wal','-shm'):
        if os.path.exists(path+suffix):
            assert os.stat(path+suffix).st_mode & 0o777 == 0o600


def test_outbound_tls_verification_and_proxy_isolation():
    import asyncio
    import ssl
    from agent_market.concierge.http_security import public_async_client
    async def probe():
        async with public_async_client() as client:
            assert client._trust_env is False
            assert client.follow_redirects is False
            assert client._transport._pool._ssl_context.verify_mode == ssl.CERT_REQUIRED
    asyncio.run(probe())


def test_self_password_change_revokes_sessions_and_commits_failed_audit(admin):
    store, client = admin
    a, b = login(client).json()['token'], login(client).json()['token']
    response = client.post('/admin/api/auth/change-password', headers=session_headers(a), json={'current_password':'bad','new_password':'replacement-password-123'})
    assert response.status_code == 400
    assert store.query("SELECT COUNT(*) FROM admin_audit_logs WHERE action='PASSWORD_CHANGE_FAIL'")[0][0] == 1
    response = client.post('/admin/api/auth/change-password', headers=session_headers(a), json={'current_password':'Audit-fixture-password','new_password':'replacement-password-123'})
    assert response.status_code == 200
    for token in (a,b):
        assert client.get('/admin/api/auth/me', headers=session_headers(token)).status_code == 401


def test_withdrawal_needs_a_valid_explicit_destination(admin):
    store, client = admin
    store.deposit_credit('target',100)
    for address in ('', '0x'+'0'*40, '0x'+'g'*40):
        response = client.post('/admin/api/payments/withdraw', headers=H, json={'account_id':'target','amount':20,'to_address':address})
        assert response.status_code == 400
        assert store.get_credit('target')['balance'] == 100


def test_async_admin_operation_has_a_total_deadline(admin, monkeypatch):
    import asyncio
    import agent_market.gateway.admin_security as security
    import agent_market.gateway.dashboard as dashboard
    store, client = admin
    rid = store.upsert_resource({'key':'slow','source':'audit','kind':'mcp','url':'https://example.com/agent','name':'Slow','description':'test','category':'ai_models','networks':[]})
    monkeypatch.setattr(security,'ASYNC_OPERATION_SECONDS',0.02)
    monkeypatch.setattr(dashboard,'check_public_url',lambda url:None)
    async def delayed(*args,**kwargs):
        await asyncio.sleep(60)
    monkeypatch.setattr(dashboard,'bounded_request',delayed)
    response = client.post('/admin/api/test/execute', headers=H, json={'resource_id':rid,'tool':'slow'})
    assert response.status_code == 504
