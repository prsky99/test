"""Isolated ingress attribution and bounded blocked-request regressions."""

from pathlib import Path
from types import SimpleNamespace
import threading
import time
import sqlite3

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from starlette.datastructures import Headers
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Route

from agent_market.concierge.front import Front, create_front_app
from agent_market.concierge.security import BLOCKED_EVENT_LIMIT, BLOCKED_PEER_LIMIT, SecurityManager
from agent_market.gateway.deployment_security import (
    TrustedIngressMiddleware, forwarded_client, trusted_proxy_networks, trusted_proxy_options,
)
from agent_market.gateway.store import Store


@pytest.fixture
def isolated(monkeypatch):
    # No production Redis connection, keys, server, filesystem, or databases.
    monkeypatch.setattr("agent_market.concierge.security.RedisHub.get_instance",
                        lambda: SimpleNamespace(is_available=lambda: False))
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "127.0.0.1,::1")
    return Store(":memory:")


def request(peer, forwarded=None, **headers):
    if forwarded is not None:
        headers["x-forwarded-for"] = forwarded
    return Request({"type": "http", "client": (peer, 40000), "headers":
                    [(k.encode(), v.encode()) for k, v in headers.items()]})


def test_shared_proxy_does_not_share_a_scanners_ban(isolated):
    front = Front(isolated)
    proxy = TrustedIngressMiddleware(create_front_app(front), trusted_proxy_networks("127.0.0.1"))
    with TestClient(proxy, client=("127.0.0.1", 45678)) as client:
        scanner = {"x-forwarded-for": "198.51.100.11"}
        legitimate = {"x-forwarded-for": "198.51.100.12"}
        assert client.get("/.env", headers=scanner).status_code == 403
        assert client.get("/robots.txt", headers=scanner).status_code == 403
        assert client.get("/robots.txt", headers=legitimate).status_code == 200
    assert front.security.is_blocked("127.0.0.1")[0] is False
    assert front.security.get_status()["blocked_403"] == 1
    assert len(front.security.get_events(event_type="blocked_ip_403")) == 1


def test_untrusted_peer_cannot_spoof_any_forwarding_header(isolated):
    sec = SecurityManager(isolated)
    peer = "198.51.100.30"
    assert sec.resolve_ip(request(peer, "203.0.113.9", **{
        "cf-connecting-ip": "203.0.113.8", "x-real-ip": "203.0.113.7"})) == peer
    assert sec.resolve_ip(request("127.0.0.1", **{"cf-connecting-ip": "203.0.113.8"})) == "127.0.0.1"


def test_ipv4_ipv6_chain_uses_rightmost_untrusted_hop(isolated):
    sec = SecurityManager(isolated, trusted_proxies=["10.0.0.0/24", "2001:db8:1::/48"])
    req = request("10.0.0.2", "203.0.113.99, 198.51.100.8, 2001:db8:1::a")
    assert sec.resolve_ip(req) == "198.51.100.8"
    assert sec.resolve_ip(request("2001:db8:1::b", "2001:db8:2::7, 10.0.0.2")) == "2001:db8:2::7"
    # A trusted transport peer with no usable client must not be auto-jailed.
    sec.record_violation("10.0.0.2", "scanner_probe", "/.env", "GET", None, "test")
    assert not sec.is_blocked("10.0.0.2")[0]


@pytest.mark.parametrize("value", ["*,198.51.100.1", "0.0.0.0/0", "::/0", "untrusted-host", "fe80::1%eth0"])
def test_invalid_proxy_configuration_fails_closed(value):
    with pytest.raises(ValueError):
        trusted_proxy_networks(value)


@pytest.mark.parametrize("forwarded", ["198.51.100.2,invalid", "", ",198.51.100.2",
                                      ",".join(["198.51.100.2"] * 17), "x" * 2049, "fe80::1%eth0"])
