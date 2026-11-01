"""Offline native agreement component backed by actual isolated private APIs."""
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect
import pytest

from agent_market.provider_claims_service import router_for
from tests.test_workspace_agreements_api import agreements_api, agreement
from tests.test_provider_claims import provider
from tests.test_front_workflow_browser import browser
from tests.test_workspace_execution_api import private_api
from tests.test_workspace_browser import sign_in, select_space


@pytest.fixture
def agreement_page(agreements_api, browser):
    w = agreements_api
    w.app.include_router(router_for(w.store, b'synthetic-provider-claim-key32!!!', claims=w.claims))
    context = browser.new_context(viewport={'width': 1280, 'height': 900}); context.set_offline(True)
    page = context.new_page(); w.page = page; w.errors = []; w.unexpected = []; w.requests = []
    html = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><style nonce="fixture">body{font-family:system-ui;background:#f4f6fa;color:#18263b}dialog{border:1px solid #dce3ee;border-radius:18px;padding:24px}.card{border:1px solid #dce3ee;border-radius:12px;margin:16px 0;padding:18px}.form-group{display:flex;flex-direction:column;gap:6px;margin:12px 0}.row{display:flex;align-items:center}button,input,select{font:inherit;padding:9px;border:1px solid #ccd7e8;border-radius:7px}label{display:block;margin:12px 0}</style></head><body><select id="workspaceSelect"><option value="WORKSPACE">Selected workspace</option></select><script nonce="fixture">let token=TOKEN,currentUser={user_id:1,role:'superadmin'};async function api(path,options={}){const r=await fetch(path,{method:options.method||'GET',headers:{'X-Dashboard':'1',Authorization:'Bearer '+token,...(options.json?{'Content-Type':'application/json'}:{})},...(options.json?{body:JSON.stringify(options.json)}:{})});if(!r.ok)throw Object.assign(new Error('private_request'),{status:r.status});return r.json()}</script><script nonce="fixture" src="/admin/assets/workspace-agreement-admin.js"></script></body></html>'''.replace('WORKSPACE', w.ws).replace('TOKEN', json.dumps(w.raw_staff))
    def serve(route):
        request = route.request; url = urlsplit(request.url)
        if url.hostname != 'private.test': w.unexpected.append(request.url); route.abort(); return
        w.requests.append((request.method, url.path, request.post_data))
        if url.path == '/admin/agreement-component':
            route.fulfill(status=200, body=html, headers={'Content-Type': 'text/html', 'Content-Security-Policy': "default-src 'none'; script-src 'nonce-fixture'; style-src 'nonce-fixture'; connect-src 'self'; base-uri 'none'"}); return
        if url.path == '/admin/assets/workspace-agreement-admin.js':
            route.fulfill(status=200, content_type='application/javascript', body=Path('agent_market/gateway/workspace-agreement-admin.js').read_text()); return
        result = w.api.request(request.method, url.path, headers=request.headers, content=request.post_data)
        if result.status_code == 404: w.errors.append('Unexpected unavailable path: ' + url.path)
        route.fulfill(status=result.status_code, body=result.content, headers={key:value for key,value in result.headers.items() if key not in ('content-length','content-encoding','transfer-encoding')})
    context.route('**/*', serve); page.on('pageerror', lambda error: w.errors.append(str(error)))
    page.goto('https://private.test/admin/agreement-component')
    page.evaluate('(ws)=>window.WorkspaceAgreementAdmin.open(ws)', w.ws)
    expect(page.locator('#workspaceAgreementDialog')).to_be_visible()
    expect(page.locator('#workspaceAgreementDialog')).to_contain_text('Current records loaded.')
    try:
        yield w
    finally:
        context.close()


def test_quote_capture_refund_and_revoke_have_fresh_separate_unchecked_consents(agreement_page):
    w = agreement_page; page = w.page; dialog = page.locator('#workspaceAgreementDialog')
    rectangle = dialog.bounding_box(); assert abs(rectangle['x'] + rectangle['width'] / 2 - 640) < 2
    assert abs(rectangle['y'] + rectangle['height'] / 2 - 450) < 2
    page.get_by_role('button', name='Preview allocation', exact=True).click()
    consent = page.get_by_label('Record this exact allocation once in TEST_UNIT simulation. No payment or payout will occur.')
    expect(consent).not_to_be_checked()
    page.get_by_role('button', name='Record simulated settlement', exact=True).click()
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_agreement_events').fetchone()[0] == 0
    consent.check(); page.get_by_label('Gross TEST_UNIT for version 1').fill('101')
    expect(page.get_by_role('button', name='Record simulated settlement', exact=True)).to_have_count(0)
    page.get_by_role('button', name='Preview allocation', exact=True).click(); expect(consent).not_to_be_checked()
    consent.check(); page.get_by_role('button', name='Record simulated settlement', exact=True).click()
    expect(dialog).to_contain_text('cumulative refund 0 TEST_UNIT')
    refund = page.get_by_label('Record this exact incremental simulated refund once under the original agreement terms.')
    expect(refund).not_to_be_checked(); page.get_by_role('button', name='Record simulated refund', exact=True).click()
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_agreement_events').fetchone()[0] == 1
    refund.check(); dialog.locator('input[type=number]').last.fill('21'); expect(refund).not_to_be_checked()
    refund.check(); page.get_by_role('button', name='Record simulated refund', exact=True).click()
    expect(dialog).to_contain_text('cumulative refund 21 TEST_UNIT')
    revoke = page.get_by_label('Revoke this exact agreement version for new simulation captures.')
    expect(revoke).not_to_be_checked(); revoke.check(); page.get_by_role('button', name='Revoke version', exact=True).click()
    expect(dialog).to_contain_text('revoked · revision 2')
    assert len(w.provider_calls) == 1 and not w.errors and not w.unexpected
    assert len([path for method,path,_ in w.requests if method == 'POST' and path.endswith('/settle')]) == 1
    Path('reports/workspace-agreements-2026-10-18').mkdir(parents=True, exist_ok=True)
    page.screenshot(path='reports/workspace-agreements-2026-10-18/admin-dialog.png', full_page=True)


def test_new_terms_form_and_session_change_discard_private_state(agreement_page):
    w = agreement_page; page = w.page; dialog = page.locator('#workspaceAgreementDialog')
    selector = dialog.get_by_label('Current verified endpoint claim')
    selector.select_option(w.verified['id'])
    page.get_by_label('Opaque terms document reference').fill('synthetic-second-terms')
    page.get_by_label('Terms document SHA-256').fill('b' * 64)
    consent = page.get_by_label('Record this exact 70% provider / 30% platform TEST_UNIT simulation agreement as legally unverified.')
    expect(consent).not_to_be_checked(); page.get_by_role('button', name='Record agreement version', exact=True).click()
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_provider_agreements').fetchone()[0] == 1
    consent.check(); page.get_by_label('Processing deduction basis points').fill('100'); expect(consent).not_to_be_checked()
    consent.check(); page.get_by_role('button', name='Record agreement version', exact=True).click()
    expect(dialog).to_contain_text('Resource 1 · agreement version 2')
    assert dialog.locator('script,img,iframe').count() == 0
    page.evaluate("token='';currentUser=null;window.WorkspaceAgreementAdmin.onSession()")
    expect(dialog).to_have_count(0)
    assert not w.errors and not w.unexpected and len(w.provider_calls) == 1


def test_small_viewport_keeps_native_dialog_centered_and_contents_within_width(agreement_page):
    w = agreement_page; w.page.set_viewport_size({'width': 390, 'height': 844})
    dialog = w.page.locator('#workspaceAgreementDialog')
    box = dialog.bounding_box()
    assert 0 <= box['x'] and box['x'] + box['width'] <= 390
    assert abs(box['x'] + box['width'] / 2 - 195) < 2
    assert dialog.evaluate('e=>e.scrollWidth<=e.clientWidth')
    Path('reports/workspace-agreements-2026-10-18').mkdir(parents=True, exist_ok=True)
    w.page.screenshot(path='reports/workspace-agreements-2026-10-18/admin-dialog-mobile.png', full_page=True)
    assert not w.errors and not w.unexpected


def test_actual_dashboard_loads_fixed_module_and_empty_provider_state_without_fake_evidence(private_api, browser):
    w = private_api; context = browser.new_context(); context.set_offline(True)
    w.page = context.new_page(); errors = []; external = []
    def serve(route):
        request = route.request; url = urlsplit(request.url)
        if url.hostname != 'admin.test': external.append(request.url); route.abort(); return
        result = w.client.request(request.method, url.path + ('?' + url.query if url.query else ''), headers=request.headers, content=request.post_data)
        route.fulfill(status=result.status_code, body=result.content, headers={key:value for key,value in result.headers.items() if key not in ('content-length','content-encoding','transfer-encoding')})
    context.route('**/*', serve); w.page.on('pageerror', lambda error: errors.append(str(error)))
    try:
        sign_in(w); select_space(w, w.ws)
        assert w.page.evaluate('Boolean(window.WorkspaceAgreementAdmin)')
        w.page.evaluate('(ws)=>window.WorkspaceAgreementAdmin.open(ws)', w.ws['id'])
        dialog = w.page.locator('#workspaceAgreementDialog')
        expect(dialog).to_be_visible(); expect(dialog).to_contain_text('No verified endpoint claim is available.')
        expect(dialog).to_contain_text('No agreement versions have been recorded.')
        assert w.store.query('SELECT COUNT(*) FROM workspace_provider_agreements')[0][0] == 0
        w.page.locator('#workspaceSelect').select_option('')
        expect(dialog).to_have_count(0)
        assert not errors and not external and not w.calls
    finally:
        context.close()
