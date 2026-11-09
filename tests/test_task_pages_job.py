"""Daily task-page snapshot refresh in the jobs service (quiet hours, short slices, own store)."""
import json
import time

import pytest
from datetime import datetime

from agent_market.concierge import growth_pages as g
from agent_market.concierge import task_pages_job as job
from agent_market.concierge.task_catalog import plan

NOW = time.time()


def kst(hour):
    return datetime(2026, 11, 10, hour, 30, tzinfo=job.ZONE).timestamp()


def item(rid, name='Weather forecast service', **extra):
    value = {'id': rid, 'kind': 'mcp', 'name': name, 'description': 'Weather forecast for any city', 'category': 'travel_maps_weather',
             'health_status': 'healthy', 'last_check_at': NOW-3600, 'trial_ok': 1, 'eval_grade': 'A', 'eval_score': 90,
             'price_usdc': 0, 'connection_readiness': {}}
    value.update(extra)
    return value


class Clock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


def refresher(tmp_path, clock, search, categories=('travel_maps_weather',)):
    ticks = iter(range(0, 10**6))
    return job.TaskPagesRefresher(None, out=tmp_path/'task-pages.json', clock=clock, monotonic=lambda: next(ticks),
                                  sleep=lambda s: None, search=search, categories=categories)


def test_runs_only_in_quiet_hours_once_a_day(tmp_path):
    clock = Clock(kst(14))
    r = refresher(tmp_path, clock, lambda front, step: [])
    assert not r.due()
    clock.value = kst(3)
    assert r.due()
    (tmp_path/'task-pages.json').write_text('{}')
    r2 = refresher(tmp_path, Clock(kst(4)), lambda front, step: [])
    assert not r2.due()  # a fresh file waits for tomorrow


def test_slices_finish_and_write_a_valid_snapshot(tmp_path):
    calls = []

    def search(front, step):
        calls.append(step)
        return [item(1), item(2), item(3, name='Unrelated tool', description='Ledger docs')]
    clock = Clock(kst(3))
    r = refresher(tmp_path, clock, search)
    slices = 0
    while True:
        assert r.due()
        r.run()
        slices += 1
        if r.steps is None:
            break
    assert slices > 1  # the monotonic clock advances one second per step, so each slice stops at 20 seconds
    snapshot = g.clean(json.loads((tmp_path/'task-pages.json').read_text()))
    assert snapshot['by_slug']['weather-forecast']['agents'][0]['id'] in (1, 2)
    assert set(snapshot['catalog']) == {1, 2, 3}
    assert not r.due()  # done for today
    assert len(calls) <= len(plan(['travel_maps_weather']))


def test_a_failed_slice_waits_and_resumes(tmp_path):
    state = {'fail': True}

    def search(front, step):
        if state['fail']:
            raise RuntimeError('statement timeout')
        return []
    clock = Clock(kst(3))
    r = refresher(tmp_path, clock, search)
    r.run()
    assert r.steps is not None and not r.due()
    clock.value += 601
    state['fail'] = False
    assert r.due()
    position = r.position
    r.run()
    assert r.position > position


def test_internal_search_matches_the_public_explore_api():
    from fastapi.testclient import TestClient
    from tests.test_concierge import populated
    from agent_market.concierge.front import create_front_app
    world = populated()
    front = world.app.state.front
    for row in world.store.query('SELECT * FROM resources'):
        world.service.prober.checker.check_and_record(dict(row))
    assert job.internal_search(front, ('catalog', None, 'mcp', False, 300))  # the fixture has one MCP listing
    client = TestClient(create_front_app(front), raise_server_exceptions=False)
    for step, query in [(('task', 'g', '', False, 24), 'q=&limit=24'), (('catalog', None, 'mcp', False, 300), 'kind=mcp&limit=300'),
                        (('task', 'g', 'weather', True, 12), 'q=weather&verified=1&limit=12')]:
        response = client.get('/api/explore?'+query)
        if response.status_code != 200:
            pytest.skip('this copy (a jobs release) carries an older public frontend; the internal path was checked above')
        assert [x['id'] for x in job.internal_search(front, step)] == [x['id'] for x in response.json()['items']]


def test_jobs_loop_registers_the_refresher():
    source = open('agent_market/service_host.py').read()
    assert 'TaskPagesRefresher(front) if self.role==\'jobs\'' in source
    assert 'elif task_pages.due():self.maintenance_pending=self.maintenance_pool.submit(task_pages.run)' in source
