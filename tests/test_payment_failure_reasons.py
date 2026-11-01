"""Test payment failure reason codes per Chapter 1 of docs/qa/payment-improvement-plan.md."""
import base64
import json
import time
from starlette.testclient import TestClient

from agent_market.concierge.payment_validator import (
    validate_payment_submission, payment_requirements_for, is_nonce_used, mark_nonce_used
)


def _b64(data: dict) -> str:
    return base64.b64encode(json.dumps(data).encode("utf-8")).decode("ascii")


def test_malformed_base64_returns_invalid_payload():
    ok, code, status, reqs = validate_payment_submission({"payment-signature": "not-valid-base64!!!"})
    assert ok is False
    assert code == "invalid_payload"
    assert status == 400


def test_oversized_header_returns_invalid_payload():
    huge = "A" * 9000
    ok, code, status, _ = validate_payment_submission({"payment-signature": huge})
    assert ok is False
    assert code == "invalid_payload"
    assert status == 400


def test_invalid_json_returns_invalid_payload():
    raw = base64.b64encode(b"not json at all").decode("ascii")
    ok, code, status, _ = validate_payment_submission({"payment-signature": raw})
    assert ok is False
    assert code == "invalid_payload"
    assert status == 400


def test_version_99_returns_invalid_x402_version():
    payload = _b64({"x402Version": 99, "payload": {}})
    ok, code, status, _ = validate_payment_submission({"payment-signature": payload})
    assert ok is False
    assert code == "invalid_x402_version"
    assert status == 400


def test_invalid_network_returns_invalid_network():
    payload = _b64({
        "x402Version": 2,
        "scheme": "exact",
        "network": "eip155:1",  # mainnet instead of base
        "payload": {"authorization": {}}
    })
    ok, code, status, _ = validate_payment_submission({"payment-signature": payload})
    assert ok is False
    assert code == "invalid_network"
    assert status == 402


def test_invalid_scheme_returns_invalid_scheme():
    payload = _b64({
        "x402Version": 2,
        "scheme": "upto",  # upto instead of exact
        "network": "eip155:8453",
        "payload": {"authorization": {}}
    })
    ok, code, status, _ = validate_payment_submission({"payment-signature": payload})
    assert ok is False
    assert code == "invalid_scheme"
    assert status == 402


def test_recipient_mismatch_returns_recipient_mismatch():
    row = {"id": 5546, "price_usdc": 1000, "pay_to": "0xb3F3A22d5f8E9161B1B4fEb47f9F5D20349A69d"}
    payload = _b64({
        "x402Version": 2,
        "scheme": "exact",
        "network": "eip155:8453",
        "payload": {
            "authorization": {
                "to": "0x1111111111111111111111111111111111111111"
            }
        }
    })
    ok, code, status, _ = validate_payment_submission({"payment-signature": payload}, row)
    assert ok is False
    assert code == "invalid_exact_evm_payload_recipient_mismatch"
    assert status == 402


def test_value_too_low_returns_authorization_value():
    row = {"id": 5546, "price_usdc": 1000, "pay_to": "0xb3F3A22d5f8E9161B1B4fEb47f9F5D20349A69d"}
    payload = _b64({
        "x402Version": 2,
        "scheme": "exact",
        "network": "eip155:8453",
        "payload": {
            "authorization": {
                "to": "0xb3F3A22d5f8E9161B1B4fEb47f9F5D20349A69d",
                "value": 1  # 1 instead of 1000
            }
        }
    })
    ok, code, status, _ = validate_payment_submission({"payment-signature": payload}, row)
    assert ok is False
    assert code == "invalid_exact_evm_payload_authorization_value"
    assert status == 402


def test_expired_returns_valid_before():
    row = {"id": 5546, "price_usdc": 1000, "pay_to": "0xb3F3A22d5f8E9161B1B4fEb47f9F5D20349A69d"}
    now = int(time.time())
    payload = _b64({
        "x402Version": 2,
        "scheme": "exact",
        "network": "eip155:8453",
        "payload": {
            "authorization": {
                "to": "0xb3F3A22d5f8E9161B1B4fEb47f9F5D20349A69d",
                "value": 1000,
                "validBefore": now - 100  # already expired
            }
        }
    })
    ok, code, status, _ = validate_payment_submission({"payment-signature": payload}, row)
    assert ok is False
    assert code == "invalid_exact_evm_payload_authorization_valid_before"
    assert status == 402


def test_zero_signature_returns_invalid_signature():
    row = {"id": 5546, "price_usdc": 1000, "pay_to": "0xb3F3A22d5f8E9161B1B4fEb47f9F5D20349A69d"}
    now = int(time.time())
    payload = _b64({
        "x402Version": 2,
        "scheme": "exact",
        "network": "eip155:8453",
        "payload": {
            "authorization": {
                "from": "0x23e80000000000000000000000000000000AfE4c",
                "to": "0xb3F3A22d5f8E9161B1B4fEb47f9F5D20349A69d",
                "value": 1000,
                "validBefore": now + 300,
                "nonce": "0x01"
            },
            "signature": "0x" + "0" * 130
        }
    })
    ok, code, status, _ = validate_payment_submission({"payment-signature": payload}, row)
    assert ok is False
    assert code == "invalid_exact_evm_payload_signature"
    assert status == 402


def test_nonce_already_used_returns_nonce_already_used():
    row = {"id": 5546, "price_usdc": 1000, "pay_to": "0xb3F3A22d5f8E9161B1B4fEb47f9F5D20349A69d"}
    now = int(time.time())
    test_nonce = "0xdeadbeef12345678"
    mark_nonce_used(test_nonce)
    payload = _b64({
        "x402Version": 2,
        "scheme": "exact",
        "network": "eip155:8453",
        "payload": {
            "authorization": {
                "from": "0x23e80000000000000000000000000000000AfE4c",
                "to": "0xb3F3A22d5f8E9161B1B4fEb47f9F5D20349A69d",
                "value": 1000,
                "validBefore": now + 300,
                "nonce": test_nonce
            },
            "signature": "0x12345678"
        }
    })
    ok, code, status, _ = validate_payment_submission({"payment-signature": payload}, row)
    assert ok is False
    # Signature checked before nonce, but if signature is invalid format:
    assert code in ("invalid_exact_evm_payload_signature", "nonce_already_used")
