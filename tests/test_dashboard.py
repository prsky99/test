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
def dash(tmp_path, monkeypatch):
    from agent_market.gateway.ssl_manager import SSLManager
    manager = SSLManager(str(tmp_path / "ssl"))
    manager.renew_certificate()
    monkeypatch.setattr("agent_market.gateway.ssl_manager.get_ssl_manager", lambda: manager)
    world = populated()
    from agent_market.gateway import admin_auth
    with world.store.tx() as db:
        user = admin_auth.create_admin_user(db, 'dashboard-fixture', 'Dashboard-fixture-password', 'Fixture', 'superadmin')
        token = admin_auth.create_session(db, user['id'], user['username'], user['role'], user['name'])
    monkeypatch.setitem(H, 'authorization', 'Bearer ' + token)
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


def test_without_token_development_mode_is_explicit_and_loopback_only(monkeypatch):
    monkeypatch.setenv("AGENTCON_ADMIN_DEV", "1")
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
    assert ov["health"]["interval"] == world.app.state.collector.checker.schedule.interval == 21600
    assert ov["crawl"]["runs"] and ov["crawl"]["last"]["report"]
    assert ov["collector"]["paused"] is False


def test_overview_six_hour_metrics_use_the_actual_six_hour_window(dash):
    world, client = dash
    now = time.time()
    ids = [r['id'] for r in world.store.query('SELECT id FROM resources WHERE active=1 ORDER BY id')]
    with world.store.tx() as db:
        for hours, outcome in [(0.5, 'healthy'), (3, 'healthy'), (5, 'fail'), (7, 'healthy')]:
            db.execute('INSERT INTO health_checks(resource_id,at,outcome,status_code,latency_ms) VALUES(?,?,?,?,?)',
                       (ids[0], now - hours * 3600, outcome, 200, 10))
        for rid, due in zip(ids, [now - 3 * 3600, now - 7 * 3600, now + 3600, None]):
            db.execute('UPDATE resources SET next_check_at=? WHERE id=?', (due, rid))
    health = client.get('/admin/api/overview', headers={**H, 'X-Admin-Refresh': '1'}).json()['health']
    assert health['interval'] == 21600
    assert (health['checks_6h'], health['ok_6h']) == (3, 2)
    assert (health['checks_2h'], health['ok_2h']) == (1, 1)  # Preserve legacy API semantics.
    assert (health['overdue_6h'], health['overdue_2h']) == (1, 2)
    assert sum(r['overdue_6h'] for r in health['by_kind'].values()) == 1


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


def test_errors_group_failures_and_capture_logs(dash, monkeypatch):
    monkeypatch.setenv("AGENTCON_ADMIN_DEV", "1")
    world, c = dash
    world.reg.down.add("https://img.example/gen")
    rid = world.store.query("SELECT id FROM resources WHERE url='https://img.example/gen'")[0]["id"]
    world.service.prober.checker.check_and_record(world.store.resource(rid))
    logging.getLogger("agent_market.collector").error("erc8004 resolve failed")
    e = c.get("/admin/api/errors", headers=H).json()
    assert e["health"][0]["n"] == 1 and e["health"][0]["sample_url"] == "https://img.example/gen"
    assert any(l["message"] == "erc8004 resolve failed" for l in e["logs"])
    c.post("/admin/api/logs/clear", headers=H, json={"reason":"Synthetic buffer review"})
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
    assert d["stats"]["total"] == 1 and d["stats"]["anonymous_reads"] == 1 and d["items"][0]["name"] is None  # 11-10: names are not stored
    assert d["items"][0]["last_task"] == "find web search API"
    vid = d["items"][0]["id"]
    detail = c.get(f"/admin/api/visitors/{vid}", headers=H).json()
    assert [m["role"] for m in detail["messages"]] == ["agent", "concierge", "agent", "concierge"]
    assert "token_hash" not in detail["visitor"] and detail["interests"][0]["task"] == "find web search API"
    assert c.post(f"/admin/api/visitors/{vid}/notify", json={"enabled": False}, headers=H).json() == {"notify": False}
    assert c.post(f"/admin/api/visitors/{vid}/digest", headers=H).json()["checked"] == 0  # 인증된 연락처 없음
    assert "nurture_info" in detail and detail["nurture_info"]["stage"] == "task_updates"
    assert "nurture_stages" in d["stats"]
    nurture_res = c.post(f"/admin/api/visitors/{vid}/nurture", json={"campaign": "welcome_audit"}, headers=H).json()
    assert nurture_res["status"] == "permission_denied"
    assert c.post("/admin/api/visitors/nurture/run", headers=H).status_code == 403
    assert c.get("/admin/api/visitors", headers={"X-Dashboard": "1"}).status_code == 401



