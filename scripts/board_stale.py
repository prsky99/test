"""Hand-off lines still 'waiting' that nobody has touched for a day (PM 11-12).

    .venv/bin/python -m scripts.board_stale [--hours 24]

A line's age is the time since its exact text first appeared in the board snapshots ops_auto keeps
(logs/ops/status-board-history, one copy per change), so any edit to the line (a new status, a note) restarts it.
The board file's own mtime says nothing: the board changes many times an hour. Prints JSON grouped by the
receiving team.
"""
import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / 'logs/ops/status-board.md'
HISTORY = ROOT / 'logs/ops/status-board-history'
SNAPSHOT = re.compile(r'status-board-(\d{8})-(\d{6})\.md$')


def handoff_rows(text):
    section = text.split('## 넘기는 일', 1)[-1].split('\n## ', 1)[0] if '## 넘기는 일' in text else ''
    return [line.rstrip() for line in section.splitlines()
            if line.startswith('|') and not line.startswith('|---') and '| 보낸 팀 |' not in line]


def waiting(line):
    cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
    return len(cells) >= 4 and cells[-1].startswith('대기'), cells


def first_seen(history=HISTORY):
    """{exact line: epoch of the oldest snapshot that has it}, oldest snapshots first."""
    seen = {}
    for path in sorted(Path(history).glob('status-board-*.md')):
        found = SNAPSHOT.search(path.name)
        if not found:
            continue
        at = datetime.strptime(found.group(1) + found.group(2), '%Y%m%d%H%M%S').timestamp()
        try:
            rows = handoff_rows(path.read_text(encoding='utf-8'))
        except OSError:
            continue
        for line in rows:
            seen.setdefault(line, at)
    return seen


def stale(hours=24, board=BOARD, history=HISTORY, now=None):
    now = time.time() if now is None else now
    seen = first_seen(history)
    out = {}
    for line in handoff_rows(Path(board).read_text(encoding='utf-8')):
        is_waiting, cells = waiting(line)
        if not is_waiting:
            continue
        since = seen.get(line, now)       # not in any snapshot yet: written just now
        age = (now - since) / 3600
        if age >= hours:
            out.setdefault(cells[1] or '(받는 팀 없음)', []).append(
                {'from': cells[0], 'age_hours': round(age, 1), 'text': cells[2][:160]})
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--hours', type=float, default=24)
    args = parser.parse_args(argv)
    print(json.dumps(stale(args.hours), ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
