"""Explicit private runtime wiring, supplied only by trusted server code."""
from dataclasses import dataclass

from .workspace_access import WorkspaceInvalid


@dataclass(frozen=True, repr=False)
class PrivateIntegrations:
    """Configuration does not grant workspace or external-call authority."""
    evaluation_adapter_enabled: bool = False
    evaluation_worker_enabled: bool = False
    receiver_enabled: bool = False
    receiver_bindings: tuple = ()
    destination_bindings: tuple = ()
    single_admission_enabled: bool = False
    single_admission_environment: str = 'isolated'
    circuit_enabled: bool = False
    operating_qualifier: object = None
    machine_updates_worker_enabled: bool = False
    remote_task_bindings: tuple = ()
    model_proposer: object = None
    recovery_authorities: tuple = ()
    circuit_automation_enabled: bool = False
    early_stop_enabled: bool = False
    early_stop_environment: str = 'isolated'
    trust_publication_enabled: bool = False
    trust_signing_configs: tuple = ()
    independent_evaluator: object = None
    corpus_documents: tuple = ()
    first_party_corpus_enabled: bool = False
    stripe_test_client: object = None

    def __post_init__(self):
        if (any(type(value) is not bool for value in (
                self.evaluation_adapter_enabled, self.evaluation_worker_enabled, self.receiver_enabled,
                self.single_admission_enabled, self.circuit_enabled,
                self.circuit_automation_enabled, self.early_stop_enabled, self.trust_publication_enabled,
                self.first_party_corpus_enabled))
                or self.evaluation_worker_enabled and not self.evaluation_adapter_enabled
                or self.circuit_automation_enabled and not (self.circuit_enabled and self.evaluation_worker_enabled)
                or type(self.receiver_bindings) is not tuple or len(self.receiver_bindings) > 50
                or type(self.destination_bindings) is not tuple or len(self.destination_bindings) > 50
                or self.single_admission_environment not in ('isolated', 'sandbox', 'operating')):
            raise WorkspaceInvalid()
        if self.operating_qualifier is not None and not callable(self.operating_qualifier):
            raise WorkspaceInvalid()
        if self.model_proposer is not None and not callable(self.model_proposer):
            raise WorkspaceInvalid()
        if self.independent_evaluator is not None and not callable(self.independent_evaluator):
            raise WorkspaceInvalid()
        if self.early_stop_environment not in ('isolated', 'approved_external'):
            raise WorkspaceInvalid()
        from .reliability_portable_receipt import SigningConfig
        if (type(self.trust_signing_configs) is not tuple or len(self.trust_signing_configs) > 5
                or any(type(value) is not SigningConfig for value in self.trust_signing_configs)):
            raise WorkspaceInvalid()
        if type(self.machine_updates_worker_enabled) is not bool:
            raise WorkspaceInvalid()
        if type(self.remote_task_bindings) is not tuple or len(self.remote_task_bindings) > 20:
            raise WorkspaceInvalid()
        if self.remote_task_bindings:
            from .workspace_remote_a2a import TaskBinding
            if any(type(binding) is not TaskBinding for binding in self.remote_task_bindings):
                raise WorkspaceInvalid()
        from .customer_recovery import RecoveryAuthority
        if (type(self.recovery_authorities) is not tuple or len(self.recovery_authorities) > 10
                or any(type(value) is not RecoveryAuthority for value in self.recovery_authorities)):
            raise WorkspaceInvalid()
        from .first_party_corpus import ApprovedDocument
        if (type(self.corpus_documents) is not tuple or len(self.corpus_documents) > 500
                or any(type(value) is not ApprovedDocument for value in self.corpus_documents)
                or self.first_party_corpus_enabled and not self.corpus_documents):
            raise WorkspaceInvalid()
        from .stripe_sandbox import StripeTestClient
        if self.stripe_test_client is not None and type(self.stripe_test_client) is not StripeTestClient:
            raise WorkspaceInvalid()


def configured_for(front):
    value = getattr(front, '_workspace_integrations', None)
    if value is None:
        return PrivateIntegrations()
    if type(value) is not PrivateIntegrations:
        raise WorkspaceInvalid()
    return value
