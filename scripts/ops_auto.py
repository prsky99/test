#!/usr/bin/env python3
"""Operations automation that runs from launchd without a Claude Code session (11-10).

    ops_auto.py watch          every 10 minutes: ops_watch; on a new anomaly, write a short Korean alert
    ops_auto.py test-reports   daily: run the probed test-report batch, then summarise the last 24 hours
    ops_auto.py board-snapshot copy the status board to logs/ops/status-board-history/ when it changed (also run by watch)
    (watch also starts scripts/real_task_score.py once a day in the 04:00 local hour, 11-11)

Claude API (scripts/ops_llm.py, Haiku, daily cap) only writes the wording; every decision about what is an
anomaly, and every fallback, is plain code, so a missing or expired key changes nothing but the wording.
Writes only to logs/ops, the status board hand-off table and the desktop alert file. It never edits code,
deploys, stops processes or writes the production database (the batch runner does its own documented writes).
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
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
BOARD_HISTORY = ROOT / 'logs/ops/status-board-history'
BOARD_KEEP_SECONDS = 14 * 86400
PSQL = ['/opt/homebrew/opt/postgresql@18/bin/psql', '-h', str(ROOT / 'gateway-data/postgres18/run'), '-p', '55432',
        '-d', 'agentcon_cutover_20261020_191757', '-Atc']
TEAM = {'site': '운영·SRE', 'memory': '운영·SRE', 'disk': '운영·SRE', 'deploy_stuck': '운영·SRE',
        'deploy_lock': '잠금을 잡은 팀', 'long_tests': '시험을 돌린 팀', 'stale_handoffs': '받는 팀',
        'ad_coin_ledger': 'AI AD Coin', 'payment_flow': 'AI AD Coin', 'adcoin_daemon': 'AI AD Coin',
        'launchd_jobs': '운영·SRE', 'backup': '운영·SRE', 'core_down': '운영·SRE', 'vector_index_usage': '검색과 RAG', 'north_star': 'PM', 'revenue': 'PM', 'fingerprints': '운영·SRE', 'necklace_checks': '운영·SRE', 'adcoin_review': 'PM',
        'answer_sets': '워크플로우', 'adcoin_refunds': 'PM', 'pearl_snapshot': '검색과 RAG'}
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


ESCALATE_AFTER = 6
ESCALATIONS = ROOT / 'logs/ops/pm-escalations.md'


def escalate(kind, text):
    """An alert still open after ESCALATE_AFTER repeats (11-15: one stayed open 86 times) goes to the desktop file
    and to logs/ops/pm-escalations.md, which the PM heartbeat reads; launchd cannot message a session itself."""
    line = f'{now()} [격상 {kind}] {text}'
    prepend_desktop(line)
    append(ESCALATIONS, '- ' + line)


# Daily report lines, not alerts (11-15): a new day's line replaces the text and is never counted as a repeat, so it
# never escalates (R53 counts repeats of alerts nobody closed).
REPORT_KINDS = frozenset({'north_star', 'revenue'})


def board_handoff(kind, text):
    """One open line per kind in the board's handoff section (11-11 PM): a repeat refreshes that line.

    The line is tagged '자동 점검 [kind]'; a repeat replaces its text and counts how many times it came back
    since it was first raised. A team closes it by changing the status from '대기'; the next alert of that kind
    then opens a new line. Board edits hold the heavy_slot file lock."""
    if not BOARD.is_file():
        return
    from heavy_slot import board_lock
    with board_lock():
        content = BOARD.read_text()
        marker = '## 넘기는 일'
        if marker not in content:
            return
        head, rest = content.split(marker, 1)
        table, sep, tail = rest.partition('\n## ')
        tag = f'| 자동 점검 [{kind}] |'
        rows = table.rstrip('\n').split('\n')
        open_at = next((i for i, row in enumerate(rows) if row.startswith(tag) and row.rstrip().endswith('| 대기 |')), None)
        count, first = 1, now()
        if open_at is not None and kind not in REPORT_KINDS:
            seen = re.search(r'\(같은 경고 (\d+)회째, 처음 ([\d-]+ [\d:]+)\)', rows[open_at])
            count = int(seen.group(1)) + 1 if seen else 2
            first = seen.group(2) if seen else rows[open_at].split('|')[3].strip()[:16]
        note = f' (같은 경고 {count}회째, 처음 {first})' if count > 1 else ''
        if count == ESCALATE_AFTER + 1:   # R53 (11-15): an alert nobody closed after 6 repeats goes to people
            escalate(kind, f'{TEAM.get(kind, "운영·SRE")} | {text[:150]}{note}')
        row = f'{tag} {TEAM.get(kind, "운영·SRE")} | {now()} {text[:150]}{note} | 대기 |'
        if open_at is None:
            rows.append(row)
        else:
            rows[open_at] = row
        BOARD.write_text(head + marker + '\n'.join(rows) + '\n' + (sep + tail if sep else ''))


def board_close(kind, note):
    """Close the open '자동 점검 [kind]' line (status '대기' -> note). Returns True when a line was closed."""
    if not BOARD.is_file():
        return False
    from heavy_slot import board_lock
    with board_lock():
        lines = BOARD.read_text().split('\n')
        tag = f'| 자동 점검 [{kind}] |'
        hit = [i for i, row in enumerate(lines) if row.startswith(tag) and row.rstrip().endswith('| 대기 |')]
        for i in hit:
            lines[i] = lines[i].rstrip()[:-len('| 대기 |')] + f'| {note} |'
        if hit:
            BOARD.write_text('\n'.join(lines))
        return bool(hit)

SLO_EVERY = 3600  # user-facing targets, measured from outside every hour (scripts/user_slo.py)
SLO_STATE = ROOT / 'logs/ops/user-slo-state.json'


def user_slo():
    """Every hour: measure the user-facing targets; hand every breach to its owning team. Nothing is excluded."""
    state = json.loads(SLO_STATE.read_text()) if SLO_STATE.is_file() else {}
    # Once in every clock hour, at the first watch of the hour (11-12 PM: 'at + 3600' drifted ten minutes a run,
    # 08:21 -> 09:22 -> 10:2x, and left hours without a record). Never put off for load: the load is recorded.
    hour = datetime.now().strftime('%Y-%m-%d %H')
    if state.get('hour') == hour:
        return
    state['at'], state['hour'] = time.time(), hour
    SLO_STATE.write_text(json.dumps(state))
    out = subprocess.run([str(ROOT / '.venv/bin/python'), str(ROOT / 'scripts/user_slo.py')], capture_output=True, text=True,
                         cwd=ROOT, timeout=600).stdout
    try:
        record = json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        board_handoff('user_slo', '사용자 기준 측정(user_slo.py)이 결과를 내지 못함')
        return
    for kind, breach in (record.get('breaches') or {}).items():
        count = f" {breach['bad_count']}/{breach['n']}건" if 'bad_count' in breach and 'n' in breach else ''
        text = f'사용자 기준 목표 미달 [{kind}]{count} ' + json.dumps(breach.get('bad'), ensure_ascii=False)[:110]
        TEAM[f'slo_{kind}'] = breach.get('team', '운영·SRE')
        board_handoff(f'slo_{kind}', text)
    breaches = record.get('breaches') or {}
    for kind, part in record.items():
        # A target measured and met this hour closes its open line (11-11 PM); unmeasured ones stay open.
        if (kind not in breaches and isinstance(part, dict) and part.get('ok') is True
                and part.get('samples')):
            board_close(f'slo_{kind}', f'해결(자동 {now()[11:]} 통과)')
    append(ACTIONS, f'{now()} user_slo: 미달 {",".join(record.get("breaches") or {}) or "없음"}')


STALE_STATE = ROOT / 'logs/ops/board-stale-state.json'
STALE_AFTER_HOUR = 10   # 11-12 PM: once a morning, one line per receiving team


def stale_handoffs(clock=time.time, find=None):
    """Once a day: hand-off lines still '대기' and untouched for 24 hours (scripts/board_stale.py), one board line
    per receiving team asking it to set '진행 중', '완료' or '보류(이유)'."""
    local = datetime.fromtimestamp(clock())
    if local.hour < STALE_AFTER_HOUR:
        return None
    day = local.strftime('%Y-%m-%d')
    state = json.loads(STALE_STATE.read_text()) if STALE_STATE.is_file() else {}
    if state.get('day') == day:
        return None
    STALE_STATE.write_text(json.dumps({'day': day}))
    if find is None:
        import board_stale
        find = board_stale.stale
    found = find(24)
    for team, rows in found.items():
        kind = 'stale|' + team
        TEAM[kind] = team
        oldest = max(row['age_hours'] for row in rows)
        sample = ' / '.join(row['text'][:40] for row in rows[:2])
        board_handoff(kind, f"24시간 넘게 갱신 없는 대기 줄 {len(rows)}개(가장 오래된 것 {oldest:.0f}시간), "
                            f"'진행 중·완료·보류(이유)' 중 하나로 고쳐 주세요: {sample}")
    append(ACTIONS, f"{now()} 오래된 대기 줄: {', '.join(f'{t} {len(r)}' for t, r in found.items()) or '없음'}")
    return {team: len(rows) for team, rows in found.items()}


NORTH_STAR_STATE = ROOT / 'logs/ops/north-star-state.json'
NORTH_STAR_AFTER_HOUR = 8   # 11-12 PM: the previous day's line every morning from 08:00, first on 11-16
NORTH_STAR_FIRST_RUN = '2026-11-16'   # PM: counting starts Monday 11-16 08:00 (the line for 11-15)


def north_star(clock=time.time, run=None):
    """Once a day after 08:00: scripts/north_star.py for the previous KST day; the board line shows the funnel."""
    local = datetime.fromtimestamp(clock())
    if local.hour < NORTH_STAR_AFTER_HOUR:
        return None
    day = local.strftime('%Y-%m-%d')
    if day < NORTH_STAR_FIRST_RUN:
        return None
    state = json.loads(NORTH_STAR_STATE.read_text()) if NORTH_STAR_STATE.is_file() else {}
    if state.get('day') == day:
        return None
    NORTH_STAR_STATE.write_text(json.dumps({'day': day}))
    run = run or (lambda: subprocess.run([str(ROOT / '.venv/bin/python'), '-m', 'scripts.north_star'],
                                         capture_output=True, text=True, cwd=ROOT, timeout=120))
    try:
        done = run()
        record = json.loads(done.stdout.strip().splitlines()[-1]) if done.returncode == 0 else None
    except (subprocess.TimeoutExpired, ValueError, IndexError):
        record = None
    if record is None:
        board_handoff('north_star', '북극성 집계(scripts/north_star.py)가 결과를 내지 못함 → 운영·SRE 확인')
        append(ACTIONS, f'{now()} 북극성 집계 실패')
        return 'failed'
    funnel = record.get('funnel') or {}
    show = lambda value: '?' if value is None else value   # noqa: E731 - approx days have no pair counts
    text = (f"{record['day']} 성공 실행 쌍 {record['north_star']}"
            f"({'근사' if record.get('basis') == 'approx' else '기록'}) | 외부 추천 요청 "
            f"{show((funnel.get('recommend') or {}).get('requests'))} → 게이트웨이 연결 쌍 "
            f"{show((funnel.get('connect') or {}).get('pairs'))} → 성공 실행 쌍 {record['north_star']}"
            f" | 끊긴 단계 {record.get('breaks_at') or '없음'}"
            f" | 엣지→원서버 넘김 {sum((record.get('edge_fallbacks') or {}).values())} (logs/ops/north-star.jsonl)")
    board_handoff('north_star', text)
    append(ACTIONS, f'{now()} 북극성: {text}')
    return record


ANSWER_SET_STATE = ROOT / 'logs/ops/answer-set-expiry-state.json'
ANSWER_SET_WARN_DAYS = 14   # PM 12:27 (11-15): a board line 14 days before an answer set expires, never a silent hold


def answer_set_expiry(clock=time.time, gold=None, state_path=None):
    """Once a day: open the '자동 점검 [answer_sets]' line when a necklace answer set (gold/<slug>/manifest.json
    valid_until) expires within 14 days, has expired or has no validity; close it when none does. Without a valid
    set no retest or gate round runs and the necklace is held 48 hours later, so the line comes first."""
    gold = Path(gold or ROOT / 'gateway-data/necklaces/gold')
    state_path = Path(state_path or ANSWER_SET_STATE)
    local = datetime.fromtimestamp(clock())
    day = local.strftime('%Y-%m-%d')
    state = json.loads(state_path.read_text()) if state_path.is_file() else {}
    if state.get('day') == day:
        return None
    state_path.write_text(json.dumps({'day': day}))
    soon = (local + timedelta(days=ANSWER_SET_WARN_DAYS)).strftime('%Y-%m-%d')
    found = []
    for path in sorted(gold.glob('*/manifest.json')):
        try:
            until = json.loads(path.read_text()).get('valid_until')
        except (OSError, ValueError):
            until = None
        if not until:
            found.append(f'{path.parent.name} 유효기간 없음')
        elif until < day:
            found.append(f'{path.parent.name} {until} 만료됨')
        elif until <= soon:
            found.append(f'{path.parent.name} {until} 만료')
    if found:
        board_handoff('answer_sets', '정답 세트 다시 만들기(만료되면 재시험·관문이 멈추고 48시간 뒤 보류): '
                      + ', '.join(found))
    else:
        board_close('answer_sets', f'해결 {day}: 14일 안에 만료되는 정답 세트 없음')
    return found


HOLIDAY_STATE = ROOT / 'logs/ops/holiday-truth-state.json'
HOLIDAY_LOG = ROOT / 'logs/ops/holiday-truth.jsonl'
HOLIDAY_AFTER_HOUR = 10   # workflow 11-15 (PM): one Nager.Date round a day inside the reference_checks share
HOLIDAY_TRIES = 3
HOLIDAY_TIMEOUT_S = 180


def holiday_truth(clock=time.time, run=None, state_path=None, log_path=None, gold=None):
    """Once a day from 10:00, outside the :55-:10 measurement window, until the holidays-at-address set is written:
    necklaces.gold_holidays in the app's Python (a subprocess with a timeout: the watch's own Python lacks the app's
    packages, ops review 11-15) asks Nager.Date for the countries it does not keep yet and writes the set at 90 cases.
    Every try leaves one line (countries kept, cases, stopped by the share, written, or the error). The day counts as
    done only on a result (stopped by the share included); an error is tried again next round, at most 3 a day; a
    skipped day is caught up the next day because kept countries stay on disk."""
    local = datetime.fromtimestamp(clock())
    if local.hour < HOLIDAY_AFTER_HOUR or local.minute >= 55 or local.minute < 10:
        return None
    gold = Path(gold or ROOT / 'gateway-data/necklaces/gold')
    if (gold / 'holidays-at-address' / 'manifest.json').is_file():
        return 'done'
    state_path, log_path = Path(state_path or HOLIDAY_STATE), Path(log_path or HOLIDAY_LOG)
    day = local.strftime('%Y-%m-%d')
    state = json.loads(state_path.read_text()) if state_path.is_file() else {}
    if state.get('day') != day:
        state = {'day': day, 'tries': 0, 'done': False}
    if state.get('done') or state.get('tries', 0) >= HOLIDAY_TRIES:
        return None
    run = run or (lambda: subprocess.run([str(ROOT / '.venv/bin/python'), '-m', 'agent_market.necklaces.gold_holidays'],
                                         capture_output=True, text=True, cwd=ROOT, timeout=HOLIDAY_TIMEOUT_S))
    state['tries'] = state.get('tries', 0) + 1
    try:
        done = run()
        result = json.loads(done.stdout.strip().splitlines()[-1]) if done.returncode == 0 else None
    except (subprocess.TimeoutExpired, ValueError, IndexError) as error:
        result, reason = None, type(error).__name__
    else:
        reason = None if result else f'exit {done.returncode}: {(done.stderr or "").strip().splitlines()[-1:]}'
    if result:
        state['done'] = True
        line = {'at': now(), 'ok': True, 'try': state['tries'], 'countries_kept': result.get('countries_kept'),
                'countries': result.get('countries'), 'cases': result.get('cases'), 'stopped': result.get('stopped'),
                'written': 'manifest' in result}
    else:
        line = {'at': now(), 'ok': False, 'try': state['tries'], 'error': str(reason)[:300]}
        append(ACTIONS, f'{now()} 공휴일 정답 받기 실패({state["tries"]}/{HOLIDAY_TRIES}): {str(reason)[:120]}')
    state_path.write_text(json.dumps(state))
    with log_path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(line, ensure_ascii=False) + '\n')
    return line


REVENUE_STATE = ROOT / 'logs/ops/revenue-funnel-state.json'
REVENUE_AFTER_HOUR = 8   # revenue review 11-15 (PM 10:57): one line every morning from 08:00, first on 11-16
REVENUE_EVERY = 2 * 3600 - 300   # PM 11-15 14:24: PM's own check reads the funnel every 2 hours, so a line every 2 hours


def revenue_funnel(clock=time.time, run=None):
    """Every 2 hours from 08:00 (PM 11-15 14:24, was once a day): scripts/revenue_funnel.py (read-only counts through
    prod_ro_sql) appends logs/ops/revenue-funnel.jsonl; the board line '자동 점검 [revenue]' shows the funnel for PM's
    own check (a report line: replaced, never escalated)."""
    local = datetime.fromtimestamp(clock())
    if local.hour < REVENUE_AFTER_HOUR:
        return None
    day = local.strftime('%Y-%m-%d')
    state = json.loads(REVENUE_STATE.read_text()) if REVENUE_STATE.is_file() else {}
    if clock() - float(state.get('at') or 0) < REVENUE_EVERY:
        return None
    REVENUE_STATE.write_text(json.dumps({'day': day, 'at': clock()}))
    run = run or (lambda: subprocess.run([str(ROOT / '.venv/bin/python'), '-m', 'scripts.revenue_funnel'],
                                         capture_output=True, text=True, cwd=ROOT, timeout=120))
    try:
        done = run()
        record = json.loads(done.stdout.strip().splitlines()[-1]) if done.returncode == 0 else None
    except (subprocess.TimeoutExpired, ValueError, IndexError):
        record = None
    if record is None:
        board_handoff('revenue', '매출 깔때기 집계(scripts/revenue_funnel.py)가 결과를 내지 못함 → 운영·SRE 확인')
        append(ACTIONS, f'{now()} 매출 깔때기 집계 실패')
        return 'failed'
    from revenue_funnel import line   # the watch runs this file as a script with scripts/ on sys.path (11-15 11:15)
    text = f"{day} {line(record)}"   # 150 characters on the board; the record is logs/ops/revenue-funnel.jsonl
    board_handoff('revenue', text)
    append(ACTIONS, f'{now()} 매출 깔때기: {text}')
    return record


REVIEW_STATE = ROOT / 'logs/ops/adcoin-review-queue-state.json'
REVIEW_SQL = ROOT / 'deploy/ops/adcoin-review-queue.sql'


def review_queue(clock=time.time, run=None):
    """Every watch run (AI AD Coin, PM 11-15 12:4x, until campaign reviews are automatic): campaign reviews waiting
    for an operator, read-only through prod_ro_sql (ids only, never ad text). One or more opens a board line for PM;
    none closes it. adc2_reviews keeps no request time, so the longest wait is measured from when this watch first saw
    each id (kept in REVIEW_STATE; an id that is no longer pending is dropped)."""
    if run is None and os.environ.get('PYTEST_CURRENT_TEST'):
        return None   # a test that runs the whole watch never reads the production database
    at = clock()
    run = run or (lambda: subprocess.run([str(ROOT / '.venv/bin/python'), '-m', 'scripts.prod_ro_sql', str(REVIEW_SQL)],
                                         capture_output=True, text=True, cwd=ROOT, timeout=60))
    try:
        done = run()
        line = [x for x in done.stdout.strip().splitlines() if '|' in x][-1] if done.returncode == 0 else None
        count, _, ids = line.partition('|') if line else ('', '', '')
        count = int(count)
    except (subprocess.TimeoutExpired, ValueError, IndexError, OSError):
        append(ACTIONS, f'{now()} 심사 대기 확인 실패(prod_ro_sql)')
        return 'failed'
    pending = [i for i in ids.split(',') if i]
    try:
        seen = json.loads(REVIEW_STATE.read_text()).get('first_seen') or {}
    except (OSError, ValueError):
        seen = {}
    seen = {i: seen.get(i, at) for i in pending}
    oldest = int((at - min(seen.values())) // 60) if seen else 0
    REVIEW_STATE.write_text(json.dumps({'at': at, 'pending': count, 'oldest_minutes': oldest, 'first_seen': seen}))
    if count:
        board_handoff('adcoin_review', f'캠페인 심사 대기 {count}건, 가장 오래 {oldest}분 → 관리자 심사 화면에서 처리(AI AD Coin)')
    else:
        board_close('adcoin_review', '심사 대기 0건(' + now() + ')')
    return {'pending': count, 'oldest_minutes': oldest}


REFUNDS_SQL = ROOT / 'deploy/ops/adcoin-refunds-due.sql'


def refunds_due(run=None):
    """Every watch run (AI AD Coin, PM 11-15 12:5x): USDC refunds the user has to send by hand (an operator takedown
    turns a paid placement into refund_due). Counts and the total only, read-only through prod_ro_sql; payer addresses
    are never read here. One or more opens a board line for PM; none closes it."""
    if run is None and os.environ.get('PYTEST_CURRENT_TEST'):
        return None   # a test that runs the whole watch never reads the production database
    run = run or (lambda: subprocess.run([str(ROOT / '.venv/bin/python'), '-m', 'scripts.prod_ro_sql', str(REFUNDS_SQL)],
                                         capture_output=True, text=True, cwd=ROOT, timeout=60))
    try:
        done = run()
        line = [x for x in done.stdout.strip().splitlines() if '|' in x][-1] if done.returncode == 0 else None
        count, units, ok_format = (int(v) for v in line.split('|')[:3])
    except (subprocess.TimeoutExpired, ValueError, IndexError, OSError, AttributeError):
        append(ACTIONS, f'{now()} 환불 대기 확인 실패(prod_ro_sql)')
        return 'failed'
    if count:
        board_handoff('adcoin_refunds', f'USDC 환불 대상 {count}건, 합계 {units / 1_000_000:.2f} USDC, 받을 주소 형식 맞음 '
                                        f'{ok_format}건(주소는 운영자 화면의 USDC 결제 대기열에서만), 사유는 운영자 화면 → 사용자가 직접 송금')
    else:
        board_close('adcoin_refunds', '환불 대상 0건(' + now() + ')')
    return {'refunds_due': count, 'usdc': units / 1_000_000, 'payer_format_ok': ok_format}


VECTOR_USAGE_STATE = ROOT / 'logs/ops/vector-index-usage-state.json'


def vector_index_usage(clock=time.time, run=None):
    """Once in every clock hour: scripts/vector_index_usage.py (one read-only connection, under a second).

    검색과 RAG 11-12 (PM): 72 hours of zero scans on the shared graph come before its drop is put up for approval,
    so a failed hour is handed to them (a gap in the record)."""
    hour = datetime.fromtimestamp(clock()).strftime('%Y-%m-%d %H')
    state = json.loads(VECTOR_USAGE_STATE.read_text()) if VECTOR_USAGE_STATE.is_file() else {}
    if state.get('hour') == hour:
        return None
    VECTOR_USAGE_STATE.write_text(json.dumps({'hour': hour}))
    run = run or (lambda: subprocess.run([str(ROOT / '.venv/bin/python'), '-m', 'scripts.vector_index_usage'],
                                         capture_output=True, text=True, cwd=ROOT, timeout=60))
    try:
        done = run()
        summary = json.loads(done.stdout.strip().splitlines()[-1]) if done.returncode == 0 else None
    except (subprocess.TimeoutExpired, ValueError, IndexError):
        summary = None
    if summary is None:
        board_handoff('vector_index_usage', '벡터 인덱스 사용 기록(vector_index_usage.py)이 이번 시간에 실패함(72시간 기록에 빈칸)')
        append(ACTIONS, f'{now()} 벡터 인덱스 사용 기록 실패')
        return 'failed'
    append(ACTIONS, f"{now()} 벡터 인덱스 사용: 공유 그래프 스캔 {summary.get('shared_graph_scans')}, "
                    f"읽기 {summary.get('shared_graph_read')}")
    return summary


REAL_TASK_STATE = ROOT / 'logs/ops/real-task-score-state.json'
REAL_TASK_WINDOWS = {'night': (4, 5), 'afternoon': (15, 17)}   # 11-12 PM: twice a day (was 04 only)


def real_task_score(clock=time.time, launch=None, free=None, window=None):
    """Twice a day (night, afternoon): score the 30-task answer set on the public site (scripts/real_task_score.py).

    Started in the background through heavy_slot (one heavy job at a time; daytime runs stay under 30 minutes)
    so the 10-minute watch never waits for it; skipped while tests or deploys run or the slot is full, and
    tried again at the next watch inside the window. Results: reports/real-task-score/<date>-<HHMM>.json,
    logs/ops/real-task-score.jsonl and the 'latest' block of reports/real-task-score/README.md.

    11-13 PM 16:2x: the 15:07 afternoon run was refused by heavy_slot (:55-:10 measurement window, exit 75) but its
    turn was already recorded, so the afternoon went unscored. Now the window is checked before starting, and the
    detached run (real_task_run) gives the turn back when heavy_slot refuses, so the next watch tries again."""
    local = datetime.fromtimestamp(clock())
    turn = next((name for name, (first, last) in REAL_TASK_WINDOWS.items() if first <= local.hour <= last), None)
    if turn is None:
        return None
    state = json.loads(REAL_TASK_STATE.read_text()) if REAL_TASK_STATE.is_file() else {}
    key = local.strftime('%Y-%m-%d') + '|' + turn
    if key in (state.get('runs') or {}) or (turn == 'night' and state.get('day') == key.split('|')[0]):
        return None
    reason = busy()
    if free is None:
        import heavy_slot
        lines = heavy_slot.BOARD.read_text(encoding='utf-8').split('\n') if heavy_slot.BOARD.is_file() else []
        free = len([line for _, line, ok in heavy_slot.entries(lines) if ok]) < heavy_slot.slots()
    if window is None:
        import heavy_slot
        window = heavy_slot.measurement_window(local)
    reason = reason or (None if free else '무거운 작업 칸이 모두 참') or (window and '매시 측정 시간(:55~:10)')
    if reason:
        append(ACTIONS, f'{now()} real_task_score({turn}) 미룸: {reason}')
        return None
    runs = {k: v for k, v in (state.get('runs') or {}).items() if k >= (local - timedelta(days=7)).strftime('%Y-%m-%d')}
    runs[key] = clock()
    REAL_TASK_STATE.parent.mkdir(parents=True, exist_ok=True)
    REAL_TASK_STATE.write_text(json.dumps({'runs': runs, 'day': state.get('day'), 'started': clock()}))
    log = (ROOT / 'logs/ops/real-task-score.out').open('a')
    command = [str(ROOT / '.venv/bin/python'), str(ROOT / 'scripts/ops_auto.py'), 'real-task-run', key]
    (launch or subprocess.Popen)(command, cwd=ROOT, stdout=log, stderr=log, start_new_session=True)
    append(ACTIONS, f'{now()} real_task_score({turn}) 시작')
    return key


def real_task_command():
    return ['nice', '-n', '10', str(ROOT / '.venv/bin/python'), '-m', 'scripts.real_task_score']


def real_task_run(key, run=None):
    """The detached half of real_task_score: run the scorer through heavy_slot and, when heavy_slot refuses
    (75 slot full or measurement window, 77 night only), take the turn's record back so a later watch retries."""
    import heavy_slot
    turn = key.split('|', 1)[-1]
    run = run or heavy_slot.run
    code = run(real_task_command(), '운영·SRE', f'real_task_score {turn}(ops_auto)', 20)
    if code in (heavy_slot.BUSY, heavy_slot.NIGHT_ONLY):
        state = json.loads(REAL_TASK_STATE.read_text()) if REAL_TASK_STATE.is_file() else {}
        runs = state.get('runs') or {}
        runs.pop(key, None)
        state['runs'] = runs
        REAL_TASK_STATE.write_text(json.dumps(state))
        append(ACTIONS, f'{now()} real_task_score({turn}) heavy_slot 거부(종료 {code}): 실행 기록을 되돌림, 다음 watch에 다시 시도')
    elif code:
        append(ACTIONS, f'{now()} real_task_score({turn}) 끝: 종료 {code}')
    return code


