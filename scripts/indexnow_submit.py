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
import urllib.request
from xml.etree import ElementTree as ET

ORIGIN = 'https://agentconcierge.biz'
ENDPOINT = 'https://api.indexnow.org/indexnow'
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


def batches(urls, size=10000):
    for start in range(0, len(urls), size):
        yield urls[start:start+size]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--key-file', default='logs/service-frontend/public-pages/indexnow-key')
    parser.add_argument('--send', action='store_true', help='actually submit (needs operator approval)')
    args = parser.parse_args(argv)
    key = open(args.key_file, encoding='ascii').read().strip()
    if not re.fullmatch(r'[a-f0-9]{32}', key):
        raise SystemExit('invalid key file')
    urls = sitemap_urls()
    report = {'urls': len(urls), 'key_served': live_key(key), 'first': urls[:5], 'sent': False}
    if args.send:
        if not report['key_served']:
            raise SystemExit('the key file is not served yet; deploy first')
        results = []
        for chunk in batches(urls):
            body = json.dumps({'host': 'agentconcierge.biz', 'key': key, 'keyLocation': f'{ORIGIN}/{key}.txt',
                               'urlList': chunk}).encode()
            request = urllib.request.Request(ENDPOINT, data=body, method='POST', headers={
                'Content-Type': 'application/json; charset=utf-8', 'User-Agent': USER_AGENT})
            with urllib.request.urlopen(request, timeout=60) as response:
                results.append(response.status)
        report.update(sent=True, responses=results)
    print(json.dumps(report, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
