import base64
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from agent_market.collector.agent import CollectorAgent
from agent_market.collector.health import HealthChecker, parse_payment_required
from agent_market.collector.server import create_app
from agent_market.gateway.crawler import Crawler
from agent_market.gateway.store import Store
from tests.test_gateway import BASE_USDC, x402_item

ACCEPTS = [{"scheme": "exact", "network": "eip155:8453", "amount": "7000", "asset": BASE_USDC, "payTo": "0x" + "cd" * 20}]


class Endpoints(httpx.BaseTransport):
    """URL별로 정해 둔 응답을 돌려주는 가짜 인터넷."""

    def __init__(self):
        self.responses = {}
        self.calls = []
        self.registry_items = []

    def handle_request(self, request):
        url = str(request.url).split("?")[0]
        self.calls.append((request.method, url, dict(request.headers)))
        if request.url.host == "api.cdp.coinbase.com":
            return httpx.Response(200, json={"items": self.registry_items, "pagination": {"total": len(self.registry_items)}})
        if request.url.host == "registry.modelcontextprotocol.io":
            return httpx.Response(200, json={"servers": [], "metadata": {}})
        fn = self.responses.get(url)
        if fn is None:
            return httpx.Response(404)
        return fn(request)


@pytest.fixture
def env():
    store = Store()
    net = Endpoints()
    http = httpx.Client(transport=net)
    checker = HealthChecker(store, http=http, allow_private=True, workers=4, per_host_delay=0)
    crawler = Crawler(store, http=http, page_delay=0)
    agent = CollectorAgent(store, crawler, checker)
    return store, net, checker, agent


def add(store, url, kind="x402", method="GET", price=5000):
    return store.upsert_resource({
        "key": f"{kind}:{url}", "source": "x402-bazaar" if kind == "x402" else "mcp-registry", "kind": kind, "url": url,
        "name": url, "description": "web search api", "category": "web_data", "networks": ["eip155:8453"],
        "price_usdc": price, "pay_to": "0x" + "ab" * 20, "method": method, "details": {},
    })


def x402_ok(request):
    return httpx.Response(402, json={"x402Version": 1, "accepts": ACCEPTS})


def test_parse_payment_required_body_and_header():
    r = httpx.Response(402, json={"accepts": ACCEPTS})
    assert parse_payment_required(r, r.content) == ACCEPTS
    header = base64.b64encode(json.dumps({"x402Version": 2, "accepts": ACCEPTS}).encode()).decode()
    r2 = httpx.Response(402, headers={"PAYMENT-REQUIRED": header}, content=b"")
    assert parse_payment_required(r2, b"") == ACCEPTS
    assert parse_payment_required(httpx.Response(402, json={"x": 1}), b'{"x":1}') is None


def test_valid_x402_is_healthy_and_price_updates(env):
    store, net, checker, _ = env
    rid = add(store, "https://a.example/api")
    net.responses["https://a.example/api"] = x402_ok
    state = checker.check_and_record(store.resource(rid))
    r = store.resource(rid)
    assert state["status"] == "healthy" and state["price_changed"]
    assert r["price_usdc"] == 7000 and r["health_n_24h"] == 1 and r["last_ok_at"]


def test_post_endpoint_checked_with_post(env):
    store, net, checker, _ = env
    rid = add(store, "https://p.example/api", method="POST")
    net.responses["https://p.example/api"] = x402_ok
    checker.check_and_record(store.resource(rid))
    assert net.calls[-1][0] == "POST"


def test_402_without_terms_is_reachable(env):
    store, net, checker, _ = env
    rid = add(store, "https://b.example/api")
    net.responses["https://b.example/api"] = lambda r: httpx.Response(402, text="pay me")
    assert checker.check_and_record(store.resource(rid))["status"] == "reachable"


def test_down_after_three_failures_still_checked_and_recovers(env):
    store, net, checker, _ = env
    rid = add(store, "https://c.example/api")
    net.responses["https://c.example/api"] = lambda r: httpx.Response(503)
    statuses = [checker.check_and_record(store.resource(rid))["status"] for _ in range(3)]
    assert statuses == ["failing", "failing", "down"]
    r = store.resource(rid)
    # down이어도 정상 주기(1시간)로 계속 점검 예정
    assert 0.8 * 3600 < r["next_check_at"] - time.time() < 1.2 * 3600
    assert rid not in [x["id"] for x in store.search("web search", "web_data", None, [], ["x402"])]
    net.responses["https://c.example/api"] = x402_ok
    state = checker.check_and_record(store.resource(rid))
    assert state["status"] == "healthy" and store.resource(rid)["failing_since"] is None
    assert rid in [x["id"] for x in store.search("web search", "web_data", None, [], ["x402"])]


