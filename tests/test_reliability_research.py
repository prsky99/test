"""Isolated paired research uses existing jobs and bounded synthetic transports."""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from agent_market.reliability_research import (NOTICE, ReliabilityResearch, fixture_fault, item_goal_hash)
from agent_market.reliability_research_service import router_for
from agent_market.reliability_evaluation import NOTICE as EVAL_NOTICE
from agent_market.workspace_access import WorkspaceConflict, WorkspaceInvalid
from tests.test_reliability_controls import controls, private_api, plan, post, reserve, prepare, dispatch
from tests.test_reliability_evaluation_worker import worker_world


def item(w):
    return {'url': 'https://docs.example/approved', 'title': 'Approved fixture',
            'excerpt': 'Known licensed fixture fact', 'version': '1',
            'retrieved_at': datetime.fromtimestamp(w.now, timezone.utc).isoformat()}


def manifest(w, **changes):
    return {'manifest_id': 'rrm_'+'8'*32, 'version': 'paired-v1', 'contract_id': 'docs.search.v1',
            'cases': [{'case_id': 'docs-1', 'input': {'query': 'Approved public documentation', 'language': 'en', 'limit': 2},
                       'expected_items': [item_goal_hash('docs.search.v1', item(w))]}],
            'k': 2, 'mutators': ['outer-whitespace-v1'], 'seed': 17,
            'reference_time': w.now, 'timezone': 'UTC', 'locale': 'en-US', 'dataset_version': 'licensed-fixture-v1',
            'oracle_version': 'exact-approved-item-goal-v1',
            'analysis': {'version': 'paired-analysis-v1', 'minimum_pairs': 2,
                         'grouping': 'resource-version-host-window-case-trials',
                         'unknown_policy': 'retain_in_admitted_denominator',
                         'confidence': 'conservative-wilson95-and-cluster-count'},
            'expires': w.now+3600, 'adaptive_priority': False, 'authorized': True, 'notice': NOTICE,
            'data_attestation': 'synthetic_or_licensed_no_personal_data',
            'semantic_attestation': 'reviewed_search_whitespace_preserves_task', **changes}


@pytest.fixture
def research_world(controls, monkeypatch):
    w = controls
    monkeypatch.setattr('agent_market.reliability_research.clock', lambda: w.now)
    w.research = ReliabilityResearch(w.access, w.evaluation)
    w.control_api.app.include_router(router_for(w.access, w.evaluation, research=w.research))
    w.research_base = w.base+'/research'
    yield w


def rp(w, path, body, who='owner', headers=None):
    return w.control_api.post(w.research_base+path, json=body, headers=headers or w.headers[who])


def rg(w, path, who='owner', headers=None):
    return w.control_api.get(w.research_base+path, headers=headers or w.headers[who])


def configured(w, body=None, **plan_changes):
    body = body or manifest(w)
    response = rp(w, '/manifests', body)
    assert response.status_code == 200, response.text
    approved = response.json()['result']
    assert post(w, '/evaluation/plans', plan(w, corpus_id=approved['corpus_id'], per_host_budget=4, **plan_changes)).status_code == 200
    assert post(w, '/evaluation/control', {'revision': 0, 'enabled': True, 'authorized': True, 'notice': EVAL_NOTICE}).status_code == 200
    return approved


def trusted_fixture(w, mode='pass'):
    w.research_calls = []
    def evaluate(envelope):
        w.research_calls.append(envelope['job_id'])
        output = {'items': [item(w)] if mode == 'pass' else [], 'partial': mode == 'partial'}
        state = 'unknown' if mode == 'unknown' else 'completed'
        if mode == 'oracle_error': output = {'invalid': True}
        observation = w.research.observe(envelope, output, state)
        return {'outcome': state, 'observed_at': w.now, 'evidence_ref': 'trusted_synthetic_observation',
                'research_observation': observation}
    w.evaluation.read_evaluator, w.evaluation.evaluator_authorizer = evaluate, lambda *args: True


def run_jobs(w):
    jobs = reserve(w)['jobs']
    for job in jobs:
        assert prepare(w, job['id']).status_code == 200
        assert dispatch(w, job['id']).status_code == 200
    return jobs


def analyze(w):
    return rg(w, '/manifests/'+('rrm_'+'8'*32)+'/analyze')