def test_admin_simulator_uses_engine_without_front_port(dash, monkeypatch):
    monkeypatch.setenv("AGENTCON_ADMIN_DEV", "1")
    _, c = dash
    first = c.post("/admin/api/visitors/simulate", json={"message": "hello", "reason":"Synthetic simulator review"}, headers=H).json()
    assert first["intent"] == "greet" and first["visitor"]["token"].startswith("vt_")
    again = c.post("/admin/api/visitors/simulate", json={"message": "find web search API", "token": first["visitor"]["token"], "reason":"Synthetic follow-up review"},
                   headers=H).json()
    assert again["intent"] == "find" and again["visitor"]["id"] == first["visitor"]["id"]
    assert c.get("/admin/api/visitors", headers=H).json()["items"][0]["channel"] == "admin-test"
    assert c.post("/admin/api/visitors/simulate", json={"message": "hi"}, headers={"X-Dashboard": "1"}).status_code == 401


def test_explore_interleaves_all_kinds(dash):
    world, c = dash
    # a2a 에이전트 등록
    world.store.upsert_resource({
        "key": "a2a-test-1", "source": "wellknown", "kind": "a2a",
        "url": "https://a2a.example/agent", "name": "Test A2A Agent",
        "description": "Autonomous AI agent for general reasoning and task delegation.",
        "category": "assistant", "networks": [], "price_usdc": 0,
        "details": {"skills": [{"id": "think", "name": "Deep Thinking"}]}
    })
    with world.store.tx() as db:
        db.execute("UPDATE resources SET health_status='healthy', eval_score=95, trial_ok=1")

    res = c.get("/admin/api/explore", headers=H).json()
    items = res["items"]
    assert len(items) >= 3
    kinds = {it["kind"] for it in items}
    assert "a2a" in kinds
    assert "mcp" in kinds
    assert "x402" in kinds


def test_gateway_security_headers_and_cache_control(dash):
    world, client = dash

    # 1. Admin endpoints have nosniff, DENY, and no-store
    resp = client.get("/admin/api/overview", headers=H)
    assert resp.status_code == 200
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "no-referrer"
    assert resp.headers["Cache-Control"] == "no-store"

    # 2. Public health endpoint has security headers
    h_resp = client.get("/health")
    assert h_resp.status_code == 200
    assert h_resp.headers["X-Content-Type-Options"] == "nosniff"
    assert h_resp.headers["X-Frame-Options"] == "DENY"


def test_twenty_categories_expansion(dash):
    from agent_market.broker.categories import CATEGORIES
    from agent_market.gateway.classify import KEYWORDS, classify

    assert len(CATEGORIES) == 20
    assert set(KEYWORDS) == set(CATEGORIES)

    # Test classification into the new categories
    assert classify("Clinical trials and medical patient records for genomic analysis") == "health_science"
    assert classify("Send SMS and WhatsApp notifications via webhook") == "communication_messaging"
    assert classify("Lookup DNS records and check SSL TLS certificate expiration") == "network_ops"
    assert classify("Convert CSV rows to JSON and canonicalize data format") == "data_utility"
    assert classify("Perpetual futures funding rates and order book arbitrage on Deribit") == "trading_derivatives"
    assert classify("Classic literature library and public-domain film archive") == "education_culture"

    # Test overview returns category_names
    world, client = dash
    ov = client.get("/admin/api/overview", headers=H).json()
    assert "category_names" in ov
    assert len(ov["category_names"]) == 21  # 20 + other
    assert ov["category_names"]["health_science"] == "헬스·의료·생명과학"
    assert ov["category_names"]["trading_derivatives"] == "트레이딩·파생상품·오더북"


