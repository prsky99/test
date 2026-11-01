"""Circuit composition must fence the existing single-call execution transaction."""
import copy
import json

import pytest

from agent_market.reliability_admission import NOTICE as ADMISSION_NOTICE
from agent_market.reliability_circuit import ReliabilityCircuit
from agent_market.workspace_access import WorkspaceConflict, WorkspaceDenied
from tests.test_reliability_admission import pilot, body
from tests.test_reliability_circuit import config
from tests.test_reliability_controls import controls, private_api


@pytest.fixture
def circuit_pilot(pilot, monkeypatch):
    w = pilot
    monkeypatch.setattr('agent_market.reliability_circuit.clock', lambda: w.now)
    w.circuit = ReliabilityCircuit(w.access, w.evaluation, enabled=True, execution=w.execution,
        evidence_guard=lambda db, ws, rid, actor: copy.deepcopy(w.sources[rid]))
    w.routing.evidence_source = w.circuit.get_agent_projection
    w.admission.evidence_guard = w.circuit.current_projection_in_transaction
    w.circuit.configure(w.ws['id'], config(w), w.actor)
    return w


def pause(w):
    w.circuit.configure(w.ws['id'], config(w, revision=1, enabled=False), w.actor)


def test_circuit_source_hash_change_before_execute_rejects_without_call(circuit_pilot):
    w = circuit_pilot
    prepared = w.admission.prepare(w.ws['id'], body(w), w.actor)
    pause(w)
    with pytest.raises((WorkspaceDenied, WorkspaceConflict)):
        w.admission.execute(w.ws['id'], prepared['id'], {'authorized': True, 'notice': ADMISSION_NOTICE}, w.actor)
    assert not w.calls


@pytest.mark.parametrize('after_packet', [False, True])
def test_circuit_change_at_packet_or_terminal_fence_preserves_one_call_and_unknown(circuit_pilot, after_packet):
    from agent_market.workspace_metering import WorkspaceMetering, NOTICE as METER_NOTICE
    w = circuit_pilot
    w.remote.tools = json.loads(w.store.resource(w.rids[0])['usage_full_tools'])
    w.remote.call_result = {'structuredContent': {'items': [], 'partial': False}}
    meter = WorkspaceMetering(w.access, w.execution); w.execution.meter = meter
    meter.configure(w.ws['id'], {'revision': 0, 'enabled': True, 'units_per_success': 7,
        'max_runs': 3, 'ttl_seconds': 3600, 'authorized': True, 'notice': METER_NOTICE}, w.actor)
    if after_packet:
        original = w.remote.handle_request
        def response(request):
            result = original(request)
            if json.loads(request.content or b'{}').get('method') == 'tools/call':
                pause(w)
            return result
        w.remote.handle_request = response
    else:
        w.control['during_list'] = lambda: pause(w)
    prepared = w.admission.prepare(w.ws['id'], body(w), w.actor)
    result = w.admission.execute(w.ws['id'], prepared['id'], {'authorized': True, 'notice': ADMISSION_NOTICE}, w.actor)
    expected = 'unknown' if after_packet else 'denied'
    assert result['run']['status'] == expected and result['replacement_calls'] == 0
    assert w.calls.count('tools/call') == int(after_packet)
    summary = meter.summary(w.ws['id'], w.actor)
    assert summary['balanced'] and summary['simulated_units'] == 0
    assert summary['outcomes'] == {expected: 1}
    again = w.admission.execute(w.ws['id'], prepared['id'], {'authorized': True, 'notice': ADMISSION_NOTICE}, w.actor)
    assert again['replayed'] and again['run']['status'] == expected
    assert w.calls.count('tools/call') == int(after_packet)


def test_completed_result_stays_readable_after_circuit_pause(circuit_pilot):
    w = circuit_pilot
    w.remote.tools = json.loads(w.store.resource(w.rids[0])['usage_full_tools'])
    w.remote.call_result = {'structuredContent': {'items': [], 'partial': False}}
    prepared = w.admission.prepare(w.ws['id'], body(w), w.actor)
    result = w.admission.execute(w.ws['id'], prepared['id'], {'authorized': True, 'notice': ADMISSION_NOTICE}, w.actor)
    assert result['run']['status'] == 'succeeded'
    pause(w)
    again = w.admission.execute(w.ws['id'], prepared['id'], {'authorized': True, 'notice': ADMISSION_NOTICE}, w.actor)
    assert again['replayed'] and again['run']['id'] == result['run']['id']
    assert w.calls.count('tools/call') == 1


def test_signed_private_attempt_can_trip_but_cannot_close_circuit(circuit_pilot):
    import time
    from agent_market.reliability_circuit import NOTICE as CIRCUIT_NOTICE
    w = circuit_pilot
    w.remote.tools = json.loads(w.store.resource(w.rids[0])['usage_full_tools'])
    w.remote.call_result = {'structuredContent': {'invalid': True}}
    prepared = w.admission.prepare(w.ws['id'], body(w), w.actor)
    result = w.admission.execute(w.ws['id'], prepared['id'], {'authorized': True, 'notice': ADMISSION_NOTICE}, w.actor)
    assert result['run']['status'] == 'failed' and w.calls.count('tools/call') == 1
    w.now = time.time()
    observed = w.circuit.ingest(w.ws['id'], w.rids[0], {'revision': 1, 'source_ref': result['run']['id'],
        'authorized': True, 'notice': CIRCUIT_NOTICE}, w.actor)
    assert observed['state'] == 'open'
    assert w.calls.count('tools/call') == 1


def test_native_helper_rejects_non_fixture_before_database_read():
    from scripts.rehearse_circuit_postgres import run_circuit_contracts
    class NotOwned:
        backend = 'sqlite'
        def __getattr__(self, _):
            raise AssertionError('No database access is allowed.')
    with pytest.raises(AssertionError, match='before database access'):
        run_circuit_contracts(NotOwned(), object(), {}, object(), 1)