def board_snapshot(board=None, history=None, clock=time.time):
    """Keep a timestamped copy of the status board whenever its content changed (11-11).

    A team overwrote other teams' rows and the original text was lost. Copies are kept 14 days."""
    board, history = Path(board or BOARD), Path(history or BOARD_HISTORY)
    try:
        data = board.read_bytes()
    except OSError:
        return None
    digest = hashlib.sha256(data).hexdigest()
    history.mkdir(parents=True, exist_ok=True)
    marker = history / '.last-sha256'
    if marker.is_file() and marker.read_text().strip() == digest:
        return None
    stamp = datetime.fromtimestamp(clock()).strftime('%Y%m%d-%H%M%S')
    target = history / f'status-board-{stamp}.md'
    target.write_bytes(data)
    marker.write_text(digest)
    for old in history.glob('status-board-*.md'):
        try:
            if clock() - old.stat().st_mtime > BOARD_KEEP_SECONDS:
                old.unlink()
        except OSError:
            pass
    return target


EDGE_STATE = ROOT / 'logs/ops/edge-transitions-state.json'
EDGE_WORDS = {'auto-block': 'Worker 실행 자동 차단(오류율 기준), 원 서버 경로로 전환', 'auto-clear': '반쯤 열기 시험 통과, Worker 실행 자동 해제',
              'clear-runtime-block': '운영자가 Worker 실행 차단 해제', 'block-runtime': '운영자가 Worker 실행 다시 차단', 'origin': '운영자가 원 서버 고정', 'auto': '운영자가 자동 경로로 되돌림'}


