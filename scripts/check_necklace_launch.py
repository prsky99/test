"""Launch-day screen check for the first open necklace (PM 11-15 17:20). Read-only, public address only.

    .venv-tests/bin/python -m scripts.check_necklace_launch <slug> [--base https://agentconcierge.biz] [--out DIR]

For the given necklace it checks, in a fresh Chromium context at 1280 and 375 px:
- /api/necklaces lists it as offered, with a standing per member;
- Home (/new/en/index.html) and Workflows show the necklace card (the reason, a link to this necklace and the request
  link) instead of the empty slot;
- its page shows the standing line, a label per step (Verified pearl / Under verification), the steps sentence, the
  fallback and scope lines when the snapshot has them, the measured line when it has a comparison, and the run form;
- /necklaces/request answers 200.
It prints one line per check (ok / FAIL with what was seen) and saves a full-page screenshot per page and width.
Nothing is submitted: the run form is looked at, never sent. Exit code 1 when any check fails.
"""
import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path


def fetch_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={'accept': 'application/json',
                                                                     'user-agent': 'agentvalcon-launch-check/1.0'}),
                                timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('slug')
    parser.add_argument('--base', default='https://agentconcierge.biz')
    parser.add_argument('--out', default='reports/launch-posts-2026-11-16/screens')
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    results = []

    def check(name, ok, seen=''):
        results.append(ok)
        print(('ok   ' if ok else 'FAIL ') + name + ('' if ok else ' :: ' + str(seen)[:200]))

    listing = fetch_json(args.base + '/api/necklaces')
    items = listing.get('necklaces') or listing.get('items') or []
    item = next((n for n in items if isinstance(n, dict) and n.get('slug') == args.slug), None)
    check('/api/necklaces lists it', item is not None, [n.get('slug') for n in items if isinstance(n, dict)])
    if item:
        check('offered', item.get('offered') is True, item.get('offered'))
        check('standing per member', all(p.get('standing') in ('verified_pearl', 'provisional')
                                         for p in item.get('pearls') or []), [p.get('standing') for p in item.get('pearls') or []])

    from playwright.sync_api import sync_playwright
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        for width in (1280, 375):
            for label, path in (('home', '/new/en/index.html'), ('workflows', '/new/en/workflows.html')):
                context = browser.new_context(viewport={'width': width, 'height': 900})
                page = context.new_page()
                started = time.time()
                page.goto(args.base + path, wait_until='load', timeout=60000)
                card = page.locator('.necklace-why-card')
                check(f'{label} {width}px: card shown ({time.time() - started:.1f}s)', card.count() >= 1, 'no .necklace-why-card')
                if card.count():
                    text = card.first.inner_text()
                    check(f'{label} {width}px: card links the necklace and requests',
                          card.first.locator(f'a[href="/necklaces/{args.slug}"]').count() >= 1
                          and card.first.locator('a[href="/necklaces/request"]').count() >= 1, text)
                page.screenshot(path=str(out / f'{label}-{width}.png'), full_page=True)
                context.close()
            context = browser.new_context(viewport={'width': width, 'height': 900})
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            started = time.time()
            response = page.goto(args.base + '/necklaces/' + args.slug, wait_until='load', timeout=60000)
            check(f'necklace page {width}px: 200 ({time.time() - started:.1f}s)', response.status == 200, response.status)
            body = page.locator('body').inner_text()
            check(f'necklace page {width}px: standing says running', 'Standing: running' in body, body[:200])
            check(f'necklace page {width}px: a label per step',
                  page.locator('.necklace-member').count() == len((item or {}).get('pearls') or []), page.locator('.necklace-member').count())
            check(f'necklace page {width}px: steps sentence', 'This necklace joins' in body, '')
            check(f'necklace page {width}px: why paragraph', page.locator('.necklace-why').count() == 1, '')
            if item and item.get('fallback'):
                check(f'necklace page {width}px: fallback line', page.locator('.necklace-fallback').count() == 1, '')
            if item and item.get('scope_notice'):
                check(f'necklace page {width}px: scope line', page.locator('.necklace-scope').count() == 1, '')
            if item and item.get('comparison'):
                check(f'necklace page {width}px: measured line', page.locator('.necklace-measured').count() == 1, '')
            check(f'necklace page {width}px: run form present (not sent)',
                  page.locator(f'form[action="/necklaces/{args.slug}/run"]').count() == 1, '')
            check(f'necklace page {width}px: no script errors', not errors, errors)
            page.screenshot(path=str(out / f'necklace-{width}.png'), full_page=True)
            context.close()
        browser.close()
    with urllib.request.urlopen(urllib.request.Request(args.base + '/necklaces/request',
                                                       headers={'accept': 'text/html'}), timeout=30) as r:
        check('/necklaces/request 200', r.status == 200, r.status)
    print(f'{sum(results)}/{len(results)} checks passed; screenshots in {out}')
    return 0 if all(results) else 1


if __name__ == '__main__':
    sys.exit(main())
