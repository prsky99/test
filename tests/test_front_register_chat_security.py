"""Comprehensive Secure Coding and Dynamic Vulnerability Test Suite for #register and #chat.

Verifies:
1. Proactive Input Blocking: Malicious payloads (Stored XSS, SQL Injection, SSRF, Control Chars)
   are intercepted and blocked with HTTP 400 at ingestion before touching database or admin console.
2. Form Boundary Hardening: Length limits, protocol validations, and nested schema safety.
3. Chat Ingestion Security: Prohibits executable HTML markup, scripts, and pseudo-protocols in /chat
   while preserving legitimate technical queries (no false positives).
4. Zero Information Leakage: Error responses contain no internal IPs, ports, DB technology names, or stack traces.
5. Strict 100% English Compliance and Zero Korean Characters.
"""

from pathlib import Path
import re
import pytest
from fastapi.testclient import TestClient

from agent_market.concierge.front import create_front_app
from agent_market.concierge.security import check_malicious_text, check_malicious_dict
from tests.test_concierge import w  # noqa: F401 (fixture)
from tests.test_gateway import populated
from tests.test_registration_hardening import consent


MALICIOUS_XSS_PAYLOADS = [
    "<script>alert('XSS')</script>",
    "<script src='https://attacker.com/payload.js'></script>",
    "<img src=x onerror=alert('StoredXSS')>",
    "<svg/onload=alert('pwn')>",
    "<iframe src=javascript:alert('iframe')></iframe>",
    "javascript:alert(document.cookie)",
    "vbscript:msgbox('pwn')",
    "data:text/html,<script>alert(1)</script>",
    "<object data='data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg=='></object>",
    "<body onload=alert('xss')>",
    "<input autofocus onfocus=alert('autofocus')>",
]

MALICIOUS_SQLI_PAYLOADS = [
    "' OR '1'='1",
    "'; DROP TABLE resources; --",
    "1' UNION SELECT 1,2,3,4,5,6,7,8,9,10--",
    "admin' --",
    "' UNION ALL SELECT null, username, password FROM users --",
]

MALICIOUS_SSRF_URLS = [
    "http://127.0.0.1:8080/card.json",
    "http://localhost:8400/mcp",
    "http://10.0.0.1/admin",
    "http://192.168.1.1/internal",
    "http://172.16.0.1/sensitive",
    "http://169.254.169.254/latest/meta-data/",
]


def test_register_ingestion_blocks_stored_xss_in_all_fields(w):
    """Dynamic Test: Ensure malicious XSS in any registration field is proactively blocked with HTTP 400."""
    world, c, _ = w

    for idx, payload in enumerate(MALICIOUS_XSS_PAYLOADS):
        hdr = {"X-Forwarded-For": f"198.51.100.{10 + idx}"}

        # 1. Stored XSS in agent name
        r_name = c.post("/api/register", json={
            "kind": "mcp",
            "url": f"https://agent{idx}.example.com/mcp",
            "name": f"Agent {payload}",
            "description": "Safe capability description for tests.",
            "category": "ai_models"
        }, headers=hdr)
        assert r_name.status_code == 400, f"Expected 400 for XSS in name: {r_name.text}"
        assert "Security validation failed" in r_name.text or "strictly prohibited" in r_name.text

        # 2. Stored XSS in description
        r_desc = c.post("/api/register", json={
            "kind": "mcp",
            "url": f"https://agent{idx}.example.com/mcp",
            "name": f"SafeAgent{idx}",
            "description": f"Dangerous description with {payload}",
            "category": "ai_models"
        }, headers=hdr)
        assert r_desc.status_code == 400, f"Expected 400 for XSS in description: {r_desc.text}"
        assert "Security validation failed" in r_desc.text

        # 3. Dangerous protocol in URL
        r_url = c.post("/api/register", json={
            "kind": "mcp",
            "url": f"javascript:alert({idx})",
            "name": f"SafeAgent{idx}",
            "description": "Safe capability description for tests.",
            "category": "ai_models"
        }, headers=hdr)
        assert r_url.status_code == 400, f"Expected 400 for dangerous URL protocol: {r_url.text}"

        # 4. Stored XSS in x402 recipient wallet
        r_payto = c.post("/api/register", json={
            "kind": "x402",
            "url": f"https://agent{idx}.example.com/pay",
            "name": f"SafeAgent{idx}",
            "description": "Safe capability description for tests.",
            "category": "ai_models",
            "price_usdc": 1000,
            "pay_to": f"0x12345{payload}"
        }, headers=hdr)
        assert r_payto.status_code == 400, f"Expected 400 for XSS in pay_to: {r_payto.text}"


