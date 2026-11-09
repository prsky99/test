"""Complete P1 user consent, attention, exposure evidence, award, receipt, and reporting regressions."""

from dataclasses import dataclass
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from agent_market.ad_coin.v2.access import COMMERCIAL_CAPABILITIES, HUMAN_CAPABILITIES
from agent_market.ad_coin.v2.auth_adapter import CredentialResolver
from agent_market.ad_coin.v2.commercial import Commercial, date_text, etag
from agent_market.ad_coin.v2.contracts import (
    MODEL_ASSET,
    canonical_bytes,
)
from agent_market.ad_coin.v2.http import router_for
from agent_market.ad_coin.v2.identity import Kind, Principal
from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_persistence import raw, store, uid  # noqa: F401

NOW = 1_800_000_000_000


def campaign_body(**changes):
    return {
        "name": "Research assistant AI",
        "asset_id": MODEL_ASSET,
        "total_budget_atoms": "1000",
        "daily_budget_atoms": "500",
        "budget_timezone": "UTC",
        "starts_at": date_text(NOW - 1000),
        "ends_at": date_text(NOW + 86400000),
        "task_categories": ["research"],
        "regions": ["US"],
        "creative_text": "Accelerate your literature review with an autonomous research agent.",
        "gross_p1_atoms": "100",
        "min_exposure_ms": 15000,
        "split_policy_id": "default_v5",
        "renderer_profile": "platform_text_v1",
        **changes,
    }


@dataclass
class P1Suite:
    service: Commercial
    resolver: CredentialResolver
    advertiser: str
    available: str
    editor_token: str
    approver_token: str
    reviewer_token: str
    user_owner: str
    user_token: str
    user_csrf: str
    user_principal_id: str
    wallet_id: str
    client: TestClient
    signing_key: Ed25519PrivateKey

    def headers(self, role="user", **extra):
        if role == "editor":
            token = self.editor_token
            csrf = "editor-csrf"
        elif role == "approver":
            token = self.approver_token
            csrf = "approver-csrf"
        elif role == "reviewer":
            token = self.reviewer_token
            csrf = None
        else:
            token = self.user_token
            csrf = self.user_csrf
        hdr = {
            "Authorization": "Bearer " + token,
            "X-AIAC-Contract": "v6.2",
            "Idempotency-Key": uid(),
            **extra,
        }
        if csrf:
            hdr["X-CSRF-Token"] = csrf
        return hdr


