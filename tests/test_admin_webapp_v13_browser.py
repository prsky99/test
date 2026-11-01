"""Connected SDK 1.3 browser/package checks use isolated grants and MCP agents."""
from io import BytesIO
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from zipfile import ZipFile

from playwright.sync_api import expect
import pytest
from tests.browser_wait import pending_request

from agent_market.admin_workflow_webapp_v13 import build_admin_package_v13
from agent_market.workflow_connection_deployment import GRANT_NOTICE
from tests.test_admin_security_browser import browser
from tests.test_workflow_fallback import routing
from tests.test_workflow_typed_flow import typed_routing
from tests.test_workflow_publication_browser import publication_page, released, enter_admin
from tests.test_workflow_runtime import wait

from tests.conftest import staff_headers  # noqa: E402
pytestmark = pytest.mark.usefixtures('rotated_bootstrap_admin')

ORIGIN='https://customer.example'
REPORT=Path('reports/advancement-connected-sdk-2026-10-18')


def enter_sdk(page,identity):
    enter_admin(page)
    button=page.locator('#publicationReleases').get_by_role('button',name='Review SDK 1.3 deployment')
    expect(button).to_be_enabled();button.click();expect(page.locator('#connectionSdkDialog')).to_be_visible()
    expect(page.locator('#connectionSdkPrepare')).to_be_enabled();page.locator('#connectionSdkOrigins').fill(ORIGIN)


def prepare_sdk(page):
    page.locator('#connectionSdkPrepare').click();expect(page.locator('#connectionSdkStatus')).to_contain_text('Deployment review ready')


def bundle(rt,identity,single_html=False):
    prepared=rt.connection_deployments.prepare_admin(identity,{'allowed_origins':[ORIGIN],'minute_limit':10,'day_limit':500,'ttl_seconds':3600},1)
    result=rt.connection_deployments.issue(identity,{k:prepared[k] for k in ('proposal','signature')}|{'deployment_authority':True,'deployment_notice':GRANT_NOTICE},1)
    data,name=build_admin_package_v13(result['config'],result['deployment'],single_html=single_html)
    if single_html:return {'index.html':data}
    with ZipFile(BytesIO(data)) as archive:return {name:archive.read(name) for name in archive.namelist()}


def host(page,files):
    root=ORIGIN+'/apps/connected/'
    def serve(route):
        name=route.request.url.removeprefix(root) or 'index.html';content=files.get(name)
        if content is None:return route.fulfill(status=404,body='Not found')
        content_type='application/javascript' if name.endswith('.js') else 'text/css' if name.endswith('.css') else 'text/html'
        route.fulfill(status=200,body=content,content_type=content_type)
    page.context.route(ORIGIN+'/**',serve);page.goto(root)


def prepare_app(page):
    page.locator('#prepareAppBtn').click();expect(page.locator('#appStatus')).to_contain_text('Review ready')


def run_app(page):
    page.locator('#shareAppAuthority').check();page.locator('#liveAppAuthority').check();page.locator('#runAppBtn').click()


