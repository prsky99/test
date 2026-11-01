"""Release panel migration: isolated grants, downloads, revocation and delivery consent."""
# ruff: noqa: F401,F811
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote
from zipfile import ZipFile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from agent_market.workspace_admin_specialists import router_for as aliases, RENEWAL
from agent_market.workspace_service import router_for as workspaces
from agent_market.workspace_release_service import router_for as releases
from agent_market.workspace_typed_release_service import router_for as typed_releases
from agent_market.workspace_typed_flow_service import router_for as flows
from agent_market.workspace_machine_update_service import router_for as machine_routes
from agent_market.workflows import runtime_for
from tests.test_workspace_release_v2 import release_world
from tests.test_workspace_execution_api import private_api
from tests.test_workspace_typed_release import typed_release_world
from tests.test_workspace_typed_flows import typed_world
from tests.test_workflow_fallback import routing
from tests.test_provider_claims import provider
from tests.test_workspace_machine_updates import machine
from tests.test_front_workflow_browser import browser
from tests.test_admin_specialist_panels import shell
from tests.test_workspace_admin_browser import browser_context


@pytest.fixture(params=['release', 'typed-release'])
def release_panel(request):
    kind = request.param
    x = request.getfixturevalue('release_world' if kind == 'release' else 'typed_release_world')
    app = FastAPI()
    if kind == 'release':
        w = x.w; ws = w.ws['id']; access = x.access; execution = x.staff
        headers = w.headers['owner']; actor = x.actor
        source = releases(x.releases, x.lifecycle, public=False)
        suffix = f'/drafts/{x.args[1]}/snapshots/{x.args[2]}/release-v2'
        run = x.result['id']
    else:
        w = x.w; ws = w.ws; access = w.access; execution = w.execution
        headers = {'Authorization':'Bearer '+w.raw,'X-Dashboard':'1'}; actor = w.actor
        source = typed_releases(x.releases, public=False)
        app.include_router(flows(w.core)); app.include_router(aliases(w.store, flows(w.core)))
        suffix = f'/typed-flows/{x.args[1]}/versions/{x.args[2]}/release-v2'
        run = x.result['id']
    app.include_router(workspaces(w.store, runtime_for(w.store).key, access=access, execution=execution))
    app.include_router(source); app.include_router(aliases(w.store, source))
    obj = SimpleNamespace(app=app, kind=kind, store=w.store, actor=actor, ws=ws, run=run, x=x,
        headers=headers, raw=headers['Authorization'][7:], url=RENEWAL+'/'+ws+suffix,
        reason={**headers, 'X-Admin-Reason': quote('Synthetic release and scoped deployment test')})
    obj.client = TestClient(app, base_url='https://admin.test'); shell(obj)
    yield obj
    obj.client.close()


def test_release_alias_guards_download_and_revocation(release_panel):
    w = release_panel; c = w.client
    assert c.get(w.url+'/options').status_code == 401
    assert c.get(w.url+'/options', headers=w.headers).status_code == 200
    assert c.get(w.url.replace(w.ws, 'ws_'+'f'*32)+'/options', headers=w.headers).status_code == 404
    body = {'run_id':w.run,'ttl_seconds':3600}
    assert c.post(w.url+'/releases', headers=w.headers, json=body).status_code == 400
    assert c.post(w.url+'/releases', headers={**w.reason,'Origin':'https://evil.test'}, json=body).status_code in (401,403)
    created = c.post(w.url+'/releases', headers=w.reason, json=body)
    assert created.status_code == 200, created.text
    release = created.json()['release']; url = w.url+'/releases/'+release['id']
    grant = {'allowed_origins':['https://customer.example'],'ttl_seconds':1800,'minute_limit':5,'day_limit':20,'authorized':True,'notice':'workspace-sdk-deployment-v2'}
    assert c.post(url+'/deployments', headers=w.reason, json={**grant,'authorized':False}).status_code == 400
    response = c.post(url+'/deployments', headers=w.reason, json=grant)
    assert response.status_code == 200, response.text
    deployment=response.json()['deployment']; package=w.url+'/deployments/'+deployment['app_id']+'/package'
    response=c.get(package,headers=w.headers)
    assert response.status_code == 200 and 'no-store' in response.headers['cache-control']
    with ZipFile(BytesIO(response.content)) as archive:
        payload=b'\n'.join(archive.read(name) for name in archive.namelist())
        assert w.raw.encode() not in payload and b'adminToken' not in payload
    revoke=w.url+'/deployments/'+deployment['app_id']+'/revoke'
    assert c.post(revoke,headers=w.reason,json={'revision':999}).status_code == 409
    assert c.post(revoke,headers=w.reason,json={'revision':deployment['revision']}).status_code == 200
    assert c.get(package,headers=w.headers).status_code == 404
    assert c.post(url+'/revoke',headers=w.reason,json={'revision':release['revision']}).status_code == 200
    rows=w.store.query("SELECT status FROM admin_audit_logs WHERE action='WORKSPACE_PANEL_CHANGE'")
    assert {'REQUESTED','SUCCESS','FAILED'} <= {r[0] for r in rows}
    assert c.post(RENEWAL+'/'+w.ws+'/drafts',headers=w.reason,json={}).status_code == 404


