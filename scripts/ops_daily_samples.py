"""매일 운영 점검용 표본(운영·SRE, 2026-11-10).

읽기 전용으로 세 가지를 잰다.
- 오류율: logs/service-frontend/traffic/*.json의 status 집계로 날짜별 5xx 비율(최근 N일)
- 탐색 3초 표본: 처음 보는 검색어 5개, 연결 하나 재사용, Server-Timing의 서버 시간과 전체 시간
- Chat 5초 표본: 처음 보는 질문 3개, POST /chat, Server-Timing concierge;dur
- 카테고리·상세 표본: /agents/category/<무작위 3개>, /api/agents/<무작위 활성 3개>
- --record: 요약 한 줄을 logs/ops/response-samples.jsonl에 덧붙인다(주간 추세용, git 제외)
- --trend: 기록 파일에서 ISO 주별 중앙값 표를 출력한다(데이터가 늘며 느려지는 구간 찾기)

    .venv/bin/python -m scripts.ops_daily_samples [--days 7] [--port 8401] [--record] [--trend]

포트를 주지 않으면 `./agentcon status`의 활성 frontend 슬롯 PID로 듣는 포트를 찾는다.
UA는 "ops-check/1 (site owner test)"라 트래픽 집계에서 internal로 잡힌다.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import random
import re
import statistics
import subprocess
import time
from datetime import date, timedelta
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
RECORD = 'logs/ops/response-samples.jsonl'
KINDS = ('explore', 'chat', 'category', 'detail')
HOST = 'agentconcierge.biz'
UA = 'ops-check/1 (site owner test)'
TOPICS = ['tide tables', 'currency rates', 'air quality', 'flight status', 'parcel tracking', 'recipe nutrition',
          'stock quotes', 'translate menu', 'pdf invoice parsing', 'earthquake alerts', 'bus timetable',
          'domain whois', 'crypto gas fees', 'job postings', 'pollen forecast', 'sports scores', 'weather radar',
          'hotel prices', 'podcast transcripts', 'patent search']
PLACES = ['Busan', 'Lisbon', 'Osaka', 'Nairobi', 'Denver', 'Hanoi', 'Oslo', 'Lima', 'Perth', 'Tbilisi', 'Quebec']


def error_rates(days: int) -> list[dict]:
    today = date.today()
    rows = []
    for back in range(days, -1, -1):
        day = (today - timedelta(days=back)).isoformat()
        status, total = collections.Counter(), 0
        for f in glob.glob(str(ROOT / f'logs/service-frontend/traffic/{day}.*.json')):
            try:
                data = json.loads(Path(f).read_text())
            except (OSError, ValueError):
                continue
            for key, n in (data.get('status') or {}).items():
                route, client, klass = key.rsplit('|', 2)
                status[(klass, 'internal' if client == 'internal' else 'external')] += n
                total += n
        if not total:
            continue
        five = sum(n for (k, _), n in status.items() if k == '5xx')
        five_ext = status[('5xx', 'external')]
        ext = sum(n for (_, c), n in status.items() if c == 'external')
        rows.append({'day': day, 'requests': total, '5xx': five, '5xx_rate': round(100 * five / total, 2),
                     'external': ext, '5xx_external': five_ext,
                     '5xx_external_rate': round(100 * five_ext / ext, 2) if ext else 0.0})
    return rows


def active_port() -> int:
    out = subprocess.run(['./agentcon', 'status'], cwd=ROOT, capture_output=True, text=True, timeout=60).stdout
    state = json.loads(out[out.index('{'):])
    front = state['services']['frontend']
    pid = front['slots'][front['active']]['pid']
    lsof = subprocess.run(['lsof', '-nP', '-a', '-p', str(pid), '-iTCP', '-sTCP:LISTEN'],
                          capture_output=True, text=True, timeout=30).stdout
    ports = [int(p) for p in re.findall(r':(\d+) \(LISTEN\)', lsof)]
    if not ports:
        raise SystemExit(f'no listening port for frontend pid {pid}')
    return ports[0]


def _server_ms(resp: httpx.Response, name: str) -> float | None:
    match = re.search(rf'{name};dur=([0-9.]+)', resp.headers.get('server-timing', ''))
    return float(match.group(1)) if match else None


def _active_ids(n: int) -> list[int]:
    out = subprocess.run(['/opt/homebrew/opt/postgresql@18/bin/psql', '-h', str(ROOT / 'gateway-data/postgres18/run'),
                          '-p', '55432', '-d', 'agentcon_cutover_20261020_191757', '-Atc',
                          f"SELECT id FROM resources WHERE active=1 ORDER BY random() LIMIT {int(n)}"],
                         capture_output=True, text=True, timeout=60).stdout
    return [int(v) for v in out.split()]


def samples(port: int, explore_n: int = 5, chat_n: int = 3, page_n: int = 3) -> dict:
    rng = random.Random(time.time_ns())
    stamp = date.today().strftime('%m%d')
    queries = [f'{t} {p}' for t, p in zip(rng.sample(TOPICS, explore_n), rng.sample(PLACES, explore_n))]
    questions = [f'I need {t} for {p} ({stamp})' for t, p in zip(rng.sample(TOPICS, chat_n), rng.sample(PLACES, chat_n))]
    base = f'http://127.0.0.1:{port}'
    headers = {'host': HOST, 'user-agent': UA}
    result = {'port': port, 'explore': [], 'chat': []}
    with httpx.Client(base_url=base, headers=headers, timeout=30) as http:
        http.get('/robots.txt')  # open the connection first so the samples reuse it
        for q in queries:
            begun = time.perf_counter()
            r = http.get('/api/explore', params={'q': q})
            result['explore'].append({'q': q, 'status': r.status_code, 'total_ms': round((time.perf_counter() - begun) * 1000),
                                      'server_ms': _server_ms(r, 'explore')})
        for q in questions:
            begun = time.perf_counter()
            r = http.post('/chat', json={'message': q})
            try:
                body = r.json()
                found = len((body.get('data') or {}).get('recommendations') or [])
            except ValueError:
                found = None
            result['chat'].append({'q': q, 'status': r.status_code, 'total_ms': round((time.perf_counter() - begun) * 1000),
                                   'server_ms': _server_ms(r, 'concierge'), 'recommendations': found})
        from agent_market.broker.categories import CATEGORIES
        result['category'], result['detail'] = [], []
        for path in [f'/agents/category/{c}' for c in rng.sample(sorted(CATEGORIES), page_n)] + \
                [f'/api/agents/{i}' for i in _active_ids(page_n)]:
            begun = time.perf_counter()
            r = http.get(path)
            result['category' if path.startswith('/agents/') else 'detail'].append(
                {'path': path, 'status': r.status_code, 'total_ms': round((time.perf_counter() - begun) * 1000)})
    for key, goal in (('explore', 3000), ('chat', 5000), ('category', 3000), ('detail', 3000)):
        times = [s['total_ms'] for s in result[key]]
        if not times:
            continue
        result[f'{key}_summary'] = {'n': len(times), 'median_ms': round(statistics.median(times)), 'max_ms': max(times),
                                    'over_goal': sum(t > goal for t in times), 'goal_ms': goal,
                                    'non_200': sum(s['status'] != 200 for s in result[key])}
    result['load_1m'] = round(__import__('os').getloadavg()[0], 2)
    return result


def record(result: dict, path: Path) -> dict:
    row = {'at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'load_1m': result['load_1m'],
           **{k: result[f'{k}_summary'] for k in KINDS if f'{k}_summary' in result}}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')
    return row


def trend(path: Path) -> list[dict]:
    """ISO week -> median of the daily medians and worst max for each kind."""
    weeks = collections.defaultdict(lambda: collections.defaultdict(list))
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            row = json.loads(line)
            year, week, _ = date.fromisoformat(row['at'][:10]).isocalendar()
        except (ValueError, KeyError, TypeError):
            continue
        for kind in KINDS:
            if isinstance(row.get(kind), dict):
                weeks[f'{year}-W{week:02d}'][kind].append(row[kind])
    table = []
    for week in sorted(weeks):
        entry = {'week': week}
        for kind, rows in weeks[week].items():
            entry[kind] = {'days': len(rows), 'median_ms': round(statistics.median(r['median_ms'] for r in rows)),
                           'max_ms': max(r['max_ms'] for r in rows), 'over_goal': sum(r['over_goal'] for r in rows)}
        table.append(entry)
    return table


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=7)
    parser.add_argument('--port', type=int)
    parser.add_argument('--no-samples', action='store_true')
    parser.add_argument('--record', action='store_true')
    parser.add_argument('--trend', action='store_true')
    args = parser.parse_args(argv)
    report = {'error_rates': error_rates(args.days)}
    if not args.no_samples:
        report['samples'] = samples(args.port or active_port())
        if args.record:
            report['recorded'] = record(report['samples'], ROOT / RECORD)
    if args.trend:
        report['trend'] = trend(ROOT / RECORD)
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
