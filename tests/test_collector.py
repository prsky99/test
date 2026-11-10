import base64
import json
import time
from datetime import datetime, timezone

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
        if request.url.host in ("a2aregistry.org", "api.a2a-registry.org"):
            items = getattr(self, "a2a_items", [])
            return httpx.Response(200, json={"agents": items, "total": len(items)})
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
        "name": url, "description": "web search api", "category": "web_search", "networks": ["eip155:8453"],
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
    # down이어도 정상 주기(기본 6시간)로 계속 점검 예정
    assert 0.8 * checker.schedule.interval < r["next_check_at"] - time.time() < 1.2 * checker.schedule.interval
    assert rid not in [x["id"] for x in store.search("web search", "web_search", None, [], ["x402"])]
    net.responses["https://c.example/api"] = x402_ok
    state = checker.check_and_record(store.resource(rid))
    assert state["status"] == "healthy" and store.resource(rid)["failing_since"] is None
    assert rid in [x["id"] for x in store.search("web search", "web_search", None, [], ["x402"])]


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
    assert r["next_check_at"] is not None  # 스캐빈저 재점검(Phase 2: 7일 간격)을 위해 일정 설정됨
    assert rid not in [x["id"] for x in store.due_for_check(time.time() + 10 * 86400, 100)]
    assert rid not in [x["id"] for x in store.search("web search", "web_search", None, [], ["x402"])]


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
                   " VALUES ('n1','0x1','t','web_search','[]','[]','active',?,1,0,0)", (ids[0],))
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
    assert len(store.collector_stats()["recent_crawls"]) == 6


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
    interval = checker.schedule.interval
    assert checker.next_check_at(0, False, now, host_size=10) - now < 1.2 * interval
    big_size = int(interval / ((checker.per_host_delay + 0.5) * 1.2) * 1.8)
    big = checker.next_check_at(0, False, now, host_size=big_size) - now
    assert big > 1.2 * interval and big >= big_size * (checker.per_host_delay + 0.5) * 1.2 * 0.9  # 호스트 한 바퀴보다 길게
    assert checker.next_check_at(0, True, now, host_size=big_size) - now < 20 * 60  # 소개 중인 에이전트는 그대로 15분


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

    def __init__(self, x402_items, mcp_items, a2a_items=None):
        self.x402, self.mcp, self.a2a = x402_items, mcp_items, a2a_items or []
        self.x402_offsets, self.mcp_params, self.a2a_offsets = [], [], []

    def handle_request(self, request):
        q = dict(request.url.params)
        if request.url.host == "api.cdp.coinbase.com":
            off, lim = int(q["offset"]), int(q["limit"])
            self.x402_offsets.append(off)
            return httpx.Response(200, json={"items": self.x402[off:off + lim], "pagination": {"total": len(self.x402)}})
        if request.url.host in ("a2aregistry.org", "api.a2a-registry.org"):
            off = int(q.get("offset", 0))
            lim = int(q.get("limit", 100))
            self.a2a_offsets.append(off)
            page = self.a2a[off:off + lim]
            return httpx.Response(200, json={"agents": page, "total": len(self.a2a), "limit": lim, "offset": off})
        self.mcp_params.append(q)
        start = int(q.get("cursor", 0))
        page = self.mcp[start:start + 100]
        nxt = str(start + 100) if start + 100 < len(self.mcp) else None
        return httpx.Response(200, json={"servers": page, "metadata": {"nextCursor": nxt} if nxt else {}})


def mcp_item(i):
    return {"server": {"name": f"io.ex/s{i}", "title": f"s{i}", "description": "web search",
                       "remotes": [{"url": f"https://s{i}.example/mcp"}]}, "_meta": {}}


def a2a_item(i, ts=None):
    res = {
        "url": f"https://a2a{i}.example/agent",
        "name": f"a2a-agent-{i}",
        "description": "helpful a2a agent",
        "skills": [{"name": "search", "description": "web search"}],
    }
    if ts:
        res["created_at"] = ts
        res["updated_at"] = ts
    return res


def crawler_with(reg, **kw):
    store = Store()
    return store, Crawler(store, http=httpx.Client(transport=reg), page_delay=0, **kw)


