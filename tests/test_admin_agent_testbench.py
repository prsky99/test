"""Tests for the Admin Agent Testbench (에이전트 테스트) feature."""

import json
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from agent_market.config import GatewayConfig
from agent_market.gateway.server import create_app
from agent_market.gateway.store import Store
from tests.test_gateway import populated
from tests.conftest import STAFF


H = {"X-Dashboard": "1", "authorization": "Bearer secret"}


@pytest.fixture
def dash(monkeypatch):
    world = populated()
    client = TestClient(world.app)
    monkeypatch.setitem(H, 'authorization', STAFF['Authorization'])
    return world, client


def test_admin_ui_has_testbench_tab_and_panel(dash):
    _, c = dash
    r = c.get("/admin/ui")
    assert r.status_code == 200
    html = r.text

    # 1. Navigation tab present
    assert 'data-tab="test"' in html
    assert "에이전트 테스트" in html

    # 2. Main panel and layout present
    assert 'data-panel="test"' in html
    assert "에이전트 라이브 테스트벤치 (Agent Testbench)" in html
    assert 'id="testKindFilter"' in html
    assert 'id="testAgentSearch"' in html
    assert 'id="testAgentSelect"' in html
    assert 'id="testAgentMetaCard"' in html
    assert 'id="testMcpActionBox"' in html
    assert 'id="testToolSelect"' in html
    assert 'id="testA2aActionBox"' in html
    assert 'id="testArgsJson"' in html
    assert 'id="testFillSampleBtn"' in html
    assert 'id="testRunBtn"' in html
    assert 'id="testOutputFormatted"' in html
    assert 'id="testWireReq"' in html
    assert 'id="testWireRes"' in html
    assert 'id="testHistoryTable"' in html


def test_admin_api_test_agents_list(dash):
    _, c = dash

    # 1. Without auth header -> 403 / 401
    assert c.get("/admin/api/test/agents").status_code == 403
    assert c.get("/admin/api/test/agents", headers={"X-Dashboard": "1"}).status_code == 401

    # 2. Authorized request
    res = c.get("/admin/api/test/agents", headers=H)
    assert res.status_code == 200
    data = res.json()
    assert "agents" in data
    assert "count" in data
    assert data["count"] > 0

    first = data["agents"][0]
    assert "id" in first
    assert "name" in first
    assert "kind" in first
    assert "url" in first
    assert "health_status" in first

    # 3. Filtering by kind
    res_mcp = c.get("/admin/api/test/agents?kind=mcp", headers=H).json()
    assert all(a["kind"] == "mcp" for a in res_mcp["agents"])


def test_admin_api_test_agent_spec(dash):
    world, c = dash

    # Get one mcp agent from DB
    res = c.get("/admin/api/test/agents?kind=mcp", headers=H).json()
    assert len(res["agents"]) > 0
    agent = res["agents"][0]
    rid = agent["id"]

    # Fetch spec
    spec_res = c.get(f"/admin/api/test/agents/{rid}/spec", headers=H)
    assert spec_res.status_code == 200
    spec = spec_res.json()
    assert spec["id"] == rid
    assert spec["name"] == agent["name"]
    assert spec["kind"] == "mcp"
    assert "tools" in spec
    assert "sample_args" in spec

    # 404 for non-existent agent
    assert c.get("/admin/api/test/agents/999999/spec", headers=H).status_code == 404


