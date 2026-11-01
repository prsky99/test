"""Isolated reliability contracts, retained sources and current evaluator qualification."""
import base64
import copy
import json
import secrets
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.capability_registry import digest
from agent_market.gateway import admin_auth
from agent_market.private_artifact_keys import ArtifactCipher, ArtifactKeys
from agent_market.workspace_access import SessionActor
from agent_market.workspace_reliability import (ERASE_NOTICE, NOTICE, RETENTION_NOTICE, EvaluatorVerdict, ReliabilityEvidence)
from agent_market.workspace_reliability_service import router_for
from tests.test_workspace_execution_api import private_api, execute


def oid(prefix): return prefix + '_' + secrets.token_hex(16)


def encryption():
    keys = ArtifactKeys({'profile': 'private-artifact-keys-v1', 'active_signing': 'isolated', 'active_encryption': 'isolated',
        'allow_legacy': True, 'keys': [{'id': 'isolated', 'key': base64.b64encode(b'S'*32).decode(),
        'verify_until': time.time()+604800, 'revoked': False}]})
    return ArtifactCipher('bounded-reliability-evidence-v1:sources', keys)


@pytest.fixture
def reliability(private_api):
    w = private_api
    from agent_market.workspace_access import WorkspaceAccess
    from agent_market.workspace_execution import WorkspaceExecution
    from agent_market.workflows import runtime_for
    access = WorkspaceAccess(w.store, runtime_for(w.store, None).key)
    execution = WorkspaceExecution(access, w.app.state._test_proxy) if hasattr(w.app.state, '_test_proxy') else None
    if execution is None:
        from types import SimpleNamespace
        execution = WorkspaceExecution(access, SimpleNamespace())
    w.plane = ReliabilityEvidence(access, execution, cipher=encryption())
    w.actor = SessionActor(1, admin_auth.session_reference(w.headers['owner']['Authorization'][7:]))
    app = FastAPI(); app.include_router(router_for(access, execution, core=w.plane))
    w.rel_api = TestClient(app, base_url='https://admin.test', raise_server_exceptions=False)
    w.rel_base = '/admin/api/workflow-workspaces/' + w.ws['id'] + '/reliability'
    try: yield w
    finally: w.rel_api.close()


def post(w, route, body, person='owner'):
    return w.rel_api.post(w.rel_base + route, headers=w.headers[person], json=body)


def command(**fields): return {'command_id': oid('rec'), 'authorized': True, 'notice': NOTICE, **fields}


def save(w, kind, spec, *, identity=None, revision=0):
    body = command(object_id=identity or oid('reo'), kind=kind, revision=revision, spec=spec)
    response = post(w, '/objects', body)
    assert response.status_code == 200, response.text
    return response.json()['result'], body


def setup(w, *, environment='isolated'):
    w.plan, _ = save(w, 'plan', {'dataset_version': 'isolated-corpus-v1', 'dataset_hash': '1'*64,
        'rubric_version': 'isolated-rubric-v1', 'rubric_hash': '2'*64, 'minimum_samples': 2,
        'window_seconds': 86400, 'confidence': 'wilson-95-v1', 'environment': environment, 'evaluator_version': 'trusted-evaluator-v1'})
    w.case, _ = save(w, 'case', {'plan_id': w.plan['id'], 'plan_revision': 1, 'case_version': 'baseline-v1',
        'case_hash': '3'*64, 'category': 'baseline'})
    w.cohort, _ = save(w, 'cohort', {'plan_id': w.plan['id'], 'plan_revision': 1, 'case_ids': [w.case['id']],
        'resource_id': w.rid, 'contract_id': 'news.search.v1', 'purpose': 'independent-read-evaluation'})
    body = command(consent_id=oid('ren'), cohort_id=w.cohort['id'], cohort_revision=1,
                   retention_seconds=3600, notice=RETENTION_NOTICE)
    response = post(w, '/consents', body); assert response.status_code == 200, response.text
    w.consent = response.json()['result']; w.consent_body = body
    return w