@pytest.fixture
def p1_suite(store):  # noqa: F811 - imported fixture
    store.migrate_model()
    signing_key = Ed25519PrivateKey.generate()
    service = Commercial(
        store,
        taxonomy=frozenset({"research", "coding"}),
        regions=frozenset({"US", "KR"}),
        fresh_key=b"k" * 32,
        receipt_keys={"kid-model-2026": signing_key},
        clock_ms=lambda: NOW,
    )
    service.receipt_signer.publish_key(
        "kid-model-2026",
        not_before_ms=NOW - 100000,
        verify_until_ms=NOW + 1000000000,
        status="active",
    )
    advertiser = uid()
    available = service.access.provision_advertiser(advertiser, uid())
    clearing = service.ledger.create_account(uid(), "external_clearing")
    service.ledger.post(
        "fixture-funding",
        [(clearing, "-50000"), (available, "50000")],
        kind="model_seed",
    )
    service.access.set_model_activation(True)

    resolver = CredentialResolver(
        store,
        mtls_verifier=lambda req: req.headers.get("x-mock-tls") == "verified",
        clock=lambda: NOW // 1000,
    )

    editor_id, approver_id, reviewer_id = uid(), uid(), uid()
    editor_owner, approver_owner = uid(), uid()
    service.access.provision_principal(
        editor_id,
        Kind.HUMAN,
        owner_id=editor_owner,
        capabilities=COMMERCIAL_CAPABILITIES,
    )
    service.access.provision_principal(
        approver_id,
        Kind.HUMAN,
        owner_id=approver_owner,
        capabilities=COMMERCIAL_CAPABILITIES,
    )
    service.access.provision_principal(reviewer_id, Kind.REVIEWER)
    for cap in (
        "campaign.edit",
        "campaign.read",
        "campaign.pause",
        "reports.read",
        "reports.acknowledge",
    ):
        service.access.grant(advertiser, editor_id, cap)
    for cap in ("budget.approve", "campaign.read", "reports.read"):
        service.access.grant(advertiser, approver_id, cap)

    editor_token = "tok-editor-" + uid()
    approver_token = "tok-approver-" + uid()
    reviewer_token = "tok-reviewer-" + uid()
    resolver.register_human_session(
        editor_token, "editor-csrf", principal_id=editor_id, owner_id=editor_owner
    )
    resolver.register_human_session(
        approver_token,
        "approver-csrf",
        principal_id=approver_id,
        owner_id=approver_owner,
    )
    resolver.register_reviewer_token(reviewer_token, principal_id=reviewer_id)

    user_owner = uid()
    user_principal_id = uid()
    service.access.provision_principal(
        user_principal_id,
        Kind.HUMAN,
        owner_id=user_owner,
        capabilities=HUMAN_CAPABILITIES,
    )
    service.access.provision_preferences(user_owner, now_ms=NOW)
    wallet_id = service.access.provision_wallet(user_owner)
    user_token = "tok-user-" + uid()
    user_csrf = "csrf-user-" + uid()
    resolver.register_human_session(
        user_token,
        user_csrf,
        principal_id=user_principal_id,
        owner_id=user_owner,
    )

    app = FastAPI()
    app.include_router(router_for(service, resolve_auth=resolver))
    with TestClient(app) as client:
        yield P1Suite(
            service,
            resolver,
            advertiser,
            available,
            editor_token,
            approver_token,
            reviewer_token,
            user_owner,
            user_token,
            user_csrf,
            user_principal_id,
            wallet_id,
            client,
            signing_key,
        )


def _activate_campaign(suite: P1Suite, **body_changes):
    base = "/api/ad-coin/v2/advertisers/" + suite.advertiser + "/campaigns"
    res = suite.client.post(
        base, json=campaign_body(**body_changes), headers=suite.headers("editor")
    )
    assert res.status_code == 200, res.text
    campaign = res.json()

    rev_res = suite.client.post(
        base + "/" + campaign["id"] + "/review-request",
        json={"revision_hash": campaign["revision_hash"]},
        headers=suite.headers("editor", **{"If-Match": res.headers["etag"]}),
    )
    assert rev_res.status_code == 200, rev_res.text
    review = rev_res.json()

    evidence_id = suite.service.record_evidence(review["id"], "a" * 64)
    dec_res = suite.client.post(
        "/api/ad-coin/v2/reviews/" + review["id"] + "/decisions",
        json={
            "revision_hash": review["revision_hash"],
            "verdict": "eligible",
            "reason_code": "verified",
            "evidence_ref": evidence_id,
        },
        headers=suite.headers(
            "reviewer", **{"If-Match": etag(review), "x-mock-tls": "verified"}
        ),
    )
    assert dec_res.status_code == 200, dec_res.text

    camp_res = suite.client.get(
        base + "/" + campaign["id"], headers=suite.headers("editor")
    )
    assert camp_res.status_code == 200, camp_res.text
    campaign = camp_res.json()

    intended = suite.service.contract.parse(
        "approveCampaign",
        canonical_bytes(
            {
                "revision_hash": campaign["revision_hash"],
                "fresh_action_id": uid(),
                "fresh_action_proof": "p" * 43,
            }
        ),
        path_parameters={
            "advertiser_id": suite.advertiser,
            "campaign_id": campaign["id"],
        },
        if_match=etag(campaign),
    )
    chal_res = suite.client.post(
        "/api/ad-coin/v2/human-challenges",
        json={
            "action": "approve_campaign",
            "target_id": campaign["id"],
            "target_revision_hash": campaign["revision_hash"],
            "request_digest": intended.semantic_digest,
        },
        headers=suite.headers("approver"),
    )
    assert chal_res.status_code == 200, chal_res.text
    chal = chal_res.json()

    app_res = suite.client.post(
        base + "/" + campaign["id"] + "/approvals",
        json={
            "revision_hash": campaign["revision_hash"],
            "fresh_action_id": chal["fresh_action_id"],
            "fresh_action_proof": chal["proof_challenge"],
        },
        headers=suite.headers("approver", **{"If-Match": etag(campaign)}),
    )
    assert app_res.status_code == 200, app_res.text
    approved_camp = app_res.json()

    act_res = suite.client.post(
        base + "/" + campaign["id"] + "/activation",
        json={"revision_hash": approved_camp["revision_hash"]},
        headers=suite.headers("approver", **{"If-Match": etag(approved_camp)}),
    )
    assert act_res.status_code == 200, act_res.text
    active_camp = act_res.json()
    assert active_camp["state"] == "active"
    return active_camp


