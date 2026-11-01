"""Renewal specialist aliases preserve private membership and explicit execution consent."""
# ruff: noqa: F401,F811
import json
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi import FastAPI, APIRouter
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.testclient import TestClient

from agent_market.workspace_admin_specialists import router_for, RENEWAL
from agent_market.workspace_service import router_for as workspace_router
from agent_market.workspace_typed_flow_service import router_for as flow_router
from agent_market.workspace_typed_evidence_service import router_for as lineage_router
from agent_market.evidence_rollup_service import router_for as evidence_router
from agent_market.workflow_quality_review_service import router_for as quality_router
from tests.test_workspace_typed_evidence import typed_evidence, capture_body
from tests.test_workspace_typed_flows import typed_world, graph
from tests.test_workflow_fallback import routing
from tests.test_front_workflow_browser import browser


@pytest.fixture
def panels(typed_evidence):
    w = typed_evidence
    app = FastAPI()
    app.include_router(workspace_router(w.store, w.rt.key, access=w.access, execution=w.execution))
    for source in (flow_router(w.core), lineage_router(w.evidence), evidence_router(w.access, w.execution), quality_router(w.access, w.execution)):
        app.include_router(source)
        app.include_router(router_for(w.store, source))
    w.app = app
    w.panel = RENEWAL + '/' + w.ws
    w.client = TestClient(app, base_url='https://admin.test')
    w.reason = {**w.headers, 'X-Admin-Reason': quote('격리 검증을 위한 명시적 요청')}
    yield w
    w.client.close()


def test_aliases_are_scoped_no_store_and_do_not_copy_other_mutations(panels):
    w = panels
    for suffix in ('/typed-flows', '/typed-flows/options', '/reliability/typed/options', '/evidence/options', '/quality/options', '/quality/assignments'):
        r = w.client.get(w.panel + suffix, headers=w.headers)
        assert r.status_code == 200, r.text
        assert 'no-store' in r.headers['cache-control']
        assert w.client.get(w.panel + suffix).status_code == 401
    assert w.client.post(w.panel + '/members', headers=w.reason, json={}).status_code == 404
    other = RENEWAL + '/ws_' + 'f'*32 + '/typed-flows'
    assert w.client.get(other, headers=w.headers).status_code == 404
    assert not w.calls


def test_reason_audit_and_exact_review_execute_no_replay(panels):
    w = panels
    url = w.panel + '/typed-flows/' + w.flow['id']
    assert w.client.post(url + '/prepare', headers=w.headers, json={'revision': 1}).status_code == 400
    prepared = w.client.post(url + '/prepare', headers=w.reason, json={'revision': 1})
    assert prepared.status_code == 200, prepared.text
    body = {'ticket_id': prepared.json()['ticket_id'], 'authorized': True, 'notice': 'workspace-whole-graph-run-v1'}
    bad = w.client.post(url + '/runs', headers={**w.reason, 'Origin': 'https://evil.test'}, json=body)
    assert bad.status_code in (401,403) and not w.calls
    result = w.client.post(url + '/runs', headers=w.reason, json=body)
    assert result.status_code == 200 and result.json()['run']['status'] == 'succeeded', result.text
    calls = len(w.calls)
    replay = w.client.post(url + '/runs', headers=w.reason, json=body)
    assert replay.status_code == 200 and replay.json()['run']['id'] == result.json()['run']['id']
    assert w.client.post(url + '/prepare', headers=w.reason, json={'revision': 999}).status_code == 409
    assert len(w.calls) == calls == 2
    rows = w.store.query("SELECT status,details FROM admin_audit_logs WHERE action='WORKSPACE_PANEL_CHANGE'")
    assert any(r[0] == 'SUCCESS' for r in rows) and any(r[0] == 'FAILED' for r in rows)
    assert all('격리 검증을 위한 명시적 요청' in r[1] for r in rows)
    assert w.raw not in str(rows) and 'Distinct original search' not in str(rows)
    capture = w.client.post(w.panel + '/reliability/typed/captures', headers=w.reason, json=capture_body(w, result.json()))
    assert capture.status_code == 200, capture.text
    assert len(w.calls) == calls


