"""Test suite for AI AD Coin v2 Admin HTTP endpoints."""

from uuid import uuid4

from fastapi import FastAPI
from starlette.testclient import TestClient

from agent_market.ad_coin.v2.access import HUMAN_CAPABILITIES
from agent_market.ad_coin.v2.identity import Kind
from agent_market.ad_coin.v2.live_service import create_live_ad_coin_v2_router
from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_persistence import store  # noqa: F401


def uid():
    return str(uuid4())


def test_admin_http_endpoints_live(store):  # noqa: F811
    store.migrate_model()
    router = create_live_ad_coin_v2_router(store)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    # 1. Without credentials -> 401
    resp = client.get("/api/ad-coin/v2/admin/reconcile")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "authentication_required"

    # 2. Provision Human principal and session
    owner_id = uid()
    principal_id = uid()
    from agent_market.ad_coin.v2.access import Access
    from agent_market.ad_coin.v2.live_auth import PersistentCredentialResolver

    access = Access(store)
    access.provision_principal(
        principal_id, Kind.HUMAN, owner_id=owner_id, capabilities=HUMAN_CAPABILITIES
    )
    access.provision_preferences(owner_id, now_ms=1_800_000_000_000)
    access.provision_wallet(owner_id)

    resolver = PersistentCredentialResolver(store)
    session_token = "sess-" + uid()
    csrf_token = "csrf-" + uid()
    resolver.register_human_session(
        session_token,
        csrf_token,
        principal_id=principal_id,
        owner_id=owner_id,
    )

    cookies = {"aiac_session": session_token}
    headers = {"X-CSRF-Token": csrf_token}

    # 3. Call /reconcile with human session
    recon_resp = client.get("/api/ad-coin/v2/admin/reconcile", cookies=cookies, headers=headers)
    assert recon_resp.status_code == 200
    recon_data = recon_resp.json()
    assert recon_data["status"] == "balanced"
    assert recon_data["audit"]["zero_sum_balanced"] is True
    assert recon_data["reconciliation"]["balanced"] is True

    # 4. Call /overview with human session
    overview_resp = client.get("/api/ad-coin/v2/admin/overview", cookies=cookies, headers=headers)
    assert overview_resp.status_code == 200
    overview_data = overview_resp.json()
    assert "total_wallets_count" in overview_data
    assert "active_campaigns_count" in overview_data
    assert overview_data["total_wallets_count"] >= 1
