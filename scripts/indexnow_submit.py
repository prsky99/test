"""Tell IndexNow search engines (Bing, Yandex, Seznam, Naver...) about our public URLs.

    .venv/bin/python -m scripts.indexnow_submit            # preview: counts and the first URLs, sends nothing
    .venv/bin/python -m scripts.indexnow_submit --send     # submit (operator approval required: external notice)

The key is a public ownership proof served at https://agentconcierge.biz/<key>.txt from
logs/service-frontend/public-pages/indexnow-key (growth_pages.indexnow_key). URLs come from the live
sitemap, so only pages with evidence are submitted. IndexNow accepts up to 10,000 URLs per request.
"""
import argparse
import json
import re
import sys
import time
import urllib.request
from xml.etree import ElementTree as ET

ORIGIN = 'https://agentconcierge.biz'
USER_AGENT = 'AgentConcierge-indexnow/1.0 (site owner)'


def sitemap_urls(base=ORIGIN):
    request = urllib.request.Request(base+'/sitemap.xml', headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        tree = ET.fromstring(response.read())
    return [e.text.strip() for e in tree.iter('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')
            if e.text and e.text.startswith(ORIGIN+'/')]


def live_key(key, base=ORIGIN):
    request = urllib.request.Request(f'{base}/{key}.txt', headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status == 200 and response.read().decode().strip() == key


def send(key, urls, attempts=5, wait=60, submit=None, sleep=time.sleep):
    """Key check with one URL first; IndexNow answers 403 until it has fetched the key file."""
    from agent_market.concierge.indexnow import submit as default_submit
    submit = submit or default_submit
    for attempt in range(1, attempts+1):
        done, statuses = submit(key, urls)
        if done or statuses[:1] not in ([403], [429]):
            return done, statuses, attempt
        sleep(wait)
    return False, statuses, attempts


def baseline(snapshot_path, state_path):
    """Record today's page fingerprints so the jobs refresher sends only later differences."""
    from agent_market.concierge import growth_pages, indexnow
    with open(snapshot_path, encoding='utf-8') as handle:
        snapshot = growth_pages.clean(json.load(handle))
    pages = indexnow.fingerprints(snapshot)
    indexnow.write_state(state_path, {'pages': pages, 'submitted_at': time.time()})
    return len(pages)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--key-file', default='logs/service-frontend/public-pages/indexnow-key')
    parser.add_argument('--send', action='store_true', help='actually submit (needs operator approval)')
    parser.add_argument('--baseline', action='store_true', help='record the current snapshot as already submitted')
    parser.add_argument('--snapshot', default='logs/service-frontend/public-pages/task-pages.json')
    parser.add_argument('--state', default='logs/service-frontend/public-pages/indexnow-state.json')
    args = parser.parse_args(argv)
    if args.baseline:
        print(json.dumps({'baseline_pages': baseline(args.snapshot, args.state)}))
        return 0
    key = open(args.key_file, encoding='ascii').read().strip()
    if not re.fullmatch(r'[a-f0-9]{32}', key):
        raise SystemExit('invalid key file')
    urls = sitemap_urls()
    report = {'urls': len(urls), 'key_served': live_key(key), 'first': urls[:5], 'sent': False}
    if args.send:
        if not report['key_served']:
            raise SystemExit('the key file is not served yet; deploy first')
        done, statuses, attempts = send(key, urls)
        report.update(sent=done, responses=statuses, attempts=attempts)
    print(json.dumps(report, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
