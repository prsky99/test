"""11-10 ten-minute work-status check: parsing helpers stay correct."""
from scripts import ops_watch


def test_etime_parsing():
    assert ops_watch.etime_seconds('04:46') == 286
    assert ops_watch.etime_seconds('01:21:23') == 4883
    assert ops_watch.etime_seconds('29-18:53:38') == 29 * 86400 + 18 * 3600 + 53 * 60 + 38


def test_board_lock_and_handoffs(tmp_path, monkeypatch):
    board = tmp_path / 'board.md'
    board.write_text('## 배포 잠금\n검색과 RAG 01-01 00:00 — x\n\n## 넘기는 일\n| PM | 운영 | 일 | 대기 |\n\n## PM 결정 대기\n')
    monkeypatch.setattr(ops_watch, 'BOARD', board)
    found = ops_watch.check_board()
    assert found['deploy_lock']['held_minutes'] > 40
    board.write_text('## 배포 잠금\n(비어 있음)\n\n## 넘기는 일\n')
    assert ops_watch.check_board() == {}


def test_disk_check_returns_numbers():
    disk = ops_watch.check_disk()
    assert disk is None or (0 <= disk['used_percent'] <= 100 and disk['free_gb'] >= 0)


def test_auto_watch_alerts_once_and_writes_handoff(tmp_path, monkeypatch):
    import json, subprocess, sys
    from scripts import ops_auto
    board = tmp_path / 'board.md'
    board.write_text('## 넘기는 일\n| 보낸 팀 | 받는 팀 | 내용 | 상태 |\n|---|---|---|---|\n\n## PM 결정 대기\n')
    for name, value in (('BOARD', board), ('ACTIONS', tmp_path / 'a.md'), ('STATE', tmp_path / 's.json'),
                        ('DESKTOP', tmp_path / 'desk.txt')):
        monkeypatch.setattr(ops_auto, name, value)
    fake = json.dumps({'anomalies': {'memory': {'free_percent': 9}}})
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 0, fake, ''))
    monkeypatch.setattr(ops_auto.ops_llm, 'ask', lambda *a, **k: None)  # no API in tests
    monkeypatch.setattr(ops_auto, 'error_ledger', lambda: None)  # tested in test_error_ledger.py
    monkeypatch.setattr(ops_auto, 'provenance', lambda: None)    # tested below and in test_provenance_check.py
    monkeypatch.setattr(ops_auto, 'ad_coin_ledger', lambda: None)  # tested below
    monkeypatch.setattr(ops_auto, 'outside_load', lambda: None)    # tested below
    monkeypatch.setattr(ops_auto, 'stability_gate', lambda: None)  # tested in test_stability_gate.py
    monkeypatch.setattr(ops_auto, 'full_check', lambda: None)  # tested below
    ops_auto.watch()
    ops_auto.watch()  # same anomaly within 30 minutes: no second alert
    assert board.read_text().count('자동 점검') == 1
    assert (tmp_path / 'desk.txt').read_text().count('[운영 이상]') == 1
    assert '## PM 결정 대기' in board.read_text()


def test_board_handoff_refreshes_one_open_line_per_kind(tmp_path, monkeypatch):
    from scripts import ops_auto
    board = tmp_path / 'board.md'
    board.write_text('## 넘기는 일\n| 보낸 팀 | 받는 팀 | 내용 | 상태 |\n|---|---|---|---|\n\n## PM 결정 대기\n- x\n')
    monkeypatch.setattr(ops_auto, 'BOARD', board)
    ops_auto.board_handoff('lock', 'lock held 48 min')
    ops_auto.board_handoff('lock', 'lock held 79 min')
    ops_auto.board_handoff('site', 'site slow')
    text = board.read_text()
    assert text.count('자동 점검 [lock]') == 1 and 'lock held 79 min' in text and '같은 경고 2회째' in text
    ops_auto.board_handoff('lock', 'lock held 109 min')
    assert '같은 경고 3회째' in board.read_text() and board.read_text().count('자동 점검 [lock]') == 1
    closed = board.read_text().replace('| 대기 |', '| 해결 |', 1)   # the team closes the lock line
    board.write_text(closed)
    ops_auto.board_handoff('lock', 'lock held again')
    text = board.read_text()
    assert text.count('자동 점검 [lock]') == 2 and text.count('자동 점검 [site]') == 1
    assert text.rstrip().endswith('- x') and '## PM 결정 대기' in text


