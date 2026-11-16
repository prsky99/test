"""Value-driver board, one line a day (PM 11-16 21:13, 운영·SRE; due 11-18).

    .venv/bin/python -m scripts.value_drivers [--day YYYY-MM-DD] [--no-db]

Seven numbers, our own tests and automatic repeats left out wherever the source can tell them apart:
  public_necklaces      necklaces offered now (necklace_surface.live: live, gate passed, two answering members,
                        delta > 0, retested within 48 h)
  external_successes    necklace runs that succeeded for someone else on DAY (north_star.day_metric: source
                        external only, our origins - retest, watch, gate, qa, user_slo, public_check, growth_check,
                        rehearsal - and runs without request meta are never counted)
  first_usdc_payment    the first confirmed USDC payment (KST time) and confirmed payments in all; counts only
  returning_cohorts     visitors first seen each week (KST, Monday) and how many came back on another day; agent
                        visitors only (a hashed id is the one thing kept across days, 11-10), our 'internal'
                        measurements and the admin test channel left out
  usable_pearls         distinct external pearl members whose terms are allowed or silent (model.terms_status)
  interim_speed         of the last 24 hourly user_slo runs, how many met every interim target (explore 3 s,
                        recommend 5 s, page 3 s; one slow sample fails the run). The 11-30 aim is 12 of 24
  real_task             the last real_task_score run (aim 27/30)
user_slo and real_task_score are our own measurements by design (X-Agentcon-QA); they measure what a user sees.

Appends one JSON line to logs/ops/value-drivers.jsonl and prints it; --no-db skips the production read (tests).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'logs/ops/value-drivers.jsonl'
SLO = ROOT / 'logs/ops/user-slo.jsonl'
REAL_TASK = ROOT / 'logs/ops/real-task-score.jsonl'
NECKLACES = ROOT / 'gateway-data/necklaces'
SQL = ROOT / 'deploy/ops/value-drivers.sql'
KST = timezone(timedelta(hours=9))
SPEED_RUNS = 24
SPEED_AIM = 12   # PM 11-16: 12 of the last 24 runs pass every interim target by 11-30
REAL_TASK_AIM = 27


def _jsonl_tail(path, n):
    try:
        lines = Path(path).read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        return []
    out = []
    for raw in lines[-max(n * 3, n):]:
        try:
            out.append(json.loads(raw))
        except ValueError:
            continue
    return out[-n:]


def public_necklaces(root=NECKLACES):
    from agent_market.concierge import necklace_surface
    path = Path(root) / 'necklaces.json'
    if not path.is_file():   # source review C15: not measured is never written as 0
        return {'value': None, 'unmeasured': 'no necklaces.json'}
    try:
        snapshot = necklace_surface.load(path)
    except Exception:
        return {'value': None, 'unmeasured': 'snapshot unreadable'}
    live = necklace_surface.live(snapshot)
    return {'value': len(live), 'slugs': sorted(e.get('slug') for e in live)}


def external_successes(day, root=NECKLACES):
    from agent_market.necklaces import north_star
    runs = Path(root) / 'runs'
    date = datetime.strptime(day, '%Y-%m-%d')
    names = {(date - timedelta(days=1)).strftime('%Y%m%d'), date.strftime('%Y%m%d')}
    if not any((runs / f'{n}.jsonl').is_file() for n in names):   # C15: no run file is "not measured", not 0
        return {'value': None, 'unmeasured': 'no run file for the day', 'day': day}
    metric = north_star.day_metric(runs, day)
    return {k: metric.get(k) for k in ('value', 'failed', 'cached', 'our_capacity') if k in metric} | {'day': day}


def usable_pearls(members_file=None):
    from agent_market.necklaces.model import USABLE_TERMS, terms_status
    path = Path(members_file or NECKLACES / 'members.json')
    try:
        members = json.loads(path.read_text(encoding='utf-8')).get('members') or []
    except (OSError, ValueError):
        return {'value': None, 'error': 'members.json unreadable'}
    usable, standing = set(), {}
    for m in members:
        if not isinstance(m, dict) or not m.get('pearl') or m.get('kind') != 'external' or m.get('resource_id') is None:
            continue
        if terms_status(m) in USABLE_TERMS:
            usable.add(m['resource_id'])
            standing[m['resource_id']] = m.get('standing') or 'unknown'
    by = {}
    for s in standing.values():
        by[s] = by.get(s, 0) + 1
    return {'value': len(usable), 'by_standing': dict(sorted(by.items()))}


def interim_speed(path=SLO, runs=SPEED_RUNS):
    rows = _jsonl_tail(path, runs)
    passed = sum(1 for r in rows if ((r.get('attainment') or {}).get('interim') or {}).get('ok') is True)
    return {'value': passed, 'runs': len(rows), 'aim': SPEED_AIM, 'met': passed >= SPEED_AIM and len(rows) >= runs,
            'last_at': rows[-1].get('at') if rows else None}


def real_task(path=REAL_TASK):
    rows = _jsonl_tail(path, 1)
    if not rows:
        return {'value': None}
    r = rows[-1]
    return {'value': r.get('passed'), 'tasks': r.get('tasks'), 'aim': REAL_TASK_AIM, 'at': r.get('at')}


def parse_sql(text):
    """The rows of value-drivers.sql ('label|a|b|c') as {'first_usdc_payment': ..., 'returning_cohorts': [...]}."""
    payment, cohorts = None, []
    for line in text.splitlines():
        parts = line.split('|')
        if len(parts) != 4:
            continue
        label, a, b, c = parts
        if label == 'payment':
            first = int(float(a)) if a.strip() else None
            payment = {'value': int(b or 0),
                       'first_at': datetime.fromtimestamp(first / 1000, KST).strftime('%Y-%m-%d %H:%M') if first else None}
        elif label == 'cohort':
            cohorts.append({'week': a, 'visitors': int(b or 0), 'returned_other_day': int(c or 0)})
    return {'first_usdc_payment': payment, 'returning_cohorts': cohorts}


def db_part(run=subprocess.run):
    result = run([sys.executable, '-m', 'scripts.prod_ro_sql', str(SQL)], cwd=ROOT, capture_output=True, text=True,
                 timeout=120)
    if result.returncode != 0:
        return {'db_error': (result.stderr or result.stdout).strip()[:200]}
    return parse_sql(result.stdout)


def collect(day, with_db=True):
    line = {'at': datetime.now(KST).strftime('%Y-%m-%d %H:%M'), 'day': day,
            'public_necklaces': public_necklaces(),
            'external_successes': external_successes(day),
            'usable_pearls': usable_pearls(),
            'interim_speed': interim_speed(),
            'real_task': real_task()}
    if with_db:
        line.update(db_part())
    return line


def summary(line):
    """One board line in Korean (the board is for people)."""
    pay = line.get('first_usdc_payment') or {}
    cohorts = line.get('returning_cohorts') or []
    last = cohorts[-2] if len(cohorts) >= 2 else (cohorts[-1] if cohorts else None)   # the last full week
    speed, rt = line['interim_speed'], line['real_task']
    def shown(value):
        return '미측정' if value is None else value

    parts = [
        f"공개 목걸이 {shown(line['public_necklaces'].get('value'))}",
        f"외부 실행 성공 {shown(line['external_successes'].get('value'))}({line['day']})",
        ('첫 USDC ' + pay['first_at']) if pay.get('first_at') else ('첫 USDC 없음' if pay else '첫 USDC 읽기 실패'),
        (f"재방문 {last['returned_other_day']}/{last['visitors']}(주 {last['week']})" if last else '재방문 자료 없음'),
        f"사용 가능 진주 {shown(line['usable_pearls'].get('value'))}",
        (f"차선 속도 {speed['value']}/{speed['runs']}(목표 {speed['aim']})" if speed['runs'] else '차선 속도 미측정'),
        (f"real_task {rt.get('value')}/{rt.get('tasks')}(목표 {rt.get('aim')})" if rt.get('value') is not None else 'real_task 미측정'),
    ]
    return ' · '.join(parts)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--day', default=None, help='KST day for external successes (default: yesterday)')
    parser.add_argument('--no-db', action='store_true')
    parser.add_argument('--no-write', action='store_true')
    args = parser.parse_args(argv)
    day = args.day or (datetime.now(KST) - timedelta(days=1)).strftime('%Y-%m-%d')
    line = collect(day, with_db=not args.no_db)
    line['summary'] = summary(line)
    if not args.no_write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with OUT.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + '\n')
    print(json.dumps(line, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
