"""Truthful public tool hints and payment/security disclosures; no real providers."""

# ruff: noqa: F811 -- pytest fixture imported for dependency injection.
import base64
import copy
import json
from unittest.mock import AsyncMock, Mock

import pytest

from agent_market.concierge.execution_policy import ExecutionDenied
from tests.test_fast_single_recommendation import catalog  # noqa: F401


def rpc(client, name, arguments=None, token=None):
    headers = {"X-Visitor-Token": token} if token else {}
    return client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        },
    ).json()["result"]


def state(store):
    tables = ("agent_visitors", "agent_messages", "agent_interests", "agent_contexts")
    return {
        table: [dict(row) for row in store.query("SELECT * FROM " + table)]
        for table in tables
    }


@pytest.mark.parametrize("name", ["search", "find_agents", "search_workflows"])
@pytest.mark.parametrize("identified", [False, True])
def test_lookup_does_not_create_or_change_conversation(catalog, name, identified):
    store, front, client, add, now = catalog
    add("Weather forecast", report_at=now)
    token = None
    if identified:
        token = client.post(
            "/chat", json={"message": "weather forecast for Seoul"}
        ).json()["visitor"]["token"]
    before = state(store)
    front.proxy.execute = Mock(
        side_effect=AssertionError("Discovery cannot execute providers")
    )
    result = rpc(
        client, name, {"task": "weather forecast for Tokyo", "kind": "mcp"}, token
    )
    data = result["structuredContent"]
    assert not result["isError"]
    assert data["conversation_recorded"] is False and data["visitor"] is None
    if name != "search_workflows":
        assert data["recommendations"]
        assert data["continuation_plan"]["start_conversation"]["tool"] == "chat"
    assert state(store) == before
    front.proxy.execute.assert_not_called()


def test_whats_new_reads_saved_chat_task_without_overwriting_it(catalog):
    store, _, client, add, now = catalog
    rid = add("Weather forecast", report_at=now)
    session = client.post(
        "/chat", json={"message": "MCP weather forecast for Seoul"}
    ).json()
    token = session["visitor"]["token"]
    rpc(client, "search", {"task": "PostgreSQL administration"}, token)
    before = state(store)
    data = rpc(client, "whats_new", token=token)["structuredContent"]
    assert data["recommendations"][0]["id"] == rid
    assert data["task"] == session["data"]["task"]
    assert state(store) == before


@pytest.mark.parametrize("token", [None, "vt_unknown"])
def test_whats_new_explains_missing_context_without_issuing_identity(catalog, token):
    store, _, client, _, _ = catalog
    before = state(store)
    result = rpc(client, "whats_new", token=token)
    assert result["isError"]
    assert result["structuredContent"]["status"] == "task_context_required"
    assert "chat" in result["content"][0]["text"]
    assert state(store) == before


