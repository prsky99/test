"""AI AD Coin public screens keep one spacing rhythm at 1280, 768 and 375 (PM 11-18, user report on AD Coin spacing).

The page shells (the v2 workspace, its five tabs with every signed-in card shown, and /advertise) are served with the
shared assets on a local port; there is no API, database or outside call. The numbers come from the shared layout
tokens in pearl-live.css: stacked cards 24px apart, text and buttons on one row within 2px of one centre line, a
badge 12px above its heading, a label 8px above its control (1px for the font's leading), field rows 24px apart,
numbered lists on the card's left line, the first lines of the side menu and the page level, no sideways scroll.
"""
import socket
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WIDTHS = (1280, 768, 375)
VIEWS = ('rewards', 'preferences', 'advertising', 'reports', 'growth')
SIGNED_IN_CARDS = ('campaign-form', 'booking-form', 'plan-form', 'pay-card', 'reward-fields')

# Measures what a person sees: text boxes, not element boxes, for rows and labels.
METRICS = r"""
() => {
  const vis = e => e && e.offsetParent !== null && getComputedStyle(e).visibility !== 'hidden';
  const r = e => e.getBoundingClientRect();
  const name = e => e.id ? '#' + e.id : (e.querySelector('h2') ? e.querySelector('h2').textContent.trim().slice(0, 18) : e.tagName.toLowerCase() + '.' + (e.className || '').split(' ')[0]);
  const out = {cardGaps: [], rows: [], badges: [], labelToInput: [], fieldRowGap: [], lists: []};
  const view = [...document.querySelectorAll('[data-view]')].find(vis) || document.querySelector('main');
  const containers = [view, ...view.querySelectorAll('.stack, .layout-stack')];
  for (const box of containers) { const kids = [...box.children].filter(vis);
    for (let i = 1; i < kids.length; i++) if (kids[i].classList.contains('card') && kids[i - 1].classList.contains('card') && getComputedStyle(box).display !== 'grid' && getComputedStyle(box).display !== 'flex')
      out.cardGaps.push([name(kids[i - 1]), name(kids[i]), Math.round(r(kids[i]).top - r(kids[i - 1]).bottom)]); }
  const textBox = el => { const t = el.matches('h1,h2,h3,p,span,code') ? el : (el.querySelector('h2,h3,p:not(.eyebrow),span:not(.badge)') || el); const range = document.createRange(); range.selectNodeContents(t); const rs = [...range.getClientRects()]; return rs.length ? rs[0] : r(t); };
  for (const row of document.querySelectorAll('main .row, main .between')) {
    if (!vis(row) || getComputedStyle(row).flexDirection === 'column') continue;
    const btn = [...row.querySelectorAll(':scope > button, :scope > a.btn, :scope > .actions > button, :scope > .actions > a.btn')].find(vis); if (!btn) continue;
    const txt = [...row.children].filter(vis).find(p => !p.contains(btn) && !p.classList.contains('badge')); if (!txt) continue;
    const a = textBox(txt), b = r(btn);
    if (a.bottom <= b.top + 1 || b.bottom <= a.top + 1) continue;   // wrapped onto two lines: not one row
    out.rows.push([(txt.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 26), Math.round(((a.top + a.bottom) / 2 - (b.top + b.bottom) / 2) * 10) / 10]);
  }
  for (const badge of document.querySelectorAll('main .card > .badge')) {
    const next = badge.nextElementSibling; if (!vis(badge) || !next || !/^H[23]$/.test(next.tagName)) continue;
    out.badges.push([badge.textContent.trim(), Math.round(r(next).top - r(badge).bottom)]);
  }
  for (const f of [...document.querySelectorAll('main label.field')].filter(vis)) {
    const ctl = f.querySelector('input,select,textarea'); if (!ctl || !f.firstChild) continue;
    const range = document.createRange(); range.selectNodeContents(f.firstChild); const lb = range.getClientRects()[0];
    if (lb) out.labelToInput.push(Math.round(r(ctl).top - lb.bottom));
  }
  for (const g of [...document.querySelectorAll('main .grid')].filter(vis)) {
    const c = [...g.children].filter(vis).filter(x => x.matches('label.field')); const tops = [...new Set(c.map(x => Math.round(r(x).top)))].sort((x, y) => x - y); if (tops.length < 2) continue;
    const first = c.find(x => Math.round(r(x).top) === tops[0]); const second = c.find(x => Math.round(r(x).top) === tops[1]);
    const ctl = first.querySelector('input,select,textarea');
    const lab = document.createRange(); lab.selectNodeContents(second.firstChild); const lb = lab.getClientRects()[0] || r(second);
    out.fieldRowGap.push(Math.round(lb.top - r(ctl).bottom));
  }
  for (const ol of [...document.querySelectorAll('main .card ol')].filter(vis)) { const card = ol.closest('.card'); const h = card.querySelector('h2'); const li = ol.querySelector('li');
    out.lists.push(Math.round(r(li).left - r(h).left)); }
  const cap = document.querySelector('.ws-sidebar > .caption'); const mainFirst = [...document.querySelector('main').children].find(vis);
  out.firstLine = {sidebar: cap && vis(cap) ? Math.round(r(cap).top) : null, main: mainFirst ? Math.round(r(mainFirst).top) : null};
  const side = document.querySelector('.ws-sidebar'); out.sidebarH = side ? Math.round(r(side).height) : null;
  out.mainTop = Math.round(r(document.querySelector('main')).top + scrollY);
  out.overflowX = document.documentElement.scrollWidth - innerWidth;
  return out;
}
"""


