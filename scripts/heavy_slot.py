#!/usr/bin/env python3
"""Run a heavy job only when the status board's heavy-work section has a free slot (11-11 PM decision).

    .venv/bin/python -m scripts.heavy_slot --team 운영·SRE --what "full pytest" --minutes 20 -- \
        .venv-tests/bin/python -m pytest -q

This Mac is also the production server. On 11-11 two broad test runs and a browser test overlapped
with a public measurement (load 6-8, Chat 3-10 s). The wrapper:
- refuses when two live lines are already in '## 무거운 작업' (exit 75, nothing runs);
- otherwise appends its own line (with its own pid and a slot token), runs the command under
  nice -n 10, and removes its line when the command ends, fails or the wrapper is interrupted;
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
SLOTS = 2
BUSY = 75          # EX_TEMPFAIL: try again later
STALE = ' [오래됨: pid 없음]'
_PID = re.compile(r'\bpid=(\d+)')


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


def entries(lines, is_alive=alive):
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
        live = STALE not in line and (pid is None or is_alive(int(pid.group(1))))
        found.append((i, line, live))
    return found


def claim(board, team, what, minutes, pid, token, now=None, is_alive=alive):
    """Add our line when a slot is free. Returns (claimed, live lines of others)."""
    board = Path(board)
    lines = board.read_text(encoding='utf-8').split('\n')
    span = _section(lines)
    if span is None:
        raise SystemExit(f'heavy_slot: the status board has no "{SECTION}" section')
    found = entries(lines, is_alive)
    for i, line, live in found:
        if not live and STALE not in line:
            lines[i] = line + STALE
    live = [line for _, line, ok in found if ok]
    if len(live) >= SLOTS:
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


def run(command, team, what, minutes, board=None, lock=None):
    board, token = Path(board or BOARD), secrets.token_hex(4)
    with board_lock(lock):
        ok, live = claim(board, team, what, minutes, os.getpid(), token)
    if not ok:
        print('heavy_slot: both heavy-work slots are in use; try again later:', file=sys.stderr)
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
        child = subprocess.Popen(command, preexec_fn=lambda: os.nice(10))
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