def sample(w, *, logical=None, run=None, bundle=None):
    if run is None: run, _ = execute(w)
    bundle = bundle or {'input': {'query': 'Synthetic semiconductor research'}, 'output': run['output'],
                        'sources': [{'reference': 'isolated-source', 'text': '<img src=x onerror=alert(1)>'}]}
    body = command(source_id=oid('res'), consent_id=w.consent['id'], bundle=bundle, notice=RETENTION_NOTICE)
    response = post(w, '/sources', body); assert response.status_code == 200, response.text
    source = response.json()['result']
    observed = command(observation_id=oid('reb'), consent_id=w.consent['id'], case_id=w.case['id'],
        source_id=source['id'], run_ref=run['id'], logical_task_id=logical or oid('ret'))
    response = post(w, '/observations', observed); assert response.status_code == 200, response.text
    return source, run, observed


def report(w, **headers):
    return w.rel_api.get(w.rel_base + '/report?resource_id=' + str(w.rid), headers=w.headers['owner'] | headers)


def trusted(binding, bundle):
    assert 'input' in bundle and 'output' in bundle and binding['bundle_hash'] == digest(bundle)
    return EvaluatorVerdict(digest(binding), 'trusted-evaluator-v1', '4'*64, '5'*64, time.time()+300,
                            binding['environment'], 'passed', 'verified')


def erase(w, identity, kind='source'):
    body = command(target_id=identity, target_kind=kind, reason='source_deleted', notice=ERASE_NOTICE)
    response = post(w, '/erasures', body); assert response.status_code == 200, response.text
    return response, body


def test_immutable_objects_revision_replay_and_bounded_exact_contracts(reliability):
    w = reliability
    plan, body = save(w, 'plan', {'dataset_version': 'corpus-v1', 'dataset_hash': '1'*64, 'rubric_version': 'rubric-v1',
        'rubric_hash': '2'*64, 'minimum_samples': 20, 'window_seconds': 3600, 'confidence': 'wilson-95-v1', 'environment': 'isolated', 'evaluator_version': 'trusted-evaluator-v1'})
    replay = post(w, '/objects', body)
    assert replay.status_code == 200 and replay.json()['result']['replayed']
    updated, _ = save(w, 'plan', plan['spec'] | {'minimum_samples': 21}, identity=plan['id'], revision=1)
    assert updated['revision'] == 2 and len(w.store.query('SELECT id FROM reliability_objects')) == 2
    assert post(w, '/objects', body | {'command_id': oid('rec')}).status_code == 409
    assert post(w, '/objects', body | {'independent': True}).status_code == 400
    for bad in (True, -1, 100000):
        assert post(w, '/objects', body | {'command_id': oid('rec'), 'revision': bad}).status_code == 400
    assert post(w, '/objects', body | {'command_id': oid('rec'), 'object_id': oid('reo'), 'spec': plan['spec'] | {'environment': 'production-certified'}}).status_code == 400


def test_encrypted_retention_unconfigured_evaluator_stays_unassessed_and_no_provider_calls_on_reads(reliability):
    w = setup(reliability); source, _, _ = sample(w); before = len(w.calls)
    response = report(w); assert response.status_code == 200, response.text
    value = response.json()['result']; group = value['groups'][0]
    assert group['logical_samples'] == 1 and group['outcomes'] == {'succeeded': 1, 'failed': 0, 'unknown': 0}
    assert group['quality_status'] == 'unassessed' and group['source_fidelity'] == 'unassessable'
    assert group['quality_outcomes'] == {'passed': 0, 'failed': 0, 'unassessed': 1}
    assert not value['qualified_operating_evidence'] and not value['public_activation'] and len(w.calls) == before
    raw = w.store.query('SELECT payload FROM reliability_sources')[0][0]
    assert 'Private research result' not in raw and 'Synthetic semiconductor' not in raw and 'encrypted_bundle' in raw
    assert '<img' not in response.text and 'session_ref' not in response.text and 'encrypted_bundle' not in response.text
    inspected = post(w, '/sources/' + source['id'] + '/inspect', {'authorized': True, 'notice': RETENTION_NOTICE})
    assert inspected.status_code == 200 and '<img' in inspected.text
    assert 'bundle' not in w.plane.inventory(w.ws['id'], w.actor)['sources'][0]


