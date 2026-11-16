"""Heavy jobs take a status-board slot first (11-11: overlapping test runs slowed the public site)."""
import os
import sys

import pytest

from datetime import datetime

from scripts import heavy_slot as hs

NOW = datetime.now().strftime('%m-%d %H:%M')   # lines that started just now are within their estimate
REAL_SLOTS = hs.slots
REAL_WINDOW = hs.measurement_window


@pytest.fixture(autouse=True)
def two_slots(monkeypatch):
    """Most tests are about counting lines, not the hour; the hour rules have their own tests."""
    monkeypatch.setattr(hs, 'slots', lambda now=None: 2)
    monkeypatch.setattr(hs, 'measurement_window', lambda now=None: None)

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
    assert code == 0 and int(out.read_text()) >= 15
    text = board.read_text(encoding='utf-8')
    assert '[slot ' not in text and f'성장·유통 {NOW}' in text and '## 배포 잠금' in text


def test_two_live_lines_refuse_without_running(tmp_path, capsys):
    me = os.getpid()
    board = _board(tmp_path, f'- A {NOW} pid={me} one (예상 5분)\n- B {NOW} pid={me} two (예상 5분)')
    marker = tmp_path / 'ran'
    code = hs.run([sys.executable, '-c', f'open({str(marker)!r}, "w")'], '운영·SRE', 'x', 1, board=board, lock=tmp_path / 'lock')
    assert code == hs.BUSY and not marker.exists() and 'heavy-work slot' in capsys.readouterr().err


def test_a_line_whose_pid_is_gone_is_marked_stale_and_not_counted(tmp_path):
    me = os.getpid()
    board = _board(tmp_path, f'- A {NOW} pid={me} one (예상 5분)\n- B {NOW} pid=999999 gone (예상 5분)')
    ok, live = hs.claim(board, '운영·SRE', 'x', 1, me, 'tok1', is_alive=lambda pid: pid == me)
    text = board.read_text(encoding='utf-8')
    assert ok and len(live) == 1 and 'gone (예상 5분)' + hs.STALE in text and '[slot tok1]' in text
    assert hs.release(board, 'tok1') and '[slot tok1]' not in board.read_text(encoding='utf-8')


def test_our_new_line_keeps_our_numeric_pid_when_an_old_line_was_marked(tmp_path):
    """11-16 PM source review: marking an old line rebound `pid`, so our line read pid=<re.Match ...> and the next
    claim counted it as a dead process (the limit was lifted)."""
    me = os.getpid()
    board = _board(tmp_path, f'- B {NOW} pid=999999 gone (예상 5분)')
    ok, _ = hs.claim(board, '운영·SRE', 'x', 1, me, 'tok9', is_alive=lambda pid: pid == me)
    ours = [line for line in board.read_text(encoding='utf-8').split('\n') if '[slot tok9]' in line]
    assert ok and len(ours) == 1 and f'pid={me} ' in ours[0] and 're.Match' not in ours[0]
    ok, live = hs.claim(board, 'other', 'y', 1, 4242, 'tok10', is_alive=lambda pid: pid == me)
    assert ok and live == ours   # our line still counts as live for the next claim


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


def test_one_slot_by_day_and_two_at_night(tmp_path, monkeypatch):
    """11-11 PM decision: 08:00-24:00 one heavy job, 00:00-08:00 two (the night database chain)."""
    monkeypatch.setattr(hs, 'slots', REAL_SLOTS)
    me = os.getpid()
    day, night = datetime(2026, 11, 11, 15, 0), datetime(2026, 11, 12, 1, 0)
    assert hs.slots(day) == 1 and hs.slots(night) == 2
    board = _board(tmp_path, f'- A 11-11 14:50 pid={me} one (예상 30분)')
    ok, _ = hs.claim(board, '운영·SRE', 'x', 5, me, 'd1', now=day, is_alive=lambda pid: True)
    assert not ok
    board = _board(tmp_path, f'- A 11-12 00:50 pid={me} one (예상 30분)')
    ok, _ = hs.claim(board, '운영·SRE', 'x', 5, me, 'n1', now=night, is_alive=lambda pid: True)
    assert ok


