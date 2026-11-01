"""Offline Chromium checks for private app-factory, SDK and support consent UI.

Every request is fulfilled by fixed synthetic interception. No project server,
real session, store, provider or external destination is used.
"""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from tests.test_front_workflow_browser import browser

WS = 'ws_' + '1'*32
OTHER_WS = 'ws_' + '2'*32
HOSTILE = '<img src=x onerror=globalThis.__hostile=1>'


@pytest.fixture
def growth_page(browser):
    context = browser.new_context(viewport={'width': 1440, 'height': 1000}); context.set_offline(True)
    page = context.new_page(); now = time.time(); page.clock.install(time=datetime.fromtimestamp(now, timezone.utc))
    state = SimpleNamespace(page=page, requests=[], errors=[], unexpected=[], alerts=[], pending=[], hold_reviews=False,
                            lose_commit_ack=False, review_count=0, commits=[], sdk_writes=[], support_writes=[], withdrawals=[], now=now)
    options = {'profile': 'workspace-contract-app-factory-v1', 'templates': [
        {'id': 'documentation_crosscheck', 'name': 'Documentation Cross-check'},
        {'id': 'research_digest', 'name': 'News and Documentation Brief'},
        {'id': 'product_brief', 'name': 'Product Evidence and Documentation'}],
        'can_edit': True, 'can_manage_sdk': True, 'notice': 'workspace-factory-save-v1',
        'sdk_notice': 'workspace-sdk-lifecycle-v1', 'provider_calls': 0, 'automatic_execution': False, 'public_activation': False}
    sdk = {'policies': [
        {'sdk_profile': 'workspace-sdk-v2', 'minimum_sdk_version': '2.0.0', 'revision': 0, 'accepting_runs': True,
         'current_owner': True, 'restored_block': False, 'sunset_at': None},
        {'sdk_profile': 'workspace-typed-sdk-v2', 'minimum_sdk_version': '2.1.0', 'revision': 0, 'accepting_runs': True,
         'current_owner': True, 'restored_block': False, 'sunset_at': None}],
        'releases': [{'id': 'wrl_'+HOSTILE, 'sdk_profile': 'workspace-sdk-v2', 'sdk_version': '2.0.0',
            'blocked_by_sdk_policy': False, 'deployments': [{'app_id': 'wap_'+HOSTILE, 'active': True,
                'expires': now+1800, 'allowed_origins': ['https://synthetic.example/'+HOSTILE]}]}]}
    support = {'cases': [{'case_id': 'wso_'+HOSTILE, 'revision': 1, 'category': HOSTILE, 'resolution': 'open',
        'state': 'retained', 'execution_status': 'succeeded', 'source_kind': 'typed', 'run_id': 'wtr_'+HOSTILE,
        'subject_id': 'wtf_'+HOSTILE, 'version_id': 'wtv_'+HOSTILE}], 'logical_run_samples': 1,
        'observed_subject_repeat_after_28_days': 0, 'can_edit': True, 'can_withdraw': True,
        'categories': ['setup','contract','execution','recovery'], 'notice': 'workspace-support-outcome-record-v1',
        'withdrawal_notice': 'workspace-support-outcome-withdraw-v1'}
    html = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><style nonce="fixture">body{font-family:system-ui;background:#f3f6fa;color:#172235}.row{display:flex;gap:12px;align-items:center;flex-wrap:wrap}dialog::backdrop{background:#14213988}.card{border:1px solid #dce3ee;border-radius:12px}button,input,select{font:inherit;padding:9px;border:1px solid #cbd5e3;border-radius:8px}button{cursor:pointer}button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #527bf5;outline-offset:3px}pre{white-space:pre-wrap}</style></head><body><select id="workspaceSelect"><option value="WORKSPACE">Synthetic workspace</option><option value="OTHER">Other synthetic workspace</option></select><script nonce="fixture">let token='a'.repeat(64),currentUser={user_id:1,role:'superadmin'};window.__apiSettled=0;window.__hostile=0;async function api(path,options={}){try{const r=await fetch(path,{method:options.method||'GET',headers:{'X-Dashboard':'1',Authorization:'Bearer '+token,...(options.json?{'Content-Type':'application/json'}:{})},...(options.json?{body:JSON.stringify(options.json)}:{})});if(!r.ok)throw Object.assign(new Error('synthetic_private_request'),{status:r.status});return await r.json()}finally{window.__apiSettled++}}</script><script nonce="fixture" src="/admin/assets/workspace-growth-admin.js"></script></body></html>'''.replace('WORKSPACE', WS).replace('OTHER', OTHER_WS)
    def fulfill(route, result): route.fulfill(status=200, json={'ok': True, 'result': result}, headers={'Cache-Control':'no-store'})
    def serve(route):
        request = route.request; url = urlsplit(request.url)
        if url.hostname != 'growth.test': state.unexpected.append(request.url); route.abort(); return
        if url.path == '/admin/growth-component':
            route.fulfill(status=200, body=html, headers={'Content-Type': 'text/html', 'Content-Security-Policy': "default-src 'none';script-src 'nonce-fixture';style-src 'nonce-fixture';connect-src 'self';base-uri 'none';frame-ancestors 'none'"}); return
        if url.path == '/admin/assets/workspace-growth-admin.js':
            route.fulfill(status=200, body=Path('agent_market/gateway/workspace-growth-admin.js').read_text(), headers={'Content-Type':'application/javascript'}); return
        body = json.loads(request.post_data) if request.post_data else None
        state.requests.append({'method': request.method, 'path': url.path, 'body': body})
        if request.method == 'GET' and url.path.endswith('/app-factory/options'): fulfill(route, options); return
        if request.method == 'GET' and url.path.endswith('/sdk-lifecycle'): fulfill(route, sdk); return
        if request.method == 'GET' and url.path.endswith('/support-outcomes'): fulfill(route, support); return
        if request.method == 'POST' and url.path.endswith('/app-factory/reviews'):
            state.review_count += 1
            result = {'profile': 'workspace-contract-app-factory-v1', 'review_id': 'wfr_'+format(state.review_count, '032x'),
                'name': body['name'], 'template_id': body['template_id'], 'expires': state.now+300,
                'definition': {'nodes': [{'id':'first','resource_id':101,'contract_id':'docs.search.v1','input':{'query':body['purpose']}},
                    {'id':'second','resource_id':102,'contract_id':'docs.search.v1','input':{'query':HOSTILE}}]},
                'destinations': [{'node_id':'first','resource_id':101,'contract_id':'docs.search.v1','tool':'search_docs'},
                    {'node_id':'second','resource_id':102,'contract_id':'docs.search.v1','tool':'search_docs '+HOSTILE}],
                'provider_calls':0, 'notice':options['notice'], 'requires_separate_execution_consent':True}
            state.latest_review = copy.deepcopy(result)
            if state.hold_reviews: state.pending.append((route,result)); return
            fulfill(route,result); return
        if request.method == 'POST' and url.path.endswith('/app-factory/commits'):
            state.commits.append(body)
            if state.lose_commit_ack: route.abort('failed'); return
            fulfill(route, {'id':'wtf_'+'3'*32,'version_id':'wtv_'+'4'*32,'revision':1,'provider_calls':0}); return
        if request.method == 'POST' and url.path.endswith('/sdk-lifecycle'):
            state.sdk_writes.append(body)
            for policy in sdk['policies']:
                if policy['sdk_profile'] == body['sdk_profile']:
                    policy['revision'] += 1; policy['accepting_runs'] = body['accepting_runs']
                    policy['sunset_at'] = state.now+body['sunset_seconds']
            fulfill(route, {'revision':body['revision']+1}); return
        if request.method == 'POST' and url.path.endswith('/support-outcomes/records'):
            state.support_writes.append(body); fulfill(route, {'case_id':'wso_'+'5'*32,'revision':1,'business_outcome':'unassessed'}); return
        if request.method == 'POST' and url.path.endswith('/support-outcomes/withdrawals'):
            state.withdrawals.append(body); support['cases'][0]['state'] = 'withdrawn'; fulfill(route, {'withdrawn':True}); return
        state.unexpected.append(request.url); route.abort()
    context.route('**/*', serve)
    page.on('pageerror', lambda error: state.errors.append(str(error)))
    page.on('dialog', lambda dialog: (state.alerts.append(dialog.message), dialog.dismiss()))
    page.goto('https://growth.test/admin/growth-component')
    page.evaluate('(ws)=>window.WorkspaceGrowthAdmin.open(ws)', WS)
    expect(page.get_by_role('status')).to_contain_text('Current private state loaded.')
    def release():
        route, result = state.pending.pop(0); before = page.evaluate('window.__apiSettled')
        fulfill(route,result)
        page.wait_for_function('(before)=>window.__apiSettled>before', arg=before)
    state.release = release
    try: yield state
    finally:
        for route, _ in state.pending:
            try: route.abort()
            except Exception: pass
        context.close()
        assert not state.errors and not state.unexpected and not state.alerts


def prepare(s):
    s.page.locator('#factoryPurpose').fill('Current reference documentation')
    s.page.locator('#factoryName').fill('Synthetic private graph')
    s.page.locator('#factoryPrepare').click()
    expect(s.page.get_by_role('status')).to_contain_text('Review ready.')
    expect(s.page.locator('#factorySaveConsent')).not_to_be_checked()
    expect(s.page.locator('#factorySave')).to_be_disabled()


def test_native_desktop_review_is_centered_exact_fresh_and_saved_only_with_explicit_consent(growth_page):
    s = growth_page; page = s.page; dialog = page.locator('#workspaceGrowthDialog')
    box = dialog.bounding_box(); assert abs(box['x']+box['width']/2-720)<2 and abs(box['y']+box['height']/2-500)<2
    assert dialog.get_attribute('aria-labelledby') == 'workspaceGrowthTitle'
    assert page.evaluate("document.querySelector('#workspaceGrowthDialog') instanceof HTMLDialogElement")
    prepare(s)
    submitted = next(r['body'] for r in s.requests if r['path'].endswith('/reviews'))
    assert submitted == {'template_id':'auto','purpose':'Current reference documentation','name':'Synthetic private graph',
                         'resource_ids':None,'from_utc':None,'criteria':[]}
    preview = page.locator('#factoryReview')
    expect(preview).to_contain_text('resource 101, docs.search.v1, tool search_docs')
    expect(preview).to_contain_text('resource 102, docs.search.v1, tool search_docs')
    assert json.loads(preview.locator('pre').inner_text()) == s.latest_review['definition']
    expect(preview).to_contain_text(HOSTILE); assert dialog.locator('img').count() == 0 and page.evaluate('window.__hostile') == 0
    page.locator('#factorySave').dispatch_event('click'); assert not s.commits
    page.locator('#factorySaveConsent').check(); expect(page.locator('#factorySave')).to_be_enabled()
    page.locator('#factorySave').click(); expect(page.get_by_role('status')).to_contain_text('Saved private workflow')
    assert s.commits == [{'review_id':s.latest_review['review_id'],'authorized':True,'notice':'workspace-factory-save-v1'}]
    expect(page.locator('#factorySaveConsent')).not_to_be_checked(); expect(page.locator('#factorySave')).to_be_disabled()
    page.locator('#factorySave').dispatch_event('click'); assert len(s.commits) == 1
    folder = Path('reports/advancement-phase2-core-2026-10-19/growth'); folder.mkdir(parents=True,exist_ok=True)
    dialog.evaluate('(element)=>element.scrollTop=0')
    page.screenshot(path=str(folder/'desktop-factory-review.png'), full_page=True)


def test_every_factory_input_edit_discards_exact_review_and_approval(growth_page):
    s = growth_page; page = s.page
    edits = [('factoryTemplate','research_digest'),('factoryPurpose','A changed public purpose'),('factoryName','Changed workflow'),
             ('factoryAgentFirst','101'),('factoryAgentSecond','102'),('factoryFromUTC','2026-10-18T00:00:00Z'),('factoryDimension','mass')]
    for identity, value in edits:
        prepare(s); page.locator('#factorySaveConsent').check()
        element = page.locator('#'+identity)
        if identity in ('factoryTemplate','factoryDimension'): element.select_option(value)
        else: element.fill(value)
        expect(page.locator('#factoryReview')).to_be_empty(); expect(page.locator('#factorySaveConsent')).not_to_be_checked()
        expect(page.locator('#factorySave')).to_be_disabled()
    assert not s.commits


def test_review_expiry_clears_preview_consent_and_disabled_save(growth_page):
    s = growth_page; page = s.page; prepare(s); page.locator('#factorySaveConsent').check()
    page.clock.fast_forward(301000)
    expect(page.get_by_role('status')).to_contain_text('graph review expired')
    expect(page.locator('#factoryReview')).to_be_empty(); expect(page.locator('#factorySaveConsent')).not_to_be_checked()
    expect(page.locator('#factorySave')).to_be_disabled()
    page.locator('#factorySaveConsent').check(); expect(page.locator('#factorySave')).to_be_disabled()
    page.locator('#factorySave').dispatch_event('click'); assert not s.commits


def test_late_review_after_input_edit_is_discarded_and_does_not_strand_busy(growth_page):
    s = growth_page; page = s.page; s.hold_reviews = True
    page.locator('#factoryPurpose').fill('Earlier public purpose'); page.locator('#factoryPrepare').click()
    assert len(s.pending) == 1
    page.locator('#factoryPurpose').fill('Edited while preparation was pending'); s.release()
    expect(page.locator('#factoryReview')).to_be_empty(); expect(page.locator('#factorySave')).to_be_disabled()
    s.hold_reviews = False; page.locator('#factoryPrepare').click()
    expect(page.get_by_role('status')).to_contain_text('Review ready.')
    expect(page.locator('#factoryReview')).to_contain_text('Edited while preparation was pending')
    assert s.review_count == 2 and not s.commits


def test_lost_commit_ack_never_retries_and_requires_fresh_read_and_review(growth_page):
    s = growth_page; page = s.page; prepare(s); s.lose_commit_ack = True
    page.locator('#factorySaveConsent').check(); page.locator('#factorySave').click()
    expect(page.get_by_role('status')).to_contain_text('No command is retried automatically.')
    assert len(s.commits) == 1
    page.locator('#factorySave').dispatch_event('click'); page.locator('#factoryPrepare').click()
    page.clock.fast_forward(10000)
    assert len(s.commits) == 1 and s.review_count == 1
    page.get_by_role('button',name='Read current state',exact=True).click()
    expect(page.get_by_role('status')).to_contain_text('Current private state loaded.')
    expect(page.locator('#factoryReview')).to_be_empty(); expect(page.locator('#factorySaveConsent')).not_to_be_checked()
    expect(page.locator('#factorySave')).to_be_disabled(); assert len(s.commits) == 1


def test_sdk_edits_reset_exact_policy_approval_and_hostile_catalog_is_text(growth_page):
    s = growth_page; page = s.page
    page.get_by_role('button',name='SDK lifecycle',exact=True).click()
    expect(page.locator('#sdkPolicyConsent')).not_to_be_checked()
    expect(page.locator('#workspaceGrowthDialog')).to_contain_text(HOSTILE)
    assert page.locator('#workspaceGrowthDialog img').count() == 0
    for identity, value in [('sdkPolicyProfile','workspace-typed-sdk-v2'),('sdkPolicyAccepting',False),('sdkPolicyMinutes','15')]:
        page.locator('#sdkPolicyConsent').check(); element = page.locator('#'+identity)
        if identity == 'sdkPolicyProfile': element.select_option(value)
        elif identity == 'sdkPolicyAccepting': element.set_checked(value)
        else: element.fill(value)
        expect(page.locator('#sdkPolicyConsent')).not_to_be_checked()
        page.locator('#sdkPolicyApply').click(); assert not s.sdk_writes
    page.locator('#sdkPolicyConsent').check(); page.locator('#sdkPolicyApply').click()
    expect(page.get_by_role('status')).to_contain_text('Current private state loaded.')
    assert s.sdk_writes == [{'sdk_profile':'workspace-typed-sdk-v2','revision':0,'accepting_runs':False,
        'minimum_sdk_version':'2.1.0','sunset_seconds':900,'authorized':True,'notice':'workspace-sdk-lifecycle-v1'}]
    expect(page.locator('#sdkPolicyConsent')).not_to_be_checked()


def test_support_edits_and_withdrawal_require_independent_unchecked_purpose_approval(growth_page):
    s = growth_page; page = s.page
    page.get_by_role('button',name='Support outcomes',exact=True).click()
    expect(page.locator('#supportRecordConsent')).not_to_be_checked()
    expect(page.locator('#workspaceGrowthDialog')).to_contain_text('Business outcome and provider quality remain unassessed.')
    assert page.locator('#workspaceGrowthDialog img').count() == 0
    edits = [('supportSourceKind','single'),('supportSubject','wd_'+'6'*32),('supportVersion','wv_'+'7'*32),
             ('supportRun','wpr_'+'8'*32),('supportCategory','recovery'),('supportResolution','resolved'),
             ('supportIterations','2'),('supportRevision','1')]
    for identity, value in edits:
        page.locator('#supportRecordConsent').check(); element = page.locator('#'+identity)
        if identity in ('supportSourceKind','supportCategory','supportResolution'): element.select_option(value)
        else: element.fill(value)
        expect(page.locator('#supportRecordConsent')).not_to_be_checked()
        page.locator('#supportRecord').click(); assert not s.support_writes
    page.locator('#supportRecordConsent').check(); page.locator('#supportRecord').click()
    expect(page.get_by_role('status')).to_contain_text('Current private state loaded.')
    assert s.support_writes == [{'source_kind':'single','subject_id':'wd_'+'6'*32,'version_id':'wv_'+'7'*32,'run_id':'wpr_'+'8'*32,
        'category':'recovery','resolution':'resolved','iterations':2,'revision':1,'authorized':True,'notice':'workspace-support-outcome-record-v1'}]
    expect(page.locator('#supportRecordConsent')).not_to_be_checked()
    withdraw = page.get_by_label('Permanently withdraw this support observation from this workspace report. The original execution record is not erased.')
    expect(withdraw).not_to_be_checked(); page.get_by_role('button',name='Withdraw support observation',exact=True).click()
    assert not s.withdrawals
    withdraw.check(); page.get_by_role('button',name='Withdraw support observation',exact=True).click()
    expect(page.get_by_role('status')).to_contain_text('Current private state loaded.')
    assert len(s.withdrawals) == 1 and s.withdrawals[0]['revision'] == 1
    expect(page.get_by_role('button',name='Withdraw support observation',exact=True)).to_have_count(0)


@pytest.mark.parametrize('change',['workspace','session'])
def test_workspace_or_session_switch_removes_dialog_and_discards_late_results(growth_page,change):
    s = growth_page; page = s.page; s.hold_reviews = True
    page.locator('#factoryPurpose').fill('Discard this earlier-session graph'); page.locator('#factoryPrepare').click()
    assert len(s.pending) == 1
    if change == 'workspace':
        page.select_option('#workspaceSelect',OTHER_WS); page.evaluate('window.WorkspaceGrowthAdmin.onSession()')
        next_ws = OTHER_WS
    else:
        page.evaluate("token='b'.repeat(64);currentUser={user_id:2,role:'admin'};window.WorkspaceGrowthAdmin.onSession()")
        next_ws = WS
    expect(page.locator('#workspaceGrowthDialog')).to_have_count(0)
    page.evaluate('(ws)=>window.WorkspaceGrowthAdmin.open(ws)',next_ws)
    expect(page.get_by_role('status')).to_contain_text('Current private state loaded.')
    s.release()
    expect(page.locator('#factoryReview')).to_be_empty()
    expect(page.locator('#workspaceGrowthDialog')).not_to_contain_text('Discard this earlier-session graph')
    expect(page.locator('#factorySaveConsent')).not_to_be_checked(); expect(page.locator('#factorySave')).to_be_disabled()
    assert not s.commits
