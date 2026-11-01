"""Canonical public connections in Chromium with isolated local provider fixtures."""
from tests.browser_wait import pending_request
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.testclient import TestClient
from playwright.sync_api import expect
import pytest

from agent_market.concierge.front import Front, create_front_app
from agent_market.gateway.admin_auth import init_admin_auth_db
from agent_market.gateway.dashboard import dashboard_router
from agent_market.public_workflow_connection import build_public_connection_page
from agent_market.workflow_publication import TEST_SHARE_NOTICE, TEST_RUN_NOTICE, PUBLISH_NOTICE
from tests.test_admin_security_browser import browser
from tests.test_workflow_fallback import routing
from tests.test_workflow_typed_flow import typed_routing
from tests.test_workflow_runtime import wait

import pytest  # noqa: E402
pytestmark = pytest.mark.usefixtures('rotated_bootstrap_admin')

REPORT=Path('reports/advancement-public-release-2026-10-18')


@pytest.fixture
def publication_page(browser,typed_routing,rotated_bootstrap_admin):
    rt,*_=typed_routing
    rt.publication_browser_modes=typed_routing[4]
    with rt.store._lock:init_admin_auth_db(rt.store._db)
    proxy=rt.proxy
    front=Front(rt.store,allow_private=True);front.proxy=front.workflows.proxy=proxy
    public=TestClient(create_front_app(front),base_url='https://agentconcierge.biz')
    app=FastAPI();app.include_router(dashboard_router(rt.store,rt.store._path,'publication-browser',None,front=front))
    admin=TestClient(app,base_url='https://admin.example')
    context=browser.new_context();page=context.new_page();errors=[];external=[];requests=[]
    page.on('pageerror',lambda value:errors.append(str(value)))
    def serve(route):
        request=route.request;url=urlsplit(request.url)
        client=public if url.hostname=='agentconcierge.biz' else admin if url.hostname=='admin.example' else None
        if client is None:external.append(request.url);return route.abort()
        requests.append((request.method,url.path,request.post_data,request.headers))
        response=client.request(request.method,url.path+('?' + url.query if url.query else ''),content=request.post_data,headers=request.headers)
        route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items() if k not in ('content-length','content-encoding','transfer-encoding')})
    context.route('**/*',serve)
    yield page,rt,front.workflows,public,admin,errors,external,requests
    context.close();public.close();admin.close()


def candidate(rt):
    service=rt.publication;options=service.options(1)
    return service.candidate({'source_id':options['news'][0]['id'],'target_id':options['docs'][0]['id'],
        'query':'Python news','from_utc':(datetime.now(timezone.utc)-timedelta(hours=24)).isoformat().replace('+00:00','Z'),'limit':3},1)


def completed_canonical_test(rt):
    plan=candidate(rt)
    job=rt.publication.test({k:plan[k] for k in ('proposal','signature')}|{'sharing_authority':True,'sharing_notice':TEST_SHARE_NOTICE,'run_authority':True,'run_notice':TEST_RUN_NOTICE},1)
    assert wait(rt,job)['status']=='succeeded'
    return job


def released(rt):
    job=completed_canonical_test(rt)
    review=rt.publication.publication_candidate({'run_id':job['run_id'],'ttl_seconds':3600},1)
    result=rt.publication.publish({k:review[k] for k in ('proposal','signature')}|{'publication_authority':True,'publication_notice':PUBLISH_NOTICE},1)
    return result['release_id'] if 'release_id' in result else result['release']['id'] if 'release' in result else result['id']


def enter_admin(page):
    page.goto('https://admin.example/admin/ui');page.locator('#adminLoginUsername').fill('sadmin');page.locator('#adminLoginPassword').fill('sadmin');page.locator('#adminLoginSubmitBtn').click()
    expect(page.locator('#adminLoginModal')).to_be_hidden();page.locator('[data-tab="workflows"]').click()
    page.evaluate('loadWorkflows()');expect(page.locator('#workflowPublicationOpen')).to_be_enabled()
    page.locator('#workflowPublicationOpen').click();expect(page.locator('#workflowPublicationDialog')).to_be_visible()
    expect(page.locator('#publicationPrepare')).to_be_enabled()


