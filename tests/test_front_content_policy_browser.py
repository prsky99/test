"""Verify public copy, current metadata, and minimal Chat details in a browser."""
import re

import pytest

from agent_market.concierge.public_metadata import PAGES
from tests.test_fast_single_recommendation import catalog  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401
from tests.test_single_agent_chat_browser import chat_page  # noqa: F401

playwright = pytest.importorskip('playwright.sync_api')
COMMERCIAL = re.compile(r'\b(?:free|paid|pay|payments?|billing|pricing|prices?|fees?|costs?|charges?|subscriptions?|wallets?|USDC)\b', re.I)


def test_home_and_chat_metadata_describe_current_selection(chat_page, request):
    page, _, _, errors, _ = chat_page
    published = request.node.callspec.params['chat_page'] == 'published'
    page.goto('https://agentconcierge.biz/#overview')
    playwright.expect(page.locator('#secOverview h1').first).to_be_visible()
    playwright.expect(page).to_have_title(PAGES['overview'][1])
    description = page.locator('head meta[name="description"]').get_attribute('content')
    assert 'A2A first' in description and 'then MCP' in description and 'explicit choice' in description
    daily = page.locator('#dailyHomeMetadata')
    if daily.count():
        import json
        assert description == json.loads(daily.inner_text())['description']
        assert 'Daily snapshot:' in description
        playwright.expect(page.locator('#daily-catalog-statistics')).to_be_visible()
    else:
        assert description == PAGES['overview'][2]
    assert page.locator('head meta[property="og:description"]').get_attribute('content') == description
    assert page.locator('head meta[name="twitter:description"]').get_attribute('content') == description
    playwright.expect(page.locator('#navTabs .nav-tab')).to_have_text(
        (['Agent Status'] if published else [])+['Learn','Explore','Test','Workflows','Chat','List Your Agent','About'])
    listing_menu = page.locator('.nav-tab[data-tab="register"]')
    playwright.expect(listing_menu).to_have_text('List Your Agent')
    listing_menu.click()
    playwright.expect(page).to_have_title(PAGES['register'][1])
    if published:
        playwright.expect(page.locator('#secRegister h1')).to_contain_text('Give your agent a place')
    else:
        playwright.expect(page.locator('#secRegister h2').first).to_have_text('List Your Agent')
    listing_description = page.locator('head meta[name="description"]').get_attribute('content')
    assert 'so others can discover it' in listing_description
    assert page.locator('head meta[property="og:description"]').get_attribute('content') == listing_description
    assert page.locator('head meta[name="twitter:description"]').get_attribute('content') == listing_description
    assert page.locator('head meta[name="agent:action"]').get_attribute('content') == 'list-agent-endpoint'
    assert page.locator('#secOverview meta[name="agent:action"]').get_attribute('content') == 'find-up-to-three-verified-agents'
    home=page.locator('a.brand-box[href]')
    assert home.get_attribute('href')==('https://agentconcierge.biz/' if published else '#overview')
    home.click()
    assert page.locator('head meta[name="description"]').get_attribute('content') == description
    assert 'Global Protocol Runtime:' not in page.locator('footer').last.inner_text()
    page.locator('.nav-tab[data-tab="chat"]').click()
    playwright.expect(page.locator('#secChat')).to_be_visible()
    playwright.expect(page).to_have_title(PAGES['chat'][1])
    assert page.locator('head meta[name="description"]').get_attribute('content') == PAGES['chat'][2]
    assert not COMMERCIAL.search(page.locator('#secChat').inner_text())
    assert page.locator('#chatVisitorTokenDisplay, #chatOutput, #chatCallingSpecCode').count() == 0
    assert not errors


def test_chat_hides_commercial_and_private_fields_in_card_and_details(chat_page):
    page, requests, _, errors, _ = chat_page
    page.goto('https://agentconcierge.biz/#chat')
    page.evaluate('''() => appendChatBubble('bot', 'Private backend response', {data:{recommendations:[{
        name:'Free Premium Weather',kind:'x402',url:'https://weather.example/api',
        description:'Pay a fee for a subscription',price_usdc:9000000,pay_to:'private-wallet-address',
        auth_required:true,auth_method:'x402_payment',source:'internal-database',
        grade:'A',quality_score:95,active_checked_at:1700000000,
        tools:['forecast'],tools_schema:[{name:'forecast',inputSchema:{properties:{city:{type:'string'}}}}],
        test_report:{id:1,success:true,created_at:1700000000}}]}})''')
    card = page.locator('.chat-recommendation')
    playwright.expect(card).to_have_count(1)
    # Billing words are removed from the name; the service name itself stays visible.
    playwright.expect(card.locator('.chat-result-name')).to_have_text('Weather')
    playwright.expect(card).to_contain_text('Connection unavailable')
    assert 'https://weather.example/api' not in card.inner_text()
    assert not COMMERCIAL.search(card.inner_text())
    card.first.get_by_role('button', name='Calling details').click()
    details = page.locator('#drawerContent')
    playwright.expect(details).to_be_visible()
    playwright.expect(details).to_contain_text('Connection unavailable')
    assert 'https://weather.example/api' not in details.inner_text()
    playwright.expect(details).to_contain_text('city')
    assert not COMMERCIAL.search(details.inner_text())
    assert 'private-wallet-address' not in details.inner_text()
    assert 'internal-database' not in details.inner_text()
    assert not any(path.startswith('/api/agents/') for _, path in requests)
    page.locator('#closeDrawer').click()
    playwright.expect(page.locator('#drawer')).to_be_hidden()
    assert not errors