def edge_transitions(rows=None):
    """Post each new edge runtime switch (audit row) to the status board once (11-11 PM decision)."""
    last = json.loads(EDGE_STATE.read_text()).get('revision', 0) if EDGE_STATE.is_file() else 0
    if rows is None:
        out = query(f"SELECT revision||'|'||action||'|'||actor||'|'||replace(reason,'|','/') FROM edge_gateway_host_audit "
                    f"WHERE revision>{int(last)} ORDER BY revision LIMIT 20")
        rows = [line.split('|', 3) for line in out.splitlines() if line.count('|') >= 3]
    posted, parts = [], []
    for revision, action, actor, reason in rows:
        parts.append(f'{EDGE_WORDS.get(action, action)} ({actor}, rev {revision}: {reason[:40]})')
        last = max(last, int(revision)); posted.append(action)
    if rows:
        # One line for the whole batch: board_handoff keeps one line per kind, so a block and the clear that
        # followed it in the same check would otherwise overwrite each other (11-12).
        board_handoff('edge_gateway', '엣지 게이트웨이: ' + ' → '.join(parts))
        EDGE_STATE.write_text(json.dumps({'revision': last}))
    return posted



LEDGER_STATE = ROOT / 'logs/ops/error-ledger-state.json'
LEDGER_DIR = ROOT / 'logs/ops/error-ledger'
LEDGER_AFTER_MINUTE = 20   # 00:20 local: yesterday's logs are complete