def prepare_admin(page):
    page.locator('#publicationQuery').fill('Python news');page.locator('#publicationPrepare').click()
    expect(page.locator('#publicationStatus')).to_contain_text('Review ready')


def prepare_public(page,identity):
    page.goto('https://agentconcierge.biz/connections/'+identity)
    expect(page.locator('#connectionPrepare')).to_be_enabled();page.locator('#connectionPrepare').click()
    expect(page.locator('#connectionStatus')).to_contain_text('Review ready')


def authorize_public(page):
    page.locator('#connectionShare').check();page.locator('#connectionLive').check();page.locator('#connectionRun').click()


def test_admin_canonical_test_publication_and_public_run_are_separately_authorized(publication_page):
    page,rt,web,_,_,errors,external,requests=publication_page;calls=rt.typed_test_controls
    enter_admin(page);prepare_admin(page)
    expect(page.locator('#publicationPreview')).to_contain_text('future actual text is not known')
    expect(page.locator('#publicationTestShare')).not_to_be_checked();expect(page.locator('#publicationTestLive')).not_to_be_checked()
    page.evaluate('runPublicationTest()');assert not calls['seen'] and not rt.store.query('SELECT id FROM workflow_publication_grants')
    page.locator('#publicationTestShare').check();expect(page.locator('#publicationTest')).to_be_disabled()
    page.locator('#publicationTestLive').check();page.locator('#publicationTest').click()
    expect(page.locator('#publicationStatus')).to_contain_text('Canonical test: succeeded',timeout=15000)
    expect(page.locator('#publicationPrepareGrant')).to_be_enabled();page.locator('#publicationPrepareGrant').click()
    expect(page.locator('#publicationStatus')).to_contain_text('Publication review ready')
    expect(page.locator('#publicationAuthority')).not_to_be_checked();expect(page.locator('#publicationPublish')).to_be_disabled()
    REPORT.mkdir(parents=True,exist_ok=True);page.set_viewport_size({'width':1280,'height':1100});page.screenshot(path=str(REPORT/'admin-publication-review.png'))
    page.locator('#publicationAuthority').check();page.locator('#publicationPublish').click()
    expect(page.locator('#publicationStatus')).to_contain_text('connection published')
    rows=rt.store.query('SELECT id FROM workflow_publication_grants');assert len(rows)==1
    identity=rows[0]['id'];assert calls['news_calls']==1 and len(calls['seen'])==2
    prepare_public(page,identity)
    expect(page.locator('#connectionResume')).to_be_hidden()
    expect(page.locator('#connectionReview')).to_contain_text('actual text is not known yet')
    expect(page.locator('#connectionShare')).not_to_be_checked();expect(page.locator('#connectionLive')).not_to_be_checked()
    page.locator('#connectionShare').check();expect(page.locator('#connectionRun')).to_be_disabled()
    page.locator('#connectionLive').check();page.locator('#connectionRun').click()
    expect(page.locator('#connectionStatus')).to_have_text('Connection: succeeded',timeout=15000)
    expect(page.locator('#connectionResults')).to_contain_text('Current documentation')
    expect(page.locator('#connectionResults')).to_contain_text('Python asynchronous task documentation')
    assert calls['news_calls']==2 and len(calls['seen'])==4
    assert not page.evaluate('Object.keys(localStorage).concat(Object.keys(sessionStorage)).length')
    rendered=page.locator('body').text_content()
    for private in ('structuredContent','workflow-public-flow','resource_id','Bearer','primary.example','alternate.example'):assert private not in rendered
    execute=[json.loads(body) for method,path,body,_ in requests if method=='POST' and path.endswith('/runs') and path.startswith('/api/workflow-connections/')]
    assert len(execute)==1 and set(execute[0])=={'proposal','signature','sharing_authority','sharing_notice','run_authority','run_notice'}
    expect(page.locator('#connectionShare')).not_to_be_checked();expect(page.locator('#connectionRun')).to_be_disabled()
    expect(page.locator('#connectionResume')).to_be_hidden()
    page.screenshot(path=str(REPORT/'public-connection.png'),full_page=True);assert not errors and not external


