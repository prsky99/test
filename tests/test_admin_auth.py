"""Tests for Admin Management, Auth (sadmin/sadmin), MyPage Password Re-registration, and Sadmin-Only Audit Trail."""

import pytest
from fastapi.testclient import TestClient

from tests.test_gateway import populated


@pytest.fixture
def admin_world():
    world = populated()
    from agent_market.gateway.admin_auth import change_user_password
    with world.store.tx() as db:
        assert change_user_password(db, 1, 'sadmin', 'Auth-fixture-password')
        db.execute("UPDATE admin_users SET active=0 WHERE role='superadmin' AND username!='sadmin'")
    from agent_market.workspace_admin_events import migrate
    migrate(world.store, getattr(world.store, '_workspace_admin_identity_key', b'isolated-admin-review-key-32bytes'))
    return world, TestClient(world.app)


def test_dashboard_html_contains_auth_mypage_and_audit_components(admin_world):
    _, client = admin_world
    res = client.get("/admin/ui")
    assert res.status_code == 200
    html = res.text

    # Header components
    assert 'id="adminUserArea"' in html
    assert 'id="adminUsername"' in html
    assert 'id="myPageBtn"' in html
    assert 'id="logoutBtn"' in html

    # Tabs
    assert 'id="tabUsers"' in html
    assert 'id="tabAudit"' in html
    # Audit tab must be hidden by default until sadmin is verified
    assert 'id="tabAudit" style="display:none"' in html or 'data-tab="audit"' in html

    # Panels
    assert 'data-panel="users"' in html
    assert 'data-panel="audit"' in html

    # Modals
    assert 'id="adminLoginModal"' in html
    assert 'id="adminMyPageModal"' in html
    assert 'id="adminCreateUserModal"' in html
    assert 'id="adminAuditDetailModal"' in html

    # My Page password re-registration fields
    assert 'id="myPageCurrentPwd"' in html
    assert 'id="myPageNewPwd"' in html
    assert 'id="myPageConfirmPwd"' in html
    assert 'id="submitChangePwdBtn"' in html


def test_rotated_sadmin_login_and_logout(admin_world):
    _, client = admin_world

    # 0. Unauthenticated call to /admin/api/auth/me without token returns 401
    unauth = client.get("/admin/api/auth/me", headers={"X-Dashboard": "1"})
    assert unauth.status_code == 401
    assert "인증이 필요합니다" in unauth.json()["detail"] or "로그인이 필요합니다" in unauth.json()["detail"]

    # 1. Login with invalid password fails and returns 401
    bad_login = client.post(
        "/admin/api/auth/login",
        json={"username": "sadmin", "password": "wrongpassword"},
        headers={"X-Dashboard": "1"},
    )
    assert bad_login.status_code == 401
    assert "올바르지 않거나" in bad_login.json()["detail"]

    # 2. Login with sadmin / sadmin succeeds
    login_res = client.post(
        "/admin/api/auth/login",
        json={"username": "sadmin", "password": "Auth-fixture-password"},
        headers={"X-Dashboard": "1"},
    )
    assert login_res.status_code == 200
    data = login_res.json()
    assert data["ok"] is True
    assert "token" in data
    assert data["user"]["username"] == "sadmin"
    assert data["user"]["role"] == "superadmin"
    assert data["user"]["is_sadmin"] is True
    token = data["token"]

    # 3. GET /admin/api/auth/me returns current user info
    me_res = client.get(
        "/admin/api/auth/me",
        headers={"Authorization": f"Bearer {token}", "X-Dashboard": "1"},
    )
    assert me_res.status_code == 200
    me = me_res.json()
    assert me["ok"] is True
    assert me["user"]["username"] == "sadmin"
    assert me["is_sadmin"] is True

    # 4. Logout invalidates session
    logout_res = client.post(
        "/admin/api/auth/logout",
        headers={"Authorization": f"Bearer {token}", "X-Dashboard": "1"},
    )
    assert logout_res.status_code == 200
    assert logout_res.json()["ok"] is True

    # Calling auth/me after logout returns 401
    after_me = client.get(
        "/admin/api/auth/me",
        headers={"Authorization": f"Bearer {token}", "X-Dashboard": "1"},
    )
    assert after_me.status_code == 401


def test_mypage_password_change_flow(admin_world):
    _, client = admin_world

    # Login as sadmin
    login_res = client.post(
        "/admin/api/auth/login",
        json={"username": "sadmin", "password": "Auth-fixture-password"},
        headers={"X-Dashboard": "1"},
    )
    token = login_res.json()["token"]

    # 1. Change password with incorrect current password fails
    bad_change = client.post(
        "/admin/api/auth/change-password",
        json={"current_password": "wrong", "new_password": "newpassword123456789"},
        headers={"Authorization": f"Bearer {token}", "X-Dashboard": "1"},
    )
    assert bad_change.status_code == 400
    assert "일치하지 않습니다" in bad_change.json()["detail"]

    # 2. Change password with short password fails
    short_change = client.post(
        "/admin/api/auth/change-password",
        json={"current_password": "Auth-fixture-password", "new_password": "12"},
        headers={"Authorization": f"Bearer {token}", "X-Dashboard": "1"},
    )
    assert short_change.status_code == 400
    assert "최소 15자" in short_change.json()["detail"]

    # 3. Change password successfully
    change_res = client.post(
        "/admin/api/auth/change-password",
        json={"current_password": "Auth-fixture-password", "new_password": "new_sadmin_pass_99"},
        headers={"Authorization": f"Bearer {token}", "X-Dashboard": "1"},
    )
    assert change_res.status_code == 200
    assert change_res.json()["ok"] is True

    # 4. Old password no longer works
    old_login = client.post(
        "/admin/api/auth/login",
        json={"username": "sadmin", "password": "Auth-fixture-password"},
        headers={"X-Dashboard": "1"},
    )
    assert old_login.status_code == 401

    # 5. New password works
    new_login = client.post(
        "/admin/api/auth/login",
        json={"username": "sadmin", "password": "new_sadmin_pass_99"},
        headers={"X-Dashboard": "1"},
    )
    assert new_login.status_code == 200
    assert new_login.json()["ok"] is True


