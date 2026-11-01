"""Private workspace UI uses real local sessions, isolated SQLite and Chromium."""
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.testclient import TestClient
from playwright.sync_api import expect
import pytest

from agent_market.gateway import admin_auth
from agent_market.gateway.dashboard import dashboard_router
from agent_market.gateway.store import Store
from agent_market.infra.redis_hub import RedisHub
from agent_market.workspace_service import BASE
from tests.test_front_workflow_browser import browser

REPORT = Path('reports/advancement-r08-workspaces-2026-10-18')


@pytest.fixture
def workspace_browser(browser, tmp_path, monkeypatch):
    cache = RedisHub(); cache._closed = True
    monkeypatch.setattr(RedisHub, 'get_instance', staticmethod(lambda: cache))
    path = tmp_path / 'private-ui.sqlite3'
    with sqlite3.connect(path) as db:
        db.executescript(admin_auth.ADMIN_SCHEMA)
        admin_auth.create_admin_user(db, 'sadmin', 'Synthetic-workspace-password-42', 'Synthetic owner', 'superadmin')
    store = Store(str(path)); users={'owner':1}; headers={}
    with store.tx() as db:
        for name, role in (('editor','admin'),('viewer','admin'),('operator','operator'),('outsider','superadmin')):
            users[name]=admin_auth.create_admin_user(db,name,'Synthetic-workspace-password-42',name,role)['id']
        for name, uid in users.items():
            row=db.execute('SELECT username,role,name FROM admin_users WHERE id=?',(uid,)).fetchone()
            value=admin_auth.create_session(db,uid,row['username'],row['role'],row['name'])
            headers[name]={'X-Dashboard':'1','Authorization':'Bearer '+value}
    app=FastAPI(); app.include_router(dashboard_router(store,str(path),'isolated-machine-token',None,ssl_manager=Mock(get_status=lambda:{})))
    client=TestClient(app,base_url='https://admin.test',raise_server_exceptions=False)
    context=browser.new_context(accept_downloads=True); page=context.new_page(); errors=[]; external=[]; requests=[]
    def serve(route):
        req=route.request; url=urlsplit(req.url)
        if url.hostname!='admin.test':external.append(req.url);return route.abort()
        requests.append((req.method,url.path,req.post_data))
        response=client.request(req.method,url.path+('?' +url.query if url.query else ''),content=req.post_data,headers=req.headers)
        route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items() if k not in ('content-length','content-encoding','transfer-encoding')})
    context.route('**/*',serve); page.on('pageerror',lambda value:errors.append(str(value)))
    world=SimpleNamespace(page=page,store=store,client=client,users=users,headers=headers,errors=errors,external=external,requests=requests)
    yield world
    context.close();client.close();store._db.close()


def sign_in(world,person='owner'):
    world.page.add_init_script('sessionStorage.setItem("adminToken",'+json.dumps(world.headers[person]['Authorization'][7:])+');')
    world.page.goto('https://admin.test/admin/ui#workspaces')
    expect(world.page.locator('#workspaceStatus')).to_contain_text('작업공간')
    expect(world.page.locator('#workspaceCreate')).to_be_visible() if person in ('owner','outsider') else None
    world.page.wait_for_function('() => Boolean(window.WorkspaceAdmin && document.querySelector("#workspaceStatus").textContent!=="작업공간 목록을 불러오는 중입니다.")')


def make_space(world,owner='owner',name='Private design'):
    response=world.client.post(BASE,headers=world.headers['owner'],json={'name':name,'owner_id':world.users[owner]})
    assert response.status_code==200,response.text
    return response.json()['workspace']


def make_draft(world,ws,name='Offline design'):
    response=world.client.post(BASE+'/'+ws['id']+'/drafts',headers=world.headers['owner'],json={'name':name,'description':'A private design only','definition':{'nodes':[],'edges':[]}})
    assert response.status_code==200,response.text
    return response.json()['draft']


def make_snapshot(world,ws,draft):
    response=world.client.post(BASE+'/'+ws['id']+'/drafts/'+draft['id']+'/snapshots',headers=world.headers['owner'],json={'draft_revision':draft['revision']})
    assert response.status_code==200,response.text
    return response.json()['snapshot']


def member(world,ws,person,role):
    response=world.client.post(BASE+'/'+ws['id']+'/members',headers=world.headers['owner'],json={'user_id':world.users[person],'role':role,'active':True,'revision':0})
    assert response.status_code==200,response.text
    return response.json()['member']


