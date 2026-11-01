"""Offline Chromium verifies purpose consent and safe private research rendering."""
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from tests.test_front_workflow_browser import browser
from tests.test_reliability_research import research_world, controls, private_api, item, item_goal_hash


@pytest.fixture
def research_page(research_world, browser):
    w = research_world
    context = browser.new_context(viewport={'width': 1280, 'height': 900}, reduced_motion='reduce')
    context.set_offline(True); page = context.new_page(); w.page = page
    w.errors, w.unexpected, w.browser_writes = [], [], []
    script = Path('agent_market/gateway/workspace-reliability-research-admin.js').read_text()
    html = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><style nonce="fixture">body{font-family:system-ui;background:#f3f6fa;color:#172235}dialog::backdrop{background:#14213988}.card{border:1px solid #dce3ee}button,input{font:inherit;padding:9px;border:1px solid #cbd5e3;border-radius:8px}label{display:block;margin:10px 0}button:focus-visible,input:focus-visible{outline:3px solid #527bf5;outline-offset:3px}</style></head><body><select id="workspaceSelect"><option value="WORKSPACE">Selected workspace</option></select><script nonce="fixture">let token=TOKEN,currentUser={user_id:1,role:'superadmin'};Date.now=()=>NOW;async function api(path,options={}){const r=await fetch(path,{method:options.method||'GET',headers:{'X-Dashboard':'1',Authorization:'Bearer '+token,...(options.json?{'Content-Type':'application/json'}:{})},...(options.json?{body:JSON.stringify(options.json)}:{})});if(!r.ok)throw Object.assign(new Error('private_request'),{status:r.status});return r.json()}</script><script nonce="fixture" src="/admin/assets/workspace-reliability-research-admin.js"></script></body></html>'''.replace('WORKSPACE', w.ws['id']).replace('TOKEN', json.dumps(w.headers['owner']['Authorization'][7:])).replace('NOW', str(w.now*1000))
    def serve(route):
        request = route.request; url = urlsplit(request.url)
        if url.hostname != 'private.test':
            w.unexpected.append(url.hostname); route.abort(); return
        if url.path == '/admin/research-component':
            route.fulfill(status=200, body=html, headers={'Content-Type': 'text/html', 'Content-Security-Policy': "default-src 'none';script-src 'nonce-fixture';style-src 'nonce-fixture';connect-src 'self';base-uri 'none';frame-ancestors 'none'"}); return
        if url.path == '/admin/assets/workspace-reliability-research-admin.js':
            route.fulfill(status=200, body=script, headers={'Content-Type': 'application/javascript'}); return
        if request.method != 'GET': w.browser_writes.append(url.path)
        result = w.control_api.request(request.method, url.path, headers=request.headers, content=request.post_data)
        route.fulfill(status=result.status_code, body=result.content, headers={key: value for key, value in result.headers.items() if key not in ('content-length', 'content-encoding', 'transfer-encoding')})
    context.route('**/*', serve); page.on('pageerror', lambda error: w.errors.append(str(error)))
    page.goto('https://private.test/admin/research-component')
    page.evaluate('(ws)=>window.WorkspaceReliabilityResearchAdmin.open(ws)', w.ws['id'])
    expect(page.locator('#workspaceReliabilityResearchDialog')).to_contain_text('Current research state loaded.')
    try:
        yield w
    finally:
        context.close()


def test_research_dialog_center_accessibility_and_unchecked_purpose_consent(research_page):
    w = research_page; page = w.page; dialog = page.locator('#workspaceReliabilityResearchDialog')
    box = dialog.bounding_box(); assert abs(box['x']+box['width']/2-640) < 2
    assert dialog.get_attribute('aria-labelledby') == 'workspaceReliabilityResearchTitle'
    for checkbox in dialog.get_by_role('checkbox').all(): expect(checkbox).not_to_be_checked()
    dialog.get_by_role('button', name='Approve paired research manifest', exact=True).click()
    expect(dialog).to_contain_text('Select the paired corpus and semantic review authorization.')
    dialog.get_by_role('button', name='Save research evaluation plan', exact=True).click()
    expect(dialog).to_contain_text('Approve a paired corpus and select its exact evaluation plan authorization.')
    assert not w.browser_writes and not w.calls and not w.errors and not w.unexpected


def test_approved_manifest_and_plan_do_not_activate_or_dispatch(research_page):
    w = research_page; dialog = w.page.locator('#workspaceReliabilityResearchDialog')
    dialog.get_by_label('Approved normalized item SHA-256', exact=True).fill(item_goal_hash('docs.search.v1', item(w)))
    dialog.get_by_label('I approve this synthetic or licensed corpus', exact=False).check()
    dialog.get_by_role('button', name='Approve paired research manifest', exact=True).click()
    expect(dialog).to_contain_text('Immutable research corpus approved.')
    expect(dialog).to_contain_text('4 planned episodes')
    for checkbox in dialog.get_by_role('checkbox').all(): expect(checkbox).not_to_be_checked()
    dialog.get_by_label('Evaluation resource reference', exact=True).fill(str(w.rids[0]))
    dialog.get_by_label('Authorize this research corpus and resource', exact=False).check()
    dialog.get_by_role('button', name='Save research evaluation plan', exact=True).click()
    expect(dialog).to_contain_text('Evaluation control and worker activation remain separate.')
    state = w.evaluation.status(w.ws['id'], w.actor)
    assert state['plan'] and state['control']['enabled'] is False and not state['jobs']
    assert not w.calls and not w.errors and not w.unexpected
    assert len(w.browser_writes) == 2
    folder = Path('reports/advancement-rnd-source-2026-10-19/research'); folder.mkdir(parents=True, exist_ok=True)
    w.page.screenshot(path=str(folder/'research-desktop.png'), full_page=True)


def test_workspace_or_session_change_discards_private_dialog_state(research_page):
    w = research_page; dialog = w.page.locator('#workspaceReliabilityResearchDialog')
    w.page.evaluate("token='';currentUser=null;window.WorkspaceReliabilityResearchAdmin.onSession()")
    expect(dialog).to_have_count(0)
    assert not w.errors and not w.unexpected and not w.browser_writes and not w.calls


def test_retained_approved_manifest_can_be_selected_after_reopening_without_duplication(research_page):
    from tests.test_reliability_research import manifest
    w = research_page; page = w.page
    approved = w.research.register_manifest(w.ws['id'], manifest(w), w.actor)
    page.get_by_role('button', name='Close research', exact=True).click()
    page.evaluate('(ws)=>WorkspaceReliabilityResearchAdmin.open(ws)', w.ws['id'])
    dialog = page.locator('#workspaceReliabilityResearchDialog')
    expect(dialog).to_contain_text('Current research state loaded.')
    expect(page.locator('#researchManifestSelect')).to_have_value('')
    selected = json.dumps([approved[key] for key in ('id', 'corpus_id', 'corpus_hash', 'revision')], separators=(',', ':'))
    page.locator('#researchManifestSelect').select_option(selected)
    expect(page.locator('#researchManifestSelection')).to_contain_text(approved['corpus_hash'])
    expect(page.locator('#researchManifestSelection')).to_contain_text('revision 1')
    dialog.get_by_label('Evaluation resource reference', exact=True).fill(str(w.rids[0]))
    dialog.get_by_label('Authorize this research corpus and resource', exact=False).check()
    dialog.get_by_role('button', name='Save research evaluation plan', exact=True).click()
    expect(dialog).to_contain_text('Evaluation control and worker activation remain separate.')
    assert w.evaluation.status(w.ws['id'], w.actor)['plan']['corpus_id'] == approved['corpus_id']
    assert len(w.research.status(w.ws['id'], w.actor)['manifests']) == 1
    assert w.browser_writes == [w.base+'/evaluation/plans']
    assert not w.calls and not w.errors and not w.unexpected


def test_manifest_selection_changes_expiry_and_withdrawal_require_fresh_authorization(research_page):
    from tests.test_reliability_research import manifest, NOTICE
    w = research_page; page = w.page
    first = w.research.register_manifest(w.ws['id'], manifest(w), w.actor)
    second = w.research.register_manifest(w.ws['id'], manifest(w, manifest_id='rrm_'+'9'*32), w.actor)
    page.get_by_role('button', name='Read current research', exact=True).click()
    select = page.locator('#researchManifestSelect')
    key = lambda value: json.dumps([value[k] for k in ('id', 'corpus_id', 'corpus_hash', 'revision')], separators=(',', ':'))
    select.select_option(key(first))
    approved = page.get_by_label('Authorize this research corpus and resource', exact=False)
    approved.check(); select.select_option(key(second)); expect(approved).not_to_be_checked()
    w.research.withdraw(w.ws['id'], second['id'], {'revision': 1, 'authorized': True, 'notice': NOTICE}, w.actor)
    page.get_by_role('button', name='Read current research', exact=True).click()
    expect(select).to_have_value('')
    withdrawn = select.locator('option').filter(has_text=second['id'])
    expect(withdrawn).to_have_text(second['id']+' · revision 2 · withdrawn')
    assert withdrawn.evaluate('(node)=>node.disabled')
    w.now = first['expires']
    page.evaluate('(now)=>{Date.now=()=>now}', w.now*1000)
    page.get_by_role('button', name='Read current research', exact=True).click()
    expired = select.locator('option').filter(has_text=first['id'])
    expect(expired).to_contain_text('expired'); assert expired.evaluate('(node)=>node.disabled')
    assert not w.browser_writes and not w.calls and not w.errors and not w.unexpected
