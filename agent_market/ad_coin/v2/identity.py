"""Server-created authority types. Request bodies cannot manufacture principals."""
from dataclasses import dataclass, field
from enum import Enum
import math
import time
from uuid import UUID

from .contracts import ContractError


class Kind(str, Enum):
    HUMAN = 'human'
    AGENT = 'agent'
    REVIEWER = 'ops'


@dataclass(frozen=True)
class Principal:
    id: UUID
    kind: Kind
    epoch: int
    expires_at: float
    owner_id: UUID | None = None
    agent_binding_id: UUID | None = None
    capabilities: frozenset[str] = field(default_factory=frozenset)
    advertiser_permissions: frozenset[tuple[UUID, str]] = field(default_factory=frozenset)
    csrf_verified: bool = False
    mtls_verified: bool = False
    audience: str = 'aiac-v2-model'

    def __post_init__(self):
        if not isinstance(self.id, UUID) or type(self.epoch) is not int or self.epoch < 1 or not isinstance(self.kind, Kind):
            raise ContractError('invalid_principal', 403)
        if self.kind in (Kind.HUMAN, Kind.AGENT) and not isinstance(self.owner_id, UUID):
            raise ContractError('owner_binding_required', 403)
        if self.kind == Kind.AGENT and not isinstance(self.agent_binding_id, UUID):
            raise ContractError('agent_binding_required', 403)
        if type(self.capabilities) is not frozenset or type(self.advertiser_permissions) is not frozenset:
            raise ContractError('immutable_authority_required', 403)
        if type(self.csrf_verified) is not bool or type(self.mtls_verified) is not bool:
            raise ContractError('invalid_authentication_evidence', 403)
        if (type(self.expires_at) not in (float, int) or not 0 < self.expires_at <= 2**53-1 or
                not math.isfinite(self.expires_at)):
            raise ContractError('invalid_authority_expiry', 403)
        if (any(type(cap) is not str for cap in self.capabilities) or
                any(type(entry) is not tuple or len(entry) != 2 or not isinstance(entry[0], UUID) or
                    type(entry[1]) is not str for entry in self.advertiser_permissions)):
            raise ContractError('invalid_capability_scope', 403)


def authorize(contract, operation_id, principal, *, owner_id=None, advertiser_id=None,
              manager_binding_id=None, current_epoch=None, now=None):
    operation = contract.operation(operation_id)
    if operation['x-principal-kinds'] == ['public']:
        return
    if principal is None:
        raise ContractError('authentication_required', 401)
    if not isinstance(principal, Principal):
        raise ContractError('invalid_principal', 403)
    if principal.expires_at <= (time.time() if now is None else now):
        raise ContractError('authority_expired', 403)
    audience = 'aiac-v2-reviewer' if principal.kind == Kind.REVIEWER else 'aiac-v2-model'
    if principal.audience != audience or principal.kind.value not in operation['x-principal-kinds']:
        raise ContractError('principal_kind_forbidden', 403)
    if current_epoch is not None and (type(current_epoch) is not int or principal.epoch != current_epoch):
        raise ContractError('authority_revoked', 403)
    method = contract._operations[operation_id][0]
    if principal.kind == Kind.HUMAN and method != 'GET' and not principal.csrf_verified:
        raise ContractError('csrf_required', 403)
    if principal.kind == Kind.REVIEWER and not principal.mtls_verified:
        raise ContractError('verified_mtls_required', 403)
    if any(p['in'] == 'path' and p['name'] == 'advertiser_id' for p in operation['parameters']):
        if not isinstance(advertiser_id, UUID):
            raise ContractError('advertiser_scope_required', 403)
    owner_operations = {'getOffer', 'declineOffer', 'approveOffer', 'startExposure', 'getApprovedCreative',
                        'submitEvidence', 'completeExposure', 'cancelExposure', 'getOperation', 'getWallet', 'getReceipt'}
    if operation_id in owner_operations and not isinstance(owner_id, UUID):
        raise ContractError('owner_scope_required', 403)
    if owner_id is not None and principal.owner_id != owner_id:
        raise ContractError('unknown_resource', 404)
    if principal.kind == Kind.AGENT and operation_id in owner_operations and manager_binding_id is None:
        raise ContractError('manager_scope_required', 403)
    if (principal.kind == Kind.AGENT and manager_binding_id is not None and
            principal.agent_binding_id != manager_binding_id):
        raise ContractError('unknown_resource', 404)
    for capability in operation['x-capabilities']:
        allowed = ((advertiser_id, capability) in principal.advertiser_permissions
                   if advertiser_id is not None else capability in principal.capabilities)
        if not allowed:
            raise ContractError('capability_required', 403)
    if method != 'GET' and current_epoch is None:
        raise ContractError('authority_epoch_required', 403)
