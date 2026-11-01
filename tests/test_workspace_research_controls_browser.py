"""Actual offline Chromium to isolated named-session plan/admission APIs."""
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from agent_market.reliability_admission import SingleAdmission
from agent_market.reliability_admission_service import router_for
from agent_market.reliability_routing import ReliabilityRouting
from agent_market.workflows import runtime_for
from tests.test_front_workflow_browser import browser
from tests.test_workspace_growth import growth
from tests.test_workspace_typed_flows import typed_world, routing
from tests.test_workspace_execution_api import private_api


@pytest.fixture
def controls_page(growth, browser):
    g = growth; w = g.w
    runtime = runtime_for(w.store, w.execution.proxy)
    core = SingleAdmission(w.access, ReliabilityRouting(w.access, runtime), w.execution)
    g.client.app.include_router(router_for(core))
    context = browser.new_context(viewport={'width': 1280, 'height': 900}, reduced_motion='reduce')
    context.set_offline(True); page = context.new_page(); g.page = page; g.errors = []; g.external = []; g.writes = []
    html = '''<!doctype html><html lang="en"><head><meta charset="utf-8"></head><body><select id="workspaceSelect"><option value="WORKSPACE">Workspace</option></select><script nonce="fixture">let token=TOKEN,currentUser={user_id:1,role:'superadmin'};async function api(path,options={}){const r=await fetch(path,{method:options.method||'GET',headers:{'X-Dashboard':'1',Authorization:'Bearer '+token,...(options.json?{'Content-Type':'application/json'}:{})},...(options.json?{body:JSON.stringify(options.json)}:{})});if(!r.ok)throw new Error('private_request');return r.json();}</script><script nonce="fixture" src="/admin/assets/workspace-research-controls-admin.js"></script></body></html>'''.replace('WORKSPACE', w.ws).replace('TOKEN', json.dumps(w.raw))
    script = Path('agent_market/gateway/workspace-research-controls-admin.js').read_text()
    def serve(route):
        request = route.request; url = urlsplit(request.url)
        if url.hostname != 'growth.test': g.external.append(url.hostname); route.abort(); return
        if url.path == '/component':
            route.fulfill(status=200, body=html, headers={'Content-Type': 'text/html', 'Content-Security-Policy': "default-src 'none';script-src 'nonce-fixture';style-src 'unsafe-inline';connect-src 'self';base-uri 'none'"}); return
        if url.path == '/admin/assets/workspace-research-controls-admin.js':
            route.fulfill(status=200, body=script, headers={'Content-Type': 'application/javascript'}); return
        if request.method != 'GET': g.writes.append(url.path)
        response = g.client.request(request.method, 'https://growth.test'+url.path, headers=request.headers, content=request.post_data)
        route.fulfill(status=response.status_code, body=response.content, headers={k:v for k,v in response.headers.items() if k not in ('content-length','content-encoding','transfer-encoding')})
    context.route('**/*', serve); page.on('pageerror', lambda error: g.errors.append(str(error)))
    page.goto('https://growth.test/component'); page.evaluate('(ws)=>WorkspaceResearchControlsAdmin.open(ws)', w.ws)
    expect(page.locator('#workspaceResearchControlsDialog')).to_contain_text('Current scoped state loaded.')
    try: yield g
    finally: context.close()


