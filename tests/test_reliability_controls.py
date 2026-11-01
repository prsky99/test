"""Isolated approvals, scheduling, expiring trust and zero-dispatch decision tests."""
import copy
import json
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.capability_contracts import CONTRACTS
from agent_market.capability_registry import Registry, digest
from agent_market.collector import usage
from agent_market.gateway import admin_auth
from agent_market.reliability_control_service import router_for
from agent_market.reliability_controls_restore import authority_id
from agent_market.reliability_evaluation import NOTICE as EVAL_NOTICE, ReliabilityEvaluation
from agent_market.reliability_routing import NOTICE as ROUTE_NOTICE, ReliabilityRouting
from agent_market.reliability_trust import ReliabilityTrust, safe_badge
from agent_market.workspace_access import SessionActor, WorkspaceAccess, _hash
from agent_market.workflows import runtime_for
from tests.test_workspace_execution_api import private_api
from tests.test_workflow_runtime import node, save


@pytest.fixture
def controls(private_api, monkeypatch):
    w = private_api
    w.now = time.time(); w.runtime = runtime_for(w.store, None)
    w.access = WorkspaceAccess(w.store, w.runtime.key)
    spec = {'name': 'search_docs', 'description': 'Search public documentation',
            'inputSchema': copy.deepcopy(CONTRACTS['docs.search.v1']['input_schema']),
            'outputSchema': copy.deepcopy(CONTRACTS['docs.search.v1']['output_schema']),
            'annotations': {'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True}}
    w.rids = []
    for host in ('primary.example', 'alternate.example', 'primary.example'):
        rid = w.store.upsert_resource({'key': 'mcp:https://'+host+'/'+str(len(w.rids)), 'kind': 'mcp',
            'source': 'mcp-registry', 'name': 'Synthetic approved read', 'description': 'Public documentation',
            'category': 'dev_tools', 'url': 'https://'+host+'/'+str(len(w.rids)), 'price_usdc': 0, 'details': {}})
        w.store.record_usage(rid, usage.compact_tools([spec]), usage.tools_hash(usage.compact_tools([spec])),
                             {}, None, {'ok': True}, full_tools=[spec])
        with w.store.tx() as db:
            db.execute("UPDATE resources SET health_status='healthy' WHERE id=?", (rid,))
        registry = Registry(w.store); version = registry.approve(w.store.resource(rid), 'docs.search.v1', 'search_docs')
        for scope in ('execution', 'contract'):
            started = time.time(); finished = time.time()
            registry.record(version, scope=scope, outcome='succeeded', started=started, finished=finished,
                            contract_id='docs.search.v1' if scope == 'contract' else '')
        w.rids.append(rid)
    w.workflow = save(w.store, [node('lookup', resource_id=w.rids[0], tool='search_docs',
        input={'query': 'documentation', 'language': 'en', 'limit': 2})], name='Synthetic offline workflow')
    w.actor = SessionActor(1, admin_auth.session_reference(w.headers['owner']['Authorization'][7:]))
    w.sources = {}
    for rid in w.rids:
        version = Registry(w.store).current(rid)
        w.sources[rid] = {'resource_id': rid, 'agent_version': version['id'], 'schema_hash': version['schema_hash'],
            'source_revision': digest(['fixture', rid]), 'contract_id': 'docs.search.v1', 'contract_revision': 1,
            'contract_hash': digest(CONTRACTS['docs.search.v1']), 'quality_status': 'assessed', 'source_fidelity': 'verified',
            'independent_qualified': True, 'latest_observed_at': w.now-10, 'expires_at': w.now+3600,
            'revoked': False, 'logical_samples': 20, 'outcomes': {'succeeded': 20, 'failed': 0, 'unknown': 0},
            'latency_ms': {'p50': 2, 'p95': 5, 'scope': 'gateway_observation_interval'},
            'environment': 'isolated', 'qualified_operating_evidence': False, 'public_activation': False,
            'private_prompt': '<script>SECRET_PROMPT</script>'}
    source = lambda ws, rid, actor: copy.deepcopy(w.sources[rid])
    w.evaluation = ReliabilityEvaluation(w.access, w.runtime)
    w.routing = ReliabilityRouting(w.access, w.runtime, evidence_source=source)
    w.trust = ReliabilityTrust(w.access, evidence_source=source)
    app = FastAPI(); app.include_router(router_for(w.access, w.runtime, evaluation=w.evaluation, routing=w.routing, trust=w.trust))
    w.control_api = TestClient(app, base_url='https://private.test')
    w.base = '/admin/api/workflow-workspaces/'+w.ws['id']+'/reliability'
    monkeypatch.setattr('agent_market.reliability_evaluation.clock', lambda: w.now)
    monkeypatch.setattr('agent_market.reliability_trust.clock', lambda: w.now)
    monkeypatch.setattr('agent_market.reliability_routing.clock', lambda: w.now)
    try:
        yield w
    finally:
        w.control_api.close()


def get(w, path, person='owner', headers=None):
    return w.control_api.get(w.base+path, headers=headers or w.headers[person])


def post(w, path, body, person='owner', headers=None):
    return w.control_api.post(w.base+path, headers=headers or w.headers[person], json=body)


def corpus(w, **changes):
    return {'corpus_id': 'rcp_'+'1'*32, 'version': 'synthetic-fixture-v1', 'contract_id': 'docs.search.v1',
            'cases': [{'case_id': 'holdout-1', 'kind': 'repeatability', 'split': 'holdout',
                       'input': {'query': 'Public documentation', 'language': 'en', 'limit': 2}}],
            'training_hashes': [], 'authorized': True, 'notice': EVAL_NOTICE,
            'data_attestation': 'synthetic_or_licensed_no_personal_data', **changes}


def plan(w, **changes):
    return {'revision': 0, 'corpus_id': 'rcp_'+'1'*32, 'resource_ids': [w.rids[0]], 'interval_seconds': 600,
            'jitter_seconds': 0, 'per_host_budget': 1, 'expires': w.now+3600,
            'authorized': True, 'notice': EVAL_NOTICE, **changes}


def setup_plan(w, **changes):
    assert post(w, '/evaluation/corpora', corpus(w)).status_code == 200
    response = post(w, '/evaluation/plans', plan(w, **changes)); assert response.status_code == 200, response.text
    assert post(w, '/evaluation/control', {'revision': 0, 'enabled': True, 'authorized': True, 'notice': EVAL_NOTICE}).status_code == 200
    return response.json()['result']


def reserve(w):
    response = post(w, '/evaluation/reserve', {'revision': 1, 'authorized': True, 'notice': EVAL_NOTICE})
    assert response.status_code == 200, response.text
    return response.json()['result']


def prepare(w, identity):
    return post(w, '/evaluation/jobs/'+identity+'/prepare', {'authorized': True, 'notice': EVAL_NOTICE})


def dispatch(w, identity):
    return post(w, '/evaluation/jobs/'+identity+'/dispatch', {'authorized': True, 'notice': EVAL_NOTICE})


def routing_policy(w, **changes):
    return {'revision': 0, 'mode': 'offline', 'workflow_id': w.workflow['id'], 'contract_id': 'docs.search.v1',
            'resource_ids': w.rids[:2], 'share_resource_ids': w.rids[:2], 'expires': w.now+3600,
            'enabled': True, 'authorized': True, 'notice': ROUTE_NOTICE, **changes}


def decide(w, identity='rld_'+'2'*32):
    return post(w, '/routing/decide', {'revision': 1, 'logical_id': identity, 'authorized': True, 'notice': ROUTE_NOTICE})


def test_default_off_has_actual_coverage_debt_without_fresh_reports_or_provider_adapter(controls):
    w = controls
    options = get(w, '/evaluation/options').json()['result']
    assert not options['control']['enabled'] and not options['evaluator_configured'] and not options['automatic_worker_enabled']
    setup_plan(w); w.now += 1200
    state = get(w, '/evaluation/status').json()['result']
    assert state['coverage']['expected_cases'] >= 2 and state['coverage']['debt_cases'] >= 2
    assert state['coverage']['latest_actual_observed_at'] is None and state['jobs'] == [] and not w.calls
    assert state['quality_status'] == 'not_inferred_from_scheduler'


@pytest.mark.parametrize('person', ['editor', 'viewer', 'operator', 'outsider'])
def test_owner_approval_is_required_for_corpus_plan_and_routing(controls, person):
    w = controls
    assert post(w, '/evaluation/corpora', corpus(w), person).status_code == 404
    assert post(w, '/routing/configure', routing_policy(w), person).status_code == 404
    assert not w.calls


@pytest.mark.parametrize('headers', [{}, {'X-Dashboard': '1', 'Authorization': 'Bearer machine-token'}])
def test_customer_machine_and_anonymous_tokens_are_not_staff_authority(controls, headers):
    w = controls
    w.control_api.cookies.set('__Host-ac_customer_session', 'synthetic-session')
    assert get(w, '/evaluation/options', headers=headers or {'X-Dashboard': '1'}).status_code == 401
    assert post(w, '/routing/configure', routing_policy(w), headers=headers or {'X-Dashboard': '1'}).status_code == 401


@pytest.mark.parametrize('extra', [{'Origin': 'https://outside.example'}, {'Origin': 'null'}, {'Sec-Fetch-Site': 'cross-site'}])
def test_csrf_and_cross_origin_trust_reads_are_denied(controls, extra):
    w = controls; headers = w.headers['owner'] | extra
    assert post(w, '/evaluation/corpora', corpus(w), headers=headers).status_code == 403
    assert get(w, '/trust/'+str(w.rids[0]), headers=headers).status_code == 403
    assert not w.calls


def test_training_overlap_holdout_contamination_and_mutable_corpus_are_rejected(controls):
    w = controls; body = corpus(w)
    leaked = copy.deepcopy(body); leaked['training_hashes'] = [_hash(body['cases'][0]['input'])]
    assert post(w, '/evaluation/corpora', leaked).status_code == 400
    duplicated = copy.deepcopy(body); duplicated['cases'].append(body['cases'][0] | {'case_id': 'evaluation-1', 'split': 'evaluation'})
    assert post(w, '/evaluation/corpora', duplicated).status_code == 400
    assert post(w, '/evaluation/corpora', body).status_code == 200
    assert post(w, '/evaluation/corpora', body).json()['result']['replayed']
    changed = copy.deepcopy(body); changed['cases'][0]['input']['query'] = 'Changed corpus'
    assert post(w, '/evaluation/corpora', changed).status_code == 409
    assert not w.calls


def test_host_budget_jitter_dedupe_and_host_concurrency_are_enforced(controls):
    w = controls; setup_plan(w, resource_ids=[w.rids[0], w.rids[2]], per_host_budget=1, jitter_seconds=30)
    first = reserve(w); again = reserve(w)
    assert len(first['jobs']) == 1 and first['deferred_cases'] == 1
    assert first['jobs'][0]['id'] == again['jobs'][0]['id']
    job = first['jobs'][0]
    assert job['window_start'] <= job['not_before'] <= max(job['window_start']+30, job['created'])
    w.now = max(w.now, job['not_before'])
    assert prepare(w, job['id']).status_code == 200
    assert dispatch(w, job['id']).status_code == 409 and not w.calls
    assert get(w, '/evaluation/status').json()['result']['jobs'][0]['state'] == 'prepared'


def test_trusted_read_adapter_is_single_dispatch_and_unknown_never_replays(controls):
    w = controls; setup_plan(w)
    job = reserve(w)['jobs'][0]; assert prepare(w, job['id']).status_code == 200
    calls = []
    def lost(envelope):
        calls.append(envelope)
        raise TimeoutError('Sensitive provider diagnostic')
    w.evaluation.read_evaluator = lost; w.evaluation.evaluator_authorizer = lambda *args: True
    first = dispatch(w, job['id']); again = dispatch(w, job['id'])
    assert first.status_code == 200 and first.json()['result']['state'] == 'unknown'
    assert again.json()['result']['state'] == 'unknown' and len(calls) == 1
    assert calls[0]['purpose'] == 'approved_read_evaluation' and calls[0]['case']['split'] == 'holdout'
    assert 'Sensitive provider diagnostic' not in first.text and not w.calls
    assert get(w, '/evaluation/status').json()['result']['coverage']['latest_actual_observed_at'] is None


def test_concurrent_dispatch_and_expired_dispatched_recovery_never_reinvoke(controls):
    w = controls; setup_plan(w); job = reserve(w)['jobs'][0]; assert prepare(w, job['id']).status_code == 200
    calls = []
    w.evaluation.evaluator_authorizer = lambda *args: True
    w.evaluation.read_evaluator = lambda envelope: calls.append(envelope) or {'outcome': 'completed', 'observed_at': w.now, 'evidence_ref': 'fixture-observation'}
    body = {'authorized': True, 'notice': EVAL_NOTICE}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: w.evaluation.dispatch(w.ws['id'], job['id'], body, w.actor), range(2)))
    assert len(calls) == 1 and all(result['state'] in ('dispatched', 'completed') for result in results)
    assert get(w, '/evaluation/status').json()['result']['coverage']['latest_actual_observed_at'] == w.now
    with w.store.tx() as db:
        value = w.evaluation._job(db, w.ws['id'], job['id']); value.update(state='dispatched', finished_at=None)
        w.evaluation._put(db, 'job', value)
    w.now = job['expires']
    assert get(w, '/evaluation/status').json()['result']['jobs'][0]['state'] == 'unknown'
    assert dispatch(w, job['id']).json()['result']['state'] == 'unknown' and len(calls) == 1