def test_daytime_refuses_restores_rehearsals_and_long_work_but_night_allows_them(tmp_path):
    """PM 11-12 12:23: copy restores and rehearsals only 00:00-08:00; in the day only work of 30 minutes or less."""
    from datetime import datetime
    from scripts import heavy_slot
    day, night = datetime(2026, 11, 12, 13, 0), datetime(2026, 11, 13, 2, 0)
    assert heavy_slot.night_only('사본 full 복원', ['bash', 'x.sh'], 20, now=day)
    assert heavy_slot.night_only('copy check', ['.venv/bin/python', '-m', 'scripts.db_change_rehearsal', 'run'], 20, now=day)
    assert heavy_slot.night_only('full pytest', ['pytest'], 45, now=day)              # over 30 minutes in the day
    assert heavy_slot.night_only('public_full_check', ['python', 'scripts/public_full_check.py'], 15, now=day) is None
    assert heavy_slot.night_only('사본 리허설', ['bash', 'x.sh'], 120, now=night) is None
    board = tmp_path / 'board.md'
    board.write_text('## 무거운 작업\n\n## 배포 잠금\n', encoding='utf-8')
    code = heavy_slot.run(['true'], '운영·SRE', 'pg_restore of the copy', 10, board=board, lock=tmp_path / 'l', now=day)
    assert code == heavy_slot.NIGHT_ONLY and '[slot' not in board.read_text(encoding='utf-8')   # nothing claimed or run


def test_daytime_starts_nothing_new_around_the_hourly_measurement(tmp_path, monkeypatch):
    """PM 11-13 10:21: the 09:00 user_slo ran at load 13.46 beside a gate and a deploy; :55-:10 stays free by day."""
    monkeypatch.setattr(hs, 'measurement_window', REAL_WINDOW)
    at = lambda h, m: datetime(2026, 11, 13, h, m)
    for h, m in ((8, 0), (9, 9), (9, 55), (23, 59), (12, 5)):
        assert hs.measurement_window(at(h, m)), (h, m)
    for h, m in ((9, 10), (9, 54), (13, 30), (0, 5), (3, 58), (7, 59)):   # night keeps every minute
        assert hs.measurement_window(at(h, m)) is None, (h, m)
    board = _board(tmp_path)
    marker = tmp_path / 'ran'
    code = hs.run([sys.executable, '-c', f'open({str(marker)!r}, "w")'], '운영·SRE', 'gate', 10,
                  board=board, lock=tmp_path / 'lock', now=at(9, 57))
    assert code == hs.BUSY and not marker.exists() and '[slot' not in board.read_text(encoding='utf-8')


def test_a_window_reserved_for_copy_rehearsals_refuses_other_heavy_work(tmp_path):
    """PM 11-14 03:4x: 11-15 00:30~03:30 is kept for copy rehearsals; other heavy runs wait (exit 75)."""
    board = tmp_path / 'status-board.md'
    board.write_text(BOARD.format(rows='').replace('## 배포 잠금', '## 리허설 전용 시간 (설명)\n'
                     '- 11-15 00:30~03:30 그래프 상한 → due_for_check (PM 03:4x)\n## 배포 잠금'), encoding='utf-8')
    inside, outside = datetime(2026, 11, 15, 1, 0), datetime(2026, 11, 15, 3, 30)
    assert 'reserved for copy rehearsals' in hs.reserved(inside, board)
    assert hs.reserved(outside, board) is None and hs.reserved(datetime(2026, 11, 14, 1, 0), board) is None
    out = tmp_path / 'ran.txt'
    probe = [sys.executable, '-c', f'open({str(out)!r}, "w").write("x")']
    assert hs.run(probe, '운영·SRE', 'full pytest', 5, board=board, lock=tmp_path / 'lock', now=inside) == hs.BUSY
    assert not out.exists()
    assert hs.run(probe, '운영·SRE', 'db_change_rehearsal due index', 5, board=board, lock=tmp_path / 'lock', now=inside) == 0
    assert out.exists()