def error_ledger(clock=time.time, launch=None):
    """Once a day: build yesterday's error ledger (scripts/error_ledger.py) and hand off what is unexplained.

    The ledger is started in the background at low priority; a later watch reads its JSON and puts one line in
    the board's handoff section when anything is unexplained (11-11 PM: stability first)."""
    local = datetime.fromtimestamp(clock())
    if local.hour * 60 + local.minute < LEDGER_AFTER_MINUTE:
        return None
    day = datetime.fromtimestamp(clock() - 86400).strftime('%Y-%m-%d')
    state = json.loads(LEDGER_STATE.read_text()) if LEDGER_STATE.is_file() else {}
    result = LEDGER_DIR / f'{day}.json'
    if state.get('reported') != day and result.is_file() and state.get('day') == day:
        data = json.loads(result.read_text())
        if data.get('unexplained'):
            top = ', '.join(r['key'][:60] for r in data['rows'] if not r['explained'])[:200]
            board_handoff('error_ledger', f"오류 장부 {day}: 설명되지 않음 {data['unexplained']}건 {data['unexplained_kinds']}종"
                                          f" (logs/ops/error-ledger/{day}.md): {top}")
        state['reported'] = day
        LEDGER_STATE.write_text(json.dumps(state))
        append(ACTIONS, f"{now()} 오류 장부 {day}: 전체 {data.get('total')}건, 설명되지 않음 {data.get('unexplained')}건")
        return 'reported'
    if state.get('day') == day:
        return None
    LEDGER_STATE.parent.mkdir(parents=True, exist_ok=True)
    LEDGER_STATE.write_text(json.dumps({'day': day, 'started': clock()}))
    log = (ROOT / 'logs/ops/error-ledger.out').open('a')
    (launch or subprocess.Popen)(['nice', '-n', '10', str(ROOT / '.venv/bin/python'), '-m', 'scripts.error_ledger',
                                  '--day', day], cwd=ROOT, stdout=log, stderr=log, start_new_session=True)
    append(ACTIONS, f'{now()} 오류 장부 {day} 시작')
    return 'started'