def test_only_trusted_current_independent_adapter_qualifies_exact_bound_samples(reliability):
    w = setup(reliability, environment='approved_external'); sample(w); sample(w)
    w.plane.evaluator = trusted
    value = report(w).json()['result']; group = value['groups'][0]
    assert group['independently_assessed_samples'] == 2 and group['quality_status'] == 'assessed'
    assert group['source_fidelity'] == 'verified' and group['minimum_sample_met']
    projection = w.plane.get_agent_projection(w.ws['id'], w.rid, w.actor)
    assert projection['independent_qualified'] and projection['logical_samples'] == 2
    assert projection['contract_revision'] == 1 and projection['environment'] == 'approved_external'
    assert not projection['qualified_operating_evidence'] and not projection['public_activation']
    w.plane.evaluator = lambda *_: {'independent': True, 'quality': 'passed'}
    assert not w.plane.get_agent_projection(w.ws['id'], w.rid, w.actor)['independent_qualified']
    w.plane.evaluator = lambda binding, bundle: EvaluatorVerdict('0'*64, 'trusted', '4'*64, '5'*64, time.time()+300, 'approved_external', 'passed', 'verified')
    assert report(w).json()['result']['groups'][0]['quality_status'] == 'unassessed'


def test_evaluator_expiry_failure_and_environment_mixup_fail_closed(reliability):
    w = setup(reliability); sample(w); sample(w)
    for evaluator in (
        lambda b, s: EvaluatorVerdict(digest(b), 'trusted-evaluator-v1', '4'*64, '5'*64, time.time()-1, b['environment'], 'passed', 'verified'),
        lambda b, s: EvaluatorVerdict(digest(b), 'trusted-evaluator-v1', '4'*64, '5'*64, time.time()+300, 'approved_external', 'passed', 'verified'),
        lambda *_: (_ for _ in ()).throw(RuntimeError('private diagnostic')),
    ):
        w.plane.evaluator = evaluator
        response = report(w); assert response.status_code == 200 and 'private diagnostic' not in response.text
        assert response.json()['result']['groups'][0]['quality_status'] == 'unassessed'
    w.plane.evaluator = lambda b, s: EvaluatorVerdict(digest(b), 'trusted-evaluator-v1', '4'*64, '5'*64, time.time()+300, b['environment'], 'failed', 'verified')
    group = report(w).json()['result']['groups'][0]
    assert group['quality_outcomes']['failed'] == 2 and group['quality_status'] == 'assessed'
    assert not w.plane.get_agent_projection(w.ws['id'], w.rid, w.actor)['independent_qualified']
    w.plane.evaluator = lambda b, s: EvaluatorVerdict(digest(b), 'trusted-evaluator-v1', '4'*64, '5'*64, time.time()+300, b['environment'], 'unassessed', 'verified')
    group = report(w).json()['result']['groups'][0]
    assert group['independently_assessed_samples'] == 0 and group['quality_outcomes']['unassessed'] == 2


def test_same_run_cannot_be_relabelled_as_independent_logical_tasks(reliability):
    w = setup(reliability); _, run, body = sample(w)
    response = post(w, '/observations', body | {'command_id': oid('rec'), 'observation_id': oid('reb'), 'logical_task_id': oid('ret')})
    assert response.status_code == 200
    group = report(w).json()['result']['groups'][0]
    assert group['logical_samples'] == 1 and group['duplicates_removed'] == 1
    logical = body['logical_task_id']; sample(w, logical=logical)
    group = report(w).json()['result']['groups'][0]
    assert group['logical_samples'] == 1 and group['duplicates_removed'] == 2
    assert group['success_interval']['denominator'] == 1