def test_membership_revoked_blocks_alias_even_after_listing(panels):
    w = panels
    assert w.client.get(w.panel + '/typed-flows', headers=w.headers).status_code == 200
    w.access.set_active(w.ws, {'active': False, 'revision': 1}, w.actor)
    assert w.client.get(w.panel + '/typed-flows', headers=w.headers).status_code == 404
    assert w.client.post(w.panel + '/typed-flows/' + w.flow['id'] + '/prepare', headers=w.reason, json={'revision': 1}).status_code == 404
    assert not w.calls


@pytest.mark.parametrize('reason', ['', 'abc', '%0Ainjected', 'x'*301])
def test_invalid_reason_never_dispatches(panels, reason):
    w = panels
    r = w.client.post(w.panel + '/typed-flows/' + w.flow['id'] + '/prepare', headers={**w.headers, 'X-Admin-Reason': reason}, json={'revision': 1})
    assert r.status_code == 400 and not w.calls


def shell(w):
    assets = Path('agent_market/gateway/admin_next')
    @w.app.get('/admin/next')
    def page():
        return HTMLResponse((assets/'index.html').read_text(), headers={'Content-Security-Policy': "default-src 'none';script-src 'self';style-src 'self';connect-src 'self';img-src 'self' data:;frame-ancestors 'none';object-src 'none';base-uri 'none'"})
    @w.app.get('/admin/next/assets/{path:path}')
    def asset(path: str):
        return FileResponse(assets/path)
    @w.app.get('/admin/api/v2/auth/me')
    @w.app.get('/admin/api/auth/me')
    def who():
        return {'user': {'user_id': w.actor.user_id, 'username':'fixture','role':'superadmin','name':'Fixture'}}
    @w.app.get('/admin/api/v2/home/bootstrap')
    def home():
        return {'me': {'username':'fixture','role':'superadmin','name':'Fixture'}, 'overview':{}, 'gateway':{}, 'alerts':[]}
    @w.app.get('/admin/api/v2/home/changes')
    def changes():
        w.change_reads = getattr(w, 'change_reads', 0) + 1
        return {'version': w.change_reads, 'tags': ['customers']}


@pytest.mark.parametrize('theme', ['light','dark'])
def test_browser_all_four_panels_and_graph_save_run(panels, browser, theme):
    from playwright.sync_api import expect
    from tests.test_workspace_admin_browser import browser_context
    w = panels; shell(w)
    client, context, page, errors, external = browser_context(browser, w.app, 'https://admin.test')
    context.add_init_script('sessionStorage.setItem("adminToken", ' + json.dumps(w.raw) + ');localStorage.setItem("adm-theme", ' + json.dumps(theme) + ');')
    page.on('console', lambda msg: errors.append(msg.text) if msg.type == 'error' else None)
    try:
        page.goto('https://admin.test/admin/next#/customers/specialists')
        page.get_by_label('직원 워크스페이스', exact=True).select_option(w.ws)
        page.get_by_role('button', name='워크플로 구성·실행 열기', exact=True).click()
        dialog = page.locator('dialog.adm-specialist-dialog')
        expect(dialog).to_be_visible()
        dialog.get_by_role('button', name='워크플로 열기', exact=True).click()
        expect(dialog.locator('.adm-typed-preview .adm-flow-svg')).to_be_visible()
        for node in w.definition['nodes']:expect(dialog.locator('.adm-typed-preview')).to_contain_text(node['id'])
        expect(dialog.get_by_role('button', name='전체 실행 내용 검토')).to_be_enabled()
        dialog.get_by_role('button', name='전체 실행 내용 검토').click()
        expect(dialog.get_by_label('전문 패널 변경 사유')).to_be_focused()
        assert not w.calls
        dialog.get_by_label('전문 패널 변경 사유').fill('Synthetic graph browser verification')
        dialog.get_by_role('button', name='전체 실행 내용 검토').click()
        dialog.get_by_role('checkbox').check()
        dialog.get_by_role('button', name='검토한 워크플로 실행').click()
        expect(dialog).to_contain_text('succeeded', timeout=20000)
        assert len(w.calls) == 2
        dialog.get_by_role('button', name='새 워크플로', exact=True).click()
        dialog.get_by_label('워크플로 이름', exact=True).fill('Browser private flow')
        dialog.locator('summary',has_text='고급 입력 · 워크플로 정의').click()
        dialog.get_by_label('워크플로 정의', exact=True).fill(json.dumps(w.definition))
        dialog.get_by_role('button', name='새 버전 저장', exact=True).click()
        expect(dialog).to_contain_text('Browser private flow')
        assert len(w.calls) == 2
        shots = Path('reports/admin-renewal-design-2026-10-21/specialists')
        shots.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(shots / ('flow-' + theme + '.png')))
        dialog.get_by_role('button', name='닫기', exact=True).click()
        for name in ('워크플로 실행 증거', '보관된 증거', '직원 품질 검토'):
            page.get_by_role('button', name=name + ' 열기', exact=True).click()
            expect(dialog).to_be_visible()
            expect(dialog).not_to_have_attribute('aria-busy', 'true')
            if name == '워크플로 실행 증거':
                dialog.locator('select').nth(0).select_option(w.flow['id'])
                expect(dialog.locator('select').nth(1).locator('option')).to_have_count(2)
            if theme == 'light':
                page.screenshot(path=str(shots / ('panel-' + str(['워크플로 실행 증거', '보관된 증거', '직원 품질 검토'].index(name)) + '.png')))
            dialog.get_by_role('button', name='닫기', exact=True).click()
        page.get_by_role('button', name='워크플로 구성·실행 열기', exact=True).click()
        page.evaluate("location.hash='#/home'")
        expect(dialog).to_have_count(0)
        assert not errors and not external
        assert page.evaluate("Object.keys(localStorage).filter(k => k !== 'adm-theme')") == []
    except Exception:
        print('BROWSER ERRORS', errors)
        print('VISIBLE TEXT', page.locator('body').inner_text()[:2500])
        raise
    finally:
        context.close(); client.close()


