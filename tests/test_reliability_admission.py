"""Single-call pilot fences, atomic artifacts and uncertainty on isolated transports."""
import copy
import hashlib
import hmac
import json
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from agent_market.reliability_admission import SingleAdmission, NOTICE
from agent_market.reliability_admission_service import router_for
from agent_market.workspace_access import SessionActor, WorkspaceConflict, WorkspaceDenied, _canonical
from agent_market.workspace_execution import WorkspaceExecution, NOTICE as RUN_NOTICE
from tests.test_reliability_controls import controls, routing_policy, post
from tests.test_workspace_execution_api import private_api


@pytest.fixture
def pilot(controls, monkeypatch):
    w = controls
    assert post(w, '/routing/configure', routing_policy(w, mode='decision_shadow')).status_code == 200
    w.execution = WorkspaceExecution(w.access, w.runtime.proxy)
    w.admission = SingleAdmission(w.access, w.routing, w.execution, enabled=True,
        evidence_guard=lambda db, ws, rid, actor: copy.deepcopy(w.sources[rid]))
    w.policy = {'revision': 0, 'shadow_revision': 1, 'enabled': True, 'percent': 10, 'max_runs': 3,
                'expires': w.now+1800, 'authorized': True, 'notice': NOTICE}
    w.admission.configure(w.ws['id'], w.policy, w.actor)
    monkeypatch.setattr('agent_market.reliability_admission.clock', lambda: w.now)
    app = FastAPI(); app.include_router(router_for(w.admission))
    with TestClient(app, base_url='https://pilot.test', raise_server_exceptions=False) as client:
        w.pilot_client = client; w.pilot_base = w.base+'/admission'
        yield w


def body(w, *, selected=True, start=0):
    for index in range(start, start+10000):
        identity = 'rld_'+format(index, '032x')
        from agent_market.workspace_access import _hash
        logical = _hash([w.ws['id'], identity])
        sample = int(hmac.new(w.admission.key, _canonical([w.ws['id'], logical, 1]).encode('ascii'), hashlib.sha256).hexdigest()[:8], 16)%100
        if (sample < 10) == selected:
            return {'revision': 1, 'logical_id': identity, 'input': {'query': 'Public docs', 'language': 'en', 'limit': 2},
                    'name': 'Single reviewed task', 'authorized': True, 'notice': NOTICE}
    raise AssertionError('deterministic sample fixture')


def test_offline_preparation_selection_deduplication_and_no_provider_calls(pilot):
    w = pilot; command = body(w); first = w.admission.prepare(w.ws['id'], command, w.actor)
    assert first['state'] == 'prepared' and first['preview']['max_calls'] == 1 and not w.calls
    again = w.admission.prepare(w.ws['id'], command, w.actor)
    assert again['id'] == first['id'] and again['replayed']
    assert w.admission.status(w.ws['id'], w.actor)['policy']['admitted'] == 1
    with pytest.raises(WorkspaceConflict):
        w.admission.prepare(w.ws['id'], command | {'name': 'Changed reviewed task'}, w.actor)
    assert not w.calls


def test_unselected_request_never_creates_a_private_execution_artifact(pilot):
    w = pilot; before = w.store.query('SELECT COUNT(*) FROM workspace_versions')[0][0]
    value = w.admission.prepare(w.ws['id'], body(w, selected=False), w.actor)
    assert value['state'] == 'not_selected' and value['snapshot_id'] is None and not w.calls
    assert w.store.query('SELECT COUNT(*) FROM workspace_versions')[0][0] == before
    with pytest.raises(WorkspaceConflict):
        w.admission.execute(w.ws['id'], value['id'], {'authorized': True, 'notice': NOTICE}, w.actor)


