"""Tests for AI AD Coin v2 agent payments, mandates, escrow holds, settlements, and refunds."""

from uuid import uuid4

from fastapi import FastAPI
import pytest
from starlette.testclient import TestClient

from agent_market.ad_coin.v2.access import HUMAN_CAPABILITIES
from agent_market.ad_coin.v2.agent_payments import AgentPaymentGateway
from agent_market.ad_coin.v2.identity import Kind
from agent_market.ad_coin.v2.key_vault import KeyVault
from agent_market.ad_coin.v2.live_service import (
    DEFAULT_LANGUAGES,
    DEFAULT_REGIONS,
    DEFAULT_TAXONOMY,
    build_live_service,
    create_live_ad_coin_v2_router,
)
from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_persistence import store  # noqa: F401

NOW = 1_800_000_000_000


@pytest.fixture(autouse=True)
def _third_party_payments_need_real_value(monkeypatch):
    # Paying third-party providers is a real-value feature; points mode allows platform benefits only.
    monkeypatch.setenv("AD_COIN_REAL_VALUE_ENABLED", "1")


def uid():
    return str(uuid4())


def test_agent_payments_escrow_settlement_and_refund(store):  # noqa: F811
    store.migrate_model()

    vault = KeyVault()
    commercial, resolver, _ = build_live_service(
        store,
        key_vault=vault,
        taxonomy=DEFAULT_TAXONOMY,
        regions=DEFAULT_REGIONS,
        languages=DEFAULT_LANGUAGES,
        clock_ms=lambda: NOW,
    )
    gateway = AgentPaymentGateway(commercial.store, commercial.ledger, commercial.access)

    user_owner = uid()
    user_principal_id = uid()
    agent_principal_id = uid()
    provider_id = uid()
    provider2_id = uid()
    binding_id = uid()

    commercial.access.provision_principal(
        user_principal_id, Kind.HUMAN, owner_id=user_owner, capabilities=HUMAN_CAPABILITIES
    )
    commercial.access.provision_agent_binding(
        binding_id,
        user_owner,
        agent_principal_id,
        uid(),
        capabilities=HUMAN_CAPABILITIES,
    )

    # Fund user available wallet
    commercial.access.provision_wallet(user_owner)
    user_acc = store.one("account_by_owner_purpose", (user_owner, "user_available"))
    clearing = commercial.ledger.create_account(uid(), "external_clearing")
    commercial.ledger.post(
        "fund-user-coins",
        [(clearing, "-50000"), (user_acc["id"], "50000")],
        kind="model_seed",
    )

    # Initial audit
    audit_before = commercial.ledger.audit()
    assert int(audit_before["beneficial_atoms"]) + int(audit_before["clearing_atoms"]) == 0

    # 1. Create Mandate
    mandate = gateway.create_mandate(
        owner_id=user_owner,
        agent_principal_id=agent_principal_id,
        total_atoms=10000,
        per_task_atoms=2000,
        providers=[provider_id, provider2_id],
    )
    assert mandate["active"] is True
    assert mandate["total_atoms"] == "10000"
    assert mandate["available_atoms"] == "10000"

    # 2. Agent Executes Task -> Escrow Hold
    hold1 = gateway.hold_execution(
        owner_id=user_owner,
        provider_id=provider_id,
        task_ref="task:analyze-dataset",
        price_atoms=1500,
        idem_key=uid(),
        actor="agent",
        agent_principal_id=agent_principal_id,
        mandate_id=mandate["id"],
    )
    assert hold1["status"] == "held"

    # Verify funds moved to locked hold account
    user_acc_cur = store.one("account_by_owner_purpose", (user_owner, "user_available"))
    hold_acc_cur = store.one("account_by_owner_purpose", (user_owner, "user_locked"))
    assert int(user_acc_cur["balance_atoms"]) == 50000 - 1500
    assert int(hold_acc_cur["balance_atoms"]) == 1500

    # Verify mandate spent
    mandate_cur = gateway.get_mandate(mandate["id"])
    assert mandate_cur["spent_atoms"] == "1500"
    assert mandate_cur["available_atoms"] == "8500"

    # 3. Settle Execution on Success
    settled = gateway.settle_execution(
        hold1["id"],
        ok=True,
        result_digest="sha256:" + "b" * 64,
    )
    assert settled["status"] == "settled"

    # Verify funds moved from locked hold to provider payable
    prov_acc_cur = store.one("account_by_owner_purpose", (provider_id, "provider_payable"))
    hold_acc_after = store.one("account_by_owner_purpose", (user_owner, "user_locked"))
    assert int(hold_acc_after["balance_atoms"]) == 0
    assert int(prov_acc_cur["balance_atoms"]) == 1500

    # Invariant zero-sum
    audit_settle = commercial.ledger.audit()
    assert int(audit_settle["beneficial_atoms"]) + int(audit_settle["clearing_atoms"]) == 0

    # 4. Agent Executes Task that FAILS -> Refund
    hold2 = gateway.hold_execution(
        owner_id=user_owner,
        provider_id=provider_id,
        task_ref="task:unstable-run",
        price_atoms=1000,
        idem_key=uid(),
        actor="agent",
        agent_principal_id=agent_principal_id,
        mandate_id=mandate["id"],
    )
    assert hold2["status"] == "held"
    assert gateway.get_mandate(mandate["id"])["spent_atoms"] == "2500"

    refunded = gateway.settle_execution(hold2["id"], ok=False)
    assert refunded["status"] == "refunded"

    # Verify user received full refund and mandate limit restored
    user_acc_after_refund = store.one("account_by_owner_purpose", (user_owner, "user_available"))
    assert int(user_acc_after_refund["balance_atoms"]) == 50000 - 1500  # only first task spent
    assert gateway.get_mandate(mandate["id"])["spent_atoms"] == "1500"

    # Final zero-sum audit
    audit_final = commercial.ledger.audit()
    assert int(audit_final["beneficial_atoms"]) + int(audit_final["clearing_atoms"]) == 0


