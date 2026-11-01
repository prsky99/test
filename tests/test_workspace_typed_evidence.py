"""Actual typed MCP fixtures, purpose-bound retention and lineage regressions."""
import copy
import json
import secrets
import sqlite3
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.capability_registry import digest
from agent_market.private_artifact_keys import ArtifactCipher
from agent_market.workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid, _canonical
from agent_market.workspace_reliability import ERASE_NOTICE, NOTICE as REL_NOTICE, RETENTION_NOTICE, EvaluatorVerdict, ReliabilityEvidence
from agent_market.workspace_typed_evidence import NOTICE, PROFILE, WorkspaceTypedEvidence
from agent_market.workspace_typed_evidence_service import router_for
from tests.test_workflow_fallback import routing
from tests.test_workspace_reliability import encryption
from tests.test_workspace_typed_flows import typed_world, graph, save, run


def oid(prefix): return prefix + '_' + secrets.token_hex(16)


def command(**fields):
    return {'command_id': oid('rec'), 'authorized': True, 'notice': REL_NOTICE, **fields}


@pytest.fixture
def typed_evidence(typed_world):
    w = typed_world
    w.plane = ReliabilityEvidence(w.access, w.execution, cipher=encryption())
    w.core.cipher = ArtifactCipher(w.core.cipher.purpose, encryption().keys)
    w.evidence = WorkspaceTypedEvidence(w.plane, w.core)
    w.definition = graph(w)
    w.definition['nodes'][0]['input']['query'] = 'Distinct original search'
    w.flow = save(w, w.definition)
    w.plan = w.plane.save_object(w.ws, command(object_id=oid('reo'), kind='plan', revision=0,
        spec={'dataset_version': 'typed-corpus-v1', 'dataset_hash': '1'*64, 'rubric_version': 'typed-rubric-v1',
              'rubric_hash': '2'*64, 'minimum_samples': 2, 'window_seconds': 3600, 'confidence': 'wilson-95-v1',
              'environment': 'isolated', 'evaluator_version': 'typed-independent-v1'}), w.actor)
    w.case = w.plane.save_object(w.ws, command(object_id=oid('reo'), kind='case', revision=0,
        spec={'plan_id': w.plan['id'], 'plan_revision': 1, 'case_version': 'typed-baseline-v1', 'case_hash': '3'*64, 'category': 'baseline'}), w.actor)
    w.bindings = []
    for node in w.definition['nodes']:
        cohort = w.plane.save_object(w.ws, command(object_id=oid('reo'), kind='cohort', revision=0,
            spec={'plan_id': w.plan['id'], 'plan_revision': 1, 'case_ids': [w.case['id']], 'resource_id': node['resource_id'],
                  'contract_id': node['contract_id'], 'purpose': 'independent-read-evaluation'}), w.actor)
        consent = w.plane.authorize_cohort(w.ws, command(consent_id=oid('ren'), cohort_id=cohort['id'],
            cohort_revision=1, retention_seconds=3600, notice=RETENTION_NOTICE), w.actor)
        w.bindings.append({'node_id': node['id'], 'consent_id': consent['id'], 'case_id': w.case['id'],
                           'source_id': oid('res'), 'observation_id': oid('reb')})
    app = FastAPI(); app.include_router(router_for(w.evidence))
    w.client = TestClient(app, base_url='https://admin.test', raise_server_exceptions=False)
    w.headers = {'Authorization': 'Bearer ' + w.raw, 'X-Dashboard': '1'}
    w.base = '/admin/api/workflow-workspaces/' + w.ws + '/reliability/typed'
    yield w
    w.client.close()


def capture_body(w, result):
    return {'command_id': oid('rec'), 'flow_id': w.flow['id'], 'run_id': result['run']['id'],
            'logical_task_id': oid('ret'), 'bindings': copy.deepcopy(w.bindings), 'authorized': True, 'notice': NOTICE}


def captured(w):
    result, _ = run(w, w.flow)
    body = capture_body(w, result)
    value = w.evidence.capture(w.ws, body, w.actor)
    return result, body, value


