"""Migrated remote tasks and conformance retain consent, membership and uncertain outcomes."""
# ruff: noqa: F401,F811
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.workspace_admin_specialists import router_for as aliases, RENEWAL
from agent_market.workspace_remote_a2a_service import router_for as remote_routes
from agent_market.workspace_protocol_conformance_service import router_for as protocol_routes
from agent_market.workspace_service import router_for as workspaces
from agent_market.workflows import runtime_for
from tests.test_workspace_remote_a2a import remote, command as task_command
from tests.test_workspace_execution_api import private_api
from tests.test_workspace_a2a_sessions import stream_provider
from tests.test_workspace_protocol_conformance import conformance, command as review_command
from tests.test_workspace_sandbox_payments import sandbox, prepare, dispatch
from tests.test_workspace_agreements import agreement
from tests.test_provider_claims import provider
from tests.test_workspace_crypto_inspection_api import body as proof_body
from tests.test_workspace_x402_eip3009 import NOW
from tests.test_front_workflow_browser import browser
from tests.test_admin_specialist_panels import shell
from tests.test_workspace_admin_browser import browser_context


@pytest.fixture
def remote_panel(remote):
    x=remote;w=x.w;app=FastAPI();source=remote_routes(x.core)
    app.include_router(source);app.include_router(aliases(w.store,source))
    app.include_router(workspaces(w.store,runtime_for(w.store).key,access=x.core.access))
    obj=SimpleNamespace(app=app,actor=x.actor,ws=w.ws['id'],raw=w.headers['owner']['Authorization'][7:])
    shell(obj);x.app=app;x.panel=RENEWAL+'/'+obj.ws+'/remote-a2a';x.raw=obj.raw
    x.reason={**w.headers['owner'],'X-Admin-Reason':quote('Synthetic remote task lifecycle verification')}
    with TestClient(app,base_url='https://admin.test') as client:
        x.renewal=client;yield x


@pytest.fixture
def protocol_panel(conformance):
    w=conformance;app=FastAPI();source=protocol_routes(w.conformance)
    app.include_router(source);app.include_router(aliases(w.store,source))
    app.include_router(workspaces(w.store,w.access.key,access=w.access))
    shell(SimpleNamespace(app=app,actor=w.staff[1]));w.app=app
    w.panel=RENEWAL+'/'+w.ws+'/protocol-conformance'
    w.reason={'Authorization':'Bearer '+w.raw_staff,'X-Dashboard':'1','X-Admin-Reason':'Synthetic signed sandbox review'}
    with TestClient(app,base_url='https://private.test') as client:
        w.renewal=client;yield w


def test_remote_alias_auth_reason_origin_membership_and_exact_once(remote_panel):
    x=remote_panel;c=x.renewal;url=x.panel
    for suffix in ('/options','/tasks'):
        assert c.get(url+suffix).status_code==401
        r=c.get(url+suffix,headers=x.reason);assert r.status_code==200 and r.headers['cache-control']=='no-store'
    assert c.post(url+'/tasks',headers=x.w.headers['owner'],json=task_command(x)).status_code==400
    assert c.post(url+'/tasks',headers={**x.reason,'Origin':'https://evil.test'},json=task_command(x)).status_code in (401,403)
    assert c.post(url+'/tasks',headers={**x.w.headers['outsider'],'X-Admin-Reason':'Foreign workspace access'},json=task_command(x)).status_code==404
    assert c.post(url+'/tasks',headers=x.reason,json={**task_command(x),'authorized':False}).status_code==400
    assert not x.calls
    sent=c.post(url+'/tasks',headers=x.reason,json=task_command(x));assert sent.status_code==200,sent.text
    task=sent.json()['task'];assert len(x.calls)==1
    replay=c.post(url+'/tasks',headers=x.reason,json=task_command(x))
    assert replay.status_code==200 and replay.json()['task']['id']==task['id'] and len(x.calls)==1
    assert c.get(url+'/tasks/'+task['id'],headers=x.reason).status_code==200 and len(x.calls)==1
    cancel={'revision':task['revision'],'action':'cancel','authorized':True,'notice':task_command(x)['notice']}
    assert c.post(url+'/tasks/'+task['id'],headers=x.reason,json={**cancel,'revision':999}).status_code==409
    x.control['state']='canceled'
    r=c.post(url+'/tasks/'+task['id'],headers=x.reason,json=cancel);assert r.status_code==200,r.text
    assert len(x.calls)==2 and x.calls[-1]['method']=='tasks/cancel'
    assert c.post(url+'/tasks/'+task['id'],headers=x.reason,json=cancel).status_code==409
    audit=x.w.store.query("SELECT details FROM admin_audit_logs WHERE action='WORKSPACE_PANEL_CHANGE'")
    assert task_command(x)['text'] not in str(audit) and x.raw not in str(audit)