def test_agent_payments_http_routes(store):  # noqa: F811
    store.migrate_model()

    vault = KeyVault()
    router = create_live_ad_coin_v2_router(
        store,
        key_vault=vault,
        taxonomy=DEFAULT_TAXONOMY,
        regions=DEFAULT_REGIONS,
        languages=DEFAULT_LANGUAGES,
        clock_ms=lambda: NOW,
        include_workspace=True,
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    commercial, resolver, _ = build_live_service(
        store,
        key_vault=vault,
        taxonomy=DEFAULT_TAXONOMY,
        regions=DEFAULT_REGIONS,
        languages=DEFAULT_LANGUAGES,
        clock_ms=lambda: NOW,
    )

    user_owner = uid()
    user_principal_id = uid()
    user_token = "usr_sess_" + uid()
    user_csrf = "csrf_" + uid()

    commercial.access.provision_principal(
        user_principal_id, Kind.HUMAN, owner_id=user_owner, capabilities=HUMAN_CAPABILITIES
    )
    commercial.access.provision_wallet(user_owner)

    user_acc = store.one("account_by_owner_purpose", (user_owner, "user_available"))
    clearing = commercial.ledger.create_account(uid(), "external_clearing")
    commercial.ledger.post(
        "seed-user",
        [(clearing, "-20000"), (user_acc["id"], "20000")],
        kind="model_seed",
    )

    expires_at = (NOW // 1000) + 3600
    resolver.register_human_session(
        user_token, user_csrf, principal_id=user_principal_id, owner_id=user_owner, epoch=1, expires_at=expires_at
    )

    headers = {
        "Cookie": f"__Host-ac_customer_session={user_token}",
        "X-CSRF-Token": user_csrf,
        "X-AIAC-Contract": "v6.2",
    }

    # 1. Create Mandate via HTTP
    agent_id = uid()
    provider_id = uid()
    res_mandate = client.post(
        "/api/ad-coin/v2/agent-payments/mandates",
        headers=headers,
        json={
            "agent_principal_id": agent_id,
            "total_atoms": 5000,
            "per_task_atoms": 1000,
            "providers": [provider_id],
        },
    )
    assert res_mandate.status_code == 201, res_mandate.text
    m_data = res_mandate.json()
    mandate_id = m_data["id"]

    # 2. List Mandates
    res_list = client.get("/api/ad-coin/v2/agent-payments/mandates", headers=headers)
    assert res_list.status_code == 200
    items = res_list.json()["mandates"]
    assert any(m["id"] == mandate_id for m in items)

    # 3. Direct User Execution Hold
    res_hold = client.post(
        "/api/ad-coin/v2/agent-payments/executions/hold",
        headers={**headers, "Idempotency-Key": uid()},
        json={
            "provider_id": provider_id,
            "task_ref": "direct-task",
            "price_atoms": 800,
        },
    )
    assert res_hold.status_code == 202, res_hold.text
    exec_data = res_hold.json()
    execution_id = exec_data["id"]

    # 4. Settle Execution
    res_settle = client.post(
        f"/api/ad-coin/v2/agent-payments/executions/{execution_id}/settle",
        headers=headers,
        json={
            "ok": True,
            "result_digest": "sha256:" + "c" * 64,
        },
    )
    assert res_settle.status_code == 200, res_settle.text
    assert res_settle.json()["status"] == "settled"

    # 5. Revoke Mandate
    res_revoke = client.post(
        f"/api/ad-coin/v2/agent-payments/mandates/{mandate_id}/revoke",
        headers=headers,
    )
    assert res_revoke.status_code == 200
    assert res_revoke.json()["revoked_at"] is not None
