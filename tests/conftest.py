"""Explicit presentation fixtures; current public-entry tests keep the default."""
import functools
import time

import pytest
from starlette.testclient import TestClient as _StarletteTestClient

# 11-05 security review: production code no longer trusts the literal peer "testclient" for
# X-Forwarded-For or jail exemptions. Test clients connect from loopback instead, which is the
# default FORWARDED_ALLOW_IPS ingress (127.0.0.1, ::1) in production too.
_StarletteTestClient.__init__.__defaults__ = tuple(
    ('127.0.0.1', 50000) if value == ('testclient', 50000) else value
    for value in _StarletteTestClient.__init__.__defaults__)


@pytest.fixture
def legacy_public_entry(monkeypatch):
    """Exercise the supported embedded fallback without changing production."""
    from agent_market.concierge import pearl_view
    monkeypatch.setattr(pearl_view, 'public_page_available', lambda: False)


class _OutcomeStore:
    """In-memory stand-in for the shared Redis task-outcome counts, one per test."""
    def __init__(self):
        self.values = {}

    def get_json(self, key):
        return self.values.get(key)

    def set_json(self, key, value, ttl_seconds=None):
        self.values[key] = value


@pytest.fixture(autouse=True)
def isolated_task_outcomes(monkeypatch):
    """Gateway answers are counted per listing in the shared Redis store (task_outcomes, 11-11).

    Tests used the machine's real Redis under the 'a2a:local:' prefix, so one test's gateway calls
    (ten tools/call for a small listing id) reordered another test's recommendations.
    """
    from agent_market.concierge import task_outcomes
    store = _OutcomeStore()
    monkeypatch.setattr(task_outcomes, '_hub', lambda: store)
    yield store


@pytest.fixture(autouse=True)
def isolated_cap_changes(monkeypatch, tmp_path):
    """Collector surveys write re-survey word losses under logs/collector (11-12); tests write to tmp."""
    from agent_market.collector import cap_changes
    monkeypatch.setattr(cap_changes, 'default_directory', lambda: tmp_path / 'cap-changes')
    yield


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
