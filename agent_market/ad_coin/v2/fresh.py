"""Short-lived human action binding; never evidence of a human advertisement view."""

from dataclasses import dataclass, field
import base64
import hashlib
import hmac
import secrets
from uuid import uuid4

from .budgets import millis
from .commands import AuthorityGuards
from .contracts import ContractError
from .identity import Kind, Principal
from .ledger import identifier

ACTIONS = frozenset(("set_ad_preferences", "approve_offer", "approve_campaign"))


def fingerprint(value):
    if (
        type(value) is not str
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ContractError("invalid_binding_hash")
    return value


def _binding(
    action, target_id, revision_hash, semantic_digest, session_hash, precondition
):
    if action not in ACTIONS:
        raise ContractError("unsupported_fresh_action")
    if precondition is not None and (
        type(precondition) is not str or not 1 <= len(precondition) <= 128
    ):
        raise ContractError("invalid_precondition")
    return (
        action,
        identifier(target_id),
        fingerprint(revision_hash),
        fingerprint(semantic_digest),
        fingerprint(session_hash),
        precondition,
    )


@dataclass(frozen=True)
class FreshChallenge:
    id: str
    proof: str = field(repr=False)
    expires_ms: int


class FreshActions:
    def __init__(self, store, proof_key=None, *, fallback_keys=()):
        self.store, self.guards = store, AuthorityGuards(store)
        if proof_key is not None and (
            type(proof_key) is not bytes or len(proof_key) != 32
        ):
            raise ContractError("invalid_fresh_key", 503)
        if type(fallback_keys) is not tuple or any(
            type(key) is not bytes or len(key) != 32 for key in fallback_keys
        ):
            raise ContractError("invalid_fresh_key", 503)
        self._proof_key = proof_key
        self._fallback_keys = fallback_keys

    def _derive_with(self, key, challenge_id):
        message = b"aiac-v2-model-fresh-v1\0" + identifier(challenge_id).encode("ascii")
        return (
            base64.urlsafe_b64encode(hmac.digest(key, message, "sha256"))
            .rstrip(b"=")
            .decode("ascii")
        )

    def _derive(self, challenge_id):
        if self._proof_key is None:
            raise ContractError("fresh_key_unavailable", 503)
        return self._derive_with(self._proof_key, challenge_id)

    def _human(self, principal, now_ms):
        if (
            not isinstance(principal, Principal)
            or principal.kind != Kind.HUMAN
            or principal.audience != "aiac-v2-model"
            or not principal.csrf_verified
            or principal.expires_at * 1000 <= now_ms
        ):
            raise ContractError("fresh_human_session_required", 403)
        if self.guards.current(str(principal.id)) != principal.epoch:
            raise ContractError("authority_revoked", 403)

    def issue(
        self,
        principal,
        *,
        session_hash,
        action,
        target_id,
        revision_hash,
        semantic_digest,
        now_ms,
        precondition=None,
        ttl_ms=120000,
    ):
        """A trusted human transport must authorize target access before issuing a challenge."""
        now_ms = millis(now_ms)
        if type(ttl_ms) is not int or not 1 <= ttl_ms <= 120000:
            raise ContractError("invalid_fresh_ttl")
        expires_ms = millis(now_ms + ttl_ms)
        (
            action,
            target_id,
            revision_hash,
            semantic_digest,
            session_hash,
            precondition,
        ) = _binding(
            action,
            target_id,
            revision_hash,
            semantic_digest,
            session_hash,
            precondition,
        )
        with self.store.atomic():
            self._human(principal, now_ms)
            challenge_id = str(uuid4())
            proof = (
                self._derive(challenge_id)
                if self._proof_key is not None
                else secrets.token_urlsafe(32)
            )
            challenge_hash = hashlib.sha256(proof.encode("ascii")).hexdigest()
            self.store.execute(
                "fresh_insert",
                (
                    challenge_id,
                    str(principal.id),
                    str(principal.owner_id),
                    principal.epoch,
                    session_hash,
                    action,
                    target_id,
                    revision_hash,
                    semantic_digest,
                    precondition,
                    challenge_hash,
                    expires_ms,
                ),
            )
            return FreshChallenge(challenge_id, proof, expires_ms)

    def recover(self, challenge_id, principal, *, session_hash, now_ms):
        """Recover the same session-bound proof without persisting plaintext in response snapshots."""
        challenge_id, session_hash, now_ms = (
            identifier(challenge_id),
            fingerprint(session_hash),
            millis(now_ms),
        )
        self.store._connection()
        self._human(principal, now_ms)
        row = self.store.one("fresh_get", (challenge_id,))
        if (
            not row
            or row["principal_id"] != str(principal.id)
            or row["owner_id"] != str(principal.owner_id)
            or row["credential_epoch"] != principal.epoch
            or row["session_hash"] != session_hash
        ):
            raise ContractError("fresh_action_binding_mismatch", 403)
        if now_ms >= row["expires_ms"]:
            raise ContractError("fresh_action_expired", 409)
        if self._proof_key is None:
            raise ContractError("fresh_key_unavailable", 503)
        for candidate_key in (self._proof_key, *self._fallback_keys):
            proof = self._derive_with(candidate_key, challenge_id)
            if hmac.compare_digest(
                hashlib.sha256(proof.encode("ascii")).hexdigest(),
                row["challenge_hash"],
            ):
                return proof
        raise ContractError("fresh_key_unavailable", 503)

    def consume(
        self,
        challenge_id,
        proof,
        principal,
        *,
        operation_id,
        session_hash,
        action,
        target_id,
        revision_hash,
        semantic_digest,
        now_ms,
        precondition=None,
    ):
        """Must run inside the command transaction so failures restore the unspent challenge."""
        self.store._connection()
        now_ms, challenge_id, operation_id = (
            millis(now_ms),
            identifier(challenge_id),
            identifier(operation_id),
        )
        expected = _binding(
            action,
            target_id,
            revision_hash,
            semantic_digest,
            session_hash,
            precondition,
        )
        if type(proof) is not str or len(proof) != 43 or not proof.isascii():
            raise ContractError("invalid_fresh_proof", 403)
        self._human(principal, now_ms)
        row = self.store.one("fresh_get", (challenge_id,))
        if row is None:
            raise ContractError("unknown_fresh_action", 404)
        actual = tuple(
            row[key]
            for key in (
                "action",
                "target_id",
                "revision_hash",
                "semantic_digest",
                "session_hash",
                "precondition",
            )
        )
        proof_hash = hashlib.sha256(proof.encode("ascii")).hexdigest()
        if (
            expected != actual
            or row["principal_id"] != str(principal.id)
            or row["owner_id"] != str(principal.owner_id)
            or row["credential_epoch"] != principal.epoch
            or not hmac.compare_digest(row["challenge_hash"], proof_hash)
        ):
            raise ContractError("fresh_action_binding_mismatch", 403)
        if now_ms >= row["expires_ms"]:
            raise ContractError("fresh_action_expired", 409)
        if row["consumed_by_operation"] is not None:
            if row["consumed_by_operation"] != operation_id:
                raise ContractError("fresh_action_already_consumed", 409)
            return False
        if (
            self.store.execute("fresh_consume", (operation_id, challenge_id)).rowcount
            != 1
        ):
            raise ContractError("fresh_action_conflict", 409)
        return True