def test_release_browser_select_create_grant_download_revoke(release_panel, browser, tmp_path):
    from playwright.sync_api import expect
    w=release_panel
    client,context,page,errors,external=browser_context(browser,w.app,'https://admin.test')
    context.add_init_script('sessionStorage.setItem("adminToken",'+json.dumps(w.raw)+');')
    page.on('dialog',lambda dialog:dialog.accept())
    try:
        page.goto('https://admin.test/admin/next#/customers/specialists')
        page.get_by_label('직원 워크스페이스',exact=True).select_option(w.ws)
        page.evaluate('''kind => {
          const buttons = [...document.querySelectorAll('button')];
          const labels = kind === 'release' ? ['다단계', '저장본'] : ['저장본', '다단계'];
          for (const label of labels) buttons.find(x => x.textContent.trim() === label+' 릴리스·배포 열기').click();
        }''', w.kind)
        expect(page.locator('dialog[open]')).to_have_count(1)
        expect(page.locator('dialog[open] h2')).to_have_text('저장본 릴리스 선택' if w.kind=='release' else '다단계 워크플로 릴리스 선택')
        page.locator('dialog[open]').get_by_role('button',name='닫기',exact=True).click()
        page.get_by_role('button',name=('저장본' if w.kind=='release' else '다단계')+' 릴리스·배포 열기',exact=True).click()
        picker=page.locator('dialog[open]')
        picker.get_by_label('릴리스 대상',exact=True).select_option(w.x.args[1])
        picker.get_by_role('button',name='선택한 버전의 배포 관리').click()
        dialog=page.locator('dialog[open]')
        create=dialog.get_by_role('button',name=('저장본' if w.kind=='release' else '다단계')+' 릴리스 생성',exact=True)
        expect(create).to_be_enabled()
        create.click();expect(dialog.get_by_label('전문 패널 변경 사유')).to_be_focused()
        dialog.get_by_label('전문 패널 변경 사유').fill('Synthetic browser release verification')
        create.click()
        grant=dialog.get_by_role('button',name=('저장본' if w.kind=='release' else '다단계')+' 배포 권한 발급',exact=True)
        expect(grant).to_be_disabled()
        dialog.get_by_label('허용할 배포 출처 (한 줄에 하나)',exact=True).fill('https://customer.example')
        dialog.locator('input[type=checkbox]').first.check()
        grant.click()
        download=dialog.get_by_role('button',name=('SDK 2 ZIP 다운로드' if w.kind=='release' else '다단계 SDK 2 ZIP 다운로드'),exact=True).last
        expect(download).to_be_enabled()
        with page.expect_download() as event:download.click()
        file=tmp_path/'package.zip';event.value.save_as(file)
        with ZipFile(file) as archive:assert 'app-manifest.json' in archive.namelist()
        revoke=dialog.get_by_role('button',name='배포 권한 철회' if w.kind=='release' else '이 배포 권한 철회',exact=True).last
        expect(revoke).to_be_enabled();revoke.click()
        expect(dialog).to_contain_text('revoked')
        if w.kind=='release':
            dialog.get_by_label('소유자 사후 확인 메모',exact=True).fill('Synthetic owner confirmed external result separately')
            dialog.get_by_role('button',name='선택 테스트 확인 메모 기록').click()
            expect(dialog).to_contain_text('Owner note recorded')
        shots=Path('reports/admin-renewal-design-2026-10-21/releases');shots.mkdir(exist_ok=True)
        page.screenshot(path=str(shots/(w.kind+'.png')))
        dialog.get_by_role('button',name='닫기',exact=True).click()
        assert not errors and not external
    except Exception:
        print(errors);print(page.locator('body').inner_text()[-2600:]);raise
    finally:context.close();client.close()


