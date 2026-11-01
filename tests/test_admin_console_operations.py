"""Real console read models remain bounded, private and non-mutating."""

# ruff: noqa: F401,F811
import pytest
from tests.test_admin_next import dash, login, D


def test_task_read_models_load_without_triggering_collection(dash):
    world, client = dash
    headers = login(client)
    paths = [
        "collection",
        "health",
        "evaluations",
        "search-index",
        "workflows/recent",
        "services",
        "settings",
        "executions",
    ]
    before = list(world.store.query("SELECT COUNT(*) AS n FROM crawl_runs"))
    for path in paths:
        response = client.get("/admin/api/v2/console/" + path, headers=headers)
        assert response.status_code == 200, (path, response.text)
        assert "no-store" in response.headers["cache-control"]
        assert "captured_at" in response.json()
        assert client.get("/admin/api/v2/console/" + path, headers=D).status_code in (
            401,
            403,
        )
        assert (
            client.get(
                "/admin/api/v2/console/" + path,
                headers={**headers, "Origin": "https://evil.example"},
            ).status_code
            == 403
        )
    assert before == list(world.store.query("SELECT COUNT(*) AS n FROM crawl_runs"))


def test_unknown_execution_is_404_not_a_successful_empty_screen(dash):
    _, client = dash
    response = client.get(
        "/admin/api/v2/console/executions/not-a-real-execution", headers=login(client)
    )
    assert response.status_code == 404


def test_finance_alias_has_individual_superadmin_boundary(dash):
    _, client = dash
    h = login(client)
    path = "/admin/api/v2/catalog-tools/payments/overview"
    assert client.get(path, headers=h).status_code == 200
    assert client.get(path, headers=D).status_code in (401, 403)
    assert (
        client.post(
            "/admin/api/v2/catalog-tools/payments/withdraw", headers=h, json={}
        ).status_code
        == 404
    )


def test_role_projections_and_financial_paging_bounds(dash):
    from agent_market.gateway import admin_auth

    world, client = dash
    owner = login(client)
    for role in ("viewer", "operator", "admin"):
        with world.store.tx() as db:
            user = admin_auth.create_admin_user(
                db, "console-" + role, "Synthetic-role-password", role, role
            )
            token = admin_auth.create_session(
                db, user["id"], user["username"], role, role
            )
        headers = {**D, "Authorization": "Bearer " + token}
        assert (
            client.get("/admin/api/v2/console/services", headers=headers).status_code
            == 200
        )
        assert (
            client.get("/admin/api/v2/console/settings", headers=headers).status_code
            == 403
        )
        assert (
            client.get(
                "/admin/api/v2/catalog-tools/payments/accounts", headers=headers
            ).status_code
            == 403
        )
        assert client.get(
            "/admin/api/v2/console/health", headers=headers
        ).status_code == (403 if role == "viewer" else 200)
        assert client.get(
            "/admin/api/v2/console/collection", headers=headers
        ).status_code == (200 if role == "admin" else 403)
    for route in ("accounts", "ledger", "clearinghouse"):
        for bad in ("limit=0", "limit=101", "offset=-1", "offset=100001"):
            assert (
                client.get(
                    "/admin/api/v2/catalog-tools/payments/" + route + "?" + bad,
                    headers=owner,
                ).status_code
                == 422
            )
