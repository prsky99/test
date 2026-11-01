"""Renewal reliability panels preserve approval, erasure, private sources and no-dispatch defaults."""
# ruff: noqa: F401,F811
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from agent_market.workspace_admin_specialists import router_for as aliases,RENEWAL
from agent_market.workspace_service import router_for as workspaces
from agent_market.workspace_reliability_service import router_for as evidence_routes
from agent_market.reliability_control_service import router_for as control_routes
from agent_market.reliability_research_service import router_for as research_routes
from agent_market.reliability_admission_service import router_for as admission_routes
from agent_market.workspace_growth_service import router_for as growth_routes
from agent_market.reliability_admission import SingleAdmission
from agent_market.reliability_routing import ReliabilityRouting
from agent_market.reliability_evaluation_worker import EvaluationWorker
from agent_market.workflows import runtime_for
from tests.test_workspace_reliability import reliability,setup,sample
from tests.test_reliability_controls import controls
from tests.test_reliability_research import research_world,item,item_goal_hash
from tests.test_workspace_execution_api import private_api
from tests.test_workspace_growth import growth,review_body
from tests.test_workspace_typed_flows import typed_world,routing,graph
from tests.test_admin_specialist_panels import shell
from tests.test_workspace_admin_browser import browser_context
from tests.test_front_workflow_browser import browser


@pytest.fixture(params=['reliability','reliability-controls','reliability-research','research-controls'])
def panel(request):
    kind=request.param;app=FastAPI()
    if kind=='reliability':
        w=setup(request.getfixturevalue('reliability'));w.sample=sample(w)
        access=w.plane.access;execution=w.plane.execution;ws=w.ws['id'];raw=w.headers['owner']['Authorization'][7:]
        sources=[evidence_routes(access,execution,core=w.plane)]
        reads=['/reliability/options','/reliability/objects','/reliability/inventory'];write='/reliability/objects'
    elif kind in ('reliability-controls','reliability-research'):
        w=request.getfixturevalue('research_world');access=w.access;execution=None;ws=w.ws['id'];raw=w.headers['owner']['Authorization'][7:]
        w.evaluation.worker=EvaluationWorker(w.evaluation)
        sources=[control_routes(access,w.runtime,evaluation=w.evaluation,routing=w.routing,trust=w.trust),research_routes(access,w.evaluation,research=w.research)]
        reads=['/reliability/evaluation/options','/reliability/evaluation/status','/reliability/routing/status','/reliability/evaluation/worker/status','/reliability/research/options','/reliability/research/status']
        write='/reliability/evaluation/control' if kind=='reliability-controls' else '/reliability/research/manifests'
    else:
        g=request.getfixturevalue('growth');w=g.w;w.growth=g;access=w.access;execution=w.execution;ws=w.ws;raw=w.raw
        runtime=runtime_for(w.store,w.execution.proxy)
        w.admission=SingleAdmission(access,ReliabilityRouting(access,runtime),execution)
        sources=[admission_routes(w.admission),growth_routes(g.factory,g.support)]
        reads=['/reliability/admission/status','/app-factory/options'];write='/app-factory/plan-reviews'
    app.include_router(workspaces(w.store,runtime_for(w.store).key,access=access,execution=execution))
    for source in sources:app.include_router(source);app.include_router(aliases(w.store,source))
    shell(SimpleNamespace(app=app,actor=w.actor))
    p=SimpleNamespace(w=w,app=app,ws=ws,kind=kind,raw=raw,reads=reads,write=write,base=RENEWAL+'/'+ws,
        headers={'Authorization':'Bearer '+raw,'X-Dashboard':'1'},calls=w.calls)
    p.reason={**p.headers,'X-Admin-Reason':quote('Synthetic reliability migration verification')}
    with TestClient(app,base_url='https://admin.test') as client:
        p.client=client;yield p


def test_aliases_membership_no_store_and_failed_write_audit(panel):
    p=panel;c=p.client;before=len(p.calls)
    for suffix in p.reads:
        r=c.get(p.base+suffix,headers=p.headers);assert r.status_code==200,r.text
        assert r.headers['cache-control']=='no-store'
        assert c.get(p.base+suffix).status_code==401
        assert c.get((p.base+suffix).replace(p.ws,'ws_'+'f'*32),headers=p.headers).status_code==404
    assert c.post(p.base+p.write,headers=p.headers,json={}).status_code==400
    assert c.post(p.base+p.write,headers={**p.reason,'Origin':'https://evil.test'},json={}).status_code in (401,403)
    rejected=c.post(p.base+p.write,headers=p.reason,json={});assert rejected.status_code==400,rejected.text
    audit=p.w.store.query("SELECT status,details FROM admin_audit_logs WHERE action='WORKSPACE_PANEL_CHANGE'")
    assert {row[0] for row in audit}=={'REQUESTED','FAILED'}
    assert p.raw not in str(audit) and len(p.calls)==before
    # No membership or ordinary draft editing aliases are introduced.
    assert c.post(p.base+'/members',headers=p.reason,json={}).status_code==404
    assert c.post(p.base+'/drafts',headers=p.reason,json={}).status_code==404


