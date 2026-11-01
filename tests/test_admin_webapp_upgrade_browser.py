"""Enhanced admin packages in Chromium using isolated gateway and provider transports."""
import json
import re
from zipfile import ZipFile

import pytest

from tests.test_admin_security_browser import browser
from tests.test_workflow_runtime_browser import studio, login
from tests.workflow_package_helpers import open_hosted_package

pytestmark = pytest.mark.usefixtures('rotated_bootstrap_admin')

playwright = pytest.importorskip('playwright.sync_api')
GATEWAY = 'https://agentconcierge.biz'


def exported(studio, tmp_path, inputs=False):
    page, wid, front, errors, requests = studio
    login(page)
    page.evaluate('async id=>{await loadWorkflows();selectWorkflow(id);}', wid)
    page.locator('#btnExportAppFromCanvas').click()
    playwright.expect(page.locator('#workflowAppExportModal')).to_be_visible()
    if inputs:
        page.locator('#appExportInputFields input').first.check()
        page.locator('#appExportAnyOrigin').uncheck()
        page.locator('#appExportOrigins').fill('https://customer.example')
    with page.expect_download() as event: page.locator('#btnDownloadStandaloneApp').click()
    path = tmp_path / 'enhanced.zip'; event.value.save_as(path)
    files = open_hosted_package(page, path)
    manifest = json.loads(files['app-manifest.json'])
    return page, wid, front, errors, requests, manifest


def status_route(page, callback):
    def respond(route):
        if route.request.method != 'GET': return route.fallback()
        return callback(route)
    page.context.route(re.compile(r'https://agentconcierge\.biz/api/workflow-apps/[^/]+/runs/[^/]+$'), respond)


def answer(route, body, status=200, **headers):
    route.fulfill(status=status, body=json.dumps(body), headers={
        'Content-Type':'application/json', 'Access-Control-Allow-Origin':'*',
        'Access-Control-Expose-Headers':'Retry-After', **headers})


def test_selected_input_reaches_real_provider_call_and_admin_can_revoke(studio, tmp_path):
    page, wid, front, errors, requests, manifest = exported(studio, tmp_path, inputs=True)
    field = manifest['input_fields'][0]
    page.locator('#input-' + field['id']).fill('London')
    page.locator('#runAppBtn').click()
    playwright.expect(page.locator('#appStatus')).to_have_text('Workflow: succeeded')
    latest = front.workflows.get(front.workflows.history(wid)[0]['id'])
    assert latest['node_results'][0]['input'] == {'city':'London'}
    assert front.store.get_workflow(wid)['nodes'][0]['data']['input'] == {'city':'Tokyo'}
    assert manifest['allowed_origins'] == ['https://customer.example']
    assert 'argument' not in str(manifest) and 'node_id' not in str(manifest)
    sent = [json.loads(b) for m,p,b in requests if m == 'POST' and p == '/api/workflow-apps/'+manifest['app_id']+'/runs']
    assert sent == [{'input':{field['id']:'London'}}]
    page.goto('https://admin.test/admin/ui')
    page.locator('[data-tab="workflows"]').click()
    page.evaluate('async id=>{await loadWorkflows();selectWorkflow(id);}', wid)
    page.locator('#btnExportAppFromCanvas').click()
    page.locator('#appExportDeployments').get_by_role('button', name='철회', exact=True).click()
    playwright.expect(page.locator('#appExportDeployments')).to_contain_text('철회됨')
    assert not errors


def test_sdk_recovers_status_errors_and_announces_only_confirmed_fallback_once(studio, tmp_path):
    page, wid, _, errors, requests, _ = exported(studio, tmp_path)
    calls = []
    def poll(route):
        calls.append(route.request.method)
        if len(calls) == 1: return answer(route, {'error':'private diagnostic'}, 429, **{'Retry-After':'0'})
        if len(calls) == 2: return route.abort()
        if len(calls) == 3: return answer(route, {'status':'running','node_results':[{'output':{'fallback_used':True}}]})
        return answer(route, {'status':'succeeded' if len(calls)>4 else 'running','node_results':[{'node_id':'a','fallback_used':True}]})
    status_route(page, poll)
    result = page.evaluate('''async id=>{
      const client=AgentConciergeWorkflow.createClient(), handle=await client.run(id);
      let retries=[], notices=0, falseNotices=0;
      const result=await client.wait(handle,{intervalMs:300,timeoutMs:8000,
        onRetry:e=>retries.push(e.status), onFallback:()=>notices++,
        onUpdate:data=>{if(data.node_results?.[0]?.output?.fallback_used) falseNotices=notices;}});
      return {status:result.status,retries,notices,falseNotices};
    }''', wid)
    assert result == {'status':'succeeded','retries':[429,0],'notices':1,'falseNotices':0}
    assert len(calls) == 5
    assert len([p for m,p,_ in requests if m=='POST' and p.endswith('/runs')]) == 1
    assert not errors


