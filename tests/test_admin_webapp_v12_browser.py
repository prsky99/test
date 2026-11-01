"""Explicit deployment review and per-run sharing use isolated apps/providers."""
from io import BytesIO
import json
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZipFile

import pytest
from tests.browser_wait import pending_request
from playwright.sync_api import expect

from agent_market.admin_workflow_webapp_v12 import build_admin_package_v12
from tests.test_admin_security_browser import browser
from tests.test_workflow_apps_v12 import v12_api, v12_runtime, export_request, ORIGIN
from tests.test_workflow_runtime import wait
from tests.test_workflow_fallback import routing

pytestmark = pytest.mark.usefixtures('rotated_bootstrap_admin')


@pytest.fixture
def v12_page(browser,v12_api,rotated_bootstrap_admin):
    rt,wf,service,calls,public,admin=v12_api
    context=browser.new_context();page=context.new_page();errors=[];external=[];requests=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    def route(request):
        req=request.request;url=urlsplit(req.url);client=public if url.hostname=='agentconcierge.biz' else admin if url.hostname=='admin.example' else None
        if client is None:external.append(req.url);return request.abort()
        requests.append((req.method,url.path,req.post_data,req.headers))
        response=client.request(req.method,url.path+('?' + url.query if url.query else ''),content=req.post_data,headers=req.headers)
        request.fulfill(status=response.status_code,body=response.content,headers={key:value for key,value in response.headers.items() if key not in ('content-length','content-encoding','transfer-encoding')})
    context.route('**/*',route)
    yield page,rt,wf,service,calls,errors,external,requests
    context.close()


def enter_export(page,wf):
    page.goto('https://admin.example/admin/ui');page.locator('#adminLoginUsername').fill('sadmin');page.locator('#adminLoginPassword').fill('sadmin');page.locator('#adminLoginSubmitBtn').click()
    expect(page.locator('#adminLoginModal')).to_be_hidden();page.locator('[data-tab="workflows"]').click()
    page.evaluate('async id=>{await loadWorkflows();selectWorkflow(id);}',wf['id'])
    page.locator('#btnExportAppFromCanvas').click();expect(page.locator('#workflowAppExportModal')).to_be_visible()


def open_review(page):
    page.locator('#appV12Open').click();expect(page.locator('#workflowAppV12Dialog')).to_be_visible()
    expect(page.locator('#appV12Prepare')).to_be_enabled()
    page.locator('#appV12Origins').fill(ORIGIN)


def prepare_review(page):
    page.locator('#appV12Prepare').click();expect(page.locator('#appV12Status')).to_contain_text('Complete deployment review ready')


def open_package(page,files):
    root=ORIGIN+'/apps/reviewed/'
    def hosted(route):
        name=route.request.url.removeprefix(root) or 'index.html';content=files.get(name)
        if content is None:return route.fulfill(status=404,body='Not found')
        kind='application/javascript' if name.endswith('.js') else 'text/css' if name.endswith('.css') else 'text/html'
        route.fulfill(status=200,body=content,content_type=kind)
    page.context.route(ORIGIN+'/**',hosted);page.goto(root)


def package_for(rt,wf,service):
    result=service.export_admin(wf['id'],export_request(service,wf),1)
    data,_=build_admin_package_v12(result['config'],result['deployment'])
    with ZipFile(BytesIO(data)) as archive:return {name:archive.read(name) for name in archive.namelist()}


