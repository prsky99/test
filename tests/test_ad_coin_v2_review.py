"""Adversarial review of P1 improvements using isolated PostgreSQL and API requests."""

import pytest

from agent_market.ad_coin.v2.contracts import ContractError, canonical_bytes, digest
from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_persistence import store, raw, uid  # noqa: F401
from tests.test_ad_coin_v2_p1 import p1_suite as _p1_fixture, _activate_campaign, NOW

p1_suite = _p1_fixture


def offer_for(suite):
    raw(
        suite.service.store,
        "UPDATE adc2_ad_preferences SET receive_offers=1,context_fields_json=? WHERE owner_id=?",
        ('["task_category","language","coarse_region"]', suite.user_owner),
    )
    response = suite.client.post(
        "/api/ad-coin/v2/offers",
        json={
            "task_category": "research",
            "language": "en",
            "coarse_region": "US",
            "selection_digest": "0" * 64,
        },
        headers=suite.headers(),
    )
    assert response.status_code in (200, 202), response.text
    assert response.json()["state"] == "succeeded", response.text
    result = suite.client.get(
        "/api/ad-coin/v2/offers/" + response.json()["resource_id"],
        headers=suite.headers(),
    )
    assert result.status_code == 200, result.text
    return result.json()


def consent_for(suite, offer):
    intended = suite.service.contract.parse(
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
    challenge = suite.client.post(
        "/api/ad-coin/v2/human-challenges",
        json={
            "action": "approve_offer",
            "target_id": offer["id"],
            "target_revision_hash": offer["quote_hash"],
            "request_digest": intended.semantic_digest,
        },
        headers=suite.headers(),
    )
    assert challenge.status_code == 200, challenge.text
    consent = suite.client.post(
        "/api/ad-coin/v2/human-consents",
        json={
            "offer_id": offer["id"],
            "quote_hash": offer["quote_hash"],
            "fresh_action_id": challenge.json()["fresh_action_id"],
            "fresh_action_proof": challenge.json()["proof_challenge"],
        },
        headers=suite.headers(),
    )
    assert consent.status_code == 200, consent.text
    return consent.json()


def start_for(suite, offer, consent, headers=None):
    return suite.client.post(
        "/api/ad-coin/v2/exposure-sessions",
        json={
            "offer_id": offer["id"],
            "consent_id": consent["id"],
            "consent_version": consent["version"],
        },
        headers=headers or suite.headers(),
    )


def session_for(suite):
    _activate_campaign(suite)
    offer = offer_for(suite)
    consent = consent_for(suite, offer)
    response = start_for(suite, offer, consent)
    assert response.status_code == 200, response.text
    return offer, response.json()


def signal(
    suite,
    session,
    seq,
    server_ms,
    claim_ms,
    *,
    visible=True,
    foreground=True,
    headers=None,
):
    suite.service.clock_ms = lambda: server_ms
    nonce = suite.service.store.one("exposure_get", (session["id"],))["next_nonce"]
    return suite.client.post(
        "/api/ad-coin/v2/exposure-sessions/" + session["id"] + "/evidence",
        json={
            "sequence": seq,
            "nonce": nonce,
            "elapsed_claim_ms": claim_ms,
            "visible": visible,
            "foreground": foreground,
        },
        headers=headers or suite.headers(),
    )


def test_zero_server_elapsed_cannot_earn_exposure_time(p1_suite):
    _, session = session_for(p1_suite)
    for seq in range(16):
        response = signal(p1_suite, session, seq, NOW, seq * 1000)
        assert response.status_code == 200, response.text
    row = p1_suite.service.store.one("exposure_get", (session["id"],))
    assert int(row["collected_valid_ms"]) == 0
    assert row["qualified_ms"] is None


def test_interval_requires_both_endpoints_visible(p1_suite):
    _, session = session_for(p1_suite)
    assert signal(p1_suite, session, 0, NOW, 0).status_code == 200
    assert (
        signal(p1_suite, session, 1, NOW + 1000, 1000, visible=False).status_code == 200
    )
    assert signal(p1_suite, session, 2, NOW + 2000, 2000).status_code == 200
    row = p1_suite.service.store.one("exposure_get", (session["id"],))
    assert int(row["collected_valid_ms"]) == 0


@pytest.mark.parametrize("stop", ["switch", "advertiser"])
def test_latest_safety_stop_blocks_previously_consented_start(p1_suite, stop):
    _activate_campaign(p1_suite)
    offer = offer_for(p1_suite)
    consent = consent_for(p1_suite, offer)
    if stop == "switch":
        p1_suite.service.access.set_model_activation(False)
    else:
        p1_suite.service.access.set_advertiser_status(p1_suite.advertiser, "suspended")
    response = start_for(p1_suite, offer, consent)
    assert response.status_code == 409, response.text
    assert p1_suite.service.store.one("exposure_by_offer", (offer["id"],)) is None


def test_idempotent_evidence_reply_keeps_its_sequence_nonce_pair(p1_suite):
    _, session = session_for(p1_suite)
    headers = p1_suite.headers()
    original_nonce = session["next_nonce"]
    first = signal(p1_suite, session, 0, NOW, 0, headers=headers)
    assert first.status_code == 200, first.text
    assert signal(p1_suite, session, 1, NOW + 1000, 1000).status_code == 200
    response = p1_suite.client.post(
        "/api/ad-coin/v2/exposure-sessions/" + session["id"] + "/evidence",
        json={
            "sequence": 0,
            "nonce": original_nonce,
            "elapsed_claim_ms": 0,
            "visible": True,
            "foreground": True,
        },
        headers=headers,
    )
    assert response.json() == first.json()


def test_mtls_callback_must_return_boolean_true(p1_suite):
    campaign = _activate_campaign(p1_suite)
    review = p1_suite.service.store.one(
        "review_latest",
        (
            p1_suite.service.store.one("campaign_get", (campaign["id"],))[
                "current_revision_id"
            ],
        ),
    )
    p1_suite.resolver._mtls_verifier = lambda _: "false"
    response = p1_suite.client.get(
        "/api/ad-coin/v2/reviews/" + review["id"], headers=p1_suite.headers("reviewer")
    )
    assert response.status_code == 403, response.text


def test_unchanged_report_does_not_publish_another_revision(p1_suite):
    _activate_campaign(p1_suite)
    p1_suite.service.workers.process_outbox(now_ms=NOW)
    assert p1_suite.service.workers.publish_reports(now_ms=NOW + 86400000 * 2) > 0
    assert p1_suite.service.workers.publish_reports(now_ms=NOW + 86400000 * 2) == 0


def test_worker_does_not_trust_forged_qualified_cache(p1_suite):
    offer, session = session_for(p1_suite)
    assert signal(p1_suite, session, 0, NOW, 0).status_code == 200
    raw(
        p1_suite.service.store,
        "UPDATE adc2_exposure_sessions SET collected_valid_ms=15000,qualified_ms=? WHERE id=?",
        (NOW, session["id"]),
    )
    response = p1_suite.client.post(
        "/api/ad-coin/v2/exposure-sessions/" + session["id"] + "/complete",
        json={"last_sequence": 0},
        headers=p1_suite.headers(),
    )
    assert response.status_code in (200, 202), response.text
    p1_suite.service.workers.process_outbox(now_ms=NOW)
    assert p1_suite.service.store.one("receipt_by_offer", (offer["id"],)) is None
    assert (
        p1_suite.service.store.one(
            "hold_get",
            (p1_suite.service.store.one("offer_get", (offer["id"],))["hold_id"],),
        )["state"]
        == "review_pending"
    )


@pytest.mark.parametrize("qualified", [False, True])
def test_expiry_uses_original_evidence_and_preserves_qualified_rights(
    p1_suite, qualified
):
    offer, session = session_for(p1_suite)
    for seq in range(16 if qualified else 1):
        assert (
            signal(p1_suite, session, seq, NOW + seq * 1000, seq * 1000).status_code
            == 200
        )
    result = p1_suite.service.workers.sweep_expired(now_ms=NOW + 31000)
    assert result["expired_sessions"] == 1
    row = p1_suite.service.store.one("offer_get", (offer["id"],))
    assert row["state"] == ("awarded" if qualified else "expired")
    assert (
        bool(p1_suite.service.store.one("receipt_by_offer", (offer["id"],)))
        == qualified
    )
    assert (
        p1_suite.service.workers.sweep_expired(now_ms=NOW + 32000)["expired_sessions"]
        == 0
    )


def test_lowered_daily_limits_apply_to_existing_attention_windows(p1_suite):
    offer, session = session_for(p1_suite)
    p1_suite.service.workers.sweep_expired(now_ms=NOW + 11000)
    p1_suite.service.clock_ms = lambda: NOW + 12000
    # A second campaign keeps the original campaign cap independent of the global cap.
    _activate_campaign(p1_suite)
    offered = offer_for(p1_suite)
    consent = consent_for(p1_suite, offered)
    raw(
        p1_suite.service.store,
        "UPDATE adc2_ad_preferences SET max_ads_per_day=1 WHERE owner_id=?",
        (p1_suite.user_owner,),
    )
    response = start_for(p1_suite, offered, consent)
    assert response.status_code == 429, response.text


def test_reports_include_late_award_in_qualification_period_and_pending_status(
    p1_suite,
):
    offer, session = session_for(p1_suite)
    p1_suite.service.workers.process_outbox(now_ms=NOW)
    for seq in range(16):
        assert (
            signal(p1_suite, session, seq, NOW + seq * 1000, seq * 1000).status_code
            == 200
        )
    response = p1_suite.client.post(
        "/api/ad-coin/v2/exposure-sessions/" + session["id"] + "/complete",
        json={"last_sequence": 15},
        headers=p1_suite.headers(),
    )
    assert response.status_code == 202, response.text
    late = NOW + 86400000 * 2
    assert p1_suite.service.workers.publish_reports(now_ms=late) > 0
    obligations = p1_suite.service.store.all(
        "reporting_obligations_for_advertiser", (p1_suite.advertiser,)
    )
    target = next(
        o
        for o in obligations
        if o["period_start_ms"] <= NOW + 15000 < o["period_end_ms"]
    )
    old = p1_suite.service.store.one(
        "report_revision_get", (target["report_id"], target["current_revision"])
    )
    assert old["complete"] == 0
    p1_suite.service.workers.process_outbox(now_ms=late)
    assert p1_suite.service.store.one("receipt_by_offer", (offer["id"],)) is not None
    assert p1_suite.service.workers.publish_reports(now_ms=late + 1000) > 0
    target = p1_suite.service.store.one("reporting_obligation_get", (target["id"],))
    latest = p1_suite.service.store.one(
        "report_revision_get", (target["report_id"], target["current_revision"])
    )
    import json

    metrics = {m["name"]: m["value"] for m in json.loads(latest["metrics_json"])}
    assert (
        metrics["valid_exposures"] == "1" and metrics["gross_ad_charge_atoms"] == "100"
    )
    assert (
        latest["complete"] == 1
        and json.loads(latest["source_manifest_json"])[0]["record_kind"] == "award"
    )
    from agent_market.ad_coin.v2.reports import report_view

    public = report_view(latest)
    expected = public.pop("content_digest")
    assert expected == digest(public)
    assert p1_suite.service.workers.publish_reports(now_ms=late + 1000) == 0


def test_expired_worker_lease_rolls_back_handler_effects(p1_suite, monkeypatch):
    import agent_market.ad_coin.v2.workers as module

    clock = iter((0, 0, 16000000000))
    monkeypatch.setattr(module, "monotonic_ns", lambda: next(clock))
    p1_suite.service.outbox.enqueue(
        "lease-timeout",
        {"event": "review_requested", "review_id": uid()},
        available_ms=NOW,
    )
    created = []

    def effect(_payload):
        created.append(p1_suite.service.ledger.create_account(uid(), "user_available"))

    monkeypatch.setattr(p1_suite.service.workers, "_handle_review_requested", effect)
    with pytest.raises(ContractError, match="stale_worker_lease"):
        p1_suite.service.workers.process_outbox(now_ms=NOW)
    assert created and p1_suite.service.store.one("account_get", (created[0],)) is None
    assert (
        p1_suite.service.store.one("outbox_get", ("lease-timeout",))["state"]
        == "leased"
    )


def test_unknown_worker_event_is_not_silently_acknowledged(p1_suite):
    p1_suite.service.outbox.enqueue(
        "unknown-event", {"event": "future_unsupported"}, available_ms=NOW
    )
    with pytest.raises(ContractError, match="unsupported_worker_event"):
        p1_suite.service.workers.process_outbox(now_ms=NOW)
    assert (
        p1_suite.service.store.one("outbox_get", ("unknown-event",))["state"] != "done"
    )


def test_real_v2_principal_constraints_are_upgraded_for_agents(p1_suite):
    from agent_market.ad_coin.v2.identity import Kind

    database = p1_suite.service.store
    raw(
        database,
        "ALTER TABLE adc2_principals DROP CONSTRAINT adc2_principals_kind_check",
    )
    raw(database, "ALTER TABLE adc2_principals DROP CONSTRAINT adc2_principals_check")
    raw(
        database,
        "ALTER TABLE adc2_principals ADD CONSTRAINT adc2_principals_kind_check CHECK (kind IN ('human','ops'))",
    )
    raw(
        database,
        "ALTER TABLE adc2_principals ADD CONSTRAINT adc2_principals_check CHECK ((kind='human' AND owner_id IS NOT NULL) OR (kind='ops' AND owner_id IS NULL))",
    )
    raw(database, "UPDATE adc2_schema SET version=2 WHERE id=1")
    database.migrate_model()
    agent_id = uid()
    p1_suite.service.access.provision_principal(
        agent_id, Kind.AGENT, owner_id=p1_suite.user_owner
    )
    assert database.one("principal_get", (agent_id,))["kind"] == "agent"
    from agent_market.ad_coin.v2.schema import VERSION

    assert database.one("schema_get")["version"] == VERSION


@pytest.mark.parametrize(
    "claim,value",
    [
        ("aud", "other-purpose"),
        ("iss", "foreign-service"),
        ("stage_key", "P2"),
        ("asset_id", "usdc:mainnet"),
        ("contract_version", "v5"),
    ],
)
def test_valid_signature_with_wrong_receipt_purpose_is_rejected(p1_suite, claim, value):
    from agent_market.ad_coin.v2.receipts import _b64url_encode
    from agent_market.ad_coin.v2.contracts import MODEL_ASSET

    claims = {
        "receipt_id": uid(),
        "offer_id": uid(),
        "stage_key": "P1",
        "asset_id": MODEL_ASSET,
        "user_reward_atoms": "50",
        "quote_hash": "a" * 64,
        "policy_version": "v6.1",
        "contract_version": "v6.2",
        "iss": "ai-ad-coin/model",
        "aud": "aiac-reward-receipt",
        "iat": NOW // 1000,
    }
    claims[claim] = value
    header = _b64url_encode(
        canonical_bytes(
            {"alg": "EdDSA", "kid": "kid-model-2026", "typ": "aiac-receipt+jwt"}
        )
    )
    body = _b64url_encode(canonical_bytes(claims))
    signing_input = (header + "." + body).encode("ascii")
    token = (
        header
        + "."
        + body
        + "."
        + _b64url_encode(p1_suite.signing_key.sign(signing_input))
    )
    with pytest.raises(ContractError, match="receipt_claims_mismatch"):
        p1_suite.service.receipt_signer.verify_jws(token)


def test_qualified_cancel_preserves_award_without_click_or_quiz(p1_suite):
    offer, session = session_for(p1_suite)
    for seq in range(16):
        assert (
            signal(p1_suite, session, seq, NOW + seq * 1000, seq * 1000).status_code
            == 200
        )
    response = p1_suite.client.post(
        "/api/ad-coin/v2/exposure-sessions/" + session["id"] + "/cancel",
        json={"reason": "user_stop"},
        headers=p1_suite.headers(),
    )
    assert response.status_code == 202, response.text
    p1_suite.service.workers.process_outbox(now_ms=NOW + 16000)
    assert p1_suite.service.store.one("receipt_by_offer", (offer["id"],)) is not None
    assert p1_suite.service.store.one("offer_get", (offer["id"],))["state"] == "awarded"


def test_real_localhost_zero_time_reward_attack_is_rejected(p1_suite):
    import socket
    import threading
    import time
    import httpx
    import uvicorn

    original = p1_suite.client
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(
        uvicorn.Config(
            original.app, host="127.0.0.1", port=0, log_level="error", access_log=False
        )
    )
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        with httpx.Client(
            base_url="http://127.0.0.1:" + str(sock.getsockname()[1]),
            timeout=5,
            trust_env=False,
        ) as client:
            p1_suite.client = client
            offer, session = session_for(p1_suite)
            for seq in range(16):
                assert (
                    signal(p1_suite, session, seq, NOW, seq * 1000).status_code == 200
                )
            response = client.post(
                "/api/ad-coin/v2/exposure-sessions/" + session["id"] + "/complete",
                json={"last_sequence": 15},
                headers=p1_suite.headers(),
            )
            assert response.status_code == 202, response.text
            p1_suite.service.workers.process_outbox(now_ms=NOW + 1000)
            assert (
                p1_suite.service.store.one("receipt_by_offer", (offer["id"],)) is None
            )
            wallet = client.get(
                "/api/ad-coin/v2/wallets/" + p1_suite.wallet_id,
                headers=p1_suite.headers(),
            ).json()
            assert wallet["available_atoms"] == "0"
    finally:
        p1_suite.client = original
        server.should_exit = True
        thread.join(5)
        sock.close()
        assert not thread.is_alive()


def test_funded_campaign_revision_cannot_reuse_old_approval_or_budget(p1_suite):
    from starlette.requests import Request
    from agent_market.ad_coin.v2.commercial import etag
    from tests.test_ad_coin_v2_p1 import campaign_body

    campaign = _activate_campaign(p1_suite)
    target = (
        "/api/ad-coin/v2/advertisers/"
        + p1_suite.advertiser
        + "/campaigns/"
        + campaign["id"]
    )
    response = p1_suite.client.post(
        target + "/pause",
        json={
            "revision_hash": campaign["revision_hash"],
            "reason_code": "schedule_change",
        },
        headers=p1_suite.headers("editor", **{"If-Match": etag(campaign)}),
    )
    assert response.status_code == 200, response.text
    principal = p1_suite.resolver(
        Request(
            {
                "type": "http",
                "method": "POST",
                "headers": [
                    (b"authorization", ("Bearer " + p1_suite.editor_token).encode()),
                    (b"x-csrf-token", b"editor-csrf"),
                ],
            }
        )
    ).principal
    before = p1_suite.service.store.one("campaign_get", (campaign["id"],))
    with pytest.raises(ContractError, match="approved_campaign_revision_forbidden"):
        p1_suite.service.revise_campaign(
            principal,
            p1_suite.advertiser,
            campaign["id"],
            campaign_body(creative_text="Different terms require a separate campaign."),
            if_match=etag(response.json()),
        )
    assert p1_suite.service.store.one("campaign_get", (campaign["id"],)) == before
