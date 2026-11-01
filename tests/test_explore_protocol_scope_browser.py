"""Explore states the applied protocol scope without changing search policy."""
import pytest
from playwright.sync_api import expect

from tests.test_explore_report_filter_browser import explore_page  # noqa: F401
from tests.test_fast_single_recommendation import catalog  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401


@pytest.mark.parametrize('legacy',[False,True],ids=['published','embedded'])
def test_applied_scope_is_visible_for_default_selection_query_and_empty_results(explore_page,monkeypatch,legacy):
    if legacy:
        from agent_market.concierge import pearl_view
        monkeypatch.setattr(pearl_view,'public_page_available',lambda:False)
    state=explore_page;page=state.page
    page.goto('https://agentconcierge.biz/#explore')
    expect(page.locator('#xProtocolScope')).to_have_text('A2A + MCP')
    expect(page.locator('#xProtocolHelp')).to_contain_text('x402 is included only when explicitly requested')
    expect(page.locator('#xTitle')).to_contain_text('A2A + MCP')
    assert page.locator('#xKind').get_attribute('aria-describedby')=='xProtocolHelp'
    expect(page.locator('#xKind option').first).to_have_text('A2A + MCP (default)')
    for kind,label in (('mcp','MCP'),('a2a','A2A'),('x402','x402')):
        with page.expect_response('**/api/explore?*'):page.locator('#xKind').select_option(kind)
        expect(page.locator('#xProtocolScope')).to_have_text(label)
        expect(page.locator('#xProtocolHelp')).to_have_text('Only '+label+' agents. Counts reflect this protocol and your filters.')
        expect(page.locator('#xTitle')).to_contain_text(label)
        assert state.calls[-1]['params']['kind']==kind
    with page.expect_response('**/api/explore?*'):page.locator('#xKind').select_option('')
    expect(page.locator('#xProtocolScope')).to_have_text('A2A + MCP')
    for query,label in (('MCP weather forecast','MCP'),('x402 weather forecast','x402')):
        with page.expect_response('**/api/explore?*'):page.locator('#xQ').fill(query)
        expect(page.locator('#xProtocolScope')).to_have_text(label)
    # A selector takes precedence over a protocol mentioned in the question.
    with page.expect_response('**/api/explore?*'):page.locator('#xKind').select_option('a2a')
    expect(page.locator('#xProtocolScope')).to_have_text('A2A')
    with page.expect_response('**/api/explore?*'):page.locator('#xQ').fill('weather <img src=x onerror="window.scopeXss=1">')
    assert page.locator('#xTitle img, .explore-scope img').count()==0
    assert page.evaluate('window.scopeXss||0')==0
    assert not state.errors and not state.blocked
    if not legacy:
        page.set_viewport_size({'width':375,'height':812})
        box=page.locator('.explore-scope').bounding_box()
        assert box and box['x']>=0 and box['x']+box['width']<=376


def test_protocol_label_follows_the_existing_explicit_request_rules(explore_page):
    state=explore_page;page=state.page
    page.goto('https://agentconcierge.biz/#explore')
    values=page.evaluate('''()=>[
        'weather forecast','MCP weather','A2A weather','x402 weather',
        'weather, not x402','MCP weather, without x402','non-x402 weather'
    ].map(query=>exploreProtocolSelection(query))''')
    assert values==['','mcp','a2a','x402','','mcp','']
    assert not state.errors and not state.blocked


@pytest.mark.parametrize('legacy',[False,True],ids=['published','embedded'])
def test_explore_keeps_focused_mcp_ahead_of_incidental_a2a(explore_page,monkeypatch,legacy):
    if legacy:
        from agent_market.concierge import pearl_view
        monkeypatch.setattr(pearl_view,'public_page_available',lambda:False)
    state=explore_page;page=state.page
    page.set_viewport_size({'width':1366,'height':1000})
    page.emulate_media(reduced_motion='reduce')
    focused=state.add('GitHub Issues and Pull Requests',kind='mcp',description='Search public GitHub issues by keywords.')
    bundle=state.add('Intelligence Mesh',kind='a2a',description='A large product catalog with many capabilities.')
    page.goto('https://agentconcierge.biz/#explore')
    reject=page.get_by_role('button',name='Reject Non-Essential',exact=True)
    if reject.is_visible():reject.click()
    expect(page.locator('#xGo')).to_be_enabled()
    # Render an authoritative mixed-protocol server order. UI must not overwrite it.
    rows=[dict(state.store.resource(rid)) for rid in (focused,bundle)]
    page.evaluate("rows=>{document.getElementById('xKind').value='';renderExplore(rows,'Search GitHub issues',2)}",rows)
    actual=page.locator('#xResults .acard[data-id]').evaluate_all('cards=>cards.map(card=>Number(card.dataset.id))')
    assert actual==[focused,bundle]
    page.screenshot(path='reports/feature-remediation-2026-10-29/search-render-preview-'+('embedded' if legacy else 'published')+'.png',full_page=False)
    expect(page.locator('#xProtocolHelp')).to_contain_text('Task-focused results first')
    page.locator('input#xQ').fill('Search GitHub issues')
    assert not state.errors and not state.blocked
