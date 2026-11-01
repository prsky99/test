"""Real Chromium component journeys against isolated authenticated APIs."""
# ruff: noqa: F401,F811
from pathlib import Path
import re
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient
from playwright.sync_api import expect

from agent_market.customer_identity_service import router_for as identity_router
from agent_market.workspace_admin_service import BASE,router_for,script_response
from agent_market.workspace_admin_events import drain
from tests.test_front_workflow_browser import browser
from tests.test_workspace_admin_control import operations,case_body
from tests.test_customer_organizations import orgs
from tests.test_workspace_access import draft_body
from tests.test_owned_data_agents import engine
from tests.test_owned_data_agents_activation import operating

import pytest  # noqa: E402
pytestmark = pytest.mark.usefixtures('rotated_bootstrap_admin')


def browser_context(browser,app,url):
    client=TestClient(app,base_url=url)
    context=browser.new_context(viewport={'width':1500,'height':1000})
    errors=[];external=[]
    def serve(route):
        request=route.request;parsed=urlsplit(request.url)
        if parsed.hostname!=urlsplit(url).hostname:
            external.append(request.url);route.abort();return
        result=client.request(request.method,parsed.path+('?' + parsed.query if parsed.query else ''),headers=request.headers,content=request.post_data)
        route.fulfill(status=result.status_code,body=result.content,headers={k:v for k,v in result.headers.items()
            if k not in ('content-length','content-encoding','transfer-encoding')})
    context.route('**/*',serve)
    page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
    return client,context,page,errors,external


def test_admin_customer_timeline_case_and_reviewed_credit_correction(browser,operations):
    w=operations;app=FastAPI();app.include_router(router_for(w.core,w.access,core=w.ops))
    html=Path('agent_market/gateway/dashboard.html').read_text()
    panel=re.search(r'<section data-panel="workspace_operations".*?</section>',html,re.S)[0]
    @app.get('/')
    def page():
        return HTMLResponse('<!doctype html><html lang="en"><head><title>Workspace operations test</title><style nonce="fixture">body{font:15px sans-serif;padding:24px}table{border-collapse:collapse;width:100%}td,th{padding:9px;text-align:left;border-bottom:1px solid #ccc}button,input,select,textarea{padding:8px;margin:4px}dialog{background:white!important;color:black!important}label{display:block}</style></head><body>'+panel+
            '<script nonce="fixture">let token="'+('a'*64)+'";let currentUser={user_id:1,role:"superadmin"};const state={tab:"workspace_operations"};</script>'+
            '<script nonce="fixture" src="/admin/assets/workspace-operations-admin.js"></script><script nonce="fixture">WorkspaceOperationsAdmin.load();</script></body></html>',
            headers={'Content-Security-Policy':"default-src 'none';script-src 'nonce-fixture';style-src 'nonce-fixture' 'unsafe-inline';connect-src 'self';frame-ancestors 'none'"})
    @app.get('/admin/assets/workspace-operations-admin.js')
    def script():return script_response()
    # Single-approver review is allowed only when one superadmin is active (design 4.3).
    with w.core.tx() as db:db.execute('UPDATE admin_users SET active=0 WHERE id=5')
    client,context,page,errors,external=browser_context(browser,app,'https://admin.test')
    try:
        drain(w.store);page.goto('https://admin.test/')
        expect(page.locator('#workspaceOpsContent')).to_contain_text('워크스페이스 운영 현황')
        page.locator('#workspaceOpsSearch').fill(w.customers[0].customer_id)
        page.locator('#workspaceOpsSearch').press('Enter')
        page.get_by_role('button',name='고객 상세',exact=True).click()
        expect(page.locator('dialog')).to_contain_text('3')
        page.get_by_role('button',name='관리 조치 요청',exact=True).click()
        page.get_by_label('조치',exact=True).select_option('credit_adjust')
        page.get_by_label('크레딧 증감',exact=True).fill('2')
        page.get_by_label('근거와 사유',exact=True).fill('Verified synthetic browser correction')
        page.get_by_label('이 고객·현재 상태·요청 내용을 확인했습니다').check()
        page.get_by_role('button',name='승인 대기 조치 등록').click()
        expect(page.locator('dialog')).to_contain_text('승인 대기')
        page.get_by_role('button',name='닫기',exact=True).click()
        page.locator('[data-ops-tab="commands"]').click()
        page.get_by_role('button',name='검토·승인').click()
        expect(page.locator('dialog')).to_contain_text('크레딧 증감: 2')
        page.get_by_label('검토 사유',exact=True).fill('Reviewed exact synthetic browser command')
        page.get_by_label('대상과 아래 조치 내용을 확인했고 적용합니다').check()
        page.get_by_label('단독 검토임을 확인합니다.',exact=False).check()
        page.get_by_role('button',name='확인한 단건 조치 적용').click()
        expect(page.locator('#workspaceOpsContent')).to_contain_text('applied')
        assert w.ops.credits.status(w.customers[0])['balance']==102
        folder=Path('reports/workspace-admin-control-2026-10-21');folder.mkdir(exist_ok=True,parents=True)
        page.screenshot(path=str(folder/'admin-reviewed-command.png'),full_page=True)
        assert not errors and not external
    finally:context.close();client.close()


