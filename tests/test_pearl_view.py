"""PM 11-18 (user): the pearl number opens Explore's pearl view, and Explore has a "Pearls only" checkbox.

The list is drawn from the public pearl list (the file behind the counts), so its length is final + verified of the same
source; the page links, the checkbox label and the browser behaviour (checkbox, search words, address, zero results) are held here.
"""
import glob
import json
from pathlib import Path

import pytest

from tests.test_pearl_badge import client_full, pearls, row  # noqa: F401
from tests.test_pearl_frontend import ORIGIN, browser, client, pearl_page  # noqa: F401

NEW = Path(__file__).resolve().parents[1] / 'new/en'


def test_the_list_has_one_row_per_agent_and_role_pair_and_as_many_as_the_counts_say(pearls, client_full):
    pearls([row(), row(role='fx.rate.v1', resource_id=101, level='verified'), row(resource_id=100, role='geo.lookup.v1', label='Places', level='verified'),
            row(resource_id=102, level='provisional'), row(resource_id=103, role='a.v1', terms='prohibits'),
            row(resource_id=100, role='x.v1', label='X'), row(resource_id=100, role='y.v1', label='Y'), row(resource_id=100, role='z.v1', label='Z')])
    listing = client_full.get('/api/pearls/list')
    counts = client_full.get('/api/pearls/public').json()['counts']
    assert listing.status_code == 200 and listing.headers['cache-control'].startswith('public') and 'set-cookie' not in listing.headers
    data = listing.json()
    assert data['count'] == len(data['rows']) == counts['final'] + counts['verified'] == 7      # agent 100 has five roles: the per-agent cap of the badge does not cut the list
    assert all({'id', 'name', 'job', 'level', 'badge', 'measured', 'direct'} <= set(r) for r in data['rows'])
    assert [r['level'] for r in data['rows']][:1] == ['final'] and {r['id'] for r in data['rows'] if r['direct']} == {103}
    assert all(r['level'] in ('final', 'verified') for r in data['rows'])


def test_every_pearl_number_card_links_to_the_pearl_view_and_explore_has_the_checkbox():
    pages = [p for p in sorted(glob.glob(str(NEW / '*.html'))) if 'data-metric="pearls"' in Path(p).read_text(encoding='utf-8')]
    assert len(pages) == 9
    for page in pages:
        html = Path(page).read_text(encoding='utf-8')
        assert html.count('<a class="metric-link" href="https://agentconcierge.biz/new/en/explore.html?view=pearls">Verified pearls</a></h2>') == 2, page
        assert html.count('<a class="metric-link" href="https://agentconcierge.biz/necklaces">Necklaces</a></h2>') == 2, page   # the necklace card opens the list (PM 11-18)
    explore = (NEW / 'explore.html').read_text(encoding='utf-8')
    assert '<input type="checkbox" id="xPearls"> Pearls only</label>' in explore          # the label wraps the input: one click target, read as one control


def test_the_script_reads_the_pearl_list_once_and_never_writes_markup_from_it():
    script = (NEW / 'assets/pearl-ui.js').read_text(encoding='utf-8')
    block = script[script.index('const pearlBox'):script.index('if(pearlViewOn()){syncPearlView();renderPearlView();}')]
    assert block.count("fetch('/api/pearls/list'") == 1 and 'innerHTML' not in block and "params.set('pearls','1')" in block and 'view' in block


ROWS = [{'id': 11, 'name': 'Airport Desk', 'role': 'airport.lookup.v1', 'job': 'Airport lookup', 'level': 'final', 'badge': 'Final pearl, #1 for Airport lookup',
         'measured': 'Passed 3 of 3 role tasks · confirmed on 1 day · last checked 2026-11-18', 'direct': False},
        {'id': 12, 'name': 'Rates Pro', 'role': 'fx.rate.v1', 'job': 'Exchange rates', 'level': 'verified', 'badge': 'Verified pearl',
         'measured': 'Passed 3 of 3 role tasks · confirmed on 1 day · last checked 2026-11-18', 'direct': True},
        {'id': 12, 'name': 'Rates Pro', 'role': 'fx.history.v1', 'job': 'Exchange history', 'level': 'verified', 'badge': 'Verified pearl',
         'measured': 'Passed 3 of 3 role tasks · confirmed on 1 day · last checked 2026-11-18', 'direct': True}]


@pytest.mark.parametrize('width', (1280, 768, 375))
def test_the_checkbox_and_the_view_show_every_pearl_search_by_words_and_keep_the_state_in_the_address(pearl_page, width):
    page, errors, _ = pearl_page
    page.set_viewport_size({'width': width, 'height': 900})
    page.route('**/api/pearls/list', lambda route: route.fulfill(status=200, json={'schema': 'x', 'count': 3, 'rows': ROWS, 'direct_note': 'Connect directly'}))
    page.goto(ORIGIN + '/new/en/explore.html?view=pearls')
    page.wait_for_selector('#xResults .pearl-result')
    assert page.locator('#xPearls').is_checked() and page.locator('#xResults .pearl-result').count() == 3
    assert page.locator('#uxExploreStatus').inner_text() == '3 pearls · 2 agents · 3 jobs'
    assert page.locator('label:has(#xPearls)').inner_text().strip() == 'Pearls only'                 # label tied to the control
    page.fill('#xQ', 'airport')
    page.wait_for_function("() => document.querySelectorAll('#xResults .pearl-result').length === 1")
    assert page.locator('#uxExploreStatus').inner_text() == '1 of 3 pearls match “airport”'
    assert page.evaluate('location.search + location.hash') == '?pearls=1&q=airport#explore?pearls=1&q=airport'
    page.fill('#xQ', 'nothing-like-this')
    page.wait_for_selector('.pearl-view-note:has-text("No pearls match")')
    assert page.locator('#xResults .pearl-result').count() == 0
    page.fill('#xQ', '')
    page.wait_for_function("() => document.querySelectorAll('#xResults .pearl-result').length === 3")
    assert page.evaluate('document.documentElement.scrollWidth - innerWidth') <= 0
    page.reload()                                                                                   # the address keeps the state
    page.wait_for_selector('#xResults .pearl-result')
    assert page.locator('#xPearls').is_checked() and page.locator('#xResults .pearl-result').count() == 3
    assert not errors

