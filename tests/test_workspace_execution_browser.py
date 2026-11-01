"""Private snapshot execution is explicit, scoped and rendered safely in Chromium."""
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect
import pytest

from agent_market.workspace_service import BASE
from tests.test_front_workflow_browser import browser
from tests.test_workspace_browser import sign_in, select_space, open_snapshot
from tests.test_workspace_execution_api import private_api, execute

REPORT=Path('reports/advancement-r08-private-runs-2026-10-18')


@pytest.fixture
def private_page(private_api,browser):
    w=private_api;context=browser.new_context(accept_downloads=True);w.page=context.new_page();w.errors=[];w.external=[];w.requests=[]
    def serve(route):
        req=route.request;url=urlsplit(req.url)
        if url.hostname!='admin.test':w.external.append(req.url);return route.abort()
        w.requests.append((req.method,url.path,req.post_data))
        response=w.client.request(req.method,url.path+('?' +url.query if url.query else ''),headers=req.headers,content=req.post_data)
        route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items() if k not in ('content-length','content-encoding','transfer-encoding')})
    context.route('**/*',serve);w.page.on('pageerror',lambda error:w.errors.append(str(error)))
    yield w
    context.close()


def enter(w,person='owner'):
    sign_in(w,person);select_space(w,w.ws);open_snapshot(w,w.ws,w.draft)
    expect(w.page.locator('#workspaceRunStatus')).not_to_have_text('지원 여부와 현재 실행 권한을 확인하는 중입니다.')


def prepare_ui(w):
    expect(w.page.locator('#workspaceRunPrepare')).to_be_enabled();w.page.locator('#workspaceRunPrepare').click()
    expect(w.page.locator('#workspaceRunStatus')).to_contain_text('실행 준비 완료')
    expect(w.page.locator('#workspaceRunPreview')).to_contain_text('Synthetic semiconductor research')


def run_ui(w):
    w.page.locator('#workspaceRunAuthority').check();expect(w.page.locator('#workspaceRunExecute')).to_be_enabled();w.page.locator('#workspaceRunExecute').click()


def assert_clean(w):
    assert not w.errors and not w.external
    for key in ('workspaceRunPreview','workspaceRunOutput'):
        assert w.page.locator('#'+key+' img, #'+key+' a, #'+key+' script').count()==0


@pytest.mark.parametrize('person',['owner','editor'])
def test_actual_private_run_requires_exact_review_unchecked_authority_and_one_explicit_post(private_page,person):
    w=private_page;enter(w,person);expect(w.page.locator('#workspaceRunExecute')).to_be_disabled();expect(w.page.locator('#workspaceRunAuthority')).not_to_be_checked();assert not w.calls
    prepare_ui(w);assert not w.calls
    expect(w.page.locator('#workspaceRunPreview')).to_contain_text('search_news');expect(w.page.locator('#workspaceRunPreview')).to_contain_text('12초')
    expect(w.page.locator('#workspaceRunExecute')).to_be_disabled()
    run_ui(w);expect(w.page.locator('#workspaceRunStatus')).to_have_text('비공개 실행: 완료');expect(w.page.locator('#workspaceRunOutput')).to_contain_text('Private research result <untrusted>')
    expect(w.page.locator('#workspaceRunAuthority')).not_to_be_checked();expect(w.page.locator('#workspaceRunExecute')).to_be_disabled()
    w.page.evaluate('document.querySelector("#workspaceRunExecute").click()');assert w.calls.count('tools/call')==1
    submitted=[json.loads(body) for method,path,body in w.requests if method=='POST' and path==w.path+'/runs']
    assert len(submitted)==1 and set(submitted[0])=={'ticket_id','authorized','notice'}
    assert submitted[0]['authorized'] is True and submitted[0]['notice']=='workspace-private-run-v1'
    prepared=[json.loads(body) for method,path,body in w.requests if method=='POST' and path==w.path+'/prepare'];assert prepared==[{'snapshot_revision':w.snapshot['revision']}]
    w.page.locator('#workspaceRunHistoryRefresh').click();w.page.locator('#workspaceRunHistory').get_by_role('button',name='실행 결과 보기').click()
    expect(w.page.locator('#workspaceRunOutput')).to_contain_text('Private research result');assert w.calls.count('tools/call')==1
    assert w.store.query('SELECT COUNT(*) FROM workflow_runs')[0][0]==0
    assert w.client.get(w.path.removesuffix('/execution')+'/artifact',headers=w.headers[person]).json()['executable'] is False
    assert_clean(w)
    if person=='owner':
        REPORT.mkdir(parents=True,exist_ok=True);w.page.set_viewport_size({'width':1280,'height':1100});w.page.screenshot(path=str(REPORT/'private-execution-result.png'))