def test_customer_support_safe_messages_reply_and_internal_note_exclusion(browser,operations):
    w=operations;app=FastAPI();app.include_router(identity_router(w.store,b'synthetic-customer-key-32bytes!!!',identity=w.core,admin=False))
    app.include_router(router_for(w.core,w.access,core=w.ops,public=True))
    client,context,page,errors,external=browser_context(browser,app,'https://customer.test')
    context.add_cookies([{'name':'__Host-ac_customer_session','value':w.auths[0]['session_token'],
        'url':'https://customer.test','secure':True,'httpOnly':True,'sameSite':'Lax'}])
    try:
        page.goto('https://customer.test/customer/support')
        expect(page.locator('#support-content')).to_be_visible()
        page.get_by_label('Subject',exact=True).fill('Workflow credit support')
        page.get_by_label('Message',exact=True).fill('<img src=x onerror="window.hostile=true"> Please review this workflow.')
        page.get_by_role('button',name='Send request',exact=True).click()
        expect(page.locator('#support-title')).to_have_text('Workflow credit support')
        assert not page.evaluate('Boolean(window.hostile)')
        case=w.ops.cases(w.staff[1])['cases'][0]
        note={'revision':1,'status':'waiting_internal','priority':'normal','assigned_to':1,
            'message':'INTERNAL ONLY synthetic note','visibility':'internal','request_id':'b'*32}
        w.ops.case_action(w.staff[1],case['id'],note)
        page.get_by_role('button',name='Refresh',exact=True).click()
        expect(page.locator('#support-messages')).not_to_contain_text('INTERNAL ONLY')
        page.get_by_label('Reply',exact=True).fill('Thank you. Please continue the review.')
        page.get_by_role('button',name='Send reply',exact=True).click()
        expect(page.locator('#support-messages')).to_contain_text('Please continue the review.')
        folder=Path('reports/workspace-admin-control-2026-10-21');page.screenshot(path=str(folder/'customer-support.png'),full_page=True)
        assert not errors and not external
    finally:context.close();client.close()


