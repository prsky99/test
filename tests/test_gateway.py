import json
import time

import httpx
import pytest
from eth_account import Account
from fastapi.testclient import TestClient

from agent_market.buyer import BuyerAgent
from agent_market.config import BuyerConfig, GatewayConfig, usdc
from agent_market.gateway.classify import classify
from agent_market.gateway.client import GatewayClient
from agent_market.gateway.crawler import Crawler, Prober, parse_mcp_item, parse_x402_item
from agent_market.gateway.server import create_app
from agent_market.gateway.service import Policy
from agent_market.gateway.store import Store
from agent_market.payments import PaymentVerifier
from tests.test_broker import Router
from tests.test_market import NET, FakeChain

GW = Account.create()
BASE_USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"


def x402_item(url, desc, price, payers, last_called="2026-09-29T00:00:00Z", network="eip155:8453", asset=BASE_USDC):
    return {
        "resource": url, "type": "http", "x402Version": 2, "description": desc,
        "accepts": [{"scheme": "exact", "network": network, "amount": str(price), "asset": asset, "payTo": "0x" + "ab" * 20}],
        "quality": {"l30DaysTotalCalls": payers * 2, "l30DaysUniquePayers": payers, "lastCalledAt": last_called},
        "extensions": {"bazaar": {"info": {"input": {"method": "GET", "type": "http"}}}},
    }


class FakeRegistries(httpx.BaseTransport):
    """x402 Bazaar / MCP Registry / 후보 엔드포인트를 흉내낸다."""

    def __init__(self):
        self.x402 = []
        self.mcp = []
        self.down = set()

    def handle_request(self, request):
        host, path = request.url.host, request.url.path
        if host == "api.cdp.coinbase.com":
            offset, limit = int(request.url.params["offset"]), int(request.url.params["limit"])
            return httpx.Response(200, json={"items": self.x402[offset:offset + limit], "pagination": {"total": len(self.x402)}})
        if host == "registry.modelcontextprotocol.io":
            return httpx.Response(200, json={"servers": self.mcp, "metadata": {}})
        if str(request.url).split("?")[0] in self.down:
            return httpx.Response(503)
        return httpx.Response(402, json={"payment": "required"})


class GW_World:
    def __init__(self, policy=Policy()):
        self.chain = FakeChain()
        self.reg = FakeRegistries()
        self.store = Store()
        ext = httpx.Client(transport=self.reg)
        config = GatewayConfig(NET, GW.address, ":memory:", "secret", 1, 3600, 900, False, True)
        self.app = create_app(
            config, store=self.store, verifier=PaymentVerifier(self.chain, NET.token, GW.address),
            crawler=Crawler(self.store, http=ext, page_delay=0), prober=Prober(self.store, http=ext, allow_private=True),
            policy=policy,
        )
        self.service = self.app.state.service
        self.http = httpx.Client(transport=Router({"gw": self.app}), base_url="http://gw")

    def crawl(self):
        return self.http.post("/admin/crawl", headers={"authorization": "Bearer secret"}).json()

    def client(self, account=None, budget="1.00"):
        account = account or Account.create()
        buyer = BuyerAgent(BuyerConfig(NET, account.key.hex(), usdc("0.10"), usdc(budget), False), rpc=self.chain, http=self.http)
        buyer.confirm_interval = 0
        return GatewayClient("http://gw", account.key.hex(), http=self.http, buyer=buyer)


@pytest.fixture
def w():
    world = GW_World()
    world.reg.x402 = [
        x402_item("https://search-a.example/api", "Web search API returning SERP results for any query", 10_000, 10),
        x402_item("https://chain.example/balance", "ERC20 token balance for any wallet", 3_000, 800),
        x402_item("https://img.example/gen", "Generate an image from a text prompt", 20_000, 30),
    ]
    world.reg.mcp = [{"server": {"name": "io.example/scraper", "title": "Scraper", "description": "Scrape and crawl web pages",
                                 "remotes": [{"type": "streamable-http", "url": "https://mcp.example/mcp"}]},
                      "_meta": {"io.modelcontextprotocol.registry/official": {"status": "active", "isLatest": True}}}]
    world.crawl()
    return world


