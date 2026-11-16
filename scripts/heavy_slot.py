#!/usr/bin/env python3
"""Run a heavy job only when the status board's heavy-work section has a free slot (11-11 PM decision).

    .venv/bin/python -m scripts.heavy_slot --team 운영·SRE --what "full pytest" --minutes 20 -- \
        .venv-tests/bin/python -m pytest -q

This Mac is also the production server. On 11-11 two broad test runs and a browser test overlapped
with a public measurement (load 6-8, Chat 3-10 s). The wrapper:
- refuses when the hour's slots are taken in '## 무거운 작업' (one 08:00-24:00, two 00:00-08:00;
  exit 75, nothing runs);
- 08:00-24:00 refuses copy restores and rehearsals (restore / rehearsal in the name or command) and any estimate
  over 30 minutes (exit 77, nothing runs; PM decision 11-12);
- 08:00-24:00 starts nothing new from :55 to :10, the hourly public measurement's window (exit 75; PM 11-13);
- otherwise appends its own line (with its own pid and a slot token), runs the command under
  nice -n 15 (PM 11-16; was 10), and removes its line when the command ends, fails or the wrapper is interrupted;
- marks a line whose pid is gone as stale and does not count it.
Board edits hold an exclusive file lock so two sessions cannot interleave their changes.
"""
import argparse
import fcntl
import os
import re
import secrets
import signal
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / 'logs/ops/status-board.md'
LOCK = ROOT / 'logs/ops/.heavy-slot.lock'
SECTION = '## 무거운 작업'
SLOTS = 2          # 00:00-08:00 KST
DAY_SLOTS = 1      # 08:00-24:00 KST: load 10 lengthened user requests directly (11-11 PM decision)


def slots(now=None):
    hour = (now or datetime.now()).hour
    return SLOTS if hour < 8 else DAY_SLOTS
BUSY = 75          # EX_TEMPFAIL: try again later
NIGHT_ONLY = 77    # EX_NOPERM: this kind of work runs only 00:00-08:00 (PM decision 11-12)
DAY_MAX_MINUTES = 30
EVENING_FROM, EVENING_MAX_MINUTES = 22, 60   # PM 11-15 16:59: the night full pytest starts at 22:40 (50 minutes)
# 11-12 12:23 PM decision: copy restores and rehearsals only at night; in the day only gates of 30 minutes or less
# (a full copy restore beside the production database at 10:44 left 92 public checks failing at load 4.9).
NIGHT_ONLY_WORDS = re.compile(r'restore|rehears|pg_restore|db_change_rehearsal|복원|리허설', re.IGNORECASE)


def night_only(what, command, minutes, now=None):
    """The reason this run may not start now, or None. Night (00:00-08:00) allows everything."""
    if (now or datetime.now()).hour < 8:
        return None
    if NIGHT_ONLY_WORDS.search(' '.join([what, *command])):
        return 'copy restores and rehearsals run only 00:00-08:00'
    limit = EVENING_MAX_MINUTES if (now or datetime.now()).hour >= EVENING_FROM else DAY_MAX_MINUTES
    if minutes > limit:
        return f'daytime work must be {limit} minutes or less (estimate {minutes})'
    return None


# 11-13 PM 10:21: the 09:00 user_slo ran at load 13.46 (explore 6/6 over) because a gate and a deploy started
# just before it. In the day no new heavy work starts from :55 to :10 (the hourly public measurement's window);
# work already running is left alone. Exit 75, as for a full slot: the caller tries again later.
QUIET_FROM, QUIET_UNTIL = 55, 10


def measurement_window(now=None):
    """The reason a new run may not start now because of the hourly measurement, or None."""
    now = now or datetime.now()
    if now.hour < 8:
        return None
    if now.minute >= QUIET_FROM or now.minute < QUIET_UNTIL:
        return f'08:00-24:00 no new heavy work starts from :{QUIET_FROM} to :{QUIET_UNTIL:02d} (hourly public measurement)'
    return None


# PM 11-14 03:4x: a night window may be kept for copy rehearsals only. Lines under RESERVED on the board,
# '- MM-DD HH:MM~HH:MM <note>', make every other heavy run (and pytest_slot's small runs) wait (exit 75).
RESERVED = '## 리허설 전용 시간'
# PM 11-15 12:24: the public full check was put off seven times in one busy day (tests and gates all day), so it never
# ran. Lines under MEASURE ('- MM-DD HH:MM~HH:MM <note>', written by ops_auto.full_check after three deferrals) keep a
# window for the public measurement: only it may start then; other heavy runs and pytest_slot's small runs wait.
MEASURE = '## 측정 전용 시간'
MEASURE_WORDS = re.compile(r'public_full_check|user_slo')
_RESERVED_LINE = re.compile(r'^- (\d{2})-(\d{2}) (\d{1,2}):(\d{2})~(\d{1,2}):(\d{2})')