@pytest.mark.parametrize('change', ['kill', 'approval', 'membership', 'session'])
def test_prepared_job_checks_current_kill_approval_membership_and_session(controls, change):
    w = controls; setup_plan(w); job = reserve(w)['jobs'][0]; assert prepare(w, job['id']).status_code == 200
    calls = []; w.evaluation.read_evaluator = lambda envelope: calls.append(envelope)
    w.evaluation.evaluator_authorizer = lambda *args: True
    with w.store.tx() as db:
        if change == 'kill':
            db.execute('UPDATE execution_controls SET invoke_enabled=0 WHERE id=1')
        elif change == 'approval':
            db.execute('DELETE FROM capability_approvals WHERE version_id=?', (Registry(w.store).current(w.rids[0])['id'],))
        elif change == 'membership':
            db.execute('UPDATE workspace_memberships SET revision=revision+1 WHERE workspace_id=? AND user_id=1', (w.ws['id'],))
        else:
            db.execute('DELETE FROM admin_sessions WHERE user_id=1')
    assert dispatch(w, job['id']).status_code in (401, 404, 409) and not calls and not w.calls


def test_permission_change_during_evaluation_can_only_leave_unknown(controls):
    w = controls; setup_plan(w); job = reserve(w)['jobs'][0]; assert prepare(w, job['id']).status_code == 200
    w.evaluation.evaluator_authorizer = lambda *args: True
    def evaluate(envelope):
        w.evaluation.set_control(w.ws['id'], {'revision': 1, 'enabled': False, 'authorized': True, 'notice': EVAL_NOTICE}, w.actor)
        return {'outcome': 'completed', 'observed_at': w.now, 'evidence_ref': 'fixture-only'}
    w.evaluation.read_evaluator = evaluate
    result = dispatch(w, job['id']).json()['result']
    assert result['state'] == 'unknown' and result['outcome'] == 'unknown' and not w.calls


