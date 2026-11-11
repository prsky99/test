"""Build first-screen CSS for each live page from the rules a real browser uses (PM decision B, 11-11).

    .venv-tests/bin/python -m scripts.build_critical_css --base http://127.0.0.1:8402

Each live page is opened at 1280 and 375 px, in light and dark, and Chrome reports which rules of the
page's CSS bundle matched (CSS.startRuleUsageTracking). The used style rules are written in their original
order, inside the same @media/@supports blocks, to new/en/assets/critical/<page>.css; @font-face,
@keyframes, @property and rules for :root/html/body are always kept. pearl_view inlines that file and loads the
full bundle without blocking the first paint; deleting a file turns it off for that page.

Run it again whenever a stylesheet changes; tests/test_critical_css.py fails when a critical file holds a rule
the bundle no longer has.
"""
import argparse
import gzip
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'new/en/assets/critical'
WIDTHS = (1280, 375)
SCHEMES = ('light', 'dark')
ALWAYS = re.compile(r'^\s*(?::root|html|body)\b[^{]*\{', re.I)
KEEP_AT = ('@font-face', '@keyframes', '@-webkit-keyframes', '@property', '@counter-style', '@layer')
MAX_GZIP = 20 * 1024


def blocks(css, i=0, n=None):
    """Items of css[i:n] as (start, end, prelude, children); offsets are into css, children are nested items."""
    out, n = [], len(css) if n is None else n
    while i < n:
        while i < n and css[i] in ' \t\r\n':
            i += 1
        if i >= n:
            break
        if css.startswith('/*', i):
            j = css.find('*/', i + 2)
            i = n if j < 0 else j + 2
            continue
        start = i
        depth, quote, brace = 0, None, -1
        while i < n:
            ch = css[i]
            if quote:
                if ch == '\\':
                    i += 2
                    continue
                if ch == quote:
                    quote = None
            elif ch in '"\'':
                quote = ch
            elif css.startswith('/*', i):
                j = css.find('*/', i + 2)
                i = n if j < 0 else j + 2
                continue
            elif ch == '{':
                if depth == 0 and brace < 0:
                    brace = i - start  # the first brace outside strings and comments
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            elif ch == ';' and depth == 0:
                i += 1
                break
            i += 1
        text = css[start:i]
        prelude = text[:brace].strip() if brace >= 0 else text.strip()
        children = None
        if prelude.startswith('@') and brace >= 0 and not prelude.lower().startswith(KEEP_AT):
            children = blocks(css, start + brace + 1, i - 1)
        out.append((start, i, prelude, children))
    return out


def critical(css, used_ranges):
    """The used part of a stylesheet, given (start, end) offsets of used style rules."""
    used = {(s, e) for s, e in used_ranges}
    starts = {s for s, _ in used_ranges}

    def keep(item):
        start, end, prelude, children = item
        if children is not None:
            inner = [keep(child) for child in children]
            inner = [x for x in inner if x]
            return prelude + '{' + ''.join(inner) + '}' if inner else ''
        text = css[start:end]
        if prelude.lower().startswith(KEEP_AT) or prelude.lower().startswith('@import') or prelude.lower().startswith('@charset'):
            return text
        if (start, end) in used or start in starts or ALWAYS.match(text):
            return text
        return ''
    return '\n'.join(x for x in (keep(item) for item in blocks(css)) if x) + '\n'


def collect(base, page):
    from playwright.sync_api import sync_playwright
    used, sheet = set(), None
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for width in WIDTHS:
            for scheme in SCHEMES:
                ctx = browser.new_context(viewport={'width': width, 'height': 900}, color_scheme=scheme,
                                          extra_http_headers={'X-Agentcon-QA': 'build_critical_css'})
                pg = ctx.new_page()
                cdp = ctx.new_cdp_session(pg)
                urls = {}
                cdp.on('CSS.styleSheetAdded', lambda e: urls.__setitem__(e['header']['styleSheetId'], e['header'].get('sourceURL', '')))
                cdp.send('DOM.enable')
                cdp.send('CSS.enable')
                cdp.send('CSS.startRuleUsageTracking')
                pg.goto(base.rstrip('/') + '/new/en/' + page, wait_until='load')
                pg.wait_for_timeout(1200)
                for rule in cdp.send('CSS.stopRuleUsageTracking')['ruleUsage']:
                    if not rule['used'] or 'bundle.css' not in urls.get(rule['styleSheetId'], ''):
                        continue
                    if sheet is None:
                        sheet = cdp.send('CSS.getStyleSheetText', {'styleSheetId': rule['styleSheetId']})['text']
                    used.add((int(rule['startOffset']), int(rule['endOffset'])))
                ctx.close()
        browser.close()
    return sheet or '', used


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', required=True, help='a running frontend (the active slot), never a public URL')
    args = parser.parse_args()
    manifest = json.loads((ROOT / 'new/en-manifest.json').read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    report = {}
    for page in sorted(manifest['live_pages']):
        sheet, used = collect(args.base, page)
        if not sheet:
            report[page] = 'no bundle stylesheet seen'
            continue
        text = critical(sheet, used)
        (OUT / (page.removesuffix('.html') + '.css')).write_text(text)
        report[page] = {'rules': len(used), 'raw': len(text), 'gzip': len(gzip.compress(text.encode(), 9))}
    print(json.dumps(report, indent=1))
    too_big = [p for p, v in report.items() if isinstance(v, dict) and v['gzip'] > MAX_GZIP]
    if too_big:
        raise SystemExit('over 20 KB gzip: ' + ', '.join(too_big))


if __name__ == '__main__':
    main()