def test_down_over_a_week_is_retired_and_excluded(env):
    store, net, checker, _ = env
    rid = add(store, "https://d.example/api")
    net.responses["https://d.example/api"] = lambda r: httpx.Response(500)
    for _ in range(3):
        checker.check_and_record(store.resource(rid))
    assert store.resource(rid)["health_status"] == "down"
    with store.tx() as db:
        db.execute("UPDATE resources SET failing_since=? WHERE id=?", (time.time() - 8 * 86400, rid))
    assert checker.check_and_record(store.resource(rid))["status"] == "retired"
    r = store.resource(rid)
    assert r["next_check_at"] is None
    assert rid not in [x["id"] for x in store.due_for_check(time.time() + 10 * 86400, 100)]
    assert rid not in [x["id"] for x in store.search("web search", "web_data", None, [], ["x402"])]


def test_down_less_than_a_week_not_retired(env):
    store, net, checker, _ = env
    rid = add(store, "https://e.example/api")
    net.responses["https://e.example/api"] = lambda r: httpx.Response(500)
    for _ in range(3):
        checker.check_and_record(store.resource(rid))
    with store.tx() as db:
        db.execute("UPDATE resources SET failing_since=? WHERE id=?", (time.time() - 6 * 86400, rid))
    assert checker.check_and_record(store.resource(rid))["status"] == "down"


def test_url_change_revives_retired_agent(env):
    store, net, checker, _ = env
    rid = add(store, "https://f.example/api")
    with store.tx() as db:
        db.execute("UPDATE resources SET health_status='retired', next_check_at=NULL WHERE id=?", (rid,))
    store.upsert_resource({**store.resource(rid), "url": "https://f2.example/api", "networks": ["eip155:8453"], "details": {}})
    r = store.resource(rid)
    assert r["health_status"] == "unknown" and rid in [x["id"] for x in store.due_for_check(time.time(), 10)]


def test_mcp_initialize_and_session_cleanup(env):
    store, net, checker, _ = env
    rid = add(store, "https://m.example/mcp", kind="mcp")
    net.responses["https://m.example/mcp"] = lambda r: (
        httpx.Response(200, headers={"mcp-session-id": "s1"}, json={"jsonrpc": "2.0", "id": 1, "result": {"capabilities": {}}})
        if r.method == "POST" else httpx.Response(204)
    )
    assert checker.check_and_record(store.resource(rid))["status"] == "healthy"
    assert net.calls[-1][0] == "DELETE" and net.calls[-1][2]["mcp-session-id"] == "s1"
    rid2 = add(store, "https://m2.example/mcp", kind="mcp")
    net.responses["https://m2.example/mcp"] = lambda r: httpx.Response(401)
    assert checker.check_and_record(store.resource(rid2))["status"] == "reachable"


def test_private_addresses_blocked():
    store = Store()
    rid = add(store, "http://127.0.0.1:9/api")
    checker = HealthChecker(store, http=httpx.Client(transport=Endpoints()), allow_private=False)
    result = checker.check(store.resource(rid))
    assert result.outcome == "fail" and "blocked" in result.error


def test_run_due_checks_new_first_and_schedules_in_use_sooner(env):
    store, net, checker, _ = env
    ids = [add(store, f"https://h{i}.example/api") for i in range(5)]
    for i in ids:
        net.responses[store.resource(i)["url"]] = x402_ok
    with store.tx() as db:  # 첫 번째 에이전트를 고객에게 소개된 상태로
        db.execute("INSERT INTO needs (need_id, client, task, category, networks, kinds, status, current_resource, free_used, created, updated)"
                   " VALUES ('n1','0x1','t','web_data','[]','[]','active',?,1,0,0)", (ids[0],))
    stats = checker.run_due(100)
    assert stats["checked"] == 5 and stats["healthy"] == 5
    assert store.due_for_check(time.time(), 100) == []
    in_use_next = store.resource(ids[0])["next_check_at"] - time.time()
    other_next = store.resource(ids[1])["next_check_at"] - time.time()
    assert in_use_next < 20 * 60 < 50 * 60 < other_next


def test_crawl_records_new_agents(env):
    store, net, _, agent = env
    net.registry_items = [x402_item("https://n1.example/api", "web search", 1000, 5), x402_item("https://n2.example/api", "web search", 1000, 5)]
    report = agent.crawler.crawl_all()
    assert report["x402-bazaar"]["new"] == 2
    net.registry_items.append(x402_item("https://n3.example/api", "web search", 1000, 5))
    second = agent.crawler.crawl_all()["x402-bazaar"]
    assert second["new"] == 1 and second["unchanged"] == 2  # 바뀌지 않은 2개는 다시 쓰지 않음
    assert len(store.collector_stats()["recent_crawls"]) == 4