def test_admin_api_test_execute_mcp_mock(dash):
    world, c = dash

    # Insert a dummy MCP agent with tools
    now = 1700000000.0
    with world.store.tx() as db:
        db.execute(
            """INSERT INTO resources (key, source, kind, name, description, url, category, networks, health_status, active, details, usage_guide, first_seen, last_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "mcp:weather-dummy",
                "manual",
                "mcp",
                "Weather Server",
                "Weather forecast MCP tool server",
                "https://api.weather-mcp.org/mcp",
                "travel_maps_weather",
                "[]",
                "healthy",
                1,
                json.dumps({"tools": [{"name": "get_weather", "description": "Get current weather", "params": {"city": {"type": "string"}}}]}),
                json.dumps({"tools": [{"name": "get_weather", "description": "Get current weather", "params": {"city": {"type": "string"}}, "required": ["city"]}]}),
                now,
                now,
            )
        )
        cur = db.execute("SELECT last_insert_rowid()")
        rid = cur.fetchone()[0]

    # Mock httpx client response
    class FakeResponse:
        status_code = 200
        text = '{"jsonrpc": "2.0", "id": "test", "result": {"content": [{"type": "text", "text": "Seoul: Sunny, 20°C"}], "isError": false}}'
        headers = {"content-type": "application/json"}
        def json(self):
            return json.loads(self.text)

    with patch("agent_market.gateway.dashboard.check_public_url"), \
         patch("agent_market.gateway.dashboard.bounded_request", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = FakeResponse()

        payload = {
            "resource_id": rid,
            "tool": "get_weather",
            "arguments": {"city": "Seoul"},
            "timeout_seconds": 10
        }
        res = c.post("/admin/api/test/execute", json=payload, headers=H)
        assert res.status_code == 200
        out = res.json()

        assert out["ok"] is True
        assert out["is_error"] is False
        assert out["status_code"] == 200
        assert out["protocol"] == "mcp"
        assert "Seoul: Sunny" in out["output_text"]
        assert out["request_wire"]["body"]["params"]["name"] == "get_weather"
        assert out["response_wire"]["result"]["isError"] is False
        assert "latency_ms" in out


def test_admin_api_test_execute_a2a_mock(dash):
    world, c = dash

    # Insert a dummy A2A agent
    now = 1700000000.0
    with world.store.tx() as db:
        db.execute(
            """INSERT INTO resources (key, source, kind, name, description, url, category, networks, health_status, active, details, first_seen, last_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "a2a:translate-dummy",
                "manual",
                "a2a",
                "Translation Agent",
                "Multilingual translation A2A agent",
                "https://agent.translate-a2a.net",
                "ai_models",
                "[]",
                "healthy",
                1,
                json.dumps({
                    "card": {
                        "name": "Translation Agent",
                        "endpoints": [{"binding": "JSONRPC", "url": "https://agent.translate-a2a.net/a2a"}],
                        "skills": [{"name": "translate", "description": "Translate text"}]
                    }
                }),
                now,
                now,
            )
        )
        cur = db.execute("SELECT last_insert_rowid()")
        rid = cur.fetchone()[0]

    class FakeA2aResponse:
        status_code = 200
        text = '{"jsonrpc": "2.0", "id": "test", "result": {"message": {"role": "agent", "parts": [{"text": "Hello in Korean is 안녕하세요."}]}, "state": "completed"}}'
        headers = {"content-type": "application/json"}
        def json(self):
            return json.loads(self.text)

    with patch("agent_market.gateway.dashboard.check_public_url"), \
         patch("agent_market.gateway.dashboard.bounded_request", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = FakeA2aResponse()

        payload = {
            "resource_id": rid,
            "message": "Translate hello to Korean",
            "timeout_seconds": 10
        }
        res = c.post("/admin/api/test/execute", json=payload, headers=H)
        assert res.status_code == 200
        out = res.json()

        assert out["ok"] is True
        assert out["is_error"] is False
        assert out["protocol"] == "a2a"
        assert "안녕하세요" in out["output_text"]
        assert out["request_wire"]["body"]["method"] == "message/send"


def test_admin_api_test_execute_validations_and_ssrf(dash):
    world, c = dash

    # Missing resource_id
    res = c.post("/admin/api/test/execute", json={"tool": "test"}, headers=H)
    assert res.status_code == 400

    # Non-existent agent
    res = c.post("/admin/api/test/execute", json={"resource_id": 999999}, headers=H)
    assert res.status_code == 404

    # SSRF protection: private IP URL
    now = 1700000000.0
    with world.store.tx() as db:
        db.execute(
            """INSERT INTO resources (key, source, kind, name, description, url, category, networks, health_status, active, details, first_seen, last_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "mcp:private-ip-ssrf",
                "manual",
                "mcp",
                "Internal Router",
                "Private network target",
                "http://192.168.1.1/mcp",
                "dev_tools",
                "[]",
                "healthy",
                1,
                "{}",
                now,
                now,
            )
        )
        cur = db.execute("SELECT last_insert_rowid()")
        ssrf_rid = cur.fetchone()[0]

    res_ssrf = c.post("/admin/api/test/execute", json={"resource_id": ssrf_rid, "tool": "test"}, headers=H)
    assert res_ssrf.status_code == 400
    assert "보안 정책에 따라 테스트할 수 없는 주소" in res_ssrf.json()["detail"]


def test_admin_ui_drawer_has_test_button_and_search_controls(dash):
    _, c = dash
    r = c.get("/admin/ui")
    assert r.status_code == 200
    html = r.text

    # 1. Drawer has test button next to check and deactivate
    assert 'id="aTest"' in html
    assert "🧪 테스트" in html
    assert "goToAgentTest" in html

    # 2. Testbench search has search and reset buttons
    assert 'id="testSearchBtn"' in html
    assert 'id="testSearchResetBtn"' in html
    assert "parseHashAgentId" in html


def test_admin_api_test_agents_search_and_agent_id_param(dash):
    world, c = dash

    # 1. Add a sample agent with category and description
    now = 1700000000.0
    with world.store.tx() as db:
        db.execute(
            """INSERT INTO resources (key, source, kind, name, description, url, category, networks, health_status, active, details, first_seen, last_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "mcp:special-weather-bot",
                "manual",
                "mcp",
                "Super Weather MCP",
                "Realtime weather forecasting and precipitation radar",
                "https://api.super-weather.io/mcp",
                "travel_maps_weather",
                "[]",
                "healthy",
                1,
                "{}",
                now,
                now,
            )
        )
        cur = db.execute("SELECT last_insert_rowid()")
        w_rid = cur.fetchone()[0]

    # Search by numeric ID
    res_id = c.get(f"/admin/api/test/agents?q={w_rid}", headers=H).json()
    assert any(a["id"] == w_rid for a in res_id["agents"])

    # Search by Korean category name "날씨"
    res_ko = c.get("/admin/api/test/agents?q=날씨", headers=H).json()
    assert any(a["id"] == w_rid for a in res_ko["agents"])

    # Search by partial name
    res_name = c.get("/admin/api/test/agents?q=Super", headers=H).json()
    assert any(a["id"] == w_rid for a in res_name["agents"])

    # Query with agent_id param ensures it is included even with narrow limits
    res_direct = c.get(f"/admin/api/test/agents?limit=1&agent_id={w_rid}", headers=H).json()
    assert any(a["id"] == w_rid for a in res_direct["agents"])


def test_admin_ui_has_tool_custom_input_preset_and_refresh_buttons(dash):
    _, c = dash
    r = c.get("/admin/ui")
    assert r.status_code == 200
    html = r.text

    assert 'id="testToolCustomInput"' in html
    assert 'id="testRefreshToolsBtn"' in html
    assert 'id="testPresetToolsWrap"' in html
    assert 'id="testA2aSkillSelect"' in html
    assert 'id="testX402ActionBox"' in html
    assert "setPresetTool" in html


def test_admin_api_test_agent_spec_live_tool_probing(dash):
    world, c = dash

    # Insert an MCP agent with completely empty tools
    now = 1700000000.0
    with world.store.tx() as db:
        db.execute(
            """INSERT INTO resources (key, source, kind, name, description, url, category, networks, health_status, active, details, usage_guide, first_seen, last_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "mcp:empty-tools-agent",
                "manual",
                "mcp",
                "Live Probe Agent",
                "Agent with no cached tools",
                "https://api.live-probe.org/mcp",
                "dev_tools",
                "[]",
                "healthy",
                1,
                "{}",
                "{}",
                now,
                now,
            )
        )
        cur = db.execute("SELECT last_insert_rowid()")
        rid = cur.fetchone()[0]

    # Mock live tools/list response
    class FakeProbeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = '{"jsonrpc": "2.0", "id": 2, "result": {"tools": [{"name": "live_calculator", "description": "Calculates math expressions", "inputSchema": {"type": "object", "properties": {"expr": {"type": "string"}}}}]}}'
        def json(self):
            return json.loads(self.text)

    with patch("agent_market.gateway.dashboard.check_public_url"), \
         patch("agent_market.gateway.dashboard.bounded_request", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = FakeProbeResponse()

        # Spec request with refresh=1
        res = c.get(f"/admin/api/test/agents/{rid}/spec?refresh=1", headers=H)
        assert res.status_code == 200
        spec = res.json()
        assert len(spec["tools"]) == 1
        assert spec["tools"][0]["name"] == "live_calculator"

        # Verify DB usage_tools was updated
        r_db = world.store.resource(rid)
        assert "live_calculator" in (r_db.get("usage_tools") or "")


def test_admin_ui_has_current_live_examples_and_recipe_runner(dash):
    _, c = dash
    html = c.get('/admin/ui').text
    assert 'id="testWalkthroughCards"' in html
    assert '/admin/api/test/examples' in html
    assert 'renderTestRecipes' in html and 'loadRecipe' in html and 'runRecipe' in html
    assert '100% 정상 처리 보장' not in html
    assert 'agent_id: -1' not in html


def test_admin_api_test_list_contains_only_registered_positive_resources(dash):
    _, c = dash
    rows = c.get('/admin/api/test/agents', headers=H).json()['agents']
    assert rows and all(row['id'] > 0 for row in rows)
    assert c.get('/admin/api/test/examples', headers=H).status_code == 200
    for identity in (-1, -2, -3, -4):
        assert c.get(f'/admin/api/test/agents/{identity}/spec', headers=H).status_code == 404


def test_admin_api_test_never_fabricates_success_for_retired_simulation_ids(dash):
    _, c = dash
    for identity in (-1, -2, -3, -4):
        response = c.post('/admin/api/test/execute', headers=H,
                          json={'resource_id': identity, 'tool': 'get_current_weather', 'arguments': {}})
        assert response.status_code == 404


def test_admin_api_test_execute_external_offline_friendly_hint(dash):
    world, c = dash

    # Insert a dummy agent that will fail with timeout
    now = 1700000000.0
    with world.store.tx() as db:
        db.execute(
            """INSERT INTO resources (key, source, kind, name, description, url, category, networks, health_status, active, details, first_seen, last_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "mcp:offline-agent-test",
                "manual",
                "mcp",
                "Offline Test Agent",
                "Simulated dead agent",
                "https://api.offline-dead-agent.net/mcp",
                "dev_tools",
                "[]",
                "healthy",
                1,
                "{}",
                now,
                now,
            )
        )
        cur = db.execute("SELECT last_insert_rowid()")
        dead_rid = cur.fetchone()[0]

    import httpx
    with patch("agent_market.gateway.dashboard.check_public_url"), \
         patch("agent_market.gateway.dashboard.bounded_request", side_effect=httpx.TimeoutException("Connection timed out")):
        res = c.post(
            "/admin/api/test/execute",
            json={"resource_id": dead_rid, "tool": "ping"},
            headers=H,
        )
        assert res.status_code == 200
        out = res.json()
        assert out["ok"] is False
        assert out["is_error"] is True
        assert "time limit" in out["output_text"]
        assert "100%" not in out["output_text"]



