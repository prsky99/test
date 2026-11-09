"""Verification suite for Tasks 1, 2, and 3: Live Auth, Operational Security, and Disaster Recovery."""

from uuid import UUID, uuid4

from fastapi import FastAPI
from starlette.testclient import TestClient

from agent_market.ad_coin.v2.access import COMMERCIAL_CAPABILITIES, HUMAN_CAPABILITIES
from agent_market.ad_coin.v2.commercial import Commercial
from agent_market.ad_coin.v2.contracts import MODEL_ASSET
from agent_market.ad_coin.v2.http import router_for
from agent_market.ad_coin.v2.identity import Kind, Principal
from agent_market.ad_coin.v2.key_vault import KeyVault
from agent_market.ad_coin.v2.live_auth import PersistentCredentialResolver
from agent_market.ad_coin.v2.reconcile import LedgerReconciler
from agent_market.ad_coin.v2.security_guards import AuditLogger, EventType, TokenBucketRateLimiter
from agent_market.ad_coin.v2.security_roles import generate_role_setup_sql, verify_role_specifications
from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_persistence import store  # noqa: F401

NOW = 1_800_000_000_000


def uid():
    return str(uuid4())


def test_task1_persistent_credential_resolver(store):  # noqa: F811
    store.migrate_model()
    resolver = PersistentCredentialResolver(store)

    user_owner = uid()
    user_principal_id = uid()
    agent_principal_id = uid()
    reviewer_principal_id = uid()
    binding_id = uid()

    commercial = Commercial(
        store,
        taxonomy=frozenset({"research", "coding"}),
        regions=frozenset({"US", "KR"}),
    )
    commercial.access.provision_principal(
        user_principal_id, Kind.HUMAN, owner_id=user_owner, capabilities=HUMAN_CAPABILITIES
    )
    commercial.access.provision_agent_binding(
        binding_id,
        user_owner,
        agent_principal_id,
        uid(),
        capabilities=HUMAN_CAPABILITIES,
    )
    commercial.access.provision_principal(
        reviewer_principal_id, Kind.REVIEWER, capabilities=frozenset(("review.decide",))
    )
    commercial.access.provision_preferences(user_owner, now_ms=NOW)
    wallet_id = commercial.access.provision_wallet(user_owner)

    # 1. Register Human Session
    user_session = "sess-" + uid()
    user_csrf = "csrf-" + uid()
    session_hash = resolver.register_human_session(
        user_session, user_csrf, principal_id=user_principal_id, owner_id=user_owner, epoch=1
    )
    assert session_hash is not None

    # 2. Register Agent Token
    agent_token = "tok-agent-" + uid()
    resolver.register_agent_token(
        agent_token,
        principal_id=agent_principal_id,
        owner_id=user_owner,
        agent_binding_id=binding_id,
        epoch=1,
    )

    # 3. Register Reviewer Token
    reviewer_token = "tok-rev-" + uid()
    resolver.register_reviewer_token(
        reviewer_token, principal_id=reviewer_principal_id, cert_fingerprint="fp123", epoch=1
    )

    # Test HTTP routing through PersistentCredentialResolver
    app = FastAPI()
    router = router_for(commercial, resolve_auth=resolver, include_workspace=True)
    app.include_router(router)
    client = TestClient(app)

    # Human request with cookie + CSRF
    headers_human = {
        "Cookie": f"__Host-ac_customer_session={user_session}",
        "X-CSRF-Token": user_csrf,
        "X-AIAC-Contract": "v6.2",
    }
    pref_res = client.get("/api/ad-coin/v2/ad-preferences", headers=headers_human)
    assert pref_res.status_code == 200, pref_res.text
    assert "id" in pref_res.json()

    # Agent request with Bearer token
    headers_agent = {
        "Authorization": f"Bearer {agent_token}",
        "X-AIAC-Contract": "v6.2",
    }
    wallet_res = client.get(f"/api/ad-coin/v2/wallets/{wallet_id}", headers=headers_agent)
    # Agent wallet query requires agent-bound wallet or owner
    assert wallet_res.status_code in (200, 403, 404)

    # Persistence verification: recreate a new PersistentCredentialResolver instance
    new_resolver = PersistentCredentialResolver(store)
    app2 = FastAPI()
    app2.include_router(router_for(commercial, resolve_auth=new_resolver, include_workspace=True))
    client2 = TestClient(app2)

    pref_res2 = client2.get("/api/ad-coin/v2/ad-preferences", headers=headers_human)
    assert pref_res2.status_code == 200, "Persistent session survived resolver reload"

    # Revocation test
    new_resolver.revoke_human_session(user_session)
    revoked_res = client2.get("/api/ad-coin/v2/ad-preferences", headers=headers_human)
    assert revoked_res.status_code == 401, "Revoked session rejected immediately"

    # Epoch rotation test
    user_session2 = "sess2-" + uid()
    new_resolver.register_human_session(
        user_session2, user_csrf, principal_id=user_principal_id, owner_id=user_owner, epoch=1
    )
    headers_human2 = {
        "Cookie": f"aiac_session={user_session2}",
        "X-CSRF-Token": user_csrf,
        "X-AIAC-Contract": "v6.2",
    }
    assert client2.get("/api/ad-coin/v2/ad-preferences", headers=headers_human2).status_code == 200

    new_epoch = new_resolver.rotate_principal_epoch(user_principal_id)
    assert new_epoch == 2
    # Older epoch should now be rejected as authority_revoked
    assert client2.get("/api/ad-coin/v2/ad-preferences", headers=headers_human2).status_code == 403