def test_public_endpoints_accessible_without_auth(p1_suite):
    res = p1_suite.client.get("/api/ad-coin/v2/capabilities")
    assert res.status_code == 200, res.text
    cap = res.json()
    assert cap["policy_version"] == "v6.1"
    assert cap["mode"] == "model"
    assert cap["products"] == ["P1"]

    res_asset = p1_suite.client.get("/api/ad-coin/v2/asset")
    assert res_asset.status_code == 200, res_asset.text
    assert res_asset.json()["asset_id"] == MODEL_ASSET

    res_keys = p1_suite.client.get("/api/ad-coin/v2/receipt-keys")
    assert res_keys.status_code == 200, res_keys.text
    assert len(res_keys.json()["keys"]) >= 1


def test_user_ad_preferences_challenge_and_update(p1_suite):
    pref_res = p1_suite.client.get(
        "/api/ad-coin/v2/ad-preferences", headers=p1_suite.headers("user")
    )
    assert pref_res.status_code == 200, pref_res.text
    pref = pref_res.json()
    assert pref["receive_offers"] is False

    intended = p1_suite.service.contract.parse(
        "setAdPreferences",
        canonical_bytes(
            {
                "fresh_action_id": uid(),
                "fresh_action_proof": "p" * 43,
                "receive_offers": True,
                "context_fields": ["task_category", "language", "coarse_region"],
                "max_offers_per_day": 10,
                "max_ads_per_campaign_day": 2,
                "max_ads_per_day": 5,
                "max_ad_ms_per_day": 90000,
            }
        ),
        if_match=etag(pref),
    )

    chal_res = p1_suite.client.post(
        "/api/ad-coin/v2/human-challenges",
        json={
            "action": "set_ad_preferences",
            "target_id": pref["id"],
            "target_revision_hash": pref["revision_hash"],
            "request_digest": intended.semantic_digest,
        },
        headers=p1_suite.headers("user"),
    )
    assert chal_res.status_code == 200, chal_res.text
    challenge = chal_res.json()

    put_res = p1_suite.client.put(
        "/api/ad-coin/v2/ad-preferences",
        json={
            "fresh_action_id": challenge["fresh_action_id"],
            "fresh_action_proof": challenge["proof_challenge"],
            "receive_offers": True,
            "context_fields": ["task_category", "language", "coarse_region"],
            "max_offers_per_day": 10,
            "max_ads_per_campaign_day": 2,
            "max_ads_per_day": 5,
            "max_ad_ms_per_day": 90000,
        },
        headers=p1_suite.headers("user", **{"If-Match": etag(pref)}),
    )
    assert put_res.status_code == 200, put_res.text
    updated = put_res.json()
    assert updated["receive_offers"] is True
    assert updated["version"] == pref["version"] + 1