def test_dashboard_input_hardening_and_rate_limits(dash):
    world, client = dash

    # 1. Null-byte injection and long query in explore
    exp_resp = client.get("/admin/api/explore", params={"q": "weather\x00malicious" + "A" * 600}, headers=H)
    assert exp_resp.status_code in (200, 422)  # clamped or validated

    # 2. Malformed JSON to visitor simulate
    bad_sim = client.post("/admin/api/visitors/simulate", content=b"invalid json{", headers={**H, "content-type": "application/json"})
    assert bad_sim.status_code == 400
    assert "JSON" in bad_sim.json()["detail"]


def test_manual_register_security_and_ssrf(dash):
    world, c = dash

    # 1. 인증 헤더 누락 시 거부
    assert c.post("/admin/api/register", json={"kind": "a2a", "url": "https://example.com", "name": "test", "description": "test"}).status_code == 403
    assert c.post("/admin/api/register", json={"kind": "a2a", "url": "https://example.com", "name": "test", "description": "test"}, headers={"X-Dashboard": "1"}).status_code == 401

    # 2. SSRF 차단 검증 (사설 IP, 루프백, 클라우드 메타데이터 IP)
    private_urls = [
        "http://127.0.0.1:8200/secret",
        "http://localhost:3000/agent",
        "http://10.0.0.1/private",
        "http://192.168.1.1/admin",
        "http://169.254.169.254/latest/meta-data",
    ]
    for purl in private_urls:
        # inspect 엔드포인트 차단
        r_inspect = c.post("/admin/api/register/inspect", json={"url": purl}, headers=H)
        assert r_inspect.status_code == 400
        assert "보안 검증 실패" in r_inspect.json()["detail"]

        # register 엔드포인트 차단
        r_reg = c.post("/admin/api/register", json={
            "kind": "a2a", "url": purl, "name": "Evil", "description": "Evil description"
        }, headers=H)
        assert r_reg.status_code == 400
        assert "보안 검증 실패" in r_reg.json()["detail"]

    # 3. 비정상 스킴 차단
    for bad_url in ["ftp://example.com/agent", "javascript:alert(1)", "file:///etc/passwd"]:
        r_bad = c.post("/admin/api/register", json={
            "kind": "a2a", "url": bad_url, "name": "Bad", "description": "Bad scheme"
        }, headers=H)
        assert r_bad.status_code == 400

    # 4. 잘못된 kind 및 빈 필수 필드 거부
    assert c.post("/admin/api/register", json={"kind": "invalid", "url": "https://example.com/a"}, headers=H).status_code == 400
    assert c.post("/admin/api/register", json={"kind": "a2a", "url": "", "name": "No Url"}, headers=H).status_code == 400
    assert c.post("/admin/api/register", json={"kind": "a2a", "url": "https://example.com/a", "name": ""}, headers=H).status_code == 400