def test_native_review_downloaded_zip_and_selfhosted_run_use_separate_authorities(publication_page):
    page,rt,web,public,_,errors,external,requests=publication_page;identity=released(web);before=list(rt.typed_test_controls['seen'])
    enter_sdk(page,identity);prepare_sdk(page)
    expect(page.locator('#connectionSdkPreview')).to_contain_text('future actual text is not known')
    expect(page.locator('#connectionSdkAuthority')).not_to_be_checked();expect(page.locator('#connectionSdkZip')).to_be_disabled()
    page.evaluate('downloadConnectionSdk("package")');assert not rt.store.query('SELECT id FROM workflow_connection_deployments')
    REPORT.mkdir(parents=True,exist_ok=True);page.set_viewport_size({'width':1280,'height':1100});page.screenshot(path=str(REPORT/'sdk13-admin-review.png'))
    page.locator('#connectionSdkAuthority').check()
    with page.expect_download() as event:
        with page.expect_response('**/export-app-v13/package') as response:page.locator('#connectionSdkZip').click()
        assert response.value.status==200,response.value.text()
        expect(page.locator('#connectionSdkStatus')).to_contain_text('exported locally')
    data=Path(event.value.path()).read_bytes()
    with ZipFile(BytesIO(data)) as archive:
        files={name:archive.read(name) for name in archive.namelist()};manifest=json.loads(files['app-manifest.json'])
        assert len(files)==6 and manifest['sdk_version']=='1.3.0' and manifest['profile']=='connected-informational-deployment-v1'
        assert all((entry.external_attr>>16)&0o777==0o644 for entry in archive.infolist())
    assert rt.typed_test_controls['seen']==before
    assert 'grant_id' not in b'\n'.join(files.values()).decode() and 'primary.example' not in b'\n'.join(files.values()).decode()
    page.wait_for_function('connectionSdkUrl===""');expect(page.locator('#connectionSdkAuthority')).not_to_be_checked()
    host(page,files);expect(page.locator('#runAppBtn')).to_be_disabled();expect(page.locator('#resumeAppBtn')).to_be_hidden()
    assert rt.typed_test_controls['seen']==before
    prepare_app(page);expect(page.locator('#inputReview')).to_contain_text('actual text is not known before the news call')
    expect(page.locator('#shareAppAuthority')).not_to_be_checked();expect(page.locator('#liveAppAuthority')).not_to_be_checked()
    page.locator('#shareAppAuthority').check();expect(page.locator('#runAppBtn')).to_be_disabled()
    page.locator('#liveAppAuthority').check();page.locator('#runAppBtn').click()
    expect(page.locator('#appStatus')).to_have_text('Connection: succeeded',timeout=15000)
    expect(page.locator('#stepsContainer')).to_contain_text('Current documentation')
    assert len(rt.typed_test_controls['seen'])==len(before)+2
    assert rt.typed_test_controls['seen'][-1]['query']==rt.typed_test_controls['title']
    starts=[(json.loads(body),headers) for method,path,body,headers in requests if method=='POST' and path.startswith('/api/workflow-connection-apps-v13/') and path.endswith('/runs')]
    assert len(starts)==1 and set(starts[0][0])=={'proposal','signature','sharing_authority','sharing_notice','run_authority','run_notice'}
    assert starts[0][1]['origin']==ORIGIN and starts[0][1]['x-publish-key'].startswith('cpk_')
    # Browser route fulfillment does not expose an OPTIONS observation here.
    app_id=manifest['app_id'];preflight=public.options('/api/workflow-connection-apps-v13/'+app_id+'/prepare',headers={'Origin':ORIGIN,'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'content-type,x-publish-key'})
    assert preflight.status_code==204 and preflight.headers['access-control-allow-origin']=='*'
    assert 'X-Publish-Key' in preflight.headers['access-control-allow-headers']
    expect(page.locator('#runAppBtn')).to_be_disabled();expect(page.locator('#shareAppAuthority')).not_to_be_checked();expect(page.locator('#resumeAppBtn')).to_be_hidden()
    assert not page.evaluate('Object.keys(localStorage).concat(Object.keys(sessionStorage)).length')
    for private in ('structuredContent','private_debug','resource_id','primary.example','alternate.example','third.example'):assert private not in page.locator('#stepsContainer').inner_text()
    page.screenshot(path=str(REPORT/'sdk13-generated-app.png'),full_page=True);assert not errors and not external


@pytest.mark.parametrize('action',['edit','close','escape','role','token'])
def test_admin_settings_and_session_changes_clear_deployment_plan_and_acknowledgement(publication_page,action):
    page,_,web,_,_,errors,external,_=publication_page;identity=released(web);enter_sdk(page,identity);prepare_sdk(page);page.locator('#connectionSdkAuthority').check()
    if action=='edit':page.locator('#connectionSdkOrigins').fill('https://different.example')
    elif action=='close':page.locator('#connectionSdkClose').click()
    elif action=='escape':page.keyboard.press('Escape')
    elif action=='role':page.evaluate('()=>{currentUser.role="admin";updateUserUI(currentUser,false);}')
    else:page.evaluate('()=>{token="rotated-session";updateUserUI(currentUser,false);}')
    assert page.evaluate('connectionSdkPlan===null')
    expect(page.locator('#connectionSdkAuthority')).not_to_be_checked();expect(page.locator('#connectionSdkZip')).to_be_disabled()
    assert not errors and not external


@pytest.mark.parametrize('action',['close','logout','token'])
def test_late_export_cannot_download_after_dialog_or_session_changes(publication_page,action):
    page,_,web,_,_,errors,external,_=publication_page;identity=released(web);enter_sdk(page,identity);prepare_sdk(page);page.locator('#connectionSdkAuthority').check();pending=[];downloads=[]
    page.route('**/export-app-v13/package',lambda route:pending.append(route));page.on('download',lambda value:downloads.append(value))
    page.locator('#connectionSdkZip').click();pending_request(page,pending)
    if action=='close':page.locator('#connectionSdkClose').click()
    elif action=='logout':page.on('dialog',lambda dialog:dialog.accept());page.evaluate('document.getElementById("logoutBtn").click()')
    else:page.evaluate('()=>{token="rotated-session";updateUserUI(currentUser,false);}')
    pending[0].fulfill(status=200,content_type='application/zip',body=b'late reviewed package')
    page.wait_for_function('()=>connectionSdkBusy===false');assert not downloads and page.evaluate('connectionSdkUrl==="" && connectionSdkPlan===null')
    assert not errors and not external


def test_old_backend_marker_disables_connected_export_without_breaking_publication(publication_page):
    page,_,web,_,admin,errors,external,requests=publication_page;released(web);staff=staff_headers(admin)
    def legacy(route):
        response=admin.get(urlsplit(route.request.url).path+('?' + urlsplit(route.request.url).query if urlsplit(route.request.url).query else ''),headers=staff)
        value=response.json();value.pop('connected_sdk_profile',None);route.fulfill(status=200,content_type='application/json',body=json.dumps(value))
    page.route('**/admin/api/workflows?limit=100',legacy);page.route('**/admin/api/workflow-publications/options',legacy)
    enter_admin(page);expect(page.locator('#publicationPrepare')).to_be_enabled()
    expect(page.locator('#publicationReleases').get_by_role('button',name='Review SDK 1.3 deployment')).to_be_disabled()
    assert not [path for _,path,_,_ in requests if '/export-app-v13/' in path] and not errors and not external


def test_connected_deployment_revoke_uses_current_revision_after_settings_edit(publication_page):
    page,rt,web,_,_,errors,external,requests=publication_page;identity=released(web);bundle(web,identity)
    enter_sdk(page,identity);expect(page.locator('#connectionSdkDeployments')).to_contain_text('Active')
    page.locator('#connectionSdkOrigins').fill('https://different.example');page.locator('#connectionSdkDeployments button').click()
    expect(page.locator('#connectionSdkStatus')).to_contain_text('deployment revoked')
    rows=rt.store.query('SELECT active,revision FROM workflow_connection_deployments');assert len(rows)==1 and rows[0]['active']==0 and rows[0]['revision']==2
    assert [json.loads(body) for method,path,body,_ in requests if method=='POST' and path.endswith('/revoke')]==[{'revision':1}]
    assert not errors and not external


def test_ambiguous_export_refreshes_history_without_issuing_another_grant(publication_page):
    page,rt,web,_,admin,errors,external,requests=publication_page;identity=released(web);enter_sdk(page,identity);prepare_sdk(page);submitted=[];downloads=[]
    def interrupted(route):
        request=route.request;response=admin.post(urlsplit(request.url).path,content=request.post_data,headers=request.headers)
        assert response.status_code==200,response.text;submitted.append(request.post_data)
        route.fulfill(status=400,content_type='application/json',body='{"error":"private diagnostic"}')
    page.route('**/export-app-v13/package',interrupted);page.on('download',lambda value:downloads.append(value))
    page.locator('#connectionSdkAuthority').check();page.locator('#connectionSdkZip').click()
    expect(page.locator('#connectionSdkStatus')).to_contain_text('export response is unavailable')
    assert len(submitted)==1 and len(rt.store.query('SELECT id FROM workflow_connection_deployments'))==1 and not downloads
    expect(page.locator('#connectionSdkDeployments')).to_contain_text('No connected')
    page.locator('#connectionSdkRefresh').click();expect(page.locator('#connectionSdkStatus')).to_contain_text('history refreshed without issuing a grant')
    expect(page.locator('#connectionSdkDeployments')).to_contain_text('Active')
    page.locator('#connectionSdkDeployments button').click();expect(page.locator('#connectionSdkStatus')).to_contain_text('deployment revoked')
    assert len(submitted)==1 and rt.store.query('SELECT active FROM workflow_connection_deployments')[0][0]==0
    assert 'private diagnostic' not in page.locator('#connectionSdkDialog').inner_text() and not errors and not external


def test_editing_settings_during_prepare_discards_late_plan_and_unblocks_inputs(publication_page):
    page,rt,web,_,_,errors,external,_=publication_page;identity=released(web);enter_sdk(page,identity);pending=[]
    page.route('**/export-app-v13/prepare',lambda route:pending.append(route));page.locator('#connectionSdkPrepare').click();pending_request(page,pending)
    page.locator('#connectionSdkOrigins').fill('https://changed.example')
    pending[0].fulfill(status=200,content_type='application/json',body='{"ok":true,"profile":"connected-informational-deployment-v1","proposal":{},"signature":"late","preview":{}}')
    expect(page.locator('#connectionSdkPrepare')).to_be_enabled();expect(page.locator('#connectionSdkOrigins')).to_be_enabled();expect(page.locator('#connectionSdkRefresh')).to_be_enabled()
    assert page.evaluate('connectionSdkPlan===null && connectionSdkBusy===false')
    expect(page.locator('#connectionSdkAuthority')).not_to_be_checked();expect(page.locator('#connectionSdkZip')).to_be_disabled()
    assert not rt.store.query('SELECT id FROM workflow_connection_deployments') and not errors and not external


def test_short_signed_review_expiry_blocks_export_while_grant_lifetime_is_still_future(publication_page):
    page,rt,web,_,_,errors,external,requests=publication_page;identity=released(web);enter_sdk(page,identity);prepare_sdk(page)
    assert page.evaluate('connectionSdkPlan.preview.expires>connectionSdkPlan.proposal.expires')
    page.evaluate('()=>{const expired=(connectionSdkPlan.proposal.expires+1)*1000;Date.now=()=>expired;}')
    page.locator('#connectionSdkAuthority').check();page.locator('#connectionSdkZip').click()
    expect(page.locator('#connectionSdkStatus')).to_contain_text('signed review expired')
    assert not rt.store.query('SELECT id FROM workflow_connection_deployments')
    assert not [path for method,path,_,_ in requests if method=='POST' and path.endswith('/package')]
    expect(page.locator('#connectionSdkAuthority')).not_to_be_checked();assert not errors and not external


def test_sdk_rejects_foreign_or_consumed_review_and_dynamic_input_without_post(publication_page):
    page,_,web,_,_,errors,external,requests=publication_page;identity=released(web);host(page,bundle(web,identity))
    result=page.evaluate('''async()=>{
      const a=AgentConciergeWorkflow.createClient(),b=AgentConciergeWorkflow.createClient();const review=await a.prepare();let refused=0;
      for(const [client,args] of [[a,{preparation:review,sharingAuthority:true}],[b,{preparation:review,sharingAuthority:true,runAuthority:true}],[a,{preparation:review,sharingAuthority:true,runAuthority:true,input:{query:"changed"}}]]){
        try{await client.run(args);}catch(_){refused++;}
      }
      return {refused,keys:Object.keys(review),frozen:Object.isFrozen(review.preview.source.input),serialized:JSON.stringify(review)};
    }''')
    assert result['refused']==3 and result['keys']==['preview'] and result['frozen']
    assert 'signature' not in result['serialized'] and 'grant_id' not in result['serialized']
    assert not [path for method,path,_,_ in requests if method=='POST' and path.endswith('/runs')] and not errors and not external


def test_sdk_and_app_lock_after_accepted_start_returns_400(publication_page):
    page,_,web,public,_,errors,external,requests=publication_page;identity=released(web);host(page,bundle(web,identity));accepted=[]
    def interrupted(route):
        response=public.post(urlsplit(route.request.url).path,content=route.request.post_data,headers=route.request.headers);assert response.status_code==202,response.text
        accepted.append(response.json());route.fulfill(status=400,content_type='application/json',headers={'Access-Control-Allow-Origin':'*'},body='{"error":"private diagnostic"}')
    page.route('https://agentconcierge.biz/api/workflow-connection-apps-v13/*/runs',interrupted)
    prepare_app(page);run_app(page);expect(page.locator('#appStatus')).to_contain_text('could not be confirmed');expect(page.locator('#prepareAppBtn')).to_be_disabled()
    page.evaluate('document.getElementById("prepareAppBtn").click();document.getElementById("runAppBtn").click()')
    assert len(accepted)==1 and wait(web,accepted[0])['status']=='succeeded'
    assert 'private diagnostic' not in page.locator('body').inner_text() and not errors and not external


def test_unknown_agent_outcome_is_visible_and_resume_is_read_only(publication_page):
    page,rt,web,_,_,errors,external,requests=publication_page;identity=released(web);files=bundle(web,identity)
    rt.publication_browser_modes['alternate.example']='unknown';rt.publication_browser_modes['third.example']='unknown';host(page,files)
    prepare_app(page);run_app(page);expect(page.locator('#appStatus')).to_have_text('Agent outcome unknown',timeout=15000)
    expect(page.locator('#prepareAppBtn')).to_be_disabled();expect(page.locator('#runAppBtn')).to_be_disabled();expect(page.locator('#cancelAppBtn')).to_be_disabled()
    before=len([path for method,path,_,_ in requests if method=='POST'])
    with page.expect_response('**/api/workflow-connection-apps-v13/*/runs/*'):page.locator('#resumeAppBtn').click()
    expect(page.locator('#appStatus')).to_have_text('Agent outcome unknown')
    assert len([path for method,path,_,_ in requests if method=='POST'])==before and not errors and not external


def test_status_get_retries_only_and_handle_does_not_serialize_key(publication_page):
    page,_,web,public,_,errors,external,requests=publication_page;identity=released(web);host(page,bundle(web,identity));polls=[]
    def status(route):
        polls.append(route.request.url)
        if len(polls)<=2:return route.fulfill(status=503,content_type='application/json',headers={'Access-Control-Allow-Origin':'*'},body='{"error":"private"}')
        response=public.get(urlsplit(route.request.url).path,headers=route.request.headers);route.fulfill(status=response.status_code,content_type='application/json',headers={'Access-Control-Allow-Origin':'*'},body=response.content)
    page.route('https://agentconcierge.biz/api/workflow-connection-apps-v13/*/runs/*',status)
    result=page.evaluate('''async()=>{const client=AgentConciergeWorkflow.createClient(),preparation=await client.prepare();const handle=await client.run({preparation,sharingAuthority:true,runAuthority:true});const data=await client.wait(handle,{intervalMs:300});return {keys:Object.keys(handle),json:JSON.stringify(handle),status:data.status};}''')
    assert result['status']=='succeeded' and result['keys']==['runId','status'] and 'key' not in result['json'] and len(polls)==3
    assert len([path for method,path,_,_ in requests if method=='POST' and path.endswith('/runs')])==1 and not errors and not external


def test_reload_and_pagehide_clear_authority_without_starting(publication_page):
    page,_,web,_,_,errors,external,requests=publication_page;identity=released(web);host(page,bundle(web,identity));prepare_app(page)
    page.locator('#shareAppAuthority').check();page.locator('#liveAppAuthority').check();before=len(requests)
    page.reload();expect(page.locator('#runAppBtn')).to_be_disabled();expect(page.locator('#shareAppAuthority')).not_to_be_checked()
    assert not any(method=='POST' for method,_,_,_ in requests[before:])
    prepare_app(page);page.locator('#shareAppAuthority').check();page.evaluate('window.dispatchEvent(new Event("pagehide"))')
    expect(page.locator('#inputReview')).to_be_empty();expect(page.locator('#prepareAppBtn')).to_be_disabled();expect(page.locator('#shareAppAuthority')).not_to_be_checked()
    assert not page.evaluate('Object.keys(localStorage).concat(Object.keys(sessionStorage)).length') and not errors and not external


def test_stop_is_one_post_with_empty_body_and_never_starts_another_run(publication_page):
    page,_,web,public,_,errors,external,requests=publication_page;identity=released(web);host(page,bundle(web,identity));cancelled=[]
    def status(route):
        request=route.request;path=urlsplit(request.url).path
        if request.method=='POST':
            cancelled.append(json.loads(request.post_data));response=public.post(path,content=request.post_data,headers=request.headers)
        elif not cancelled:return route.fulfill(status=200,content_type='application/json',headers={'Access-Control-Allow-Origin':'*'},body='{"status":"running","node_results":[]}')
        else:response=public.get(path,headers=request.headers)
        route.fulfill(status=response.status_code,content_type='application/json',headers={'Access-Control-Allow-Origin':'*'},body=response.content)
    page.route('https://agentconcierge.biz/api/workflow-connection-apps-v13/*/runs/**',status)
    prepare_app(page);run_app(page);expect(page.locator('#cancelAppBtn')).to_be_enabled();page.locator('#cancelAppBtn').click()
    expect(page.locator('#appStatus')).to_have_text(re.compile(r'^(Connection: (succeeded|failed|cancelled)|Agent outcome unknown)$'),timeout=15000)
    assert cancelled==[{}] and len([path for method,path,_,_ in requests if method=='POST' and path.endswith('/runs')])==1
    expect(page.locator('#cancelAppBtn')).to_be_disabled();expect(page.locator('#runAppBtn')).to_be_disabled();expect(page.locator('#shareAppAuthority')).not_to_be_checked()
    assert not errors and not external


def test_result_markup_is_text_and_unknown_wrapper_fields_are_not_displayed(publication_page):
    page,_,web,_,_,errors,external,_=publication_page;identity=released(web);host(page,bundle(web,identity));hostile='<img src="https://evil.example/pixel" onerror="window.injected=true">'
    def output(route):
        route.fulfill(status=200,content_type='application/json',headers={'Access-Control-Allow-Origin':'*'},body=json.dumps({'status':'succeeded','node_results':[
            {'type':'trigger','status':'succeeded','data':{'trigger':'private trigger'}},
            {'type':'agent','status':'succeeded','name':'private provider','data':{'content':[{'text':'PRIVATE_WRAPPER'}],'structuredContent':{'partial':False,'items':[{'title':hostile,'summary':'Recorded summary','url':'https://sources.example/article'}]}}}]}))
    page.route('https://agentconcierge.biz/api/workflow-connection-apps-v13/*/runs/*',output)
    prepare_app(page);run_app(page);expect(page.locator('#stepsContainer')).to_contain_text(hostile)
    assert page.locator('#stepsContainer img').count()==0 and page.evaluate('window.injected===undefined')
    expect(page.locator('#stepsContainer a')).to_have_attribute('rel','noopener noreferrer')
    for private in ('PRIVATE_WRAPPER','private trigger','private provider','structuredContent'):assert private not in page.locator('#stepsContainer').inner_text()
    job=web.store.query("SELECT id FROM workflow_runs WHERE actor LIKE 'connection-app:%' ORDER BY created DESC LIMIT 1")[0];wait(web,{'run_id':job['id']})
    assert not errors and not external


def test_cross_origin_iframe_cannot_prepare_or_run_the_exported_app(publication_page):
    page,_,web,_,_,errors,external,requests=publication_page;identity=released(web);files=bundle(web,identity);host(page,files)
    parent='https://embedding.example/'
    page.context.route(parent,lambda route:route.fulfill(status=200,content_type='text/html',body='<iframe title="Embedded connection" src="'+ORIGIN+'/apps/connected/"></iframe>'))
    page.goto(parent);frame=page.frame_locator('iframe');expect(frame.locator('#appStatus')).to_contain_text('own browser tab')
    expect(frame.locator('#prepareAppBtn')).to_be_disabled();expect(frame.locator('#runAppBtn')).to_be_disabled()
    result=page.frames[1].evaluate('''async()=>{const client=AgentConciergeWorkflow.createClient();try{await client.prepare();return false;}catch(_){return true;}}''')
    assert result and not [path for method,path,_,_ in requests if method=='POST' and path.startswith('/api/workflow-connection-apps-v13/')]
    assert not errors and not external
