"""Circuit contracts only inside the parent's fixed native MockTransport fixture."""
from contextlib import ExitStack
from copy import deepcopy
import json
import secrets
import time
from unittest.mock import patch


def run_circuit_contracts(store, graph, workspace, staff, resource_id):
    import httpx
    from agent_market.capability_contracts import CONTRACTS
    from agent_market.capability_registry import Registry, digest
    from agent_market.concierge.proxy import McpProxy
    from agent_market.reliability_circuit import NOTICE, ReliabilityCircuit
    from agent_market.reliability_evaluation import NOTICE as EVAL_NOTICE
    from agent_market.reliability_evaluation_worker import McpReadEvaluator
    from agent_market.workspace_access import WorkspaceConflict
    from tests.test_mcp_proxy import MockRemoteMcp

    # Reject before the first database read. No DSN, key, endpoint or executable
    # is accepted from a caller; the parent owns this disposable database.
    if (getattr(store, 'backend', None) != 'postgresql' or getattr(store, 'workflow_key', None) != b'k'*32
            or getattr(getattr(graph, 'access', None), 'store', None) is not store):
        raise AssertionError('Only the parent-owned native fixture is accepted before database access.')
    evaluation = graph.reliability_evaluation
    circuit = getattr(graph, 'reliability_circuit', None)
    proxy = evaluation.runtime.proxy
    resource = store.resource(resource_id)
    if (type(circuit) is not ReliabilityCircuit or circuit.evaluation is not evaluation
            or circuit.access is not graph.access or type(proxy) is not McpProxy or proxy.store is not store
            or graph.execution.proxy is not proxy or not isinstance(getattr(proxy, '_http', None), httpx.Client)
            or type(proxy._http._transport) not in (httpx.MockTransport, MockRemoteMcp)
            or not resource or resource['kind'] != 'mcp' or resource['source'] != 'mcp-registry'
            or resource['url'] not in ('https://typed-0.example/mcp', 'https://typed-1.example/mcp')):
        raise AssertionError('Only the current parent graph with fixed synthetic MCP transport is accepted.')
    fixture_workspace = graph.access.provision({'name': 'Native circuit-only fixture', 'owner_id': staff.user_id}, staff)
    ws = fixture_workspace['id']
    # Earlier parent contracts use this same synthetic host. Keep the circuit
    # in its own evaluation window instead of weakening the shared host budget.
    now = (int(time.time()//600)+1)*600+1; checks = {}; calls = []; mode = ['error']
    spec = json.loads(resource['usage_full_tools'])
    version = Registry(store).current(resource_id)
    source = {'resource_id': resource_id, 'agent_version': version['id'], 'schema_hash': version['schema_hash'],
        'contract_id': 'docs.search.v1', 'contract_revision': CONTRACTS['docs.search.v1']['version'],
        'contract_hash': digest(CONTRACTS['docs.search.v1']), 'quality_status': 'assessed', 'source_fidelity': 'verified',
        'independent_qualified': True, 'latest_observed_at': now-1, 'expires_at': now+3500, 'revoked': False,
        'logical_samples': 2, 'outcomes': {'succeeded': 2, 'failed': 0, 'unknown': 0},
        'latency_ms': {'p95': 10}, 'environment': 'isolated', 'qualified_operating_evidence': False}

    def transport(request):
        if str(request.url) != resource['url']:
            raise AssertionError('Unexpected synthetic circuit destination.')
        body = json.loads(request.content)
        calls.append(body['method'])
        if body['method'] == 'server/discover':
            result = {'protocolVersion': '2026-07-28'}
        elif body['method'] == 'tools/list':
            result = {'tools': spec}
        elif body['method'] == 'tools/call':
            if mode[0] == 'error':
                return httpx.Response(200, json={'jsonrpc': '2.0', 'id': body['id'],
                    'error': {'code': -32603, 'message': 'Synthetic circuit failure'}})
            result = {'structuredContent': {'items': [], 'partial': False}}
        else:
            raise AssertionError('Unexpected synthetic circuit RPC.')
        return httpx.Response(200, json={'jsonrpc': '2.0', 'id': body['id'], 'result': result})

    def require(value, label):
        if value is not True:
            raise AssertionError(label)

    def approval(revision, **fields):
        return {'revision': revision, 'authorized': True, 'notice': NOTICE, **fields}

    original = (evaluation.read_evaluator, evaluation.evaluator_authorizer, proxy._http,
                circuit.enabled, circuit.evidence_guard)
    scope = ExitStack()
    for target in ('agent_market.reliability_evaluation.clock', 'agent_market.reliability_evaluation_worker.clock',
                   'agent_market.reliability_circuit.clock'):
        scope.enter_context(patch(target, lambda: now))
    client = httpx.Client(transport=httpx.MockTransport(transport))
    circuit.enabled = True
    circuit.evidence_guard = lambda db, identity, rid, actor: deepcopy(source)
    proxy._http = client
    adapter = McpReadEvaluator(evaluation, enabled=True)
    evaluation.read_evaluator, evaluation.evaluator_authorizer = adapter, adapter.authorizer
    configuration = approval(0, resource_id=resource_id, contract_id='docs.search.v1', environment='isolated',
        enabled=True, failure_count=1, unknown_count=1, sample_window_seconds=1200,
        sample_max_age_seconds=900, open_seconds=1, probe_max_age_seconds=300, expires=now+3500)
    eval_body = {'authorized': True, 'notice': EVAL_NOTICE}

    def reserve():
        reserved = evaluation.reserve(ws, {'revision': 1, **eval_body}, staff)
        require(len(reserved['jobs']) == 1 and reserved['deferred_cases'] == 0,
                'Native circuit must reserve one separately approved evaluation job in its own host window.')
        return reserved['jobs'][0]['id']

    try:
        require(circuit.get_agent_projection(ws, resource_id, staff) == source,
                'Unconfigured native composer altered base evidence.')
        first = circuit.configure(ws, configuration, staff)
        try:
            circuit.configure(ws, configuration, staff)
        except WorkspaceConflict:
            pass
        else:
            raise AssertionError('Native circuit accepted stale configuration CAS.')
        corpus = evaluation.register_corpus(ws, {'corpus_id': 'rcp_'+secrets.token_hex(16), 'version': 'circuit-native-v1',
            'contract_id': 'docs.search.v1', 'cases': [{'case_id': 'circuit-probe', 'kind': 'repeatability',
            'split': 'holdout', 'input': {'query': 'Synthetic approved documentation', 'language': 'en', 'limit': 2}}],
            'training_hashes': [], **eval_body, 'data_attestation': 'synthetic_or_licensed_no_personal_data'}, staff)
        corpus_id = evaluation.status(ws, staff)['plan']
        require(corpus_id is None, 'Fresh circuit-only native workspace unexpectedly had an evaluation plan.')
        evaluation.configure_plan(ws, {'revision': 0, 'corpus_id': corpus['id'], 'resource_ids': [resource_id],
            'interval_seconds': 600, 'jitter_seconds': 0, 'per_host_budget': 1, 'expires': now+3500, **eval_body}, staff)
        evaluation.set_control(ws, {'revision': 0, 'enabled': True, **eval_body}, staff)
        ref = reserve(); evaluation.prepare(ws, ref, eval_body, staff); evaluation.dispatch(ws, ref, eval_body, staff)
        tripped = circuit.ingest(ws, resource_id, approval(first['revision'], source_ref=ref), staff)
        require(tripped['state'] == 'open', 'Native circuit failed to ingest verified failure and open.')
        sticky = circuit.configure(ws, dict(configuration, revision=tripped['revision']), staff)
        require(sticky['state'] == 'open', 'Native reconfiguration cleared open state.')
        checks['native_circuit_explicit_configuration_cas_and_sticky_open'] = True
        now = (int(now//600)+1)*600+1
        ref = reserve()
        bound = circuit.bind_probe(ws, resource_id, approval(sticky['revision'], job_id=ref), staff)
        require(bound['state'] == 'half_open' and calls.count('tools/call') == 1,
                'Native probe binding dispatched work or allowed business calls.')
        require(circuit.get_agent_projection(ws, resource_id, staff)['circuit_state'] == 'half_open',
                'Native half-open circuit was not excluded.')
        mode[0] = 'ok'
        evaluation.prepare(ws, ref, eval_body, staff); evaluation.dispatch(ws, ref, eval_body, staff)
        closed = circuit.refresh_probe(ws, resource_id, approval(bound['revision']), staff)
        require(closed['state'] == 'closed' and closed['probe_outcome'] == 'completed' and calls.count('tools/call') == 2,
                'Native circuit did not consume exactly its verified approved probe.')
        require(evaluation.dispatch(ws, ref, eval_body, staff)['state'] == 'completed' and calls.count('tools/call') == 2,
                'Native completed probe was replayed.')
        checks['native_circuit_existing_signed_mcp_probe_proof_closes_once'] = True
        with graph.access._tx(staff, write=True) as (db, _):
            before = db.execute('SELECT * FROM reliability_circuit_states WHERE workspace_id=? ORDER BY resource_id LIMIT 51',
                                (ws,)).fetchone()
            db.execute('INSERT INTO reliability_circuit_restore_blocks VALUES(?) ON CONFLICT(authority_id) DO NOTHING',
                       ('circuit:'+ws+':'+str(resource_id)+':'+str(closed['generation']),))
            after = db.execute('SELECT * FROM reliability_circuit_states WHERE workspace_id=? ORDER BY resource_id LIMIT 51',
                               (ws,)).fetchone()
            require(tuple(before) == tuple(after), 'Native circuit restore rewrote signed history.')
        require(circuit.get_agent_projection(ws, resource_id, staff)['circuit_state'] == 'quarantined',
                'Native restore marker failed to exclude an old circuit.')
        renewed = circuit.configure(ws, dict(configuration, revision=closed['revision'], expires=now+1200), staff)
        require(renewed['state'] == 'open' and renewed['generation'] > closed['generation'],
                'Native restore reapproval resurrected a healthy circuit without a new probe.')
        checks['native_circuit_restore_tombstone_and_reapproval_require_fresh_probe'] = True
    finally:
        (evaluation.read_evaluator, evaluation.evaluator_authorizer, proxy._http,
         circuit.enabled, circuit.evidence_guard) = original
        client.close()
        scope.close()
    return checks
