"""Each Explore intent owns centered progress, including cached revalidation."""
import time
import pytest
from playwright.sync_api import expect
from agent_market.concierge.front import clear_front_caches
from tests.test_fast_single_recommendation import catalog  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401
from tests.test_explore_report_filter_browser import explore_page, _open, _fulfill, _wait_calls  # noqa: F401


def _loader_state(page):
    return page.evaluate('''()=>{const element=document.getElementById('binaryLoader'),style=getComputedStyle(element);
      return {active:activeReqs,tokens:loaderOperations.size,popover:element.matches(':popover-open'),
      aria:element.getAttribute('aria-hidden'),display:style.display,visibility:style.visibility,opacity:style.opacity}}''')


def _hidden(page):
    expect(page.locator('#binaryLoader')).not_to_be_visible()
    assert _loader_state(page)=={'active':0,'tokens':0,'popover':False,'aria':'true','display':'none','visibility':'hidden','opacity':'0'}


def _searching(page):
    expect(page.locator('#xResults')).to_have_attribute('aria-busy','true')
    expect(page.locator('#binaryLoader')).to_be_visible()
    assert _loader_state(page)['tokens']>=1


def _prepare_45(state):
    _open(state)
    for number in range(43):state.add(f'Report Forecast {number:02}',report_at=state.now-60)
    clear_front_caches();state.hold=True


@pytest.mark.parametrize('mode',['search','report-filter'])
def test_fresh_and_cached_explicit_searches_show_progress_until_their_response(explore_page,mode):
    state=explore_page;page=state.page;_prepare_45(state);before=len(state.calls)
    if mode=='search':
        page.locator('#xQ').fill('Forecast');page.locator('#xGo').click()
    else:page.locator('#xHasReport').check()
    _wait_calls(state,before+1);_searching(page)
    _fulfill(state.calls[-1]);expect(page.locator('#xResults .acard')).to_have_count(15)
    page.wait_for_function('()=>exploreRequestedKey===null');_hidden(page)
    before=len(state.calls);page.locator('#xGo').click();_wait_calls(state,before+1)
    expect(page.locator('#xResults .acard')).to_have_count(15);_searching(page)
    _fulfill(state.calls[-1]);page.wait_for_function('()=>exploreRequestedKey===null');_hidden(page)
    assert not state.errors and not state.blocked


def test_search_completion_cannot_hide_independent_detail_progress(explore_page):
    state=explore_page;page=state.page;_open(state);state.hold=True;state.hold_details=True
    before=len(state.calls);page.locator('#xGo').click();_wait_calls(state,before+1);_searching(page)
    rid=state.add('Uncached detail progress');page.evaluate('id=>void openAgent(id)',rid)
    page.wait_for_function('()=>activeReqs===2');_fulfill(state.calls[-1])
    page.wait_for_function('()=>exploreRequestedKey===null');assert _loader_state(page)['tokens']==1
    expect(page.locator('#binaryLoader')).to_be_visible()
    deadline=time.monotonic()+3
    while not state.details and time.monotonic()<deadline:page.wait_for_timeout(10)
    assert len(state.details)==1;_fulfill(state.details[0]);page.wait_for_function('()=>activeReqs===0');_hidden(page)
    assert not state.errors and not state.blocked


@pytest.mark.parametrize('marker',['missing','wrong-limit'])
def test_partial_or_other_limit_cache_does_not_replace_a_complete_visible_page(explore_page,marker):
    state=explore_page;page=state.page;_prepare_45(state)
    # First obtain the complete first page (15 cards since 11-12).
    before=len(state.calls);page.locator('#xGo').click();_wait_calls(state,before+1)
    _fulfill(state.calls[-1]);expect(page.locator('#xResults .acard')).to_have_count(15)
    page.evaluate('''marker=>{const key='explore:v4:'+JSON.stringify(['','','','0','0','0',0,15]);
      const preview={...getSwrCache(key)};preview.items=preview.items.slice(0,3);
      if(marker==='missing')delete preview._complete_page;else preview._request_limit=90;
      setSwrCache(key,preview)}''',marker)
    before=len(state.calls);page.locator('#xGo').click();_wait_calls(state,before+1)
    expect(page.locator('#xResults .acard')).to_have_count(15);_searching(page)
    _fulfill(state.calls[-1]);page.wait_for_function('()=>exploreRequestedKey===null');_hidden(page)
    assert not state.errors


@pytest.mark.parametrize('outcome',['failure','cancel'])
def test_failed_or_cancelled_search_releases_only_its_progress(explore_page,outcome):
    state=explore_page;page=state.page;_open(state);state.hold=True;before=len(state.calls)
    page.locator('#xQ').fill('Uncached Forecast');page.locator('#xGo').click()
    _wait_calls(state,before+1);old=state.calls[-1];_searching(page)
    if outcome=='failure':
        _fulfill(old,400);expect(page.locator('#xTitle')).to_have_text('Search unavailable')
    else:
        page.locator('#xQ').fill('Next search');expect(page.locator('#binaryLoader')).to_be_visible()
        _fulfill(old);_wait_calls(state,before+2);_searching(page);_fulfill(state.calls[-1])
    page.wait_for_function('()=>exploreRequestedKey===null');_hidden(page)
    assert not state.errors and not state.blocked


def test_leaving_explore_cancels_debounce_and_does_not_leave_centered_progress(explore_page):
    state=explore_page;page=state.page;_open(state);before=len(state.calls)
    page.locator('#xQ').fill('Pending search');expect(page.locator('#binaryLoader')).to_be_visible()
    page.locator('.nav-tab[data-tab="about"]').click();_hidden(page)
    page.wait_for_timeout(350);assert len(state.calls)==before
    assert not state.errors