def test_machine_alias_consent_and_single_dispatch(machine):
    w=machine;app=FastAPI();app.include_router(aliases(w.store,machine_routes(w.machine)))
    c=TestClient(app,base_url='https://private.test');base=RENEWAL+'/'+w.ws+'/machine-updates'
    headers={**w.machine_headers,'X-Admin-Reason':'Synthetic delivery consent test'}
    state=c.get(base+'/status',headers=headers).json()['result']
    body={'resource_id':1,'destination_ref':'configured_inbox','audience':'audience_fixture','protocol':'a2a_inbox','authorized':True,'notice':state['subscribe_notice']}
    assert c.post(base+'/subscriptions',headers=w.machine_headers,json=body).status_code == 400
    assert c.post(base+'/subscriptions',headers=headers,json={**body,'authorized':False}).status_code == 400
    result=c.post(base+'/subscriptions',headers=headers,json=body)
    assert result.status_code == 200,result.text
    subscription=result.json()['result']
    event=c.post(base+'/events/prepare',headers=headers,json={'subscription_id':subscription['id'],'authorized':True,'notice':state['prepare_notice']})
    assert event.status_code == 200,event.text
    command={'event_id':event.json()['result']['id'],'authorized':True,'notice':state['dispatch_notice']}
    assert not w.receiver.calls
    sent=c.post(base+'/events/dispatch',headers=headers,json=command)
    assert sent.status_code == 200,sent.text
    assert len(w.receiver.calls)==1
    assert c.post(base+'/events/dispatch',headers=headers,json=command).status_code == 404
    assert len(w.receiver.calls)==1
    withdrawn=c.post(base+'/subscriptions/withdraw',headers=headers,json={'subscription_id':subscription['id'],'authorized':True,'notice':state['withdraw_notice']})
    assert withdrawn.status_code == 200,withdrawn.text
    c.close()


def test_machine_browser_explicit_consent_dispatch_withdraw_and_disabled_receiver(machine, browser):
    from playwright.sync_api import expect
    from agent_market.workspace_machine_receiver import MachineReceiver
    w=machine;app=FastAPI()
    source=machine_routes(w.machine,receiver=MachineReceiver(w.access))
    app.include_router(source);app.include_router(aliases(w.store,source))
    app.include_router(workspaces(w.store,w.access.key,access=w.access))
    ui=SimpleNamespace(app=app,actor=w.staff[1]);shell(ui)
    client,context,page,errors,external=browser_context(browser,app,'https://private.test')
    context.add_init_script('sessionStorage.setItem("adminToken",'+json.dumps(w.raw_staff)+');localStorage.setItem("adm-theme","dark");')
    try:
        page.goto('https://private.test/admin/next#/customers/specialists')
        page.get_by_label('직원 워크스페이스',exact=True).select_option(w.ws)
        page.get_by_role('button',name='검증된 수신처 알림 열기',exact=True).click()
        dialog=page.locator('dialog[open]')
        expect(dialog.get_by_role('button',name='비공개 수신 활성화',exact=True)).to_be_disabled()
        dialog.get_by_label('전문 패널 변경 사유').fill('Synthetic consent and private metadata delivery')
        card=dialog.locator('section').filter(has=page.get_by_role('heading',name='근거 알림 구독 승인'))
        card.get_by_label('카탈로그 에이전트 참조',exact=False).fill('1')
        card.get_by_label('설정된 수신처 참조',exact=False).fill('configured_inbox')
        card.get_by_label('설정된 수신 대상 참조',exact=False).fill('audience_fixture')
        card.get_by_label('전달 프로토콜',exact=False).select_option('a2a_inbox')
        card.get_by_role('button',name='개별 구독 승인',exact=True).click()
        assert not w.receiver.calls
        card.get_by_role('checkbox').check();card.get_by_role('button',name='개별 구독 승인',exact=True).click()
        notice=dialog.locator('section').filter(has=page.get_by_role('button',name='알림 준비',exact=True))
        expect(notice).to_be_visible();notice.get_by_role('checkbox').first.check()
        notice.get_by_role('button',name='알림 준비',exact=True).click()
        delivery=dialog.locator('section').filter(has=page.get_by_role('button',name='준비된 알림 1회 발송',exact=True))
        expect(delivery).to_be_visible();assert not w.receiver.calls
        delivery.get_by_role('checkbox').check();delivery.get_by_role('button',name='준비된 알림 1회 발송',exact=True).click()
        expect(delivery).to_have_count(0);assert len(w.receiver.calls)==1
        withdraw=dialog.locator('section').filter(has=page.get_by_role('button',name='구독 철회',exact=True))
        withdraw.get_by_role('checkbox').last.check();withdraw.get_by_role('button',name='구독 철회',exact=True).click()
        expect(dialog).to_contain_text('withdrawn')
        page.screenshot(path='reports/admin-renewal-design-2026-10-21/releases/machine-updates.png')
        assert not errors and not external
    except Exception:
        print(errors);print(page.locator('body').inner_text()[-2500:]);raise
    finally:context.close();client.close()
