"""QA11: directory browsing, lexical recall and specialist ranking without weaker gates."""

# ruff: noqa: F811
import json
from unittest.mock import patch
import pytest
from agent_market.concierge.explore_search import browse_query, task_advertised
from agent_market.concierge.discovery import lexical_match
from agent_market.concierge.selection import _service_focus
from agent_market.concierge.front import clear_front_caches
from tests.test_fast_single_recommendation import catalog  # noqa: F401


@pytest.mark.parametrize(
    "query", ["data", "api", "agent", "mcp", "a", "*", "the and of", "MCP agents"]
)
def test_general_queries_are_explicit_browsing_with_pagination(catalog, query):
    _, _, client, add, _ = catalog
    clear_front_caches()
    for i in range(50):
        add("Catalog entry " + str(i))
    first = client.get("/api/explore", params={"q": query, "kind": "mcp"}).json()
    assert len(first["items"]) == 45 and first["status"] == "browsing"
    assert (
        first["query_ignored"] and first["next_cursor"] == "o45" and first["has_more"]
    )
    assert "broad" in first["search_notice"] and first["query"] == query
    second = client.get(
        "/api/explore",
        params={"q": query, "kind": "mcp", "cursor": first["next_cursor"]},
    ).json()
    assert second["items"] and {r["id"] for r in first["items"]}.isdisjoint(
        r["id"] for r in second["items"]
    )


@pytest.mark.parametrize(
    "query",
    ["weather", "API documentation", "data analysis", "agent memory", "zzqqnotatask"],
)
def test_specific_queries_are_not_silently_browsed(query):
    assert not browse_query(query)


def test_protocol_browse_respects_explicit_selector(catalog):
    _, _, client, add, _ = catalog
    clear_front_caches()
    add("Catalog MCP", kind="mcp")
    expected = add("Catalog A2A", kind="a2a")
    body = client.get("/api/explore", params={"q": "mcp", "kind": "a2a"}).json()
    assert [r["id"] for r in body["items"]] == [expected]


def test_specialist_weather_is_a_bundle_even_if_it_has_a_usable_ground_tool():
    resource = {
        "kind": "mcp",
        "name": "Observatory",
        "description": "Aviation and space data: METAR/TAF, space weather and aurora.",
        "usage_guide": json.dumps(
            {
                "tools": [
                    {
                        "name": "get_weather",
                        "description": "Hourly weather forecast for a city.",
                    },
                    {"name": "get_metar", "description": "Airport METAR."},
                    {"name": "solar", "description": "Solar storms."},
                ]
            }
        ),
    }
    assert not _service_focus(["weather"], resource, ["weather"])
    assert _service_focus(
        ["weather"],
        {
            "kind": "mcp",
            "name": "Global Weather",
            "description": "Current weather in any city.",
        },
    )


def test_simple_lexical_index_keeps_translate_translation_recall():
    assert (
        lexical_match(["translation"], " ")
        == '"translation" OR "translate" OR "translator"'
    )
    assert '"weather" "forecasts"' in lexical_match(["weather", "forecast"], " ")
    assert len(lexical_match(["translation"] * 8, " ").split(" OR ")) <= 16


def test_current_all_unsupported_tool_facts_skip_parsing():
    row = {
        "kind": "mcp",
        "name": "Weather",
        "description": "Weather forecast",
        "_capability_text": "weather forecast",
        "_tool_support": {"forecast": False},
    }
    with patch(
        "agent_market.concierge.selection._advertised_tools",
        side_effect=AssertionError("No contract parsing needed"),
    ):
        assert (
            task_advertised(
                "weather forecast",
                row,
                terms=["weather", "forecast"],
                core=["weather", "forecast"],
            )
            is False
        )


@pytest.mark.parametrize(
    "reference",
    [
        "the second one",
        "tell me more about the second one",
        "could you tell me about the second option",
    ],
)
def test_four_turn_reference_uses_the_original_list(catalog, reference):
    _, _, client, add, now = catalog
    ids = [add("Weather " + str(n), report_at=now - n) for n in range(3)]
    first = client.post("/chat", json={"message": "MCP weather forecast"}).json()
    expected = first["data"]["recommendations"][1]["id"]
    headers = {"X-Visitor-Token": first["visitor"]["token"]}
    for phrase in (
        reference,
        "can you tell me more about it",
        "how do I connect to it?",
    ):
        answer = client.post("/chat", json={"message": phrase}, headers=headers).json()
        assert answer["data"]["recommendations"][0]["id"] == expected
    assert ids


def test_protocol_reads_overlap_without_a_parent_pool_lease(monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    import threading
    from agent_market.concierge import hybrid_explore as module
    from agent_market.concierge.retrieval_metrics import count

    barrier = threading.Barrier(2)
    leased = []
    memo_ids = []

    class Pool:
        maximum = 2

        @contextmanager
        def lease_store(self):
            store = SimpleNamespace(backend="postgresql")
            leased.append(store)
            yield store

    source = SimpleNamespace(backend="postgresql", _admin_read_pool=Pool())

    def read(store, engine, query, kind, category, verified, no_auth, limit, near=None):  # 596856c0 added near
        from agent_market.concierge.discovery_contracts import _request

        memo_ids.append(id(_request.get()))
        assert store is not source and category == "travel_maps_weather" and no_auth
        barrier.wait(timeout=3)
        count("returned_candidates", 1)
        return {
            "query": query,
            "items": [
                {"id": 1 if kind == "a2a" else 2, "kind": kind, "name": "Weather"}
            ],
            "total": 1,
            "total_is_estimate": False,
            "terms": ["weather"],
        }

    monkeypatch.setattr(module, "explore", read)
    recorded = []
    monkeypatch.setattr(
        "agent_market.search_quality.recorder",
        lambda _: SimpleNamespace(record=lambda *args: recorded.append(args[3])),
    )
    result = module.scoped_explore(
        source, None, "weather", None, "travel_maps_weather", False, True, 45
    )
    assert len(leased) == 2 and leased[0] is not leased[1] and len(set(memo_ids)) == 2
    assert {item["kind"] for item in result["items"]} == {"a2a", "mcp"}
    assert recorded[0]["counts"]["returned_candidates"] == 2


def test_single_reader_pool_never_waits_on_a_second_lease(monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from agent_market.concierge import hybrid_explore as module

    class Pool:
        maximum = 1

        @contextmanager
        def lease_store(self):
            yield SimpleNamespace(backend="postgresql")

    source = SimpleNamespace(backend="postgresql", _admin_read_pool=Pool())
    calls = []

    def read(*args):
        calls.append(args[3])
        return {"items": []}

    monkeypatch.setattr(module, "explore", read)
    assert module.scoped_explore(
        source, None, "weather", None, None, False, False, 45
    ) == {"items": []}
    assert calls == [None]


def test_machine_document_badge_template_matches_openapi(catalog):
    _, _, client, _, _ = catalog
    text = client.get('/llms.txt').text
    paths = client.get('/api/agent/v1/openapi.json').json()['paths']
    assert '/api/agent/v1/badge/{resource_id}.svg' in paths
    assert '/api/agent/v1/badge/{resource_id}.svg' in text
    assert '/api/agent/v1/openapi.json' in text
