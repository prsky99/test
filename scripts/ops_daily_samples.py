"""매일 운영 점검용 표본(운영·SRE, 2026-11-10).

읽기 전용으로 세 가지를 잰다.
- 오류율: logs/service-frontend/traffic/*.json의 status 집계로 날짜별 5xx 비율(최근 N일)
- 탐색 3초 표본: 처음 보는 검색어 5개, 연결 하나 재사용, Server-Timing의 서버 시간과 전체 시간
- Chat 5초 표본: 처음 보는 질문 3개, POST /chat, Server-Timing concierge;dur

    .venv/bin/python -m scripts.ops_daily_samples [--days 7] [--port 8401]

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


def samples(port: int, explore_n: int = 5, chat_n: int = 3) -> dict:
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
    for key, goal in (('explore', 3000), ('chat', 5000)):
        times = [s['total_ms'] for s in result[key]]
        result[f'{key}_summary'] = {'n': len(times), 'median_ms': round(statistics.median(times)), 'max_ms': max(times),
                                    'over_goal': sum(t > goal for t in times), 'goal_ms': goal,
                                    'non_200': sum(s['status'] != 200 for s in result[key])}
    result['load_1m'] = round(__import__('os').getloadavg()[0], 2)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=7)
    parser.add_argument('--port', type=int)
    parser.add_argument('--no-samples', action='store_true')
    args = parser.parse_args(argv)
    report = {'error_rates': error_rates(args.days)}
    if not args.no_samples:
        report['samples'] = samples(args.port or active_port())
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
