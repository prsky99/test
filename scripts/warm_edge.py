"""Fill the Cloudflare edge with the public pages right after a frontend deploy (11-11 PM, page target 1 s).

    .venv/bin/python -m scripts.warm_edge            # after ./agentcon deploy frontend ...

Each live page is fetched once the way a first-time browser asks for it (text/html, no cookie, a new
connection), then every bundle and versioned asset the page names. One line per run goes to
logs/ops/edge-warm.jsonl with the status, the cache state (cf-cache-status) and the airport (cf-ray) of each
request. Only the airport this Mac reaches (LAX from Korea) is filled; visitors elsewhere still fill their own.
It is not a keep-warm loop: run it once per deploy, never on a timer (that would only flatter user_slo).
"""
import html
import json
import re
import time
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://agentconcierge.biz'
PAGES = ('/', '/new/en/index.html', '/new/en/explore.html', '/new/en/chat.html', '/new/en/test.html',
         '/new/en/learn.html', '/new/en/workflows.html', '/new/en/list-agent.html', '/new/en/about.html',
         '/new/en/agent-status.html')
HEADERS = {'Accept': 'text/html,application/xhtml+xml', 'X-Agentcon-QA': 'warm_edge',
           'User-Agent': 'agentcon-warm-edge/1 (site owner QA; contact@agentconcierge.biz)'}
ASSET = re.compile(r'(?:href|src)="(/new/en/assets/[^"]+\?[^"]*v=[^"]+)"')
LOG = ROOT / 'logs/ops/edge-warm.jsonl'


def fetch(url, headers):
    start = time.monotonic()
    try:
        with httpx.Client(timeout=30, headers=headers) as client:  # a new connection per request
            r = client.get(url)
    except httpx.HTTPError as exc:
        return None, {'s': round(time.monotonic() - start, 2), 'status': type(exc).__name__}
    ray = r.headers.get('cf-ray', '')
    return r, {'s': round(time.monotonic() - start, 2), 'status': r.status_code,
               'cache': r.headers.get('cf-cache-status'), 'colo': ray.rsplit('-', 1)[-1] if '-' in ray else None}


def assets_of(text):
    return sorted({html.unescape(u) for u in ASSET.findall(text)})


def main():
    rows, assets = [], set()
    for path in PAGES:
        r, row = fetch(BASE + path, HEADERS)
        rows.append({'path': path, **row})
        if r is not None and r.status_code == 200:
            assets.update(assets_of(r.text))
    for path in sorted(assets):
        _, row = fetch(BASE + path, {k: v for k, v in HEADERS.items() if k != 'Accept'})
        rows.append({'path': path.split('?')[0] + ('?f=' + path.split('f=')[1].split('&')[0] if 'f=' in path else ''), **row})
    record = {'at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'rows': rows,
              'failed': [r['path'] for r in rows if r['status'] != 200]}
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open('a') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')
    for r in rows:
        print('%-48s %s %-8s %s %.2fs' % (r['path'][:48], r['status'], r.get('cache'), r.get('colo'), r['s']))
    raise SystemExit(1 if record['failed'] else 0)


if __name__ == '__main__':
    main()