@pytest.mark.parametrize('person',['viewer','operator'])
def test_readonly_member_can_inspect_retained_results_but_never_authorize_new_run(private_page,person):
    w=private_page;execute(w);enter(w,person)
    expect(w.page.locator('#workspaceRunPrepare')).to_be_disabled();expect(w.page.locator('#workspaceRunExecute')).to_be_disabled()
    w.page.locator('#workspaceRunHistoryRefresh').click();w.page.locator('#workspaceRunHistory').get_by_role('button',name='실행 결과 보기').click()
    expect(w.page.locator('#workspaceRunOutput')).to_contain_text('Private research result');assert w.calls.count('tools/call')==1
    assert not any(method=='POST' and path.startswith(w.path) for method,path,_ in w.requests);assert_clean(w)


def test_output_markup_is_untrusted_text_and_never_creates_elements(private_page):
    w=private_page;attack='<img src=x onerror="window.__privateRunXss=1"><a href="javascript:alert(1)">untrusted</a>'
    w.remote.call_result={'content':[{'type':'text','text':attack}]};enter(w);prepare_ui(w);run_ui(w)
    expect(w.page.locator('#workspaceRunStatus')).to_have_text('비공개 실행: 완료')
    expect(w.page.locator('#workspaceRunOutput')).to_contain_text('<img');assert w.page.evaluate('window.__privateRunXss || 0')==0;assert_clean(w)


def test_old_execution_endpoint_absence_preserves_snapshot_read_and_json_download(private_page):
    w=private_page;w.page.route('**/execution/options',lambda route:route.fulfill(status=404,content_type='application/json',body='{"detail":"Not Found"}'));enter(w)
    expect(w.page.locator('#workspaceRunStatus')).to_contain_text('현재 서버에서는')
    expect(w.page.locator('#workspaceRunPrepare')).to_be_disabled();expect(w.page.locator('#workspaceSnapshotPreview')).to_be_visible()
    with w.page.expect_download() as pending:w.page.locator('#workspaceSnapshotDownload').click()
    assert json.loads(Path(pending.value.path()).read_bytes())['saved_snapshot'] is True
    assert not w.calls and not any(method=='POST' and path.startswith(w.path) for method,path,_ in w.requests);assert_clean(w)


def test_unsupported_blank_snapshot_cannot_execute_but_remains_a_valid_private_artifact(private_page):
    w=private_page
    saved=w.client.post(BASE+'/'+w.ws['id']+'/drafts',headers=w.headers['owner'],json={'name':'Blank planning','description':'','definition':{'nodes':[],'edges':[]}}).json()['draft']
    version=w.client.post(BASE+'/'+w.ws['id']+'/drafts/'+saved['id']+'/snapshots',headers=w.headers['owner'],json={'draft_revision':saved['revision']}).json()['snapshot']
    sign_in(w);select_space(w,w.ws)
    # Select the row by its own private title, without changing any execution inputs.
    row=w.page.locator('#workspaceDraftList .card').filter(has_text='Blank planning');row.get_by_role('button',name='저장본 보기').click()
    w.page.locator('#workspaceSnapshotList').get_by_role('button',name='저장본 열기').click()
    expect(w.page.locator('#workspaceRunStatus')).to_contain_text('지원하지 않습니다');expect(w.page.locator('#workspaceRunPrepare')).to_be_disabled();expect(w.page.locator('#workspaceSnapshotDownload')).to_be_enabled()
    assert not w.calls and version['active'];assert_clean(w)


