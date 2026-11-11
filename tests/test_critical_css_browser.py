"""11-11 PM decision B: the first screen drawn with the inline first-screen CSS alone matches the full CSS.

For each live page with a built file (new/en/assets/critical/<page>.css), Chromium draws the page twice:
A with the bundle stylesheet blocked (only the inline CSS applies) and B as served (the bundle arrives and is
switched on). Every visible element in the first viewport must have the same box (within 2 px), font size,
colour and background in A and B; B must have no console error and no more layout shift than the page has without first-screen CSS.
"""
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from tests.test_agent_adoption import adoption, routing  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
CRITICAL = ROOT / 'new/en/assets/critical'
PAGES = sorted(json.loads((ROOT / 'new/en-manifest.json').read_text())['live_pages'])
SNAPSHOT = """() => {
  const out = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height || r.bottom <= 0 || r.top >= innerHeight || r.right <= 0 || r.left >= innerWidth) continue;
    if (el.closest('template,script,style,noscript,[hidden]')) continue;
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || s.display === 'none' || s.opacity === '0') continue;
    const name = el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (el.classList.length ? '.' + [...el.classList].slice(0, 2).join('.') : '');
    out.push([name, Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height), s.fontSize, s.color, s.backgroundColor]);
  }
  return out;
}"""
CLS = """() => new Promise(done => { let v = 0; new PerformanceObserver(l => { for (const e of l.getEntries()) if (!e.hadRecentInput) v += e.value; })
  .observe({type: 'layout-shift', buffered: true}); setTimeout(() => done(v), 600); })"""


def draw(browser, client, path, width, scheme, block_bundle):
    context = browser.new_context(viewport={'width': width, 'height': 900}, color_scheme=scheme)
    errors = []

    def serve(route):
        request = route.request
        url = urlsplit(request.url)
        if url.hostname != 'agentconcierge.biz' or (block_bundle and url.path.endswith('/bundle.css')):
            route.abort()
            return
        response = client.request(request.method, url.path + ('?' + url.query if url.query else ''),
                                  content=request.post_data, headers=request.headers)
        headers = {k: v for k, v in response.headers.items() if k not in ('content-length', 'content-encoding', 'transfer-encoding')}
        route.fulfill(status=response.status_code, body=response.content, headers=headers)
    context.route('**/*', serve)
    page = context.new_page()
    page.on('console', lambda m: m.type == 'error' and not block_bundle and errors.append(m.text))
    try:
        page.goto('https://agentconcierge.biz' + path, wait_until='load')
        if not block_bundle:
            page.wait_for_function("[...document.querySelectorAll('link[data-full-css]')].every(l => l.media === 'all' && l.sheet)", timeout=5000)
        page.wait_for_timeout(300)
        boxes = page.evaluate(SNAPSHOT)
        shift = page.evaluate(CLS) if not block_bundle else 0
        inline = page.locator('style[data-critical-css]').count()
    finally:
        context.close()
    return boxes, shift, errors, inline


@pytest.mark.parametrize('width,scheme', ((1280, 'light'), (375, 'light'), (1280, 'dark'), (375, 'dark')))
def test_first_screen_with_inline_css_alone_matches_the_full_css(adoption, browser, width, scheme, tmp_path, monkeypatch):  # noqa: F811
    from agent_market.concierge import pearl_view
    *_, client = adoption[:6]
    built = [p for p in PAGES if (CRITICAL / (p.removesuffix('.html') + '.css')).is_file()]
    if not built:
        pytest.skip('no first-screen CSS built')
    failures = {}
    for page in built:
        path = '/new/en/' + page
        alone, _, _, inline = draw(browser, client, path, width, scheme, True)
        full, shift, errors, _ = draw(browser, client, path, width, scheme, False)
        with monkeypatch.context() as m:  # the same page without first-screen CSS, for the shift it already has
            m.setattr(pearl_view, 'CRITICAL_DIR', tmp_path)
            _, before, _, _ = draw(browser, client, path, width, scheme, False)
        problems = []
        if inline != 1:
            problems.append('inline first-screen CSS missing')
        if errors:
            problems.append('console: ' + errors[0][:120])
        if shift > before + 0.01:  # first-screen CSS must not add shift (Chat at 375 shifts 0.055 without it, 11-11)
            problems.append('layout shift %.3f, %.3f without first-screen CSS' % (shift, before))
        a = {(b[0], i): b for i, b in enumerate(alone)}
        f = {(b[0], i): b for i, b in enumerate(full)}
        if len(alone) != len(full):
            problems.append('visible elements %d alone vs %d full' % (len(alone), len(full)))
        for key in list(f)[:400]:
            x, y = a.get(key), f[key]
            if x is None:
                continue
            if any(abs(p - q) > 2 for p, q in zip(x[1:5], y[1:5])) or x[5:] != y[5:]:
                problems.append('%s alone %s full %s' % (key[0], x[1:], y[1:]))
                if len(problems) > 6:
                    break
        if problems:
            failures[page] = problems
    if failures:  # the whole list, since pytest shortens the message
        report = ROOT / 'logs/ops' / ('critical-css-failures-%d-%s.json' % (width, scheme))
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(failures, indent=1))
    assert not failures, failures
