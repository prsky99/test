import logging
import time

import pytest
from fastapi.testclient import TestClient

from agent_market.config import GatewayConfig
from agent_market.gateway.server import create_app
from agent_market.gateway.store import Store
from tests.test_gateway import GW, NET, populated

H = {"X-Dashboard": "1", "authorization": "Bearer secret"}


@pytest.fixture
def dash():
    world = populated()
    return world, TestClient(world.app)


def local_app():
    """ADMIN_TOKEN이 없는 게이트웨이 (로컬 실행 기본값)."""
    config = GatewayConfig(NET, None, ":memory:", None, 1, 3600, 900, False, True)
    return create_app(config, store=Store())


def test_page_is_served_with_strict_headers(dash):
    _, c = dash
    r = c.get("/admin/ui")
    assert r.status_code == 200 and "수집 관리" in r.text
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"] and r.headers["x-frame-options"] == "DENY"


def test_api_needs_dashboard_header_and_token(dash):
    _, c = dash
    assert c.get("/admin/api/overview", headers={"authorization": "Bearer secret"}).status_code == 403  # CSRF 방지 헤더 없음
    assert c.get("/admin/api/overview", headers={"X-Dashboard": "1"}).status_code == 401
    assert c.get("/admin/api/overview", headers={"X-Dashboard": "1", "authorization": "Bearer wrong"}).status_code == 401
    assert c.get("/admin/api/overview", headers=H).status_code == 200


def test_without_token_only_local_browser_is_allowed():
    app = local_app()
    local = TestClient(app, base_url="http://localhost:8200", client=("127.0.0.1", 50000))
    assert local.get("/admin/api/session", headers={"X-Dashboard": "1"}).json() == {"ok": True, "token_required": False}
    remote = TestClient(app, base_url="http://localhost:8200", client=("203.0.113.5", 50000))
    assert remote.get("/admin/api/session", headers={"X-Dashboard": "1"}).status_code == 401
    rebind = TestClient(app, base_url="http://evil.example:8200", client=("127.0.0.1", 50000))  # DNS rebinding
    assert rebind.get("/admin/api/session", headers={"X-Dashboard": "1"}).status_code == 401
    assert local.get("/admin/api/session").status_code == 403


def test_overview_reports_counts_and_progress(dash):
    world, c = dash
    ov = c.get("/admin/api/overview", headers=H).json()
    assert sum(r["n"] for r in ov["resources"] if r["active"]) == 4
    assert {r["kind"] for r in ov["resources"]} == {"x402", "mcp"}
    assert ov["health"]["never_checked"] == 4 and ov["policy"] == "free"
    assert ov["crawl"]["runs"] and ov["crawl"]["last"]["report"]
    assert ov["collector"]["paused"] is False


def test_agents_list_detail_and_activation(dash):
    world, c = dash
    page = c.get("/admin/api/agents", params={"kind": "x402", "sort": "name"}, headers=H).json()
    assert page["total"] == 3 and [a["kind"] for a in page["items"]] == ["x402"] * 3
    rid = page["items"][0]["id"]
    world.service.prober.checker.check_and_record(world.store.resource(rid))
    detail = c.get(f"/admin/api/agents/{rid}", headers=H).json()
    assert detail["agent"]["id"] == rid and len(detail["history"]) == 1 and isinstance(detail["agent"]["details"], dict)
    assert c.post(f"/admin/api/agents/{rid}/deactivate", headers=H).json() == {"active": False}
    assert c.get("/admin/api/agents", params={"kind": "x402"}, headers=H).json()["total"] == 2
    assert c.get("/admin/api/agents", params={"kind": "x402", "active": "all"}, headers=H).json()["total"] == 3
    c.post(f"/admin/api/agents/{rid}/activate", headers=H)
    r = world.store.resource(rid)
    assert r["active"] == 1 and r["health_status"] == "unknown" and r["next_check_at"] is None
    assert c.get("/admin/api/agents/999999", headers=H).status_code == 404


def test_errors_group_failures_and_capture_logs(dash):
    world, c = dash
    world.reg.down.add("https://img.example/gen")
    rid = world.store.query("SELECT id FROM resources WHERE url='https://img.example/gen'")[0]["id"]
    world.service.prober.checker.check_and_record(world.store.resource(rid))
    logging.getLogger("agent_market.collector").error("erc8004 resolve failed")
    e = c.get("/admin/api/errors", headers=H).json()
    assert e["health"][0]["n"] == 1 and e["health"][0]["sample_url"] == "https://img.example/gen"
    assert any(l["message"] == "erc8004 resolve failed" for l in e["logs"])
    c.post("/admin/api/logs/clear", headers=H)
    assert c.get("/admin/api/errors", headers=H).json()["logs"] == []


def test_timeseries_buckets_checks(dash):
    world, c = dash
    for r in world.store.query("SELECT * FROM resources"):
        world.service.prober.checker.check_and_record(dict(r))
    ts = c.get("/admin/api/timeseries", params={"hours": 6}, headers=H).json()
    assert ts["bucket_seconds"] == 300 and sum(p["healthy"] + p["reachable"] + p["fail"] for p in ts["points"]) == 4