def _board(tmp_path, monkeypatch):
    from scripts import ops_auto
    board = tmp_path / 'board.md'
    board.write_text('## 넘기는 일\n| 보낸 팀 | 받는 팀 | 내용 | 상태 |\n|---|---|---|---|\n\n## PM 결정 대기\n')
    monkeypatch.setattr(ops_auto, 'BOARD', board)
    monkeypatch.setattr(ops_auto, 'ACTIONS', tmp_path / 'a.md')
    return ops_auto, board


def test_a_target_that_passes_closes_its_open_line(tmp_path, monkeypatch):
    import subprocess
    ops_auto, board = _board(tmp_path, monkeypatch)
    ops_auto.board_handoff('slo_pages', 'pages slow')
    ops_auto.board_handoff('slo_connect', 'connect unmeasured')
    monkeypatch.setattr(ops_auto, 'SLO_STATE', tmp_path / 'slo.json')
    # Real records carry sample lists (11-11 17:07: a number here hid a TypeError on the real shape).
    record = ('{"at": "2026-11-11 18:08", "targets": {"page_s": 2.0}, "pages": {"ok": true, "samples": [{"path": "/", "s": 1.1}]}, '
              '"connect": {"ok": false, "samples": [], "bad": []}, "breaches": {}}')
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 0, record + '\n', ''))
    ops_auto.user_slo()
    text = board.read_text()
    assert '자동 점검 [slo_pages]' in text and '해결(자동' in text
    assert [l for l in text.splitlines() if '[slo_connect]' in l][0].endswith('| 대기 |')   # not measured: stays open


def test_full_check_runs_every_two_hours_and_records_a_deferral(tmp_path, monkeypatch):
    ops_auto, board = _board(tmp_path, monkeypatch)
    monkeypatch.setattr(ops_auto, 'FULL_CHECK_STATE', tmp_path / 'fc.json')
    monkeypatch.setattr(ops_auto, 'busy', lambda: None)
    launched = []
    run = lambda t, free: ops_auto.full_check(clock=lambda: t, launch=lambda *a, **k: launched.append(a), free=free,
                                              window=False)
    assert run(10_000, False) == 'deferred' and not launched
    assert '자동 점검 [full_check_deferred]' in board.read_text()
    assert run(10_600, False) == 'deferred' and board.read_text().count('[full_check_deferred]') == 1
    assert run(11_200, True) == 'started' and 'scripts.heavy_slot' in launched[0][0]
    assert launched[0][0][-2].endswith('.venv-tests/bin/python')   # playwright lives only in .venv-tests
    assert '해결(자동' in board.read_text()
    assert run(11_200 + 3600, True) is None                  # not yet two hours
    assert run(11_200 + 7300, True) == 'started' and len(launched) == 2


def test_provenance_runs_once_a_day_and_warns_or_closes(tmp_path, monkeypatch):
    from datetime import datetime
    ops_auto, board = _board(tmp_path, monkeypatch)
    monkeypatch.setattr(ops_auto, 'PROVENANCE_STATE', tmp_path / 'prov.json')
    at = lambda h, m, d=12: datetime(2026, 11, d, h, m).timestamp()
    dirty = lambda: {'uncommitted': {'cap-jobs-r1': ['agent_market/x.py']}, 'closed': [], 'open': ['agent_market/x.py']}
    assert ops_auto.provenance(clock=lambda: at(6, 0), run=dirty) is None           # before 06:30
    assert ops_auto.provenance(clock=lambda: at(6, 31), run=dirty) == 'warned'
    assert '자동 점검 [provenance]' in board.read_text() and 'agent_market/x.py' in board.read_text()
    assert ops_auto.provenance(clock=lambda: at(9, 0), run=dirty) is None            # once a day
    clean = lambda: {'uncommitted': {}, 'closed': ['agent_market/x.py'], 'open': []}
    assert ops_auto.provenance(clock=lambda: at(6, 40, 13), run=clean) == 'clean'
    assert [l for l in board.read_text().splitlines() if '[provenance]' in l][0].count('해결(자동') == 1


