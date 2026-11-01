"""The private pair dialog requires two fresh approvals and one atomic execute."""
from tests.browser_wait import pending_request
import json

import pytest
from playwright.sync_api import expect

from agent_market.workflow_controlled_pairs import ControlledPairs

from tests.test_workflow_composer_browser import enter
from tests.test_workflow_controlled_pairs_api import BASE, SHARE, LIVE
from tests.test_workflow_fallback import routing
from tests.test_workflow_fallback_api import routing_api as base_routing_api
from tests.test_workflow_fallback_browser import browser, fallback_page
from tests.test_workflow_typed_flow import typed_routing
from tests.test_workflow_runtime import wait


@pytest.fixture
def routing_api(typed_routing):
    yield from base_routing_api.__wrapped__(typed_routing)


def open_pair(page):
    expect(page.locator('#workflowPairOpen')).to_be_enabled()
    page.locator('#workflowPairOpen').click()
    expect(page.locator('#workflowPairDialog')).to_be_visible()
    expect(page.locator('#workflowPairPrepare')).to_be_enabled()
    page.locator('#workflowPairObjective').fill('Latest Python news')


def prepare_pair(page):
    page.locator('#workflowPairPrepare').click()
    expect(page.locator('#workflowPairStatus')).to_contain_text('Private plan ready')


def authorize_pair(page):
    page.locator('#workflowPairShare').check()
    page.locator('#workflowPairLive').check()


def posts_for(page):
    posts=[]
    page.on('request',lambda request:posts.append((request.url,request.post_data_json))
            if request.method=='POST' and '/admin/api/' in request.url else None)
    return posts


def test_fresh_private_pair_has_explicit_authorities_equal_target_inputs_and_no_publication(fallback_page):
    page,routing,errors,external,_=fallback_page;rt,_,_,calls,*_=routing
    enter(page);posts=posts_for(page);builder=page.evaluate('JSON.stringify(canvasGraph)');open_pair(page)
    assert not calls
    for name in ('Share','Live'):
        expect(page.locator('#workflowPair'+name)).not_to_be_checked()
        expect(page.locator('#workflowPair'+name)).to_be_disabled()
    prepare_pair(page)
    expect(page.locator('#workflowPairPreview')).to_contain_text('Maximum calls: 3')
    expect(page.locator('#workflowPairPreview')).to_contain_text('25 seconds')
    assert not calls and not any(url.endswith('/execute') for url,_ in posts)
    page.locator('#workflowPairShare').check()
    page.evaluate('runControlledPair()')
    assert not any(url.endswith('/execute') for url,_ in posts)
    page.locator('#workflowPairLive').check();page.locator('#workflowPairRun').click()
    expect(page.locator('#workflowPairStatus')).to_contain_text('Controlled pair: succeeded',timeout=15000)
    sent=[body for url,body in posts if url.endswith('/execute')]
    assert len(sent)==1 and sent[0]['share_authority'] is True and sent[0]['share_notice']==SHARE
    assert sent[0]['live_authority'] is True and sent[0]['live_notice']==LIVE
    assert set(sent[0])=={'proposal','signature','share_authority','share_notice','live_authority','live_notice'}
    assert len(calls)==3 and calls.count('primary.example')==1
    assert rt.typed_test_controls['seen'][1]==rt.typed_test_controls['seen'][2]
    expect(page.locator('#workflowPairResult')).to_contain_text('Python asynchronous task documentation')
    expect(page.locator('#workflowPairResult')).to_contain_text('Publication is blocked')
    expect(page.locator('#workflowPairShare')).not_to_be_checked();expect(page.locator('#workflowPairLive')).not_to_be_checked()
    expect(page.locator('#workflowPairRun')).to_be_disabled()
    page.evaluate('runControlledPair()')
    assert len([url for url,_ in posts if url.endswith('/execute')])==1
    assert not any('/publish' in url for url,_ in posts)
    assert page.evaluate('JSON.stringify(canvasGraph)')==builder
    assert not page.evaluate('Object.keys(sessionStorage).concat(Object.keys(localStorage)).some(key=>key.toLowerCase().includes("controlledpair"))')
    page.set_viewport_size({'width':1280,'height':1100})
    box=page.locator('#workflowPairDialog').bounding_box();assert box is not None
    assert abs(box['x']+box['width']/2-640)<3 and abs(box['y']+box['height']/2-550)<3
    page.screenshot(path='reports/advancement-r07-controlled-pairs-2026-10-18/controlled-pair.png')
    assert not errors and not external