@pytest.mark.parametrize('change',['query','source','close','escape','role','token'])
def test_admin_review_and_authority_clear_on_context_changes(publication_page,change):
    page,_,_,_,_,errors,external,_=publication_page;enter_admin(page);prepare_admin(page)
    page.locator('#publicationTestShare').check();page.locator('#publicationTestLive').check()
    if change=='query':page.locator('#publicationQuery').fill('Different public news')
    elif change=='source':page.locator('#publicationSource').dispatch_event('change')
    elif change=='close':page.locator('#publicationClose').click()
    elif change=='escape':page.keyboard.press('Escape')
    elif change=='role':page.evaluate('()=>{currentUser.role="admin";updateUserUI(currentUser,false);}')
    else:page.evaluate('()=>{token="rotated-session";updateUserUI(currentUser,false);}')
    assert page.evaluate('publicationPlan===null && publicationGrant===null')
    expect(page.locator('#publicationTestShare')).not_to_be_checked();expect(page.locator('#publicationTest')).to_be_disabled()
    assert not errors and not external


def test_old_backend_marker_keeps_new_publication_actions_disabled(publication_page):
    page,_,_,_,admin,errors,external,requests=publication_page
    def old(route):
        response=admin.get('/admin/api/workflows?limit=100',headers={'X-Dashboard':'1','Authorization':'Bearer publication-browser'})
        value=response.json();value.pop('publication_profile',None);route.fulfill(status=200,content_type='application/json',body=json.dumps(value))
    page.route('**/admin/api/workflows?limit=100',old)
    page.goto('https://admin.example/admin/ui');page.locator('#adminLoginUsername').fill('sadmin');page.locator('#adminLoginPassword').fill('sadmin');page.locator('#adminLoginSubmitBtn').click()
    expect(page.locator('#adminLoginModal')).to_be_hidden();page.locator('[data-tab="workflows"]').click();page.evaluate('loadWorkflows()')
    expect(page.locator('#workflowPublicationOpen')).to_be_disabled();page.evaluate('openPublication()')
    assert not [path for _,path,_,_ in requests if path.startswith('/admin/api/workflow-publications')]
    assert not errors and not external


def test_late_admin_preparation_after_close_does_not_restore_private_state(publication_page):
    page,_,_,_,_,errors,external,_=publication_page;enter_admin(page);pending=[]
    page.route('**/admin/api/workflow-publications/prepare',lambda route:pending.append(route))
    page.locator('#publicationQuery').fill('Python news');page.locator('#publicationPrepare').click();pending_request(page,pending)
    page.locator('#publicationClose').click();pending[0].fulfill(status=200,content_type='application/json',body=json.dumps({'ok':True,'profile':'public-news-title-to-docs-v1','proposal':{},'signature':'late','executed':False,'preview':{}}))
    page.wait_for_function('publicationBusy===false')
    assert page.evaluate('publicationPlan===null && publicationGrant===null') and not errors and not external


def test_editing_publication_ttl_during_review_discards_late_grant_and_allows_fresh_review(publication_page):
    page,_,web,_,_,errors,external,_=publication_page;job=completed_canonical_test(web);enter_admin(page)
    page.locator('#publicationHistory').select_option(job['run_id']);page.locator('#publicationInspect').click()
    expect(page.locator('#publicationPrepareGrant')).to_be_enabled();pending=[]
    page.route('**/admin/api/workflow-publications/prepare-publication',lambda route:pending.append(route))
    page.locator('#publicationPrepareGrant').click();pending_request(page,pending)
    page.locator('#publicationTtl').fill('3600')
    pending[0].fulfill(status=200,content_type='application/json',body='{"ok":true,"proposal":{},"signature":"stale","preview":{}}')
    expect(page.locator('#publicationPrepareGrant')).to_be_enabled();expect(page.locator('#publicationAuthority')).not_to_be_checked()
    expect(page.locator('#publicationPublish')).to_be_disabled()
    assert page.evaluate('publicationBusy===false && publicationGrant===null')
    assert not errors and not external