def select_space(world,ws):
    world.page.locator('#workspaceSelect').select_option(ws['id'])
    expect(world.page.locator('#workspaceSummary')).to_contain_text(ws['name'])
    expect(world.page.locator('#workspaceDraftList')).not_to_be_empty()


def open_snapshot(world,ws,draft):
    world.page.locator('#workspaceDraftList').get_by_role('button',name='저장본 보기').click()
    expect(world.page.locator('#workspaceSnapshotDialog')).to_be_visible()
    world.page.locator('#workspaceSnapshotList').get_by_role('button',name='저장본 열기').click()
    expect(world.page.locator('#workspaceSnapshotPreview')).to_be_visible()


def test_provision_save_snapshot_download_and_revoke_are_private_only(workspace_browser):
    w=workspace_browser;page=w.page;before=w.store.query('SELECT COUNT(*) FROM agent_workflows')[0][0]
    sign_in(w);page.locator('#workspaceCreate').click();expect(page.locator('#workspaceCreateDialog')).to_be_visible()
    page.locator('#workspaceName').fill('Research team');page.locator('#workspaceCreateSave').click()
    expect(page.locator('#workspaceCreateDialog')).not_to_be_visible();expect(page.locator('#workspaceSelect option')).to_have_count(2)
    ws={'id':page.locator('#workspaceSelect option').nth(1).get_attribute('value'),'name':'Research team'};select_space(w,ws)
    page.locator('#workspaceDraftCreate').click();expect(page.locator('#workspaceDraftDefinition')).to_have_value('{"nodes":[],"edges":[]}')
    page.locator('#workspaceDraftName').fill('Private first draft');page.locator('#workspaceDraftSave').click()
    expect(page.locator('#workspaceDraftDialog')).not_to_be_visible();expect(page.locator('#workspaceDraftList')).to_contain_text('Private first draft')
    page.locator('#workspaceDraftList').get_by_role('button',name='저장본 보기').click();expect(page.locator('#workspaceSnapshotSave')).to_be_enabled();page.locator('#workspaceSnapshotSave').click()
    page.locator('#workspaceSnapshotList').get_by_role('button',name='저장본 열기').click();expect(page.locator('#workspaceSnapshotPreview')).to_contain_text('Private first draft')
    with page.expect_download() as pending:page.locator('#workspaceSnapshotDownload').click()
    artifact=json.loads(Path(pending.value.path()).read_bytes());assert artifact['snapshot']['definition']=={'nodes':[],'edges':[]}
    assert artifact['saved_snapshot'] and not any(artifact[key] for key in ('executable','deployable','published'))
    assert not {'signature','token','session_ref','run_key'} & set(artifact)
    page.on('dialog',lambda dialog:dialog.accept());page.locator('#workspaceSnapshotRevoke').click()
    expect(page.locator('#workspaceSnapshotStatus')).to_contain_text('철회');expect(page.locator('#workspaceSnapshotDownload')).to_be_disabled();expect(page.locator('#workspaceSnapshotPreview')).not_to_be_visible()
    assert w.store.query('SELECT COUNT(*) FROM agent_workflows')[0][0]==before and w.store.query('SELECT COUNT(*) FROM workflow_runs')[0][0]==0
    assert not w.errors and not w.external


@pytest.mark.parametrize('person,role,editable,manageable',[('editor','editor',True,False),('viewer','viewer',False,False),('operator','editor',False,False)])
def test_current_membership_and_operator_ceiling_control_visible_actions(workspace_browser,person,role,editable,manageable):
    w=workspace_browser;ws=make_space(w);member(w,ws,person,role);saved=make_draft(w,ws);make_snapshot(w,ws,saved)
    sign_in(w,person);select_space(w,ws)
    assert w.page.locator('#workspaceDraftCreate').is_enabled()==editable
    assert w.page.locator('#workspaceMembers').is_enabled()==manageable
    assert w.page.locator('#workspaceArchive').is_enabled()==manageable
    w.page.locator('#workspaceDraftList').get_by_role('button',name='초안 편집' if editable else '초안 보기').click()
    expect(w.page.locator('#workspaceDraftName')).to_have_value(saved['name'])
    assert w.page.locator('#workspaceDraftDefinition').get_attribute('readonly') == (None if editable else '')
    assert w.page.locator('#workspaceDraftSave').is_enabled()==editable
    assert not w.errors and not w.external


def test_superadmin_without_membership_has_no_private_content(workspace_browser):
    w=workspace_browser;ws=make_space(w);saved=make_draft(w,ws)
    sign_in(w,'outsider');expect(w.page.locator('#workspaceSelect option')).to_have_count(1);expect(w.page.locator('#workspaceContent')).not_to_be_visible()
    assert saved['name'] not in w.page.locator('#workspacePanel').inner_text()
    assert not any(path.endswith('/'+ws['id']) for method,path,_ in w.requests if method=='GET')


