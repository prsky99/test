import json

import httpx
import pytest
from eth_account import Account
from fastapi.testclient import TestClient

from agent_market.broker.categories import match_fee
from agent_market.broker.discovery import CardFetcher, DiscoveryError, check_public_url
from agent_market.broker.registry import Registry
from agent_market.broker.server import create_app as create_broker
from agent_market.buyer import BuyerAgent, BuyerError
from agent_market.config import BrokerConfig, BuyerConfig, SellerConfig, usdc
from agent_market.ledger import Ledger
from agent_market.payments import PaymentVerifier, sign_payment, sign_request
from agent_market.server import create_app as create_seller
from agent_market.services import ServiceError
from tests.test_market import NET, FakeChain, FakeWorker

BROKER = Account.create()
BUYER = Account.create()


class Router(httpx.BaseTransport):
    """호스트 이름별로 in-process ASGI 앱에 요청을 보내는 테스트용 전송 계층."""

    def __init__(self, apps):
        self.transports = {host: TestClient(app)._transport for host, app in apps.items()}

    def handle_request(self, request):
        resp = self.transports[request.url.host].handle_request(request)
        return httpx.Response(resp.status_code, headers=resp.headers, content=resp.read())


class FakeClassifier:
    def __init__(self, category="llm_inference"):
        self.category = category
        self.calls = []

    def classify(self, task):
        self.calls.append(task)
        return self.category, task[:50]


class World:
    def __init__(self, seller_prices=None):
        self.chain = FakeChain()
        self.apps = {}
        self.sellers = {}
        self.http = httpx.Client(transport=Router(self.apps), base_url="http://broker")
        self.classifier = FakeClassifier()
        config = BrokerConfig(NET, BROKER.address, ":memory:", "secret", 1, 500, usdc("0.001"), True)
        self.registry = Registry()
        fetcher = CardFetcher(http=self.http, allow_private=True, network={"chain_id": NET.chain_id, "token": NET.token})
        self.apps["broker"] = create_broker(
            config, verifier=PaymentVerifier(self.chain, NET.token, BROKER.address), classifier=self.classifier,
            fetcher=fetcher, registry=self.registry, ledger=Ledger(),
        )
        self.router_reset()

    def router_reset(self):
        self.http._transport = Router(self.apps)

    def add_seller(self, host):
        wallet = Account.create()
        worker = FakeWorker()
        self.apps[host] = create_seller(
            SellerConfig(NET, wallet.address, ":memory:", None, 1),
            verifier=PaymentVerifier(self.chain, NET.token, wallet.address), worker=worker, ledger=Ledger(),
        )
        self.router_reset()
        self.sellers[host] = (wallet, worker)
        r = self.http.post("http://broker/agents/register", json={"url": f"http://{host}"})
        assert r.status_code == 200, r.text
        return r.json()["agent_id"]

    def buyer(self, **overrides):
        cfg = dict(network=NET, private_key=BUYER.key.hex(), max_per_call=usdc("0.10"), budget=usdc("1.00"), allow_mainnet=False)
        cfg.update(overrides)
        agent = BuyerAgent(BuyerConfig(**cfg), rpc=self.chain, http=self.http)
        agent.confirm_interval = 0
        return agent

    def paid_accept(self, quote_id, key=BUYER.key, amount=None, payer=BUYER.address):
        tx = self.chain.add_transfer(payer, BROKER.address, amount)
        body = json.dumps({"quote_id": quote_id}).encode()
        return tx, self.http.post(
            "/match/accept", content=body,
            headers={"content-type": "application/json", "X-Payment-Tx": tx, "X-Payment-Signature": sign_payment(key, tx, body)},
        )


@pytest.fixture
def world():
    return World()


def test_register_reads_seller_card(world):
    world.add_seller("seller-a")
    listings = world.registry.find("llm_inference", None, 10)
    assert {l.service for l in listings} == {"summarize", "translate", "code_review"}


