"""Desktop Chromium exercises the actual signed transport and private API offline."""
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from tests.test_front_workflow_browser import browser
from tests.test_provider_claims import provider
from tests.test_workspace_agreements import agreement
from tests.test_workspace_sandbox_payments import sandbox
from tests.test_workspace_sandbox_payments_api import sandbox_api


@pytest.fixture
def sandbox_page(sandbox_api, browser):
    w = sandbox_api
    context = browser.new_context(viewport={'width': 1280, 'height': 900})
    context.set_offline(True)
    w.page = context.new_page(); w.errors = []; w.external = []; w.requests = []
    w.discard_dispatch_response = False
    html = '''<!doctype html><html lang="en"><head><meta charset="utf-8">
<style nonce="fixture">body{font:16px system-ui;background:#f4f6fa;color:#18263b}
.card{border:1px solid #dce3ee;border-radius:12px;padding:16px;margin:12px 0}
button,input,select{font:inherit;padding:8px}label{display:block;margin:12px 0}</style>
</head><body><select id="workspaceSelect"><option value="WORKSPACE">Selected workspace</option></select>
<script nonce="fixture">let token=TOKEN,currentUser={user_id:1,role:'superadmin'};
async function api(path,options={}){const r=await fetch(path,{method:options.method||'GET',
headers:{'X-Dashboard':'1',Authorization:'Bearer '+token,...(options.json?{'Content-Type':'application/json'}:{})},
...(options.json?{body:JSON.stringify(options.json)}:{})});
if(!r.ok)throw Object.assign(new Error('private_request'),{status:r.status});return r.json()}
</script><script nonce="fixture" src="/admin/assets/advancement-admin.js"></script></body></html>'''
    html = html.replace('WORKSPACE', w.ws).replace('TOKEN', json.dumps(w.raw_staff))

    def serve(route):
        request = route.request; url = urlsplit(request.url)
        if url.hostname != 'private.test':
            w.external.append(request.url); route.abort(); return
        w.requests.append((request.method, url.path, request.post_data))
        if url.path == '/admin/sandbox-component':
            route.fulfill(status=200, body=html, headers={'Content-Type': 'text/html',
                'Content-Security-Policy': "default-src 'none'; script-src 'nonce-fixture'; style-src 'nonce-fixture'; connect-src 'self'; base-uri 'none'"})
            return
        if url.path == '/admin/assets/advancement-admin.js':
            route.fulfill(status=200, content_type='application/javascript',
                body=Path('agent_market/gateway/advancement-admin.js').read_text()); return
        result = w.api.request(request.method, url.path, headers=request.headers, content=request.post_data)
        if w.discard_dispatch_response and url.path.endswith('/sandbox-payments/dispatch'):
            w.discard_dispatch_response = False
            route.fulfill(status=503, body='Unconfirmed transport result'); return
        route.fulfill(status=result.status_code, body=result.content,
            headers={k:v for k,v in result.headers.items() if k not in ('content-length','content-encoding','transfer-encoding')})

    context.route('**/*', serve)
    w.page.on('pageerror', lambda error: w.errors.append(str(error)))
    w.page.goto('https://private.test/admin/sandbox-component')
    w.page.evaluate('(ws)=>window.AdvancementAdmin.open(ws)', w.ws)
    expect(w.page.locator('#advancementAdminDialog')).to_be_visible()
    w.page.get_by_role('button', name='Signed event sandbox', exact=True).click()
    expect(w.page.get_by_label('Sandbox integer TEST_UNIT')).to_be_visible()
    try:
        yield w
        assert not w.errors and not w.external
        assert len(w.provider_calls) == 1
    finally:
        context.close()


def prepared(w):
    page = w.page
    page.get_by_label('Sandbox agreement or settlement').select_option(w.agreement['id'])
    page.get_by_label('Sandbox integer TEST_UNIT').fill('101')
    consent = page.get_by_label('Prepare this exact TEST_UNIT event without dispatching it.')
    expect(consent).not_to_be_checked()
    consent.check(); page.get_by_role('button', name='Prepare sandbox event', exact=True).click()
    expect(page.locator('#advancementAdminDialog')).to_contain_text('capture · 101 TEST_UNIT · prepared')