def test_explicit_admin_review_exports_local_bytes_and_each_visitor_must_review_again(v12_page,tmp_path):
    page,rt,wf,service,calls,errors,external,requests=v12_page;enter_export(page,wf)
    assert not rt.store.query('SELECT id FROM workflow_deployment_grants') and not calls
    expect(page.locator('#btnDownloadStandaloneApp')).to_be_enabled()
    open_review(page);prepare_review(page)
    expect(page.locator('#appV12Preview')).to_contain_text('Python documentation search')
    expect(page.locator('#appV12Preview')).to_contain_text(ORIGIN)
    expect(page.locator('#appV12Authority')).not_to_be_checked();expect(page.locator('#appV12Zip')).to_be_disabled()
    page.set_viewport_size({'width':1280,'height':1100});page.screenshot(path='reports/advancement-sdk12-consent-2026-10-18/admin-deployment-review.png')
    page.evaluate('downloadV12Export("package")');assert not rt.store.query('SELECT id FROM workflow_deployment_grants')
    page.locator('#appV12Authority').check()
    with page.expect_download() as downloaded:
        with page.expect_response('**/export-app-v12/package') as package_response:page.locator('#appV12Zip').click()
        response=package_response.value
        assert response.status==200,response.text()
        expect(page.locator('#appV12Status')).to_contain_text('exported locally')
    data=Path(downloaded.value.path()).read_bytes()
    with ZipFile(BytesIO(data)) as archive:files={name:archive.read(name) for name in archive.namelist()}
    manifest=json.loads(files['app-manifest.json']);assert manifest['sdk_version']=='1.2.0'
    assert len(rt.store.query('SELECT id FROM workflow_deployment_grants'))==1 and not calls
    expect(page.locator('#appV12Authority')).not_to_be_checked()
    page.wait_for_function('v12ExportUrl===""')
    open_package(page,files)
    expect(page.locator('#runAppBtn')).to_be_disabled();assert not calls
    page.locator('#prepareAppBtn').click();expect(page.locator('#appStatus')).to_contain_text('Review ready')
    expect(page.locator('#inputReview')).to_contain_text('Python documentation search')
    expect(page.locator('#shareAppAuthority')).not_to_be_checked();expect(page.locator('#liveAppAuthority')).not_to_be_checked()
    page.locator('#shareAppAuthority').check();expect(page.locator('#runAppBtn')).to_be_disabled()
    page.locator('#liveAppAuthority').check();page.locator('#runAppBtn').click()
    expect(page.locator('#appStatus')).to_have_text('Workflow: succeeded',timeout=15000)
    expect(page.locator('#stepsContainer')).to_contain_text('Current documentation')
    rendered=page.locator('#stepsContainer').text_content()
    for private in ('structuredContent','"content"','"trigger"','Manual search','node_id','Documentation agent'):
        assert private not in rendered
    expect(page.locator('#stepsContainer h2')).to_have_text('Search 1 · Succeeded')
    expect(page.locator('#inputReview')).to_contain_text('Query: Python documentation search')
    assert 'docs.search.v1' not in page.locator('#inputReview').text_content()
    assert len(calls)==1
    sent=[json.loads(body) for method,path,body,_ in requests if method=='POST' and path.startswith('/api/workflow-apps-v12/') and path.endswith('/runs')]
    assert len(sent)==1 and sent[0]['share_authority'] is True and sent[0]['live_authority'] is True
    assert 'input' not in sent[0] and 'grant_authority' not in sent[0]
    expect(page.locator('#runAppBtn')).to_be_disabled();expect(page.locator('#shareAppAuthority')).not_to_be_checked()
    assert not page.evaluate('Object.keys(localStorage).concat(Object.keys(sessionStorage)).length')
    page.set_viewport_size({'width':1280,'height':1100});page.screenshot(path='reports/advancement-sdk12-consent-2026-10-18/generated-app.png')
    assert not errors and not external


@pytest.mark.parametrize('action',['edit','close','escape','role'])
def test_admin_proposal_and_grant_ack_clear_on_context_change(v12_page,action):
    page,rt,wf,_,calls,errors,external,_=v12_page;enter_export(page,wf);open_review(page);prepare_review(page);page.locator('#appV12Authority').check()
    if action=='edit':page.locator('#appV12Origins').fill('https://other.example')
    elif action=='close':page.locator('#appV12Close').click()
    elif action=='escape':page.keyboard.press('Escape')
    else:page.evaluate('()=>{currentUser.role="admin";updateUserUI(currentUser,false);}')
    assert page.evaluate('v12ExportPlan===null')
    expect(page.locator('#appV12Authority')).not_to_be_checked();expect(page.locator('#appV12Zip')).to_be_disabled()
    assert not rt.store.query('SELECT id FROM workflow_deployment_grants') and not calls and not errors and not external


