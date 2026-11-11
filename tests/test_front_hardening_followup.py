"""Regression checks for strict CSP, bounded egress, token hygiene and deployment."""

import json
import re
import ssl
import stat
from types import SimpleNamespace

import httpcore
import httpx
import pytest
from fastapi.testclient import TestClient

from agent_market.concierge.front import Front, create_front_app
from agent_market.concierge.http_security import (
    BoundedClient, DeadlineStream, OutboundBudget, PublicOnlySyncBackend, _active_budget,
    bounded_client, validate_public_url,
)
from agent_market.concierge.memory import VisitorBook
from agent_market.concierge.token_hygiene import inventory_and_scrub, redact_visitor_tokens
from agent_market.gateway.deployment_security import trusted_proxy_options, validate_production_runtime
from agent_market.gateway.store import Store


def test_csp_uses_fresh_nonce_and_has_no_executable_html_handlers():
    # 11-11 PM decision A: inline scripts are allowed by hash (the page is the same for everyone), not a nonce.
    import base64, hashlib
    client = TestClient(create_front_app(Front(Store())))
    responses = [client.get("/", headers={"accept": "text/html"}) for _ in range(2)]
    policies = [r.headers["content-security-policy"] for r in responses]
    assert policies[0] == policies[1] and responses[0].text == responses[1].text
    for response, policy in zip(responses, policies):
        scripts = re.search(r"script-src ([^;]+)", policy).group(1)
        assert "'unsafe-inline'" not in scripts and "'unsafe-eval'" not in scripts
        assert "script-src-attr 'none'" in policy
        assert "'nonce-" not in policy
        tags = re.findall(r'<script\b([^>]*)>(.*?)</script>', response.text, re.S)
        executable = [(attrs, body) for attrs, body in tags if not re.search(r'type="application/(?:ld\+)?json"', attrs)]
        assert executable
        allowed = set(re.findall(r"'sha256-([^']+)'", policy))
        for attrs, body in executable:
            assert 'src="/' in attrs or base64.b64encode(hashlib.sha256(body.encode()).digest()).decode() in allowed
        assert not re.search(r'\bon(?:click|change|input|submit|mousedown|mouseup)="', response.text)


class Chunks(httpx.SyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    def __iter__(self):
        yield from self.chunks

    def close(self):
        self.closed = True


def test_sync_response_is_stopped_before_reading_the_entire_stream():
    stream = Chunks([b"1234", b"5678", b"never-read"])
    raw = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, stream=stream)))
    client = BoundedClient(raw, limit=6)
    with pytest.raises(httpx.DecodingError, match="larger than"):
        client.get("https://agent.example/")
    assert stream.closed


def test_sync_operation_budget_is_shared_across_requests():
    calls = []
    raw = httpx.Client(transport=httpx.MockTransport(lambda req: calls.append(req) or httpx.Response(200, text="ok")))
    budget = OutboundBudget()
    client = BoundedClient(raw, budget=budget)
    assert client.get("https://agent.example/").text == "ok"
    budget.deadline = 0
    with pytest.raises(httpx.TimeoutException):
        client.get("https://agent.example/")
    assert len(calls) == 1


def test_network_stream_deadline_clamps_each_read():
    timeouts = []
    class Network:
        def read(self, maximum, timeout):
            timeouts.append(timeout)
            return b"x"
    budget = OutboundBudget(0.5)
    token = _active_budget.set(budget)
    try:
        stream = DeadlineStream(Network())
        assert stream.read(1, timeout=15) == b"x"
        assert 0 < timeouts[0] <= 0.5
        budget.deadline = 0
        with pytest.raises(httpx.TimeoutException):
            stream.read(1, timeout=15)
        assert len(timeouts) == 1
    finally:
        _active_budget.reset(token)


def test_sync_client_blocks_private_connections_at_connect_time(monkeypatch):
    monkeypatch.setattr("agent_market.concierge.http_security._resolve_addresses", lambda *args: ["127.0.0.1"])
    with pytest.raises(httpcore.ConnectError, match="non-public"):
        PublicOnlySyncBackend().connect_tcp("rebind.example", 443)


def test_sync_client_has_tls_checks_and_no_environment_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://untrusted.example:9999")
    client = bounded_client()
    try:
        assert client.client._transport._pool._ssl_context.verify_mode == ssl.CERT_REQUIRED
        assert client.client._transport._pool._ssl_context.check_hostname
        assert not client.client._mounts
    finally:
        client.close()


def test_redirects_and_compressed_responses_fail_closed():
    seen = []
    raw = httpx.Client(follow_redirects=True, transport=httpx.MockTransport(
        lambda req: seen.append(req) or httpx.Response(302, headers={"location": "http://127.0.0.1/"})))
    assert BoundedClient(raw).get("https://agent.example/").status_code == 302
    assert len(seen) == 1
    assert seen[0].headers["accept-encoding"] == "identity"
    raw = httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, headers={"content-encoding": "br"}, stream=Chunks([b"x"]))))
    with pytest.raises(httpx.DecodingError, match="Compressed"):
        BoundedClient(raw).get("https://agent.example/")


def test_outbound_request_count_is_bounded():
    raw = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200)))
    client = BoundedClient(raw)
    for _ in range(16):
        client.get("https://agent.example/")
    with pytest.raises(httpx.RequestError, match="count limit"):
        client.get("https://agent.example/")


