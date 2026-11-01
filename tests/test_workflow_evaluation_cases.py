"""Curated input fixtures are machine checks, never expert quality evidence."""
import importlib
import json
from pathlib import Path

import pytest

from agent_market.workflow_composer import intent_spec


ARTIFACT = Path(__file__).resolve().parents[1] / "docs" / "workflow-evaluation-cases.json"
DATASET = json.loads(ARTIFACT.read_text(encoding="utf-8"))
CASES = DATASET["cases"]


def test_dataset_discloses_pending_expert_review_and_bounded_mapping():
    assert DATASET["dataset_id"] == "workflow-typed-flow-cases-v1"
    assert DATASET["schema_version"] == 1
    assert DATASET["review_status"] == "pending-human-review"
    assert DATASET["human_expert_reviewed"] is False
    assert DATASET["provider_quality_certified"] is False
    assert "not human expert reviewed" in DATASET["authoring_method"]
    assert DATASET["scope"] == {
        "source_contract": "news.search.v1",
        "source_path": ["items", 0, "title"],
        "target_contract": "docs.search.v1",
        "target_field": "query",
        "maximum_characters": 500,
        "implicit_coercion": False,
        "truncation": False,
        "external_requests": False,
    }
    assert len(DATASET["limitations"]) >= 4


def test_case_inventory_covers_public_concepts_attacks_and_exact_boundaries():
    assert len(CASES) == 30
    assert len({case["id"] for case in CASES}) == len(CASES)
    assert {case["category"] for case in CASES} == {
        "benign", "length-boundary", "control-character", "address",
        "sensitive", "template", "markup", "json-type",
    }
    assert sum(case["expected"]["title_accepted"] for case in CASES) == 10
    for case in CASES:
        assert set(case) == {
            "id", "category", "source_title", "expected", "rationale", "human_assessment",
        }
        assert case["human_assessment"] is None
        assert len(case["rationale"]) >= 20
        assert set(case["expected"]) == {"title_accepted", "intent_accepted"}
        assert all(type(value) is bool for value in case["expected"].values())
    by_id = {case["id"]: case for case in CASES}
    assert len(by_id["minimum-title"]["source_title"]) == 1
    assert len(by_id["maximum-title"]["source_title"]) == 500
    assert len(by_id["oversized-title"]["source_title"]) == 501


def test_human_rubric_is_unscored_and_requires_independent_evidence():
    review = DATASET["human_review"]
    assert review["status"] == "pending-human-review"
    assert "No scores" in review["scoring"]
    assert len(review["required_evidence"]) >= 3
    assert {row["id"] for row in review["rubric"]} == {
        "task-relevance", "source-fidelity", "temporal-fit",
        "missing-data-honesty", "typed-query-usefulness", "data-sharing-safety",
    }
    for row in review["rubric"]:
        assert set(row) == {"id", "question", "meets", "partial", "fails"}
        assert all(isinstance(value, str) and len(value) > 10 for value in row.values())


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_curated_objectives_follow_the_existing_public_intent_profile(case):
    body = {"intent": {
        "objective": case["source_title"],
        "contracts": ["news.search.v1", "docs.search.v1"],
    }}
    if not case["expected"]["intent_accepted"]:
        with pytest.raises(ValueError):
            intent_spec(body)
        return
    intent = intent_spec(body)
    assert intent["objective"] == case["source_title"]
    assert intent["contracts"] == ["news.search.v1", "docs.search.v1"]
    assert intent["language"] == "en"
    assert intent["data_class"] == "public"
    assert intent["execution"] == "manual"


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_curated_titles_follow_the_forwarding_profile_without_coercion(case):
    # Lazy import lets the artifact and existing IntentSpec checks collect while
    # the typed-flow implementation is developed independently.
    validate_title = importlib.import_module("agent_market.workflow_typed_flow").validate_title
    if not case["expected"]["title_accepted"]:
        with pytest.raises(ValueError):
            validate_title(case["source_title"])
        return
    assert validate_title(case["source_title"]) == case["source_title"]
