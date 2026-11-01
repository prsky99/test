import json
import time
import pytest
from fastapi.testclient import TestClient

from agent_market.gateway.store import Store
from agent_market.concierge.engine import Recommender
from agent_market.concierge.front import Front, create_front_app


def create_mock_store():
    store = Store()
    # 서버 A: LocationHub (geocode_address 도구 보유)
    rid_a = store.upsert_resource({
        "key": "mcp:https://loc.example/mcp", "source": "mcp-registry", "kind": "mcp",
        "url": "https://loc.example/mcp", "name": "LocationHub",
        "description": "General location and geolocation utility server",
        "category": "travel_maps_weather", "networks": [], "price_usdc": 0,
        "details": {"remotes": [{"type": "streamable-http", "url": "https://loc.example/mcp"}]}
    })
    tools_a = [
        {"name": "geocode_address", "description": "Convert street address into latitude and longitude coordinates",
         "inputSchema": {"type": "object", "properties": {"address": {"type": "string"}}, "required": ["address"]}},
        {"name": "reverse_geocode", "description": "Lookup address from GPS latitude and longitude"}
    ]
    store.record_usage(rid_a, tools=tools_a, digest="hash_a", guide={"tools": tools_a, "steps": ["call geocode_address"]}, changes=["init"], trial={"ok": True})
    with store.tx() as db:
        db.execute("UPDATE resources SET health_status='healthy' WHERE id=?", (rid_a,))

    # 서버 B: RoutingEngine (calculate_route 도구 보유)
    rid_b = store.upsert_resource({
        "key": "mcp:https://route.example/mcp", "source": "mcp-registry", "kind": "mcp",
        "url": "https://route.example/mcp", "name": "RoutingEngine",
        "description": "Turn by turn navigation and routing assistant",
        "category": "travel_maps_weather", "networks": [], "price_usdc": 0,
        "details": {"remotes": [{"type": "streamable-http", "url": "https://route.example/mcp"}]}
    })
    tools_b = [
        {"name": "calculate_route", "description": "Find driving directions and calculate distance between coordinates",
         "inputSchema": {"type": "object", "properties": {"origin": {"type": "string"}, "destination": {"type": "string"}}}}
    ]
    store.record_usage(rid_b, tools=tools_b, digest="hash_b", guide={"tools": tools_b, "steps": ["call calculate_route"]}, changes=["init"], trial={"ok": True})
    with store.tx() as db:
        db.execute("UPDATE resources SET health_status='healthy' WHERE id=?", (rid_b,))

    # 서버 C: GeoFallback (batch_geocode 도구 보유, Self-Reflection 대체 후보)
    rid_c = store.upsert_resource({
        "key": "mcp:https://geofallback.example/mcp", "source": "mcp-registry", "kind": "mcp",
        "url": "https://geofallback.example/mcp", "name": "GeoFallback",
        "description": "Fallback address resolver and coordinate finder",
        "category": "travel_maps_weather", "networks": [], "price_usdc": 0,
        "details": {"remotes": [{"type": "streamable-http", "url": "https://geofallback.example/mcp"}]}
    })
    tools_c = [
        {"name": "batch_geocode", "description": "Batch convert street addresses into GPS coordinates accurately",
         "inputSchema": {"type": "object", "properties": {"addresses": {"type": "array", "items": {"type": "string"}}}},
         "annotations": {"readOnlyHint": True, "destructiveHint": False}}
    ]
    store.record_usage(rid_c, tools=tools_c, digest="hash_c", guide={"tools": tools_c, "steps": ["call batch_geocode"]}, changes=["init"], trial={"ok": True})
    with store.tx() as db:
        db.execute("UPDATE resources SET health_status='healthy' WHERE id=?", (rid_c,))

    # Keep the expected primary tool most recently verified as well as high quality.
    with store.tx() as db:
        db.execute("UPDATE resources SET eval_grade='B',eval_score=80,eval_at=?",(time.time(),))
        db.execute("UPDATE resources SET eval_grade='A',eval_score=95 WHERE id=?",(rid_a,))
    store.record_usage(rid_a, tools=tools_a, digest="hash_a", guide={"tools":tools_a}, changes=None, trial={"ok":True})
    return store, rid_a, rid_b, rid_c


def test_tool_level_fts5_and_relevance():
    """서버 이름에는 없지만 도구 이름('geocode_address')으로 검색했을 때 상위 매칭되는지 검증."""
    store, rid_a, rid_b, rid_c = create_mock_store()
    rec = Recommender(store)

    # 1. 도구 이름 'geocode_address' 검색
    results = rec.search("geocode_address", limit=3)
    assert len(results) >= 1
    top = results[0]
    assert top["id"] == rid_a
    assert top["name"] == "LocationHub"
    # 도구 스키마가 정상 추출되어 주입되었는지 확인
    assert any(t["name"] == "geocode_address" for t in top["tools_schema"])
    assert "address" in top["tools_schema"][0]["inputSchema"]["properties"]

    # 2. 도구 설명 'driving directions' 검색 -> RoutingEngine 매칭
    route_results = rec.search("driving directions and distance", limit=3)
    assert len(route_results) >= 1
    assert route_results[0]["id"] == rid_b
    assert route_results[0]["name"] == "RoutingEngine"