def test_hints_agree_in_runtime_and_discovery_documents(catalog):
    _, _, client, _, _ = catalog
    tools = client.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    ).json()["result"]["tools"]
    assert tools == client.get("/.well-known/mcp.json").json()["tools"]
    by_name = {tool["name"]: tool for tool in tools}
    for name in ("search", "find_agents", "whats_new", "search_workflows"):
        assert by_name[name]["annotations"] == {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
    for name in ("hello", "chat", "report"):
        assert not by_name[name]["annotations"]["readOnlyHint"]
    # call relays only read-only tools (not destructive, open world); adapt_rest can send POST/PUT/DELETE.
    assert not by_name["call"]["annotations"]["destructiveHint"] and by_name["call"]["annotations"]["openWorldHint"]
    assert by_name["adapt_rest"]["annotations"]["destructiveHint"]
    assert client.get("/.well-known/mcp/server.json").status_code == 200


@pytest.mark.parametrize("name", ["search", "find_agents"])
def test_readonly_lookup_masks_sensitive_input(catalog, name):
    store, _, client, _, _ = catalog
    before = state(store)
    data = rpc(
        client, name, {"task": "weather API using api_key=" + "sk_" + "live_123456789012345678901234"}
    )
    assert "sk_live_" not in json.dumps(data)
    assert not data["structuredContent"]["recommendations"]
    assert state(store) == before


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("method", ["get", "post"])
def test_first_payment_challenge_explains_inspection_only(catalog, version, method):
    _, front, client, add, _ = catalog
    rid = add("Payment inspection", kind="x402", price=100)
    front.security.allow_probe = lambda *a, **kw: True
    terms = {
        "scheme": "exact",
        "network": "eip155:8453",
        "asset": "0x" + "11" * 20,
        "payTo": "0x" + "22" * 20,
        "amount" if version == 2 else "maxAmountRequired": "100",
        "maxTimeoutSeconds": 60,
    }
    raw = {
        "x402Version": version,
        "error": "Payment required",
        "accepts": [terms],
        "resource": {"url": "https://provider.example/api"},
    }
    original = copy.deepcopy(raw)
    front.managed_gateway.execute = AsyncMock(
        return_value={"status_code": 402, "protocol_valid": True, "output": raw}
    )
    kwargs = {"json": {"action": "probe"}} if method == "post" else {}
    response = getattr(client, method)(f"/api/gateway/x402/{rid}", **kwargs)
    assert response.status_code == 402
    body = response.json()
    assert body["gateway_mode"] == "inspection_only" and body["inspection_only"] is True
    assert all(
        body[key] is False
        for key in (
            "payment_processed",
            "payment_accepted",
            "payment_forwarded",
            "settlement_performed",
        )
    )
    assert "Do not submit payment proofs here" in body["instructions"]
    assert body["next_action"]["action"] == "review_provider_terms"
    assert (
        body["accepts"] == original["accepts"]
        and body["resource"] == original["resource"]
    )
    assert body["x402Version"] == version and raw == original
    assert response.headers["x-agentconcierge-payment-mode"] == "inspection-only"
    if version == 2:
        assert (
            json.loads(base64.b64decode(response.headers["payment-required"])) == body
        )
    else:
        assert "payment-required" not in response.headers


@pytest.mark.parametrize("kind", ["mcp", "a2a", "x402"])
@pytest.mark.parametrize("late", [False, True])
def test_policy_403_is_actionable_and_keeps_protection(catalog, late, kind):
    _, front, client, add, _ = catalog
    rid = add("Security review", kind=kind, eval_security="review" if not late else "safe")
    front.security.allow_probe = lambda *a, **kw: True
    front.managed_gateway.execute = AsyncMock(
        side_effect=ExecutionDenied(
            "private policy diagnostic", error_code="POLICY_DENIED"
        )
    )
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "forecast", "arguments": {"city": "Seoul"}}}
    if kind == "a2a":
        body.update(method="message/send", params={"message": {"parts": [{"kind": "text", "text": "weather"}]}})
    elif kind == "x402":
        body = {"action": "probe"}
    response = client.post(f"/api/gateway/{kind}/{rid}", json=body)
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["error_code"] == "POLICY_DENIED" and body["retryable"] is False
    assert "Choose another agent" in body["detail"]
    assert body["next_action"]["action"] == "choose_another_agent"
    assert (
        "private policy" not in response.text
        and "not permitted for this connection" not in response.text
    )
    if not late:
        front.managed_gateway.execute.assert_not_called()


def test_blocked_access_does_not_publish_internal_reason(catalog, monkeypatch):
    _, front, client, _, _ = catalog
    monkeypatch.setattr(
        front.security, "is_blocked", lambda *a, **kw: (True, "private internal rule")
    )
    response = client.get("/api/explore")
    assert response.status_code == 403
    assert response.json()["error_code"] == "ACCESS_BLOCKED"
    assert "contact support" in response.json()["detail"]
    assert "private internal" not in response.text