@pytest.mark.parametrize('change', ['evidence', 'policy', 'fallback', 'role', 'restore', 'expiry', 'unconfigured'])
def test_last_dispatch_guard_rejects_changed_authority_without_calling(pilot, change):
    w = pilot; prepared = w.admission.prepare(w.ws['id'], body(w), w.actor)
    with w.store.tx() as db:
        value = w.admission._admission(db, w.ws['id'], prepared['id'])
    if change == 'evidence': w.sources[value['resource_id']]['revoked'] = True
    elif change == 'policy': w.admission.configure(w.ws['id'], w.policy | {'revision': 1, 'enabled': False}, w.actor)
    elif change == 'fallback':
        monkey = pytest.MonkeyPatch(); monkey.setattr(w.routing, '_fallback_absent', lambda _: (_ for _ in ()).throw(WorkspaceConflict()))
    elif change == 'role':
        with w.store.tx() as db: db.execute("UPDATE workspace_memberships SET role='viewer',revision=revision+1 WHERE workspace_id=?", (w.ws['id'],))
    elif change == 'restore':
        with w.store.tx() as db: db.execute('INSERT INTO reliability_admission_restore_blocks VALUES(?)', (value['id'],))
    elif change == 'expiry': w.now = value['expires']
    elif change == 'unconfigured': w.admission.enabled = False
    try:
        with pytest.raises((WorkspaceDenied, WorkspaceConflict)):
            w.admission.execute(w.ws['id'], prepared['id'], {'authorized': True, 'notice': NOTICE}, w.actor)
        assert not w.calls
    finally:
        if change == 'fallback': monkey.undo()


def test_generic_ticket_cannot_bypass_reserved_pilot_ticket_or_session(pilot):
    w = pilot; prepared = w.admission.prepare(w.ws['id'], body(w), w.actor)
    extra = w.execution.prepare(w.ws['id'], prepared['draft_id'], prepared['snapshot_id'], {'snapshot_revision': 1}, w.actor)
    with pytest.raises(WorkspaceDenied):
        w.execution.execute(w.ws['id'], prepared['draft_id'], prepared['snapshot_id'],
                            {'ticket_id': extra['ticket_id'], 'authorized': True, 'notice': RUN_NOTICE}, w.actor)
    assert not w.calls


@pytest.mark.parametrize('corrupt_payload', [False, True])
def test_new_snapshot_of_pilot_draft_cannot_escape_execution_or_sdk_policy(pilot, corrupt_payload):
    from agent_market.workspace_release import WorkspaceReleases
    w = pilot; prepared = w.admission.prepare(w.ws['id'], body(w), w.actor)
    fresh = w.access.create_snapshot(w.ws['id'], prepared['draft_id'], {'draft_revision': 1}, w.actor)
    extra = w.execution.prepare(w.ws['id'], prepared['draft_id'], fresh['id'], {'snapshot_revision': 1}, w.actor)
    w.admission.configure(w.ws['id'], w.policy | {'revision': 1, 'enabled': False}, w.actor)
    if corrupt_payload:
        with w.store.tx() as db:
            db.execute("UPDATE reliability_admissions SET payload='{}' WHERE id=?", (prepared['id'],))
    with pytest.raises((WorkspaceDenied, WorkspaceConflict)):
        w.execution.execute(w.ws['id'], prepared['draft_id'], fresh['id'],
            {'ticket_id': extra['ticket_id'], 'authorized': True, 'notice': RUN_NOTICE}, w.actor)
    releases = WorkspaceReleases(w.execution)
    with w.store.tx() as db:
        with pytest.raises((WorkspaceDenied, WorkspaceConflict)):
            releases._release_profile(db, fresh['id'], prepared['preview']['resource_id'], prepared['preview']['tool'])
    assert not w.calls


def test_pilot_api_requires_named_owner_session_and_same_origin(pilot):
    w = pilot; client = w.pilot_client; path = w.pilot_base+'/prepare'
    assert client.get(w.pilot_base+'/status').status_code == 401
    assert client.post(path, headers=w.headers['viewer'], json=body(w)).status_code == 404
    assert client.post(path, headers=w.headers['owner'] | {'Origin': 'https://other.test'}, json=body(w)).status_code == 403
    response = client.post(path, headers=w.headers['owner'], json=body(w))
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    assert w.actor.session_ref not in response.text and 'source_hash' not in response.text
    assert client.post(path, headers=w.headers['owner'], json=body(w) | {'endpoint': 'https://forbidden.test'}).status_code == 400