def reserved(now=None, board=None, what=''):
    """The reason work described by WHAT may not start now (a reserved window on the board), or None. A copy-rehearsal
    window lets rehearsals through; a measurement window lets the public measurement through."""
    now = now or datetime.now()
    try:
        lines = Path(board or BOARD).read_text(encoding='utf-8').split('\n')
    except OSError:
        return None
    section = None
    for line in lines:
        if line.startswith('## '):
            section = RESERVED if line.startswith(RESERVED) else MEASURE if line.startswith(MEASURE) else None
            continue
        match = _RESERVED_LINE.match(line) if section else None
        if not match:
            continue
        month, day, h1, m1, h2, m2 = map(int, match.groups())
        try:
            start = now.replace(month=month, day=day, hour=h1, minute=m1, second=0, microsecond=0)
            end = now.replace(month=month, day=day, hour=h2, minute=m2, second=0, microsecond=0)
        except ValueError:
            continue
        if not start <= now < end:
            continue
        if section == RESERVED and not NIGHT_ONLY_WORDS.search(what):
            return f'reserved for copy rehearsals: {line[2:].strip()}'
        if section == MEASURE and not MEASURE_WORDS.search(what):
            return f'reserved for the public measurement: {line[2:].strip()}'
    return None


STALE = ' [오래됨: pid 없음]'
TIMED_OUT = ' [오래됨: 시간 초과]'
NO_ESTIMATE_MINUTES = 180   # a line without an estimate counts for at most three hours
_PID = re.compile(r'\bpid=(\d+)')
_START = re.compile(r'\b(\d{2})-(\d{2}) (\d{1,2}):(\d{2})\b')
_ESTIMATE = re.compile(r'예상[^0-9()]{0,8}(\d+)\s*분')


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@contextmanager
def board_lock(lock=None):
    path = Path(lock or LOCK)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _section(lines):
    """(start, end) line indexes of the entries under SECTION; None when the section is missing."""
    for i, line in enumerate(lines):
        if line.startswith(SECTION):
            j = i + 1
            while j < len(lines) and not lines[j].startswith('## '):
                j += 1
            return i + 1, j
    return None


def overdue(line, now=None):
    """True when the line started more than twice its estimate ago (three hours without one, 11-11).

    Lines written by hand carry a session pid, which stays alive after the job ends; the time limit
    keeps a forgotten line from holding a slot all night."""
    start = _START.search(line)
    if not start:
        return False
    now = now or datetime.now()
    month, day, hour, minute = map(int, start.groups())
    try:
        began = now.replace(month=month, day=day, hour=hour, minute=minute, second=0, microsecond=0)
    except ValueError:
        return False
    if began > now:
        began = began.replace(year=now.year - 1)
    estimate = _ESTIMATE.search(line)
    limit = 2 * int(estimate.group(1)) if estimate else NO_ESTIMATE_MINUTES
    return (now - began).total_seconds() > limit * 60


def entries(lines, is_alive=alive, now=None):
    """[(index, line, live)] for each '- ' entry in the section."""
    span = _section(lines)
    if span is None:
        return []
    found = []
    for i in range(*span):
        line = lines[i]
        if not line.startswith('- '):
            continue
        pid = _PID.search(line)
        live = ('[오래됨' not in line and (pid is None or is_alive(int(pid.group(1))))
                and not overdue(line, now))
        found.append((i, line, live))
    return found


def claim(board, team, what, minutes, pid, token, now=None, is_alive=alive):
    """Add our line when a slot is free. Returns (claimed, live lines of others)."""
    board = Path(board)
    lines = board.read_text(encoding='utf-8').split('\n')
    span = _section(lines)
    if span is None:
        raise SystemExit(f'heavy_slot: the status board has no "{SECTION}" section')
    found = entries(lines, is_alive, now)
    for i, line, live in found:
        if not live and '[오래됨' not in line:
            # 11-16 PM source review: this used to rebind `pid`, so our own new line read pid=<re.Match ...>
            # whenever an old line was marked, and the next claim treated it as a dead process (limit lifted).
            old_pid = _PID.search(line)
            lines[i] = line + (STALE if old_pid and not is_alive(int(old_pid.group(1))) else TIMED_OUT)
    live = [line for _, line, ok in found if ok]
    if len(live) >= slots(now):
        board.write_text('\n'.join(lines), encoding='utf-8')
        return False, live
    stamp = (now or datetime.now()).strftime('%m-%d %H:%M')
    entry = f'- {team} {stamp} pid={pid} {what} (예상 {minutes}분) [slot {token}]'
    last = max([i for i, _, _ in found], default=span[0] - 1)
    insert = last + 1 if found else span[0]
    while not found and insert < span[1] and lines[insert].strip() and not lines[insert].startswith('- '):
        insert += 1   # keep the section's explanation lines above the entries
    lines.insert(insert, entry)
    board.write_text('\n'.join(lines), encoding='utf-8')
    return True, live