def test_cancelled_prepared_job_expires_and_never_calls_evaluator(controls):
    w = controls; setup_plan(w); job = reserve(w)['jobs'][0]; assert prepare(w, job['id']).status_code == 200
    calls = []; w.evaluation.read_evaluator = lambda envelope: calls.append(envelope)
    w.evaluation.evaluator_authorizer = lambda *args: True
    response = post(w, '/evaluation/jobs/'+job['id']+'/cancel', {'authorized': True, 'notice': EVAL_NOTICE})
    assert response.json()['result']['state'] == 'expired'
    assert dispatch(w, job['id']).json()['result']['state'] == 'expired' and not calls and not w.calls


def test_plan_revision_change_does_not_inherit_old_scheduled_coverage_or_observation_time(controls):
    w = controls; setup_plan(w); job = reserve(w)['jobs'][0]; assert prepare(w, job['id']).status_code == 200
    w.evaluation.evaluator_authorizer = lambda *args: True
    w.evaluation.read_evaluator = lambda envelope: {'outcome': 'completed', 'observed_at': w.now, 'evidence_ref': 'fixture-only'}
    assert dispatch(w, job['id']).json()['result']['state'] == 'completed'
    assert post(w, '/evaluation/plans', plan(w, revision=1)).status_code == 200
    coverage = get(w, '/evaluation/status').json()['result']['coverage']
    assert coverage['plan_revision'] == 2 and coverage['scheduled_cases'] == 0
    assert coverage['latest_actual_observed_at'] is None and coverage['debt_cases'] >= 1


