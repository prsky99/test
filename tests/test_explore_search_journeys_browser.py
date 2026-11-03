"""Search chips, URL history, input feedback and layout with isolated handlers."""
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import pytest
from playwright.sync_api import expect
from tests.test_explore_report_filter_browser import explore_page, _open, _wait_calls, _fulfill  # noqa: F401
from tests.test_fast_single_recommendation import catalog  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401


def test_all_twenty_quick_tasks_execute_and_all_evidence_filters_requery(explore_page):
    state=explore_page;page=state.page;_open(state)
    page.locator('.pearl-more-tasks').evaluate('node=>node.open=true')
    buttons=page.locator('#xChips button').all()
    assert len(buttons)==20
    for button in buttons:
        expected=button.get_attribute('data-q')
        with page.expect_response('**/api/explore?*'):button.click()
        expect(page.locator('#xQ')).to_have_value(expected)
        assert state.calls[-1]['params']['q']==expected
        page.wait_for_function('exploreRequestedKey === null')
        expect(page.locator('#binaryLoader')).not_to_be_visible()
    for field,parameter in [('xVerified','verified'),('xNoAuth','no_auth'),('xHasReport','has_report')]:
        with page.expect_response('**/api/explore?*'):page.locator('#'+field).check()
        assert state.calls[-1]['params'][parameter]=='true'
    assert not state.errors and not state.blocked


def test_url_survives_reload_and_back_forward_restores_controls(explore_page):
    state=explore_page;page=state.page
    page.goto('https://agentconcierge.biz/#explore?q=Forecast&kind=mcp&category=travel_maps_weather&no_auth=1')
    expect(page.locator('#xQ')).to_have_value('Forecast')
    expect(page.locator('#xKind')).to_have_value('mcp')
    expect(page.locator('#xNoAuth')).to_be_checked()
    expect(page.locator('#xCategory')).to_have_value('travel_maps_weather')
    expect(page.locator('#xResults .acard')).to_have_count(4)
    with page.expect_response('**/api/explore?*'):page.locator('#xQ').fill('Historical')
    page.wait_for_function('exploreRequestedKey === null')
    assert parse_qs(urlsplit(page.url).fragment.partition('?')[2])['q']==['Historical']
    page.reload()
    expect(page.locator('#xQ')).to_have_value('Historical')
    expect(page.locator('#xResults .acard')).to_have_count(1)
    page.go_back()
    expect(page.locator('#xQ')).to_have_value('Forecast')
    expect(page.locator('#xResults .acard')).to_have_count(4)
    page.go_forward()
    expect(page.locator('#xQ')).to_have_value('Historical')
    expect(page.locator('#xResults .acard')).to_have_count(1)
    assert not state.errors and not state.blocked


def test_long_deeplink_is_actionable_and_never_sent_to_api(explore_page):
    state=explore_page;page=state.page
    page.goto('https://agentconcierge.biz/#explore?q='+('x'*501))
    expect(page.locator('#xSearchHint')).to_contain_text('500 characters')
    expect(page.locator('#xTitle')).to_have_text('Shorten your search')
    assert not state.calls
    expect(page.locator('#binaryLoader')).not_to_be_visible()
    with page.expect_response('**/api/explore?*'):page.locator('#xQ').fill('weather')
    expect(page.locator('#xSearchHint')).to_be_hidden()
    assert not state.errors


def test_typo_suggestion_is_explicit_and_keeps_selected_protocol(explore_page):
    state=explore_page;page=state.page
    # Curated misspellings (forcasst) are searched as corrected; a fuzzy one stays an explicit suggestion.
    page.goto('https://agentconcierge.biz/#explore?q=forecsat&kind=mcp')
    suggestion=page.get_by_role('button',name='Try “forecast”')
    expect(suggestion).to_be_visible()
    with page.expect_response('**/api/explore?*'):suggestion.click()
    expect(page.locator('#xQ')).to_have_value('forecast')
    assert state.calls[-1]['params']['kind']=='mcp'
    expect(page.locator('#xResults .acard')).to_have_count(4)
    assert not state.errors and not state.blocked


def test_centered_progress_covers_debounce_filters_and_cancellation(explore_page):
    state=explore_page;page=state.page;_open(state);state.hold=True
    page.locator('#xQ').fill('Forecast')
    expect(page.locator('#binaryLoader')).to_be_visible()
    _wait_calls(state,2)
    old=state.calls[-1]
    page.locator('#xHasReport').check()
    _wait_calls(state,3)
    latest=state.calls[-1]
    _fulfill(old)
    expect(page.locator('#binaryLoader')).to_be_visible()
    box=page.locator('#binaryLoader').bounding_box();size=page.viewport_size
    assert abs(box['x']+box['width']/2-size['width']/2)<5
    assert abs(box['y']+box['height']/2-size['height']/2)<5
    folder=Path('reports/explore-remediation-2026-10-26/screenshots');folder.mkdir(exist_ok=True)
    page.screenshot(path=str(folder/'search-in-progress.png'))
    _fulfill(latest)
    expect(page.locator('#binaryLoader')).not_to_be_visible()
    assert page.evaluate('loaderOperations.size')==0
    assert not state.errors


@pytest.mark.parametrize('width',[320,768,1024,1440])
def test_protocol_text_cookie_notice_and_category_labels_do_not_overlap(explore_page,width):
    state=explore_page;page=state.page;page.set_viewport_size({'width':width,'height':960});_open(state)
    buttons=page.locator('#xKind + .pearl-protocol-segmented button')
    expect(buttons).to_have_count(4)
    for button in buttons.all():
        assert button.evaluate('node=>{const b=node.getBoundingClientRect(),r=document.createRange();r.selectNodeContents(node);const t=r.getBoundingClientRect();return t.left>=b.left&&t.right<=b.right+1}')
    pos = page.locator('#cookieConsentBanner').evaluate('node=>getComputedStyle(node).position')
    assert pos in ('fixed', 'relative')
    if pos == 'relative':
        banner=page.locator('#cookieConsentBanner').bounding_box();section=page.locator('#secExplore').bounding_box()
        assert banner['y']+banner['height']<=section['y']
    option=page.locator('#xCategory option[value="travel_maps_weather"]').text_content()
    expect(page.locator('#xResults .ux-agent-category').first).to_have_text(option)
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    folder=Path('reports/explore-remediation-2026-10-26/screenshots');folder.mkdir(exist_ok=True)
    page.screenshot(path=str(folder/('explore-'+str(width)+'.png')))
    assert not state.errors and not state.blocked


def test_mobile_explicit_search_moves_focus_to_results(explore_page):
    state=explore_page;page=state.page;page.set_viewport_size({'width':390,'height':844});_open(state)
    page.locator('#xQ').fill('Forecast')
    page.locator('#xGo').click()
    expect(page.locator('#xTitle')).to_be_focused()
    # The scroll is smooth unless reduced motion is set, so wait for it to settle.
    page.wait_for_function("()=>{const y=document.getElementById('xTitle').getBoundingClientRect().top;return y>=0&&y<160}")
    assert not state.errors