@pytest.mark.parametrize('mode', ['persistent', 'invalid', 'callback'])
def test_sdk_retry_bounds_and_callback_errors(studio, tmp_path, mode):
    page, wid, _, errors, _, _ = exported(studio, tmp_path)
    calls = []
    def poll(route):
        calls.append(1)
        answer(route, {'status':'running'} if mode=='callback' else None, 503 if mode=='persistent' else 200)
    status_route(page, poll)
    message = page.evaluate('''async ({id,mode})=>{
      const client=AgentConciergeWorkflow.createClient(), handle=await client.run(id);
      try {await client.wait(handle,{intervalMs:300,timeoutMs:10000,
        onUpdate:mode==='callback'?()=>{throw new Error('consumer callback failed');}:undefined});return 'unexpected';}
      catch(e){return e.message;}
    }''', {'id':wid,'mode':mode})
    assert message != 'unexpected'
    assert len(calls) == (4 if mode=='persistent' else 1)
    if mode=='callback': assert message == 'consumer callback failed'
    assert not errors


@pytest.mark.parametrize('status', [429,503])
def test_sdk_never_retries_start_posts(studio, tmp_path, status):
    page, wid, _, errors, _, manifest = exported(studio, tmp_path)
    calls = []
    def fail(route):
        if route.request.method != 'POST': return route.fallback()
        calls.append(1); answer(route, {'error':'private diagnostic'}, status)
    page.context.route(GATEWAY+'/api/workflow-apps/'+manifest['app_id']+'/runs', fail)
    message = page.evaluate('''async id=>{try{await AgentConciergeWorkflow.createClient().run(id);return 'unexpected';}catch(e){return e.message;}}''', wid)
    assert len(calls) == 1 and message != 'unexpected' and 'private diagnostic' not in message
    assert not errors


def test_result_dom_selection_scroll_json_and_xss_are_preserved(studio, tmp_path):
    page, _, _, errors, _, _ = exported(studio, tmp_path)
    calls = []
    payload = {'text':'<img src=x onerror=alert(1)>', 'lines':['Recorded result '+str(i) for i in range(150)]}
    def poll(route):
        calls.append(1)
        answer(route, {'status':'succeeded' if len(calls)>1 else 'running',
                      'node_results':[{'node_id':'stable','name':'Result','status':'succeeded','output':payload}]})
    status_route(page, poll)
    page.locator('#runAppBtn').click()
    playwright.expect(page.locator('#stepsContainer pre')).to_be_visible()
    page.evaluate('''()=>{
      globalThis.savedPre=document.querySelector('#stepsContainer pre');
      savedPre.scrollTop=100;
      const range=document.createRange(); range.setStart(savedPre.firstChild,5);range.setEnd(savedPre.firstChild,15);
      getSelection().removeAllRanges();getSelection().addRange(range);
      globalThis.selectedText=getSelection().toString();
    }''')
    playwright.expect(page.locator('#appStatus')).to_have_text('Workflow: succeeded')
    result = page.evaluate('''()=>({same:savedPre===document.querySelector('#stepsContainer pre'),
      selection:getSelection().toString()===selectedText,scroll:savedPre.scrollTop,
      json:JSON.parse(savedPre.textContent),injected:document.querySelectorAll('#stepsContainer img').length})''')
    assert result['same'] and result['selection'] and result['scroll'] == 100
    assert result['json'] == payload and result['injected'] == 0
    assert not errors


def test_stop_is_locked_aborts_polling_and_waits_for_confirmed_terminal_status(studio, tmp_path):
    page, _, _, errors, _, manifest = exported(studio, tmp_path)
    polls, cancels = [], []
    terminal, unavailable = [False], [False]
    def poll(route):
        polls.append(1)
        if unavailable[0]: return answer(route, {'error':'not available'}, 404)
        answer(route, {'status':'cancelled' if terminal[0] else 'running','node_results':[]})
    status_route(page,poll)
    def cancel(route):
        if route.request.method != 'POST': return route.fallback()
        cancels.append(1); answer(route, {'ok':True,'cancel_requested':True})
    page.context.route(GATEWAY+'/api/workflow-apps/'+manifest['app_id']+'/runs/*/cancel',cancel)
    page.locator('#runAppBtn').click()
    playwright.expect(page.locator('#appStatus')).to_have_text('Workflow: running')
    page.evaluate("()=>{document.querySelector('#cancelAppBtn').click();document.querySelector('#cancelAppBtn').click();}")
    playwright.expect(page.locator('#appStatus')).to_contain_text('Cancellation requested.')
    playwright.expect(page.locator('#runAppBtn')).to_be_disabled()
    playwright.expect(page.locator('#cancelAppBtn')).to_be_disabled()
    before = len(polls)
    page.wait_for_timeout(1400)
    assert len(polls)==before and len(cancels)==1
    unavailable[0] = True
    page.get_by_role('button', name='Check final status', exact=True).click()
    playwright.expect(page.get_by_role('button', name='Resume status', exact=True)).to_be_visible()
    playwright.expect(page.locator('#runAppBtn')).to_be_disabled()
    playwright.expect(page.locator('#cancelAppBtn')).to_be_disabled()
    terminal[0], unavailable[0] = True, False
    page.get_by_role('button', name='Resume status', exact=True).click()
    playwright.expect(page.locator('#appStatus')).to_have_text('Workflow: cancelled')
    playwright.expect(page.locator('#runAppBtn')).to_be_enabled()
    assert not errors
