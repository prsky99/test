"""Configured circuits reuse existing signed jobs on isolated mock transports only."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from agent_market.reliability_circuit import NOTICE, ReliabilityCircuit, quarantine_circuits
from agent_market.reliability_evaluation import NOTICE as EVALUATION_NOTICE
from agent_market.workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid, _canonical, _hash
from tests.test_reliability_controls import controls, private_api, setup_plan, reserve, prepare, dispatch, routing_policy, post
from tests.test_reliability_evaluation_worker import worker_world


@pytest.fixture
def circuit(worker_world, monkeypatch):
    w = worker_world
    monkeypatch.setattr('agent_market.reliability_circuit.clock', lambda: w.now)
    w.circuit = ReliabilityCircuit(w.access, w.evaluation, enabled=True,
        evidence_guard=lambda db, ws, rid, actor: copy.deepcopy(w.sources[rid]))
    return w


def config(w, **changes):
    return {'revision': 0, 'resource_id': w.rids[0], 'contract_id': 'docs.search.v1',
        'environment': 'isolated', 'enabled': True, 'failure_count': 1, 'unknown_count': 1,
        'sample_window_seconds': 1200, 'sample_max_age_seconds': 900, 'open_seconds': 1,
        'probe_max_age_seconds': 300, 'expires': w.now+3500, 'authorized': True, 'notice': NOTICE, **changes}


def command(revision, **fields):
    return {'revision': revision, 'authorized': True, 'notice': NOTICE, **fields}


def state(w):
    return w.circuit.status(w.ws['id'], w.rids[0], w.actor)['circuit']


def evaluate(w, mode='ok'):
    w.eval_control['mode'] = mode
    job = reserve(w)['jobs'][0]
    assert prepare(w, job['id']).status_code == 200
    response = dispatch(w, job['id'])
    assert response.status_code == 200, response.text
    return job['id'], response.json()['result']


def next_window(w):
    w.now = (int(w.now//600)+1)*600+1


def opened(w, mode='tool_error'):
    w.circuit.configure(w.ws['id'], config(w), w.actor)
    setup_plan(w)
    ref, result = evaluate(w, mode)
    assert result['state'] in ('failed', 'unknown')
    result = w.circuit.ingest(w.ws['id'], w.rids[0], command(1, source_ref=ref), w.actor)
    assert result['state'] == 'open'
    return result


def bind(w):
    next_window(w)
    job = reserve(w)['jobs'][0]
    value = w.circuit.bind_probe(w.ws['id'], w.rids[0], command(state(w)['revision'], job_id=job['id']), w.actor)
    assert value['state'] == 'half_open'
    return job['id'], value


def test_default_off_and_unconfigured_projection_is_exact(circuit):
    w = circuit
    disabled = ReliabilityCircuit(w.access, w.evaluation,
        evidence_guard=lambda db, ws, rid, actor: copy.deepcopy(w.sources[rid]))
    assert disabled.get_agent_projection(w.ws['id'], w.rids[0], w.actor) == w.sources[w.rids[0]]
    with pytest.raises(WorkspaceConflict):
        disabled.configure(w.ws['id'], config(w), w.actor)
    assert not w.eval_calls and not w.calls


@pytest.mark.parametrize('change', [
    {'failure_count': True}, {'failure_count': 0}, {'unknown_count': 101}, {'open_seconds': 0},
    {'probe_max_age_seconds': 86401}, {'expires': float('nan')}, {'authorized': False},
    {'notice': 'legacy'}, {'enabled': 1}, {'resource_id': True}, {'extra': 'unexpected'},
])
def test_configuration_has_no_inferred_thresholds_or_coercion(circuit, change):
    w = circuit
    with pytest.raises(WorkspaceInvalid):
        w.circuit.configure(w.ws['id'], config(w, **change), w.actor)
    assert not w.eval_calls


def test_configuration_requires_owner_current_base_evidence_and_explicit_environment(circuit):
    w = circuit
    w.sources[w.rids[0]]['qualified_operating_evidence'] = False
    for changes in ({'environment': 'operating'}, {'contract_id': 'news.search.v1'}):
        with pytest.raises(WorkspaceConflict):
            w.circuit.configure(w.ws['id'], config(w, **changes), w.actor)
    w.sources[w.rids[0]]['revoked'] = True
    with pytest.raises(WorkspaceConflict):
        w.circuit.configure(w.ws['id'], config(w), w.actor)
    assert not w.eval_calls


def test_exact_cas_and_concurrent_configuration_has_one_winner(circuit):
    w = circuit
    def save(_):
        try:
            return w.circuit.configure(w.ws['id'], config(w), w.actor)['revision']
        except WorkspaceConflict:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(save, range(2)), key=lambda x: x is None) == [1, None]
    assert len(w.store.query('SELECT * FROM reliability_circuit_states')) == 1
    assert not w.eval_calls


def test_threshold_opens_and_time_unrelated_success_and_config_do_not_close(circuit):
    w = circuit; value = opened(w)
    count = len(w.eval_calls); w.now += 2
    assert w.circuit.get_agent_projection(w.ws['id'], w.rids[0], w.actor)['circuit_state'] == 'open'
    updated = w.circuit.configure(w.ws['id'], config(w, revision=value['revision'], failure_count=10), w.actor)
    assert updated['state'] == 'open' and updated['open_epoch'] > value['open_epoch']
    next_window(w); ref, result = evaluate(w)
    assert result['state'] == 'completed'
    observed = w.circuit.ingest(w.ws['id'], w.rids[0], command(updated['revision'], source_ref=ref), w.actor)
    assert observed['state'] == 'open' and len(w.eval_calls) == count+3
    assert w.circuit.status(w.ws['id'], w.rids[0], w.actor)['provider_calls'] == 0


def test_separately_approved_bound_job_can_close_only_after_verified_response(circuit):
    w = circuit; opened(w)
    ref, value = bind(w); before = len(w.eval_calls)
    assert w.circuit.get_agent_projection(w.ws['id'], w.rids[0], w.actor)['circuit_state'] == 'half_open'
    waiting = w.circuit.refresh_probe(w.ws['id'], w.rids[0], command(value['revision']), w.actor)
    assert waiting['waiting'] and len(w.eval_calls) == before
    w.eval_control['mode'] = 'ok'
    assert prepare(w, ref).status_code == dispatch(w, ref).status_code == 200
    result = w.circuit.refresh_probe(w.ws['id'], w.rids[0], command(value['revision']), w.actor)
    assert result['state'] == 'closed' and result['probe_outcome'] == 'completed'
    assert w.eval_calls.count('tools/call') == 2
    with pytest.raises(WorkspaceConflict):
        w.circuit.refresh_probe(w.ws['id'], w.rids[0], command(result['revision']), w.actor)
    assert dispatch(w, ref).json()['result']['state'] == 'completed'
    assert w.eval_calls.count('tools/call') == 2


@pytest.mark.parametrize('mode,outcome', [('timeout', 'unknown'), ('invalid', 'failed'), ('tool_error', 'failed')])
def test_failed_or_unknown_probe_never_closes_or_replays(circuit, mode, outcome):
    w = circuit; opened(w); ref, value = bind(w)
    w.eval_control['mode'] = mode
    assert prepare(w, ref).status_code == dispatch(w, ref).status_code == 200
    result = w.circuit.refresh_probe(w.ws['id'], w.rids[0], command(value['revision']), w.actor)
    assert result['state'] == 'open' and result['probe_outcome'] == outcome
    assert dispatch(w, ref).json()['result']['state'] == outcome
    w.now += 2
    with pytest.raises(WorkspaceConflict):
        w.circuit.bind_probe(w.ws['id'], w.rids[0], command(result['revision'], job_id=ref), w.actor)
    assert w.eval_calls.count('tools/call') == 2


def test_generic_completed_and_client_profile_marker_are_not_probe_evidence(circuit):
    w = circuit; opened(w); ref, value = bind(w)
    before = len(w.eval_calls)
    w.evaluation.read_evaluator = lambda envelope: {'outcome': 'completed', 'observed_at': w.now,
        'evidence_ref': 'generic_self_report', 'response_proof': {'profile': 'approved-mcp-response-observation-v1'}}
    w.evaluation.evaluator_authorizer = lambda *args: True
    assert prepare(w, ref).status_code == dispatch(w, ref).status_code == 200
    with w.access._tx(w.actor) as (db, _):
        assert 'response_proof' not in w.evaluation._job(db, w.ws['id'], ref)
    result = w.circuit.refresh_probe(w.ws['id'], w.rids[0], command(value['revision']), w.actor)
    assert result['state'] == 'open' and len(w.eval_calls) == before


@pytest.mark.parametrize('fault', ['old_job', 'completed_job', 'cooldown', 'stale_revision'])
def test_probe_requires_new_post_epoch_reserved_job_and_exact_cas(circuit, fault):
    w = circuit
    if fault == 'old_job':
        w.circuit.configure(w.ws['id'], config(w), w.actor); setup_plan(w)
        old = reserve(w)['jobs'][0]
        with w.access._tx(w.actor, write=True) as (db, _):
            value = w.circuit._read(db, w.ws['id'], w.rids[0])
            value.update(state='open', opened_at=w.now+1, open_epoch=1)
            w.circuit._save(db, value, w.actor, 'fixture')
        w.now += 3; ref = old['id']; revision = 1
    else:
        opened(w); revision = state(w)['revision']
        if fault == 'cooldown':
            ref = reserve(w)['jobs'][0]['id']
        else:
            next_window(w); ref = reserve(w)['jobs'][0]['id']
            if fault == 'completed_job':
                assert prepare(w, ref).status_code == dispatch(w, ref).status_code == 200
            else:
                revision -= 1
    before = len(w.eval_calls)
    with pytest.raises(WorkspaceConflict):
        w.circuit.bind_probe(w.ws['id'], w.rids[0], command(revision, job_id=ref), w.actor)
    assert len(w.eval_calls) == before


@pytest.mark.parametrize('fault', ['policy', 'control', 'corpus', 'expiry', 'pin', 'payload', 'restore', 'base_evidence'])
def test_late_or_changed_probe_never_closes(circuit, fault):
    w = circuit; opened(w); ref, value = bind(w)
    w.eval_control['mode'] = 'ok'
    assert prepare(w, ref).status_code == dispatch(w, ref).status_code == 200
    if fault == 'policy':
        w.circuit.configure(w.ws['id'], config(w, revision=value['revision']), w.actor)
    elif fault == 'control':
        w.evaluation.set_control(w.ws['id'], command(1) | {'notice': EVALUATION_NOTICE, 'enabled': False}, w.actor)
    elif fault == 'corpus':
        with w.store.tx() as db:
            db.execute("UPDATE reliability_eval_jobs SET payload='{}' WHERE id=?", (ref,))
    elif fault == 'expiry':
        w.now += 301
    elif fault == 'pin':
        with w.store.tx() as db:
            db.execute('UPDATE resources SET active=0 WHERE id=?', (w.rids[0],))
    elif fault == 'payload':
        with w.store.tx() as db:
            db.execute("UPDATE reliability_circuit_claims SET payload='{}' WHERE source_ref=?", (ref,))
    elif fault == 'base_evidence':
        w.sources[w.rids[0]]['revoked'] = True
    else:
        with w.store.tx() as db:
            quarantine_circuits(db)
    try:
        result = w.circuit.refresh_probe(w.ws['id'], w.rids[0], command(value['revision']), w.actor)
    except (WorkspaceDenied, WorkspaceConflict):
        pass
    else:
        assert result['state'] == 'open'
    assert w.circuit.get_agent_projection(w.ws['id'], w.rids[0], w.actor)['circuit_state'] != 'closed'
    assert w.eval_calls.count('tools/call') == 2


def test_restore_and_disable_preserve_history_and_require_new_probe_on_reapproval(circuit):
    w = circuit; w.circuit.configure(w.ws['id'], config(w), w.actor)
    before = w.store.query('SELECT payload,signature FROM reliability_circuit_states')[0]
    with w.store.tx() as db:
        quarantine_circuits(db)
    assert w.store.query('SELECT payload,signature FROM reliability_circuit_states')[0] == before
    assert w.circuit.get_agent_projection(w.ws['id'], w.rids[0], w.actor)['circuit_state'] == 'quarantined'
    value = w.circuit.configure(w.ws['id'], config(w, revision=1), w.actor)
    assert value['state'] == 'open' and value['generation'] == 2
    value = w.circuit.configure(w.ws['id'], config(w, revision=2, enabled=False), w.actor)
    assert w.circuit.get_agent_projection(w.ws['id'], w.rids[0], w.actor)['circuit_state'] == 'quarantined'
    value = w.circuit.configure(w.ws['id'], config(w, revision=3), w.actor)
    assert value['state'] == 'open' and not w.eval_calls


def test_duplicate_observation_is_not_counted_twice(circuit):
    w = circuit; opened(w)
    ref = w.evaluation.status(w.ws['id'], w.actor)['jobs'][0]['id']
    again = w.circuit.ingest(w.ws['id'], w.rids[0], command(2, source_ref=ref), w.actor)
    assert again['replayed'] and again['revision'] == 2
    assert w.store.query('SELECT COUNT(*) FROM reliability_circuit_claims')[0][0] == 1


def test_shared_projection_changes_routing_hash_and_correlated_host_exclusion(circuit):
    w = circuit
    assert post(w, '/routing/configure', routing_policy(w, resource_ids=w.rids, share_resource_ids=w.rids)).status_code == 200
    w.routing.evidence_source = w.circuit.get_agent_projection
    before = w.circuit.get_agent_projection(w.ws['id'], w.rids[0], w.actor)
    with w.access._tx(w.actor) as (db, _):
        assert before == w.circuit.current_projection_in_transaction(db, w.ws['id'], w.rids[0], w.actor)
    opened(w); ref, _ = bind(w)
    after = w.circuit.get_agent_projection(w.ws['id'], w.rids[0], w.actor)
    assert _hash(before) != _hash(after)
    decision = w.routing.decide(w.ws['id'], {'revision': 1, 'logical_id': 'rld_'+'a'*32,
        'authorized': True, 'notice': 'offline-decision-shadow-only-v1'}, w.actor)
    assert decision['selected_resource_id'] == w.rids[1]
    assert {item['resource_id']: item['reason'] for item in decision['excluded']}[w.rids[2]] == 'correlated_host_failure'
    assert w.eval_calls.count('tools/call') == 1


def test_composer_requires_exact_store_transaction(circuit):
    w = circuit
    with pytest.raises(WorkspaceConflict):
        w.circuit.current_projection_in_transaction(w.store._db, w.ws['id'], w.rids[0], w.actor)
    assert not w.eval_calls


def test_unsigned_resource_locator_cannot_hide_configured_circuit(circuit):
    w = circuit; w.circuit.configure(w.ws['id'], config(w), w.actor)
    with w.store.tx() as db:
        db.execute('UPDATE reliability_circuit_states SET resource_id=? WHERE workspace_id=?', (w.rids[1], w.ws['id']))
    with pytest.raises(WorkspaceConflict):
        w.circuit.get_agent_projection(w.ws['id'], w.rids[0], w.actor)
    assert not w.eval_calls


def test_consumed_source_capacity_fails_closed_without_unbounded_history(circuit, monkeypatch):
    w = circuit
    monkeypatch.setattr('agent_market.reliability_circuit.MAX_CLAIMS', 1)
    opened(w)
    assert w.circuit.get_agent_projection(w.ws['id'], w.rids[0], w.actor)['circuit_state'] == 'quarantined'
    next_window(w); ref = reserve(w)['jobs'][0]['id']
    with pytest.raises(WorkspaceConflict):
        w.circuit.bind_probe(w.ws['id'], w.rids[0], command(2, job_id=ref), w.actor)
    assert w.store.query('SELECT COUNT(*) FROM reliability_circuit_claims')[0][0] == 1