@pytest.fixture(scope="module")
def base():
    import uvicorn
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from starlette.responses import JSONResponse
    from agent_market.ad_coin.v2 import admin_page, workspace

    app = FastAPI()
    app.include_router(workspace.router_for(None, resolve_auth=None))
    app.include_router(admin_page.router_for())

    @app.api_route("/api/{rest:path}", methods=["GET", "POST"])
    async def no_api(rest: str):
        return JSONResponse({"error": {"code": "no_api_in_layout_test"}}, status_code=404)

    app.mount("/new/en", StaticFiles(directory=str(ROOT / "new/en")), name="en")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error", access_log=False))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started
    yield "http://127.0.0.1:%d" % sock.getsockname()[1]
    server.should_exit = True
    thread.join(5)
    sock.close()


def problems(m):
    out = ['card gap %s (%s -> %s)' % (g[2], g[0], g[1]) for g in m['cardGaps'] if g[2] != 24]
    out += ['row %r off centre by %spx' % (t, d) for t, d in m['rows'] if abs(d) > 2]
    out += ['badge %r %spx above its heading' % (t, d) for t, d in m['badges'] if d != 12]
    out += ['label to control %spx' % d for d in m['labelToInput'] if abs(d - 8) > 1]
    out += ['field rows %spx apart' % d for d in m['fieldRowGap'] if abs(d - 24) > 1]
    out += ['numbered list %spx off the left line' % d for d in m['lists'] if d != 0]
    if m['overflowX'] > 0:
        out.append('page scrolls sideways by %spx' % m['overflowX'])
    first = m['firstLine']
    if first['sidebar'] is not None and abs(first['sidebar'] - first['main']) > 1:
        out.append('first lines differ: %s' % first)
    return out


@pytest.mark.parametrize("width", WIDTHS)
def test_ad_coin_public_screens_keep_one_spacing_rhythm(base, width):
    from playwright.sync_api import sync_playwright
    found, measured = {}, 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_context(viewport={"width": width, "height": 900}, color_scheme="light",
                                       locale="en-US").new_page()
            page.goto(base + "/ad-coin/v2")
            for view in VIEWS:
                page.evaluate("v => { location.hash = v }", view)
                page.wait_for_function("v => !document.querySelector('[data-view=' + v + ']').hidden", arg=view)
                m = page.evaluate(METRICS)
                found[view], measured = problems(m), measured + len(m['cardGaps']) + len(m['rows'])
                if view == 'advertising':
                    page.evaluate("ids => ids.forEach(id => { document.getElementById(id).hidden = false })",
                                  list(SIGNED_IN_CARDS))
                    m = page.evaluate(METRICS)
                    found['advertising, signed-in cards'] = problems(m)
                    assert len(m['cardGaps']) >= 7 and m['badges'] and m['lists']   # the cards are really measured
            page.goto(base + "/ad-coin/v2/advertise")
            m = page.evaluate(METRICS)
            found['advertise'] = problems(m)
            assert m['cardGaps']
        finally:
            browser.close()
    assert measured, "nothing was measured"
    assert {k: v for k, v in found.items() if v} == {}


def test_the_rhythm_lives_in_the_shared_stylesheet_and_the_source_copy():
    """One block, in the served pearl-live.css and in its source layout-system.css; the pages only use classes."""
    served = (ROOT / "new/en/assets/pearl-live.css").read_text()
    source = (ROOT / "new/live-assets/layout-system.css").read_text()
    for css in (served, source):
        assert ".layout-stack>*+*{margin-top:var(--layout-group-gap)}" in css
        assert ".ws-main label.field{display:grid;gap:var(--layout-field-gap)" in css
    for name in ("index.html", "advertise.html"):
        html = (ROOT / "agent_market/ad_coin/v2/web" / name).read_text()
        assert "layout-stack" in html and "<style" not in html and "style=" not in html
