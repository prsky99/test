"""Offline Chromium security checks for the private desktop reliability controls."""
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from tests.test_reliability_controls import controls, private_api, post, routing_policy
from tests.test_front_workflow_browser import browser


@pytest.fixture
def reliability_page(controls, browser):
    w = controls
    context = browser.new_context(viewport={'width': 1280, 'height': 900}, reduced_motion='reduce')
    context.set_offline(True); page = context.new_page(); w.page = page
    w.errors = []; w.unexpected = []; w.browser_writes = []
    script = Path('agent_market/gateway/workspace-reliability-controls-admin.js').read_text()
    html = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><style nonce="fixture">body{font-family:system-ui;background:#f3f6fa;color:#172235}dialog::backdrop{background:#14213988}.card{border:1px solid #dce3ee;border-radius:12px}button,input,select{font:inherit;padding:9px;border:1px solid #cbd5e3;border-radius:8px}button{cursor:pointer}label{display:block;margin:10px 0}button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #527bf5;outline-offset:3px}</style></head><body><select id="workspaceSelect"><option value="WORKSPACE">Selected workspace</option></select><script nonce="fixture">let token=TOKEN,currentUser={user_id:1,role:'superadmin'};async function api(path,options={}){const r=await fetch(path,{method:options.method||'GET',headers:{'X-Dashboard':'1',Authorization:'Bearer '+token,...(options.json?{'Content-Type':'application/json'}:{})},...(options.json?{body:JSON.stringify(options.json)}:{})});if(!r.ok)throw Object.assign(new Error('private_request'),{status:r.status});return r.json()}</script><script nonce="fixture" src="/admin/assets/workspace-reliability-controls-admin.js"></script></body></html>'''.replace('WORKSPACE', w.ws['id']).replace('TOKEN', json.dumps(w.headers['owner']['Authorization'][7:]))
    def serve(route):
        request = route.request; url = urlsplit(request.url)
        if url.hostname != 'private.test':
            w.unexpected.append(url.hostname); route.abort(); return
        if url.path == '/admin/reliability-controls-component':
            route.fulfill(status=200, body=html, headers={'Content-Type': 'text/html', 'Content-Security-Policy': "default-src 'none';script-src 'nonce-fixture';style-src 'nonce-fixture';connect-src 'self';base-uri 'none';frame-ancestors 'none'"}); return
        if url.path == '/admin/assets/workspace-reliability-controls-admin.js':
            route.fulfill(status=200, body=script, headers={'Content-Type': 'application/javascript'}); return
        if request.method != 'GET':
            w.browser_writes.append(url.path)
        result = w.control_api.request(request.method, url.path, headers=request.headers, content=request.post_data)
        route.fulfill(status=result.status_code, body=result.content, headers={key: value for key, value in result.headers.items() if key not in ('content-length', 'content-encoding', 'transfer-encoding')})
    context.route('**/*', serve); page.on('pageerror', lambda error: w.errors.append(str(error)))
    page.goto('https://private.test/admin/reliability-controls-component')
    page.evaluate('(ws)=>window.WorkspaceReliabilityControlsAdmin.open(ws)', w.ws['id'])
    expect(page.locator('#workspaceReliabilityControlsDialog')).to_contain_text('Current private controls loaded.')
    try:
        yield w
    finally:
        context.close()


def test_private_desktop_dialog_requires_per_purpose_consent_and_safe_trust_rendering(reliability_page):
    w = reliability_page; page = w.page; dialog = page.locator('#workspaceReliabilityControlsDialog')
    box = dialog.bounding_box(); assert abs(box['x']+box['width']/2-640) < 2
    assert dialog.get_attribute('aria-labelledby') == 'workspaceReliabilityControlsTitle'
    for checkbox in dialog.get_by_role('checkbox').all():
        expect(checkbox).not_to_be_checked()
    page.get_by_role('button', name='Enable evaluation reservations', exact=True).click()
    expect(dialog).to_contain_text('Select the evaluation switch authorization.')
    page.get_by_role('button', name='Approve corpus version', exact=True).click()
    expect(dialog).to_contain_text('Select the corpus authorization.')
    assert not w.browser_writes
    dialog.get_by_label('Trust resource reference').fill(str(w.rids[0]))
    page.get_by_role('button', name='Read trust preview', exact=True).click()
    expect(dialog.get_by_role('region', name='Trust evidence result')).to_contain_text('Evidence pending')
    assert 'SECRET_PROMPT' not in dialog.inner_text() and 'primary.example' not in dialog.inner_text()
    assert page.evaluate('typeof window.alertWasCalled') == 'undefined'
    assert not w.calls and not w.errors and not w.unexpected
    folder = Path('reports/advancement-phase2-core-2026-10-19/evaluation-routing'); folder.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(folder/'desktop-controls.png'), full_page=True)


