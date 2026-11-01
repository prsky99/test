"""Comprehensive dynamic security vulnerability tests for #needs menu and related endpoints.

Tests against:
- Stored and DOM XSS payloads (<script>, <img onerror>, <svg onload>, <iframe src=javascript:>)
- Pseudo-protocol injections (javascript:, vbscript:, data:text/html)
- Inline attribute breakouts and event handler injection
- Malicious emails, null bytes, unicode bypasses, nested tags
- Frontend rendering secure coding (textContent, safeMailto, safeUrl, event delegation)
"""

import re
import pytest
from fastapi.testclient import TestClient

from agent_market.gateway.sanitizer import (
    sanitize_text,
    sanitize_email,
    sanitize_url,
    is_safe_text,
)
from agent_market.gateway.server import create_app
from agent_market.gateway.service import GatewayService, Policy
from agent_market.gateway.store import Store


@pytest.fixture
def test_setup(tmp_path):
    db_path = str(tmp_path / "test_store.db")
    st = Store(db_path)
    return st, db_path, str(tmp_path / "ledger.db")


@pytest.fixture
def test_store(test_setup):
    st, _, _ = test_setup
    return st


class TestSanitizerCore:
    """Unit tests for defensive sanitization engine."""

    def test_strip_script_tags(self):
        payloads = [
            ("<script>alert('XSS')</script>", ""),
            ("<SCRIPT SRC=http://evil.com/xss.js></SCRIPT>", ""),
            ("<script\x00>alert(1)</script>", ""),
            ("Task before <script>alert(1)</script> task after", "Task before  task after"),
            ("<<SCRIPT>alert(1);//<</SCRIPT>", ""),
            ("<scr<script>ipt>alert(1)</script>", ""),
        ]
        for payload, expected in payloads:
            res = sanitize_text(payload)
            assert "<script" not in res.lower(), f"Failed for {payload}: got {res}"
            assert "alert('XSS')" not in res

    def test_strip_inline_event_handlers(self):
        payloads = [
            ("<img src=x onerror=alert(1)>", ""),
            ("<svg onload=alert(document.cookie)>", ""),
            ("<body onload=alert('pwned')>", ""),
            ("<input onfocus=alert(1) autofocus>", ""),
            ("<details open ontoggle=alert(1)>", ""),
            ("<video><source onerror=alert(1)>", ""),
        ]
        for payload in payloads:
            res = sanitize_text(payload)
            assert "onerror" not in res.lower(), f"Failed for {payload}: got {res}"
            assert "onload" not in res.lower(), f"Failed for {payload}: got {res}"
            assert "onfocus" not in res.lower(), f"Failed for {payload}: got {res}"
            assert "ontoggle" not in res.lower(), f"Failed for {payload}: got {res}"

    def test_neutralize_dangerous_schemes(self):
        payloads = [
            ("javascript:alert(1)", "blocked-uri:alert(1)"),
            ("JAVASCRIPT:void(0)", "blocked-uri:void(0)"),
            ("vbscript:msgbox(1)", "blocked-uri:msgbox(1)"),
            ("data:text/html,<script>alert(1)</script>", "blocked-uri:"),
        ]
        for payload, expected_part in payloads:
            res = sanitize_text(payload)
            assert "javascript:" not in res.lower()
            assert "vbscript:" not in res.lower()
            assert "data:text/html" not in res.lower()

    def test_null_byte_and_control_char_removal(self):
        payload = "Hello\x00World\x08Test\x1fClean"
        res = sanitize_text(payload)
        assert "\x00" not in res
        assert "\x08" not in res
        assert "\x1f" not in res
        assert "HelloWorldTestClean" == res

    def test_preserve_legitimate_content(self):
        normal_en = "Need an autonomous agent for web scraping and data pipeline"
        normal_ko = "이더리움 및 솔라나 온체인 트랜잭션 모니터링 에이전트 추천"
        math_exp = "Score > 80 and latency < 200ms"
        assert sanitize_text(normal_en) == normal_en
        assert sanitize_text(normal_ko) == normal_ko
        assert sanitize_text(math_exp) == math_exp

    def test_sanitize_email(self):
        assert sanitize_email("user@example.com") == "user@example.com"
        assert sanitize_email("agent.tester+sub@test.co.kr") == "agent.tester+sub@test.co.kr"
        # Malicious attempts
        assert sanitize_email("javascript:alert(1)") == ""
        assert sanitize_email("user@example.com<script>") == ""
        assert sanitize_email("user@example.com\r\nBcc: evil@attacker.com") == ""
        assert sanitize_email("user@example.com' OR '1'='1") == ""

    def test_sanitize_url(self):
        assert sanitize_url("https://example.com/agent") == "https://example.com/agent"
        assert sanitize_url("http://localhost/path") == "http://localhost/path"
        # Malicious attempts
        assert sanitize_url("javascript:alert(1)") is None
        assert sanitize_url("data:text/html,test") is None
        assert sanitize_url("https://example.com' onclick='alert(1)") is None
        assert sanitize_url("https://example.com<script>") is None


