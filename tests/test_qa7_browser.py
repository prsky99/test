"""Keyboard, narrow layouts, learning search and public identity rendering."""
import json
from pathlib import Path

import pytest
from tests.test_single_agent_chat_browser import chat_page
from tests.test_fast_single_recommendation import catalog
from tests.test_front_workflow_browser import browser
playwright=pytest.importorskip('playwright.sync_api')


@pytest.mark.parametrize('width',[320,390,768])
def test_narrow_pages_controls_and_chat_input(chat_page,catalog,width,request):
    page,_,_,errors,_=chat_page
    page.set_viewport_size({'width':width,'height':844})
    page.add_init_script("window.__qaShifts=[];new PerformanceObserver(l=>l.getEntries().forEach(e=>{if(!e.hadRecentInput)window.__qaShifts.push({value:e.value,t:e.startTime});})).observe({type:'layout-shift',buffered:true});")
    measurements=[]
    for tab in ('overview','chat','workflows','test','explore'):
        page.goto('https://agentconcierge.biz/#'+tab)
        page.wait_for_timeout(400)
        sizes=page.evaluate("""()=>({viewport:innerWidth,scroll:document.documentElement.scrollWidth,protocol:document.querySelector('#chatProtocol').getBoundingClientRect().width,shifts:window.__qaShifts})""")
        assert sizes['scroll']<=width+1,(tab,sizes)
        if tab=='chat':assert sizes['protocol']<=width
        measurements.append({'page':tab,**sizes})
    page.goto('https://agentconcierge.biz/#chat')
    if page.locator('.pearl-protocol-segmented[aria-label="Recommendation protocol"]').count():
        page.get_by_role('group',name='Recommendation protocol',exact=True).get_by_role('button',name='MCP',exact=True).click()
    else:page.locator('#chatProtocol').select_option('mcp')
    page.locator('#chatInput').fill('weather forecast')
    page.locator('#chatInput').press('Enter')
    playwright.expect(page.locator('.chat-recommendation').first).to_contain_text('Verified Weather A')
    page.locator('.chat-recommendation').first.get_by_role('button',name='Calling details').click()
    playwright.expect(page.locator('#drawer')).to_be_visible()
    assert not errors,errors
    target=Path('reports/qa7-remediation-2026-10-29');target.mkdir(exist_ok=True)
    mode=request.node.callspec.params['chat_page']
    page.screenshot(path=str(target/f'after-{mode}-{width}.png'),full_page=True)
    (target/f'layout-{mode}-{width}.json').write_text(json.dumps(measurements,indent=2))


def test_published_learning_search_has_working_destinations(chat_page,request):
    if request.node.callspec.params['chat_page']=='legacy':pytest.skip('Published guide uses the public learning layout.')
    page,_,_,errors,_=chat_page
    page.goto('https://agentconcierge.biz/#learn')
    search=page.get_by_label('Search learning guides',exact=True)
    playwright.expect(search).to_be_visible()
    search.fill('MCP')
    results=page.locator('#learnGuideResults button')
    assert results.count()>0
    results.first.click()
    assert page.locator('[role="tabpanel"]:visible').count()>=1
    search.fill('zzznomatchingguide')
    playwright.expect(page.locator('.learn-guide-search [role="status"]')).to_contain_text('No matching guides')
    assert not errors