def test_failed_and_unknown_are_distinct_denominators_and_never_quality_success(reliability):
    w = setup(reliability); sample(w)
    original_result = w.remote.call_result
    w.remote.call_result = {'isError': True, 'content': [{'type': 'text', 'text': 'Synthetic deterministic tool refusal'}]}
    sample(w); w.remote.call_result = original_result
    w.control['mode'] = 'timeout'; sample(w)
    group = report(w).json()['result']['groups'][0]
    assert group['outcomes'] == {'succeeded': 1, 'failed': 1, 'unknown': 1}
    assert group['success_interval']['denominator'] == 3 and group['unassessed_ratio'] == 1
    w.plane.evaluator = trusted
    assert not w.plane.get_agent_projection(w.ws['id'], w.rid, w.actor)['independent_qualified']


def test_arbitrary_bundle_cannot_impersonate_original_signed_input_output(reliability):
    w = setup(reliability); run, _ = execute(w)
    body = command(source_id=oid('res'), consent_id=w.consent['id'], bundle={'input': {'query': 'invented input'}, 'output': run['output'], 'sources': []}, notice=RETENTION_NOTICE)
    response = post(w, '/sources', body); assert response.status_code == 200
    response = post(w, '/observations', command(observation_id=oid('reb'), consent_id=w.consent['id'], case_id=w.case['id'], source_id=body['source_id'], run_ref=run['id'], logical_task_id=oid('ret')))
    assert response.status_code == 409 and not w.store.query('SELECT id FROM reliability_observations')


def test_permanent_erasure_deletes_ciphertext_prevents_hash_relabel_and_invalidates_etag(reliability):
    w = setup(reliability); source, _, _ = sample(w); sample(w); w.plane.evaluator = trusted
    first = report(w); assert w.plane.get_agent_projection(w.ws['id'], w.rid, w.actor)['independent_qualified']
    original = w.store.query('SELECT * FROM reliability_sources WHERE id=?', (source['id'],))[0]
    response, body = erase(w, source['id'])
    assert not w.store.query('SELECT id FROM reliability_sources WHERE id=?', (source['id'],))
    assert post(w, '/erasures', body).json()['result']['replayed']
    fresh = report(w, **{'If-None-Match': first.headers['etag']})
    assert fresh.status_code == 200 and not w.plane.get_agent_projection(w.ws['id'], w.rid, w.actor)['independent_qualified']
    with w.store.tx() as db: db.execute('INSERT INTO reliability_sources VALUES(?,?,?,?,?)', tuple(original))
    assert not w.plane.get_agent_projection(w.ws['id'], w.rid, w.actor)['independent_qualified']
    inspected = post(w, '/sources/' + source['id'] + '/inspect', {'authorized': True, 'notice': RETENTION_NOTICE})
    assert inspected.status_code == 409
    raw = json.loads(original['payload'] if isinstance(original, dict) else original[3])
    from agent_market.workspace_access import _canonical
    bundle = json.loads(w.plane.cipher.open(_canonical(raw['encrypted_bundle']).encode(), w.plane._context(raw)))
    assert post(w, '/sources', command(source_id=oid('res'), consent_id=w.consent['id'], bundle=bundle, notice=RETENTION_NOTICE)).status_code == 409


def test_consent_withdrawal_erases_sources_and_object_revocation_blocks_resurrection(reliability):
    w = setup(reliability); sample(w)
    erase(w, w.consent['id'], 'consent')
    assert not w.store.query('SELECT id FROM reliability_sources')
    assert report(w).json()['result']['groups'] == []
    erase(w, w.plan['id'], 'object')
    response = post(w, '/objects', command(object_id=w.plan['id'], kind='plan', revision=1, spec=w.plan['spec']))
    assert response.status_code == 409


