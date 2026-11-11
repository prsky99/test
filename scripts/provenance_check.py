#!/usr/bin/env python3
"""Provenance check: is every file the running versions execute in git? (11-11 PM, once a day from ops_auto)

    .venv/bin/python -m scripts.provenance_check            # check, write logs/ops/provenance.json, update the board
    .venv/bin/python -m scripts.provenance_check --dry-run  # print only

For each active release (./agentcon status) every file under agent_market/ is hashed as git would hash it
and looked up among all blobs ever committed there. A file whose content is in no commit came from an
uncommitted working tree: that is a warning on the board, never closed by hand.
Board lines '| (출처 모름…) | <path> | …' are closed automatically when the working tree matches HEAD for
that path and no running version carries uncommitted content of it; otherwise they stay and are named
in the warning. Read only, apart from the board and the result file.
"""
import argparse
import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASES = ROOT / 'gateway-data/services/releases'
BOARD = ROOT / 'logs/ops/status-board.md'
OUT = ROOT / 'logs/ops/provenance.json'
KST = timezone(timedelta(hours=9))
SCOPE = 'agent_market'
UNKNOWN = re.compile(r'^\| \(출처 모름[^|]*\) \| `?([\w./-]+)`? \|')


def git(*args, stdin=None):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, input=stdin, check=True).stdout


def active_releases():
    status = json.loads(subprocess.run([str(ROOT / 'agentcon'), 'status'], cwd=ROOT, capture_output=True,
                                       text=True, check=True).stdout)
    active = {}
    for role, service in status['services'].items():
        slot = service['slots'][service['active']] if 'slots' in service else service
        if slot.get('release'):
            active[role] = slot['release']
    return active


def committed_blobs():
    blobs = set()
    for line in git('rev-list', '--objects', '--all', '--', SCOPE).splitlines():
        blobs.add(line.split(' ', 1)[0])
    return blobs


def release_files(release, root=None):
    base = Path(root or RELEASES) / release
    return sorted(p for p in (base / SCOPE).rglob('*') if p.is_file() and '__pycache__' not in p.parts)


def hashes(paths):
    if not paths:
        return []
    return git('hash-object', '--stdin-paths', stdin='\n'.join(str(p) for p in paths) + '\n').split()


def uncommitted(active, blobs, root=None):
    """{release: [relative paths whose content is in no commit]}"""
    found = {}
    for release in sorted(set(active.values())):
        files = release_files(release, root)
        base = Path(root or RELEASES) / release
        bad = [str(p.relative_to(base)) for p, h in zip(files, hashes(files)) if h not in blobs]
        if bad:
            found[release] = bad
    return found


def worktree_matches_head(path):
    return subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--', path], cwd=ROOT).returncode == 0


def close_lines(lines, found, today, matches=worktree_matches_head):
    """Close '출처 모름' lines whose file is clean everywhere; return (lines, closed paths, still open paths)."""
    dirty = {path for paths in found.values() for path in paths}
    closed, still = [], []
    for i, line in enumerate(lines):
        match = UNKNOWN.match(line)
        if not match:
            continue
        path = match.group(1)
        if path not in dirty and matches(path):
            lines[i] = (f'| ~~(출처 모름)~~ 운영·SRE 자동 | {path} | **자동 닫음 {today}(provenance_check):** 작업본 = HEAD이고, '
                        f'운영 중인 버전 모두 이 파일이 커밋된 내용과 같음 |')
            closed.append(path)
        else:
            still.append(path)
    return lines, closed, still


def check(dry_run=False):
    today = datetime.now(KST).strftime('%m-%d %H:%M')
    active = active_releases()
    found = uncommitted(active, committed_blobs())
    result = {'at': today, 'active': active, 'uncommitted': found, 'closed': [], 'open': []}
    if BOARD.is_file() and not dry_run:
        try:
            from scripts.heavy_slot import board_lock
        except ImportError:   # run from scripts/ (ops_auto puts that folder on sys.path)
            from heavy_slot import board_lock
        with board_lock():
            lines = BOARD.read_text(encoding='utf-8').split('\n')
            lines, result['closed'], result['open'] = close_lines(lines, found, today)
            if result['closed']:
                BOARD.write_text('\n'.join(lines), encoding='utf-8')
    if not dry_run:
        OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    print(json.dumps(check(args.dry_run), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
