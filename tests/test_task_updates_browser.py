"""Real Chromium interaction tests with isolated ASGI apps and enforced CSP."""
import json
import re
from urllib.parse import urlsplit

import pytest
from tests.test_single_agent_chat_browser import chat_page  # noqa: F401
from tests.test_fast_single_recommendation import catalog  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401
from tests.test_task_updates_security import UpdateCourier

import pytest  # noqa: E402
pytestmark = pytest.mark.usefixtures('rotated_bootstrap_admin')

playwright=pytest.importorskip('playwright.sync_api')


def test_protocol_choice_optional_poll_update_and_footer_stop(chat_page,catalog):
    page,requests,bodies,errors,_=chat_page
    store,front,client,add,now=catalog
    best=add('Verified A2A Weather',kind='a2a',report_at=now)
    page.goto('https://agentconcierge.biz/#chat')
    page.locator('#chatProtocol').select_option('a2a')
    page.locator('#chatInput').fill('MCP weather forecast')
    page.locator('#chatSubmit').click()
    card=page.locator('.chat-recommendation')
    playwright.expect(card).to_contain_text('Verified A2A Weather')
    assert bodies[-1]['data']['protocol']=='a2a'
    assert bodies[-1]['data']['recommendations'][0]['id']==best
    # One updates control follows the reply's recommendations.
    page.get_by_role('button',name='Get updates for this task').last.click()
    dialog=page.locator('#taskUpdateDialog')
    playwright.expect(dialog).to_be_visible()
    assert page.locator('#taskUpdateConsent').is_checked() is False
    assert page.locator('#taskUpdateAuthority').is_checked() is False
    page.locator('#taskUpdateChannel').select_option('poll')
    page.locator('#taskUpdateAuthority').check()
    page.locator('#taskUpdateConsent').check()
    page.locator('#taskUpdateSubmit').click()
    page.locator('#taskUpdateConfirmDestination').click()
    playwright.expect(page.locator('#taskUpdateStatus')).to_have_text('Task updates are on.')
    assert not any(path=='/api/contact/submit' for _,path in requests)
    page.locator('#taskUpdateManage').click()
    playwright.expect(page.locator('#legalModalTitle')).to_have_text('Notification Preferences')
    playwright.expect(page.locator('#taskPreferences')).to_contain_text('A2A')
    page.get_by_role('button',name='Stop updates',exact=True).click()
    playwright.expect(page.locator('#taskPreferences')).to_contain_text('Stopped')
    assert store.query('SELECT state FROM agent_task_watches')[0]['state']=='revoked'
    assert not page.locator('#ftcCancelToken').count()
    assert page.evaluate('localStorage.getItem("visitorToken")') is None
    assert not errors


def test_webhook_verification_private_input_masking_and_delete(chat_page,catalog):
    page,_,_,errors,_=chat_page
    _,front,_,_,_=catalog
    courier=UpdateCourier();front.updates.courier=courier
    page.goto('https://agentconcierge.biz/#chat')
    page.locator('#chatInput').fill('MCP weather forecast')
    page.locator('#chatSubmit').click()
    page.get_by_role('button',name='Get updates for this task').click()
    page.locator('#taskUpdateChannel').select_option('webhook')
    endpoint='https://inbox.example/private-notification-inbox'
    page.locator('#taskUpdateUrl').fill(endpoint)
    assert page.locator('#taskUpdateUrl').get_attribute('data-clarity-mask')=='true'
    page.locator('#taskUpdateAuthority').check();page.locator('#taskUpdateConsent').check()
    page.locator('#taskUpdateSubmit').click()
    page.locator('#taskUpdateConfirmDestination').click()
    playwright.expect(page.locator('#taskUpdateVerify')).to_be_visible()
    playwright.expect(page.locator('#taskUpdateUrl')).to_have_value('')
    code=courier.challenges[-1]['verification_code']
    page.locator('#taskUpdateCode').fill(code)
    page.locator('#taskUpdateVerifyButton').click()
    playwright.expect(page.locator('#taskUpdateStatus')).to_have_text('Task updates are on.')
    assert endpoint not in page.locator('#chatMessages').inner_text()
    page.locator('#taskUpdateManage').click()
    page.get_by_role('button',name='Delete notification data').click()
    playwright.expect(page.locator('#taskPreferences')).to_contain_text('Stopped')
    assert not errors


