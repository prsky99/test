"""Stored model entitlements; provisioning methods are not public HTTP operations."""

from dataclasses import replace
import json
from uuid import UUID, uuid4

from .budgets import millis
from .commands import AuthorityGuards
from .contracts import ContractError, MODEL_ASSET, canonical_bytes, digest
from .identity import Kind, Principal
from .ledger import ModelLedger, identifier

COMMERCIAL_CAPABILITIES = frozenset(
    (
        "campaign.edit",
        "campaign.read",
        "campaign.pause",
        "budget.approve",
        "reports.read",
        "reports.acknowledge",
    )
)

HUMAN_CAPABILITIES = frozenset(
    (
        "offers.request",
        "offers.read",
        "offers.decline",
        "operations.read",
        "wallet.read",
        "receipts.read",
    )
)


# Platform operator rights. Never granted by default; provisioned explicitly for staff only.
OPERATOR_CAPABILITY = "platform.operate"


class Access:
    def __init__(self, store):
        self.store, self.guards = store, AuthorityGuards(store)

    def require_operator(self, principal):
        """Platform-wide views and settlements need a human with the explicit operator capability."""
        if principal.kind != Kind.HUMAN:
            raise ContractError("operator_required", 403)
        with self.store.atomic():
            capabilities = self.current(principal).capabilities
        if OPERATOR_CAPABILITY not in capabilities:
            raise ContractError("operator_required", 403)

    def provision_principal(
        self, principal_id, kind, *, owner_id=None, capabilities=None
    ):
        principal_id = identifier(principal_id)
        if not isinstance(kind, Kind) or kind not in (
            Kind.HUMAN,
            Kind.AGENT,
            Kind.REVIEWER,
        ):
            raise ContractError("unsupported_principal_provisioning")
        owner_id = identifier(owner_id) if owner_id is not None else None
        if (kind in (Kind.HUMAN, Kind.AGENT)) != (owner_id is not None):
            raise ContractError("invalid_principal_owner")
        if kind == Kind.REVIEWER:
            caps = ["creative.review"]
        elif kind == Kind.AGENT:
            caps = sorted(
                HUMAN_CAPABILITIES if capabilities is None else set(capabilities)
            )
            if not set(caps) <= HUMAN_CAPABILITIES:
                raise ContractError("unsupported_owner_capability")
        else:
            if capabilities is None:
                caps = sorted(HUMAN_CAPABILITIES)
            else:
                caps = sorted(set(capabilities))
                if not set(caps) <= (HUMAN_CAPABILITIES | COMMERCIAL_CAPABILITIES | {OPERATOR_CAPABILITY}):
                    raise ContractError("unsupported_owner_capability")
        with self.store.atomic():
            self.guards.provision(principal_id)
            self.guards.current(principal_id)
            if self.store.one("advertiser_get", (principal_id,)):
                raise ContractError("guard_identity_conflict", 409)
            old = self.store.one("principal_get", (principal_id,))
            if old:
                if (old["kind"], old["owner_id"]) != (kind.value, owner_id):
                    raise ContractError("principal_identity_conflict", 409)
                return
            self.store.execute(
                "principal_insert",
                (
                    principal_id,
                    kind.value,
                    owner_id,
                    canonical_bytes(caps).decode(),
                ),
            )

    def provision_agent_binding(
        self,
        binding_id,
        owner_id,
        agent_principal_id,
        operator_id,
        *,
        capabilities=None,
    ):
        binding_id, owner_id, agent_principal_id, operator_id = map(
            identifier, (binding_id, owner_id, agent_principal_id, operator_id)
        )
        caps = sorted(HUMAN_CAPABILITIES if capabilities is None else set(capabilities))
        if not set(caps) <= HUMAN_CAPABILITIES:
            raise ContractError("unsupported_owner_capability")
        with self.store.atomic():
            self.provision_principal(
                agent_principal_id,
                Kind.AGENT,
                owner_id=owner_id,
                capabilities=caps,
            )
            self.guards.provision(binding_id)
            self.guards.current(binding_id)
            self.store.execute(
                "agent_binding_upsert",
                (
                    binding_id,
                    owner_id,
                    agent_principal_id,
                    operator_id,
                    canonical_bytes(caps).decode(),
                ),
            )
            return binding_id

    def revoke_agent_binding(self, binding_id):
        binding_id = identifier(binding_id)
        with self.store.atomic():
            self.guards.current(binding_id)
            if self.store.execute("agent_binding_revoke", (binding_id,)).rowcount != 1:
                raise ContractError("unknown_resource", 404)

    def provision_preferences(self, owner_id, *, now_ms=0, preference_id=None):
        owner_id = identifier(owner_id)
        now_ms = millis(now_ms)
        pref_id = identifier(preference_id) if preference_id else str(uuid4())
        with self.store.atomic():
            old = self.store.one("preference_by_owner", (owner_id,))
            if old:
                return old["id"]
            rev_hash = digest(
                {
                    "owner_id": owner_id,
                    "receive_offers": False,
                    "context_fields": [],
                    "max_offers_per_day": 10,
                    "max_ads_per_campaign_day": 1,
                    "max_ads_per_day": 3,
                    "max_ad_ms_per_day": 90000,
                }
            )
            self.store.execute(
                "preference_insert",
                (
                    pref_id,
                    owner_id,
                    0,
                    "[]",
                    10,
                    1,
                    3,
                    90000,
                    1,
                    rev_hash,
                    now_ms,
                ),
            )
            return pref_id

    def provision_wallet(
        self,
        owner_id,
        *,
        wallet_id=None,
        manager_binding_id=None,
        operator_id=None,
    ):
        owner_id = identifier(owner_id)
        wallet_id = identifier(wallet_id) if wallet_id else str(uuid4())
        manager_binding_id = (
            identifier(manager_binding_id) if manager_binding_id is not None else None
        )
        operator_owner = identifier(operator_id) if operator_id else owner_id
        with self.store.atomic():
            old = self.store.one("wallet_get", (wallet_id,))
            if old:
                if old["owner_id"] != owner_id:
                    raise ContractError("wallet_identity_conflict", 409)
                return wallet_id
            ledger = ModelLedger(self.store)
            available = ledger.create_account(owner_id, "user_available")
            locked = ledger.create_account(owner_id, "user_locked")
            operator_acc = ledger.create_account(operator_owner, "operator_payable")
            self.store.execute(
                "wallet_insert",
                (
                    wallet_id,
                    owner_id,
                    manager_binding_id,
                    MODEL_ASSET,
                    available,
                    locked,
                    operator_acc,
                ),
            )
            return wallet_id

    def provision_advertiser(self, advertiser_id, commercial_tenant_id):
        advertiser_id, commercial_tenant_id = (
            identifier(advertiser_id),
            identifier(commercial_tenant_id),
        )
        with self.store.atomic():
            self.guards.provision(advertiser_id)
            self.guards.current(advertiser_id)
            old = self.store.one("advertiser_get", (advertiser_id,))
            if old:
                if old["commercial_tenant_id"] != commercial_tenant_id:
                    raise ContractError("advertiser_identity_conflict", 409)
                return old["available_account"]
            if self.store.one("principal_get", (advertiser_id,)):
                raise ContractError("guard_identity_conflict", 409)
            account = ModelLedger(self.store).create_account(
                advertiser_id, "advertiser_available"
            )
            self.store.execute(
                "advertiser_insert", (advertiser_id, commercial_tenant_id, account)
            )
            return account

    def grant(self, advertiser_id, principal_id, capability):
        advertiser_id, principal_id = (
            identifier(advertiser_id),
            identifier(principal_id),
        )
        if capability not in COMMERCIAL_CAPABILITIES:
            raise ContractError("unsupported_commercial_capability")
        with self.store.atomic():
            self.guards.current(advertiser_id)
            person = self.store.one("principal_get", (principal_id,))
            if not person or person["kind"] != Kind.HUMAN.value:
                raise ContractError("human_membership_required", 403)
            self.store.execute(
                "membership_grant", (advertiser_id, principal_id, capability)
            )

    def revoke_membership(self, advertiser_id, principal_id, capability):
        advertiser_id, principal_id = (
            identifier(advertiser_id),
            identifier(principal_id),
        )
        with self.store.atomic():
            self.guards.current(advertiser_id)
            self.store.execute(
                "membership_revoke", (advertiser_id, principal_id, capability)
            )

    def set_advertiser_status(self, advertiser_id, status):
        advertiser_id = identifier(advertiser_id)
        if status not in ("active", "suspended"):
            raise ContractError("invalid_advertiser_status")
        with self.store.atomic():
            self.guards.current(advertiser_id)
            self.store.execute("advertiser_status", (status, advertiser_id))

    def set_model_activation(self, enabled):
        if type(enabled) is not bool:
            raise ContractError("invalid_model_control")
        with self.store.atomic():
            self.store.execute("commercial_control_set", (int(enabled),))

    def current(self, principal, advertiser_id=None):
        """Caller locks all authority guards in sorted order before resolving entitlements."""
        if not isinstance(principal, Principal):
            raise ContractError("authentication_required", 401)
        epoch = self.guards.current(str(principal.id))
        row = self.store.one("principal_get", (str(principal.id),))
        expected_owner = (
            str(principal.owner_id) if principal.owner_id is not None else None
        )
        if not row or (row["kind"], row["owner_id"]) != (
            principal.kind.value,
            expected_owner,
        ):
            raise ContractError("principal_binding_mismatch", 403)
        if principal.epoch != epoch:
            raise ContractError("authority_revoked", 403)
        capabilities = frozenset(json.loads(row["capabilities_json"]))
        if principal.kind == Kind.AGENT:
            binding_id = str(principal.agent_binding_id)
            self.guards.current(binding_id)
            binding = self.store.one("agent_binding_get", (binding_id,))
            if (
                not binding
                or not binding["active"]
                or binding["owner_id"] != expected_owner
                or binding["agent_principal_id"] != str(principal.id)
            ):
                raise ContractError("authority_revoked", 403)
            capabilities = frozenset(json.loads(binding["capabilities_json"]))
        permissions = frozenset()
        if advertiser_id is not None:
            permissions = frozenset(
                (UUID(advertiser_id), r["capability"])
                for r in self.store.all(
                    "membership_list", (advertiser_id, str(principal.id))
                )
            )
        return replace(
            principal,
            capabilities=capabilities,
            advertiser_permissions=permissions,
        )
