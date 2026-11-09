"""Tests for Stripe and Circle webhook verification and fiat deposit handler."""

import hashlib
import hmac
import json
import time
from uuid import uuid4

from fastapi import FastAPI
import pytest
from starlette.testclient import TestClient

from agent_market.ad_coin.v2.access import Access
from agent_market.ad_coin.v2.contracts import ContractError
from agent_market.ad_coin.v2.fiat_providers import (
    CircleWebhookVerifier,
    FiatWebhookHandler,
    StripeWebhookVerifier,
)
from agent_market.ad_coin.v2.ledger import ModelLedger
from agent_market.ad_coin.v2.real_value import RealValueGateway
from agent_market.ad_coin.v2.real_value_http import router_for as real_value_router
from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_persistence import store  # noqa: F401


def uid():
    return str(uuid4())


def test_stripe_and_circle_webhook_verification(store):  # noqa: F811
    store.migrate_model()
    ledger = ModelLedger(store)
    access = Access(store)
    clearing_acc = ledger.create_account(uid(), "external_clearing")
    gateway = RealValueGateway(store, ledger, access)

    user_owner = uid()
    wallet_id = access.provision_wallet(user_owner)

    stripe_secret = "whsec_test_secret_12345"
    circle_secret = "circle_test_secret_67890"

    stripe_verifier = StripeWebhookVerifier(stripe_secret, tolerance_seconds=300)
    circle_verifier = CircleWebhookVerifier(circle_secret)
    handler = FiatWebhookHandler(
        gateway,
        clearing_acc,
        stripe_verifier=stripe_verifier,
        circle_verifier=circle_verifier,
    )

    # 1. Stripe webhook verification
    stripe_event = {
        "id": "evt_" + uid(),
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": "pi_" + uid(),
                "amount": 2500,  # $25.00 -> 25,000,000 atoms
                "currency": "usd",
                "metadata": {
                    "wallet_id": wallet_id,
                    "owner_id": user_owner,
                },
            }
        },
    }
    raw_payload = json.dumps(stripe_event).encode("utf-8")
    now_ts = int(time.time())
    sig_payload = f"{now_ts}.".encode("utf-8") + raw_payload
    v1_sig = hmac.new(stripe_secret.encode("utf-8"), sig_payload, hashlib.sha256).hexdigest()
    stripe_header = f"t={now_ts},v1={v1_sig}"

    res = handler.handle_stripe_event(raw_payload, stripe_header)
    assert res["status"] == "confirmed"
    assert res["amount_atoms"] == 25_000_000

    # Wallet credited
    w_row = store.one("wallet_get", (wallet_id,))
    avail = store.one("account_get", (w_row["available_account"],))
    assert avail["balance_atoms"] == 25_000_000

    # Outdated timestamp rejected
    old_ts = now_ts - 500
    old_sig = hmac.new(stripe_secret.encode("utf-8"), f"{old_ts}.".encode() + raw_payload, hashlib.sha256).hexdigest()
    with pytest.raises(ContractError, match="stripe_timestamp_out_of_tolerance"):
        handler.handle_stripe_event(raw_payload, f"t={old_ts},v1={old_sig}")

    # 2. Circle webhook verification
    circle_event = {
        "notificationType": "settlements",
        "settlement": {
            "id": "stl_" + uid(),
            "amount": {"amount": "15.500000", "currency": "USD"},
            "metadata": {
                "wallet_id": wallet_id,
                "owner_id": user_owner,
            },
        },
    }
    raw_circle = json.dumps(circle_event).encode("utf-8")
    circle_sig = hmac.new(circle_secret.encode("utf-8"), raw_circle, hashlib.sha256).hexdigest()

    circle_res = handler.handle_circle_event(raw_circle, circle_sig)
    assert circle_res["status"] == "confirmed"
    assert circle_res["amount_atoms"] == 15_500_000

    # Wallet updated (25.00 + 15.50 = 40.50 USDC)
    avail_after = store.one("account_get", (w_row["available_account"],))
    assert avail_after["balance_atoms"] == 40_500_000


def test_fiat_webhooks_http_endpoint(store):  # noqa: F811
    store.migrate_model()
    ledger = ModelLedger(store)
    access = Access(store)
    clearing_acc = ledger.create_account(uid(), "external_clearing")
    gateway = RealValueGateway(store, ledger, access)

    user_owner = uid()
    wallet_id = access.provision_wallet(user_owner)

    stripe_secret = "whsec_stripe_test"
    stripe_verifier = StripeWebhookVerifier(stripe_secret)
    handler = FiatWebhookHandler(
        gateway, clearing_acc, stripe_verifier=stripe_verifier
    )

    app = FastAPI()
    app.state.fiat_handler = handler
    app.include_router(real_value_router(gateway, clearing_acc))
    client = TestClient(app)

    event = {
        "id": "evt_" + uid(),
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": "pi_" + uid(),
                "amount": 5000,  # $50.00
                "currency": "usd",
                "metadata": {"wallet_id": wallet_id, "owner_id": user_owner},
            }
        },
    }
    raw = json.dumps(event).encode("utf-8")
    now_ts = int(time.time())
    sig = hmac.new(stripe_secret.encode("utf-8"), f"{now_ts}.".encode() + raw, hashlib.sha256).hexdigest()

    resp = client.post(
        "/api/ad-coin/v2/real/webhooks/stripe",
        content=raw,
        headers={"stripe-signature": f"t={now_ts},v1={sig}"},
    )
    assert resp.status_code == 200
    assert resp.json()["result"]["status"] == "confirmed"