@pytest.mark.parametrize('action',['close','logout','token'])
def test_closed_export_ignores_late_file_response_without_creating_blob(v12_page,action):
    page,rt,wf,_,calls,errors,external,_=v12_page;enter_export(page,wf);open_review(page);prepare_review(page);page.locator('#appV12Authority').check()
    pending=[];downloads=[];page.on('download',lambda value:downloads.append(value))
    page.route('**/export-app-v12/package',lambda route:pending.append(route))
    page.locator('#appV12Zip').click();pending_request(page,pending)
    if action=='close':page.locator('#appV12Close').click()
    elif action=='logout':
        page.on('dialog',lambda dialog:dialog.accept());page.evaluate('logoutAdmin()')
    else:page.evaluate('()=>{token="rotated-session";updateUserUI(currentUser,true);}')
    pending[0].fulfill(status=200,content_type='application/zip',body=b'late package')
    page.wait_for_timeout(100)
    assert not downloads and page.evaluate('v12ExportUrl==="" && v12ExportPlan===null')
    assert not calls and not errors and not external


def test_old_server_marker_keeps_legacy_export_but_never_calls_v12(v12_page):
    page,_,wf,_,calls,errors,external,requests=v12_page
    page.route('**/export-app/options',lambda route:route.fulfill(status=200,content_type='application/json',body='{"fields":[],"deployments":[]}'))
    enter_export(page,wf);expect(page.locator('#appV12Open')).to_be_disabled();expect(page.locator('#btnDownloadStandaloneApp')).to_be_enabled()
    page.evaluate('openV12Export()')
    assert not any('export-app-v12' in path for _,path,_,_ in requests)
    assert not calls and not errors and not external


def test_generated_sdk_rejects_missing_consent_foreign_reviews_and_dynamic_input_before_start(v12_page):
    page,rt,wf,service,calls,errors,external,requests=v12_page;open_package(page,package_for(rt,wf,service))
    result=page.evaluate('''async id=>{
      const client=AgentConciergeWorkflow.createClient(),review=await client.prepare();let refused=0;
      for(const options of [{},{preparation:review,shareAuthority:true},{preparation:{preview:review.preview},shareAuthority:true,liveAuthority:true},{preparation:review,shareAuthority:true,liveAuthority:true,input:{query:'injected'}}]){
        try{await client.run(id,options);}catch(_){refused++;}
      }
      return {refused,serialized:JSON.stringify(review),frozen:Object.isFrozen(review.preview.recipients[0].input)};
    }''',wf['id'])
    assert result['refused']==4 and result['frozen']
    assert 'signature' not in result['serialized'] and 'grant_id' not in result['serialized']
    assert not any(path.endswith('/runs') for _,path,_,_ in requests) and not calls
    assert not errors and not external


@pytest.mark.parametrize('status',[429,503])
def test_generated_start_is_never_retried_and_uncertain_start_does_not_unlock_run(v12_page,status):
    page,rt,wf,service,calls,errors,external,requests=v12_page;open_package(page,package_for(rt,wf,service));starts=[]
    page.route('https://agentconcierge.biz/api/workflow-apps-v12/*/runs',lambda route:(starts.append(1),route.fulfill(status=status,content_type='application/json',body='{"error":"private synthetic diagnostic"}')))
    page.locator('#prepareAppBtn').click();expect(page.locator('#appStatus')).to_contain_text('Review ready')
    page.locator('#shareAppAuthority').check();page.locator('#liveAppAuthority').check();page.locator('#runAppBtn').click()
    expect(page.locator('#appStatus')).not_to_contain_text('Starting one authorized')
    assert len(starts)==1 and 'private synthetic diagnostic' not in page.locator('body').text_content()
    expect(page.locator('#runAppBtn')).to_be_disabled()
    if status==503:expect(page.locator('#prepareAppBtn')).to_be_disabled()
    assert not calls and not errors and not external


def test_generated_reload_does_not_prepare_or_execute_and_forgets_authorities(v12_page):
    page,rt,wf,service,calls,errors,external,requests=v12_page;open_package(page,package_for(rt,wf,service))
    page.locator('#prepareAppBtn').click();expect(page.locator('#appStatus')).to_contain_text('Review ready');page.locator('#shareAppAuthority').check()
    count=len(requests);page.reload();expect(page.locator('#appStatus')).to_have_text('Ready')
    expect(page.locator('#runAppBtn')).to_be_disabled();expect(page.locator('#shareAppAuthority')).not_to_be_checked()
    assert not [row for row in requests[count:] if row[0]=='POST'] and not calls
    assert not errors and not external