def test_current_owner_membership_resource_and_case_revisions_invalidate_conditional_read(reliability):
    w = setup(reliability); sample(w); first = report(w)
    with w.store.tx() as db: db.execute('UPDATE workspace_memberships SET revision=revision+1 WHERE workspace_id=? AND user_id=1', (w.ws['id'],))
    fresh = report(w, **{'If-None-Match': first.headers['etag']})
    assert fresh.status_code == 200 and fresh.json()['result']['groups'] == []
    setup(w); sample(w); first = report(w)
    save(w, 'case', w.case['spec'] | {'case_version': 'baseline-v2'}, identity=w.case['id'], revision=1)
    assert report(w, **{'If-None-Match': first.headers['etag']}).json()['result']['groups'] == []


def test_native_restore_quarantine_blocks_old_consent_even_after_owner_reactivation(reliability):
    w = setup(reliability); sample(w); sample(w); w.plane.evaluator = trusted
    first = report(w)
    with w.store.tx() as db: db.execute('INSERT INTO reliability_restore_blocks VALUES(?)', (w.consent['id'],))
    fresh = report(w, **{'If-None-Match': first.headers['etag']})
    assert fresh.status_code == 200 and fresh.json()['result']['groups'] == []
    assert post(w, '/sources', command(source_id=oid('res'), consent_id=w.consent['id'], bundle={'input': {}, 'output': None, 'sources': []}, notice=RETENTION_NOTICE)).status_code == 409


def test_conditional_report_revalidates_exact_session_scope_and_no_store(reliability):
    w = setup(reliability); sample(w); first = report(w)
    assert report(w, **{'If-None-Match': first.headers['etag']}).status_code == 304
    for tag in ('*', 'W/'+first.headers['etag'], first.headers['etag']+', "other"'):
        assert report(w, **{'If-None-Match': tag}).status_code == 200
    for name in ('editor', 'viewer', 'operator'):
        response = w.rel_api.get(w.rel_base + '/report?resource_id=' + str(w.rid), headers=w.headers[name] | {'If-None-Match': first.headers['etag']})
        assert response.status_code == 200
    outsider = w.rel_api.get(w.rel_base + '/report?resource_id=' + str(w.rid), headers=w.headers['outsider'] | {'If-None-Match': first.headers['etag']})
    assert outsider.status_code == 404 and outsider.headers['cache-control'] == 'no-store'
    invalid = w.rel_api.get(w.rel_base + '/options', headers={'Authorization': 'Bearer isolated-machine-token', 'X-Dashboard': '1'})
    assert invalid.status_code == 401
    assert w.rel_api.get(w.rel_base + '/report?resource_id=1&resource_id=2', headers=w.headers['owner']).status_code == 400


def test_owner_only_writes_csrf_duplicate_json_and_cross_workspace_idor(reliability):
    w = setup(reliability); source, _, body = sample(w)
    for name in ('editor', 'viewer', 'operator', 'outsider'):
        assert post(w, '/observations', body | {'command_id': oid('rec'), 'observation_id': oid('reb')}, name).status_code == 404
        assert post(w, '/sources/'+source['id']+'/inspect', {'authorized': True, 'notice': RETENTION_NOTICE}, name).status_code == 404
    assert w.rel_api.post(w.rel_base+'/observations', headers=w.headers['owner'] | {'Origin': 'https://evil.test'}, json=body).status_code == 403
    duplicate = w.rel_api.post(w.rel_base+'/erasures', headers=w.headers['owner'] | {'Content-Type': 'application/json'}, content='{"authorized":true,"authorized":false}')
    assert duplicate.status_code == 400
    path = w.rel_base.replace(w.ws['id'], oid('ws'))+'/sources/'+source['id']+'/inspect'
    assert w.rel_api.post(path, headers=w.headers['owner'], json={'authorized': True, 'notice': RETENTION_NOTICE}).status_code == 404