def test_manual_register_agent_lifecycle(dash, monkeypatch):
    from agent_market.collector.health import CheckResult
    world, c = dash

    # SSRF DNS 검증 모킹 (테스트 가상 도메인 허용)
    monkeypatch.setattr("agent_market.gateway.dashboard.check_public_url", lambda url: None)

    # 헬스체크 모킹: 실제 활성 에이전트 응답
    monkeypatch.setattr(
        "agent_market.collector.health.HealthChecker.check",
        lambda self, r: CheckResult("healthy", 200, latency_ms=45)
    )

    # 1. A2A 에이전트 신규 등록 (활성 검증 성공)
    a2a_payload = {
        "kind": "a2a",
        "url": "https://example.com/radar-agent",
        "name": "Global Radar A2A\x00Cleaned",
        "description": "Real-time high resolution satellite weather radar and forecasting.",
        "category": "weather"
    }
    res = c.post("/admin/api/register", json=a2a_payload, headers=H)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["status"] == "healthy"
    assert data["name"] == "Global Radar A2ACleaned"  # null-byte 살균
    rid = data["id"]
    assert rid is not None

    # DB 적재 및 헬스체크 대기열 포함 확인 (source='manual', health_status='healthy')
    r_db = world.store.query("SELECT * FROM resources WHERE id=?", (rid,))[0]
    assert r_db["source"] == "manual"
    assert r_db["kind"] == "a2a"
    assert r_db["name"] == "Global Radar A2ACleaned"
    assert r_db["health_status"] == "healthy"
    assert r_db["next_check_at"] is not None and r_db["next_check_at"] > time.time()
    assert r_db["probe_latency_ms"] == 45

    # health_checks 이력 테이블 기록 확인
    h_rows = world.store.query("SELECT * FROM health_checks WHERE resource_id=?", (rid,))
    assert len(h_rows) >= 1
    assert h_rows[0]["outcome"] == "healthy"

    # sqlite-vec 아웃박스에 큐잉 확인
    outbox = world.store.query("SELECT * FROM vec_outbox WHERE resource_id=?", (rid,))
    assert len(outbox) == 1
    assert outbox[0]["reason"] in ("new", "source")

    # FTS5 전문 검색 테이블 동기화 확인
    fts_hits = world.store.query("SELECT rowid FROM resources_fts WHERE resources_fts MATCH ?", ("radar",))
    assert any(h["rowid"] == rid for h in fts_hits)

    # 2. x402 유료 API 신규 등록
    x402_payload = {
        "kind": "x402",
        "url": "https://example.com/paid-ocr",
        "name": "Micro OCR API",
        "description": "Pay-per-scan document OCR service powered by x402.",
        "category": "productivity",
        "price_usdc": 2500,
        "pay_to": "0x1234567890abcdef1234567890abcdef12345678",
        "networks": ["base"]
    }
    x_res = c.post("/admin/api/register", json=x402_payload, headers=H)
    assert x_res.status_code == 200
    x_data = x_res.json()
    assert x_data["ok"] is True
    x_rid = x_data["id"]

    x_db = world.store.query("SELECT * FROM resources WHERE id=?", (x_rid,))[0]
    assert x_db["price_usdc"] == 2500
    assert x_db["pay_to"] == "0x1234567890abcdef1234567890abcdef12345678"
    assert x_db["health_status"] == "healthy"

    # 3. 중복 등록 차단 검증 (수동 등록 건 재등록 시 409 Conflict)
    dup_res = c.post("/admin/api/register", json={
        "kind": "a2a",
        "url": "https://example.com/radar-agent",
        "name": "Duplicate Radar",
        "description": "Trying to register duplicate URL.",
        "category": "weather"
    }, headers=H)
    assert dup_res.status_code == 409
    assert "이미 등록되어 있는 에이전트 URL입니다" in dup_res.json()["detail"]

    # 4. 수집기로 이미 수집된 에이전트와도 중복 등록 차단 검증
    crawler_res = c.post("/admin/api/register", json={
        "kind": "x402",
        "url": "https://chain.example/balance",  # populated()에서 이미 수집된 URL
        "name": "Colliding Chain Balance",
        "description": "Collides with existing crawler agent",
        "category": "finance_crypto"
    }, headers=H)
    assert crawler_res.status_code == 409
    assert "이미 등록되어 있는 에이전트 URL입니다" in crawler_res.json()["detail"]

    # 5. 활성 상태 검증 실패 시 등록 거부 검증 (오프라인 상태)
    monkeypatch.setattr(
        "agent_market.collector.health.HealthChecker.check",
        lambda self, r: CheckResult("fail", 502, error="HTTP 502 Bad Gateway")
    )
    fail_res = c.post("/admin/api/register", json={
        "kind": "a2a",
        "url": "https://example.com/dead-agent",
        "name": "Dead Agent",
        "description": "Offline endpoint",
        "category": "weather"
    }, headers=H)
    assert fail_res.status_code == 422
    assert "에이전트 활성 검증 실패" in fail_res.json()["detail"]

    # 6. 최근 등록 목록 조회 (/admin/api/agents?source=manual)
    agents_page = c.get("/admin/api/agents", params={"source": "manual", "sort": "new"}, headers=H).json()
    assert agents_page["total"] >= 2
    urls = [a["url"] for a in agents_page["items"]]
    assert "https://example.com/radar-agent" in urls
    assert "https://example.com/paid-ocr" in urls
    assert "https://example.com/dead-agent" not in urls


