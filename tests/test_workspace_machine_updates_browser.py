"""Desktop dialog uses actual private APIs and no external delivery target."""

from urllib.parse import urlsplit

import pytest

from tests.test_front_workflow_browser import browser  # noqa: F401
from tests.test_workspace_machine_updates import machine, provider, subscribe, prepare  # noqa: F401

playwright = pytest.importorskip('playwright.sync_api')


@pytest.fixture
def machine_page(machine, browser):
    w = machine
    context = browser.new_context(viewport={'width': 1440, 'height': 1000})
    calls = []

    def route(request):
        url = urlsplit(request.request.url)
        if url.hostname != 'private.test':
            request.abort(); return
        if url.path == '/':
            request.fulfill(status=200, content_type='text/html',
                            body='<main><select id="workspaceSelect"><option></option></select></main>')
            return
        calls.append((request.request.method, url.path))
        response = w.machine_http.request(request.request.method, url.path,
            headers=w.machine_headers | {'content-type': request.request.headers.get('content-type', '')},
            content=request.request.post_data)
        request.fulfill(status=response.status_code, body=response.content,
            headers={key:value for key,value in response.headers.items() if key not in ('content-length','content-encoding','transfer-encoding')})

    context.route('https://private.test/**', route)
    page = context.new_page()
    page.goto('https://private.test/')
    page.evaluate('''config => {
      window.token=config.token; window.currentUser={user_id:1,role:'superadmin'};
      document.getElementById('workspaceSelect').append(new Option('Fixture workspace',config.ws));
      document.getElementById('workspaceSelect').value=config.ws;
      window.api=async (path,options={}) => {
        const response=await fetch('https://private.test'+path,{method:options.method||'GET',
          headers:{'Content-Type':'application/json'},body:options.json===undefined?undefined:JSON.stringify(options.json)});
        const value=await response.json(); if(!response.ok) { const e=Error('private_request');e.status=response.status;throw e; } return value;
      };
    }''', {'token':w.raw_staff,'ws':w.ws})
    page.add_script_tag(path='agent_market/gateway/workspace-machine-updates-admin.js')
    errors=[]; page.on('pageerror',lambda error:errors.append(str(error)))
    yield page,w,calls,errors
    context.close()


def test_desktop_fresh_consent_prepare_then_exact_once_delivery_receipt(machine_page):
    page,w,calls,errors=machine_page
    page.evaluate('ws=>WorkspaceMachineUpdatesAdmin.open(ws)',w.ws)
    dialog=page.locator('#workspaceMachineUpdatesDialog')
    playwright.expect(dialog).to_be_visible()
    playwright.expect(dialog).to_contain_text('Actual external target acceptance remains unverified.')
    assert page.locator('input[type="checkbox"]:checked').count()==0
    labels=dialog.locator('section').first
    labels.get_by_label('Catalog resource reference',exact=False).fill('1')
    labels.get_by_label('Configured destination reference',exact=False).fill('configured_inbox')
    labels.get_by_label('Configured audience reference',exact=False).fill('audience_fixture')
    labels.get_by_label('Delivery protocol',exact=False).select_option('a2a_inbox')
    labels.get_by_role('button',name='Authorize subscription',exact=True).click()
    assert not any(method=='POST' for method,_ in calls)
    labels.locator('input[type="checkbox"]').check()
    labels.get_by_role('button',name='Authorize subscription',exact=True).click()
    playwright.expect(dialog.get_by_role('button',name='Prepare notice',exact=True)).to_be_visible()
    subcard=dialog.locator('section').filter(has=page.get_by_role('button',name='Prepare notice',exact=True))
    assert page.locator('input[type="checkbox"]:checked').count()==0
    subcard.locator('input[type="checkbox"]').first.check()
    subcard.get_by_role('button',name='Prepare notice',exact=True).click()
    playwright.expect(dialog.get_by_role('button',name='Dispatch once',exact=True)).to_be_visible()
    assert not w.receiver.calls
    eventcard=dialog.locator('section').filter(has=page.get_by_role('button',name='Dispatch once',exact=True))
    eventcard.locator('input[type="checkbox"]').check()
    eventcard.get_by_role('button',name='Dispatch once',exact=True).click()
    playwright.expect(dialog).to_contain_text('Delivery state: accepted.')
    assert len(w.receiver.calls)==1 and page.locator('input[type="checkbox"]:checked').count()==0
    assert dialog.get_by_role('button',name='Dispatch once',exact=True).count()==0
    assert 'synthetic.invalid' not in dialog.inner_text() and not errors