def test_owner_can_register_an_existing_member_with_explicit_role(workspace_browser):
    w=workspace_browser;ws=make_space(w);sign_in(w);select_space(w,ws)
    w.page.locator('#workspaceMembers').click();expect(w.page.locator('#workspaceMemberDialog')).to_be_visible()
    w.page.locator('#workspaceMemberUser').fill(str(w.users['editor']));w.page.locator('#workspaceMemberRole').select_option('editor');w.page.locator('#workspaceMemberSave').click()
    expect(w.page.locator('#workspaceMemberDialog')).not_to_be_visible()
    row=w.client.get(BASE+'/'+ws['id']+'/members',headers=w.headers['owner']).json()['members'][-1]
    assert row['user_id']==w.users['editor'] and row['role']=='editor' and row['revision']==1
    assert not w.errors


def test_untrusted_names_and_snapshot_json_are_text_only_under_nonce_csp(workspace_browser):
    w=workspace_browser;attack='<img src=x onerror=alert(1)>';ws=make_space(w,name=attack);saved=make_draft(w,ws,name=attack);make_snapshot(w,ws,saved)
    sign_in(w);select_space(w,ws);open_snapshot(w,ws,saved)
    expect(w.page.locator('#workspaceSnapshotPreview')).to_contain_text(attack)
    assert w.page.locator('#workspacePanel img, #workspaceSnapshotDialog img').count()==0
    assert not w.errors and not w.external
    REPORT.mkdir(parents=True,exist_ok=True);w.page.set_viewport_size({'width':1280,'height':1000});w.page.screenshot(path=str(REPORT/'private-snapshot-dialog.png'))
    box=w.page.locator('#workspaceSnapshotDialog').bounding_box();assert box and abs(box['x']+box['width']/2-640)<2 and box['y']>=0


@pytest.mark.parametrize('raw',['{"nodes":[],"nodes":[],"edges":[]}','{"nodes":[],"no\\u0064es":[],"edges":[]}'])
def test_raw_nested_duplicate_definition_keys_reach_strict_server_without_becoming_success(workspace_browser,raw):
    w=workspace_browser;ws=make_space(w);sign_in(w);select_space(w,ws);w.page.locator('#workspaceDraftCreate').click()
    w.page.locator('#workspaceDraftName').fill('Duplicate test');w.page.locator('#workspaceDraftDefinition').fill(raw)
    with w.page.expect_response('**/'+ws['id']+'/drafts') as response:w.page.locator('#workspaceDraftSave').click()
    assert response.value.status==400
    expect(w.page.locator('#workspaceDraftStatus')).to_contain_text('요청을 완료하지 못했습니다')
    assert w.store.query('SELECT COUNT(*) FROM workspace_drafts')[0][0]==0
    assert raw in next(body for method,path,body in reversed(w.requests) if method=='POST' and path.endswith('/drafts'))


def test_stale_draft_revision_does_not_overwrite_saved_content(workspace_browser):
    w=workspace_browser;ws=make_space(w);saved=make_draft(w,ws);sign_in(w);select_space(w,ws)
    w.page.locator('#workspaceDraftList').get_by_role('button',name='초안 편집').click();expect(w.page.locator('#workspaceDraftName')).to_have_value(saved['name'])
    update={key:saved[key] for key in ('id','name','description','definition','revision')};update['name']='Other writer'
    assert w.client.post(BASE+'/'+ws['id']+'/drafts',headers=w.headers['owner'],json=update).status_code==200
    w.page.locator('#workspaceDraftName').fill('Stale browser');w.page.locator('#workspaceDraftSave').click()
    expect(w.page.locator('#workspaceDraftStatus')).to_contain_text('버전이 변경')
    assert w.client.get(BASE+'/'+ws['id']+'/drafts/'+saved['id'],headers=w.headers['owner']).json()['draft']['name']=='Other writer'
    assert not w.errors


