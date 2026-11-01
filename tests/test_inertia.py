import json
import httpx
import pytest
import time
from fastapi.testclient import TestClient

from agent_market.collector import usage
from agent_market.concierge.front import Front, create_front_app
from agent_market.concierge.inertia import InertiaGraph
from agent_market.concierge.proxy import McpProxy
from agent_market.gateway.store import Store
from tests.test_mcp_proxy import MockRemoteMcp, WEATHER_TOOL
from tests.report_fixtures import execution_report


def verified_fixture(store, rid, tools):
    """Bind synthetic successful execution to a surveyed full schema."""
    for tool in tools:
        tool.setdefault('annotations', {'readOnlyHint': True, 'destructiveHint': False})
    with store.tx() as db:
        db.execute('UPDATE resources SET health_status=?,last_ok_at=?,usage_full_tools=?,usage_tools=? WHERE id=?',
                   ('healthy', time.time(), json.dumps(tools), json.dumps(tools), rid))
    execution_report(store, rid, time.time()-1, title='Synthetic next-tool proof',
                     slug='inertia-proof-'+str(rid), is_success=1, status_code=200)


GEOCODE_TOOL = {
    "name": "geocode_address",
    "description": "Convert street address to coordinates",
    "inputSchema": {"type": "object", "properties": {"address": {"type": "string"}}, "required": ["address"]},
    "annotations": {"readOnlyHint": True, "destructiveHint": False}
}

ROUTE_TOOL = {
    "name": "calculate_route",
    "description": "Calculate route between two points",
    "inputSchema": {"type": "object", "properties": {"origin": {"type": "string"}, "destination": {"type": "string"}}},
    "annotations": {"readOnlyHint": True, "destructiveHint": False}
}


def test_transition_recording_and_markov_probabilities():
    """도구 호출 전이 기록 및 1차 마르코프 전이 확률 계산 검증."""
    store = Store()
    inertia = InertiaGraph(store)

    # A -> B 3회, A -> C 1회 전이 기록
    for _ in range(3):
        inertia.record_transition(from_rid=1, from_tool="geocode_address", to_rid=2, to_tool="calculate_route")
    inertia.record_transition(from_rid=1, from_tool="geocode_address", to_rid=3, to_tool="get_weather")

    # 동일 도구 연속 재시도 (A -> A)는 노이즈이므로 전이로 기록되지 않아야 함
    inertia.record_transition(from_rid=1, from_tool="geocode_address", to_rid=1, to_tool="geocode_address")

    transitions = store.get_tool_transitions(from_rid=1, from_tool="geocode_address", limit=5)
    assert len(transitions) == 2

    # 1순위: calculate_route (3/4 = 0.75)
    assert transitions[0]["to_tool"] == "calculate_route"
    assert transitions[0]["count"] == 3
    assert transitions[0]["probability"] == 0.75

    # 2순위: get_weather (1/4 = 0.25)
    assert transitions[1]["to_tool"] == "get_weather"
    assert transitions[1]["count"] == 1
    assert transitions[1]["probability"] == 0.25


def test_predict_next_with_empirical_data():
    """학습된 전이 확률에 따라 다음 도구 스키마가 정확히 프리페칭되는지 검증."""
    store = Store()
    # 서버 2: RoutingEngine (calculate_route 보유)
    tools_2 = [ROUTE_TOOL]
    c_2 = usage.compact_tools(tools_2)
    h_2 = usage.tools_hash(c_2)
    rid_2 = store.upsert_resource({
        "key": "mcp:https://route.example/mcp", "source": "mcp-registry", "kind": "mcp",
        "url": "https://route.example/mcp", "name": "RoutingEngine", "description": "Navigation",
        "category": "travel_maps_weather", "networks": [], "price_usdc": 0,
        "details": {"remotes": [{"type": "streamable-http", "url": "https://route.example/mcp"}]}
    })
    store.record_usage(rid_2, tools=c_2, digest=h_2, guide={"tools": c_2}, changes=None, trial=None)
    verified_fixture(store, rid_2, tools_2)

    inertia = InertiaGraph(store)
    inertia.record_transition(from_rid=1, from_tool="geocode_address", to_rid=rid_2, to_tool="calculate_route")

    # A current verified contract is required before suggesting another tool.
    prefetched = inertia.predict_next(from_rid=1, from_tool="geocode_address", limit=1)
    assert len(prefetched) == 1
    top = prefetched[0]
    assert top["resource_id"] == rid_2
    assert top["server_name"] == "RoutingEngine"
    assert top["tool"]["name"] == "calculate_route"
    assert "origin" in top["tool"]["inputSchema"]["properties"]
    assert top["probability"] == 1.0
    assert top["source"] == "empirical_markov"