def test_malformed_or_excessive_chain_uses_socket_peer(isolated, forwarded):
    sec = SecurityManager(isolated, trusted_proxies=["10.0.0.1"])
    assert sec.resolve_ip(request("10.0.0.1", forwarded)) == "10.0.0.1"


def test_duplicate_xff_fields_are_one_bounded_chain():
    networks = trusted_proxy_networks("10.0.0.0/24")
    headers = Headers(raw=[(b"x-forwarded-for", b"203.0.113.99"),
                           (b"x-forwarded-for", b"198.51.100.9, 10.0.0.8")])
    assert forwarded_client("10.0.0.2", headers, networks) == "198.51.100.9"


def test_no_trusted_proxy_is_a_supported_explicit_policy(isolated):
    sec = SecurityManager(isolated, trusted_proxies=[])
    assert sec.resolve_ip(request("127.0.0.1", "198.51.100.2")) == "127.0.0.1"


def test_ingress_resolves_once_before_all_identity_consumers(isolated):
    captured = []
    # SecurityManager deliberately has a different trust policy: the outer
    # middleware's internal scope marker is the sole resolved identity.
    sec = SecurityManager(isolated, trusted_proxies=["198.51.100.0/24"])

    async def endpoint(req):
        captured.append((req.client.host, sec.resolve_ip(req), req.url.scheme))
        return Response()

    middleware = TrustedIngressMiddleware(Starlette(routes=[Route("/", endpoint)]), trusted_proxy_networks("10.0.0.1"))
    with TestClient(middleware, client=("10.0.0.1", 40000)) as client:
        assert client.get("/", headers={"x-forwarded-for": "203.0.113.99, 198.51.100.8",
                                         "x-forwarded-proto": "https"}).status_code == 200
    assert captured == [("198.51.100.8", "198.51.100.8", "https")]


def test_untrusted_peer_cannot_set_https_or_client_identity():
    captured = []

    async def endpoint(req):
        captured.append((req.client.host, req.url.scheme))
        return Response()

    app = Starlette(routes=[Route("/", endpoint)])
    with TestClient(TrustedIngressMiddleware(app, trusted_proxy_networks("10.0.0.1")),
                    client=("198.51.100.9", 40000)) as client:
        client.get("/", headers={"x-forwarded-for": "203.0.113.2", "x-forwarded-proto": "https"})
    assert captured == [("198.51.100.9", "http")]


@pytest.mark.parametrize("values", [["https", "http"], ["https,http"], ["wss"], ["javascript"]])
def test_ambiguous_or_invalid_forwarded_scheme_is_ignored(values):
    captured = []

    async def endpoint(req):
        captured.append(req.url.scheme)
        return Response()

    middleware = TrustedIngressMiddleware(Starlette(routes=[Route("/", endpoint)]), trusted_proxy_networks("10.0.0.1"))
    with TestClient(middleware, client=("10.0.0.1", 40000)) as client:
        client.get("/", headers=[("x-forwarded-proto", value) for value in values])
    assert captured == ["http"]


def test_blocked_counter_counts_all_requests_but_persistence_is_bounded(isolated, monkeypatch):
    sec = SecurityManager(isolated)
    ip = "198.51.100.40"
    sec.ban_ip(ip, "isolated test")
    clock = [100.0]
    monkeypatch.setattr("agent_market.concierge.security.time.monotonic", lambda: clock[0])
    for _ in range(1000):
        sec.record_blocked(ip, "/robots.txt", "GET", None, "isolated test")
    status = sec.get_status()
    assert status["blocked_403"] == 1000
    assert status["blocked_403_sampled"] == 1
    assert status["blocked_403_suppressed"] == 999
    assert len(sec.get_events(event_type="blocked_ip_403")) == 1
    assert isolated.query("SELECT blocked_hits FROM security_ip_rules WHERE ip=?", (ip,))[0]["blocked_hits"] == 1
    clock[0] += 61
    sec.record_blocked(ip, "/robots.txt", "GET", None, "isolated test")
    assert isolated.query("SELECT blocked_hits FROM security_ip_rules WHERE ip=?", (ip,))[0]["blocked_hits"] == 1001