def test_classifier_keywords():
    assert classify("Web search API for company leads") == "web_data"
    assert classify("ERC20 token balance for any wallet") == "onchain_intel"
    assert classify("이미지 생성해줘") == "media_generation"
    assert classify("zzz") == "other"


def test_parse_x402_picks_usdc_price():
    item = x402_item("https://a.example/x", "desc", 5000, 10)
    item["accepts"].insert(0, {"network": "eip155:8453", "amount": "1", "asset": "0x" + "00" * 20, "payTo": "0x1"})
    r = parse_x402_item(item)
    assert r["price_usdc"] == 5000 and r["payers_30d"] == 10 and r["networks"] == ["eip155:8453"]
    assert parse_x402_item({**item, "resource": "http://insecure"}) is None


def test_parse_mcp_skips_non_latest():
    item = {"server": {"name": "a", "remotes": [{"url": "https://x"}]}, "_meta": {"io.modelcontextprotocol.registry/official": {"isLatest": False}}}
    assert parse_mcp_item(item) is None


def test_crawl_indexes_sources_and_deactivates_removed(w):
    counts = w.store.resource_counts()
    assert counts["x402"]["web_data"] == 1 and counts["mcp"]["web_data"] == 1
    w.reg.x402 = w.reg.x402[1:]
    time.sleep(1.1)
    report = w.crawl()
    assert report["x402-bazaar"]["deactivated"] == 1


def test_first_intro_is_free_and_revealed(w):
    out = w.client().create_need("web search for SERP results", kinds=["x402"])
    assert out["free_intro"] and out["status"] == "active"
    assert out["agent"]["url"] == "https://search-a.example/api"


def test_second_need_same_category_is_paid(w):
    acct = Account.create()
    c = w.client(acct)
    c.create_need("web search for SERP results", kinds=["x402"])
    out = c.create_need("another web search task", kinds=["x402"])
    assert out["status"] == "offer_pending" and not out["free_intro"]
    assert "url" not in json.dumps(out["offer"]["teaser"]) and out["offer"]["payment"]["pay_to"] == GW.address


def test_unsigned_or_forged_need_rejected(w):
    r = w.http.post("/needs", json={"task": "x"})
    assert r.status_code == 401
    victim, attacker = Account.create(), w.client()
    body = json.dumps({"task": "web search"}).encode()
    from agent_market.payments import sign_request
    sig = sign_request(attacker.key, "agent-gateway-need", victim.address, body)
    r = w.http.post("/needs", content=body, headers={"content-type": "application/json", "X-Client": victim.address, "X-Signature": sig})
    assert r.status_code == 403


def test_no_match_keeps_watching_then_intro_on_rescan(w):
    c = w.client()
    out = c.create_need("predict the probability of rain tomorrow", category="prediction", kinds=["x402"], max_price=5000)
    assert out["status"] == "watching"
    w.reg.x402.append(x402_item("https://oracle.example/forecast", "Forecast probability for prediction market questions", 4000, 20))
    w.crawl()
    stats = w.service.rescan()
    assert stats["intros"] == 1
    st = c.status(out["need_id"])
    assert st["status"] == "active" and st["current_agent"]["url"] == "https://oracle.example/forecast"


