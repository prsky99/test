"""End-to-end integration and live service tests for AI AD Coin v2."""

from uuid import uuid4

from fastapi import FastAPI
from starlette.testclient import TestClient

from agent_market.ad_coin.v2.contracts import MODEL_ASSET
from agent_market.ad_coin.v2.key_vault import KeyVault
from agent_market.ad_coin.v2.live_service import (
    DEFAULT_LANGUAGES,
    DEFAULT_REGIONS,
    DEFAULT_TAXONOMY,
    build_live_service,
    create_live_ad_coin_v2_router,
)
from agent_market.ad_coin.v2.reconcile import LedgerReconciler
from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_persistence import store  # noqa: F401

NOW = 1_800_000_000_000


def uid():
    return str(uuid4())


def test_live_service_e2e_lifecycle(store):  # noqa: F811
    store.migrate_model()

    vault = KeyVault()
    commercial, resolver, _ = build_live_service(
        store,
        key_vault=vault,
        taxonomy=DEFAULT_TAXONOMY,
        regions=DEFAULT_REGIONS,
        languages=DEFAULT_LANGUAGES,
        clock_ms=lambda: NOW,
    )
    # Publish receipt signing key in registry
    commercial.receipt_signer.publish_key(
        vault.kid,
        not_before_ms=NOW - 100000,
        verify_until_ms=NOW + 1000000000,
        status="active",
    )
    commercial.access.set_model_activation(True)

    router = create_live_ad_coin_v2_router(
        store,
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

    # 1. Static Workspace Shell & Assets Verification
    resp_shell = client.get("/ad-coin/v2")
    assert resp_shell.status_code == 200
    assert resp_shell.headers["cache-control"] == "no-store"
    assert "content-security-policy" in resp_shell.headers

    import re

    urls = re.findall(r'(?:src|href)="(/ad-coin/v2/assets/[^\"]+)"', resp_shell.text)
    assert len(urls) == 2
    for url in urls:
        resp_asset = client.get(url)
        assert resp_asset.status_code == 200
        assert "cache-control" in resp_asset.headers

    # 2. Onboard User & Editor & Reviewer
    user_owner = uid()
    user_principal_id = uid()
    user_token = "usr_sess_" + uid()
    user_csrf = "csrf_" + uid()

    editor_owner = uid()
    editor_principal_id = uid()
    editor_token = "edt_sess_" + uid()
    editor_csrf = "csrf_" + uid()

    reviewer_principal_id = uid()
    reviewer_token = "rev_tok_" + uid()
    reviewer_thumbprint = "thumb_reviewer_01"

    from agent_market.ad_coin.v2.access import HUMAN_CAPABILITIES
    from agent_market.ad_coin.v2.identity import Kind

    commercial.access.provision_principal(
        user_principal_id, Kind.HUMAN, owner_id=user_owner, capabilities=HUMAN_CAPABILITIES
    )
    commercial.access.provision_principal(
        editor_principal_id, Kind.HUMAN, owner_id=editor_owner, capabilities=HUMAN_CAPABILITIES
    )
    commercial.access.provision_principal(
        reviewer_principal_id, Kind.REVIEWER, capabilities=frozenset(("review.decide",))
    )
    commercial.access.provision_preferences(user_owner, now_ms=NOW)
    commercial.access.provision_wallet(user_owner)

    expires_at = (NOW // 1000) + 3600

    resolver.register_human_session(
        user_token, user_csrf, principal_id=user_principal_id, owner_id=user_owner, epoch=1, expires_at=expires_at
    )
    resolver.register_human_session(
        editor_token, editor_csrf, principal_id=editor_principal_id, owner_id=editor_owner, epoch=1, expires_at=expires_at
    )
    resolver.register_reviewer_token(
        reviewer_token, principal_id=reviewer_principal_id, cert_fingerprint=reviewer_thumbprint, epoch=1, expires_at=expires_at
    )

    # User headers & Editor headers
    user_headers = {
        "Cookie": f"__Host-ac_customer_session={user_token}",
        "X-CSRF-Token": user_csrf,
        "X-AIAC-Contract": "v6.2",
    }
    editor_headers = {
        "Cookie": f"__Host-ac_customer_session={editor_token}",
        "X-CSRF-Token": editor_csrf,
        "X-AIAC-Contract": "v6.2",
    }

    # 3. User Workspace Session Check
    resp_user_sess = client.get("/ad-coin/v2/ui/session", headers=user_headers)
    assert resp_user_sess.status_code == 200
    user_ui = resp_user_sess.json()
    assert "preferences" in user_ui
    assert user_ui["preferences"]["receive_offers"] is False
    assert len(user_ui["wallets"]) >= 1

    # 4. Provision Advertiser & Capabilities
    advertiser_id = uid()
    available_acc = commercial.access.provision_advertiser(advertiser_id, editor_owner)
    commercial.access.grant(advertiser_id, editor_principal_id, "campaign.edit")
    commercial.access.grant(advertiser_id, editor_principal_id, "campaign.read")
    commercial.access.grant(advertiser_id, editor_principal_id, "budget.approve")

    # Fund Advertiser available balance
    clearing = commercial.ledger.create_account(uid(), "external_clearing")
    commercial.ledger.post(
        "adv-seed",
        [(clearing, "-100000"), (available_acc, "100000")],
        kind="model_seed",
    )

    from agent_market.ad_coin.v2.commercial import date_text, etag
    from agent_market.ad_coin.v2.contracts import canonical_bytes

    # 5. Editor creates campaign draft via API
    campaign_payload = {
        "name": "Live Assistant Agent Campaign",
        "asset_id": MODEL_ASSET,
        "total_budget_atoms": "5000",
        "daily_budget_atoms": "2500",
        "budget_timezone": "UTC",
        "starts_at": date_text(NOW - 1000),
        "ends_at": date_text(NOW + 86400000),
        "task_categories": ["general"],
        "regions": ["US"],
        "creative_text": "Experience next-generation autonomous AI pair programming.",
        "gross_p1_atoms": "100",
        "min_exposure_ms": 15000,
        "split_policy_id": "default_v5",
        "renderer_profile": "platform_text_v1",
    }

    draft_res = client.post(
        f"/api/ad-coin/v2/advertisers/{advertiser_id}/campaigns",
        headers={**editor_headers, "Idempotency-Key": uid()},
        json=campaign_payload,
    )
    assert draft_res.status_code == 200, draft_res.text
    campaign = draft_res.json()
    campaign_id = campaign["id"]

    # 6. Submit campaign for review
    rev_res = client.post(
        f"/api/ad-coin/v2/advertisers/{advertiser_id}/campaigns/{campaign_id}/review-request",
        headers={
            **editor_headers,
            "Idempotency-Key": uid(),
            "If-Match": draft_res.headers["etag"],
        },
        json={"revision_hash": campaign["revision_hash"]},
    )
    assert rev_res.status_code == 200, rev_res.text
    review = rev_res.json()

    # 7. Reviewer approves campaign via mTLS
    reviewer_headers = {
        "Authorization": f"Bearer {reviewer_token}",
        "X-Mock-TLS": "verified",
        "X-AIAC-Contract": "v6.2",
        "Idempotency-Key": uid(),
        "If-Match": etag(review),
    }
    evidence_id = commercial.record_evidence(review["id"], "a" * 64)

    dec_res = client.post(
        f"/api/ad-coin/v2/reviews/{review['id']}/decisions",
        headers=reviewer_headers,
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

    # 8. Approve and Activate campaign with fresh action
    intended = commercial.contract.parse(
        "approveCampaign",
        canonical_bytes(
            {
                "revision_hash": campaign["revision_hash"],
                "fresh_action_id": uid(),
                "fresh_action_proof": "p" * 43,
            }
        ),
        path_parameters={
            "advertiser_id": advertiser_id,
            "campaign_id": campaign_id,
        },
        if_match=etag(campaign),
    )
    chal_res = client.post(
        "/api/ad-coin/v2/human-challenges",
        json={
            "action": "approve_campaign",
            "target_id": campaign_id,
            "target_revision_hash": campaign["revision_hash"],
            "request_digest": intended.semantic_digest,
        },
        headers={**editor_headers, "Idempotency-Key": uid()},
    )
    assert chal_res.status_code == 200, chal_res.text
    chal = chal_res.json()

    app_res = client.post(
        f"/api/ad-coin/v2/advertisers/{advertiser_id}/campaigns/{campaign_id}/approvals",
        json={
            "revision_hash": campaign["revision_hash"],
            "fresh_action_id": chal["fresh_action_id"],
            "fresh_action_proof": chal["proof_challenge"],
        },
        headers={**editor_headers, "If-Match": etag(campaign), "Idempotency-Key": uid()},
    )
    assert app_res.status_code == 200, app_res.text
    approved_camp = app_res.json()

    act_res = client.post(
        f"/api/ad-coin/v2/advertisers/{advertiser_id}/campaigns/{campaign_id}/activation",
        headers={
            **editor_headers,
            "Idempotency-Key": uid(),
            "If-Match": etag(approved_camp),
        },
        json={"revision_hash": approved_camp["revision_hash"]},
    )
    assert act_res.status_code == 200, act_res.text
    active_camp = act_res.json()
    assert active_camp["state"] == "active"

    # 9. User updates preferences to receive offers via human challenge
    cur_pref = client.get("/api/ad-coin/v2/ad-preferences", headers=user_headers)
    assert cur_pref.status_code == 200
    pref = cur_pref.json()

    intended_pref = commercial.contract.parse(
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

    chal_pref = client.post(
        "/api/ad-coin/v2/human-challenges",
        json={
            "action": "set_ad_preferences",
            "target_id": pref["id"],
            "target_revision_hash": pref["revision_hash"],
            "request_digest": intended_pref.semantic_digest,
        },
        headers={**user_headers, "Idempotency-Key": uid()},
    )
    assert chal_pref.status_code == 200, chal_pref.text
    challenge = chal_pref.json()

    pref_res = client.put(
        "/api/ad-coin/v2/ad-preferences",
        headers={
            **user_headers,
            "If-Match": etag(pref),
            "Idempotency-Key": uid(),
        },
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
    )
    assert pref_res.status_code == 200, pref_res.text

    # 10. Ledger Reconciler check
    reconciler = LedgerReconciler(store)
    report = reconciler.run_full_reconciliation()
    assert report.status == "clean"
    assert len(report.issues) == 0

    # 11. Security negative tests
    # Missing session returns 401
    anon_res = client.get("/ad-coin/v2/ui/session")
    assert anon_res.status_code == 401

    # Bad session returns 401
    bad_sess = client.get(
        "/ad-coin/v2/ui/session",
        headers={"Cookie": "__Host-ac_customer_session=bad-session-token"},
    )
    assert bad_sess.status_code == 401

    # Mixed credentials (Authorization header + Cookie) returns 403
    mixed = client.get(
        "/api/ad-coin/v2/ad-preferences",
        headers={**user_headers, "Authorization": "Bearer some-token"},
    )
    assert mixed.status_code == 403