FULL_CHECK_STATE = ROOT / 'logs/ops/public-full-check-state.json'
FULL_CHECK_EVERY = 7200   # 11-11 PM: every two hours
FULL_CHECK_MINUTES = 15


OUTSIDE_LOAD = 10.0                      # 1-minute load that is worth a board line when another project causes it
WORKSPACE = ROOT.parent                  # sibling project folders (driver_agent, ...)


def outside_load(load=None, ps=None, cwd_of=None):
    """Alert, never stop: name the other projects whose processes carry the load when it is OUTSIDE_LOAD or more.

    11-12 09:16~09:24: driver_agent's parallel tests (pytest -n 8, eight test PostgreSQL clusters) pushed the load
    to 23~58 and our jobs and execution rounds timed out (PM: add a board alert; the user asked that project to run
    its tests at low priority). A process belongs to the workspace folder that is its working directory."""
    load = os.getloadavg()[0] if load is None else load
    if load < OUTSIDE_LOAD:
        board_close('outside_load', f'해결(자동 {now()[11:]} load {load:.1f})')
        return None
    rows = (ps or (lambda: subprocess.run(['ps', '-Ao', 'pcpu=,pid='], capture_output=True, text=True).stdout))()
    top = []
    for line in rows.splitlines():
        parts = line.split()
        if len(parts) == 2:
            try:
                top.append((float(parts[0]), int(parts[1])))
            except ValueError:
                continue
    top.sort(reverse=True)

    def cwd(pid):
        out = subprocess.run(['lsof', '-a', '-p', str(pid), '-d', 'cwd', '-Fn'], capture_output=True, text=True).stdout
        return next((l[1:] for l in out.splitlines() if l.startswith('n')), '')
    projects = {}
    for cpu, pid in top[:30]:
        folder = (cwd_of or cwd)(pid)
        if folder.startswith(str(WORKSPACE) + '/') and not folder.startswith(str(ROOT)):
            name = folder[len(str(WORKSPACE)) + 1:].split('/', 1)[0]
            count, total = projects.get(name, (0, 0.0))
            projects[name] = (count + 1, total + cpu)
    if not projects:
        return None
    listed = ', '.join(f'{name} 프로세스 {count}개 CPU {total:.0f}%' for name, (count, total) in
                       sorted(projects.items(), key=lambda kv: -kv[1][1]))
    board_handoff('outside_load', f'다른 프로젝트 부하: load {load:.1f}(기준 {OUTSIDE_LOAD:.0f}) — {listed}. '
                                  f'알림만 함(끄지 않음). 낮은 우선순위(nice)로 돌려 달라는 사용자 결정(11-12)')
    return projects


ADC_LEDGER_STATE = ROOT / 'logs/ops/ad-coin-ledger-state.json'
ADC_LEDGER_AFTER_MINUTE = 9 * 60          # daily after 09:00, outside the 03:00-08:00 database change window
AGENTCON_ENV = ROOT / 'gateway-data/agentcon.env'


def _env_paths(names, env_file=None):
    """File paths (never their contents) from the production service environment file."""
    found = {}
    path = Path(env_file or AGENTCON_ENV)
    for line in path.read_text().splitlines() if path.is_file() else []:
        key, sep, value = line.partition('=')
        if sep and key.strip() in names:
            found[key.strip()] = value.strip().strip('"\'')
    return found


def ad_coin_ledger(clock=time.time, run=None):
    """Once a day: AI AD Coin v2 ledger conservation check (scripts/ad_coin_daily_ledger_check.py, 11-11 PM).

    Read only, one database connection, about a second. A failed check or a check that could not run is
    handed off on one board line; a clean day closes it."""
    local = datetime.fromtimestamp(clock())
    day = local.strftime('%Y-%m-%d')
    if local.hour * 60 + local.minute < ADC_LEDGER_AFTER_MINUTE:
        return None
    state = json.loads(ADC_LEDGER_STATE.read_text()) if ADC_LEDGER_STATE.is_file() else {}
    if state.get('day') == day:
        return None
    ADC_LEDGER_STATE.write_text(json.dumps({'day': day}))
    paths = _env_paths({'APPLICATION_POSTGRES_DSN_FILE', 'APPLICATION_WORKFLOW_KEY_FILE'})
    if len(paths) != 2:
        board_handoff('ad_coin_ledger', 'AD Coin 원장 보존 검사를 돌리지 못함: gateway-data/agentcon.env에 DSN·키 파일 경로가 없음')
        return 'unrunnable'
    command = [str(ROOT / '.venv/bin/python'), '-m', 'scripts.ad_coin_daily_ledger_check',
               '--dsn-file', paths['APPLICATION_POSTGRES_DSN_FILE'], '--key-file', paths['APPLICATION_WORKFLOW_KEY_FILE']]
    done = (run or (lambda c: subprocess.run(c, cwd=ROOT, capture_output=True, text=True, timeout=120)))(command)
    tail = (done.stdout or '').strip().splitlines()[-1:] or (done.stderr or '').strip().splitlines()[-1:] or ['']
    if done.returncode == 0:
        board_close('ad_coin_ledger', f'해결(자동 {now()[11:]} 원장 보존 검사 clean)')
        append(ACTIONS, f'{now()} AD Coin 원장 보존 검사: clean')
        return 'clean'
    board_handoff('ad_coin_ledger', f'AD Coin 원장 보존 검사 실패(종료 코드 {done.returncode}, logs/ops/ad-coin-ledger/): {tail[0][:160]}')
    append(ACTIONS, f'{now()} AD Coin 원장 보존 검사 실패: 종료 코드 {done.returncode}')
    return 'failed'