def test_real_slow_drip_socket_cannot_extend_the_total_deadline():
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "30")
            self.end_headers()
            try:
                for _ in range(30):
                    self.wfile.write(b"x")
                    self.wfile.flush()
                    time.sleep(0.03)
            except (BrokenPipeError, ConnectionResetError):
                pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.02), daemon=True)
    thread.start()
    client = bounded_client(allow_private=True, budget=OutboundBudget(0.18), timeout=5.0)
    try:
        started = time.monotonic()
        with pytest.raises(httpx.TimeoutException):
            client.get(f"http://127.0.0.1:{server.server_port}/")
        assert time.monotonic() - started < 0.65
    finally:
        client.close()
        server.shutdown()
        server.server_close()
def test_token_storage_redacts_text_without_losing_response_token(tmp_path):
    store = Store(str(tmp_path / "tokens.db"))
    client = TestClient(create_front_app(Front(store)))
    response = client.post("/chat", json={"message": "hello"}).json()
    token = response["visitor"]["token"]
    assert token.startswith("vt_") and token not in response["reply"]
    rows = store.query("SELECT text, data FROM agent_messages")
    assert token not in json.dumps([dict(row) for row in rows])
    assert client.get("/me", headers={"x-visitor-token": token}).status_code == 200


def test_legacy_scrub_is_backed_up_idempotent_and_preserves_identity(tmp_path):
    path = tmp_path / "legacy.db"
    store = Store(str(path))
    book = VisitorBook(store)
    visitor = book.create("rest", "Audit", "fingerprint")
    token = visitor.token
    with store.tx() as db:
        db.execute("INSERT INTO agent_messages(visitor_id,at,role,text) VALUES (?,0,'concierge',?)", (visitor.id, "Your token: " + token))
    assert inventory_and_scrub(path)["changed_fields"] == 1
    result = inventory_and_scrub(path, apply=True, backup_dir=tmp_path / "private")
    assert result["changed_fields"] == 1
    from pathlib import Path
    backup = Path(result["private_backup"])
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert token in backup.read_text()
    assert inventory_and_scrub(path)["changed_fields"] == 0
    assert book.by_token(token).id == visitor.id


def test_inquiry_write_boundary_hashes_raw_tokens():
    store = Store()
    token = "vt_" + "x" * 40
    inquiry = store.record_customer_inquiry("general", "Audit", "audit@example.com", "Question", "Hello", visitor_token=token)
    row = store.get_customer_inquiry(inquiry)
    assert token not in json.dumps(row)
    assert len(row["visitor_token"]) == 64


@pytest.mark.parametrize("value", ["*", "0.0.0.0/0", "::/0", "127.0.0.1,*", "unverified-host"])
def test_proxy_trust_rejects_wildcard_and_unverified_sources(value):
    with pytest.raises(ValueError):
        trusted_proxy_options(value)


def test_explicit_proxy_and_production_guards():
    assert trusted_proxy_options("172.30.90.2")["forwarded_allow_ips"] == "172.30.90.2"
    config = SimpleNamespace(agent_front_url="https://agent.example", allow_private_urls=False, ssl_enabled=False, admin_token="a" * 48)
    store = Store()
    env = {"DEPLOYMENT_MODE": "production", "FORWARDED_ALLOW_IPS": "172.30.90.2", "PUBLIC_TLS_TERMINATION": "proxy"}
    with pytest.raises(ValueError, match="Default administrator"):
        validate_production_runtime(config, store, env)
    with store.tx() as db:
        db.execute("UPDATE admin_users SET active=0")
    validate_production_runtime(config, store, env)
    config.allow_private_urls = True
    with pytest.raises(ValueError, match="Private"):
        validate_production_runtime(config, store, env)


def test_fresh_production_database_requires_private_bootstrap_password(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_MODE", "production")
    monkeypatch.delenv("ADMIN_BOOTSTRAP_PASSWORD", raising=False)
    with pytest.raises(ValueError, match="ADMIN_BOOTSTRAP_PASSWORD"):
        Store()


def test_admin_tokens_are_hashed_and_stored_hash_is_not_a_bearer_token(rotated_bootstrap_admin):
    from agent_market.gateway.admin_auth import create_session, get_session_user, delete_session
    store = Store()
    with store.tx() as db:
        user = db.execute("SELECT * FROM admin_users LIMIT 1").fetchone()
        token = create_session(db, user["id"], user["username"], user["role"], user["name"])
        stored = db.execute("SELECT token FROM admin_sessions").fetchone()[0]
        assert stored != token and stored.startswith("sha256:")
        assert get_session_user(db, stored) is None
        assert get_session_user(db, token)["user_id"] == user["id"]
        assert delete_session(db, token)


def test_legacy_admin_session_is_upgraded_without_revoking_its_owner(rotated_bootstrap_admin):
    from agent_market.gateway.admin_auth import create_session, get_session_user
    store = Store()
    with store.tx() as db:
        user = db.execute("SELECT * FROM admin_users LIMIT 1").fetchone()
        token = create_session(db, user["id"], user["username"], user["role"], user["name"])
        db.execute("UPDATE admin_sessions SET token=?", (token,))
        assert get_session_user(db, token)
        assert db.execute("SELECT token FROM admin_sessions").fetchone()[0].startswith("sha256:")
        assert get_session_user(db, token)