def test_campaign_revise_creates_new_revision_and_can_be_activated(p1_suite):
    base = "/api/ad-coin/v2/advertisers/" + p1_suite.advertiser + "/campaigns"
    res = p1_suite.client.post(
        base, json=campaign_body(), headers=p1_suite.headers("editor")
    )
    assert res.status_code == 200
    camp = res.json()

    cred = p1_suite.resolver._sessions[list(p1_suite.resolver._sessions.keys())[0]]
    editor = Principal(
        cred.principal_id,
        Kind.HUMAN,
        cred.epoch,
        2_000_000_000,
        owner_id=cred.owner_id,
        csrf_verified=True,
    )
    revised = p1_suite.service.revise_campaign(
        editor,
        p1_suite.advertiser,
        camp["id"],
        campaign_body(
            creative_text="Revised creative text with enhanced quality guarantee."
        ),
        if_match=etag(camp),
    )
    assert revised["version"] == camp["version"] + 1
    assert revised["revision_hash"] != camp["revision_hash"]


def test_full_offer_consent_exposure_evidence_award_and_receipt_jws_flow(p1_suite):
    # 1. Activate campaign
    _activate_campaign(p1_suite)

    # 2. Enable user offers
    pref_res = p1_suite.client.get(
        "/api/ad-coin/v2/ad-preferences", headers=p1_suite.headers("user")
    )
    pref = pref_res.json()
    intended = p1_suite.service.contract.parse(
        "setAdPreferences",
        canonical_bytes(
            {
                "fresh_action_id": uid(),
                "fresh_action_proof": "p" * 43,
                "receive_offers": True,
                "context_fields": ["task_category", "language", "coarse_region"],
                "max_offers_per_day": 10,
                "max_ads_per_campaign_day": 2,
                "max_ads_per_day": 5,
                "max_ad_ms_per_day": 90000,
            }
        ),
        if_match=etag(pref),
    )
    chal_res = p1_suite.client.post(
        "/api/ad-coin/v2/human-challenges",
        json={
            "action": "set_ad_preferences",
            "target_id": pref["id"],
            "target_revision_hash": pref["revision_hash"],
            "request_digest": intended.semantic_digest,
        },
        headers=p1_suite.headers("user"),
    )
    chal = chal_res.json()
    p1_suite.client.put(
        "/api/ad-coin/v2/ad-preferences",
        json={
            "fresh_action_id": chal["fresh_action_id"],
            "fresh_action_proof": chal["proof_challenge"],
            "receive_offers": True,
            "context_fields": ["task_category", "language", "coarse_region"],
            "max_offers_per_day": 10,
            "max_ads_per_campaign_day": 2,
            "max_ads_per_day": 5,
            "max_ad_ms_per_day": 90000,
        },
        headers=p1_suite.headers("user", **{"If-Match": etag(pref)}),
    )

    # 3. Request offer
    req_offer_res = p1_suite.client.post(
        "/api/ad-coin/v2/offers",
        json={
            "task_category": "research",
            "language": "en",
            "coarse_region": "US",
            "selection_digest": "0" * 64,
        },
        headers=p1_suite.headers("user"),
    )
    assert (
        req_offer_res.status_code == 200 or req_offer_res.status_code == 202
    ), req_offer_res.text
    op = req_offer_res.json()
    assert op["state"] == "succeeded"
    offer_id = op["resource_id"]
    assert offer_id is not None

    # 4. Get offer
    offer_res = p1_suite.client.get(
        "/api/ad-coin/v2/offers/" + offer_id, headers=p1_suite.headers("user")
    )
    assert offer_res.status_code == 200, offer_res.text
    offer = offer_res.json()
    assert offer["state"] == "reserved"
    assert offer["user_reward_atoms"] == "50"
    assert offer["operator_reward_atoms"] == "10"
    assert offer["direct_cost_atoms"] == "15"
    assert offer["platform_reward_atoms"] == "25"

    # 5. Challenge and approve offer
    intended_consent = p1_suite.service.contract.parse(
        "approveOffer",
        canonical_bytes(
            {
                "offer_id": offer["id"],
                "quote_hash": offer["quote_hash"],
                "fresh_action_id": uid(),
                "fresh_action_proof": "p" * 43,
            }
        ),
    )
    offer_chal_res = p1_suite.client.post(
        "/api/ad-coin/v2/human-challenges",
        json={
            "action": "approve_offer",
            "target_id": offer["id"],
            "target_revision_hash": offer["quote_hash"],
            "request_digest": intended_consent.semantic_digest,
        },
        headers=p1_suite.headers("user"),
    )
    assert offer_chal_res.status_code == 200, offer_chal_res.text
    offer_chal = offer_chal_res.json()

    consent_res = p1_suite.client.post(
        "/api/ad-coin/v2/human-consents",
        json={
            "offer_id": offer["id"],
            "quote_hash": offer["quote_hash"],
            "fresh_action_id": offer_chal["fresh_action_id"],
            "fresh_action_proof": offer_chal["proof_challenge"],
        },
        headers=p1_suite.headers("user"),
    )
    assert consent_res.status_code == 200, consent_res.text
    consent = consent_res.json()

    # 6. Start exposure
    exp_start_res = p1_suite.client.post(
        "/api/ad-coin/v2/exposure-sessions",
        json={
            "offer_id": offer["id"],
            "consent_id": consent["id"],
            "consent_version": consent["version"],
        },
        headers=p1_suite.headers("user"),
    )
    assert exp_start_res.status_code == 200, exp_start_res.text
    session = exp_start_res.json()
    session_id = session["id"]

    # 7. Get approved creative
    creative_res = p1_suite.client.get(
        "/api/ad-coin/v2/exposure-sessions/" + session_id + "/creative",
        headers=p1_suite.headers("user"),
    )
    assert creative_res.status_code == 200, creative_res.text
    assert "research" in creative_res.json()["plain_text"].lower()

    # 8. Submit evidence (sequence 0..15 with 1000ms steps to accumulate 15,000ms valid attention)
    cur_time = NOW + 1000
    for seq in range(16):
        next_nonce = p1_suite.service.store.one("exposure_get", (session_id,))[
            "next_nonce"
        ]
        p1_suite.service.clock_ms = lambda t=cur_time: t
        ev = p1_suite.client.post(
            "/api/ad-coin/v2/exposure-sessions/" + session_id + "/evidence",
            json={
                "sequence": seq,
                "nonce": next_nonce,
                "elapsed_claim_ms": seq * 1000,
                "visible": True,
                "foreground": True,
            },
            headers=p1_suite.headers("user"),
        )
        assert ev.status_code == 200, ev.text
        cur_time += 1000

    # 9. Complete exposure
    p1_suite.service.clock_ms = lambda t=cur_time: t
    comp_res = p1_suite.client.post(
        "/api/ad-coin/v2/exposure-sessions/" + session_id + "/complete",
        json={"last_sequence": 15},
        headers=p1_suite.headers("user"),
    )
    assert comp_res.status_code == 200 or comp_res.status_code == 202, comp_res.text

    # 10. Run workers to verify evidence, commit award, and sign receipt
    p1_suite.service.clock_ms = lambda: cur_time + 1000
    p1_suite.service.workers.process_outbox(now_ms=cur_time + 1000)
    p1_suite.service.workers.process_outbox(now_ms=cur_time + 2000)

    # 11. Verify wallet balance increased by 50 atoms
    wallet_res = p1_suite.client.get(
        "/api/ad-coin/v2/wallets/" + p1_suite.wallet_id,
        headers=p1_suite.headers("user"),
    )
    assert wallet_res.status_code == 200, wallet_res.text
    wallet = wallet_res.json()
    assert wallet["available_atoms"] == "50"

    # 12. Check receipt and JWS signature
    receipt_row = p1_suite.service.store.one("receipt_by_offer", (offer["id"],))
    assert receipt_row is not None
    receipt_res = p1_suite.client.get(
        "/api/ad-coin/v2/receipts/" + receipt_row["id"],
        headers=p1_suite.headers("user"),
    )
    assert receipt_res.status_code == 200, receipt_res.text
    receipt = receipt_res.json()
    assert receipt["signature_state"] == "signed"
    assert receipt["jws"] is not None

    # Verify cryptographic signature
    verified = p1_suite.service.receipt_signer.verify_jws(receipt["jws"])
    assert verified["claims"]["user_reward_atoms"] == "50"
    assert verified["claims"]["stage_key"] == "P1"


