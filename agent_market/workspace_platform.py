"""Shared private components; public and staff transports remain separate."""
from types import SimpleNamespace
import threading

_construction = threading.RLock()


def start_for(front):
    """Start configured workers, or drain and fail the host startup."""
    with _construction:
        platform = getattr(front, '_workspace_platform', None)
    try:
        for name in ('evaluation_worker', 'machine_update_automation', 'early_stop', 'operations_worker'):
            worker = getattr(platform, name, None)
            if worker is not None and worker.enabled and not worker.start():
                from .workspace_access import WorkspaceConflict
                raise WorkspaceConflict()
    except BaseException:
        close_for(front)
        raise
    return True


def close_for(front):
    """Stop an explicitly enabled private worker without constructing a graph."""
    with _construction:
        platform = getattr(front, '_workspace_platform', None)
    if platform is None:
        return True
    success = True
    for name in ('operations_worker', 'early_stop', 'machine_update_automation', 'evaluation_worker'):
        worker = getattr(platform, name, None)
        if worker is not None:
            try:
                success = worker.close() and success
            except Exception:
                # Other workers must still be drained after one shutdown fails.
                success = False
    return success


def platform_for(front, *, store=None, runtime=None):
    with _construction:
        existing = getattr(front, '_workspace_platform', None)
        if existing is not None:
            if store is not None and existing.access.store is not store:
                from .workspace_access import WorkspaceInvalid
                raise WorkspaceInvalid()
            return existing
        from .workspace_access import WorkspaceAccess
        from .workspace_execution import WorkspaceExecution
        from .customer_identity import customer_identity_for
        from .customer_workspace_runtime import CustomerWorkspaceAccess
        from .workspace_lifecycle import WorkspaceLifecycle
        from .workspace_release import WorkspaceReleases
        from .provider_claims import ProviderClaims
        from .workflow_product_composer import ProductComposer
        from .workspace_metering import WorkspaceMetering
        from .workspace_typed_flows import TypedFlows
        from .workspace_typed_release import CustomerTypedFlows, WorkspaceTypedReleases
        from .workspace_agreements import WorkspaceAgreements
        from .workspace_sandbox_payments import SandboxPayments
        from .workspace_reliability import ReliabilityEvidence
        from .reliability_evaluation import ReliabilityEvaluation
        from .reliability_trust import ReliabilityTrust
        from .reliability_routing import ReliabilityRouting
        from .workspace_app_factory import AppFactory
        from .workspace_support_outcomes import SupportOutcomes
        from .workspace_machine_updates import MachineUpdates
        from .workspace_machine_receiver import MachineReceiver
        from .workspace_machine_automation import MachineUpdateAutomation
        from .workspace_remote_a2a import RemoteTasks
        from .workspace_machine_adapters import VerifiedWorkflowDestinations, SecureMachineSender
        from .reliability_evaluation_worker import McpReadEvaluator, EvaluationWorker
        from .workspace_integrations import configured_for
        from .workspace_typed_evidence import WorkspaceTypedEvidence
        from .reliability_research import ReliabilityResearch
        from .reliability_admission import SingleAdmission
        from .workspace_protocol_conformance import ProtocolConformance
        from .reliability_circuit import ReliabilityCircuit

        runtime = runtime if runtime is not None else front.workflows
        store = store if store is not None else front.store
        key, proxy = runtime.key, runtime.proxy
        access = WorkspaceAccess(store, key)
        execution = WorkspaceExecution(access, proxy)
        identity = customer_identity_for(store, key)
        from .customer_organizations import CustomerOrganizations
        from .customer_recovery import CustomerRecovery
        # Independent recovery is available only with explicit offline review
        # authority keys. Constructing this graph never enables public login.
        integrations = configured_for(front)
        customer_recovery = CustomerRecovery(CustomerOrganizations(identity, access),
            integrations.recovery_authorities) if integrations.recovery_authorities else None
        customer_access = CustomerWorkspaceAccess(access, identity)
        app_execution = WorkspaceExecution(customer_access, proxy)
        releases = WorkspaceReleases(execution, customer_identity=identity,
                                     customer_executor=app_execution)
        app_execution.authority_guard = releases.guard_ticket
        products = ProductComposer(execution)
        execution.authority_guard = products.guard_ticket
        meter = WorkspaceMetering(access, execution)
        meter.customer_access = customer_access
        execution.meter = meter
        app_execution.meter = meter
        typed_flows = TypedFlows(execution)
        app_typed_flows = CustomerTypedFlows(app_execution)
        typed_releases = WorkspaceTypedReleases(typed_flows, customer_identity=identity,
                                               customer_flows=app_typed_flows)
        meter.typed_flows = typed_flows
        def typed_active(db, now):
            return db.execute("SELECT COUNT(*) FROM workspace_typed_flow_runs WHERE status='running' AND deadline>?", (now,)).fetchone()[0]
        execution.related_active_count = app_execution.related_active_count = typed_active
        claims = ProviderClaims(store, key)
        agreements = WorkspaceAgreements(access, claims)
        sandbox_payments = SandboxPayments(access, agreements)
        from .stripe_sandbox import StripeSandbox
        stripe_sandbox = StripeSandbox(access, execution, client=integrations.stripe_test_client)
        legacy_evaluator = getattr(front, '_workspace_reliability_evaluator', None)
        if legacy_evaluator is not None and integrations.independent_evaluator is not None:
            from .workspace_access import WorkspaceInvalid
            raise WorkspaceInvalid()
        reliability_evidence = ReliabilityEvidence(access, execution,
            evaluator=integrations.independent_evaluator or legacy_evaluator,
            operating_qualifier=integrations.operating_qualifier)
        evidence_source = reliability_evidence.get_agent_projection
        reliability_evaluation = ReliabilityEvaluation(access, runtime,
            read_evaluator=getattr(front, '_workspace_read_evaluator', None),
            evaluator_authorizer=getattr(front, '_workspace_evaluator_authorizer', None))
        evaluation_adapter = McpReadEvaluator(reliability_evaluation,
            enabled=integrations.evaluation_adapter_enabled)
        if reliability_evaluation.read_evaluator is None and reliability_evaluation.evaluator_authorizer is None:
            reliability_evaluation.read_evaluator = evaluation_adapter
            reliability_evaluation.evaluator_authorizer = evaluation_adapter.authorizer
        elif integrations.evaluation_adapter_enabled or integrations.evaluation_worker_enabled:
            from .workspace_access import WorkspaceInvalid
            raise WorkspaceInvalid()
        evaluation_worker = EvaluationWorker(reliability_evaluation,
            enabled=integrations.evaluation_worker_enabled)
        reliability_evaluation.worker = evaluation_worker
        reliability_trust = ReliabilityTrust(access, evidence_source=evidence_source)
        reliability_circuit = ReliabilityCircuit(access, reliability_evaluation,
            evidence_guard=reliability_evidence.current_projection_in_transaction,
            enabled=integrations.circuit_enabled, execution=execution)
        from .reliability_automation import CircuitAutomation
        circuit_automation = CircuitAutomation(reliability_circuit,
            enabled=integrations.circuit_automation_enabled)
        evaluation_worker.circuit_automation = circuit_automation
        reliability_routing = ReliabilityRouting(access, runtime,
            evidence_source=reliability_circuit.get_agent_projection)
        typed_evidence = WorkspaceTypedEvidence(reliability_evidence, typed_flows)
        reliability_research = ReliabilityResearch(access, reliability_evaluation, lineage=typed_evidence)
        single_admission = SingleAdmission(access, reliability_routing, execution,
            enabled=integrations.single_admission_enabled,
            environment=integrations.single_admission_environment,
            evidence_guard=reliability_circuit.current_projection_in_transaction)
        protocol_conformance = ProtocolConformance(access, sandbox_payments)
        app_factory = AppFactory(typed_flows, releases=releases, typed_releases=typed_releases,
            model_proposer=integrations.model_proposer)
        support_outcomes = SupportOutcomes(access, execution, typed_flows)
        machine_destinations = VerifiedWorkflowDestinations(access, runtime,
            bindings=integrations.destination_bindings)
        machine_sender = SecureMachineSender(machine_destinations)
        machine_updates = MachineUpdates(access, evidence_source, provider_claims=claims,
            destination_verifier=getattr(front, '_workspace_machine_destination_verifier', None)
                or (machine_destinations if integrations.destination_bindings else None),
            sender=getattr(front, '_workspace_machine_sender', None)
                or (machine_sender.configured() if integrations.destination_bindings else None))
        machine_receiver = MachineReceiver(access, bindings=integrations.receiver_bindings,
            enabled=integrations.receiver_enabled)
        machine_update_automation = MachineUpdateAutomation(machine_updates,
            enabled=integrations.machine_updates_worker_enabled)
        remote_tasks = RemoteTasks(access, bindings=integrations.remote_task_bindings)
        from .reliability_early_stop import ReliabilityEarlyStop
        from .reliability_publication import ReliabilityPublication
        early_stop = ReliabilityEarlyStop(access, remote_tasks, enabled=integrations.early_stop_enabled,
            comparator=integrations.independent_evaluator, environment=integrations.early_stop_environment)
        trust_publication = ReliabilityPublication(access, reliability_trust,
            configs=integrations.trust_signing_configs, enabled=integrations.trust_publication_enabled)
        from .workspace_admin_control import WorkspaceAdminControl
        from .workspace_admin_worker import OperationsWorker
        operations = WorkspaceAdminControl(identity, access)
        value = SimpleNamespace(key=key, runtime=runtime, access=access, execution=execution, identity=identity,
                                operations=operations, operations_worker=OperationsWorker(operations),
                                customer_recovery=customer_recovery,
                                circuit_automation=circuit_automation, early_stop=early_stop,
                                trust_publication=trust_publication,
                                customer_access=customer_access, app_execution=app_execution,
                                releases=releases, lifecycle=WorkspaceLifecycle(execution),
                                claims=claims, products=products, meter=meter,
                                typed_flows=typed_flows, agreements=agreements,
                                sandbox_payments=sandbox_payments,
                                stripe_sandbox=stripe_sandbox,
                                app_typed_flows=app_typed_flows, typed_releases=typed_releases,
                                reliability_evidence=reliability_evidence,
                                reliability_evaluation=reliability_evaluation,
                                evaluation_adapter=evaluation_adapter, evaluation_worker=evaluation_worker,
                                reliability_trust=reliability_trust,
                                reliability_circuit=reliability_circuit,
                                reliability_routing=reliability_routing,
                                typed_evidence=typed_evidence, reliability_research=reliability_research,
                                single_admission=single_admission, protocol_conformance=protocol_conformance,
                                app_factory=app_factory, support_outcomes=support_outcomes,
                                machine_updates=machine_updates, machine_receiver=machine_receiver,
                                machine_update_automation=machine_update_automation,
                                remote_tasks=remote_tasks,
                                machine_destinations=machine_destinations, machine_sender=machine_sender)
        if front is not None:
            front._workspace_platform = value
        return value