@pytest.mark.parametrize('mode',['invalid','unknown'])
def test_public_source_problem_blocks_documentation_and_never_retries(publication_page,mode):
    page,rt,web,_,_,errors,external,requests=publication_page;identity=released(web)
    rt.typed_test_controls['seen'].clear();rt.typed_test_controls['news_calls']=0
    if mode=='invalid':rt.typed_test_controls['title']=None
    else:rt.publication_browser_modes['primary.example']='unknown'
    prepare_public(page,identity);authorize_public(page)
    expect(page.locator('#connectionStatus')).to_have_text('Connection: failed' if mode=='invalid' else 'Agent outcome unknown',timeout=15000)
    assert len(rt.typed_test_controls['seen'])==1
    assert rt.typed_test_controls['news_calls']==(1 if mode=='invalid' else 0)
    assert len([1 for method,path,_,_ in requests if method=='POST' and path.endswith('/runs')])==1
    if mode=='unknown':expect(page.locator('#connectionPrepare')).to_be_disabled();expect(page.locator('#connectionRun')).to_be_disabled()
    assert 'https://unsafe.example' not in page.locator('body').text_content()
    assert not errors and not external


def test_public_accepted_start_followed_by_400_locks_new_starts(publication_page):
    page,rt,web,public,_,errors,external,requests=publication_page;identity=released(web);accepted=[]
    def interrupted(route):
        response=public.post(urlsplit(route.request.url).path,content=route.request.post_data,headers=route.request.headers)
        assert response.status_code==202,response.text;accepted.append(response.json())
        route.fulfill(status=400,content_type='application/json',body='{"error":"synthetic private diagnostic"}')
    page.route('**/api/workflow-connections/*/runs',interrupted)
    prepare_public(page,identity);authorize_public(page)
    expect(page.locator('#connectionStatus')).to_contain_text('could not be confirmed')
    expect(page.locator('#connectionPrepare')).to_be_disabled();page.evaluate('document.getElementById("connectionPrepare").click()')
    assert len(accepted)==1 and wait(web,accepted[0])['status']=='succeeded'
    assert 'synthetic private diagnostic' not in page.locator('body').text_content() and not errors and not external


def test_public_reload_and_close_forget_consents_without_starting(publication_page):
    page,_,web,_,_,errors,external,requests=publication_page;identity=released(web)
    prepare_public(page,identity);page.locator('#connectionShare').check();page.locator('#connectionLive').check();before=len(requests)
    page.reload();expect(page.locator('#connectionPrepare')).to_be_enabled();expect(page.locator('#connectionRun')).to_be_disabled()
    expect(page.locator('#connectionShare')).not_to_be_checked();assert not any(method=='POST' for method,_,_,_ in requests[before:])
    page.locator('#connectionPrepare').click();expect(page.locator('#connectionStatus')).to_contain_text('Review ready');page.locator('#connectionShare').check()
    page.evaluate('window.dispatchEvent(new Event("pagehide"))');expect(page.locator('#connectionReview')).to_be_empty();expect(page.locator('#connectionShare')).not_to_be_checked()
    assert not page.evaluate('Object.keys(localStorage).concat(Object.keys(sessionStorage)).length') and not errors and not external


