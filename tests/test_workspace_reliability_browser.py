"""Offline desktop private evaluation contracts with actual isolated scoped APIs."""
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from tests.test_front_workflow_browser import browser
from tests.test_workspace_reliability import reliability, private_api, setup, sample


@pytest.fixture
def reliability_page(reliability, browser):
    w = setup(reliability); sample(w)
    context = browser.new_context(viewport={'width': 1440, 'height': 1000}); context.set_offline(True)
    page = context.new_page(); w.page = page; w.errors = []; w.unexpected = []; w.browser_requests = []
    html = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><style nonce="fixture">body{font-family:system-ui;background:#f3f6fa;color:#172235}dialog::backdrop{background:#14213988}.card{border:1px solid #dce3ee;border-radius:12px}button,input,select,textarea{font:inherit;padding:9px;border:1px solid #cbd5e3;border-radius:8px}button{cursor:pointer}label{display:block;margin:10px 0}button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:3px solid #527bf5;outline-offset:3px}pre{white-space:pre-wrap}input[type=checkbox]{width:auto}</style></head><body><select id="workspaceSelect"><option value="WORKSPACE">Selected workspace</option></select><script nonce="fixture">let token=TOKEN,currentUser={user_id:1,role:'superadmin'};async function api(path,options={}){const r=await fetch(path,{method:options.method||'GET',headers:{'X-Dashboard':'1',Authorization:'Bearer '+token,...(options.json?{'Content-Type':'application/json'}:{})},...(options.json?{body:JSON.stringify(options.json)}:{})});if(!r.ok)throw Object.assign(new Error('private_evidence_request'),{status:r.status});return r.json()}</script><script nonce="fixture" src="/admin/assets/workspace-reliability-admin.js"></script></body></html>'''.replace('WORKSPACE', w.ws['id']).replace('TOKEN', json.dumps(w.headers['owner']['Authorization'][7:]))
    def serve(route):
        request = route.request; url = urlsplit(request.url)
        if url.hostname != 'admin.test': w.unexpected.append(url.hostname); route.abort(); return
        w.browser_requests.append((request.method, url.path))
        if url.path == '/admin/reliability-component':
            route.fulfill(status=200, body=html, headers={'Content-Type': 'text/html', 'Content-Security-Policy': "default-src 'none';script-src 'nonce-fixture';style-src 'nonce-fixture';connect-src 'self';base-uri 'none';frame-ancestors 'none'"}); return
        if url.path == '/admin/assets/workspace-reliability-admin.js':
            route.fulfill(status=200, body=Path('agent_market/gateway/workspace-reliability-admin.js').read_text(), headers={'Content-Type': 'application/javascript'}); return
        response = w.rel_api.request(request.method, url.path + ('?' + url.query if url.query else ''), headers=request.headers, content=request.post_data)
        route.fulfill(status=response.status_code, body=response.content, headers={k:v for k,v in response.headers.items() if k not in ('content-length','content-encoding','transfer-encoding')})
    context.route('**/*', serve); page.on('pageerror', lambda error: w.errors.append(str(error)))
    page.goto('https://admin.test/admin/reliability-component')
    page.evaluate('(ws)=>window.WorkspaceReliabilityAdmin.open(ws)', w.ws['id'])
    expect(page.get_by_role('status')).to_contain_text('Private evaluation contracts loaded.')
    w.provider_calls_before = len(w.calls)
    try: yield w
    finally: context.close()


def test_desktop_contract_crud_is_explicit_bounded_and_accessible(reliability_page):
    w = reliability_page; page = w.page; dialog = page.locator('#workspaceReliabilityDialog')
    box = dialog.bounding_box(); assert abs(box['x']+box['width']/2-720) < 2 and abs(box['y']+box['height']/2-500) < 2
    assert dialog.get_attribute('aria-labelledby') == 'workspaceReliabilityTitle'
    expect(dialog).to_contain_text('unconfigured; quality remains unassessed')
    expect(dialog.get_by_label('Authorize this exact version for private evaluation contract preparation.')).not_to_be_checked()
    before = len(w.store.query('SELECT id FROM reliability_objects'))
    page.get_by_role('button', name='Save immutable version', exact=True).click()
    expect(page.get_by_role('status')).to_contain_text('Select the purpose-specific authorization')
    assert len(w.store.query('SELECT id FROM reliability_objects')) == before
    page.get_by_label('Authorize this exact version for private evaluation contract preparation.').check()
    page.get_by_role('button', name='Save immutable version', exact=True).click()
    expect(page.get_by_role('status')).to_contain_text('Saved. Current authority and evidence have been read again.')
    assert len(w.store.query('SELECT id FROM reliability_objects')) == before+1
    expect(page.get_by_label('Authorize this exact version for private evaluation contract preparation.')).not_to_be_checked()
    assert not w.errors and not w.unexpected and len(w.calls) == w.provider_calls_before
    folder = Path('reports/advancement-phase2-core-2026-10-19/evidence'); folder.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(folder/'private-evaluation-desktop.png'), full_page=True)


def test_private_source_inspection_is_text_escaped_erasure_is_permanent_and_session_change_clears_content(reliability_page):
    w = reliability_page; page = w.page
    inspect = page.get_by_label('Inspect this private source for the authorized evaluation purpose.')
    expect(inspect).not_to_be_checked(); inspect.check()
    page.get_by_role('button', name='Inspect private source', exact=True).click()
    expect(page.locator('#workspaceReliabilityDialog')).to_contain_text('<img src=x onerror=alert(1)>')
    assert page.locator('#workspaceReliabilityDialog img').count() == 0
    erase = page.get_by_label('Permanently erase this source and prevent this bundle from qualifying again.')
    expect(erase).not_to_be_checked(); erase.check()
    page.get_by_role('button', name='Erase source permanently', exact=True).click()
    expect(page.get_by_role('status')).to_contain_text('Saved. Current authority and evidence have been read again.')
    assert not w.store.query('SELECT id FROM reliability_sources')
    assert len(w.store.query('SELECT target_id FROM reliability_tombstones')) == 2
    page.evaluate("token='';currentUser=null;window.WorkspaceReliabilityAdmin.onSession()")
    expect(page.locator('#workspaceReliabilityDialog')).to_have_count(0)
    assert not w.errors and not w.unexpected and len(w.calls) == w.provider_calls_before
