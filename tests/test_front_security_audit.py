"""Adversarial regressions for the public front; no external targets are contacted."""

import asyncio
import json
import socket

import httpcore
import httpx
import pytest
from fastapi.testclient import TestClient

from agent_market.concierge.front import MAX_BODY, Front, create_front_app
from agent_market.gateway.store import Store


@pytest.fixture
def target():
    store = Store(":memory:")
    front = Front(store)
    with TestClient(create_front_app(front), raise_server_exceptions=False) as client:
        yield front, client


JSON_ROUTES = ["/api/workflows/run", "/api/register/inspect", "/api/register",
               "/api/test/execute", "/api/contact/submit", "/api/privacy/opt-out",
               "/unsubscribe", "/chat", "/mcp", "/a2a"]


@pytest.mark.parametrize("path", JSON_ROUTES)
@pytest.mark.parametrize("chunked", [False, True])
def test_all_body_readers_enforce_size_limit(target, path, chunked):
    _, client = target
    body = json.dumps({"nodes": [{"id": "n"}], "padding": "A" * MAX_BODY}).encode()
    content = iter([body[:200], body[200:]]) if chunked else body
    response = client.post(path, content=content, headers={"content-type": "application/json"})
    assert response.status_code == 413
    assert response.headers.get("x-content-type-options") == "nosniff"


@pytest.mark.parametrize("path", JSON_ROUTES[:5])
@pytest.mark.parametrize("body", [None, [], "text", 12])
def test_object_routes_reject_wrong_json_types(target, path, body):
    _, client = target
    response = client.post(path, content=json.dumps(body), headers={"content-type": "application/json"})
    assert response.status_code == 400


def test_untrusted_peer_cannot_spoof_a_ban_or_rate_limit(target):
    front, _ = target
    front.security.ban_ip("203.0.113.44", "Audit ban")
    with TestClient(create_front_app(front), client=("203.0.113.44", 9000)) as client:
        response = client.get("/api/test/presets", headers={"x-forwarded-for": "203.0.113.45"})
        assert response.status_code == 403
        assert response.headers.get("content-security-policy")


@pytest.mark.parametrize("path", ["/.env", "/.git/config", "/admin/ui", "/docs", "/not-found"])
def test_error_responses_keep_security_headers(target, path):
    _, client = target
    response = client.get(path)
    assert response.status_code in (403, 404)
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"
    assert response.headers.get("cache-control") == "no-store"


@pytest.mark.parametrize("timeout", ["bad", [], {}, "NaN", "Infinity"])
def test_testbench_timeout_is_finite_number(target, timeout):
    _, client = target
    response = client.post("/api/test/execute", json={"resource_id": -1, "timeout_seconds": timeout})
    assert response.status_code == 400


@pytest.mark.parametrize("nodes", [[None], ["node"], [12], [{"id": {}}], [{"data": []}],
                                  [{"id": "n"}] * 101])
def test_workflow_graph_validation(target, nodes):
    _, client = target
    response = client.post("/api/workflows/run", json={"nodes": nodes})
    assert response.status_code == 400


@pytest.mark.parametrize("params", [[1], "text", {"clientInfo": [1]}, {"clientInfo": "text"}])
def test_mcp_malformed_params_return_protocol_error(target, params):
    _, client = target
    response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": params})
    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32602


def rpc(client, name, arguments, token=None):
    return client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments}},
        headers={"x-visitor-token": token} if token else {}).json()


def test_mcp_credit_cannot_mint_funds_or_read_another_account(target):
    front, client = target
    front.clearinghouse.deposit("victim", 100)
    for action in ("deposit", "balance"):
        response = rpc(client, "credit", {"action": action, "account_id": "victim", "amount": 999})
        assert "error" in response
    assert front.clearinghouse.balance("victim")["balance"] == 100


def test_mcp_call_cannot_charge_someone_elses_account(target, monkeypatch):
    front, client = target
    calls = []
    monkeypatch.setattr(front.proxy, "execute", lambda *args: calls.append(args) or {"ok": False})
    response = rpc(client, "call", {"resource_id": 1, "tool": "read", "account_id": "victim"})
    assert "error" in response
    assert not calls


def test_authenticated_credit_is_read_only_and_bound_to_owner(target):
    front, client = target
    hello = rpc(client, "hello", {})["result"]["structuredContent"]["visitor"]
    token, account = hello["token"], hello["id"]
    front.clearinghouse.deposit(account, 50)
    balance = rpc(client, "credit", {"action": "balance"}, token)["result"]
    assert balance["structuredContent"]["credits"]["balance"] == 50
    assert "error" in rpc(client, "credit", {"action": "deposit", "amount": 999}, token)
    assert front.clearinghouse.balance(account)["balance"] == 50


def test_trusted_proxy_uses_rightmost_untrusted_hop(target):
    front, _ = target
    front.security.ban_ip("203.0.113.44", "Audit ban")
    with TestClient(create_front_app(front), client=("127.0.0.1", 9000)) as client:
        response = client.get("/api/test/presets", headers={
            "x-forwarded-for": "198.51.100.1, 203.0.113.44",
            "cf-connecting-ip": "198.51.100.1", "x-real-ip": "198.51.100.1"})
        assert response.status_code == 403


def test_host_header_cannot_poison_public_links(target):
    _, client = target
    response = client.get("/", headers={"host": "attacker.example"})
    assert "attacker.example" not in response.text