def test_isolated_evidence_never_grants_last_verified_or_operating_badge(controls):
    w = controls; response = get(w, '/trust/'+str(w.rids[0])); result = response.json()['result']
    assert result['state'] == 'evidence_pending' and result['last_verified_at'] is None
    assert not result['qualified_operating_evidence'] and not result['public_activation'] and result['provider_calls'] == 0
    assert 'SECRET_PROMPT' not in response.text and 'primary.example' not in response.text


def test_conditional_trust_read_rechecks_expiry_revocation_version_and_session(controls):
    w = controls; rid = w.rids[0]; w.sources[rid]['environment'] = 'approved_external'
    path = '/trust/'+str(rid); first = get(w, path); assert first.json()['result']['state'] == 'last_verified'
    assert first.json()['result']['contract_id'] == 'docs.search.v1'
    tag = first.headers['etag']; cached = w.headers['owner'] | {'If-None-Match': tag}
    assert get(w, path, headers=cached).status_code == 304
    for invalid in ('*', 'W/'+tag, tag+', "other"'):
        assert get(w, path, headers=w.headers['owner'] | {'If-None-Match': invalid}).status_code == 200
    w.sources[rid]['revoked'] = True
    revoked = get(w, path, headers=cached); assert revoked.status_code == 200 and revoked.json()['result']['state'] == 'evidence_pending'
    w.sources[rid]['revoked'] = False; w.now = w.sources[rid]['expires_at']
    expired = get(w, path, headers=cached); assert expired.status_code == 200 and expired.json()['result']['state'] == 'verification_expired'
    with w.store.tx() as db:
        db.execute('UPDATE resources SET url=? WHERE id=?', ('https://changed.example/mcp', rid))
    assert get(w, path, headers=cached).json()['result']['state'] == 'evidence_pending'
    with w.store.tx() as db:
        db.execute('DELETE FROM admin_sessions WHERE user_id=1')
    assert get(w, path, headers=cached).status_code == 401