def test_zero_dispatch_shadow_and_session_switch_clear_private_state(reliability_page):
    w = reliability_page; page = w.page; dialog = page.locator('#workspaceReliabilityControlsDialog')
    assert post(w, '/routing/configure', routing_policy(w, mode='decision_shadow')).status_code == 200
    page.get_by_role('button', name='Read current reliability controls', exact=True).click()
    expect(dialog).to_contain_text('Policy 1 · decision_shadow')
    consent = dialog.get_by_label('Record one recommendation with current evidence and authority. No provider will be invoked.')
    expect(consent).not_to_be_checked(); consent.check()
    page.get_by_role('button', name='Record routing decision', exact=True).click()
    expect(dialog).to_contain_text('decision_shadow · qualified_rule_choice')
    assert not w.calls
    page.evaluate("token='';currentUser=null;window.WorkspaceReliabilityControlsAdmin.onSession()")
    expect(dialog).to_have_count(0)
    assert not w.errors and not w.unexpected


def test_current_owner_activates_and_deactivates_configured_worker_with_separate_consent(reliability_page):
    import threading
    import httpx
    from agent_market.concierge.proxy import McpProxy
    from agent_market.reliability_control_service import router_for
    from agent_market.reliability_evaluation_worker import EvaluationWorker, McpReadEvaluator
    from tests.test_reliability_controls import setup_plan
    w = reliability_page
    unexpected = []
    def no_provider(request):
        unexpected.append(request.url.host)
        raise AssertionError('No evaluation is dispatched by this UI-only acceptance.')
    client = httpx.Client(transport=httpx.MockTransport(no_provider))
    w.runtime.proxy = McpProxy(w.store, allow_private=True, http=client)
    adapter = McpReadEvaluator(w.evaluation, enabled=True)
    w.evaluation.read_evaluator, w.evaluation.evaluator_authorizer = adapter, adapter.authorizer
    worker = EvaluationWorker(w.evaluation, enabled=True, poll_seconds=60)
    w.evaluation.worker = worker
    w.control_api.app.include_router(router_for(w.access, w.runtime, evaluation=w.evaluation,
                                                routing=w.routing, trust=w.trust))
    setup_plan(w)
    first_tick = threading.Event()
    original = worker.tick
    def tick():
        result = original()
        first_tick.set()
        return result
    worker.tick = tick
    try:
        assert worker.start() and first_tick.wait(2)
        page = w.page
        dialog = page.locator('#workspaceReliabilityControlsDialog')
        dialog.get_by_role('button', name='Read current reliability controls', exact=True).click()
        expect(dialog).to_contain_text('Configured worker: running. Workspace activation: inactive.')
        card = dialog.locator('section').filter(has=page.get_by_role('heading', name='Bounded evaluation worker', exact=True))
        card.get_by_role('button', name='Activate evaluation worker', exact=True).click()
        expect(dialog).to_contain_text('Select the exact worker activation authorization.')
        assert not any(path.endswith('/worker/activate') for path in w.browser_writes)
        card.get_by_label('Activate the current approved evaluation plan', exact=False).check()
        card.get_by_role('button', name='Activate evaluation worker', exact=True).click()
        expect(dialog).to_contain_text('Workspace activation: active.')
        assert dialog.locator('input[type="checkbox"]:checked').count() == 0
        card.get_by_label('Deactivate this workspace worker', exact=False).check()
        card.get_by_role('button', name='Deactivate evaluation worker', exact=True).click()
        expect(dialog).to_contain_text('Workspace activation: inactive.')
        assert sum(path.endswith('/worker/activate') for path in w.browser_writes) == 1
        assert sum(path.endswith('/worker/deactivate') for path in w.browser_writes) == 1
        assert not unexpected and not w.calls and not w.errors and not w.unexpected
    finally:
        assert worker.close()
        client.close()
