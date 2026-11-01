"""Explicit presentation fixtures; current public-entry tests keep the default."""
import functools
import time

import pytest


@pytest.fixture
def legacy_public_entry(monkeypatch):
    """Exercise the supported embedded fallback without changing production."""
    from agent_market.concierge import pearl_view
    monkeypatch.setattr(pearl_view, 'public_page_available', lambda: False)


@pytest.fixture(autouse=True)
def fresh_agent_pacing():
    """Provider pacing is process-wide; each test starts without earlier dispatch times."""
    from agent_market import workspace_typed_flows
    workspace_typed_flows._last_dispatch.clear()
    yield


@pytest.fixture
def rotated_bootstrap_admin(monkeypatch):
    """Legacy feature tests sign in as the bootstrap superadmin; treat it as already rotated.

    The forced-rotation boundary itself is covered by test_admin_renewal_auth and test_admin_auth.
    """
    from agent_market.gateway import admin_auth
    monkeypatch.setattr(admin_auth, 'password_change_required', lambda *_: False)


def staff_headers(client, username='sadmin', password='sadmin'):
    """Individual staff session headers; the shared machine token only reads aggregate monitoring."""
    response = client.post('/admin/api/auth/login', headers={'X-Dashboard': '1'},
                           json={'username': username, 'password': password})
    assert response.status_code == 200, response.text
    return {'X-Dashboard': '1', 'Authorization': 'Bearer ' + response.json()['token']}


STAFF_TOKEN = '5a' * 32
STAFF = {'X-Dashboard': '1', 'Authorization': 'Bearer ' + STAFF_TOKEN}


@functools.cache
def _rotated_password():
    from agent_market.gateway import admin_auth
    return admin_auth.hash_password('Synthetic-rotated-password', 'synthetic-staff-salt')


def staff_session(store, token=STAFF_TOKEN):
    """A separate synthetic superadmin with a rotated password and a known individual session.

    The bootstrap sadmin account is left untouched so login and rotation tests keep their own flow.
    """
    from agent_market.gateway import admin_auth
    with store.tx() as db:
        if not db.execute('SELECT 1 FROM admin_sessions WHERE token=?', (admin_auth.session_reference(token),)).fetchone():
            row = db.execute("SELECT id FROM admin_users WHERE username='synthetic-staff'").fetchone()
            if row is None:
                digest, salt = _rotated_password()
                now = time.time()
                db.execute("INSERT INTO admin_users (username, password_hash, salt, role, name, active, created_at, updated_at) "
                           "VALUES ('synthetic-staff', ?, ?, 'superadmin', 'Synthetic staff', 1, ?, ?)", (digest, salt, now, now))
                row = db.execute("SELECT id FROM admin_users WHERE username='synthetic-staff'").fetchone()
            db.execute('INSERT INTO admin_sessions (token, user_id, username, role, name, created_at, expires_at) VALUES (?,?,?,?,?,?,?)',
                       (admin_auth.session_reference(token), row[0], 'synthetic-staff', 'superadmin', 'Synthetic staff', time.time(), time.time() + 86400))
    return {'X-Dashboard': '1', 'Authorization': 'Bearer ' + token}