def test_public_results_are_semantic_text_and_provider_markup_cannot_execute(publication_page):
    page,rt,web,_,_,errors,external,_=publication_page;identity=released(web)
    hostile='<img src="https://evil.example/pixel" onerror="window.publicInjected=true">'
    def outcome(route):
        route.fulfill(status=200,content_type='application/json',body=json.dumps({'status':'succeeded','node_results':[
            {'node_id':'start','type':'trigger','name':'private trigger','status':'succeeded','data':{'trigger':'manual'}},
            {'type':'agent','name':'private provider','status':'succeeded','data':{'structuredContent':{'partial':False,'items':[{'title':hostile,'summary':'Recorded summary','url':'https://sources.example/news','published_at':'2026-10-18T00:00:00Z','retrieved_at':'2026-10-18T01:00:00Z'}]}}}]}))
    page.route('**/api/workflow-connections/*/runs/*',outcome)
    prepare_public(page,identity);authorize_public(page);expect(page.locator('#connectionResults')).to_contain_text(hostile)
    assert page.locator('#connectionResults img').count()==0 and page.evaluate('window.publicInjected===undefined')
    expect(page.locator('#connectionResults a')).to_have_attribute('rel','noopener noreferrer')
    rendered=page.locator('#connectionResults').text_content();assert 'private provider' not in rendered and 'private trigger' not in rendered and 'structuredContent' not in rendered
    jobs=web.store.query("SELECT id FROM workflow_runs WHERE actor=?",('public-flow:'+identity,));assert len(jobs)==1;wait(web,{'run_id':jobs[0]['id']})
    assert not errors and not external


def test_admin_withdrawal_uses_current_revision_and_public_page_stops_new_runs(publication_page):
    page,rt,web,public,_,errors,external,requests=publication_page;identity=released(web)
    before=len(rt.typed_test_controls['seen']);enter_admin(page)
    expect(page.locator('#publicationReleases')).to_contain_text('Active')
    page.locator('#publicationReleases').get_by_role('button', name='Withdraw publication', exact=True).click()
    expect(page.locator('#publicationStatus')).to_contain_text('Publication withdrawn')
    row=rt.store.query('SELECT active,revision FROM workflow_publication_grants WHERE id=?',(identity,))[0]
    assert row['active']==0 and row['revision']==2
    assert public.get('/api/workflow-connections/'+identity).status_code==404
    assert public.post('/api/workflow-connections/'+identity+'/prepare',json={}).status_code==400
    assert len(rt.typed_test_controls['seen'])==before
    revoke=[json.loads(body) for method,path,body,_ in requests if method=='POST' and path.endswith('/revoke')]
    assert revoke==[{'revision':1}] and not errors and not external


def test_unknown_documentation_outcome_stays_readable_without_new_invocation(publication_page):
    page,rt,web,public,_,errors,external,requests=publication_page;identity=released(web)
    rt.typed_test_controls['seen'].clear();rt.publication_browser_modes['alternate.example']='unknown';rt.publication_browser_modes['third.example']='unknown'
    prepare_public(page,identity);authorize_public(page)
    expect(page.locator('#connectionStatus')).to_have_text('Agent outcome unknown',timeout=15000)
    expect(page.locator('#connectionResults')).to_contain_text('did not complete with a verified result')
    reads=[(path,headers['x-workflow-key']) for method,path,_,headers in requests if method=='GET' and '/runs/' in path and 'x-workflow-key' in headers]
    assert reads
    path,key=reads[-1];response=public.get(path,headers={'X-Workflow-Key':key})
    assert response.status_code==200 and response.json()['execution_outcome']=='unknown'
    assert public.get('/api/workflow-connections/'+identity).status_code==200
    expect(page.locator('#connectionPrepare')).to_be_disabled();expect(page.locator('#connectionRun')).to_be_disabled();expect(page.locator('#connectionCancel')).to_be_disabled()
    posts_before=len([1 for method,_,_,_ in requests if method=='POST'])
    page.evaluate('document.getElementById("connectionPrepare").click();document.getElementById("connectionRun").click()')
    with page.expect_response('**/api/workflow-connections/*/runs/*'):page.locator('#connectionResume').click()
    expect(page.locator('#connectionStatus')).to_have_text('Agent outcome unknown')
    assert len([1 for method,_,_,_ in requests if method=='POST'])==posts_before
    assert len(rt.typed_test_controls['seen'])==2 and key not in page.locator('body').text_content()
    page.reload();expect(page.locator('#connectionStatus')).to_contain_text('unavailable for new runs');expect(page.locator('#connectionPrepare')).to_be_disabled()
    assert public.get(path,headers={'X-Workflow-Key':key}).status_code==200
    assert not errors and not external


