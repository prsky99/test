import json

import pytest
from eth_account import Account
from fastapi.testclient import TestClient

from agent_market.buyer import BuyerAgent, BuyerError
from agent_market.chain import TRANSFER_TOPIC
from agent_market.config import BuyerConfig, NetworkConfig, SellerConfig, usdc
from agent_market.ledger import Ledger
from agent_market.payments import PaymentVerifier, sign_payment
from agent_market.server import create_app
from agent_market.services import SERVICES, ServiceError

NET = NetworkConfig(84532, "base-sepolia", "http://rpc", "0x036CbD53842c5426634e7929541eC2318f3dCF7e", True)
SELLER = Account.create()
BUYER = Account.create()


def topic(addr):
    return "0x" + addr.lower().removeprefix("0x").rjust(64, "0")


class FakeChain:
    """receipt/block_number/nonce/gas_price/estimate_gas/send_raw 만 흉내내는 가짜 체인."""

    def __init__(self):
        self.receipts = {}
        self.height = 100
        self._pending_call = None

    def add_transfer(self, frm, to, amount, token=NET.token, status=1, block=100):
        tx_hash = "0x" + format(len(self.receipts) + 1, "064x")
        self.receipts[tx_hash] = {
            "status": hex(status),
            "blockNumber": hex(block),
            "logs": [{"address": token, "topics": [TRANSFER_TOPIC, topic(frm), topic(to)], "data": hex(amount)}],
        }
        return tx_hash

    def receipt(self, tx_hash):
        return self.receipts.get(tx_hash)

    def block_number(self):
        return self.height

    def nonce(self, address):
        return 0

    def gas_price(self):
        return 1

    def estimate_gas(self, tx):
        self._pending_call = tx
        return 60000

    def send_raw(self, raw):
        sender = Account.recover_transaction(raw)
        data = self._pending_call["data"].removeprefix("0x")
        to, amount = "0x" + data[8 + 24 : 8 + 64], int(data[8 + 64 :], 16)
        return self.add_transfer(sender, to, amount)


class FakeWorker:
    def __init__(self, fail=None):
        self.fail = fail
        self.calls = []

    def run(self, service, text):
        self.calls.append((service.name, text))
        if self.fail:
            raise self.fail
        return f"[{service.name}] {text[:20]}"


@pytest.fixture
def env():
    chain = FakeChain()
    worker = FakeWorker()
    config = SellerConfig(NET, SELLER.address, ":memory:", "secret", 1)
    ledger = Ledger()
    verifier = PaymentVerifier(chain, NET.token, SELLER.address, 1)
    client = TestClient(create_app(config, verifier=verifier, worker=worker, ledger=ledger))
    return chain, worker, client


def paid_post(client, tx_hash, body_obj, key=BUYER.key, service="summarize"):
    body = json.dumps(body_obj).encode()
    return client.post(
        f"/services/{service}",
        content=body,
        headers={"content-type": "application/json", "X-Payment-Tx": tx_hash, "X-Payment-Signature": sign_payment(key, tx_hash, body)},
    )


def test_agent_card_lists_services(env):
    _, _, client = env
    card = client.get("/.well-known/agent.json").json()
    assert {s["name"] for s in card["services"]} == set(SERVICES)
    assert card["services"][0]["payment"]["pay_to"] == SELLER.address


def test_unpaid_request_gets_402_with_terms(env):
    _, worker, client = env
    r = client.post("/services/summarize", json={"input": "hello"})
    assert r.status_code == 402
    assert r.json()["payment"]["amount"] == SERVICES["summarize"].price
    assert worker.calls == []


def test_valid_payment_runs_service_and_records_revenue(env):
    chain, worker, client = env
    tx = chain.add_transfer(BUYER.address, SELLER.address, usdc("0.02"))
    r = paid_post(client, tx, {"input": "long text"})
    assert r.status_code == 200, r.text
    assert r.json()["receipt"]["payer"] == BUYER.address.lower()
    assert worker.calls == [("summarize", "long text")]
    stats = client.get("/stats", headers={"authorization": "Bearer secret"}).json()
    assert stats["total_revenue"] == usdc("0.02")


def test_payment_cannot_be_reused(env):
    chain, _, client = env
    tx = chain.add_transfer(BUYER.address, SELLER.address, usdc("0.02"))
    assert paid_post(client, tx, {"input": "a"}).status_code == 200
    assert paid_post(client, tx, {"input": "b"}).status_code == 409


def test_underpayment_rejected(env):
    chain, worker, client = env
    tx = chain.add_transfer(BUYER.address, SELLER.address, usdc("0.01"))
    r = paid_post(client, tx, {"input": "a"})
    assert r.status_code == 402 and "부족" in r.json()["error"]
    assert worker.calls == []