def test_chat_does_not_echo_private_input_or_backend_diagnostics(chat_page):
    page, _, bodies, errors, _ = chat_page
    page.goto('https://agentconcierge.biz/#chat')
    private_input = '\uc11c\uc6b8 weather forecast for audit-person@example.test'
    page.locator('#chatInput').fill(private_input)
    page.locator('#chatSubmit').click()
    playwright.expect(page.locator('#chatStatus')).to_have_text('Ready')
    playwright.expect(page.locator('#chatMessages .chat-bubble')).to_have_count(2)
    assert bodies
    chat = page.locator('#chatMessages').inner_text()
    assert 'audit-person@example.test' not in chat
    playwright.expect(page.locator('.chat-request')).to_contain_text('\uc11c\uc6b8')
    page.evaluate('''() => appendChatBubble('bot', 'DEBUG /private/system/config audit-person@example.test payment', {})''')
    chat = page.locator('#chatMessages').inner_text()
    assert 'DEBUG' not in chat and '/private/system/config' not in chat
    assert not COMMERCIAL.search(chat)
    assert not errors


@pytest.mark.parametrize('width,scheme', [(1280, 'dark'), (390, 'light'), (390, 'dark')])
def test_chat_responsive_keyboard_navigation_and_icons(chat_page, width, scheme, request):
    page, _, _, errors, _ = chat_page
    page.set_viewport_size({'width': width, 'height': 900})
    page.emulate_media(color_scheme=scheme, reduced_motion='reduce')
    page.goto('https://agentconcierge.biz/#chat')
    published = request.node.callspec.params['chat_page'] == 'published'
    if published:
        playwright.expect(page.locator('#chatSubmit .chat-submit-icon svg.lucide')).to_be_visible()
        page.locator('.pearl-chat-protocol [data-value="mcp"]').focus()
        page.keyboard.press('Enter')
        playwright.expect(page.locator('#chatProtocol')).to_have_value('mcp')
    else:
        assert page.locator('#secChat svg.lucide').count() >= 8
    assert page.locator('#secChat svg:not([aria-hidden="true"])').count() == 0
    page.locator('#chatInput').focus()
    page.keyboard.type('MCP weather forecast')
    page.keyboard.press('Tab')
    if not published:
        playwright.expect(page.locator('#chatProtocol')).to_be_focused()
        page.keyboard.press('Tab')
    playwright.expect(page.locator('#chatSubmit')).to_be_focused()
    assert page.locator('#chatSubmit').bounding_box()['height'] >= 44
    page.keyboard.press('Enter')
    card = page.locator('.chat-recommendation')
    playwright.expect(card).to_have_count(3)
    playwright.expect(page.locator('.chat-welcome')).to_be_hidden()
    assert card.locator('svg.lucide').count() >= 6
    assert page.locator('#secChat').evaluate('el => el.scrollWidth <= el.clientWidth + 1')
    if published:
        assert page.locator('.pearl-chat-protocol button').evaluate_all('buttons=>buttons.every(b=>{const r=document.createRange();r.selectNodeContents(b);return r.getBoundingClientRect().right<=b.getBoundingClientRect().right+1})')
    playwright.expect(card.first.get_by_role('button', name='Calling details')).to_be_visible()
    if width <= 640:
        assert page.evaluate('''() => {
          const a = document.querySelector('.chat-rec-btn').getBoundingClientRect();
          const b = document.getElementById('scrollTopBtn').getBoundingClientRect();
          return a.right <= b.left || a.left >= b.right || a.bottom <= b.top || a.top >= b.bottom;
        }''')
    card.first.get_by_role('button', name='Calling details').click()
    playwright.expect(page.locator('#drawerContent')).to_contain_text('Verified Weather A')
    assert not errors


def test_chat_request_busy_state_recovers_after_failure(chat_page):
    page, _, _, errors, _ = chat_page
    pending = []
    page.route('**/chat', lambda route: pending.append(route))
    page.goto('https://agentconcierge.biz/#chat')
    page.locator('#chatInput').fill('MCP weather forecast')
    page.locator('#chatSubmit').click()
    playwright.expect(page.locator('#chatSubmit')).to_be_disabled()
    playwright.expect(page.locator('#chatForm')).to_have_attribute('aria-busy', 'true')
    playwright.expect(page.locator('.chat-loading-icon')).to_be_visible()
    assert pending
    pending[0].fulfill(status=503, content_type='application/json', body='{"error":"Private diagnostic"}')
    playwright.expect(page.locator('#chatSubmit')).to_be_enabled()
    playwright.expect(page.locator('#chatForm')).to_have_attribute('aria-busy', 'false')
    playwright.expect(page.locator('.chat-loading-icon')).to_be_hidden()
    playwright.expect(page.locator('#chatStatus')).to_have_text('The request could not be completed. Your question is kept; try again when ready.')
    playwright.expect(page.locator('#chatInput')).to_have_value('MCP weather forecast')
    assert 'Private diagnostic' not in page.locator('#secChat').inner_text()
    assert not errors
