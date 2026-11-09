"""Test suite for AI AD Coin v2 Real-Value Issuance, Proof-of-Reserves, and Blockchain Operations."""

from uuid import uuid4

from fastapi import FastAPI
import pytest
from starlette.testclient import TestClient

from agent_market.ad_coin.v2.access import Access, HUMAN_CAPABILITIES
from agent_market.ad_coin.v2.contracts import ContractError
from agent_market.ad_coin.v2.identity import Kind
from agent_market.ad_coin.v2.ledger import ModelLedger
from agent_market.ad_coin.v2.live_auth import PersistentCredentialResolver
from agent_market.ad_coin.v2.real_value import RealValueGateway
from agent_market.ad_coin.v2.real_value_http import router_for as real_value_router
from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_persistence import store  # noqa: F401


@pytest.fixture(autouse=True)
def _real_value_switch_on(monkeypatch):
    # These tests exercise the real-value code paths, which stay off unless switched on explicitly.
    monkeypatch.setenv("AD_COIN_REAL_VALUE_ENABLED", "1")



def uid():
    return str(uuid4())


def test_real_value_deposit_and_full_reserve_lifecycle(store):  # noqa: F811
    store.migrate_model()
    ledger = ModelLedger(store)
    access = Access(store)
    gateway = RealValueGateway(store, ledger, access)

    clearing_acc = ledger.create_account(uid(), "external_clearing")
    user_owner = uid()
    user_wallet_id = access.provision_wallet(user_owner)

    # 1. Inbound fiat deposit
    deposit_id = uid()
    ext_ref = "stripe_ch_" + uid()
    dep = gateway.record_fiat_deposit(
        deposit_id,
        user_wallet_id,
        user_owner,
        50_000_000,  # 50.00 USDC
        "USDC",
        ext_ref,
    )
    assert dep["status"] == "pending"
    assert dep["amount_atoms"] == 50_000_000

    # Duplicate external ref rejected
    with pytest.raises(ContractError, match="duplicate_external_tx_ref"):
        gateway.record_fiat_deposit(
            uid(),
            user_wallet_id,
            user_owner,
            10_000_000,
            "USDC",
            ext_ref,
        )

    # 2. Confirm deposit webhook
    confirmed_dep = gateway.confirm_fiat_deposit(deposit_id, clearing_acc)
    assert confirmed_dep["status"] == "confirmed"

    # Wallet balance credited
    wallet_row = store.one("wallet_get", (user_wallet_id,))
    avail_acc = store.one("account_get", (wallet_row["available_account"],))
    assert avail_acc["balance_atoms"] == 50_000_000

    # Clearing account debited
    clearing_row = store.one("account_get", (clearing_acc,))
    assert clearing_row["balance_atoms"] == -50_000_000

    # 3. Custodian reserve attestation & Proof-of-Reserves check
    chk_id = uid()
    gateway.record_custody_reserve_checkpoint(
        chk_id,
        "Anchor Custody Trust",
        "0x1111222233334444555566667777888899990000",
        50_000_000,
        "sha256-merkle-attestation-01",
        1_800_000_000.0,
    )
    por_report = gateway.reconcile_proof_of_reserves()
    assert por_report["clean"] is True
    assert por_report["status"] == "solvent_full_reserve"
    assert por_report["coverage_bps"] >= 10000

    # 4. On-chain withdrawal request
    withdrawal_id = uid()
    dest_address = "0x742d35cc6634c0532925a3b844bc454e4438f44e"
    withdrawal = gateway.request_onchain_withdrawal(
        withdrawal_id,
        user_wallet_id,
        user_owner,
        "base",
        8453,
        dest_address,
        20_000_000,  # 20.00 USDC
        1_000_000,   # 1.00 USDC gas fee
    )
    assert withdrawal["status"] == "pending"
    assert withdrawal["amount_atoms"] == 20_000_000

    # Available balance reduced by amount + fee (21 USDC), held in locked account
    avail_acc_after = store.one("account_get", (wallet_row["available_account"],))
    locked_acc_after = store.one("account_get", (wallet_row["locked_account"],))
    assert avail_acc_after["balance_atoms"] == 29_000_000
    assert locked_acc_after["balance_atoms"] == 21_000_000

    # 5. Confirm on-chain broadcast
    tx_hash = "0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
    confirmed_withdrawal = gateway.confirm_onchain_withdrawal(withdrawal_id, tx_hash)
    assert confirmed_withdrawal["status"] == "confirmed"
    assert confirmed_withdrawal["tx_hash"] == tx_hash

    # 6. Cancellation & refund test
    refund_withdraw_id = uid()
    gateway.request_onchain_withdrawal(
        refund_withdraw_id,
        user_wallet_id,
        user_owner,
        "ethereum",
        1,
        dest_address,
        10_000_000,
        500_000,
    )
    # Cancelled before broadcast
    cancelled = gateway.cancel_onchain_withdrawal(refund_withdraw_id)
    assert cancelled["status"] == "cancelled"

    # Wallet available refunded back to 29_000_000
    avail_acc_refunded = store.one("account_get", (wallet_row["available_account"],))
    assert avail_acc_refunded["balance_atoms"] == 29_000_000


