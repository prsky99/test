"""Opt-in workspace access, privacy, static delivery and bounded projections on PostgreSQL."""

import re

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from agent_market.ad_coin.v2.contracts import ContractError

from agent_market.ad_coin.v2.http import router_for
from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_persistence import store  # noqa: F401
from tests.test_ad_coin_v2_p1 import p1_suite as _fixture, campaign_body

p1_suite = _fixture


@pytest.fixture
def workspace(p1_suite):
    app = FastAPI()
    app.include_router(
        router_for(
            p1_suite.service, resolve_auth=p1_suite.resolver, include_workspace=True
        )
    )
    with TestClient(app) as client:
        yield p1_suite, client, app


def cookies(suite, role="user"):
    return {
        "Cookie": "aiac_session="
        + ({"editor": suite.editor_token, "user": suite.user_token}[role])
    }


def test_shell_is_static_has_no_credentials_and_assets_are_fingerprinted(
    workspace, monkeypatch
):
    suite, client, _ = workspace

    def fail(*_args, **_kwargs):
        pytest.fail("A static shell must not access the database")

    monkeypatch.setattr(suite.service.store, "atomic", fail)
    response = client.get("/ad-coin/v2")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert "unsafe-inline" not in response.headers["content-security-policy"]
    assert (
        suite.user_token not in response.text and suite.user_owner not in response.text
    )
    urls = re.findall(r'(?:src|href)="(/ad-coin/v2/assets/[^\"]+)"', response.text)
    assert len(urls) == 2
    for url in urls:
        asset = client.get(url)
        assert (
            asset.status_code == 200 and "immutable" in asset.headers["cache-control"]
        )
        assert (
            client.get(
                url, headers={"If-None-Match": asset.headers["etag"]}
            ).status_code
            == 304
        )
    assert client.get("/ad-coin/v2/assets/not-an-asset.js").status_code == 404


def test_workspace_projects_only_current_human_data(workspace):
    suite, client, _ = workspace
    response = client.get("/ad-coin/v2/ui/session", headers=cookies(suite))
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["preferences"]["receive_offers"] is False
    assert value["preferences"]["context_fields"] == []
    assert len(value["wallets"]) == 1 and value["wallets"][0]["available_atoms"] == "0"
    assert value["advertisers"] == []
    assert (
        suite.user_owner not in response.text and suite.user_token not in response.text
    )
    assert "principal_id" not in response.text and "session_hash" not in response.text


def test_workspace_requires_an_explicit_boolean_opt_in(workspace):
    suite, _, _ = workspace
    with pytest.raises(ContractError, match="invalid_workspace_flag"):
        router_for(
            suite.service, resolve_auth=suite.resolver, include_workspace="false"
        )


@pytest.mark.parametrize(
    "mode,status",
    [("anonymous", 401), ("bearer", 403), ("query", 422), ("revoked", 403)],
)
def test_workspace_denies_inappropriate_access(workspace, mode, status):
    suite, client, _ = workspace
    headers = cookies(suite)
    target = "/ad-coin/v2/ui/session"
    if mode == "anonymous":
        headers = {}
    if mode == "bearer":
        headers = suite.headers()
    if mode == "query":
        target += "?token=never-display-this"
    if mode == "revoked":
        suite.service.access.guards.revoke(suite.user_principal_id, 1)
    response = client.get(target, headers=headers)
    assert response.status_code == status, response.text
    assert response.headers["cache-control"] == "no-store"
    assert "never-display-this" not in response.text


def test_campaign_projection_is_scoped_and_paginated_without_n_plus_one(
    workspace, monkeypatch
):
    suite, client, _ = workspace
    root = "/api/ad-coin/v2/advertisers/" + suite.advertiser + "/campaigns"
    for n in range(12):
        response = suite.client.post(
            root,
            json=campaign_body(name="Notebook " + str(n)),
            headers=suite.headers("editor"),
        )
        assert response.status_code == 200, response.text
    url = "/ad-coin/v2/ui/advertisers/" + suite.advertiser + "/campaigns"
    assert client.get(url, headers=cookies(suite)).status_code == 403
    calls = []
    original = suite.service.store.one

    def read(name, *args, **kwargs):
        calls.append(name)
        return original(name, *args, **kwargs)

    monkeypatch.setattr(suite.service.store, "one", read)
    first = client.get(url, headers=cookies(suite, "editor"))
    assert first.status_code == 200, first.text
    count = len(calls)
    calls.clear()
    value = first.json()
    assert len(value["items"]) == 10 and value["next_cursor"]
    second = client.get(
        url + "?cursor=" + value["next_cursor"], headers=cookies(suite, "editor")
    )
    assert len(second.json()["items"]) == 2 and second.json()["next_cursor"] is None
    assert len(calls) == count
    assert "creative_text" not in first.text and "payload_json" not in first.text
    assert (
        client.get(url + "?cursor=bad", headers=cookies(suite, "editor")).status_code
        == 422
    )


def test_schema_three_upgrade_adds_indexes_without_changing_balances(workspace):
    from agent_market.ad_coin.sql_registry import unchecked
    from agent_market.ad_coin.v2.performance_schema import INDEXES
    from tests.test_ad_coin_v2_persistence import raw
    import psycopg

    suite, _, _ = workspace
    database = suite.service.store
    before = suite.service.ledger.audit()
    with unchecked(), database.database.transaction() as connection:
        for sql in INDEXES:
            connection.execute(
                psycopg.sql.SQL("DROP INDEX {}")
                .format(psycopg.sql.Identifier(sql.split()[5]))
                .as_string()
            )
    raw(database, "UPDATE adc2_schema SET version=3 WHERE id=1")
    database.migrate_model()
    from agent_market.ad_coin.v2.schema import VERSION

    assert database.one("schema_get")["version"] == VERSION
    for sql in INDEXES:
        rows = raw(
            database,
            "SELECT indexdef FROM pg_indexes WHERE schemaname=? AND indexname=?",
            ("public", sql.split()[5]),
        )
        assert len(rows) == 1
    assert suite.service.ledger.audit() == before
