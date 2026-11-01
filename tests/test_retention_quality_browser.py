"""Chat recommendations preserve the task for explicit review, never auto-execution."""
import json
import pytest
from pathlib import Path
from tests.test_single_agent_chat_browser import chat_page,browser,catalog,playwright


def published(request):
    if request.node.callspec.params['chat_page']!='published':pytest.skip('Published presentation feature.')


def test_a2a_task_survives_review_and_delayed_presets(chat_page,catalog,request):
    published(request)
    page,requests,_,errors,_=chat_page
    _,_,_,add,now=catalog
    rid=add('Global Forecast',kind='a2a',report_at=now-1)
    task='Find a weather forecast agent for Seoul'
    page.goto('https://agentconcierge.biz/#chat')
    page.locator('#chatInput').fill(task);page.locator('#chatSubmit').click()
    button=page.locator('.chat-review-task').first
    playwright.expect(button).to_be_visible()
    evidence=Path('/Users/kingstonelee/workspace/A2A_Discovery/reports/frontend-retention-quality-2026-10-25')
    page.screenshot(path=str(evidence/'chat-before-task-review.png'),full_page=True)
    button.click()
    playwright.expect(page.locator('#tbA2aMessage')).to_have_value(task)
    playwright.expect(page.locator('#chatTaskReview')).to_contain_text('Nothing has been sent')
    assert page.evaluate('tbSelectedAgent.id')==rid
    # A late preset refresh must never replace the explicit user choice/input.
    page.evaluate('renderTestbenchRecipes()')
    playwright.expect(page.locator('#tbA2aMessage')).to_have_value(task)
    assert 'Seoul'not in page.url
    assert not any(method=='POST'and any(s in path for s in ('/test/execute','/test/run','/proxy/call','/workflows/run'))for method,path in requests)
    assert not errors
    page.screenshot(path=str(evidence/'test-after-task-review.png'),full_page=True)


@pytest.mark.parametrize('compact',[False,True])
def test_mcp_query_is_copied_into_the_actual_selected_tool(chat_page,catalog,request,compact):
    published(request)
    page,requests,_,errors,_=chat_page
    _,_,_,add,now=catalog
    schema={'name':'forecast','description':'Search weather forecasts for any location.','inputSchema':{'type':'object','properties':{'query':{'type':'string'}},'required':['query']}}
    if compact:
        fields=schema.pop('inputSchema');schema.update(params=fields['properties'],required=fields['required'])
    add('Queryable Forecast',kind='mcp',report_at=now-1,usage_guide=json.dumps({'tools':[schema]}))
    task='MCP weather forecast for Tokyo'
    page.goto('https://agentconcierge.biz/#chat')
    page.locator('#chatInput').fill(task);page.locator('#chatSubmit').click()
    page.locator('.chat-review-task').first.click()
    playwright.expect(page.locator('#chatTaskReview')).to_contain_text('ready to review')
    assert json.loads(page.locator('#tbArgsEditor').input_value())['query']==task
    playwright.expect(page.locator('[data-arg-key="query"]')).to_have_value(task)
    assert not errors


def test_ambiguous_schema_keeps_task_without_guessing_inputs(chat_page,request):
    published(request)
    page,_,_,errors,_=chat_page
    page.goto('https://agentconcierge.biz/#chat')
    task='MCP weather forecast for Seoul'
    page.locator('#chatInput').fill(task);page.locator('#chatSubmit').click()
    page.locator('.chat-review-task').first.click()
    playwright.expect(page.locator('#chatTaskReview')).to_contain_text('needs specific inputs')
    assert task not in page.locator('#tbArgsEditor').input_value()
    assert not errors


def test_task_review_uses_masked_text_and_never_html(chat_page,request):
    published(request)
    page,_,_,errors,best=chat_page
    page.goto('https://agentconcierge.biz/#chat')
    page.evaluate('''id=>appendChatBubble('concierge','',{data:{task:'Weather <img src=x onerror="window.__reviewXss=1">',recommendations:[{id,kind:'mcp',name:'Weather',tools:['forecast']}]}})''',best)
    page.locator('.chat-review-task').first.click()
    panel=page.locator('#chatTaskReview')
    playwright.expect(panel).to_contain_text('<img')
    assert panel.locator('img,[onerror]').count()==0
    assert panel.get_attribute('data-clarity-mask')=='true'
    assert page.evaluate('window.__reviewXss||0')==0
    assert not errors


def test_mobile_handoff_and_replacement_do_not_keep_a_stale_ready_notice(chat_page,catalog,request):
    published(request)
    page,_,_,errors,_=chat_page
    _,_,_,add,now=catalog
    other=add('Alternate Forecast',kind='a2a',report_at=now-30)
    page.set_viewport_size({'width':390,'height':844})
    page.goto('https://agentconcierge.biz/#chat')
    page.locator('#chatInput').fill('MCP weather forecast for Seoul');page.locator('#chatSubmit').click()
    page.locator('.chat-review-task').first.click()
    playwright.expect(page.locator('#chatTaskReview')).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    page.screenshot(path='/Users/kingstonelee/workspace/A2A_Discovery/reports/frontend-retention-quality-2026-10-25/mobile-task-review.png',full_page=True)
    page.evaluate('id=>onTestbenchAgentChange(id)',other)
    playwright.expect(page.locator('#chatTaskReview')).to_have_count(0)
    assert not errors
