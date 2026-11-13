"""Plan 3 step 3 (PM 11-14 00:3x): CSS rules that no public screen or state ever matches, as a list for PM.

    .venv/bin/python -m scripts.heavy_slot --team 성장·유통 --what "CSS 미사용 후보" --minutes 15 -- \
        .venv-tests/bin/python -m scripts.css_unused_candidates

Every screen of scripts/css_pixel_compare (ten pages) x 1280/375 x light/dark is loaded from this working tree with
the fixed catalog (no live data, no network). On each, the selectors of every style rule (inside @media/@supports
too, whether or not the media matches now) are tried with querySelector after the load and again after each state:
every collapsed toggle opened ([aria-expanded=false], <details>), and on Explore/Chat one query sent. Pseudo
classes and elements are stripped first (a :hover rule counts when its element exists).

A selector that never matched is a candidate. Its class and id names are then looked up in the page scripts and
the server code that builds markup: a name found there is 'dynamic' (it may appear in a state not driven here) and
is not proposed for removal. Nothing is deleted: the list goes to PM first (a missed state would break a screen).
Output: reports/css-structure-2026-11-14/unused-candidates.json
"""
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.css_pixel_compare import SCREENS, SCHEMES, STILL, WIDTHS, app  # noqa: E402

OUT = ROOT / 'reports/css-structure-2026-11-14/unused-candidates.json'
QUERIES = {'/new/en/explore.html': 'research', '/new/en/chat.html': 'find a research agent'}

COLLECT = r"""() => {
  const strip = s => s.replace(/::?(?:-[a-z]+-)?[a-z-]+(\((?:[^()]|\([^()]*\))*\))?/gi, (m) =>
      /^:(not|is|where|has)\(/i.test(m) ? m : '').trim() || '*';
  const rules = [];
  const walk = (list, sheet) => { for (const r of list) {
      if (r.selectorText !== undefined) for (const part of r.selectorText.split(/,(?![^()]*\))/))
          rules.push([sheet, part.trim()]);
      if (r.cssRules) walk(r.cssRules, sheet); } };
  for (const s of document.styleSheets) {
    let list; try { list = s.cssRules; } catch (e) { continue; }
    const href = s.href ? new URL(s.href).pathname : 'inline';
    walk(list, href);
  }
  const hit = [];
  for (const [sheet, sel] of rules) {
    let ok = false;
    try { ok = !!document.querySelector(strip(sel)); } catch (e) { ok = null; }
    hit.push([sheet, sel, ok]);
  }
  return hit;
}"""

OPEN = r"""() => {
  let n = 0;
  for (const d of document.querySelectorAll('details:not([open])')) { d.open = true; n++; }
  for (const b of document.querySelectorAll('[aria-expanded="false"]')) {
    try { b.click(); n++; } catch (e) {}
  }
  return n;
}"""


def drive(page, path, record):
    record(page)
    if page.evaluate(OPEN):
        page.wait_for_timeout(300)
        record(page)
    query = QUERIES.get(path)
    if query:
        field = page.locator('input[type="search"], input[name="q"], textarea').locator('visible=true').first
        try:
            field.fill(query, timeout=3000)
            field.press('Enter')
        except Exception as exc:  # no visible field in this layout: the other states still count
            print('query skipped:', path, type(exc).__name__)
        else:
            page.wait_for_timeout(2500)
            record(page)
            if page.evaluate(OPEN):
                page.wait_for_timeout(300)
                record(page)


def collect():
    from playwright.sync_api import sync_playwright
    client = app()
    seen, matched, invalid = {}, set(), set()

    def serve(route):
        request = route.request
        url = urlsplit(request.url)
        if url.hostname != 'agentconcierge.biz':
            return route.abort()
        response = client.request(request.method, url.path + ('?' + url.query if url.query else ''),
                                  content=request.post_data, headers=request.headers)
        headers = {k: v for k, v in response.headers.items() if k not in ('content-length', 'content-encoding', 'transfer-encoding')}
        route.fulfill(status=response.status_code, body=response.content, headers=headers)

    def record(page):
        try:
            hits = page.evaluate(COLLECT)
        except Exception as exc:  # a toggle that navigated away: keep what the other states saw
            print('state skipped:', page.url, type(exc).__name__)
            return
        for sheet, sel, ok in hits:
            key = (sheet, sel)
            seen.setdefault(key, 0)
            if ok:
                matched.add(key)
            elif ok is None:
                invalid.add(key)
    states = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for path in SCREENS:
            for width in WIDTHS:
                for scheme in SCHEMES:
                    ctx = browser.new_context(viewport={'width': width, 'height': 900}, color_scheme=scheme,
                                              reduced_motion='reduce', bypass_csp=True)
                    ctx.route('**/*', serve)
                    page = ctx.new_page()
                    page.goto('https://agentconcierge.biz' + path, wait_until='load')
                    page.add_style_tag(content=STILL)
                    page.wait_for_function("[...document.querySelectorAll('link[data-full-css]')].every(l => l.media === 'all')",
                                           timeout=5000)
                    drive(page, path, record)
                    states += 1
                    ctx.close()
        browser.close()
    return seen, matched, invalid, states


def code_names():
    """Class and id names that page scripts or markup-building server code mention as strings."""
    text = []
    for pattern in ('new/en/assets/*.js', 'new/en/*.html', 'agent_market/concierge/*.py', 'agent_market/agent_access/*.py'):
        for path in ROOT.glob(pattern):
            try:
                text.append(path.read_text(encoding='utf-8'))
            except (OSError, UnicodeDecodeError):
                continue
    return '\n'.join(text)


def names_in(selector):
    return re.findall(r'[.#]([A-Za-z_][\w-]*)', selector)


def main():
    seen, matched, invalid, states = collect()
    # raw first (a long run is not lost to a summary bug): gateway-data, not git
    raw = ROOT / 'gateway-data/css-pixels/unused-raw.json'
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text(json.dumps({'states': states, 'seen': [list(k) for k in seen], 'matched': [list(k) for k in matched],
                               'invalid': [list(k) for k in invalid]}))
    source = code_names()
    unmatched = sorted(k for k in seen if k not in matched and k not in invalid)
    rows = []
    for sheet, sel in unmatched:
        names = names_in(sel)
        dynamic = [n for n in names if re.search(r'(?<![\w-])' + re.escape(n) + r'(?![\w-])', source)]
        rows.append({'sheet': sheet, 'selector': sel, 'names': names,
                     'status': 'dynamic' if dynamic else 'candidate', 'found_in_code': dynamic})
    by_sheet = {}
    for row in rows:
        entry = by_sheet.setdefault(row['sheet'], {'candidate': 0, 'dynamic': 0})
        entry[row['status']] += 1
    total = {}
    for sheet, _ in seen:
        total[sheet] = total.get(sheet, 0) + 1
    result = {'states': states, 'selectors': len(seen), 'matched': len(matched), 'invalid': len(invalid),
              'unmatched': len(rows), 'candidates': sum(r['status'] == 'candidate' for r in rows),
              'by_sheet': {s: {**v, 'selectors': total.get(s, 0)} for s, v in sorted(by_sheet.items())},
              'rows': rows}
    OUT.write_text(json.dumps(result, indent=1, ensure_ascii=False) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'rows'}, indent=1))


if __name__ == '__main__':
    main()