def test_mcp_incremental_after_full_and_full_again_when_due():
    reg = PagedRegistries([], [mcp_item(i) for i in range(150)])
    store, crawler = crawler_with(reg, full_interval=3600)
    first = crawler.crawl_all()["mcp-registry"]
    assert first["mode"] == "full" and first["pages"] == 2 and first["new"] == 150
    assert all("updated_since" not in p and p["version"] == "latest" for p in reg.mcp_params)
    reg.mcp_params.clear()
    second = crawler.crawl_all()["mcp-registry"]
    assert second["mode"] == "incremental" and "updated_since" in reg.mcp_params[0]
    store.set_meta("crawl_last_full:mcp-registry", time.time() - 7200)  # 전체 수집 주기가 지남
    assert crawler.crawl_all()["mcp-registry"]["mode"] == "full"


def test_x402_bazaar_incremental_pass_and_early_stop():
    items = [x402_item(f"https://x{i}.example/api", "web search", 1000, 5) for i in range(500)]
    reg = PagedRegistries(items, [])
    store, crawler = crawler_with(reg, full_interval=3600, incremental_x402_max_pages=5)

    # First pass: full mode
    first = crawler.crawl_all()["x402-bazaar"]
    assert first["mode"] == "full" and first["seen"] == 500

    # Second pass within full_interval: incremental mode!
    reg.x402_offsets.clear()
    second = crawler.crawl_all()["x402-bazaar"]
    assert second["mode"] == "incremental"
    # Because all items are unchanged, it stops after 2 consecutive unchanged pages (200 items)
    assert second["pages"] == 2
    assert second["seen"] == 200
    assert second["unchanged"] == 200


def test_a2a_registry_incremental_pass_and_early_stop():
    items = [a2a_item(i) for i in range(500)]
    reg = PagedRegistries([], [], items)
    store, crawler = crawler_with(reg, full_interval=3600, incremental_a2a_max_pages=5)

    # First pass: full mode
    first = crawler.crawl_all()["a2a-registry"]
    assert first["mode"] == "full" and first["seen"] == 500 and first["new"] == 500

    # Second pass within full_interval: incremental mode
    reg.a2a_offsets.clear()
    second = crawler.crawl_all()["a2a-registry"]
    assert second["mode"] == "incremental"
    # Because all items are unchanged, it stops after 2 consecutive unchanged pages (200 items)
    assert second["pages"] == 2
    assert second["seen"] == 200
    assert second["unchanged"] == 200


def test_a2a_registry_incremental_early_stop_on_older_timestamp():
    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    old_ts = "2025-01-01T00:00:00Z"
    items = [a2a_item(i, now_ts if i < 50 else old_ts) for i in range(300)]
    reg = PagedRegistries([], [], items)
    store, crawler = crawler_with(reg, full_interval=3600, incremental_a2a_max_pages=5)

    first = crawler.crawl_all()["a2a-registry"]
    assert first["mode"] == "full" and first["seen"] == 300

    store.set_meta("crawl_last_start:a2a-registry", time.time())
    store.set_meta("crawl_last_full:a2a-registry", time.time())

    reg.a2a_offsets.clear()
    second = crawler.crawl_all()["a2a-registry"]
    assert second["mode"] == "incremental"
    # Stopped early once all items on page were older than since
    assert second["pages"] <= 2


def test_a2a_registry_fallback():
    class FallbackTransport(httpx.BaseTransport):
        def __init__(self):
            self.calls = []

        def handle_request(self, request):
            self.calls.append(request.url.host)
            if request.url.host == "a2aregistry.org":
                return httpx.Response(500, json={"error": "service unavailable"})
            if request.url.host == "api.a2a-registry.org":
                return httpx.Response(200, json={"agents": [a2a_item(1)], "total": 1})
            return httpx.Response(200, json={"items": [], "servers": [], "pagination": {"total": 0}})

    reg = FallbackTransport()
    store, crawler = crawler_with(reg)
    res = crawler._pass("a2a-registry", force_full=True)
    assert res["ok"] is True
    assert res["seen"] == 1
    assert "a2aregistry.org" in reg.calls
    assert "api.a2a-registry.org" in reg.calls


def test_crawler_respects_429_retry_after(monkeypatch):
    class RateLimited(httpx.BaseTransport):
        calls = 0

        def handle_request(self, request):
            self.calls += 1
            if self.calls == 1:
                return httpx.Response(429, headers={"Retry-After": "0.01"}, json={"error": "Rate limit"})
            return httpx.Response(200, json={"items": [], "pagination": {"total": 0}})

    reg = RateLimited()
    store, crawler = crawler_with(reg)
    slept = []
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))
    crawler._get("https://api.cdp.coinbase.com/platform/v2/x402/discovery/resources", {"limit": 100, "offset": 0})
    assert reg.calls == 2
    assert len(slept) == 1
    assert slept[0] >= 0.01



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


