"""Tests for Front (8400) DDoS defense shield and Admin (8200) security management."""

import asyncio
import time
import pytest
from fastapi.testclient import TestClient

from tests.admin_public_helpers import prepare, approved
from agent_market.concierge.security import SecurityManager
from agent_market.gateway.store import Store
from tests.test_concierge import w  # noqa: F401 (fixture)
from tests.test_gateway import populated

from tests.conftest import STAFF as H  # individual staff session; the machine token reads aggregates only


@pytest.fixture
def store():
    return Store(":memory:")


@pytest.fixture
def sec(store):
    return SecurityManager(store)


@pytest.fixture
def dash():
    world = populated()
    prepare(world.store,H)
    return world, TestClient(world.app)


# ---------------- SecurityManager Engine Unit Tests ----------------

def test_security_manager_manual_ban_and_unban(sec):
    ip = "203.0.113.10"
    blocked, _ = sec.is_blocked(ip)
    assert blocked is False

    sec.ban_ip(ip, "manual test ban", duration_seconds=None)
    blocked, reason = sec.is_blocked(ip)
    assert blocked is True
    assert reason is not None

    rules = sec.get_rules(action="block")
    assert any(r["ip"] == ip for r in rules)

    ok = sec.unban_ip(ip)
    assert ok is True
    blocked, _ = sec.is_blocked(ip)
    assert blocked is False


def test_security_manager_timed_ban_expiration(sec):
    ip = "203.0.113.11"
    sec.ban_ip(ip, "short temporary ban", duration_seconds=0.1)

    blocked, _ = sec.is_blocked(ip)
    assert blocked is True

    time.sleep(0.15)
    blocked, _ = sec.is_blocked(ip)
    assert blocked is False

    # Clean up expired rules
    cleared = sec.clear_expired_rules()
    assert cleared >= 1


def test_security_manager_auto_jail_on_repeated_violations(sec):
    ip = "203.0.113.50"
    # Cause 5 rate limit violations within 60s
    for _ in range(5):
        sec.record_violation(ip, "rate_limit_429", "/test", "GET", "TestBot/1.0", "Rate limit exceeded")

    blocked, reason = sec.is_blocked(ip)
    assert blocked is True

    events = sec.get_events(event_type="auto_jail_ddos", ip=ip)
    assert len(events) >= 1
    assert events[0]["ip"] == ip


def test_shared_worker_egress_address_is_never_jailed(sec):
    ip = "2a06:98c0:3600::103"
    for _ in range(6):
        sec.record_violation(ip, "scanner_probe", "/wp-admin/install.php", "GET", "scanner", "Suspicious path")
    assert sec.is_blocked(ip)[0] is False
    assert sec.get_events(event_type="scanner_probe", ip=ip)
    assert not sec.get_events(event_type="auto_jail_ddos", ip=ip)


def test_security_manager_under_attack_mode_tightens_limits(sec):
    assert sec.under_attack_mode is False
    assert sec.rate_multiplier == 1.0

    sec.set_under_attack_mode(True)
    assert sec.under_attack_mode is True
    assert sec.rate_multiplier == 0.2

    # Under attack mode jails after only 2 violations
    ip = "203.0.113.60"
    sec.record_violation(ip, "rate_limit_429", "/test", "GET", None, "Rate limit exceeded")
    assert sec.is_blocked(ip)[0] is False
    sec.record_violation(ip, "rate_limit_429", "/test", "GET", None, "Rate limit exceeded")
    assert sec.is_blocked(ip)[0] is True


def test_security_manager_probe_slot_and_domain_cooldown(sec):
    # Acquire probe slot
    has_slot = sec.try_acquire_probe_slot()
    assert has_slot is True
    sec.release_probe_slot()

    # Domain probe cooldown
    domain = "agent.example.com"
    ok = sec.check_target_domain_cooldown(domain, cooldown_seconds=10.0)
    assert ok is True

    # Immediate repeat to same domain should hit cooldown
    ok2 = sec.check_target_domain_cooldown(domain, cooldown_seconds=10.0)
    assert ok2 is False


