"""Public retrieval must be bounded, current, grounded, and constraint-aware."""

# ruff: noqa: F401,F811 -- shared isolated catalog fixture
import concurrent.futures
import json
import time
from unittest.mock import Mock

import httpx
import pytest

from agent_market.gateway.rag import RagEngine
from agent_market.concierge.discovery import normalize_task
from tests.test_fast_single_recommendation import catalog, ask, chosen


def test_semantic_phrases_normalize_capability_without_inventing_results():
    assert (
        normalize_task("Turn a spoken interview into searchable text.")
        == "audio transcription"
    )
    assert (
        normalize_task("Transcribe a podcast with timestamps.")
        == "audio transcription timestamps"
    )
    assert normalize_task("Translate English text into Japanese.").startswith(
        "translation for "
    )
    assert normalize_task("Find Python API documentation.").startswith(
        "documentation for "
    )


def test_same_query_embedding_has_single_flight_and_model_bound_memory_cache():
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        time.sleep(0.03)
        return httpx.Response(200, json={"embeddings": [[0.1] * 768]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        engine = RagEngine(http=client)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            found = list(
                pool.map(
                    lambda _: engine.discovery_embedding("weather forecast"), range(8)
                )
            )
        assert all(len(vector) == 768 for vector in found)
        assert len(calls) == 1
        assert (
            engine.discovery_embedding("weather forecast") is not None
            and len(calls) == 1
        )
        engine.embed_revision = "changed-declared-revision"
        assert (
            engine.discovery_embedding("weather forecast") is not None
            and len(calls) == 2
        )
        assert all(
            "weather forecast" not in str(key) for key in engine._query_embeddings
        )


def test_query_embedding_failure_is_short_cached_and_generation_is_not_called():
    calls = []

    def response(request):
        calls.append(request.url.path)
        return httpx.Response(503, json={})

    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        engine = RagEngine(http=client)
        assert engine.discovery_embedding("weather") is None
        assert engine.discovery_embedding("weather") is None
        assert calls == ["/api/embed"]
        engine.embeddings_enabled = False
        assert engine.discovery_embedding("different query") is None
        assert len(calls) == 1


def test_invalid_unicode_does_not_escape_query_embedding_fallback():
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: pytest.fail("No HTTP expected"))
    ) as client:
        assert RagEngine(http=client).discovery_embedding("\ud800") is None


def test_embedding_cache_capacity_and_caller_mutation_are_isolated():
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"embeddings": [[0.1] * 768]})
        )
    ) as client:
        engine = RagEngine(http=client)
        vector = engine.discovery_embedding("first")
        vector[0] = 999
        assert engine.discovery_embedding("first")[0] == 0.1
        for n in range(130):
            engine.discovery_embedding("query " + str(n))
        assert len(engine._query_embeddings) == 128


def test_nonsense_is_not_matched_to_a_single_generic_word(catalog):
    _, _, client, add, now = catalog
    add(
        "Graph memory",
        description="Cross-session graph memory with time travel.",
        usage_guide='{"tools": [{"name": "graph_memory", "description": "Cross-session graph memory with time travel.", "inputSchema": {"type": "object", "properties": {}}}]}',
        usage_tools='[{"name": "graph_memory", "description": "Cross-session graph memory with time travel.", "inputSchema": {"type": "object", "properties": {}}}]',
        usage_full_tools='[{"name": "graph_memory", "description": "Cross-session graph memory with time travel.", "inputSchema": {"type": "object", "properties": {}}}]',
    )
    reply = ask(
        client,
        "Find a telepathic time travel unicorn detector.",
        data={"protocol": "any"},
    )
    assert not reply["data"].get("recommendations")


def test_forecast_does_not_recommend_current_space_weather(catalog):
    _, _, client, add, now = catalog
    add(
        "Space observatory",
        description="Space weather, aurora and asteroids.",
        usage_guide='{"tools": [{"name": "space_observatory", "description": "Space weather, aurora and asteroids.", "inputSchema": {"type": "object", "properties": {}}}]}',
        usage_tools='[{"name": "space_observatory", "description": "Space weather, aurora and asteroids.", "inputSchema": {"type": "object", "properties": {}}}]',
        usage_full_tools='[{"name": "space_observatory", "description": "Space weather, aurora and asteroids.", "inputSchema": {"type": "object", "properties": {}}}]',
    )
    good = add(
        "City forecast",
        description="Daily weather forecast for cities around the world.",
        health_at=now - 60,
    )
    reply = ask(
        client,
        "Forecast the weather in Seoul for the next three days.",
        data={"protocol": "any"},
    )
    assert chosen(reply)["id"] == good


