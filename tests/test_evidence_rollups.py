"""Retained evidence projection uses isolated source rows and controlled executions."""
import copy
import json
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.capability_registry import Registry
from agent_market.evidence_rollups import EvidenceRollups, NOTICE
from agent_market.evidence_rollup_service import router_for
from agent_market.gateway import admin_auth
from agent_market.observability import journal_for
from agent_market.workspace_access import SessionActor, WorkspaceAccess
from agent_market.workspace_execution import WorkspaceExecution
from agent_market.workflows import runtime_for
from tests.test_workspace_execution_api import private_api, execute


@pytest.fixture
def evidence(private_api):
    w = private_api
    runtime = runtime_for(w.store, None)
    access = WorkspaceAccess(w.store, runtime.key)
    execution = WorkspaceExecution(access, SimpleNamespace())
    w.evidence = EvidenceRollups(access, execution)
    w.actor = SessionActor(1, admin_auth.session_reference(w.headers['owner']['Authorization'][7:]))
    app = FastAPI(); app.include_router(router_for(access, execution, core=w.evidence))
    w.ev_api = TestClient(app, base_url='https://private.test')
    w.ev_base = '/admin/api/workflow-workspaces/' + w.ws['id'] + '/evidence'
    w.ev_path = w.ev_base + '/rollup?resource_id=' + str(w.rid)
    try: yield w
    finally: w.ev_api.close()


def catalog_source(w, *, operation=None, outcome='succeeded', started=None, finished=None):
    registry = Registry(w.store); version = registry.current(w.rid)
    if operation is None:
        operation = journal_for(w.store).begin('execution', 'testbench', resource_id=w.rid, proto='mcp')
    attempt = operation.attempt(w.rid, 'mcp')
    now = time.time()
    identity = registry.record(version, scope='execution', outcome=outcome, started=started or now - 2,
                               finished=finished or now - 1, operation_ref=attempt.id)
    return identity, operation


def get(w, *, scope='workspace', headers=None, path=None):
    return w.ev_api.get((path or w.ev_path) + '&scope=' + scope, headers=headers or w.headers['owner'])


def withdrawal(w, ref, *, scope='workspace', **changes):
    return {'scope': scope, 'resource_id': w.rid, 'source_ref': ref, 'revision': 0,
            'reason': 'source_withdrawn', 'authorized': True, 'notice': NOTICE, **changes}


def test_private_real_retained_signed_run_is_metadata_only_and_does_not_dispatch_or_decrypt(evidence, monkeypatch):
    w = evidence
    run, _ = execute(w); before = len(w.calls)
    monkeypatch.setattr(w.evidence.execution._output_cipher, 'open', lambda *_: pytest.fail('Rollup decrypted private output'))
    response = get(w); assert response.status_code == 200, response.text
    result = response.json()['result']
    assert result['groups'][0]['outcomes'] == {'succeeded': 1, 'failed': 0, 'unknown': 0}
    assert result['quality_status'] == 'unassessed' and result['source_fidelity'] == 'unassessable_from_metadata'
    assert not result['qualified_operating_evidence'] and result['provider_calls'] == 0
    assert result['sources'][0]['source_ref'] == run['id'] and len(w.calls) == before
    for marker in ('Private research result', 'Synthetic semiconductor', 'private-provider.example', 'session_ref', 'signature', 'encrypted_output', 'actor_user_id'):
        assert marker not in response.text


def test_catalog_retry_attempts_collapse_logical_task_and_unknown_is_never_promoted(evidence):
    w = evidence; _, op = catalog_source(w)
    catalog_source(w, operation=op, outcome='failed')
    catalog_source(w, operation=op, outcome='unknown')
    result = get(w, scope='catalog').json()['result']
    group = result['groups'][0]
    assert group['logical_samples'] == 1 and group['duplicates_removed'] == 2
    assert group['outcomes'] == {'succeeded': 0, 'failed': 0, 'unknown': 1}
    assert not group['minimum_sample_met'] and result['quality_status'] == 'unassessed'


def test_unattributed_catalog_record_is_not_a_success_sample(evidence):
    w = evidence; registry = Registry(w.store); now = time.time()
    registry.record(registry.current(w.rid), scope='execution', outcome='succeeded', started=now-2, finished=now-1)
    result = get(w, scope='catalog').json()['result']
    assert result['groups'] == [] and result['excluded_sources']['unattributed'] == 1


