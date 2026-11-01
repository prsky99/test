import json
from unittest.mock import patch
import pytest

from agent_market import explore_documents as doc
from agent_market.concierge.discovery import normalize_task
from agent_market.concierge.explore_search import task_advertised
from agent_market.concierge.selection import search_terms, capability_terms
from tests.explore_a1_cases import CASES, listing


def projected(row):
    value = {key: item for key, item in row.items() if key != "usage_full_tools"}
    encoded = doc.build(row)
    document = json.loads(encoded)
    value["_explore_document"] = doc._Facts(
        tuple(value.get(key) for key in doc.BOUND_FIELDS),
        json.dumps(document["tools"]),
        doc.source_digest(row),
    )
    value["_tool_support"] = json.loads(encoded)["support"]
    value["_capability_text"] = json.loads(encoded)["text"]
    return value


def match(query, row):
    normalized = normalize_task(query)
    return task_advertised(
        query,
        row,
        terms=list(dict.fromkeys(search_terms(normalized) + search_terms(query))),
        core=capability_terms(normalized),
    )


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["case_id"])
def test_fixed_task_judgments_and_projection_parity(case):
    row = listing(case["task"], large=True)
    small = projected(row)
    assert match(case["query"], row) is case["expected_match"]
    assert match(case["query"], small) is case["expected_match"]
    unrelated = listing((case["task"] + 3) % 10)
    assert match(case["query"], unrelated) is case["unrelated_expected_match"]
    assert (
        match(case["query"], projected(unrelated)) is case["unrelated_expected_match"]
    )


def test_metadata_is_not_a_callable_contract_and_isolated_from_mutation():
    from agent_market.concierge.execution_policy import tools_for

    row = projected(listing(0, large=True))
    assert "usage_full_tools" not in row
    assert tools_for(row) == []
    first = doc.tools_for_search(row)
    first[0]["description"] = "modified"
    assert doc.tools_for_search(row)[0]["description"] != "modified"
    assert len(doc.build(listing(0, large=True))) < 1500


@pytest.mark.parametrize(
    "field",
    (
        "id",
        "kind",
        "name",
        "usage_tools",
        "usage_full_hash",
        "usage_guide",
        "description",
    ),
)
def test_facts_cannot_be_rebound_to_a_changed_row(field):
    row = projected(listing(0))
    row[field] = 999 if field == "id" else "changed"
    assert doc.tools_for_search(row) is None


def test_untrusted_marker_is_not_used():
    row = listing(0)
    row["_explore_document"] = {"tools": [{"name": "invented"}]}
    assert doc.tools_for_search(row) is None


def test_corrupt_full_or_compact_contract_never_becomes_supported_metadata():
    for field in ("usage_full_hash", "usage_tools"):
        row = listing(0)
        row[field] = "invalid"
        value = json.loads(doc.build(row))
        assert not value["tools"] and not value["support"]


def test_policy_facts_change_with_exact_source_and_handle_utf8():
    row = listing(0)
    before = doc.source_digest(row)
    assert (
        doc.source_digest({**row, "usage_full_tools": row["usage_full_tools"] + " "})
        != before
    )
    assert doc.source_digest({**row, "description": "\u00e9\U0001f30e"}) != before
    with pytest.raises(ValueError):
        doc.source_digest({**row, "usage_tools": []})


def test_private_marker_has_stable_task_fingerprint_without_hiding_live_fields():
    from agent_market.concierge.discovery_contracts import TaskFacts

    cache = TaskFacts()
    row = projected(listing(0))
    key = cache.fingerprint("weather", row, ["weather"], ["weather"])
    assert key == cache.fingerprint(
        "weather", projected(listing(0)), ["weather"], ["weather"]
    )
    for field in (
        "health_status",
        "auth_observed",
        "cap_languages",
        "_capability_text",
    ):
        assert key != cache.fingerprint(
            "weather", {**row, field: "changed"}, ["weather"], ["weather"]
        )
    assert b"weather" not in key


def test_supported_discovery_gate_still_runs_without_full_schema_parsing():
    row = projected(listing(0))
    with patch(
        "agent_market.concierge.execution_policy._tools_for_uncached",
        side_effect=AssertionError("full parse"),
    ):
        assert match("weather forecast seoul", row)
    # The fact does not turn an unsupported tool into an executable one.
    row["_tool_support"] = {"get_weather_forecast": False}
    assert not match("weather forecast seoul", row)