def test_due_selection_spreads_across_hosts_even_when_big_host_is_oldest(env):
    store, net, checker, _ = env
    big = [add(store, f"https://huge.example/api/{i}") for i in range(300)]
    small = [add(store, f"https://h{i}.example/api") for i in range(40)]
    with store.tx() as db:  # 큰 호스트 쪽이 훨씬 오래 기다린 상태
        db.executemany("UPDATE resources SET next_check_at=? WHERE id=?", [(1000.0, i) for i in big])
        db.executemany("UPDATE resources SET next_check_at=? WHERE id=?", [(time.time() - 60, i) for i in small])
    due = store.due_for_check(time.time(), 500, per_host=10)
    hosts = {r["host"] for r in due}
    assert len(due) == 50 and len(hosts) == 41  # 큰 호스트 10개 + 작은 호스트 40곳


def test_existing_rows_get_host_backfilled(tmp_path):
    path = str(tmp_path / "db.sqlite3")
    store = Store(path)
    rid = add(store, "https://backfill.example/x")
    with store.tx() as db:
        db.execute("UPDATE resources SET host=NULL")
    assert Store(path).resource(rid)["host"] == "backfill.example"


def test_crawler_retries_page_after_timeout():
    from agent_market.gateway.crawler import Crawler
    from agent_market.gateway.store import Store
    from tests.test_gateway import FakeRegistries

    class Flaky(FakeRegistries):
        timeouts = 2

        def handle_request(self, request):
            if request.url.host == "registry.modelcontextprotocol.io" and self.timeouts:
                self.timeouts -= 1
                raise httpx.ReadTimeout("The read operation timed out", request=request)
            return super().handle_request(request)

    reg = Flaky()
    reg.mcp = [{"server": {"name": "io.ex/w", "title": "W", "description": "Weather",
                           "remotes": [{"type": "streamable-http", "url": "https://w.example/mcp"}]}, "_meta": {}}]
    crawler = Crawler(Store(), http=httpx.Client(transport=reg), page_delay=0)
    crawler.retry_delay = 0
    report = crawler.crawl_all()
    assert report["mcp-registry"]["ok"] and report["mcp-registry"]["new"] == 1


