"""Concrete gateway evaluation and finite lifecycle use only synthetic transports."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from agent_market.concierge.proxy import McpProxy
from agent_market.reliability_evaluation import NOTICE
from agent_market.reliability_evaluation_worker import EvaluationWorker, McpReadEvaluator
from agent_market.workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid
from tests.test_reliability_controls import controls, setup_plan, reserve, prepare, dispatch, private_api


@pytest.fixture
def worker_world(controls, monkeypatch):
    w = controls
    monkeypatch.setattr('agent_market.reliability_evaluation_worker.clock', lambda: w.now)
    w.eval_calls = []
    w.eval_control = {'during_list': None, 'during_call': None, 'mode': 'ok'}
    spec = json.loads(w.store.resource(w.rids[0])['usage_full_tools'])

    def transport(request):
        body = json.loads(request.content)
        method = body['method']
        w.eval_calls.append(method)
        if method == 'server/discover':
            result = {'protocolVersion': '2026-07-28'}
        elif method == 'tools/list':
            if w.eval_control['during_list']:
                w.eval_control['during_list']()
            result = {'tools': spec}
        elif method == 'tools/call':
            if w.eval_control['during_call']:
                w.eval_control['during_call']()
            if w.eval_control['mode'] == 'timeout':
                raise httpx.ReadTimeout('Synthetic response loss', request=request)
            if w.eval_control['mode'] == 'tool_error':
                return httpx.Response(200, json={'jsonrpc': '2.0', 'id': body['id'],
                    'error': {'code': -32603, 'message': 'Synthetic failure'}})
            result = {'structuredContent': {'items': [], 'partial': False}}
            if w.eval_control['mode'] == 'invalid':
                result = {'structuredContent': {'invalid': True}}
        else:
            raise AssertionError(method)
        return httpx.Response(200, json={'jsonrpc': '2.0', 'id': body['id'], 'result': result})

    client = httpx.Client(transport=httpx.MockTransport(transport))
    w.runtime.proxy = McpProxy(w.store, allow_private=True, http=client)
    w.adapter = McpReadEvaluator(w.evaluation, enabled=True)
    w.evaluation.read_evaluator = w.adapter
    w.evaluation.evaluator_authorizer = w.adapter.authorizer
    w.worker = EvaluationWorker(w.evaluation, enabled=True)
    w.evaluation.worker = w.worker
    yield w
    w.worker.close()
    client.close()


def activate(w):
    setup_plan(w)
    w.worker.activate(w.ws['id'], w.actor, 1)


def test_default_adapter_and_worker_never_call_or_start(worker_world):
    w = worker_world
    adapter = McpReadEvaluator(w.evaluation)
    w.evaluation.read_evaluator, w.evaluation.evaluator_authorizer = adapter, adapter.authorizer
    worker = EvaluationWorker(w.evaluation)
    assert not adapter.configured and not worker.start()
    assert worker.tick() == {'attempted_jobs': 0, 'active_workspaces': 0, 'enabled': False}
    assert not w.eval_calls
    setup_plan(w)
    with pytest.raises(WorkspaceConflict):
        worker.activate(w.ws['id'], w.actor, 1)
    job = reserve(w)['jobs'][0]
    assert prepare(w, job['id']).status_code == 200
    assert dispatch(w, job['id']).status_code == 409
    assert not w.eval_calls


@pytest.mark.parametrize('field,value', [('enabled', 1), ('enabled', 'true'), ('max_seconds', True), ('max_seconds', 13)])
def test_adapter_configuration_is_typed(worker_world, field, value):
    with pytest.raises(WorkspaceInvalid):
        McpReadEvaluator(worker_world.evaluation, **{field: value})


def test_concrete_gateway_is_single_call_and_does_not_assert_independent_quality(worker_world):
    w = worker_world
    activate(w)
    first = w.worker.tick()
    again = w.worker.tick()
    assert first['attempted_jobs'] == 1 and again['attempted_jobs'] == 0
    assert w.eval_calls == ['server/discover', 'tools/list', 'tools/call']
    state = w.evaluation.status(w.ws['id'], w.actor)
    assert state['jobs'][0]['state'] == 'completed'
    assert state['quality_status'] == 'not_inferred_from_scheduler'
    assert w.worker.status(w.ws['id'], w.actor)['quality_status'] == 'not_independently_assessed_by_worker'
    assert 'reo_' in w.store.query('SELECT payload FROM reliability_eval_jobs')[0][0]


@pytest.mark.parametrize('mode,outcome', [('timeout', 'unknown'), ('tool_error', 'failed'), ('invalid', 'failed')])
def test_response_loss_invalid_output_and_tool_error_do_not_retry(worker_world, mode, outcome):
    w = worker_world
    activate(w)
    w.eval_control['mode'] = mode
    w.worker.tick()
    w.worker.tick()
    assert w.eval_calls.count('tools/call') == 1
    assert w.evaluation.status(w.ws['id'], w.actor)['jobs'][0]['state'] == outcome


@pytest.mark.parametrize('revocation', ['control', 'cancel', 'expiry', 'schema', 'stop', 'deactivate'])
def test_final_packet_fence_blocks_changed_authority(worker_world, revocation):
    w = worker_world
    activate(w)
    def revoke():
        if revocation == 'control':
            w.evaluation.set_control(w.ws['id'], {'revision': 1, 'enabled': False, 'authorized': True, 'notice': NOTICE}, w.actor)
        elif revocation == 'cancel':
            job = w.evaluation.status(w.ws['id'], w.actor)['jobs'][0]
            w.evaluation.cancel(w.ws['id'], job['id'], {'authorized': True, 'notice': NOTICE}, w.actor)
        elif revocation == 'expiry':
            w.now += 3601
        elif revocation == 'schema':
            with w.store.tx() as db:
                db.execute('UPDATE resources SET active=0 WHERE id=?', (w.rids[0],))
        elif revocation == 'stop':
            w.worker.close()
        else:
            w.worker.deactivate(w.ws['id'])
    w.eval_control['during_list'] = revoke
    w.worker.tick()
    assert 'tools/call' not in w.eval_calls
    assert w.evaluation.status(w.ws['id'], w.actor)['jobs'][0]['state'] == 'unknown'


def test_concurrent_ticks_and_new_worker_never_replay_dispatched_job(worker_world):
    w = worker_world
    activate(w)
    entered, release = threading.Event(), threading.Event()
    w.eval_control['during_call'] = lambda: (entered.set(), release.wait(2))
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(w.worker.tick)
        assert entered.wait(2)
        with pytest.raises(WorkspaceConflict):
            w.worker.tick()
        replacement = EvaluationWorker(w.evaluation, enabled=True)
        replacement.activate(w.ws['id'], w.actor, 1)
        assert replacement.tick()['attempted_jobs'] == 0
        release.set()
        assert first.result()['attempted_jobs'] == 1
        replacement.close()
    assert w.eval_calls.count('tools/call') == 1


def test_restart_requires_fresh_activation_and_can_resume_only_prepared(worker_world):
    w = worker_world
    activate(w)
    job = reserve(w)['jobs'][0]
    assert prepare(w, job['id']).status_code == 200
    w.worker.close()
    replacement = EvaluationWorker(w.evaluation, enabled=True)
    assert replacement.tick()['attempted_jobs'] == 0
    replacement.activate(w.ws['id'], w.actor, 1)
    assert replacement.tick()['attempted_jobs'] == 1
    assert replacement.tick()['attempted_jobs'] == 0
    assert w.eval_calls.count('tools/call') == 1
    replacement.close()


def test_session_withdrawal_deactivates_without_handshake(worker_world):
    w = worker_world
    activate(w)
    with w.store.tx() as db:
        db.execute('DELETE FROM admin_sessions WHERE token=?', (w.actor.session_ref,))
    assert w.worker.tick()['active_workspaces'] == 0
    assert not w.eval_calls


def test_restore_tombstone_blocks_worker_and_does_not_revive_on_new_instance(worker_world):
    w = worker_world
    activate(w)
    with w.store.tx() as db:
        db.execute('INSERT INTO reliability_controls_restore_blocks VALUES(?)', ('eval_plan:'+w.ws['id']+':1',))
    assert w.worker.tick()['active_workspaces'] == 0
    assert not w.eval_calls
    replacement = EvaluationWorker(w.evaluation, enabled=True)
    with pytest.raises(WorkspaceConflict):
        replacement.activate(w.ws['id'], w.actor, 1)
    replacement.close()


def test_legacy_arbitrary_adapter_never_powers_automatic_worker(worker_world):
    w = worker_world
    setup_plan(w)
    w.evaluation.read_evaluator = lambda envelope: {}
    w.evaluation.evaluator_authorizer = lambda *args: True
    with pytest.raises(WorkspaceConflict):
        w.worker.activate(w.ws['id'], w.actor, 1)
    assert not w.eval_calls


def test_worker_start_close_is_idempotent_and_does_not_implicitly_activate(worker_world):
    w = worker_world
    assert w.worker.start() and w.worker.start() and w.worker.running
    assert w.worker.close() and w.worker.close() and not w.worker.running
    assert not w.worker.start() and not w.eval_calls


def test_explicit_worker_commands_recheck_notice_revision_and_owner(worker_world, monkeypatch):
    w = worker_world
    setup_plan(w)
    body = {'revision': 1, 'authorized': True, 'notice': NOTICE}
    for changed in (body | {'authorized': False}, body | {'revision': True}, body | {'notice': 'old'}, body | {'enabled': True}):
        with pytest.raises(WorkspaceInvalid):
            w.worker.activate_for(w.ws['id'], changed, w.actor)
    with pytest.raises(WorkspaceConflict):
        w.worker.activate_for(w.ws['id'], body | {'revision': 0}, w.actor)
    monkeypatch.setattr(w.worker, '_run', lambda: w.worker._stop.wait(2))
    state = w.worker.activate_for(w.ws['id'], body, w.actor)
    assert state['active'] and state['running']
    w.evaluation.set_control(w.ws['id'], {'revision': 1, 'enabled': False, 'authorized': True, 'notice': NOTICE}, w.actor)
    assert not w.worker.status(w.ws['id'], w.actor)['active']
    assert not w.worker.deactivate_for(w.ws['id'], body, w.actor)['active']
    assert not w.eval_calls


def test_worker_activation_fails_closed_when_thread_cannot_start(worker_world, monkeypatch):
    w = worker_world
    setup_plan(w)
    monkeypatch.setattr(w.worker, 'start', lambda: False)
    with pytest.raises(WorkspaceConflict):
        w.worker.activate_for(w.ws['id'], {'revision': 1, 'authorized': True, 'notice': NOTICE}, w.actor)
    assert not w.worker.status(w.ws['id'], w.actor)['active'] and not w.eval_calls


def test_deactivation_after_sent_packet_keeps_unknown_and_never_replays(worker_world):
    w = worker_world
    activate(w)
    w.eval_control['during_call'] = lambda: w.worker.deactivate(w.ws['id'])
    assert w.worker.tick()['attempted_jobs'] == 1
    assert w.evaluation.status(w.ws['id'], w.actor)['jobs'][0]['state'] == 'unknown'
    w.worker.activate(w.ws['id'], w.actor, 1)
    assert w.worker.tick()['attempted_jobs'] == 0
    assert w.eval_calls.count('tools/call') == 1
