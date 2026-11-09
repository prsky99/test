"""Atomic model ledger. Its commands are internal; it exposes no public credit API."""

from dataclasses import dataclass
import time
from uuid import UUID, uuid4

from .contracts import ContractError, MAX_ATOMS, MODEL_ASSET, digest
from .points import (ISSUANCE_ACCOUNT, ISSUANCE_MONTHLY_CAP_ATOMS, month_start_ms, require_issuance_shape,
                     require_single_holder)
from .store import signed_atoms

PURPOSES = frozenset(
    (
        "external_clearing",
        "advertiser_available",
        "campaign_available",
        "offer_hold",
        "user_available",
        "user_locked",
        "provider_payable",
        "operator_payable",
        "direct_cost",
        "platform_revenue",
    )
)
KINDS = frozenset(
    (
        "model_seed",
        "transfer",
        "campaign_funding",
        "reserve",
        "award",
        "release",
        "payment",
        "refund",
        "expiry",
        "issuance",
        "grant",
        "sponsored_purchase",
        "growth_reward",
    )
)


def identifier(value):
    if type(value) is not str:
        raise ContractError("invalid_identifier")
    try:
        return str(UUID(value))
    except ValueError:
        raise ContractError("invalid_identifier") from None


def business_key(value):
    if (
        type(value) is not str
        or not 1 <= len(value) <= 160
        or any(ord(c) < 32 for c in value)
    ):
        raise ContractError("invalid_economic_key")
    return value


@dataclass(frozen=True)
class PostingResult:
    journal_id: str
    replayed: bool


class ModelLedger:
    def __init__(self, store):
        self.store = store

    def create_account(
        self, owner_id, purpose, *, account_id=None, asset_id=MODEL_ASSET
    ):
        self.store.require_model(asset_id)
        owner_id = identifier(owner_id)
        account_id = identifier(account_id) if account_id else str(uuid4())
        if purpose not in PURPOSES:
            raise ContractError("invalid_account_purpose")
        beneficial = int(purpose != "external_clearing")
        with self.store.atomic():
            self.store.lock("1:account_create:" + account_id)
            existing = self.store.one("account_get", (account_id,), locked=True)
            if existing:
                if (
                    existing["owner_id"],
                    existing["purpose"],
                    existing["asset_id"],
                ) != (owner_id, purpose, asset_id):
                    raise ContractError("account_identity_conflict", 409)
                return account_id
            self.store.execute(
                "account_insert",
                (account_id, owner_id, asset_id, purpose, beneficial, "0"),
            )
        return account_id

    def account(self, account_id):
        self.store.require_model(MODEL_ASSET)
        row = self.store.one("account_get", (identifier(account_id),))
        if row is None:
            raise ContractError("unknown_account", 404)
        return {**row, "balance_atoms": str(row["balance_atoms"])}

    def post(self, economic_key, postings, *, kind, asset_id=MODEL_ASSET):
        self.store.require_model(asset_id)
        economic_key = business_key(economic_key)
        if (
            kind not in KINDS
            or type(postings) not in (list, tuple)
            or not 2 <= len(postings) <= 64
        ):
            raise ContractError("invalid_postings")
        changes = {}
        for line in postings:
            if type(line) not in (list, tuple) or len(line) != 2:
                raise ContractError("invalid_posting")
            account_id, value = line
            account_id = identifier(account_id)
            amount = signed_atoms(value)
            if amount == 0:
                raise ContractError("zero_posting")
            changes[account_id] = changes.get(account_id, 0) + amount
        changes = {key: value for key, value in changes.items() if value}
        if (
            len(changes) < 2
            or sum(changes.values()) != 0
            or any(abs(n) > MAX_ATOMS for n in changes.values())
        ):
            raise ContractError("unbalanced_journal")
        ordered = sorted(changes.items())
        payload_hash = digest(
            {
                "asset_id": asset_id,
                "kind": kind,
                "postings": [[key, str(value)] for key, value in ordered],
            }
        )
        with self.store.atomic():
            self.store.lock("1:economic_event:" + asset_id + ":" + economic_key)
            old = self.store.one("journal_get", (asset_id, economic_key))
            if old:
                if old["payload_hash"] != payload_hash or old["state"] != "sealed":
                    raise ContractError("economic_event_conflict", 409)
                return PostingResult(old["id"], True)
            rows = {}
            for account_id, amount in ordered:
                row = self.store.one("account_get", (account_id,), locked=True)
                if row is None or row["asset_id"] != asset_id:
                    raise ContractError("account_asset_mismatch", 409)
                balance = int(row["balance_atoms"]) + amount
                if abs(balance) > MAX_ATOMS or (row["beneficial"] and balance < 0):
                    raise ContractError("insufficient_balance", 409)
                rows[account_id] = row, balance
            require_single_holder(kind, [row for row, _ in rows.values()])
            clearing = [
                (account_id, amount)
                for account_id, amount in ordered
                if rows[account_id][0]["purpose"] == "external_clearing"
            ]
            if kind == "model_seed":
                if (
                    len(clearing) != 1
                    or clearing[0][1] >= 0
                    or any(
                        amount <= 0
                        for account_id, amount in ordered
                        if account_id != clearing[0][0]
                    )
                ):
                    raise ContractError("invalid_model_seed", 409)
            elif kind == "issuance":
                require_issuance_shape(changes)
                self.store.lock("1:issuance_cap:" + asset_id)
                now_ms = int(time.time() * 1000)
                issued = self.store.one("issuance_month_total", (asset_id, ISSUANCE_ACCOUNT, month_start_ms(now_ms)))
                if -int(issued["total"]) - changes[ISSUANCE_ACCOUNT] > ISSUANCE_MONTHLY_CAP_ATOMS:
                    raise ContractError("issuance_monthly_cap_exceeded", 409)
            elif clearing:
                raise ContractError("clearing_requires_model_fixture", 403)
            journal_id = str(uuid4())
            self.store.execute(
                "journal_insert",
                (
                    journal_id,
                    asset_id,
                    economic_key,
                    payload_hash,
                    kind,
                    int(time.time() * 1000),
                ),
            )
            for line_no, (account_id, amount) in enumerate(ordered):
                row, balance = rows[account_id]
                self.store.execute(
                    "posting_insert",
                    (journal_id, line_no, asset_id, account_id, str(amount)),
                )
                changed = self.store.execute(
                    "account_update", (str(balance), account_id, row["version"])
                )
                if changed.rowcount != 1:
                    raise ContractError("account_version_conflict", 409)
            self.store.execute("journal_seal", (journal_id,))
            return PostingResult(journal_id, False)

    def audit(self):
        self.store.require_model(MODEL_ASSET)
        checked, beneficial, offset = 0, 0, 0
        with self.store.database.read():
            cursor = ""
            while True:
                rows = self.store.all("accounts_audit", (cursor,))
                if not rows:
                    break
                for row in rows:
                    expected = int(
                        self.store.one(
                            "postings_total_" + self.store.backend, (row["id"],)
                        )["total"]
                    )
                    if expected != int(row["balance_atoms"]):
                        raise ContractError("ledger_audit_mismatch", 503)
                    checked += 1
                    if row["beneficial"]:
                        beneficial += expected
                    else:
                        offset += expected
                cursor = rows[-1]["id"]
        if beneficial + offset != 0:
            raise ContractError("ledger_audit_mismatch", 503)
        return {
            "accounts_checked": checked,
            "beneficial_atoms": str(beneficial),
            "clearing_atoms": str(offset),
            "mode": "model",
            "real_reserve_verified": False,
        }
