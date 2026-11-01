"""Comprehensive test suite for Customer Requests & Compliance Hub (Footer management & Admin Customer Needs)."""

import re
import pytest
from fastapi.testclient import TestClient

from agent_market.concierge.front import create_front_app
from tests.test_gateway import populated

from tests.conftest import STAFF as H  # individual staff session; the machine token reads aggregates only


@pytest.fixture
def env():
    world = populated()
    front = world.app.state.front
    admin_client = TestClient(world.app)
    front_client = TestClient(create_front_app(front))
    return world, front_client, admin_client


def test_contact_inquiry_public_and_admin_workflow(env):
    world, front_c, admin_c = env

    # 1. Validation error checks
    bad_res = front_c.post("/api/contact/submit", json={"name": "A", "email": "invalid", "subject": "Hi", "message": "12"})
    assert bad_res.status_code == 422

    # 2. Valid submission from footer Contact form
    payload = {
        "category": "technical",
        "name": "Autonomous Tester",
        "email": "agent@autonomous.org",
        "subject": "A2A Protocol schema clarification",
        "message": "We are experiencing a schema validation mismatch with tool parameter declarations. Please advise."
    }
    res = front_c.post("/api/contact/submit", json=payload, headers={"User-Agent": "TesterBot/1.0"})
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    inquiry_id = data["inquiry_id"]
    assert inquiry_id.startswith("inq_")

    # 3. Verify inquiry is retrieved via Admin API
    inq_res = admin_c.get("/admin/api/needs/inquiries", headers=H)
    assert inq_res.status_code == 200
    items = inq_res.json()["items"]
    match = next((item for item in items if item["inquiry_id"] == inquiry_id), None)
    assert match is not None
    assert match["category"] == "technical"
    assert match["name"] == "Autonomous Tester"
    assert match["status"] == "pending"
    assert match["admin_response"] is None

    # 4. Search and filter inquiries
    filtered = admin_c.get("/admin/api/needs/inquiries?category=technical&q=schema", headers=H).json()
    assert any(i["inquiry_id"] == inquiry_id for i in filtered["items"])

    filtered_none = admin_c.get("/admin/api/needs/inquiries?category=billing", headers=H).json()
    assert not any(i["inquiry_id"] == inquiry_id for i in filtered_none["items"])

    # 5. Operator updates status and responds
    update_res = admin_c.patch(
        f"/admin/api/needs/inquiries/{inquiry_id}",
        json={"status": "resolved", "admin_response": "Verified tool schema under A2A v0.3 specifications and sent clarification email."},
        headers=H
    )
    assert update_res.status_code == 200
    assert update_res.json()["status"] == "resolved"

    # Verify resolved status persisted
    refreshed = admin_c.get("/admin/api/needs/inquiries?status=resolved", headers=H).json()
    resolved_item = next(i for i in refreshed["items"] if i["inquiry_id"] == inquiry_id)
    assert resolved_item["status"] == "resolved"
    assert "Verified tool schema" in resolved_item["admin_response"]


def test_privacy_rights_opt_out_and_compliance(env):
    world, front_c, admin_c = env

    # 1. Submit privacy opt-out with GPC signal
    payload = {
        "request_type": "ccpa_opt_out",
        "email": "california.user@domain.com",
        "details": "Opting out of data sharing under CCPA/CPRA"
    }
    headers = {"Sec-GPC": "1", "User-Agent": "PrivacyAgent/2.0"}
    res = front_c.post("/api/privacy/opt-out", json=payload, headers=headers)
    assert res.status_code == 200
    d = res.json()
    assert d["ok"] is True
    assert d["gpc_detected"] is True
    request_id = d["request_id"]
    assert request_id.startswith("prv_")

    # 2. Verify admin privacy list & statutory deadline
    prv_list = admin_c.get("/admin/api/needs/privacy", headers=H).json()
    item = next((i for i in prv_list["items"] if i["request_id"] == request_id), None)
    assert item is not None
    assert item["request_type"] == "ccpa_opt_out"
    assert item["gpc_detected"] == 1
    assert item["statutory_deadline"] > item["created_at"]
    assert item["proof_hash"] is not None

    # 3. Update compliance audit record
    update_res = admin_c.patch(
        f"/admin/api/needs/privacy/{request_id}",
        json={"status": "completed", "notes": "Synthetic reviewed preference evidence", "proof_hash": "a" * 64},
        headers=H
    )
    assert update_res.status_code == 200
    assert update_res.json()["status"] == "completed"