def test_match_returns_quote_without_contact_info(world):
    world.add_seller("seller-a")
    r = world.http.post("/match", json={"task": "이 글을 요약해줘"})
    assert r.status_code == 402
    q = r.json()
    assert q["category"] == "llm_inference" and q["candidates"]
    assert "agent_url" not in q["candidates"][0] and "pay_to" not in q["candidates"][0]
    assert q["payment"]["pay_to"] == BROKER.address and q["fee"] == match_fee(q["candidates"][0]["price"])


def test_no_candidates_means_no_fee(world):
    r = world.http.post("/match", json={"task": "x", "category": "prediction"})
    assert r.status_code == 404


def test_explicit_category_skips_classifier(world):
    world.add_seller("seller-a")
    world.http.post("/match", json={"task": "x", "category": "llm_inference"})
    assert world.classifier.calls == []


def test_max_price_filters(world):
    world.add_seller("seller-a")
    q = world.http.post("/match", json={"task": "x", "category": "llm_inference", "max_price": usdc("0.02")}).json()
    assert [c["service"] for c in q["candidates"]] == ["summarize"]


def test_paid_accept_reveals_contacts_and_counts_revenue(world):
    world.add_seller("seller-a")
    q = world.http.post("/match", json={"task": "x", "category": "llm_inference"}).json()
    tx, r = world.paid_accept(q["quote_id"], amount=q["fee"])
    assert r.status_code == 200, r.text
    assert r.json()["candidates"][0]["agent_url"] == "http://seller-a"
    # 같은 결제로 재요청하면 같은 결과 (응답 유실 대비)
    body = json.dumps({"quote_id": q["quote_id"]}).encode()
    again = world.http.post("/match/accept", content=body, headers={"content-type": "application/json", "X-Payment-Tx": tx, "X-Payment-Signature": sign_payment(BUYER.key, tx, body)})
    assert again.status_code == 200
    stats = world.http.get("/stats", headers={"authorization": "Bearer secret"}).json()
    assert stats["fee_revenue"] == q["fee"] and stats["by_category"]["llm_inference"]["paid_matches"] == 1


def test_underpaid_fee_rejected(world):
    world.add_seller("seller-a")
    q = world.http.post("/match", json={"task": "x", "category": "llm_inference"}).json()
    _, r = world.paid_accept(q["quote_id"], amount=q["fee"] - 1)
    assert r.status_code == 402


def test_quote_cannot_be_paid_twice_and_fee_tx_not_reusable(world):
    world.add_seller("seller-a")
    q1 = world.http.post("/match", json={"task": "x", "category": "llm_inference"}).json()
    q2 = world.http.post("/match", json={"task": "y", "category": "llm_inference"}).json()
    tx, r = world.paid_accept(q1["quote_id"], amount=q1["fee"])
    assert r.status_code == 200
    _, r = world.paid_accept(q1["quote_id"], amount=q1["fee"])
    assert r.status_code == 409
    body = json.dumps({"quote_id": q2["quote_id"]}).encode()
    r = world.http.post("/match/accept", content=body, headers={"content-type": "application/json", "X-Payment-Tx": tx, "X-Payment-Signature": sign_payment(BUYER.key, tx, body)})
    assert r.status_code == 409


def test_feedback_only_from_payer_and_once(world):
    agent_id = world.add_seller("seller-a")
    q = world.http.post("/match", json={"task": "x", "category": "llm_inference"}).json()
    _, r = world.paid_accept(q["quote_id"], amount=q["fee"])
    cand = r.json()["candidates"][0]
    body = json.dumps({"match_id": q["quote_id"], "agent_id": agent_id, "service": cand["service"], "success": True, "rating": 5}).encode()

    def post(key):
        sig = sign_request(key, "agent-broker-feedback", q["quote_id"], body)
        return world.http.post("/match/feedback", content=body, headers={"content-type": "application/json", "X-Signature": sig})

    assert post(Account.create().key).status_code == 403
    assert post(BUYER.key).status_code == 200
    assert post(BUYER.key).status_code == 409