def test_only_status_gets_have_bounded_retries_and_never_repeat_execution(publication_page):
    page,_,web,public,_,errors,external,requests=publication_page;identity=released(web);polls=[]
    def status_response(route):
        polls.append(route.request.url)
        if len(polls)<=2:return route.fulfill(status=503,content_type='application/json',body='{"error":"private temporary diagnostic"}')
        response=public.get(urlsplit(route.request.url).path,headers=route.request.headers)
        route.fulfill(status=response.status_code,content_type='application/json',body=response.content)
    page.route('**/api/workflow-connections/*/runs/*',status_response)
    prepare_public(page,identity);authorize_public(page)
    expect(page.locator('#connectionStatus')).to_have_text('Connection: succeeded',timeout=15000)
    assert len(polls)==3 and len([1 for method,path,_,_ in requests if method=='POST' and path.endswith('/runs')])==1
    assert 'private temporary diagnostic' not in page.locator('body').text_content() and not errors and not external


def test_public_stop_is_one_explicit_request_and_never_restarts_the_run(publication_page,monkeypatch):
    page,_,web,public,_,errors,external,requests=publication_page;identity=released(web);cancelled=[]
    # Hold this run before dispatch so cancellation has a definite outcome.
    # Cancellation after dispatch may correctly remain unknown and locked.
    monkeypatch.setattr(web,'launch',lambda _:None)
    web.typed_test_controls['seen'].clear()
    def running(route):
        request=route.request;path=urlsplit(request.url).path
        if request.method=='POST':
            cancelled.append(path);response=public.post(path,headers=request.headers)
            web._execute(path.split('/')[-2])
            return route.fulfill(status=response.status_code,content_type='application/json',body=response.content)
        if not cancelled:return route.fulfill(status=200,content_type='application/json',body='{"status":"running","node_results":[]}')
        response=public.get(path,headers=request.headers);route.fulfill(status=response.status_code,content_type='application/json',body=response.content)
    page.route('**/api/workflow-connections/*/runs/**',running)
    prepare_public(page,identity);authorize_public(page);expect(page.locator('#connectionCancel')).to_be_enabled()
    page.locator('#connectionCancel').click();expect(page.locator('#connectionCancel')).to_be_disabled()
    try:expect(page.locator('#connectionPrepare')).to_be_enabled(timeout=15000)
    except AssertionError as error:raise AssertionError((page.locator('#connectionStatus').text_content(),page.locator('#connectionNotice').text_content(),cancelled)) from error
    assert len(cancelled)==1 and cancelled[0].endswith('/cancel')
    assert len([1 for method,path,_,_ in requests if method=='POST' and path.endswith('/runs')])==1
    assert not web.typed_test_controls['seen']
    run_id=cancelled[0].split('/')[-2]
    assert web.get(run_id)['status']=='cancelled'
    assert not web.store.query('SELECT 1 FROM workflow_execution_attempts WHERE run_id=?',(run_id,))
    expect(page.locator('#connectionRun')).to_be_disabled();expect(page.locator('#connectionShare')).not_to_be_checked()
    assert not page.evaluate('Object.keys(localStorage).concat(Object.keys(sessionStorage)).length') and not errors and not external


def test_public_page_has_local_nonce_csp_english_metadata_and_no_identity_projection():
    page=build_public_connection_page('pub_'+'a'*32,nonce='n'*32)
    assert '<html lang="en">' in page and 'og:title' in page and 'twitter:description' in page
    assert "script-src 'nonce-" in page and 'unsafe-inline' not in page and 'unsafe-eval' not in page
    assert 'lucide lucide-link' in page and 'lucide lucide-play' in page and 'prefers-reduced-motion' in page
    assert '/assets/public-connection.js' in page and 'resource_id' not in page and 'workflow-public-flow-test' not in page
    assert not any('\uac00'<=character<='\ud7a3' for character in page)
    with pytest.raises(ValueError):build_public_connection_page('</script>')