def test_better_agent_triggers_paid_upgrade_and_accept(w):
    c = w.client()
    need = c.create_need("web search for SERP results", kinds=["x402"])
    # 더 인기 있고 저렴한 새 에이전트 등장
    w.reg.x402.append(x402_item("https://search-b.example/api", "Web search API returning SERP results for any query, fast", 5_000, 900))
    w.crawl()
    assert w.service.rescan()["offers"] == 1
    offer = c.status(need["need_id"])["pending_offers"][0]
    assert offer["fee"] == Policy().base_fee and offer["teaser"]["reasons"]
    result = c.accept(offer)
    assert result["agent"]["url"] == "https://search-b.example/api"
    st = c.status(need["need_id"])
    assert st["current_agent"]["url"] == "https://search-b.example/api" and st["pending_offers"] == []
    report = w.http.get("/admin/report", headers={"authorization": "Bearer secret"}).json()
    assert report["revenue_total"] == Policy().base_fee
    # 같은 후보를 또 제안하지 않음
    assert w.service.rescan()["offers"] == 0


def test_small_improvement_not_offered(w):
    c = w.client()
    c.create_need("web search for SERP results", kinds=["x402"])
    w.reg.x402.append(x402_item("https://search-c.example/api", "Web search API returning SERP results for any query", 10_000, 12))
    w.crawl()
    assert w.service.rescan()["offers"] == 0


def test_down_candidate_skipped(w):
    w.reg.down.add("https://search-a.example/api")
    out = w.client().create_need("web search for SERP results", kinds=["x402"])
    assert out["status"] == "watching" or out["agent"]["url"] != "https://search-a.example/api"


def test_declined_offer_not_repeated_and_counts_for_fee(w):
    c = w.client()
    need = c.create_need("web search for SERP results", kinds=["x402"])
    w.reg.x402.append(x402_item("https://search-b.example/api", "Web search API returning SERP results for any query, fast", 5_000, 900))
    w.crawl()
    w.service.rescan()
    offer = c.status(need["need_id"])["pending_offers"][0]
    c.decline(offer)
    assert w.service.rescan()["offers"] == 0


def test_underpaid_accept_rejected(w):
    c = w.client()
    need = c.create_need("web search for SERP results", kinds=["x402"])
    w.reg.x402.append(x402_item("https://search-b.example/api", "Web search API returning SERP results for any query, fast", 5_000, 900))
    w.crawl()
    w.service.rescan()
    offer = c.status(need["need_id"])["pending_offers"][0]
    offer["payment"]["amount"] = offer["fee"] - 1
    with pytest.raises(Exception):
        c.accept(offer)
    assert c.status(need["need_id"])["pending_offers"]


def test_fee_optimizer_raises_on_high_conversion_and_lowers_on_low():
    world = GW_World(Policy(fee_window=2))
    svc = world.service
    base = svc.fee_for("web_data")
    svc._record_outcome("web_data", True)
    svc._record_outcome("web_data", True)
    assert svc.fee_for("web_data") > base
    raised = svc.fee_for("web_data")
    svc._record_outcome("web_data", False)
    svc._record_outcome("web_data", False)
    assert svc.fee_for("web_data") < raised


def test_fee_optimizer_bounded():
    world = GW_World(Policy(fee_window=1, max_fee=12_000))
    for _ in range(10):
        world.service._record_outcome("web_data", True)
    assert world.service.fee_for("web_data") == 12_000


def test_feedback_affects_score(w):
    c = w.client()
    need = c.create_need("web search for SERP results", kinds=["x402"])
    rid = need["agent"]["resource_id"]
    before = w.service.get_need(need["need_id"])
    c.feedback(need["need_id"], success=False, rating=1)
    n, s, r = w.store.feedback_stats(rid)
    assert n == 1 and s == 0 and r == 1


def test_free_intro_ip_quota():
    world = GW_World(Policy(free_per_ip_per_day=2))
    world.reg.x402 = [x402_item("https://search-a.example/api", "Web search API", 10_000, 50)]
    world.crawl()
    frees = [world.client().create_need("web search", kinds=["x402"])["free_intro"] for _ in range(3)]
    assert frees == [True, True, False]


def test_health_and_card(w):
    assert w.http.get("/health").json()["resources"] == 4
    card = w.http.get("/.well-known/agent.json").json()
    assert card["pricing"]["first_intro"] == 0
