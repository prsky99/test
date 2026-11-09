"""UTC model attention reservations, independent of reward funds and qualification."""

from uuid import uuid4

from .budgets import millis
from .contracts import ContractError, digest
from .ledger import identifier

DAY_MS = 86400000
MIN_VIEW_MS = 15000
MAX_VIEW_MS = 30000
STARTUP_MS = 10000


class Attention:
    def __init__(self, store):
        self.store = store

    def create_window(
        self,
        owner_id,
        scope_kind,
        scope_id,
        *,
        day_start_ms,
        count_limit,
        time_limit_ms,
    ):
        """Limits come from verified preferences/policy, never directly from a visiting agent."""
        owner_id, scope_id = identifier(owner_id), identifier(scope_id)
        day_start_ms = millis(day_start_ms)
        if (
            scope_kind not in ("global", "advertiser", "campaign")
            or (scope_kind == "global" and scope_id != owner_id)
            or day_start_ms % DAY_MS
            or type(count_limit) is not int
            or not 1 <= count_limit <= 10000
            or type(time_limit_ms) is not int
            or not MIN_VIEW_MS <= time_limit_ms <= DAY_MS
        ):
            raise ContractError("invalid_attention_window")
        with self.store.atomic():
            self.store.lock("1:attention_owner:" + owner_id)
            row = self.store.one(
                "attention_window_get", (owner_id, scope_kind, scope_id, day_start_ms)
            )
            if row:
                if (row["count_limit"], row["time_limit_ms"]) != (
                    count_limit,
                    time_limit_ms,
                ):
                    raise ContractError("attention_window_conflict", 409)
                return row["id"]
            window_id = str(uuid4())
            self.store.execute(
                "attention_window_insert",
                (
                    window_id,
                    owner_id,
                    scope_kind,
                    scope_id,
                    day_start_ms,
                    count_limit,
                    time_limit_ms,
                ),
            )
            return window_id

    def _update(self, row, started, reserved, observed):
        if (
            reserved < 0
            or observed < 0
            or reserved + observed > row["time_limit_ms"]
            or started < 0
            or started > row["count_limit"]
        ):
            raise ContractError("attention_limit_exceeded", 429)
        if (
            self.store.execute(
                "attention_window_update",
                (started, reserved, observed, row["id"], row["version"]),
            ).rowcount
            != 1
        ):
            raise ContractError("attention_version_conflict", 409)

    def reserve(
        self,
        session_id,
        owner_id,
        advertiser_id,
        campaign_id,
        *,
        now_ms,
        maximum_ms=MAX_VIEW_MS,
    ):
        if type(maximum_ms) is not int or not MIN_VIEW_MS <= maximum_ms <= MAX_VIEW_MS:
            raise ContractError("invalid_attention_reservation")
        session_id, owner_id, advertiser_id, campaign_id = map(
            identifier, (session_id, owner_id, advertiser_id, campaign_id)
        )
        now_ms = millis(now_ms)
        day_start = now_ms // DAY_MS * DAY_MS
        payload_hash = digest(
            {
                "owner": owner_id,
                "advertiser": advertiser_id,
                "campaign": campaign_id,
                "day_start_ms": day_start,
            }
        )
        with self.store.atomic():
            self.store.lock("1:attention_owner:" + owner_id)
            old = self.store.one("attention_session_get", (session_id,))
            if old:
                if old["owner_id"] != owner_id or old["payload_hash"] != payload_hash:
                    raise ContractError("attention_session_conflict", 409)
                return {
                    "session_id": session_id,
                    "reserved_ms": old["reserved_ms"],
                    "state": old["state"],
                    "replayed": True,
                }
            if self.store.one("attention_active", (owner_id,)):
                raise ContractError("active_exposure_exists", 409)
            if day_start + DAY_MS - now_ms < STARTUP_MS + MAX_VIEW_MS:
                raise ContractError("attention_window_closing", 409)
            rows = []
            # Same scope order for all paths; the owner guard also serializes different campaigns.
            for kind, scope_id in (
                ("global", owner_id),
                ("advertiser", advertiser_id),
                ("campaign", campaign_id),
            ):
                row = self.store.one(
                    "attention_window_get", (owner_id, kind, scope_id, day_start)
                )
                if row is None:
                    raise ContractError("attention_configuration_required", 409)
                rows.append(row)
            reserved = min(
                maximum_ms,
                *(
                    row["time_limit_ms"] - row["reserved_ms"] - row["observed_ms"]
                    for row in rows
                ),
            )
            if reserved < MIN_VIEW_MS or any(
                row["started_sessions"] >= row["count_limit"] for row in rows
            ):
                raise ContractError("attention_limit_exceeded", 429)
            self.store.execute(
                "attention_session_insert",
                (session_id, owner_id, payload_hash, reserved),
            )
            for row in rows:
                self._update(
                    row,
                    row["started_sessions"] + 1,
                    row["reserved_ms"] + reserved,
                    row["observed_ms"],
                )
                self.store.execute(
                    "attention_reservation_insert", (session_id, row["id"], reserved)
                )
            return {
                "session_id": session_id,
                "reserved_ms": reserved,
                "state": "active",
                "replayed": False,
            }

    def close(self, session_id, owner_id, *, consumed_ms=None):
        """Unknown evidence consumes the full reservation; no ad billing or reward is implied."""
        session_id, owner_id = identifier(session_id), identifier(owner_id)
        if consumed_ms is not None and (
            type(consumed_ms) is not int or consumed_ms < 0
        ):
            raise ContractError("invalid_attention_consumption")
        with self.store.atomic():
            self.store.lock("1:attention_owner:" + owner_id)
            row = self.store.one("attention_session_get", (session_id,))
            if not row or row["owner_id"] != owner_id:
                raise ContractError("unknown_attention_session", 404)
            consumed = row["reserved_ms"] if consumed_ms is None else consumed_ms
            if consumed > row["reserved_ms"]:
                raise ContractError("invalid_attention_consumption")
            settlement_hash = digest({"consumed_ms": consumed})
            if row["state"] == "closed":
                if row["settlement_hash"] != settlement_hash:
                    raise ContractError("attention_settlement_conflict", 409)
                return False
            reservations = self.store.all("attention_reservations", (session_id,))
            if len(reservations) != 3:
                raise ContractError("attention_reservation_incomplete", 503)
            for reservation in reservations:
                window = self.store.one(
                    "attention_window_id", (reservation["window_id"],)
                )
                self._update(
                    window,
                    window["started_sessions"],
                    window["reserved_ms"] - reservation["reserved_ms"],
                    window["observed_ms"] + consumed,
                )
                if (
                    self.store.execute(
                        "attention_reservation_close",
                        (consumed, session_id, window["id"]),
                    ).rowcount
                    != 1
                ):
                    raise ContractError("attention_settlement_conflict", 409)
            self.store.execute("attention_session_close", (settlement_hash, session_id))
            return True