def test_named_desktop_plan_review_requires_fresh_consent_and_clear_on_edit(controls_page):
    g = controls_page; page = g.page; dialog = page.locator('#workspaceResearchControlsDialog')
    assert abs(dialog.bounding_box()['x']+dialog.bounding_box()['width']/2-640)<2
    for item in dialog.get_by_role('checkbox').all(): expect(item).not_to_be_checked()
    expect(dialog).to_contain_text('Single-provider execution is disabled')
    assert not g.writes and not g.w.calls
    page.locator('#researchPreparePlan').click()
    expect(dialog).to_contain_text('Review the exact graph, inputs and destinations.')
    expect(page.locator('#researchSavePlan')).to_be_disabled()
    page.locator('#researchPlanConsent').check()
    expect(page.locator('#researchSavePlan')).to_be_enabled()
    page.locator('#researchIntent').fill('Documentation about changed research then documentation about references')
    expect(page.locator('#researchSavePlan')).to_be_disabled()
    expect(page.locator('#researchPlanConsent')).not_to_be_checked()
    page.locator('#researchPreparePlan').click()
    expect(dialog).to_contain_text('Review the exact graph, inputs and destinations.')
    page.locator('#researchPlanConsent').check(); page.locator('#researchSavePlan').click()
    expect(dialog).to_contain_text('Saved new draft')
    assert sum(path.endswith('/commits') for path in g.writes)==1 and not g.w.calls
    assert not g.errors and not g.external


def test_unsupported_intent_and_session_switch_never_execute_or_keep_private_state(controls_page):
    g = controls_page; page = g.page
    page.locator('#researchIntent').fill('Build anything without details')
    page.locator('#researchPreparePlan').click()
    expect(page.locator('#workspaceResearchControlsDialog')).to_contain_text('Provide the missing intent details')
    expect(page.locator('#researchSavePlan')).to_be_disabled()
    page.evaluate("token='';currentUser=null;WorkspaceResearchControlsAdmin.onSession()")
    expect(page.locator('#workspaceResearchControlsDialog')).to_have_count(0)
    assert not g.w.calls and not g.errors and not g.external


def test_replan_preview_displays_exact_base_revision_and_changes_before_new_draft(controls_page):
    from copy import deepcopy
    from tests.test_workspace_typed_flows import save
    g = controls_page; page = g.page
    original = save(g.w); before = g.w.core.detail(g.w.ws, original['id'], g.w.actor)
    definition = deepcopy(before['definition'])
    definition['nodes'][1]['bindings'].pop('query', None)
    definition['nodes'][1]['input']['query'] = 'Reviewed changed input'
    page.locator('#researchDefinition').fill(json.dumps(definition))
    page.get_by_label('Existing flow to review as a new draft (optional)', exact=True).fill(original['id'])
    page.get_by_label('Existing flow revision (optional)', exact=True).fill(str(original['revision']))
    page.locator('#researchPreparePlan').click()
    dialog = page.locator('#workspaceResearchControlsDialog')
    expect(dialog).to_contain_text(f"Reviewed base flow {original['id']}; revision {original['revision']}; version {original['version_id']}.")
    expect(dialog.get_by_label('Reviewed plan changes')).to_contain_text('followup: input.')
    expect(dialog.get_by_label('Reviewed plan changes')).to_contain_text('followup: bindings.')
    expect(page.locator('#researchSavePlan')).to_be_disabled()
    page.locator('#researchPlanConsent').check(); page.locator('#researchSavePlan').click()
    expect(dialog).to_contain_text('Saved new draft')
    assert g.w.core.detail(g.w.ws, original['id'], g.w.actor) == before
    assert len(g.w.store.query('SELECT id FROM workspace_typed_flows')) == 2
    assert not g.w.calls and not g.errors and not g.external


from tests.test_reliability_admission import pilot, body
from tests.test_reliability_controls import controls


