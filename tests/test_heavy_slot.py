"""Heavy jobs take a status-board slot first (11-11: overlapping test runs slowed the public site)."""
import os
import sys

from scripts import heavy_slot as hs

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
    board = _board(tmp_path, '- 성장·유통 11-11 13:45 pid=%d AD Coin tests (예상 10분)' % os.getpid())
    out = tmp_path / 'nice.txt'
    code = hs.run([sys.executable, '-c', f'import os; open({str(out)!r}, "w").write(str(os.nice(0)))'],
                  '운영·SRE', 'probe', 1, board=board, lock=tmp_path / 'lock')
    assert code == 0 and int(out.read_text()) >= 10
    text = board.read_text(encoding='utf-8')
    assert '[slot ' not in text and '성장·유통 11-11 13:45' in text and '## 배포 잠금' in text


def test_two_live_lines_refuse_without_running(tmp_path, capsys):
    me = os.getpid()
    board = _board(tmp_path, f'- A 11-11 13:45 pid={me} one (예상 5분)\n- B 11-11 13:46 pid={me} two (예상 5분)')
    marker = tmp_path / 'ran'
    code = hs.run([sys.executable, '-c', f'open({str(marker)!r}, "w")'], '운영·SRE', 'x', 1, board=board, lock=tmp_path / 'lock')
    assert code == hs.BUSY and not marker.exists() and 'both heavy-work slots' in capsys.readouterr().err


def test_a_line_whose_pid_is_gone_is_marked_stale_and_not_counted(tmp_path):
    me = os.getpid()
    board = _board(tmp_path, f'- A 11-11 13:45 pid={me} one (예상 5분)\n- B 11-11 09:00 pid=999999 gone (예상 5분)')
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
