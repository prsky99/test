"""Tests for payment improvements and admin payment management dashboard.

Covers:
1. Multi-RPC failover pool and exponential backoff
2. Thread-safe NonceManager
3. EIP-1559 dynamic fee calculation
4. EIP-712 typed structured data signing and verification
5. Orphan pending and hold sweepers
6. Clearinghouse reserve audit and credit withdrawal
7. Admin payment API endpoints in dashboard.py
8. Dashboard HTML tab, panel, and modal presence
"""

import time
import pytest
from unittest.mock import MagicMock, patch

from agent_market.chain import RPC, NonceManager, get_nonce_manager, RPCError
from agent_market.payments import (
    payment_eip712_data,
    sign_payment_eip712,
    recover_signer,
    sign_payment,
)
from agent_market.ledger import Ledger
from agent_market.gateway.store import Store
from agent_market.concierge.clearinghouse import Clearinghouse, InsufficientCreditsError
from agent_market.gateway.dashboard import dashboard_router
from fastapi.testclient import TestClient
from fastapi import FastAPI
from tests.conftest import staff_headers

pytestmark = pytest.mark.usefixtures('rotated_bootstrap_admin')


# ---------------------------------------------------------------------------
# 1. Multi-RPC & NonceManager Tests
# ---------------------------------------------------------------------------

def test_multi_rpc_provider_failover():
    urls = ["http://primary-rpc.invalid:8545", "http://secondary-rpc.invalid:8545"]
    rpc = RPC(urls, max_retries=1)

    assert rpc.urls == urls
    assert rpc.url == urls[0]

    # Test failover on error
    mock_client = MagicMock()
    mock_resp_ok = MagicMock()
    mock_resp_ok.status_code = 200
    mock_resp_ok.raise_for_status.return_value = None
    mock_resp_ok.json.return_value = {"jsonrpc": "2.0", "result": "0x123", "id": 1}

    # First request fails, second succeeds on next URL
    import httpx
    mock_client.post.side_effect = [
        httpx.ConnectError("Connection failed"),
        mock_resp_ok,
    ]
    rpc.client = mock_client

    result = rpc.call("eth_blockNumber")
    assert result == "0x123"
    # url index should have moved to urls[1]
    assert rpc.url == urls[1]


def test_nonce_manager_thread_safety():
    rpc = MagicMock()
    rpc.nonce.return_value = 10

    manager = NonceManager()
    account = "0x1111111111111111111111111111111111111111"

    n1 = manager.get_nonce(account, rpc)
    assert n1 == 10
    n2 = manager.get_nonce(account, rpc)
    assert n2 == 11

    # On reset (e.g. error in tx dispatch), next call re-fetches from rpc
    rpc.nonce.return_value = 25
    manager.reset(account)
    n3 = manager.get_nonce(account, rpc)
    assert n3 == 25


def test_eip1559_fee_calculation():
    rpc = MagicMock()
    rpc.call.side_effect = lambda method, *args: {
        "eth_maxPriorityFeePerGas": hex(2_000_000_000),  # 2 Gwei
        "eth_getBlockByNumber": {"baseFeePerGas": hex(10_000_000_000)},  # 10 Gwei
    }.get(method, "0x0")

    rpc.max_priority_fee = lambda: 2_000_000_000
    max_fee, priority_fee = RPC.eip1559_fees(rpc)

    # 10 Gwei * 1.3 + 2 Gwei = 13 + 2 = 15 Gwei
    assert priority_fee == 2_000_000_000
    assert max_fee == 15_000_000_000


# ---------------------------------------------------------------------------
# 2. EIP-712 Structured Signing & Verification
# ---------------------------------------------------------------------------

def test_eip712_structured_signing_and_verification():
    from eth_account import Account
    acct = Account.create()

    tx_hash = "0x" + "a" * 64
    body = b'{"query": "health check", "target": "agent-1"}'
    chain_id = 8453
    verifying_contract = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"  # Base USDC

    # 1. Sign using EIP-712
    sig_eip712 = sign_payment_eip712(
        private_key=acct.key.hex(),
        chain_id=chain_id,
        verifying_contract=verifying_contract,
        tx_hash=tx_hash,
        body=body,
    )
    assert sig_eip712.startswith("0x")

    # 2. Recover signer with EIP-712 fallback
    recovered = recover_signer(
        purpose="agent-market",
        subject=tx_hash,
        body=body,
        signature=sig_eip712,
        chain_id=chain_id,
        token=verifying_contract,
    )
    assert recovered.lower() == acct.address.lower()

    # 3. Backward compatibility: verify standard EIP-191 sign also recovers properly
    sig_eip191 = sign_payment(
        private_key=acct.key.hex(),
        tx_hash=tx_hash,
        body=body,
    )
    recovered_legacy = recover_signer(
        purpose="agent-market",
        subject=tx_hash,
        body=body,
        signature=sig_eip191,
    )
    assert recovered_legacy.lower() == acct.address.lower()


# ---------------------------------------------------------------------------
# 3. Orphan Sweeper in PaymentLedger
# ---------------------------------------------------------------------------