def test_native_review_can_revoke_current_deployment_revision_after_editing_fields(v12_page):
    page,rt,wf,service,calls,errors,external,_=v12_page
    issued=service.export_admin(wf['id'],export_request(service,wf),1)['deployment']
    enter_export(page,wf);open_review(page)
    page.locator('#appV12Deployments').get_by_role('button',name='Revoke deployment',exact=True).click()
    expect(page.locator('#appV12Status')).to_contain_text('Deployment revoked')
    expect(page.locator('#appV12Deployments')).to_contain_text('Revoked')
    assert rt.store.query('SELECT active FROM workflow_deployment_grants WHERE app_id=?',(issued['app_id'],))[0]['active']==0
    assert not calls and not errors and not external


def test_generated_sdk_retries_only_status_and_run_handle_never_serializes_a_key(v12_page):
    page,rt,wf,service,calls,errors,external,requests=v12_page;open_package(page,package_for(rt,wf,service));polls=[]
    def status(route):
        polls.append(1)
        route.fulfill(status=503 if len(polls)==1 else 200,content_type='application/json',body=json.dumps({'status':'succeeded','node_results':[]}),headers={'Access-Control-Allow-Origin':'*','Retry-After':'0'})
    page.route('https://agentconcierge.biz/api/workflow-apps-v12/*/runs/*',status)
    result=page.evaluate('''async id=>{
      const client=AgentConciergeWorkflow.createClient(),review=await client.prepare();
      const handle=await client.run(id,{preparation:review,shareAuthority:true,liveAuthority:true});let retries=0;
      const result=await client.wait(handle,{intervalMs:300,timeoutMs:5000,onRetry:()=>retries++});
      let refused=false;try{await client.run(id,{preparation:review,shareAuthority:true,liveAuthority:true});}catch(_){refused=true;}
      return {handle:JSON.parse(JSON.stringify(handle)),status:result.status,retries,refused};
    }''',wf['id'])
    assert result['status']=='succeeded' and result['retries']==1 and result['refused'] and len(polls)==2
    assert set(result['handle'])=={'runId','status'}
    wait(rt,{'run_id':result['handle']['runId']})
    assert len(calls)==1 and len([path for method,path,_,_ in requests if method=='POST' and path.endswith('/runs')])==1
    assert not errors and not external


def test_generated_page_close_clears_review_and_never_reuses_checked_authorities(v12_page):
    page,rt,wf,service,calls,errors,external,requests=v12_page;open_package(page,package_for(rt,wf,service))
    page.locator('#prepareAppBtn').click();expect(page.locator('#appStatus')).to_contain_text('Review ready');page.locator('#shareAppAuthority').check()
    count=len(requests);page.evaluate('window.dispatchEvent(new Event("pagehide"))')
    expect(page.locator('#appStatus')).to_have_text('Local review cleared.')
    expect(page.locator('#prepareAppBtn')).to_be_enabled();expect(page.locator('#runAppBtn')).to_be_disabled()
    expect(page.locator('#shareAppAuthority')).not_to_be_checked();expect(page.locator('#liveAppAuthority')).not_to_be_checked()
    assert page.locator('#inputReview').text_content()=='' and not requests[count:] and not calls
    assert not errors and not external


def test_generated_stop_requests_once_and_terminal_status_requires_fresh_review(v12_page):
    page,rt,wf,service,calls,errors,external,requests=v12_page;open_package(page,package_for(rt,wf,service));terminal=[False];cancels=[]
    def status(route):route.fulfill(status=200,content_type='application/json',body=json.dumps({'status':'cancelled' if terminal[0] else 'running','node_results':[]}),headers={'Access-Control-Allow-Origin':'*'})
    page.route('https://agentconcierge.biz/api/workflow-apps-v12/*/runs/*',status)
    def stop(route):cancels.append(1);route.fulfill(status=200,content_type='application/json',body='{"ok":true,"cancel_requested":true}',headers={'Access-Control-Allow-Origin':'*'})
    page.route('https://agentconcierge.biz/api/workflow-apps-v12/*/runs/*/cancel',stop)
    page.locator('#prepareAppBtn').click();expect(page.locator('#appStatus')).to_contain_text('Review ready')
    page.locator('#shareAppAuthority').check();page.locator('#liveAppAuthority').check();page.locator('#runAppBtn').click()
    expect(page.locator('#appStatus')).to_have_text('Workflow: running')
    page.evaluate('()=>{document.querySelector("#cancelAppBtn").click();document.querySelector("#cancelAppBtn").click();}')
    expect(page.locator('#appStatus')).to_contain_text('Cancellation requested')
    assert len(cancels)==1;expect(page.locator('#runAppBtn')).to_be_disabled();expect(page.locator('#prepareAppBtn')).to_be_disabled()
    terminal[0]=True;page.get_by_role('button',name='Check final status',exact=True).click()
    expect(page.locator('#appStatus')).to_have_text('Workflow: cancelled');expect(page.locator('#prepareAppBtn')).to_be_enabled();expect(page.locator('#runAppBtn')).to_be_disabled()
    starts=[row for row in requests if row[0]=='POST' and row[1].endswith('/runs')];assert len(starts)==1
    actual=rt.history(wf['id'])[0]['id'];wait(rt,{'run_id':actual})
    assert len(calls)==1 and not errors and not external


