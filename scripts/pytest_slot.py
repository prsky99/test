"""Run named test files safely on the production Mac (PM 11-12).

    .venv/bin/python -m scripts.pytest_slot [--team 운영·SRE] [--minutes 15] tests/test_a.py tests/test_b.py::test_x ...

11-12: a zsh glob that matched nothing left the file list empty, and `pytest -q` with no arguments ran the whole
suite for ten minutes in the daytime outside heavy_slot. This wrapper never runs pytest without named tests:
- no argument, or a path that does not exist: nothing runs (exit 2)
- more than SMALL files, or a directory: the run goes through scripts.heavy_slot (one heavy job at a time)
- always at nice 10 with .venv-tests
- nothing runs inside a window reserved for copy rehearsals or the public measurement on the status board, nor in the
  hourly measurement window (:55-:10, 08:00-24:00) (exit 75)
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
    run = ['nice', '-n', '10', str(Path(root) / '.venv-tests/bin/python'), '-m', 'pytest', '-q', '-p', 'no:cacheprovider', *tests]
    wide = len(tests) > SMALL or any((Path(root) / t.split('::', 1)[0]).is_dir() for t in tests)
    if not wide:
        return run
    return [str(Path(root) / '.venv/bin/python'), '-m', 'scripts.heavy_slot', '--team', team,
            '--what', f'pytest {len(tests)} targets', '--minutes', str(minutes), '--', *run]


DAY_SMALL_RUNS = 2   # PM 11-15 16:26: small runs had no limit; five teams at once slowed explore in the afternoon
LOAD_MAX = 6.0       # 1-minute load on this 8-core Mac above which no new test starts in the day (08:00-24:00)


def day_busy(now=None, load=None, running=None):
    """Why a small run may not start now in the day, or None. Night (00:00-08:00) keeps the old rule."""
    import os
    from datetime import datetime
    now = now or datetime.now()
    if now.hour < 8:
        return None
    load = os.getloadavg()[0] if load is None else load
    if load >= LOAD_MAX:
        return f'load {load:.1f} >= {LOAD_MAX} in the day: the public site needs the CPU'
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
    reason = reserved() or measurement_window() or (None if cmd[0] != 'nice' else day_busy())
    if reason:
        print(f'pytest_slot: refused ({reason}); nothing runs, try again later', file=sys.stderr)
        return BUSY
    from scripts.pytest_env import clean_environment
    return subprocess.run(cmd, cwd=ROOT, env=clean_environment()).returncode   # R03: no production pointers


if __name__ == '__main__':
    raise SystemExit(main())