def test_svg_fixed_template_escapes_malicious_text_and_disables_external_content(controls):
    w = controls
    svg = safe_badge({'state': 'evidence_pending', 'agent_version': '"><script>alert(1)</script><foreignObject href="https://bad.example">'})
    assert '<script' not in svg and '<foreignObject' not in svg and '&lt;script&gt;' in svg
    assert 'href=' not in svg.replace('&quot;', '') or 'href=&quot;' in svg
    response = get(w, '/trust/'+str(w.rids[0])+'/badge.svg')
    assert response.status_code == 200 and response.headers['content-type'].startswith('image/svg+xml')
    assert response.headers['cache-control'] == 'no-store' and response.headers['x-content-type-options'] == 'nosniff'
    assert "default-src 'none'" in response.headers['content-security-policy'] and not w.calls
    json_response = get(w, '/trust/'+str(w.rids[0]))
    assert response.headers['etag'] != json_response.headers['etag']
    assert get(w, '/trust/'+str(w.rids[0])+'/badge.svg', headers=w.headers['owner'] | {'If-None-Match': json_response.headers['etag']}).status_code == 200


def test_rule_routing_uses_current_qualified_equivalent_candidates_and_never_dispatches(controls):
    w = controls; w.sources[w.rids[0]]['outcomes'] = {'succeeded': 15, 'failed': 3, 'unknown': 2}
    response = post(w, '/routing/configure', routing_policy(w)); assert response.status_code == 200, response.text
    decision = decide(w).json()['result']
    assert decision['selected_resource_id'] == w.rids[1] and decision['business_calls'] == decision['replacement_calls'] == 0
    assert decision['future_business_call_limit'] == 1 and decision['future_replacements_limit'] == 0
    assert decision['selected_propensity'] == 1 and not decision['execution_authority']
    assert decide(w).json()['result']['replayed'] and not w.calls
    w.sources[w.rids[1]]['revoked'] = True
    assert decide(w).status_code == 409