# ---------------- Frontend Port 8400 DDoS Defense Tests ----------------

def test_front_banned_ip_immediately_dropped_403(w):
    _, c, _ = w
    sec = c.app.state.front.security
    ip = "198.51.100.1"
    sec.ban_ip(ip, "DDoS flood attacker")

    # Fast-drop via middleware before reaching any route
    res = c.get("/api/overview", headers={"X-Forwarded-For": ip})
    assert res.status_code == 403
    body = res.json()
    # A stable error code with a plain explanation and a support path; the reason is not disclosed.
    assert body["error_code"] == "ACCESS_BLOCKED" and body["retryable"] is False
    assert "blocked this request" in body["error"].lower() and "DDoS" not in res.text


def test_front_scanner_probe_blocked_and_auto_jailed(w):
    _, c, _ = w
    sec = c.app.state.front.security
    ip = "198.51.100.2"
    # Attempt vulnerability scanner path probe
    res = c.get("/.env", headers={"X-Forwarded-For": ip})
    assert res.status_code == 403

    # Verify IP was instantly auto-jailed
    blocked, _ = sec.is_blocked(ip)
    assert blocked is True

    # Subsequent legitimate requests are also blocked
    res2 = c.get("/api/overview", headers={"X-Forwarded-For": ip})
    assert res2.status_code == 403


def test_front_inspect_rate_limiting(w):
    _, c, _ = w
    sec = c.app.state.front.security
    ip = "198.51.100.3"
    # Exhaust the registration inspection limit (10 per window) that the endpoint applies
    for _ in range(12):
        sec.allow_feature(ip, 'registration_inspect', 10)

    # Next inspect request should hit 429
    res = c.post(
        "/api/register/inspect",
        json={"url": "https://test.example.com/agent"},
        headers={"X-Forwarded-For": ip},
    )
    assert res.status_code == 429


def test_front_whitelisted_ip_bypasses_rate_limits(w):
    _, c, _ = w
    sec = c.app.state.front.security
    ip = "198.51.100.99"
    sec.whitelist_ip(ip, "internal trusted crawler")

    # Exhaust normal rate limit token bucket
    for _ in range(150):
        sec.allow_explore(ip, base_limit=10)

    # Request still succeeds because IP is whitelisted
    res = c.get("/api/explore", headers={"X-Forwarded-For": ip})
    assert res.status_code == 200


# ---------------- Admin Port 8200 Security API Tests ----------------

def test_admin_security_status_endpoint(dash):
    _, c = dash
    res = c.get("/admin/api/security/status", headers=H)
    assert res.status_code == 200
    data = res.json()
    assert "threat_level" in data
    assert "rate_multiplier" in data
    assert "banned_ips_active" in data
    assert "in_flight_requests" in data


def test_admin_security_rules_add_and_query(dash):
    _, c = dash
    ip = "203.0.113.88"
    add_res = c.post(
        "/admin/api/security/rules",
        headers=H,
        json={"ip": ip, "action": "block", "reason": "Admin test ban", "duration": 3600},
    )
    assert add_res.status_code == 200
    assert add_res.json()["ok"] is True

    # List rules
    list_res = c.get("/admin/api/security/rules?action=block", headers=H)
    assert list_res.status_code == 200
    rules = list_res.json()["rules"]
    assert any(r["ip"] == ip for r in rules)

    # Delete rule
    del_res = c.delete(f"/admin/api/security/rules/{ip}", headers={**H,"X-Admin-Reason":"Synthetic%20unblock%20review"})
    assert approved(c,H,del_res)["action"]=="remove"


def test_admin_security_toggle_under_attack(dash):
    _, c = dash
    # Enable under attack mode
    res1 = c.post("/admin/api/security/under-attack", headers=H, json={"enabled": True,"reason":"Synthetic defense tightening"})
    assert res1.status_code == 200
    assert res1.json()["result"]["enabled"] is True

    # Revert
    res2 = c.post("/admin/api/security/under-attack", headers=H, json={"enabled": False,"reason":"Synthetic defense relaxation"})
    assert approved(c,H,res2)["enabled"] is False


