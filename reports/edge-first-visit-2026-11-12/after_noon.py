"""First visits after the noon bundle (08276c69: swr on public HTML, growth s-maxage 3600 / swr 86400). PM ③.

    .venv/bin/python reports/edge-first-visit-2026-11-12/after_noon.py <label>

Each address once, a new connection per request, public address, nothing excluded: the 10 live pages, every
category page, the weekly list and latest issue, and 6 agent pages picked at random (growth pages nobody warms).
Raw rows go to after-noon.json before anything is summarised.
"""
import json
import random
import re
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.warm_edge import PAGES, growth_paths  # noqa: E402

B = 'https://agentconcierge.biz'
H = {'User-Agent': 'agentcon-post-deploy-check/1 (site owner QA)', 'Accept-Encoding': 'gzip',
     'Accept': 'text/html,application/xhtml+xml', 'X-Agentcon-QA': 'edge_first_visit'}
OUT = Path(__file__).with_name('after-noon.json')


def get(path):
    t = time.monotonic()
    try:
        with httpx.Client(timeout=30) as c:
            r = c.get(B + path, headers=H)
    except httpx.HTTPError as exc:
        return {'path': path, 's': round(time.monotonic() - t, 2), 'status': type(exc).__name__}
    ray = r.headers.get('cf-ray', '')
    return {'path': path, 'at': datetime.now().strftime('%H:%M:%S'), 's': round(time.monotonic() - t, 2),
            'status': r.status_code, 'cache': r.headers.get('cf-cache-status'), 'age': r.headers.get('age'),
            'cache_control': r.headers.get('cache-control'), 'colo': ray.rsplit('-', 1)[-1] if '-' in ray else None}


def main():
    label = sys.argv[1] if len(sys.argv) > 1 else 'run'
    sm = httpx.get(B + '/sitemap.xml', headers=H).text
    agents = re.findall(r'<loc>https://agentconcierge\.biz(/agent/\d+)</loc>', sm)
    groups = {'live': list(PAGES), 'category_weekly': growth_paths(sm), 'agent': random.sample(agents, min(6, len(agents)))}
    rec = {'label': label, 'at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'rows': {}}
    for name, paths in groups.items():
        rec['rows'][name] = []
        for p in paths:
            rec['rows'][name].append(get(p))
            time.sleep(0.5)
    runs = json.loads(OUT.read_text()) if OUT.is_file() else []
    runs.append(rec)
    OUT.write_text(json.dumps(runs, ensure_ascii=False, indent=1))
    for name, rows in rec['rows'].items():
        by = {}
        for r in rows:
            by.setdefault(r.get('cache'), []).append(r['s'])
        within = sum(1 for r in rows if isinstance(r.get('status'), int) and r['s'] <= 1.0)
        print('%s %s: %d개, 1초 안 %d | %s' % (label, name, len(rows), within, ' | '.join(
            '%s %d (%s)' % (k, len(v), ', '.join('%.2f' % x for x in sorted(v))) for k, v in sorted(by.items(), key=lambda kv: str(kv[0])))))
    return 0


if __name__ == '__main__':
    sys.exit(main())