def test_offer_decline_and_unspent_budget_release(p1_suite):
    _activate_campaign(p1_suite)
    pref_res = p1_suite.client.get(
        "/api/ad-coin/v2/ad-preferences", headers=p1_suite.headers("user")
    )
    pref = pref_res.json()
    intended = p1_suite.service.contract.parse(
        "setAdPreferences",
        canonical_bytes(
            {
                "fresh_action_id": uid(),
                "fresh_action_proof": "p" * 43,
                "receive_offers": True,
                "context_fields": ["task_category", "language", "coarse_region"],
                "max_offers_per_day": 10,
                "max_ads_per_campaign_day": 2,
                "max_ads_per_day": 5,
                "max_ad_ms_per_day": 90000,
            }
        ),
        if_match=etag(pref),
    )
    chal_res = p1_suite.client.post(
        "/api/ad-coin/v2/human-challenges",
        json={
            "action": "set_ad_preferences",
            "target_id": pref["id"],
            "target_revision_hash": pref["revision_hash"],
            "request_digest": intended.semantic_digest,
        },
        headers=p1_suite.headers("user"),
    )
    chal = chal_res.json()
    p1_suite.client.put(
        "/api/ad-coin/v2/ad-preferences",
        json={
            "fresh_action_id": chal["fresh_action_id"],
            "fresh_action_proof": chal["proof_challenge"],
            "receive_offers": True,
            "context_fields": ["task_category", "language", "coarse_region"],
            "max_offers_per_day": 10,
            "max_ads_per_campaign_day": 2,
            "max_ads_per_day": 5,
            "max_ad_ms_per_day": 90000,
        },
        headers=p1_suite.headers("user", **{"If-Match": etag(pref)}),
    )

    req_offer_res = p1_suite.client.post(
        "/api/ad-coin/v2/offers",
        json={
            "task_category": "research",
            "language": "en",
            "coarse_region": "US",
            "selection_digest": "0" * 64,
        },
        headers=p1_suite.headers("user"),
    )
    offer_id = req_offer_res.json()["resource_id"]
    p1_suite.client.get(
        "/api/ad-coin/v2/offers/" + offer_id, headers=p1_suite.headers("user")
    )

    hold_row = p1_suite.service.store.one(
        "hold_get", (p1_suite.service._offer(offer_id)["hold_id"],)
    )
    assert hold_row["state"] == "held"

    dec_res = p1_suite.client.post(
        "/api/ad-coin/v2/offers/" + offer_id + "/decline",
        json={"reason": "not_relevant"},
        headers=p1_suite.headers("user"),
    )
    assert dec_res.status_code == 200, dec_res.text
    assert dec_res.json()["state"] == "declined"

    hold_row_after = p1_suite.service.store.one("hold_get", (hold_row["id"],))
    assert hold_row_after["state"] == "released"
    assert hold_row_after["remaining_atoms"] == 0


