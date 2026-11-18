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
def fresh_agent_pacing():
    """Provider pacing is process-wide; each test starts without earlier dispatch times."""
    from agent_market import workspace_typed_flows
    workspace_typed_flows._last_dispatch.clear()
    yield


@pytest.fixture(autouse=True)
def rested_providers_cleared():
    """The 429 rest book is process-wide (provider_rest.BOOK); each test starts with no host resting."""
    from agent_market.provider_rest import BOOK
    BOOK.clear()
    yield
    BOOK.clear()


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


@pytest.fixture(autouse=True)
def isolated_provider_budget(monkeypatch, tmp_path_factory):
    """The shared outside-call ledger (provider_budget, GitHub hourly share) is a real file under gateway-data;
    tests count into a temporary folder so they never use up the services' allowance."""
    from agent_market import provider_budget
    monkeypatch.setattr(provider_budget, 'DIR', tmp_path_factory.mktemp('provider-budget'))


@pytest.fixture(autouse=True)
def isolated_news_bundle(monkeypatch, tmp_path_factory):
    """The owned technology-news bundle (11-16, GDELT) is one shared file under gateway-data that the services read;
    every engine a test makes stores its bundle in a temporary folder instead."""
    from agent_market.owned_data_agents import tech_news
    monkeypatch.setattr(tech_news, 'PATH', tmp_path_factory.mktemp('tech-news') / 'tech-news.json')


# 11-15 11:01: a watch test ran ops_auto.watch() and wrote today's date into the real once-a-day state files under
# logs/ops (the 11:05 watch skipped the revenue line and the vector-index hour). Every file the ops watch writes
# (its board, logs and state) points into a temporary folder for every test that loaded these modules; inputs the
# watch only reads (agentcon.env, release folders, the PG pid file, backups) stay as they are. A test that sets one
# of these itself still wins (its monkeypatch runs after this one).
_OPS_WRITES = {'ops_auto': None,   # every logs/ops and gateway-data path in ops_auto except the ones below
               'ops_watch': ('BOARD', 'OUT')}
_OPS_READS = ('AGENTCON_ENV',)


@pytest.fixture(autouse=True)
def isolated_ops_state(monkeypatch, tmp_path_factory):
    import sys
    from pathlib import Path
    folder = None
    for short, only in _OPS_WRITES.items():
        for module in {sys.modules.get(short), sys.modules.get('scripts.' + short)} - {None}:
            for key, value in list(vars(module).items()):
                if (not isinstance(value, Path) or key in _OPS_READS or (only is not None and key not in only)
                        or not any(part in str(value) for part in ('/logs/', '/gateway-data/'))):
                    continue
                folder = folder or tmp_path_factory.mktemp('ops-state')
                monkeypatch.setattr(module, key, folder / short / key / value.name)
                (folder / short / key).mkdir(parents=True, exist_ok=True)


# Precision review R03 (11-15): every value that points at a production store or service (the same list as
# scripts/pytest_env.PRODUCTION_POINTERS, tests/test_pytest_env.py checks it). Cleared when this conftest is
# imported, before any test module is collected (the shell that started pytest may hold them), and restored after
# every test below, whoever set them. Redis gets its own database number; production keeps 0.
_PRODUCTION_POINTERS = ('APPLICATION_', 'AGENTCON_PROJECT_ROOT', 'AGENTCON_TESTS_MAY_USE_PRODUCTION', 'GATEWAY_DB',
                        'COLLECTOR_DB', 'AD_COIN_', 'AGENT_EDGE_', 'AGENT_PRIVATE_', 'PG', 'REDIS_')
_TEST_REDIS_DB = '15'


def _clear_production_pointers():
    import os
    for key in [k for k in os.environ if k.startswith(_PRODUCTION_POINTERS)]:
        del os.environ[key]
    os.environ['REDIS_DB'] = _TEST_REDIS_DB
    # 11-18: the mark that makes infra.redis_hub refuse database 0 here and in every child that keeps it
    os.environ['AGENTCON_UNDER_TEST'] = '1'


_clear_production_pointers()