@pytest.mark.parametrize('change,reason', [('expiry', 'evidence_expired'), ('revoked', 'evidence_binding_changed'),
    ('schema', 'evidence_binding_changed'), ('half_open', 'circuit_probe_requires_separate_evaluation'), ('quality', 'unqualified_evidence')])
def test_safe_admission_excludes_changed_evidence_and_no_probe_is_dispatched(controls, change, reason):
    w = controls; assert post(w, '/routing/configure', routing_policy(w)).status_code == 200
    source = w.sources[w.rids[0]]
    if change == 'expiry': source['expires_at'] = w.now
    elif change == 'revoked': source['revoked'] = True
    elif change == 'schema': source['schema_hash'] = 'changed'
    elif change == 'half_open': source['circuit_state'] = 'half-open'
    else: source['quality_status'] = 'unassessed'
    response = decide(w); assert response.status_code == 200, response.text
    decision = response.json()['result']; assert decision['selected_resource_id'] == w.rids[1]
    assert {'resource_id': w.rids[0], 'reason': reason} in decision['excluded'] and not w.calls


def test_common_host_failure_excludes_correlated_candidate_and_both_failed_is_neutral(controls):
    w = controls; refs = [w.rids[0], w.rids[2]]
    assert post(w, '/routing/configure', routing_policy(w, resource_ids=refs, share_resource_ids=refs, mode='decision_shadow')).status_code == 200
    w.sources[w.rids[0]]['circuit_state'] = 'open'
    result = decide(w).json()['result']
    assert result['selected_resource_id'] is None and result['mode'] == 'decision_shadow'
    assert {item['reason'] for item in result['excluded']} == {'circuit_probe_requires_separate_evaluation', 'correlated_host_failure'}
    assert not w.calls


def test_offline_replay_uses_signed_snapshots_without_duplicate_history_or_causal_claim(controls):
    w = controls; assert post(w, '/routing/configure', routing_policy(w)).status_code == 200
    assert decide(w).status_code == 200
    assert decide(w, 'rld_'+'3'*32).status_code == 200
    result = post(w, '/routing/replay', {'revision': 1, 'authorized': True, 'notice': ROUTE_NOTICE}).json()['result']
    assert result['replayed_decisions'] == result['deterministic_matches'] == 2
    assert result['baseline_history']['logical_observations'] == result['selected_history']['logical_observations'] == 20
    assert not result['paired_corpus_verified'] and not result['causal_improvement_established']
    assert result['extra_attempts'] == result['business_calls'] == 0 and not w.calls


def test_existing_fallback_budget_is_mutually_exclusive_and_kill_remains_available(controls):
    w = controls; assert post(w, '/routing/configure', routing_policy(w)).status_code == 200
    from agent_market.workflow_fallback import NOTICE as FALLBACK_NOTICE
    w.runtime.fallback.configure(w.workflow['id'], {'revision': 0, 'mode': 'shadow',
        'pairs': [{'node_id': 'lookup', 'resource_id': w.rids[1], 'contract_id': 'docs.search.v1'}],
        'authority': True, 'notice': FALLBACK_NOTICE, 'canary_percent': 1, 'max_runs': 1,
        'expires': time.time()+3600}, 1)
    assert decide(w).status_code == 409
    with w.store.tx() as db:
        db.execute('DELETE FROM capability_approvals')
    # Pause must work even after contract evidence or another profile changed.
    assert post(w, '/routing/configure', routing_policy(w, revision=1, enabled=False)).status_code == 200
    assert not w.calls


