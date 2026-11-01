"""Private reliability APIs for the owned native Unix PostgreSQL fixture only.

The parent application harness owns transport isolation, the current named staff
session and controlled MCP responder. No address, DSN or provider is accepted.
"""
import base64
import secrets
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient


def run_reliability_contracts(store, graph, workspace, staff, resource_id, session_token):
    from agent_market.capability_registry import digest
    from agent_market.gateway import admin_auth
    from agent_market.private_artifact_keys import ArtifactCipher, ArtifactKeys
    from agent_market.workspace_execution import NOTICE as RUN_NOTICE
    from agent_market.workspace_reliability import (ERASE_NOTICE, NOTICE, RETENTION_NOTICE,
                                                    EvaluatorVerdict, ReliabilityEvidence)
    from agent_market.workspace_reliability_service import router_for

    if (store.backend != 'postgresql' or store.workflow_key != b'k'*32 or graph.access.store is not store
            or graph.execution.access is not graph.access
            or admin_auth.session_reference(session_token) != staff.session_ref):
        raise AssertionError('Only the owned synthetic native application fixture is accepted.')
    resource = store.resource(resource_id)
    if (resource['kind'] != 'mcp' or resource['source'] != 'mcp-registry'
            or resource['url'] not in ('https://typed-0.example/mcp', 'https://typed-1.example/mcp')):
        raise AssertionError('Only the fixed native documentation mock is accepted.')
    checks = {}
    def require(value, label):
        if value is not True: raise AssertionError(label)
    def identity(prefix): return prefix + '_' + secrets.token_hex(16)
    def command(**values): return {'command_id': identity('rec'), 'authorized': True, 'notice': NOTICE, **values}
    keys = ArtifactKeys({'profile': 'private-artifact-keys-v1', 'active_signing': 'native-fixture', 'active_encryption': 'native-fixture',
        'allow_legacy': True, 'keys': [{'id': 'native-fixture', 'key': base64.b64encode(b'R'*32).decode(),
                                      'verify_until': time.time()+3600, 'revoked': False}]})
    core = ReliabilityEvidence(graph.access, graph.execution, cipher=ArtifactCipher('bounded-reliability-evidence-v1:sources', keys))
    app = FastAPI(); app.include_router(router_for(graph.access, graph.execution, core=core))
    ws = workspace['id']; base = '/admin/api/workflow-workspaces/'+ws+'/reliability'
    headers = {'Authorization': 'Bearer '+session_token, 'X-Dashboard': '1'}
    arguments = {'query': 'documentation', 'language': 'en', 'limit': 2}
    draft = graph.access.save_draft(ws, {'name': 'Native retained reliability case', 'description': 'Isolated fixed read',
        'definition': {'nodes': [{'id': 'start', 'name': 'Manual start', 'type': 'trigger', 'kind': 'trigger', 'data': {}},
            {'id': 'docs', 'name': 'Documentation read', 'type': 'agent', 'kind': 'mcp', 'resource_id': resource_id,
             'data': {'tool': 'search_docs', 'input': arguments}}], 'edges': [{'source': 'start', 'target': 'docs'}]}}, staff)
    snapshot = graph.access.create_snapshot(ws, draft['id'], {'draft_revision': draft['revision']}, staff)
    with TestClient(app, base_url='https://native-reliability.example', raise_server_exceptions=False) as api:
        def post(route, body, expected=200):
            response = api.post(base+route, headers=headers, json=body)
            require(response.status_code == expected, 'Native reliability API '+route+': '+response.text)
            return response.json().get('result')
        def save(kind, spec):
            return post('/objects', command(object_id=identity('reo'), kind=kind, revision=0, spec=spec))
        plan = save('plan', {'dataset_version': 'native-isolated-corpus-v1', 'dataset_hash': '1'*64,
            'rubric_version': 'native-isolated-rubric-v1', 'rubric_hash': '2'*64, 'minimum_samples': 2,
            'window_seconds': 3600, 'confidence': 'wilson-95-v1', 'environment': 'isolated',
            'evaluator_version': 'native-fixture-evaluator-v1'})
        case = save('case', {'plan_id': plan['id'], 'plan_revision': 1, 'case_version': 'baseline-v1',
            'case_hash': '3'*64, 'category': 'baseline'})
        cohort = save('cohort', {'plan_id': plan['id'], 'plan_revision': 1, 'case_ids': [case['id']],
            'resource_id': resource_id, 'contract_id': 'docs.search.v1', 'purpose': 'independent-read-evaluation'})
        consent = post('/consents', command(consent_id=identity('ren'), cohort_id=cohort['id'], cohort_revision=1,
                                           retention_seconds=1800, notice=RETENTION_NOTICE))
        checks['native_reliability_signed_plan_case_cohort_constructor_and_purpose_consent'] = True
        retained = []
        for _ in range(2):
            prepared = graph.execution.prepare(ws, draft['id'], snapshot['id'], {'snapshot_revision': snapshot['revision']}, staff)
            run = graph.execution.execute(ws, draft['id'], snapshot['id'], {'ticket_id': prepared['ticket_id'],
                'authorized': True, 'notice': RUN_NOTICE}, staff)
            require(run['status'] == 'succeeded', 'Native original reliability execution must succeed.')
            bundle = {'input': arguments, 'output': run['output'], 'sources': [{'reference': 'native-isolated-docs-v1'}]}
            source_body = command(source_id=identity('res'), consent_id=consent['id'], bundle=bundle, notice=RETENTION_NOTICE)
            source = post('/sources', source_body)
            observation = command(observation_id=identity('reb'), consent_id=consent['id'], case_id=case['id'],
                source_id=source['id'], run_ref=run['id'], logical_task_id=identity('ret'))
            post('/observations', observation)
            replay = post('/observations', observation)
            require(replay['replayed'] is True, 'Native observation command replay failed.')
            retained.append((source, source_body))
        neutral = api.get(base+'/report', params={'resource_id': resource_id}, headers=headers)
        require(neutral.status_code == 200, 'Native unconfigured evaluator report failed.')
        group = neutral.json()['result']['groups'][0]
        require(group['logical_samples'] == 2 and group['quality_status'] == 'unassessed'
                and group['source_fidelity'] == 'unassessable', 'Metadata incorrectly qualified evaluator or source fidelity.')
        require('encrypted_bundle' not in neutral.text and arguments['query'] not in neutral.text
                and session_token not in neutral.text and 'session_ref' not in neutral.text, 'Native report exposed private source or authority.')
        checks['native_reliability_original_source_binding_encrypted_retention_and_neutral_default'] = True
        def evaluator(binding, bundle):
            require(binding['environment'] == 'isolated', 'Fixture evaluator cannot establish external acceptance.')
            require(binding['bundle_hash'] == digest(bundle), 'Exact retained bundle binding changed.')
            return EvaluatorVerdict(digest(binding), 'native-fixture-evaluator-v1', '4'*64, '5'*64,
                                    time.time()+300, 'isolated', 'passed', 'verified')
        core.evaluator = evaluator
        assessed = api.get(base+'/report', params={'resource_id': resource_id}, headers=headers)
        require(assessed.status_code == 200 and assessed.json()['result']['groups'][0]['quality_status'] == 'assessed',
                'Trusted synthetic evaluator binding did not round-trip through native SQL.')
        projection = core.get_agent_projection(ws, resource_id, staff)
        require(projection['independent_qualified'] and projection['environment'] == 'isolated'
                and not projection['qualified_operating_evidence'] and not projection['public_activation'],
                'Synthetic independent fixture was converted into operating evidence.')
        checks['native_reliability_current_typed_qualification_is_scoped_and_never_operating'] = True
        source, source_body = retained[0]
        post('/erasures', command(target_id=source['id'], target_kind='source', reason='source_deleted', notice=ERASE_NOTICE))
        stale = api.get(base+'/report', params={'resource_id': resource_id}, headers=headers | {'If-None-Match': assessed.headers['etag']})
        require(stale.status_code == 200 and not core.get_agent_projection(ws, resource_id, staff)['independent_qualified'],
                'Erased native source retained a positive conditional projection.')
        post('/sources', {**source_body, 'source_id': identity('res'), 'command_id': identity('rec')}, expected=409)
        denied = api.get(base.replace(ws, identity('ws'))+'/inventory', headers=headers)
        require(denied.status_code == 404 and denied.headers['cache-control'] == 'no-store', 'Native workspace IDOR protection failed.')
        checks['native_reliability_source_erasure_tombstone_hash_relabel_etag_and_workspace_idor'] = True
    return checks