def test_conditional_read_revalidates_authority_and_exact_scope_before_304(evidence):
    w = evidence; catalog_source(w)
    first = get(w, scope='catalog'); tag = first.headers['etag']
    current = get(w, scope='catalog', headers=w.headers['owner'] | {'If-None-Match': tag})
    assert current.status_code == 304 and not current.content
    assert current.headers['cache-control'] == 'no-store' and 'Authorization' in current.headers['vary']
    for condition in ('*', 'W/' + tag, tag + ', "other"'):
        assert get(w, scope='catalog', headers=w.headers['owner'] | {'If-None-Match': condition}).status_code == 200
    for name in ('editor', 'viewer', 'operator', 'outsider'):
        assert get(w, scope='catalog', headers=w.headers[name] | {'If-None-Match': tag}).status_code == 404
    assert get(w, headers=w.headers['owner'] | {'If-None-Match': tag}).status_code == 200


def test_withdrawal_is_permanent_scoped_deduplicated_and_invalidates_matching_etag(evidence):
    w = evidence; ref, _ = catalog_source(w)
    first = get(w, scope='catalog'); before = w.store.resource(w.rid)
    body = withdrawal(w, ref, scope='catalog')
    for _ in range(2):
        response = w.ev_api.post(w.ev_base + '/withdrawals', headers=w.headers['owner'], json=body)
        assert response.status_code == 200 and response.json()['result']['withdrawn']
    assert w.store.query('SELECT COUNT(*) FROM evidence_rollup_audit')[0][0] == 1
    fresh = get(w, scope='catalog', headers=w.headers['owner'] | {'If-None-Match': first.headers['etag']})
    assert fresh.status_code == 200 and fresh.json()['result']['excluded_sources']['withdrawn'] == 1
    assert fresh.json()['result']['groups'] == [] and w.store.resource(w.rid) == before
    assert w.store.query('SELECT id FROM capability_evidence WHERE id=?', (ref,))
    conflicting = w.ev_api.post(w.ev_base + '/withdrawals', headers=w.headers['owner'], json=body | {'reason': 'invalid_source'})
    assert conflicting.status_code == 409


def test_expiry_version_change_and_source_deletion_cannot_return_old_304(evidence, monkeypatch):
    w = evidence; ref, _ = catalog_source(w)
    first = get(w, scope='catalog'); tag = first.headers['etag']
    expires = w.store.query('SELECT expires FROM capability_evidence WHERE id=?', (ref,))[0][0]
    with monkeypatch.context() as changed_clock:
        changed_clock.setattr('agent_market.evidence_rollups.clock', lambda: expires)
        expired = get(w, scope='catalog', headers=w.headers['owner'] | {'If-None-Match': tag})
        assert expired.status_code == 200 and expired.json()['result']['excluded_sources']['expired'] == 1
    with w.store.tx() as db: db.execute('UPDATE resources SET url=? WHERE id=?', ('https://changed.example/mcp', w.rid))
    changed = get(w, scope='catalog', headers=w.headers['owner'] | {'If-None-Match': tag})
    assert changed.status_code == 200 and changed.json()['result']['excluded_sources']['version_changed'] == 1
    with w.store.tx() as db: db.execute('DELETE FROM capability_evidence WHERE id=?', (ref,))
    missing = get(w, scope='catalog', headers=w.headers['owner'] | {'If-None-Match': changed.headers['etag']})
    assert missing.status_code == 200 and missing.json()['result']['groups'] == []


def test_private_snapshot_revocation_and_binding_aba_exclude_history(evidence):
    w = evidence; execute(w)
    before = get(w); assert before.json()['result']['groups']
    original = w.store.resource(w.rid)['url']
    with w.store.tx() as db:
        db.execute('UPDATE resources SET url=? WHERE id=?', ('https://changed.example/mcp', w.rid))
        db.execute('UPDATE resources SET url=? WHERE id=?', (original, w.rid))
    changed = get(w, headers=w.headers['owner'] | {'If-None-Match': before.headers['etag']})
    assert changed.status_code == 200 and changed.json()['result']['excluded_sources']['not_current'] == 1


