"""Approved retention (design 4.3/6.1): nothing deleted by default, reviewed periods, summarized days only."""
# ruff: noqa: F811 -- shared isolated fixtures
import time

import pytest

from agent_market import workspace_admin_retention as module
from agent_market.workspace_admin_events import migrate
from agent_market.workspace_admin_retention import Retention, validate
from agent_market.workspace_admin_summaries import DAY, HealthSummaries
from tests.test_admin_next import login
from tests.test_dashboard import dash  # noqa: F401

D = {'X-Dashboard': '1'}
NOW = time.time()


def test_policy_validation_enforces_floors_backup_and_tables():
    assert validate({'table': 'health_checks', 'days': 3, 'backup_confirmed': True})
    assert validate({'table': 'security_events', 'days': None, 'backup_confirmed': True})
    for bad in ({'table': 'health_checks', 'days': 2, 'backup_confirmed': True},
                {'table': 'security_events', 'days': 7, 'backup_confirmed': True},
                {'table': 'health_checks', 'days': 3, 'backup_confirmed': False},
                {'table': 'admin_users', 'days': 30, 'backup_confirmed': True},
                {'table': 'health_checks', 'days': '3', 'backup_confirmed': True},
                {'table': 'health_checks', 'days': 3}):
        with pytest.raises(ValueError):
            validate(bad)


def test_unmigrated_store_never_deletes_and_cannot_request(dash):
    world, client = dash
    assert Retention(world.store).run_due(force=True) == {'ready': False}
    staff = login(client)
    assert client.get('/admin/api/v2/system/retention/policy', headers=staff).json()['available'] is False
    response = client.post('/admin/api/v2/system/retention/policy', headers=staff,
                           json={'table': 'health_checks', 'days': 3, 'backup_confirmed': True, 'reason': '보존 기간 단축 요청'})
    assert response.status_code == 409


@pytest.fixture
def migrated(dash):
    world, client = dash
    migrate(world.store, world.store._workspace_admin_identity_key)
    with world.store.tx() as db:
        db.execute("UPDATE admin_users SET active=0 WHERE role='superadmin' AND username!='sadmin'")
    return world, client, login(client)


def seed_checks(store, days_ago_list, rid=11):
    with store.tx() as db:
        for days_ago in days_ago_list:
            db.execute('INSERT INTO health_checks(resource_id,at,outcome,status_code,latency_ms) VALUES(?,?,?,?,?)',
                       (rid, NOW - days_ago * DAY, 'healthy', 200, 100))


def count(store, table, older_than_days):
    return store.query(f'SELECT COUNT(*) FROM {table} WHERE at<?', (NOW - older_than_days * DAY,))[0][0]


def test_reviewed_period_deletes_only_summarized_days(migrated):
    world, client, staff = migrated
    seed_checks(world.store, [6, 5, 4.5, 1, 0.1])
    request = client.post('/admin/api/v2/system/retention/policy', headers=staff,
                          json={'table': 'health_checks', 'days': 3, 'backup_confirmed': True, 'reason': '상태 확인 원본 3일 보존'})
    assert request.status_code == 202, request.text
    review = request.json()['review']
    runner = Retention(world.store)
    assert runner.run_due(force=True) == {'ready': True, 'removed': {}}  # nothing until approved
    applied = client.post(f"/admin/api/v2/reviews/{review['id']}/approve", headers=staff,
                          json={'revision': review['revision'], 'reason': '백업 확인 후 승인', 'acknowledge': True})
    assert applied.status_code == 200 and applied.json()['item']['status'] == 'applied'
    assert client.get('/admin/api/v2/system/retention/policy', headers=staff).json()['policy']['health_checks'] == 3
    # Without daily summaries no raw check is removed.
    assert runner.run_due(force=True)['removed'] == {'health_checks': 0}
    assert count(world.store, 'health_checks', 3) == 3
    summaries = HealthSummaries(world.store)
    for _ in range(8):
        summaries.run_due(force=True)
    assert runner.run_due(force=True)['removed']['health_checks'] == 3
    assert count(world.store, 'health_checks', 3) == 0 and count(world.store, 'health_checks', 0) == 2
    assert any(row['checks'] for row in summaries.agent(11, days=30))  # history kept in the summary
    last = client.get('/admin/api/v2/system/retention/policy', headers=staff).json()['last']
    assert last['removed'] == {'health_checks': 3}


