"""User's two stock/news queries under real Chromium/CSP with newest replies first."""
from pathlib import Path

import pytest
from tests.test_single_agent_chat_browser import chat_page, browser, catalog  # noqa: F401
from tests.test_recent_a2a_chat import stock_catalog

playwright=pytest.importorskip('playwright.sync_api')


@pytest.mark.parametrize('width',[390,1280])
def test_stock_news_protocol_and_newest_reply_first(chat_page,catalog,width):
    page,requests,bodies,errors,_=chat_page;ids=stock_catalog(catalog)
    page.set_viewport_size({'width':width,'height':900})
    page.goto('https://agentconcierge.biz/#chat')
    consent = page.get_by_role('button',name='Reject Non-Essential',exact=True)
    if consent.is_visible():consent.click()
    # Rejecting non-essential cookies no longer opens a follow-up dialog.
    playwright.expect(page.locator('#appLayerModal')).not_to_be_visible()
    assert page.locator('#chatProtocol').input_value()=='auto'
    playwright.expect(page.locator('#chatProtocol option[value="auto"]')).to_contain_text('A2A')
    page.locator('#chatInput').fill('stock news');page.locator('#chatSubmit').click()
    cards=page.locator('.chat-recommendation:visible')
    playwright.expect(cards).to_have_count(1)
    playwright.expect(cards.first).to_contain_text('Recent A2A Stock News')
    assert bodies[-1]['data']['recommendations'][0]['id']==ids['a2a']
    page.locator('#chatInput').fill('mcp stock news');page.locator('#chatSubmit').click()
    playwright.expect(cards).to_have_count(2)
    playwright.expect(cards.first).to_contain_text('Recent MCP Stock News')
    playwright.expect(cards.nth(1)).to_contain_text('Recent A2A Stock News')
    assert bodies[-1]['data']['recommendations'][0]['id']==ids['mcp']
    assert page.locator('#chatMessages').evaluate('(el)=>el.scrollTop')==0
    assert page.locator('#secChat').evaluate('(el)=>el.scrollWidth<=el.clientWidth+1')
    assert page.locator('#chatMessages img,[onerror]').count()==0 and not errors
    assert 'Older' not in page.locator('#chatMessages').inner_text()
    report=Path('reports/security-2026-10-17-a2a-recency');report.mkdir(parents=True,exist_ok=True)
    cards.first.scroll_into_view_if_needed()
    page.screenshot(path=str(report/f'stock-news-{width}.png'))
