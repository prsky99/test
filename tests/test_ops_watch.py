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
    ops_auto.watch()
    ops_auto.watch()  # same anomaly within 30 minutes: no second alert
    assert board.read_text().count('자동 점검') == 1
    assert (tmp_path / 'desk.txt').read_text().count('[운영 이상]') == 1
    assert '## PM 결정 대기' in board.read_text()