@pytest.mark.parametrize('fail_at', [1, 2])
def test_audit_failure_never_invites_automatic_reexecution(panels, monkeypatch, fail_at):
    from contextlib import contextmanager
    import sqlite3
    w = panels
    original = w.store.tx
    counter = 0
    class Fault:
        def __init__(self, db): self.db = db
        def __getattr__(self, name): return getattr(self.db, name)
        def execute(self, sql, args=()):
            nonlocal counter
            if 'INSERT INTO admin_audit_logs' in sql and 'WORKSPACE_PANEL_CHANGE' in args:
                counter += 1
                if counter == fail_at: raise sqlite3.OperationalError('synthetic audit failure')
            return self.db.execute(sql, args)
    @contextmanager
    def tx():
        with original() as db: yield Fault(db)
    monkeypatch.setattr(w.store, 'tx', tx)
    response = w.client.post(w.panel + '/typed-flows/' + w.flow['id'] + '/prepare', headers=w.reason, json={'revision': 1})
    if fail_at == 1:
        assert response.status_code == 503 and 'no-store' in response.headers['cache-control']
    else:
        assert response.status_code == 200 and response.headers['x-admin-audit-state'] == 'pending'
        assert response.json()['ticket_id']
    assert not w.calls


def test_open_panel_survives_refresh_but_closes_on_session_end(panels, browser):
    from playwright.sync_api import expect
    from tests.test_workspace_admin_browser import browser_context
    w = panels; shell(w)
    client, context, page, errors, external = browser_context(browser, w.app, 'https://admin.test')
    context.add_init_script('sessionStorage.setItem("adminToken", ' + json.dumps(w.raw) + ');')
    page.clock.install()
    try:
        page.goto('https://admin.test/admin/next#/customers/specialists')
        page.get_by_label('직원 워크스페이스', exact=True).select_option(w.ws)
        page.get_by_role('button', name='워크플로 구성·실행 열기', exact=True).click()
        dialog = page.locator('dialog.adm-specialist-dialog')
        reason = dialog.get_by_label('전문 패널 변경 사유')
        reason.fill('Keep this unsubmitted review reason')
        page.clock.run_for(16000)
        expect(dialog).to_be_visible()
        expect(reason).to_have_value('Keep this unsubmitted review reason')
        assert w.change_reads >= 2
        page.evaluate("sessionStorage.removeItem('adminToken')")
        page.clock.run_for(600)
        expect(dialog).to_have_count(0)
        expect(page.locator('#adm-login')).to_be_visible()
        assert not errors and not external and not w.calls
    finally:
        context.close(); client.close()
