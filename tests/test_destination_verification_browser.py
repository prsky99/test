"""Native Chromium/SW logic with an emulated OS notification and fake push provider."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from agent_market.concierge.front import create_front_app
from tests.test_destination_verification import delivery, updates, catalog  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401

playwright=pytest.importorskip('playwright.sync_api')

SW_SHIM="""self.__notifications=[];self.__handlers={};
const nativeAdd=self.addEventListener.bind(self);
self.addEventListener=(name,fn)=>{self.__handlers[name]=fn;nativeAdd(name,fn);};
self.registration.showNotification=async(title,options)=>{self.__notifications.push({title,options});};
"""


@pytest.fixture
def notification_page(browser,delivery):
    store,front,client,add,headers,courier,data,vid,push,payload=delivery
    state={'client':None,'requests':[]}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):self.forward()
        def do_POST(self):self.forward()
        def forward(self):
            body=self.rfile.read(int(self.headers.get('Content-Length','0')))
            state['requests'].append((self.command,urlsplit(self.path).path))
            forwarded=dict(self.headers)
            # Production serves this page from its trusted HTTPS origin; the local proxy
            # (needed for service workers) forwards same-origin requests as that origin.
            if forwarded.get('Origin')==origin:forwarded['Origin']='https://agentconcierge.biz'
            response=state['client'].request(self.command,self.path,content=body,headers=forwarded)
            content=response.content
            if self.path.startswith('/task-updates-sw.js'):content=SW_SHIM.encode()+content
            self.send_response(response.status_code)
            for key,value in response.headers.items():
                if key.lower() not in ('content-length','content-encoding','transfer-encoding','connection'):self.send_header(key,value)
            self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    origin='http://127.0.0.1:'+str(server.server_port)
    testclient=TestClient(create_front_app(front),base_url=origin);state['client']=testclient
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    context=browser.new_context(permissions=['notifications'])
    context.route('**/*',lambda route:route.continue_() if urlsplit(route.request.url).hostname=='127.0.0.1' else route.abort())
    mock='''window.__notificationPermission="granted";window.__permissionCalls=0;window.__unsubscribed=0;
Object.defineProperty(Notification,"permission",{get:()=>window.__notificationPermission});
Notification.requestPermission=async()=>{window.__permissionCalls++;return window.__notificationPermission;};
const mockSubscription={toJSON:()=>(SUBSCRIPTION),unsubscribe:async()=>{window.__unsubscribed++;return true;}};
PushManager.prototype.getSubscription=async()=>null;
PushManager.prototype.subscribe=async()=>mockSubscription;
'''.replace('SUBSCRIPTION',json.dumps(payload['subscription']))
    context.add_init_script(mock)
    page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto(origin+'/#chat')
    assert page.evaluate('window.__permissionCalls') == 0, errors
    page.get_by_role('button',name='Reject Non-Essential',exact=True).click()
    close_notice = page.locator('#layerModalCloseBtn')
    if close_notice.is_visible():
        close_notice.click()
    page.locator('#chatInput').fill('MCP weather forecast');page.locator('#chatSubmit').click()
    page.get_by_role('button',name='Get updates for this task').click()
    yield page,context,origin,state,errors,delivery
    context.close();server.shutdown();server.server_close();thread.join(timeout=5);testclient.close()


def review(page,channel='browser',marketing=False):
    page.locator('#taskUpdateChannel').select_option(channel)
    if channel in ('webhook','a2a'):page.locator('#taskUpdateUrl').fill('https://inbox.example/private-browser-test-inbox')
    page.locator('#taskUpdateAuthority').check();page.locator('#taskUpdateConsent').check()
    if marketing:page.locator('#taskUpdateMarketing').check()
    page.locator('#taskUpdateSubmit').click()
    playwright.expect(page.locator('#taskUpdateReview')).to_be_visible()


def push_to_worker(context,message):
    worker=context.service_workers[0]
    worker.evaluate('''async data=>{let pending;self.__handlers.push({data:{json:()=>data},waitUntil:value=>pending=value});await pending;}''',message)
    return worker


def click_notification(worker,action='confirm'):
    worker.evaluate('''async action=>{const note=self.__notifications[0];let pending;self.__handlers.notificationclick({notification:{data:note.options.data,close:()=>{}},action,waitUntil:value=>pending=value});await pending;}''',action)


@pytest.mark.parametrize("width",[390,1280])
def test_browser_requires_test_notification_and_actual_worker_click(notification_page,width):
    page,context,origin,state,errors,delivery=notification_page
    store,front,client,add,headers,courier,data,vid,push,payload=delivery
    page.set_viewport_size({'width':width,'height':900})
    assert page.locator('#taskUpdateChannel').input_value()=='browser'
    assert not page.locator('#taskUpdateMarketing').is_checked()
    review(page,marketing=True)
    assert page.evaluate('window.__permissionCalls')==0 and not store.query('SELECT * FROM agent_task_watches')
    page.locator('#taskUpdateConfirmDestination').click()
    playwright.expect(page.locator('#taskUpdateBrowserPending')).to_be_visible()
    row=dict(store.query('SELECT * FROM agent_task_watches')[0])
    assert row['state']=='pending_verification' and not row['verified_at']
    worker=push_to_worker(context,push.sent[-1][1])
    assert worker.evaluate('self.__notifications[0].title')=='Confirm browser notifications'
    assert store.query('SELECT state FROM agent_task_watches')[0]['state']=='pending_verification'
    click_notification(worker)
    playwright.expect(page.locator('#taskUpdateStatus')).to_have_text('Browser notifications are verified and on.')
    assert store.query('SELECT verified_at FROM agent_marketing_permissions')[0]['verified_at']
    assert page.evaluate('window.__permissionCalls')==1 and not errors
    assert not page.locator('#taskUpdateCode').is_visible()
    playwright.expect(page.locator('#taskUpdatePendingDecline')).to_be_hidden()
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    assert page.locator('#taskUpdateDialog').evaluate('(el)=>el.scrollWidth<=el.clientWidth')
    from pathlib import Path
    report=Path('reports/security-2026-10-17-destination-verification');report.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(report/f'browser-confirmed-{width}.png'))


def test_permission_denial_creates_no_registration(notification_page):
    page,context,origin,state,errors,delivery=notification_page
    store=delivery[0]
    page.evaluate('window.__notificationPermission="denied"')
    review(page);page.locator('#taskUpdateConfirmDestination').click()
    playwright.expect(page.locator('#taskUpdateStatus')).to_contain_text('not allowed')
    assert not store.query('SELECT * FROM agent_task_watches')
    assert not [r for r in state['requests'] if r==('POST','/api/task-updates')]
    assert not errors


def test_decline_review_does_not_create_meaningless_data(notification_page):
    page,context,origin,state,errors,delivery=notification_page
    review(page,'webhook',marketing=True)
    playwright.expect(page.locator('#taskUpdateReviewDestination')).to_have_text('https://inbox.example/private-browser-test-inbox')
    assert page.locator('#taskUpdateReviewDestination').get_attribute('data-clarity-mask')=='true'
    page.locator('#taskUpdateReviewDecline').click()
    playwright.expect(page.locator('#taskUpdateStatus')).to_contain_text('Request deleted')
    assert not delivery[0].query('SELECT * FROM agent_task_watches')
    assert not delivery[5].challenges and not errors


@pytest.mark.parametrize('decision',['decline','close','notification_decline'])
def test_pending_decline_or_close_deletes_registration(notification_page,decision):
    page,context,origin,state,errors,delivery=notification_page
    store,front,client,add,headers,courier,data,vid,push,payload=delivery
    review(page,marketing=True);page.locator('#taskUpdateConfirmDestination').click()
    playwright.expect(page.locator('#taskUpdateBrowserPending')).to_be_visible()
    if decision=='notification_decline':click_notification(push_to_worker(context,push.sent[-1][1]),'decline')
    elif decision=='close':page.locator('#taskUpdateClose').click()
    else:page.locator('#taskUpdatePendingDecline').click()
    page.wait_for_function('()=>document.getElementById("taskUpdateDialog").open===false || document.getElementById("taskUpdateStatus").textContent.includes("removed") || document.getElementById("taskUpdateStatus").textContent.includes("deleted")')
    # The close path performs an asynchronous authenticated removal.
    for _ in range(30):
        if not store.query('SELECT * FROM agent_task_watches'):break
        page.wait_for_timeout(50)
    assert not store.query('SELECT * FROM agent_task_watches')
    assert not store.query('SELECT * FROM agent_marketing_permissions') and not errors


@pytest.mark.parametrize('channel',['webhook','a2a'])
def test_webhook_confirmation_code_and_optional_marketing_are_separate(notification_page,channel):
    page,context,origin,state,errors,delivery=notification_page
    store,front,client,add,headers,courier,data,vid,push,payload=delivery
    review(page,channel,marketing=True);page.locator('#taskUpdateConfirmDestination').click()
    playwright.expect(page.locator('#taskUpdateVerify')).to_be_visible()
    assert not store.query('SELECT verified_at FROM agent_marketing_permissions')[0]['verified_at']
    page.locator('#taskUpdateCode').fill(courier.challenges[-1]['verification_code']);page.locator('#taskUpdateVerifyButton').click()
    playwright.expect(page.locator('#taskUpdateStatus')).to_have_text('Task updates are on.')
    page.locator('#taskUpdateManage').click()
    playwright.expect(page.locator('#taskPreferences')).to_contain_text('Separate permission recorded')
    page.get_by_role('button',name='Withdraw marketing permission').click()
    playwright.expect(page.locator('#taskPreferences')).to_contain_text('Marketing: Not enabled')
    assert store.query('SELECT state FROM agent_task_watches')[0]['state']=='active' and not errors


def test_unavailable_browser_errors_do_not_leak_runtime_details(notification_page):
    page,context,origin,state,errors,delivery=notification_page
    page.evaluate('()=>{Notification.requestPermission=async()=>{throw new Error("PRIVATE_BROWSER_DIAGNOSTIC /internal/path")};}')
    review(page);page.locator('#taskUpdateConfirmDestination').click()
    playwright.expect(page.locator('#taskUpdateStatus')).to_contain_text('Unable to verify this destination')
    assert 'PRIVATE_BROWSER_DIAGNOSTIC' not in page.locator('#taskUpdateDialog').inner_text()
    assert not delivery[0].query('SELECT * FROM agent_task_watches') and not errors


def test_revoked_browser_permission_removes_previously_confirmed_watch(notification_page):
    page,context,origin,state,errors,delivery=notification_page
    review(page,marketing=True);page.locator('#taskUpdateConfirmDestination').click()
    playwright.expect(page.locator('#taskUpdateBrowserPending')).to_be_visible()
    click_notification(push_to_worker(context,delivery[8].sent[-1][1]))
    playwright.expect(page.locator('#taskUpdateStatus')).to_have_text('Browser notifications are verified and on.')
    page.locator('#taskUpdateClose').click()
    page.evaluate('()=>{window.__notificationPermission="denied";document.dispatchEvent(new Event("visibilitychange"));}')
    for _ in range(50):
        if not delivery[0].query('SELECT * FROM agent_task_watches'):break
        page.wait_for_timeout(50)
    assert not delivery[0].query('SELECT * FROM agent_task_watches')
    grant=delivery[0].query('SELECT * FROM agent_marketing_permissions')[0]
    assert grant['withdrawn_at'] and not errors
