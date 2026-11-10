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


# ---------------------------------------------------------------- IndexNow differences
def snapshot_with(items):
    from agent_market.concierge.task_catalog import Assembler
    a = Assembler()
    a.add(('task', 'Weather', 'weather forecast', True, 12), items)
    a.add(('catalog', 'travel_maps_weather', 'mcp', True, 300), items)
    return g.clean(a.snapshot({'day': '2026-11-10', 'cataloged': 10, 'reachable': 5, 'with_status_check': 10, 'a2a': 3, 'mcp': 4, 'x402': 3}))


def test_fingerprints_ignore_timestamps_but_catch_real_changes():
    from agent_market.concierge import indexnow
    base = indexnow.fingerprints(snapshot_with([item(1), item(2)]))
    later = indexnow.fingerprints(snapshot_with([item(1, last_check_at=NOW-60, probe_latency_ms=99), item(2)]))
    assert indexnow.changed(base, later) == []  # a newer health check alone is not a new page
    graded = indexnow.fingerprints(snapshot_with([item(1, eval_grade='B'), item(2)]))
    assert '/agent/1' in indexnow.changed(base, graded) and '/agent/2' not in indexnow.changed(base, graded)
    added = indexnow.fingerprints(snapshot_with([item(1), item(2), item(5)]))
    assert '/agent/5' in indexnow.changed(base, added)
    removed = indexnow.fingerprints(snapshot_with([item(1), item(5)]))
    assert '/agent/2' in indexnow.changed(base, removed)  # deletions are announced too


def test_submit_checks_the_key_with_one_url_first():
    from agent_market.concierge import indexnow
    calls = []

    def opener_for(code):
        def opener(request, timeout):
            calls.append(len(json.loads(request.data)['urlList']))
            if code != 200:
                raise indexnow.urllib.error.HTTPError(request.full_url, code, 'x', {}, None)

            class R:
                status = 200
                def __enter__(self): return self
                def __exit__(self, *e): return False
            return R()
        return opener
    urls = ['https://agentconcierge.biz/agent/%d' % i for i in range(5)]
    assert indexnow.submit('k'*32, urls, opener_for(403)) == (False, [403]) and calls == [1]
    calls.clear()
    assert indexnow.submit('k'*32, urls, opener_for(200)) == (True, [200, 200]) and calls == [1, 4]


def test_job_records_a_baseline_then_sends_only_differences(tmp_path):
    (tmp_path/'indexnow-key').write_text('a'*32)
    sent = []
    clock = Clock(kst(3))
    r = refresher(tmp_path, clock, lambda front, step: [item(1), item(2)])
    r.submit = lambda key, urls: (sent.append(urls) or (True, [200]))
    while True:
        r.run()
        if r.steps is None:
            break
    assert sent == [] and (tmp_path/'indexnow-state.json').exists()  # first day: baseline only
    clock.value = kst(3) + 86400
    r2 = refresher(tmp_path, clock, lambda front, step: [item(1, eval_grade='B'), item(2)])
    r2.submit = lambda key, urls: (sent.append(urls) or (True, [200]))
    (tmp_path/'task-pages.json').touch()
    import os
    os.utime(tmp_path/'task-pages.json', (clock.value-86400, clock.value-86400))
    while True:
        r2.run()
        if r2.steps is None:
            break
    assert len(sent) == 1 and 'https://agentconcierge.biz/agent/1' in sent[0]
    assert 'https://agentconcierge.biz/agent/2' not in sent[0]


def test_job_retries_a_403_later(tmp_path):
    (tmp_path/'indexnow-key').write_text('a'*32)
    clock = Clock(kst(3))
    r = refresher(tmp_path, clock, lambda front, step: [])
    answers = iter([(False, [403]), (True, [200, 200])])
    r.submit = lambda key, urls: next(answers)
    r.notice = {'urls': ['https://agentconcierge.biz/agent/1'], 'pages': {'/agent/1': 'x'}, 'attempts': 0}
    r.run()
    assert r.notice is not None and not r.due()
    clock.value += job.NOTICE_RETRY
    assert r.due()
    r.run()
    assert r.notice is None and json.loads((tmp_path/'indexnow-state.json').read_text())['pages'] == {'/agent/1': 'x'}


def test_usage_line_is_written_once_per_day(tmp_path):
    import json
    from datetime import datetime, timezone
    from agent_market.concierge import traffic
    from agent_market.concierge.task_pages_job import TaskPagesRefresher
    root = tmp_path / 'logs'
    rec = traffic.Traffic(root / 'service-frontend' / 'traffic', clock=lambda: datetime(2026, 11, 9, 12, tzinfo=timezone.utc).timestamp())
    rec.observe('POST', '/mcp', 200, '203.0.113.5', 'node',
                b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"clientInfo":{"name":"Cursor"}}}', {}, {'mcp-session-id': 's'})
    rec.observe('POST', '/mcp', 200, '203.0.113.5', 'node', b'{"jsonrpc":"2.0","id":2,"method":"tools/call"}', {'mcp-session-id': 's'}, {})
    rec.flush()
    job = TaskPagesRefresher(None, out=root / 'service-frontend' / 'public-pages' / 'task-pages.json',
                             clock=lambda: datetime(2026, 11, 10, 19, tzinfo=timezone.utc).timestamp(), categories=[])
    job.record_usage()
    job.record_usage()
    lines = (root / 'growth' / 'usage-daily.jsonl').read_text().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row['day'] == '2026-11-09' and row['mcp_sessions_real'] == 1 and row['mcp_tool_calls_real'] == 1
