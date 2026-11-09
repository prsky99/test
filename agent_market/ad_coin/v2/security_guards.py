"""Security rate limiters, abuse protection guards, and immutable audit logging."""

import json
from threading import Lock
import time
from uuid import uuid4

from .budgets import millis
from .contracts import ContractError
from .ledger import identifier


class EventType:
    CAMPAIGN_APPROVED = "campaign_approved"
    CAMPAIGN_ACTIVATED = "campaign_activated"
    CAMPAIGN_PAUSED = "campaign_paused"
    CAMPAIGN_RESUMED = "campaign_resumed"
    CAMPAIGN_REVISED = "campaign_revised"
    OFFER_APPROVED = "offer_approved"
    OFFER_DECLINED = "offer_declined"
    RECEIPT_SIGNED = "receipt_signed"
    KEY_ROTATED = "key_rotated"
    EPOCH_ROTATED = "epoch_rotated"
    SESSION_REVOKED = "session_revoked"
    APPEAL_SUBMITTED = "appeal_submitted"
    APPEAL_DECIDED = "appeal_decided"
    MANDATE_CREATED = "mandate_created"
    MANDATE_REVOKED = "mandate_revoked"
    EXECUTION_HELD = "execution_held"
    EXECUTION_SETTLED = "execution_settled"
    EXECUTION_REFUNDED = "execution_refunded"
    RELAY_PARTNER_REGISTERED = "relay_partner_registered"
    RELAY_PARTNER_REVOKED = "relay_partner_revoked"
    RELAY_DISPATCHED = "relay_dispatched"
    RELAY_CONSENTED = "relay_consented"
    RELAY_SETTLED = "relay_settled"
    RELAY_EXPIRED = "relay_expired"
    RELAY_REJECTED = "relay_rejected"
    STAGE_CLAIMED = "stage_claimed"
    STAGE_SETTLED = "stage_settled"
    EXPERIMENT_CREATED = "experiment_created"
    EXPERIMENT_UPDATED = "experiment_updated"
    CONVERSION_RECORDED = "conversion_recorded"


class TokenBucketRateLimiter:
    """Thread-safe token bucket rate limiter for public and authenticated endpoints."""

    def __init__(self, clock=None):
        self._clock = clock or time.time
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, last_refreshed)
        self._lock = Lock()

    def check(self, key: str, *, limit_per_minute: int = 60, cost: int = 1) -> tuple[bool, int]:
        """Check if request is allowed. Returns (allowed, retry_after_seconds)."""
        now = self._clock()
        rate = limit_per_minute / 60.0  # tokens per second
        capacity = float(limit_per_minute)

        with self._lock:
            if key not in self._buckets:
                self._buckets[key] = (capacity - cost, now)
                return True, 0

            tokens, last_time = self._buckets[key]
            elapsed = max(0.0, now - last_time)
            tokens = min(capacity, tokens + elapsed * rate)

            if tokens >= cost:
                self._buckets[key] = (tokens - cost, now)
                return True, 0

            deficit = cost - tokens
            retry_after = max(1, int(deficit / rate) + 1)
            self._buckets[key] = (tokens, now)
            return False, retry_after

    def clear(self):
        with self._lock:
            self._buckets.clear()


class AuditLogger:
    """Immutable audit trail writer for financial and operational events."""

    @staticmethod
    def log(
        store,
        event_type: str,
        status: str,
        *,
        actor_principal_id: str | None = None,
        actor_owner_id: str | None = None,
        target_id: str | None = None,
        client_ip: str | None = None,
        user_agent: str | None = None,
        details: dict | None = None,
        now_ms: int | None = None,
    ) -> str:
        if status not in ("succeeded", "denied", "failed"):
            raise ContractError("invalid_audit_status")

        entry_id = str(uuid4())
        ts = millis(now_ms if now_ms is not None else int(time.time() * 1000))
        details_json = json.dumps(details or {}, sort_keys=True, separators=(",", ":"))

        with store.atomic():
            store.execute(
                "audit_log_insert",
                (
                    entry_id,
                    ts,
                    event_type,
                    identifier(actor_principal_id) if actor_principal_id else None,
                    identifier(actor_owner_id) if actor_owner_id else None,
                    identifier(target_id) if target_id else None,
                    client_ip,
                    user_agent,
                    status,
                    details_json,
                ),
            )
        return entry_id

    @staticmethod
    def recent(store, limit: int = 50) -> list[dict]:
        with store.atomic():
            rows = store.execute("audit_log_recent", (limit,)).fetchall()
            return [dict(r) for r in rows]
