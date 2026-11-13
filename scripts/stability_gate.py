#!/usr/bin/env python3
"""Stability gate: judge each KST day on four measures and show the streaks at the top of the status board (11-11).

    .venv/bin/python -m scripts.stability_gate            # judge, write logs/ops/stability-gate.json, update the board
    .venv/bin/python -m scripts.stability_gate --dry-run  # print only

The user decided on 11-11 that internal stability comes before advertisers. The gate opens when all four hold:
- user_slo (scripts/user_slo.py, hourly): 7 days in a row where no run had a breach and at least MIN_SLO_RUNS ran;
- public full check (scripts/public_full_check.py): 3 days in a row with at least one run and no failed check;
- real tasks (scripts/real_task_score.py): the latest scored day passed at least TASK_TARGET of 30;
- error ledger (scripts/error_ledger.py): yesterday has no unexplained error.
A day is judged only once it is over; today is shown as "in progress" and never breaks or extends a streak.
A missing record counts as a failed day: nothing passes by not being measured.
"""
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:  # run as python -m scripts.<name> or as a file
    from scripts.slo_targets import FINAL, INTERIM, attainment
except ImportError:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from slo_targets import FINAL, INTERIM, attainment

ROOT = Path(__file__).resolve().parents[1]
OPS = ROOT / 'logs/ops'
BOARD = OPS / 'status-board.md'
OUT = OPS / 'stability-gate.json'
KST = timezone(timedelta(hours=9))
SLO_DAYS, FULL_DAYS, TASK_TARGET = 7, 3, 27
MIN_SLO_RUNS = 12          # hourly runs; fewer means the day was not really measured
MARK = '> **[안정성 관문'


def _rows(path):
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def _day(at):
    """KST day of a record time: 'YYYY-MM-DD HH:MM' is already local; ISO with an offset is converted."""
    text = str(at or '')
    if 'T' in text:
        try:
            return datetime.fromisoformat(text).astimezone(KST).strftime('%Y-%m-%d')
        except ValueError:
            return None
    return text[:10] or None


def slo_days(rows):
    days = {}
    for r in rows:
        day = _day(r.get('at'))
        if day:
            runs, bad = days.get(day, (0, 0))
            days[day] = (runs + 1, bad + (1 if r.get('breaches') else 0))
    return {d: {'ok': bad == 0 and runs >= MIN_SLO_RUNS, 'runs': runs, 'breached_runs': bad}
            for d, (runs, bad) in days.items()}


def interim_days(rows):
    """user_slo days against the interim target (11-14), recomputed from the recorded samples so earlier runs count."""
    days = {}
    for r in rows:
        day = _day(r.get('at'))
        if day:
            runs, bad = days.get(day, (0, 0))
            days[day] = (runs + 1, bad + (0 if attainment(r, INTERIM)['ok'] else 1))
    return {d: {'ok': bad == 0 and runs >= MIN_SLO_RUNS, 'runs': runs, 'failed_runs': bad} for d, (runs, bad) in days.items()}


def slo_rates(rows, today, days=7):
    """Share of runs and of timed samples within the final and the interim target over the last `days` days."""
    first = (datetime.strptime(today, '%Y-%m-%d') - timedelta(days=days - 1)).strftime('%Y-%m-%d')
    recent = [r for r in rows if (_day(r.get('at')) or '') >= first]
    out = {'days': days, 'runs': len(recent)}
    for name, targets in (('final', FINAL), ('interim', INTERIM)):
        judged = [attainment(r, targets) for r in recent]
        good = sum(sum(p['passed'] for p in j['parts'].values()) for j in judged)
        total = sum(sum(p['n'] for p in j['parts'].values()) for j in judged)
        out[name] = {'run_rate': round(sum(j['ok'] for j in judged) / len(judged), 3) if judged else None,
                     'sample_rate': round(good / total, 3) if total else None}
    return out


def full_days(rows):
    days = {}
    for r in rows:
        day = _day(r.get('at'))
        if day:
            runs, failed = days.get(day, (0, 0))
            days[day] = (runs + 1, failed + int(r.get('failed') or 0))
    return {d: {'ok': runs > 0 and failed == 0, 'runs': runs, 'failed': failed} for d, (runs, failed) in days.items()}


def task_latest(rows):
    scored = [r for r in rows if _day(r.get('at'))]
    if not scored:
        return None
    last = max(scored, key=lambda r: str(r['at']))
    return {'day': _day(last['at']), 'passed': last.get('passed', 0), 'tasks': last.get('tasks', 30),
            'ok': int(last.get('passed') or 0) >= TASK_TARGET}