@pytest.mark.parametrize('action',['close','escape','selection','role','token','logout'])
def test_late_genuine_preparation_never_restores_consent_after_scope_changes(private_page,action):
    w=private_page;enter(w);pending=[]
    if action=='selection':
        alternate=w.client.post(w.path.removesuffix('/'+w.snapshot['id']+'/execution'),headers=w.headers['owner'],json={'draft_revision':w.draft['revision']})
        assert alternate.status_code==200
        w.page.locator('#workspaceSnapshotClose').click()
        w.page.locator('#workspaceDraftList').get_by_role('button',name='저장본 보기').click()
        w.page.locator('#workspaceSnapshotList .card').filter(has_text='저장본 '+str(w.snapshot['ordinal'])+' ·').get_by_role('button',name='저장본 열기').click()
        expect(w.page.locator('#workspaceRunPrepare')).to_be_enabled()
    def hold(route):
        response=w.client.post(w.path+'/prepare',headers=w.headers['owner'],content=route.request.post_data)
        assert response.status_code==200,response.text
        pending.append((route,response));w.page.evaluate('window.__privatePrepareHeld=true')
    w.page.route('**/execution/prepare',hold);w.page.locator('#workspaceRunPrepare').click();w.page.wait_for_function('() => window.__privatePrepareHeld===true')
    if action=='close':w.page.locator('#workspaceSnapshotClose').click()
    elif action=='escape':w.page.keyboard.press('Escape')
    elif action=='selection':w.page.locator('#workspaceSnapshotList').get_by_role('button',name='저장본 열기').nth(1).click()
    elif action=='role':w.page.evaluate('()=>{currentUser.role="operator";updateUserUI(currentUser,false);}')
    elif action=='token':w.page.evaluate('()=>{token="rotated-private-session";updateUserUI(currentUser,false);}')
    else:
        w.page.route('**/admin/api/auth/logout',lambda route:None);w.page.on('dialog',lambda dialog:dialog.accept());w.page.evaluate('document.querySelector("#logoutBtn").click()')
    route,response=pending[0];route.fulfill(status=200,content_type='application/json',body=response.content)
    expect(w.page.locator('#workspaceRunAuthority')).not_to_be_checked();expect(w.page.locator('#workspaceRunExecute')).to_be_disabled()
    assert w.page.locator('#workspaceRunPreview').inner_text()=='';assert not w.calls;assert_clean(w)


def test_accepted_run_followed_by_http400_locks_new_starts_and_only_history_resolves(private_page):
    w=private_page;enter(w);prepare_ui(w)
    def accepted_then_lost(route):
        response=w.client.post(w.path+'/runs',headers=w.headers['owner'],content=route.request.post_data)
        assert response.status_code==200,response.text
        route.fulfill(status=400,content_type='application/json',body='{"detail":"Synthetic ambiguous admission response"}')
    w.page.route('**/execution/runs',accepted_then_lost,times=1);run_ui(w)
    expect(w.page.locator('#workspaceRunStatus')).to_contain_text('확정할 수 없습니다');expect(w.page.locator('#workspaceRunPrepare')).to_be_disabled();expect(w.page.locator('#workspaceRunExecute')).to_be_disabled()
    assert w.calls.count('tools/call')==1
    w.page.locator('#workspaceRunHistoryRefresh').click();w.page.locator('#workspaceRunHistory').get_by_role('button',name='실행 결과 보기').click();expect(w.page.locator('#workspaceRunOutput')).to_contain_text('Private research result')
    expect(w.page.locator('#workspaceRunPrepare')).to_be_disabled();assert w.calls.count('tools/call')==1;assert_clean(w)


def test_unknown_external_outcome_is_visible_and_never_reexecuted(private_page):
    w=private_page;w.control['mode']='timeout';enter(w);prepare_ui(w);run_ui(w)
    expect(w.page.locator('#workspaceRunStatus')).to_contain_text('외부 실행 결과 확인 필요');expect(w.page.locator('#workspaceRunPrepare')).to_be_disabled();expect(w.page.locator('#workspaceRunExecute')).to_be_disabled();assert w.calls.count('tools/call')==1
    w.page.locator('#workspaceRunRefresh').click();expect(w.page.locator('#workspaceRunStatus')).to_contain_text('외부 실행 결과 확인 필요');assert w.calls.count('tools/call')==1;assert_clean(w)


@pytest.mark.parametrize('action',['close','logout'])
def test_late_accepted_run_result_cannot_repopulate_after_close_or_held_logout(private_page,action):
    w=private_page;enter(w);prepare_ui(w);pending=[]
    def hold(route):
        response=w.client.post(w.path+'/runs',headers=w.headers['owner'],content=route.request.post_data)
        assert response.status_code==200,response.text
        pending.append((route,response));w.page.evaluate('window.__privateResultHeld=true')
    w.page.route('**/execution/runs',hold);run_ui(w);w.page.wait_for_function('() => window.__privateResultHeld===true');assert w.calls.count('tools/call')==1
    if action=='close':w.page.locator('#workspaceSnapshotClose').click()
    else:
        w.page.route('**/admin/api/auth/logout',lambda route:None);w.page.on('dialog',lambda dialog:dialog.accept());w.page.evaluate('document.querySelector("#logoutBtn").click()')
    route,response=pending[0];route.fulfill(status=200,content_type='application/json',body=response.content)
    expect(w.page.locator('#workspaceSnapshotDialog')).not_to_be_visible();assert w.page.locator('#workspaceRunOutput').inner_text()=='';assert w.page.locator('#workspaceRunPreview').inner_text()=='';assert_clean(w)