def test_heavy_work_waits_for_load_in_the_day_but_not_the_measurement():
    """PM 11-15 16:38: gates, rescoring and report rebuilds wait too while this Mac is busy in the day."""
    from datetime import datetime
    from scripts import heavy_slot
    day, night = datetime(2026, 11, 16, 14, 20), datetime(2026, 11, 16, 3, 0)
    assert 'load 9.5' in heavy_slot.day_load(day, 9.5, 'substitute gate')
    assert heavy_slot.day_load(day, 7.0, 'substitute gate') is None   # PM 11-16: 9.0, was 6.0
    assert heavy_slot.day_load(day, 2.0, 'substitute gate') is None
    assert heavy_slot.day_load(night, 9.0, 'substitute gate') is None
    assert heavy_slot.day_load(day, 9.0, 'public_full_check') is None


def _slo(tmp_path, medians, at):
    import json
    rows = []
    for i, m in enumerate(medians):
        stamp = at if i == len(medians) - 1 else '2026-11-16 0%d:00' % (i % 10)
        rows.append(json.dumps({'at': stamp, 'explore': {'samples': [{'server_ms': m}]},
                                'recommend': {'samples': [{'server_ms': m}]}}))
    path = tmp_path / 'user-slo.jsonl'
    path.write_text('\n'.join(rows) + '\n')
    return path


def test_the_load_limit_goes_back_to_six_when_server_time_rises_30_percent(tmp_path):
    """PM 11-16 14:4x: the raised 9.0 limit holds only while the server-side time of the last hourly measurement stays
    within 30% of the measurements before it (server time only, so the LAX edge delay does not count)."""
    now = datetime(2026, 11, 16, 15, 20)
    calm = _slo(tmp_path, [800, 760, 820, 900, 2.0, 850], '2026-11-16 15:00')
    assert hs.server_guard(calm, now=now) is None and hs.load_limit(now, guard=None or '') == hs.LOAD_MAX
    up = _slo(tmp_path, [800, 760, 820, 900, 2.0, 1100], '2026-11-16 15:00')   # 1100 > 1.3 x 810
    reason = hs.server_guard(up, now=now)
    assert reason and '1100 ms' in reason and hs.load_limit(now, guard=reason) == hs.LOAD_MAX_GUARDED == 6.0
    assert hs.server_guard(up, now=datetime(2026, 11, 16, 17, 0)) is None   # a measurement older than 90 minutes


def test_real_requests_decide_the_guard_when_there_are_enough_of_them():
    """PM 11-16: per-request server time (logs/ops/request-timing) judges the raised limit when at least ten real
    requests of a kind came in the last 20 minutes; with fewer, the hourly measurement decides."""
    from types import SimpleNamespace
    now = datetime(2026, 11, 17, 15, 0)
    slow = SimpleNamespace(recent=lambda t: {'recommend': (2600.0, 12), 'explore': (500.0, 40)},
                           baseline=lambda t: {'recommend': 1700.0, 'explore': 700.0})
    reason = hs.real_guard(now=now, read=slow)
    assert reason and 'recommend' in reason and '2600 ms' in reason
    few = SimpleNamespace(recent=lambda t: {'recommend': (2600.0, 9)}, baseline=lambda t: {'recommend': 1700.0})
    assert hs.real_guard(now=now, read=few) is None
    calm = SimpleNamespace(recent=lambda t: {'recommend': (1800.0, 30)}, baseline=lambda t: {'recommend': 1700.0})
    assert hs.real_guard(now=now, read=calm) is None
    broken = SimpleNamespace(recent=lambda t: 1 / 0, baseline=lambda t: {})
    assert hs.real_guard(now=now, read=broken) is None