def test_ftc_one_click_unsubscribe_and_reactivation(env):
    world, front_c, admin_c = env

    # 1. Create visitor through chat
    chat_res = front_c.post("/chat", json={"message": "Looking for crypto arbitrage bots"}).json()
    token = chat_res["visitor"]["token"]
    assert token is not None

    # Verify initial notify is True
    me_res = front_c.get("/me", headers={"X-Visitor-Token": token}).json()
    assert me_res["notify"] is True

    # 2. 1-Click Unsubscribe under FTC standard
    unsub_payload = {"token": token, "reason": "Testing completed", "source": "ftc_footer"}
    unsub_res = front_c.post("/unsubscribe", json=unsub_payload, headers={"X-Visitor-Token": token})
    assert unsub_res.status_code == 200
    unsub_data = unsub_res.json()
    assert unsub_data["ok"] is True
    cancel_id = unsub_data["request_id"]
    assert cancel_id.startswith("cnl_")

    # Verify notify is now False
    me_after = front_c.get("/me", headers={"X-Visitor-Token": token}).json()
    assert me_after["notify"] is False

    # 3. Verify Admin cancellation audit log
    cancellations = admin_c.get("/admin/api/needs/cancellations", headers=H).json()
    match = next((c for c in cancellations["items"] if c["request_id"] == cancel_id), None)
    assert match is not None
    assert match["reason"] == "Testing completed"
    assert match["source"] == "ftc_footer"
    assert match["status"] == "cancelled"

    # 4. Administrative notes cannot create renewed customer consent
    reactivate_res = admin_c.post(f"/admin/api/needs/cancellations/{cancel_id}/reactivate", json={"notes": "Client requested reactivation"}, headers=H)
    assert reactivate_res.status_code == 409

    # Customer must reapply and verify independently
    me_restored = front_c.get("/me", headers={"X-Visitor-Token": token}).json()
    assert me_restored["notify"] is False


def test_customer_requests_summary_and_needs_offers(env):
    world, front_c, admin_c = env

    # 1. Summary API returns counts across all 4 sub-domains
    s_res = admin_c.get("/admin/api/needs/summary", headers=H)
    assert s_res.status_code == 200
    summary = s_res.json()
    assert "needs" in summary
    assert "inquiries" in summary
    assert "cancellations" in summary
    assert "privacy" in summary

    # 2. Needs list and search filtering
    needs_res = admin_c.get("/admin/api/needs", headers=H)
    assert needs_res.status_code == 200
    items = needs_res.json()["items"]
    assert isinstance(items, list)

    if items:
        need_id = items[0]["need_id"]
        offers_res = admin_c.get(f"/admin/api/needs/{need_id}/offers", headers=H)
        assert offers_res.status_code == 200
        assert "items" in offers_res.json()


def test_ui_and_frontend_compliance(env, legacy_public_entry):
    world, front_c, admin_c = env

    # 1. Admin UI contains 4-tab modern Customer Requests hub
    ui = admin_c.get("/admin/ui").text
    assert 'data-panel="needs"' in ui
    assert 'id="needsSubtabs"' in ui
    assert 'data-subtab="needs_list"' in ui
    assert 'data-subtab="inquiries"' in ui
    assert 'data-subtab="cancellations"' in ui
    assert 'data-subtab="privacy"' in ui
    assert 'id="inquiryModal"' in ui
    assert 'id="needOffersModal"' in ui

    # 2. Zero raw emojis in newly added needs panel
    needs_slice = ui[ui.find('<section data-panel="needs"'):ui.find('</section>', ui.find('<section data-panel="needs"'))]
    emoji_pattern = re.compile(r'[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|[\u2b50-\u2b55]')
    assert len(emoji_pattern.findall(needs_slice)) == 0, "No raw emojis permitted in needs panel"

    # 3. Public HTML contains interactive Contact form and FTC options
    html = front_c.get("/", headers={"accept": "text/html"}).text
    assert 'id="contactInquiryForm"' in html
    assert 'submitContactInquiry' in html
    assert 'id="inqCategory"' in html
    assert "taskPreferences" in html and 'id="ftcCancelReason"' not in html
    assert 'api("/api/contact/submit"' in html
    assert 'api("/api/privacy/opt-out"' in html
