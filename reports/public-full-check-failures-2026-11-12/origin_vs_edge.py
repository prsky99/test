"""PM 11-12 13:1x ①②: the top failing pages of the 13:13 public_full_check, measured at the origin (Caddy :8400 on
this Mac, Host agentconcierge.biz) and at the public address, each on a new connection, nothing excluded.

    .venv/bin/python reports/public-full-check-failures-2026-11-12/origin_vs_edge.py [label]

Also sends one conditional request to the origin with the ETag it just gave (what the edge does on REVALIDATED):
does the origin answer 304, and how long does it take? Raw rows go to origin-vs-edge.json first.
"""
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).with_name('origin-vs-edge.json')
H = {'User-Agent': 'agentcon-public-full-check-triage/1 (site owner QA)', 'Accept': 'text/html,application/xhtml+xml',
     'Accept-Encoding': 'gzip', 'X-Agentcon-QA': 'origin_vs_edge'}


def get(url, headers):
    t = time.monotonic()
    try:
        with httpx.Client(timeout=30) as c:
            r = c.get(url, headers=headers)
    except httpx.HTTPError as exc:
        return {'s': round(time.monotonic() - t, 3), 'status': type(exc).__name__}
    return {'s': round(time.monotonic() - t, 3), 'status': r.status_code, 'bytes': len(r.content),
            'cache': r.headers.get('cf-cache-status'), 'cache_control': r.headers.get('cache-control'),
            'etag': r.headers.get('etag'), 'last_modified': r.headers.get('last-modified'),
            'server_timing': r.headers.get('server-timing'), 'vary': r.headers.get('vary')}


def top_failures(n=10):
    runs = [json.loads(l) for l in open(ROOT / 'logs/ops/public-full-check.jsonl')]
    run = next(r for r in reversed(runs) if r['at'].startswith('2026-11-12 13'))
    rows = [x for x in run['failures'] if x['part'] == 'pages' and x['check'].startswith('time ')]
    rows.sort(key=lambda x: -x['s'])
    return [(x['check'][5:], x['s'], x['detail']) for x in rows[:n]], run['at']


def main():
    label = sys.argv[1] if len(sys.argv) > 1 else 'run'
    picked, run_at = top_failures()
    rec = {'label': label, 'at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'from_run': run_at, 'rows': []}
    for path, was, detail in picked:
        origin = get('http://127.0.0.1:8400' + path, dict(H, Host='agentconcierge.biz'))
        cond = None
        if origin.get('etag'):
            cond = get('http://127.0.0.1:8400' + path, dict(H, Host='agentconcierge.biz', **{'If-None-Match': origin['etag']}))
        public = get('https://agentconcierge.biz' + path, H)
        rec['rows'].append({'path': path, 'at_13_13': {'s': was, 'detail': detail},
                            'origin': origin, 'origin_conditional': cond, 'public': public})
        time.sleep(0.5)
    runs = json.loads(OUT.read_text()) if OUT.is_file() else []
    runs.append(rec)
    OUT.write_text(json.dumps(runs, ensure_ascii=False, indent=1))
    for r in rec['rows']:
        o, c, p = r['origin'], r['origin_conditional'] or {}, r['public']
        print('%-48s 13:13 %5.2fs | 원서버 %s %.3fs %dB etag=%s | 조건부 %s %s | 공개 %s %.2fs %s' % (
            r['path'][:48], r['at_13_13']['s'], o.get('status'), o['s'], o.get('bytes') or 0, 'Y' if o.get('etag') else 'N',
            c.get('status'), c.get('s'), p.get('status'), p['s'], p.get('cache')))
    return 0


if __name__ == '__main__':
    sys.exit(main())