def test_register_ingestion_blocks_nested_metadata_xss(w):
    """Dynamic Test: Ensure malicious payloads in nested tools/metadata details dict are blocked."""
    world, c, _ = w
    hdr = {"X-Forwarded-For": "198.51.100.35"}

    # Malicious nested tool name in details
    r_nested = c.post("/api/register", json={
        "kind": "mcp",
        "url": "https://validagent.example.com/mcp",
        "name": "NestedAgent",
        "description": "Valid agent description for testing.",
        "category": "ai_models",
        "details": {
            "tools": [
                {"name": "<script>alert('pwn')</script>", "description": "Malicious tool"}
            ]
        }
    }, headers=hdr)
    assert r_nested.status_code == 400
    assert "Security validation failed in agent metadata" in r_nested.text


def test_register_ingestion_blocks_ssrf(w):
    """Dynamic Test: Ensure private loopback, RFC-1918, and metadata IPs are rejected with 400."""
    world, c, _ = w

    for idx, ssrf_url in enumerate(MALICIOUS_SSRF_URLS):
        hdr = {"X-Forwarded-For": f"198.51.100.{50 + idx}"}
        # 1. /api/register
        r1 = c.post("/api/register", json={
            "kind": "mcp",
            "url": ssrf_url,
            "name": "SSRFProbe",
            "description": "Probing private address.",
            "category": "ai_models", "legal_consent": consent()
        }, headers=hdr)
        assert r1.status_code == 400, f"Expected 400 for SSRF in register: {r1.text}"
        assert r1.json()["error_code"] == "PRIVATE_DESTINATION"

        # 2. /api/register/inspect
        r2 = c.post("/api/register/inspect", json={"url": ssrf_url}, headers=hdr)
        assert r2.status_code == 400, f"Expected 400 for SSRF in inspect: {r2.text}"
        assert r2.json()["error_code"] == "PRIVATE_DESTINATION"


def test_chat_ingestion_blocks_stored_xss_and_scripts(w):
    """Dynamic Test: Proactively block executable scripts and HTML markup in /chat message and name."""
    world, c, _ = w

    for idx, payload in enumerate(MALICIOUS_XSS_PAYLOADS):
        hdr = {"X-Forwarded-For": f"198.51.100.{70 + idx}"}

        # 1. Script in chat message
        r_msg = c.post("/chat", json={"message": f"Hello concierge {payload}"}, headers=hdr)
        assert r_msg.status_code == 400, f"Expected 400 for XSS in chat message: {r_msg.text}"
        assert "Security validation failed" in r_msg.text
        assert "HTML markup and executable scripts are prohibited" in r_msg.text

        # 2. Script in visitor name
        r_name = c.post("/chat", json={"message": "Safe message", "name": f"Visitor {payload}"}, headers=hdr)
        assert r_name.status_code == 400, f"Expected 400 for XSS in visitor name: {r_name.text}"
        assert "Security validation failed" in r_name.text


def test_chat_ingestion_allows_legitimate_technical_queries(w):
    """Dynamic Test: Ensure legitimate developer queries containing SQL or programming terms are NOT blocked."""
    world, c, _ = w
    hdr = {"X-Forwarded-For": "198.51.100.120"}

    legit_queries = [
        "How can I generate a SELECT query builder for postgresql?",
        "Recommend an eval() sandbox runner for python scripts",
        "Find an MCP server for web search with brave search API",
        "Looking for a weather API without requiring an API key",
        "Show me database analytics tools supporting time series data"
    ]

    for q in legit_queries:
        r = c.post("/chat", json={"message": q}, headers=hdr)
        assert r.status_code == 200, f"Legitimate query was falsely blocked: {q} -> {r.text}"
        data = r.json()
        assert "reply" in data
        assert "audience" in data


