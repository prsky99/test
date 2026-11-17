"""Daily signals for the developer pass decision (PM 11-17, docs/AD_COIN_KEYLESS_PASS.md section 3).

    .venv/bin/python -m scripts.ad_coin_pass_signals [--day YYYY-MM-DD]

One finished UTC day (yesterday by default). A signal holds when, for that day:
  (a) 3 or more agent fingerprints called at 50% or more of a public rate limit,
  (b) 10 or more feed requests were refused by the page limit,
  (c) 1,000 or more Sponsored impressions were served (all surfaces, necklace answers included).
The doc's rule: one signal holding 7 days in a row goes to the PM.

What we keep today decides what is measured; nothing is estimated:
  (a) not measured. The public limits are per address and per minute (concierge/security.py _sliding_check); the
      windows live 60 s in Redis or memory and no per-minute peak is stored. agent_hits keeps only a lifetime total
      per fingerprint (concierge/memory.py), which says nothing about a minute. Shown for reference: rate-limit 429
      events of that day (security_events, our own 'internal' clients excluded), i.e. callers that reached 100%.
  (b) not measured. A feed page above 100 items is refused with 400 (agent_access/events.py feed) and the feed's own
      limiter answers 429 (agent_access/service.py rate) without any record; the traffic files fold /api/feed into
      'api_other' by status class. Shown for reference: 429 events of the general read limiter on /api/feed/ paths
      (security_events), a part of the refusals only.
  (c) measured: adc2_sponsored_impressions for that day (placement explore/chat/mcp/a2a) plus the necklace answers
      counted by the frontend in logs/growth/necklace-ad-served.jsonl (ad_coin/v2/sponsored_agent.py). Necklace
      serves are mcp or a2a answers and are already inside the table's mcp/a2a rows; they are shown apart, not added.

Production is read only through scripts.prod_ro_sql.run (its checks, read-only session, one connection at a time and
its own log). The result is printed and appended as one JSON line to logs/ops/ad-coin-pass-signals.jsonl. The script
never edits the status board and is not scheduled by itself.
"""
import argparse
import calendar
import io
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'logs/ops/ad-coin-pass-signals.jsonl'
NECKLACE_FILE = ROOT / 'logs/growth/necklace-ad-served.jsonl'
DAY_MS = 86_400_000
NEED_DAYS = 7
THRESHOLD = {'a': 3, 'b': 10, 'c': 1000}

NOT_MEASURED = {
    'a': 'per-minute use per fingerprint is not kept (limits are per address, 60 s windows in Redis or memory; '
         'agent_hits holds lifetime totals only)',
    'b': 'page-size 400s and the feed limiter 429s are not recorded; traffic files fold /api/feed into api_other',
}
REASON_KO = {
    'a': '분당 지문별 사용량을 남기지 않음',
    'b': '피드 페이지 한도 거절을 남기지 않음',
}


def _utc(day):
    return calendar.timegm(time.strptime(day, '%Y-%m-%d'))


def day_bounds(day):
    """(day_ms, start_s, end_s) of the UTC day 'YYYY-MM-DD'."""
    start = _utc(day)
    return start * 1000, start, start + 86_400


def yesterday(now=None):
    now = time.time() if now is None else now
    return time.strftime('%Y-%m-%d', time.gmtime(now - 86_400))


def build_sql(day):
    day_ms, start, end = day_bounds(day)
    return (
        "SELECT 'imp', placement, COALESCE(sum(served),0) FROM ad_coin_v2.adc2_sponsored_impressions "
        f"WHERE day_ms = {day_ms} GROUP BY placement ORDER BY placement;\n"
        "SELECT 'r429', count(*), count(DISTINCT ip) FROM security_events WHERE event_type = 'rate_limit_429' "
        f"AND at >= {start} AND at < {end} AND coalesce(user_agent,'') <> 'internal';\n"
        "SELECT 'feed429', count(*) FROM security_events WHERE event_type = 'rate_limit_429' "
        f"AND path LIKE '/api/feed/%' AND at >= {start} AND at < {end} AND coalesce(user_agent,'') <> 'internal'")


def parse(lines):
    """Rows printed by prod_ro_sql ('tag|v1|v2'), into {'impressions': {placement: n}, 'r429': (events, networks),
    'feed429': n}. Raises ValueError on a line it does not understand."""
    found = {'impressions': {}}
    for line in lines:
        if not line.strip():
            continue
        parts = line.split('|')
        if parts[0] == 'imp' and len(parts) == 3:
            found['impressions'][parts[1]] = int(parts[2])
        elif parts[0] == 'r429' and len(parts) == 3:
            found['r429'] = (int(parts[1]), int(parts[2]))
        elif parts[0] == 'feed429' and len(parts) == 2:
            found['feed429'] = int(parts[1])
        else:
            raise ValueError('unexpected line: ' + line[:80])
    if 'r429' not in found or 'feed429' not in found:
        raise ValueError('missing rows')
    return found


def query(day, runner=None):
    """Run the read-only statements once. Returns (parsed rows, None) or (None, reason)."""
    if runner is None:
        from scripts.prod_ro_sql import run as runner
    out, err = io.StringIO(), io.StringIO()
    code = runner(build_sql(day), out=out, err=err)
    if code != 0:
        return None, f'prod_ro_sql exit {code}: {err.getvalue().strip()[:200]}'
    try:
        return parse(out.getvalue().splitlines()), None
    except ValueError as exc:
        return None, str(exc)