PAYMENT_FLOW_STATE = ROOT / 'logs/ops/payment-flow-state.json'
PAYMENT_FLOW_AFTER_MINUTE = 10 * 60 + 15     # daily after 10:15, inside :15-:50 (never the measurement minutes)


def payment_flow(clock=time.time, run=None):
    """Once a day: the AD Coin payment flow tests in the operations format (scripts.ad_coin_payment_flow_report,
    PM 11-14): the booking flow and its six failure cases in a throwaway database, plus one USDC receipt read on
    Base Sepolia (no wallet, no transfer). Its result file feeds the payment stability standard (1). A failure or a
    run that could not finish is handed off on one board line (the error watch alert); a clean day closes it."""
    local = datetime.fromtimestamp(clock())
    day = local.strftime('%Y-%m-%d')
    if local.hour * 60 + local.minute < PAYMENT_FLOW_AFTER_MINUTE or not 15 <= local.minute <= 50:
        return None
    state = json.loads(PAYMENT_FLOW_STATE.read_text()) if PAYMENT_FLOW_STATE.is_file() else {}
    if state.get('day') == day:
        return None
    PAYMENT_FLOW_STATE.write_text(json.dumps({'day': day}))
    command = ['nice', '-n', '10', str(ROOT / '.venv/bin/python'), '-m', 'scripts.ad_coin_payment_flow_report']
    try:
        done = (run or (lambda c: subprocess.run(c, cwd=ROOT, capture_output=True, text=True, timeout=900)))(command)
    except subprocess.TimeoutExpired:
        board_handoff('payment_flow', '결제 흐름 시험이 15분 안에 끝나지 않음(logs/ops/payment-flow-tests/)')
        return 'timeout'
    tail = (done.stdout or '').strip().splitlines()[-1:] or (done.stderr or '').strip().splitlines()[-1:] or ['']
    if done.returncode == 0:
        board_close('payment_flow', f'해결(자동 {now()[11:]} 결제 흐름 시험 전부 통과)')
        append(ACTIONS, f'{now()} 결제 흐름 시험: 전부 통과')
        return 'clean'
    board_handoff('payment_flow', f'결제 흐름 시험 실패(종료 코드 {done.returncode}, logs/ops/payment-flow-tests/): {tail[0][:160]}')
    append(ACTIONS, f'{now()} 결제 흐름 시험 실패: 종료 코드 {done.returncode}')
    return 'failed'


PROVENANCE_STATE = ROOT / 'logs/ops/provenance-state.json'
PROVENANCE_AFTER_MINUTE = 6 * 60 + 30   # daily, before the 08:00 bundle deploy


def provenance(clock=time.time, run=None):
    """Once a day: is every file the running versions execute committed? (scripts/provenance_check.py, 11-11 PM)

    Clean '출처 모름' board lines are closed by the check itself; uncommitted content in a running version is
    handed off on one line, which closes again once a later day is clean."""
    local = datetime.fromtimestamp(clock())
    day = local.strftime('%Y-%m-%d')
    if local.hour * 60 + local.minute < PROVENANCE_AFTER_MINUTE:
        return None
    state = json.loads(PROVENANCE_STATE.read_text()) if PROVENANCE_STATE.is_file() else {}
    if state.get('day') == day:
        return None
    PROVENANCE_STATE.write_text(json.dumps({'day': day}))
    if run is None:
        import provenance_check
        run = provenance_check.check
    result = run()
    found = result.get('uncommitted') or {}
    if found:
        listed = '; '.join(f"{release}: {', '.join(paths[:3])}" + (f' 외 {len(paths) - 3}개' if len(paths) > 3 else '')
                           for release, paths in found.items())
        board_handoff('provenance', f'운영 버전에 커밋되지 않은 파일 있음(출처 확인 필요, logs/ops/provenance.json): {listed[:220]}')
    else:
        board_close('provenance', f'해결(자동 {now()[11:]} 운영 버전 모두 커밋된 내용)')
    append(ACTIONS, f"{now()} 출처 대조: 미커밋 {sum(len(v) for v in found.values())}개, 자동 닫음 {len(result.get('closed') or [])}줄, "
                    f"남은 출처 모름 {len(result.get('open') or [])}줄")
    return 'warned' if found else 'clean'


ORPHAN_STATE = ROOT / 'logs/ops/orphan-clusters-state.json'


def orphan_clusters(clock=time.time, run=None):
    """Once a day: stop private test clusters a dead test left running (ppid 1, over 6 hours, no clients; PM 11-12).

    Folders are never deleted; those untouched for 7 days are listed on the board line (deleting is the user's
    decision)."""
    day = datetime.fromtimestamp(clock()).strftime('%Y-%m-%d')
    state = json.loads(ORPHAN_STATE.read_text()) if ORPHAN_STATE.is_file() else {}
    if state.get('day') == day:
        return None
    ORPHAN_STATE.write_text(json.dumps({'day': day}))
    if run is None:
        from rehearse_storage_adapter_postgres import stop_orphan_clusters as run
    result = run()
    stopped, kept, old = result.get('stopped') or [], result.get('kept') or [], result.get('old_folders') or []
    if stopped or kept or old:
        parts = []
        if stopped:
            parts.append(f"고아 시험 클러스터 {len(stopped)}개 멈춤({', '.join(Path(r['root']).name for r in stopped)})")
        if kept:
            parts.append(f"연결 있어 남김 {len(kept)}개")
        if old:
            parts.append(f"7일 넘은 폴더 {len(old)}개(삭제는 사용자 결정): {', '.join(Path(f).name for f in old)}")
        board_handoff('orphan_clusters', '; '.join(parts))
    append(ACTIONS, f'{now()} 고아 시험 클러스터: 멈춤 {len(stopped)}, 남김 {len(kept)}, 7일 넘은 폴더 {len(old)}')
    return {'stopped': len(stopped), 'kept': len(kept), 'old_folders': len(old)}


TEST_PYTHON = ROOT / '.venv-tests/bin/python'   # the browser part needs playwright, which only .venv-tests has (11-11)


FULL_CHECK_OVERLAPS_KEPT = 12  # the reasons of the last two hours of deferrals travel with the run's record
# PM 11-15 12:24: on a busy day the check was put off seven times and never ran. After this many deferrals in a row it
# keeps a measurement window on the board (heavy_slot.MEASURE): work already running goes on, but no new heavy run or
# pytest_slot run starts until the check has started and finished; the one daytime heavy slot rule is unchanged.
FULL_CHECK_PRIORITY_AFTER = 3
FULL_CHECK_HOLD_MINUTES = 60          # how long the window waits for running work to end before it lapses


def keep_measurement_window(start, minutes, note, board=None):
    """Write (or move) today's full-check line under '## 측정 전용 시간', creating the section above the rehearsal one.
    Older full-check lines are dropped."""
    import heavy_slot
    board = Path(board or BOARD)   # this module's board (tests point it at a temporary file), the same file as heavy_slot's
    if not board.is_file():
        return False
    end = start + timedelta(minutes=minutes)
    if end.date() != start.date():
        end = start.replace(hour=23, minute=59)
    line = f'- {start:%m-%d %H:%M}~{end:%H:%M} 측정 전용: {note}'
    with heavy_slot.board_lock():
        rows = board.read_text(encoding='utf-8').split('\n')
        rows = [r for r in rows if not (r.startswith('- ') and '측정 전용: 전수 점검' in r)]
        at = next((i for i, r in enumerate(rows) if r.startswith(heavy_slot.MEASURE)), None)
        if at is None:
            before = next((i for i, r in enumerate(rows) if r.startswith(heavy_slot.RESERVED)), len(rows))
            rows[before:before] = [heavy_slot.MEASURE + ' (PM 11-15 12:24, heavy_slot·pytest_slot이 확인: 이 시간엔 전수 점검만 시작, '
                                   '다른 무거운 작업·시험은 exit 75, 운영 감시가 씀)', '']
            at = before
        rows.insert(at + 1, line)
        board.write_text('\n'.join(rows), encoding='utf-8')
    return line


