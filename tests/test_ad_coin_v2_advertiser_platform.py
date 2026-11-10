"""Tests for advertiser platform advancement: multi-stage rewards, campaign A/B testing,

conversion measurement, funnel analytics, budget pacing, and market benchmarks.
"""

from uuid import uuid4

from fastapi import FastAPI
import pytest
from starlette.testclient import TestClient

from agent_market.ad_coin.v2.access import COMMERCIAL_CAPABILITIES, HUMAN_CAPABILITIES
from agent_market.ad_coin.v2.advertiser_platform import AdvertiserPlatformGateway
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
            "name": "Advanced Advertiser Campaign",
            "asset_id": MODEL_ASSET,
            "total_budget_atoms": "50000",
            "daily_budget_atoms": "25000",
            "budget_timezone": "UTC",
            "starts_at": date_text(NOW - 1000),
            "ends_at": date_text(NOW + 86400000),
            "task_categories": ["general"],
            "regions": ["US"],
            "creative_text": "High Performance AI Optimization Suite.",
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

    return campaign_id, offer_id, advertiser_id, editor_headers


def test_advertiser_platform_gateway_stages(store):  # noqa: F811
    """Test multi-stage reward claims, deduplication, and PLAT-12 neutral feedback."""
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
    gateway = AdvertiserPlatformGateway(commercial.store, commercial.ledger, commercial.access, clock=lambda: NOW // 1000)

    user_owner = uid()
    user_principal_id = uid()
    user_token = "usr_tok_" + uid()
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

    campaign_id, offer_id, advertiser_id, _ = setup_live_campaign_and_offer(
        client, commercial, resolver, user_owner, user_headers
    )

    # 1. Claim Click Stage Reward
    click_claim = gateway.claim_stage_reward(
        offer_id=offer_id,
        owner_id=user_owner,
        stage_type="click",
        evidence={"target_url": "https://example.com/demo"},
    )
    assert click_claim["stage_type"] == "click"
    assert click_claim["status"] == "settled"
    assert click_claim["reward_atoms"] == "20"

    # Verify deduplication on duplicate click claim
    with pytest.raises(ContractError, match="stage_already_claimed"):
        gateway.claim_stage_reward(
            offer_id=offer_id,
            owner_id=user_owner,
            stage_type="click",
            evidence={"target_url": "https://example.com/demo"},
        )

    # 2. Claim Feedback Stage Reward - PLAT-12 Neutral Feedback Rule
    # Even a 1-star critical feedback receives 100% of the promised reward
    feedback_claim = gateway.claim_stage_reward(
        offer_id=offer_id,
        owner_id=user_owner,
        stage_type="feedback",
        evidence={"rating": 1, "comment": "Needs better documentation."},
    )
    assert feedback_claim["stage_type"] == "feedback"
    assert feedback_claim["status"] == "settled"
    assert feedback_claim["reward_atoms"] == "30"

    # Validation: rating must be between 1 and 5
    with pytest.raises(ContractError, match="feedback_rating_must_be_1_to_5"):
        gateway.claim_stage_reward(
            offer_id=offer_id,
            owner_id=user_owner,
            stage_type="feedback",
            evidence={"rating": 6, "comment": "Too high."},
        )

    # 3. Claim Watch Complete Stage Reward
    # Incomplete view (< 100%) rejected
    with pytest.raises(ContractError, match="watch_complete_requires_100_percent"):
        gateway.claim_stage_reward(
            offer_id=offer_id,
            owner_id=user_owner,
            stage_type="watch_complete",
            evidence={"watch_percentage": 75},
        )

    # Complete 100% watch succeeded
    watch_claim = gateway.claim_stage_reward(
        offer_id=offer_id,
        owner_id=user_owner,
        stage_type="watch_complete",
        evidence={"watch_percentage": 100},
    )
    assert watch_claim["stage_type"] == "watch_complete"
    assert watch_claim["status"] == "settled"
    assert watch_claim["reward_atoms"] == "50"

    # Verify all claims listed
    claims = gateway.list_stage_claims_for_offer(offer_id)
    assert len(claims) == 3
    assert {c["stage_type"] for c in claims} == {"click", "feedback", "watch_complete"}

    # Verify double-entry ledger audit
    audit = commercial.ledger.audit()
    assert int(audit["beneficial_atoms"]) + int(audit["clearing_atoms"]) == 0


def test_advertiser_platform_gateway_experiments(store):  # noqa: F811
    """Test A/B testing experiment creation, variant weights, and deterministic user routing."""
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
    gateway = AdvertiserPlatformGateway(commercial.store, commercial.ledger, commercial.access, clock=lambda: NOW // 1000)

    user_owner = uid()
    user_principal_id = uid()
    user_token = "usr_tok_" + uid()
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

    campaign_id, _, advertiser_id, _ = setup_live_campaign_and_offer(
        client, commercial, resolver, user_owner, user_headers
    )

    # 1. Create A/B Experiment
    exp = gateway.create_experiment(
        advertiser_id=advertiser_id,
        campaign_id=campaign_id,
        name="Creative Headline A/B Test",
        variants=[
            {"id": "var_a", "weight": 60, "headline": "Automate Agent Workflows"},
            {"id": "var_b", "weight": 40, "headline": "Scale Multi-Agent Teams"},
        ],
    )
    assert exp["name"] == "Creative Headline A/B Test"
    assert exp["status"] == "active"
    assert len(exp["variants"]) == 2

    # Weight validation: must sum to 100
    with pytest.raises(ContractError, match="variant_weights_must_sum_to_100"):
        gateway.create_experiment(
            advertiser_id=advertiser_id,
            campaign_id=campaign_id,
            name="Bad Weights",
            variants=[
                {"id": "var_a", "weight": 40},
                {"id": "var_b", "weight": 40},
            ],
        )

    # Min variants validation
    with pytest.raises(ContractError, match="at_least_two_variants_required"):
        gateway.create_experiment(
            advertiser_id=advertiser_id,
            campaign_id=campaign_id,
            name="One Variant",
            variants=[{"id": "var_a", "weight": 100}],
        )

    # 2. Deterministic Routing Test
    routed_1 = gateway.route_variant_for_user(exp["id"], "user_alpha_1")
    routed_1_repeat = gateway.route_variant_for_user(exp["id"], "user_alpha_1")
    assert routed_1["id"] == routed_1_repeat["id"]

    # 3. Status updates
    paused = gateway.update_experiment_status(exp["id"], "paused")
    assert paused["status"] == "paused"
    completed = gateway.update_experiment_status(exp["id"], "completed")
    assert completed["status"] == "completed"


def test_advertiser_platform_conversions_and_analytics(store):  # noqa: F811
    """Test conversion attribution, funnel analytics, budget optimization pacing, and market benchmarks."""
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
    gateway = AdvertiserPlatformGateway(commercial.store, commercial.ledger, commercial.access, clock=lambda: NOW // 1000)

    user_owner = uid()
    user_principal_id = uid()
    user_token = "usr_tok_" + uid()
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

    campaign_id, offer_id, advertiser_id, _ = setup_live_campaign_and_offer(
        client, commercial, resolver, user_owner, user_headers
    )

    # Claim click and feedback stages
    gateway.claim_stage_reward(
        offer_id=offer_id,
        owner_id=user_owner,
        stage_type="click",
        evidence={"target_url": "https://example.com/trial"},
    )
    gateway.claim_stage_reward(
        offer_id=offer_id,
        owner_id=user_owner,
        stage_type="feedback",
        evidence={"rating": 5, "comment": "Great product!"},
    )

    # 1. Record Conversion
    conv = gateway.record_conversion(
        advertiser_id=advertiser_id,
        campaign_id=campaign_id,
        offer_id=offer_id,
        owner_id=user_owner,
        conversion_event="subscription",
        value_atoms=5000,
        order_id="order_987",
    )
    assert conv["conversion_event"] == "subscription"
    assert conv["value_atoms"] == "5000"
    assert conv["order_id"] == "order_987"

    # Deduplication on order_id
    with pytest.raises(ContractError, match="order_already_attributed"):
        gateway.record_conversion(
            advertiser_id=advertiser_id,
            campaign_id=campaign_id,
            offer_id=offer_id,
            owner_id=user_owner,
            conversion_event="subscription",
            order_id="order_987",
        )

    # 2. Get Campaign Analytics
    analytics = gateway.get_campaign_analytics(advertiser_id, campaign_id)
    assert analytics["campaign_id"] == campaign_id
    assert analytics["funnel"]["clicks"] == 1
    assert analytics["funnel"]["feedbacks"] == 1
    assert analytics["funnel"]["conversions"] == 1
    assert analytics["feedback_sentiment"]["average_rating"] == 5.0
    assert analytics["feedback_sentiment"]["rating_distribution"][5] == 1
    assert "ctr_percent" in analytics["rates"]
    assert "cvr_percent" in analytics["rates"]

    # 3. Budget Optimization & Pacing
    opt = gateway.get_budget_optimization(advertiser_id, campaign_id)
    assert opt["campaign_id"] == campaign_id
    assert "status" in opt["pacing"]
    assert "pacing_ratio" in opt["pacing"]
    assert "optimization" in opt
    assert "suggested_daily_budget_adjustment_percent" in opt["optimization"]

    # 4. Market Benchmarks
    benchmarks_tech = gateway.get_market_benchmarks("tech")
    assert benchmarks_tech["category"] == "tech"
    assert benchmarks_tech["benchmarks"]["benchmark_ctr_percent"] == 3.8
    assert benchmarks_tech["benchmarks"]["benchmark_cvr_percent"] == 2.6


def test_advertiser_platform_http_routes(store):  # noqa: F811
    """Test full HTTP endpoints for advertiser platform under /api/ad-coin/v2/advertiser."""
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
    user_headers = {
        "Cookie": f"__Host-ac_customer_session={user_token}",
        "X-CSRF-Token": user_csrf,
        "X-AIAC-Contract": "v6.2",
    }

    campaign_id, offer_id, advertiser_id, editor_headers = setup_live_campaign_and_offer(
        client, commercial, resolver, user_owner, user_headers
    )

    # 1. HTTP Claim Stage (Click)
    res_claim = client.post(
        "/api/ad-coin/v2/advertiser/stages/claim",
        headers=user_headers,
        json={
            "offer_id": offer_id,
            "stage_type": "click",
            "evidence": {"target_url": "https://example.com/click-test"},
        },
    )
    assert res_claim.status_code == 201, res_claim.text
    claim_id = res_claim.json()["id"]

    # 2. HTTP List Stages for Offer
    res_list = client.get(f"/api/ad-coin/v2/advertiser/stages/{offer_id}", headers=user_headers)
    assert res_list.status_code == 200
    assert any(s["id"] == claim_id for s in res_list.json()["stages"])

    # 3. HTTP Create Experiment
    res_exp = client.post(
        f"/api/ad-coin/v2/advertiser/campaigns/{campaign_id}/experiments",
        headers=editor_headers,
        json={
            "name": "Live HTTP A/B Test",
            "variants": [
                {"id": "var_1", "weight": 50, "headline": "Headline 1"},
                {"id": "var_2", "weight": 50, "headline": "Headline 2"},
            ],
        },
    )
    assert res_exp.status_code == 201, res_exp.text
    exp_id = res_exp.json()["id"]

    # 4. HTTP List Experiments
    res_exps = client.get(f"/api/ad-coin/v2/advertiser/campaigns/{campaign_id}/experiments", headers=editor_headers)
    assert res_exps.status_code == 200
    assert any(e["id"] == exp_id for e in res_exps.json()["experiments"])

    # 5. HTTP Route Variant
    res_route = client.post(f"/api/ad-coin/v2/advertiser/experiments/{exp_id}/route", headers=user_headers)
    assert res_route.status_code == 200
    assert "assigned_variant" in res_route.json()

    # 6. HTTP Record Conversion
    res_conv = client.post(
        "/api/ad-coin/v2/advertiser/conversions",
        headers=editor_headers,
        json={
            "campaign_id": campaign_id,
            "offer_id": offer_id,
            "owner_id": user_owner,
            "conversion_event": "free_trial",
            "value_atoms": 1000,
            "order_id": "http_ord_1",
        },
    )
    assert res_conv.status_code == 201, res_conv.text

    # 7. HTTP Analytics
    res_ana = client.get(f"/api/ad-coin/v2/advertiser/campaigns/{campaign_id}/analytics", headers=editor_headers)
    assert res_ana.status_code == 200, res_ana.text
    ana_data = res_ana.json()
    assert "funnel" in ana_data
    assert ana_data["funnel"]["clicks"] == 1
    assert ana_data["funnel"]["conversions"] == 1

    # 8. HTTP Optimization
    res_opt = client.get(f"/api/ad-coin/v2/advertiser/campaigns/{campaign_id}/optimization", headers=editor_headers)
    assert res_opt.status_code == 200, res_opt.text
    assert "pacing" in res_opt.json()

    # 9. HTTP Market Benchmarks
    res_bm = client.get("/api/ad-coin/v2/advertiser/market-benchmarks?category=tech")
    assert res_bm.status_code == 200, res_bm.text
    assert res_bm.json()["category"] == "tech"