def test_manifest_creates_only_immutable_existing_corpus_no_calls(research_world):
    w = research_world; body = manifest(w)
    first = rp(w, '/manifests', body)
    assert first.status_code == 200 and first.json()['result']['planned_episodes'] == 4
    assert first.json()['result']['independent_quality'] == 'unassessed' and not w.calls
    assert rp(w, '/manifests', body).json()['result']['replayed']
    changed = deepcopy(body); changed['analysis']['minimum_pairs'] = 1
    assert rp(w, '/manifests', changed).status_code == 409
    with w.store.tx() as db:
        corpus = w.evaluation._corpus(db, w.ws['id'], first.json()['result']['corpus_id'])
        assert len(corpus['cases']) == 4
        assert corpus['cases'][0]['input']['query'] == 'Approved public documentation'
        assert corpus['cases'][1]['input']['query'] == ' Approved public documentation '
    assert not w.calls


def test_equal_corpus_content_never_inherits_another_manifest_authority(research_world):
    w = research_world; first = configured(w); trusted_fixture(w)
    second_body = manifest(w, manifest_id='rrm_'+'9'*32)
    second = rp(w, '/manifests', second_body).json()['result']
    assert first['corpus_hash'] == second['corpus_hash'] and first['corpus_id'] != second['corpus_id']
    assert rp(w, '/manifests/'+second['id']+'/withdraw', {'revision': 1, 'authorized': True, 'notice': NOTICE}).status_code == 200
    run_jobs(w)
    assert analyze(w).json()['result']['paired']['both_goal_pass'] == 2
    assert rg(w, '/manifests/'+second['id']+'/analyze').status_code == 409


@pytest.mark.parametrize('who', ['editor', 'viewer', 'operator', 'outsider'])
def test_non_owner_cannot_approve_or_analyze(research_world, who):
    w = research_world
    assert rp(w, '/manifests', manifest(w), who).status_code == 404
    configured(w)
    assert analyze(w).status_code == 200
    assert rg(w, '/manifests/rrm_'+'8'*32+'/analyze', who).status_code == 404


@pytest.mark.parametrize('change', [
    {'timezone': 'Asia/Seoul'}, {'locale': 'ko-KR'}, {'seed': True}, {'k': 4},
    {'mutators': ['unreviewed-paraphrase']}, {'oracle_version': 'llm-guaranteed-correct'},
    {'semantic_attestation': 'looks_equivalent'}, {'authorized': False},
    {'adaptive_priority': 'yes'}, {'reference_time': float('nan')},
])
def test_bounded_precommitted_manifest_rejects_invalid_scope(research_world, change):
    w = research_world
    if 'reference_time' in change:
        response = w.control_api.post(w.research_base+'/manifests', content='{"reference_time":NaN}', headers=w.headers['owner'])
    else:
        response = rp(w, '/manifests', manifest(w, **change))
    assert response.status_code == 400 and not w.calls


def test_meaning_changing_query_and_duplicate_goals_are_rejected(research_world):
    w = research_world; body = manifest(w)
    body['cases'][0]['input']['query'] = '"Exact phrase" OR https://private.example'
    assert rp(w, '/manifests', body).status_code == 400
    body = manifest(w); body['cases'][0]['expected_items'] *= 2
    assert rp(w, '/manifests', body).status_code == 400


@pytest.mark.parametrize('mode,label,rate', [('pass', 'both_goal_pass', 1), ('fail', 'both_failed', 0),
    ('unknown', 'unknown', 0), ('partial', 'unassessable', 0), ('oracle_error', 'unassessable', 0)])
def test_oracle_pairs_keep_failed_unknown_unassessable_and_admission_denominators(research_world, mode, label, rate):
    w = research_world; configured(w); trusted_fixture(w, mode)
    initial = analyze(w).json()['result']
    assert initial['scheduled_episodes'] == 0 and initial['unscheduled_episodes'] == initial['expected_episodes'] == 4
    jobs = run_jobs(w)
    result = analyze(w).json()['result']
    assert result['paired'][label] == result['paired']['admitted_pairs'] == 2
    assert len(w.research_calls) == 4 and len(set(w.research_calls)) == 4
    assert all(c['conservative_admitted_all_k_rate'] == rate for c in result['cells'])
    assert all(c['uncertainty']['low'] <= rate <= c['uncertainty']['high'] for c in result['cells'])
    assert result['independent_quality'] == 'unassessed' and not result['operating_qualification']
    assert result['promotion_status'] == 'pending_paired_intervention_evidence'
    assert result['false_stop_rate'] is result['successful_outcome_loss'] is None
    for job in jobs:
        assert dispatch(w, job['id']).status_code == 200
    assert len(w.research_calls) == 4
    assert 'Known licensed fixture fact' not in str(result)