def test_full_admin_navigation_nonce_dialog_refresh_and_session_clear(browser,operating):
    import time
    from types import SimpleNamespace
    from agent_market.gateway.dashboard import dashboard_router
    from agent_market.workspace_platform import platform_for
    from agent_market.workspace_admin_events import migrate
    front=operating[0];graph=platform_for(front)
    from scripts.workspace_admin_control import identity_key_from_workflow_root
    from agent_market.concierge.task_updates import TaskUpdates
    assert identity_key_from_workflow_root(TaskUpdates._load_key(front.workflows))==graph.identity.key
    migrate(front.store,graph.identity.key)
    customer='cu_'+'8'*32
    with front.store.tx() as db:
        db.execute('INSERT INTO customer_identities VALUES(?,?,?,1,1,?,?)',
            (customer,'https://accounts.google.com','synthetic-workspace-customer',time.time(),time.time()))
    app=FastAPI();app.include_router(dashboard_router(front.store,front.store._path,'fixture-browser',None,
        front=front,ssl_manager=SimpleNamespace(get_status=lambda:{})))
    client,context,page,errors,external=browser_context(browser,app,'https://admin.test')
    try:
        page.goto('https://admin.test/admin/ui')
        page.locator('#adminLoginUsername').fill('sadmin');page.locator('#adminLoginPassword').fill('sadmin')
        page.locator('#adminLoginSubmitBtn').click();expect(page.locator('#adminLoginModal')).to_be_hidden()
        page.locator('[data-tab="workspace_operations"]').click()
        expect(page.locator('#workspaceOpsContent')).to_contain_text('워크스페이스 운영 현황')
        page.locator('[data-ops-tab="customers"]').click()
        page.get_by_role('button',name='고객 상세',exact=True).click()
        expect(page.locator('dialog[open]')).to_contain_text(customer)
        page.evaluate('WorkspaceOperationsAdmin.load()')
        expect(page.locator('dialog[open]')).to_contain_text(customer)
        page.screenshot(path='reports/workspace-admin-control-2026-10-21/full-admin-customer-detail.png',full_page=True)
        page.evaluate('token="expired-synthetic-session";currentUser=null')
        expect(page.locator('dialog[open]')).to_have_count(0)
        expect(page.locator('#workspaceOpsContent')).to_be_empty()
        assert not errors and not external
    finally:context.close();client.close()


def test_customer_explicit_draft_sharing_and_withdrawal(browser,operations):
    from agent_market.workspace_access import WorkspaceDenied
    import pytest
    w=operations;actor=w.customers[0];ws=w.organization['id']
    draft=w.orgs.drafts.save_draft(ws,draft_body(),w.orgs.runtime_actor(ws,actor))
    app=FastAPI();app.include_router(identity_router(w.store,b'synthetic-customer-key-32bytes!!!',identity=w.core,admin=False))
    app.include_router(router_for(w.core,w.access,core=w.ops,public=True))
    client,context,page,errors,external=browser_context(browser,app,'https://customer.test')
    context.add_cookies([{'name':'__Host-ac_customer_session','value':w.auths[0]['session_token'],
        'url':'https://customer.test','secure':True,'httpOnly':True,'sameSite':'Lax'}])
    try:
        page.goto('https://customer.test/customer/support');expect(page.locator('#support-content')).to_be_visible()
        page.get_by_label('Workspace',exact=True).select_option(ws)
        page.get_by_label('Subject',exact=True).fill('Review a draft')
        page.get_by_label('Message',exact=True).fill('Please review this exact revision.')
        page.get_by_role('button',name='Send request',exact=True).click()
        expect(page.locator('#support-sharing')).to_be_visible()
        page.get_by_label('Draft',exact=True).select_option(draft['id'])
        page.get_by_label('I authorize support to read this draft revision for this request.',exact=True).check()
        page.get_by_role('button',name='Share for 15 minutes',exact=True).click()
        expect(page.get_by_role('button',name='Withdraw access',exact=True)).to_be_visible()
        grant=w.ops.disclosures(w.staff[1],actor.customer_id)['disclosures'][0]
        assert w.ops.disclosure_read(w.staff[1],grant['id'])['draft']['id']==draft['id']
        page.get_by_role('button',name='Withdraw access',exact=True).click()
        expect(page.get_by_role('button',name='Withdraw access',exact=True)).to_have_count(0)
        with pytest.raises(WorkspaceDenied):w.ops.disclosure_read(w.staff[1],grant['id'])
        w.core.logout(w.auths[0]['session_token'])
        page.get_by_role('button',name='Refresh',exact=True).click()
        page.wait_for_url('**/customer/sign-in?*')
        expect(page.locator('#status')).to_have_text('Your session expired. Sign in again to continue.')
        from urllib.parse import parse_qs
        query=parse_qs(urlsplit(page.url).query)
        assert query=={'next':['/customer/support']}
        expect(page.locator('#support-content')).to_have_count(0)
        expect(page.locator('#support-messages')).to_have_count(0)
        assert not errors and not external
    finally:context.close();client.close()


