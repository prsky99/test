"""Ed25519 JWS receipt signing, verification, and public key registry."""

import base64
from datetime import datetime, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
)

from .budgets import millis
from .contracts import ContractError, MODEL_ASSET, canonical_bytes
from .contracts import atoms, decode_body
from .ledger import business_key, identifier


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    if (
        type(text) is not str
        or not text
        or any(
            c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
            for c in text
        )
    ):
        raise ValueError("invalid_base64url")
    padding = "=" * ((4 - len(text) % 4) % 4)
    decoded = base64.b64decode(
        (text + padding).encode("ascii"), altchars=b"-_", validate=True
    )
    if _b64url_encode(decoded) != text:
        raise ValueError("noncanonical_base64url")
    return decoded


def _date_text(value_ms: int) -> str:
    return (
        datetime.fromtimestamp(value_ms // 1000, timezone.utc)
        .replace(microsecond=value_ms % 1000 * 1000)
        .isoformat()
        .replace("+00:00", "Z")
    )


class ReceiptSigner:
    """Manages Ed25519 receipt keys and produces verified JWS compact tokens."""

    def __init__(self, store, private_keys=None):
        self.store = store
        self._keys: dict[str, Ed25519PrivateKey] = {}
        for kid, secret in (private_keys or {}).items():
            self.register_private_key(kid, secret)

    def register_private_key(self, kid: str, secret: bytes | Ed25519PrivateKey):
        kid = business_key(kid)
        if isinstance(secret, Ed25519PrivateKey):
            key = secret
        elif type(secret) is bytes and len(secret) == 32:
            key = Ed25519PrivateKey.from_private_bytes(secret)
        else:
            raise ContractError("invalid_receipt_signing_key", 503)
        self._keys[kid] = key
        return key

    def publish_key(
        self,
        kid: str,
        *,
        not_before_ms: int,
        verify_until_ms: int,
        status: str = "active",
        public_x: str | None = None,
    ):
        kid = business_key(kid)
        not_before_ms, verify_until_ms = (
            millis(not_before_ms),
            millis(verify_until_ms),
        )
        if status not in ("active", "verify_only", "revoked") or (
            verify_until_ms <= not_before_ms
        ):
            raise ContractError("invalid_receipt_key_metadata")
        if public_x is None:
            if kid not in self._keys:
                raise ContractError("receipt_key_unavailable", 503)
            raw_pub = (
                self._keys[kid]
                .public_key()
                .public_bytes(Encoding.Raw, PublicFormat.Raw)
            )
            public_x = _b64url_encode(raw_pub)
        else:
            if (
                type(public_x) is not str
                or len(public_x) != 43
                or len(_b64url_decode(public_x)) != 32
            ):
                raise ContractError("invalid_receipt_key_metadata")
        with self.store.atomic():
            self.store.execute(
                "receipt_key_upsert",
                (kid, status, not_before_ms, verify_until_ms, public_x),
            )
        return self.key_view(self.store.one("receipt_key_get", (kid,)))

    def set_key_status(self, kid: str, status: str):
        kid = business_key(kid)
        if status not in ("active", "verify_only", "revoked"):
            raise ContractError("invalid_receipt_key_metadata")
        with self.store.atomic():
            if self.store.execute("receipt_key_status", (status, kid)).rowcount != 1:
                raise ContractError("unknown_resource", 404)

    def key_view(self, row: dict) -> dict:
        return {
            "kid": row["kid"],
            "status": row["status"],
            "not_before": _date_text(row["not_before_ms"]),
            "verify_until": _date_text(row["verify_until_ms"]),
            "jwk": {
                "kty": "OKP",
                "crv": "Ed25519",
                "alg": "EdDSA",
                "use": "sig",
                "x": row["public_x"],
            },
        }

    def key_set_view(self) -> dict:
        rows = self.store.all("receipt_keys_list")
        return {
            "issuer": "ai-ad-coin/model",
            "keys": [self.key_view(row) for row in rows],
        }

    def claims_for(self, row: dict) -> dict:
        return {
            "receipt_id": row["id"],
            "offer_id": row["offer_id"],
            "stage_key": "P1",
            "asset_id": row["asset_id"],
            "user_reward_atoms": str(row["user_reward_atoms"]),
            "quote_hash": row["quote_hash"],
            "policy_version": "v6.1",
            "contract_version": "v6.2",
            "iss": "ai-ad-coin/model",
            "aud": "aiac-reward-receipt",
            "iat": int(row["issued_ms"]) // 1000,
        }

    def verify_jws(self, jws: str, *, expected_claims: dict | None = None) -> dict:
        if type(jws) is not str or len(jws) > 32768 or jws.count(".") != 2:
            raise ContractError("invalid_receipt_signature", 409)
        header_b64, payload_b64, sig_b64 = jws.split(".")
        try:
            header_bytes, claims_bytes = (
                _b64url_decode(header_b64),
                _b64url_decode(payload_b64),
            )
            header = decode_body(header_bytes)
            claims = decode_body(claims_bytes)
            signature = _b64url_decode(sig_b64)
        except Exception:
            raise ContractError("invalid_receipt_signature", 409) from None
        if (
            type(header) is not dict
            or set(header) != {"typ", "alg", "kid"}
            or header.get("typ") != "aiac-receipt+jwt"
            or header.get("alg") != "EdDSA"
            or type(header.get("kid")) is not str
        ):
            raise ContractError("invalid_receipt_signature", 409)
        required = {
            "receipt_id",
            "offer_id",
            "stage_key",
            "asset_id",
            "user_reward_atoms",
            "quote_hash",
            "policy_version",
            "contract_version",
            "iss",
            "aud",
            "iat",
        }
        if (
            set(claims) != required
            or claims.get("iss") != "ai-ad-coin/model"
            or claims.get("aud") != "aiac-reward-receipt"
            or claims.get("stage_key") != "P1"
            or claims.get("asset_id") != MODEL_ASSET
            or claims.get("policy_version") != "v6.1"
            or claims.get("contract_version") != "v6.2"
            or type(claims.get("iat")) is not int
            or claims["iat"] < 0
            or canonical_bytes(header) != header_bytes
            or canonical_bytes(claims) != claims_bytes
            or type(claims.get("quote_hash")) is not str
            or len(claims["quote_hash"]) != 64
            or any(c not in "0123456789abcdef" for c in claims["quote_hash"])
        ):
            raise ContractError("receipt_claims_mismatch", 409)
        try:
            identifier(claims["receipt_id"])
            identifier(claims["offer_id"])
            atoms(claims["user_reward_atoms"], positive=True)
        except ContractError:
            raise ContractError("receipt_claims_mismatch", 409) from None
        key_row = self.store.one("receipt_key_get", (header["kid"],))
        if not key_row or key_row["status"] == "revoked":
            raise ContractError("receipt_key_revoked_or_unknown", 409)
        if not (
            claims["iat"] * 1000 < key_row["verify_until_ms"]
            and (claims["iat"] + 1) * 1000 > key_row["not_before_ms"]
        ):
            raise ContractError("receipt_key_time_mismatch", 409)
        public_key = Ed25519PublicKey.from_public_bytes(
            _b64url_decode(key_row["public_x"])
        )
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        try:
            public_key.verify(signature, signing_input)
        except InvalidSignature:
            raise ContractError("invalid_receipt_signature", 409) from None
        if expected_claims is not None and claims != expected_claims:
            raise ContractError("receipt_claims_mismatch", 409)
        return {"header": header, "claims": claims}

    def sign_receipt(self, receipt_id: str, *, kid: str | None = None, now_ms: int):
        receipt_id = identifier(receipt_id)
        now_ms = millis(now_ms)
        with self.store.atomic():
            self.store.lock("2:receipt:" + receipt_id)
            row = self.store.one("receipt_locked", (receipt_id,))
            if row is None:
                raise ContractError("unknown_resource", 404)
            if row["signature_state"] == "signed":
                return self.receipt_view(row)
            journal = self.store.one("journal_by_id", (row["journal_id"],))
            if (
                not journal
                or journal["state"] != "sealed"
                or journal["asset_id"] != MODEL_ASSET
            ):
                raise ContractError("receipt_journal_unsealed", 409)
            if kid is None:
                active_rows = [
                    r
                    for r in self.store.all("receipt_keys_list")
                    if r["status"] == "active"
                    and r["not_before_ms"] <= now_ms < r["verify_until_ms"]
                    and r["kid"] in self._keys
                ]
                if not active_rows:
                    raise ContractError("receipt_key_unavailable", 503)
                key_row = active_rows[0]
            else:
                key_row = self.store.one("receipt_key_get", (business_key(kid),))
                if (
                    not key_row
                    or key_row["status"] != "active"
                    or not (
                        key_row["not_before_ms"] <= now_ms < key_row["verify_until_ms"]
                    )
                    or key_row["kid"] not in self._keys
                ):
                    raise ContractError("receipt_key_unavailable", 503)
            selected_kid = key_row["kid"]
            header = {
                "typ": "aiac-receipt+jwt",
                "alg": "EdDSA",
                "kid": selected_kid,
            }
            claims = self.claims_for(row)
            header_b64 = _b64url_encode(canonical_bytes(header))
            payload_b64 = _b64url_encode(canonical_bytes(claims))
            signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
            signature = self._keys[selected_kid].sign(signing_input)
            jws = f"{header_b64}.{payload_b64}.{_b64url_encode(signature)}"
            self.verify_jws(jws, expected_claims=claims)
            if (
                self.store.execute(
                    "receipt_sign", (selected_kid, jws, receipt_id)
                ).rowcount
                != 1
            ):
                raise ContractError("version_conflict", 409)
            return self.receipt_view(self.store.one("receipt_get", (receipt_id,)))

    def receipt_view(self, row: dict) -> dict:
        return {
            "id": row["id"],
            "kind": "p1_award",
            "offer_id": row["offer_id"],
            "stage_key": "P1",
            "asset_id": row["asset_id"],
            "user_reward_atoms": str(row["user_reward_atoms"]),
            "quote_hash": row["quote_hash"],
            "issued_at": _date_text(row["issued_ms"]),
            "signature_state": row["signature_state"],
            "key_id": row["key_id"],
            "jws": row["jws"],
            "issuer": "ai-ad-coin/model",
            "audience": "aiac-reward-receipt",
            "policy_version": "v6.1",
            "contract_version": "v6.2",
        }
