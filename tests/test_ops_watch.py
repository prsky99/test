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