def read(w, result, **headers):
    return w.client.get(w.base + '/runs/' + result['run']['id'] + '?flow_id=' + w.flow['id'], headers=w.headers | headers)


def erase(w, identity, kind='source'):
    return w.plane.erase(w.ws, command(target_id=identity, target_kind=kind, reason='withdrawn', notice=ERASE_NOTICE), w.actor)


def test_real_projection_capture_reuses_encryption_and_agent_report(typed_evidence):
    w = typed_evidence; result, body, saved = captured(w); calls = list(w.calls)
    assert saved['profile'] == PROFILE and len(saved['nodes']) == 2
    assert w.calls == ['primary.example', 'alternate.example']
    assert len(w.store.query('SELECT * FROM reliability_sources')) == 2
    for row in w.store.query('SELECT payload FROM reliability_sources'):
        source = json.loads(row[0]); assert 'encrypted_bundle' in source
        assert 'Current documentation' not in row[0]
    first_bundle = w.plane.inspect_source(w.ws, w.bindings[0]['source_id'], {'authorized': True, 'notice': RETENTION_NOTICE}, w.actor)['bundle']
    second_bundle = w.plane.inspect_source(w.ws, w.bindings[1]['source_id'], {'authorized': True, 'notice': RETENTION_NOTICE}, w.actor)['bundle']
    assert first_bundle['input']['query'] == 'Distinct original search'
    assert second_bundle['input']['query'] == first_bundle['output']['items'][0]['title'] == 'Current documentation'
    report = read(w, result); assert report.status_code == 200, report.text
    value = report.json()['result']; assert value['evidence_current'] and value['logical_samples'] == 1
    assert value['attempts'] == 2 and value['closed_actions'] == 2
    assert value['nodes'][1]['projections']['query']['node_id'] == 'first'
    assert all(n['output_source_ref'] for n in value['nodes'])
    assert 'Current documentation' not in report.text and 'encrypted_bundle' not in report.text and 'session_ref' not in report.text
    for rid in w.ids[:2]:
        agent = w.plane.current_report(w.ws, rid, w.actor)
        assert agent['groups'][0]['logical_samples'] == 1
        assert agent['groups'][0]['outcomes']['succeeded'] == 1
        assert agent['groups'][0]['quality_status'] == 'unassessed'
    again = w.evidence.capture(w.ws, body, w.actor)
    assert again['replayed'] and len(w.store.query('SELECT * FROM reliability_observations')) == 2
    changed = body | {'command_id': oid('rec'), 'logical_task_id': oid('ret')}
    with pytest.raises(WorkspaceConflict): w.evidence.capture(w.ws, changed, w.actor)
    assert w.calls == calls


def test_skipped_and_unreached_nodes_do_not_create_execution_samples(typed_evidence):
    w = typed_evidence
    definition = graph(w); definition['nodes'][1]['when']['equals'] = True
    w.flow = w.core.save(w.ws, {'flow_id': w.flow['id'], 'revision': 1, 'name': 'Skipped path', 'definition': definition}, w.actor)
    result, body, value = captured(w)
    assert w.calls == ['primary.example']
    assert value['nodes'][1]['status'] == 'skipped' and value['nodes'][1]['source_id'] is None
    assert len(w.store.query('SELECT * FROM reliability_sources')) == 1
    view = read(w, result).json()['result']
    assert view['nodes'][1]['attempt_ref'] is None and view['nodes'][1]['input_hash'] is None
    assert view['nodes'][1]['prepared_input_hash'] is not None
    assert view['nodes'][1]['output_source_ref'] is None and view['attempts'] == 1


