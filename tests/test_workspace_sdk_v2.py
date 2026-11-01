"""SDK 2 packages and BFF use isolated customer rows and synthetic MCP only."""
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qsl,urlsplit
from zipfile import ZipFile

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
from playwright.sync_api import expect
import pytest

from agent_market.workspace_release_service import build_package,router_for
from agent_market.workspace_sdk_bff import create_app
from tests.test_workspace_release_v2 import release_world,deployment,ORIGIN
from tests.test_workspace_execution_api import private_api
from tests.test_front_workflow_browser import browser

REPORT=Path('reports/advancement-completion-2026-10-18')

@pytest.fixture
def sdk_world(release_world,tmp_path):
    x=release_world;grant=deployment(x);config=x.releases.package_config(*x.args,grant['app_id'],x.actor)
    data,name=build_package(config)
    with ZipFile(BytesIO(data)) as archive:archive.extractall(tmp_path)
    gateway_app=FastAPI();gateway_app.include_router(router_for(x.releases,x.lifecycle,admin=False))
    from agent_market.customer_identity_service import router_for as customer_router
    gateway_app.include_router(customer_router(x.w.store,b'synthetic-sdk-identity-key-long-32bytes',identity=x.identity,admin=False))
    gateway=TestClient(gateway_app,base_url='https://agentconcierge.biz',raise_server_exceptions=False)
    def forward(request):
        result=gateway.request(request.method,request.url.path+('?' +request.url.query.decode() if request.url.query else ''),headers=dict(request.headers),content=request.content)
        return httpx.Response(result.status_code,headers={k:v for k,v in result.headers.items() if k not in ('content-length','content-encoding','transfer-encoding')},content=result.content)
    transport=httpx.Client(transport=httpx.MockTransport(forward));bff=TestClient(create_app(config,app_origin=ORIGIN,http=transport,root=tmp_path),base_url=ORIGIN,raise_server_exceptions=False)
    yield SimpleNamespace(x=x,grant=grant,config=config,zip=data,name=name,root=tmp_path,gateway=gateway,bff=bff)
    bff.close();transport.close();gateway.close()


def sign_in(s):
    started=s.bff.post('/bff/login',json={},headers={'Origin':ORIGIN});assert started.status_code==200,started.text
    url=started.json()['authorization_url'];params=dict(parse_qsl(urlsplit(url).query))
    header={'Origin':'https://agentconcierge.biz','X-Customer-CSRF':s.x.identity.csrf(s.x.raw_cookie),'Cookie':'__Host-ac_customer_session='+s.x.raw_cookie}
    result=s.gateway.post('/api/workspace-apps-v2/'+s.grant['app_id']+'/authorize',headers=header,json=params)
    assert result.status_code==200,result.text
    callback=s.bff.get('/bff/callback',params={'code':result.json()['code'],'state':params['state']},follow_redirects=False);assert callback.status_code==303,callback.text
    session=s.bff.get('/bff/session').json();assert session['authenticated']
    return {'Origin':ORIGIN,'X-App-CSRF':session['csrf_token']}


def test_package_has_only_static_app_identity_and_customer_bff_no_embedded_authority(sdk_world):
    s=sdk_world
    with ZipFile(BytesIO(s.zip)) as archive:
        assert len(archive.namelist())==8
        assert all('/' not in name and '..' not in name for name in archive.namelist())
        config=json.loads(archive.read('app-manifest.json'));assert set(config)=={'app_id','profile','sdk_version','allowed_origins','release_id'}
        assert all((item.external_attr>>16)&0o777==0o644 for item in archive.infolist())
        combined=b'\n'.join(archive.read(name) for name in archive.namelist()).decode()
        assert s.x.raw_cookie not in combined and s.x.w.headers['owner']['Authorization'][7:] not in combined
        assert 'private-provider.example' not in combined
    assert s.name.endswith('.zip') and s.bff.get('/').headers['content-security-policy'].find("frame-ancestors 'none'")>=0