def test_specific_docs_do_not_return_other_products_documentation(catalog):
    _, _, client, add, now = catalog
    add(
        "Other product docs",
        description="Official Capawesome Cloud documentation.",
        category="docs_knowledge",
        usage_guide='{"tools": [{"name": "other_product_docs", "description": "Official Capawesome Cloud documentation.", "inputSchema": {"type": "object", "properties": {}}}]}',
        usage_tools='[{"name": "other_product_docs", "description": "Official Capawesome Cloud documentation.", "inputSchema": {"type": "object", "properties": {}}}]',
        usage_full_tools='[{"name": "other_product_docs", "description": "Official Capawesome Cloud documentation.", "inputSchema": {"type": "object", "properties": {}}}]',
    )
    good = add(
        "Python documentation",
        description="Python API documentation and HTTP client examples.",
        category="docs_knowledge",
        health_at=now - 90,
        usage_guide='{"tools": [{"name": "python_documentation", "description": "Python API documentation and HTTP client examples.", "inputSchema": {"type": "object", "properties": {}}}]}',
        usage_tools='[{"name": "python_documentation", "description": "Python API documentation and HTTP client examples.", "inputSchema": {"type": "object", "properties": {}}}]',
        usage_full_tools='[{"name": "python_documentation", "description": "Python API documentation and HTTP client examples.", "inputSchema": {"type": "object", "properties": {}}}]',
    )
    reply = ask(client, "Find official Python documentation.", data={"protocol": "any"})
    assert chosen(reply)["id"] == good


def test_technology_news_does_not_return_crypto_only_headlines(catalog):
    _, _, client, add, now = catalog
    add(
        "Crypto headlines",
        description="Cryptocurrency news with source links.",
        category="news_media",
        usage_guide='{"tools": [{"name": "crypto_headlines", "description": "Cryptocurrency news with source links.", "inputSchema": {"type": "object", "properties": {}}}]}',
        usage_tools='[{"name": "crypto_headlines", "description": "Cryptocurrency news with source links.", "inputSchema": {"type": "object", "properties": {}}}]',
        usage_full_tools='[{"name": "crypto_headlines", "description": "Cryptocurrency news with source links.", "inputSchema": {"type": "object", "properties": {}}}]',
    )
    good = add(
        "Tech news",
        description="Technology news and artificial intelligence research updates.",
        category="news_media",
        health_at=now - 90,
        usage_guide='{"tools": [{"name": "tech_news", "description": "Technology news and artificial intelligence research updates.", "inputSchema": {"type": "object", "properties": {}}}]}',
        usage_tools='[{"name": "tech_news", "description": "Technology news and artificial intelligence research updates.", "inputSchema": {"type": "object", "properties": {}}}]',
        usage_full_tools='[{"name": "tech_news", "description": "Technology news and artificial intelligence research updates.", "inputSchema": {"type": "object", "properties": {}}}]',
    )
    reply = ask(
        client,
        "Research current technology news with source links.",
        data={"protocol": "any"},
    )
    assert chosen(reply)["id"] == good


def test_wallet_monitoring_is_not_a_token_price_quote(catalog):
    _, _, client, add, now = catalog
    add(
        "Ethereum token quote",
        description="Ethereum token price and market capitalization.",
        category="finance_crypto",
        usage_guide='{"tools": [{"name": "ethereum_token_quote", "description": "Ethereum token price and market capitalization.", "inputSchema": {"type": "object", "properties": {}}}]}',
        usage_tools='[{"name": "ethereum_token_quote", "description": "Ethereum token price and market capitalization.", "inputSchema": {"type": "object", "properties": {}}}]',
        usage_full_tools='[{"name": "ethereum_token_quote", "description": "Ethereum token price and market capitalization.", "inputSchema": {"type": "object", "properties": {}}}]',
    )
    good = add(
        "Wallet monitor",
        description="Monitor Ethereum wallet token balances and address transaction activity.",
        category="finance_crypto",
        health_at=now - 90,
        usage_guide='{"tools": [{"name": "wallet_monitor", "description": "Monitor Ethereum wallet token balances and address transaction activity.", "inputSchema": {"type": "object", "properties": {}}}]}',
        usage_tools='[{"name": "wallet_monitor", "description": "Monitor Ethereum wallet token balances and address transaction activity.", "inputSchema": {"type": "object", "properties": {}}}]',
        usage_full_tools='[{"name": "wallet_monitor", "description": "Monitor Ethereum wallet token balances and address transaction activity.", "inputSchema": {"type": "object", "properties": {}}}]',
    )
    reply = ask(
        client,
        "Monitor Ethereum wallet activity and token balances.",
        data={"protocol": "any"},
    )
    assert chosen(reply)["id"] == good


