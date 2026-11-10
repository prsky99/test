"""Verify task evidence, safe rendering and recovery in isolated Chromium."""
# ruff: noqa: F401,F811 -- shared isolated browser/catalog fixtures
import re
from pathlib import Path
from tests.test_single_agent_chat_browser import chat_page
from tests.test_front_workflow_browser import browser
from tests.test_fast_single_recommendation import catalog
from playwright.sync_api import expect

REPORT = Path('reports/chat-recommendation-quality-development-2026-10-26')


def test_selected_tool_scope_is_visible_and_not_inferred_from_connection(chat_page,request):
    page,_,_,errors,_=chat_page
    page.goto('https://agentconcierge.biz/#chat')
    page.locator('#chatInput').fill('MCP weather forecast')
    page.locator('#chatSubmit').click()
    first=page.locator('.chat-recommendation').first
    expect(page.locator('.chat-recommendation:visible')).to_have_count(1)
    expect(page.locator('.chat-alternatives > summary')).to_have_text('Show 2 alternatives')
    page.locator('.chat-alternatives > summary').click()
    expect(page.locator('.chat-recommendation:visible')).to_have_count(3)
    page.locator('.chat-alternatives > summary').click()
    # An unrecorded tool check is omitted rather than shown as an internal status.
    expect(first).not_to_contain_text('Selected tool check:')
    expect(first).not_to_contain_text('Not separately recorded')
    # The reason names the selected tool: the server's sentence ("... through its forecast tool ...",
    # 11-04 B3) when it sends one, otherwise the page's own ("Its forecast tool covers ...").
    expect(first.locator('.chat-why')).to_contain_text(re.compile(r'tool covers|through its \w+ tool'))
    expect(page.locator('#chatSubmit')).to_be_enabled()
    first.get_by_role('button',name='Calling details').click()
    expect(page.locator('#drawer')).to_be_visible()
    page.locator('#closeDrawer').click()
    REPORT.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(REPORT/('task-evidence-'+request.node.callspec.params['chat_page']+'.png')),full_page=True)
    assert not errors


def test_new_constraint_metadata_is_allowlisted_and_escaped(chat_page):
    page,_,_,errors,_=chat_page
    page.set_viewport_size({'width':390,'height':844})
    page.goto('https://agentconcierge.biz/#chat')
    page.evaluate('''() => appendChatBubble('bot','',{data:{recommendations:[{
      id:1,name:'PDF Extraction',kind:'mcp',tools:['extract'],url:'https://agentconcierge.biz/api/gateway/mcp/1',
      task_fit:{matched:['pdf_input','ocr','json_output','<img src=x onerror="window.bad=1">']},
      task_verification:{status:'not_recorded',tool:'extract'}
    }]}})''')
    first=page.locator('.chat-recommendation').first
    expect(first).to_contain_text('PDF input')
    expect(first).to_contain_text('JSON output')
    assert first.locator('img,[onerror]').count()==0
    assert not page.evaluate('window.bad===1')
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
    page.screenshot(path=str(REPORT/'mobile-constraint-evidence.png'),full_page=True)
    assert not errors


def test_no_match_is_not_displayed_as_a_successful_answer(chat_page):
    page,_,_,errors,_=chat_page
    page.goto('https://agentconcierge.biz/#chat')
    page.locator('#chatInput').fill('MCP obscure fictional capability')
    page.locator('#chatSubmit').click()
    expect(page.locator('#chatMessages')).to_contain_text('No currently verified match meets this task')
    expect(page.locator('#chatSubmit')).to_be_enabled()
    assert page.locator('#chatForm').get_attribute('aria-busy')=='false'
    assert not errors