def test_remote_unknown_is_retained_without_automatic_resubmit(remote_panel):
    x=remote_panel;x.control['timeout']=True
    r=x.renewal.post(x.panel+'/tasks',headers=x.reason,json=task_command(x));assert r.status_code==200,r.text
    task=r.json()['task'];assert task['state']=='unknown' and len(x.calls)==1
    assert x.renewal.get(x.panel+'/tasks',headers=x.reason).status_code==200
    r=x.renewal.post(x.panel+'/tasks',headers=x.reason,json=task_command(x))
    assert r.status_code==200 and r.json()['task']['id']==task['id'] and len(x.calls)==1


def test_conformance_alias_report_and_offline_proof_create_no_financial_events(protocol_panel,monkeypatch):
    w=protocol_panel;c=w.renewal;capture=prepare(w);dispatch(w,capture)
    before=w.store._db.execute('SELECT COUNT(*) FROM workspace_agreement_events').fetchone()[0]
    payload=review_command(w,capture)
    assert c.get(w.panel).status_code==401
    assert c.post(w.panel+'/runs',headers={k:v for k,v in w.reason.items() if k!='X-Admin-Reason'},json=payload).status_code==400
    assert c.post(w.panel+'/runs',headers=w.reason,json={**payload,'authorized':False}).status_code==400
    result=c.post(w.panel+'/runs',headers=w.reason,json=payload)
    assert result.status_code==200,result.text
    report=result.json()['result'];assert report['wire_checks']['passed'] and not report['actual_money']
    assert c.get(w.panel+'/reports/'+report['id'],headers=w.reason).status_code==200
    foreign=w.panel.replace(w.ws,'ws_'+'f'*32)
    assert c.get(foreign+'/reports/'+report['id'],headers=w.reason).status_code==404
    monkeypatch.setattr('agent_market.workspace_x402_eip3009.time',SimpleNamespace(time=lambda:NOW))
    response=c.post(w.panel+'/cryptographic-check',headers=w.reason,json=proof_body())
    assert response.status_code==200,response.text
    value=response.json()['result'];assert value['signature_valid'] and not value['verified_payment'] and not value['settlement_authorized']
    assert value['rpc_calls']==value['broadcasts']==value['ledger_events']==0
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_agreement_events').fetchone()[0]==before


def launch(browser,w,app,url,raw,ws,label):
    client,context,page,errors,external=browser_context(browser,app,url)
    context.add_init_script('sessionStorage.setItem("adminToken",'+json.dumps(raw)+');localStorage.setItem("adm-theme","dark");')
    page.goto(url+'/admin/next#/customers/specialists')
    page.get_by_label('직원 워크스페이스',exact=True).select_option(ws)
    page.get_by_role('button',name=label+' 열기',exact=True).click()
    return client,context,page,errors,external


