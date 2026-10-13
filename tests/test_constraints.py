import json
import time

import httpx
import pytest
from eth_account import Account
from fastapi.testclient import TestClient

from agent_market.collector.capabilities import CapabilityProber
from agent_market.collector.health import HealthChecker
from agent_market.collector.server import create_app as create_collector
from agent_market.gateway import constraints as cons
from agent_market.gateway.store import Store
from tests.test_gateway import GW_World, x402_item


# ---------------- 추출 규칙 ----------------

@pytest.mark.parametrize("text,regions,lang", [
    ("Tribunal TRT11: Lookup Processual, official-source lookup", ["br"], None),
    ("Contact us for details about our search API", [], "en"),  # 'us'(우리)는 미국이 아님
    ("SEC EDGAR filings for US companies", ["us"], "en"),
    ("EU regulations from EUR-Lex", ["eu"], "en"),
    ("한국 공시 DART 조회", ["kr"], "ko"),
    ("Consulta de dados da empresa por CNPJ", ["br"], "pt"),
    ("Swiss weather from MeteoSwiss", ["ch"], "en"),
    ("Get user ID and MX records, P/E ratio via the PE field", [], "en"),  # 약어 오탐 없음
])
def test_text_extraction(text, regions, lang):
    assert cons.regions_in_text(text) == regions
    assert cons.detect_language(text) == lang


def test_declared_auth_and_normalizers():
    assert cons.declared_auth([{"headers": [{"name": "Authorization", "isRequired": True, "isSecret": True}]}]) is True
    assert cons.declared_auth([{"headers": [{"name": "X-Trace", "isRequired": False}]}]) is False
    assert cons.declared_auth([{"url": "https://x"}]) is None
    assert cons.normalize_language("en-US") == "en" and cons.normalize_language("Korean") == "ko"
    assert cons.normalize_language("klingon") is None
    assert cons.normalize_region("GB") == "gb" and cons.normalize_region("ES") == "eu" and cons.normalize_region("zz") is None


def test_from_tools_reads_enums_and_defaults():
    tools = [{"name": "search", "inputSchema": {"properties": {
        "language": {"type": "string", "enum": ["ko", "en-US"]},
        "country": {"type": "string", "enum": ["GB", "US"], "default": "US"},
        "vs_currency": {"type": "string", "default": "usd"},
        "query": {"type": "string"}}}}]
    caps = cons.from_tools(tools)
    assert caps["languages"] == ["en", "ko"] and caps["regions"] == ["gb", "us"] and caps["currencies"] == ["USD"]
    assert caps["tool_count"] == 1 and caps["tool_names"] == ["search"]


# ---------------- 수집·점검 ----------------

def mcp_resource(store, url, desc="web search tool", remotes=None):
    return store.upsert_resource({"key": f"mcp:{url}", "source": "mcp-registry", "kind": "mcp", "url": url, "name": url,
                                  "description": desc, "category": "web_search", "networks": [], "price_usdc": 0,
                                  "details": {"remotes": remotes or [{"type": "streamable-http", "url": url}]}})


def test_upsert_stores_text_constraints_and_declared_auth():
    store = Store()
    rid = mcp_resource(store, "https://br.example/mcp", "Consulta processual por CNPJ no Brasil",
                       remotes=[{"url": "https://br.example/mcp", "headers": [{"name": "Authorization", "isRequired": True, "isSecret": True}]}])
    r = store.resource(rid)
    assert r["regions"] == ",br," and r["desc_lang"] == "pt" and r["auth_declared"] == 1


def test_backfill_when_rules_change(tmp_path):
    path = str(tmp_path / "db.sqlite3")
    store = Store(path)
    rid = mcp_resource(store, "https://kr.example/mcp", "Korean DART disclosures for listed companies")
    with store.tx() as db:
        db.execute("UPDATE resources SET regions=NULL, desc_lang=NULL")
        db.execute("UPDATE meta SET value='0' WHERE key='constraints_version'")
    r = Store(path).resource(rid)
    assert r["regions"] == ",kr," and r["desc_lang"] == "en"


class FakeMCP(httpx.BaseTransport):
    """initialize → tools/list 를 SSE로 응답하는 가짜 MCP 서버들."""

    def __init__(self, tools_by_url, auth_urls=()):
        self.tools_by_url, self.auth_urls, self.calls = tools_by_url, set(auth_urls), []

    def handle_request(self, request):
        url = str(request.url)
        self.calls.append((request.method, url))
        if url in self.auth_urls:
            return httpx.Response(401)
        if request.method == "DELETE":
            return httpx.Response(204)
        body = json.loads(request.content or b"{}")
        if body.get("method") == "initialize":
            return httpx.Response(200, headers={"mcp-session-id": "s1"},
                                  json={"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-06-18", "capabilities": {}}})
        if body.get("method") == "tools/list":
            payload = json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"tools": self.tools_by_url[url]}})
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=f"event: message\ndata: {payload}\n\n")
        return httpx.Response(202)


def test_health_check_records_observed_auth():
    store = Store()
    ok = mcp_resource(store, "https://open.example/mcp")
    locked = mcp_resource(store, "https://locked.example/mcp")
    checker = HealthChecker(store, http=httpx.Client(transport=FakeMCP({}, auth_urls=["https://locked.example/mcp"])), allow_private=True)
    checker.check_and_record(store.resource(ok))
    checker.check_and_record(store.resource(locked))
    assert store.resource(ok)["auth_observed"] == 0 and store.resource(locked)["auth_observed"] == 1


