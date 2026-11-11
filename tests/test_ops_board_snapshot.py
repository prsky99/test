"""The status board keeps a timestamped copy whenever it changes (11-11: a team overwrote other rows)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))


def test_board_copy_only_on_change_and_old_copies_expire(tmp_path, monkeypatch):
    import ops_auto
    board, history = tmp_path / 'status-board.md', tmp_path / 'history'
    import time
    now = [time.time()]
    board.write_text('v1')
    first = ops_auto.board_snapshot(board, history, clock=lambda: now[0])
    assert first.read_text() == 'v1'
    now[0] += 60
    assert ops_auto.board_snapshot(board, history, clock=lambda: now[0]) is None   # unchanged
    board.write_text('v2 (another team overwrote a row)')
    second = ops_auto.board_snapshot(board, history, clock=lambda: now[0])
    assert second != first and second.read_text().startswith('v2') and first.read_text() == 'v1'
    import os
    os.utime(first, (now[0] - 15 * 86400, now[0] - 15 * 86400))
    board.write_text('v3')
    ops_auto.board_snapshot(board, history, clock=lambda: now[0] + 1)
    assert not first.exists() and second.exists()
    assert ops_auto.board_snapshot(tmp_path / 'missing.md', history) is None


def test_edge_runtime_switches_reach_the_status_board_once(tmp_path, monkeypatch):
    import ops_auto
    board = tmp_path / 'status-board.md'
    board.write_text('# 현황판\n## 넘기는 일\n| 보낸 팀 | 받는 팀 | 내용 | 상태 |\n|---|---|---|---|\n## 공지\n', encoding='utf-8')
    monkeypatch.setattr(ops_auto, 'BOARD', board)
    monkeypatch.setattr(ops_auto, 'EDGE_STATE', tmp_path / 'edge-state.json')
    rows = [('103143', 'auto-block', 'edge-monitor', '10 Worker errors in 100 invocations over 15 minutes'),
            ('103150', 'auto-clear', 'edge-monitor', '0 Worker errors in 50 invocations over 15 minutes')]
    assert ops_auto.edge_transitions(rows) == ['auto-block', 'auto-clear']
    text = board.read_text(encoding='utf-8')
    assert '자동 차단' in text and '자동 해제' in text and text.index('## 넘기는 일') < text.index('자동 차단') < text.index('## 공지')
    assert ops_auto.edge_transitions([]) == [] and '"revision": 103150' in (tmp_path / 'edge-state.json').read_text()