@pytest.mark.parametrize('mode,run_status,node_status', [('unknown', 'unknown', 'unknown'), ('error', 'failed', 'failed'), ('invalid', 'failed', 'unknown')])
def test_failed_unknown_and_missing_response_evidence_are_not_retried(typed_evidence, mode, run_status, node_status):
    w = typed_evidence; w.modes['primary.example'] = mode
    result, body, value = captured(w)
    assert result['run']['status'] == run_status
    assert value['nodes'][0]['status'] == node_status and value['nodes'][1]['status'] == 'unreached'
    assert w.calls == ['primary.example']
    report = w.plane.current_report(w.ws, w.ids[0], w.actor)
    assert report['groups'][0]['outcomes'][node_status] == 1
    assert report['groups'][0]['quality_status'] == 'unassessed'
    assert not w.plane.get_agent_projection(w.ws, w.ids[0], w.actor)['independent_qualified']
    view = read(w, result).json()['result']
    assert view['nodes'][1]['input_hash'] is None and view['automatic_retry'] is False
    assert w.calls == ['primary.example']


def test_explicit_signed_terminal_failure_preserves_partial_prior_output(typed_evidence):
    w = typed_evidence; result, _ = run(w, w.flow)
    # A controlled persisted-state fixture exercises a definite failure record.
    # It does not claim the remote fixture's uncertain error is definite.
    with w.store.tx() as db:
        value, _, _ = w.core._run(db, w.ws, w.flow['id'], result['run']['id'])
        value['status'] = 'failed'; value['error_code'] = 'UPSTREAM_FAILURE'; w.core._write_run(db, value)
        row = db.execute('SELECT * FROM workspace_typed_flow_steps WHERE run_id=? AND node_id=?', (value['id'], 'followup')).fetchone()
        step = w.core._step(dict(row)); step['status'] = 'failed'; step['output'] = None
        w.core._write_step(db, step)
    captured_value = w.evidence.capture(w.ws, capture_body(w, result), w.actor)
    assert [n['status'] for n in captured_value['nodes']] == ['succeeded', 'failed']
    first = w.plane.current_report(w.ws, w.ids[0], w.actor)
    second = w.plane.current_report(w.ws, w.ids[1], w.actor)
    assert first['groups'][0]['outcomes']['succeeded'] == 1
    assert second['groups'][0]['outcomes']['failed'] == 1
    assert len(w.calls) == 2


def test_source_erasure_changes_etag_and_all_lineage_source_fidelity(typed_evidence):
    w = typed_evidence; result, _, _ = captured(w)
    before = read(w, result); etag = before.headers['etag']
    assert read(w, result, **{'If-None-Match': etag}).status_code == 304
    erase(w, w.bindings[0]['source_id'])
    after = read(w, result, **{'If-None-Match': etag})
    assert after.status_code == 200 and after.headers['etag'] != etag
    assert not after.json()['result']['evidence_current']
    assert all(n['source_fidelity'] == 'unassessable' for n in after.json()['result']['nodes'])
    report = w.plane.current_report(w.ws, w.ids[1], w.actor)
    assert report['groups'][0]['source_fidelity'] == 'unassessable'
    assert report['excluded_sources']['source_unavailable'] == 1
    assert len(w.calls) == 2


@pytest.mark.parametrize('change', ['owner_revision', 'control', 'restore', 'pin', 'signature'])
def test_current_authority_restore_and_original_source_tamper_fail_closed(typed_evidence, change):
    w = typed_evidence; result, _, _ = captured(w)
    with w.store.tx() as db:
        if change == 'owner_revision': db.execute('UPDATE workspace_memberships SET revision=revision+1 WHERE workspace_id=?', (w.ws,))
        elif change == 'control': db.execute('UPDATE execution_controls SET revision=revision+1 WHERE id=1')
        elif change == 'restore': db.execute('INSERT INTO workspace_typed_flow_restore_blocks VALUES(?)', (w.flow['id'],))
        elif change == 'pin': db.execute('DELETE FROM capability_approvals WHERE version_id IN (SELECT id FROM connection_versions WHERE resource_id=?)', (w.ids[0],))
        else: db.execute("UPDATE workspace_typed_flow_steps SET signature='invalid' WHERE run_id=?", (result['run']['id'],))
    assert read(w, result).status_code in (404, 409)
    assert not w.plane.get_agent_projection(w.ws, w.ids[0], w.actor)['independent_qualified']
    assert len(w.calls) == 2


