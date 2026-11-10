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
    COINS_ISSUED = "coins_issued"
    COINS_GRANTED = "coins_granted"
    SPONSORED_BOOKED = "sponsored_booked"
    SPONSORED_REFUNDED = "sponsored_refunded"


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


# Personal data in the audit trail is minimised before it is stored (docs/AD_COIN_PRIVACY_FLOW.md).
AUDIT_RETENTION_DAYS = 90          # audit entries are deleted after this many days
CREDENTIAL_RETENTION_DAYS = 30     # expired or revoked sessions and tokens are deleted this long after they end
_DAY_MS = 86_400_000


def coarse_ip(value):
    """Keep only the network part of an address: IPv4 /24, IPv6 /48. Anything else is dropped."""
    import ipaddress

    if not value or not isinstance(value, str):
        return None
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    prefix = 24 if address.version == 4 else 48
    return str(ipaddress.ip_network(f"{address}/{prefix}", strict=False))


_EMAIL = __import__("re").compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = __import__("re").compile(r"(?<![\w-])(?:\+\d{1,3}[\s.-]?)?\(?\d{2,4}\)?[\s.-]\d{3,4}[\s.-]\d{4}(?![\w-])")
_IPV4 = __import__("re").compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def scrub_text(value):
    """Free text in audit details (review reasons, grant reasons, names) keeps no contact data."""
    if not isinstance(value, str):
        return value
    value = _EMAIL.sub("[email removed]", value)
    value = _IPV4.sub("[address removed]", value)
    return _PHONE.sub("[number removed]", value)


def _scrub_details(details):
    if isinstance(details, dict):
        return {key: _scrub_details(item) for key, item in details.items()}
    if isinstance(details, (list, tuple)):
        return [_scrub_details(item) for item in details]
    return scrub_text(details)


def client_class(user_agent):
    """Store a coarse client class instead of the raw user agent string."""
    if not user_agent or not isinstance(user_agent, str):
        return None
    text = user_agent.lower()
    if any(word in text for word in ("bot", "crawler", "spider", "curl", "python", "httpx", "wget")):
        return "automated"
    if "mobile" in text or "android" in text or "iphone" in text:
        return "mobile_browser"
    if "mozilla" in text:
        return "browser"
    return "other"



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
        details_json = json.dumps(_scrub_details(details or {}), sort_keys=True, separators=(",", ":"))

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
                    coarse_ip(client_ip),
                    client_class(user_agent),
                    status,
                    details_json,
                ),
            )
        return entry_id

    @staticmethod
    def prune(store, *, now_ms: int, batch: int = 500, max_batches: int = 20) -> int:
        """Delete audit entries older than AUDIT_RETENTION_DAYS, in bounded batches."""
        cutoff = millis(now_ms - AUDIT_RETENTION_DAYS * _DAY_MS)
        removed = 0
        for _ in range(max_batches):
            with store.atomic():
                count = store.execute("audit_log_prune", (cutoff, batch)).rowcount or 0
            removed += count
            if count < batch:
                break
        return removed

    @staticmethod
    def recent(store, limit: int = 50) -> list[dict]:
        with store.atomic():
            rows = store.execute("audit_log_recent", (limit,)).fetchall()
            return [dict(r) for r in rows]


def prune_credentials(store, *, now_ms: int, batch: int = 500) -> int:
    """Delete sessions and tokens that ended more than CREDENTIAL_RETENTION_DAYS ago."""
    cutoff = (now_ms - CREDENTIAL_RETENTION_DAYS * _DAY_MS) / 1000.0
    removed = 0
    for name in ("human_session_prune", "agent_token_prune", "reviewer_credential_prune"):
        with store.atomic():
            removed += store.execute(name, (cutoff, cutoff, batch)).rowcount or 0
    return removed