def ledger_day(day, folder=None):
    path = Path(folder or OPS / 'error-ledger') / f'{day}.json'
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {'day': day, 'ok': False, 'unexplained': None}
    return {'day': day, 'ok': data.get('unexplained') == 0, 'unexplained': data.get('unexplained')}


def streak(judged, today):
    """Consecutive passing days ending yesterday; a day without a record breaks the streak."""
    count, day = 0, datetime.strptime(today, '%Y-%m-%d') - timedelta(days=1)
    while judged.get(day.strftime('%Y-%m-%d'), {}).get('ok'):
        count += 1
        day -= timedelta(days=1)
    return count


def judge(today=None, ops=None):
    ops = Path(ops or OPS)
    today = today or datetime.now(KST).strftime('%Y-%m-%d')
    yesterday = (datetime.strptime(today, '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d')
    slo_rows = _rows(ops / 'user-slo.jsonl')
    slo = slo_days(slo_rows)
    interim = interim_days(slo_rows)
    full = full_days(_rows(ops / 'public-full-check.jsonl'))
    task = task_latest(_rows(ops / 'real-task-score.jsonl'))
    ledger = ledger_day(yesterday, ops / 'error-ledger')
    result = {
        'judged_at': datetime.now(KST).strftime('%Y-%m-%d %H:%M'), 'today': today,
        'user_slo': {'streak': streak(slo, today), 'need': SLO_DAYS, 'today': slo.get(today)},
        'full_check': {'streak': streak(full, today), 'need': FULL_DAYS, 'today': full.get(today)},
        'real_tasks': task or {'ok': False, 'passed': None, 'tasks': 30},
        'error_ledger': ledger,
    }
    result['user_slo']['ok'] = result['user_slo']['streak'] >= SLO_DAYS
    # 11-14: reported beside the gate, never part of it (the gate opens on the final target only).
    result['user_slo_interim'] = {'streak': streak(interim, today), 'need': SLO_DAYS, 'today': interim.get(today)}
    result['user_slo_interim']['ok'] = result['user_slo_interim']['streak'] >= SLO_DAYS
    result['slo_rates'] = slo_rates(slo_rows, today)
    result['full_check']['ok'] = result['full_check']['streak'] >= FULL_DAYS
    result['open'] = all(result[k]['ok'] for k in ('user_slo', 'full_check', 'real_tasks', 'error_ledger'))
    return result


def pct(r, name):
    rate = ((r.get('slo_rates') or {}).get(name) or {}).get('run_rate')
    return '-' if rate is None else f"{round(rate * 100)}%"


def board_line(r):
    def mark(ok):
        return '통과' if ok else '미달'
    task = r['real_tasks']
    ledger = r['error_ledger']
    unexplained = '장부 없음' if ledger['unexplained'] is None else f"{ledger['unexplained']}건"
    return (f"{MARK} {r['judged_at']} 자동 판정: {'열림' if r['open'] else '닫힘'}]** "
            f"user_slo {r['user_slo']['streak']}/{SLO_DAYS}일({mark(r['user_slo']['ok'])}) · "
            f"차선 목표 user_slo {r.get('user_slo_interim', {}).get('streak', 0)}/{SLO_DAYS}일 · "
            f"7일 달성률 최종 {pct(r, 'final')}·차선 {pct(r, 'interim')} · "
            f"전수 점검 실패 0 {r['full_check']['streak']}/{FULL_DAYS}일({mark(r['full_check']['ok'])}) · "
            f"실제 과제 {task.get('passed')}/{task.get('tasks')}(목표 {TASK_TARGET}, {mark(task['ok'])}) · "
            f"설명되지 않은 오류 {ledger['day']} {unexplained}({mark(ledger['ok'])}). "
            f"관문 전에는 USDC 스위치·유치·새 기능 동결(11-11 사용자 결정). 기록 logs/ops/stability-gate.json")


def update_board(line, board=None):
    """Replace our line, or put it right under the board title. Holds the heavy_slot board lock."""
    try:
        from scripts.heavy_slot import board_lock
    except ImportError:   # run from scripts/ (ops_auto puts that folder on sys.path)
        from heavy_slot import board_lock
    board = Path(board or BOARD)
    with board_lock():
        lines = board.read_text(encoding='utf-8').split('\n')
        ours = [i for i, text in enumerate(lines) if text.startswith(MARK)]
        if len(ours) > 1:
            raise SystemExit('stability_gate: more than one gate line on the board; fix it by hand')
        if ours:
            lines[ours[0]] = line
        else:
            title = next((i for i, text in enumerate(lines) if text.startswith('# ')), -1)
            lines[title + 1:title + 1] = ['', line]
        board.write_text('\n'.join(lines), encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    result = judge()
    line = board_line(result)
    print(line)
    if not args.dry_run:
        OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1))
        update_board(line)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
