"""In-process model credential registry adapter for human sessions, agent bindings, and reviewer mTLS."""

from dataclasses import dataclass
import hashlib
import hmac
import time
from uuid import UUID

from .contracts import ContractError
from .http import AuthContext
from .identity import Kind, Principal
from .ledger import identifier


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RegisteredCredential:
    principal_id: UUID
    kind: Kind
    epoch: int
    expires_at: float
    owner_id: UUID | None = None
    agent_binding_id: UUID | None = None
    csrf_secret_hash: str | None = None
    session_hash: str | None = None


class CredentialResolver:
    """Verifies human session+CSRF, agent bearer tokens, and reviewer mTLS independently of request claims."""

    def __init__(self, store, *, mtls_verifier=None, clock=None):
        self.store = store
        self._tokens: dict[str, RegisteredCredential] = {}
        self._sessions: dict[str, RegisteredCredential] = {}
        self._mtls_verifier = mtls_verifier or (lambda _request: False)
        self._clock = clock or time.time

    def register_human_session(
        self,
        session_token: str,
        csrf_token: str,
        *,
        principal_id: str,
        owner_id: str,
        epoch: int = 1,
        expires_at: float = 2_000_000_000.0,
    ) -> str:
        if not session_token or not csrf_token:
            raise ContractError("invalid_credential_registration")
        session_hash = _sha256_hex("session:" + session_token)
        record = RegisteredCredential(
            principal_id=UUID(identifier(principal_id)),
            kind=Kind.HUMAN,
            epoch=epoch,
            expires_at=expires_at,
            owner_id=UUID(identifier(owner_id)),
            csrf_secret_hash=_sha256_hex("csrf:" + csrf_token),
            session_hash=session_hash,
        )
        self._sessions[_sha256_hex(session_token)] = record
        self._tokens[_sha256_hex(session_token)] = record
        return session_hash

    def register_agent_token(
        self,
        bearer_token: str,
        *,
        principal_id: str,
        owner_id: str,
        agent_binding_id: str,
        epoch: int = 1,
        expires_at: float = 2_000_000_000.0,
    ):
        if not bearer_token:
            raise ContractError("invalid_credential_registration")
        self._tokens[_sha256_hex(bearer_token)] = RegisteredCredential(
            principal_id=UUID(identifier(principal_id)),
            kind=Kind.AGENT,
            epoch=epoch,
            expires_at=expires_at,
            owner_id=UUID(identifier(owner_id)),
            agent_binding_id=UUID(identifier(agent_binding_id)),
        )

    def register_reviewer_token(
        self,
        bearer_token: str,
        *,
        principal_id: str,
        epoch: int = 1,
        expires_at: float = 2_000_000_000.0,
    ):
        if not bearer_token:
            raise ContractError("invalid_credential_registration")
        self._tokens[_sha256_hex(bearer_token)] = RegisteredCredential(
            principal_id=UUID(identifier(principal_id)),
            kind=Kind.REVIEWER,
            epoch=epoch,
            expires_at=expires_at,
        )

    def __call__(self, request) -> AuthContext:
        auth_header = request.headers.get("authorization", "")
        cookie_header = request.headers.get("cookie", "")
        if auth_header and cookie_header:
            raise ContractError("mixed_credentials", 403)
        record = None
        if auth_header:
            if not auth_header.startswith("Bearer "):
                raise ContractError("authentication_required", 401)
            raw_token = auth_header[7:]
            record = self._tokens.get(_sha256_hex(raw_token))
        elif cookie_header:
            parts = [p.strip() for p in cookie_header.split(";") if "=" in p]
            cookies = dict(p.split("=", 1) for p in parts)
            raw_session = cookies.get("aiac_session", "")
            if raw_session:
                record = self._sessions.get(_sha256_hex(raw_session))
        if record is None:
            raise ContractError("authentication_required", 401)
        if record.expires_at <= self._clock():
            raise ContractError("authority_expired", 403)
        if record.kind == Kind.HUMAN:
            csrf_header = request.headers.get("x-csrf-token", "")
            csrf_ok = request.method == "GET" or (
                bool(csrf_header)
                and record.csrf_secret_hash is not None
                and hmac.compare_digest(
                    _sha256_hex("csrf:" + csrf_header), record.csrf_secret_hash
                )
            )
            principal = Principal(
                record.principal_id,
                Kind.HUMAN,
                record.epoch,
                record.expires_at,
                owner_id=record.owner_id,
                csrf_verified=csrf_ok,
                audience="aiac-v2-model",
            )
            return AuthContext(principal, record.session_hash)
        if record.kind == Kind.AGENT:
            principal = Principal(
                record.principal_id,
                Kind.AGENT,
                record.epoch,
                record.expires_at,
                owner_id=record.owner_id,
                agent_binding_id=record.agent_binding_id,
                audience="aiac-v2-model",
            )
            return AuthContext(principal, None)
        mtls_ok = self._mtls_verifier(request) is True
        principal = Principal(
            record.principal_id,
            Kind.REVIEWER,
            record.epoch,
            record.expires_at,
            mtls_verified=mtls_ok,
            audience="aiac-v2-reviewer",
        )
        return AuthContext(principal, None)