def test_stop_link_fragment_is_removed_and_does_not_mutate_on_get(chat_page,catalog):
    page,requests,_,errors,_=chat_page
    _,front,client,_,_=catalog
    body=client.post('/chat',json={'message':'weather forecast'}).json()
    from agent_market.concierge.task_updates import NOTICE_VERSION
    row=front.updates.create(body['visitor']['id'],{'task':'weather forecast','channel':'poll','authority':True,'task_updates':True,'notice_version':NOTICE_VERSION})
    cap=front.updates.capability(row['id'])
    page.goto('https://agentconcierge.biz/#stop-updates='+cap)
    playwright.expect(page.locator('#taskStopFromLink')).to_be_visible()
    assert cap not in page.url
    assert front.updates._get(row['id'])['state']=='active'
    page.locator('#taskStopFromLink').click()
    playwright.expect(page.locator('#taskPreferences')).to_have_text('Task updates stopped.')
    assert front.updates._get(row['id'])['state']=='revoked'
    assert not errors


@pytest.mark.parametrize('width',[390,1280])
def test_update_dialog_keyboard_layout_and_untrusted_label(chat_page,width):
    page,_,_,errors,_=chat_page
    page.set_viewport_size({'width':width,'height':850})
    page.goto('https://agentconcierge.biz/#chat')
    page.locator('#chatInput').fill('MCP weather forecast');page.locator('#chatSubmit').click()
    page.get_by_role('button',name='Get updates for this task').click()
    playwright.expect(page.locator('#taskUpdateLabel')).to_be_focused()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    bounds=page.locator('#taskUpdateDialog').bounding_box()
    assert bounds['y'] >= 0 and bounds['y']+bounds['height'] <= 851
    page.screenshot(path=f'/tmp/a2a-task-updates-{width}.png')
    page.locator('#taskUpdateLabel').fill('<img src=x onerror=alert(1)>')
    page.locator('#taskUpdateAuthority').check();page.locator('#taskUpdateConsent').check()
    page.locator('#taskUpdateSubmit').click()
    playwright.expect(page.locator('#taskUpdateStatus')).to_contain_text('Unable to complete')
    assert page.locator('#taskUpdateDialog img').count()==0
    page.keyboard.press('Escape')
    playwright.expect(page.locator('#taskUpdateDialog')).not_to_be_visible()
    assert not errors


def test_admin_visiting_agents_shows_scoped_updates_and_can_stop(browser,catalog):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agent_market.gateway.dashboard import dashboard_router
    from agent_market.concierge.task_updates import NOTICE_VERSION
    store,front,client,add,now=catalog
    front.llm=None
    add('Admin Weather',report_at=now)
    response=client.post('/chat',json={'message':'MCP weather forecast'}).json()
    vid=response['visitor']['id']
    front.updates.create(vid,{'task':'weather forecast','protocol':'mcp','channel':'poll','authority':True,'task_updates':True,'notice_version':NOTICE_VERSION})
    app=FastAPI();app.include_router(dashboard_router(store,':memory:','admin-test-token',None,front=front))
    admin=TestClient(app,base_url='https://admin.test')
    context=browser.new_context()
    def serve(route):
        request=route.request;url=urlsplit(request.url)
        if url.hostname!='admin.test': route.abort();return
        res=admin.request(request.method,url.path+('?' + url.query if url.query else ''),content=request.post_data,headers=request.headers)
        route.fulfill(status=res.status_code,body=res.content,headers={k:v for k,v in res.headers.items() if k not in ('content-length','content-encoding','transfer-encoding')})
    context.route('**/*',serve)
    page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto('https://admin.test/admin/ui')
    page.locator('#adminLoginUsername').fill('sadmin');page.locator('#adminLoginPassword').fill('sadmin');page.locator('#adminLoginSubmitBtn').click()
    playwright.expect(page.locator('#adminLoginModal')).to_be_hidden()
    page.locator('[data-tab="visitors"]').click()
    page.locator("#vContact").select_option("all")
    page.locator('tr[data-vid="'+vid+'"]').click()
    playwright.expect(page.locator('#drawer')).to_contain_text('task-updates-2026-10-17-v1')
    playwright.expect(page.locator('#drawer')).to_contain_text('MCP')
    # Restricting a visitor's updates records an operator reason first.
    page.once('dialog',lambda dialog:dialog.accept('Visitor asked to stop task updates'))
    page.locator('#drawer [data-watch-action="stop"]').click()
    playwright.expect(page.locator('#drawer')).to_contain_text('revoked')
    assert not page.locator('#btnNurtureProSla').count() and not errors
    context.close();admin.close()