def test_collector_api(env):
    store, net, checker, agent = env
    good = add(store, "https://g.example/api")
    gone = add(store, "https://x.example/api")
    net.responses["https://g.example/api"] = x402_ok
    with store.tx() as db:
        db.execute("UPDATE resources SET health_status='retired' WHERE id=?", (gone,))
    checker.run_due(10)
    client = TestClient(create_app(store, agent, "secret", run_background=False))
    listed = client.get("/agents", params={"q": "web search"}).json()
    assert [a["id"] for a in listed] == [good] and listed[0]["uptime_24h"] == 1.0
    assert [a["id"] for a in client.get("/agents", params={"status": "retired"}).json()] == [gone]
    detail = client.get(f"/agents/{good}").json()
    assert detail["health_status"] == "healthy" and detail["history"][0]["outcome"] == "healthy"
    stats = client.get("/stats").json()
    assert stats["by_health"]["healthy"] == 1 and stats["checks_last_hour"]["total"] >= 1
    assert client.post(f"/admin/check/{good}").status_code == 401
    assert client.post(f"/admin/check/{good}", headers={"authorization": "Bearer secret"}).json()["status"] == "healthy"


def test_batch_caps_endpoints_per_host(env):
    store, net, checker, _ = env
    for i in range(30):
        rid = add(store, f"https://big.example/api/{i}")
        net.responses[store.resource(rid)["url"]] = x402_ok
    for i in range(5):
        rid = add(store, f"https://small{i}.example/api")
        net.responses[store.resource(rid)["url"]] = x402_ok
    stats = checker.run_due(100)
    assert stats["checked"] == checker.per_host_cap + 5  # 큰 호스트는 이번 묶음에 10개만
    assert len(store.due_for_check(time.time(), 100)) == 30 - checker.per_host_cap


def test_interval_stretches_for_hosts_with_many_endpoints(env):
    _, _, checker, _ = env
    now = time.time()
    assert checker.next_check_at(0, False, now, host_size=10) - now < 1.2 * 3600
    big = checker.next_check_at(0, False, now, host_size=8000) - now
    assert big > 1.2 * 3600 and big >= 8000 * (checker.per_host_delay + 0.5) * 1.2 * 0.9  # 호스트 한 바퀴보다 길게
    assert checker.next_check_at(0, True, now, host_size=8000) - now < 20 * 60  # 소개 중인 에이전트는 그대로 15분


def test_templated_urls_skipped_and_bad_urls_recorded(env):
    from agent_market.gateway.crawler import parse_mcp_item

    item = {"server": {"name": "t", "remotes": [{"url": "https://{tenant}.x.ai/mcp"}, {"url": "https://ok.x.ai/mcp"}]}, "_meta": {}}
    assert parse_mcp_item(item)["url"] == "https://ok.x.ai/mcp"
    only_template = {"server": {"name": "t2", "remotes": [{"url": "https://{HOST}:{PORT}/mcp"}]}, "_meta": {}}
    assert parse_mcp_item(only_template) is None
    store, _, checker, _ = env
    rid = add(store, "https://exa mple.com:99999/x")  # 잘못된 URL도 점검이 멈추지 않고 실패로 기록
    assert checker.check_and_record(store.resource(rid))["status"] == "failing"


def test_mass_failure_treated_as_local_problem(env):
    store, net, checker, _ = env
    ids = [add(store, f"https://m{i}.example/api") for i in range(25)]
    for i in ids:  # 모든 호스트가 동시에 실패 = 우리 쪽 네트워크 문제로 판단
        net.responses[store.resource(i)["url"]] = lambda r: (_ for _ in ()).throw(httpx.ConnectTimeout("boom"))
    stats = checker.run_due(100)
    assert stats["local_network_problem"] and stats["postponed"] == 25
    assert all(store.resource(i)["consecutive_failures"] == 0 for i in ids)
    assert store.query("SELECT COUNT(*) AS n FROM health_checks")[0]["n"] == 0
    assert store.due_for_check(time.time(), 100) == []  # 5분 뒤 재점검
    assert len(store.due_for_check(time.time() + 400, 100)) == 25


def test_pool_timeout_not_recorded_as_agent_failure(env):
    store, net, checker, _ = env
    rid = add(store, "https://pool.example/api")
    net.responses["https://pool.example/api"] = lambda r: (_ for _ in ()).throw(httpx.PoolTimeout("pool"))
    state = checker.check_and_record(store.resource(rid))
    assert state["postponed"] and store.resource(rid)["consecutive_failures"] == 0