def necklace_counts(day, path=NECKLACE_FILE):
    """{(necklace, surface): served} for that UTC day from the frontend's growth file; None when the file is absent."""
    try:
        lines = Path(path).read_text(encoding='utf-8').splitlines()
    except FileNotFoundError:
        return None
    except OSError:
        return None
    totals = {}
    for text in lines:
        try:
            line = json.loads(text)
        except ValueError:
            continue
        for row in (line.get('counts') if isinstance(line, dict) else None) or []:
            if not isinstance(row, dict) or (row.get('day') or line.get('day')) != day:
                continue
            served = row.get('served')
            if type(served) is int and served >= 0:
                key = (str(row.get('necklace')), str(row.get('surface')))
                totals[key] = totals.get(key, 0) + served
    return totals


def signals(day, rows, necklace, error=None):
    """The record for DAY. ROWS from parse() or None (then (c) is unmeasured with ERROR as the reason)."""
    record = {'day': day, 'at': int(time.time()), 'thresholds': THRESHOLD,
              'a': {'measured': False, 'reason': NOT_MEASURED['a']},
              'b': {'measured': False, 'reason': NOT_MEASURED['b']}}
    if rows is not None:
        events, networks = rows['r429']
        record['a']['reference'] = {'rate_limit_429_events': events, 'rate_limit_429_networks': networks}
        record['b']['reference'] = {'read_limit_429_on_feed': rows['feed429']}
        by_surface = dict(sorted(rows['impressions'].items()))
        total = sum(by_surface.values())
        record['c'] = {'measured': True, 'value': total, 'by_surface': by_surface, 'met': total >= THRESHOLD['c']}
    else:
        record['c'] = {'measured': False, 'reason': error or 'production not read'}
    record['c']['necklace'] = (None if necklace is None else
                               [{'necklace': k[0], 'surface': k[1], 'served': v} for k, v in sorted(necklace.items())])
    return record


def streaks(record, history):
    """{signal: consecutive days ending at record['day'] with the signal met}, from earlier records (one per day,
    the last line of a day wins). A day missing in between breaks the run."""
    by_day = {}
    for old in history:
        if isinstance(old, dict) and isinstance(old.get('day'), str):
            by_day[old['day']] = old
    by_day[record['day']] = record
    result = {}
    for key in ('a', 'b', 'c'):
        count, day = 0, record['day']
        while day in by_day and (by_day[day].get(key) or {}).get('met') is True:
            count += 1
            day = time.strftime('%Y-%m-%d', time.gmtime(_utc(day) - 86_400))
        result[key] = count
    return result


def line_text(record, run):
    def part(key, label):
        item = record[key]
        if not item.get('measured'):
            reason = REASON_KO.get(key) or item.get('reason', '')
            text = f'({key}) {label} 측정 안 됨({reason})'
            ref = item.get('reference')
            if key == 'a' and ref:
                text += f', 참고 429 {ref["rate_limit_429_events"]:,}건/{ref["rate_limit_429_networks"]:,}개 망'
            if key == 'b' and ref:
                text += f', 참고 읽기 한도 429 중 피드 {ref["read_limit_429_on_feed"]}건'
            return text
        return f'({key}) {label} {item["value"]:,}회(기준 {THRESHOLD[key]:,})'
    c_text = part('c', '광고 노출')
    necklace = record['c'].get('necklace')
    if necklace is None:
        c_text += ', 목걸이 기록 없음'
    else:
        c_text += f', 그중 목걸이 {sum(r["served"] for r in necklace):,}회'
    best = max(run.values())
    tail = (f'{", ".join(k for k, v in run.items() if v >= NEED_DAYS)} {NEED_DAYS}일 연속 충족, PM에 올림'
            if best >= NEED_DAYS else f'{NEED_DAYS}일 연속 충족 없음' + (f'(최장 {best}일)' if best else ''))
    day = record['day'][5:]
    return (f'- {day} 개발자 이용권 신호: {part("a", "한도 50% 지문")}, {part("b", "피드 페이지 한도 거절")}, '
            f'{c_text}, {tail}')


def read_history(path):
    try:
        lines = Path(path).read_text(encoding='utf-8').splitlines()
    except OSError:
        return []
    out = []
    for text in lines[-60:]:
        try:
            out.append(json.loads(text))
        except ValueError:
            continue
    return out


def main(argv=None, runner=None, out_path=OUT, necklace_path=NECKLACE_FILE, stdout=sys.stdout):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--day', help='UTC day YYYY-MM-DD (default: yesterday)')
    args = parser.parse_args(argv)
    day = args.day or yesterday()
    _utc(day)                                        # ValueError on a bad day before anything connects
    rows, error = query(day, runner)
    record = signals(day, rows, necklace_counts(day, necklace_path), error)
    run = streaks(record, read_history(out_path))
    record['streak_days'] = run
    record['text'] = line_text(record, run)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'a', encoding='utf-8') as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n')
    print(record['text'], file=stdout)
    return 0 if rows is not None else 1


if __name__ == '__main__':
    raise SystemExit(main())