def test_real_bff_code_exchange_cookie_prepare_run_and_retained_status(sdk_world):
    s=sdk_world;headers=sign_in(s);session=s.bff.get('/bff/session')
    assert 'access_token' not in session.text and 'session_ref' not in session.text
    cookie=str(s.bff.cookies);assert s.x.raw_cookie not in cookie
    plan=s.bff.post('/bff/prepare',json={},headers=headers);assert plan.status_code==200,plan.text
    before=s.x.calls.count('tools/call')
    result=s.bff.post('/bff/runs',headers=headers,json={'ticket_id':plan.json()['ticket_id'],'authorized':True,'notice':'workspace-sdk-run-v2'})
    assert result.status_code==200,result.text
    assert result.json()['run']['status']=='succeeded' and s.x.calls.count('tools/call')==before+1
    assert 'status_capability' not in result.text and 'access_token' not in result.text
    history=s.bff.get('/bff/history').json();assert history['runs'][0]['id']==result.json()['run']['id']
    detail=s.bff.post('/bff/status',headers=headers,json={'run_id':result.json()['run']['id']});assert detail.status_code==200 and detail.json()['run']['status']=='succeeded'
    assert s.x.calls.count('tools/call')==before+1


@pytest.mark.parametrize('attack',['origin','csrf','duplicate','nonfinite','compressed'])
def test_bff_rejects_cross_origin_or_malformed_requests_before_gateway_prepare(sdk_world,attack):
    s=sdk_world;headers=sign_in(s);body='{}'
    if attack=='origin':headers['Origin']='https://other.example'
    if attack=='csrf':headers['X-App-CSRF']='invalid'
    if attack=='duplicate':body='{"x":1,"x":2}'
    if attack=='nonfinite':body='{"x":1e999}'
    if attack=='compressed':headers['Content-Encoding']='gzip'
    headers['Content-Type']='application/json';before=s.x.calls.count('tools/call')
    response=s.bff.post('/bff/prepare',headers=headers,content=body);assert response.status_code in (400,403)
    assert s.x.calls.count('tools/call')==before


def test_bff_callback_duplicate_state_never_exchanges_customer_authority(sdk_world):
    s=sdk_world;s.bff.post('/bff/login',headers={'Origin':ORIGIN},json={})
    response=s.bff.get('/bff/callback?code=x&state=y&state=z');assert response.status_code==403
    assert s.bff.get('/bff/session').json()['authenticated'] is False


def test_sdk_app_actual_customer_authorization_review_and_single_run_in_chromium(sdk_world,browser):
    s=sdk_world;context=browser.new_context();context.add_cookies([{'name':'__Host-ac_customer_session','value':s.x.raw_cookie,'domain':'agentconcierge.biz','path':'/','secure':True,'httpOnly':True,'sameSite':'Lax'}]);page=context.new_page();errors=[];external=[]
    def serve(route):
        request=route.request;url=urlsplit(request.url)
        client=s.bff if url.hostname=='customer.example' else s.gateway if url.hostname=='agentconcierge.biz' else None
        if client is None:external.append(request.url);return route.abort()
        response=client.request(request.method,url.path+('?' +url.query if url.query else ''),headers=request.all_headers(),content=request.post_data,follow_redirects=False)
        headers={k:v for k,v in response.headers.items() if k not in ('content-length','content-encoding','transfer-encoding')}
        if response.headers.get_list('set-cookie'):headers['set-cookie']='\n'.join(response.headers.get_list('set-cookie'))
        if url.path=='/bff/callback':
            # Redirect chains bypass further Playwright routing. HTTP tests prove the303;
            # this bridge applies its native cookies and follows Location as a fresh route.
            assert response.status_code==303 and headers.pop('location')=='/'
            headers['content-type']='text/html; charset=utf-8'
            route.fulfill(status=200,headers=headers,body='<p>Verified callback bridge</p>')
        else:route.fulfill(status=response.status_code,headers=headers,body=response.content)
    context.route('**/*',serve);page.on('pageerror',lambda error:errors.append(str(error)));page.goto(ORIGIN)
    expect(page.locator('#status')).to_contain_text('Sign in as a customer')
    page.locator('#login').click();expect(page.locator('h1')).to_have_text('Authorize a private workspace app');page.locator('#check').click();expect(page.locator('#authorize')).to_be_enabled()
    with page.expect_response('**/bff/callback?*'):page.locator('#authorize').click()
    expect(page.locator('p')).to_have_text('Verified callback bridge')
    page.goto(ORIGIN)
    expect(page.locator('#status')).to_contain_text('Customer app session confirmed');before=s.x.calls.count('tools/call');page.locator('#prepare').click();expect(page.locator('#preview')).to_contain_text('Synthetic semiconductor research');expect(page.locator('#authority')).not_to_be_checked();expect(page.locator('#run')).to_be_disabled();assert s.x.calls.count('tools/call')==before
    page.locator('#authority').check();page.locator('#run').click();expect(page.locator('#status')).to_have_text('Task completed.');expect(page.locator('#output')).to_contain_text('Private research result <untrusted>');assert s.x.calls.count('tools/call')==before+1
    expect(page.locator('#authority')).not_to_be_checked();expect(page.locator('#run')).to_be_disabled();assert page.locator('#output img,#output a').count()==0
    assert not page.evaluate('Object.keys(localStorage).length+Object.keys(sessionStorage).length') and not errors and not external
    REPORT.mkdir(parents=True,exist_ok=True);page.set_viewport_size({'width':1100,'height':1000});page.screenshot(path=str(REPORT/'sdk2-customer-app.png'),full_page=True)
    context.close()