def test_ad_coin_ledger_runs_once_a_day_after_nine_and_reports(tmp_path, monkeypatch):
    import types
    from datetime import datetime
    ops_auto, board = _board(tmp_path, monkeypatch)
    monkeypatch.setattr(ops_auto, 'ADC_LEDGER_STATE', tmp_path / 'adc.json')
    env = tmp_path / 'agentcon.env'
    env.write_text('APPLICATION_POSTGRES_DSN_FILE=/x/dsn\nAPPLICATION_WORKFLOW_KEY_FILE="/x/key"\nOTHER=1\n')
    monkeypatch.setattr(ops_auto, 'AGENTCON_ENV', env)
    at = lambda h, d=12: datetime(2026, 11, d, h, 5).timestamp()
    calls = []
    fail = lambda c: calls.append(c) or types.SimpleNamespace(returncode=1, stdout='{"ok": false, "issues": ["x"]}', stderr='')
    assert ops_auto.ad_coin_ledger(clock=lambda: at(4), run=fail) is None          # inside the 03-08 window
    assert ops_auto.ad_coin_ledger(clock=lambda: at(9), run=fail) == 'failed'
    assert calls[0][-4:] == ['--dsn-file', '/x/dsn', '--key-file', '/x/key']
    assert '자동 점검 [ad_coin_ledger]' in board.read_text() and '| AI AD Coin |' in board.read_text()
    assert ops_auto.ad_coin_ledger(clock=lambda: at(10), run=fail) is None         # once a day
    ok = lambda c: types.SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr='')
    assert ops_auto.ad_coin_ledger(clock=lambda: at(9, 13), run=ok) == 'clean'
    assert '해결(자동' in [l for l in board.read_text().splitlines() if '[ad_coin_ledger]' in l][0]


def test_outside_load_names_other_projects_and_closes_when_the_load_drops(tmp_path, monkeypatch):
    ops_auto, board = _board(tmp_path, monkeypatch)
    ws = str(ops_auto.WORKSPACE)
    folders = {11: ws + '/driver_agent', 12: ws + '/driver_agent/tests', 13: str(ops_auto.ROOT), 14: '/'}
    ps = lambda: '  90.0 11\n  80.0 12\n  70.0 13\n  60.0 14\n'
    assert ops_auto.outside_load(load=4.0, ps=ps, cwd_of=folders.get) is None          # quiet below the threshold
    found = ops_auto.outside_load(load=23.5, ps=ps, cwd_of=folders.get)
    assert found == {'driver_agent': (2, 170.0)}                                        # our own and system processes left out
    line = [l for l in board.read_text().splitlines() if '[outside_load]' in l][0]
    assert 'driver_agent 프로세스 2개 CPU 170%' in line and 'load 23.5' in line
    ops_auto.outside_load(load=3.0, ps=ps, cwd_of=folders.get)
    assert '해결(자동' in [l for l in board.read_text().splitlines() if '[outside_load]' in l][0]


def test_full_check_never_forces_and_runs_at_the_first_free_watch_with_its_waits(tmp_path, monkeypatch):
    """11-13 PM 10:21: the 10:19 run was forced beside tests and a deploy (84.8%); an overlap now only defers it."""
    import json as _json
    ops_auto, board = _board(tmp_path, monkeypatch)
    monkeypatch.setattr(ops_auto, 'FULL_CHECK_STATE', tmp_path / 'fc.json')
    reasons = ['tests_or_deploy_running'] * 4 + [None, None]
    monkeypatch.setattr(ops_auto, 'busy', lambda: reasons.pop(0))
    launched = []
    run = lambda t, window=False: ops_auto.full_check(clock=lambda: t, launch=lambda *a, **k: launched.append((a, k)),
                                                      free=True, window=window)
    for t in (10_000, 10_600, 11_200, 11_800):                       # past the old two-deferral limit: still waits
        assert run(t) == 'deferred'
    assert not launched
    assert run(12_400, window='hourly measurement') == 'deferred' and not launched   # :55-:10 also waits
    assert run(13_000) == 'started'
    command, env = launched[0][0][0], launched[0][1]['env']
    assert 'scripts.heavy_slot' in command and command[:3] != ['nice', '-n', '10']  # always inside the heavy slot
    context = _json.loads(env['AGENTCON_RUN_CONTEXT'])
    assert context['deferred_before'] == 5 and len(context['overlaps']) == 5 and 'load_1' in context
    assert context['overlaps'][0].endswith('tests_or_deploy_running') and '(:55~:10)' in context['overlaps'][-1]
    assert '빈 시간에 실행 시작, 5번 미룬 뒤' in [l for l in board.read_text().splitlines() if '[full_check_deferred]' in l][0]
    assert _json.loads((tmp_path / 'fc.json').read_text())['deferred'] == 0     # the count starts again


