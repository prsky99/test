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