def test_prepare_dispatch_and_refund_have_separate_fresh_desktop_consents(sandbox_page):
    w = sandbox_page; page = w.page; dialog = page.locator('#advancementAdminDialog')
    box = dialog.bounding_box()
    assert abs(box['x'] + box['width'] / 2 - 640) < 2
    assert abs(box['y'] + box['height'] / 2 - 450) < 2
    page.get_by_role('button', name='Prepare sandbox event', exact=True).click()
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_sandbox_payment_intents').fetchone()[0] == 0
    prepared(w)
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_agreement_events').fetchone()[0] == 0
    consent = page.get_by_label('Dispatch this exact signed sandbox event once.')
    expect(consent).not_to_be_checked()
    page.get_by_role('button', name='Dispatch sandbox event', exact=True).click()
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_agreement_events').fetchone()[0] == 0
    consent.check(); page.get_by_role('button', name='Dispatch sandbox event', exact=True).click()
    expect(dialog).to_contain_text('capture · 101 TEST_UNIT · recorded')
    page.get_by_label('Sandbox event action').select_option('refund')
    select = page.get_by_label('Sandbox agreement or settlement')
    target = w.store._db.execute('SELECT id FROM workspace_agreement_settlements').fetchone()[0]
    select.select_option(target); page.get_by_label('Sandbox integer TEST_UNIT').fill('33')
    prepare = page.get_by_label('Prepare this exact TEST_UNIT event without dispatching it.')
    prepare.check(); page.get_by_label('Sandbox integer TEST_UNIT').fill('34')
    expect(prepare).not_to_be_checked()
    prepare.check(); page.get_by_role('button', name='Prepare sandbox event', exact=True).click()
    expect(dialog).to_contain_text('refund · 34 TEST_UNIT · prepared')
    consent = page.get_by_label('Dispatch this exact signed sandbox event once.')
    expect(consent).not_to_be_checked(); consent.check()
    page.get_by_role('button', name='Dispatch sandbox event', exact=True).click()
    expect(dialog).to_contain_text('refund · 34 TEST_UNIT · recorded')
    assert w.agreements.summary(w.ws, w.staff[1])['balanced']
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_agreement_events').fetchone()[0] == 2
    output = Path('reports/advancement-batch7-2026-10-19/sandbox-desktop.png')
    output.parent.mkdir(parents=True, exist_ok=True); page.screenshot(path=str(output), full_page=True)


def test_unconfirmed_response_is_never_retried_and_history_reveals_atomic_receipt(sandbox_page):
    w = sandbox_page; page = w.page; prepared(w)
    w.discard_dispatch_response = True
    page.get_by_label('Dispatch this exact signed sandbox event once.').check()
    page.get_by_role('button', name='Dispatch sandbox event', exact=True).click()
    expect(page.get_by_role('status')).to_contain_text('No request is retried automatically')
    assert len([1 for method,path,_ in w.requests if method == 'POST' and path.endswith('/dispatch')]) == 1
    page.get_by_role('button', name='Read current sandbox history', exact=True).click()
    expect(page.locator('#advancementAdminDialog')).to_contain_text('capture · 101 TEST_UNIT · recorded')
    assert page.get_by_role('button', name='Dispatch sandbox event', exact=True).count() == 0
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_sandbox_payment_receipts').fetchone()[0] == 1


def test_preparation_is_readonly_and_logout_discards_all_private_dialog_state(sandbox_page):
    w = sandbox_page; page = w.page
    page.get_by_role('button', name='Integration preparation', exact=True).click()
    dialog = page.locator('#advancementAdminDialog')
    expect(dialog).to_contain_text('Integration preparation is separate from operating acceptance')
    expect(dialog).to_contain_text('Current operating evidence')
    expect(dialog).to_contain_text('missing')
    assert dialog.locator('input,select').count() == 0
    text = dialog.inner_text()
    for secret in (w.raw_staff, 'synthetic.invalid', 'session_ref', 'client_secret', 'signature'):
        assert secret not in text
    assert not any(method == 'POST' for method,_,_ in w.requests)
    page.evaluate("token='';currentUser=null;window.AdvancementAdmin.onSession()")
    expect(dialog).to_have_count(0)
