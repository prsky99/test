"""Actual new console reads against a temporary PostgreSQL 18 cluster."""

import json
from pathlib import Path
from unittest.mock import Mock
import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from agent_market.gateway.dashboard import dashboard_router
from agent_market.gateway import admin_auth
from agent_market.storage_adapter import open_store
from scripts.rehearse_storage_adapter_postgres import (
    _private_cluster,
    PORT,
    RehearsalError,
)


def test_new_console_queries_on_native_postgresql18():
    tools = {
        name: "/opt/homebrew/opt/postgresql@18/bin/" + name
        for name in ("initdb", "pg_ctl")
    }
    if not all(Path(value).exists() for value in tools.values()):
        pytest.skip("PostgreSQL 18 test binaries unavailable")
    manager = _private_cluster(tools)
    try:
        cluster = manager.__enter__()
    except RehearsalError:
        pytest.skip(
            "Temporary cluster initialization unavailable; host shared-memory limits. See read-only PostgreSQL evidence."
        )
    try:
        connection = psycopg.connect(
            host=cluster["socket"],
            port=PORT,
            dbname="postgres",
            user="postgres",
            autocommit=True,
        )
        store = open_store(
            "postgresql", connection=connection, initialize=True, workflow_key=b"a" * 32
        )
        try:
            with store.tx() as db:
                user = admin_auth.create_admin_user(
                    db,
                    "console-native",
                    "Synthetic-native-pass42",
                    "Fixture",
                    "superadmin",
                )
                raw = admin_auth.create_session(
                    db, user["id"], user["username"], user["role"], user["name"]
                )
            store.upsert_resource(
                {
                    "key": "fixture:console",
                    "source": "fixture",
                    "kind": "mcp",
                    "url": "https://fixture.example/mcp",
                    "name": "Native console agent",
                    "description": "Synthetic",
                    "category": "research",
                    "networks": [],
                    "details": {},
                },
                now=1,
            )
            app = FastAPI()
            app.include_router(
                dashboard_router(
                    store,
                    None,
                    "synthetic-machine",
                    None,
                    ssl_manager=Mock(get_status=lambda: {}),
                )
            )
            headers = {"X-Dashboard": "1", "Authorization": "Bearer " + raw}
            checks = {}
            with TestClient(app, base_url="https://admin.test") as client:
                for name in (
                    "collection",
                    "health",
                    "evaluations",
                    "search-index",
                    "workflows/recent",
                    "workflow-candidates",
                    "services",
                    "settings",
                    "executions",
                    "logs",
                ):
                    response = client.get(
                        "/admin/api/v2/console/" + name, headers=headers
                    )
                    assert response.status_code == 200, (name, response.text)
                    checks[name] = response.status_code
                assert (
                    client.get("/admin/api/v2/console/health", headers=headers).json()[
                        "items"
                    ][0]["name"]
                    == "Native console agent"
                )
            folder = Path("reports/admin-redesign-implementation-2026-10-24")
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "postgres18-results.json").write_text(
                json.dumps(
                    {
                        "version": connection.info.server_version,
                        "checks": checks,
                        "operating_database_writes": 0,
                        "temporary_socket_only": True,
                    },
                    indent=2,
                )
            )
        finally:
            store.close()
            connection.close()

    finally:
        manager.__exit__(None, None, None)