@pytest.fixture(autouse=True)
def _no_production_storage_leak():
    """PM 11-15: a test that calls a script's main() left APPLICATION_STORE_BACKEND=postgresql and the
    production DSN file in os.environ, and a later test's subprocess (workflow_maintenance --apply) opened
    the production Postgres. Values that point at storage are restored after every test, whoever set them."""
    import os
    before = {k: v for k, v in os.environ.items() if k.startswith(_PRODUCTION_POINTERS)}
    yield
    for key in [k for k in os.environ if k.startswith(_PRODUCTION_POINTERS)]:
        if key not in before:
            del os.environ[key]
    os.environ.update(before)


@pytest.fixture(autouse=True)
def _no_live_pearl_list(monkeypatch, tmp_path):
    """PM 11-18: cards and pages read gateway-data/pearls/public-pearls.json; a test never sees the live list
    (it changes three times a day). A test that needs pearls writes its own file and points PEARLS_PUBLIC_PATH at it."""
    monkeypatch.setenv('PEARLS_PUBLIC_PATH', str(tmp_path / 'no-public-pearls.json'))



# Precision review R04 (11-15): from 11-17 the production signing key exists; no test may sign into
# gateway-data/signing. Every run gets its own temporary signing folder (scripts.report_v2.signing_dir), and
# report_v2 also refuses the production folder while pytest runs.
import os as _os
import tempfile as _tempfile
_os.environ['AGENTCON_SIGNING_DIR'] = _tempfile.mkdtemp(prefix='agentcon-test-signing-')
# 11-18 (운영·SRE): rehearsal scripts that tests start as child processes (rehearse_qa7_remediation's DataAgents)
# do not see the isolated_news_bundle fixture, so their background refresh wrote two fake articles into the shared
# gateway-data/owned-data-agents/tech-news.json that production reads (11-17 02:05, 11-18 04:33 and 06:28).
# tech_news.PATH follows OWNED_NEWS_BUNDLE, which every child inherits.
_os.environ['OWNED_NEWS_BUNDLE'] = _os.path.join(_tempfile.mkdtemp(prefix='agentcon-test-news-'), 'tech-news.json')
# 11-18 (운영·SRE): a Python child does not inherit the patched socket either; tests/child_guard/sitecustomize.py
# installs the outside-network part of tests/report_redirect.py in every child whose PYTHONPATH leads with it.
_CHILD_GUARD = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'child_guard')
_os.environ['PYTHONPATH'] = _CHILD_GUARD + (_os.pathsep + _os.environ['PYTHONPATH'] if _os.environ.get('PYTHONPATH') else '')


# PM 11-17: test runs never touch production records, secrets or the production database (tests/report_redirect.py):
# writes under reports/, exports/ and the status board go to gateway-data/test-report-out/ (REPORT_SHOTS=1 writes the
# records on purpose), opening the production DSN, env or key files and connecting to the production database raise
# PermissionError. A test that must use them carries @pytest.mark.production_paths. No effect in a release copy.
from tests import report_redirect as _report_redirect
from pathlib import Path as _Path


def pytest_configure(config):
    config.addinivalue_line('markers', 'production_paths: this test reads production secrets or connects to the '
                                       'production database on purpose (reported to the PM, 11-17)')
    config.addinivalue_line('markers', 'live_network: this test calls a real outside service on purpose; the night '
                                       'full pytest leaves it out (PM 11-18)')


@pytest.fixture(autouse=True, scope='session')
def _reports_are_records():
    _report_redirect.install(_Path(__file__).resolve().parents[1])
    yield
    _report_redirect.uninstall()


@pytest.fixture(autouse=True)
def _production_paths_marker(request):
    _report_redirect.allow_production(request.node.get_closest_marker('production_paths') is not None)
    yield
    _report_redirect.allow_production(False)


@pytest.fixture(autouse=True)
def _no_outside_network(request):
    """PM 11-18 (tests/report_redirect.py part 4): no test reaches the internet unless it is marked live_network. The
    code under test may catch the refusal (a fallback agent turns it into source_unavailable), so the test fails here."""
    _report_redirect.allow_live_network(request.node.get_closest_marker('live_network') is not None)
    _report_redirect.take_outside()
    yield
    _report_redirect.allow_live_network(False)
    refused = _report_redirect.take_outside()
    if refused:
        pytest.fail('outside network refused: ' + ', '.join(sorted({f'{host}:{port}' for _, host, port in refused}))
                    + ' (use a cassette or fake transport, or mark live_network)', pytrace=False)
