"""Run named test files safely on the production Mac (PM 11-12).

    .venv/bin/python -m scripts.pytest_slot [--team 운영·SRE] [--minutes 15] tests/test_a.py tests/test_b.py::test_x ...

11-12: a zsh glob that matched nothing left the file list empty, and `pytest -q` with no arguments ran the whole
suite for ten minutes in the daytime outside heavy_slot. This wrapper never runs pytest without named tests:
- no argument, or a path that does not exist: nothing runs (exit 2)
- more than SMALL files, or a directory: the run goes through scripts.heavy_slot (one heavy job at a time)
- always at nice 15 with .venv-tests (PM 11-16; was 10)
- nothing runs inside a window reserved for copy rehearsals or the public measurement on the status board, nor in the
  hourly measurement window (:55-:10) (exit 75); the board is the main checkout's, also from a worktree or a copy,
  and an unreadable board refuses (PM 11-17 05:18)
- the same tests started REPEAT_MAX (5) times within REPEAT_MINUTES (10) are refused the next time (exit 75): 11-17 a
  retry loop in a worktree had run one PostgreSQL test file again and again for 13 hours. A rerun a person checked
  sets PYTEST_SLOT_REPEAT_OK='<reason>', kept with the run in logs/ops/pytest-slot-runs.jsonl
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SMALL = 5


def command(tests, team='운영·SRE', minutes=15, root=ROOT):
    """The command to run TESTS, or raise SystemExit(2) when they cannot be run safely."""
    if not tests:
        raise SystemExit('pytest_slot: name the test files; an empty list would run the whole suite')
    missing = [t for t in tests if not (Path(root) / t.split('::', 1)[0]).exists()]
    if missing:
        raise SystemExit('pytest_slot: no such test file: ' + ', '.join(missing))
    run = ['nice', '-n', '15', str(Path(root) / '.venv-tests/bin/python'), '-m', 'pytest', '-q', '-p', 'no:cacheprovider', *tests]
    wide = len(tests) > SMALL or any((Path(root) / t.split('::', 1)[0]).is_dir() for t in tests)
    if not wide:
        return run
    return [str(Path(root) / '.venv/bin/python'), '-m', 'scripts.heavy_slot', '--team', team,
            '--what', f'pytest {len(tests)} targets', '--minutes', str(minutes), '--', *run]


REPEAT_MAX, REPEAT_MINUTES = 5, 10   # PM 11-17 06:3x: five starts in ten minutes, the sixth waits (a fix-and-rerun
# cycle runs three or four times in ten minutes; the 11-17 loop ran about ten)
REPEAT_OK = 'PYTEST_SLOT_REPEAT_OK'   # a rerun a person checked: the reason, kept in the run log


def repeat_log():
    from scripts.heavy_slot import MAIN
    return MAIN / 'logs/ops/pytest-slot-runs.jsonl'


def repeated(tests, now=None, log=None):
    """Why these tests may not start again now (started REPEAT_MAX times within REPEAT_MINUTES), or None."""
    import json
    import time
    now = time.time() if now is None else now
    key = ' '.join(sorted(tests))
    try:
        lines = Path(log or repeat_log()).read_text(encoding='utf-8').splitlines()[-500:]
    except OSError:
        return None
    recent = 0
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        recent += row.get('tests') == key and now - row.get('at', 0) < REPEAT_MINUTES * 60
    if recent >= REPEAT_MAX:
        return (f'the same tests started {recent} times in the last {REPEAT_MINUTES} minutes; no automatic retry loops. '
                f"For a rerun a person checked, set {REPEAT_OK}='<reason>'")
    return None


def note_start(tests, now=None, log=None, reason=None):
    """Append one line per started run (the time, the tests, where it runs and a repeat reason; nothing else)."""
    import fcntl
    import json
    import time
    path = Path(log or repeat_log())
    row = {'at': round(time.time() if now is None else now), 'tests': ' '.join(sorted(tests)), 'root': str(ROOT)}
    if reason:
        row['repeat_ok'] = reason[:200]
    try:
        with path.open('a', encoding='utf-8') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')
    except OSError:
        pass


DAY_SMALL_RUNS = 2   # PM 11-15 16:26: small runs had no limit; five teams at once slowed explore in the afternoon
LOAD_MAX = 9.0       # 1-minute load above which no new test starts in the day; 6.0 while heavy_slot.server_guard holds (PM 11-16)


def day_busy(now=None, load=None, running=None):
    """Why a small run may not start now in the day, or None. Night (00:00-08:00) keeps the old rule."""
    import os
    from datetime import datetime
    now = now or datetime.now()
    if now.hour < 8:
        return None
    injected = load is not None
    load = os.getloadavg()[0] if load is None else load
    from scripts.heavy_slot import load_limit
    limit = LOAD_MAX if injected else load_limit(now)
    if load >= limit:
        return f'load {load:.1f} >= {limit} in the day: the public site needs the CPU'
    running = small_runs() if running is None else running
    if running >= DAY_SMALL_RUNS:
        return f'{running} small test runs already running (day limit {DAY_SMALL_RUNS})'
    return None


def small_runs(root=ROOT):
    """pytest processes this wrapper started for this project (other projects and shells do not count)."""
    marker = str(Path(root) / '.venv-tests/bin/python') + ' -m pytest -q -p no:cacheprovider'
    out = subprocess.run(['ps', '-axww', '-o', 'args='], capture_output=True, text=True).stdout
    return sum(1 for line in out.splitlines() if marker in line)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--team', default='운영·SRE')
    parser.add_argument('--minutes', type=int, default=15)
    parser.add_argument('tests', nargs='*')
    args = parser.parse_args(argv)
    try:
        cmd = command(args.tests, args.team, args.minutes)
    except SystemExit as stop:
        print(stop, file=sys.stderr)
        return 2
    from scripts.heavy_slot import reserved, measurement_window, BUSY
    # PM 11-14 03:4x: small runs wait too while a copy rehearsal has the night window; PM 11-15 12:24: and in the
    # hourly measurement window (:55-:10 in the day) and a window kept for the public full check
    import os
    repeat_ok = os.environ.get(REPEAT_OK, '').strip()
    reason = (reserved() or measurement_window() or (None if repeat_ok else repeated(args.tests))
              or (None if cmd[0] != 'nice' else day_busy()))
    if reason:
        print(f'pytest_slot: refused ({reason}); nothing runs, try again later', file=sys.stderr)
        return BUSY
    note_start(args.tests, reason=repeat_ok or None)
    from scripts.pytest_env import clean_environment
    return subprocess.run(cmd, cwd=ROOT, env=clean_environment()).returncode   # R03: no production pointers


if __name__ == '__main__':
    raise SystemExit(main())
