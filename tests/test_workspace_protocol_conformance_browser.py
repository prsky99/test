"""Desktop browser exercises the actual private component without external calls."""
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from tests.test_front_workflow_browser import browser
from tests.test_workspace_protocol_conformance_api import conformance_api
from tests.test_workspace_protocol_conformance import conformance
from tests.test_workspace_sandbox_payments import sandbox, prepare, dispatch
from tests.test_workspace_agreements import agreement
from tests.test_provider_claims import provider
from tests.test_workspace_crypto_inspection_api import body as crypto_body
from tests.test_workspace_x402_eip3009 import NOW


@pytest.fixture
def protocol_page(conformance_api, browser):
    w = conformance_api; w.capture = prepare(w); dispatch(w, w.capture)
    context = browser.new_context(viewport={'width': 1280, 'height': 900})
    context.set_offline(True); w.page = context.new_page(); w.errors = []; w.external = []; w.posts = []; w.crypto_responses = []
    w.discard_response = False
    html = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><style nonce="fixture">
body{font:16px system-ui;background:#f4f6fa;color:#18263b}.card{border:1px solid #dce3ee;border-radius:12px;padding:16px;margin:12px 0}button,input,select{font:inherit;padding:8px}label{display:block;margin:12px 0}
</style></head><body><select id="workspaceSelect"><option value="WORKSPACE">Selected workspace</option></select>
<script nonce="fixture">let token=TOKEN,currentUser={user_id:1,role:'superadmin'};
async function api(path,options={}){const r=await fetch(path,{method:options.method||'GET',headers:{'X-Dashboard':'1',Authorization:'Bearer '+token,...(options.json?{'Content-Type':'application/json'}:{})},...(options.json?{body:JSON.stringify(options.json)}:{})});if(!r.ok)throw Object.assign(Error('private_request'),{status:r.status});return r.json()}
</script><script nonce="fixture" src="/admin/assets/workspace-protocol-conformance-admin.js"></script></body></html>'''
    html = html.replace('WORKSPACE', w.ws).replace('TOKEN', json.dumps(w.raw_staff))
    def serve(route):
        request = route.request; url = urlsplit(request.url)
        if url.hostname != 'private.test': w.external.append(request.url); route.abort(); return
        if url.path == '/admin/protocol-component':
            route.fulfill(status=200, body=html, headers={'Content-Type': 'text/html',
                'Content-Security-Policy': "default-src 'none'; script-src 'nonce-fixture'; style-src 'nonce-fixture'; connect-src 'self'; base-uri 'none'"}); return
        if request.method == 'POST': w.posts.append((url.path, request.post_data))
        result = w.api.request(request.method, url.path, headers=request.headers, content=request.post_data)
        if url.path.endswith('/cryptographic-check'):
            w.crypto_responses.append((result.status_code, result.json()))
        if w.discard_response and url.path.endswith('/runs'):
            w.discard_response = False; route.fulfill(status=503, body='Unconfirmed report response'); return
        route.fulfill(status=result.status_code, body=result.content,
            headers={key: value for key, value in result.headers.items() if key not in ('content-length', 'content-encoding', 'transfer-encoding')})
    context.route('**/*', serve)
    w.page.on('pageerror', lambda error: w.errors.append(str(error)))
    w.page.goto('https://private.test/admin/protocol-component')
    w.page.evaluate('(ws)=>window.WorkspaceProtocolConformanceAdmin.open(ws)', w.ws)
    expect(w.page.locator('#workspaceProtocolConformanceDialog')).to_be_visible()
    expect(w.page.get_by_role('status', name='Protocol review status', exact=True)).to_contain_text('Current private review state loaded')
    try:
        yield w
        assert not w.errors and not w.external
        assert len(w.provider_calls) == 1
    finally:
        context.close()


def test_centered_report_consent_resets_source_change_and_does_not_dispatch_payment(protocol_page):
    w = protocol_page; page = w.page; dialog = page.locator('#workspaceProtocolConformanceDialog')
    box = dialog.bounding_box()
    assert abs(box['x'] + box['width'] / 2 - 640) < 2
    assert abs(box['y'] + box['height'] / 2 - 450) < 2
    submit = page.get_by_role('button', name='Record synthetic conformance review')
    consent = page.get_by_label('Review these exact retained sandbox records without creating financial events.')
    expect(consent).not_to_be_checked(); expect(submit).to_be_disabled()
    page.get_by_label('Existing sandbox capture').select_option(w.capture['id'])
    consent.check(); expect(submit).to_be_enabled()
    page.get_by_label('Synthetic wire profile').select_option('x402-v2-http-batch-fixture-v1')
    expect(consent).not_to_be_checked(); expect(submit).to_be_disabled()
    consent.check(); submit.click()
    expect(page.get_by_role('status', name='Protocol review status', exact=True)).to_contain_text('No financial event was created')
    expect(dialog).to_contain_text('commitment: synthetic_fixture_only')
    expect(dialog).to_contain_text('payout: disabled')
    expect(consent).not_to_be_checked()
    assert len(w.posts) == 1
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_agreement_events').fetchone()[0] == 1
    assert all(secret not in dialog.inner_text() for secret in (w.raw_staff, 'session_ref', 'synthetic.invalid'))
    out = Path('reports/advancement-rnd-source-2026-10-19/protocol-sdk')
    out.mkdir(parents=True, exist_ok=True); page.screenshot(path=str(out / 'protocol-conformance-desktop.png'))


def test_lost_report_ack_reads_committed_history_without_automatic_retry_and_logout_clears_modal(protocol_page):
    w = protocol_page; page = w.page; w.discard_response = True
    page.get_by_label('Existing sandbox capture').select_option(w.capture['id'])
    page.get_by_label('Review these exact retained sandbox records without creating financial events.').check()
    page.get_by_role('button', name='Record synthetic conformance review').click()
    expect(page.get_by_role('status', name='Protocol review status', exact=True)).to_contain_text('No request is retried automatically')
    assert len(w.posts) == 1
    page.get_by_role('button', name='Read current protocol history').click()
    expect(page.locator('#workspaceProtocolConformanceDialog')).to_contain_text('wire subset passed')
    assert len(w.posts) == 1 and w.store._db.execute('SELECT COUNT(*) FROM workspace_protocol_reports').fetchone()[0] == 1
    page.evaluate("token='';currentUser=null;window.WorkspaceProtocolConformanceAdmin.onSession()")
    expect(page.locator('#workspaceProtocolConformanceDialog')).to_have_count(0)


def financial_counts(w):
    return {table: w.store._db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
        for table in ('workspace_sandbox_payment_intents', 'workspace_agreement_events', 'workspace_protocol_reports')}


def test_offline_signature_requires_fresh_consent_after_edit_and_never_creates_payment(protocol_page, monkeypatch):
    w = protocol_page; page = w.page
    # Replace this module's clock object only. Staff sessions, ledger clocks and
    # the browser keep their actual clocks and current authority boundaries.
    monkeypatch.setattr('agent_market.workspace_x402_eip3009.time', SimpleNamespace(time=lambda: NOW))
    proof = page.get_by_label('Public proof and independently pinned context', exact=True)
    consent = page.get_by_label('Inspect this exact public proof without authorizing any transaction.', exact=False)
    inspect = page.get_by_role('button', name='Inspect offline signature', exact=True)
    output = page.get_by_role('status', name='Offline signature inspection status', exact=True)
    before = financial_counts(w)
    expect(consent).not_to_be_checked(); expect(inspect).to_be_disabled()
    proof.fill(json.dumps(crypto_body()))
    expect(inspect).to_be_disabled()
    consent.check(); expect(inspect).to_be_enabled()
    # Any edit invalidates this exact-input approval, even if whitespace is the
    # only difference. No inspection happens while filling or granting consent.
    proof.fill(json.dumps(crypto_body(), indent=2))
    expect(consent).not_to_be_checked(); expect(inspect).to_be_disabled()
    assert not w.posts and not w.crypto_responses
    consent.check(); inspect.click()
    expect(output).to_contain_text('Signature and local context matched')
    expect(output).to_contain_text('settlement remain unverified')
    expect(output).to_contain_text('No transaction or ledger event was created')
    expect(consent).not_to_be_checked(); expect(inspect).to_be_disabled()
    assert len(w.posts) == len(w.crypto_responses) == 1
    assert w.posts[0][0].endswith('/cryptographic-check')
    status, response = w.crypto_responses[0]
    result = response['result']
    assert status == 200 and result['signature_valid'] is True
    assert result['verified_payment'] is result['settlement_authorized'] is False
    assert result['rpc_calls'] == result['broadcasts'] == result['ledger_events'] == 0
    assert 'recovered_from' not in result and 'nonce_reference' not in result
    assert financial_counts(w) == before and len(w.provider_calls) == 1
    assert w.raw_staff not in page.locator('#workspaceProtocolConformanceDialog').inner_text()
    # A fresh current-state read does not re-inspect the submitted proof.
    page.get_by_role('button', name='Read current protocol history', exact=True).click()
    expect(page.get_by_role('status', name='Protocol review status', exact=True)).to_contain_text('Current private review state loaded')
    expect(page.get_by_label('Public proof and independently pinned context', exact=True)).to_have_value('')
    expect(page.get_by_label('Inspect this exact public proof without authorizing any transaction.', exact=False)).not_to_be_checked()
    assert len(w.crypto_responses) == 1 and financial_counts(w) == before


def test_wrong_offline_proof_shows_only_safe_failure_and_no_automatic_repeat(protocol_page, monkeypatch):
    w = protocol_page; page = w.page
    monkeypatch.setattr('agent_market.workspace_x402_eip3009.time', SimpleNamespace(time=lambda: NOW))
    payload = crypto_body()
    marker = 'untrusted-proof-marker-do-not-display-in-response'
    payload['payment']['payload']['signature'] = marker
    proof = page.get_by_label('Public proof and independently pinned context', exact=True)
    consent = page.get_by_label('Inspect this exact public proof without authorizing any transaction.', exact=False)
    output = page.get_by_role('status', name='Offline signature inspection status', exact=True)
    before = financial_counts(w)
    proof.fill(json.dumps(payload)); consent.check()
    assert not w.posts
    page.get_by_role('button', name='Inspect offline signature', exact=True).click()
    expect(output).to_have_text('The proof or current permission could not be validated. No transaction was submitted.')
    expect(consent).not_to_be_checked()
    assert len(w.crypto_responses) == 1 and w.crypto_responses[0][0] == 400
    assert len(w.posts) == 1 and financial_counts(w) == before and len(w.provider_calls) == 1
    visible = page.locator('#workspaceProtocolConformanceDialog').inner_text()
    assert all(value not in visible for value in (marker, w.raw_staff, 'session_ref', 'Traceback', '"detail"', '"result"'))
    assert page.locator('#workspaceProtocolConformanceDialog script, #workspaceProtocolConformanceDialog iframe').count() == 0
    page.get_by_role('button', name='Read current protocol history', exact=True).click()
    expect(page.get_by_role('status', name='Protocol review status', exact=True)).to_contain_text('Current private review state loaded')
    assert len(w.crypto_responses) == 1 and len(w.posts) == 1 and financial_counts(w) == before
