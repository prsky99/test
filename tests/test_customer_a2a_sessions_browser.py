"""Private customer A2A context and resume journeys in offline Chromium."""
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from agent_market.customer_identity_service import COOKIE
from tests.test_customer_a2a_sessions import customer_session
from tests.test_customer_typed_authoring import customer_flow
from tests.test_workspace_typed_release import typed_release_world
from tests.test_workspace_typed_flows import typed_world,routing
from tests.test_workspace_a2a_sessions import stream_provider
from tests.test_front_workflow_browser import browser


@pytest.mark.parametrize('resume',[False,True])
def test_customer_can_continue_or_resume_long_task_with_fresh_authority(customer_session,browser,resume):
    x=customer_session
    if resume:stream_provider(x.remote,disconnect=True)
    context=browser.new_context();context.set_offline(True)
    context.add_cookies([{'name':COOKIE,'value':x.s.raw,'url':'https://customer.test','secure':True,'httpOnly':True,'sameSite':'Lax'}])
    page=context.new_page();errors=[];external=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    def handler(route):
        request=route.request;url=urlsplit(request.url)
        if url.hostname!='customer.test':external.append(request.url);route.abort();return
        response=x.client.request(request.method,url.path,headers=request.headers,content=request.post_data,follow_redirects=False)
        if response.status_code>=400:errors.append(str(response.status_code)+':'+url.path)
        route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items()
            if k not in ('content-length','content-encoding','set-cookie','transfer-encoding')})
    context.route('**/*',handler)
    try:
        page.goto('https://customer.test/customer/organizations/'+x.ws+'/flows')
        expect(page.locator('#status')).to_have_text('Review a workflow or inspect retained tests.')
        page.locator('#human-nav-library').click()
        page.locator('#a2a-panel > summary').click()
        page.locator('#a2a-binding').select_option('0');page.locator('#a2a-text').fill('Public source task')
        expect(page.locator('#a2a-send')).to_be_disabled()
        page.locator('#a2a-send-consent').check();page.locator('#a2a-send').click()
        expect(page.locator('#a2a-status')).to_contain_text('unknown' if resume else 'input-required')
        if resume:
            page.locator('#a2a-action').select_option('resume')
            expect(page.locator('#a2a-command')).to_be_disabled()
            page.locator('#a2a-command-consent').check();page.locator('#a2a-command').click()
        else:
            page.locator('#a2a-text').fill('Reviewed follow-up')
            expect(page.locator('#a2a-turn')).to_be_disabled()
            page.locator('#a2a-turn-consent').check();page.locator('#a2a-turn').click()
        expect(page.locator('#a2a-status')).to_contain_text('completed')
        assert len(x.remote.calls)==2 and not errors and not external
        assert x.remote.calls[-1]['method']==('tasks/resubscribe' if resume else 'message/stream')
        page.locator('#a2a-read').click()
        expect(page.locator('#a2a-output')).to_contain_text('Retained evidence')
        assert len(x.remote.calls)==2
    finally:context.close()