def test_owner_native_management_grants_and_download_remain_separate_from_customer_login(sdk_world,browser):
    s=sdk_world;w=s.x.w;context=browser.new_context(accept_downloads=True);context.add_init_script('sessionStorage.setItem("adminToken",'+json.dumps(w.headers['owner']['Authorization'][7:])+');');page=context.new_page();errors=[]
    def serve(route):
        request=route.request;url=urlsplit(request.url)
        if url.hostname!='admin.test':return route.abort()
        response=w.client.request(request.method,url.path,headers=request.headers,content=request.post_data)
        headers={k:v for k,v in response.headers.items() if k not in ('content-length','content-encoding','transfer-encoding')}
        if response.headers.get_list('set-cookie'):headers['set-cookie']='\n'.join(response.headers.get_list('set-cookie'))
        route.fulfill(status=response.status_code,headers=headers,body=response.content)
    context.route('**/*',serve);page.on('pageerror',lambda value:errors.append(str(value)));page.goto('https://admin.test/admin/ui#workspaces')
    expect(page.locator('#workspaceSelect')).to_be_enabled();page.locator('#workspaceSelect').select_option(w.ws['id']);page.locator('#workspaceDraftList').get_by_role('button',name='저장본 보기').click();page.locator('#workspaceSnapshotList').get_by_role('button',name='저장본 열기').click()
    page.locator('#workspaceReleaseMount').get_by_role('button',name='Manage private releases and lifecycle').click();expect(page.locator('#workspaceReleaseDialog')).to_be_visible();expect(page.locator('#workspaceReleaseStatus')).to_contain_text('Current owner controls loaded')
    expect(page.locator('#workspaceDeploymentAuthority')).not_to_be_checked();expect(page.locator('#workspaceReleaseDialog').get_by_role('button',name='Issue deployment grant')).to_be_disabled()
    page.locator('#workspaceReleaseExactdeploymentorigins').fill(ORIGIN);page.locator('#workspaceDeploymentAuthority').check();page.locator('#workspaceReleaseDialog').get_by_role('button',name='Issue deployment grant').click();expect(page.locator('#workspaceReleaseStatus')).to_contain_text('Deployment issued')
    expect(page.locator('#workspaceDeploymentAuthority')).not_to_be_checked()
    with page.expect_download() as pending:page.locator('#workspaceDeploymentList').get_by_role('button',name='Download SDK 2 ZIP').last.click()
    with ZipFile(pending.value.path()) as archive:assert 'bff.py' in archive.namelist()
    REPORT.mkdir(parents=True,exist_ok=True);page.set_viewport_size({'width':1280,'height':1100});page.screenshot(path=str(REPORT/'sdk2-owner-management.png'))
    assert not errors;context.close()


def test_bff_callback_removes_secrets_from_uvicorn_access_log_path_even_when_invalid(sdk_world):
    from uvicorn.protocols.utils import get_path_with_query_string
    from starlette.requests import Request
    s=sdk_world
    callback=next(route.endpoint for route in s.bff.app.routes if getattr(route,'path','')=='/bff/callback')
    for query in (b'code=synthetic-code&state=synthetic-state',b'code=first&code=second&state=synthetic-state',b'invalid=synthetic-secret'):
        scope={'type':'http','method':'GET','path':'/bff/callback','raw_path':b'/bff/callback','query_string':query,'headers':[], 'scheme':'https','server':('customer.example',443)}
        response=callback(Request(scope))
        assert response.status_code==403
        assert scope['query_string']==b'' and get_path_with_query_string(scope)=='/bff/callback'
        assert 'synthetic-' not in response.body.decode()