def test_full_check_reads_the_measurement_window_from_heavy_slot(tmp_path, monkeypatch):
    from datetime import datetime as _dt
    ops_auto, _ = _board(tmp_path, monkeypatch)
    monkeypatch.setattr(ops_auto, 'FULL_CHECK_STATE', tmp_path / 'fc.json')
    monkeypatch.setattr(ops_auto, 'busy', lambda: None)
    launched = []
    at = lambda h, m: _dt(2026, 11, 13, h, m).timestamp()
    run = lambda t: ops_auto.full_check(clock=lambda: t, launch=lambda *a, **k: launched.append(a), free=True)
    assert run(at(10, 58)) == 'deferred' and run(at(11, 5)) == 'deferred' and not launched
    assert run(at(11, 12)) == 'started' and len(launched) == 1


def test_user_slo_runs_once_in_every_clock_hour(tmp_path, monkeypatch):
    """11-12 PM: 'last run + 3600' drifted by up to ten minutes a run and left 09:22~10:23 without a record."""
    import subprocess, types
    ops_auto, board = _board(tmp_path, monkeypatch)
    monkeypatch.setattr(ops_auto, 'SLO_STATE', tmp_path / 'slo.json')
    calls = []
    record = '{"pages": {"ok": true, "samples": [{"path": "/", "s": 0.5}]}, "breaches": {}}'
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: calls.append(1) or types.SimpleNamespace(stdout=record))
    ops_auto.user_slo(); ops_auto.user_slo()
    assert len(calls) == 1                                         # same hour: once
    state = __import__('json').loads((tmp_path / 'slo.json').read_text())
    state['hour'] = '2000-01-01 00'                                # an earlier hour
    (tmp_path / 'slo.json').write_text(__import__('json').dumps(state))
    ops_auto.user_slo()
    assert len(calls) == 2


def test_site_retry_moves_single_connection_stall_to_path(monkeypatch, tmp_path):
    """11-12 16:12: one 8.5 s llms.txt timeout from this Mac's line is recorded, not alerted, when a retry answers."""
    calls = {}

    def fake_fetch(url):
        calls[url] = calls.get(url, 0) + 1
        if url.endswith('/llms.txt') and calls[url] == 1:
            return 'TimeoutError', 8.5
        if url.endswith('weather'):
            return 'TimeoutError', 8.4  # fails twice: a real anomaly
        return 200, 0.8
    monkeypatch.setattr(ops_watch, 'fetch', fake_fetch)
    monkeypatch.setattr(ops_watch, 'NET_PATH', tmp_path / 'none.jsonl')
    bad, path = ops_watch.check_site(retry_wait=0)
    assert [b['url'].rsplit('/', 1)[-1] for b in bad] == ['explore?q=weather']
    assert bad[0]['retry']['status'] == 'TimeoutError'
    assert len(path) == 1 and path[0]['status'] == 'TimeoutError' and path[0]['retry'] == {'status': 200, 'seconds': 0.8}
    assert calls['https://agentconcierge.biz/'] == 1


def test_site_security_answers_are_not_retried(monkeypatch):
    calls = []
    monkeypatch.setattr(ops_watch, 'fetch', lambda url: (calls.append(url), (429, 0.9))[1])
    bad, path = ops_watch.check_site(retry_wait=0)
    assert len(bad) == 3 and not path and len(calls) == 3


def test_nearest_path_record(tmp_path, monkeypatch):
    import json
    from datetime import datetime
    f = tmp_path / 'p.jsonl'
    f.write_text(json.dumps({'at': '2026-11-12 16:12:34', 'edge': {'status': 200}, 'gateway_ms': 0.6}) + '\n'
                 + json.dumps({'at': '2026-11-12 16:14:38', 'edge': {'status': 0}}) + '\n')
    monkeypatch.setattr(ops_watch, 'NET_PATH', f)
    at = datetime(2026, 11, 12, 16, 12, 10).timestamp()
    assert ops_watch.nearest_path_record(at)['at'] == '2026-11-12 16:12:34'
    assert ops_watch.nearest_path_record(at + 3600) is None


def test_busy_ignores_the_sleeping_reclaim_of_the_old_slot(monkeypatch):
    """11-13: the 30-minute reclaim-standby waiter after a deploy is not a deploy in progress."""
    from types import SimpleNamespace
    from scripts import ops_auto
    monkeypatch.setattr(ops_auto.ops_watch, 'check_memory', lambda: 50)
    ps = ['python -m scripts.service_deploy --root /x reclaim-standby --after 1800']
    monkeypatch.setattr(ops_auto.subprocess, 'run', lambda *a, **k: SimpleNamespace(stdout='\n'.join(ps)))
    assert ops_auto.busy() is None
    ps.append('python -m scripts.service_deploy deploy frontend r1 --lock-owner x')
    assert ops_auto.busy() == 'tests_or_deploy_running'