def test_real_value_http_api(store):  # noqa: F811
    store.migrate_model()
    ledger = ModelLedger(store)
    access = Access(store)
    resolver = PersistentCredentialResolver(store)
    clearing_acc = ledger.create_account(uid(), "external_clearing")
    gateway = RealValueGateway(store, ledger, access)

    user_owner = uid()
    user_principal = uid()
    access.provision_principal(
        user_principal, Kind.HUMAN, owner_id=user_owner, capabilities=HUMAN_CAPABILITIES
    )
    wallet_id = access.provision_wallet(user_owner)

    session_token = "sess-" + uid()
    csrf_token = "csrf-" + uid()
    resolver.register_human_session(
        session_token, csrf_token, principal_id=user_principal, owner_id=user_owner
    )

    app = FastAPI()
    app.include_router(real_value_router(gateway, clearing_acc, resolve_auth=resolver))
    client = TestClient(app)
    cookies = {"aiac_session": session_token}
    headers = {"X-CSRF-Token": csrf_token}

    # 1. Deposit creation (webhook)
    dep_payload = {
        "wallet_id": wallet_id,
        "payer_owner_id": user_owner,
        "amount_atoms": 100_000_000,
        "currency": "USD",
        "external_tx_ref": "ach_" + uid(),
    }
    dep_resp = client.post("/api/ad-coin/v2/real/deposits", json=dep_payload)
    assert dep_resp.status_code == 201
    dep_data = dep_resp.json()["deposit"]
    dep_id = dep_data["id"]

    # 2. Deposit confirmation
    confirm_resp = client.post(
        f"/api/ad-coin/v2/real/deposits/{dep_id}/confirm",
        cookies=cookies,
        headers=headers,
    )
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["deposit"]["status"] == "confirmed"

    # 3. Reserve checkpoint & Proof-of-Reserves
    res_payload = {
        "custodian_name": "Circle Financial",
        "vault_address": "0x1234567890123456789012345678901234567890",
        "reported_atoms": 100_000_000,
        "attestation_hash": "attest-hash-circle-01",
        "reported_at": 1_800_000_000.0,
    }
    chk_resp = client.post(
        "/api/ad-coin/v2/real/reserves/checkpoints",
        json=res_payload,
        cookies=cookies,
        headers=headers,
    )
    assert chk_resp.status_code == 201

    proof_resp = client.get("/api/ad-coin/v2/real/reserves/proof")
    assert proof_resp.status_code == 200
    assert proof_resp.json()["status"] == "solvent_full_reserve"

    # 4. Withdrawal request
    w_payload = {
        "wallet_id": wallet_id,
        "destination_chain": "base",
        "chain_id": 8453,
        "destination_address": "0x742d35cc6634c0532925a3b844bc454e4438f44e",
        "amount_atoms": 40_000_000,
        "fee_atoms": 2_000_000,
    }
    w_resp = client.post(
        "/api/ad-coin/v2/real/withdrawals",
        json=w_payload,
        cookies=cookies,
        headers=headers,
    )
    assert w_resp.status_code == 201
    w_id = w_resp.json()["withdrawal"]["id"]

    # 5. Confirm withdrawal
    conf_w_resp = client.post(
        f"/api/ad-coin/v2/real/withdrawals/{w_id}/confirm",
        json={"tx_hash": "0x" + "a" * 64},
        cookies=cookies,
        headers=headers,
    )
    assert conf_w_resp.status_code == 200
    assert conf_w_resp.json()["withdrawal"]["status"] == "confirmed"
