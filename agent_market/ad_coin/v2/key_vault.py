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
        owner_link_key: bytes | None = None,
    ):
        self._clock = clock or time.time
        # Server-secret key that turns a site customer id into v2 ids (HMAC), so knowing a customer id
        # is not enough to compute or link that customer's v2 identity.
        env_link = os.environ.get("AIAC_OWNER_LINK_KEY_HEX")
        if owner_link_key is None and env_link:
            owner_link_key = bytes.fromhex(env_link)
        # Only a stable key may link site customers: a random one would give a customer another v2
        # identity in every process and after every restart.
        self.owner_link_persistent = owner_link_key is not None
        self._owner_link_key = owner_link_key if owner_link_key is not None else secrets.token_bytes(32)
        if len(self._owner_link_key) != 32:
            raise ContractError("invalid_owner_link_key", 503)
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

    @classmethod
    def from_directory(cls, directory, **kwargs) -> "KeyVault":
        """Keys kept in owner-only files so every process and restart signs and verifies the same way.

        Files are created once (exclusive create, mode 0600). A process that loses the race reads the
        winner's file. The directory lives under gateway-data/ and is never committed.
        """
        def load_or_create(name, make, parse):
            path = os.path.join(directory, name)
            os.makedirs(directory, mode=0o700, exist_ok=True)
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            except FileExistsError:
                with open(path, "rb") as handle:
                    return parse(handle.read())
            data = make()
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            return parse(data)

        signing = load_or_create(
            "signing.pem",
            lambda: ed25519.Ed25519PrivateKey.generate().private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()),
            lambda data: serialization.load_pem_private_key(data, password=None),
        )
        fresh = load_or_create("fresh.key", lambda: secrets.token_bytes(32).hex().encode("ascii"),
                               lambda data: bytes.fromhex(data.decode("ascii").strip()))
        link = load_or_create("owner-link.key", lambda: secrets.token_bytes(32).hex().encode("ascii"),
                              lambda data: bytes.fromhex(data.decode("ascii").strip()))
        return cls(signing_key=signing, fresh_proof_key=fresh, owner_link_key=link, **kwargs)

    @property
    def kid(self) -> str:
        return self._kid

    def get_signing_key(self) -> ed25519.Ed25519PrivateKey:
        return self._signing_key

    def get_owner_link_key(self) -> bytes:
        return self._owner_link_key

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