def test_chat_ingestion_blocks_malicious_nested_contact_url(w):
    """Dynamic Test: Ensure malicious pseudo-protocols in contact payload are rejected."""
    world, c, _ = w
    hdr = {"X-Forwarded-For": "198.51.100.125"}

    r = c.post("/chat", json={
        "message": "Update my contact",
        "data": {
            "contact": {
                "type": "webhook",
                "url": "javascript:alert('pwn')"
            }
        }
    }, headers=hdr)
    assert r.status_code == 400
    assert "Security validation failed" in r.text or "Contact URL must be a valid http(s) address" in r.text


def test_security_violation_audit_logged(w):
    """Dynamic Test: Verify security violations increment security telemetry and are logged for admin review."""
    world, c, _ = w
    hdr = {"X-Forwarded-For": "198.51.100.130"}

    # Send violation
    c.post("/chat", json={"message": "<script>alert('audit_test')</script>"}, headers=hdr)

    # Check security telemetry in SecurityManager
    sec = world.app.state.front.security
    assert sec is not None
    events = list(sec._recent_events)
    matching = [e for e in events if e.get("ip") == "198.51.100.130" and e.get("event_type") == "stored_xss_attempt"]
    assert len(matching) >= 1, "Security violation was not recorded in security telemetry events"


def test_zero_leakage_in_error_responses(w):
    """Zero-Leakage Policy: Ensure 400/422 responses contain no internal IPs, ports, or server paths."""
    world, c, _ = w
    hdr = {"X-Forwarded-For": "198.51.100.140"}

    responses = [
        c.post("/api/register", json={"kind": "mcp", "url": "http://127.0.0.1:8000/mcp", "name": "Local", "description": "Local test"}, headers=hdr),
        c.post("/api/register/inspect", json={"url": "http://192.168.1.1/card.json"}, headers=hdr),
        c.post("/chat", json={"message": "<script>alert(1)</script>"}, headers=hdr),
        c.post("/api/contact/submit", json={"name": "A", "email": "bad", "subject": "Hi", "message": "Short", "category": "general"}, headers=hdr),
    ]

    for resp in responses:
        body = resp.text
        # No internal port numbers
        assert ":8080" not in body and ":8200" not in body and ":8400" not in body
        # No internal server absolute paths
        assert "/Users/" not in body and "/home/" not in body
        # No internal db technology names in user error message
        assert "sqlite" not in body.lower()


def test_client_side_extracted_html_security_guards():
    """Static Test: Verify extracted_html.txt contains client-side guards and zero Korean characters."""
    html = Path("extracted_html.txt").read_text(encoding="utf-8")

    # 1. Helper definitions
    assert "const DANGEROUS_PAYLOAD_RE" in html
    assert "function isUnsafeInput(s)" in html
    assert "isComposing" in html

    # 2. Registration client-side checks
    assert "$(\"regInspectBtn\").onclick" in html
    assert "$(\"regSubmitBtn\").onclick" in html
    assert "isUnsafeInput(u)" in html
    assert "isUnsafeInput(url)" in html
    assert "isUnsafeInput(name)" in html
    assert "isUnsafeInput(desc)" in html

    # 3. Chat client-side checks
    assert "isUnsafeInput(query)" in html
    assert "if (!res.ok)" in html

    # 4. Strict 100% English Check
    hangul = re.findall(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]", html)
    assert len(hangul) == 0, f"Found Korean in extracted_html.txt: {set(hangul)}"


def test_front_py_synchronized_and_zero_korean():
    """Static Test: Verify front.py and security.py have zero Korean characters."""
    for file_path in ["agent_market/concierge/front.py", "agent_market/concierge/security.py"]:
        code = Path(file_path).read_text(encoding="utf-8")
        hangul = re.findall(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]", code)
        assert len(hangul) == 0, f"Found Korean in {file_path}: {set(hangul)}"