def test_desktop_panel_actions_fresh_consent_no_implicit_dispatch(panel,browser):
    from playwright.sync_api import expect
    p=panel;w=p.w;before=len(p.calls)
    if p.kind=='reliability-research':
        w.evaluation.set_control(p.ws,{'revision':0,'enabled':True,'authorized':True,'notice':'approved-read-evaluation-corpus-v1'},w.actor)
    client,context,page,errors,external=browser_context(browser,p.app,'https://admin.test')
    theme='light' if p.kind in ('reliability','reliability-research') else 'dark'
    context.add_init_script('sessionStorage.setItem("adminToken",'+json.dumps(p.raw)+');localStorage.setItem("adm-theme",'+json.dumps(theme)+');')
    if hasattr(w,'now'):context.add_init_script('Date.now=()=>'+str(w.now*1000)+';')
    names={'reliability':'신뢰성 평가 근거','reliability-controls':'평가·라우팅 제어','reliability-research':'짝지은 신뢰성 연구','research-controls':'검토된 계획·단일 제공자'}
    try:
        page.goto('https://admin.test/admin/next#/customers/specialists')
        page.get_by_label('직원 워크스페이스',exact=True).select_option(p.ws)
        page.get_by_role('button',name=names[p.kind]+' 열기',exact=True).click()
        dialog=page.locator('dialog[open]');expect(dialog).to_be_visible()
        reason=dialog.get_by_label('전문 패널 변경 사유')
        if p.kind=='reliability':
            expect(dialog).to_contain_text('비공개 평가 계약을 조회했습니다.')
            # Editing the exact specification clears previously granted consent.
            editor=dialog.locator('section').filter(has=page.get_by_role('heading',name='불변 평가 계획·항목·코호트',exact=True))
            editor.get_by_role('checkbox').first.check()
            editor.get_by_label('평가 계약 정의',exact=False).fill('{}')
            expect(editor.get_by_role('checkbox').first).not_to_be_checked()
            row=dialog.locator('section').filter(has=page.get_by_role('button',name='비공개 원본 열람',exact=True)).last
            row.get_by_role('checkbox').first.check();row.get_by_role('button',name='비공개 원본 열람',exact=True).click()
            expect(reason).to_be_focused()
            reason.fill('Inspect and erase this synthetic retained source')
            row.get_by_role('button',name='비공개 원본 열람',exact=True).click()
            expect(row.locator('pre')).to_contain_text('<img src=x onerror=alert(1)>')
            assert row.locator('img').count()==0
            row.get_by_role('checkbox').last.check();row.get_by_role('button',name='원본 영구 삭제',exact=True).click()
            expect(dialog).to_contain_text('저장했습니다.')
            expect(dialog.get_by_role('button',name='비공개 원본 열람',exact=True)).to_have_count(0)
        elif p.kind=='reliability-controls':
            expect(dialog).to_contain_text('현재 비공개 평가 제어를 조회했습니다.')
            expect(dialog.get_by_role('button',name='평가 워커 활성화',exact=True)).to_be_disabled()
            reason.fill('Synthetic corpus and bounded reservation plan')
            coverage=dialog.locator('section').filter(has=page.get_by_role('heading',name='평가 범위 현황',exact=True))
            coverage.get_by_role('checkbox').check();coverage.get_by_role('button',name='평가 예약 활성화',exact=True).click()
            expect(dialog.get_by_role('button',name='평가 예약 중지',exact=True)).to_be_visible()
            corpus=dialog.locator('section').filter(has=page.get_by_role('heading',name='승인된 평가 코퍼스',exact=True))
            corpus.get_by_role('checkbox').check();corpus.get_by_label('합성 평가 질문',exact=False).fill('Approved public documentation')
            expect(corpus.get_by_role('checkbox')).not_to_be_checked()
            corpus.get_by_role('checkbox').check();corpus.get_by_role('button',name='평가 코퍼스 버전 승인',exact=True).click()
            expect(dialog).to_contain_text('Immutable corpus approved.')
            plan=dialog.locator('section').filter(has=page.get_by_role('heading',name='제한된 평가 계획',exact=True))
            plan.get_by_label('평가 대상 에이전트 참조',exact=False).fill(str(w.rids[0]))
            plan.get_by_role('checkbox').first.check();plan.get_by_role('button',name='평가 계획 저장',exact=True).click()
            expect(dialog).to_contain_text('Evaluation plan revision 1 saved.')
            plan.get_by_role('checkbox').last.check();plan.get_by_role('button',name='기한이 된 평가 예약',exact=True).click()
            expect(dialog).to_contain_text('현재 비공개 평가 제어를 조회했습니다.')
            assert w.evaluation.worker.running is False
        elif p.kind=='reliability-research':
            expect(dialog).to_contain_text('현재 연구 기록을 조회했습니다.')
            reason.fill('Synthetic paired corpus and metadata-only research')
            card=dialog.locator('section').filter(has=page.get_by_role('heading',name='짝지은 연구 코퍼스 승인',exact=True))
            card.get_by_label('검토한 정규화 항목 SHA-256',exact=False).fill(item_goal_hash('docs.search.v1',item(w)))
            card.get_by_role('checkbox').first.check();card.get_by_role('button',name='짝지은 연구 명세 승인',exact=True).click()
            expect(dialog).to_contain_text('Immutable research corpus approved.')
            expect(dialog.get_by_role('button',name='짝지은 분석 조회',exact=True)).to_be_disabled()
            plan=dialog.locator('section').filter(has=page.get_by_role('heading',name='기존 평가 계획 승인',exact=True))
            plan.get_by_label('평가 대상 에이전트 참조',exact=False).fill(str(w.rids[0]))
            plan.get_by_role('checkbox').check();plan.get_by_role('button',name='연구 평가 계획 저장',exact=True).click()
            expect(dialog).to_contain_text('Research plan approved.')
            dialog.get_by_role('button',name='짝지은 분석 조회',exact=True).click()
            expect(dialog).to_contain_text('Scheduled 0; expected 4; unscheduled 4.')
            history=dialog.locator('section').filter(has=page.get_by_role('heading',name='짝지은 연구 명세',exact=True))
            history.get_by_role('checkbox').check();history.get_by_role('button',name='연구 명세 철회',exact=True).click()
            expect(dialog).to_contain_text('withdrawn')
        else:
            expect(dialog).to_contain_text('현재 권한 범위의 기록을 조회했습니다.')
            reason.fill('Synthetic exact graph review and private draft save')
            dialog.get_by_label('선택 사항: 명시적 워크플로 정의 JSON',exact=True).fill(json.dumps(graph(w)))
            dialog.get_by_role('button',name='계획 검토 준비',exact=True).click()
            expect(dialog).to_contain_text('Review the exact graph, inputs and destinations.')
            dialog.locator('#researchPlanConsent').check()
            dialog.get_by_label('새 워크플로 이름',exact=False).fill('Reviewed new synthetic graph')
            expect(dialog.get_by_role('button',name='검토한 새 초안 저장',exact=True)).to_be_disabled()
            dialog.get_by_role('button',name='계획 검토 준비',exact=True).click()
            expect(dialog).to_contain_text('Review the exact graph, inputs and destinations.')
            dialog.locator('#researchPlanConsent').check();dialog.get_by_role('button',name='검토한 새 초안 저장',exact=True).click()
            expect(dialog).to_contain_text('Saved new draft')
            dialog.get_by_role('button',name='선택적 모델 제안 사용 가능 여부',exact=True).click()
            expect(dialog).to_contain_text('Optional model proposals are unavailable.')
            assert w.store.query('SELECT COUNT(*) FROM workspace_typed_flows')[0][0]==1
        expect(dialog).not_to_have_attribute('aria-busy','true')
        assert len(p.calls)==before
        shots=Path('reports/admin-renewal-design-2026-10-21/reliability');shots.mkdir(exist_ok=True)
        page.screenshot(path=str(shots/(p.kind+'.png')))
        page.evaluate('sessionStorage.removeItem("adminToken")');expect(dialog).to_have_count(0,timeout=3000)
        assert not errors and not external
    except Exception:
        print(errors);print(page.locator('body').inner_text()[-2800:]);raise
    finally:context.close();client.close()