def test_predict_next_cold_start_intra_server_affinity():
    """전이 통계가 없는 초기 상태(Cold-start)에서 동일 서버 내 형제 도구 프리페칭 검증."""
    store = Store()
    # 서버 1에 geocode_address 와 reverse_geocode 동시 보유
    tools_1 = [
        GEOCODE_TOOL,
        {"name": "reverse_geocode", "description": "GPS to address", "inputSchema": {"type": "object", "properties": {"lat": {"type": "number"}}}}
    ]
    c_1 = usage.compact_tools(tools_1)
    h_1 = usage.tools_hash(c_1)
    rid_1 = store.upsert_resource({
        "key": "mcp:https://geo.example/mcp", "source": "mcp-registry", "kind": "mcp",
        "url": "https://geo.example/mcp", "name": "GeoServer", "description": "Geocoding Hub",
        "category": "travel_maps_weather", "networks": [], "price_usdc": 0,
        "details": {"remotes": [{"type": "streamable-http", "url": "https://geo.example/mcp"}]}
    })
    store.record_usage(rid_1, tools=c_1, digest=h_1, guide={"tools": c_1}, changes=None, trial=None)
    verified_fixture(store, rid_1, tools_1)

    inertia = InertiaGraph(store)
    # geocode_address 호출 후 이전 전이 데이터가 없어도 형제 도구 reverse_geocode 프리페칭
    prefetched = inertia.predict_next(from_rid=rid_1, from_tool="geocode_address", limit=1)
    assert len(prefetched) == 1
    assert prefetched[0]["tool"]["name"] == "reverse_geocode"
    assert prefetched[0]["source"] == "intra_server_affinity"


def test_code_mode_template_generation():
    """연계 도구 체인을 기반으로 Code Mode 파이썬 실행 스크립트 템플릿 생성 검증."""
    chain = [
        {"resource_id": 1, "name": "geocode_address"},
        {"resource_id": 2, "tool": {"name": "calculate_route"}}
    ]
    code = InertiaGraph.generate_code_mode_template(chain, base_url="https://testgw:443/mcp")
    assert "Auto-generated Nexus-A2A Code Mode Pipeline" in code
    assert "GATEWAY_URL = \"https://testgw:443/mcp\"" in code
    assert "geocode_address" in code
    assert "calculate_route" in code
    assert "res_1 = client.post" in code
    assert "res_2 = client.post" in code


def test_e2e_call_with_autotool_prefetching():
    """MCP Concierge의 'call' 도구 호출 시 AutoTool 0ms 프리페칭 및 Code Mode 템플릿 자동 번들링 E2E 검증."""
    store = Store()
    tools = [
        GEOCODE_TOOL,
        {"name": "lookup_timezone", "description": "Get timezone for coordinates", "inputSchema": {"type": "object", "properties": {"lat": {"type": "number"}}},
         "annotations": {"readOnlyHint": True, "destructiveHint": False}}
    ]
    c_tools = usage.compact_tools(tools)
    h_tools = usage.tools_hash(c_tools)

    rid = store.upsert_resource({
        "key": "mcp:https://geo.example/mcp", "source": "mcp-registry", "kind": "mcp",
        "url": "https://geo.example/mcp", "name": "GeoServer", "description": "Geo service",
        "category": "travel_maps_weather", "networks": [], "price_usdc": 0,
        "details": {"remotes": [{"type": "streamable-http", "url": "https://geo.example/mcp"}]}
    })
    store.record_usage(rid, tools=c_tools, digest=h_tools, guide={"tools": c_tools}, changes=None, trial=None)
    verified_fixture(store, rid, tools)
    with store.tx() as db:
        db.execute("UPDATE resources SET health_status='healthy' WHERE id=?", (rid,))

    server = MockRemoteMcp(tools, call_result={"content": [{"type": "text", "text": "Coordinates: 37.5665, 126.9780"}]})
    front = Front(store, allow_private=True)
    front.proxy = McpProxy(store, allow_private=True, http=httpx.Client(transport=server))
    app = create_front_app(front)
    client = TestClient(app)

    # 1. 초기 call 실행
    resp = client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {
            "name": "call",
            "arguments": {"resource_id": rid, "tool": "geocode_address", "arguments": {"address": "Seoul"}}
        }
    }).json()["result"]

    sc = resp["structuredContent"]
    assert sc["ok"] is True
    assert sc["tool"] == "geocode_address"
    # AutoTool 프리페칭 도구 포함 확인
    prefetched = sc.get("prefetched_tools")
    assert prefetched and len(prefetched) >= 1
    assert prefetched[0]["tool"]["name"] == "lookup_timezone"
    # Code Mode 템플릿 포함 확인
    assert "run_pipeline" in sc.get("code_mode_template", "")
    assert "[Next-tool suggestions]" in resp["content"][0]["text"]