@pytest.mark.parametrize('change',['objective','target'])
def test_new_context_or_target_invalidates_plan_and_both_authorities(fallback_page,change):
    page,routing,errors,external,_=fallback_page;_,_,_,calls,*_=routing
    enter(page);open_pair(page);prepare_pair(page);authorize_pair(page)
    if change=='objective':page.locator('#workflowPairObjective').fill('Latest database news')
    else:page.locator('#workflowPairTargetA').dispatch_event('change')
    assert page.evaluate('controlledPairPlan===null')
    for name in ('Share','Live'):
        expect(page.locator('#workflowPair'+name)).not_to_be_checked()
        expect(page.locator('#workflowPair'+name)).to_be_disabled()
    expect(page.locator('#workflowPairRun')).to_be_disabled()
    assert not calls and not errors and not external


@pytest.mark.parametrize('action',['close','escape','refresh','role'])
def test_dialog_lifecycle_clears_private_plan_and_authorities(fallback_page,action):
    page,routing,errors,external,_=fallback_page;_,_,_,calls,*_=routing
    enter(page);open_pair(page);prepare_pair(page);authorize_pair(page)
    if action=='close':page.locator('#workflowPairClose').click()
    elif action=='escape':page.keyboard.press('Escape')
    elif action=='refresh':page.locator('#workflowPairRefresh').click()
    else:page.evaluate('() => {currentUser.role="admin"; updateUserUI(currentUser,false);}')
    assert page.evaluate('controlledPairPlan===null && controlledPairRunId===""')
    expect(page.locator('#workflowPairShare')).not_to_be_checked();expect(page.locator('#workflowPairLive')).not_to_be_checked()
    if action!='refresh':expect(page.locator('#workflowPairDialog')).to_be_hidden()
    assert not calls and not errors and not external


def test_late_preparation_response_is_discarded_after_close(fallback_page):
    page,routing,errors,external,_=fallback_page;rt,_,_,calls,*_=routing
    enter(page);open_pair(page);pending=[]
    page.route('**'+BASE+'/prepare',lambda route:pending.append(route))
    page.locator('#workflowPairPrepare').click()
    expect(page.locator('#workflowPairPrepare')).to_be_disabled();pending_request(page,pending)
    page.locator('#workflowPairClose').click()
    pending[0].fulfill(status=200,content_type='application/json',body=json.dumps({'ok':True,'profile':'news-title-docs-pair-v1'}))
    page.wait_for_timeout(100)
    assert page.evaluate('controlledPairPlan===null') and page.locator('#workflowPairPreview').text_content()==''
    assert not calls and not errors and not external


@pytest.mark.parametrize('marker',[None,'news-title-docs-pair-obsolete'])
def test_old_server_without_exact_marker_never_calls_pair_endpoints(fallback_page,marker):
    page,routing,errors,external,_=fallback_page;_,_,_,calls,*_=routing;requests=[]
    inventory={'ok':True,'workflows':[],'total':0}
    if marker is not None:inventory['controlled_pair_profile']=marker
    page.route('**/admin/api/workflows?limit=100',lambda route:route.fulfill(status=200,content_type='application/json',body=json.dumps(inventory)))
    page.on('request',lambda request:requests.append(request.url))
    enter(page)
    expect(page.locator('#workflowPairOpen')).to_be_disabled()
    expect(page.locator('#workflowPairAvailability')).to_contain_text('unavailable in this server version')
    page.evaluate('openControlledPair()')
    assert not any(BASE in url for url in requests)
    assert not calls and not errors and not external


