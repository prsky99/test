"""Heavy jobs take a status-board slot first (11-11: overlapping test runs slowed the public site)."""
import os
import sys

from datetime import datetime

from scripts import heavy_slot as hs

NOW = datetime.now().strftime('%m-%d %H:%M')   # lines that started just now are within their estimate

BOARD = """# 현황판
## 무거운 작업 (최대 2개)
설명 한 줄.
{rows}
## 배포 잠금
(비어 있음)
"""


def _board(tmp_path, rows=''):
    path = tmp_path / 'status-board.md'
    path.write_text(BOARD.format(rows=rows), encoding='utf-8')
    return path


def test_a_free_slot_runs_the_command_under_nice_and_removes_its_line(tmp_path):
    board = _board(tmp_path, '- 성장·유통 %s pid=%d AD Coin tests (예상 10분)' % (NOW, os.getpid()))
    out = tmp_path / 'nice.txt'
    code = hs.run([sys.executable, '-c', f'import os; open({str(out)!r}, "w").write(str(os.nice(0)))'],
                  '운영·SRE', 'probe', 1, board=board, lock=tmp_path / 'lock')
    assert code == 0 and int(out.read_text()) >= 10
    text = board.read_text(encoding='utf-8')
    assert '[slot ' not in text and f'성장·유통 {NOW}' in text and '## 배포 잠금' in text


def test_two_live_lines_refuse_without_running(tmp_path, capsys):
    me = os.getpid()
    board = _board(tmp_path, f'- A {NOW} pid={me} one (예상 5분)\n- B {NOW} pid={me} two (예상 5분)')
    marker = tmp_path / 'ran'
    code = hs.run([sys.executable, '-c', f'open({str(marker)!r}, "w")'], '운영·SRE', 'x', 1, board=board, lock=tmp_path / 'lock')
    assert code == hs.BUSY and not marker.exists() and 'both heavy-work slots' in capsys.readouterr().err


def test_a_line_whose_pid_is_gone_is_marked_stale_and_not_counted(tmp_path):
    me = os.getpid()
    board = _board(tmp_path, f'- A {NOW} pid={me} one (예상 5분)\n- B {NOW} pid=999999 gone (예상 5분)')
    ok, live = hs.claim(board, '운영·SRE', 'x', 1, me, 'tok1', is_alive=lambda pid: pid == me)
    text = board.read_text(encoding='utf-8')
    assert ok and len(live) == 1 and 'gone (예상 5분)' + hs.STALE in text and '[slot tok1]' in text
    assert hs.release(board, 'tok1') and '[slot tok1]' not in board.read_text(encoding='utf-8')


def test_the_line_goes_in_the_section_below_its_explanation(tmp_path):
    board = _board(tmp_path)
    ok, _ = hs.claim(board, '운영·SRE', 'x', 3, os.getpid(), 'tok2')
    lines = board.read_text(encoding='utf-8').split('\n')
    i = next(n for n, line in enumerate(lines) if '[slot tok2]' in line)
    assert ok and lines[i - 1] == '설명 한 줄.' and lines.index('## 배포 잠금') > i


def test_a_failing_command_still_releases_the_slot(tmp_path):
    board = _board(tmp_path)
    assert hs.run([sys.executable, '-c', 'raise SystemExit(3)'], '운영·SRE', 'x', 1, board=board, lock=tmp_path / 'lock') == 3
    assert '[slot ' not in board.read_text(encoding='utf-8')


def test_a_hand_written_line_past_twice_its_estimate_times_out(tmp_path):
    """11-11: hand-written lines carry a live session pid; a forgotten one would block the 01:00 chain."""
    me = os.getpid()
    now = datetime(2026, 11, 11, 16, 0)
    rows = (f'- A 11-11 13:45 pid={me} tests (예상 60분)\n'          # 135 min > 2 x 60: timed out
            f'- B 11-11 15:30 pid={me} tests (예상 남은 60분)\n'      # 30 min: live
            f'- C 11-11 12:30 pid={me} no estimate')                 # 210 min > 180: timed out
    board = _board(tmp_path, rows)
    ok, live = hs.claim(board, '운영·SRE', 'x', 5, me, 'tok3', now=now, is_alive=lambda pid: True)
    text = board.read_text(encoding='utf-8')
    assert ok and live == [f'- B 11-11 15:30 pid={me} tests (예상 남은 60분)']
    assert text.count(hs.TIMED_OUT) == 2 and hs.STALE not in text