def full_check(clock=time.time, launch=None, free=None, window=None):
    """Every two hours: run scripts/public_full_check.py through heavy_slot (it drives a browser).

    11-13 PM 10:21: never forced. The 10:19 run went ahead after two deferrals beside tests and a deploy and read
    84.8%. Now an overlap (tests, a deploy, a full heavy slot, the :55-:10 measurement window) only puts the run off
    to the next watch (ten minutes later) and keeps the reasons; the run starts at the first free watch and its
    record carries how often and why it waited. Nothing is excluded from the result."""
    state = json.loads(FULL_CHECK_STATE.read_text()) if FULL_CHECK_STATE.is_file() else {}
    if clock() - state.get('started', 0) < FULL_CHECK_EVERY:
        return None
    import heavy_slot
    reason = busy()
    if free is None:
        lines = heavy_slot.BOARD.read_text(encoding='utf-8').split('\n') if heavy_slot.BOARD.is_file() else []
        live = [line for _, line, ok in heavy_slot.entries(lines) if ok]
        free = len(live) < heavy_slot.slots()
    if window is None:   # heavy_slot would refuse inside it and the two-hour turn would be lost
        window = heavy_slot.measurement_window(datetime.fromtimestamp(clock()))
    deferred = int(state.get('deferred') or 0)
    overlaps = list(state.get('overlaps') or [])
    why = reason or (None if free else '무거운 작업 칸이 모두 참') or (window and '매시 측정 시간(:55~:10)')
    if why and deferred + 1 >= FULL_CHECK_PRIORITY_AFTER and clock() >= state.get('held_until', 0):
        keep_measurement_window(datetime.fromtimestamp(clock()), FULL_CHECK_HOLD_MINUTES,
                                f'전수 점검(운영·SRE) {deferred + 1}번 밀림 → 진행 중인 작업이 끝나면 먼저 실행')
        state['held_until'] = clock() + FULL_CHECK_HOLD_MINUTES * 60
    if why:
        state['deferred'] = deferred + 1
        state['overlaps'] = (overlaps + [f'{datetime.fromtimestamp(clock()):%H:%M} {why}'])[-FULL_CHECK_OVERLAPS_KEPT:]
        FULL_CHECK_STATE.write_text(json.dumps(state, ensure_ascii=False))
        board_handoff('full_check_deferred', f'전수 점검(public_full_check) 2시간 주기 실행을 미룸: {why} '
                                             f'({deferred + 1}번째). 겹친 채 강제 실행하지 않고 10분 뒤 빈 시간에 다시 시도')
        append(ACTIONS, f'{now()} public_full_check 미룸: {why}')
        return 'deferred'
    FULL_CHECK_STATE.write_text(json.dumps({'started': clock(), 'deferred': 0}))
    if clock() < state.get('held_until', 0):   # keep the quiet until the check is done, then the window lapses
        keep_measurement_window(datetime.fromtimestamp(clock()), FULL_CHECK_MINUTES + 5,
                                f'전수 점검(운영·SRE) 실행 중({deferred}번 밀린 뒤)')
    log = (ROOT / 'logs/ops/public-full-check.out').open('a')
    check = [str(TEST_PYTHON), str(ROOT / 'scripts/public_full_check.py')]
    env = dict(os.environ)
    if deferred:
        env['AGENTCON_RUN_CONTEXT'] = json.dumps({'deferred_before': deferred, 'overlaps': overlaps,
                                                  'load_1': round(os.getloadavg()[0], 2)}, ensure_ascii=False)
    command = [str(ROOT / '.venv/bin/python'), '-m', 'scripts.heavy_slot', '--team', '운영·SRE',
               '--what', 'public_full_check (ops_auto 2시간)', '--minutes', str(FULL_CHECK_MINUTES), '--'] + check
    (launch or subprocess.Popen)(command, cwd=ROOT, stdout=log, stderr=log, start_new_session=True, env=env)
    board_close('full_check_deferred', f'해결(자동 {now()[11:]} 빈 시간에 실행 시작' + (f', {deferred}번 미룬 뒤)' if deferred else ')'))
    append(ACTIONS, f'{now()} public_full_check 시작' + (f' (미룸 {deferred}번 뒤)' if deferred else '')
           + (f' (다른 프로젝트 시험 {len(OTHER_LOAD)}개 실행 중: 부하 있음)' if OTHER_LOAD else ''))
    return 'started'


GATE_STATE = ROOT / 'logs/ops/stability-gate-state.json'


def stability_gate(clock=time.time):
    """Hourly: judge the stability gate (scripts/stability_gate.py) and refresh its line at the top of the board."""
    hour = datetime.fromtimestamp(clock()).strftime('%Y-%m-%d %H')
    state = json.loads(GATE_STATE.read_text()) if GATE_STATE.is_file() else {}
    if state.get('hour') == hour:
        return None
    import stability_gate as gate  # scripts/ is on sys.path
    result = gate.judge()
    gate.OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    gate.update_board(gate.board_line(result))
    GATE_STATE.write_text(json.dumps({'hour': hour, 'open': result['open']}))
    if gate.record_met(result):   # 11-14 09:4x: an operating measure only (the switch is already on)
        append(ACTIONS, f'{now()} 결제 안정 기준 충족(운영 지표, 3/3일·결제 흐름 시험 통과): PM에 기록으로 알림')
    return result['open']


REALERT_SECONDS = 1800


def signature(kind, value):
    """What makes an alert of KIND the same alert (11-15 PM: plist_missing turning into not_running was held back
    because only the kind was compared). Counters that grow every run (minutes held, sizes) are left out."""
    if isinstance(value, dict) and 'problems' in value:
        return sorted(map(str, value.get('problems') or []))
    if kind == 'launchd_jobs':
        return sorted((item.get('label'), item.get('status')) for item in value or [])
    if kind == 'site':
        return sorted((item.get('url'), str(item.get('status'))) for item in value or [])
    if kind == 'deploy_lock':
        return (value or {}).get('line')
    if kind in ('core_down',):
        return sorted(value or [])
    if kind in ('long_tests', 'deploy_stuck'):
        return sorted(str(item.get('pid')) for item in value or [])
    return None   # memory, swap, disk, stale_handoffs: the kind alone


def is_down(kind, value):
    """A service is off: alerted every run, never held back, and written to the desktop file."""
    if kind == 'core_down':
        return bool(value)
    return isinstance(value, dict) and 'not_running' in (value.get('problems') or [])


CLOSE_WHEN_CLEAR = ('fingerprints', 'backup', 'necklace_checks', 'launchd_jobs', 'core_down', 'memory', 'disk', 'swap')


def select_fresh(anomalies, state, now):
    """(fresh, state): an anomaly is alerted when it is new, when its signature changed (it got worse or
    different), when it means a service is down, or when REALERT_SECONDS passed since its last alert. Cleared
    kinds leave the state so they alert again when they come back. Old states held a bare time per kind."""
    new_state, fresh = {}, {}
    for kind, value in anomalies.items():
        before = state.get(kind)
        if not isinstance(before, dict):
            before = {'at': before or 0, 'sig': None} if before else None
        sig = json.loads(json.dumps(signature(kind, value)))   # as stored: tuples become lists
        due = (before is None or is_down(kind, value) or sig != before.get('sig')
               or now - before.get('at', 0) > REALERT_SECONDS)
        if due:
            fresh[kind] = value
            new_state[kind] = {'at': now, 'sig': sig}
        else:
            new_state[kind] = before
    return fresh, new_state


