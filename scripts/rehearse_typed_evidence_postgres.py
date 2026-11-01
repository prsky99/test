"""Typed lineage contracts in the parent's owned Unix PostgreSQL fixture only.

No DSN/address, server startup, live provider or operating database is accepted.
The parent application harness owns the isolated transport and fixed MCP mocks.
"""
import base64
import secrets
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient


def run_typed_evidence_contracts(store, graph, ws, staff, resource_ids, *, session_token=None):
    from agent_market.gateway import admin_auth
    from agent_market.concierge.proxy import McpProxy
    from agent_market.private_artifact_keys import ArtifactCipher, ArtifactKeys
    from agent_market.workspace_reliability import ERASE_NOTICE, NOTICE as REL_NOTICE, RETENTION_NOTICE, ReliabilityEvidence
    from agent_market.workspace_typed_evidence import NOTICE, PROFILE, WorkspaceTypedEvidence
    from agent_market.workspace_typed_evidence_service import router_for
    from agent_market.workspace_typed_flows import NOTICE as RUN_NOTICE
    from tests.test_mcp_proxy import MockRemoteMcp

    if (store.backend != 'postgresql' or store.workflow_key != b'k'*32 or graph.access.store is not store
            or graph.execution.access is not graph.access or graph.typed_flows.access is not graph.access
            or not isinstance(graph.execution.proxy, McpProxy) or graph.execution.proxy.store is not store
            or type(getattr(graph.execution.proxy._http, '_transport', None)) is not MockRemoteMcp
            or type(resource_ids) not in (list, tuple) or len(resource_ids) < 2
            or type(session_token) is not str or admin_auth.session_reference(session_token) != staff.session_ref):
        raise AssertionError('Only the owned synthetic native application fixture is accepted.')
    for rid in resource_ids[:2]:
        resource = store.resource(rid)
        if (not resource or resource['kind'] != 'mcp' or resource['source'] != 'mcp-registry'
                or resource['url'] not in ('https://typed-0.example/mcp', 'https://typed-1.example/mcp')):
            raise AssertionError('Only the fixed native documentation mocks are accepted.')
    workspace = ws['id'] if isinstance(ws, dict) else ws
    checks = {}
    def require(value, label):
        if value is not True: raise AssertionError(label)
    def identity(prefix): return prefix + '_' + secrets.token_hex(16)
    def command(**fields): return {'command_id': identity('rec'), 'authorized': True, 'notice': REL_NOTICE, **fields}

    # Reuse the parent's current synthetic session without changing user
    # revisions or invalidating purpose consents from earlier contracts.
    raw, actor = session_token, staff
    keys = ArtifactKeys({'profile': 'private-artifact-keys-v1', 'active_signing': 'typed-native', 'active_encryption': 'typed-native',
        'allow_legacy': True, 'keys': [{'id': 'typed-native', 'key': base64.b64encode(b'T'*32).decode(),
                                       'verify_until': time.time()+3600, 'revoked': False}]})
    plane = ReliabilityEvidence(graph.access, graph.execution, cipher=ArtifactCipher('bounded-reliability-evidence-v1:sources', keys))
    core = WorkspaceTypedEvidence(plane, graph.typed_flows)
    definition = {'nodes': [
        {'id': 'source', 'resource_id': resource_ids[0], 'contract_id': 'docs.search.v1',
         'input': {'query': 'Native distinct source request', 'language': 'en', 'limit': 2}, 'bindings': {}, 'after': [], 'when': None},
        {'id': 'followup', 'resource_id': resource_ids[1], 'contract_id': 'docs.search.v1',
         'input': {'language': 'en', 'limit': 2}, 'bindings': {'query': {'node_id': 'source', 'path': ['items', 0, 'title']}},
         'after': ['source'], 'when': {'node_id': 'source', 'path': ['partial'], 'equals': False}}]}
    flow = graph.typed_flows.save(workspace, {'flow_id': None, 'revision': 0, 'name': 'Native typed evidence lineage', 'definition': definition}, actor)
    def save(kind, spec):
        return plane.save_object(workspace, command(object_id=identity('reo'), kind=kind, revision=0, spec=spec), actor)
    plan = save('plan', {'dataset_version': 'native-typed-corpus-v1', 'dataset_hash': '1'*64,
        'rubric_version': 'native-typed-rubric-v1', 'rubric_hash': '2'*64, 'minimum_samples': 2,
        'window_seconds': 3600, 'confidence': 'wilson-95-v1', 'environment': 'isolated', 'evaluator_version': 'native-typed-independent-v1'})
    case = save('case', {'plan_id': plan['id'], 'plan_revision': 1, 'case_version': 'native-typed-baseline-v1', 'case_hash': '3'*64, 'category': 'baseline'})
    bindings = []; cohorts = []
    for node in definition['nodes']:
        cohort = save('cohort', {'plan_id': plan['id'], 'plan_revision': 1, 'case_ids': [case['id']],
            'resource_id': node['resource_id'], 'contract_id': node['contract_id'], 'purpose': 'independent-read-evaluation'})
        consent = plane.authorize_cohort(workspace, command(consent_id=identity('ren'), cohort_id=cohort['id'],
            cohort_revision=1, retention_seconds=1800, notice=RETENTION_NOTICE), actor)
        cohorts.append(cohort['id'])
        bindings.append({'node_id': node['id'], 'consent_id': consent['id'], 'case_id': case['id'],
                         'source_id': identity('res'), 'observation_id': identity('reb')})
    prepared = graph.typed_flows.prepare(workspace, flow['id'], {'revision': flow['revision']}, actor)
    executed = graph.typed_flows.execute(workspace, flow['id'], {'ticket_id': prepared['ticket_id'], 'authorized': True, 'notice': RUN_NOTICE}, actor)
    require(executed['run']['status'] == 'succeeded', 'Native original typed execution must succeed.')
    run_id = executed['run']['id']
    app = FastAPI(); app.include_router(router_for(core))
    base = '/admin/api/workflow-workspaces/' + workspace + '/reliability/typed'
    headers = {'Authorization': 'Bearer ' + raw, 'X-Dashboard': '1'}
    with TestClient(app, base_url='https://native-typed-evidence.example', raise_server_exceptions=False) as api:
        require(api.get(base + '/options').status_code == 401, 'Native typed lineage requires a named session.')
        require(api.get(base + '/options', headers=headers).status_code == 200, 'Native typed lineage options failed.')
        checks['native_typed_evidence_existing_authority_and_no_new_source_schema'] = True
        body = {'command_id': identity('rec'), 'flow_id': flow['id'], 'run_id': run_id, 'logical_task_id': identity('ret'),
                'bindings': bindings, 'authorized': True, 'notice': NOTICE}
        captured = api.post(base + '/captures', headers=headers, json=body)
        require(captured.status_code == 200 and captured.json()['result']['profile'] == PROFILE, 'Native purpose-bound typed capture failed: ' + captured.text)
        replay = api.post(base + '/captures', headers=headers, json=body)
        require(replay.status_code == 200 and replay.json()['result']['replayed'] is True, 'Native typed capture replay must be receipt-only.')
        checks['native_typed_evidence_per_node_consent_projection_and_capture_dedupe'] = True
        endpoint = base + '/runs/' + run_id + '?flow_id=' + flow['id']
        response = api.get(endpoint, headers=headers)
        require(response.status_code == 200, 'Native current lineage read failed: ' + response.text)
        value = response.json()['result']
        require(value['evidence_current'] and value['logical_samples'] == 1 and value['attempts'] == 2
                and value['nodes'][1]['projections']['query']['node_id'] == 'source', 'Native whole-run/node lineage did not round-trip.')
        require('Native distinct source request' not in response.text and 'encrypted_bundle' not in response.text
                and raw not in response.text and 'session_ref' not in response.text, 'Native lineage exposed raw input or authority.')
        require(api.get(endpoint, headers=headers | {'If-None-Match': response.headers['etag']}).status_code == 304, 'Native current lineage ETag failed.')
        checks['native_typed_evidence_sanitized_metadata_etag_and_current_lineage'] = True
        for rid, cohort_id in zip(resource_ids[:2], cohorts):
            report = plane.current_report(workspace, rid, actor)
            group = next(item for item in report['groups'] if item['cohort_id'] == cohort_id)
            require(group['logical_samples'] == 1 and group['outcomes']['succeeded'] == 1
                    and group['quality_status'] == 'unassessed', 'Native typed observation was not reused by existing agent report.')
        checks['native_typed_evidence_existing_agent_report_no_synthetic_quality_promotion'] = True
        with graph.access._tx(actor) as (db, _):
            projection = plane.current_projection_in_transaction(db, workspace, resource_ids[0], actor)
            require(projection['public_activation'] is False, 'Native transaction projection cannot activate public quality.')
        plane.erase(workspace, command(target_id=bindings[0]['source_id'], target_kind='source', reason='source_deleted', notice=ERASE_NOTICE), actor)
        changed = api.get(endpoint, headers=headers | {'If-None-Match': response.headers['etag']})
        require(changed.status_code == 200 and not changed.json()['result']['evidence_current'], 'Native source erasure must invalidate current lineage and ETag.')
        remaining = plane.current_report(workspace, resource_ids[1], actor)
        group = next(item for item in remaining['groups'] if item['cohort_id'] == cohorts[1])
        require(group['source_fidelity'] == 'unassessable', 'Native partial source loss cannot preserve whole-run fidelity.')
        checks['native_typed_evidence_transaction_guard_erasure_and_hash_only_neutral'] = True
    return checks
