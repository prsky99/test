"""Integration tests for P4: A402 Virtual Escrow & Dynamic REST ↔ MCP Universal Adapter."""

import json
import httpx
import pytest
from starlette.testclient import TestClient

from agent_market.concierge.clearinghouse import Clearinghouse
from agent_market.concierge.front import Front, create_front_app
from agent_market.concierge.proxy import McpProxy
from agent_market.gateway.store import Store


@pytest.fixture
def test_env():
    store = Store(":memory:")
    clearinghouse = Clearinghouse(store)
    return store, clearinghouse


def test_proxy_paid_mcp_settlement_and_refund(test_env):
    store, clearinghouse = test_env

    # 1. Register a paid MCP resource (price: 50,000 micro-USDC = 0.05 USDC)
    from agent_market.collector import usage
    tool_spec = [{"name": "premium_calc", "description": "High precision math", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}}]
    compact = usage.compact_tools(tool_spec)
    usage_json = json.dumps(compact)
    schema_hash = usage.tools_hash(compact)

    rid = store.upsert_resource({
        "key": "mcp:https://premium.example/mcp",
        "source": "mcp-registry",
        "kind": "mcp",
        "url": "https://premium.example/mcp",
        "name": "Premium Math MCP",
        "description": "Paid compute MCP server",
        "category": "developer_tools",
        "price_usdc": 50_000,
        "pay_to": "0x1234567890123456789012345678901234567890",
    })
    with store.tx() as db:
        db.execute("UPDATE resources SET usage_tools=?, usage_tools_hash=?, health_status='healthy' WHERE id=?",
                   (usage_json, schema_hash, rid))

    # Mock remote server responses
    should_succeed = True

    def handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.read())
        method = data.get("method")
        if method == "server/discover":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2026-07-28"}})
        if method == "tools/list":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 2, "result": {"tools": tool_spec}})
        if method == "tools/call":
            if should_succeed:
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": 3, "result": {"content": [{"type": "text", "text": "42"}]}})
            else:
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": 3, "result": {"isError": True, "content": [{"type": "text", "text": "Compute overflow"}]}})
        return httpx.Response(404)

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    proxy = McpProxy(store, allow_private=True, http=mock_client, clearinghouse=clearinghouse)

    # Attempt 1: Call without credit account -> Payment Required
    res = proxy.execute(rid, "premium_calc", {})
    assert res["ok"] is False
    assert res.get("payment_required") is True
    assert res["price_usdc"] == 50_000

    # Attempt 2: Insufficient credits
    clearinghouse.deposit("agent_x", 20_000)
    res = proxy.execute(rid, "premium_calc", {}, account_id="agent_x")
    assert res["ok"] is False
    assert res.get("payment_required") is True
    assert "Insufficient" in res["error"]

    # Attempt 3: Deposit enough funds -> Successful execution and SLA escrow settlement
    clearinghouse.deposit("agent_x", 100_000)  # total 120,000
    res = proxy.execute(rid, "premium_calc", {}, account_id="agent_x")
    assert res["ok"] is True
    assert res["result"]["content"][0]["text"] == "42"
    assert "payment" in res
    assert res["payment"]["status"] == "settled"
    assert res["payment"]["amount"] == 50_000
    assert "receipt" in res["payment"]

    bal = clearinghouse.balance("agent_x")
    assert bal["balance"] == 70_000
    assert bal["held"] == 0
    assert bal["available"] == 70_000

    # Attempt 4: Upstream tool fails -> Escrow refunded, no credits lost!
    should_succeed = False
    res_fail = proxy.execute(rid, "premium_calc", {}, account_id="agent_x")
    assert res_fail["ok"] is False
    assert "payment" in res_fail
    assert res_fail["payment"]["status"] == "refunded"
    assert res_fail["payment"]["amount"] == 50_000

    bal_after = clearinghouse.balance("agent_x")
    assert bal_after["balance"] == 70_000
    assert bal_after["held"] == 0
    assert bal_after["available"] == 70_000


