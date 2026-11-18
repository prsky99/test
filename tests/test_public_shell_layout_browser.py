"""PM 11-18 21:2x (user report): /methodology and the pearl cards on Agent Status keep the shared rhythm at 1280, 768 and 375.

/methodology is drawn by the growth pages' shell, which now carries the same pearl footer as Home and About; its sections stand
32px apart on one left line; the pearl and necklace cards on Agent Status sit on the same column lines as the four catalog cards
above them, and nothing scrolls sideways.
"""
import pytest
from tests.test_pearl_frontend import ORIGIN, browser, client, pearl_page  # noqa: F401

WIDTHS = (1280, 768, 375)

METHODOLOGY = r"""
() => {
  const r = e => e.getBoundingClientRect();
  const main = document.querySelector('main');
  const sections = [...main.querySelectorAll('.stack-page > section')];
  const gaps = sections.slice(1).map((s, i) => Math.round(r(s).top - r(sections[i]).bottom));
  const footer = document.querySelector('footer');
  const lefts = new Set([...main.querySelectorAll('h1, h2, p, table')].map(e => Math.round(r(e).left)));
  return {gaps, footerClass: footer.className, footerHeight: Math.round(r(footer).height), lefts: [...lefts],
          overflowX: document.documentElement.scrollWidth - innerWidth};
}
"""

BANDS = r"""
() => {
  const r = e => e.getBoundingClientRect();
  const bands = [...document.querySelectorAll('.metric-grid')].filter(g => g.offsetParent !== null && g.closest('section') && g.children.length);
  const cards = g => [...g.children].filter(c => c.offsetParent !== null).map(c => ({left: Math.round(r(c).left), right: Math.round(r(c).right), width: Math.round(r(c).width), top: Math.round(r(c).top + scrollY)}));
  const isPair = g => !!g.querySelector('[data-metric="pearls"]');
  const pair = bands.find(isPair);
  const first = bands.find(g => !isPair(g));
  return {pair: pair ? cards(pair) : null, first: first ? cards(first) : null, overflowX: document.documentElement.scrollWidth - innerWidth};
}
"""


@pytest.mark.parametrize('width', WIDTHS)
def test_methodology_sections_are_32px_apart_on_one_left_line_with_the_shared_footer(pearl_page, width):
    page, errors, _ = pearl_page
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(ORIGIN + '/methodology')
    m = page.evaluate(METHODOLOGY)
    assert len(m['gaps']) >= 6 and set(m['gaps']) == {32}, m['gaps']
    assert len(m['lefts']) <= 3, m['lefts']        # the heading on the page line, the card text on one inner line (cards, PM 11-18)
    assert m['footerClass'] == 'pearl-footer' and m['overflowX'] <= 0
    page.goto(ORIGIN + '/new/en/about.html')
    about = page.evaluate("() => { const f = document.querySelector('footer'); return [f.className, Math.round(f.getBoundingClientRect().height)]; }")
    assert about == ['pearl-footer', m['footerHeight']]                        # the same footer as About, same height at this width
    assert not errors


@pytest.mark.parametrize('width', WIDTHS)
def test_agent_status_pearl_and_necklace_cards_are_four_equal_cards_on_the_catalog_column_lines(pearl_page, width):
    page, errors, _ = pearl_page
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(ORIGIN + '/new/en/agent-status.html')
    m = page.evaluate(BANDS)
    assert m['pair'] and m['first'] and m['overflowX'] <= 0
    assert len(m['pair']) == 4 and len({c['width'] for c in m['pair']}) == 1, m['pair']      # four cards of one width, nothing left over on the right
    lines = {c['left'] for c in m['first']}
    for card in m['pair']:
        assert any(abs(card['left'] - x) <= 1 for x in lines), (card, sorted(lines))
    assert abs(max(c['right'] for c in m['pair']) - max(c['right'] for c in m['first'])) <= 1   # the row ends where the catalog row ends
    assert min(c['top'] for c in m['pair']) > max(c['top'] for c in m['first'])
    assert not errors
