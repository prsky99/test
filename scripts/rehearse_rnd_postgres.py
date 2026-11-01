"""Research contracts in the parent's owned native application mock fixture.

No cluster operation, DSN, server address or operating credential is accepted.
"""
import secrets
import time
import json
from contextlib import ExitStack
from unittest.mock import patch


def run_research_contracts(store, graph, ws, staff, resource_id):
    import httpx
    from agent_market.concierge.proxy import McpProxy
    from agent_market.reliability_evaluation import NOTICE as EVAL_NOTICE
    from agent_market.reliability_evaluation_worker import EvaluationWorker, McpReadEvaluator
    from agent_market.reliability_research import NOTICE, ReliabilityResearch
    from agent_market.workspace_access import WorkspaceConflict
    from tests.test_mcp_proxy import MockRemoteMcp

    if (getattr(store, 'backend', None) != 'postgresql' or getattr(store, 'workflow_key', None) != b'k'*32
            or getattr(getattr(graph, 'access', None), 'store', None) is not store):
        raise AssertionError('Only the parent-owned native fixture is accepted before any database read.')
    evaluation = graph.reliability_evaluation
    proxy = evaluation.runtime.proxy
    resource = store.resource(resource_id)
    if (getattr(store, 'backend', None) != 'postgresql' or store.workflow_key != b'k'*32
            or graph.access.store is not store or evaluation.access is not graph.access
            or evaluation.runtime.store is not store or graph.execution.proxy is not proxy
            or type(proxy) is not McpProxy or proxy.store is not store
            or not isinstance(getattr(proxy, '_http', None), httpx.Client)
            or type(proxy._http._transport) not in (httpx.MockTransport, MockRemoteMcp)
            or not resource or resource['kind'] != 'mcp' or resource['source'] != 'mcp-registry'
            or resource['url'] not in ('https://typed-0.example/mcp', 'https://typed-1.example/mcp')):
        raise AssertionError('Only the parent-owned native store and fixed synthetic MCP transport are accepted.')
    workspace_id = ws['id'] if isinstance(ws, dict) else ws
    research = getattr(graph, 'reliability_research', None)
    if type(research) is not ReliabilityResearch or research.evaluation is not evaluation or research.access is not graph.access:
        raise AssertionError('Use the current graph-bound research core, never a second authority graph.')
    original = evaluation.read_evaluator, evaluation.evaluator_authorizer, evaluation.worker
    worker = EvaluationWorker(evaluation, enabled=True, max_jobs_per_tick=8)
    checks = {}

    def require(value, label):
        if value is not True:
            raise AssertionError(label)

    # Keep both explicit ticks in one admitted window. This process owns only
    # the isolated fixture; the three module-local clocks are restored below.
    now = time.time()
    clock_scope = ExitStack()
    for target in ('agent_market.reliability_evaluation.clock',
                   'agent_market.reliability_evaluation_worker.clock',
                   'agent_market.reliability_research.clock'):
        clock_scope.enter_context(patch(target, lambda: now))
    body = {'manifest_id': 'rrm_'+secrets.token_hex(16), 'version': 'native-paired-v1',
        'contract_id': 'docs.search.v1', 'cases': [{'case_id': 'native-docs',
            'input': {'query': 'Approved synthetic documentation', 'language': 'en', 'limit': 2},
            # Intentionally unmatched approved fixture goal: two failed goals
            # must not become a metamorphic success merely by being equal.
            'expected_items': ['0'*64]}], 'k': 2, 'mutators': ['outer-whitespace-v1'], 'seed': 19,
        'reference_time': now, 'timezone': 'UTC', 'locale': 'en-US', 'dataset_version': 'native-fixture-v1',
        'oracle_version': 'exact-approved-item-goal-v1', 'analysis': {'version': 'native-analysis-v1',
            'minimum_pairs': 2, 'grouping': 'resource-version-host-window-case-trials',
            'unknown_policy': 'retain_in_admitted_denominator',
            'confidence': 'conservative-wilson95-and-cluster-count'},
        'expires': now+1200, 'adaptive_priority': True, 'authorized': True, 'notice': NOTICE,
        'semantic_attestation': 'reviewed_search_whitespace_preserves_task',
        'data_attestation': 'synthetic_or_licensed_no_personal_data'}
    try:
        approved = research.register_manifest(workspace_id, body, staff)
        require(approved['planned_episodes'] == 4 and approved['provider_calls'] == 0,
                'Native research manifest did not reuse its bounded existing corpus.')
        require(research.register_manifest(workspace_id, body, staff)['replayed'],
                'Native immutable manifest replay changed the approved definition.')
        current = evaluation.status(workspace_id, staff)
        plan = evaluation.configure_plan(workspace_id, {'revision': current['plan']['revision'] if current['plan'] else 0,
            'corpus_id': approved['corpus_id'], 'resource_ids': [resource_id], 'interval_seconds': 600,
            'jitter_seconds': 0, 'per_host_budget': 10, 'expires': now+1200,
            'authorized': True, 'notice': EVAL_NOTICE}, staff)
        evaluation.set_control(workspace_id, {'revision': current['control']['revision'], 'enabled': True,
            'authorized': True, 'notice': EVAL_NOTICE}, staff)
        pending = research.analyze(workspace_id, approved['id'], staff)
        require(pending['scheduled_episodes'] == 0 and pending['expected_episodes'] >= 4
                and pending['independent_quality'] == 'unassessed',
                'Native research fabricated observations before evaluation.')
        checks['native_rnd_research_manifest_existing_corpus_immutable_and_missing_coverage'] = True
        adapter = McpReadEvaluator(evaluation, enabled=True)
        evaluation.read_evaluator, evaluation.evaluator_authorizer, evaluation.worker = adapter, adapter.authorizer, worker
        worker.activate(workspace_id, staff, plan['revision'])
        attempted = worker.tick()['attempted_jobs']
        second_attempted = worker.tick()['attempted_jobs']
        if attempted != 4 or second_attempted != 0:
            current_state = evaluation.status(workspace_id, staff)
            current_jobs = [job for job in current_state['jobs'] if job['plan_revision'] == plan['revision']]
            previous_jobs = [job for job in current_state['jobs'] if job['plan_revision'] != plan['revision']]
            diagnostic = {'expected_unique_manifest_episodes': 4, 'plan_revision': plan['revision'],
                'attempted_first_tick': attempted, 'attempted_second_tick': second_attempted,
                'current_corpus_hash_matches_manifest': plan['corpus_hash'] == approved['corpus_hash'],
                'current_jobs': [{key: job[key] for key in ('case_id', 'state', 'plan_revision', 'restore_quarantined')}
                                 for job in current_jobs[:10]],
                'previous_jobs': [{key: job[key] for key in ('state', 'plan_revision', 'restore_quarantined')}
                                  for job in previous_jobs[:10]],
                'coverage_expected': current_state['coverage']['expected_cases'],
                'coverage_scheduled': current_state['coverage']['scheduled_cases']}
            raise AssertionError('Native research repeated or missed its four current manifest episodes: '
                                 + json.dumps(diagnostic, sort_keys=True, separators=(',', ':')))
        observed = research.analyze(workspace_id, approved['id'], staff)
        require(observed['paired']['admitted_pairs'] == observed['paired']['both_failed'] == 2
                and observed['paired']['both_goal_pass'] == 0
                and all(c['all_k_pass'] == 0 for c in observed['cells'])
                and observed['promotion_status'] == 'pending_paired_intervention_evidence'
                and not observed['operating_qualification'],
                'Native paired oracle promoted both-failed, technical or counterfactual evidence.')
        checks['native_rnd_research_concrete_worker_goal_oracle_pairs_no_quality_promotion'] = True
        withdrawn = research.withdraw(workspace_id, approved['id'],
            {'revision': 1, 'authorized': True, 'notice': NOTICE}, staff)
        require(withdrawn['withdrawn'] and withdrawn['revision'] == 2,
                'Native research withdrawal did not retain a new signed revision.')
        try:
            research.analyze(workspace_id, approved['id'], staff)
        except WorkspaceConflict:
            pass
        else:
            raise AssertionError('A withdrawn native research manifest remained assessable.')
        checks['native_rnd_research_manifest_withdrawal_current_scope'] = True
        # Native fixture-only seeding of a permanent restore tombstone. The
        # original signed manifest is never rewritten or granted fresh consent.
        fresh = dict(body, manifest_id='rrm_'+secrets.token_hex(16), version='native-restored-v1')
        fresh['reference_time'] = now
        restored = research.register_manifest(workspace_id, fresh, staff)
        with store.tx():
            before = store._execute('SELECT payload,signature FROM reliability_research_manifests WHERE id=%s',
                                    (restored['id'],)).fetchone()
            store._execute('INSERT INTO reliability_research_restore_blocks VALUES(%s)', (restored['id'],))
            after = store._execute('SELECT payload,signature FROM reliability_research_manifests WHERE id=%s',
                                   (restored['id'],)).fetchone()
            require(tuple(before) == tuple(after), 'Native research restore rewrote signed history.')
        state = research.status(workspace_id, staff)
        require(any(m['id'] == restored['id'] and m['restore_quarantined'] for m in state['manifests']),
                'Native restored research authority was not permanently blocked.')
        try:
            research.analyze(workspace_id, restored['id'], staff)
        except WorkspaceConflict:
            pass
        else:
            raise AssertionError('Native restore tombstone did not deny research use.')
        checks['native_rnd_research_restore_tombstone_preserves_original_signature'] = True
    finally:
        try:
            require(worker.close(), 'Native research worker failed to close.')
        finally:
            evaluation.read_evaluator, evaluation.evaluator_authorizer, evaluation.worker = original
            clock_scope.close()
    return checks
