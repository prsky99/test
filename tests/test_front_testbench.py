"""Test suite for Frontend Agent Testbench (#test) and wire inspection sandbox."""

import json
import re
import pytest
from fastapi.testclient import TestClient

from agent_market.concierge.front import FRONT_TESTBENCH_PRESETS, create_front_app
from tests.test_concierge import chat, w  # noqa: F401 (fixture)

pytestmark = pytest.mark.usefixtures('legacy_public_entry')


def test_front_testbench_nav_and_panel_ordering(w):
    world, client, _ = w
    res = client.get("/", headers={"accept": "text/html"})
    assert res.status_code == 200
    html = res.text

    # 1. Navigation Tab ordering: Explore -> Test -> Workflows -> Register
    idx_explore = html.find('data-tab="explore"')
    idx_test = html.find('data-tab="test"')
    idx_workflows = html.find('data-tab="workflows"')
    idx_register = html.find('data-tab="register"')

    assert idx_explore != -1, "Explore tab not found"
    assert idx_test != -1, "Test tab not found"
    assert idx_workflows != -1, "Workflows tab not found"
    assert idx_register != -1, "Register tab not found"
    assert idx_explore < idx_test < idx_workflows < idx_register, "Test tab must be positioned next to Explore, followed by Workflows and Register"

    # 2. Lucide flask-conical SVG icon in Test tab
    test_tab_snippet = html[idx_test - 100:idx_test + 400]
    assert "<svg" in test_tab_snippet
    assert 'M10 2v7.31M14 2v7.31M8.5 2h7M14 9.3a6.5 6.5 0 1 1-4 0' in test_tab_snippet
    assert "<span>Test</span>" in test_tab_snippet

    # 3. Section panel container ordering: secExplore -> secTest -> secWorkflows -> secRegister
    idx_sec_explore = html.find('id="secExplore"')
    idx_sec_test = html.find('id="secTest"')
    idx_sec_workflows = html.find('id="secWorkflows"')
    idx_sec_register = html.find('id="secRegister"')

    assert idx_sec_explore != -1, "secExplore not found"
    assert idx_sec_test != -1, "secTest not found"
    assert idx_sec_workflows != -1, "secWorkflows not found"
    assert idx_sec_register != -1, "secRegister not found"
    assert idx_sec_explore < idx_sec_test < idx_sec_workflows < idx_sec_register, "secTest panel must be next to secExplore, followed by secWorkflows and secRegister"
    assert 'data-panel="test"' in html[idx_sec_test:idx_sec_test + 100]


def test_front_testbench_meta_and_microdata(w):
    world, client, _ = w
    res = client.get("/", headers={"accept": "text/html"})
    assert res.status_code == 200
    html = res.text

    # 1. Page-level head meta tags
    assert '<meta name="page:test:title" content="AgentValCon — Interactive Agent Testbench &amp; Protocol Sandbox">' in html
    assert '<meta name="page:test:target-action" content="test-agent-endpoints">' in html
    assert '<meta name="page:test:retention-hook"' in html

    # 2. Section-level DOM microdata
    idx_sec = html.find('id="secTest"')
    sec_head = html[idx_sec:idx_sec + 700]
    assert 'meta itemprop="name" content="AgentValCon — Interactive Agent Testbench &amp; Protocol Sandbox"' in sec_head
    assert 'meta name="agent:page" content="test"' in sec_head
    assert 'meta name="agent:action" content="test-agent-endpoints"' in sec_head
    assert 'meta name="agent:retention-hook"' in sec_head

    # 3. Client-side PAGE_METAS definition
    assert "test: {" in html
    assert 'action: "test-agent-endpoints"' in html


def test_front_testbench_preset_api_and_details(w):
    world, client, _ = w

    # 1. GET /api/test/presets
    res = client.get("/api/test/presets")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    presets = data["presets"]
    assert len(presets) == 4

    preset_map = {p["id"]: p for p in presets}
    assert -1 in preset_map and preset_map[-1]["kind"] == "mcp"
    assert -2 in preset_map and preset_map[-2]["kind"] == "mcp"
    assert -3 in preset_map and preset_map[-3]["kind"] == "a2a"
    assert -4 in preset_map and preset_map[-4]["kind"] == "x402"

    # 2. GET /api/agents/-1 returns preset directly
    res_agent = client.get("/api/agents/-1")
    assert res_agent.status_code == 200
    agent_data = res_agent.json()["agent"]
    assert agent_data["name"] == "Demo: Weather response format"
    assert agent_data["tools"][0]["name"] == "get_current_weather"


def test_front_testbench_execution_presets(w):
    _,client,_=w
    for rid in (-1,-2,-3,-4):
        payload={'resource_id':rid,'arguments':{}}
        response=client.post('/api/test/execute',json=payload)
        assert response.status_code==200
        result=response.json()
        assert result['simulated'] is True
        assert result['execution_succeeded'] is result['ok'] is False
        assert result['status_code'] is None
        assert result['request_wire']['body']==payload
        assert result['request_wire']['url']=='https://agentconcierge.biz/api/test/execute'
        assert 'No provider was contacted' in result['output']
        assert result['latency_ms']>=0


