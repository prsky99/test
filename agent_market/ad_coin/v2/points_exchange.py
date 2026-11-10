"""Points -> workspace credits (docs/AD_COIN_BENEFITS.md). Points live on the v2 ledger, credits in the
application store, so the exchange runs as: debit points and record an outbox job in one v2 transaction;
a worker grants the credits through customer_credits.exchange_points (idempotent per exchange id); when
the credit side refuses, the points are refunded. Temporary failures leave the job for a retry.
"""

import re

from .commands import Outbox
from .contracts import ContractError
from .ledger import MODEL_ASSET, ModelLedger, identifier
from .points import (ATOMS_PER_COIN, MAX_CREDITS_PER_EXCHANGE, POINTS_PER_WORKSPACE_CREDIT, REVENUE_ACCOUNT,
                     ensure_platform_accounts)

EVENT = "points_exchange_requested"


def cost_atoms(credits: int) -> int:
    return credits * POINTS_PER_WORKSPACE_CREDIT * ATOMS_PER_COIN


class PointsExchange:
    def __init__(self, store, ledger=None):
        self.store = store
        self.ledger = ledger or ModelLedger(store)
        self.outbox = Outbox(store)

    def request(self, *, owner_id, customer_id, credits, exchange_id, now_ms):
        owner_id = identifier(owner_id)
        if (type(credits) is not int or not 1 <= credits <= MAX_CREDITS_PER_EXCHANGE
                or not re.fullmatch(r"[a-f0-9]{32}", str(exchange_id))
                or not re.fullmatch(r"cu_[0-9a-f]{32}", str(customer_id))):
            raise ContractError("invalid_points_exchange", 422)
        ensure_platform_accounts(self.ledger)
        cost = cost_atoms(credits)
        with self.store.atomic():
            account = self.store.one("account_by_owner_purpose", (owner_id, "user_available"))
            if account is None:
                raise ContractError("user_wallet_required", 404)
            posted = self.ledger.post("points_exchange:" + exchange_id,
                                      [(account["id"], str(-cost)), (REVENUE_ACCOUNT, str(cost))], kind="payment")
            if posted.replayed:  # the same exchange retried: already debited and queued once
                refunded = self.store.one("journal_get", (MODEL_ASSET, "points_exchange_refund:" + exchange_id))
                return {"exchange_id": exchange_id, "state": "refunded" if refunded else "pending",
                        "credits": credits, "points": cost // ATOMS_PER_COIN, "replayed": True}
            self.outbox.enqueue("points_exchange:" + exchange_id, {
                "event": EVENT, "exchange_id": exchange_id, "owner_id": owner_id, "customer_id": customer_id,
                "credits": credits, "cost_atoms": str(cost), "user_account": account["id"],
            }, available_ms=now_ms)
        return {"exchange_id": exchange_id, "state": "pending", "credits": credits, "points": cost // ATOMS_PER_COIN}

    def handle(self, payload, grant):
        """Run inside the worker's v2 transaction. Returns "granted" or "refunded"; raises to retry."""
        from ...workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid

        exchange_id, cost = payload["exchange_id"], int(payload["cost_atoms"])
        try:
            grant(payload["customer_id"], payload["credits"], exchange_id)
        except (WorkspaceDenied, WorkspaceInvalid, WorkspaceConflict):
            self.ledger.post("points_exchange_refund:" + exchange_id,
                             [(REVENUE_ACCOUNT, str(-cost)), (payload["user_account"], str(cost))], kind="refund")
            return "refunded"
        return "granted"