@pytest.mark.parametrize(
    "description",
    [
        "Discovery agent for pay-per-call tools: returns a matching endpoint.",
        "This A2A agent is a receptionist: every message returns the same guide.",
        "This A2A agent is a free concierge: it replies with matching tools.",
    ],
)
def test_downstream_catalog_is_not_promoted_to_task_execution(catalog, description):
    _, _, client, add, _ = catalog
    add(
        "Audio catalog",
        kind="a2a",
        description=description,
        usage_guide=json.dumps(
            {
                "tools": [
                    {
                        "name": "Transcribe audio",
                        "description": "Transcribe audio into text.",
                    }
                ]
            }
        ),
    )
    assert not ask(client, "audio transcription")["data"].get("recommendations")


def test_seoul_forecast_does_not_use_us_only_provider(catalog):
    _, _, client, add, now = catalog
    add(
        "US weather",
        description="US weather forecasts from the National Weather Service.",
    )
    good = add(
        "Global forecast",
        description="Daily weather forecast for any city worldwide.",
        health_at=now - 90,
    )
    assert (
        chosen(ask(client, "Weather forecast in Seoul", data={"protocol": "any"}))["id"]
        == good
    )


def test_pull_request_translation_is_not_a_security_review(catalog):
    _, _, client, add, now = catalog
    add(
        "Product translations",
        description="Ship reviewed translations as GitHub pull requests.",
        usage_guide='{"tools": [{"name": "product_translations", "description": "Ship reviewed translations as GitHub pull requests.", "inputSchema": {"type": "object", "properties": {}}}]}',
        usage_tools='[{"name": "product_translations", "description": "Ship reviewed translations as GitHub pull requests.", "inputSchema": {"type": "object", "properties": {}}}]',
    )
    good = add(
        "Security review",
        description="Review pull request changes for security vulnerabilities.",
        health_at=now - 90,
        usage_guide='{"tools": [{"name": "security_review", "description": "Review pull request changes for security vulnerabilities.", "inputSchema": {"type": "object", "properties": {}}}]}',
        usage_tools='[{"name": "security_review", "description": "Review pull request changes for security vulnerabilities.", "inputSchema": {"type": "object", "properties": {}}}]',
    )
    assert (
        chosen(
            ask(
                client,
                "Review pull request changes for security vulnerabilities.",
                data={"protocol": "any"},
            )
        )["id"]
        == good
    )


def test_timestamp_constraint_is_not_dropped(catalog):
    _, _, client, add, now = catalog
    add(
        "Plain transcript",
        description="Audio transcription into plain text.",
        usage_guide='{"tools": [{"name": "plain_transcript", "description": "Audio transcription into plain text.", "inputSchema": {"type": "object", "properties": {}}}]}',
        usage_tools='[{"name": "plain_transcript", "description": "Audio transcription into plain text.", "inputSchema": {"type": "object", "properties": {}}}]',
    )
    good = add(
        "Caption transcript",
        description="Audio transcription with timestamps and SRT captions.",
        health_at=now - 90,
        usage_guide='{"tools": [{"name": "caption_transcript", "description": "Audio transcription with timestamps and SRT captions.", "inputSchema": {"type": "object", "properties": {}}}]}',
        usage_tools='[{"name": "caption_transcript", "description": "Audio transcription with timestamps and SRT captions.", "inputSchema": {"type": "object", "properties": {}}}]',
    )
    assert (
        chosen(
            ask(
                client,
                "Turn a podcast recording into a timestamped transcript.",
                data={"protocol": "any"},
            )
        )["id"]
        == good
    )


