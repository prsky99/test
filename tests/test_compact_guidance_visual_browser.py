"""Compact public guidance stays optional and fits narrow and wide layouts."""
from pathlib import Path

import pytest
from playwright.sync_api import expect

from tests.test_pearl_frontend import client,pearl_page  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401


@pytest.mark.parametrize('width',[390,1440])
def test_guidance_views_keep_secondary_explanations_collapsed(pearl_page,width):
    page,errors,calls=pearl_page
    page.set_viewport_size({'width':width,'height':950})
    folder=Path('reports/frontend-guidance-design-2026-10-26');folder.mkdir(exist_ok=True,parents=True)
    for panel,help_selector in [('overview','#uxCatalogHelp'),('explore','#exploreScopeDetails'),('workflows','#frontSelectionContext details'),('status','#connection-status .context-help'),('chat',None)]:
        page.goto('https://agentconcierge.biz/#'+panel)
        if panel=='chat':
            page.evaluate("()=>appendChatBubble('bot','',{data:{recommendations:[{id:7,name:'Research reference',kind:'mcp',grade:'A',quality_score:90}]}})")
            help_selector='.chat-result-basis'
        help=page.locator(help_selector)
        expect(help.locator(':scope > summary')).to_be_visible()
        assert not help.evaluate('(n)=>n.open')
        assert help.bounding_box()['height']<=44  # one line; 44px is the touch-target floor since 11-11
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.screenshot(path=str(folder/f'public-{panel}-{width}.png'),full_page=True)
    assert not errors
    assert not any(path.startswith('/api/gateway/')for _,path in calls)