def test_unknown_receipt_disables_replay_and_session_change_discards_dialog(machine_page):
    page,w,calls,errors=machine_page
    event=prepare(w);w.receiver.fault='exception'
    page.evaluate('ws=>WorkspaceMachineUpdatesAdmin.open(ws)',w.ws)
    dialog=page.locator('#workspaceMachineUpdatesDialog')
    eventcard=dialog.locator('section').filter(has=page.get_by_role('button',name='Dispatch once',exact=True))
    eventcard.locator('input[type="checkbox"]').check()
    eventcard.get_by_role('button',name='Dispatch once',exact=True).click()
    playwright.expect(dialog).to_contain_text('Delivery state: unknown.')
    playwright.expect(dialog).to_contain_text('This event cannot be retried.')
    assert len(w.receiver.calls)==1
    page.evaluate("token='changed-session'; WorkspaceMachineUpdatesAdmin.onSession()")
    playwright.expect(dialog).to_have_count(0)
    assert not errors


def test_dialog_renders_hostile_status_text_without_markup_and_rejects_stale_reads(machine_page):
    page,w,calls,errors=machine_page
    page.evaluate('''() => {
      window.api=async()=>({ok:true,profile:'workspace-machine-evidence-updates-v1',result:{can_manage:false,
        subscriptions:[{id:'<img src=x onerror="window.machineXss=1">',state:'unavailable'}],events:[]}});
    }''')
    page.evaluate('ws=>WorkspaceMachineUpdatesAdmin.open(ws)',w.ws)
    assert page.locator('#workspaceMachineUpdatesDialog img').count()==0
    assert page.evaluate('window.machineXss||0')==0
    page.evaluate('''() => {
      window.pendingMachineRead=null;
      window.api=()=>new Promise(resolve=>{window.pendingMachineRead=resolve});
    }''')
    page.evaluate('ws=>{WorkspaceMachineUpdatesAdmin.open(ws)}',w.ws)
    page.evaluate('WorkspaceMachineUpdatesAdmin.leave()')
    page.evaluate('''() => pendingMachineRead({ok:true,profile:'workspace-machine-evidence-updates-v1',result:{}})''')
    assert page.locator('#workspaceMachineUpdatesDialog').count()==0
    assert not errors and not w.receiver.calls


def test_owner_receiver_activation_rechecks_edited_fields_and_keeps_receipt_history(machine_page):
    import time
    from agent_market.workspace_machine_receiver import MachineReceiver, ReceiverBinding
    from agent_market.workspace_machine_update_service import router_for
    from agent_market.workspace_machine_updates import PURPOSE
    page,w,calls,errors=machine_page
    receiver = MachineReceiver(w.access, enabled=True, bindings=(ReceiverBinding(w.ws, 'configured_inbox',
        'audience_fixture', 'a2a_inbox', PURPOSE, 1, time.time()+3600, 'isolated', w.machine.envelope_key(w.destination), b'r'*32),))
    w.machine_http.app.include_router(router_for(w.machine, receiver=receiver))
    page.evaluate('ws=>WorkspaceMachineUpdatesAdmin.open(ws)',w.ws)
    dialog=page.locator('#workspaceMachineUpdatesDialog')
    card=dialog.locator('section').filter(has=page.get_by_role('heading',name='Durable private receiver',exact=True))
    playwright.expect(card).to_contain_text('A trusted private receiver binding is configured.')
    card.get_by_label('Receiver configured destination reference',exact=False).fill('configured_inbox')
    card.get_by_label('Receiver configured audience reference',exact=False).fill('audience_fixture')
    card.get_by_label('Receiver protocol',exact=True).select_option('a2a_inbox')
    card.get_by_label('Receiver activation lifetime in seconds',exact=False).fill('600')
    card.get_by_role('button',name='Activate private receiver',exact=True).click()
    assert not any(path.endswith('/receivers/activate') for method,path in calls)
    check=card.get_by_label('Activate only the exact configured receiver reference',exact=False)
    check.check()
    card.get_by_label('Receiver activation lifetime in seconds',exact=False).fill('300')
    playwright.expect(check).not_to_be_checked()
    check.check()
    card.get_by_role('button',name='Activate private receiver',exact=True).click()
    playwright.expect(card.get_by_role('button',name='Revoke private receiver',exact=True)).to_be_visible()
    assert len(receiver.status(w.ws,w.staff[1])['authorities'])==1
    assert dialog.locator('input[type="checkbox"]:checked').count()==0
    card.get_by_role('button',name='Revoke private receiver',exact=True).click()
    assert not any(path.endswith('/receivers/revoke') for method,path in calls)
    card.get_by_label('Revoke this exact receiver activation',exact=False).check()
    card.get_by_role('button',name='Revoke private receiver',exact=True).click()
    playwright.expect(card).to_contain_text('revoked.')
    assert receiver.status(w.ws,w.staff[1])['receipts']==[]
    assert sum(path.endswith('/receivers/activate') for method,path in calls)==1
    assert sum(path.endswith('/receivers/revoke') for method,path in calls)==1
    assert not errors and not w.receiver.calls