@pytest.mark.parametrize('mode',['poll','cancel','continue','resume','unknown'])
def test_remote_browser_explicit_actions_retained_reads_and_session_cleanup(remote_panel,browser,mode):
    from playwright.sync_api import expect
    x=remote_panel
    if mode in ('continue','resume'):stream_provider(x,disconnect=mode=='resume')
    if mode=='unknown':x.control['timeout']=True
    client,context,page,errors,external=launch(browser,x,x.app,'https://admin.test',x.raw,x.w.ws['id'],'원격 A2A 작업')
    try:
        dialog=page.locator('dialog[open]');submit=dialog.get_by_role('button',name='작업 1회 제출',exact=True)
        expect(dialog).to_contain_text('보관 이력을 조회했습니다.')
        dialog.get_by_label('승인된 에이전트 연결',exact=True).select_option('0')
        dialog.get_by_label('공유할 작업 입력',exact=True).fill('Synthetic public research')
        dialog.locator('#remoteA2ASendConsent').check();submit.click()
        expect(dialog.get_by_label('전문 패널 변경 사유')).to_be_focused();assert not x.calls
        dialog.get_by_label('전문 패널 변경 사유').fill('Synthetic named-session lifecycle test')
        submit.click();expect(dialog).to_contain_text('작업 제출 1회를 기록했습니다.')
        assert len(x.calls)==1
        dialog.get_by_role('button',name='보관 이력 조회',exact=True).click()
        expect(dialog).to_contain_text('보관 이력을 조회했습니다.');assert len(x.calls)==1
        dialog.get_by_role('button',name='Read retained task ',exact=False).first.click()
        expect(dialog).to_contain_text('보관된 작업을 조회했습니다.');assert len(x.calls)==1
        if mode=='unknown':
            expect(dialog).to_contain_text('외부 처리 결과가 불확실합니다.')
            assert dialog.locator('#remoteA2ApollOnce').count()==0
        else:
            if mode=='poll':
                x.control['state']='completed'
                original=x.core.bindings[x.w.remote_rid].client.call
                def hostile_output(*args,**kwargs):
                    result=original(*args,**kwargs)
                    result['artifacts']=[{'parts':[{'kind':'text','text':'<img src=https://hostile.test/leak onerror=alert(1)> retained'}]}]
                    return result
                x.core.bindings[x.w.remote_rid].client.call=hostile_output
            if mode=='cancel':x.control['state']='canceled'
            if mode=='continue':
                dialog.locator('#remoteA2AContinuation').fill('Next public research input')
            consent=dialog.locator('#remoteA2A'+mode+'Consent');action=dialog.locator('#remoteA2A'+mode+'Once')
            expect(action).to_be_disabled();consent.check();action.click()
            expect(dialog).to_contain_text({'poll':'원격 상태 확인 1회를 기록했습니다.', 'cancel':'취소 요청 1회를 기록했습니다.', 'continue':'동일한 작업에 추가 입력 1회를 기록했습니다.', 'resume':'동일 작업의 스트림 재연결을 기록했습니다.'}[mode])
            expect(dialog).not_to_have_attribute('aria-busy','true')
            assert len(x.calls)==2
            assert x.calls[-1]['method']=={'poll':'tasks/get','cancel':'tasks/cancel','continue':'message/stream','resume':'tasks/resubscribe'}[mode]
        if mode=='poll':
            dialog.get_by_role('button',name='Read retained task ',exact=False).first.click()
            expect(dialog.get_by_label('보관된 출력 미리보기')).to_contain_text('<img src=')
            assert dialog.locator('img').count()==0 and len(x.calls)==2
        out=Path('reports/admin-renewal-design-2026-10-21/protocols');out.mkdir(exist_ok=True)
        if mode in ('poll','resume'):page.screenshot(path=str(out/('remote-'+mode+'.png')))
        page.evaluate('sessionStorage.removeItem("adminToken")')
        expect(page.locator('dialog[open]')).to_have_count(0,timeout=3000)
        assert not errors and not external
    except Exception:
        print(errors);print(page.locator('body').inner_text()[-2600:]);raise
    finally:context.close();client.close()


