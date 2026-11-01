"""Explain current results without running providers or granting authority."""
from playwright.sync_api import expect
from tests.test_pearl_frontend import client,pearl_page  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401


def test_visible_protocol_and_catalog_scope_match_results(pearl_page):
    page,errors,calls=pearl_page
    page.goto('https://agentconcierge.biz/#explore')
    expect(page.get_by_role('group',name='Search protocol').get_by_role('button',name='A2A + MCP',exact=True)).to_have_attribute('aria-pressed','true')
    expect(page.locator('#xProtocolScope')).to_have_text('A2A + MCP')
    expect(page.locator('#xProtocolHelp')).to_be_hidden()
    assert page.locator('.explore-scope').bounding_box()['height']<=40
    page.locator('a.brand').click()
    expect(page.locator('#uxCatalogScope')).not_to_be_visible()
    assert page.locator('#uxCatalogHelp').bounding_box()['height']<=36
    page.locator('#uxCatalogHelp > summary').click()
    expect(page.locator('#uxCatalogScope')).to_be_visible()
    expect(page.locator('#uxCatalogScope')).to_contain_text('including unavailable entries')
    expect(page.locator('#uxCatalogScope')).to_contain_text('Explore defaults to reachable A2A and MCP')
    assert not errors


def test_refresh_preserves_dated_snapshot_capture_time(pearl_page):
    page,errors,calls=pearl_page
    page.goto('https://agentconcierge.biz/#status')
    expect(page.locator('#snapshot-feedback')).to_contain_text('distinct scopes')
    page.evaluate('''()=>{const stamp=document.querySelector('#daily-catalog-statistics time');stamp.setAttribute('datetime','2001-01-01T00:00:00Z');stamp.textContent='Original daily capture'}''')
    with page.expect_response('**/api/pearl/status'):page.get_by_role('button',name='Refresh data',exact=True).click()
    expect(page.locator('#daily-catalog-statistics time')).to_have_attribute('datetime','2001-01-01T00:00:00Z')
    expect(page.locator('#daily-catalog-statistics time')).to_have_text('Original daily capture')
    expect(page.locator('#uxConnectionMeaning')).to_contain_text('retired or unclassified')
    assert not errors


def test_recommendations_explain_rank_check_and_report(pearl_page):
    page,errors,calls=pearl_page
    page.goto('https://agentconcierge.biz/#chat')
    expect(page.locator('#chatForm button[type="submit"]')).to_contain_text('Find matches')
    page.evaluate('''()=>appendChatBubble('bot','',{data:{recommendations:[{
        id:7,name:'Weather reference',kind:'mcp',grade:'A',quality_score:85,
        capability_contract:{verified_within_24h:true,verified_at:1792900000},active_checked_at:1792900010
    }]}})''')
    result=page.locator('.chat-bubble').first
    expect(result.locator('.chat-result-basis .context-help-body')).not_to_be_visible()
    result.locator('.chat-result-basis > summary').focus()
    page.keyboard.press('Enter')
    expect(result.locator('.chat-result-basis .context-help-body')).to_be_visible()
    expect(result).to_contain_text('recent successful checks come first')
    expect(result).to_contain_text('Connection execution check:')
    # Evidence that was not recorded is omitted, not labeled with internal wording.
    expect(result).not_to_contain_text('Selected tool check:')
    expect(result).not_to_contain_text('No published report')
    expect(result).to_contain_text('UTC')
    assert not errors and not any(path.startswith('/api/gateway/')for _,path in calls)


def test_loading_does_not_claim_an_empty_template_hub(pearl_page,client):
    page,errors,calls=pearl_page;held=[]
    page.route('**/api/workflows/templates',lambda route:held.append(route))
    page.goto('https://agentconcierge.biz/#workflows')
    expect(page.locator('#pearlWorkflowChoiceState')).to_contain_text('Loading available workflows')
    expect(page.locator('#btnFrontRunWorkflow')).to_be_disabled()
    expect(page.locator('#btnFrontExportApp')).to_be_disabled()
    response=client.get('/api/workflows/templates');assert held
    held.pop().fulfill(status=response.status_code,body=response.content,content_type='application/json')
    page.wait_for_function('frontTemplatesLoaded===true')
    if response.json()['templates']:
        expect(page.locator('#btnFrontExportApp')).to_be_enabled()
        expect(page.locator('#frontWfNodeCountChip')).to_contain_text('workflow steps')
        expect(page.locator('#frontSelectionBasis')).to_contain_text('selected')
    else:expect(page.locator('#pearlWorkflowChoiceState')).to_contain_text('No published workflows')
    assert not errors