def test_task2_key_vault_and_security_guards(store):  # noqa: F811
    store.migrate_model()

    # 1. KeyVault Lifecycle
    vault = KeyVault()
    status = vault.get_status()
    assert status["vault_healthy"] is True
    assert status["fallback_keys_count"] == 0

    jwk = vault.get_jwk()
    assert jwk["kty"] == "OKP"
    assert jwk["crv"] == "Ed25519"
    assert "x" in jwk

    # Rotate fresh proof key
    active_key, fallbacks = vault.get_fresh_keys()
    new_active = vault.rotate_fresh_key()
    assert new_active != active_key
    assert vault.get_fresh_keys()[1] == (active_key,)

    # 2. TokenBucketRateLimiter
    limiter = TokenBucketRateLimiter()
    key = "ip:192.168.1.100"
    # Allow 5 requests with cost=1
    for _ in range(5):
        allowed, retry_after = limiter.check(key, limit_per_minute=5, cost=1)
        assert allowed is True
        assert retry_after == 0

    # 6th request should be rate-limited
    allowed, retry_after = limiter.check(key, limit_per_minute=5, cost=1)
    assert allowed is False
    assert retry_after >= 1

    # 3. AuditLogger
    actor_id = uid()
    target_id = uid()
    log_id = AuditLogger.log(
        store,
        EventType.CAMPAIGN_ACTIVATED,
        "succeeded",
        actor_principal_id=actor_id,
        target_id=target_id,
        details={"budget": "1000"},
        now_ms=NOW,
    )
    assert log_id is not None
    recent = AuditLogger.recent(store, limit=10)
    assert len(recent) >= 1
    assert recent[0]["event_type"] == EventType.CAMPAIGN_ACTIVATED
    assert recent[0]["target_id"] == target_id

    # 4. Role Separation Specifications
    role_specs = verify_role_specifications()
    assert role_specs["status"] == "valid"
    sql = generate_role_setup_sql()
    assert "GRANT USAGE ON SCHEMA public TO ad_coin_app;" in sql
    assert "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO ad_coin_migrator;" in sql