def test_unknown_private_execution_stays_unknown_and_ticket_withdrawal_is_neutral(evidence):
    w = evidence; w.control['mode'] = 'timeout'; run, _ = execute(w)
    first = get(w)
    assert first.json()['result']['groups'][0]['outcomes']['unknown'] == 1
    result = w.ev_api.post(w.ev_base + '/withdrawals', headers=w.headers['owner'], json=withdrawal(w, run['id']))
    assert result.status_code == 200
    assert get(w).json()['result']['groups'] == []
    assert w.store.query('SELECT status FROM workspace_private_runs WHERE id=?', (run['id'],))[0][0] == 'unknown'


def test_workspace_and_cache_partition_and_private_idor(evidence):
    w = evidence; run, _ = execute(w)
    other = w.evidence.access.provision({'name': 'Separate evidence workspace', 'owner_id': 1}, w.actor)['id']
    other_base = w.ev_base.replace(w.ws['id'], other)
    response = get(w, path=w.ev_path.replace(w.ws['id'], other))
    assert response.status_code == 200 and response.json()['result']['groups'] == []
    assert response.headers['etag'] != get(w).headers['etag']
    denied = w.ev_api.post(other_base + '/withdrawals', headers=w.headers['owner'], json=withdrawal(w, run['id']))
    assert denied.status_code == 404
    assert get(w, headers=w.headers['outsider']).status_code == 404


@pytest.mark.parametrize('headers', [{}, {'Authorization': 'Bearer machine'}, {'X-Dashboard': '1', 'Authorization': 'Bearer ' + 'f'*64}])
def test_individual_staff_session_required_not_machine_or_customer(evidence, headers):
    w = evidence; w.ev_api.cookies.set('__Host-ac_customer_session', 'synthetic-customer')
    response = get(w, headers=headers or {'X-Dashboard': '1'})
    assert response.status_code == 401 and response.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('header', [{'Origin': 'https://outside.example'}, {'Origin': 'null'}, {'Sec-Fetch-Site': 'cross-site'}])
def test_cross_origin_cannot_read_or_withdraw(evidence, header):
    w = evidence; ref, _ = catalog_source(w)
    headers = w.headers['owner'] | header
    assert get(w, scope='catalog', headers=headers).status_code == 403
    assert w.ev_api.post(w.ev_base+'/withdrawals', headers=headers, json=withdrawal(w, ref, scope='catalog')).status_code == 403


@pytest.mark.parametrize('raw', ['{"scope":"workspace","scope":"catalog"}', '{"resource_id":NaN}', '[]', 'x'*4097])
def test_duplicate_nonfinite_or_oversize_withdrawal_has_no_side_effect(evidence, raw):
    w = evidence; response = w.ev_api.post(w.ev_base+'/withdrawals', headers=w.headers['owner'], content=raw)
    assert response.status_code == 400 and response.headers['cache-control'] == 'no-store'
    assert w.store.query('SELECT COUNT(*) FROM evidence_rollup_audit')[0][0] == 0


def test_revoked_staff_session_cannot_retain_304(evidence):
    w = evidence; first = get(w)
    with w.store.tx() as db: db.execute('DELETE FROM admin_sessions WHERE user_id=1')
    response = get(w, headers=w.headers['owner'] | {'If-None-Match': first.headers['etag']})
    assert response.status_code == 401 and 'etag' not in response.headers


def test_future_clock_observation_is_neutral_until_actual_observation_time(evidence, monkeypatch):
    w = evidence; now = time.time(); catalog_source(w, started=now-1, finished=now+1)
    with monkeypatch.context() as frozen:
        frozen.setattr('agent_market.evidence_rollups.clock', lambda: now)
        before = get(w, scope='catalog')
        assert before.json()['result']['excluded_sources']['clock_skew'] == 1
        assert before.json()['result']['groups'] == []
    with monkeypatch.context() as later:
        later.setattr('agent_market.evidence_rollups.clock', lambda: now+1)
        after = get(w, scope='catalog', headers=w.headers['owner'] | {'If-None-Match': before.headers['etag']})
        assert after.status_code == 200 and after.json()['result']['groups'][0]['logical_samples'] == 1


