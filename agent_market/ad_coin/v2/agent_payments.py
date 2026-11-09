"""Agent payments engine: mandates, execution escrow holds, settlements, and refunds."""

import json
import time
from typing import Any
from uuid import uuid4

from .contracts import ContractError
from .ledger import ModelLedger, identifier
from .points import require_platform_benefit
from .security_guards import AuditLogger, EventType


class AgentPaymentGateway:
    """Manages coin payments for paid agent invocations with escrow and mandate controls."""

    def __init__(self, store, ledger: ModelLedger, access, audit_logger: Any = None, clock=None):
        self.store = store
        self.ledger = ledger
        self.access = access
        self.audit = audit_logger or AuditLogger
        self._clock = clock or time.time

    def create_mandate(
        self,
        *,
        owner_id: str,
        agent_principal_id: str,
        total_atoms: int,
        per_task_atoms: int,
        providers: list[str] | None = None,
        duration_seconds: int = 86400 * 30,
    ) -> dict:
        owner_id = identifier(owner_id)
        agent_principal_id = identifier(agent_principal_id)
        if total_atoms < 1:
            raise ContractError("invalid_total_atoms", 422)
        if per_task_atoms < 1 or per_task_atoms > total_atoms:
            raise ContractError("invalid_per_task_atoms", 422)
        if duration_seconds < 60:
            raise ContractError("invalid_mandate_duration", 422)

        providers_list = list(providers or [])
        mandate_id = str(uuid4())
        now = int(self._clock())
        expires_at = now + duration_seconds

        with self.store.atomic():
            self.store.execute(
                "mandate_insert",
                (
                    mandate_id,
                    owner_id,
                    agent_principal_id,
                    total_atoms,
                    per_task_atoms,
                    0,
                    json.dumps(providers_list),
                    expires_at,
                    now,
                ),
            )
            self.audit.log(
                self.store,
                event_type=EventType.MANDATE_CREATED,
                status="succeeded",
                actor_principal_id=owner_id,
                target_id=mandate_id,
                details={
                    "agent_principal_id": agent_principal_id,
                    "total_atoms": str(total_atoms),
                    "per_task_atoms": str(per_task_atoms),
                },
            )

        return self.get_mandate(mandate_id, owner_id=owner_id)

    def get_mandate(self, mandate_id: str, *, owner_id: str | None = None) -> dict:
        row = self.store.one("mandate_get", (mandate_id,))
        if row is None:
            raise ContractError("unknown_mandate", 404)
        if owner_id is not None and row["owner_id"] != identifier(owner_id):
            raise ContractError("unauthorized_mandate_access", 403)
        return {
            "id": row["id"],
            "owner_id": row["owner_id"],
            "agent_principal_id": row["agent_principal_id"],
            "total_atoms": str(row["total_atoms"]),
            "per_task_atoms": str(row["per_task_atoms"]),
            "spent_atoms": str(row["spent_atoms"]),
            "available_atoms": str(int(row["total_atoms"]) - int(row["spent_atoms"])),
            "providers": json.loads(row["providers"]) if isinstance(row["providers"], str) else row["providers"],
            "expires_at": row["expires_at"],
            "revoked_at": row["revoked_at"],
            "active": row["revoked_at"] is None and row["expires_at"] > int(self._clock()),
            "created_at": row["created_at"],
        }

    def get_mandates(self, owner_id: str) -> list[dict]:
        owner_id = identifier(owner_id)
        rows = self.store.all("mandate_list_by_owner", (owner_id,))
        return [self.get_mandate(r["id"]) for r in rows]

    def revoke_mandate(self, mandate_id: str, *, owner_id: str) -> dict:
        owner_id = identifier(owner_id)
        mandate = self.get_mandate(mandate_id, owner_id=owner_id)
        if mandate["revoked_at"] is not None:
            return mandate

        now = int(self._clock())
        with self.store.atomic():
            self.store.execute("mandate_revoke", (now, mandate_id))
            self.audit.log(
                self.store,
                event_type=EventType.MANDATE_REVOKED,
                status="succeeded",
                actor_principal_id=owner_id,
                target_id=mandate_id,
                details={},
            )
        return self.get_mandate(mandate_id, owner_id=owner_id)

    def hold_execution(
        self,
        *,
        owner_id: str,
        provider_id: str,
        task_ref: str,
        price_atoms: int,
        idem_key: str,
        actor: str = "user",
        agent_principal_id: str | None = None,
        mandate_id: str | None = None,
    ) -> dict:
        owner_id = identifier(owner_id)
        require_platform_benefit(provider_id)
        if price_atoms < 1:
            raise ContractError("invalid_execution_price", 422)
        if actor not in ("user", "agent"):
            raise ContractError("invalid_actor", 422)

        execution_id = str(uuid4())
        now = int(self._clock())

        with self.store.atomic():
            # 1. Lock mandate FIRST if provided (ensures strict hierarchical locking order)
            if mandate_id:
                m_row = self.store.one("mandate_get_for_update", (mandate_id,))
                if m_row is None or m_row["owner_id"] != owner_id:
                    raise ContractError("mandate_invalid", 403)
                if m_row["revoked_at"] is not None:
                    raise ContractError("mandate_revoked", 403)
                if m_row["expires_at"] <= now:
                    raise ContractError("mandate_expired", 403)
                if actor == "agent" and agent_principal_id and m_row["agent_principal_id"] != identifier(agent_principal_id):
                    raise ContractError("mandate_principal_mismatch", 403)
                if price_atoms > int(m_row["per_task_atoms"]):
                    raise ContractError("mandate_per_task_exceeded", 403)
                if int(m_row["spent_atoms"]) + price_atoms > int(m_row["total_atoms"]):
                    raise ContractError("mandate_total_budget_exceeded", 403)

                allowed_provs = json.loads(m_row["providers"]) if isinstance(m_row["providers"], str) else m_row["providers"]
                if allowed_provs and provider_id not in allowed_provs:
                    raise ContractError("provider_not_permitted_by_mandate", 403)

                self.store.execute("mandate_spend", (price_atoms, mandate_id))
            elif actor == "agent":
                raise ContractError("mandate_required", 403)

            # 2. Verify user available wallet account
            user_acc = self.store.one("account_by_owner_purpose", (owner_id, "user_available"))
            if user_acc is None:
                raise ContractError("user_wallet_required", 404)
            if int(user_acc["balance_atoms"]) < price_atoms:
                raise ContractError("insufficient_coins", 409)

            # 3. Get or create hold account (user_locked)
            hold_acc = self.store.one("account_by_owner_purpose", (owner_id, "user_locked"))
            if hold_acc is None:
                hold_acc_id = self.ledger.create_account(owner_id, "user_locked")
            else:
                hold_acc_id = hold_acc["id"]

            # 4. Get or create provider payable account
            prov_acc = self.store.one("account_by_owner_purpose", (provider_id, "provider_payable"))
            if prov_acc is None:
                prov_acc_id = self.ledger.create_account(provider_id, "provider_payable")
            else:
                prov_acc_id = prov_acc["id"]

            # 5. Move funds from user_available into user_locked (escrow)
            self.ledger.post(
                f"spend:{owner_id}:{idem_key}",
                [(user_acc["id"], f"-{price_atoms}"), (hold_acc_id, str(price_atoms))],
                kind="payment",
            )

            # 6. Insert execution row
            self.store.execute(
                "execution_insert",
                (
                    execution_id,
                    owner_id,
                    provider_id,
                    task_ref,
                    price_atoms,
                    "held",
                    mandate_id,
                    user_acc["id"],
                    hold_acc_id,
                    prov_acc_id,
                    now,
                ),
            )

            self.audit.log(
                self.store,
                event_type=EventType.EXECUTION_HELD,
                status="succeeded",
                actor_principal_id=owner_id,
                target_id=execution_id,
                details={
                    "action": "hold_execution",
                    "price_atoms": str(price_atoms),
                    "provider_id": provider_id,
                    "task_ref": task_ref,
                    "mandate_id": mandate_id,
                },
            )

        return self.get_execution(execution_id)

    def get_execution(self, execution_id: str) -> dict:
        row = self.store.one("execution_get", (execution_id,))
        if row is None:
            raise ContractError("unknown_execution", 404)
        return {
            "id": row["id"],
            "owner_id": row["owner_id"],
            "provider_id": row["provider_id"],
            "task_ref": row["task_ref"],
            "price_atoms": str(row["price_atoms"]),
            "status": row["status"],
            "mandate_id": row["mandate_id"],
            "user_account_id": row["user_account_id"],
            "hold_account_id": row["hold_account_id"],
            "provider_account_id": row["provider_account_id"],
            "result_digest": row["result_digest"],
            "created_at": row["created_at"],
            "finished_at": row["finished_at"],
        }

    def settle_execution(
        self,
        execution_id: str,
        *,
        ok: bool,
        result_digest: str | None = None,
    ) -> dict:
        now = int(self._clock())

        with self.store.atomic():
            row = self.store.one("execution_get_for_update", (execution_id,))
            if row is None:
                raise ContractError("unknown_execution", 404)
            if row["status"] != "held":
                raise ContractError("execution_closed", 409)

            price_atoms = int(row["price_atoms"])

            # Lock mandate FIRST if execution is linked to a mandate (mandate -> account hierarchy)
            if row["mandate_id"]:
                self.store.one("mandate_get_for_update", (row["mandate_id"],))

            if ok:
                if not result_digest:
                    raise ContractError("result_digest_required", 422)

                # Move from escrow (user_locked) to provider_payable
                self.ledger.post(
                    f"settle:{execution_id}",
                    [(row["hold_account_id"], f"-{price_atoms}"), (row["provider_account_id"], str(price_atoms))],
                    kind="payment",
                )
                self.store.execute("execution_settle", (result_digest, now, execution_id))
                self.audit.log(
                    self.store,
                    event_type=EventType.EXECUTION_SETTLED,
                    status="succeeded",
                    actor_principal_id=row["owner_id"],
                    target_id=execution_id,
                    details={"action": "settle_execution", "price_atoms": str(price_atoms), "result_digest": result_digest},
                )
            else:
                # Full refund back to user_available
                self.ledger.post(
                    f"refund:{execution_id}",
                    [(row["hold_account_id"], f"-{price_atoms}"), (row["user_account_id"], str(price_atoms))],
                    kind="refund",
                )
                self.store.execute("execution_refund", (now, execution_id))

                # If mandate was used, restore mandate spent limit
                if row["mandate_id"]:
                    self.store.execute("mandate_refund", (price_atoms, row["mandate_id"]))

                self.audit.log(
                    self.store,
                    event_type=EventType.EXECUTION_REFUNDED,
                    status="succeeded",
                    actor_principal_id=row["owner_id"],
                    target_id=execution_id,
                    details={"action": "refund_execution", "price_atoms": str(price_atoms)},
                )

        return self.get_execution(execution_id)