class TestNeedsDatabaseSanitization:
    """Dynamic vulnerability testing on Store customer requests hub methods."""

    def test_record_customer_inquiry_with_xss_payloads(self, test_store):
        # Register inquiry containing diverse XSS vectors
        xss_name = "Hacker<script>alert('name')</script>"
        xss_email = "evil@example.com\"><script>alert('email')</script>"
        xss_subject = "Urgent: <img src=x onerror=alert('subj')> Help"
        xss_message = "Payload: <svg onload=alert('msg')><iframe src=javascript:alert(1)> Click here"

        inq_id = test_store.record_customer_inquiry(
            category="security_abuse",
            name=xss_name,
            email=xss_email,
            subject=xss_subject,
            message=xss_message,
            ip="198.51.100.1"
        )
        assert inq_id.startswith("inq_")

        # Retrieve and verify stored data is completely neutralized
        inq = test_store.get_customer_inquiry(inq_id)
        assert inq is not None
        assert "<script>" not in inq["name"]
        assert "<script>" not in inq["email"]
        assert "onerror=" not in inq["subject"]
        assert "<img" not in inq["subject"]
        assert "<svg" not in inq["message"]
        assert "<iframe" not in inq["message"]
        assert "javascript:" not in inq["message"]

    def test_update_customer_inquiry_admin_response_sanitization(self, test_store):
        inq_id = test_store.record_customer_inquiry("general", "Alice", "alice@example.com", "Test", "Hello")
        malicious_response = "Admin reply with </textarea><script>alert('admin_pwned')</script>"
        ok = test_store.update_customer_inquiry(inq_id, status="resolved", admin_response=malicious_response)
        assert ok is True

        inq = test_store.get_customer_inquiry(inq_id)
        assert "<script>" not in inq["admin_response"]
        assert "</textarea>" not in inq["admin_response"]

    def test_cancellation_reason_sanitization(self, test_store):
        malicious_reason = "Unsubscribe because <img src=x onerror=alert('cnl')> broken"
        req_id = test_store.record_cancellation_request(reason=malicious_reason)
        rows, _ = test_store.list_cancellation_requests()
        item = next(r for r in rows if r["request_id"] == req_id)
        assert "onerror=" not in item["reason"]
        assert "<img" not in item["reason"]

    def test_privacy_request_sanitization(self, test_store):
        malicious_details = "Delete my data <script>alert('gdpr')</script>"
        req_id = test_store.record_privacy_request("data_erasure", email="test@example.com", details=malicious_details)
        rows, _ = test_store.list_privacy_requests()
        item = next(r for r in rows if r["request_id"] == req_id)
        assert "<script>" not in item["details"]