def test_batches_respect_the_floor_and_stopping_the_policy(migrated, monkeypatch):
    world, client, _ = migrated
    with world.store.tx() as db:
        for days_ago in (40, 35, 31, 10):
            db.execute('INSERT INTO security_events(at,event_type,ip,path,detail) VALUES(?,?,?,?,?)',
                       (NOW - days_ago * DAY, 'synthetic', '192.0.2.1', '/x', 'fixture'))
    runner = Retention(world.store)
    runner.apply({'table': 'security_events', 'days': 30, 'backup_confirmed': True}, 1)
    monkeypatch.setattr(module, 'BATCH', 2)
    assert runner.run_due(force=True)['removed'] == {'security_events': 3}
    assert count(world.store, 'security_events', 0) == 1
    runner.apply({'table': 'security_events', 'days': None, 'backup_confirmed': True}, 1)
    assert runner.run_due(force=True)['removed'] == {}
    with pytest.raises(ValueError):
        runner.apply({'table': 'security_events', 'days': 10, 'backup_confirmed': True}, 1)


def test_completed_vector_jobs_only_and_index_gate(migrated, monkeypatch):
    world, client, staff = migrated
    with world.store.tx() as db:
        for n, (status, days_ago) in enumerate((('superseded', 9), ('indexed', 8), ('failed', 7), ('pending', 9), ('indexed', 1))):
            db.execute('INSERT INTO legacy_vector_jobs(job_id,resource_id,generation,status,created,finished) VALUES(?,?,?,?,?,?)',
                       ('job-%d' % n, 1, 1, status, NOW - days_ago * DAY, NOW - days_ago * DAY))
    runner = Retention(world.store)
    status = client.get('/admin/api/v2/system/retention/policy', headers=staff).json()
    assert status['tables']['legacy_vector_jobs']['indexed'] is True  # SQLite builds its own index
    runner.apply({'table': 'legacy_vector_jobs', 'days': 3, 'backup_confirmed': True}, 1)
    assert runner.run_due(force=True)['removed'] == {'legacy_vector_jobs': 3}
    left = sorted(row[0] for row in world.store.query("SELECT status FROM legacy_vector_jobs WHERE job_id LIKE 'job-%'"))
    assert left == ['indexed', 'pending']  # recent completed job and unfinished work stay
    # A PostgreSQL store without the operator-built index refuses the request and skips the table.
    original = Retention.indexed
    monkeypatch.setattr(Retention, 'indexed', lambda self, table: table != 'platform_observation_events' and original(self, table))
    refused = client.post('/admin/api/v2/system/retention/policy', headers=staff, json={
        'table': 'platform_observation_events', 'days': 30, 'backup_confirmed': True, 'reason': '관측 이벤트 30일 보존'})
    assert refused.status_code == 409 and '인덱스' in refused.json()['detail']
    runner.apply({'table': 'platform_observation_events', 'days': 30, 'backup_confirmed': True}, 1)
    assert runner.run_due(force=True)['removed']['platform_observation_events'] == 'index_missing'


def test_security_events_step_stops_at_its_row_limit(migrated, monkeypatch):
    world, client, _ = migrated
    with world.store.tx() as db:
        for n in range(7):
            db.execute('INSERT INTO security_events(at,event_type,ip,path,detail) VALUES(?,?,?,?,?)',
                       (NOW - (100 + n) * DAY, 'synthetic', '192.0.2.0/24', '/x', 'fixture'))
    runner = Retention(world.store)
    runner.apply({'table': 'security_events', 'days': 90, 'backup_confirmed': True}, 1)
    monkeypatch.setattr(module, 'BATCH', 2)
    monkeypatch.setitem(module.STEP_LIMIT, 'security_events', 4)
    assert runner.run_due(force=True)['removed'] == {'security_events': 4}   # two full batches, then stop
    assert runner.run_due(force=True)['removed'] == {'security_events': 3}   # the rest on the next step
    assert runner.status()['last']['removed'] == {'security_events': 3}
    assert module.STEP_LIMIT['security_events'] == 4 and module.TABLES['security_events'][1] <= 90