def test_capability_prober_records_tool_parameters():
    store = Store()
    rid = mcp_resource(store, "https://ko.example/mcp")
    with store.tx() as db:
        db.execute("UPDATE resources SET health_status='healthy' WHERE id=?", (rid,))
    tools = [{"name": "news", "inputSchema": {"properties": {"lang": {"enum": ["ko", "en"]}, "country": {"default": "KR"}}}}]
    net = FakeMCP({"https://ko.example/mcp": tools})
    prober = CapabilityProber(store, http=httpx.Client(transport=net), allow_private=True, per_host_delay=0)
    stats = prober.run_due()
    r = store.resource(rid)
    assert stats["ok"] == 1 and r["cap_languages"] == ",en,ko," and r["cap_regions"] == ",kr," and r["cap_tool_count"] == 1
    assert ("DELETE", "https://ko.example/mcp") in net.calls  # 점검 세션 정리
    assert prober.run_due()["checked"] == 0  # 하루 안에는 다시 조사하지 않음
    assert len(store.due_for_capability(time.time() + 2 * 86400, 86400, 10)) == 1


# ---------------- 게이트웨이 조건 ----------------

@pytest.fixture
def world():
    w = GW_World()
    w.reg.x402 = [
        x402_item("https://global.example/api", "Company news search API", 5_000, 100),
        x402_item("https://br.example/api", "Company news search API for Brazil (CNPJ)", 5_000, 100),
        x402_item("https://kr.example/api", "Company news search API for Korea (DART)", 5_000, 100),
    ]
    w.reg.mcp = [
        {"server": {"name": "io.ex/locked", "title": "Locked news", "description": "Company news search",
                    "remotes": [{"type": "streamable-http", "url": "https://locked.example/mcp",
                                 "headers": [{"name": "Authorization", "isRequired": True, "isSecret": True}]}]}, "_meta": {}},
        {"server": {"name": "io.ex/open", "title": "Open news", "description": "Company news search",
                    "remotes": [{"type": "streamable-http", "url": "https://open.example/mcp"}]}, "_meta": {}},
    ]
    w.crawl()
    return w


def intro_url(world, **opts):
    out = world.client().create_need("company news search", **opts)
    return out["agent"]["url"] if out["status"] == "active" else None


def test_region_excludes_other_country_agents(world):
    store = world.store
    ids = {r["url"]: r["id"] for r in store.query("SELECT id, url FROM resources")}
    cands = {r["url"] for r in store.search("company news search", "web_search", None, [], ["x402"], region="kr")}
    assert "https://br.example/api" not in cands and {"https://global.example/api", "https://kr.example/api"} <= cands
    assert intro_url(world, region="kr", kinds=["x402"]) == "https://kr.example/api"
    assert ids


def test_auth_none_excludes_agents_that_need_accounts(world):
    urls = {r["url"] for r in world.store.search("company news search", "web_search", None, [], ["mcp"], auth_free=True)}
    assert urls == {"https://open.example/mcp"}
    out = world.client().create_need("company news search", kinds=["mcp"], auth="none")
    # 헤더 선언도 헬스체크도 없으면 '모름'(None)이고, 인증 필요로 확인된 것만 제외된다
    assert out["agent"]["url"] == "https://open.example/mcp" and out["agent"]["constraints"]["auth_required"] is not True


def test_language_preference_boosts_supporting_agent(world):
    with world.store.tx() as db:
        db.execute("UPDATE resources SET cap_languages=',ko,en,' WHERE url='https://global.example/api'")
        db.execute("UPDATE resources SET regions=NULL WHERE url IN ('https://br.example/api','https://kr.example/api')")
        db.execute("UPDATE resources SET active=0 WHERE url IN ('https://br.example/api','https://kr.example/api')")
        db.execute("UPDATE resources SET active=1, url='https://other.example/api', host='other.example' WHERE url='https://br.example/api'")
    out = world.client().create_need("company news search", kinds=["x402"], language="ko")
    assert out["agent"]["url"] == "https://global.example/api"
    assert "ko" in out["agent"]["constraints"]["languages"] and out["conditions"]["language"] == "ko"


def test_invalid_conditions_rejected(world):
    c = world.client()
    for bad in ({"language": "klingon"}, {"region": "atlantis"}, {"auth": "maybe"}):
        with pytest.raises(httpx.HTTPStatusError):
            c.create_need("company news search", **bad)


def test_collector_api_filters_and_stats(world):
    app = create_collector(world.store, None, None, run_background=False)
    client = TestClient(app)
    kr = client.get("/agents", params={"region": "kr"}).json()
    assert [a["url"] for a in kr] == ["https://kr.example/api"] and kr[0]["constraints"]["regions"] == ["kr"]
    open_only = client.get("/agents", params={"kind": "mcp", "auth": "none"}).json()
    assert [a["url"] for a in open_only] == ["https://open.example/mcp"]
    stats = client.get("/stats").json()["constraints"]
    assert stats["auth_required"] == 1 and stats["region_specific"] == 2


def test_need_conditions_survive_in_rescan(world):
    c = world.client(Account.create())
    need = c.create_need("company news search", kinds=["x402"], region="kr")
    world.reg.x402.append(x402_item("https://br2.example/api", "Company news search API for Brazil, fastest", 1_000, 5000))
    world.crawl()
    world.service.rescan()
    assert c.status(need["need_id"])["pending_offers"] == []  # 브라질 전용은 한국 요청에 재소개하지 않음
