"""Run named test files safely on the production Mac (PM 11-12).

    .venv/bin/python -m scripts.pytest_slot [--team 운영·SRE] [--minutes 15] tests/test_a.py tests/test_b.py::test_x ...

11-12: a zsh glob that matched nothing left the file list empty, and `pytest -q` with no arguments ran the whole
suite for ten minutes in the daytime outside heavy_slot. This wrapper never runs pytest without named tests:
- no argument, or a path that does not exist: nothing runs (exit 2)
- more than SMALL files, or a directory: the run goes through scripts.heavy_slot (one heavy job at a time)
- always at nice 10 with .venv-tests
- nothing runs inside a window reserved for copy rehearsals on the status board (exit 75)
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
    from scripts.heavy_slot import reserved, BUSY
    reason = reserved()
    if reason:   # PM 11-14 03:4x: small runs wait too while a copy rehearsal has the night window
        print(f'pytest_slot: refused ({reason}); nothing runs, try again later', file=sys.stderr)
        return BUSY
    return subprocess.run(cmd, cwd=ROOT).returncode


if __name__ == '__main__':
    raise SystemExit(main())
