"""Pixel comparison for the CSS structure work (PM 11-14 00:3x, plan 3: "what is drawn stays the same, only less CSS").

    .venv/bin/python -m scripts.heavy_slot --team 성장·유통 --what "CSS 픽셀 기준" --minutes 15 -- \
        .venv-tests/bin/python -m scripts.css_pixel_compare shoot baseline
    ... -- .venv-tests/bin/python -m scripts.css_pixel_compare shoot step1
    python3 -m scripts.css_pixel_compare diff baseline step1     # needs Pillow (the system python3 has it)

shoot: ten screens (the nine live pages and privacy) x 1280 and 375 x light and dark, full page, from this working
tree, served by an in-process app with a fixed catalog (no live data, no network), animations and transitions off,
fonts settled. PNGs go to reports/css-structure-2026-11-14/<stage>/.
diff: the number of differing pixels per screenshot (and a red diff picture when there is any). The rule is 0.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/css-structure-2026-11-14'
SCREENS = ('/', '/new/en/agent-status.html', '/new/en/explore.html', '/new/en/learn.html', '/new/en/test.html',
           '/new/en/workflows.html', '/new/en/chat.html', '/new/en/list-agent.html', '/new/en/about.html',
           '/new/en/privacy.html')
WIDTHS = (1280, 375)
SCHEMES = ('light', 'dark')
STILL = ('*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important;'
         'scroll-behavior:auto!important}')


# The pages print the current time (e.g. "13 Nov 2026, 16:23 UTC"); two runs a minute apart differed only there.
CLOCK = r"""() => { const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = w.nextNode(); n; n = w.nextNode()) n.nodeValue = n.nodeValue.replace(/\b\d{1,2}:\d{2}(:\d{2})?\b/g, '00:00'); }"""


def app():
    from fastapi.testclient import TestClient
    from agent_market.concierge.front import Front, clear_front_caches, create_front_app
    from agent_market.gateway.store import Store
    store = Store(str(Path(tempfile.mkdtemp(prefix='css-pixels-')) / 'pixels.db'))
    for i in range(8):  # the fixed catalog of tests/test_pearl_frontend.py
        rid = store.upsert_resource({'key': 'pearl-' + str(i), 'name': 'Research ' + str(i), 'kind': ['a2a', 'mcp', 'x402'][i % 3],
                                     'source': 'isolated', 'url': 'https://agent-' + str(i) + '.example/api',
                                     'description': 'Public research sources', 'category': 'web_search'})
        with store.tx() as db:
            db.execute("UPDATE resources SET health_status='healthy',last_check_at=1 WHERE id=?", (rid,))
    clear_front_caches()
    return TestClient(create_front_app(Front(store), manage_book_lifecycle=False))


def name_of(path, width, scheme):
    return (path.strip('/').replace('new/en/', '').replace('.html', '') or 'index') + '-%d-%s.png' % (width, scheme)


def shoot(stage):
    from playwright.sync_api import sync_playwright
    client = app()
    out = OUT / stage
    out.mkdir(parents=True, exist_ok=True)

    def serve(route):
        request = route.request
        url = urlsplit(request.url)
        if url.hostname != 'agentconcierge.biz':
            return route.abort()
        response = client.request(request.method, url.path + ('?' + url.query if url.query else ''),
                                  content=request.post_data, headers=request.headers)
        headers = {k: v for k, v in response.headers.items() if k not in ('content-length', 'content-encoding', 'transfer-encoding')}
        route.fulfill(status=response.status_code, body=response.content, headers=headers)
    done = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for path in SCREENS:
            for width in WIDTHS:
                for scheme in SCHEMES:
                    ctx = browser.new_context(viewport={'width': width, 'height': 900}, color_scheme=scheme,
                                              reduced_motion='reduce', device_scale_factor=1,
                                              bypass_csp=True)  # only for the still-frame style below
                    ctx.route('**/*', serve)
                    page = ctx.new_page()
                    page.goto('https://agentconcierge.biz' + path, wait_until='load')
                    page.add_style_tag(content=STILL)
                    page.wait_for_function("[...document.querySelectorAll('link[data-full-css]')].every(l => l.media === 'all')",
                                           timeout=5000)
                    page.evaluate('document.fonts.ready')
                    page.evaluate(CLOCK)
                    page.wait_for_timeout(800)
                    target = out / name_of(path, width, scheme)
                    page.screenshot(path=str(target), full_page=True, animations='disabled', caret='hide')
                    done.append(target.name)
                    ctx.close()
        browser.close()
    (out / 'shots.json').write_text(json.dumps(done, indent=1))
    print(stage, len(done), 'screenshots')


def diff(a, b, noise=None):
    """noise: a second shot of stage a; pixels that already differ between a and noise are left out (11-14: two
    shots of the same tree differed in 1 of 40 pictures, 7 anti-aliased pixels of a chat panel edge)."""
    from PIL import Image, ImageChops
    rows, worst = [], 0
    for left in sorted((OUT / a).glob('*.png')):
        right = OUT / b / left.name
        if not right.is_file():
            rows.append((left.name, 'missing'))
            continue
        x, y = Image.open(left).convert('RGB'), Image.open(right).convert('RGB')
        if x.size != y.size:
            rows.append((left.name, 'size %s vs %s' % (x.size, y.size)))
            worst = max(worst, 1)
            continue
        delta = ImageChops.difference(x, y)
        if noise and (OUT / noise / left.name).is_file():
            z = Image.open(OUT / noise / left.name).convert('RGB')
            if z.size == x.size:
                r, g, bl = ImageChops.difference(x, z).split()  # any channel (an L conversion rounds 1-step changes to 0)
                shaky = ImageChops.lighter(ImageChops.lighter(r, g), bl).point(lambda v: 0 if v else 255)
                delta = Image.composite(delta, Image.new('RGB', x.size), shaky)
        box = delta.getbbox()
        count = sum(1 for px in delta.getdata() if px != (0, 0, 0)) if box else 0
        if count:
            r, g, bl = delta.split()
            mask = ImageChops.lighter(ImageChops.lighter(r, g), bl).point(lambda v: 255 if v else 0)
            red = Image.new('RGB', x.size, (255, 0, 0))
            shown = Image.composite(red, x.point(lambda v: v // 3), mask)
            (OUT / ('diff-%s-%s' % (a, b))).mkdir(exist_ok=True)
            shown.save(OUT / ('diff-%s-%s' % (a, b)) / left.name)
        rows.append((left.name, count, box))
        worst = max(worst, count)
    for row in rows:
        print(*row)
    print('screens', len(rows), 'with any difference', sum(1 for r in rows if r[1] != 0))
    return 0 if worst == 0 else 1


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('shoot'); s.add_argument('stage')
    d = sub.add_parser('diff'); d.add_argument('a'); d.add_argument('b')
    d.add_argument('--noise', help='a second shot of stage a: pixels that differ between the two are not counted')
    args = parser.parse_args(argv)
    if args.cmd == 'shoot':
        shoot(args.stage)
        return 0
    return diff(args.a, args.b, args.noise)


if __name__ == '__main__':
    sys.exit(main())