def test_renewed_console_reviews_command_with_a_different_superadmin(browser,operations):
    from fastapi.responses import FileResponse
    w=operations
    item=w.ops.command(w.staff[2],{'customer_id':w.customers[0].customer_id,'kind':'credit_adjust','target_revision':1,
        'delta':2,'credit_status':'active','reason':'Synthetic renewed console request','request_id':'c'*32})
    # The renewed shell and its modules are static; only the workspace operations API is real here.
    assets=Path('agent_market/gateway/admin_next');me={'username':'synthetic-1','role':'superadmin','name':'Synthetic member'}
    app=FastAPI();app.include_router(router_for(w.core,w.access,core=w.ops))
    @app.get('/admin/next')
    def shell():return HTMLResponse((assets/'index.html').read_text())
    @app.get('/admin/next/assets/{path:path}')
    def asset(path:str):return FileResponse(assets/path,media_type='text/css' if path.endswith('.css') else 'text/javascript')
    @app.get('/admin/api/v2/auth/me')
    def who():return {'user':me}
    @app.get('/admin/api/v2/home/bootstrap')
    def boot():return {'me':me,'overview':{},'gateway':{},'alerts':[]}
    @app.get('/admin/api/v2/home/changes')
    def changes():return {'version':0,'tags':[]}
    client,context,page,errors,external=browser_context(browser,app,'https://admin.test')
    try:
        context.add_init_script("sessionStorage.setItem('adminToken','"+'a'*64+"')")
        page.goto('https://admin.test/admin/next#/customers/commands')
        row=page.locator('.adm-table tbody tr').first
        expect(row).to_contain_text('크레딧 조정')
        expect(row).to_contain_text('분 남음')
        row.click()
        expect(page.locator('.adm-drawer')).to_contain_text('Synthetic renewed console request')
        page.get_by_role('button',name='검토 후 적용',exact=True).click()
        dialog=page.locator('dialog.adm-dialog')
        expect(dialog.locator('#adm-ack')).to_have_count(0)
        dialog.locator('textarea').fill('Reviewed by a different superadmin')
        dialog.get_by_role('button',name='적용',exact=True).click()
        expect(page.locator('.adm-toast')).to_contain_text('적용했습니다')
        expect(page.locator('.adm-table tbody tr').first).to_contain_text('적용됨')
        assert w.ops.credits.status(w.customers[0])['balance']==102
        assert [x for x in w.ops.commands(w.staff[1])['commands'] if x['id']==item['command_id']][0]['approved_by']==1
        assert not errors and not external
    finally:context.close();client.close()