def approve_account(client, headers, response):
    from tests.test_admin_reviewed_commands import act
    assert response.status_code == 202, response.text
    done = act(client, headers, response.json()['item'], acknowledge=True)
    assert done.status_code == 200, done.text
    assert done.json()['item']['status'] == 'applied', done.text
    return done.json()['item']


def test_admin_user_crud_and_sadmin_protection(admin_world):
    import json
    from tests.conftest import staff_headers
    _, client = admin_world
    headers = staff_headers(client, password='Auth-fixture-password')
    users = client.get('/admin/api/users', headers=headers).json()['users']
    item = approve_account(client, headers, client.post('/admin/api/users', headers=headers,
        json={'username': 'op_test', 'password': 'operator-password-123', 'role': 'operator', 'reason': 'Synthetic create request'}))
    uid = json.loads(item['result'])['user_id']
    assert client.post('/admin/api/users', headers=headers,
        json={'username': 'op_test', 'password': 'duplicate-password-123', 'reason': 'Synthetic duplicate request'}).status_code == 400
    approve_account(client, headers, client.put('/admin/api/users/' + str(uid), headers=headers,
        json={'name': 'Updated operator', 'role': 'admin', 'reason': 'Synthetic role request'}))
    owner = next(u['id'] for u in users if u['username'] == 'sadmin')
    assert client.request('DELETE', '/admin/api/users/' + str(owner), headers=headers,
        json={'reason': 'Synthetic protected delete'}).status_code == 400
    approve_account(client, headers, client.request('DELETE', '/admin/api/users/' + str(uid), headers=headers,
        json={'reason': 'Synthetic deletion request'}))


def test_audit_logs_and_sadmin_exclusive_permission(admin_world):
    _, client = admin_world

    # 1. Login as sadmin and perform actions
    s_login = client.post(
        "/admin/api/auth/login",
        json={"username": "sadmin", "password": "Auth-fixture-password"},
        headers={"X-Dashboard": "1"},
    )
    sadmin_token = s_login.json()["token"]
    sadmin_hdr = {"Authorization": f"Bearer {sadmin_token}", "X-Dashboard": "1"}

    # Create an operator only after explicit review.
    approve_account(client, sadmin_hdr, client.post(
        "/admin/api/users",
        json={"username": "regular_admin", "password": "regular-password-123", "name": "일반관리자", "role": "admin", "reason": "Synthetic staff creation"},
        headers=sadmin_hdr,
    ))

    # 2. Login as regular_admin
    r_login = client.post(
        "/admin/api/auth/login",
        json={"username": "regular_admin", "password": "regular-password-123"},
        headers={"X-Dashboard": "1"},
    )
    assert r_login.status_code == 200
    reg_token = r_login.json()["token"]
    assert r_login.json()["user"]["is_sadmin"] is False
    reg_hdr = {"Authorization": f"Bearer {reg_token}", "X-Dashboard": "1"}

    # 3. Regular admin tries to access /admin/api/audit/logs -> MUST return 403 Forbidden!
    forbidden_audit = client.get("/admin/api/audit/logs", headers=reg_hdr)
    assert forbidden_audit.status_code == 403
    assert "sadmin(최고관리자) 권한만 접근할 수 있는 메뉴" in forbidden_audit.json()["detail"]

    # 4. Regular admin tries to access /admin/api/users -> MUST return 403 Forbidden!
    forbidden_users = client.get("/admin/api/users", headers=reg_hdr)
    assert forbidden_users.status_code == 403
    assert "sadmin(최고관리자) 권한만 접근할 수 있는 메뉴" in forbidden_users.json()["detail"]

    # 5. sadmin accesses /admin/api/audit/logs -> 200 OK and sees all logs
    audit_res = client.get("/admin/api/audit/logs", headers=sadmin_hdr)
    assert audit_res.status_code == 200
    audit_data = audit_res.json()
    assert audit_data["ok"] is True
    logs = audit_data["logs"]
    assert len(logs) > 0

    # Verify actions are properly recorded
    actions = [l["action"] for l in logs]
    assert "LOGIN" in actions
    assert "USER_CREATE" in actions

    # 6. Test filters on audit logs
    filtered = client.get("/admin/api/audit/logs?action=USER_CREATE", headers=sadmin_hdr)
    assert filtered.status_code == 200
    for l in filtered.json()["logs"]:
        assert l["action"] == "USER_CREATE"