def test_revoked_membership_after_prepare_denies_call_and_clears_private_content(private_page):
    w=private_page;enter(w,'editor');prepare_ui(w)
    response=w.client.post(BASE+'/'+w.ws['id']+'/members',headers=w.headers['owner'],json={'user_id':w.users['editor'],'role':'editor','active':False,'revision':1});assert response.status_code==200
    run_ui(w);expect(w.page.locator('#workspaceSnapshotDialog')).not_to_be_visible();expect(w.page.locator('#workspaceContent')).not_to_be_visible();assert not w.calls;assert_clean(w)


def test_short_client_review_expiry_disables_authority_without_any_call(private_page):
    w=private_page;enter(w)
    def short_review(route):
        response=w.client.post(w.path+'/prepare',headers=w.headers['owner'],content=route.request.post_data);assert response.status_code==200
        value=response.json();value['expires']=w.page.evaluate('Date.now()/1000+0.5')
        route.fulfill(status=200,content_type='application/json',body=json.dumps(value))
    w.page.route('**/execution/prepare',short_review);prepare_ui(w)
    w.page.locator('#workspaceRunAuthority').check()
    expect(w.page.locator('#workspaceRunStatus')).to_contain_text('만료되었습니다');expect(w.page.locator('#workspaceRunAuthority')).not_to_be_checked();expect(w.page.locator('#workspaceRunExecute')).to_be_disabled();assert not w.calls;assert_clean(w)


@pytest.mark.parametrize('status',['prepared','dispatched'])
def test_nonterminal_accepted_status_blocks_fresh_start_and_keeps_readonly_history(private_page,status):
    w=private_page;enter(w);prepare_ui(w)
    def retained_nonterminal(route):
        response=w.client.post(w.path+'/runs',headers=w.headers['owner'],content=route.request.post_data);assert response.status_code==200
        value=response.json();value['run']['status']=status;value['run']['output']=None
        route.fulfill(status=200,content_type='application/json',body=json.dumps(value))
    w.page.route('**/execution/runs',retained_nonterminal,times=1);run_ui(w)
    expect(w.page.locator('#workspaceRunPrepare')).to_be_disabled();expect(w.page.locator('#workspaceRunExecute')).to_be_disabled();expect(w.page.locator('#workspaceRunHistoryRefresh')).to_be_enabled();expect(w.page.locator('#workspaceRunRefresh')).to_be_enabled()
    w.page.locator('#workspaceRunRefresh').click();expect(w.page.locator('#workspaceRunStatus')).to_have_text('비공개 실행: 완료');expect(w.page.locator('#workspaceRunPrepare')).to_be_disabled()
    assert w.calls.count('tools/call')==1;assert_clean(w)


def test_late_scoped_history_response_cannot_restore_closed_private_ui(private_page):
    w=private_page;execute(w);enter(w);pending=[]
    def hold(route):
        response=w.client.get(w.path+'/runs',headers=w.headers['owner']);assert response.status_code==200
        pending.append((route,response));w.page.evaluate('window.__privateHistoryHeld=true')
    w.page.route('**/execution/runs',hold);w.page.locator('#workspaceRunHistoryRefresh').click();w.page.wait_for_function('() => window.__privateHistoryHeld===true');w.page.locator('#workspaceSnapshotClose').click()
    route,response=pending[0];route.fulfill(status=200,content_type='application/json',body=response.content)
    expect(w.page.locator('#workspaceSnapshotDialog')).not_to_be_visible();assert w.page.locator('#workspaceRunHistory').inner_text()=='';assert w.page.locator('#workspaceRunOutput').inner_text()=='';assert_clean(w)


@pytest.mark.parametrize('field,value',[('resource_id',None),('max_calls',2)])
def test_malformed_target_or_call_limit_never_becomes_an_executable_review(private_page,field,value):
    w=private_page;enter(w)
    def invalid_review(route):
        response=w.client.post(w.path+'/prepare',headers=w.headers['owner'],content=route.request.post_data);assert response.status_code==200
        body=response.json();body['preview'][field]=value
        route.fulfill(status=200,content_type='application/json',body=json.dumps(body))
    w.page.route('**/execution/prepare',invalid_review);w.page.locator('#workspaceRunPrepare').click()
    expect(w.page.locator('#workspaceRunStatus')).to_contain_text('요청을 완료하지 못했습니다');expect(w.page.locator('#workspaceRunExecute')).to_be_disabled();expect(w.page.locator('#workspaceRunAuthority')).to_be_disabled();expect(w.page.locator('#workspaceRunPreview')).not_to_be_visible()
    assert not w.calls;assert_clean(w)