def test_unadmitted_variant_remains_missing_and_not_a_successful_pair(research_world):
    w = research_world; configured(w); trusted_fixture(w)
    jobs = reserve(w)['jobs']; original = next(j for j in jobs if j['case_id'].endswith('-0'))
    assert prepare(w, original['id']).status_code == 200
    dispatch(w, original['id'])
    result = analyze(w).json()['result']
    assert result['paired']['both_goal_pass'] == 0 and result['paired']['unassessable'] == 2
    assert all(c['all_k_pass'] == 0 for c in result['cells'])


def test_plain_client_style_observation_cannot_forge_trusted_goal(research_world):
    w = research_world; configured(w)
    w.evaluation.evaluator_authorizer = lambda *a: True
    w.evaluation.read_evaluator = lambda e: {'outcome': 'completed', 'observed_at': w.now,
        'evidence_ref': 'synthetic_reference', 'research_observation': {'outcome': 'goal_pass'}}
    jobs = run_jobs(w)
    assert all(w.evaluation.status(w.ws['id'], w.actor)['jobs'][i]['state'] == 'unknown' for i in range(len(jobs)))
    assert analyze(w).json()['result']['paired']['unknown'] == 2


@pytest.mark.parametrize('change', ['withdraw', 'expiry', 'restore', 'membership'])
def test_research_current_authority_is_rechecked_before_each_dispatch(research_world, change):
    w = research_world; approved = configured(w); trusted_fixture(w)
    job = reserve(w)['jobs'][0]; assert prepare(w, job['id']).status_code == 200
    if change == 'withdraw':
        assert rp(w, '/manifests/'+approved['id']+'/withdraw', {'revision': 1, 'authorized': True, 'notice': NOTICE}).status_code == 200
    elif change == 'expiry': w.now += 3601
    else:
        with w.store.tx() as db:
            if change == 'restore': db.execute('INSERT INTO reliability_research_restore_blocks VALUES(?)', (approved['id'],))
            else: db.execute('UPDATE workspace_memberships SET revision=revision+1 WHERE workspace_id=?', (w.ws['id'],))
    assert dispatch(w, job['id']).status_code == 409
    assert not w.research_calls and not w.calls
    assert analyze(w).status_code == 409


def test_existing_concrete_worker_attaches_oracle_without_second_scheduler(worker_world, monkeypatch):
    w = worker_world
    monkeypatch.setattr('agent_market.reliability_research.clock', lambda: w.now)
    w.research = ReliabilityResearch(w.access, w.evaluation)
    w.control_api.app.include_router(router_for(w.access, w.evaluation, research=w.research))
    w.research_base = w.base+'/research'; configured(w)
    w.worker.activate(w.ws['id'], w.actor, 1)
    for _ in range(3): w.worker.tick()
    assert w.eval_calls.count('tools/call') == 4
    result = analyze(w).json()['result']
    assert result['paired']['both_failed'] == 2
    assert result['independent_quality'] == 'unassessed'
    assert w.evaluation.status(w.ws['id'], w.actor)['quality_status'] == 'not_inferred_from_scheduler'


def test_manifest_withdrawal_at_concrete_packet_fence_blocks_provider(worker_world, monkeypatch):
    w = worker_world
    monkeypatch.setattr('agent_market.reliability_research.clock', lambda: w.now)
    w.research = ReliabilityResearch(w.access, w.evaluation)
    w.control_api.app.include_router(router_for(w.access, w.evaluation, research=w.research))
    w.research_base = w.base+'/research'; approved = configured(w)
    w.eval_control['during_list'] = lambda: w.research.withdraw(w.ws['id'], approved['id'],
        {'revision': 1, 'authorized': True, 'notice': NOTICE}, w.actor)
    w.worker.activate(w.ws['id'], w.actor, 1); w.worker.tick()
    assert 'tools/call' not in w.eval_calls


