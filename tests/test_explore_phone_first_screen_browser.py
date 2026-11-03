"""Phones: the category folds with the filters and a search brings the first result onto the screen (11-03)."""
from playwright.sync_api import expect

from tests.test_pearl_frontend import ORIGIN, browser, client, pearl_page


def results_route(page):
    items = [{'id': i + 1, 'name': 'Weather capability ' + str(i + 1), 'kind': 'mcp', 'category': 'travel_maps_weather',
              'description': 'Current conditions and forecasts for a named city.', 'eval_grade': 'B'} for i in range(12)]
    page.route('**/api/explore?*', lambda route: route.fulfill(json={'items': items, 'total': 12, 'has_more': False}))


def test_category_folds_behind_the_filter_button_on_a_phone(pearl_page):
    page, errors, calls = pearl_page
    results_route(page)
    page.set_viewport_size({'width': 375, 'height': 812})
    page.goto(ORIGIN + '/#explore')
    expect(page.locator('#xResults .acard:not(.skeleton-card)')).to_have_count(12)
    toggle = page.locator('.ux-filter-toggle')
    expect(page.locator('#xCategory')).not_to_be_visible()
    toggle.click()
    page.locator('#xCategory').select_option(index=1)
    expect(toggle).to_contain_text('(1 on)')
    assert page.evaluate('document.documentElement.scrollWidth') <= 375
    # Choosing a filter keeps the visitor at the filters.
    assert page.locator('#xCategory').bounding_box()['y'] < 812
    page.set_viewport_size({'width': 1280, 'height': 900})
    expect(page.locator('.pearl-search-panel .explore-inputs-row #xCategory')).to_be_visible()
    expect(toggle).to_be_hidden()


def test_search_on_a_phone_shows_the_first_result_on_the_first_screen(pearl_page):
    page, errors, calls = pearl_page
    results_route(page)
    page.emulate_media(reduced_motion='reduce')
    page.set_viewport_size({'width': 375, 'height': 812})
    page.goto(ORIGIN + '/#explore')
    expect(page.locator('#xResults .acard:not(.skeleton-card)')).to_have_count(12)
    page.locator('#xQ').fill('weather forecast')
    page.locator('#xGo').click()
    first = page.locator('#xResults .acard:not(.skeleton-card)').first
    expect(first).to_be_in_viewport()
    assert 0 <= first.bounding_box()['y'] < 812 - 80
    assert page.evaluate('document.documentElement.scrollWidth') <= 375
