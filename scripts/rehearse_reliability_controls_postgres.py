"""Bounded reliability controls inside the parent's fixed native Unix PG fixture.

This helper accepts an existing isolated store and mock graph only. It does not
accept a DSN/address, create a cluster, start a server or configure a provider.
"""
import hashlib
import hmac
import secrets
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient


def run_reliability_control_contracts(store, graph, ws, staff, resource_id, session_token):
    from agent_market.gateway import admin_auth
    from agent_market.reliability_control_service import router_for
    from agent_market.reliability_controls_restore import authority_id
    from agent_market.reliability_evaluation import NOTICE as EVAL_NOTICE, ReliabilityEvaluation
    from agent_market.reliability_routing import NOTICE as ROUTE_NOTICE, ReliabilityRouting
    from agent_market.reliability_trust import ReliabilityTrust
    from agent_market.workspace_access import PROFILE as ACCESS_PROFILE, _rows
    from agent_market.workflows import runtime_for

    if (store.backend != 'postgresql' or store.workflow_key != b'k'*32 or graph.access.store is not store
            or graph.execution.access is not graph.access
            or admin_auth.session_reference(session_token) != staff.session_ref):
        raise AssertionError('Only the owned synthetic native application fixture is accepted.')
    resource = store.resource(resource_id)
    if (not resource or resource['kind'] != 'mcp' or resource['source'] != 'mcp-registry'
            or resource['url'] not in ('https://typed-0.example/mcp', 'https://typed-1.example/mcp')):
        raise AssertionError('Only the fixed native documentation mock is accepted.')
    workspace_id = ws['id'] if isinstance(ws, dict) else ws
    runtime = getattr(graph, 'runtime', None) or runtime_for(store, None)
    expected_access_key = hmac.new(runtime.key, ACCESS_PROFILE.encode('ascii'), hashlib.sha256).digest()
    if (runtime.store is not store or not hmac.compare_digest(expected_access_key, graph.access.key)
            or runtime.proxy is not graph.execution.proxy):
        raise AssertionError('The current isolated native runtime and execution proxy are required.')
    checks = {}

    def signed_snapshot(db):
        controls = _rows(db, 'SELECT * FROM reliability_eval_controls WHERE workspace_id=?', (workspace_id,))
        plans = _rows(db, 'SELECT * FROM reliability_eval_plans WHERE workspace_id=?', (workspace_id,))
        policies = _rows(db, 'SELECT * FROM reliability_route_policies WHERE workspace_id=?', (workspace_id,))
        jobs = _rows(db, 'SELECT id FROM reliability_eval_jobs WHERE workspace_id=? ORDER BY window_start DESC,id LIMIT 501', (workspace_id,))
        job_rows = []
        for item in jobs:
            job_rows.extend(_rows(db, 'SELECT * FROM reliability_eval_jobs WHERE id=? AND workspace_id=?', (item['id'], workspace_id)))
        return {'control': [(row['payload'], row['signature']) for row in controls],
                'plan': [(row['payload'], row['signature']) for row in plans],
                'policy': [(row['payload'], row['signature']) for row in policies],
                'jobs': {row['id']: (row['payload'], row['signature']) for row in job_rows}}

    def require(value, label):
        if value is not True:
            raise AssertionError(label)

    evaluation = ReliabilityEvaluation(graph.access, runtime)
    evidence_source = getattr(getattr(graph, 'reliability_evidence', None), 'get_agent_projection', None)
    trust = ReliabilityTrust(graph.access, evidence_source=evidence_source)
    routing = ReliabilityRouting(graph.access, runtime, evidence_source=evidence_source)
    app = FastAPI(); app.include_router(router_for(graph.access, runtime, evaluation=evaluation, trust=trust, routing=routing))
    base = '/admin/api/workflow-workspaces/'+workspace_id+'/reliability'
    headers = {'Authorization': 'Bearer '+session_token, 'X-Dashboard': '1'}
    sent = {'count': 0}; previous_execute = runtime.proxy.execute

    def forbidden_provider_send(*args, **kwargs):
        sent['count'] += 1
        raise AssertionError('Evaluation, trust preview and decision shadow must not send a provider call.')

    runtime.proxy.execute = forbidden_provider_send
    try:
        with TestClient(app, base_url='https://native-reliability-controls.example', raise_server_exceptions=False) as api:
            def post(path, body, expected=200):
                response = api.post(base+path, headers=headers, json=body)
                require(response.status_code == expected, 'Native reliability control '+path+': '+response.text)
                return response.json().get('result')

            def read(path):
                response = api.get(base+path, headers=headers)
                require(response.status_code == 200, 'Native reliability read '+path+': '+response.text)
                return response

            options = read('/evaluation/options').json()['result']
            require(not options['evaluator_configured'] and not options['automatic_worker_enabled'],
                    'The native evaluation fixture must start without a trusted adapter or worker.')
            old = read('/evaluation/status').json()['result']
            corpus_id = 'rcp_'+secrets.token_hex(16)
            corpus = post('/evaluation/corpora', {'corpus_id': corpus_id, 'version': 'native-isolated-corpus-v1',
                'contract_id': 'docs.search.v1', 'cases': [{'case_id': 'holdout-1', 'kind': 'repeatability', 'split': 'holdout',
                    'input': {'query': 'Synthetic public documentation', 'language': 'en', 'limit': 2}}],
                'training_hashes': [], 'authorized': True, 'notice': EVAL_NOTICE,
                'data_attestation': 'synthetic_or_licensed_no_personal_data'})
            require(corpus['id'] == corpus_id, 'Native immutable corpus was not retained.')
            plan_body = {'revision': old['plan']['revision'] if old['plan'] else 0,
                'corpus_id': corpus_id, 'resource_ids': [resource_id], 'interval_seconds': 600,
                'jitter_seconds': 0, 'per_host_budget': 1, 'expires': time.time()+1200,
                'authorized': True, 'notice': EVAL_NOTICE}
            plan = post('/evaluation/plans', plan_body)
            control = post('/evaluation/control', {'revision': old['control']['revision'], 'enabled': True,
                'authorized': True, 'notice': EVAL_NOTICE})
            reserved = post('/evaluation/reserve', {'revision': plan['revision'], 'authorized': True, 'notice': EVAL_NOTICE})
            require(len(reserved['jobs']) == 1, 'Native bounded plan did not reserve its one eligible case.')
            job = reserved['jobs'][0]
            again = post('/evaluation/reserve', {'revision': plan['revision'], 'authorized': True, 'notice': EVAL_NOTICE})
            require(again['jobs'][0]['id'] == job['id'], 'Native reservation replay changed its logical job.')
            prepared = post('/evaluation/jobs/'+job['id']+'/prepare', {'authorized': True, 'notice': EVAL_NOTICE})
            require(prepared['state'] == 'prepared', 'Native job preparation was not durable.')
            post('/evaluation/jobs/'+job['id']+'/dispatch', {'authorized': True, 'notice': EVAL_NOTICE}, expected=409)
            coverage = read('/evaluation/status').json()['result']['coverage']
            require(coverage['scheduled_cases'] == 1 and coverage['debt_cases'] >= 1
                    and coverage['latest_actual_observed_at'] is None and sent['count'] == 0,
                    'Unconfigured evaluation fabricated a fresh observation or attempted a provider call.')
            checks['native_reliability_controls_corpus_plan_control_budget_dedupe_preparation_no_adapter_dispatch'] = True

            from agent_market.reliability_evaluation_worker import McpReadEvaluator, EvaluationWorker
            adapter = McpReadEvaluator(evaluation, enabled=True)
            evaluation.read_evaluator, evaluation.evaluator_authorizer = adapter, adapter.authorizer
            worker = EvaluationWorker(evaluation, enabled=True)
            evaluation.worker = worker
            evaluation_calls = []
            def controlled_evaluation(*args, **kwargs):
                evaluation_calls.append(args[0])
                return previous_execute(*args, **kwargs)
            runtime.proxy.execute = controlled_evaluation
            try:
                worker.activate(workspace_id, staff, plan['revision'])
                require(worker.tick()['attempted_jobs'] == 1, 'Native worker did not claim its prepared case.')
                observed = read('/evaluation/status').json()['result']
                with store.tx() as db:
                    technical_reference = evaluation._job(db, workspace_id, job['id']).get('evidence_ref')
                require(observed['jobs'][0]['state'] == 'completed'
                        and type(technical_reference) is str and technical_reference.startswith('reo_')
                        and observed['quality_status'] == 'not_inferred_from_scheduler',
                        'Native technical observation became missing or inferred independent quality.')
                duplicate = post('/evaluation/jobs/'+job['id']+'/dispatch', {'authorized': True, 'notice': EVAL_NOTICE})
                require(duplicate['state'] == 'completed' and worker.tick()['attempted_jobs'] == 0
                        and evaluation_calls == [resource_id], 'Native job replay dispatched twice.')
                checks['native_evaluation_concrete_mcp_worker_once_and_unassessed_quality'] = True
            finally:
                require(worker.close(), 'Native worker did not close.')
                runtime.proxy.execute = forbidden_provider_send

            preview = read('/trust/'+str(resource_id))
            result = preview.json()['result']
            require(result['state'] == 'evidence_pending' and not result['qualified_operating_evidence']
                    and not result['public_activation'] and result['provider_calls'] == 0,
                    'Native unconfigured evidence unexpectedly issued a positive or operating badge.')
            cached = api.get(base+'/trust/'+str(resource_id), headers=headers | {'If-None-Match': preview.headers['etag']})
            require(cached.status_code == 304 and cached.headers['cache-control'] == 'no-store',
                    'Native current conditional trust projection was not revalidated.')
            badge = read('/trust/'+str(resource_id)+'/badge.svg')
            require(badge.headers['etag'] != preview.headers['etag'] and '<script' not in badge.text
                    and '<foreignObject' not in badge.text and 'href=' not in badge.text,
                    'Native SVG representation binding or fixed content boundary changed.')
            require(session_token not in preview.text and resource['url'] not in preview.text, 'Native trust DTO exposed authority or deployment data.')
            checks['native_reliability_controls_neutral_trust_conditional_read_and_safe_svg'] = True

            workflow_id = store.create_workflow({'name': 'Native private routing preview', 'is_template': 0,
                'nodes': [{'id': 'docs', 'name': 'Documentation read', 'type': 'agent', 'kind': 'mcp',
                           'resource_id': resource_id, 'data': {'tool': 'search_docs',
                           'input': {'query': 'Synthetic public documentation', 'language': 'en', 'limit': 2}}}], 'edges': []})
            prior_policy = read('/routing/status').json()['result']['policy']
            policy = post('/routing/configure', {'revision': prior_policy['revision'] if prior_policy else 0,
                'mode': 'decision_shadow', 'workflow_id': workflow_id, 'contract_id': 'docs.search.v1',
                'resource_ids': [resource_id], 'share_resource_ids': [resource_id], 'expires': time.time()+1200,
                'enabled': True, 'authorized': True, 'notice': ROUTE_NOTICE})
            decision = post('/routing/decide', {'revision': policy['revision'], 'logical_id': 'rld_'+secrets.token_hex(16),
                'authorized': True, 'notice': ROUTE_NOTICE})
            require(decision['business_calls'] == decision['replacement_calls'] == 0
                    and not decision['execution_authority'] and decision['future_business_call_limit'] == 1
                    and decision['future_replacements_limit'] == 0, 'Native decision shadow enlarged its dispatch budget.')
            replay = post('/routing/replay', {'revision': policy['revision'], 'authorized': True, 'notice': ROUTE_NOTICE})
            require(replay['replayed_decisions'] == replay['deterministic_matches'] == 1
                    and not replay['paired_corpus_verified'] and not replay['causal_improvement_established']
                    and sent['count'] == 0, 'Native historical replay invoked a provider or inferred causal quality.')
            checks['native_reliability_controls_rule_shadow_and_historical_replay_zero_business_dispatch'] = True

            # Seed only the durable uncertain boundary to verify restore behavior;
            # this fixture is explicitly not evidence of a provider network send.
            with store.tx() as db:
                value = evaluation._job(db, workspace_id, job['id'])
                value.update(state='dispatched', dispatched_at=time.time())
                evaluation._put(db, 'job', value)
                originals = signed_snapshot(db)
                ids = (authority_id('eval_control', workspace_id, control['revision']),
                       authority_id('eval_plan', workspace_id, plan['revision']), authority_id('eval_job', job['id']),
                       authority_id('routing_policy', workspace_id, policy['revision']))
                for identity in ids:
                    store._execute('INSERT INTO reliability_controls_restore_blocks VALUES(%s) ON CONFLICT(authority_id) DO NOTHING', (identity,))
            quarantined = read('/evaluation/status').json()['result']
            require(not quarantined['control']['enabled'] and quarantined['plan']['restore_quarantined']
                    and quarantined['jobs'][0]['state'] == 'unknown' and quarantined['jobs'][0]['restore_quarantined'],
                    'Native restored authority or uncertain job escaped quarantine.')
            post('/evaluation/jobs/'+job['id']+'/dispatch', {'authorized': True, 'notice': EVAL_NOTICE}, expected=409)
            post('/routing/decide', {'revision': policy['revision'], 'logical_id': 'rld_'+secrets.token_hex(16),
                'authorized': True, 'notice': ROUTE_NOTICE}, expected=409)
            with store.tx() as db:
                require(signed_snapshot(db) == originals, 'Native restore guard rewrote signed original rows.')
            require(sent['count'] == 0, 'A native control/read/shadow/restore path attempted provider execution.')
            checks['native_reliability_controls_restore_tombstones_unknown_and_original_signature_preservation'] = True
    finally:
        runtime.proxy.execute = previous_execute
    return checks
