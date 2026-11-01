"""QA11 contracts on disposable native PostgreSQL 18; no real user data or providers."""

import time


def contracts(connect, factory):
    from fastapi.testclient import TestClient
    from agent_market.postgres_lexical import install
    from agent_market.capability_registry import Registry
    from agent_market.collector import usage
    from agent_market.concierge.front import Front, create_front_app
    from agent_market.concierge.selection import QualityRecommender
    from agent_market.concierge.hybrid_explore import scoped_explore
    from agent_market.admin_postgres_pool import AdminReaderPool

    connection = connect()
    assert 180000 <= connection.info.server_version < 190000
    key = b"n" * 32
    store = factory(connection, initialize=True, workflow_key=key)
    front = None
    pool = None
    checks = {"postgresql_18": True}
    try:
        install(store)
        registry = Registry(store)

        def add(index, name, description, tool_name):
            spec = {
                "name": tool_name,
                "description": description,
                "inputSchema": {"type": "object", "properties": {}, "required": []},
                "annotations": {"readOnlyHint": True},
            }
            if tool_name == "translate_text":
                spec["inputSchema"] = {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "target_lang": {"type": "string"},
                    },
                    "required": ["text", "target_lang"],
                }
            rid = store.upsert_resource(
                {
                    "key": "synthetic-qa11:" + str(index),
                    "source": "fixture",
                    "kind": "mcp",
                    "url": f"https://qa11-{index}.example/mcp",
                    "name": name,
                    "description": description,
                    "category": "general",
                    "price_usdc": 0,
                }
            )
            compact = usage.compact_tools([spec])
            store.record_usage(
                rid,
                compact,
                usage.tools_hash(compact),
                {},
                None,
                None,
                full_tools=[spec],
            )
            store.record_health(
                rid, "healthy", 200, 1, None, time.time() + 21600, auth_observed=False
            )
            store.record_evaluation(
                rid, {"score": 95, "grade": "A", "security": "ok", "coverage": 100}
            )
            now = time.time() - 1
            registry.record(
                registry.current(store.resource(rid)),
                scope="execution",
                outcome="succeeded",
                started=now,
                finished=now,
            )
            return rid

        ground = add(
            0,
            "Global Weather",
            "Current weather and daily forecasts in any city.",
            "get_weather",
        )
        add(
            1,
            "Sky Observatory",
            "Aviation and space data: METAR/TAF, space weather and aurora.",
            "space_weather",
        )
        translate = add(
            2,
            "Focused Translate",
            "Translate text and documents into 100 languages.",
            "translate_text",
        )
        for index in range(3, 54):
            add(
                index,
                "Catalog entry " + str(index),
                "Read a public catalog record.",
                "read_record",
            )
        front = Front(store)
        with TestClient(create_front_app(front)) as client:
            for query in ("data", "api", "agent", "mcp", "*", "the and of"):
                first = client.get(
                    "/api/explore", params={"q": query, "kind": "mcp"}
                ).json()
                assert (
                    first["status"] == "browsing"
                    and len(first["items"]) == 45
                    and first["next_cursor"] == "o45"
                )
                second = client.get(
                    "/api/explore", params={"q": query, "kind": "mcp", "cursor": "o45"}
                ).json()
                assert second["items"] and {r["id"] for r in first["items"]}.isdisjoint(
                    r["id"] for r in second["items"]
                )
            checks["general_queries_and_filtered_cursor_browse"] = True
            text = client.get("/llms.txt").text
            assert "/api/agent/v1/badge/{resource_id}.svg" in text
            checks["document_badge_template_matches_schema"] = True
        recommender = QualityRecommender(store)
        result = recommender.search(
            "Translate a Korean contract into English", kind="mcp", limit=3
        )
        assert result and result[0]["id"] == translate
        checks["native_simple_index_translation_inflection_recall"] = True

        def reader():
            pg = connect()
            pg.execute("SET default_transaction_read_only=on")
            return factory(pg, workflow_key=key), pg

        pool = AdminReaderPool(reader, maximum=3)
        store._admin_read_pool = pool
        result = scoped_explore(store, None, "weather", None, None, False, False, 46)
        assert ground in [r["id"] for r in result["items"]]
        assert all(r["kind"] != "x402" for r in result["items"])
        assert pool.leased == 0
        checks["parallel_readers_return_and_preserve_protocol_scope"] = True
        return {"checks": checks}
    finally:
        if pool is not None:
            pool.close()
        if front is not None:
            assert front.book.close()
        store.close()
