"""Funded model reservations with separate original total/day accounting windows."""

from uuid import uuid4

from .contracts import ContractError, MODEL_ASSET, atoms, digest
from .ledger import business_key, identifier


def millis(value):
    if type(value) is not int or not 0 <= value <= 2**53 - 1:
        raise ContractError("invalid_time")
    return value


class ModelBudgets:
    def __init__(self, ledger):
        self.ledger, self.store = ledger, ledger.store

    def create_window(
        self, source_account, kind, start_ms, end_ms, limit_atoms, *, window_id=None
    ):
        source_account = identifier(source_account)
        window_id = identifier(window_id) if window_id else str(uuid4())
        start_ms, end_ms = millis(start_ms), millis(end_ms)
        limit = atoms(limit_atoms, positive=True)
        if kind not in ("total", "day") or end_ms <= start_ms:
            raise ContractError("invalid_budget_window")
        with self.store.atomic():
            self.store.lock("2:window:" + window_id)
            account = self.ledger.account(source_account)
            if account["purpose"] != "campaign_available":
                raise ContractError("campaign_account_required", 409)
            self.store.execute(
                "window_insert",
                (
                    window_id,
                    source_account,
                    MODEL_ASSET,
                    kind,
                    start_ms,
                    end_ms,
                    str(limit),
                    "0",
                    "0",
                ),
            )
        return window_id

    def _windows(self, total_id, day_id, source_account, now_ms=None):
        keys = sorted((identifier(total_id), identifier(day_id)))
        if keys[0] == keys[1]:
            raise ContractError("distinct_budget_windows_required")
        self.store.lock(*("2:window:" + key for key in keys))
        rows = {key: self.store.one("window_get", (key,), locked=True) for key in keys}
        if any(row is None for row in rows.values()):
            raise ContractError("unknown_budget_window", 404)
        total, day = rows[total_id], rows[day_id]
        if (
            total["kind"] != "total"
            or day["kind"] != "day"
            or any(
                r["source_account"] != source_account or r["asset_id"] != MODEL_ASSET
                for r in rows.values()
            )
            or day["starts_ms"] < total["starts_ms"]
            or day["ends_ms"] > total["ends_ms"]
        ):
            raise ContractError("budget_scope_mismatch", 409)
        if now_ms is not None and not all(
            r["starts_ms"] <= now_ms < r["ends_ms"] for r in rows.values()
        ):
            raise ContractError("budget_window_closed", 409)
        return total, day

    def _update(self, row, reserved, spent):
        if reserved < 0 or spent < 0 or reserved + spent > int(row["limit_atoms"]):
            raise ContractError("insufficient_budget", 409)
        changed = self.store.execute(
            "window_update", (str(reserved), str(spent), row["id"], row["version"])
        )
        if changed.rowcount != 1:
            raise ContractError("budget_version_conflict", 409)

    def reserve(
        self,
        source_account,
        total_window,
        day_window,
        amount_atoms,
        expires_ms,
        *,
        hold_id=None,
        now_ms,
    ):
        source_account, total_window, day_window = map(
            identifier, (source_account, total_window, day_window)
        )
        hold_id = identifier(hold_id) if hold_id else str(uuid4())
        amount = atoms(amount_atoms, positive=True)
        now_ms, expires_ms = millis(now_ms), millis(expires_ms)
        if expires_ms <= now_ms:
            raise ContractError("invalid_hold_expiry")
        payload_hash = digest(
            {
                "source": source_account,
                "total": total_window,
                "day": day_window,
                "amount": str(amount),
                "expires_ms": expires_ms,
            }
        )
        with self.store.atomic():
            self.store.lock("1:hold:" + hold_id)
            old = self.store.one("hold_get", (hold_id,), locked=True)
            if old:
                if old["payload_hash"] != payload_hash:
                    raise ContractError("hold_conflict", 409)
                return hold_id
            windows = self._windows(total_window, day_window, source_account, now_ms)
            for row in windows:
                self._update(
                    row, int(row["reserved_atoms"]) + amount, int(row["spent_atoms"])
                )
            source = self.ledger.account(source_account)
            if source["purpose"] != "campaign_available":
                raise ContractError("campaign_account_required", 409)
            hold_account = self.ledger.create_account(source["owner_id"], "offer_hold")
            self.ledger.post(
                "reserve:" + hold_id,
                [(source_account, str(-amount)), (hold_account, str(amount))],
                kind="reserve",
            )
            self.store.execute(
                "hold_insert",
                (
                    hold_id,
                    MODEL_ASSET,
                    source_account,
                    hold_account,
                    total_window,
                    day_window,
                    payload_hash,
                    expires_ms,
                    str(amount),
                    str(amount),
                    "held",
                ),
            )
        return hold_id

    def mark_review_pending(self, hold_id):
        hold_id = identifier(hold_id)
        with self.store.atomic():
            self.store.lock("1:hold:" + hold_id)
            row = self.store.one("hold_get", (hold_id,), locked=True)
            if row is None:
                raise ContractError("unknown_hold", 404)
            if row["state"] not in ("held", "partial", "review_pending"):
                raise ContractError("hold_closed", 409)
            self.store.execute(
                "hold_update", (str(row["remaining_atoms"]), "review_pending", hold_id)
            )

    def consume(self, hold_id, stage_key, allocations, *, resolve_review=False):
        hold_id, stage_key = identifier(hold_id), business_key(stage_key)
        if (
            type(resolve_review) is not bool
            or type(allocations) not in (list, tuple)
            or not 1 <= len(allocations) <= 32
        ):
            raise ContractError("invalid_allocation")
        combined = {}
        for line in allocations:
            if type(line) not in (tuple, list) or len(line) != 2:
                raise ContractError("invalid_allocation")
            account, amount = line
            account, amount = identifier(account), atoms(amount, positive=True)
            combined[account] = combined.get(account, 0) + amount
        amount = sum(combined.values())
        payload_hash = digest(
            {
                "kind": "consume",
                "allocation": [[k, str(v)] for k, v in sorted(combined.items())],
            }
        )
        with self.store.atomic():
            self.store.lock("1:hold:" + hold_id)
            row = self.store.one("hold_get", (hold_id,), locked=True)
            if row is None:
                raise ContractError("unknown_hold", 404)
            old = self.store.one("budget_event_get", (hold_id, stage_key))
            if old:
                if old["payload_hash"] != payload_hash or old["kind"] != "consume":
                    raise ContractError("budget_event_conflict", 409)
                return old["journal_id"]
            if (
                row["state"] not in ("held", "partial", "review_pending")
                or (row["state"] == "review_pending" and not resolve_review)
                or row["hold_account"] in combined
                or amount > int(row["remaining_atoms"])
            ):
                raise ContractError("hold_not_spendable", 409)
            for account in combined:
                target = self.ledger.account(account)
                if not target["beneficial"] or target["purpose"] in (
                    "campaign_available",
                    "advertiser_available",
                    "offer_hold",
                ):
                    raise ContractError("invalid_reward_recipient", 409)
            windows = self._windows(
                row["total_window"], row["day_window"], row["source_account"]
            )
            for window in windows:
                self._update(
                    window,
                    int(window["reserved_atoms"]) - amount,
                    int(window["spent_atoms"]) + amount,
                )
            economic_key = "budget:" + hold_id + ":" + digest({"stage": stage_key})
            result = self.ledger.post(
                economic_key,
                [
                    (row["hold_account"], str(-amount)),
                    *[(key, str(value)) for key, value in sorted(combined.items())],
                ],
                kind="award",
            )
            remaining = int(row["remaining_atoms"]) - amount
            self.store.execute(
                "hold_update",
                (str(remaining), "partial" if remaining else "consumed", hold_id),
            )
            self.store.execute(
                "budget_event_insert",
                (
                    hold_id,
                    stage_key,
                    payload_hash,
                    result.journal_id,
                    "consume",
                    str(amount),
                ),
            )
            return result.journal_id

    def release_expired(self, hold_id, event_key, *, now_ms):
        """Internal primitive: caller must first lock delivery state and prove release eligibility.

        Expiry alone cannot authorize releasing a qualified or undecided exposure.
        No expiry worker or public endpoint is installed by this module.
        """
        hold_id, event_key, now_ms = (
            identifier(hold_id),
            business_key(event_key),
            millis(now_ms),
        )
        with self.store.atomic():
            self.store.lock("1:hold:" + hold_id)
            row = self.store.one("hold_get", (hold_id,), locked=True)
            if row is None:
                raise ContractError("unknown_hold", 404)
            payload_hash = digest({"kind": "release", "hold_id": hold_id})
            old = self.store.one("budget_event_get", (hold_id, event_key))
            if old:
                if old["payload_hash"] != payload_hash or old["kind"] != "release":
                    raise ContractError("budget_event_conflict", 409)
                return old["journal_id"]
            if row["state"] not in ("held", "partial") or now_ms < row["expires_ms"]:
                raise ContractError("hold_not_releasable", 409)
            amount = int(row["remaining_atoms"])
            if amount <= 0:
                raise ContractError("hold_closed", 409)
            windows = self._windows(
                row["total_window"], row["day_window"], row["source_account"]
            )
            for window in windows:
                self._update(
                    window,
                    int(window["reserved_atoms"]) - amount,
                    int(window["spent_atoms"]),
                )
            result = self.ledger.post(
                "budget:" + hold_id + ":" + digest({"release": event_key}),
                [
                    (row["hold_account"], str(-amount)),
                    (row["source_account"], str(amount)),
                ],
                kind="release",
            )
            self.store.execute("hold_update", ("0", "released", hold_id))
            self.store.execute(
                "budget_event_insert",
                (
                    hold_id,
                    event_key,
                    payload_hash,
                    result.journal_id,
                    "release",
                    str(amount),
                ),
            )
            return result.journal_id

    def release_unspent(self, hold_id, event_key):
        """Release an unstarted declined offer or verified unqualified exposure hold."""
        hold_id, event_key = identifier(hold_id), business_key(event_key)
        with self.store.atomic():
            self.store.lock("1:hold:" + hold_id)
            row = self.store.one("hold_get", (hold_id,), locked=True)
            if row is None:
                raise ContractError("unknown_hold", 404)
            payload_hash = digest({"kind": "release", "hold_id": hold_id})
            old = self.store.one("budget_event_get", (hold_id, event_key))
            if old:
                if old["payload_hash"] != payload_hash or old["kind"] != "release":
                    raise ContractError("budget_event_conflict", 409)
                return old["journal_id"]
            if row["state"] not in ("held", "partial"):
                raise ContractError("hold_not_releasable", 409)
            amount = int(row["remaining_atoms"])
            if amount <= 0:
                raise ContractError("hold_closed", 409)
            windows = self._windows(
                row["total_window"], row["day_window"], row["source_account"]
            )
            for window in windows:
                self._update(
                    window,
                    int(window["reserved_atoms"]) - amount,
                    int(window["spent_atoms"]),
                )
            result = self.ledger.post(
                "budget:" + hold_id + ":" + digest({"release": event_key}),
                [
                    (row["hold_account"], str(-amount)),
                    (row["source_account"], str(amount)),
                ],
                kind="release",
            )
            self.store.execute("hold_update", ("0", "released", hold_id))
            self.store.execute(
                "budget_event_insert",
                (
                    hold_id,
                    event_key,
                    payload_hash,
                    result.journal_id,
                    "release",
                    str(amount),
                ),
            )
            return result.journal_id
