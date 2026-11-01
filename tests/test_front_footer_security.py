"""Comprehensive Secure Coding & Dynamic Vulnerability Test Suite for Frontend Footer."""

import pytest

pytestmark = pytest.mark.usefixtures('legacy_public_entry')
from fastapi.testclient import TestClient

from agent_market.concierge.front import create_front_app
from tests.test_concierge import w  # noqa: F401 (fixture)
from tests.test_gateway import populated


def test_footer_xss_resilience(w):
    """Dynamic Test: Ensure XSS payloads in footer forms are safely handled without code execution."""
    world, c, _ = w

    xss_payloads = [
        "<script>alert('XSS')</script>",
        "<img src=x onerror=alert(1)>",
        "\"><svg/onload=alert('pwn')>",
        "javascript:alert(document.cookie)",
        "{{7*7}}"
    ]

    for idx, payload in enumerate(xss_payloads):
        r = c.post("/api/contact/submit", json={
            "name": f"Auditor {payload}",
            "email": f"auditor{idx}@agentconcierge.biz",
            "subject": f"Inquiry {payload}",
            "message": f"Security audit payload {payload}",
            "category": "security_abuse"
        }, headers={"X-Forwarded-For": f"198.51.100.{20 + idx}"})
        assert r.status_code == 200, f"XSS payload caused error: {r.text}"
        data = r.json()
        assert data.get("ok") is True

        # Verify stored and disarmed in DB without script execution
        inq = world.store.get_customer_inquiry(data["inquiry_id"])
        assert inq is not None
        assert "<script>" not in inq["name"]
        assert "onerror=" not in inq["name"]
        assert "onload=" not in inq["name"]


def test_footer_sqli_resilience(w):
    """Dynamic Test: Ensure SQL injection attempts do not manipulate queries or crash endpoints."""
    world, c, _ = w

    sqli_vectors = [
        "' OR '1'='1",
        "'; DROP TABLE customer_inquiries; --",
        "1' UNION SELECT 1,2,3,4,5,6,7,8,9,10,11,12--",
        "admin'--",
    ]

    for idx, sqli in enumerate(sqli_vectors):
        hdr = {"X-Forwarded-For": f"198.51.100.{40 + idx}"}
        # 1. Contact Form
        r_contact = c.post("/api/contact/submit", json={
            "name": sqli,
            "email": "sqli@agentconcierge.biz",
            "subject": sqli,
            "message": sqli,
            "category": "general"
        }, headers=hdr)
        assert r_contact.status_code == 200

        # 2. Privacy Opt-Out
        r_privacy = c.post("/api/privacy/opt-out", json={
            "request_type": sqli,
            "email": "sqli@agentconcierge.biz",
            "details": sqli
        }, headers=hdr)
        assert r_privacy.status_code == 422

        # 3. Unsubscribe
        r_unsub = c.post("/unsubscribe", json={
            "token": sqli,
            "reason": sqli
        }, headers=hdr)
        assert r_unsub.status_code in (401, 200)

    # Verify tables remain intact and operational
    with world.store.tx() as db:
        res = db.execute("SELECT COUNT(*) AS n FROM customer_inquiries").fetchone()
        assert res["n"] > 0
        p_res = db.execute("SELECT COUNT(*) AS n FROM privacy_requests").fetchone()
        assert p_res["n"] == 0


def test_footer_rate_limiting_defense(w):
    """Dynamic Test: Enforce sliding-window rate limiters across all footer public POST endpoints."""
    world, c, _ = w

    # 1. Contact submission rate limit
    ip_contact = "198.51.100.80"
    contact_rate_limited = False
    for i in range(25):
        r = c.post("/api/contact/submit", json={
            "name": f"Tester {i}",
            "email": "tester@agentconcierge.biz",
            "subject": "Load test",
            "message": "Testing endpoint resilience",
            "category": "general"
        }, headers={"X-Forwarded-For": ip_contact})
        if r.status_code == 429:
            contact_rate_limited = True
            break
    assert contact_rate_limited is True, "Contact endpoint must reject high-volume bursts with 429"

    # 2. Privacy opt-out rate limit
    ip_privacy = "198.51.100.81"
    privacy_rate_limited = False
    for i in range(25):
        r = c.post("/api/privacy/opt-out", json={
            "request_type": "ccpa_opt_out",
            "details": f"Test {i}"
        }, headers={"X-Forwarded-For": ip_privacy})
        if r.status_code == 429:
            privacy_rate_limited = True
            break
    assert privacy_rate_limited is True, "Privacy opt-out endpoint must reject high-volume bursts with 429"

    # 3. Unsubscribe rate limit
    ip_unsub = "198.51.100.82"
    unsub_rate_limited = False
    for i in range(30):
        r = c.post("/unsubscribe", json={
            "token": f"token_probe_{i}",
            "reason": "testing"
        }, headers={"X-Forwarded-For": ip_unsub})
        if r.status_code == 429:
            unsub_rate_limited = True
            break
    assert unsub_rate_limited is True, "Unsubscribe endpoint must reject token flooding with 429"