@pytest.fixture
def retained_controls_page(pilot, browser):
    w = pilot
    prepared = w.admission.prepare(w.ws['id'], body(w), w.actor)
    context = browser.new_context(viewport={'width': 1280, 'height': 900}, reduced_motion='reduce')
    context.set_offline(True); page = context.new_page(); w.page = page
    w.browser_writes, w.browser_reads, w.errors, w.external = [], [], [], []
    raw = w.headers['owner']['Authorization'][7:]
    html = '''<!doctype html><html lang="en"><head><meta charset="utf-8"></head><body><select id="workspaceSelect"><option value="WORKSPACE">Workspace</option></select><script nonce="fixture">let token=TOKEN,currentUser={user_id:1,role:'superadmin'};Date.now=()=>NOW;async function api(path,options={}){const r=await fetch(path,{method:options.method||'GET',headers:{'X-Dashboard':'1',Authorization:'Bearer '+token,...(options.json?{'Content-Type':'application/json'}:{})},...(options.json?{body:JSON.stringify(options.json)}:{})});if(!r.ok)throw new Error('private_request');return r.json();}</script><script nonce="fixture" src="/admin/assets/workspace-research-controls-admin.js"></script></body></html>'''.replace('WORKSPACE', w.ws['id']).replace('TOKEN', json.dumps(raw)).replace('NOW', str(w.now*1000))
    script = Path('agent_market/gateway/workspace-research-controls-admin.js').read_text()
    def serve(route):
        request = route.request; url = urlsplit(request.url)
        if url.hostname != 'pilot.test': w.external.append(url.hostname); route.abort(); return
        if url.path == '/component':
            route.fulfill(status=200, body=html, headers={'Content-Type': 'text/html', 'Content-Security-Policy': "default-src 'none';script-src 'nonce-fixture';style-src 'unsafe-inline';connect-src 'self';base-uri 'none'"}); return
        if url.path == '/admin/assets/workspace-research-controls-admin.js':
            route.fulfill(status=200, body=script, headers={'Content-Type': 'application/javascript'}); return
        (w.browser_reads if request.method == 'GET' else w.browser_writes).append(url.path)
        response = w.pilot_client.request(request.method, url.path+('?'+url.query if url.query else ''), headers=request.headers, content=request.post_data)
        route.fulfill(status=response.status_code, body=response.content, headers={k:v for k,v in response.headers.items() if k not in ('content-length','content-encoding','transfer-encoding')})
    context.route('**/*', serve); page.on('pageerror', lambda error: w.errors.append(str(error)))
    page.goto('https://pilot.test/component'); page.evaluate('(ws)=>WorkspaceResearchControlsAdmin.open(ws)', w.ws['id'])
    expect(page.locator('#workspaceResearchControlsDialog')).to_contain_text('Current scoped state loaded.')
    w.prepared = prepared
    try: yield w
    finally: context.close()


def test_retained_prepared_admission_preview_requires_fresh_consent_after_read_and_reopen(retained_controls_page):
    w = retained_controls_page; page = w.page; prepared = w.prepared
    review = lambda: page.get_by_role('button', name='Review prepared admission '+prepared['id'], exact=True)
    before = {table: w.store.query(f'SELECT COUNT(*) FROM {table}')[0][0] for table in ('reliability_admissions', 'workspace_private_tickets', 'workspace_versions')}
    review().click()
    expect(page.locator('#pilotExactPreview')).to_contain_text(prepared['id'])
    expect(page.locator('#pilotExactPreview')).to_contain_text('Public docs')
    expect(page.locator('#pilotRunOnce')).to_be_disabled()
    page.locator('#pilotRunConsent').check(); expect(page.locator('#pilotRunOnce')).to_be_enabled()
    page.get_by_role('button', name='Read current state', exact=True).click()
    expect(page.locator('#pilotRunConsent')).not_to_be_checked(); expect(page.locator('#pilotRunOnce')).to_be_disabled()
    review().click(); page.locator('#pilotRunConsent').check()
    page.locator('#pilotInput').fill('{"query":"Changed input","language":"en","limit":2}')
    expect(page.locator('#pilotRunConsent')).not_to_be_checked(); expect(page.locator('#pilotRunOnce')).to_be_disabled()
    expect(page.locator('#pilotExactPreview')).to_have_text('')
    page.get_by_role('button', name='Close research controls', exact=True).click()
    page.evaluate('(ws)=>WorkspaceResearchControlsAdmin.open(ws)', w.ws['id'])
    review().click(); expect(page.locator('#pilotRunOnce')).to_be_disabled()
    assert w.browser_reads.count(w.pilot_base+'/'+prepared['id']+'/review') == 3
    assert before == {table: w.store.query(f'SELECT COUNT(*) FROM {table}')[0][0] for table in before}
    assert not w.browser_writes and not w.calls and not w.errors and not w.external


