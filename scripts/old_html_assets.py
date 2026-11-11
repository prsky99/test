"""Do the asset URLs named by an earlier release's HTML still answer 200 on the public site? (PM 11-12 08:4x)

    .venv/bin/python -m scripts.old_html_assets usdc-frontend-20261111-r1

With stale-while-revalidate the edge may keep handing out HTML made by the previous release for a while after a
deploy. That HTML names the previous bundle digests (bundle.css?f=...&v=<old>, panels.js?v=<old>, images).
7ac34f2c serves old digests from the earlier release folders; this checks it against the real site.

The earlier release renders its own live pages with its own code (a subprocess with that release first on the
path, the same page_response it served with); every /new/en/assets/ URL in them is then fetched from the public
address. Anything but 200, or a versioned URL answered with the current bytes instead of
its own (not immutable), is a failure (exit 1). Results go to logs/ops/old-html-assets/<date>.json.
"""
import html
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
RELEASES = ROOT / 'gateway-data/services/releases'
BASE = 'https://agentconcierge.biz'
UA = 'agentcon-old-html-assets/1 (site owner QA; contact@agentconcierge.biz)'
OUT = ROOT / 'logs/ops/old-html-assets'
ASSET = re.compile(r'(?:src|href)="((?:/new/en/)?assets/[^"]+)"')
RENDER = r'''
import inspect, json, sys
from agent_market.concierge import pearl_view as v
manifest = json.loads((v.ROOT / 'en-manifest.json').read_text())
accepts_page = 'page' in inspect.signature(v.page_response).parameters
out = {}
for name in manifest['live_pages']:
    value = (v.ROOT / 'en' / name).read_text()
    response = v.page_response(value, public=True, **({'page': name} if accepts_page else {}))
    out[name] = response.body.decode()
print(json.dumps(out))
'''


def render(release):
    """{page: html} as the earlier release served it."""
    folder = RELEASES / release
    if not (folder / 'agent_market/concierge/pearl_view.py').is_file():
        raise SystemExit('no such release: %s' % release)
    done = subprocess.run([sys.executable, '-c', RENDER], cwd=folder, capture_output=True, text=True, timeout=120,
                          env={'PYTHONPATH': str(folder), 'PATH': '/usr/bin:/bin'})
    if done.returncode:
        raise SystemExit('render failed: %s' % done.stderr[-800:])
    return json.loads(done.stdout)


def asset_urls(pages):
    urls = set()
    for page in pages.values():
        for found in ASSET.findall(page):
            found = html.unescape(found)  # href="...&amp;v=..." is "&v=" on the wire
            urls.add(found if found.startswith('/') else '/new/en/' + found)
    return sorted(urls)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        raise SystemExit(__doc__)
    pages = render(args[0])
    urls = asset_urls(pages)
    rows = []
    with httpx.Client(timeout=30, headers={'User-Agent': UA, 'Accept-Encoding': 'gzip'}) as client:
        for url in urls:
            try:
                r = client.get(BASE + url)
                rows.append({'url': url, 'status': r.status_code, 'cache': r.headers.get('cf-cache-status'),
                             'cache_control': r.headers.get('cache-control')})
            except httpx.HTTPError as exc:
                rows.append({'url': url, 'status': type(exc).__name__})
    # A versioned URL the origin recognised comes back immutable with the old bytes; an unrecognised digest gets
    # the current bytes for 300 s, which an old page may not match.
    for r in rows:
        if r['status'] == 200 and 'v=' in r['url'] and 'immutable' not in (r.get('cache_control') or ''):
            r['status'] = 'current bytes, not the old digest'
    bad = [r for r in rows if r['status'] != 200]
    record = {'at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'release': args[0], 'pages': len(pages),
              'urls': len(rows), 'bad': bad, 'rows': rows}
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / (datetime.now().strftime('%Y-%m-%d') + '.json')
    runs = json.loads(path.read_text()) if path.is_file() else []
    runs.append(record)
    path.write_text(json.dumps(runs, ensure_ascii=False, indent=1))
    print('%s: 화면 %d개, 자원 주소 %d개, 200 아님 %d개' % (args[0], len(pages), len(rows), len(bad)))
    for row in bad:
        print(' -', row['status'], row['url'])
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