def test_reputation_changes_ranking(world):
    a = world.add_seller("seller-a")
    b = world.add_seller("seller-b")
    for good, bad in [(b, a)] * 3:
        q = world.http.post("/match", json={"task": "x", "category": "llm_inference", "max_price": usdc("0.02")}).json()
        _, r = world.paid_accept(q["quote_id"], amount=q["fee"])
        for agent_id, success, rating in [(good, True, 5), (bad, False, 1)]:
            body = json.dumps({"match_id": q["quote_id"], "agent_id": agent_id, "service": "summarize", "success": success, "rating": rating}).encode()
            sig = sign_request(BUYER.key, "agent-broker-feedback", q["quote_id"], body)
            assert world.http.post("/match/feedback", content=body, headers={"content-type": "application/json", "X-Signature": sig}).status_code == 200
    top = world.registry.find("llm_inference", usdc("0.02"), 2)
    assert [l.agent_id for l in top] == [b, a]


def test_buyer_hire_end_to_end(world):
    world.add_seller("seller-a")
    buyer = world.buyer()
    result = buyer.hire("http://broker", "긴 보고서를 요약해 줄 에이전트", "보고서 본문...", max_price=usdc("0.02"), judge=lambda out: 4)
    assert result["output"].startswith("[summarize]")
    fee = match_fee(usdc("0.02"))
    assert buyer.spent == fee + usdc("0.02")
    assert world.registry.find("llm_inference", usdc("0.02"), 1)[0].ratings == 1


def test_buyer_hire_falls_back_to_next_candidate(world):
    world.add_seller("seller-a")
    world.add_seller("seller-b")
    first = world.registry.find("llm_inference", usdc("0.02"), 1)[0]
    host = first.agent_url.removeprefix("http://")
    world.sellers[host][1].fail = ServiceError("down")
    result = world.buyer().hire("http://broker", "요약", "text", max_price=usdc("0.02"))
    assert result["agent"]["agent_id"] != first.agent_id


def test_buyer_hire_respects_budget(world):
    world.add_seller("seller-a")
    buyer = world.buyer(budget=usdc("0.02"))  # 수수료 + 서비스 대금을 못 냄
    with pytest.raises(BuyerError, match="예산"):
        buyer.hire("http://broker", "요약", "text", max_price=usdc("0.02"))
    assert all(not r["logs"][0]["topics"][2].endswith(BROKER.address.lower()[2:]) for r in world.chain.receipts.values())


def test_seller_pay_to_swap_detected(world):
    world.add_seller("seller-a")
    # 등록 후 판매자가 결제 지갑을 몰래 바꾼 경우
    other = Account.create()
    world.apps["seller-a"] = create_seller(
        SellerConfig(NET, other.address, ":memory:", None, 1),
        verifier=PaymentVerifier(world.chain, NET.token, other.address), worker=FakeWorker(), ledger=Ledger(),
    )
    world.router_reset()
    with pytest.raises(BuyerError, match="모든 후보가 실패"):
        world.buyer().hire("http://broker", "요약", "text", max_price=usdc("0.02"))


def test_card_parse_rejects_other_network_and_unknown_categories():
    fetcher = CardFetcher(http=httpx.Client(), allow_private=True, network={"chain_id": NET.chain_id, "token": NET.token})
    svc = {"name": "s", "category": "llm_inference", "endpoint": "/s", "payment": {"amount": 1, "pay_to": "0xabc", "chain_id": 1, "token": NET.token}}
    with pytest.raises(DiscoveryError, match="네트워크"):
        fetcher.parse("http://x", {"name": "a", "services": [svc]})
    with pytest.raises(DiscoveryError, match="지원 카테고리"):
        fetcher.parse("http://x", {"name": "a", "services": [{**svc, "category": "gambling"}]})


def test_ssrf_guard_blocks_private_hosts():
    for url in ["http://127.0.0.1:8000", "http://localhost", "http://10.0.0.5", "http://169.254.169.254", "file:///etc/passwd"]:
        with pytest.raises(DiscoveryError):
            check_public_url(url)


def test_classification_is_rate_limited(world):
    world.add_seller("seller-a")
    codes = [world.http.post("/match", json={"task": "x"}).status_code for _ in range(25)]
    assert codes.count(429) == 5 and len(world.classifier.calls) == 20