def test_contract_approval_withdrawal_invalidates_exact_contract_scope(evidence):
    w = evidence
    with w.store.tx() as db: db.execute('UPDATE resources SET usage_full_tools=? WHERE id=?', (json.dumps(w.remote.tools), w.rid))
    registry = Registry(w.store); version = registry.approve(w.store.resource(w.rid), 'news.search.v1', 'search_news')
    at = time.time()
    registry.record(version, scope='contract', outcome='succeeded', started=at, finished=at,
                    contract_id='news.search.v1', dataset='explicit-contract-test-v1')
    first = get(w, scope='catalog')
    assert first.json()['result']['groups'][0]['contract_id'] == 'news.search.v1'
    with w.store.tx() as db: db.execute('DELETE FROM capability_approvals WHERE version_id=?', (version['id'],))
    changed = get(w, scope='catalog', headers=w.headers['owner'] | {'If-None-Match': first.headers['etag']})
    assert changed.status_code == 200 and changed.json()['result']['excluded_sources']['not_current'] == 1


def test_source_signature_tamper_fails_closed_without_decrypting_or_repair(evidence):
    w = evidence; run, _ = execute(w)
    with w.store.tx() as db:
        original = db.execute('SELECT payload FROM workspace_private_runs WHERE id=?', (run['id'],)).fetchone()[0]
        value = json.loads(original); value['output'] = 'Synthetic tampering marker'
        db.execute('UPDATE workspace_private_runs SET payload=? WHERE id=?', (json.dumps(value), run['id']))
    response = get(w)
    assert response.status_code == 409 and 'Synthetic tampering marker' not in response.text
    assert 'Synthetic tampering marker' in w.store.query('SELECT payload FROM workspace_private_runs WHERE id=?', (run['id'],))[0][0]


def test_member_role_does_not_grant_withdrawal_and_revoked_ticket_is_not_current(evidence):
    w = evidence; run, _ = execute(w)
    for role in ('editor', 'viewer', 'operator'):
        assert w.ev_api.post(w.ev_base+'/withdrawals', headers=w.headers[role], json=withdrawal(w, run['id'])).status_code == 404
    first = get(w)
    with w.store.tx() as db: db.execute('UPDATE workspace_private_tickets SET revoked=? WHERE run_id=?', (time.time(), run['id']))
    after = get(w, headers=w.headers['owner'] | {'If-None-Match': first.headers['etag']})
    assert after.status_code == 200 and after.json()['result']['excluded_sources']['not_current'] == 1


def test_minimum_sample_threshold_never_promotes_operating_quality(evidence):
    w = evidence
    for _ in range(20): catalog_source(w)
    result = get(w, scope='catalog').json()['result']
    assert result['groups'][0]['logical_samples'] == 20 and result['groups'][0]['minimum_sample_met']
    assert result['state'] == 'retained_history_only' and result['quality_status'] == 'unassessed'
    assert result['source_fidelity'] == 'unassessable_from_metadata' and not result['qualified_operating_evidence']


def test_retained_source_scan_and_visible_refs_are_bounded(evidence):
    w = evidence; registry = Registry(w.store); version = registry.current(w.rid); at = time.time()-1
    with w.store.tx() as db:
        for index in range(201):
            db.execute('INSERT INTO capability_evidence VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       ('ev_'+f'{index:032x}', version['id'], 'execution', 'succeeded', at-1, at, at, at+86400,
                        None, None, '', 'capability-validator-v1', 'live-execution-v1', 1, 1, None))
    response = get(w, scope='catalog'); result = response.json()['result']
    assert result['truncated'] and len(result['sources']) == 50
    assert result['excluded_sources']['unattributed'] == 200 and result['groups'] == []
    assert len(response.content) < 65536


def test_actual_dashboard_has_only_fixed_evidence_asset_with_nonce(evidence):
    import re
    from pathlib import Path
    w = evidence; response = w.client.get('/admin/ui')
    nonce = re.search(r"script-src 'nonce-([^']+)'", response.headers['content-security-policy']).group(1)
    assert f'<script nonce="{nonce}" src="/admin/assets/workspace-evidence-admin.js"></script>' in response.text
    asset = w.client.get('/admin/assets/workspace-evidence-admin.js')
    assert asset.status_code == 200 and asset.content == Path('agent_market/gateway/workspace-evidence-admin.js').read_bytes()
    assert asset.headers['cache-control'] == 'no-store' and w.client.get('/admin/assets/evidence_rollups.py').status_code == 404
