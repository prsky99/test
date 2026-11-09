"""Coin economy step 2 (docs/AD_COIN_COIN_ECONOMY.md): the growth budget and the ways coins leave it.

All coins start in the growth budget (monthly-capped issuance) and move only from the platform to users:
a one-time welcome grant for a reviewed advertiser, a monthly provider reward capped per provider, and
manual grants by platform staff. Every movement is one idempotent ledger journal plus an audit entry.
People and advertisers never pay each other; the ledger enforces that separately.
"""

import re

from .contracts import ContractError
from .ledger import ModelLedger, identifier
from .points import (GROWTH_ACCOUNT, OPERATOR_GRANT_MAX_ATOMS, PROVIDER_REWARD_MONTHLY_CAP_ATOMS,
                     WELCOME_GRANT_ATOMS, ensure_platform_accounts, issue)
from .security_guards import AuditLogger, EventType

_MONTH = re.compile(r"20[0-9]{2}-(0[1-9]|1[0-2])\Z")
_REQUEST = re.compile(r"[a-f0-9]{32}\Z")


class CoinEconomy:
    def __init__(self, store, ledger=None, access=None):
        self.store, self.ledger, self.access = store, ledger or ModelLedger(store), access

    def _advertiser_account(self, advertiser_id):
        row = self.store.one("advertiser_get", (identifier(advertiser_id),))
        if row is None:
            raise ContractError("unknown_advertiser", 404)
        if row["status"] != "active":
            raise ContractError("advertiser_not_active", 409)
        return row["available_account"]

    def _grant(self, key, account, amount, kind, details):
        ensure_platform_accounts(self.ledger)
        with self.store.atomic():
            result = self.ledger.post(key, [(GROWTH_ACCOUNT, str(-amount)), (account, str(amount))], kind=kind)
            if not result.replayed:
                AuditLogger.log(self.store, EventType.COINS_GRANTED, "succeeded", target_id=account,
                                details={"key": key, "atoms": str(amount), **details})
        return {"key": key, "account": account, "atoms": str(amount), "replayed": result.replayed}

    def issue_monthly(self, month, amount_atoms):
        """Fill the growth budget for a UTC month; the ledger enforces the monthly cap."""
        if not _MONTH.match(str(month)) or type(amount_atoms) is not int or amount_atoms <= 0:
            raise ContractError("invalid_issuance", 422)
        with self.store.atomic():
            result = issue(self.ledger, amount_atoms, reason="month:" + month)
            if not result.replayed:
                AuditLogger.log(self.store, EventType.COINS_ISSUED, "succeeded", target_id=GROWTH_ACCOUNT,
                                details={"month": month, "atoms": str(amount_atoms)})
        return {"month": month, "atoms": str(amount_atoms), "replayed": result.replayed}

    def welcome_grant(self, advertiser_id):
        account = self._advertiser_account(advertiser_id)
        return self._grant("welcome:" + identifier(advertiser_id), account, WELCOME_GRANT_ATOMS, "grant",
                           {"reason": "welcome"})

    def provider_reward(self, advertiser_id, month, amount_atoms):
        """One reward per provider and UTC month, never above PROVIDER_REWARD_MONTHLY_CAP_ATOMS."""
        if (not _MONTH.match(str(month)) or type(amount_atoms) is not int
                or not 0 < amount_atoms <= PROVIDER_REWARD_MONTHLY_CAP_ATOMS):
            raise ContractError("invalid_provider_reward", 422)
        account = self._advertiser_account(advertiser_id)
        return self._grant("provider_reward:" + identifier(advertiser_id) + ":" + month, account, amount_atoms,
                           "grant", {"reason": "provider_reward", "month": month})

    def operator_grant(self, principal, *, account_id, amount_atoms, reason, request_id):
        """A manual grant by platform staff (platform.operate) to a person or an advertiser account."""
        if self.access is None:
            raise ContractError("operator_required", 403)
        self.access.require_operator(principal)
        if (type(amount_atoms) is not int or not 0 < amount_atoms <= OPERATOR_GRANT_MAX_ATOMS
                or type(reason) is not str or not 5 <= len(reason.strip()) <= 200
                or not _REQUEST.match(str(request_id))):
            raise ContractError("invalid_operator_grant", 422)
        account = self.store.one("account_get", (identifier(account_id),))
        if account is None or account["purpose"] not in ("user_available", "advertiser_available"):
            raise ContractError("grant_target_not_allowed", 422)
        kind = "growth_reward" if account["purpose"] == "user_available" else "grant"
        return self._grant("operator:" + request_id, account["id"], amount_atoms, kind,
                           {"reason": reason.strip(), "operator": str(principal.id)})