class TestNeedsServiceAndServerIntegration:
    """Integration tests verifying end-to-end defense across gateway and service."""

    def test_create_need_sanitizes_malicious_task(self, test_setup):
        st, db_path, ledger_path = test_setup
        from agent_market.ledger import Ledger
        from agent_market.gateway.crawler import Prober
        prober = Prober(st)
        ledger = Ledger(ledger_path)
        service = GatewayService(st, prober, ledger, Policy(free=True))
        client_addr = "0x1111111111111111111111111111111111111111"
        malicious_task = "Find agent <script>alert('task_xss')</script> for trading <img src=x onerror=alert(1)>"

        res = service.create_need(client_addr, malicious_task, category=None, max_price=None, networks=None, kinds=None, webhook=None, ip="127.0.0.1")
        need_id = res["need_id"]

        with st.tx() as db:
            row = db.execute("SELECT * FROM needs WHERE need_id = ?", (need_id,)).fetchone()
            assert "<script" not in row["task"]
            assert "onerror=" not in row["task"]
            assert "alert('task_xss')" not in row["task"]
            assert "Find agent" in row["task"]
            assert "for trading" in row["task"]


class TestDashboardFrontendSecureCoding:
    """Verify frontend dashboard.html uses secure coding patterns for #needs."""

    def test_dashboard_source_contains_secure_coding_patterns(self):
        from pathlib import Path
        html_file = Path(__file__).resolve().parent.parent / "agent_market" / "gateway" / "dashboard.html"
        assert html_file.exists()
        content = html_file.read_text(encoding="utf-8")

        # 1. Enhanced esc() with backtick and slash escaping
        assert "&#96;" in content, "esc() must escape backticks"
        assert "&#47;" in content, "esc() must escape slashes"
        assert "\\0" in content, "esc() must filter null bytes"

        # 2. safeMailto and safeUrl validators
        assert "function safeMailto" in content, "dashboard.html must define safeMailto validator"
        assert "function safeUrl" in content, "dashboard.html must define safeUrl validator"

        # 3. No inline onclick with string interpolation in needs buttons
        assert "onclick=\"openNeedOffers('" not in content, "Forbidden inline onclick string interpolation for openNeedOffers"
        assert "onclick=\"openInquiryDetail('" not in content, "Forbidden inline onclick string interpolation for openInquiryDetail"
        assert "onclick=\"reactivateCancellation('" not in content, "Forbidden inline onclick string interpolation for reactivateCancellation"

        # 4. Data attributes are used instead
        assert "btn-need-offers" in content
        assert "data-need-id=" in content
        assert "btn-inquiry-detail" in content
        assert "data-inquiry-id=" in content
        assert "btn-reactivate-cnl" in content
        assert "data-request-id=" in content

        # 5. Modal uses textContent for dynamic user content
        assert "$(\"inqDtlSubject\").textContent = item.subject" in content
        assert "$(\"inqDtlMessage\").textContent = item.message" in content
        assert "$(\"inqDtlName\").textContent = item.name" in content

        # 6. Event delegation listener handles secure buttons
        assert "btnOffer.dataset.needId" in content
        assert "btnInq.dataset.inquiryId" in content
        assert "btnReactivate.dataset.requestId" in content

    def test_dashboard_csp_header_hardened(self, test_setup):
        st, db_path, _ = test_setup
        from agent_market.gateway.dashboard import dashboard_router
        from fastapi import FastAPI
        test_app = FastAPI()
        test_app.include_router(dashboard_router(store=st, db_path=db_path, admin_token=None, collector=None))
        client = TestClient(test_app)

        res = client.get("/admin/ui")
        assert res.status_code == 200
        csp = res.headers.get("content-security-policy", "")
        assert "object-src 'none'" in csp
        assert "base-uri 'none'" in csp
        assert "script-src 'nonce-" in csp
        assert "script-src-attr 'none'" in csp
        assert "form-action 'self'" in csp