def test_partial_failures_still_recorded(env):
    store, net, checker, _ = env
    ids = [add(store, f"https://p{i}.example/api") for i in range(25)]
    for n, i in enumerate(ids):
        net.responses[store.resource(i)["url"]] = (lambda r: httpx.Response(503)) if n < 5 else x402_ok
    stats = checker.run_due(100)
    assert not stats["local_network_problem"] and stats["failing"] == 5 and stats["healthy"] == 20



# ---------------- 연속·증분·이어서 수집 ----------------

class PagedRegistries(httpx.BaseTransport):
    """페이지 단위로 응답하고 받은 파라미터를 기록하는 가짜 레지스트리."""

    def __init__(self, x402_items, mcp_items):
        self.x402, self.mcp = x402_items, mcp_items
        self.x402_offsets, self.mcp_params = [], []

    def handle_request(self, request):
        q = dict(request.url.params)
        if request.url.host == "api.cdp.coinbase.com":
            off, lim = int(q["offset"]), int(q["limit"])
            self.x402_offsets.append(off)
            return httpx.Response(200, json={"items": self.x402[off:off + lim], "pagination": {"total": len(self.x402)}})
        self.mcp_params.append(q)
        start = int(q.get("cursor", 0))
        page = self.mcp[start:start + 100]
        nxt = str(start + 100) if start + 100 < len(self.mcp) else None
        return httpx.Response(200, json={"servers": page, "metadata": {"nextCursor": nxt} if nxt else {}})


def mcp_item(i):
    return {"server": {"name": f"io.ex/s{i}", "title": f"s{i}", "description": "web search",
                       "remotes": [{"url": f"https://s{i}.example/mcp"}]}, "_meta": {}}


def crawler_with(reg, **kw):
    store = Store()
    return store, Crawler(store, http=httpx.Client(transport=reg), page_delay=0, **kw)


def test_mcp_incremental_after_full_and_full_again_when_due():
    reg = PagedRegistries([], [mcp_item(i) for i in range(150)])
    store, crawler = crawler_with(reg, full_interval=3600)
    first = crawler.crawl_all()["mcp-registry"]
    assert first["mode"] == "full" and first["pages"] == 2 and first["new"] == 150
    assert all("updated_since" not in p for p in reg.mcp_params)
    reg.mcp_params.clear()
    second = crawler.crawl_all()["mcp-registry"]
    assert second["mode"] == "incremental" and "updated_since" in reg.mcp_params[0]
    store.set_meta("crawl_last_full:mcp-registry", time.time() - 7200)  # 전체 수집 주기가 지남
    assert crawler.crawl_all()["mcp-registry"]["mode"] == "full"


def test_crawl_resumes_from_saved_position():
    reg = PagedRegistries([x402_item(f"https://r{i}.example/api", "web search", 1000, 5) for i in range(350)], [])
    store, crawler = crawler_with(reg)
    pages = {"n": 0}

    def stop_after_two_pages():
        pages["n"] += 1
        return pages["n"] >= 2

    crawler.should_stop = stop_after_two_pages
    report = crawler.crawl_all()["x402-bazaar"]
    assert report["interrupted"] and report["pages"] == 2
    crawler.should_stop = lambda: False
    reg.x402_offsets.clear()
    resumed = crawler.crawl_all()["x402-bazaar"]
    assert resumed["resumed"] and reg.x402_offsets[0] == 200  # 처음이 아니라 3번째 페이지부터
    assert resumed["seen"] == 350 and store.get_meta("crawl_pass:x402-bazaar") is None


def test_concurrent_crawl_is_rejected():
    reg = PagedRegistries([], [])
    _, crawler = crawler_with(reg)
    crawler._lock.acquire()
    assert crawler.crawl_all() == {"busy": True}
    crawler._lock.release()


def test_collector_crawls_continuously():
    reg = PagedRegistries([x402_item("https://c1.example/api", "web search", 1000, 5)], [mcp_item(1)])
    store, crawler = crawler_with(reg)
    checker = HealthChecker(store, http=httpx.Client(transport=Endpoints()), allow_private=True)
    agent = CollectorAgent(store, crawler, checker, min_gap=0.05)
    agent.start()
    deadline = time.time() + 5
    while time.time() < deadline and store.query("SELECT COUNT(*) AS n FROM crawl_runs WHERE source='x402-bazaar'")[0]["n"] < 3:
        time.sleep(0.05)
    agent.stop()
    assert store.query("SELECT COUNT(*) AS n FROM crawl_runs WHERE source='x402-bazaar'")[0]["n"] >= 3  # 끝나면 바로 다시 시작
