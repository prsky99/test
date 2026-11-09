"""Recompute P1 time from the immutable, bounded server evidence prefix."""

from dataclasses import dataclass
import hashlib

from .contracts import ContractError, digest


@dataclass(frozen=True)
class EvidenceSummary:
    valid_ms: int = 0
    qualified_ms: int | None = None
    first_signal_ms: int | None = None
    last_signal_ms: int | None = None
    last_claim_ms: int = 0
    active_deadline_ms: int | None = None


def verify_prefix(session, chunks, *, cutoff_ms):
    """Client visibility is a claim, never proof of biological presence or attention."""
    if len(chunks) > 301:
        raise ContractError("invalid_evidence_prefix", 409)
    valid, qualified, first, previous = 0, None, None, None
    active_end = None
    for sequence, row in enumerate(chunks):
        received, claim = int(row["server_received_ms"]), int(row["elapsed_claim_ms"])
        canonical_hash = digest(
            {
                "session_id": session["id"],
                "sequence": sequence,
                "nonce_hash": row["nonce_hash"],
                "elapsed_claim_ms": claim,
                "visible": bool(row["visible"]),
                "foreground": bool(row["foreground"]),
            }
        )
        if (
            row["sequence"] != sequence
            or received > cutoff_ms
            or received > session["evidence_deadline_ms"]
            or canonical_hash != row["canonical_hash"]
            or not 0 <= claim <= 30000
        ):
            raise ContractError("invalid_evidence_prefix", 409)
        if previous is not None:
            if (
                received < previous["server_received_ms"]
                or claim < previous["elapsed_claim_ms"]
            ):
                raise ContractError("non_monotonic_evidence", 409)
            if (
                hashlib.sha256(
                    previous["issued_next_nonce"].encode("ascii")
                ).hexdigest()
                != row["nonce_hash"]
            ):
                raise ContractError("invalid_evidence_prefix", 409)
        positive = bool(row["visible"] and row["foreground"])
        if positive and first is None:
            if received > session["startup_deadline_ms"]:
                raise ContractError("startup_deadline_exceeded", 409)
            first, active_end = received, received + int(session["max_view_ms"])
        elif (
            positive
            and previous is not None
            and previous["visible"]
            and previous["foreground"]
        ):
            elapsed = received - int(previous["server_received_ms"])
            claimed = claim - int(previous["elapsed_claim_ms"])
            if (
                active_end is not None
                and received <= active_end
                and 0 < elapsed <= 3000
            ):
                valid += min(elapsed, claimed)
                if valid >= 15000 and qualified is None:
                    qualified = received
        previous = row
    return EvidenceSummary(
        min(int(session["max_view_ms"]), valid),
        qualified,
        first,
        int(previous["server_received_ms"])
        if previous is not None and first is not None
        else None,
        int(previous["elapsed_claim_ms"]) if previous is not None else 0,
        active_end,
    )