def test_blocked_sampling_has_global_and_memory_limits(isolated, monkeypatch):
    sec = SecurityManager(isolated)
    monkeypatch.setattr("agent_market.concierge.security.time.monotonic", lambda: 100.0)
    for index in range(BLOCKED_PEER_LIMIT + 50):
        sec.record_blocked(f"2001:db8::{index:x}", "/", "GET", None, "isolated test")
    assert sec.get_status()["blocked_403"] == BLOCKED_PEER_LIMIT + 50
    assert len(sec._blocked_samples) == BLOCKED_PEER_LIMIT
    assert len(sec.get_events(event_type="blocked_ip_403")) == BLOCKED_EVENT_LIMIT


def test_blocked_record_does_not_wait_for_a_busy_store_or_commit_an_owner(isolated):
    sec = SecurityManager(isolated)
    acquired = threading.Event()
    release = threading.Event()

    def hold_store():
        with isolated._lock:
            acquired.set()
            release.wait(2)

    worker = threading.Thread(target=hold_store)
    worker.start()
    assert acquired.wait(1)
    try:
        start = time.monotonic()
        sec.record_blocked("198.51.100.1", "/", "GET", None, "isolated test")
        assert time.monotonic() - start < 0.1
        assert sec.get_status()["blocked_403"] == 1
        assert sec.get_status()["blocked_403_unpersisted_samples"] == 1
    finally:
        release.set()
        worker.join(2)
    assert not isolated.query("SELECT * FROM security_events WHERE event_type='blocked_ip_403'")
    with isolated.tx() as db:
        db.execute("INSERT INTO security_ip_rules(ip,action,reason,created_at) VALUES ('198.51.100.2','block','test',0)")
        assert db.in_transaction
        sec.record_blocked("198.51.100.2", "/", "GET", None, "isolated test")
        assert db.in_transaction
        db.rollback()
    assert not isolated.query("SELECT * FROM security_ip_rules WHERE ip='198.51.100.2'")


def test_blocked_persistence_restores_sqlite_timeout(isolated):
    sec = SecurityManager(isolated)
    before = isolated._db.execute("PRAGMA busy_timeout").fetchone()[0]
    sec.record_blocked("198.51.100.1", "/", "GET", None, "isolated test")
    assert isolated._db.execute("PRAGMA busy_timeout").fetchone()[0] == before
    assert len(isolated.query("SELECT * FROM security_events WHERE event_type='blocked_ip_403'")) == 1
    assert sec.get_status()["blocked_403_persisted_samples"] == 1
    assert sec.get_status()["blocked_403_unpersisted_samples"] == 0


def test_blocked_persistence_does_not_wait_on_sqlite_writer(isolated, tmp_path):
    path = tmp_path / "isolated-security.sqlite3"
    store = Store(str(path))
    sec = SecurityManager(store)
    other = sqlite3.connect(path)
    try:
        other.execute("BEGIN IMMEDIATE")
        started = time.monotonic()
        sec.record_blocked("198.51.100.1", "/", "GET", None, "isolated test")
        assert time.monotonic() - started < 0.25
        assert sec.get_status()["blocked_403_unpersisted_samples"] == 1
        assert sec.get_status()["blocked_403_persisted_samples"] == 0
    finally:
        other.rollback()
        other.close()
        store._db.close()


def test_server_entrypoint_has_one_ingress_resolver_and_shared_logging():
    assert trusted_proxy_options("10.0.0.1")["proxy_headers"] is False
    source = (Path(__file__).parents[1] / "agent_market/gateway/server.py").read_text()
    assert "uvicorn.Config(TrustedIngressMiddleware(app)" in source
    assert "uvicorn.Config(TrustedIngressMiddleware(front_app)" in source
    assert source.count("log_config=None") == 2
