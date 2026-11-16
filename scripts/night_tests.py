"""Night full pytest and the failure list by team (운영·SRE, PM 11-15 16:52).

    .venv/bin/python -m scripts.night_tests run      # the whole suite once, then the report (started by ops_auto)
    .venv/bin/python -m scripts.night_tests report   # the report again from the last result

Why: before a commit only the changed files' tests run (CLAUDE.md), so a test another team's change broke was run by
nobody - storage_inventory failed from 11-08 and test_explore_retest_fixes from 11-11 until PM ran them by hand on
11-15. The rule "full pytest once a night" had no job behind it.

What it does
- runs `pytest -q` over tests/ in the working tree at nice 15 with .venv-tests and the production pointers cleared
  (scripts/pytest_env.clean_environment), writing JUnit XML; the whole run is one heavy_slot job (night slots)
- keeps, for every failing test id, the day it was first seen (logs/ops/night-tests-state.json) and appends one line
  per run to logs/ops/night-tests.jsonl (counts, failing ids, seconds, dirty files in the working tree)
- puts one board line per owning team ('자동 점검 [night_tests|<team>]'): the failing test files and since when. The
  owner is the team named in the last commit that changed the test file (or the code it names), from the commit text;
  when no team is named, PM assigns it
- a test failing for more than 2 days opens '자동 점검 [night_tests_stale]' for PM
- a run with no failures closes the open lines
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'logs/ops/night-tests'
LOG = ROOT / 'logs/ops/night-tests.jsonl'
STATE = ROOT / 'logs/ops/night-tests-state.json'
TIMEOUT_S = 50 * 60
STALE_DAYS = 2
# Team names as commit messages write them (status board names on the right).
TEAM_WORDS = (('운영·SRE', '운영·SRE'), ('ops 11-', '운영·SRE'), ('검색과 RAG', '검색과 RAG'), ('search team', '검색과 RAG'),
              ('워크플로우', '워크플로우'), ('workflow', '워크플로우'), ('에이전트 팀', '에이전트 팀'), ('agent team', '에이전트 팀'),
              ('성장·유통', '성장·유통'), ('growth', '성장·유통'), ('AI AD Coin', 'AI AD Coin'), ('AD Coin', 'AI AD Coin'),
              ('오류 감시', '오류 감시'))


def machine() -> dict:
    """1-minute load and swap use (PM 16:59: the Mac is short of memory at night; keep both around the run)."""
    import os
    out = subprocess.run(['sysctl', '-n', 'vm.swapusage'], capture_output=True, text=True).stdout
    used = re.search(r'used = ([\d.]+)M', out)
    return {'load_1': round(os.getloadavg()[0], 2), 'swap_used_mb': float(used.group(1)) if used else None}


def failures(xml_path: Path) -> tuple[int, list[str]]:
    """(tests run, failing ids 'tests/file.py::name') from JUnit XML."""
    root = ET.parse(xml_path).getroot()
    total, failing = 0, []
    for case in root.iter('testcase'):
        total += 1
        if any(child.tag in ('failure', 'error') for child in case):
            failing.append(f"{test_file(case.get('classname') or '')}::{case.get('name')}")
    return total, failing


def test_file(classname: str, root: Path = ROOT) -> str:
    """'tests.test_x' or 'tests.test_x.TestY' -> 'tests/test_x.py' (the longest prefix that is a file)."""
    parts = classname.split('.')
    for n in range(len(parts), 0, -1):
        candidate = '/'.join(parts[:n]) + '.py'
        if (root / candidate).is_file():
            return candidate
    return '/'.join(parts) + '.py'


def owner(test_file: str, git=None) -> tuple[str, str]:
    """(team, commit) of the last commit that changed TEST_FILE, the team read from the commit text."""
    git = git or (lambda *a: subprocess.run(['git', *a], cwd=ROOT, capture_output=True, text=True).stdout)
    line = git('log', '-1', '--format=%h %B', '--', test_file).strip()
    commit = line.split(' ', 1)[0] if line else ''
    for word, team in TEAM_WORDS:
        if word.lower() in line.lower():
            return team, commit
    return 'PM 배정', commit


def update_state(failing: list[str], day: str, state: dict) -> dict:
    """first_seen per failing id; ids that pass again leave."""
    seen = state.get('first_seen') or {}
    return {'first_seen': {tid: seen.get(tid, day) for tid in failing}, 'day': day}


def days_between(a: str, b: str) -> int:
    return (datetime.strptime(b, '%Y-%m-%d') - datetime.strptime(a, '%Y-%m-%d')).days


def report(record: dict, state: dict, git=None, handoff=None, close=None) -> dict:
    """Board lines per team for the failing tests, and the PM line for those older than STALE_DAYS."""
    sys.path.insert(0, str(ROOT / 'scripts'))
    import ops_auto
    handoff = handoff or ops_auto.board_handoff
    close = close or ops_auto.board_close
    by_team: dict[str, list[str]] = {}
    files = sorted({tid.split('::', 1)[0] for tid in record['failing']})
    owners = {f: owner(f, git) for f in files}
    for tid in record['failing']:
        team, commit = owners[tid.split('::', 1)[0]]
        by_team.setdefault(team, []).append(tid)
    for team, ids in by_team.items():
        kind = f'night_tests|{team}'
        ops_auto.TEAM[kind] = team if team != 'PM 배정' else 'PM'
        files_of = sorted({i.split('::', 1)[0].removeprefix('tests/') for i in ids})
        since = min(state['first_seen'][i] for i in ids)
        handoff(kind, f"밤 전체 시험 실패 {len(ids)}건({', '.join(files_of)[:90]}), {since}부터 — 고치거나 이유를 적어 주세요")
    for team in record.get('teams_before') or []:
        if team not in by_team:
            close(f'night_tests|{team}', f"해결(밤 시험 {record['day']} 통과)")
    stale = [i for i in record['failing'] if days_between(state['first_seen'][i], record['day']) > STALE_DAYS]
    if stale:
        ops_auto.TEAM['night_tests_stale'] = 'PM'
        handoff('night_tests_stale', f"{STALE_DAYS}일 넘게 실패한 시험 {len(stale)}건: {', '.join(s.removeprefix('tests/') for s in stale)[:110]}")
    else:
        close('night_tests_stale', f"해결({record['day']} {STALE_DAYS}일 넘은 실패 없음)")
    return {'teams': sorted(by_team), 'stale': stale}


def no_result(line: dict, handoff=None) -> None:
    """11-16 PM source review: a run that timed out (50 minutes) or ended without a result was only a line in
    night-tests.jsonl, so nobody heard that the night had no full run. It goes to the board for 운영·SRE."""
    sys.path.insert(0, str(ROOT / 'scripts'))
    import ops_auto
    handoff = handoff or ops_auto.board_handoff
    ops_auto.TEAM['night_tests_run'] = '운영·SRE'
    why = '50분 시간 초과' if line.get('error') == 'timeout' else f"결과 파일 없음({line.get('error') or '이유 없음'})"
    handoff('night_tests_run', f"밤 전체 시험 {line['day']}: {why}, {line['seconds']}초 — 그날 밤 전체 시험 결과가 없습니다")


def run(now=None) -> int:
    from scripts.pytest_env import clean_environment
    now = now or time.time()
    day = time.strftime('%Y-%m-%d', time.localtime(now))
    OUT.mkdir(parents=True, exist_ok=True)
    xml = OUT / f'{day}.xml'
    dirty = len(subprocess.run(['git', 'status', '--porcelain'], cwd=ROOT, capture_output=True, text=True).stdout.splitlines())
    head = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    cmd = ['nice', '-n', '15', str(ROOT / '.venv-tests/bin/python'), '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
           f'--junitxml={xml}', 'tests']
    started = time.time()
    before = machine()
    try:
        done = subprocess.run(cmd, cwd=ROOT, env=clean_environment(), capture_output=True, text=True, timeout=TIMEOUT_S)
        tail = (done.stdout or '').strip().splitlines()[-1:] or ['']
    except subprocess.TimeoutExpired:
        tail = ['timeout']
    seconds = round(time.time() - started)
    after = machine()
    if not xml.is_file():
        line = {'at': time.strftime('%Y-%m-%d %H:%M'), 'day': day, 'ok': False, 'error': tail[0][:200], 'seconds': seconds}
        with LOG.open('a') as out:
            out.write(json.dumps(line, ensure_ascii=False) + '\n')
        no_result(line)
        return 1
    total, failing = failures(xml)
    state = json.loads(STATE.read_text()) if STATE.is_file() else {}
    teams_before = state.get('teams') or []
    state = update_state(failing, day, state)
    record = {'at': time.strftime('%Y-%m-%d %H:%M'), 'day': day, 'ok': True, 'head': head, 'dirty_files': dirty,
              'tests': total, 'failed': len(failing), 'failing': failing, 'seconds': seconds, 'summary': tail[0][:200],
              'teams_before': teams_before, 'machine_before': before, 'machine_after': after}
    result = report(record, state)
    sys.path.insert(0, str(ROOT / 'scripts'))
    import ops_auto
    ops_auto.board_close('night_tests_run', f"해결(밤 시험 {day} 결과 있음)")
    state['teams'] = result['teams']
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    with LOG.open('a') as out:
        out.write(json.dumps({**record, **result}, ensure_ascii=False) + '\n')
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ['run']:
        return run()
    if argv[:1] == ['report']:
        last = json.loads(LOG.read_text().strip().splitlines()[-1])
        state = json.loads(STATE.read_text())
        print(json.dumps(report(last, state), ensure_ascii=False))
        return 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main())