def test_manual_register_inspect_auto_detection(dash, monkeypatch):
    world, c = dash

    # 1. A2A Agent Card 감지 모킹
    class FakeCardResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = ""

        def json(self):
            return {
                "name": "Auto Weather Bot",
                "description": "Accurate rainfall and satellite weather forecasts",
                "skills": [{"id": "forecast", "name": "Weather Forecast"}]
            }

    class FakeClient:
        def get(self, url):
            return FakeCardResponse()
        def close(self):
            pass

    monkeypatch.setattr("agent_market.gateway.dashboard.public_client", lambda **kw: FakeClient())
    monkeypatch.setattr("agent_market.gateway.dashboard.check_public_url", lambda url: None)

    r = c.post("/admin/api/register/inspect", json={"url": "https://example.com/bot"}, headers=H)
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert d["kind"] == "a2a"
    assert d["name"] == "Auto Weather Bot"
    assert "rainfall" in d["description"]
    assert d["category"] == "travel_maps_weather"


def test_binary_clock_loader_in_dashboard(dash):
    world, c = dash
    r = c.get("/admin/ui")
    assert r.status_code == 200
    html = r.text
    # 1. Binary clock hand spinner styles and markup
    assert "binary-spinner-overlay" in html
    assert "binary-dial" in html
    assert "clock-hand" in html
    assert "clock-center" in html
    assert "binaryClockRotate" in html
    assert "bitPulse" in html
    # 2. Binary bits 0 and 1
    assert '<span class="bit"' in html
    # 3. Floating loader and inline helper
    assert 'id="binaryLoader"' in html
    assert "binaryClockHtml" in html
    assert "showLoader" in html
    assert "hideLoader" in html


def test_ssl_status_and_renew_via_admin(dash):
    world, c = dash
    # 1. Overview includes SSL info
    ov = c.get("/admin/api/overview", headers=H).json()
    assert "ssl" in ov
    assert "auto_renew_enabled" in ov["ssl"]
    assert ov["ssl"]["auto_renew_enabled"] is True

    # 2. GET /admin/api/ssl returns active status and OpenSSL info
    r = c.get("/admin/api/ssl", headers=H)
    assert r.status_code == 200
    ssl_info = r.json()
    assert ssl_info["exists"] is True
    assert ssl_info["valid"] is True
    from agent_market.gateway.ssl_manager import get_openssl_version
    assert ssl_info.get("openssl_version") == get_openssl_version()
    assert ssl_info.get("days_remaining", 0) > 300

    # 3. POST /admin/api/ssl/renew manually triggers renewal with 365 days
    r_renew = c.post("/admin/api/ssl/renew?days=365", headers=H)
    assert r_renew.status_code == 200
    res = r_renew.json()
    assert res["ok"] is True
    assert "renewed successfully" in res["message"]
    assert res["details"]["validity_days"] == 365

    # Certificate operations remain available to authenticated system clients;
    # the visitor security screen no longer includes their controls or polling.
    ui = c.get("/admin/ui").text
    assert "OpenSSL" not in ui
    assert "sslRenewBtn" not in ui
    assert "loadSslStatus" not in ui
    assert '"/admin/api/ssl' not in ui
    assert "포트 443 (HTTPS) 공개 프론트앤드 트래픽 쉴드" in ui