def test_expired_preview_cannot_dispatch_and_requires_new_authorities(fallback_page):
    page,routing,errors,external,_=fallback_page;_,_,_,calls,*_=routing
    enter(page);open_pair(page);prepare_pair(page);authorize_pair(page);posts=posts_for(page)
    page.evaluate('controlledPairPlan.preview.expires=1;runControlledPair()')
    expect(page.locator('#workflowPairStatus')).to_contain_text('plan expired')
    assert not any(url.endswith('/execute') for url,_ in posts) and not calls
    expect(page.locator('#workflowPairShare')).not_to_be_checked();expect(page.locator('#workflowPairLive')).not_to_be_checked()
    assert not errors and not external


@pytest.mark.parametrize('mode',['invalid','unknown'])
def test_first_target_problem_blocks_second_target_and_no_browser_retry(fallback_page,mode):
    page,routing,errors,external,_=fallback_page;_,_,_,calls,modes,*_=routing
    enter(page);open_pair(page);prepare_pair(page);authorize_pair(page);posts=posts_for(page)
    modes['alternate.example']=modes['third.example']=mode
    page.locator('#workflowPairRun').click()
    expect(page.locator('#workflowPairStatus')).to_contain_text('Controlled pair: failed',timeout=15000)
    assert len(calls)==2 and calls[0]=='primary.example'
    assert len([url for url,_ in posts if url.endswith('/execute')])==1
    expect(page.locator('#workflowPairResult')).to_contain_text('Publication is blocked')
    assert not errors and not external


def test_preview_metadata_is_text_only_and_cannot_load_provider_markup(fallback_page):
    page,routing,errors,external,_=fallback_page;rt,_,_,calls,*_=routing
    enter(page);open_pair(page)
    def replace(route):
        body=ControlledPairs(rt).prepare(route.request.post_data_json,1)
        body['preview']['objective']='<img src="https://evil.example/pixel" onerror="window.pairInjected=true">'
        route.fulfill(status=200,content_type='application/json',body=json.dumps(body))
    page.route('**'+BASE+'/prepare',replace)
    prepare_pair(page)
    expect(page.locator('#workflowPairPreview')).to_contain_text('<img')
    assert page.locator('#workflowPairPreview img').count()==0 and page.evaluate('window.pairInjected===undefined')
    assert not calls and not errors and not external


def test_expired_session_during_prepare_clears_private_state(fallback_page):
    page,routing,errors,external,_=fallback_page;_,_,_,calls,*_=routing
    enter(page);open_pair(page);prepare_pair(page);authorize_pair(page)
    page.route('**'+BASE+'/prepare',lambda route:route.fulfill(status=401,content_type='application/json',body='{"detail":"Session expired."}'))
    page.locator('#workflowPairPrepare').click()
    expect(page.locator('#workflowPairDialog')).to_be_hidden();expect(page.locator('#adminLoginModal')).to_be_visible()
    assert page.evaluate('controlledPairPlan===null && controlledPairOptions===null && controlledPairAvailable===false')
    assert not calls and not errors and not external


def test_simultaneous_execute_attempts_issue_one_post_and_status_loss_never_retries(fallback_page):
    page,routing,errors,external,_=fallback_page;rt,_,_,calls,*_=routing
    enter(page);open_pair(page);prepare_pair(page);authorize_pair(page);posts=posts_for(page)
    page.route('**'+BASE+'/inspect',lambda route:route.fulfill(status=503,content_type='application/json',body='{"detail":"Unavailable"}'))
    page.evaluate('() => {runControlledPair();runControlledPair();}')
    expect(page.locator('#workflowPairStatus')).to_contain_text('Recorded status is unavailable',timeout=15000)
    assert len([url for url,_ in posts if url.endswith('/execute')])==1
    assert wait(rt,{'run_id':page.evaluate('controlledPairRunId')})['status']=='succeeded'
    assert len(calls)==3 and calls.count('primary.example')==1
    expect(page.locator('#workflowPairRun')).to_be_disabled()
    assert not errors and not external


