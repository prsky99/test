"""Reviewed-plan, one-call pilot and TEST_UNIT conformance in the owned fixture."""
import copy
import hashlib
import hmac
import time


def run_rnd_control_contracts(store, graph, workspace, staff, resource_ids, workflow_id, agreement):
    import httpx
    from tests.test_mcp_proxy import MockRemoteMcp
    from agent_market.capability_contracts import CONTRACTS
    from agent_market.capability_registry import Registry, digest
    from agent_market.reliability_admission import NOTICE
    from agent_market.reliability_routing import NOTICE as SHADOW_NOTICE
    from agent_market.workspace_access import WorkspaceDenied, _canonical, _hash
    from agent_market.workspace_app_factory import NOTICE as FACTORY_NOTICE
    from agent_market.workspace_sandbox_payments import PREPARE_NOTICE, EXECUTE_NOTICE
    from agent_market.workspace_protocol_conformance import NOTICE as PROTOCOL_NOTICE, WIRE_PROFILES
    if (getattr(store, 'backend', None) != 'postgresql' or getattr(store, 'workflow_key', None) != b'k'*32
            or graph.access.store is not store or type(graph.execution.proxy._http._transport) not in (httpx.MockTransport, MockRemoteMcp)
            or len(resource_ids) != 2 or any(store.resource(rid)['url'] != 'https://typed-'+str(i)+'.example/mcp' for i,rid in enumerate(resource_ids))):
        raise AssertionError('Only the parent-owned native fixture is accepted.')
    checks = {}; ws = workspace['id']; now = time.time()
    def require(value, label):
        if value is not True: raise AssertionError(label)
    review = graph.app_factory.prepare_intent(ws, {'purpose': 'Documentation about public research then documentation about references',
        'name': 'Native reviewed intent', 'resource_ids': resource_ids, 'from_utc': None, 'criteria': []}, staff)
    saved = graph.app_factory.commit(ws, {'review_id': review['review_id'], 'authorized': True, 'notice': FACTORY_NOTICE}, staff)
    base = graph.typed_flows.detail(ws, saved['id'], staff)
    definition = copy.deepcopy(base['definition']); definition['nodes'][1]['input']['query'] = 'Reviewed native change'
    proposal = graph.app_factory.prepare_plan(ws, {'name': 'New native revision draft', 'definition': definition,
        'base_flow_id': saved['id'], 'base_revision': saved['revision']}, staff)
    revised = graph.app_factory.commit(ws, {'review_id': proposal['review_id'], 'authorized': True, 'notice': FACTORY_NOTICE}, staff)
    require(revised['id'] != saved['id'] and graph.typed_flows.detail(ws, saved['id'], staff) == base, 'Native replan mutated its base graph.')
    checks['native_rnd_intent_and_reviewed_new_draft_preserve_original'] = True
    routing, admission = graph.reliability_routing, graph.single_admission
    previous = routing.evidence_source, admission.evidence_guard, admission.enabled, admission.environment
    sources = {}
    for rid in resource_ids:
        version = Registry(store).current(rid)
        sources[rid] = {'resource_id': rid, 'agent_version': version['id'], 'schema_hash': version['schema_hash'],
            'contract_id': 'docs.search.v1', 'contract_revision': CONTRACTS['docs.search.v1']['version'],
            'contract_hash': digest(CONTRACTS['docs.search.v1']), 'quality_status': 'assessed', 'source_fidelity': 'verified',
            'independent_qualified': True, 'latest_observed_at': now-1, 'expires_at': now+600, 'revoked': False,
            'logical_samples': 2, 'outcomes': {'succeeded': 2, 'failed': 0, 'unknown': 0}, 'latency_ms': {'p95': 10},
            'environment': 'isolated', 'qualified_operating_evidence': False}
    routing.evidence_source = lambda ws, rid, actor: copy.deepcopy(sources[rid])
    admission.evidence_guard = lambda db, ws, rid, actor: copy.deepcopy(sources[rid])
    admission.enabled, admission.environment = True, 'isolated'
    try:
        current = routing.status(ws, staff)['policy']
        shadow = routing.configure(ws, {'revision': current['revision'] if current else 0, 'mode': 'decision_shadow',
            'workflow_id': workflow_id, 'contract_id': 'docs.search.v1', 'resource_ids': resource_ids,
            'share_resource_ids': resource_ids, 'expires': now+600, 'enabled': True, 'authorized': True, 'notice': SHADOW_NOTICE}, staff)
        policy = admission.configure(ws, {'revision': 0, 'shadow_revision': shadow['revision'], 'enabled': True,
            'percent': 10, 'max_runs': 1, 'expires': now+300, 'authorized': True, 'notice': NOTICE}, staff)
        logical = None
        for i in range(10000):
            candidate = 'rld_'+format(i, '032x')
            sample = int(hmac.new(admission.key, _canonical([ws,_hash([ws,candidate]),policy['revision']]).encode('ascii'),hashlib.sha256).hexdigest()[:8],16)%100
            if sample < 10: logical = candidate; break
        require(logical is not None, 'Native deterministic pilot sample absent.')
        approved = admission.prepare(ws, {'revision': policy['revision'], 'logical_id': logical,
            'input': {'query': 'documentation', 'language': 'en', 'limit': 2}, 'name': 'Native one-call task',
            'authorized': True, 'notice': NOTICE}, staff)
        first = admission.execute(ws, approved['id'], {'authorized': True, 'notice': NOTICE}, staff)
        again = admission.execute(ws, approved['id'], {'authorized': True, 'notice': NOTICE}, staff)
        require(first['run']['status']=='succeeded' and again['replayed'] and first['run']['id']==again['run']['id']
                and first['replacement_calls']==0, 'Native pilot was not single-call and deduplicated.')
        checks['native_rnd_single_admission_reuses_private_dispatch_and_replay_zero_replacements'] = True
        with store.tx():
            store._execute('INSERT INTO reliability_admission_restore_blocks VALUES(%s)', (approved['id'],))
        require(admission.status(ws, staff)['admissions'][0]['run_id']==first['run']['id'], 'Native pilot lost retained history after quarantine.')
        checks['native_rnd_admission_restore_block_preserves_retained_run'] = True
    finally:
        routing.evidence_source, admission.evidence_guard, admission.enabled, admission.environment = previous
    payments = graph.sandbox_payments
    capture = payments.prepare(ws, {'action': 'capture', 'target_id': agreement['id'], 'units': 103,
        'revision': agreement['revision'], 'event_reference': 'sim_rnd_native_capture', 'authorized': True, 'notice': PREPARE_NOTICE}, staff)
    settled = payments.dispatch(ws, {'intent_id': capture['id'], 'authorized': True, 'notice': EXECUTE_NOTICE}, staff)['result']
    refund = payments.prepare(ws, {'action': 'refund', 'target_id': settled['id'], 'units': 31,
        'revision': settled['revision'], 'event_reference': 'sim_rnd_native_refund', 'authorized': True, 'notice': PREPARE_NOTICE}, staff)
    payments.dispatch(ws, {'intent_id': refund['id'], 'authorized': True, 'notice': EXECUTE_NOTICE}, staff)
    with store.tx(readonly=True):
        before = store._execute('SELECT COUNT(*) FROM workspace_agreement_events').fetchone()[0]
    command = {'profile_id': WIRE_PROFILES[0]['id'], 'capture_intent_id': capture['id'], 'refund_intent_id': refund['id'],
        'event_reference': 'conformance_native_protocol_review', 'authorized': True, 'notice': PROTOCOL_NOTICE}
    report = graph.protocol_conformance.run(ws, command, staff)
    replay = graph.protocol_conformance.run(ws, command, staff)
    with store.tx(readonly=True):
        after = store._execute('SELECT COUNT(*) FROM workspace_agreement_events').fetchone()[0]
    require(report['wire_checks']['passed'] and report['ledger']['refunded_units']==31 and report['ledger']['remaining_units']==72
            and replay['replayed'] and not report['actual_money'] and report['states']['payout']=='disabled'
            and after==before,
            'Native protocol conformance changed the ledger or asserted actual settlement.')
    checks['native_rnd_protocol_existing_ledger_partial_refund_and_report_only_dedupe'] = True
    with store.tx(): store._execute('INSERT INTO workspace_protocol_restore_blocks VALUES(%s)', (report['id'],))
    require(graph.protocol_conformance.report(ws,report['id'],staff)['states']['source_use']=='restore_blocked', 'Native protocol restore report was promoted.')
    checks['native_rnd_protocol_restore_never_revives_financial_authority'] = True
    return checks
