"""Cryptographic key vault abstraction for Ed25519 signing and Fresh challenge proof keys."""

import base64
import os
import secrets
import time
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from .contracts import ContractError


class KeyVault:
    """Manages lifecycle, zero-downtime rotation, and JWK publication of signing and challenge keys."""

    def __init__(
        self,
        *,
        signing_key: ed25519.Ed25519PrivateKey | None = None,
        fresh_proof_key: bytes | None = None,
        fresh_fallback_keys: tuple[bytes, ...] = (),
        kid: str | None = None,
        clock=None,
    ):
        self._clock = clock or time.time
        self._kid = kid or "k1"
        self._created_at = self._clock()

        # 1. Signing Key (Ed25519)
        env_signing = os.environ.get("AIAC_ED25519_PRIVATE_KEY_PEM")
        if signing_key is not None:
            self._signing_key = signing_key
        elif env_signing:
            self._signing_key = serialization.load_pem_private_key(
                env_signing.encode("ascii"), password=None
            )
        else:
            self._signing_key = ed25519.Ed25519PrivateKey.generate()

        # 2. Fresh Challenge Key (HMAC-SHA256 32 bytes)
        env_fresh = os.environ.get("AIAC_FRESH_PROOF_KEY_HEX")
        if fresh_proof_key is not None:
            self._proof_key = fresh_proof_key
        elif env_fresh:
            self._proof_key = bytes.fromhex(env_fresh)
        else:
            self._proof_key = secrets.token_bytes(32)

        if len(self._proof_key) != 32:
            raise ContractError("invalid_fresh_key", 503)

        self._fallback_keys: list[bytes] = list(fresh_fallback_keys)
        env_fallbacks = os.environ.get("AIAC_FRESH_FALLBACK_KEYS_HEX")
        if env_fallbacks:
            for item in env_fallbacks.split(","):
                item = item.strip()
                if item:
                    parsed = bytes.fromhex(item)
                    if len(parsed) == 32 and parsed not in self._fallback_keys:
                        self._fallback_keys.append(parsed)

    @property
    def kid(self) -> str:
        return self._kid

    def get_signing_key(self) -> ed25519.Ed25519PrivateKey:
        return self._signing_key

    def get_fresh_keys(self) -> tuple[bytes, tuple[bytes, ...]]:
        return self._proof_key, tuple(self._fallback_keys)

    def rotate_fresh_key(self, new_key: bytes | None = None) -> bytes:
        """Rotate the active fresh challenge key, moving the current key into fallbacks."""
        if new_key is None:
            new_key = secrets.token_bytes(32)
        if len(new_key) != 32:
            raise ContractError("invalid_fresh_key", 503)
        old_key = self._proof_key
        if old_key not in self._fallback_keys:
            self._fallback_keys.insert(0, old_key)
        # Keep at most 3 fallback keys
        self._fallback_keys = self._fallback_keys[:3]
        self._proof_key = new_key
        return new_key

    def rotate_signing_key(self, new_signing_key: ed25519.Ed25519PrivateKey | None = None, *, new_kid: str | None = None):
        """Rotate the Ed25519 signing key with updated key ID."""
        self._signing_key = new_signing_key or ed25519.Ed25519PrivateKey.generate()
        self._kid = new_kid or f"k{int(self._clock())}"
        self._created_at = self._clock()

    def retire_fallback_keys(self):
        """Clear expired fallback challenge keys."""
        self._fallback_keys.clear()

    def get_jwk(self) -> dict[str, str]:
        """Export RFC 7517 compliant JWK for the current Ed25519 public key."""
        public_bytes = self._signing_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        x_b64 = base64.urlsafe_b64encode(public_bytes).rstrip(b"=").decode("ascii")
        return {
            "kty": "OKP",
            "crv": "Ed25519",
            "x": x_b64,
            "kid": self._kid,
            "use": "sig",
            "alg": "EdDSA",
        }

    def get_status(self) -> dict[str, Any]:
        """Return cryptographic key vault health status."""
        return {
            "kid": self._kid,
            "algorithm": "Ed25519 / HMAC-SHA256",
            "key_age_seconds": round(self._clock() - self._created_at, 2),
            "fallback_keys_count": len(self._fallback_keys),
            "vault_healthy": True,
        }