def watch():
    try:
        board_snapshot()
    except Exception as error:  # noqa: BLE001
        append(ACTIONS, f'{now()} 현황판 사본 실패: {type(error).__name__}')
    try:
        edge_transitions()
    except Exception as error:  # noqa: BLE001
        append(ACTIONS, f'{now()} 엣지 전환 알림 실패: {type(error).__name__}')
    try:
        stale_handoffs()
    except Exception as error:  # noqa: BLE001
        append(ACTIONS, f'{now()} 오래된 대기 줄 확인 실패: {type(error).__name__}')
    try:
        north_star()
    except Exception as error:  # noqa: BLE001
        append(ACTIONS, f'{now()} 북극성 집계 실패: {type(error).__name__}')
    try:
        answer_set_expiry()
    except Exception as error:  # noqa: BLE001
        append(ACTIONS, f'{now()} 정답 세트 유효기간 확인 실패: {type(error).__name__}')
    try:
        holiday_truth()
    except Exception as error:  # noqa: BLE001
        append(ACTIONS, f'{now()} 공휴일 정답 받기 실패: {type(error).__name__}')
    try:
        revenue_funnel()
    except Exception as error:  # noqa: BLE001
        append(ACTIONS, f'{now()} 매출 깔때기 집계 실패: {type(error).__name__}')
    try:
        review_queue()
    except Exception as error:  # noqa: BLE001
        append(ACTIONS, f'{now()} 심사 대기 확인 실패: {type(error).__name__}')
    try:
        refunds_due()
    except Exception as error:  # noqa: BLE001
        append(ACTIONS, f'{now()} 환불 대기 확인 실패: {type(error).__name__}')
    try:
        vector_index_usage()
    except Exception as error:  # noqa: BLE001
        append(ACTIONS, f'{now()} 벡터 인덱스 사용 기록 실패: {type(error).__name__}')
    try:
        user_slo()
    except Exception as error:  # noqa: BLE001 - the 10-minute watch must keep running
        append(ACTIONS, f'{now()} user_slo 실패: {type(error).__name__}')
    try:
        real_task_score()
    except Exception as error:  # noqa: BLE001
        append(ACTIONS, f'{now()} real_task_score 실패: {type(error).__name__}')
    try:
        error_ledger()
    except Exception as error:  # noqa: BLE001
        append(ACTIONS, f'{now()} 오류 장부 실패: {type(error).__name__}')
    try:
        outside_load()
    except Exception as error:  # noqa: BLE001
        append(ACTIONS, f'{now()} 다른 프로젝트 부하 확인 실패: {type(error).__name__}')
    try:
        ad_coin_ledger()
    except Exception as error:  # noqa: BLE001
        append(ACTIONS, f'{now()} AD Coin 원장 보존 검사 실패: {type(error).__name__}')
    try:
        provenance()
    except Exception as error:  # noqa: BLE001
        append(ACTIONS, f'{now()} 출처 대조 실패: {type(error).__name__}')
    try:
        payment_flow()
    except Exception as error:  # noqa: BLE001
        append(ACTIONS, f'{now()} 결제 흐름 시험 실패: {type(error).__name__}')
    try:
        orphan_clusters()
    except Exception as error:  # noqa: BLE001
        append(ACTIONS, f'{now()} 고아 시험 클러스터 정리 실패: {type(error).__name__}')
    try:
        full_check()
    except Exception as error:  # noqa: BLE001
        append(ACTIONS, f'{now()} public_full_check 실패: {type(error).__name__}')
    try:
        stability_gate()
    except (Exception, SystemExit) as error:  # noqa: BLE001
        append(ACTIONS, f'{now()} 안정성 관문 판정 실패: {type(error).__name__}')
    record = json.loads(subprocess.run([sys.executable, str(ROOT / 'scripts/ops_watch.py')],
                                       capture_output=True, text=True, cwd=ROOT).stdout or '{}')
    anomalies = record.get('anomalies') or {}
    state = json.loads(STATE.read_text()) if STATE.is_file() else {}
    before = dict(state)
    fresh, state = select_fresh(anomalies, state, time.time())
    # 11-15 16:2x (PM): a state check that comes back clean closes its own open board line, so a fixed alarm
    # (the 34-hour fingerprint line stayed '대기' after the 16:16 refresh) never needs a person to close it.
    for kind in CLOSE_WHEN_CLEAR:
        if kind in before and kind not in anomalies:
            board_close(kind, f'해결(자동 {now()[11:]} 이상 없음)')
    if not fresh:
        STATE.write_text(json.dumps(state))
        return 0
    wording = ops_llm.ask(ALERT_SYSTEM, json.dumps(fresh, ensure_ascii=False), 'watch_alert', max_tokens=400)
    text = ' / '.join(line.strip() for line in (wording or '').splitlines() if line.strip()) or \
        ', '.join(f'{k}: {json.dumps(v, ensure_ascii=False)[:120]}' for k, v in fresh.items())
    urgent = any(k in fresh for k in ('site', 'memory', 'disk', 'core_down', 'backup')) or \
        any(is_down(k, v) for k, v in fresh.items())
    if urgent:
        prepend_desktop(f'{now()} [운영 이상] {text}')
    for kind in fresh:
        board_handoff(kind, text)
    append(ACTIONS, f'{now()} {",".join(fresh)} → 현황판 넘기는 일{" + 바탕화면" if urgent else ""}: {text[:200]}')
    STATE.write_text(json.dumps(state))
    return 0


# 11-15 12:5x: three sessions' shells looping on 'pytest_slot ... refused' (waiting for the measurement hour to end)
# held the full check itself off. A running test is its python process, which is listed on its own line.
SHELL_WRAPPER = re.compile(r'^\S*/?(zsh|bash|sh) (-\S+ )*-c ')
OURS = ('A2A_Discovery', 'A2A-Discovery')   # this project and its scratch worktrees
OTHER_LOAD: list[str] = []                 # other projects' tests seen by the last busy() (noted, never waited on)


def _cwd(pid):
    out = subprocess.run(['lsof', '-a', '-p', str(pid), '-d', 'cwd', '-Fn'], capture_output=True, text=True).stdout
    return next((line[1:] for line in out.splitlines() if line.startswith('n')), '')


def _ours(pid, args):
    """11-15: the freight TMS project on this Mac runs pytest and playwright for hours; matching the bare word
    'pytest' put the full check off 18 times in a row. A test belongs to us when its command or working folder is
    this project (or one of its scratch worktrees); a command naming another workspace is not ours."""
    if any(mark in args for mark in OURS):
        return True
    if '/workspace/' in args:
        return False
    if not pid:
        return True                                   # unknown: keep waiting, as before
    folder = _cwd(pid)
    return not folder or any(mark in folder for mark in OURS)


def busy():
    procs = subprocess.run(['ps', '-axww', '-o', 'pid=,args='], capture_output=True, text=True).stdout
    # 11-13: 'service_deploy reclaim-standby --after 1800' only sleeps for 30 minutes after a deploy before it stops
    # the old slot; counting it as a deploy put every check off for half an hour after each switch.
    OTHER_LOAD.clear()
    for line in procs.splitlines():
        if 'reclaim-standby' in line or not any(w in line for w in ('pytest', 'scripts.service_deploy', 'release_gate')):
            continue
        head, _, rest = line.strip().partition(' ')
        pid, args = (int(head), rest) if head.isdigit() else (None, line)
        if SHELL_WRAPPER.match(args):
            continue      # a session's shell whose script mentions pytest (often a retry loop waiting for this check)
        if _ours(pid, args):
            return 'tests_or_deploy_running'
        OTHER_LOAD.append(args[:80])
    if (ops_watch.check_memory() or 100) < 15:
        return 'memory_low'
    return None


def query(sql):
    """Counts for the test-report summary. The session is read-only (11-15 PM audit: the watch never writes the
    production database), with a short statement and lock limit."""
    env = {**os.environ, 'PGOPTIONS': '-c default_transaction_read_only=on -c statement_timeout=15000 -c lock_timeout=1000'}
    return subprocess.run(PSQL + [sql], capture_output=True, text=True, env=env).stdout.strip()


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
    raise SystemExit({'watch': watch, 'test-reports': test_reports, 'board-snapshot': lambda: board_snapshot() and 0,
                     'real-task-run': lambda: real_task_run(sys.argv[2])}.get(command, lambda: 2)())