@pytest.mark.parametrize('panel',['reliability-controls'],indirect=True)
def test_parallel_private_loading_keeps_busy_until_last_reply(panel,browser):
    from playwright.sync_api import expect
    p=panel;client,context,page,errors,external=browser_context(browser,p.app,'https://admin.test')
    context.add_init_script('sessionStorage.setItem("adminToken",'+json.dumps(p.raw)+');')
    held=[]
    def hold(route):
        response=client.get(p.base+'/reliability/routing/status',headers=route.request.headers)
        held.append((route,response))
    context.route('**/reliability/routing/status',hold)
    try:
        page.goto('https://admin.test/admin/next#/customers/specialists')
        page.get_by_label('직원 워크스페이스',exact=True).select_option(p.ws)
        with page.expect_request_finished(lambda req:req.url.endswith('/evaluation/worker/status')):
            page.get_by_role('button',name='평가·라우팅 제어 열기',exact=True).click()
        page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
        assert len(held)==1
        dialog=page.locator('dialog[open]');expect(dialog).to_have_attribute('aria-busy','true')
        route,result=held.pop();route.fulfill(status=result.status_code,body=result.content,headers={'Content-Type':'application/json','Cache-Control':'no-store'})
        expect(dialog).to_contain_text('현재 비공개 평가 제어를 조회했습니다.')
        expect(dialog).to_have_attribute('aria-busy','false')
        assert not errors and not external
    finally:
        for route,_ in held:route.abort()
        context.close();client.close()
