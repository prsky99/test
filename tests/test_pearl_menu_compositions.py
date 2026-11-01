"""Check the approved menu layouts against operating state and security boundaries."""
import json

import pytest
from playwright.sync_api import expect

from tests.test_pearl_frontend import ORIGIN, browser, client, pearl_page


@pytest.mark.parametrize('width', [1440, 768, 390])
def test_menu_typography_geometry_and_drafts(pearl_page, width):
    page, errors, calls = pearl_page
    page.set_viewport_size({'width': width, 'height': 1000})
    for panel in ['explore', 'test', 'workflows', 'chat', 'register']:
        page.goto(ORIGIN+'/#'+panel)
        section = page.locator('[data-panel="'+panel+'"]')
        expect(section).to_be_visible()
        style = section.locator('h1').first.evaluate('(n)=>{const s=getComputedStyle(n);return {font:s.fontFamily,size:parseFloat(s.fontSize),color:s.color,weight:s.fontWeight}}')
        assert 'Georgia' in style['font'] and style['size'] >= 30
        assert style['color'] == 'rgb(6, 47, 64)'
        assert style['weight'] == '500'
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+2')
    page.locator('#regName').fill('Keep this draft')
    page.locator('#regDesc').fill('A public documentation assistant.')
    if width <= 950:
        page.locator('[data-pearl-action="menu"]').click()
    page.locator('#navTabs [data-tab="chat"]').click()
    page.locator('#chatInput').fill('Keep this task')
    page.locator('.pearl-chat-protocol [data-value="mcp"]').click()
    expect(page.locator('#chatProtocol')).to_have_value('mcp')
    if width <= 950:
        page.locator('[data-pearl-action="menu"]').click()
    page.locator('#navTabs [data-tab="register"]').click()
    expect(page.locator('#regName')).to_have_value('Keep this draft')
    expect(page.locator('#regDesc')).to_have_value('A public documentation assistant.')
    assert not [(m,p) for m,p in calls if m == 'POST']
    assert not errors


def test_chat_protocol_submission_and_sidebar_safe_text(pearl_page):
    page, errors, calls = pearl_page
    requests = []

    def reply(route):
        requests.append(json.loads(route.request.post_data))
        route.fulfill(json={'reply': 'Selected.', 'data': {'recommendations': [{
            'id': 2, 'kind': 'mcp', 'name': '<img src=x onerror=window.bad=1>',
            'description': 'wallet private-token data must not be displayed',
            'grade': 'A', 'active_checked_at': 1,
            'test_report': {'id': 1, 'created_at': 1, 'success': True},
        }]}})

    page.route('**/chat', reply)
    page.goto(ORIGIN+'/#chat')
    expect(page.locator('.pearl-chat-protocol')).to_be_visible()
    page.locator('.pearl-chat-protocol [data-value="mcp"]').click()
    page.locator('#chatInput').fill('Find a public documentation agent.')
    page.locator('#chatSubmit').click()
    expect(page.locator('#pearlChatSelectedAgent h4')).to_have_text('<img src=x onerror=window.bad=1>')
    assert requests[0]['data']['protocol'] == 'mcp'
    assert page.locator('#pearlChatSelectedAgent img').count() == 0
    assert not page.evaluate('window.bad || false')
    # Provider text appears only in its labelled block, as plain text; never in the selected-agent
    # sidebar, which shows Concierge's own fields.
    source = page.locator('#secChat .chat-provider-description')
    expect(source.locator('span')).to_have_text('Provider description')
    # chatLabel() drops billing and wallet wording from provider text before showing it.
    assert source.locator('p').inner_text() == 'private-token data must not be displayed'
    assert source.locator('p *').count() == 0
    outside = page.evaluate('''()=>{const copy=document.querySelector('#secChat').cloneNode(true);
      copy.querySelectorAll('.chat-provider-description').forEach(n=>n.remove());return copy.innerText.toLowerCase()}''')
    assert 'wallet' not in outside and 'private-token' not in outside
    sidebar = page.locator('#pearlChatSelectedAgent').inner_text().lower()
    assert 'wallet' not in sidebar and 'private-token' not in sidebar
    page.locator('#chatMessages .chat-rec-btn').click()
    expect(page.locator('#drawer')).to_be_visible()
    assert 'wallet' not in page.locator('#drawer').inner_text().lower()
    assert not errors


