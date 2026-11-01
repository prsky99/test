"""Actual Explore API on disposable PostgreSQL; provider evidence is synthetic."""

import json
from pathlib import Path
from unittest.mock import patch
import pytest
import psycopg
from fastapi.testclient import TestClient

from agent_market import explore_documents as doc
from agent_market.collector.usage import compact_tools
from agent_market.concierge.front import Front, create_front_app, clear_front_caches
from agent_market.postgres_lexical import install as install_lexical
from agent_market.storage_adapter import open_store
from scripts.rehearse_storage_adapter_postgres import _private_cluster, PORT


def test_explore_api_current_documents_cursor_scope_and_escaping():
    binary = Path("/opt/homebrew/opt/postgresql@18/bin")
    if not (binary / "initdb").is_file():
        pytest.skip("PostgreSQL 18 fixture tools unavailable")
    with _private_cluster(
        {name: str(binary / name) for name in ("initdb", "pg_ctl")}
    ) as cluster:
        with psycopg.connect(
            host=cluster["socket"],
            port=PORT,
            dbname="postgres",
            user="postgres",
            autocommit=True,
        ) as pg:
            store = open_store(
                "postgresql", connection=pg, initialize=True, workflow_key=b"p" * 32
            )
            install_lexical(store)
            from agent_market.postgres_capability_text import install as install_text

            install_text(store)
            ids = []
            tool = {
                "name": "get_weather_forecast",
                "description": "Get global weather forecasts for any city.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                },
                "annotations": {"readOnlyHint": True},
            }
            for index in range(55):
                rid = store.upsert_resource(
                    {
                        "key": f"a1-api-{index}",
                        "source": "fixture",
                        "kind": "mcp",
                        "url": f"https://a1-api-{index}.example/mcp",
                        "name": f"Global Weather {index}",
                        "description": tool["description"],
                        "category": "travel_maps_weather",
                    }
                )
                store.record_usage(
                    rid, compact_tools([tool]), None, {}, None, None, full_tools=[tool]
                )
                store.record_health(
                    rid, "healthy", 200, 1, None, 9999999999, auth_observed=False
                )
                ids.append(rid)
            doc.install(store)
            worker = doc.Refresher(store, batch=100, interval=0)
            assert worker.run()["written"] == 55
            clear_front_caches()
            front = Front(store)
            with TestClient(create_front_app(front)) as client:
                # The compact metadata is consumed before complete contracts are
                # hydrated for final cards; it never appears in the JSON response.
                result = client.get(
                    "/api/explore",
                    params={"q": "weather forecast seoul", "kind": "mcp"},
                ).json()
                assert len(result["items"]) == 45 and result["next_cursor"] == "o45"
                # A full lightweight-read budget uses original complete admission,
                # rather than failing the request or inventing unrelated results.
                clear_front_caches()
                with patch.object(doc, "MAX_READ_BYTES", 1):
                    fallback = client.get(
                        "/api/explore",
                        params={"q": "weather forecast seoul", "kind": "mcp"},
                    ).json()
                assert [row["id"] for row in fallback["items"]] == [
                    row["id"] for row in result["items"]
                ]
                assert "_explore_document" not in json.dumps(result)
                assert "source_digest" not in json.dumps(result)
                later = client.get(
                    "/api/explore",
                    params={
                        "q": "weather forecast seoul",
                        "kind": "mcp",
                        "cursor": "o45",
                    },
                ).json()
                assert later["items"] and {r["id"] for r in result["items"]}.isdisjoint(
                    r["id"] for r in later["items"]
                )
                assert all(
                    row["kind"] == "mcp" for row in result["items"] + later["items"]
                )
                assert not client.get(
                    "/api/explore",
                    params={"q": "weather forecast seoul", "kind": "a2a"},
                ).json()["items"]
                assert not client.get("/api/explore", params={"q": "xyzqxzjkq"}).json()[
                    "items"
                ]
                assert (
                    client.get("/api/explore", params={"q": "mcp"}).json()["status"]
                    == "browsing"
                )

                removed = result["items"][0]["id"]
                with store.tx():
                    store._execute(
                        "UPDATE resources SET active=0 WHERE id=%s", (removed,)
                    )
                # Even a reused result page rechecks current availability.
                assert removed not in [
                    row["id"]
                    for row in client.get(
                        "/api/explore",
                        params={"q": "weather forecast seoul", "kind": "mcp"},
                    ).json()["items"]
                ]

                clear_front_caches()
                with store.tx():
                    store._execute(
                        "UPDATE resources SET auth_observed=1 WHERE id=%s", (ids[1],)
                    )
                filtered = client.get(
                    "/api/explore",
                    params={
                        "q": "weather forecast seoul",
                        "kind": "mcp",
                        "no_auth": True,
                    },
                ).json()
                assert ids[1] not in [row["id"] for row in filtered["items"]]
                assert not client.get(
                    "/api/explore",
                    params={"q": "weather forecast seoul", "verified": True},
                ).json()["items"]
                assert (
                    client.get(
                        "/api/explore", params={"q": "weather", "limit": 301}
                    ).status_code
                    == 422
                )
            store.close()