def release(board, token):
    board = Path(board)
    lines = board.read_text(encoding='utf-8').split('\n')
    kept = [line for line in lines if f'[slot {token}]' not in line]
    if len(kept) != len(lines):
        board.write_text('\n'.join(kept), encoding='utf-8')
        return True
    return False


LOAD_MAX = 9.0   # PM 11-16 14:4x (user: "apply it as fast as possible"): most of the 6+ load was the screen (WindowServer,
                 # remote desktop, FSEvents, the Claude app), not the services, so every team waited; tests now run at
                 # nice 15 and start below 9.0. Before: 6.0 (PM 11-15 16:38).
LOAD_MAX_GUARDED = 6.0   # the old limit, back while the server-side time of the last public measurement is up
GUARD_RATIO = 1.3        # latest median server_ms of explore + recommend over the median of the day before it
SLO_LOG = ROOT / 'logs/ops/user-slo.jsonl'
GUARD_NOTE = ROOT / 'logs/ops/test-load-guard.json'
TEST_NICE = 15


def _server_median(entry):
    values = sorted(x['server_ms'] for kind in ('explore', 'recommend')
                    for x in (entry.get(kind) or {}).get('samples') or []
                    if isinstance(x.get('server_ms'), (int, float)))
    if not values:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def server_guard(path=SLO_LOG, now=None, window=24, ratio=GUARD_RATIO):
    """PM 11-16 14:4x safety for the raised limit: when the last hourly public measurement (at most 90 minutes old)
    shows the server-side time of explore + recommend more than 30% above the median of the measurements before it,
    return why (the limit goes back to 6.0); else None. Server-side time only, so the LAX edge delay does not count.
    Medians under 50 ms are left out (a blocked or failed hour, e.g. 12:08 on 11-16)."""
    try:
        lines = Path(path).read_text(encoding='utf-8').splitlines()[-(window + 1):]
        import json
        entries = [json.loads(line) for line in lines if line.strip()]
    except (OSError, ValueError):
        return None
    if len(entries) < 4:
        return None
    latest = entries[-1]
    try:
        age = ((now or datetime.now()) - datetime.strptime(latest['at'], '%Y-%m-%d %H:%M')).total_seconds()
    except (KeyError, ValueError, TypeError):
        return None
    current = _server_median(latest)
    history = sorted(m for m in (_server_median(e) for e in entries[:-1]) if m is not None and m >= 50)
    if age > 5400 or current is None or current < 50 or len(history) < 3:
        return None
    base = history[len(history) // 2]
    if current > base * ratio:
        return (f'server-side time {current:.0f} ms at {latest["at"]} is over {ratio:.1f}x the median {base:.0f} ms '
                f'of the {len(history)} measurements before it')
    return None


REAL_MIN = 10   # real (non-QA) requests of a kind in the last 20 minutes before that kind is judged on them


def real_guard(now=None, ratio=GUARD_RATIO, read=None):
    """PM 11-16: the same 1.3x rule on real public requests (logs/ops/request-timing, written by the frontend from
    r11): a kind with at least REAL_MIN requests in the last 20 minutes whose median server_ms is over RATIO times its
    median of the 24 hours before. None when there are too few lines (then the hourly measurement decides)."""
    try:
        if read is None:
            from scripts import request_timing_report as read
        when = (now or datetime.now()).timestamp()
        current, base = read.recent(when), read.baseline(when)
    except Exception:   # noqa: BLE001 - a missing or broken log never blocks tests
        return None
    for kind, (median, count) in sorted(current.items()):
        if count >= REAL_MIN and base.get(kind) and median > base[kind] * ratio:
            return (f'real {kind} requests: median server time {median:.0f} ms over the last 20 minutes ({count} '
                    f'requests) is over {ratio:.1f}x the median {base[kind]:.0f} ms of the day before')
    return None


def load_limit(now=None, guard=None):
    """The day load limit for starting tests: 9.0, or 6.0 while server_guard() holds (noted once per measurement)."""
    reason = (real_guard(now=now) or server_guard(now=now)) if guard is None else guard
    if not reason:
        return LOAD_MAX
    if guard is None and not os.environ.get('PYTEST_CURRENT_TEST'):
        _note_guard(reason)
    return LOAD_MAX_GUARDED


def _note_guard(reason):
    """Tell the PM once per measurement through the status board (the hand-off section)."""
    import json
    if ' at ' in reason:
        stamp = reason.split(' at ', 1)[1][:16]          # the hourly measurement's time
    else:                                                # real requests: once per 20-minute window
        moment = datetime.now()
        stamp = moment.strftime('%Y-%m-%d %H:') + '%02d' % (moment.minute // 20 * 20)
    try:
        if json.loads(GUARD_NOTE.read_text()).get('at') == stamp:
            return
    except (OSError, ValueError, AttributeError):
        pass
    try:
        GUARD_NOTE.write_text(json.dumps({'at': stamp, 'reason': reason}))
        line = (f'- **[heavy_slot 자동 {datetime.now().strftime("%m-%d %H:%M")}] 시험 부하 상한을 6.0으로 되돌림'
                f'(PM 11-16 안전장치)**: {reason}. 다음 정각 측정이 정상이면 9.0으로 돌아감 | 알림 |\n')
        with board_lock():
            text = BOARD.read_text(encoding='utf-8')
            key = '## 넘기는 일\n'
            if text.count(key) == 1:
                BOARD.write_text(text.replace(key, key + line, 1), encoding='utf-8')
    except OSError:
        pass


def day_load(now=None, load=None, what=''):
    """Why heavy work may not start now because this Mac is busy (08:00-24:00 only), or None. The public measurement
    itself is never held back. Inside a test the real load is not read (only an injected one)."""
    now = now or datetime.now()
    if now.hour < 8 or MEASURE_WORDS.search(what or ''):
        return None
    injected = load is not None
    if load is None:
        if os.environ.get('PYTEST_CURRENT_TEST'):
            return None
        load = os.getloadavg()[0]
    limit = LOAD_MAX if injected else load_limit(now)
    return f'load {load:.1f} >= {limit} in the day: the public site needs the CPU' if load >= limit else None


def run(command, team, what, minutes, board=None, lock=None, now=None, load=None):
    reason = night_only(what, command, minutes, now)
    if reason:
        print(f'heavy_slot: refused ({reason}); nothing runs', file=sys.stderr)
        return NIGHT_ONLY
    reason = (measurement_window(now) or reserved(now, board, ' '.join([what, *command]))
              or day_load(now, load, ' '.join([what, *command])))
    if reason:
        print(f'heavy_slot: refused ({reason}); nothing runs, try again later', file=sys.stderr)
        return BUSY
    board, token = Path(board or BOARD), secrets.token_hex(4)
    with board_lock(lock):
        ok, live = claim(board, team, what, minutes, os.getpid(), token)
    if not ok:
        print(f'heavy_slot: all {slots()} heavy-work slot(s) for this hour are in use; try again later:', file=sys.stderr)
        for line in live:
            print('  ' + line, file=sys.stderr)
        return BUSY
    child = None

    def stop(signum, _frame):
        if child and child.poll() is None:
            child.send_signal(signum)
        raise KeyboardInterrupt

    previous = {s: signal.signal(s, stop) for s in (signal.SIGTERM, signal.SIGHUP)}
    try:
        if str(ROOT) not in sys.path:   # ops_auto imports this module with only scripts/ on the path (11-15: the
            sys.path.insert(0, str(ROOT))   # afternoon real_task_score died here with No module named 'scripts')
        from scripts.pytest_env import clean_environment, is_test_command
        env = clean_environment() if is_test_command(command) else None   # R03: tests never get production pointers
        child = subprocess.Popen(command, preexec_fn=lambda: os.nice(TEST_NICE), env=env)
        return child.wait()
    except KeyboardInterrupt:
        if child and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                child.kill()
        return 130
    finally:
        for s, handler in previous.items():
            signal.signal(s, handler)
        with board_lock(lock):
            release(board, token)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--team', required=True)
    parser.add_argument('--what', required=True)
    parser.add_argument('--minutes', type=int, required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('give the command after --')
    return run(command, args.team, args.what, args.minutes)


if __name__ == '__main__':
    raise SystemExit(main())