def test_front_testbench_ssrf_protection(w):
    world, client, _ = w
    store = world.store

    # Insert malicious internal IP endpoints
    bad_id = store.upsert_resource({
        "key": "mcp:evil_loopback",
        "source": "manual",
        "name": "Evil Loopback",
        "description": "Internal test endpoint trying to target private services",
        "url": "http://127.0.0.1:8200/admin/api/test",
        "kind": "mcp",
        "active": 1,
        "category": "dev_tools"
    })

    payload = {
        "resource_id": bad_id,
        "tool": "steal_secrets",
        "arguments": {}
    }
    res = client.post("/api/test/execute", json=payload)
    assert res.status_code == 400
    assert "SSRF security policy" in res.json()["detail"]


def test_front_testbench_strictly_english_no_korean(w):
    world, client, _ = w
    res = client.get("/", headers={"accept": "text/html"})
    assert res.status_code == 200
    html = res.text

    idx_sec = html.find('id="secTest"')
    assert idx_sec != -1
    idx_end = html.find('id="secRegister"')
    sec_html = html[idx_sec:idx_end]

    # Verify zero Korean in #secTest markup
    korean = re.findall(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]", sec_html)
    assert len(korean) == 0, f"Found Korean in #secTest markup: {set(korean)}"

    # Verify zero Korean in preset responses
    for pid in (-1, -2, -3, -4):
        p_res = client.post("/api/test/execute", json={"resource_id": pid})
        p_text = json.dumps(p_res.json())
        k = re.findall(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]", p_text)
        assert len(k) == 0, f"Found Korean in preset {pid} output: {set(k)}"


def test_front_testbench_onclick_event_safety():
    from pathlib import Path
    html = Path("extracted_html.txt").read_text(encoding="utf-8")

    idx_sec = html.find('id="secTest"')
    idx_end = html.find('id="secRegister"')
    sec_html = html[idx_sec:idx_end]

    # Ensure zero inline dynamic interpolations in on* handlers
    unsafe_handlers = [m for m in re.findall(r'\bon[a-z]+="[^"]*?\$\{[^"]*?"', sec_html) if not m.startswith("ontent")]
    assert len(unsafe_handlers) == 0, f"Unsafe inline handler interpolation in #secTest: {unsafe_handlers}"

    # Verify dataset usage
    assert 'data-recipe="${esc(r.id)}" data-ac-click=' in html
    assert 'data-idx="${idx}" data-ac-click=' in html
    assert not re.search(r'\bon(?:click|change|input|submit|mousedown|mouseup)="', html)


def test_front_gateway_non_exposure_in_details_and_testbench(w):
    world, client, _ = w
    store = world.store

    secret_host = "secret-upstream-provider.example.org"
    raw_target_url = f"https://{secret_host}/v1/mcp/rpc"
    rid = store.upsert_resource({
        "key": "mcp:secret_upstream_provider",
        "source": "manual",
        "name": "Gateway Protected Analytics MCP",
        "description": "Analytics tool whose raw upstream URL must remain hidden behind gateway.",
        "url": raw_target_url,
        "kind": "mcp",
        "active": 1,
        "health_status": "healthy",
        "category": "database_analytics",
        "details": json.dumps({
            "endpoint": raw_target_url,
            "card_url": f"https://{secret_host}/.well-known/agent-card.json",
            "documentationUrl": f"https://{secret_host}/docs",
            "tools": [{"name": "run_report", "description": f"Calls https://{secret_host}/v1/mcp/rpc"}]
        }),
    })
    with store.tx() as db:
        db.execute("UPDATE resources SET health_status='healthy', active=1 WHERE id=?", (rid,))
    expected_gw = f"https://agentconcierge.biz/api/gateway/mcp/{rid}"

    # 1. /api/agents/{rid} must return gateway URL and scrub details
    res_detail = client.get(f"/api/agents/{rid}")
    assert res_detail.status_code == 200
    agent_obj = res_detail.json()["agent"]
    assert agent_obj["url"] == expected_gw
    assert agent_obj["usage_endpoint"] == expected_gw
    serialized_detail = json.dumps(agent_obj)
    assert secret_host not in serialized_detail

    # 2. /api/explore and /api/register/recent must expose only gateway URLs
    res_explore = client.get("/api/explore?q=Gateway+Protected+Analytics")
    assert res_explore.status_code == 200
    assert secret_host not in json.dumps(res_explore.json())
    matched = [it for it in res_explore.json().get("items", []) if it.get("id") == rid]
    assert matched and matched[0]["url"] == expected_gw

    res_recent = client.get("/api/register/recent")
    assert res_recent.status_code == 200
    assert secret_host not in json.dumps(res_recent.json())

    # 3. Demo exchanges disclose the actual test request and never fabricate provider connections.
    for pid in (-1, -2, -3, -4):
        p_res = client.post("/api/test/execute", json={"resource_id": pid})
        assert p_res.status_code == 200
        p_data = p_res.json()
        assert p_data["request_wire"]["url"] == "https://agentconcierge.biz/api/test/execute"
        urls_in_resp = re.findall(r"https?://[^\s\"'<>)\]]+", json.dumps(p_data))
        for u in urls_in_resp:
            assert u.startswith("https://agentconcierge.biz/"), f"Non-gateway URL leaked in preset {pid}: {u}"