def test_dashboard_explore_category_chips_active_state(dash):
    world, c = dash
    ui = c.get("/admin/ui").text
    assert ".qchips button.active" in ui
    assert ".qchips button.on" in ui
    assert "updateActiveExploreChip" in ui
    assert 'id="xChips"' in ui
    assert "data-q=" in ui


def test_dashboard_no_horizontal_scroll_overflow(dash):
    world, c = dash
    ui = c.get("/admin/ui").text
    assert "overflow-x: hidden" in ui
    assert "max-width: 100%" in ui


def test_dashboard_html_script_syntax_valid(dash):
    import re, subprocess, shutil
    world, c = dash
    ui = c.get("/admin/ui").text
    scripts = re.findall(r'<script\b[^>]*>(.*?)</script>', ui, re.DOTALL)
    assert len(scripts) > 0, "dashboard.html must contain a <script> block"
    if shutil.which("node"):
        for idx, s in enumerate(scripts):
            res = subprocess.run(["node", "--check"], input=s, text=True, capture_output=True)
            assert res.returncode == 0, f"Script {idx} in dashboard.html has JS syntax error:\n{res.stderr}"


def test_dashboard_a2a_registry_elements(dash):
    world, c = dash
    ui = c.get("/admin/ui").text
    assert "A2A Registry" in ui
    assert 'id="fSource"' in ui
    assert 'value="a2a-registry"' in ui
    assert 'id="mCrawlFull"' in ui

    # Test filtering agents by source
    r = c.get("/admin/api/agents", params={"source": "a2a-registry"}, headers=H)
    assert r.status_code == 200
    assert "total" in r.json()

    # Test crawl action with force_full=true
    r_full = c.post("/admin/api/actions/crawl?force_full=true", headers=H)
    assert r_full.status_code == 200
    assert r_full.json()["started"] is True


