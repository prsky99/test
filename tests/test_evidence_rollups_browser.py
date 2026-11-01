"""Offline desktop evidence dialog backed by actual isolated scoped APIs."""
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from tests.test_evidence_rollups import evidence, private_api
from tests.test_workspace_execution_api import execute
from tests.test_front_workflow_browser import browser


@pytest.fixture
def evidence_page(evidence, browser):
    w = evidence; execute(w); before = len(w.calls)
    context = browser.new_context(viewport={'width': 1280, 'height': 900}); context.set_offline(True)
    page = context.new_page(); w.page = page; w.errors = []; w.unexpected = []; w.browser_requests = []
    raw = w.headers['owner']['Authorization'][7:]
    html = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><style nonce="fixture">body{font-family:system-ui;background:#f3f6fa;color:#172235}dialog::backdrop{background:#14213988}.card{border:1px solid #dce3ee;border-radius:12px}.row{display:flex;align-items:center;gap:12px;flex-wrap:wrap}button,input,select{font:inherit;padding:9px;border:1px solid #cbd5e3;border-radius:8px}button{cursor:pointer}label{display:block;margin:10px 0}h2{display:flex;align-items:center;gap:8px}button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #527bf5;outline-offset:3px}</style></head><body><select id="workspaceSelect"><option value="WORKSPACE">Selected workspace</option></select><script nonce="fixture">let token=TOKEN,currentUser={user_id:1,role:'superadmin'};async function api(path,options={}){const r=await fetch(path,{method:options.method||'GET',headers:{'X-Dashboard':'1',Authorization:'Bearer '+token,...(options.json?{'Content-Type':'application/json'}:{})},...(options.json?{body:JSON.stringify(options.json)}:{})});if(!r.ok)throw Object.assign(new Error('evidence_request'),{status:r.status});return r.json()}</script><script nonce="fixture" src="/admin/assets/workspace-evidence-admin.js"></script></body></html>'''.replace('WORKSPACE', w.ws['id']).replace('TOKEN', json.dumps(raw))
    def serve(route):
        request = route.request; url = urlsplit(request.url)
        if url.hostname != 'private.test': w.unexpected.append(url.hostname); route.abort(); return
        w.browser_requests.append((request.method, url.path))
        if url.path == '/admin/evidence-component':
            route.fulfill(status=200, body=html, headers={'Content-Type':'text/html','Content-Security-Policy':"default-src 'none';script-src 'nonce-fixture';style-src 'nonce-fixture';connect-src 'self';base-uri 'none';frame-ancestors 'none'"}); return
        if url.path == '/admin/assets/workspace-evidence-admin.js':
            result = w.client.get(url.path)
        else:
            result = w.ev_api.request(request.method, url.path + ('?' + url.query if url.query else ''), headers=request.headers, content=request.post_data)
        route.fulfill(status=result.status_code, body=result.content, headers={key:value for key,value in result.headers.items() if key not in ('content-length','content-encoding','transfer-encoding')})
    context.route('**/*', serve); page.on('pageerror', lambda error: w.errors.append(str(error)))
    page.goto('https://private.test/admin/evidence-component')
    page.evaluate('(ws)=>window.WorkspaceEvidenceAdmin.open(ws)', w.ws['id'])
    expect(page.locator('#workspaceEvidenceDialog')).to_contain_text('Current retained evidence loaded.')
    w.initial_provider_calls = before
    try: yield w
    finally: context.close()


def test_native_desktop_dialog_is_centered_accessible_metadata_only_and_withdrawal_is_explicit(evidence_page):
    w = evidence_page; page = w.page; dialog = page.locator('#workspaceEvidenceDialog')
    box = dialog.bounding_box(); assert abs(box['x'] + box['width']/2 - 640) < 2
    assert abs(box['y'] + box['height']/2 - 450) < 2
    assert dialog.get_attribute('aria-labelledby') == 'workspaceEvidenceTitle'
    expect(dialog).to_contain_text('Quality is unassessed.')
    assert 'Private research result' not in dialog.inner_text() and 'private-provider.example' not in dialog.inner_text()
    consent = dialog.get_by_label('Withdraw this exact source from this workspace scope. This is permanent and does not delete or rewrite the original record.')
    expect(consent).not_to_be_checked(); page.get_by_role('button', name='Withdraw source', exact=True).click()
    assert w.store.query('SELECT COUNT(*) FROM evidence_rollup_audit')[0][0] == 0
    consent.check(); page.get_by_role('button', name='Withdraw source', exact=True).click()
    expect(dialog).to_contain_text('withdrawn: 1')
    expect(page.get_by_role('button', name='Withdraw source', exact=True)).to_have_count(0)
    assert w.store.query('SELECT COUNT(*) FROM evidence_rollup_audit')[0][0] == 1
    assert len(w.calls) == w.initial_provider_calls and not w.errors and not w.unexpected
    folder = Path('reports/advancement-batch7-2026-10-19/evidence'); folder.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(folder/'desktop-dialog.png'), full_page=True)


def test_scope_selection_and_session_change_discard_visible_private_state(evidence_page):
    w = evidence_page; page = w.page; dialog = page.locator('#workspaceEvidenceDialog')
    selector = dialog.get_by_label('Evidence scope'); selector.select_option('catalog')
    expect(dialog).not_to_contain_text('Logical observations 1; succeeded 1')
    page.get_by_role('button', name='Read current evidence', exact=True).click()
    expect(dialog).to_contain_text('Evidence scope: catalog.')
    page.evaluate("token='';currentUser=null;window.WorkspaceEvidenceAdmin.onSession()")
    expect(dialog).to_have_count(0)
    assert not w.errors and not w.unexpected and len(w.calls) == w.initial_provider_calls