def test_renewed_console_answers_a_support_case_and_keeps_internal_notes_private(browser,operations):
    from fastapi.responses import FileResponse
    w=operations
    case=w.ops.create_case(w.staff[1],w.customers[0].customer_id,case_body())['case']
    # The renewed shell and its modules are static; only the workspace operations API is real here.
    assets=Path('agent_market/gateway/admin_next');me={'username':'synthetic-1','role':'superadmin','name':'Synthetic member'}
    app=FastAPI();app.include_router(router_for(w.core,w.access,core=w.ops))
    @app.get('/admin/next')
    def shell():return HTMLResponse((assets/'index.html').read_text())
    @app.get('/admin/next/assets/{path:path}')
    def asset(path:str):return FileResponse(assets/path,media_type='text/css' if path.endswith('.css') else 'text/javascript')
    @app.get('/admin/api/v2/auth/me')
    def who():return {'user':me}
    @app.get('/admin/api/v2/home/bootstrap')
    def boot():return {'me':me,'overview':{},'gateway':{},'alerts':[]}
    @app.get('/admin/api/v2/home/changes')
    def changes():return {'version':0,'tags':[]}
    client,context,page,errors,external=browser_context(browser,app,'https://admin.test')
    try:
        context.add_init_script("sessionStorage.setItem('adminToken','"+'a'*64+"')")
        page.goto('https://admin.test/admin/next#/customers/cases')
        page.locator('.adm-table tbody tr',has_text='Credit question').click()
        drawer=page.locator('.adm-drawer')
        expect(drawer).to_contain_text('Please review this saved workflow.')
        drawer.get_by_label('공개 범위').select_option('internal')
        drawer.get_by_label('보낼 메시지').fill('<b>Internal</b> synthetic triage note')
        drawer.get_by_role('button',name='내부 메모 저장').click()
        expect(drawer.locator('li[data-visibility=internal]')).to_contain_text('<b>Internal</b> synthetic triage note')
        drawer.get_by_label('상태').select_option('waiting_customer')
        drawer.get_by_label('공개 범위').select_option('customer')
        drawer.get_by_label('보낼 메시지').fill('We checked your workflow and need one detail.')
        drawer.get_by_role('button',name='고객에게 보내기').click()
        expect(drawer).to_contain_text('고객 답변 대기')
        detail=w.ops.case(w.staff[1],case['id'])
        assert detail['case']['status']=='waiting_customer' and detail['case']['revision']==3
        assert [m['visibility'] for m in detail['messages']]==['customer','internal','customer']
        assert not page.evaluate("document.querySelector('.adm-drawer b')")  # bodies render as text
        assert not errors and not external
    finally:context.close();client.close()


def test_renewed_console_requests_a_credit_correction_for_review(browser,operations):
    from fastapi.responses import FileResponse
    w=operations;customer=w.customers[0].customer_id
    # The renewed shell and its modules are static; only the workspace operations API is real here.
    assets=Path('agent_market/gateway/admin_next');me={'username':'synthetic-1','role':'superadmin','name':'Synthetic member'}
    app=FastAPI();app.include_router(router_for(w.core,w.access,core=w.ops))
    @app.get('/admin/next')
    def shell():return HTMLResponse((assets/'index.html').read_text())
    @app.get('/admin/next/assets/{path:path}')
    def asset(path:str):return FileResponse(assets/path,media_type='text/css' if path.endswith('.css') else 'text/javascript')
    @app.get('/admin/api/v2/auth/me')
    def who():return {'user':me}
    @app.get('/admin/api/v2/home/bootstrap')
    def boot():return {'me':me,'overview':{},'gateway':{},'alerts':[]}
    @app.get('/admin/api/v2/home/changes')
    def changes():return {'version':0,'tags':[]}
    client,context,page,errors,external=browser_context(browser,app,'https://admin.test')
    try:
        context.add_init_script("sessionStorage.setItem('adminToken','"+'a'*64+"')")
        page.goto('https://admin.test/admin/next#/customers/customers?customer='+customer)
        drawer=page.locator('.adm-drawer')
        drawer.locator('summary',has_text='관리 조치 요청').click()
        drawer.get_by_label('조치 종류').select_option('credit_adjust')
        drawer.get_by_label('크레딧 증감').fill('2')
        drawer.get_by_label('근거와 사유').fill('Verified synthetic correction')
        drawer.get_by_role('button',name='승인 대기 조치 등록').click()
        expect(drawer.locator('.adm-status')).to_contain_text('확인 항목')
        drawer.locator('#adm-command-confirm').check()
        drawer.get_by_role('button',name='승인 대기 조치 등록').click()
        expect(page.locator('.adm-toast')).to_contain_text('승인 대기 조치를 등록했습니다')
        command=w.ops.commands(w.staff[1])['commands'][0]
        assert command['kind']=='credit_adjust' and command['status']=='pending' and command['requested_by']==1
        assert w.ops.credits.status(w.customers[0])['balance']==100  # nothing applied until a different superadmin reviews
        review=w.ops.command_detail(w.staff[1],command['id'])['review']
        assert review['delta']==2 and review['customer_id']==customer
        assert not errors and not external
    finally:context.close();client.close()