def test_each_node_needs_exact_current_purpose_and_original_input_hash(typed_evidence):
    w = typed_evidence; result, _ = run(w, w.flow)
    body = capture_body(w, result); bad = copy.deepcopy(body); bad['bindings'][1]['consent_id'] = bad['bindings'][0]['consent_id']
    with pytest.raises(WorkspaceConflict): w.evidence.capture(w.ws, bad, w.actor)
    with w.store.tx() as db:
        row = dict(db.execute('SELECT * FROM workspace_typed_flow_steps WHERE run_id=? AND node_id=?', (result['run']['id'], 'followup')).fetchone())
        step = json.loads(row['payload']); step['input_hash'] = 'sha256:' + '0'*64
        db.execute('UPDATE workspace_typed_flow_steps SET payload=?,signature=? WHERE run_id=? AND node_id=?',
                   (_canonical(step), w.core.signer.sign(step), result['run']['id'], 'followup'))
    with pytest.raises(WorkspaceConflict): w.evidence.capture(w.ws, body, w.actor)
    assert not w.store.query('SELECT * FROM reliability_sources') and len(w.calls) == 2


def test_api_individual_session_csrf_exact_fields_idor_and_no_public_route(typed_evidence):
    w = typed_evidence; result, _ = run(w, w.flow); body = capture_body(w, result)
    assert w.client.get(w.base + '/options').status_code == 401
    assert w.client.post(w.base + '/captures', headers=w.headers | {'Origin': 'https://other.test'}, json=body).status_code == 403
    for changes in ({'authorized': False}, {'notice': RETENTION_NOTICE}, {'extra': True}):
        assert w.client.post(w.base + '/captures', headers=w.headers, json=body | changes).status_code == 400
    response = w.client.post(w.base + '/captures', headers=w.headers, json=body)
    assert response.status_code == 200, response.text
    assert 'no-store' in response.headers['cache-control']
    assert w.client.get(w.base + '/runs?flow_id=' + w.flow['id'] + '&flow_id=' + w.flow['id'], headers=w.headers).status_code == 400
    other_ws = w.access.provision({'name': 'Other private scope', 'owner_id': w.actor.user_id}, w.actor)['id']
    assert w.client.get(w.base.replace(w.ws, other_ws) + '/runs/' + result['run']['id'] + '?flow_id=' + w.flow['id'], headers=w.headers).status_code == 404
    assert w.client.get('/api/reliability/typed').status_code == 404
    assert len(w.calls) == 2


def test_same_transaction_projection_requires_exact_current_store_and_sees_withdrawal(typed_evidence):
    w = typed_evidence; captured(w)
    with pytest.raises(WorkspaceConflict): w.plane.current_projection_in_transaction(w.store._db, w.ws, w.ids[0], w.actor)
    with sqlite3.connect(':memory:') as foreign:
        with pytest.raises(WorkspaceConflict): w.plane.current_projection_in_transaction(foreign, w.ws, w.ids[0], w.actor)
    with w.access._tx(w.actor) as (db, _):
        value = w.plane.current_projection_in_transaction(db, w.ws, w.ids[0], w.actor)
        member, user = w.plane.scope(w.ws, w.actor)
        assert value == w.plane._projection(w.plane._current_report(db, w.ws, w.ids[0], w.actor, user, member))
    erase(w, w.bindings[0]['consent_id'], 'consent')
    with w.access._tx(w.actor) as (db, _):
        assert not w.plane.current_projection_in_transaction(db, w.ws, w.ids[0], w.actor)['independent_qualified']


def test_metadata_reads_never_decrypt_unretained_outputs(typed_evidence, monkeypatch):
    w = typed_evidence; result, _ = run(w, w.flow)
    monkeypatch.setattr(w.core.cipher, 'open', lambda *_: (_ for _ in ()).throw(AssertionError('No raw read permission')))
    value = read(w, result)
    assert value.status_code == 200 and not value.json()['result']['evidence_current']
    assert all(n['output_source_ref'] is None for n in value.json()['result']['nodes'])
    assert len(w.calls) == 2