def typed_engine_for(platform, identity, ws, flow):
    """Engine whose authority check matches the actor that admitted a typed run.

    Customer runs must be revalidated against the customer session, never the
    staff membership check of the administrator engine.
    """
    from .workspace_access import WorkspaceDenied
    admin = platform.typed_flows
    with admin.execution._internal() as db:
        run, ticket, claims = admin._run(db, ws, flow, identity)
        executor = run.get('executor')
        if executor is None:
            # Runs admitted before the engine was recorded on the signed run.
            if claims.get('actor_kind') != 'customer':
                executor = 'admin'
            # Reuses the registered statement; the PostgreSQL store rejects unlisted SQL.
            elif db.execute('SELECT * FROM workspace_app_run_links WHERE ticket_id=?', (ticket['id'],)).fetchone():
                executor = 'customer_app'
            else:
                executor = 'customer'
    if executor == 'admin':
        return admin
    if executor == 'customer_app':
        return platform.app_typed_flows
    if executor == 'customer':
        from .customer_authoring import authoring_for
        return authoring_for(platform).typed
    raise WorkspaceDenied()


def admin_router_for(front, *, store=None, runtime=None):
    from fastapi import APIRouter
    from .workspace_service import router_for as workspaces
    from .customer_identity_service import router_for as customers
    from .provider_claims_service import router_for as providers
    from .workspace_release_service import router_for as releases
    from .advancement_service import router_for as advancement
    from .workflow_quality_review_service import router_for as quality
    from .workflow_product_composer_service import router_for as products
    from .workspace_typed_flow_service import router_for as typed_flows
    from .evidence_rollup_service import router_for as evidence_rollups
    from .workspace_typed_release_service import router_for as typed_releases
    from .workspace_reliability_service import router_for as reliability_evidence
    from .reliability_control_service import router_for as reliability_controls
    from .workspace_growth_service import router_for as growth
    from .workspace_machine_update_service import router_for as machine_updates
    from .workspace_typed_evidence_service import router_for as typed_evidence
    from .reliability_research_service import router_for as research
    from .reliability_admission_service import router_for as admission
    from .workspace_protocol_conformance_service import router_for as conformance
    from .workspace_remote_a2a_service import router_for as remote_tasks
    platform = platform_for(front, store=store, runtime=runtime)
    from .workspace_admin_service import router_for as operations_router
    store, key, proxy = platform.access.store, platform.key, platform.execution.proxy
    router = APIRouter()
    router.include_router(operations_router(platform.identity, platform.access, core=platform.operations))
    from .workspace_admin_specialists import router_for as specialist_aliases
    core_workspaces = workspaces(store, key, proxy, access=platform.access, execution=platform.execution)
    router.include_router(core_workspaces)
    router.include_router(specialist_aliases(store, core_workspaces, staff_core=True))
    from .customer_credit_service import router_for as credits
    router.include_router(credits(platform.identity,platform.access,admin=True))
    advancement_source = advancement(platform.access, meter=platform.meter,
                                     support_engine=getattr(front, '_workspace_support_engine', None),
                                     agreements=platform.agreements,
                                     sandbox_payments=platform.sandbox_payments,
                                     identity=platform.identity,
                                     preparation_sources=getattr(front, '_workspace_preparation_sources', None))
    for specialist in (customers(store, key, identity=platform.identity, public=False),
                       providers(store, key, claims=platform.claims), advancement_source, products(platform.products), quality(platform.access, platform.execution), typed_flows(platform.typed_flows),
                       evidence_rollups(platform.access, platform.execution), typed_evidence(platform.typed_evidence),
                       releases(platform.releases, platform.lifecycle, public=False),
                       typed_releases(platform.typed_releases, public=False),
                       machine_updates(platform.machine_updates, receiver=platform.machine_receiver),
                       conformance(platform.protocol_conformance), remote_tasks(platform.remote_tasks)):
        router.include_router(specialist)
        router.include_router(specialist_aliases(platform.access.store, specialist))
    for specialist in (
        reliability_evidence(platform.access, platform.execution, core=platform.reliability_evidence),
        reliability_controls(platform.access, platform.runtime,
        evaluation=platform.reliability_evaluation, trust=platform.reliability_trust,
        routing=platform.reliability_routing, evidence=platform.reliability_evidence,
        circuit=platform.reliability_circuit, early_stop=platform.early_stop,
        publication=platform.trust_publication),
        growth(platform.app_factory, platform.support_outcomes),
        research(platform.access, platform.reliability_evaluation,
                                  research=platform.reliability_research, lineage=platform.typed_evidence),
        admission(platform.single_admission)
    ):
        router.include_router(specialist)
        router.include_router(specialist_aliases(platform.access.store, specialist))
    from .stripe_sandbox_service import router_for as stripe_sandbox_controls
    router.include_router(stripe_sandbox_controls(platform.stripe_sandbox))
    return router


def public_router_for(front, *, workspace_access_enabled=False):
    from fastapi import APIRouter, Depends
    if type(workspace_access_enabled) is not bool:
        raise ValueError('Choose an explicit customer workspace access setting.')
    router = APIRouter()
    if not workspace_access_enabled:
        return router
    from .customer_identity_service import router_for as customers
    from .workspace_release_service import router_for as releases
    from .workspace_typed_release_service import router_for as typed_releases
    platform = platform_for(front)
    from .customer_identity_service import customer_entry_guard
    router = APIRouter(dependencies=[Depends(customer_entry_guard(platform.identity))])
    from .workspace_admin_service import router_for as operations_router
    router.include_router(operations_router(platform.identity, platform.access, core=platform.operations, public=True))
    router.include_router(customers(front.store, front.workflows.key, identity=platform.identity, admin=False))
    router.include_router(releases(platform.releases, platform.lifecycle, admin=False))
    router.include_router(typed_releases(platform.typed_releases, admin=False))
    from .customer_authoring_service import router_for as authoring
    router.include_router(authoring(platform))
    return router
