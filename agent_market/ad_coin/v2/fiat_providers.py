"""External fiat payment gateway and custody webhook signature verification adapters (Stripe / Circle)."""

import hashlib
import hmac
import time
from typing import Any

from .contracts import ContractError
from .real_value import RealValueGateway, require_real_value


class StripeWebhookVerifier:
    """Verifies Stripe webhook signatures (v1=hmac_sha256(secret, t.payload))."""

    def __init__(self, endpoint_secret: str, tolerance_seconds: int = 300):
        self.endpoint_secret = endpoint_secret
        self.tolerance_seconds = tolerance_seconds

    def verify_and_parse(self, payload: bytes, signature_header: str) -> dict[str, Any]:
        if not signature_header:
            raise ContractError("missing_stripe_signature", 401)

        items = dict(
            part.strip().split("=", 1)
            for part in signature_header.split(",")
            if "=" in part
        )
        timestamp = items.get("t")
        v1_sig = items.get("v1")

        if not timestamp or not v1_sig:
            raise ContractError("invalid_stripe_signature_header", 400)

        # Check timestamp tolerance
        try:
            t = int(timestamp)
        except ValueError:
            raise ContractError("invalid_stripe_timestamp", 400) from None

        if abs(time.time() - t) > self.tolerance_seconds:
            raise ContractError("stripe_timestamp_out_of_tolerance", 400)

        # Compute expected signature
        signed_payload = f"{t}.".encode("utf-8") + payload
        expected_sig = hmac.new(
            self.endpoint_secret.encode("utf-8"),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected_sig, v1_sig):
            raise ContractError("stripe_signature_verification_failed", 401)

        import json

        return json.loads(payload.decode("utf-8"))


class CircleWebhookVerifier:
    """Verifies Circle payment and reserve attestation notification webhooks."""

    def __init__(self, shared_secret: str):
        self.shared_secret = shared_secret

    def verify_and_parse(self, payload: bytes, signature_header: str) -> dict[str, Any]:
        if not signature_header:
            raise ContractError("missing_circle_signature", 401)

        expected = hmac.new(
            self.shared_secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected, signature_header):
            raise ContractError("circle_signature_verification_failed", 401)

        import json

        return json.loads(payload.decode("utf-8"))


class FiatWebhookHandler:
    """Dispatches verified payment webhooks to RealValueGateway."""

    def __init__(
        self,
        gateway: RealValueGateway,
        clearing_account_id: str,
        stripe_verifier: StripeWebhookVerifier | None = None,
        circle_verifier: CircleWebhookVerifier | None = None,
    ):
        self.gateway = gateway
        self.clearing_account_id = clearing_account_id
        self.stripe_verifier = stripe_verifier
        self.circle_verifier = circle_verifier

    def handle_stripe_event(self, raw_body: bytes, signature_header: str) -> dict[str, Any]:
        require_real_value()
        if self.stripe_verifier is None:
            raise ContractError("stripe_verifier_not_configured", 503)

        event = self.stripe_verifier.verify_and_parse(raw_body, signature_header)
        event_type = event.get("type", "")

        if event_type == "payment_intent.succeeded":
            data = event.get("data", {}).get("object", {})
            metadata = data.get("metadata", {})
            wallet_id = metadata.get("wallet_id")
            owner_id = metadata.get("owner_id")
            amount_cents = int(data.get("amount", 0))
            # 1 cent USD = 10,000 atoms (at 6 decimals, 1 USD = 1,000,000 atoms)
            amount_atoms = amount_cents * 10_000
            currency = data.get("currency", "usd").upper()
            ext_ref = data.get("id")

            if not wallet_id or not owner_id or amount_atoms <= 0:
                raise ContractError("invalid_stripe_payment_metadata", 422)

            import uuid

            dep_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"stripe:{ext_ref}"))
            dep = self.gateway.record_fiat_deposit(
                deposit_id=dep_uuid,
                wallet_id=wallet_id,
                payer_owner_id=owner_id,
                amount_atoms=amount_atoms,
                currency=currency,
                external_tx_ref=ext_ref,
            )
            return self.gateway.confirm_fiat_deposit(dep["id"], self.clearing_account_id)

        return {"handled": False, "type": event_type}

    def handle_circle_event(self, raw_body: bytes, signature_header: str) -> dict[str, Any]:
        require_real_value()
        if self.circle_verifier is None:
            raise ContractError("circle_verifier_not_configured", 503)

        event = self.circle_verifier.verify_and_parse(raw_body, signature_header)
        notification_type = event.get("notificationType", "")

        if notification_type == "settlements":
            data = event.get("settlement", {})
            wallet_id = data.get("metadata", {}).get("wallet_id")
            owner_id = data.get("metadata", {}).get("owner_id")
            amount_units = data.get("amount", {}).get("amount", "0")
            currency = data.get("amount", {}).get("currency", "USD")
            ext_ref = data.get("id")

            # Parse decimal amount to atoms (6 decimals)
            parts = str(amount_units).split(".")
            whole = int(parts[0])
            fraction = parts[1] if len(parts) > 1 else ""
            fraction = fraction.ljust(6, "0")[:6]
            amount_atoms = whole * 1_000_000 + int(fraction)

            if not wallet_id or not owner_id or amount_atoms <= 0:
                raise ContractError("invalid_circle_settlement_metadata", 422)

            import uuid

            dep_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"circle:{ext_ref}"))
            dep = self.gateway.record_fiat_deposit(
                deposit_id=dep_uuid,
                wallet_id=wallet_id,
                payer_owner_id=owner_id,
                amount_atoms=amount_atoms,
                currency=currency,
                external_tx_ref=ext_ref,
            )
            return self.gateway.confirm_fiat_deposit(dep["id"], self.clearing_account_id)

        return {"handled": False, "type": notification_type}