def test_concurrent_health_batches_never_share_agents_or_hosts():
    import threading as th

    import httpx

    from agent_market.collector.health import HealthChecker
    from agent_market.gateway.store import Store

    started, release, seen = th.Event(), th.Event(), []

    class Slow(httpx.BaseTransport):
        def handle_request(self, request):
            seen.append(str(request.url))
            if request.url.host == "slow.example":
                started.set()
                release.wait(5)
            return httpx.Response(402, json={"x402Version": 1, "accepts": [{"scheme": "exact", "network": "base",
                                                                             "maxAmountRequired": "1000", "payTo": "0x" + "a" * 40,
                                                                             "asset": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"}]})

    store = Store()
    for host, n in (("slow.example", 3), ("fast.example", 3)):
        for i in range(n):
            store.upsert_resource({"key": f"x402:https://{host}/{i}", "source": "x402-bazaar", "kind": "x402", "url": f"https://{host}/{i}",
                                   "name": f"{host}/{i}", "description": "d", "category": "other", "networks": ["eip155:8453"],
                                   "price_usdc": 1000, "details": {}})
    checker = HealthChecker(store, http=httpx.Client(transport=Slow()), allow_private=True, per_host_delay=0)
    first = {}
    t = th.Thread(target=lambda: first.update(checker.run_due(limit=4)))
    t.start()
    assert started.wait(5)
    second = checker.run_due(limit=10)  # 첫 묶음이 slow.example을 붙잡고 있는 동안
    release.set()
    t.join(5)
    third = checker.run_due(limit=10)  # 첫 묶음이 끝나 호스트가 풀린 뒤 남은 것
    assert first["checked"] + second["checked"] + third["checked"] == 6  # 6개가 정확히 한 번씩 (겹침·누락 없음)
    assert sorted(seen) == sorted(set(seen))  # 같은 에이전트를 두 번 점검하지 않음
    assert checker.run_due(limit=10)["checked"] == 0  # 모두 다음 점검 시각으로 넘어감


# ---------------- 스캐빈저 및 재활성화 (Revival) 테스트 ----------------
def test_retired_agent_scheduled_with_tiered_backoff():
    store = Store()
    now = time.time()
    store.upsert_resource({
        "key": "x402:test-retired", "source": "x402-bazaar", "kind": "x402",
        "url": "https://api.example.com/test", "name": "Test", "description": "d",
        "category": "other", "networks": [], "price_usdc": 1000, "details": {}
    })
    rid = store.query("SELECT id FROM resources WHERE key='x402:test-retired'")[0]["id"]

    # 1) Phase 2 (8~30일차): 7일 간격 스케줄링
    with store.tx() as db:
        db.execute("UPDATE resources SET consecutive_failures=10, failing_since=? WHERE id=?",
                   (now - 10 * 86400, rid))
    res = store.record_health(rid, "fail", 500, 100, "server error", next_check_at=now + 60,
                              down_after=3, retire_after=7 * 86400)
    assert res["status"] == "retired"
    r = store.resource(rid)
    assert r["health_status"] == "retired"
    assert r["next_check_at"] is not None
    # 7일 ± 10% 지터 범위
    assert now + 6 * 86400 <= r["next_check_at"] <= now + 8 * 86400

    # 2) Phase 3 (31~90일차): 30일 간격 스케줄링
    with store.tx() as db:
        db.execute("UPDATE resources SET consecutive_failures=20, failing_since=? WHERE id=?",
                   (now - 40 * 86400, rid))
    store.record_health(rid, "fail", 500, 100, "server error", next_check_at=now + 60,
                        down_after=3, retire_after=7 * 86400)
    r = store.resource(rid)
    assert r["health_status"] == "retired"
    assert now + 26 * 86400 <= r["next_check_at"] <= now + 34 * 86400

    # 3) Phase 4 (90일 초과): None (영구 휴면)
    with store.tx() as db:
        db.execute("UPDATE resources SET consecutive_failures=50, failing_since=? WHERE id=?",
                   (now - 100 * 86400, rid))
    store.record_health(rid, "fail", 500, 100, "server error", next_check_at=now + 60,
                        down_after=3, retire_after=7 * 86400)
    r = store.resource(rid)
    assert r["health_status"] == "retired"
    assert r["next_check_at"] is None


def test_scavenger_probes_and_detects_revival(env, monkeypatch):
    monkeypatch.setenv("COLLECT_X402", "1")  # these fixtures are x402 resources
    store, net, checker, _ = env
    url = "https://api.example.com/revival-target"
    rid = add(store, url)
    now = time.time()

    # retired 상태로 설정하고 점검 시각 도래
    with store.tx() as db:
        db.execute("""UPDATE resources SET health_status='retired', consecutive_failures=15,
                      failing_since=?, next_check_at=? WHERE id=?""",
                   (now - 14 * 86400, now - 10, rid))

    # 엔드포인트가 살아남 (200 OK 또는 402 반환)
    net.responses[url] = x402_ok

    scav = checker.scavenge_retired(limit=10)
    assert scav["scavenged"] == 1
    assert scav["revived"] == 1
    assert scav["still_dead"] == 0

    r = store.resource(rid)
    assert r["health_status"] == "healthy"
    assert r["consecutive_failures"] == 0
    assert r["failing_since"] is None


def test_scavenger_still_dead_increments_and_delays(env, monkeypatch):
    monkeypatch.setenv("COLLECT_X402", "1")  # these fixtures are x402 resources
    store, net, checker, _ = env
    url = "https://api.example.com/dead-target"
    rid = add(store, url)
    now = time.time()

    with store.tx() as db:
        db.execute("""UPDATE resources SET health_status='retired', consecutive_failures=15,
                      failing_since=?, next_check_at=? WHERE id=?""",
                   (now - 14 * 86400, now - 10, rid))

    # 엔드포인트 여전히 500 에러
    net.responses[url] = lambda req: httpx.Response(500)

    scav = checker.scavenge_retired(limit=10)
    assert scav["scavenged"] == 1
    assert scav["revived"] == 0
    assert scav["still_dead"] == 1

    r = store.resource(rid)
    assert r["health_status"] == "retired"
    assert r["consecutive_failures"] == 16
    assert r["next_check_at"] > now + 6 * 86400


def test_crawler_metadata_preserves_local_retirement():
    store = Store()
    now = time.time()
    store.upsert_resource({
        "key": "x402:rediscover", "source": "x402-bazaar", "kind": "x402",
        "url": "https://api.example.com/v1", "name": "Old Name", "description": "Old Desc",
        "category": "other", "networks": [], "price_usdc": 1000, "details": {}
    })
    rid = store.query("SELECT id FROM resources WHERE key='x402:rediscover'")[0]["id"]

    # retired 상태로 만듦
    with store.tx() as db:
        db.execute("UPDATE resources SET health_status='retired', consecutive_failures=15, failing_since=?, next_check_at=NULL WHERE id=?",
                   (now - 14 * 86400, rid))

    # 크롤러가 새 버전(변경된 내용)을 수집함
    store.upsert_resource({
        "key": "x402:rediscover", "source": "x402-bazaar", "kind": "x402",
        "url": "https://api.example.com/v1", "name": "New Version 2.0", "description": "Updated Desc",
        "category": "other", "networks": [], "price_usdc": 2000, "details": {"v": 2}
    })

    r = store.resource(rid)
    # Registry metadata does not manufacture a recovery observation.
    assert r["health_status"] == "retired"
    assert r["consecutive_failures"] == 15
    assert r["next_check_at"] is None


def test_fts_orphan_rowid_conflict_resilience():
    """FTS5 테이블에 이미 동일한 rowid의 고아 레코드가 남아있어도 새 리소스 upsert 시 충돌 없이 정상 반영된다."""
    store = Store()
    # FTS5에 가상의 고아 행을 임의로 삽입 (예: rowid=1)
    with store.tx() as db:
        db.execute("INSERT INTO resources_fts(rowid, name, description) VALUES (1, 'Old Ghost Name', 'Old Ghost Description')")

    # 이제 새로운 리소스를 추가 (resources 테이블의 첫 rowid는 1이 됨)
    record = {
        "key": "mcp:ghost_test", "source": "mcp-registry", "kind": "mcp",
        "url": "https://mcp.ghost.example", "name": "New MCP Server",
        "description": "Ghost should be replaced cleanly", "category": "dev_tools",
    }
    counts = store.upsert_page([record])
    assert counts["new"] == 1

    # FTS 검색 결과가 'New MCP Server'로 조회되는지 확인
    res = store.search("Ghost replaced", "dev_tools", None, [], ["mcp"])
    assert len(res) == 1
    assert res[0]["name"] == "New MCP Server"


def test_store_init_sync_fts_orphans_and_missing(tmp_path):
    """Store 초기화 시 resources와 resources_fts 간의 고아 행 삭제 및 누락 행 색인 자동 동기화 검증."""
    db_path = str(tmp_path / "sync_test.sqlite3")
    store = Store(db_path)
    # 1. 정상 리소스 1개 등록
    store.upsert_resource({
        "key": "mcp:item1", "source": "mcp-registry", "kind": "mcp",
        "url": "https://item1.example", "name": "Item One", "description": "Desc One",
        "category": "dev_tools",
    })
    rid1 = store.query("SELECT id FROM resources WHERE key='mcp:item1'")[0]["id"]

    # 2. 수동으로 고아 행 생성 (resources에는 없으나 fts에만 존재)
    # 및 누락 행 생성 (resources에는 있으나 fts에서 삭제)
    store.upsert_resource({
        "key": "mcp:item2", "source": "mcp-registry", "kind": "mcp",
        "url": "https://item2.example", "name": "Item Two", "description": "Desc Two",
        "category": "dev_tools",
    })
    rid2 = store.query("SELECT id FROM resources WHERE key='mcp:item2'")[0]["id"]

    with store.tx() as db:
        # 고아 행: rowid=9999
        db.execute("INSERT INTO resources_fts(rowid, name, description) VALUES (9999, 'Orphan Name', 'Orphan Desc')")
        # 누락 행: rid2의 fts 색인 삭제
        db.execute("DELETE FROM resources_fts WHERE rowid=?", (rid2,))

    # 검증 전 상태 확인
    orphans_before = store.query("SELECT rowid FROM resources_fts WHERE rowid NOT IN (SELECT id FROM resources)")
    missing_before = store.query("SELECT id FROM resources WHERE id NOT IN (SELECT rowid FROM resources_fts)")
    assert len(orphans_before) == 1
    assert len(missing_before) == 1

    # Store 재초기화 시 자동 동기화(self._sync_fts_if_needed) 수행
    store2 = Store(db_path)
    orphans_after = store2.query("SELECT rowid FROM resources_fts WHERE rowid NOT IN (SELECT id FROM resources)")
    missing_after = store2.query("SELECT id FROM resources WHERE id NOT IN (SELECT rowid FROM resources_fts)")
    assert len(orphans_after) == 0
    assert len(missing_after) == 0

    # 복구된 rid2 검색 확인
    hits = store2.search("Item Two", "dev_tools", None, [], ["mcp"])
    assert any(h["id"] == rid2 for h in hits)