def test_public_agent_metadata_redacts_credentials(target):
    front, client = target
    rid = front.store.upsert_resource({"key": "audit-secret", "source": "audit", "kind": "mcp",
        "url": "https://public.example/mcp", "name": "Audit", "description": "Audit agent", "category": "dev_tools",
        "networks": [], "details": {"headers": {"Authorization": "Bearer audit-secret-marker", "X-API-Key": "audit-key-marker"}}})
    response = client.get(f"/api/agents/{rid}")
    assert response.status_code == 200
    assert "audit-secret-marker" not in response.text
    assert "audit-key-marker" not in response.text
    assert "details" not in response.json()["agent"]


def test_concurrency_limit_releases_slots_and_returns_security_headers(target):
    front, client = target
    front.security.max_concurrent_requests = 1
    assert front.security.try_acquire_request_slot()
    response = client.get("/api/test/presets")
    assert response.status_code == 503
    assert response.headers.get("content-security-policy")
    front.security.release_request_slot()
    assert client.get("/api/test/presets").status_code == 200


def test_nested_list_markup_cannot_bypass_ingestion_checks():
    from agent_market.concierge.security import check_malicious_dict
    assert check_malicious_dict({"nested": [["<svg/onload=alert(1)>"]]})[0]


def test_a2a_context_binding_distinguishes_clients_behind_trusted_proxy(target):
    _, client = target
    def send(ip):
        return client.post("/a2a", json={"jsonrpc": "2.0", "id": 1, "method": "message/send",
            "params": {"message": {"contextId": "shared-context", "parts": [{"text": "hello"}]}}},
            headers={"x-forwarded-for": ip, "user-agent": "SameAgent/1.0"}).json()
    first = send("203.0.113.20")
    owner = first["result"]["parts"][1]["data"]["visitor"]["id"]
    # Another client behind the proxy cannot join that context, even with the same User-Agent.
    other = send("203.0.113.21")
    assert other["error"]["code"] == -32602 and owner not in json.dumps(other)
    assert send("203.0.113.20")["result"]["parts"][1]["data"]["visitor"]["id"] == owner


def test_contact_inquiry_does_not_persist_bearer_token(target):
    front, client = target
    response = client.post("/api/contact/submit", headers={"x-visitor-token": "vt_private_credential"},
        json={"name": "Audit agent", "email": "audit@example.com", "subject": "Security audit", "message": "Local test inquiry"})
    assert response.status_code == 200
    row = dict(front.store.query("SELECT * FROM customer_inquiries")[0])
    assert "vt_private_credential" not in json.dumps(row)


def test_templates_failure_does_not_disclose_internal_exception(target, monkeypatch):
    _, client = target
    def fail(*args, **kwargs):
        raise RuntimeError("private-database-path secret credential")
    monkeypatch.setattr("agent_market.concierge.front.get_front_workflow_templates", fail)
    response = client.get("/api/workflows/templates")
    assert response.status_code == 500
    assert "private-database-path" not in response.text


def test_a2a_testbench_checks_actual_endpoint(target, monkeypatch):
    from unittest.mock import Mock
    front, client = target
    rid = front.store.upsert_resource({"key":"audit-a2a","source":"audit","kind":"a2a",
        "url":"https://public.example/a2a","name":"Audit","description":"Audit agent","category":"dev_tools",
        "networks":[],"details":{"endpoints":[{"binding":"JSONRPC","url":"http://127.0.0.1/private"}]}})
    with front.store.tx() as db:db.execute("UPDATE resources SET health_status='healthy' WHERE id=?",(rid,))
    resolve=Mock(side_effect=AssertionError('No private destination may be resolved'))
    send=Mock(side_effect=AssertionError('No private destination may be contacted'))
    monkeypatch.setattr(front.courier,'resolve',resolve)
    monkeypatch.setattr(front.courier,'_request',send)
    response=client.post('/api/test/execute',json={'resource_id':rid,'message':'Summarize a research topic.'})
    assert response.status_code==400
    assert not resolve.called and not send.called


def test_oversized_remote_testbench_response_is_stopped(target, monkeypatch):
    from agent_market.collector import usage
    from agent_market.concierge.proxy import McpProxy
    front, client=target
    rid=front.store.upsert_resource({'key':'audit-mcp','source':'audit','kind':'mcp','url':'https://public.example/mcp',
        'name':'Audit','description':'Audit agent','category':'dev_tools','networks':[]})
    tools=[{'name':'read','inputSchema':{'type':'object','properties':{}}}]
    compact=usage.compact_tools(tools)
    front.store.record_usage(rid,tools=compact,digest=usage.tools_hash(compact),guide={},changes=None,trial={'ok':True})
    with front.store.tx() as db:db.execute("UPDATE resources SET health_status='healthy' WHERE id=?",(rid,))
    calls=[]
    def remote(request):
        calls.append(request)
        return httpx.Response(200,content=b'A'*(1024*1024+1))
    front.proxy=McpProxy(front.store,allow_private=True,http=httpx.Client(transport=httpx.MockTransport(remote)))
    response=client.post('/api/test/execute',json={'resource_id':rid,'tool':'read'})
    assert calls and response.json()['ok'] is False
    assert len(response.content)<10000


def test_connect_time_dns_rebinding_is_blocked(monkeypatch):
    from agent_market.concierge.http_security import PublicOnlyAsyncBackend
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(httpcore.ConnectError, match="non-public"):
        asyncio.run(PublicOnlyAsyncBackend().connect_tcp("rebind.example", 443))