def test_proxy_x402_resource(test_env):
    store, clearinghouse = test_env

    rid = store.upsert_resource({
        "key": "x402:https://serp.example/api",
        "source": "x402-bazaar",
        "kind": "x402",
        "url": "https://serp.example/api",
        "name": "SERP Search API",
        "description": "Paid x402 search API",
        "category": "web_search",
        "price_usdc": 10_000,
        "pay_to": "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "method": "POST",
    })
    with store.tx() as db:
        db.execute("UPDATE resources SET health_status='healthy' WHERE id=?", (rid,))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": ["https://site1.com", "https://site2.com"]})

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    proxy = McpProxy(store, allow_private=True, http=mock_client, clearinghouse=clearinghouse)

    clearinghouse.deposit("agent_buyer", 50_000)
    res = proxy.execute(rid, "search", {"query": "python ai"}, account_id="agent_buyer")

    assert res["ok"] is True
    assert res["status_code"] == 200
    assert len(res["result"]["results"]) == 2
    assert res["payment"]["status"] == "settled"
    assert res["payment"]["amount"] == 10_000

    bal = clearinghouse.balance("agent_buyer")
    assert bal["available"] == 40_000


def test_mcp_front_credit_tool():
    store = Store(":memory:")
    front = Front(store, allow_private=True)
    app = create_front_app(front)
    client = TestClient(app)

    # 1. Initialize
    init = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    sid = init.headers.get("mcp-session-id")

    # 2. Authenticate the account owner before reading a balance.
    hello = client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 10, "method": "tools/call",
        "params": {"name": "hello", "arguments": {}}
    }).json()["result"]["structuredContent"]
    token = hello["visitor"]["token"]
    account = hello["visitor"]["id"]
    check = client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "credit", "arguments": {"action": "balance", "account_id": account}}
    }, headers={"mcp-session-id": sid, "X-Visitor-Token": token}).json()["result"]
    assert check["structuredContent"]["credits"]["balance"] == 0

    # 3. Public requests cannot mint credits without a verified settlement.
    dep = client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "credit", "arguments": {"action": "deposit", "amount": 250_000, "account_id": account}}
    }, headers={"mcp-session-id": sid, "X-Visitor-Token": token}).json()
    assert dep["error"]["code"] == -32602
    assert front.clearinghouse.balance(account)["balance"] == 0


def test_mcp_front_adapt_rest_tool(monkeypatch):
    import socket
    # The public adapter still validates DNS even when the runtime permits private jobs.
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))])
    store = Store(":memory:")
    front = Front(store, allow_private=True)
    app = create_front_app(front)
    client = TestClient(app)

    spec = {
        "openapi": "3.0.0",
        "servers": [{"url": "https://echo.example/api"}],
        "paths": {
            "/greet": {
                "get": {
                    "operationId": "get_greeting",
                    "summary": "Greets user",
                    "parameters": [{"name": "name", "in": "query", "schema": {"type": "string"}}],
                }
            }
        },
    }

    # 1. List tools from OpenAPI spec
    list_res = client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "adapt_rest", "arguments": {"spec": spec, "action": "list_tools"}}
    }).json()["result"]

    assert list_res["structuredContent"]["tools_count"] == 1
    assert list_res["structuredContent"]["tools"][0]["name"] == "get_greeting"
    assert "Adapted 1 MCP tools" in list_res["content"][0]["text"]

    # 2. Call adapted tool
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": f"Hello {request.url.params.get('name')}!"})

    front.proxy._http = httpx.Client(transport=httpx.MockTransport(handler))

    call_res = client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {
            "name": "adapt_rest",
            "arguments": {"spec": spec, "action": "call", "tool": "get_greeting", "arguments": {"name": "Nexus"}}
        }
    }).json()["result"]

    assert call_res["structuredContent"]["tool"] == "get_greeting"
    assert call_res["structuredContent"]["execution"]["ok"] is True
    assert "Hello Nexus!" in call_res["content"][0]["text"]