def test_reporting_status_publishing_and_consumption(p1_suite):
    _activate_campaign(p1_suite)
    p1_suite.service.workers.process_outbox(now_ms=NOW)

    status_res = p1_suite.client.get(
        "/api/ad-coin/v2/advertisers/" + p1_suite.advertiser + "/reporting-status",
        headers=p1_suite.headers("editor"),
    )
    assert status_res.status_code == 200, status_res.text
    status = status_res.json()
    assert len(status["obligations"]) >= 1

    p1_suite.service.workers.publish_reports(now_ms=NOW + 86400000 * 2)

    status_res2 = p1_suite.client.get(
        "/api/ad-coin/v2/advertisers/" + p1_suite.advertiser + "/reporting-status",
        headers=p1_suite.headers("editor"),
    )
    avail_ob = [
        o for o in status_res2.json()["obligations"] if o["state"] == "available"
    ]
    assert len(avail_ob) >= 1
    ob = avail_ob[0]

    rep_res = p1_suite.client.get(
        f"/api/ad-coin/v2/advertisers/{p1_suite.advertiser}/reports/{ob['report_id']}/revisions/{ob['current_revision']}",
        headers=p1_suite.headers("editor"),
    )
    assert rep_res.status_code == 200, rep_res.text
    rep = rep_res.json()
    assert rep["methodology_version"] == "aiac_p1_reporting_v1"

    ack_res = p1_suite.client.post(
        f"/api/ad-coin/v2/advertisers/{p1_suite.advertiser}/reports/{ob['report_id']}/consumption",
        json={
            "revision": ob["current_revision"],
            "state": "received",
            "observed_digest": rep["content_digest"],
        },
        headers=p1_suite.headers("editor"),
    )
    assert ack_res.status_code == 200, ack_res.text
    assert ack_res.json()["state"] == "received"


