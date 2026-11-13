"""Home and About layout numbers and screenshots, before and after a change (PM 11-13 09:4x, 09:5x).

    .venv/bin/python -m scripts.heavy_slot --team 성장·유통 --what "홈·About 배치 측정" --minutes 6 -- \
        .venv-tests/bin/python -m scripts.home_about_layout before            # the public site as it is
    ... -- .venv-tests/bin/python -m scripts.home_about_layout after --local  # pages and assets from this tree

For each width (1280, 768, 375) and colour scheme (dark, light) it opens / and /new/en/about.html and records:
  home   the left and right edges of every block, the gaps between the three protocol cards, the tops of the
         hero's two columns, the vertical gaps (hero -> band -> protocols -> sections; heading -> lead -> body;
         Evidence grid -> note -> details) and whether the catalog-measures toggle exists;
  about  the necklace art box and whether its picture loaded, the quote box, and every image request of the
         page (with failures such as net::ERR_ABORTED), on About and on the other live pages.
Screenshots (first screen, and the full home page at 1280 and 375) and layout.json go to
reports/home-about-ui-2026-11-13/<stage>/. --local serves /new/en/ from this working tree (the same route
scripts.build_critical_css --local uses) and reads live data from the public API.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/home-about-ui-2026-11-13'
BASE = 'https://agentconcierge.biz'
WIDTHS = (1280, 768, 375)
SCHEMES = ('dark', 'light')
QA = {'X-Agentcon-QA': 'home_about_layout'}

HOME = """() => {
  const R = e => { if (!e || !e.getClientRects().length) return null; const b = e.getBoundingClientRect();
    return {l: Math.round(b.left), t: Math.round(b.top + scrollY), r: Math.round(b.right), b: Math.round(b.bottom + scrollY)}; };
  const q = s => document.querySelector(s), qa = s => [...document.querySelectorAll(s)].filter(e => e.getClientRects().length);
  const sec = q('#secOverview'), hero = q('#secOverview > .catalog-hero'), band = q('#secOverview > .catalog-band');
  const protocols = q('#secOverview > .home-protocols');
  const gap = (a, b) => (a && b) ? b.t - a.b : null;
  const out = {width: innerWidth, toggle: !!q('.catalog-measures-toggle'), left: {}, right: {}, gaps: {}, sections: []};
  const heroText = hero && hero.firstElementChild, necklace = hero && hero.querySelector('.necklace');
  out.left.hero = R(heroText)?.l; out.right.hero = R(necklace)?.r ?? R(heroText)?.r;
  out.gaps.hero_text_top_vs_necklace_top = (R(heroText) && R(necklace)) ? R(heroText).t - R(necklace).t : null;
  const bandFirst = band && [...band.children].find(c => c.getClientRects().length);
  const grid = band && band.querySelector('.metric-grid');
  out.left.band_content = R(bandFirst)?.l; out.right.band_grid = R(grid)?.r;
  out.left.band_box = R(band)?.l; out.right.band_box = R(band)?.r;
  out.gaps.hero_to_band = gap(R(hero), R(band));
  out.gaps.band_to_protocols = gap(R(band), R(protocols));
  if (grid) { const next = [...band.children].slice([...band.children].indexOf(grid) + 1).find(c => c.getClientRects().length);
    out.gaps.grid_to_next = gap(R(grid), R(next)); out.gaps.grid_next = next ? (next.className || next.tagName).toString().slice(0, 40) : null; }
  const cards = protocols ? [...protocols.children].filter(c => c.getClientRects().length).map(R) : [];
  out.left.protocols = cards[0]?.l; out.right.protocols = cards.length ? Math.max(...cards.map(c => c.r)) : null;
  out.gaps.protocol_cards = cards.slice(1).map((c, i) => c.t === cards[i].t ? c.l - cards[i].r : c.t - cards[i].b);
  out.gaps.protocols_section_top_to_first_card = cards[0] ? cards[0].t - R(protocols).t : null;
  let prev = protocols;
  for (const s of qa('#secOverview > section.section, #secOverview > .end-cta')) {
    const h2 = s.querySelector(':scope > h2'), lead = s.querySelector(':scope > .lead');
    const kids = [...s.children].filter(c => c.getClientRects().length);
    const after = el => el ? kids[kids.indexOf(el) + 1] : null;
    const row = {title: (h2 ? h2.textContent : s.className).trim().slice(0, 32), left: R(kids[0])?.l,
                 right: Math.max(...kids.map(k => R(k).r)), from_previous: gap(R(prev), R(s)),
                 section_top_to_first: kids[0] ? R(kids[0]).t - R(s).t : null,
                 h2_to_next: h2 ? gap(R(h2), R(after(h2))) : null, lead_to_next: lead ? gap(R(lead), R(after(lead))) : null};
    if (s.classList.contains('home-evidence')) {
      const g = s.querySelector('.definition-grid'), n = s.querySelector(':scope > .note'), d = s.querySelector(':scope > details');
      row.grid_to_note = gap(R(g), R(n)); row.note_to_details = gap(R(n), R(d));
    }
    out.sections.push(row); prev = s;
  }
  out.page_right = R(sec)?.r;
  return out; }"""

ABOUT = """() => {
  const R = e => { if (!e || !e.getClientRects().length) return null; const b = e.getBoundingClientRect();
    return {l: Math.round(b.left), t: Math.round(b.top + scrollY), r: Math.round(b.right), b: Math.round(b.bottom + scrollY)}; };
  const art = document.querySelector('#secAbout .about-necklace-art'), quote = document.querySelector('#secAbout .reference-about-quote');
  const h1 = document.querySelector('#secAbout .reference-about-intro h1'), lead = document.querySelector('#secAbout .reference-about-intro .lead');
  const bg = art ? getComputedStyle(art).backgroundImage : null;
  return {width: innerWidth, art: R(art), art_background: bg && bg !== 'none' ? bg.slice(0, 160) : null,
          art_hidden_to_assistive_tech: art ? art.getAttribute('aria-hidden') === 'true' : null,
          quote: R(quote), quote_text: quote ? quote.textContent.replace(/\\s+/g, ' ').trim() : null, h1: R(h1), lead: R(lead),
          lead_color: lead ? getComputedStyle(lead).color : null, h1_color: h1 ? getComputedStyle(h1).color : null,
          background: getComputedStyle(document.body).backgroundColor}; }"""


def open_page(browser, path, width, scheme, local):
    from scripts.build_critical_css import serve_local
    ctx = browser.new_context(viewport={'width': width, 'height': 900}, color_scheme=scheme, extra_http_headers=QA)
    if local is not None:
        ctx.route('**/*', lambda route: serve_local(route, local))
    page = ctx.new_page()
    images, failed = [], []
    page.on('request', lambda r: r.resource_type == 'image' and images.append(r.url.split('?')[0].rsplit('/', 1)[-1]))
    page.on('requestfailed', lambda r: failed.append((r.url.split('?')[0].rsplit('/', 1)[-1], r.failure)))
    page.goto(BASE + path, wait_until='load', timeout=45000)
    page.wait_for_timeout(1500)
    return ctx, page, images, failed


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('before', 'after', 'deployed'))
    parser.add_argument('--local', action='store_true', help='serve /new/en/ from this working tree')
    args = parser.parse_args(argv)
    from playwright.sync_api import sync_playwright
    local = None
    if args.local:
        from scripts.build_critical_css import local_client
        local = local_client()
    out_dir = OUT / args.stage
    out_dir.mkdir(parents=True, exist_ok=True)
    record = {'stage': args.stage, 'local': args.local, 'home': [], 'about': [], 'other_pages_images': {}}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for width in WIDTHS:
            for scheme in SCHEMES:
                ctx, page, images, failed = open_page(browser, '/', width, scheme, local)
                row = page.evaluate(HOME)
                row.update(scheme=scheme, failed=failed)
                record['home'].append(row)
                page.screenshot(path=str(out_dir / f'home-{width}-{scheme}.png'))
                if scheme == 'dark' and width in (1280, 375):
                    page.screenshot(path=str(out_dir / f'home-{width}-{scheme}-full.png'), full_page=True)
                ctx.close()
                ctx, page, images, failed = open_page(browser, '/new/en/about.html', width, scheme, local)
                row = page.evaluate(ABOUT)
                row.update(scheme=scheme, images=images, failed=failed)
                record['about'].append(row)
                page.screenshot(path=str(out_dir / f'about-{width}-{scheme}.png'))
                ctx.close()
        for path in ('/', '/new/en/explore.html', '/new/en/chat.html', '/new/en/test.html', '/new/en/agent-status.html'):
            ctx, page, images, failed = open_page(browser, path, 1280, 'dark', local)
            record['other_pages_images'][path] = {'about_art': [i for i in images if 'about' in i or 'pearl' in i],
                                                  'aborted': [f for f in failed if 'ABORTED' in str(f[1])]}
            ctx.close()
        browser.close()
    (out_dir / 'layout.json').write_text(json.dumps(record, ensure_ascii=False, indent=1))
    for row in record['home']:
        if row['scheme'] == 'dark':
            print('home', row['width'], 'toggle', row['toggle'], 'left', row['left'], 'right', row['right'], 'gaps', row['gaps'])
            for s in row['sections']:
                print('   ', s)
    for row in record['about']:
        print('about', row['width'], row['scheme'], 'art', row['art'], 'bg', bool(row['art_background']), 'quote', row['quote'],
              'images', row['images'], 'failed', row['failed'])
    print('other pages', record['other_pages_images'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
