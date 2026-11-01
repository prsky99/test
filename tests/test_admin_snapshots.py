"""Persisted console projections: a restarted process answers from the last snapshot (design 5.3)."""
# ruff: noqa: F811 -- shared isolated fixtures
import threading
import time
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.admin_next import SnapshotStore, TimedCache
from agent_market.gateway.dashboard import dashboard_router
from agent_market.workspace_admin_events import migrate
from tests.test_admin_next import login
from tests.test_dashboard import dash  # noqa: F401


class Memory:
    def __init__(self, saved=None):
        self.saved, self.writes = dict(saved or {}), []

    def load(self, key):
        return self.saved.get(key)

    def save(self, key, value):
        self.writes.append((key, value))
        return True


def test_cold_cache_answers_from_snapshot_and_refreshes_in_background():
    done = threading.Event()
    def loader():
        done.set()
        return {'n': 2}
    persist = Memory({'home': (120.0, {'n': 1})})
    cache = TimedCache(5, 30, persist=persist)
    first = cache.get('home', loader)
    assert first == {'n': 1, 'cache': 'stale'}
    assert done.wait(2)
    for _ in range(100):
        if persist.writes:
            break
        time.sleep(0.01)
    assert persist.writes == [('home', {'n': 2})]
    assert cache.get('home', loader) == {'n': 2, 'cache': 'hit'}


def test_local_write_never_serves_an_older_snapshot():
    persist = Memory({'home': (10.0, {'n': 1})})
    cache = TimedCache(5, 30, persist=persist)
    cache.invalidate()
    assert cache.get('home', lambda: {'n': 3}) == {'n': 3, 'cache': 'miss'}
    # A successful save clears the fence, so the next cold read may use snapshots again.
    assert cache.invalidated is False


def test_snapshot_store_is_throttled_bounded_and_requires_migration(dash):
    world, _ = dash
    clock = [1000.0]
    snapshots = SnapshotStore(world.store, every=60, clock=lambda: clock[0])
    assert snapshots.load('home') is None and snapshots.save('home', {'n': 1}) is False  # not migrated
    migrate(world.store, b'synthetic-snapshot-key-32-bytes!!')
    assert snapshots.save('home', {'n': 1}) is True
    assert snapshots.save('home', {'n': 2}) is False  # throttled
    clock[0] += 30
    assert snapshots.load('home') == (30.0, {'n': 1})
    clock[0] += 61
    assert snapshots.save('home', {'blob': 'x' * 600_000}) is False  # oversize is skipped
    assert snapshots.save(24, {'n': 3}) is True and snapshots.load(24)[1] == {'n': 3}
    clock[0] += 86_401
    assert snapshots.load('home') is None  # too old to show


def test_restarted_console_reads_the_snapshot_without_source_aggregation(dash):
    world, client = dash
    migrate(world.store, world.store._workspace_admin_identity_key)  # the key the app itself activates with
    staff = login(client)
    first = client.get('/admin/api/v2/home/bootstrap', headers=staff)
    assert first.status_code == 200
    cataloged = first.json()['overview']['public_catalog']['cataloged']
    # A new router on the same store stands in for a restarted process whose aggregation is slow.
    restarted = FastAPI()
    restarted.include_router(dashboard_router(world.store, world.store._path, None, None, ssl_manager=Mock(get_status=lambda: {})))
    with TestClient(restarted) as again:
        started = time.perf_counter()
        second = again.get('/admin/api/v2/home/bootstrap', headers=staff)
        elapsed = time.perf_counter() - started
    assert second.status_code == 200, second.text
    assert second.json()['overview']['public_catalog']['cataloged'] == cataloged
    assert second.json()['overview']['cache'] == 'stale' and elapsed < 2


def test_activity_is_superadmin_only_and_hides_literal_values(dash):
    from agent_market.admin_next import statement_shape
    from agent_market.gateway import admin_auth
    world, client = dash
    staff = login(client)
    result = client.get('/admin/api/v2/system/activity', headers=staff)
    assert result.status_code == 200 and result.json()['available'] is False  # SQLite fixture
    with world.store.tx() as db:
        admin_auth.create_admin_user(db, 'activity-admin', 'Activity-admin-password', 'Admin', 'admin')
    token = client.post('/admin/api/auth/login', headers={'X-Dashboard': '1'},
                        json={'username': 'activity-admin', 'password': 'Activity-admin-password'}).json()['token']
    assert client.get('/admin/api/v2/system/activity', headers={'X-Dashboard': '1', 'authorization': 'Bearer ' + token}).status_code == 403
    assert client.get('/admin/api/v2/system/activity', headers={'X-Dashboard': '1'}).status_code == 401
    shape = statement_shape("SELECT * FROM admin_users WHERE username='o''brien' AND id=42 AND score>3.5\n  LIMIT 10")
    assert shape == 'SELECT * FROM admin_users WHERE username=? AND id=? AND score>? LIMIT ?'
    assert len(statement_shape('SELECT ' + 'x,' * 400)) == 160