def test_retained_review_executes_once_only_with_new_explicit_confirmation(retained_controls_page):
    from tests.test_workflow_fallback import output
    w = retained_controls_page; page = w.page
    w.remote.tools = json.loads(w.store.resource(w.rids[0])['usage_full_tools']); w.remote.call_result = output()
    page.get_by_role('button', name='Review prepared admission '+w.prepared['id'], exact=True).click()
    expect(page.locator('#pilotRunOnce')).to_be_disabled()
    page.locator('#pilotRunConsent').check(); page.locator('#pilotRunOnce').click()
    expect(page.locator('#workspaceResearchControlsDialog')).to_contain_text('Execution succeeded. Replacement calls: 0.')
    assert w.calls.count('tools/call') == 1
    page.get_by_role('button', name='Read current state', exact=True).click()
    expect(page.get_by_role('button', name='Review prepared admission '+w.prepared['id'], exact=True)).to_have_count(0)
    expect(page.locator('#pilotRunOnce')).to_be_disabled()
    assert len(w.browser_writes) == 1 and w.browser_writes[0].endswith('/execute')
    assert not w.errors and not w.external


def test_unknown_retained_admission_has_no_replay_action_and_session_change_clears_preview(retained_controls_page):
    w = retained_controls_page; page = w.page
    page.get_by_role('button', name='Review prepared admission '+w.prepared['id'], exact=True).click()
    w.remote.tools = json.loads(w.store.resource(w.rids[0])['usage_full_tools']); w.control['mode'] = 'timeout'
    page.locator('#pilotRunConsent').check(); page.locator('#pilotRunOnce').click()
    expect(page.locator('#workspaceResearchControlsDialog')).to_contain_text('Execution unknown. Replacement calls: 0.')
    page.get_by_role('button', name='Read current state', exact=True).click()
    expect(page.get_by_role('button', name='Review prepared admission '+w.prepared['id'], exact=True)).to_have_count(0)
    expect(page.locator('#pilotRunOnce')).to_be_disabled()
    assert w.calls.count('tools/call') == 1 and len(w.browser_writes) == 1
    page.evaluate("token='';currentUser=null;WorkspaceResearchControlsAdmin.onSession()")
    expect(page.locator('#workspaceResearchControlsDialog')).to_have_count(0)
    assert not w.errors and not w.external


def test_late_retained_review_cannot_restore_consent_after_an_input_edit(retained_controls_page):
    w = retained_controls_page; page = w.page; held = []
    page.route('**/reliability/admission/*/review', lambda route: held.append(route))
    page.get_by_role('button', name='Review prepared admission '+w.prepared['id'], exact=True).click()
    page.locator('#pilotInput').fill('{"query":"Different input","language":"en","limit":2}')
    assert len(held) == 1
    route = held.pop(); response = w.pilot_client.get(urlsplit(route.request.url).path, headers=w.headers['owner'])
    assert response.status_code == 200
    route.fulfill(status=200, body=response.content, headers={'Content-Type': 'application/json'})
    expect(page.locator('#pilotExactPreview')).to_have_text('')
    expect(page.locator('#pilotRunConsent')).not_to_be_checked()
    expect(page.locator('#pilotRunOnce')).to_be_disabled()
    assert not w.browser_writes and not w.calls and not w.errors and not w.external


