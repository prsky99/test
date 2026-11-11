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
    record = '{"pages": {"ok": true, "samples": 3}, "connect": {"ok": false, "samples": 0}, "breaches": {}}'
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
    run = lambda t, free: ops_auto.full_check(clock=lambda: t, launch=lambda *a, **k: launched.append(a), free=free)
    assert run(10_000, False) == 'deferred' and not launched
    assert '자동 점검 [full_check_deferred]' in board.read_text()
    assert run(10_600, False) == 'deferred' and board.read_text().count('[full_check_deferred]') == 1
    assert run(11_200, True) == 'started' and 'scripts.heavy_slot' in launched[0][0]
    assert '해결(자동' in board.read_text()
    assert run(11_200 + 3600, True) is None                  # not yet two hours
    assert run(11_200 + 7300, True) == 'started' and len(launched) == 2
