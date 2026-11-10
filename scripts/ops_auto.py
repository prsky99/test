#!/usr/bin/env python3
"""Operations automation that runs from launchd without a Claude Code session (11-10).

    ops_auto.py watch          every 10 minutes: ops_watch; on a new anomaly, write a short Korean alert
    ops_auto.py test-reports   daily: run the probed test-report batch, then summarise the last 24 hours

Claude API (scripts/ops_llm.py, Haiku, daily cap) only writes the wording; every decision about what is an
anomaly, and every fallback, is plain code, so a missing or expired key changes nothing but the wording.
Writes only to logs/ops, the status board hand-off table and the desktop alert file. It never edits code,
deploys, stops processes or writes the production database (the batch runner does its own documented writes).
"""
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import ops_llm  # noqa: E402
import ops_watch  # noqa: E402

DESKTOP = Path('/Users/kingstonelee/Desktop/Agent Concierge 메일 알림.txt')
ACTIONS = ROOT / 'logs/ops/watch-actions.md'
BOARD = ROOT / 'logs/ops/status-board.md'
STATE = ROOT / 'logs/ops/watch-alert-state.json'
REPORTS = ROOT / 'logs/ops/test-reports'
PSQL = ['/opt/homebrew/opt/postgresql@18/bin/psql', '-h', str(ROOT / 'gateway-data/postgres18/run'), '-p', '55432',
        '-d', 'agentcon_cutover_20261020_191757', '-Atc']
TEAM = {'site': '운영·SRE', 'memory': '운영·SRE', 'disk': '운영·SRE', 'deploy_stuck': '운영·SRE',
        'deploy_lock': '잠금을 잡은 팀', 'long_tests': '시험을 돌린 팀', 'stale_handoffs': '받는 팀'}
ALERT_SYSTEM = (
    'You write operations alerts in Korean for the owner of the Agent Concierge website. '
    'Input is JSON describing detected anomalies. Write at most three short lines in plain Korean: what is wrong, '
    'why it matters, and which team should act. No markdown, no English sentences, no guesses beyond the data.')
SUMMARY_SYSTEM = (
    'You summarise a daily batch of AI agent test reports in Korean for the site owner. Input is JSON with counts. '
    'Write three short Korean sentences: how many reports, the grade and success mix, and anything that needs '
    'attention. Use only the numbers given. No markdown.')


def now():
    return datetime.now().strftime('%Y-%m-%d %H:%M')


def prepend_desktop(line):
    old = DESKTOP.read_text().splitlines() if DESKTOP.is_file() else []
    DESKTOP.write_text('\n'.join([line] + old[:49]) + '\n')


def append(path, line):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as fh:
        fh.write(line + '\n')


def board_handoff(kind, text):
    if not BOARD.is_file():
        return
    content = BOARD.read_text()
    marker = '## 넘기는 일'
    if marker not in content:
        return
    head, rest = content.split(marker, 1)
    table, sep, tail = rest.partition('\n## ')
    row = f'| 자동 점검 | {TEAM.get(kind, "운영·SRE")} | {now()} {text[:150]} | 대기 |'
    BOARD.write_text(head + marker + table.rstrip('\n') + '\n' + row + '\n' + (sep + tail if sep else ''))


