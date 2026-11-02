"""Tests for Explore Search Panel 2-line layout and fixed right search button."""

import json
import time

import pytest
from playwright.sync_api import expect

from agent_market.capability_registry import Registry
from agent_market.concierge.bootstrap_delivery import EMPTY
from tests.test_concierge import w  # noqa: F401 (fixture)
from tests.test_explore_report_filter_browser import explore_page, _expect_ids  # noqa: F401
from tests.test_fast_single_recommendation import catalog  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401


def test_explore_search_layout_structure(w, legacy_public_entry):
    world, c, _ = w
    r = c.get("/", headers={"accept": "text/html"})
    assert r.status_code == 200
    html = r.text

    # 1. Container structure
    assert 'class="explore-search-wrap"' in html
    assert 'class="explore-inputs-row"' in html
    assert 'class="explore-checkboxes-row"' in html

    # 2. Line 1: Input, Select Boxes, and Search Button
    idx_inputs_row = html.find('class="explore-inputs-row"')
    idx_checks_row = html.find('class="explore-checkboxes-row"')
    assert 0 < idx_inputs_row < idx_checks_row, "Inputs row must come before Checkboxes row"

    # Input and selects inside explore-inputs-row
    row1_html = html[idx_inputs_row:idx_checks_row]
    assert 'id="xQ"' in row1_html
    assert 'id="xKind"' in row1_html
    assert 'id="xCategory"' in row1_html
    assert 'id="xGo"' in row1_html, "Search button must be in line 1 on the right"

    # 3. Line 2: Checkboxes inside explore-checkboxes-row
    idx_chips = html.find('id="xChips"')
    assert idx_checks_row < idx_chips, "Checkboxes row must come before category chips"
    row2_html = html[idx_checks_row:idx_chips]
    assert 'id="xVerified"' in row2_html
    assert 'id="xNoAuth"' in row2_html
    assert 'id="xHasReport"' in row2_html
    assert 'id="xGo"' not in row2_html, "Search button must NOT be in checkboxes row"

    # 4. Search button fixed right styling
    assert "button#xGo" in html
    assert "margin-left: auto" in html
    assert "flex-shrink: 0" in html


@pytest.mark.parametrize('preview', [False, True], ids=['empty-shell', 'inline-preview'])
def test_explore_category_chip_toggle_and_initial_newest_display(explore_page, catalog, monkeypatch, preview):
    state = explore_page
    _, front, client, _, _ = catalog
    initial = client.get('/api/explore?limit=45').json()
    bootstrap = dict(EMPTY)
    if preview:
        bootstrap['explore'] = dict(initial, items=initial['items'][:1])
    # Exercise both lean delivery forms. A one-card preview must not suppress
    # the authoritative full-page request on the first Explore visit.
    monkeypatch.setattr(front.html_bootstrap, 'read', lambda: json.dumps(bootstrap))
    page = state.page
    page.goto('https://agentconcierge.biz/#explore')
    _expect_ids(state, state.all_ids)
    assert json.loads(page.locator('#appBootstrapData').text_content()) == bootstrap
    assert state.calls and state.calls[0]['params']['limit'] == '45'
    assert state.calls[0]['params']['q'] == ''
    expect(page.locator('#xVerified')).not_to_be_checked()
    expect(page.locator('#xHasReport')).not_to_be_checked()
    expect(page.locator('#xResults .skeleton-card')).to_have_count(0)
    expect(page.locator('#xTitle')).to_contain_text('Latest discovered agents')

    weather = page.locator('#xChips').get_by_role('button', name='Weather', exact=True)
    with page.expect_response('**/api/explore?*'):
        weather.click()
    _expect_ids(state, state.all_ids)
    query=weather.get_attribute('data-q')
    expect(page.locator('#xQ')).to_have_value(query)
    expect(weather).to_have_class('chip-btn active on')
    assert state.calls[-1]['params']['q'] == query
    expect(page.locator('#xTitle')).to_contain_text('Search Results')

    with page.expect_response('**/api/explore?*'):
        weather.click()
    _expect_ids(state, state.all_ids)
    expect(page.locator('#xQ')).to_have_value('')
    expect(weather).to_have_class('chip-btn')
    assert state.calls[-1]['params']['q'] == '' and state.calls[-1]['params']['limit'] == '45'
    expect(page.locator('#xTitle')).to_contain_text('Latest discovered agents')
    assert not state.errors and not state.blocked


def test_explore_initial_agents_sorted_newest_first_and_populated(w):
    world, c, _ = w
    store = world.store
    now = time.time()
    id1 = store.upsert_resource({
        "key": "x402:https://api.agent-older.org/v1", "source": "test", "kind": "x402",
        "url": "https://api.agent-older.org/v1", "name": "Older Agent", "description": "Earlier discovery",
        "category": "finance_crypto",
    })
    id2 = store.upsert_resource({
        "key": "x402:https://api.agent-newer.org/v1", "source": "test", "kind": "x402",
        "url": "https://api.agent-newer.org/v1", "name": "Newer Agent", "description": "Latest discovery",
        "category": "finance_crypto",
    })
    with store.tx() as db:
        db.execute("UPDATE resources SET health_status='healthy', auth_observed=0, trial_ok=1, first_seen=? WHERE id=?", (now - 1000, id1))
        db.execute("UPDATE resources SET health_status='healthy', auth_observed=0, trial_ok=1, first_seen=? WHERE id=?", (now, id2))

    # A legacy trial flag is not current execution evidence. Record explicit
    # successful checks for these synthetic current-version fixtures only.
    registry = Registry(store)
    for identity in (id1, id2):
        registry.record(registry.current(identity), scope='execution', outcome='succeeded',
            started=now, finished=now)

    from agent_market.concierge.front import clear_front_caches
    clear_front_caches()

    res = c.get("/api/explore?kind=x402&verified=true&limit=10")
    assert res.status_code == 200
    data = res.json()
    items = data.get("items", [])
    assert len(items) >= 2, "Explicit x402 explore query must return agents"
    
    # Newer agent must appear before older agent (sorted by newest first)
    idx_newer = next((i for i, it in enumerate(items) if it["id"] == id2), None)
    idx_older = next((i for i, it in enumerate(items) if it["id"] == id1), None)
    assert idx_newer is not None and idx_older is not None
    assert idx_newer < idx_older, "Explore agents must be sorted by newest first (first_seen DESC)"