def test_task3_disaster_recovery_and_reconciliation(store):  # noqa: F811
    store.migrate_model()
    commercial = Commercial(
        store,
        taxonomy=frozenset({"research", "coding"}),
        regions=frozenset({"US", "KR"}),
    )

    # 1. Reconciliation of a clean ledger
    reconciler = LedgerReconciler(store)
    report = reconciler.run_full_reconciliation()
    assert report.status == "clean"
    assert report.asset_balances[MODEL_ASSET] == "0"
    assert len(report.issues) == 0

    # 2. Worker Crash Recovery: Stale lease reclamation
    worker_id = uid()
    # Enqueue a test outbox item
    with store.atomic():
        store.execute(
            "outbox_insert",
            (
                uid(),
                "test-stale-lease",
                "h" * 64,
                '{"event": "campaign_paused"}',
                NOW,
            ),
        )
    # Claim it
    leases = commercial.workers.outbox.claim(worker_id, now_ms=NOW, limit=1)
    assert len(leases) == 1
    lease = leases[0]
    assert lease.worker_id == worker_id

    # Reclaim stale leases at a later time
    reclaimed = commercial.workers.reclaim_stale_leases(now_ms=NOW + 120_000, limit=10)
    assert reclaimed == 1
    # Verify lease is back to pending and can be claimed by a different worker
    new_leases = commercial.workers.outbox.claim(uid(), now_ms=NOW + 120_000, limit=1)
    assert len(new_leases) == 1

    # 3. Campaign Review Appeal Workflow
    advertiser_id = uid()
    editor_id = uid()
    editor_owner = uid()
    reviewer_id = uid()

    commercial.access.provision_principal(
        editor_id, Kind.HUMAN, owner_id=editor_owner, capabilities=COMMERCIAL_CAPABILITIES
    )
    commercial.access.provision_principal(
        reviewer_id, Kind.REVIEWER, capabilities=frozenset(("review.decide",))
    )
    commercial.access.provision_advertiser(advertiser_id, uid())
    commercial.access.grant(advertiser_id, editor_id, "campaign.edit")

    # Create campaign and request review
    editor_principal = Principal(
        UUID(editor_id),
        Kind.HUMAN,
        1,
        2_000_000_000,
        owner_id=UUID(editor_owner),
        csrf_verified=True,
        advertiser_permissions=frozenset(((UUID(advertiser_id), "campaign.edit"),)),
    )
    # We use commercial methods directly
    with store.atomic():
        camp_id = uid()
        rev_id = uid()
        acc = commercial.ledger.create_account(advertiser_id, "campaign_available")
        store.execute("campaign_insert", (camp_id, advertiser_id, rev_id, acc))
        store.execute(
            "revision_insert",
            (
                rev_id,
                camp_id,
                advertiser_id,
                "0" * 64,
                '{"name":"Test"}',
                NOW,
                NOW + 86400000,
                "1000",
                "100",
                "10",
                '{"user":"5","operator":"2","direct":"1","platform":"2"}',
            ),
        )
        rev_review_id = uid()
        store.execute("review_insert", (rev_review_id, camp_id, advertiser_id, rev_id, 1))
        ev_id = uid()
        store.execute(
            "review_evidence_insert",
            (ev_id, rev_review_id, rev_id, advertiser_id, "0" * 64),
        )
        store.execute(
            "review_decide",
            ("rejected", reviewer_id, ev_id, "policy_violation", rev_review_id, 1),
        )

    # Submit Appeal
    appeal = commercial.submit_review_appeal(
        editor_principal,
        rev_review_id,
        reason_text="Ad text conforms to community guidelines. Please reconsider.",
        now_ms=NOW,
    )
    assert appeal["state"] == "pending"
    assert appeal["campaign_id"] == camp_id

    # Reviewer decides appeal
    reviewer_principal = Principal(
        UUID(reviewer_id),
        Kind.REVIEWER,
        1,
        2_000_000_000,
        mtls_verified=True,
        capabilities=frozenset(("review.decide",)),
        audience="aiac-v2-reviewer",
    )
    decided_appeal = commercial.decide_review_appeal(
        reviewer_principal,
        appeal["id"],
        verdict="accepted",
        decision_reason="Re-reviewed and approved for resubmission",
        now_ms=NOW + 5000,
    )
    assert decided_appeal["state"] == "accepted"
    # Campaign should be back in draft
    camp_row = store.one("campaign_get", (camp_id,))
    assert camp_row["state"] == "draft"
