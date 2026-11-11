#!/usr/bin/env python3
"""Daily error ledger: every error of one KST day counted by cause, unexplained ones flagged (11-11).

    .venv/bin/python -m scripts.error_ledger                 # yesterday (KST)
    .venv/bin/python -m scripts.error_ledger --day 2026-11-11

Sources (read only):
- service logs (logs/services/*.log): ERROR lines and tracebacks, by logger and normalized message;
- gateway executions: 'Execution failure ... code=X' warnings, by code;
- edge delivery: edge_gateway_events outcomes 'error:*' and Origin fallbacks 'origin:*', by code;
- the AD Coin worker daemon log.
An entry is explained when a pattern in logs/ops/error-ledger-known.json matches its key; the file
holds the reason and the team, so an explanation is a reviewed decision, not a guess. The ledger is
written to logs/ops/error-ledger/<day>.json and .md; the stability gate reads the unexplained count.
"""
import argparse
import json
import re
import subprocess
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / 'logs/services'
KNOWN = ROOT / 'logs/ops/error-ledger-known.json'
OUT = ROOT / 'logs/ops/error-ledger'
KST = timezone(timedelta(hours=9))
PSQL = ['/opt/homebrew/opt/postgresql@18/bin/psql', '-h', str(ROOT / 'gateway-data/postgres18/run'), '-p', '55432',
        '-d', 'agentcon_cutover_20261020_191757', '-At', '-F', '|', '-c']
_LINE = re.compile(r'^(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2} (ERROR|CRITICAL) ([\w.]+): (.*)$')
_FAILURE = re.compile(r'^(\d{4}-\d{2}-\d{2}) .*Execution failure reference=\S+ resource_id=\S+ protocol=(\w+) code=(\w+) stage=(\w+)'
                      r'(?:.*? qa=([a-z][a-z0-9_]*))?')
INTERNAL = 'qa|'   # our own measurement requests (X-Agentcon-QA, 11-11 PM): counted on their own rows, not hidden
_TRACE = re.compile(r'^(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2} \w+ ([\w.]+): .*')


def normalize(text):
    """A stable cause key: ids, numbers, addresses and quoted values are folded away."""
    text = re.sub(r'https?://\S+', '<url>', text)
    text = re.sub(r'"[^"]{0,200}"', '"…"', text)
    text = re.sub(r'\b[0-9a-f]{8,}\b', '<id>', text)
    text = re.sub(r'\d+(\.\d+)?', 'N', text)
    return re.sub(r'\s+', ' ', text).strip()[:140]


def from_logs(day, logs=None):
    counts = Counter()
    for path in sorted(Path(logs or LOGS).glob('*.log')):
        role = path.name.split('.')[-2] if path.name.count('.') >= 2 else path.stem
        try:
            lines = path.read_text(errors='replace').splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines):
            if not line.startswith(day):
                continue
            failure = _FAILURE.match(line)
            if failure:
                key = f'gateway|{failure.group(2)}|{failure.group(3)}|{failure.group(4)}'
                counts[(f'{INTERNAL}{failure.group(5)}|' if failure.group(5) else '') + key] += 1
                continue
            match = _LINE.match(line)
            if not match:
                continue
            logger, message = match.group(3), match.group(4)
            if logger == 'uvicorn.access':
                path_match = re.search(r'"(\w+) (\S+?)(?:\?\S*)? HTTP/[\d.]+" (\d{3})', message)
                message = f'{path_match.group(1)} {normalize(path_match.group(2))} {path_match.group(3)}' if path_match else normalize(message)
            else:
                message = normalize(message)
            exception = ''
            for follow in lines[i + 1:i + 40]:          # the exception class closes a following traceback
                if re.match(r'^\d{4}-\d{2}-\d{2} ', follow):
                    break
                last = re.match(r'^([\w.]+(?:Error|Exception|Timeout|Busy|Failed)\w*)(?::|$)', follow)
                if last:
                    exception = last.group(1)
            counts[f'log|{role}|{logger}|{message}' + (f'|{exception}' if exception else '')] += 1
    return counts


def from_edge(day, run=None):
    start = datetime.strptime(day, '%Y-%m-%d').replace(tzinfo=KST).timestamp()
    sql = ("SELECT outcome, count(*) FROM edge_gateway_events WHERE substr(run_id,1,3)='eo_' "
           f"AND recorded >= {start} AND recorded < {start + 86400} "
           "AND (outcome LIKE 'error:%' OR outcome LIKE 'origin:%') GROUP BY 1")
    try:
        out = (run or (lambda q: subprocess.run(PSQL + [q], capture_output=True, text=True, timeout=60).stdout))(sql)
    except Exception as error:   # the ledger still reports what it could read
        return Counter({f'ledger|edge_unreadable|{type(error).__name__}': 1})
    counts = Counter()
    for line in out.splitlines():
        if '|' in line:
            outcome, n = line.rsplit('|', 1)
            counts['edge|' + outcome] += int(n)
    return counts


def explain(counts, known=None, day=None):
    """A rule with 'until' (a fixed bug) explains only days up to that date; a later return is unexplained."""
    rules = known if known is not None else (json.loads(KNOWN.read_text()) if KNOWN.is_file() else [])
    rows = []
    for key, n in counts.most_common():
        if key.startswith(INTERNAL):
            rows.append({'key': key, 'count': n, 'explained': True, 'internal': True,
                         'reason': '내부 측정 요청(X-Agentcon-QA)', 'team': '측정 도구 주인'})
            continue
        rule = next((r for r in rules if re.search(r['pattern'], key)
                     and not (day and r.get('until') and day > r['until'])), None)
        rows.append({'key': key, 'count': n, 'explained': bool(rule),
                     **({'reason': rule['reason'], 'team': rule.get('team', '운영·SRE')} if rule else {})})
    return rows


def ledger(day, counts=None, known=None):
    counts = counts if counts is not None else from_logs(day) + from_edge(day)
    rows = explain(counts, known, day)
    unexplained = [r for r in rows if not r['explained']]
    internal = sum(r['count'] for r in rows if r.get('internal'))
    return {'day': day, 'total': sum(r['count'] for r in rows), 'kinds': len(rows), 'internal': internal,
            'unexplained_kinds': len(unexplained), 'unexplained': sum(r['count'] for r in unexplained), 'rows': rows}


def write(result, out=None):
    out = Path(out or OUT)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{result['day']}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    lines = [f"# 오류 장부 {result['day']} (KST)", '',
             f"전체 {result['total']}건, {result['kinds']}종. 그중 내부 측정 {result.get('internal', 0)}건(따로 셈). "
             f"설명되지 않음 {result['unexplained']}건, {result['unexplained_kinds']}종.", '',
             '| 건수 | 원인 | 설명 |', '|---|---|---|']
    for r in result['rows']:
        note = f"{r['reason']} ({r['team']})" if r['explained'] else '**설명되지 않음**'
        lines.append(f"| {r['count']} | `{r['key'][:150]}` | {note} |")
    (out / f"{result['day']}.md").write_text('\n'.join(lines) + '\n')
    return out / f"{result['day']}.md"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--day', default=(datetime.now(KST) - timedelta(days=1)).strftime('%Y-%m-%d'))
    args = parser.parse_args(argv)
    result = ledger(args.day)
    path = write(result)
    print(json.dumps({k: result[k] for k in ('day', 'total', 'kinds', 'unexplained', 'unexplained_kinds')}, ensure_ascii=False), path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