def test_admin_security_rate_multiplier(dash):
    _, c = dash
    res = c.post("/admin/api/security/rate-multiplier", headers=H, json={"multiplier": 0.5,"reason":"Synthetic rate tightening"})
    assert res.status_code == 200
    assert res.json()["result"]["multiplier"] == 0.5


def test_admin_security_events_and_clear_expired(dash):
    _, c = dash
    ev_res = c.get("/admin/api/security/events?limit=10", headers=H)
    assert ev_res.status_code == 200
    assert "events" in ev_res.json()

    clear_res = c.post("/admin/api/security/clear-expired", headers={**H,"X-Admin-Reason":"Synthetic%20expired%20cleanup"})
    assert clear_res.status_code == 200
    assert "cleared" in clear_res.json()


# ---------------- FIFO Backpressure Queue & Strict Zero Admin Tests ----------------

@pytest.mark.anyio
async def test_fifo_request_queue_at_90_percent_load(sec):
    # Set limit to 10 for deterministic testing. 90% threshold = 9
    sec.max_concurrent_requests = 10
    sec.queue_threshold = 0.90

    # Acquire 9 slots (under 90% threshold)
    acquired_list = []
    for _ in range(9):
        acq, queued, pos = await sec.acquire_request_slot_or_queue(timeout=1.0)
        assert acq is True
        assert queued is False
        acquired_list.append(acq)

    assert sec.get_status()["in_flight_requests"] == 9
    assert sec.get_status()["load_ratio_pct"] == 90.0

    # 10th request reaches 90% threshold -> must be queued in FIFO order
    waiter_task = asyncio.create_task(sec.acquire_request_slot_or_queue(timeout=2.0))
    await asyncio.sleep(0.05)  # Yield to event loop to allow enqueue
    assert len(sec._fifo_waiters) == 1
    assert sec.get_status()["queued_requests_active"] == 1

    # Release 1 slot -> FIFO waiter must be granted the slot immediately
    sec.release_request_slot()
    acq10, queued10, pos10 = await waiter_task
    assert acq10 is True
    assert queued10 is True
    assert pos10 == 1
    assert len(sec._fifo_waiters) == 0

    # Clean up all acquired slots
    for _ in range(9):
        sec.release_request_slot()
    sec.release_request_slot()
    assert sec.get_status()["in_flight_requests"] == 0


@pytest.mark.anyio
async def test_fifo_queue_timeout_rejection(sec):
    sec.max_concurrent_requests = 5
    sec.queue_threshold = 0.80  # threshold = 4

    for _ in range(4):
        await sec.acquire_request_slot_or_queue(timeout=0.5)

    # 5th request enqueues, but nobody releases within timeout -> timeout rejection
    acq, queued, pos = await sec.acquire_request_slot_or_queue(timeout=0.1)
    assert acq is False
    assert queued is True
    assert len(sec._fifo_waiters) == 0

    # Clean up
    for _ in range(4):
        sec.release_request_slot()


def test_front_zero_admin_trace_and_endpoints(w):
    _, c, _ = w
    # 1. Front app must reject any attempt to hit /admin routes
    res = c.get("/admin")
    assert res.status_code in (404, 403)
    res_ui = c.get("/admin/ui")
    assert res_ui.status_code in (404, 403)
    res_api = c.get("/admin/api/resources")
    assert res_api.status_code in (404, 403)

    # 2. Front HTML must contain zero occurrences of 'admin' in rendered text or comments
    home_html = c.get("/").text
    assert "admin" not in home_html.lower()

    # 3. robots.txt must not advertise /admin
    robots = c.get("/robots.txt").text
    assert "admin" not in robots.lower()



def test_admin_explore_document_status_is_authenticated_and_aggregate(dash):
    _, c = dash
    assert c.get("/admin/api/explore-documents/status").status_code in (401, 403)
    res = c.get("/admin/api/explore-documents/status", headers=H)
    assert res.status_code == 200 and res.json() == {"installed": False}  # this fixture is not PostgreSQL