def watch():
    record = json.loads(subprocess.run([sys.executable, str(ROOT / 'scripts/ops_watch.py')],
                                       capture_output=True, text=True, cwd=ROOT).stdout or '{}')
    anomalies = record.get('anomalies') or {}
    state = json.loads(STATE.read_text()) if STATE.is_file() else {}
    fresh = {k: v for k, v in anomalies.items() if time.time() - state.get(k, 0) > 1800}
    for kind in list(state):
        if kind not in anomalies:
            state.pop(kind)  # cleared: alert again if it comes back
    if not fresh:
        STATE.write_text(json.dumps(state))
        return 0
    wording = ops_llm.ask(ALERT_SYSTEM, json.dumps(fresh, ensure_ascii=False), 'watch_alert', max_tokens=400)
    text = ' / '.join(line.strip() for line in (wording or '').splitlines() if line.strip()) or \
        ', '.join(f'{k}: {json.dumps(v, ensure_ascii=False)[:120]}' for k, v in fresh.items())
    urgent = any(k in fresh for k in ('site', 'memory', 'disk'))
    if urgent:
        prepend_desktop(f'{now()} [운영 이상] {text}')
    for kind in fresh:
        board_handoff(kind, text)
        state[kind] = time.time()
    append(ACTIONS, f'{now()} {",".join(fresh)} → 현황판 넘기는 일{" + 바탕화면" if urgent else ""}: {text[:200]}')
    STATE.write_text(json.dumps(state))
    return 0


def busy():
    procs = subprocess.run(['ps', '-eo', 'args'], capture_output=True, text=True).stdout
    if 'pytest' in procs or 'scripts.service_deploy' in procs or 'release_gate' in procs:
        return 'tests_or_deploy_running'
    if (ops_watch.check_memory() or 100) < 15:
        return 'memory_low'
    return None


def query(sql):
    return subprocess.run(PSQL + [sql], capture_output=True, text=True).stdout.strip()


def test_reports():
    REPORTS.mkdir(parents=True, exist_ok=True)
    day = datetime.now().strftime('%Y-%m-%d')
    reason = None
    for _ in range(3):
        reason = busy()
        if not reason:
            break
        time.sleep(1200)
    if reason:
        prepend_desktop(f'{now()} [시험 보고서 건너뜀] {reason}')
        append(REPORTS / f'{day}.md', f'- {now()} 건너뜀: {reason}')
        return 0
    log = REPORTS / f'run-{datetime.now().strftime("%Y%m%d-%H%M")}.log'
    with log.open('w') as fh:
        try:
            code = subprocess.run(['nice', '-n', '10', str(ROOT / '.venv/bin/python'), 'scripts/batch_report_runner.py'],
                                  cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT, timeout=2700).returncode
        except subprocess.TimeoutExpired:
            code = 'timeout'
    since = "extract(epoch from now() - interval '1 day')"
    counts = {
        'runner_exit': code,
        'reports_24h': query(f'select count(*) from agent_test_reports where created_at > {since}'),
        'by_kind_grade_success': query(
            f"select string_agg(k||':'||g||':'||s||'='||n, ', ') from (select kind k, coalesce(eval_grade,'-') g, "
            f"is_success s, count(*) n from agent_test_reports where created_at > {since} group by 1,2,3) x"),
    }
    summary = ops_llm.ask(SUMMARY_SYSTEM, json.dumps(counts, ensure_ascii=False), 'test_report_summary', max_tokens=500)
    lines = [f'# 시험 결과 보고서 일일 요약 {day}', '', f'- 실행 로그: {log.relative_to(ROOT)}',
             f'- 실행기 종료 코드: {code}', f'- 지난 24시간 보고서: {counts["reports_24h"]}건',
             f'- 종류:등급:성공=건수: {counts["by_kind_grade_success"]}', '', summary or '(요약 문장 없음: API 미사용)']
    (REPORTS / f'{day}.md').write_text('\n'.join(lines) + '\n')
    if code != 0 or counts['reports_24h'] in ('', '0'):
        tail = ' '.join(log.read_text().splitlines()[-3:])[:200] if log.is_file() else ''
        prepend_desktop(f'{now()} [시험 보고서 실패] 종료 {code}, 24시간 {counts["reports_24h"]}건 {tail}')
        board_handoff('test_reports', f'시험 보고서 배치 실패(종료 {code}), 로그 {log.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    command = sys.argv[1] if len(sys.argv) > 1 else ''
    raise SystemExit({'watch': watch, 'test-reports': test_reports}.get(command, lambda: 2)())
