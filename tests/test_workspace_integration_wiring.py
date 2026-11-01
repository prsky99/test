"""Private adapters are connected without opening a public or automatic path."""
from types import SimpleNamespace

import pytest

from agent_market.gateway.admin_auth import session_reference
from agent_market.workspace_access import SessionActor, WorkspaceInvalid
from agent_market.workspace_integrations import PrivateIntegrations
from agent_market.workspace_platform import close_for, platform_for, start_for
from tests.test_workspace_execution_api import private_api  # noqa: F401
from tests.test_workspace_platform_integration import surfaces  # noqa: F401


def test_default_graph_connects_concrete_adapters_but_starts_no_work(surfaces):
    w, front, customer, staff = surfaces
    graph = platform_for(front)
    assert graph.reliability_evaluation.read_evaluator is graph.evaluation_adapter
    assert graph.reliability_evaluation.worker is graph.evaluation_worker
    assert not graph.evaluation_adapter.configured and not graph.evaluation_worker.enabled
    assert not graph.machine_receiver.enabled and not graph.machine_receiver.bindings
    assert graph.machine_updates.sender is graph.machine_updates.destination_verifier is None
    assert start_for(front) and not graph.evaluation_worker.running
    base = '/admin/api/workflow-workspaces/' + w.ws['id']
    worker = staff.get(base + '/reliability/evaluation/worker/status', headers=w.headers['owner'])
    receiver = staff.get(base + '/machine-updates/receivers/status', headers=w.headers['owner'])
    assert worker.status_code == receiver.status_code == 200
    assert worker.json()['result']['configured'] is False
    assert receiver.json()['result']['receiver_enabled'] is False
    assert receiver.json()['result']['configured_destinations'] == 0
    assert receiver.json()['result']['receipts'] == []
    for client in (customer, staff):
        assert client.post('/private/machine-inbox/wmr_' + 'a' * 32).status_code == 404
    assert not w.calls and close_for(front)


@pytest.mark.parametrize('settings', [
    {'evaluation_adapter_enabled': 1}, {'evaluation_worker_enabled': True},
    {'receiver_enabled': 'true'}, {'receiver_bindings': []}, {'destination_bindings': {}},
    {'receiver_bindings': tuple(range(51))},
    {'single_admission_enabled': 1}, {'single_admission_environment': 'production'},
    {'circuit_enabled': 'true'},
])
def test_runtime_configuration_rejects_ambiguous_flags_and_unbounded_bindings(settings):
    with pytest.raises(WorkspaceInvalid):
        PrivateIntegrations(**settings)


def test_trusted_configuration_is_not_accepted_from_an_untyped_mapping(surfaces):
    w, front, _, _ = surfaces
    other = SimpleNamespace(store=w.store, workflows=front.workflows,
                            _workspace_integrations={'evaluation_adapter_enabled': True})
    with pytest.raises(WorkspaceInvalid):
        platform_for(other)
    assert not w.calls


def test_explicit_worker_configuration_still_requires_named_workspace_activation(surfaces):
    w, front, _, _ = surfaces
    other = SimpleNamespace(store=w.store, workflows=front.workflows,
        _workspace_integrations=PrivateIntegrations(evaluation_adapter_enabled=True, evaluation_worker_enabled=True))
    graph = platform_for(other)
    try:
        assert graph.evaluation_adapter.configured and graph.evaluation_worker.enabled
        assert start_for(other) and graph.evaluation_worker.running
        actor = SessionActor(1, session_reference(w.headers['owner']['Authorization'][7:]))
        assert not graph.evaluation_worker.status(w.ws['id'], actor)['active']
        assert not w.calls
    finally:
        assert close_for(other)
    assert not graph.evaluation_worker.running


def test_lifecycle_does_not_construct_components_and_reports_unfinished_shutdown():
    empty = SimpleNamespace()
    assert start_for(empty) and close_for(empty)
    assert not hasattr(empty, '_workspace_platform')
    worker = SimpleNamespace(close=lambda: False)
    assert close_for(SimpleNamespace(_workspace_platform=SimpleNamespace(evaluation_worker=worker))) is False


def test_research_surfaces_share_authority_and_remain_staff_only_and_inactive(surfaces):
    w, front, customer, staff = surfaces
    graph = platform_for(front)
    assert graph.typed_evidence.typed is graph.typed_flows
    assert graph.reliability_research.evaluation is graph.reliability_evaluation
    assert graph.single_admission.execution is graph.execution
    assert graph.reliability_routing.evidence_source == graph.reliability_circuit.get_agent_projection
    assert graph.single_admission.evidence_guard == graph.reliability_circuit.current_projection_in_transaction
    assert not graph.reliability_circuit.enabled
    assert graph.protocol_conformance.payments is graph.sandbox_payments
    assert not graph.single_admission.enabled
    base = '/admin/api/workflow-workspaces/' + w.ws['id']
    suffixes = ('/reliability/typed/options', '/reliability/research/status',
                '/reliability/admission/status', '/protocol-conformance')
    for suffix in suffixes:
        assert customer.get(base + suffix, headers=w.headers['owner']).status_code == 404
        assert staff.get(base + suffix).status_code == 401
        response = staff.get(base + suffix, headers=w.headers['owner'])
        assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    result = staff.get(base + '/reliability/admission/status', headers=w.headers['owner']).json()['result']
    assert result['configured'] is False and result['policy'] is None and result['admissions'] == []
    assert not w.calls