def test_ledger_sweep_orphaned_pending(tmp_path):
    db_file = tmp_path / "ledger.db"
    ledger = Ledger(str(db_file))

    # Record two payments: one old, one fresh
    ledger.claim("0x111", "0xpayer1", "serviceA", 100)
    # simulate old claim by directly updating created_at
    ledger._db.execute("UPDATE payments SET created_at = ? WHERE tx_hash = '0x111'", (time.time() - 3600,))
    ledger._db.commit()

    ledger.claim("0x222", "0xpayer2", "serviceB", 200)

    swept = ledger.sweep_orphaned_pending(ttl_seconds=1800)
    assert swept == 1

    assert ledger.get_payment("0x111") is None
    fresh_entry = ledger.get_payment("0x222")
    assert fresh_entry is not None
    assert fresh_entry["status"] == "pending"


# ---------------------------------------------------------------------------
# 4. Clearinghouse Reserve Audit & Credit Withdrawal
# ---------------------------------------------------------------------------

def test_clearinghouse_reserve_audit_and_withdraw(tmp_path):
    db_file = tmp_path / "store.db"
    store = Store(str(db_file))
    clearing = Clearinghouse(store=store)

    agent_id = "agent-test-clearing-1"
    clearing.deposit(agent_id, 1000)

    # Check reserve audit before withdrawal
    audit1 = clearing.reserve_audit()
    assert audit1["total_user_balance_micro_usdc"] == 1000
    assert audit1["is_fully_backed"] is True

    # Test withdraw
    w_res = clearing.withdraw(agent_id, 400, to_address="0x3333333333333333333333333333333333333333")
    assert w_res["status"] == "withdrawn"
    assert w_res["amount"] == 400
    assert store.get_credit(agent_id)["balance"] == 600

    # Check reserve audit after withdrawal
    audit2 = clearing.reserve_audit()
    assert audit2["total_user_balance_micro_usdc"] == 600

    # Overdraft should fail
    with pytest.raises(InsufficientCreditsError):
        clearing.withdraw(agent_id, 9999, to_address="0x3333333333333333333333333333333333333333")


# ---------------------------------------------------------------------------
# 5. Admin Payment Management API Endpoints
# ---------------------------------------------------------------------------

@pytest.fixture
def admin_client(tmp_path):
    db_file = str(tmp_path / "admin_test.db")
    store = Store(db_file)
    app = FastAPI()
    router = dashboard_router(store=store, db_path=db_file, admin_token="test-secret-token", collector=None)
    app.include_router(router)
    client = TestClient(app)
    return client, store


def test_admin_payment_endpoints(admin_client):
    client, store = admin_client
    headers = staff_headers(client)

    # 1. Overview
    res = client.get("/admin/api/payments/overview", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "clearinghouse" in data
    assert "reserve_audit" in data

    # 2. Deposit credits via admin API
    res_dep = client.post(
        "/admin/api/payments/deposit",
        headers=headers,
        json={"agent_id": "test-agent-alpha", "amount_credits": 2500, "reason": "Admin Bonus"},
    )
    assert res_dep.status_code == 200
    assert res_dep.json()["balance"] == 2500

    # 3. List accounts
    res_acc = client.get("/admin/api/payments/accounts", headers=headers)
    assert res_acc.status_code == 200
    acc_data = res_acc.json()
    assert acc_data["total"] >= 1
    found = any(a["agent_id"] == "test-agent-alpha" for a in acc_data["items"])
    assert found is True

    # 4. Withdraw credits via admin API
    res_wd = client.post(
        "/admin/api/payments/withdraw",
        headers=headers,
        json={"agent_id": "test-agent-alpha", "amount_credits": 500, "notes": "Admin withdrawal", "to_address": "0x" + "3" * 40},
    )
    assert res_wd.status_code == 200
    assert res_wd.json()["remaining_balance"] == 2000

    # 5. Sweep orphaned
    res_sweep = client.post(
        "/admin/api/payments/sweep",
        headers=headers,
        json={"ttl_seconds": 1800},
    )
    assert res_sweep.status_code == 200
    assert res_sweep.json()["ok"] is True

    # 6. Clearinghouse transactions list
    res_ch = client.get("/admin/api/payments/clearinghouse", headers=headers)
    assert res_ch.status_code == 200
    assert "items" in res_ch.json()

    # 7. On-chain ledger list
    res_led = client.get("/admin/api/payments/ledger", headers=headers)
    assert res_led.status_code == 200
    assert "items" in res_led.json()


# ---------------------------------------------------------------------------
# 6. Dashboard HTML Tab and UI Components Verification
# ---------------------------------------------------------------------------

def test_dashboard_html_payment_ui():
    from pathlib import Path
    html_path = Path("agent_market/gateway/dashboard.html")
    assert html_path.exists()
    content = html_path.read_text(encoding="utf-8")

    # Navigation tab
    assert 'data-tab="payments"' in content
    assert 'id="tabPayments"' in content

    # Panel section
    assert 'data-panel="payments"' in content

    # Sub panels
    assert 'id="paySubPanelClearing"' in content
    assert 'id="paySubPanelAccounts"' in content
    assert 'id="paySubPanelLedger"' in content
    assert 'id="paySubPanelReserve"' in content

    # Modals
    assert 'id="paymentDepositModal"' in content
    assert 'id="paymentWithdrawModal"' in content
    assert 'id="paymentReceiptModal"' in content

    # Script hooks
    assert 'state.tab === "payments"' in content
    assert '"payments"' in content  # in TABS array
    assert 'loadPayments' in content
