"""Tests for external agent ad distribution, A2A/MCP relay partners, owner consent, and viewer connection."""

from uuid import uuid4

from fastapi import FastAPI
import pytest
from starlette.testclient import TestClient

from agent_market.ad_coin.v2.access import COMMERCIAL_CAPABILITIES, HUMAN_CAPABILITIES, OPERATOR_CAPABILITY
from agent_market.ad_coin.v2.ad_relay import AdRelayGateway
from agent_market.ad_coin.v2.commercial import date_text, etag
from agent_market.ad_coin.v2.contracts import MODEL_ASSET, canonical_bytes, ContractError
from agent_market.ad_coin.v2.identity import Kind
from agent_market.ad_coin.v2.key_vault import KeyVault
from agent_market.ad_coin.v2.live_service import (
    DEFAULT_LANGUAGES,
    DEFAULT_REGIONS,
    DEFAULT_TAXONOMY,
    build_live_service,
    create_live_ad_coin_v2_router,
)

MOCK_TLS = lambda request: request.headers.get("x-mock-tls") == "verified"  # noqa: E731 - test reviewer only
from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_persistence import store  # noqa: F401

NOW = 1_800_000_000_000


def uid() -> str:
    return str(uuid4())


def setup_live_campaign_and_offer(client, commercial, resolver, user_owner, user_headers):
    """Fixture helper to create an approved campaign and a reserved offer through the live API."""
    advertiser_id = uid()
    editor_owner = uid()
    editor_principal_id = uid()
    editor_token = "ed_token_" + uid()
    editor_csrf = "csrf_" + uid()
    reviewer_token = "rev_token_" + uid()
    reviewer_principal_id = uid()

    commercial.access.provision_principal(
        editor_principal_id, Kind.HUMAN, owner_id=editor_owner, capabilities=COMMERCIAL_CAPABILITIES
    )
    commercial.access.provision_principal(
        reviewer_principal_id, Kind.REVIEWER, capabilities=frozenset({"review.decide"})
    )
    commercial.access.set_model_activation(True)
    available_acc = commercial.access.provision_advertiser(advertiser_id, editor_owner)
    commercial.access.grant(advertiser_id, editor_principal_id, "campaign.edit")
    commercial.access.grant(advertiser_id, editor_principal_id, "campaign.read")
    commercial.access.grant(advertiser_id, editor_principal_id, "budget.approve")

    clearing = commercial.ledger.create_account(uid(), "external_clearing")
    commercial.ledger.post(
        "fund-adv-" + uid(),
        [(clearing, "-200000"), (available_acc, "200000")],
        kind="model_seed",
    )

    expires_at = (NOW // 1000) + 3600
    resolver.register_human_session(
        editor_token, editor_csrf, principal_id=editor_principal_id, owner_id=editor_owner, epoch=1, expires_at=expires_at
    )
    resolver.register_reviewer_token(
        reviewer_token, principal_id=reviewer_principal_id, cert_fingerprint="fp_" + uid(), epoch=1, expires_at=expires_at
    )

    editor_headers = {
        "Cookie": f"__Host-ac_customer_session={editor_token}",
        "X-CSRF-Token": editor_csrf,
        "X-AIAC-Contract": "v6.2",
    }
    reviewer_headers = {
        "Authorization": f"Bearer {reviewer_token}",
        "X-Mock-TLS": "verified",
        "X-AIAC-Contract": "v6.2",
    }

    # 1. Create Campaign Draft
    c_res = client.post(
        f"/api/ad-coin/v2/advertisers/{advertiser_id}/campaigns",
        headers={**editor_headers, "Idempotency-Key": uid()},
        json={
            "name": "A2A Relay Network Campaign",
            "asset_id": MODEL_ASSET,
            "total_budget_atoms": "50000",
            "daily_budget_atoms": "25000",
            "budget_timezone": "UTC",
            "starts_at": date_text(NOW - 1000),
            "ends_at": date_text(NOW + 86400000),
            "task_categories": ["general"],
            "regions": ["US"],
            "creative_text": "Next-gen Autonomous AI Agent Discovery.",
            "gross_p1_atoms": "1000",
            "min_exposure_ms": 15000,
            "split_policy_id": "default_v5",
            "renderer_profile": "platform_text_v1",
        },
    )
    assert c_res.status_code == 200, c_res.text
    campaign = c_res.json()
    campaign_id = campaign["id"]

    # 2. Review Request
    r_res = client.post(
        f"/api/ad-coin/v2/advertisers/{advertiser_id}/campaigns/{campaign_id}/review-request",
        headers={**editor_headers, "If-Match": c_res.headers["etag"], "Idempotency-Key": uid()},
        json={"revision_hash": campaign["revision_hash"]},
    )
    assert r_res.status_code == 200, r_res.text
    review = r_res.json()

    # 3. Reviewer Decision
    evidence_id = commercial.record_evidence(review["id"], "e" * 64)
    dec_res = client.post(
        f"/api/ad-coin/v2/reviews/{review['id']}/decisions",
        headers={**reviewer_headers, "If-Match": etag(review), "Idempotency-Key": uid()},
        json={
            "revision_hash": review["revision_hash"],
            "verdict": "eligible",
            "reason_code": "verified",
            "evidence_ref": evidence_id,
        },
    )
    assert dec_res.status_code == 200, dec_res.text

    # Fetch latest campaign state
    camp_res = client.get(
        f"/api/ad-coin/v2/advertisers/{advertiser_id}/campaigns/{campaign_id}",
        headers=editor_headers,
    )
    assert camp_res.status_code == 200
    campaign = camp_res.json()

    # 4. Human Approval
    intended = commercial.contract.parse(
        "approveCampaign",
        canonical_bytes({
            "revision_hash": campaign["revision_hash"],
            "fresh_action_id": uid(),
            "fresh_action_proof": "p" * 43,
        }),
        path_parameters={"advertiser_id": advertiser_id, "campaign_id": campaign_id},
        if_match=etag(campaign),
    )
    chal_res = client.post(
        "/api/ad-coin/v2/human-challenges",
        headers={**editor_headers, "Idempotency-Key": uid()},
        json={
            "action": "approve_campaign",
            "target_id": campaign_id,
            "target_revision_hash": campaign["revision_hash"],
            "request_digest": intended.semantic_digest,
        },
    )
    assert chal_res.status_code == 200, chal_res.text
    chal = chal_res.json()

    app_res = client.post(
        f"/api/ad-coin/v2/advertisers/{advertiser_id}/campaigns/{campaign_id}/approvals",
        headers={**editor_headers, "If-Match": etag(campaign), "Idempotency-Key": uid()},
        json={
            "revision_hash": campaign["revision_hash"],
            "fresh_action_id": chal["fresh_action_id"],
            "fresh_action_proof": chal["proof_challenge"],
        },
    )
    assert app_res.status_code == 200, app_res.text
    app_camp = app_res.json()

    # 5. Activation
    act_res = client.post(
        f"/api/ad-coin/v2/advertisers/{advertiser_id}/campaigns/{campaign_id}/activation",
        headers={**editor_headers, "If-Match": etag(app_camp), "Idempotency-Key": uid()},
        json={"revision_hash": app_camp["revision_hash"]},
    )
    assert act_res.status_code == 200, act_res.text

    # 6. User Ad Preferences
    commercial.access.provision_preferences(user_owner, now_ms=NOW)
    pref = client.get("/api/ad-coin/v2/ad-preferences", headers=user_headers).json()
    intended_pref = commercial.contract.parse(
        "setAdPreferences",
        canonical_bytes({
            "fresh_action_id": uid(),
            "fresh_action_proof": "p" * 43,
            "receive_offers": True,
            "context_fields": ["task_category", "language", "coarse_region"],
            "max_offers_per_day": 10,
            "max_ads_per_campaign_day": 2,
            "max_ads_per_day": 5,
            "max_ad_ms_per_day": 90000,
        }),
        if_match=etag(pref),
    )
    chal_pref = client.post(
        "/api/ad-coin/v2/human-challenges",
        headers={**user_headers, "Idempotency-Key": uid()},
        json={
            "action": "set_ad_preferences",
            "target_id": pref["id"],
            "target_revision_hash": pref["revision_hash"],
            "request_digest": intended_pref.semantic_digest,
        },
    ).json()

    client.put(
        "/api/ad-coin/v2/ad-preferences",
        headers={**user_headers, "If-Match": etag(pref), "Idempotency-Key": uid()},
        json={
            "fresh_action_id": chal_pref["fresh_action_id"],
            "fresh_action_proof": chal_pref["proof_challenge"],
            "receive_offers": True,
            "context_fields": ["task_category", "language", "coarse_region"],
            "max_offers_per_day": 10,
            "max_ads_per_campaign_day": 2,
            "max_ads_per_day": 5,
            "max_ad_ms_per_day": 90000,
        },
    )

    # 7. Request Offer
    off_res = client.post(
        "/api/ad-coin/v2/offers",
        headers={**user_headers, "Idempotency-Key": uid()},
        json={
            "task_category": "general",
            "language": "en",
            "coarse_region": "US",
            "selection_digest": "0" * 64,
        },
    )
    assert off_res.status_code in (200, 202), off_res.text
    offer_id = off_res.json()["resource_id"]

    return campaign_id, offer_id, available_acc


def test_ad_relay_gateway_lifecycle(store):  # noqa: F811
    store.migrate_model()

    vault = KeyVault()
    router = create_live_ad_coin_v2_router(
        store,
        mtls_verifier=MOCK_TLS,
        key_vault=vault,
        taxonomy=DEFAULT_TAXONOMY,
        regions=DEFAULT_REGIONS,
        languages=DEFAULT_LANGUAGES,
        clock_ms=lambda: NOW,
        include_workspace=True,
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    commercial, resolver, _ = build_live_service(
        store,
        mtls_verifier=MOCK_TLS,
        key_vault=vault,
        taxonomy=DEFAULT_TAXONOMY,
        regions=DEFAULT_REGIONS,
        languages=DEFAULT_LANGUAGES,
        clock_ms=lambda: NOW,
    )
    gateway = AdRelayGateway(commercial.store, commercial.ledger, commercial.access, clock=lambda: NOW // 1000)

    user_owner = uid()
    user_principal_id = uid()
    user_token = "usr_token_" + uid()
    user_csrf = "csrf_" + uid()

    commercial.access.provision_principal(
        user_principal_id, Kind.HUMAN, owner_id=user_owner, capabilities=HUMAN_CAPABILITIES
    )
    commercial.access.provision_wallet(user_owner)

    expires_at = (NOW // 1000) + 3600
    resolver.register_human_session(
        user_token, user_csrf, principal_id=user_principal_id, owner_id=user_owner, epoch=1, expires_at=expires_at
    )
    user_headers = {
        "Cookie": f"__Host-ac_customer_session={user_token}",
        "X-CSRF-Token": user_csrf,
        "X-AIAC-Contract": "v6.2",
    }

    partner_owner = uid()
    partner_operator_acc = commercial.ledger.create_account(partner_owner, "operator_payable")

    # 1. Register Relay Partner (A2A)
    partner_a2a = gateway.register_partner(
        name="A2A Agent Network Hub",
        protocol="a2a",
        endpoint_url="https://agentconcierge.biz/a2a/relay",
        fee_basis_points=500,  # 5%
        operator_account_id=partner_operator_acc,
    )
    assert partner_a2a["name"] == "A2A Agent Network Hub"
    assert partner_a2a["protocol"] == "a2a"
    assert partner_a2a["fee_basis_points"] == 500
    assert partner_a2a["status"] == "active"

    # Register Relay Partner (MCP)
    partner_mcp = gateway.register_partner(
        name="MCP Tool Discovery Server",
        protocol="mcp",
        endpoint_url="https://agentconcierge.biz/mcp/sponsored",
        fee_basis_points=1000,  # 10%
        operator_account_id=partner_operator_acc,
    )
    assert partner_mcp["protocol"] == "mcp"

    # Negative registration validation: invalid protocol & fee out of bounds
    with pytest.raises(ContractError, match="unsupported_relay_protocol"):
        gateway.register_partner(
            name="Bad Protocol",
            protocol="unknown",
            endpoint_url="https://example.com",
            fee_basis_points=100,
            operator_account_id=partner_operator_acc,
        )

    with pytest.raises(ContractError, match="invalid_fee_basis_points"):
        gateway.register_partner(
            name="Exorbitant Fee",
            protocol="a2a",
            endpoint_url="https://example.com",
            fee_basis_points=5000,
            operator_account_id=partner_operator_acc,
        )

    # 2. Setup Campaign and Offer
    campaign_id, offer_id, _ = setup_live_campaign_and_offer(client, commercial, resolver, user_owner, user_headers)

    # 3. Dispatch to A2A Partner
    a2a_result = gateway.dispatch_ad_offer(
        partner_id=partner_a2a["id"],
        owner_id=user_owner,
        campaign_id=campaign_id,
        offer_id=offer_id,
        user_reward_atoms=100,
        headline="AI Research Suite",
        summary="Automate your literature reviews",
        hop_count=1,
    )
    dispatch_a2a = a2a_result["dispatch"]
    msg_a2a = a2a_result["message"]

    assert dispatch_a2a["status"] == "dispatched"
    assert dispatch_a2a["user_reward_atoms"] == "100"
    assert dispatch_a2a["relay_fee_atoms"] == "5"  # 5% of 100
    assert "https://agentconcierge.biz/ad-coin/v2/view/" in dispatch_a2a["platform_viewer_url"]

    # Verify A2A envelope formatting
    assert msg_a2a["protocol"] == "a2a"
    assert msg_a2a["message_type"] == "ad_proposal"
    assert msg_a2a["creative"]["headline"] == "AI Research Suite"
    assert msg_a2a["rewards"]["user_reward_atoms"] == "100"
    assert msg_a2a["rewards"]["relay_fee_atoms"] == "5"
    assert msg_a2a["hop_count"] == 1

    # 4. Anti-Abuse: Duplicate offer dispatch rejection
    with pytest.raises(ContractError, match="offer_already_dispatched"):
        gateway.dispatch_ad_offer(
            partner_id=partner_mcp["id"],
            owner_id=user_owner,
            campaign_id=campaign_id,
            offer_id=offer_id,
            user_reward_atoms=100,
            headline="Duplicated Offer",
            summary="",
        )

    # Hop count bounds check (> 3 hops rejected)
    with pytest.raises(ContractError, match="max_hop_count_exceeded"):
        gateway.dispatch_ad_offer(
            partner_id=partner_mcp["id"],
            owner_id=user_owner,
            campaign_id=campaign_id,
            offer_id=offer_id,
            user_reward_atoms=100,
            headline="Oversized Hops",
            summary="",
            hop_count=4,
        )

    # 5. Owner Consent
    consented_disp = gateway.consent_relay_dispatch(dispatch_a2a["id"], user_owner)
    assert consented_disp["status"] == "consented"
    assert consented_disp["consented_at"] is not None

    # Consent alone never pays: settlement waits for the view the platform records itself.
    with pytest.raises(ContractError, match="issuance_only"):  # settlement is closed (11-10, issuance only)
        gateway.settle_relay_dispatch(dispatch_a2a["id"])

    # 6. Platform Viewer Connection (DEC-03)
    viewer_session = gateway.open_viewer_session(dispatch_a2a["id"], dispatch_a2a["relay_token"])
    assert viewer_session["status"] == "viewed"
    assert viewer_session["view_requirement"]["min_duration_ms"] == 15000
    assert viewer_session["user_reward_atoms"] == "100"

    # The same GET again (a retry, or a TLS 0-RTT replay) returns the same session, not 409 (11-12 PM)
    assert gateway.open_viewer_session(dispatch_a2a["id"], dispatch_a2a["relay_token"]) == viewer_session

    # Wrong token rejected
    with pytest.raises(ContractError, match="invalid_relay_token"):
        gateway.open_viewer_session(dispatch_a2a["id"], "wrong-token-abc")

    # 7. Settle Relay Dispatch and Verify Ledger Conservation
    # Closed 11-10: the relay fee was minted outside issuance, so settlement refuses and pays nothing.
    with pytest.raises(ContractError, match="issuance_only"):
        gateway.settle_relay_dispatch(dispatch_a2a["id"])
    assert commercial.ledger.account(partner_operator_acc)["balance_atoms"] == "0"

    audit = commercial.ledger.audit()
    assert int(audit["beneficial_atoms"]) + int(audit["clearing_atoms"]) == 0

    # 8. MCP Formatting Verification
    # Request a second offer for user
    off2_res = client.post(
        "/api/ad-coin/v2/offers",
        headers={**user_headers, "Idempotency-Key": uid()},
        json={
            "task_category": "general",
            "language": "en",
            "coarse_region": "US",
            "selection_digest": "1" * 64,
        },
    )
    assert off2_res.status_code in (200, 202), off2_res.text
    offer2_id = off2_res.json()["resource_id"]

    mcp_result = gateway.dispatch_ad_offer(
        partner_id=partner_mcp["id"],
        owner_id=user_owner,
        campaign_id=campaign_id,
        offer_id=offer2_id,
        user_reward_atoms=100,
        headline="MCP Analysis Tool",
        summary="Deep query capabilities",
        hop_count=2,
    )
    disp_mcp = mcp_result["dispatch"]
    msg_mcp = mcp_result["message"]

    assert msg_mcp["protocol"] == "mcp"
    assert msg_mcp["tool"] == "present_sponsored_offer"
    assert msg_mcp["arguments"]["reward_atoms"] == "100"

    # Reject dispatch
    rejected = gateway.reject_dispatch(disp_mcp["id"], user_owner)
    assert rejected["status"] == "rejected"

    # Revoke partner and test inactive dispatch block
    revoked = gateway.revoke_partner(partner_mcp["id"])
    assert revoked["status"] == "revoked"


def test_ad_relay_http_routes(store):  # noqa: F811
    store.migrate_model()

    vault = KeyVault()
    router = create_live_ad_coin_v2_router(
        store,
        mtls_verifier=MOCK_TLS,
        key_vault=vault,
        taxonomy=DEFAULT_TAXONOMY,
        regions=DEFAULT_REGIONS,
        languages=DEFAULT_LANGUAGES,
        clock_ms=lambda: NOW,
        include_workspace=True,
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    commercial, resolver, _ = build_live_service(
        store,
        mtls_verifier=MOCK_TLS,
        key_vault=vault,
        taxonomy=DEFAULT_TAXONOMY,
        regions=DEFAULT_REGIONS,
        languages=DEFAULT_LANGUAGES,
        clock_ms=lambda: NOW,
    )

    user_owner = uid()
    user_principal_id = uid()
    user_token = "usr_sess_" + uid()
    user_csrf = "csrf_" + uid()

    commercial.access.provision_principal(
        user_principal_id, Kind.HUMAN, owner_id=user_owner, capabilities=HUMAN_CAPABILITIES
    )
    commercial.access.provision_wallet(user_owner)

    expires_at = (NOW // 1000) + 3600
    resolver.register_human_session(
        user_token, user_csrf, principal_id=user_principal_id, owner_id=user_owner, epoch=1, expires_at=expires_at
    )

    headers = {
        "Cookie": f"__Host-ac_customer_session={user_token}",
        "X-CSRF-Token": user_csrf,
        "X-AIAC-Contract": "v6.2",
    }

    partner_owner = uid()
    operator_acc = commercial.ledger.create_account(partner_owner, "operator_payable")

    # Platform staff hold the explicit operator capability; ordinary people do not.
    staff_principal, staff_owner = uid(), uid()
    staff_token, staff_csrf = "staff_sess_" + uid(), "csrf_" + uid()
    commercial.access.provision_principal(
        staff_principal, Kind.HUMAN, owner_id=staff_owner,
        capabilities=HUMAN_CAPABILITIES | {OPERATOR_CAPABILITY},
    )
    resolver.register_human_session(
        staff_token, staff_csrf, principal_id=staff_principal, owner_id=staff_owner, epoch=1, expires_at=expires_at
    )
    staff = {"Cookie": f"__Host-ac_customer_session={staff_token}", "X-CSRF-Token": staff_csrf,
             "X-AIAC-Contract": "v6.2"}
    partner_body = {"name": "Live A2A Network", "protocol": "a2a",
                    "endpoint_url": "https://agentconcierge.biz/a2a/live", "fee_basis_points": 700,
                    "operator_account_id": operator_acc}
    refused = client.post("/api/ad-coin/v2/relays/partners", headers=headers, json=partner_body)
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "operator_required", refused.text
    assert client.get("/api/ad-coin/v2/relays/partners", headers=headers).status_code == 403
    no_csrf = {key: value for key, value in staff.items() if key != "X-CSRF-Token"}
    refused_csrf = client.post("/api/ad-coin/v2/relays/partners", headers=no_csrf, json=partner_body)
    assert refused_csrf.status_code == 403, refused_csrf.text  # operator writes need the CSRF proof
    private = client.post("/api/ad-coin/v2/relays/partners", headers=staff,
                          json={**partner_body, "endpoint_url": "https://192.168.0.10/relay"})
    assert private.status_code == 422, private.text

    # 1. Register Partner via HTTP
    reg_res = client.post(
        "/api/ad-coin/v2/relays/partners",
        headers=staff,
        json={
            "name": "Live A2A Network",
            "protocol": "a2a",
            "endpoint_url": "https://agentconcierge.biz/a2a/live",
            "fee_basis_points": 700,
            "operator_account_id": operator_acc,
        },
    )
    assert reg_res.status_code == 201, reg_res.text
    partner_id = reg_res.json()["id"]

    # 2. List Partners via HTTP
    list_res = client.get("/api/ad-coin/v2/relays/partners", headers=staff)
    assert list_res.status_code == 200
    partners = list_res.json()["partners"]
    assert any(p["id"] == partner_id for p in partners)

    # 3. Setup Campaign and Offer
    campaign_id, offer_id, _ = setup_live_campaign_and_offer(client, commercial, resolver, user_owner, headers)

    # 4. Dispatch Ad Offer via HTTP
    disp_res = client.post(
        "/api/ad-coin/v2/relays/dispatch",
        headers=headers,
        json={
            "partner_id": partner_id,
            "campaign_id": campaign_id,
            "offer_id": offer_id,
            "user_reward_atoms": 100,
            "headline": "Live HTTP Ad",
            "summary": "Full REST dispatch test",
            "hop_count": 1,
        },
    )
    assert disp_res.status_code == 201, disp_res.text
    disp_data = disp_res.json()["dispatch"]
    dispatch_id = disp_data["id"]
    relay_token = disp_data["relay_token"]

    # 5. List Owner Dispatches via HTTP
    owner_disps_res = client.get("/api/ad-coin/v2/relays/dispatches", headers=headers)
    assert owner_disps_res.status_code == 200
    dispatches = owner_disps_res.json()["dispatches"]
    assert any(d["id"] == dispatch_id for d in dispatches)

    # 6. Consent Dispatch via HTTP
    consent_res = client.post(f"/api/ad-coin/v2/relays/{dispatch_id}/consent", headers=headers)
    assert consent_res.status_code == 200, consent_res.text
    assert consent_res.json()["status"] == "consented"

    # 7. Connect to Platform Viewer via HTTP (DEC-03)
    view_res = client.get(f"/api/ad-coin/v2/relays/{dispatch_id}/view?token={relay_token}")
    assert view_res.status_code == 200, view_res.text
    assert view_res.json()["status"] == "viewed"
    assert "creative" in view_res.json()

    # 8. Settle Dispatch via HTTP
    early = client.post(f"/api/ad-coin/v2/relays/{dispatch_id}/settle", headers=headers)
    assert early.status_code == 403, early.text  # the person cannot settle their own relay
    settle_res = client.post(f"/api/ad-coin/v2/relays/{dispatch_id}/settle", headers=staff)
    assert settle_res.status_code == 403 and settle_res.json()["error"]["code"] == "issuance_only"

    # 9. Settlement is closed (issuance only), so the dispatch stays 'viewed': the same GET again (a retry or
    # a TLS 0-RTT replay) returns the same viewer session with 200, not 409 (11-12 PM); a wrong token is refused.
    view_again = client.get(f"/api/ad-coin/v2/relays/{dispatch_id}/view?token={relay_token}")
    assert view_again.status_code == 200 and view_again.json() == view_res.json()
    wrong = client.get(f"/api/ad-coin/v2/relays/{dispatch_id}/view?token=wrong-token-abc")
    assert wrong.status_code == 403
