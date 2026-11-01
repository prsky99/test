import re
import pytest
from starlette.testclient import TestClient
from agent_market.gateway.store import Store
from agent_market.concierge.front import Front, create_front_app

def test_front_idle_resilience_client_and_server_architecture(legacy_public_entry):
    store = Store(":memory:")
    # Seed sample agent
    store.upsert_page([{
        "key": "mcp:https://example.com/mcp",
        "source": "manual",
        "kind": "mcp",
        "url": "https://example.com/mcp",
        "name": "Resilient Test Agent",
        "description": "High-availability test agent node.",
        "category": "dev_tools",
        "networks": ["base"],
        "price_usdc": 0,
        "pay_to": None,
        "method": "POST",
        "details": {"capabilities": ["resilience_probe"]},
        "calls_30d": 10,
        "payers_30d": 2,
        "last_called": None,
    }])
    front = Front(store, allow_private=True)
    app = create_front_app(front)
    client = TestClient(app)

    # 1. Fetch HTML and verify client-side resilience features are present
    res = client.get("/", headers={"accept": "text/html"})
    assert res.status_code == 200
    html = res.text

    # Verify Resilient SWR Cache & In-Memory Explore Map
    assert "EXPLORE_AGENT_MAP" in html
    assert "renderDrawerAgent" in html

    # Verify Stale Socket Dead-Connection Auto-Retry with Timeout in api()
    assert "AbortController" in html
    assert "maxRetries" in html
    assert "no-store" in html
    assert "isNetworkDrop" in html

    # Verify Page Lifecycle & W3C Visibility API Reconnection Engine
    assert "visibilitychange" in html
    assert "handleIdleReconnection" in html
    assert "lastUserActiveTimestamp" in html

    # 2. Test pre-warming HEAD ping (used by browser when tab becomes visible after hours of idle)
    head_res = client.head("/api/overview")
    assert head_res.status_code == 200

    # 3. Test agent specification retrieval endpoint
    rows = store.query("SELECT id FROM resources WHERE name='Resilient Test Agent'")
    assert len(rows) > 0
    rid = rows[0]["id"]

    agent_res = client.get(f"/api/agents/{rid}")
    assert agent_res.status_code == 200
    agent_data = agent_res.json()
    assert agent_data["agent"]["name"] == "Resilient Test Agent"
    assert agent_data["agent"]["kind"] == "mcp"

    # 4. Strict Language Compliance: 0 Korean characters in front.py
    with open("agent_market/concierge/front.py", "r", encoding="utf-8") as f:
        front_code = f.read()
    hangul = re.findall(r'[\uac00-\ud7a3]', front_code)
    assert len(hangul) == 0, f"Found {len(hangul)} Korean characters in front.py"