def test_erc8004_retry_requeues_failed(dash):
    world, c = dash
    with world.store.tx() as db:
        db.execute("""INSERT INTO erc8004_tokens (chain, agent_id, uri, host, status, next_at, error)
                      VALUES ('base', 1, 'https://r.example/1.json', 'r.example', 'error', 9e9, 'HTTP 502')""")
    assert c.post("/admin/api/actions/erc8004-retry", headers=H).json() == {"requeued": 1}
    row = world.store.query("SELECT status, next_at, error FROM erc8004_tokens")[0]
    assert (row["status"], row["next_at"], row["error"]) == ("pending", None, None)


def test_pause_resume_and_background_crawl(dash):
    world, c = dash
    assert c.post("/admin/api/actions/pause", headers=H).json() == {"paused": True}
    assert c.get("/admin/api/overview", headers=H).json()["collector"]["paused"] is True
    c.post("/admin/api/actions/resume", headers=H)
    assert c.post("/admin/api/actions/crawl", headers=H).json() == {"started": True}
    deadline = time.time() + 5
    while time.time() < deadline:
        state = c.get("/admin/api/overview", headers=H).json()["actions"].get("crawl", {})
        if state and not state.get("running"):
            break
        time.sleep(0.05)
    assert state.get("result", {}).get("x402-bazaar", {}).get("ok") is True


def test_paused_collector_stops_crawler():
    world = populated()
    collector = world.app.state.collector
    assert collector.crawler.should_stop() is False
    collector.pause()
    assert collector.crawler.should_stop() is True
    collector.resume()
    assert collector.crawler.should_stop() is False


def test_insights_stats_and_featured(dash):
    world, c = dash
    for r in world.store.query("SELECT * FROM resources"):
        world.service.prober.checker.check_and_record(dict(r))
    ins = c.get("/admin/api/insights", headers=H).json()
    x = ins["kinds"]["x402"]
    assert x["stats"]["total"] == 3 and x["stats"]["min_price"] == 3_000 and x["stats"]["median_price"] == 10_000
    most_paid = next(f for f in x["featured"] if f["key"] == "most_paid")
    assert most_paid["items"][0]["url"] == "https://chain.example/balance"  # 30일 결제자 800명
    assert ins["kinds"]["mcp"]["stats"]["total"] == 1 and ins["categories"]["web_search"]


def test_explore_full_text_and_filters(dash):
    world, c = dash
    for r in world.store.query("SELECT * FROM resources"):
        world.service.prober.checker.check_and_record(dict(r))
    hits = c.get("/admin/api/explore", params={"q": "image prompt"}, headers=H).json()
    assert hits["items"][0]["url"] == "https://img.example/gen"
    assert {r["kind"] for r in c.get("/admin/api/explore", params={"kind": "mcp"}, headers=H).json()["items"]} == {"mcp"}
    world.reg.down.add("https://img.example/gen")  # 서비스 불가가 되면 탐색 결과에서 빠짐
    rid = world.store.query("SELECT id FROM resources WHERE url='https://img.example/gen'")[0]["id"]
    world.service.prober.checker.check_and_record(world.store.resource(rid))
    assert all(r["id"] != rid for r in c.get("/admin/api/explore", params={"q": "image prompt"}, headers=H).json()["items"])


def test_visitors_admin_api(dash):
    world, c = dash
    from agent_market.concierge.front import create_front_app
    front = TestClient(create_front_app(world.app.state.front))  # 에이전트는 별도 포트의 프론트로 들어옴
    first = front.post("/chat", json={"message": "Hi, I am TravelBot"}).json()
    front.post("/chat", json={"message": "find web search API"}, headers={"X-Visitor-Token": first["visitor"]["token"]})
    front.get("/")
    d = c.get("/admin/api/visitors", headers=H).json()
    assert d["stats"]["total"] == 1 and d["stats"]["anonymous_reads"] == 1 and d["items"][0]["name"] == "TravelBot"
    assert d["items"][0]["last_task"] == "find web search API"
    vid = d["items"][0]["id"]
    detail = c.get(f"/admin/api/visitors/{vid}", headers=H).json()
    assert [m["role"] for m in detail["messages"]] == ["agent", "concierge", "agent", "concierge"]
    assert "token_hash" not in detail["visitor"] and detail["interests"][0]["task"] == "find web search API"
    assert c.post(f"/admin/api/visitors/{vid}/notify", json={"enabled": False}, headers=H).json() == {"notify": False}
    assert c.post(f"/admin/api/visitors/{vid}/digest", headers=H).json()["checked"] == 0  # 인증된 연락처 없음
    assert c.get("/admin/api/visitors", headers={"X-Dashboard": "1"}).status_code == 401



def test_admin_simulator_uses_engine_without_front_port(dash):
    _, c = dash
    first = c.post("/admin/api/visitors/simulate", json={"message": "hello"}, headers=H).json()
    assert first["intent"] == "greet" and first["visitor"]["token"].startswith("vt_")
    again = c.post("/admin/api/visitors/simulate", json={"message": "find web search API", "token": first["visitor"]["token"]},
                   headers=H).json()
    assert again["intent"] == "find" and again["visitor"]["id"] == first["visitor"]["id"]
    assert c.get("/admin/api/visitors", headers=H).json()["items"][0]["channel"] == "admin-test"
    assert c.post("/admin/api/visitors/simulate", json={"message": "hi"}, headers={"X-Dashboard": "1"}).status_code == 401