def test_adaptive_priority_only_reorders_existing_budget_and_keeps_coverage_debt(research_world):
    w = research_world
    approved = configured(w, manifest(w, adaptive_priority=True))
    # Explicitly lower the existing plan budget; the research hook cannot raise it.
    assert post(w, '/evaluation/plans', plan(w, revision=1, corpus_id=approved['corpus_id'], per_host_budget=1)).status_code == 200
    trusted_fixture(w)
    first = post(w, '/evaluation/reserve', {'revision': 2, 'authorized': True, 'notice': EVAL_NOTICE}).json()['result']['jobs']
    assert len(first) == 1
    assert prepare(w, first[0]['id']).status_code == 200
    assert dispatch(w, first[0]['id']).status_code == 200
    w.now = first[0]['window_start']+601
    second = post(w, '/evaluation/reserve', {'revision': 2, 'authorized': True, 'notice': EVAL_NOTICE}).json()['result']
    assert len(second['jobs']) == 1 and second['deferred_cases'] == 3
    assert second['jobs'][0]['case_id'] != first[0]['case_id']
    assert len(w.research_calls) == 1


def test_no_external_or_production_fault_injection_and_fixed_seed_fixture_only():
    for fault in ('rate_limit', 'response_loss', 'partial', 'schema_drift'):
        a = fixture_fault({'fixture': 1}, seed=9, fault=fault, environment='isolated_fixture')
        assert a == fixture_fault({'fixture': 1}, seed=9, fault=fault, environment='isolated_fixture')
        with pytest.raises(WorkspaceInvalid): fixture_fault({}, seed=9, fault=fault, environment='approved_external')


def test_metadata_dual_clock_shadow_has_no_hidden_trace_or_intervention(research_world):
    w = research_world; configured(w)
    source = {'profile': 'p2-01-typed-evidence-profile-v1', 'current': True, 'evidence_current': True,
        'source_revision': 'bound-source-revision', 'nodes': [{'node_id': 'read'}],
        'events': [{'sequence': 1, 'event_type': 'dispatch', 'node_id': 'read', 'observed_at': w.now},
                   {'sequence': 2, 'event_type': 'closed_action', 'node_id': 'read', 'observed_at': w.now,
                    'closed_action_sequence': 1}]}
    calls = []
    w.research.lineage = SimpleNamespace(access=w.access, current_run=lambda *args: calls.append(args) or deepcopy(source))
    body = {'flow_id': 'fixture-flow', 'run_id': 'fixture-run', 'authorized': True, 'notice': NOTICE, 'stagnation_actions': 2}
    path = '/manifests/rrm_'+'8'*32+'/shadow'
    response = rp(w, path, body); assert response.status_code == 200, response.text
    result = response.json()['result']
    assert result['raw_event_count'] == 2 and result['closed_action_count'] == 1
    assert result['actual_interventions'] == result['business_calls'] == 0
    assert result['counterfactual_saved_steps'] is None and not result['would_stop']
    assert len(calls) == 2 and not w.calls
    source['evidence_current'] = False
    assert rp(w, path, body).status_code == 409
    source['evidence_current'] = True; source['events'].reverse()
    assert rp(w, path, body).status_code == 409
    assert rp(w, path, body | {'thoughts': 'private hidden reasoning'}).status_code == 400


def test_sessions_idor_csrf_exact_json_and_no_public_research(research_world):
    w = research_world; configured(w)
    assert w.control_api.get(w.research_base+'/status').status_code == 401
    assert rg(w, '/status?scope=all').status_code == 400
    assert rg(w, '/status', headers=w.headers['owner'] | {'Origin': 'https://outside.example'}).status_code == 403
    other = w.access.provision({'name': 'Other research scope', 'owner_id': 1}, w.actor)['id']
    path = w.research_base.replace(w.ws['id'], other)+'/manifests/rrm_'+'8'*32+'/analyze'
    assert w.control_api.get(path, headers=w.headers['owner']).status_code == 404
    for raw in ('{"authorized":true,"authorized":false}', '[]', 'x'*16385):
        assert w.control_api.post(w.research_base+'/manifests', content=raw, headers=w.headers['owner']).status_code == 400
    assert w.control_api.get('/api/reliability/research/status').status_code == 404
    assert not w.calls