def test_consent_expiry_changes_etag_and_blocks_recapture(typed_evidence, monkeypatch):
    w = typed_evidence; result, body, _ = captured(w)
    before = read(w, result)
    monkeypatch.setattr('agent_market.workspace_reliability.clock', lambda: time.time() + 3700)
    after = read(w, result, **{'If-None-Match': before.headers['etag']})
    assert after.status_code == 200 and not after.json()['result']['evidence_current']
    with pytest.raises(WorkspaceConflict): w.evidence.capture(w.ws, body, w.actor)
    assert not w.plane.current_report(w.ws, w.ids[0], w.actor)['groups'] and len(w.calls) == 2


def test_logical_task_dedupes_distinct_node_attempts_without_extra_samples(typed_evidence):
    w = typed_evidence; result, first, _ = captured(w)
    second_run, _ = run(w, w.flow)
    second = capture_body(w, second_run); second['logical_task_id'] = first['logical_task_id']
    for item in second['bindings']:
        item.update(source_id=oid('res'), observation_id=oid('reb'))
    w.evidence.capture(w.ws, second, w.actor)
    for rid in w.ids[:2]:
        value = w.plane.current_report(w.ws, rid, w.actor)['groups'][0]
        assert value['logical_samples'] == 1 and value['duplicates_removed'] == 1
    assert len(w.calls) == 4


def test_signed_late_or_reordered_step_is_not_silently_normalized(typed_evidence):
    w = typed_evidence; result, _, _ = captured(w)
    with w.store.tx() as db:
        rows = {row['node_id']: dict(row) for row in db.execute('SELECT * FROM workspace_typed_flow_steps WHERE run_id=?', (result['run']['id'],))}
        first = w.core._step(rows['first']); second = w.core._step(rows['followup'])
        first['finished'] = second['finished']; w.core._write_step(db, first)
    assert read(w, result).status_code == 409
    assert not w.plane.current_report(w.ws, w.ids[0], w.actor)['groups']
    assert len(w.calls) == 2


def test_existing_restore_quarantine_erases_sources_and_keeps_signed_history(typed_evidence):
    from agent_market.workflow_backup import quarantine
    w = typed_evidence; result, _, _ = captured(w)
    original = w.store.query('SELECT payload,signature FROM workspace_typed_flow_versions')[0][:]
    with w.store.tx() as db: quarantine(db)
    assert not w.store.query('SELECT * FROM reliability_sources')
    assert w.store.query('SELECT payload,signature FROM workspace_typed_flow_versions')[0][:] == original
    assert read(w, result).status_code in (401, 404, 409)
    assert len(w.calls) == 2


@pytest.mark.parametrize('key_owner', ['plane', 'original'])
def test_unavailable_retention_or_original_key_cannot_keep_current_hash_only_lineage(typed_evidence, key_owner):
    w = typed_evidence; result, _, _ = captured(w); before = read(w, result)
    cipher = w.plane.cipher if key_owner == 'plane' else w.core.cipher
    cipher.keys.config['keys']['isolated']['revoked'] = True
    after = read(w, result, **{'If-None-Match': before.headers['etag']})
    assert after.status_code == 200 and not after.json()['result']['evidence_current']
    assert all(node['source_fidelity'] == 'unassessable' for node in after.json()['result']['nodes'])
    assert w.plane.current_report(w.ws, w.ids[0], w.actor)['groups'][0]['source_fidelity'] == 'unassessable'
    assert len(w.calls) == 2


def test_expired_interrupted_run_is_unknown_without_invented_terminal_time(typed_evidence, monkeypatch):
    w = typed_evidence; result, _ = run(w, w.flow)
    with w.store.tx() as db:
        value, _, _ = w.core._run(db, w.ws, w.flow['id'], result['run']['id'])
        value.update(status='running', finished=None, error_code=None); w.core._write_run(db, value)
    monkeypatch.setattr('agent_market.workspace_typed_evidence.clock', lambda: time.time()+200)
    value = read(w, result).json()['result']
    assert value['status'] == 'unknown' and value['observed_status'] == 'running'
    assert not value['evidence_current'] and not value['automatic_retry']
    with pytest.raises(WorkspaceConflict): w.evidence.capture(w.ws, capture_body(w, result), w.actor)
    assert len(w.calls) == 2