def test_cross_workspace_idor_and_strict_json_do_not_admit(controls):
    w = controls; setup_plan(w); job = reserve(w)['jobs'][0]
    other = w.access.provision({'name': 'Other scoped team', 'owner_id': 1}, w.actor)['id']
    other_path = w.base.replace(w.ws['id'], other)
    response = w.control_api.post(other_path+'/evaluation/jobs/'+job['id']+'/prepare', headers=w.headers['owner'], json={'authorized': True, 'notice': EVAL_NOTICE})
    assert response.status_code in (404, 409)
    for raw in ('{"authorized":true,"authorized":false}', '{"revision":NaN}', '[]', 'x'*32769):
        response = w.control_api.post(w.base+'/evaluation/corpora', headers=w.headers['owner'], content=raw)
        assert response.status_code == 400 and response.headers['cache-control'] == 'no-store'
    assert not w.calls


def test_restore_tombstones_do_not_rewrite_signed_payloads_or_revive_dispatch_authority(controls):
    w = controls; setup_plan(w, resource_ids=w.rids[:2], per_host_budget=2)
    jobs = reserve(w)['jobs']; assert len(jobs) == 2
    assert post(w, '/routing/configure', routing_policy(w)).status_code == 200
    with w.store.tx() as db:
        uncertain = w.evaluation._job(db, w.ws['id'], jobs[1]['id'])
        uncertain.update(state='dispatched', dispatched_at=w.now)
        w.evaluation._put(db, 'job', uncertain)
        originals = {table: [dict(row) for row in db.execute('SELECT * FROM '+table)] for table in (
            'reliability_eval_controls', 'reliability_eval_plans', 'reliability_eval_jobs', 'reliability_route_policies')}
        keys = [authority_id('eval_control', w.ws['id'], 1), authority_id('eval_plan', w.ws['id'], 1),
                authority_id('routing_policy', w.ws['id'], 1), *(authority_id('eval_job', job['id']) for job in jobs)]
        for key in keys:
            db.execute('INSERT INTO reliability_controls_restore_blocks VALUES(?)', (key,))
    state = get(w, '/evaluation/status').json()['result']
    assert not state['control']['enabled'] and state['plan']['restore_quarantined']
    assert {job['state'] for job in state['jobs']} == {'unknown', 'expired'}
    assert all(job['restore_quarantined'] for job in state['jobs'])
    assert state['coverage']['scheduled_cases'] == 0 and state['coverage']['latest_actual_observed_at'] is None
    assert get(w, '/routing/status').json()['result']['policy']['restore_quarantined']
    assert decide(w).status_code == 409
    assert dispatch(w, jobs[1]['id']).status_code == 409
    with w.store.tx() as db:
        for table, old in originals.items():
            assert [dict(row) for row in db.execute('SELECT * FROM '+table)] == old
    # A restored corpus is data; explicitly issuing only a fresh control does not approve its old plan.
    assert post(w, '/evaluation/control', {'revision': 1, 'enabled': True, 'authorized': True, 'notice': EVAL_NOTICE}).status_code == 200
    assert post(w, '/evaluation/reserve', {'revision': 1, 'authorized': True, 'notice': EVAL_NOTICE}).status_code == 409
    assert post(w, '/evaluation/plans', plan(w, revision=1, resource_ids=w.rids[:2], per_host_budget=2)).status_code == 200
    calls = []; w.evaluation.read_evaluator = lambda envelope: calls.append(envelope)
    w.evaluation.evaluator_authorizer = lambda *args: True
    restored_job = dispatch(w, jobs[1]['id'])
    assert restored_job.status_code == 200 and restored_job.json()['result']['state'] == 'unknown' and not calls
    # Putting an older signed authority row back cannot remove its permanent tombstone.
    with w.store.tx() as db:
        old = originals['reliability_eval_plans'][0]
        db.execute('UPDATE reliability_eval_plans SET revision=?,payload=?,signature=? WHERE workspace_id=?',
                   (old['revision'], old['payload'], old['signature'], w.ws['id']))
    assert post(w, '/evaluation/reserve', {'revision': 1, 'authorized': True, 'notice': EVAL_NOTICE}).status_code == 409
    assert not w.calls