def test_renewed_console_reads_only_customer_shared_draft_with_two_step_confirmation(browser,operations):
    from fastapi.responses import FileResponse
    w=operations;actor=w.customers[0];ws=w.organization['id'];customer=actor.customer_id
    draft=w.orgs.drafts.save_draft(ws,draft_body(),w.orgs.runtime_actor(ws,actor))
    case=w.ops.create_case(w.staff[1],customer,case_body(workspace_id=ws))['case']
    grant=w.ops.disclosure(actor,case['id'],{'workspace_id':ws,'draft_id':draft['id'],'ttl_seconds':900,'confirm':'SHARE'})
    # The renewed shell and its modules are static; only the workspace operations API is real here.
    assets=Path('agent_market/gateway/admin_next');me={'username':'synthetic-1','role':'superadmin','name':'Synthetic member'}
    app=FastAPI();app.include_router(router_for(w.core,w.access,core=w.ops))
    @app.get('/admin/next')
    def shell():return HTMLResponse((assets/'index.html').read_text())
    @app.get('/admin/next/assets/{path:path}')
    def asset(path:str):return FileResponse(assets/path,media_type='text/css' if path.endswith('.css') else 'text/javascript')
    @app.get('/admin/api/v2/auth/me')
    def who():return {'user':me}
    @app.get('/admin/api/v2/home/bootstrap')
    def boot():return {'me':me,'overview':{},'gateway':{},'alerts':[]}
    @app.get('/admin/api/v2/home/changes')
    def changes():return {'version':0,'tags':[]}
    client,context,page,errors,external=browser_context(browser,app,'https://admin.test')
    try:
        context.add_init_script("sessionStorage.setItem('adminToken','"+'a'*64+"')")
        page.goto('https://admin.test/admin/next#/customers/customers?customer='+customer)
        drawer=page.locator('.adm-drawer')
        drawer.locator('summary',has_text='고객 공유 자료').click()
        expect(drawer).to_contain_text('열람 가능')
        drawer.get_by_role('button',name='승인된 자료 열람').click()
        expect(drawer.get_by_role('button',name='열람 확인(감사 기록)')).to_be_visible()
        expect(drawer.locator('pre')).to_have_count(0)  # nothing read on the first press
        drawer.get_by_role('button',name='열람 확인(감사 기록)').click()
        expect(drawer.locator('pre')).to_be_visible()
        assert any(row['action']=='disclosure.read' for row in w.ops.audits(w.staff[1])['audit'])
        identity=grant.get('id') or grant.get('disclosure',{}).get('id') or w.ops.disclosures(w.staff[1],customer)['disclosures'][0]['id']
        revision=w.ops.disclosures(w.staff[1],customer)['disclosures'][0]['revision']
        w.ops.disclosure_revoke(actor,identity,{'revision':revision})
        page.reload()
        drawer.locator('summary',has_text='고객 공유 자료').click()
        expect(drawer).to_contain_text('고객이 철회')
        expect(drawer.get_by_role('button',name='승인된 자료 열람')).to_have_count(0)
        assert not errors and not external
    finally:context.close();client.close()