def test_conformance_browser_report_offline_proof_and_history_without_dispatch(protocol_panel,browser,monkeypatch):
    from playwright.sync_api import expect
    w=protocol_panel;capture=prepare(w);dispatch(w,capture)
    before=w.store._db.execute('SELECT COUNT(*) FROM workspace_agreement_events').fetchone()[0]
    monkeypatch.setattr('agent_market.workspace_x402_eip3009.time',SimpleNamespace(time=lambda:NOW))
    client,context,page,errors,external=launch(browser,w,w.app,'https://private.test',w.raw_staff,w.ws,'규격 적합성·테스트 원장')
    try:
        dialog=page.locator('dialog[open]');expect(dialog).to_contain_text('현재 비공개 검토 기록을 조회했습니다.')
        dialog.get_by_label('전문 패널 변경 사유').fill('Synthetic protocol and offline proof review')
        dialog.get_by_label('기존 테스트 캡처',exact=True).select_option(capture['id'])
        submit=dialog.get_by_role('button',name='합성 규격 검토 기록',exact=True);expect(submit).to_be_disabled()
        dialog.get_by_role('checkbox',name='선택한 보관 샌드박스 기록만 검토하며 금융 이벤트를 생성하지 않습니다.',exact=True).check()
        submit.click();expect(dialog).to_contain_text('wire subset passed')
        dialog.get_by_label('공개 증명·독립 검토한 기준 정보',exact=True).fill(json.dumps(proof_body()))
        dialog.get_by_role('checkbox',name='이 공개 증명만 검사하며 거래를 승인하지 않습니다.',exact=True).check()
        dialog.get_by_role('button',name='오프라인 서명 검사',exact=True).click()
        expect(dialog).to_contain_text('서명과 로컬 기준이 일치합니다.')
        assert w.store._db.execute('SELECT COUNT(*) FROM workspace_agreement_events').fetchone()[0]==before
        dialog.get_by_role('button',name='현재 규격 검토 이력 조회',exact=True).click()
        expect(dialog.get_by_role('status',name='규격 검토 상태',exact=True)).to_contain_text('현재 비공개 검토 기록을 조회했습니다.')
        expect(dialog).not_to_have_attribute('aria-busy','true')
        expect(dialog).to_contain_text('wire subset passed')
        assert w.store._db.execute('SELECT COUNT(*) FROM workspace_protocol_reports').fetchone()[0]==1
        out=Path('reports/admin-renewal-design-2026-10-21/protocols');out.mkdir(exist_ok=True)
        page.screenshot(path=str(out/'conformance.png'))
        page.evaluate("location.hash='#/home'");expect(page.locator('dialog[open]')).to_have_count(0)
        assert not errors and not external
    except Exception:
        print(errors);print(page.locator('body').inner_text()[-2500:]);raise
    finally:context.close();client.close()


def test_remote_browser_lost_ack_reads_history_without_resending(remote_panel,browser):
    from playwright.sync_api import expect
    x=remote_panel
    client,context,page,errors,external=launch(browser,x,x.app,'https://admin.test',x.raw,x.w.ws['id'],'원격 A2A 작업')
    requests=[]
    def lose(route):
        if route.request.method!='POST':route.fallback();return
        requests.append(route.request.url)
        result=client.post(x.panel+'/tasks',headers=route.request.headers,content=route.request.post_data)
        assert result.status_code==200
        route.fulfill(status=503,headers={'Content-Type':'application/json'},body='{"detail":"Synthetic lost acknowledgement"}')
    context.route('**/remote-a2a/tasks',lose)
    try:
        dialog=page.locator('dialog[open]');expect(dialog).to_contain_text('보관 이력을 조회했습니다.')
        dialog.get_by_label('전문 패널 변경 사유').fill('Synthetic lost response and retained history')
        dialog.get_by_label('승인된 에이전트 연결',exact=True).select_option('0')
        dialog.get_by_label('공유할 작업 입력',exact=True).fill('Public research with lost acknowledgement')
        dialog.locator('#remoteA2ASendConsent').check()
        dialog.get_by_role('button',name='작업 1회 제출',exact=True).click()
        expect(dialog).to_contain_text('응답을 확인하지 못했습니다.')
        assert len(requests)==len(x.calls)==1
        dialog.get_by_role('button',name='보관 이력 조회',exact=True).click()
        expect(dialog.get_by_role('button',name='Read retained task ',exact=False)).to_have_count(1)
        assert len(requests)==len(x.calls)==1
        assert not errors and not external
    finally:context.close();client.close()
