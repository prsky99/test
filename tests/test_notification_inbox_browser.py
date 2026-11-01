"""Public Chat registration through real HTTPS webhook/A2A receivers."""
from pathlib import Path
import time
from urllib.parse import urlsplit

import pytest

from tests.test_front_workflow_browser import browser  # noqa: F401
from tests.test_notification_inbox_integration import network, catalog, receipts, ORIGIN, CASES  # noqa: F401

playwright = pytest.importorskip('playwright.sync_api')


@pytest.mark.parametrize('channel,path',CASES[:3])
def test_chat_enrolls_and_confirms_real_https_inbox(browser,catalog,network,channel,path):
    store,front,client,add,now = catalog
    add('Initial Browser Weather',report_at=now-10)
    front.updates.courier = network[3]
    context = browser.new_context(viewport={'width':1280,'height':950})
    def serve(route):
        request = route.request
        url = urlsplit(request.url)
        if url.hostname!='agentconcierge.biz':
            route.abort();return
        response = client.request(request.method,url.path+('?' + url.query if url.query else ''),content=request.post_data,headers=request.headers)
        route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items() if k not in ('content-length','content-encoding','transfer-encoding')})
    context.route('**/*',serve)
    page = context.new_page();errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    try:
        page.goto('https://agentconcierge.biz/#chat')
        page.get_by_role('button',name='Reject Non-Essential',exact=True).click()
        playwright.expect(page.locator('#appLayerModal')).not_to_be_visible()
        page.locator('#chatInput').fill('MCP weather forecast');page.locator('#chatSubmit').click()
        page.get_by_role('button',name='Get updates for this task').click()
        page.locator('#taskUpdateChannel').select_option(channel)
        page.locator('#taskUpdateUrl').fill(ORIGIN+path)
        page.locator('#taskUpdateAuthority').check();page.locator('#taskUpdateConsent').check()
        page.locator('#taskUpdateMarketing').check()
        page.locator('#taskUpdateSubmit').click()
        playwright.expect(page.locator('#taskUpdateReviewDestination')).to_have_text(ORIGIN+path)
        assert not receipts(network)['challenges']
        page.locator('#taskUpdateConfirmDestination').click()
        playwright.expect(page.locator('#taskUpdateVerify')).to_be_visible()
        received = receipts(network)
        assert len(received['challenges'])==1 and not received['events']
        page.locator('#taskUpdateCode').fill(received['challenges'][0]['verification_code'])
        page.locator('#taskUpdateVerifyButton').click()
        playwright.expect(page.locator('#taskUpdateStatus')).to_have_text('Task updates are on.')
        newest = add('Newest Browser TLS Weather',report_at=time.time())
        vid = store.query('SELECT visitor_id FROM agent_task_watches')[0]['visitor_id']
        assert front.updates.run_due(vid)['sent']==1
        assert receipts(network)['events'][0]['recommendation_id']==newest
        page.locator('#taskUpdateManage').click()
        playwright.expect(page.locator('#taskPreferences')).to_contain_text('Separate permission recorded')
        page.get_by_role('button',name='Check for updates',exact=True).click()
        playwright.expect(page.locator('#chatMessages .chat-recommendation').first).to_contain_text('Newest Browser TLS Weather')
        assert ORIGIN not in page.locator('#secChat').inner_text() and not errors
        report = Path('reports/security-2026-10-17-notification-inboxes');report.mkdir(parents=True,exist_ok=True)
        suffix = 'webhook' if channel=='webhook' else 'a2a-v1' if 'v1' in path else 'a2a-v03'
        page.screenshot(path=str(report/(suffix+'-chat-confirmed.png')))
    finally:
        context.close()