def _mount_private_evidence_controls(w, *, enabled=False):
    from copy import deepcopy
    from agent_market.reliability_control_service import router_for as controls_router
    from agent_market.reliability_circuit import ReliabilityCircuit
    from agent_market.workspace_reliability import ReliabilityEvidence
    plane = ReliabilityEvidence(w.access, w.execution)
    circuit = ReliabilityCircuit(w.access, w.evaluation, enabled=enabled,
        evidence_guard=lambda db, ws, rid, actor: deepcopy(w.sources[rid]))
    w.pilot_client.app.include_router(controls_router(w.access, w.runtime,
        evaluation=w.evaluation, routing=w.routing, trust=w.trust, evidence=plane, circuit=circuit))
    return plane, circuit


def test_evidence_circuit_cards_only_read_explicit_resources_and_enforce_server_off(retained_controls_page):
    w = retained_controls_page; page = w.page
    plane, circuit = _mount_private_evidence_controls(w)
    assert w.browser_reads == [w.pilot_base+'/status']
    page.locator('#researchEvidenceResource').fill(str(w.rids[0]))
    assert len(w.browser_reads) == 1
    expect(page.locator('#researchCircuitPolicy')).to_have_value('')
    page.get_by_role('button', name='Read operating evidence status', exact=True).click()
    expect(page.locator('#researchOperatingStatus')).to_contain_text('no independent operating qualifier is configured')
    expect(page.get_by_role('button', name='Qualify current operating evidence', exact=True)).to_be_disabled()
    expect(page.locator('#researchOperatingConsent')).to_be_disabled()
    page.get_by_role('button', name='Read circuit state', exact=True).click()
    expect(page.locator('#researchCircuitStatus')).to_contain_text('disabled in server configuration')
    expect(page.locator('#researchCircuitConsent')).to_be_disabled()
    for name in ('Save explicit circuit policy', 'Ingest one retained observation', 'Bind separately approved probe', 'Read completed bound probe'):
        expect(page.get_by_role('button', name=name, exact=True)).to_be_disabled()
    page.locator('#researchEvidenceResource').fill(str(w.rids[1]))
    expect(page.locator('#researchOperatingStatus')).to_have_text('Operating evidence has not been read.')
    expect(page.locator('#researchCircuitStatus')).to_have_text('Circuit state has not been read.')
    assert len(w.browser_reads) == 3 and not w.browser_writes and not w.calls and not w.errors and not w.external


def test_explicit_circuit_policy_requires_current_read_and_fresh_command_consent(retained_controls_page):
    from tests.test_reliability_circuit import config
    w = retained_controls_page; page = w.page
    plane, circuit = _mount_private_evidence_controls(w, enabled=True)
    page.locator('#researchEvidenceResource').fill(str(w.rids[0]))
    expect(page.locator('#researchCircuitPolicy')).to_have_value('')
    page.get_by_role('button', name='Read circuit state', exact=True).click()
    expect(page.locator('#researchCircuitStatus')).to_contain_text('revision 0; no circuit policy')
    consent = page.locator('#researchCircuitConsent'); save = page.get_by_role('button', name='Save explicit circuit policy', exact=True)
    expect(consent).not_to_be_checked(); expect(save).to_be_disabled()
    policy = config(w); policy.pop('authorized'); policy.pop('notice')
    page.locator('#researchCircuitPolicy').fill(json.dumps(policy)); consent.check(); expect(save).to_be_enabled()
    page.get_by_label('Retained circuit observation source reference', exact=True).fill('Changed reviewed input')
    expect(consent).not_to_be_checked(); expect(save).to_be_disabled()
    consent.check(); save.click()
    expect(page.locator('#workspaceResearchControlsDialog')).to_contain_text('Circuit command recorded.')
    expect(consent).not_to_be_checked(); expect(save).to_be_disabled()
    state = circuit.status(w.ws['id'], w.rids[0], w.actor)
    assert state['circuit']['revision'] == 1 and state['circuit']['state'] == 'closed'
    assert state['provider_calls'] == 0
    page.get_by_role('button', name='Read circuit state', exact=True).click()
    expect(page.locator('#researchCircuitStatus')).to_contain_text('revision 1; state closed')
    expect(consent).not_to_be_checked(); expect(save).to_be_disabled()
    assert len(w.browser_writes) == 1 and w.browser_writes[0].endswith('/circuits/'+str(w.rids[0])+'/configure')
    assert not w.calls and not w.errors and not w.external