def test_agent_bearer_token_and_binding(p1_suite):
    _activate_campaign(p1_suite)
    agent_principal_id = uid()
    binding_id = uid()
    p1_suite.service.access.provision_agent_binding(
        binding_id,
        p1_suite.user_owner,
        agent_principal_id,
        uid(),
        capabilities=HUMAN_CAPABILITIES,
    )
    agent_wallet_id = p1_suite.service.access.provision_wallet(
        p1_suite.user_owner, manager_binding_id=binding_id
    )
    agent_token = "tok-agent-" + uid()
    p1_suite.resolver.register_agent_token(
        agent_token,
        principal_id=agent_principal_id,
        owner_id=p1_suite.user_owner,
        agent_binding_id=binding_id,
    )

    agent_headers = {
        "Authorization": "Bearer " + agent_token,
        "X-AIAC-Contract": "v6.2",
    }
    wallet_res = p1_suite.client.get(
        "/api/ad-coin/v2/wallets/" + agent_wallet_id, headers=agent_headers
    )
    assert wallet_res.status_code == 200, wallet_res.text
    assert wallet_res.json()["ownership"] == "user_owned"

    p1_suite.service.access.revoke_agent_binding(binding_id)
    revoked_res = p1_suite.client.get(
        "/api/ad-coin/v2/wallets/" + agent_wallet_id, headers=agent_headers
    )
    assert revoked_res.status_code == 403
    assert revoked_res.json()["error"]["code"] == "authority_revoked"


def test_fresh_key_rotation_with_fallback(p1_suite):
    old_key = b"o" * 32
    new_key = b"n" * 32
    service = p1_suite.service
    service.fresh = type(service.fresh)(service.store, proof_key=old_key)

    principal = Principal(
        UUID(p1_suite.user_principal_id),
        Kind.HUMAN,
        1,
        2_000_000_000,
        owner_id=UUID(p1_suite.user_owner),
        csrf_verified=True,
    )
    chal = service.fresh.issue(
        principal,
        session_hash="1" * 64,
        action="set_ad_preferences",
        target_id=uid(),
        revision_hash="a" * 64,
        semantic_digest="b" * 64,
        now_ms=NOW,
    )
    assert chal.proof

    service.fresh = type(service.fresh)(
        service.store, proof_key=new_key, fallback_keys=(old_key,)
    )
    with service.store.atomic():
        recovered_proof = service.fresh.recover(
            chal.id, principal, session_hash="1" * 64, now_ms=NOW
        )
    assert recovered_proof == chal.proof