@pytest.mark.parametrize(
    "field",
    [
        None,
        "generation",
        "job_id",
        "status",
        "source_hash",
        "corpus_hash",
        "descriptor_hash",
        "actual_hash",
    ],
)
def test_native_bulk_publication_gate_rejects_each_changed_proof(monkeypatch, field):
    from types import SimpleNamespace
    from agent_market.application_store_vector import PostgresVectorIndex
    from agent_market.legacy_vector_index import PROFILE, source

    descriptor = RagEngine().model_descriptor()
    resource = {
        "id": 1,
        "name": "Forecast",
        "description": "Weather forecasts",
        "category": "weather",
        "active": 1,
        "kind": "mcp",
        "url": "https://forecast.example/mcp",
    }
    data = source(resource)
    state = {
        "resource_id": 1,
        "generation": 1,
        "current_generation": 1,
        "job_id": "j1",
        "current_job": "j1",
        "status": "indexed",
        "source_hash": data.source_hash,
        "corpus_hash": data.corpus_hash,
        "descriptor_hash": descriptor.digest,
        "vector_hash": "abc",
        "actual_hash": "abc",
    }
    if field is not None:
        state[field] = "changed"
    results = iter([[(1, PROFILE, descriptor.digest)], [state]])
    index = PostgresVectorIndex.__new__(PostgresVectorIndex)
    index.store = SimpleNamespace(
        _execute=lambda *a: SimpleNamespace(fetchall=lambda: next(results))
    )
    monkeypatch.setattr(
        "agent_market.application_store_resource_batches.resources",
        lambda *a, **kw: [resource],
    )
    assert index._current_batch([1], descriptor) == ({1} if field is None else set())


def test_hybrid_cards_paginate_without_writes_or_unsafe_urls(catalog, monkeypatch):
    from agent_market.concierge.hybrid_explore import explore

    store, _, _, add, _ = catalog
    ids = [add("Forecast " + str(n)) for n in range(100)]
    found = [dict(store.resource(rid)) for rid in ids]
    found.insert(0, {**found[0], "id": 999999, "url": "http://[invalid"})
    found.insert(0, {**found[1], "id": 999998, "url": "http://127.0.0.1/private"})
    monkeypatch.setattr(
        "agent_market.concierge.hybrid_explore.candidates", lambda *a, **k: found
    )
    before = store.query("SELECT COUNT(*) FROM connection_versions")[0][0]
    previous = []
    for limit, count in [(45, 45), (90, 90), (300, 100)]:
        result = explore(
            store, None, "weather forecast", None, None, False, False, limit
        )
        current = [item["id"] for item in result["items"]]
        assert len(current) == count and current[: len(previous)] == previous
        assert len(set(current)) == count and set(current) <= set(ids)
        assert result["total_is_estimate"] is True
        assert all(
            not i["connection_readiness"]["verified_callable"] for i in result["items"]
        )
        previous = current
    assert store.query("SELECT COUNT(*) FROM connection_versions")[0][0] == before


def test_exact_agent_name_is_a_lookup_not_an_inferred_capability(catalog, monkeypatch):
    from agent_market.concierge.hybrid_explore import explore

    store, _, _, add, _ = catalog
    rid = add(
        "Unique Observatory", description="Weather forecasts and temperature data."
    )
    monkeypatch.setattr(
        "agent_market.concierge.hybrid_explore.candidates",
        lambda *a, **k: [dict(store.resource(rid))],
    )
    result = explore(store, None, "Unique Observatory", None, None, False, False, 45)
    assert [item["id"] for item in result["items"]] == [rid]


def test_exact_name_leads_small_windows_too(catalog, monkeypatch):
    # Production: "Research Papers" was first with limit=45 but missing with limit=5.
    from agent_market.concierge.hybrid_explore import explore

    store, _, _, add, _ = catalog
    others = [add("Paper Search " + str(n), description="Search research papers.") for n in range(12)]
    rid = add("Research Papers", description="Find research papers.")
    found = [dict(store.resource(i)) for i in others + [rid]]
    monkeypatch.setattr("agent_market.concierge.hybrid_explore.candidates", lambda *a, **k: found)
    for limit in (3, 6, 46):
        result = explore(store, None, "Research Papers", None, None, False, False, limit)
        assert result["items"][0]["id"] == rid