def test_registration_authority_and_consent_precede_any_write(pearl_page):
    page, errors, calls = pearl_page
    page.goto(ORIGIN+'/#register')
    page.locator('#regSubmitBtn').click()
    expect(page.get_by_text('Authorization required', exact=True)).to_be_visible()
    page.keyboard.press('Escape')
    page.locator('#pearlRegAuthority').check()
    page.locator('#regSubmitBtn').click()
    expect(page.get_by_text('Affirmative Consent Required', exact=True)).to_be_visible()
    page.keyboard.press('Escape')
    page.locator('#regKind + .pearl-protocol-segmented [data-value="x402"]').click()
    expect(page.locator('#regKind')).to_have_value('x402')
    expect(page.locator('#regX402Fields')).to_be_visible()
    page.locator('#regKind + .pearl-protocol-segmented [data-value="a2a"]').click()
    expect(page.locator('#regX402Fields')).not_to_be_visible()
    page.locator('#regResetBtn').click()
    expect(page.locator('#pearlRegAuthority')).not_to_be_checked()
    assert not [(m,p) for m,p in calls if m == 'POST']
    assert not errors


def test_selected_example_and_request_survive_navigation(pearl_page):
    page, errors, calls = pearl_page
    page.route('**/api/test/presets', lambda route: route.fulfill(json={'presets': [], 'live_examples': [{
        'id': 'news-example', 'title': 'Technology news', 'desc': 'Read public news sources.',
        'protocol': 'mcp', 'available': True, 'resource_id': 2, 'args': {'topic': 'technology'}, 'tool': 'search',
    }]}))
    page.goto(ORIGIN+'/#test')
    expect(page.locator('#pearlTestExampleName')).to_have_text('Technology news')
    expect(page.locator('.pearl-example-choice.active')).to_have_text('Technology newsRead public news sources.MCP · Sample request')
    page.locator('#uxRawArgs>summary').click()
    page.locator('#tbArgsEditor').fill('{"topic":"Retain this request"}')
    page.locator('#uxToggleTestResult').click()
    page.locator('#secTest [data-subtab="raw"]').click()
    expect(page.locator('#tbInspectorRaw')).to_be_visible()
    page.locator('#navTabs [data-tab="chat"]').click()
    page.locator('#navTabs [data-tab="test"]').click()
    expect(page.locator('#tbArgsEditor')).to_have_value('{"topic":"Retain this request"}')
    expect(page.locator('#tbInspectorRaw')).to_be_visible()
    assert not [(m,p) for m,p in calls if m == 'POST']
    assert not errors


def test_workflow_published_input_and_run_output_are_safe(pearl_page,client):
    page, errors, calls = pearl_page
    from tests.test_pearl_frontend import mock_selectable_templates
    mock_selectable_templates(page,client)
    page.goto(ORIGIN+'/#workflows')
    expect(page.locator('#pearlWorkflowSearch')).to_be_visible()
    page.locator('#btnFrontWfViewTemplates').click()
    page.locator('#frontTemplatesGrid .template-card').first.get_by_role('button',name='Use workflow',exact=True).click()
    expect(page.locator('#pearlWorkflowInputSteps button').first).to_be_visible()
    page.locator('#pearlWorkflowInputSteps button').first.click()
    expect(page.locator('#pearlWorkflowInputDialog')).to_be_visible()
    assert page.locator('#pearlWorkflowInputDialog textarea').count() == 0
    page.locator('#pearlCloseWorkflowInput').click()
    page.evaluate('showFrontRunOutputModal({status:"failed",results:[{name:"Read sources",status:"failed",output:"<img src=x onerror=window.bad=1>"}]})')
    expect(page.locator('#pearlWorkflowResult')).to_contain_text('<img src=x onerror=window.bad=1>')
    expect(page.locator('#pearlWorkflowResultState')).to_have_text('Last run: failed')
    assert page.locator('#pearlWorkflowResult img').count() == 0
    assert not page.evaluate('window.bad || false')
    assert not [(m,p) for m,p in calls if m == 'POST']
    assert not errors
