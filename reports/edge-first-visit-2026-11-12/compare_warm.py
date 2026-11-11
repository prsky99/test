"""First visits to category pages: warmed once vs untouched, at +30 s, +4 min and +6 min (PM 11-12 09:0x).

Public address, a new connection per request, addresses nobody asked for this morning, nothing excluded.
The +6 min round is past the origin's max-age 300 and inside stale-while-revalidate 600, so it also shows
whether the edge answers a stale copy at once (swr) or goes back to the origin first.
"""
import json
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

B = 'https://agentconcierge.biz'
H = {'User-Agent': 'agentcon-post-deploy-check/1 (site owner QA)', 'Accept-Encoding': 'gzip',
     'Accept': 'text/html,application/xhtml+xml', 'X-Agentcon-QA': 'edge_first_visit'}
USED = {'/agents/category/finance_crypto', '/agents/category/data_utility', '/agents/category/web_search',
        '/agents/category/research'}
ROUNDS = (30, 240, 360)


def get(path):
    t = time.monotonic()
    with httpx.Client(timeout=30) as c:
        r = c.get(B + path, headers=H)
    ray = r.headers.get('cf-ray', '')
    return {'path': path, 'at': datetime.now().strftime('%H:%M:%S'), 's': round(time.monotonic() - t, 2),
            'status': r.status_code, 'cache': r.headers.get('cf-cache-status'), 'age': r.headers.get('age'),
            'colo': ray.rsplit('-', 1)[-1] if '-' in ray else None}


def main():
    sm = httpx.get(B + '/sitemap.xml', headers=H).text
    pool = [p for p in re.findall(r'https://agentconcierge.biz(/agents/category/[^<]+)', sm) if p not in USED]
    random.shuffle(pool)
    warm, cold = pool[:3], pool[3:6]
    rec = {'started': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'warm': [], 'rounds': []}
    for p in warm:
        rec['warm'].append(get(p))
        time.sleep(1)
    t0 = time.monotonic()
    for i, delay in enumerate(ROUNDS):
        time.sleep(max(0, delay - (time.monotonic() - t0)))
        row = {'after_s': delay, 'warmed': get(warm[i])}
        time.sleep(1)
        row['untouched'] = get(cold[i])
        rec['rounds'].append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    out = Path(__file__).with_name('compare-warm.json')
    runs = json.loads(out.read_text()) if out.is_file() else []
    runs.append(rec)
    out.write_text(json.dumps(runs, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
