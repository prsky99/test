"""Tests for A402 Virtual Escrow & Micropayment Clearinghouse."""

import pytest
from agent_market.concierge.clearinghouse import (
    Clearinghouse,
    ClearinghouseError,
    InsufficientCreditsError,
)
from agent_market.gateway.store import Store


@pytest.fixture
def store():
    return Store(":memory:")


@pytest.fixture
def clearinghouse(store):
    return Clearinghouse(store, max_latency_ms=1000)


def test_deposit_and_balance(clearinghouse):
    bal = clearinghouse.deposit("agent_alice", 500_000)
    assert bal["balance"] == 500_000
    assert bal["held"] == 0
    assert bal["available"] == 500_000
    assert bal["total_deposited"] == 500_000

    bal2 = clearinghouse.deposit("agent_alice", 250_000)
    assert bal2["balance"] == 750_000
    assert bal2["available"] == 750_000

    with pytest.raises(ClearinghouseError):
        clearinghouse.deposit("agent_alice", -10)


def test_escrow_hold_and_settle(clearinghouse):
    clearinghouse.deposit("agent_bob", 100_000)

    # Hold escrow
    tx_id = clearinghouse.escrow_hold("agent_bob", 40_000, 101, "search_api")
    assert tx_id.startswith("clr_")

    bal = clearinghouse.balance("agent_bob")
    assert bal["balance"] == 100_000
    assert bal["held"] == 40_000
    assert bal["available"] == 60_000

    # Insufficient credits for another large hold
    with pytest.raises(InsufficientCreditsError):
        clearinghouse.escrow_hold("agent_bob", 70_000, 102, "expensive_api")

    # Settle escrow after successful SLA
    result = {
        "ok": True,
        "latency_ms": 120,
        "result": {"status": "success", "data": [1, 2, 3]},
    }
    settled = clearinghouse.escrow_settle(tx_id, result)
    assert settled["status"] == "settled"
    assert settled["amount"] == 40_000
    receipt = settled["receipt"]
    assert receipt["receipt_id"] == tx_id
    assert receipt["sla_verified"] is True
    assert "integrity_seal" in receipt

    bal_after = clearinghouse.balance("agent_bob")
    assert bal_after["balance"] == 60_000
    assert bal_after["held"] == 0
    assert bal_after["available"] == 60_000
    assert bal_after["total_spent"] == 40_000


def test_escrow_refund_on_sla_failure(clearinghouse):
    clearinghouse.deposit("agent_charlie", 50_000)

    tx_id = clearinghouse.escrow_hold("agent_charlie", 20_000, 202, "broken_tool")
    bal = clearinghouse.balance("agent_charlie")
    assert bal["available"] == 30_000

    # Tool returned error -> SLA verification fails
    failed_result = {
        "ok": False,
        "error": "Upstream 500 Internal Server Error",
        "latency_ms": 80,
    }
    refunded = clearinghouse.escrow_settle(tx_id, failed_result)
    assert refunded["status"] == "refunded"
    assert refunded["amount"] == 20_000

    bal_after = clearinghouse.balance("agent_charlie")
    assert bal_after["balance"] == 50_000
    assert bal_after["held"] == 0
    assert bal_after["available"] == 50_000
    assert bal_after["total_spent"] == 0


def test_escrow_refund_on_timeout(clearinghouse):
    clearinghouse.deposit("agent_dan", 30_000)
    tx_id = clearinghouse.escrow_hold("agent_dan", 15_000, 303, "slow_tool")

    # Exceeds max_latency_ms (1000ms)
    timeout_result = {
        "ok": True,
        "latency_ms": 1500,
        "result": {"data": "too late"},
    }
    refunded = clearinghouse.escrow_settle(tx_id, timeout_result)
    assert refunded["status"] == "refunded"
    assert "exceeded maximum" in refunded["reason"]

    bal = clearinghouse.balance("agent_dan")
    assert bal["available"] == 30_000


def test_clearinghouse_stats(clearinghouse):
    clearinghouse.deposit("agent_1", 100_000)
    clearinghouse.deposit("agent_2", 200_000)

    tx1 = clearinghouse.escrow_hold("agent_1", 20_000, 1, "t1")
    clearinghouse.escrow_settle(tx1, {"ok": True, "latency_ms": 50, "result": "ok"})

    tx2 = clearinghouse.escrow_hold("agent_2", 30_000, 2, "t2")
    clearinghouse.escrow_refund(tx2, reason="canceled")

    stats = clearinghouse.stats()
    assert stats["accounts"]["total_accounts"] == 2
    assert stats["accounts"]["total_settled"] == 20_000
    assert stats["ledger_by_status"]["settled"]["count"] == 1
    assert stats["ledger_by_status"]["settled"]["total_amount"] == 20_000
    assert stats["ledger_by_status"]["refunded"]["count"] == 1
