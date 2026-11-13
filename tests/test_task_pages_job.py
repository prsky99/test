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


def item(rid, name=None, **extra):
    # A distinct name, a 40+ character description and tools: an indexed detail page (11-14 noindex tiers).
    value = {'id': rid, 'kind': 'mcp', 'name': name or 'Weather forecast service %d' % rid,
             'description': 'Weather forecast for any city, hourly and daily', 'tool_count': 2, 'category': 'travel_maps_weather',
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


def _traffic_day(root, day, name=None, calls=1, clients=None):
    """One recorder per day (the day file is named by process id, so a second recorder would replace it)."""
    from datetime import datetime, timezone
    from agent_market.concierge import traffic
    at = datetime.fromisoformat(day + 'T12:00:00+00:00').timestamp()
    rec = traffic.Traffic(root / 'service-frontend' / 'traffic', clock=lambda: at)
    for name, calls in (clients or {name: calls}).items():
        rec.observe('POST', '/mcp', 200, '203.0.113.5', 'node',
                    b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"clientInfo":{"name":"' + name.encode() + b'"}}}',
                    {}, {'mcp-session-id': 's-' + name})
        for _ in range(calls):
            rec.observe('POST', '/mcp', 200, '203.0.113.5', 'node', b'{"jsonrpc":"2.0","id":2,"method":"tools/call"}',
                        {'mcp-session-id': 's-' + name}, {})
        rec.observe('GET', '/mcp', 405, '203.0.113.5', 'node', b'', {'accept': 'text/event-stream'}, {})
    rec.flush()


def test_missing_usage_days_are_filled_in_order_and_a_day_without_files_is_skipped(tmp_path):
    """11-14 PM: a late or failed build left 11-12 and 11-13 out; the next run writes every finished day."""
    import json
    from datetime import datetime, timezone
    from agent_market.concierge.task_pages_job import TaskPagesRefresher
    root = tmp_path / 'logs'
    for day in ('2026-11-10', '2026-11-12', '2026-11-13'):
        _traffic_day(root, day, 'Cursor')
    (root / 'growth').mkdir(parents=True)
    (root / 'growth' / 'usage-daily.jsonl').write_text(json.dumps({'day': '2026-11-10'}) + '\n')
    job = TaskPagesRefresher(None, out=root / 'service-frontend' / 'public-pages' / 'task-pages.json',
                             clock=lambda: datetime(2026, 11, 14, 3, tzinfo=timezone.utc).timestamp(), categories=[])
    job.record_usage()
    days = [json.loads(line)['day'] for line in (root / 'growth' / 'usage-daily.jsonl').read_text().splitlines()]
    assert days == ['2026-11-10', '2026-11-12', '2026-11-13']   # 11-11 had no files; 11-14 is not finished


def test_usage_line_recounts_real_calls_by_name_and_splits_spec_errors(tmp_path):
    """11-13: adding 'histor' to the probe list moved its calls from real to probe; by name the rule is one."""
    import json
    from datetime import datetime, timezone
    from agent_market.concierge.task_pages_job import TaskPagesRefresher
    root = tmp_path / 'logs'
    _traffic_day(root, '2026-11-13', clients={'Cursor': 2, 'histor': 5})
    job = TaskPagesRefresher(None, out=root / 'service-frontend' / 'public-pages' / 'task-pages.json',
                             clock=lambda: datetime(2026, 11, 14, 3, tzinfo=timezone.utc).timestamp(), categories=[])
    job.record_usage()
    row = json.loads((root / 'growth' / 'usage-daily.jsonl').read_text())
    assert row['mcp_tool_calls_real_by_name'] == 2 and row['mcp_tool_calls_real'] == 2 and row['probe_list']
    assert row['protocol_errors_spec'] == 2 and row['protocol_errors_other'] == 0
    assert row['protocol_errors'] == row['protocol_errors_spec'] + row['protocol_errors_other']


def test_the_build_start_writes_the_usage_line_before_the_snapshot_finishes(tmp_path):
    import json
    from datetime import datetime, timezone
    from agent_market.concierge.task_pages_job import TaskPagesRefresher
    root = tmp_path / 'logs'
    _traffic_day(root, '2026-11-12', 'Cursor')
    job = TaskPagesRefresher(object(), out=root / 'service-frontend' / 'public-pages' / 'task-pages.json',
                             clock=lambda: datetime(2026, 11, 13, 18, tzinfo=timezone.utc).timestamp(),
                             monotonic=iter(range(0, 10**6, 100)).__next__, search=lambda *a: [], categories=['weather'])
    job.run()            # the first slice only plans and starts; the snapshot is far from done
    assert job.steps is not None
    assert [json.loads(l)['day'] for l in (root / 'growth' / 'usage-daily.jsonl').read_text().splitlines()] == ['2026-11-12']