def test_execute_400_after_real_admission_is_uncertain_and_blocks_new_starts(v12_page):
    page,rt,wf,service,calls,errors,external,requests=v12_page;open_package(page,package_for(rt,wf,service));jobs=[]
    def admitted_then_error(route):
        request=route.request;app_id=urlsplit(request.url).path.split('/')[3]
        app=service.legacy.authorize(app_id,request.header_value('X-Publish-Key'),ORIGIN)
        jobs.append(service.execute(app,request.post_data_json,ORIGIN))
        route.fulfill(status=400,content_type='application/json',body='{"error":"synthetic private capability mapping failure"}',headers={'Access-Control-Allow-Origin':'*'})
    page.route('https://agentconcierge.biz/api/workflow-apps-v12/*/runs',admitted_then_error)
    page.locator('#prepareAppBtn').click();expect(page.locator('#appStatus')).to_contain_text('Review ready')
    page.locator('#shareAppAuthority').check();page.locator('#liveAppAuthority').check();page.locator('#runAppBtn').click()
    expect(page.locator('#appNotice')).to_contain_text('start outcome could not be confirmed')
    expect(page.locator('#prepareAppBtn')).to_be_disabled();expect(page.locator('#runAppBtn')).to_be_disabled()
    assert len(jobs)==1 and wait(rt,jobs[0])['status']=='succeeded' and len(calls)==1
    assert 'synthetic private' not in page.locator('body').text_content()
    assert not errors and not external


def test_generated_contract_renderer_omits_wrappers_and_never_executes_provider_markup(v12_page):
    page,rt,wf,service,calls,errors,external,_=v12_page;open_package(page,package_for(rt,wf,service))
    hostile='<img src="https://evil.example/pixel" onerror="window.v12Injected=true">'
    def status(route):
        route.fulfill(status=200,content_type='application/json',headers={'Access-Control-Allow-Origin':'*'},body=json.dumps({
            'status':'succeeded','node_results':[{'node_id':'start','type':'trigger','name':'Manual search','status':'succeeded','output':{'trigger':'manual'}},
            {'node_id':'search-1','type':'agent','name':'private-provider-id-never-shown','status':'succeeded','output':{'content':[],'structuredContent':{
                'items':[{'title':hostile,'excerpt':'A recorded source excerpt','version':'v1','retrieved_at':'2026-10-18T00:00:00Z','url':'https://sources.example/public'}],'partial':False}}}]}))
    page.route('https://agentconcierge.biz/api/workflow-apps-v12/*/runs/*',status)
    page.locator('#prepareAppBtn').click();expect(page.locator('#appStatus')).to_contain_text('Review ready')
    page.locator('#shareAppAuthority').check();page.locator('#liveAppAuthority').check();page.locator('#runAppBtn').click()
    expect(page.locator('#appStatus')).to_have_text('Workflow: succeeded')
    expect(page.locator('#stepsContainer')).to_contain_text(hostile)
    expect(page.locator('#stepsContainer')).to_contain_text('A recorded source excerpt')
    rendered=page.locator('#stepsContainer').text_content()
    assert 'structuredContent' not in rendered and 'Manual search' not in rendered and '"trigger"' not in rendered
    assert 'private-provider-id-never-shown' not in rendered
    assert page.locator('#stepsContainer img').count()==0 and page.evaluate('window.v12Injected===undefined')
    link=page.locator('#stepsContainer a');expect(link).to_have_attribute('rel','noopener noreferrer');expect(link).to_have_attribute('href','https://sources.example/public')
    wait(rt,{'run_id':rt.history(wf['id'])[0]['id']})
    assert len(calls)==1 and not errors and not external