def test_agent_telemetry_and_improvement_discovery(dash):
    import json, time
    world, c = dash
    now = time.time()

    # 1. Verify UI has the new menu button and panel
    ui = c.get("/admin/ui").text
    assert 'data-tab="agent_telemetry"' in ui
    assert 'data-panel="agent_telemetry"' in ui
    assert "에이전트 활동·개선 분석" in ui
    assert "loadAgentTelemetry" in ui

    # 2. Seed autonomous agent hits, visitors, matched/unmet queries, outcomes, and tool inertia
    with world.store.tx() as db:
        db.execute(
            "INSERT OR REPLACE INTO agent_hits VALUES (?,?,?,?,?,?)",
            ("fp_claude_0001", "Claude-Code/1.0 (Anthropic)", now - 600, now - 60, 4, "/skill.md"),
        )
        db.execute(
            "INSERT OR REPLACE INTO agent_hits VALUES (?,?,?,?,?,?)",
            ("fp_mcp_0002", "MCP-Client/2.1", now - 500, now - 30, 2, "/llms.txt"),
        )
        db.execute(
            """INSERT OR REPLACE INTO agent_visitors
               (id, token_hash, name, channel, user_agent, fingerprint, lang, first_seen, last_seen, visits, visit_days, messages, tier)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("vis_auto_1", "th_auto_1", "AlphaPlanner", "mcp", "Claude-Code/1.0", "fp_claude_0001", "en", now - 3600, now - 30, 3, 2, 6, "returning"),
        )
        db.execute(
            """INSERT OR REPLACE INTO agent_visitors
               (id, token_hash, name, channel, user_agent, fingerprint, lang, first_seen, last_seen, visits, visit_days, messages, tier)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("vis_auto_2", "th_auto_2", "BetaCrawler", "a2a", "A2A-Agent/1.0", "fp_mcp_0002", "en", now - 1800, now - 120, 1, 1, 2, "new"),
        )
        # Matched turn + details turn for vis_auto_1
        db.execute(
            "INSERT INTO agent_messages (visitor_id, at, role, channel, text, data) VALUES (?,?,?,?,?,?)",
            ("vis_auto_1", now - 300, "concierge", "mcp", "Recommended weather agent.", json.dumps({
                "record_version": 1,
                "intent": "find",
                "status": "matched",
                "protocol_filter": "mcp",
                "task": "weather forecast api",
                "recommendations": [{"id": 1, "name": "Weather MCP"}],
            })),
        )
        db.execute(
            "INSERT INTO agent_messages (visitor_id, at, role, channel, text, data) VALUES (?,?,?,?,?,?)",
            ("vis_auto_1", now - 200, "concierge", "mcp", "Details for #1", json.dumps({
                "record_version": 1,
                "intent": "details",
                "status": "ok",
                "protocol_filter": "mcp",
                "task": "weather forecast api",
            })),
        )
        # Unmet query turn for vis_auto_2
        db.execute(
            "INSERT INTO agent_messages (visitor_id, at, role, channel, text, data) VALUES (?,?,?,?,?,?)",
            ("vis_auto_2", now - 150, "concierge", "a2a", "No verified match.", json.dumps({
                "record_version": 1,
                "intent": "find",
                "status": "no_match",
                "protocol_filter": "x402",
                "task": "quantum satellite telemetry stream",
                "recommendations": [],
            })),
        )
        # Runtime failure outcome report
        db.execute(
            "INSERT OR REPLACE INTO agent_outcomes (visitor_id, resource_id, success, at) VALUES (?,?,?,?)",
            ("vis_auto_1", 1, 0, now - 100),
        )
        # Tool inertia transition
        db.execute(
            "INSERT OR REPLACE INTO tool_inertia (from_resource_id, from_tool, to_resource_id, to_tool, count, last_transition) VALUES (?,?,?,?,?,?)",
            (1, "fetch_news", 2, "summarize_paper", 5, now - 50),
        )

    # 3. Call /admin/api/agent-telemetry and verify structure & discovered improvements
    r = c.get("/admin/api/agent-telemetry?days=7&source=live", headers=H)
    assert r.status_code == 200
    data = r.json()
    assert data["kpis"]["total_visitors"] >= 2
    assert data["kpis"]["anonymous_reads"] >= 6
    assert data["kpis"]["unmet_query_count"] >= 1
    assert data["kpis"]["outcomes_fail"] >= 1
    assert len(data["funnel"]) == 5
    assert data["funnel"][0]["key"] == "discovery_entry"
    assert data["funnel"][4]["key"] == "retained_agent"

    # Entry paths include /skill.md and /llms.txt
    paths = {ep["path"] for ep in data["entry_paths"]}
    assert "/skill.md" in paths
    assert "/llms.txt" in paths

    # Unmet query detected
    unmet_tasks = [u["task"] for u in data["unmet_queries"]]
    assert any("quantum satellite telemetry stream" in t for t in unmet_tasks)

    # Failing agent detected
    assert any(fa["resource_id"] == 1 and fa["fail_count"] >= 1 for fa in data["failing_agents"])

    # Inertia chain detected
    assert any(ic["from_tool"] == "fetch_news" and ic["to_tool"] == "summarize_paper" for ic in data["inertia_chains"])

    # Synthesized actionable improvements include unmet_capability_gap, runtime_failing_agents, inertia_workflow_synthesis
    imp_ids = {imp["id"] for imp in data["improvements"]}
    assert "unmet_capability_gap" in imp_ids
    assert "runtime_failing_agents" in imp_ids
    assert "inertia_workflow_synthesis" in imp_ids

    # Recent trajectories include vis_auto_1 with steps
    traj_by_id = {t["visitor_id"]: t for t in data["recent_trajectories"]}
    assert "vis_auto_1" in traj_by_id
    assert len(traj_by_id["vis_auto_1"]["steps"]) >= 2


