"""Persistent PostgreSQL-backed credential resolver for human sessions, agent bindings, and reviewer mTLS."""

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


class PersistentCredentialResolver:
    """Production database-backed resolver ensuring persistent authentication across process restarts."""

    SITE_COOKIE = "__Host-ac_customer_session"
    SITE_PRINCIPAL_SECONDS = 300  # a site-session principal is re-derived on every request

    def __init__(self, store, *, mtls_verifier=None, clock=None, customer_identity=None, owner_link_key=None):
        self.store = store
        self._mtls_verifier = mtls_verifier or (lambda req: req.headers.get("x-mock-tls") == "verified")
        self._clock = clock or time.time
        # Site sign-in bridge: a callable returning the customer identity core (or None when customer
        # workspaces are closed) and the server-secret HMAC key that derives v2 ids from customer ids.
        if customer_identity is not None and (type(owner_link_key) is not bytes or len(owner_link_key) != 32):
            raise ContractError("owner_link_key_required", 503)
        self._customer_identity = customer_identity
        self._owner_link_key = owner_link_key

    def _linked_id(self, label, customer_id):
        """A v2 id derived with the server secret; it cannot be computed from the customer id alone."""
        digest = hmac.new(self._owner_link_key, (label + customer_id).encode("utf-8"), hashlib.sha256).digest()
        return str(UUID(bytes=digest[:16], version=4))

    def site_customer(self, request):
        """The signed-in site customer behind a request: (customer_id, owner_id, principal_id, csrf_ok).

        Every call re-checks the site session, so signing out or revoking it takes effect at once."""
        identity = self._customer_identity() if self._customer_identity is not None else None
        token = self._site_token(request) if identity is not None else None
        if not token:
            raise ContractError("authentication_required", 401)
        from ...workflow_publication_service import same_origin
        from ...workspace_access import WorkspaceDenied
        if not same_origin(request):
            raise ContractError("cross_origin_refused", 403)
        try:
            actor = identity.actor(token)
        except (WorkspaceDenied, ValueError, TypeError, KeyError, LookupError):
            raise ContractError("authentication_required", 401) from None
        customer_id = str(actor.customer_id)
        proof = request.headers.get("x-csrf-token", "")
        csrf_ok = request.method == "GET" or (bool(proof) and hmac.compare_digest(proof, identity.csrf(token)))
        return (customer_id, self._linked_id("adc2-owner:", customer_id),
                self._linked_id("adc2-principal:", customer_id), csrf_ok)

    def _site_token(self, request):
        """The one site session cookie, read from the raw header; two copies are refused so the session
        that is checked is always the session that is used."""
        values = [part.split("=", 1)[1].strip() for header in request.headers.getlist("cookie")
                  for part in header.split(";") if part.strip().startswith(self.SITE_COOKIE + "=")]
        if len(values) > 1:
            raise ContractError("duplicate_session_cookie", 401)
        return values[0] if values else None

    def _site_context(self, request, now):
        customer_id, owner_id, principal_id, csrf_ok = self.site_customer(request)
        guard = self.store.one("guard_get", (principal_id,))
        if guard is None:
            self._provision_site_person(customer_id, owner_id, principal_id, now)
            guard = self.store.one("guard_get", (principal_id,))
        if guard is None or guard["status"] != "active":
            raise ContractError("authority_revoked", 403)
        principal = Principal(UUID(principal_id), Kind.HUMAN, guard["epoch"], now + self.SITE_PRINCIPAL_SECONDS,
                              owner_id=UUID(owner_id), csrf_verified=csrf_ok, audience="aiac-v2-model")
        return AuthContext(principal, _sha256_hex("session:" + self._site_token(request)))

    def _provision_site_person(self, customer_id, owner_id, principal_id, now):
        """First use: an ordinary person (no advertiser or operator authority), preferences and a wallet.
        No customer id, e-mail or name is stored; only the derived ids."""
        from .access import HUMAN_CAPABILITIES, Access
        access = Access(self.store)
        with self.store.atomic():
            self.store.lock("site_person:" + principal_id)
            access.provision_principal(principal_id, Kind.HUMAN, owner_id=owner_id, capabilities=HUMAN_CAPABILITIES)
            access.provision_preferences(owner_id, now_ms=int(now * 1000))
            access.provision_wallet(owner_id, wallet_id=self._linked_id("adc2-wallet:", customer_id))

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
        token_hash = _sha256_hex(session_token)
        csrf_secret_hash = _sha256_hex("csrf:" + csrf_token)
        now = self._clock()
        with self.store.atomic():
            self.store.execute(
                "human_session_insert",
                (
                    token_hash,
                    csrf_secret_hash,
                    identifier(principal_id),
                    identifier(owner_id),
                    epoch,
                    now,
                    expires_at,
                    None,
                ),
            )
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
        token_hash = _sha256_hex(bearer_token)
        now = self._clock()
        with self.store.atomic():
            self.store.execute(
                "agent_token_insert",
                (
                    token_hash,
                    identifier(principal_id),
                    identifier(owner_id),
                    identifier(agent_binding_id),
                    epoch,
                    now,
                    expires_at,
                    None,
                ),
            )

    def register_reviewer_token(
        self,
        bearer_token: str,
        *,
        principal_id: str,
        cert_fingerprint: str | None = None,
        epoch: int = 1,
        expires_at: float = 2_000_000_000.0,
    ):
        if not bearer_token:
            raise ContractError("invalid_credential_registration")
        token_hash = _sha256_hex(bearer_token)
        now = self._clock()
        with self.store.atomic():
            self.store.execute(
                "reviewer_credential_insert",
                (
                    token_hash,
                    identifier(principal_id),
                    cert_fingerprint,
                    epoch,
                    now,
                    expires_at,
                    None,
                ),
            )

    def revoke_human_session(self, session_token: str):
        token_hash = _sha256_hex(session_token)
        with self.store.atomic():
            self.store.execute("human_session_revoke", (self._clock(), token_hash))

    def revoke_agent_token(self, bearer_token: str):
        token_hash = _sha256_hex(bearer_token)
        with self.store.atomic():
            self.store.execute("agent_token_revoke", (self._clock(), token_hash))

    def revoke_reviewer_token(self, bearer_token: str):
        token_hash = _sha256_hex(bearer_token)
        with self.store.atomic():
            self.store.execute("reviewer_credential_revoke", (self._clock(), token_hash))

    def rotate_principal_epoch(self, principal_id: str) -> int:
        principal_id = identifier(principal_id)
        with self.store.atomic():
            guard = self.store.one("guard_get", (principal_id,))
            if guard is None:
                raise ContractError("unknown_resource", 404)
            self.store.execute("guard_bump", (principal_id,))
            updated_guard = self.store.one("guard_get", (principal_id,))
            return int(updated_guard["epoch"])

    def __call__(self, request) -> AuthContext:
        auth_header = request.headers.get("authorization", "")
        cookie_header = request.headers.get("cookie", "")
        if auth_header and cookie_header:
            raise ContractError("mixed_credentials", 403)

        now = self._clock()

        if cookie_header:
            parts = [p.strip() for p in cookie_header.split(";") if "=" in p]
            cookies = dict(p.split("=", 1) for p in parts)
            if self._customer_identity is not None and cookies.get(self.SITE_COOKIE):
                return self._site_context(request, now)  # the site sign-in is the only source for this cookie
            raw_session = cookies.get("__Host-ac_customer_session") or cookies.get("aiac_session", "")
            if not raw_session:
                raise ContractError("authentication_required", 401)
            token_hash = _sha256_hex(raw_session)
            row = self.store.one("human_session_get", (token_hash,))
            if row is None or row["revoked_at"] is not None:
                raise ContractError("authentication_required", 401)
            if row["expires_at"] <= now:
                raise ContractError("authority_expired", 403)

            # Check principal epoch
            guard = self.store.one("guard_get", (row["principal_id"],))
            if guard is None or guard["status"] != "active" or guard["epoch"] != row["epoch"]:
                raise ContractError("authority_revoked", 403)

            csrf_header = request.headers.get("x-csrf-token", "")
            csrf_ok = request.method == "GET" or (
                bool(csrf_header)
                and hmac.compare_digest(
                    _sha256_hex("csrf:" + csrf_header), row["csrf_secret_hash"]
                )
            )

            session_hash = _sha256_hex("session:" + raw_session)
            principal = Principal(
                UUID(row["principal_id"]),
                Kind.HUMAN,
                row["epoch"],
                row["expires_at"],
                owner_id=UUID(row["owner_id"]),
                csrf_verified=csrf_ok,
                audience="aiac-v2-model",
            )
            return AuthContext(principal, session_hash)

        if auth_header:
            if not auth_header.startswith("Bearer "):
                raise ContractError("authentication_required", 401)
            raw_token = auth_header[7:]
            token_hash = _sha256_hex(raw_token)

            # 1. Try agent token
            agent_row = self.store.one("agent_token_get", (token_hash,))
            if agent_row is not None:
                if agent_row["revoked_at"] is not None:
                    raise ContractError("authentication_required", 401)
                if agent_row["expires_at"] <= now:
                    raise ContractError("authority_expired", 403)
                # Verify binding is still active
                binding = self.store.one("agent_binding_get", (agent_row["agent_binding_id"],))
                if binding is None or binding["active"] != 1:
                    raise ContractError("authority_revoked", 403)
                # Verify principal epoch
                guard = self.store.one("guard_get", (agent_row["principal_id"],))
                if guard is None or guard["status"] != "active" or guard["epoch"] != agent_row["epoch"]:
                    raise ContractError("authority_revoked", 403)

                principal = Principal(
                    UUID(agent_row["principal_id"]),
                    Kind.AGENT,
                    agent_row["epoch"],
                    agent_row["expires_at"],
                    owner_id=UUID(agent_row["owner_id"]),
                    agent_binding_id=UUID(agent_row["agent_binding_id"]),
                    audience="aiac-v2-model",
                )
                return AuthContext(principal, None)

            # 2. Try reviewer credential
            rev_row = self.store.one("reviewer_credential_get", (token_hash,))
            if rev_row is not None:
                if rev_row["revoked_at"] is not None:
                    raise ContractError("authentication_required", 401)
                if rev_row["expires_at"] <= now:
                    raise ContractError("authority_expired", 403)
                guard = self.store.one("guard_get", (rev_row["principal_id"],))
                if guard is None or guard["status"] != "active" or guard["epoch"] != rev_row["epoch"]:
                    raise ContractError("authority_revoked", 403)

                mtls_ok = self._mtls_verifier(request) is True
                principal = Principal(
                    UUID(rev_row["principal_id"]),
                    Kind.REVIEWER,
                    rev_row["epoch"],
                    rev_row["expires_at"],
                    mtls_verified=mtls_ok,
                    audience="aiac-v2-reviewer",
                )
                return AuthContext(principal, None)

            raise ContractError("authentication_required", 401)

        raise ContractError("authentication_required", 401)
