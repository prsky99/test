"""Render complete contracts from compact guides in isolated browser routes."""
# ruff: noqa: F401,F811 -- shared isolated catalog and Chromium fixtures
from pathlib import Path
import pytest
from playwright.sync_api import expect
from agent_market.collector import usage
from agent_market.owned_data_agents.catalog import tool_spec
from tests.report_fixtures import execution_report
from tests.test_single_agent_chat_browser import chat_page
from tests.test_fast_single_recommendation import catalog
from tests.test_front_workflow_browser import browser

REPORT=Path('reports/weather-news-quality-2026-10-26')


@pytest.mark.parametrize('topic',['news','weather'])
def test_original_weather_news_contract_renders_and_opens_details(chat_page,catalog,request,topic):
    store,_,_,add,now=catalog
    if topic=='news':
        spec=tool_spec('technology-news');name='Technology News';task='technology news search'
    else:
        spec={'name':'get_weather','description':'Current weather and multi-day forecast for any location.',
              'inputSchema':{'type':'object','properties':{'location':{'type':'string','maxLength':100}},
                             'required':['location']},'annotations':{'readOnlyHint':True}}
        name='Global Weather';task='weather forecast Seoul'
    rid=add(name,description=spec['description'])
    compact=usage.compact_tools([spec])
    store.record_usage(rid,compact,usage.tools_hash(compact),{'tools':compact},None,None,full_tools=[spec])
    execution_report(store,rid,now,slug='weather-news-browser-'+topic,title='Isolated source verification',
                     tool_name=spec['name'],status_code=200)
    page,_,bodies,errors,_=chat_page
    page.goto('https://agentconcierge.biz/#chat')
    REPORT.mkdir(exist_ok=True,parents=True)
    mode=request.node.callspec.params['chat_page']
    page.screenshot(path=str(REPORT/f'{topic}-{mode}-before.png'),full_page=True)
    page.locator('#chatInput').fill('MCP '+task)
    page.locator('#chatSubmit').click()
    card=page.locator('.chat-recommendation').first
    expect(card).to_contain_text(name)
    expect(card).to_contain_text(spec['name'])
    expect(page.locator('#chatSubmit')).to_be_enabled()
    item=bodies[-1]['data']['recommendations'][0]
    assert item['id']==rid and item['tools_schema'][0]['inputSchema']==spec['inputSchema']
    page.screenshot(path=str(REPORT/f'{topic}-{mode}-after.png'),full_page=True)
    card.get_by_role('button',name='Calling details').click()
    expect(page.locator('#drawer')).to_be_visible()
    assert page.locator('#drawer script').count()==0
    page.screenshot(path=str(REPORT/f'{topic}-{mode}-details.png'),full_page=True)
    page.locator('#closeDrawer').click()
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
    assert not errors