def test_payment_to_other_wallet_rejected(env):
    chain, _, client = env
    tx = chain.add_transfer(BUYER.address, Account.create().address, usdc("1"))
    assert paid_post(client, tx, {"input": "a"}).status_code == 402


def test_wrong_token_rejected(env):
    chain, _, client = env
    tx = chain.add_transfer(BUYER.address, SELLER.address, usdc("1"), token="0x" + "11" * 20)
    assert paid_post(client, tx, {"input": "a"}).status_code == 402


def test_failed_tx_rejected(env):
    chain, _, client = env
    tx = chain.add_transfer(BUYER.address, SELLER.address, usdc("1"), status=0)
    assert paid_post(client, tx, {"input": "a"}).status_code == 402


def test_someone_elses_payment_cannot_be_stolen(env):
    chain, worker, client = env
    tx = chain.add_transfer(BUYER.address, SELLER.address, usdc("0.02"))
    thief = Account.create()
    r = paid_post(client, tx, {"input": "a"}, key=thief.key)
    assert r.status_code == 403
    assert worker.calls == []
    # 진짜 결제자는 여전히 사용할 수 있다
    assert paid_post(client, tx, {"input": "a"}).status_code == 200


def test_signature_bound_to_body(env):
    chain, _, client = env
    tx = chain.add_transfer(BUYER.address, SELLER.address, usdc("0.02"))
    signed_for = json.dumps({"input": "a"}).encode()
    r = client.post(
        "/services/summarize",
        content=json.dumps({"input": "other"}).encode(),
        headers={"content-type": "application/json", "X-Payment-Tx": tx, "X-Payment-Signature": sign_payment(BUYER.key, tx, signed_for)},
    )
    assert r.status_code == 403


def test_unconfirmed_payment_is_retryable(env):
    chain, _, client = env
    tx = chain.add_transfer(BUYER.address, SELLER.address, usdc("0.02"), block=101)
    r = paid_post(client, tx, {"input": "a"})
    assert r.status_code == 402 and r.json()["retryable"] is True


def test_service_failure_releases_payment_for_retry(env):
    chain, worker, client = env
    worker.fail = ServiceError("refused")
    tx = chain.add_transfer(BUYER.address, SELLER.address, usdc("0.02"))
    r = paid_post(client, tx, {"input": "a"})
    assert r.status_code == 422 and r.json()["retry_with_same_payment"]
    worker.fail = None
    assert paid_post(client, tx, {"input": "a"}).status_code == 200


def test_stats_requires_admin_token(env):
    _, _, client = env
    assert client.get("/stats").status_code == 401
    assert client.get("/stats", headers={"authorization": "Bearer wrong"}).status_code == 401


def buyer_for(client, chain, **overrides):
    cfg = dict(network=NET, private_key=BUYER.key.hex(), max_per_call=usdc("0.10"), budget=usdc("1.00"), allow_mainnet=False)
    cfg.update(overrides)
    agent = BuyerAgent(BuyerConfig(**cfg), rpc=chain, http=client)
    agent.confirm_interval = 0
    return agent


def test_buyer_agent_end_to_end(env):
    chain, worker, client = env
    agent = buyer_for(client, chain)
    result = agent.buy("", "code_review", "def f(): return 1/0")
    assert result["output"].startswith("[code_review]")
    assert result["receipt"]["amount"] == SERVICES["code_review"].price
    assert agent.spent == SERVICES["code_review"].price


def test_buyer_refuses_over_per_call_limit(env):
    chain, worker, client = env
    agent = buyer_for(client, chain, max_per_call=usdc("0.01"))
    with pytest.raises(BuyerError, match="상한"):
        agent.buy("", "summarize", "x")
    assert chain.receipts == {}  # 돈이 나가지 않았다


def test_buyer_refuses_over_budget(env):
    chain, _, client = env
    agent = buyer_for(client, chain, budget=usdc("0.05"))
    agent.buy("", "code_review", "x")
    with pytest.raises(BuyerError, match="예산"):
        agent.buy("", "summarize", "x")


def test_buyer_refuses_mainnet_by_default(env):
    chain, _, _ = env
    mainnet = NetworkConfig(8453, "base", "http://rpc", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", False)
    config = SellerConfig(mainnet, SELLER.address, ":memory:", None, 1)
    client = TestClient(create_app(config, verifier=PaymentVerifier(chain, mainnet.token, SELLER.address), worker=FakeWorker(), ledger=Ledger()))
    agent = buyer_for(client, chain, network=mainnet)
    with pytest.raises(BuyerError, match="ALLOW_MAINNET"):
        agent.buy("", "summarize", "x")