def test_footer_input_bounds_and_format_validation(w):
    """Secure Coding: Enforce length caps and strict email regex validation."""
    world, c, _ = w
    hdr = {"X-Forwarded-For": "198.51.100.90"}

    # 1. Oversized message body (>4000 chars) rejected with 422
    r_oversized = c.post("/api/contact/submit", json={
        "name": "Bob",
        "email": "bob@agentconcierge.biz",
        "subject": "Audit",
        "message": "X" * 4001,
        "category": "general"
    }, headers=hdr)
    assert r_oversized.status_code == 422
    assert "5 to 4000 characters" in r_oversized.text

    # 2. Malformed emails rejected with 422
    malformed_emails = ["notanemail", "user@localhost", "@nodomain.com", "test@.com", "user@domain..com"]
    for bad_email in malformed_emails:
        r_bad = c.post("/api/contact/submit", json={
            "name": "Bob",
            "email": bad_email,
            "subject": "Audit",
            "message": "Valid body content here",
            "category": "general"
        }, headers=hdr)
        assert r_bad.status_code == 422, f"Expected 422 for malformed email '{bad_email}', got {r_bad.status_code}"


def test_footer_zero_leakage_on_exceptions(w):
    """Zero-Leakage Policy: Error responses must not expose database tech, ports, internal paths, or IPs."""
    world, c, _ = w

    # Malformed JSON
    r_bad_json = c.post("/api/contact/submit", content=b"INVALID{JSON", headers={"content-type": "application/json"})
    assert r_bad_json.status_code == 400
    lower_text = r_bad_json.text.lower()
    for sensitive in ["sqlite", "postgres", "127.0.0.1", "localhost", ":8200", ":8400", "/users/", "traceback"]:
        assert sensitive not in lower_text, f"Found sensitive leak in response: {sensitive}"


def test_footer_dom_secure_coding_standards(w):
    """Static/DOM Test: Verify prototype pollution defense, PII masking, and length limits in HTML markup."""
    world, c, _ = w
    r = c.get("/", headers={"accept": "text/html"})
    assert r.status_code == 200
    html = r.text

    # 1. Whitelist-based prototype pollution defense in switchLegalDoc
    assert "VALID_LEGAL_DOCS" in html
    assert "VALID_LEGAL_DOCS.has(docType)" in html

    # 2. PII masking on contact form and token input for session replay privacy
    assert 'id="inqName" class="input fs-mask" data-clarity-mask="true"' in html
    assert 'id="inqEmail" class="input fs-mask" data-clarity-mask="true"' in html
    assert 'id="inqMessage" class="input fs-mask" data-clarity-mask="true"' in html
    assert 'id="taskUpdateUrl" class="input fs-mask" data-clarity-mask="true"' in html
    assert 'id="ftcCancelToken"' not in html

    # 3. HTML5 maxlength attributes enforced on client controls
    assert 'id="inqName"' in html and 'maxlength="100"' in html
    assert 'id="inqEmail"' in html and 'maxlength="150"' in html
    assert 'id="inqSubject"' in html and 'maxlength="200"' in html
    assert 'id="inqMessage"' in html and 'maxlength="4000"' in html
    assert 'id="taskUpdateUrl"' in html and 'maxlength="500"' in html

    # 4. Double submission / race condition prevention (button disabling in JS)
    assert 'btnConfirmCcpaOptOut' in html and 'btn.disabled = true' in html
    assert 'taskUpdateSubmit' in html and 'button.disabled = true' in html

    # 5. Direct legal route hash support
    assert "LEGAL_ROUTES = [" in html
    assert "openLegalModal(initTab)" in html
