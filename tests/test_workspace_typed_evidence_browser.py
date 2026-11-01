"""Desktop typed lineage uses real isolated APIs and never invokes providers."""
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from tests.test_front_workflow_browser import browser
from tests.test_workflow_fallback import routing
from tests.test_workspace_typed_flows import typed_world, run
from tests.test_workspace_typed_evidence import typed_evidence


@pytest.fixture
def typed_evidence_page(typed_evidence, browser):
    w = typed_evidence; w.result, _ = run(w, w.flow)
    context = browser.new_context(viewport={'width': 1440, 'height': 1000}); context.set_offline(True)
    page = context.new_page(); w.page = page; w.errors = []; w.unexpected = []; w.requests = []
    html = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><style nonce="fixture">body{font-family:system-ui;background:#f3f6fa;color:#172235}dialog::backdrop{background:#14213988}.card{border:1px solid #dce3ee;border-radius:12px}button,input,select,textarea{font:inherit;padding:9px;border:1px solid #cbd5e3;border-radius:8px}button{cursor:pointer}label{display:block;margin:10px 0}button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:3px solid #527bf5;outline-offset:3px}input[type=checkbox]{width:auto}</style></head><body><select id="workspaceSelect"><option value="WORKSPACE">Selected workspace</option></select><script nonce="fixture">let token=TOKEN,currentUser={user_id:1,role:'superadmin'};async function api(path,options={}){const response=await fetch(path,{method:options.method||'GET',headers:{'X-Dashboard':'1',Authorization:'Bearer '+token,...(options.json?{'Content-Type':'application/json'}:{})},...(options.json?{body:JSON.stringify(options.json)}:{})});if(!response.ok)throw Object.assign(new Error('private_lineage_request'),{status:response.status});return response.json()}</script><script nonce="fixture" src="/admin/assets/workspace-typed-evidence-admin.js"></script></body></html>'''.replace('WORKSPACE', w.ws).replace('TOKEN', json.dumps(w.raw))
    def serve(route):
        request = route.request; url = urlsplit(request.url)
        if url.hostname != 'admin.test': w.unexpected.append(url.hostname); route.abort(); return
        w.requests.append((request.method, url.path))
        if url.path == '/admin/typed-evidence-component':
            route.fulfill(status=200, body=html, headers={'Content-Type': 'text/html', 'Content-Security-Policy': "default-src 'none';script-src 'nonce-fixture';style-src 'nonce-fixture';connect-src 'self';base-uri 'none';frame-ancestors 'none'"}); return
        if url.path == '/admin/assets/workspace-typed-evidence-admin.js':
            route.fulfill(status=200, body=Path('agent_market/gateway/workspace-typed-evidence-admin.js').read_text(), headers={'Content-Type': 'application/javascript'}); return
        response = w.client.request(request.method, url.path + ('?' + url.query if url.query else ''), headers=request.headers, content=request.post_data)
        route.fulfill(status=response.status_code, body=response.content, headers={key:value for key,value in response.headers.items() if key not in ('content-length','content-encoding','transfer-encoding')})
    context.route('**/*', serve); page.on('pageerror', lambda error: w.errors.append(str(error)))
    page.goto('https://admin.test/admin/typed-evidence-component')
    page.evaluate('(ws)=>window.WorkspaceTypedEvidenceAdmin.open(ws)', w.ws)
    expect(page.get_by_role('status')).to_contain_text('Private typed lineage ready.')
    page.get_by_label('Typed flow', exact=False).select_option(w.flow['id'])
    expect(page.get_by_label('Signed execution', exact=False).locator('option')).to_have_count(2)
    page.get_by_label('Signed execution', exact=False).select_option(w.result['run']['id'])
    expect(page.get_by_role('status')).to_contain_text('Current signed lineage loaded.')
    w.calls_before = list(w.calls)
    try: yield w
    finally: context.close()


def test_central_desktop_dialog_explicit_retention_and_session_cleanup(typed_evidence_page):
    w = typed_evidence_page; page = w.page; dialog = page.locator('#workspaceTypedEvidenceDialog')
    box = dialog.bounding_box(); assert abs(box['x']+box['width']/2-720) < 2 and abs(box['y']+box['height']/2-500) < 2
    assert dialog.get_attribute('aria-labelledby') == 'workspaceTypedEvidenceTitle'
    confirm = page.get_by_label('Authorize encrypted retention', exact=False)
    expect(confirm).not_to_be_checked()
    page.get_by_role('button', name='Retain existing node sources', exact=True).click()
    expect(page.get_by_role('status')).to_contain_text('select the purpose-specific retention authorization')
    assert not w.store.query('SELECT * FROM reliability_sources')
    page.get_by_label('Current node consent and case references', exact=False).fill(json.dumps(w.bindings))
    confirm.check(); page.get_by_role('button', name='Retain existing node sources', exact=True).click()
    expect(page.get_by_role('status')).to_contain_text('Existing sources retained under current permission.')
    expect(confirm).not_to_be_checked()
    expect(dialog).to_contain_text('Current retained sources are available.')
    expect(dialog).to_contain_text('query')
    assert len(w.store.query('SELECT * FROM reliability_observations')) == 2
    assert page.locator('img').count() == 0 and w.calls == w.calls_before and not w.errors and not w.unexpected
    page.evaluate("token='';currentUser=null;window.WorkspaceTypedEvidenceAdmin.onSession()")
    expect(dialog).to_have_count(0)


def test_workspace_switch_closes_private_content_without_retention(typed_evidence_page):
    w = typed_evidence_page
    w.page.evaluate("document.getElementById('workspaceSelect').value='';window.WorkspaceTypedEvidenceAdmin.onSession()")
    expect(w.page.locator('#workspaceTypedEvidenceDialog')).to_have_count(0)
    assert not w.store.query('SELECT * FROM reliability_sources') and w.calls == w.calls_before
    assert not w.errors and not w.unexpected