def test_late_execute_response_after_close_is_not_polled_or_displayed(fallback_page):
    page,routing,errors,external,_=fallback_page;_,_,_,calls,*_=routing
    enter(page);open_pair(page);prepare_pair(page);authorize_pair(page);pending=[];posts=posts_for(page)
    page.route('**'+BASE+'/execute',lambda route:pending.append(route))
    page.locator('#workflowPairRun').click()
    expect(page.locator('#workflowPairShare')).not_to_be_checked()
    expect(page.locator('#workflowPairLive')).not_to_be_checked()
    pending_request(page,pending)
    page.locator('#workflowPairClose').click()
    pending[0].fulfill(status=202,content_type='application/json',body=json.dumps({'ok':True,'run_id':'wr_'+'0'*32,'status':'queued'}))
    page.wait_for_timeout(100)
    assert not any(url.endswith('/inspect') for url,_ in posts)
    assert page.evaluate('controlledPairRunId==="" && controlledPairPlan===null')
    assert page.locator('#workflowPairResult').text_content()=='' and not calls
    assert not errors and not external


def test_changing_selection_during_prepare_discards_stale_plan(fallback_page):
    page,routing,errors,external,_=fallback_page;_,_,_,calls,*_=routing
    enter(page);open_pair(page);pending=[]
    page.route('**'+BASE+'/prepare',lambda route:pending.append(route))
    page.locator('#workflowPairPrepare').click()
    expect(page.locator('#workflowPairPrepare')).to_be_disabled()
    page.locator('#workflowPairObjective').fill('Latest database news')
    expect(page.locator('#workflowPairPrepare')).to_be_enabled()
    pending_request(page,pending)
    pending[0].fulfill(status=200,content_type='application/json',body=json.dumps({'ok':True,'profile':'news-title-docs-pair-v1'}))
    page.wait_for_timeout(100)
    assert page.evaluate('controlledPairPlan===null')
    assert page.locator('#workflowPairPreview').text_content()==''
    expect(page.locator('#workflowPairShare')).to_be_disabled()
    assert not calls and not errors and not external


def test_empty_approved_catalog_explains_missing_agents_and_keeps_history_available(fallback_page):
    from tests.test_workflow_controlled_pairs import completed_pair
    page,routing,errors,external,_=fallback_page;rt,_,_,calls,*_=routing
    _,_,run=completed_pair(routing);count=len(calls)
    page.route('**'+BASE+'/options',lambda route:route.fulfill(status=200,content_type='application/json',body=json.dumps({
        'ok':True,'profile':'news-title-docs-pair-v1','available':False,'sources':[],'targets':[],
        'unavailable_reasons':['NEWS_SOURCE_UNAVAILABLE','DOCUMENTATION_TARGETS_UNAVAILABLE']})))
    enter(page);expect(page.locator('#workflowPairOpen')).to_be_enabled();page.locator('#workflowPairOpen').click()
    expect(page.locator('#workflowPairStatus')).to_contain_text('No approved news source')
    expect(page.locator('#workflowPairStatus')).to_contain_text('Two distinct approved documentation agents')
    expect(page.locator('#workflowPairPrepare')).to_be_disabled()
    page.locator('#workflowPairObjective').fill('Latest Python news');expect(page.locator('#workflowPairPrepare')).to_be_disabled()
    page.locator('#workflowPairHistory').select_option(run['run_id']);page.locator('#workflowPairInspect').click()
    expect(page.locator('#workflowPairResult')).to_contain_text('Python asynchronous task documentation')
    assert len(calls)==count and not errors and not external