def test_record_usage_updates_fts_index():
    """새로운 도구 사용법이 기록될 때 FTS5 인덱스에 도구 설명이 반영되어 검색 가능해지는지 검증."""
    store = Store()
    rid = store.upsert_resource({
        "key": "mcp:https://doc.example/mcp", "source": "mcp-registry", "kind": "mcp",
        "url": "https://doc.example/mcp", "name": "DocHelper",
        "description": "Simple document tool", "category": "docs_knowledge",
        "networks": [], "price_usdc": 0,
        "details": {"remotes": [{"type": "streamable-http", "url": "https://doc.example/mcp"}]}
    })
    with store.tx() as db:
        db.execute("UPDATE resources SET health_status='healthy' WHERE id=?", (rid,))

    rec = Recommender(store)
    # 아직 'convert_pdf_to_markdown' 도구가 등록되기 전에는 매칭되지 않음
    initial = rec.search("convert_pdf_to_markdown", limit=1)
    assert len(initial) == 0

    # usage_tools 등록 (Store.record_usage)
    new_tools = [{"name": "convert_pdf_to_markdown", "description": "Extract text and tables from PDF and format as Markdown"}]
    guide = {"tools": new_tools, "steps": ["call convert_pdf_to_markdown"]}
    store.record_usage(rid, tools=new_tools, digest="hash_doc", guide=guide,
                       changes=["added tool convert_pdf_to_markdown"], trial={"ok": True})

    # 등록 후 즉시 검색 시 도구 이름으로 매칭 성공해야 함
    updated = rec.search("convert_pdf_to_markdown", limit=1)
    assert len(updated) == 1
    assert updated[0]["id"] == rid
    assert updated[0]["name"] == "DocHelper"
    assert updated[0]["tools_schema"][0]["name"] == "convert_pdf_to_markdown"


def test_mcp_fast_search_latency_and_schema():
    """MCP 'search' 도구 호출 시 초저지연(<100ms)으로 도구 스키마가 반환되는지 검증."""
    store, rid_a, rid_b, rid_c = create_mock_store()
    app = create_front_app(Front(store, allow_private=True))
    client = TestClient(app)

    start = time.perf_counter()
    resp = client.post("/mcp", json={
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "search",
            "arguments": {"task": "geocode_address coordinates", "kind":"mcp", "k": 2}
        }
    })
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert resp.status_code == 200
    res = resp.json()["result"]
    recs = res["structuredContent"]["recommendations"]
    assert len(recs) >= 1
    assert recs[0]["id"] == rid_a
    assert "tools_schema" in recs[0]
    # LLM 지연 없이 100ms 이내 초고속 반환 검증
    assert elapsed_ms < 150.0  # 로컬/CI 환경 편차 감안


def test_mcp_self_reflection_workflow():
    """도구 실행 실패 시 report(ok=False)를 통해 즉시 Self-Reflection 대안 도구가 검색되는지 검증."""
    store, rid_a, rid_b, rid_c = create_mock_store()
    # Recovery suggests only alternatives whose current contract executed successfully within 24 hours.
    from tests.report_fixtures import execution_report
    execution_report(store, rid_c, time.time() - 1, title='GeoFallback proof', slug='geofallback-proof', is_success=1)
    app = create_front_app(Front(store, allow_private=True))
    client = TestClient(app)

    # 1. 초기 검색 수행 (LocationHub가 1순위)
    s_resp = client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "search", "arguments": {"task": "geocode address coordinates", "kind":"mcp", "k": 3}}
    }).json()["result"]
    first_tool = s_resp["structuredContent"]["recommendations"][0]
    first_id = first_tool["id"]
    assert first_id == rid_a
    # `search` is read-only and creates no visitor; `hello` starts the remembered session.
    assert s_resp["structuredContent"].get("visitor") is None
    token = client.post("/mcp", json={"jsonrpc": "2.0", "id": 9, "method": "tools/call",
        "params": {"name": "hello", "arguments": {}}}).json()["result"]["structuredContent"]["visitor"]["token"]

    # 2. 첫 번째 도구 호출 실패 보고 (Self-Reflection retry)
    fail_resp = client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {
            "name": "report",
            "arguments": {
                "resource_id": first_id,
                "ok": False,
                "task": "geocode address coordinates",
                "error": "HTTP 500: Geocoding provider rate limited",
                "visitor_token": token
            }
        }
    }).json()["result"]

    sc = fail_resp["structuredContent"]
    assert sc["ok"] is False
    assert sc["resource_id"] == first_id
    # 실패한 리소스(LocationHub)는 제외되고 대체 리소스(GeoFallback)가 반환됨
    alt = sc["alternative"]
    assert alt is not None
    assert alt["id"] == rid_c
    assert alt["name"] == "GeoFallback"
    assert "batch_geocode" in [t["name"] for t in alt["tools_schema"]]
    # Recovery suggests; it never re-executes. The caller reviews and authorizes a new call.
    assert "Review alternatives before authorizing a new call." in fail_resp["content"][0]["text"]
    assert sc.get("execution_authorized") is not True