def test_agent_telemetry_ax_remediation_and_circuit_breaker(dash):
    import json
    from agent_market.concierge.memory import VisitorBook
    world, c = dash
    now = time.time()
    book = VisitorBook(world.store)

    # 1. Adversarial payloads are separate; task wording alone never proves simulation provenance.
    with world.store.tx() as db:
        db.execute(
            """INSERT OR REPLACE INTO agent_visitors
               (id, token_hash, name, channel, user_agent, fingerprint, lang, first_seen, last_seen, visits, visit_days, messages, tier)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("vis_sec_1", "th_sec_1", "ProbeBot", "rest", "curl/8.4.0", "fp_sec_1", "en", now - 300, now - 60, 1, 1, 2, "new"),
        )
        db.execute(
            "INSERT INTO agent_messages (visitor_id, at, role, channel, text, data) VALUES (?,?,?,?,?,?)",
            ("vis_sec_1", now - 250, "concierge", "rest", "No match.", json.dumps({
                "record_version": 1,
                "intent": "find",
                "status": "no_match",
                "protocol_filter": "any",
                "task": '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY xxe SYSTEM "http://169.254.169.254/latest/meta-data/">]>',
                "recommendations": [],
            })),
        )
        db.execute(
            "INSERT INTO agent_messages (visitor_id, at, role, channel, text, data) VALUES (?,?,?,?,?,?)",
            ("vis_sec_1", now - 240, "concierge", "rest", "No match.", json.dumps({
                "record_version": 1,
                "intent": "find",
                "status": "no_match",
                "protocol_filter": "any",
                "task": "Find a telepathic time travel unicorn detector",
                "recommendations": [],
            })),
        )
        db.execute(
            "INSERT INTO agent_messages (visitor_id, at, role, channel, text, data) VALUES (?,?,?,?,?,?)",
            ("vis_sec_1", now - 230, "concierge", "rest", "No match.", json.dumps({
                "record_version": 1,
                "intent": "find",
                "status": "no_match",
                "protocol_filter": "x402",
                "task": "deep ocean bathymetry sonar feed",
                "recommendations": [],
            })),
        )

    res = c.get("/admin/api/agent-telemetry?days=7&source=live", headers=H).json()
    unmet_tasks = [u["task"] for u in res["unmet_queries"]]
    assert not any("169.254.169.254" in t for t in unmet_tasks)
    assert any("unicorn detector" in t for t in unmet_tasks)
    assert any("deep ocean bathymetry sonar feed" in t for t in unmet_tasks)
    assert res["kpis"]["filtered_noise_queries"] >= 1

    # 2. Crowd-sourced runtime circuit breaker via POST /admin/api/agent-telemetry/remediate
    assert 1 not in book.global_failing_resources()
    trip = c.post("/admin/api/agent-telemetry/remediate", json={"action": "trip_circuit", "resource_id": 1}, headers=H)
    assert trip.status_code == 200 and trip.json()["circuit_open"] is True
    assert 1 in book.global_failing_resources()

    res_after_trip = c.get("/admin/api/agent-telemetry?days=7&source=live", headers=H).json()
    fa_1 = next(fa for fa in res_after_trip["failing_agents"] if fa["resource_id"] == 1)
    assert fa_1["circuit_open"] is True
    assert res_after_trip["kpis"]["circuit_open_count"] >= 1

    # Reset circuit breaker
    reset = c.post("/admin/api/agent-telemetry/remediate", json={"action": "reset_circuit", "resource_id": 1}, headers=H)
    assert reset.status_code == 200 and reset.json()["circuit_open"] is False
    assert 1 not in book.global_failing_resources()

    # 3. Resolve unmet query action
    resolve = c.post("/admin/api/agent-telemetry/remediate", json={"action": "resolve_unmet", "task": "deep ocean bathymetry sonar feed"}, headers=H)
    assert resolve.status_code == 409