def test_expired_permission_evaluator_and_cipher_loss_neutralize_current_evidence(reliability, monkeypatch):
    w = setup(reliability); sample(w); sample(w); w.plane.evaluator = trusted; first = report(w)
    with monkeypatch.context() as patch:
        patch.setattr(w.plane.cipher, 'open', lambda *_: (_ for _ in ()).throw(ValueError('isolated-key-loss')))
        response = report(w, **{'If-None-Match': first.headers['etag']})
        assert response.status_code == 200 and response.json()['result']['groups'][0]['source_fidelity'] == 'unassessable'
        assert 'isolated-key-loss' not in response.text
    with monkeypatch.context() as patch:
        patch.setattr('agent_market.workspace_reliability.clock', lambda: w.consent['expires']+1)
        assert report(w).json()['result']['groups'] == []
        assert post(w, '/consents', w.consent_body).status_code == 200
        assert post(w, '/sources', command(source_id=oid('res'), consent_id=w.consent['id'], bundle={'input': {}, 'output': None, 'sources': []}, notice=RETENTION_NOTICE)).status_code == 409


def test_encryption_is_required_and_plaintext_is_never_fallback(reliability):
    w = setup(reliability); w.plane.cipher = ArtifactCipher('bounded-reliability-evidence-v1:sources', ArtifactKeys())
    body = command(source_id=oid('res'), consent_id=w.consent['id'], bundle={'input': {}, 'output': 'private-value', 'sources': []}, notice=RETENTION_NOTICE)
    assert post(w, '/sources', body).status_code == 409
    assert not w.store.query('SELECT id FROM reliability_sources')


def test_expired_source_cleanup_is_bounded_signed_permanent_and_replay_safe(reliability, monkeypatch):
    w = setup(reliability); source, _, _ = sample(w)
    body = command(notice=ERASE_NOTICE)
    with monkeypatch.context() as patch:
        patch.setattr('agent_market.workspace_reliability.clock', lambda: w.consent['expires']+1)
        response = post(w, '/retention-cleanup', body)
        assert response.status_code == 200 and response.json()['result']['erased_sources'] == 1
        assert not w.store.query('SELECT id FROM reliability_sources')
        assert len(w.store.query('SELECT target_id FROM reliability_tombstones')) == 2
        replay = post(w, '/retention-cleanup', body)
        assert replay.json()['result']['replayed'] and replay.json()['result']['erased_sources'] == 1
    assert report(w).json()['result']['groups'][0]['source_fidelity'] == 'unassessable'


def test_resource_binding_aba_and_contract_change_invalidate_source_authority(reliability, monkeypatch):
    w = setup(reliability); sample(w); first = report(w)
    original = w.store.resource(w.rid)['url']
    with w.store.tx() as db:
        db.execute('UPDATE resources SET url=? WHERE id=?', ('https://changed.example/mcp', w.rid))
        db.execute('UPDATE resources SET url=? WHERE id=?', (original, w.rid))
    response = report(w, **{'If-None-Match': first.headers['etag']})
    assert response.status_code == 200 and response.json()['result']['groups'] == []
    setup(w); sample(w)
    from agent_market.capability_contracts import CONTRACTS
    with monkeypatch.context() as patch:
        patch.setitem(CONTRACTS, 'news.search.v1', CONTRACTS['news.search.v1'] | {'version': 2})
        assert report(w).json()['result']['groups'] == []


def test_original_run_deletion_or_ciphertext_tampering_cannot_leave_quality_positive(reliability):
    w = setup(reliability); first_source, run, _ = sample(w); sample(w); w.plane.evaluator = trusted
    assert report(w).status_code == 200  # Prepare local verdicts outside the final read transaction.
    assert w.plane.get_agent_projection(w.ws['id'], w.rid, w.actor)['independent_qualified']
    with w.store.tx() as db: db.execute('DELETE FROM workspace_private_runs WHERE id=?', (run['id'],))
    assert not w.plane.get_agent_projection(w.ws['id'], w.rid, w.actor)['independent_qualified']
    with w.store.tx() as db: db.execute('UPDATE reliability_sources SET signature=? WHERE id=?', ('0'*64, first_source['id']))
    response = post(w, '/sources/'+first_source['id']+'/inspect', {'authorized': True, 'notice': RETENTION_NOTICE})
    assert response.status_code == 409 and 'Traceback' not in response.text