@pytest.mark.parametrize('action',['close','escape','selection','role','token','logout'])
def test_late_artifact_never_downloads_after_scope_or_session_changes(workspace_browser,action):
    w=workspace_browser;ws=make_space(w);other=make_space(w,name='Other team');saved=make_draft(w,ws);version=make_snapshot(w,ws,saved)
    sign_in(w);select_space(w,ws);open_snapshot(w,ws,saved);pending=[];downloads=[]
    def hold(route):pending.append(route);w.page.evaluate('window.__artifactHeld=true')
    w.page.route('**/snapshots/'+version['id']+'/artifact',hold);w.page.on('download',lambda value:downloads.append(value));w.page.locator('#workspaceSnapshotDownload').click();w.page.wait_for_function('() => window.__artifactHeld===true')
    if action=='close':w.page.locator('#workspaceSnapshotClose').click()
    elif action=='escape':w.page.keyboard.press('Escape')
    elif action=='selection':w.page.evaluate('id=>{const el=document.querySelector("#workspaceSelect");el.value=id;el.dispatchEvent(new Event("change"));}',other['id'])
    elif action=='role':w.page.evaluate('()=>{currentUser.role="operator";updateUserUI(currentUser,false);}')
    elif action=='token':w.page.evaluate('()=>{token="rotated-session";updateUserUI(currentUser,false);}')
    else:
        w.page.route('**/admin/api/auth/logout',lambda route:None);w.page.on('dialog',lambda dialog:dialog.accept());w.page.evaluate('document.querySelector("#logoutBtn").click()')
    artifact=w.client.get(BASE+'/'+ws['id']+'/drafts/'+saved['id']+'/snapshots/'+version['id']+'/artifact',headers=w.headers['owner'])
    assert artifact.status_code==200
    pending[0].fulfill(status=200,content_type='application/json',body=artifact.content)
    w.page.wait_for_function('() => !document.querySelector("#workspaceSnapshotDialog").open')
    assert not downloads and w.page.locator('#workspaceSnapshotPreview').inner_text()==''
    assert not w.errors


def test_private_404_clears_open_content_after_membership_withdrawal(workspace_browser):
    w=workspace_browser;ws=make_space(w);member(w,ws,'editor','editor');saved=make_draft(w,ws);make_snapshot(w,ws,saved)
    sign_in(w,'editor');select_space(w,ws);open_snapshot(w,ws,saved)
    assert w.client.post(BASE+'/'+ws['id']+'/members',headers=w.headers['owner'],json={'user_id':w.users['editor'],'role':'editor','active':False,'revision':1}).status_code==200
    w.page.locator('#workspaceSnapshotDownload').click();expect(w.page.locator('#workspaceSnapshotDialog')).not_to_be_visible();expect(w.page.locator('#workspaceContent')).not_to_be_visible()
    expect(w.page.locator('#workspaceStatus')).to_contain_text('권한 또는 세션')
    assert w.page.locator('#workspaceSnapshotPreview').inner_text()==''


def test_delayed_workspace_response_cannot_replace_new_selected_scope(workspace_browser):
    w=workspace_browser;first=make_space(w,name='Earlier team');second=make_space(w,name='Current team');make_draft(w,second);sign_in(w);pending=[]
    def hold(route):pending.append(route);w.page.evaluate('window.__workspaceHeld=true')
    w.page.route('**'+BASE+'/'+first['id'],hold);w.page.locator('#workspaceSelect').select_option(first['id']);w.page.wait_for_function('() => window.__workspaceHeld===true')
    w.page.locator('#workspaceSelect').select_option(second['id']);expect(w.page.locator('#workspaceSummary')).to_contain_text(second['name'])
    pending[0].fulfill(status=200,content_type='application/json',body=json.dumps({'ok':True,'profile':'workspace-private-snapshots-v1','workspace':first}))
    expect(w.page.locator('#workspaceSummary')).to_contain_text(second['name']);assert first['name'] not in w.page.locator('#workspaceSummary').inner_text()
    assert not w.errors


def test_old_backend_options_disables_mutations_and_auto_refresh_keeps_forms(workspace_browser):
    w=workspace_browser;ws=make_space(w);sign_in(w);select_space(w,ws);w.page.locator('#workspaceDraftCreate').click();w.page.locator('#workspaceDraftName').fill('Unsaved form')
    w.page.evaluate('refresh(true)');expect(w.page.locator('#workspaceDraftName')).to_have_value('Unsaved form');expect(w.page.locator('#workspaceDraftDialog')).to_be_visible()
    w.page.locator('#workspaceDraftClose').click();w.page.route('**'+BASE+'/options',lambda route:route.fulfill(status=404,content_type='application/json',body='{"detail":"Not Found"}'))
    w.page.locator('#workspaceRefresh').click();expect(w.page.locator('#workspaceStatus')).to_contain_text('현재 서버에서는')
    expect(w.page.locator('#workspaceCreate')).not_to_be_visible();expect(w.page.locator('#workspaceDraftCreate')).to_be_disabled()
    assert not w.errors