@pytest.mark.parametrize('uncertain', [False, True])
def test_actual_mcp_packet_is_dispatched_once_even_with_concurrent_replay(pilot, uncertain):
    w = pilot
    from tests.test_workflow_fallback import output
    w.remote.tools = json.loads(w.store.resource(w.rids[0])['usage_full_tools']); w.remote.call_result = output()
    if uncertain:
        w.control['mode'] = 'timeout'
    prepared = w.admission.prepare(w.ws['id'], body(w), w.actor)
    command = {'authorized': True, 'notice': NOTICE}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: w.admission.execute(w.ws['id'], prepared['id'], command, w.actor), range(2)))
    assert w.calls.count('tools/call') == 1, (w.calls, results)
    assert all(result['replacement_calls'] == 0 for result in results)
    assert any(result['run']['status'] == ('unknown' if uncertain else 'succeeded') for result in results), results
    again = w.admission.execute(w.ws['id'], prepared['id'], command, w.actor)
    assert again['replayed'] and w.calls.count('tools/call') == 1


def test_invalid_contract_output_is_committed_failed_in_original_run_without_replacement(pilot):
    w = pilot; w.remote.tools = json.loads(w.store.resource(w.rids[0])['usage_full_tools'])
    w.remote.call_result = {'structuredContent': {'unexpected': 'shape'}, 'content': []}
    prepared = w.admission.prepare(w.ws['id'], body(w), w.actor)
    result = w.admission.execute(w.ws['id'], prepared['id'], {'authorized': True, 'notice': NOTICE}, w.actor)
    assert result['run']['status'] == 'failed' and result['run']['error_code'] == 'OUTPUT_REJECTED'
    assert result['run']['output'] is None and w.calls.count('tools/call') == 1
    retained = w.execution.run(w.ws['id'], prepared['draft_id'], prepared['snapshot_id'], result['run']['id'], w.actor)
    assert retained['status'] == 'failed' and retained['output'] is None
    assert w.admission.execute(w.ws['id'], prepared['id'], {'authorized': True, 'notice': NOTICE}, w.actor)['replayed']
    assert w.calls.count('tools/call') == 1


@pytest.mark.parametrize('revoke_after_packet', [False, True])
def test_contract_failure_and_late_authority_withdrawal_match_atomic_meter(pilot, revoke_after_packet):
    from agent_market.workspace_metering import WorkspaceMetering, NOTICE as METER_NOTICE
    from tests.test_workflow_fallback import output
    w = pilot; meter = WorkspaceMetering(w.access, w.execution); w.execution.meter = meter
    meter.configure(w.ws['id'], {'revision': 0, 'enabled': True, 'units_per_success': 7,
        'max_runs': 3, 'ttl_seconds': 3600, 'authorized': True, 'notice': METER_NOTICE}, w.actor)
    w.remote.tools = json.loads(w.store.resource(w.rids[0])['usage_full_tools'])
    w.remote.call_result = output() if revoke_after_packet else {'structuredContent': {'unexpected': 'shape'}, 'content': []}
    original = w.remote.handle_request
    def response(request):
        result = original(request)
        if revoke_after_packet and json.loads(request.content or b'{}').get('method') == 'tools/call':
            w.admission.configure(w.ws['id'], w.policy | {'revision': 1, 'enabled': False}, w.actor)
        return result
    w.remote.handle_request = response
    prepared = w.admission.prepare(w.ws['id'], body(w), w.actor)
    result = w.admission.execute(w.ws['id'], prepared['id'], {'authorized': True, 'notice': NOTICE}, w.actor)
    expected = 'unknown' if revoke_after_packet else 'failed'
    summary = meter.summary(w.ws['id'], w.actor)
    assert result['run']['status'] == expected and summary['outcomes'] == {expected: 1}
    assert summary['balanced'] and summary['simulated_units'] == 0 and summary['attempts'] == 1
    assert w.calls.count('tools/call') == 1
    assert w.admission.execute(w.ws['id'], prepared['id'], {'authorized': True, 'notice': NOTICE}, w.actor)['replayed']
    assert w.calls.count('tools/call') == 1