def test_optional_model_proposal_is_explicit_default_off_and_does_not_replace_bounded_intent(controls_page):
    g=controls_page;page=g.page;dialog=page.locator('#workspaceResearchControlsDialog')
    expect(page.locator('#researchModelConsent')).to_be_disabled()
    expect(page.locator('#researchModelProposal')).to_be_disabled()
    assert not g.writes
    page.locator('#researchReadModel').click()
    expect(dialog).to_contain_text('Optional model proposals are unavailable.')
    expect(page.locator('#researchModelConsent')).to_be_disabled()
    assert not g.writes and not g.w.calls and not g.errors and not g.external


def test_configured_model_proposal_shares_public_objective_once_then_requires_fresh_exact_graph_review(controls_page):
    from copy import deepcopy
    g=controls_page;page=g.page;dialog=page.locator('#workspaceResearchControlsDialog');seen=[]
    def proposer(envelope):
        assert not g.w.store._db.in_transaction
        seen.append(deepcopy(envelope))
        candidates=[item for item in envelope['candidates'] if item['contract_id']=='docs.search.v1']
        return {'nodes':[dict(item,input={'query':'Public documentation','language':'en','limit':2}) for item in candidates[:2]]}
    g.factory.model_proposer=proposer
    page.locator('#researchReadModel').click()
    expect(dialog).to_contain_text('Optional advisory proposals are available.')
    expect(page.locator('#researchModelConsent')).not_to_be_checked()
    expect(page.locator('#researchModelProposal')).to_be_disabled()
    page.locator('#researchModelConsent').check();page.locator('#researchModelProposal').click()
    expect(dialog).to_contain_text('Review the exact graph, inputs and destinations.')
    expect(page.locator('#researchModelConsent')).not_to_be_checked()
    expect(page.locator('#researchPlanConsent')).not_to_be_checked()
    expect(page.locator('#researchSavePlan')).to_be_disabled()
    assert len(seen)==1 and sum(path.endswith('/model-proposals') for path in g.writes)==1
    assert g.w.ws not in json.dumps(seen) and g.w.raw not in json.dumps(seen)
    assert not g.w.calls and not g.w.store.query('SELECT id FROM workspace_typed_flows')
    page.locator('#researchPlanConsent').check();page.locator('#researchSavePlan').click()
    expect(dialog).to_contain_text('Saved new draft')
    assert len(g.w.store.query('SELECT id FROM workspace_typed_flows'))==1
    assert not g.w.calls and not g.errors and not g.external


def test_model_proposal_refuses_to_share_existing_graph_or_stale_public_objective_consent(controls_page):
    g=controls_page;page=g.page;seen=[]
    g.factory.model_proposer=lambda envelope:seen.append(envelope) or {'nodes':[]}
    page.locator('#researchReadModel').click()
    expect(page.locator('#researchModelConsent')).to_be_enabled()
    page.locator('#researchModelConsent').check()
    page.locator('#researchIntent').fill('Changed public documentation objective')
    expect(page.locator('#researchModelConsent')).not_to_be_checked()
    expect(page.locator('#researchModelProposal')).to_be_disabled()
    page.locator('#researchDefinition').fill('{"private":"never share this original graph"}')
    page.locator('#researchModelConsent').check();page.locator('#researchModelProposal').click()
    expect(page.locator('#workspaceResearchControlsDialog')).to_contain_text('Clear the private graph and base references')
    assert seen==[] and not g.writes and not g.w.calls and not g.errors and not g.external
