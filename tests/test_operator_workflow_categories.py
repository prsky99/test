"""Every hub category needs enough real, independently reviewed operator recipes."""

# ruff: noqa: F401,F811 -- shared isolated fixtures
from collections import Counter
from agent_market.broker.server import RateLimiter
import pytest
from agent_market.gateway.store import Store
from agent_market.operator_workflow_categories import definitions, CATEGORY_NAMES
from agent_market.operator_workflow_templates import install, review, fingerprint
from agent_market.owned_data_agents.activation import install as activate
from agent_market.owned_data_agents.verification import isolated_world, wait, ORIGIN
from agent_market.workflow_templates import bind_resources
from tests.test_owned_data_agents import engine
from tests.test_operator_workflow_templates import proof_world


@pytest.fixture
def reviewed(tmp_path, engine, monkeypatch):
    core, _, _ = engine
    # Synthetic source fixtures test publication, not a wall-clock rate window.
    # Live-source qualification retains the normal service limit and is paced.
    monkeypatch.setattr(
        "agent_market.owned_data_agents.service.RateLimiter",
        lambda rate: RateLimiter(rate, window=0.01),
    )
    with isolated_world(tmp_path / "category-proof", engine=core) as world:
        for recipe in definitions(ORIGIN):
            recipe = bind_resources(world.store, recipe)
            wid = world.store.create_workflow(recipe)
            with world.store.tx() as db:
                db.execute(
                    "INSERT INTO workflow_seed_registry VALUES (?,?)",
                    (recipe["seed_key"], wid),
                )
            assert (
                wait(
                    world.runtime,
                    world.runtime.submit(
                        world.store.get_workflow(wid), source="verification"
                    ),
                )["status"]
                == "succeeded"
            )
        yield world


def test_categories_are_genuine_readonly_connected_recipes_with_unique_graphs():
    recipes = definitions()
    assert len(recipes) == 17 and len({fingerprint(r) for r in recipes}) == 17
    assert Counter(r["category"] for r in recipes) == Counter(
        {
            "travel_maps_weather": 3,
            "finance_crypto": 3,
            "automation": 3,
            "sports_health": 3,
            "business_productivity": 3,
            "docs_knowledge": 2,
        }
    )
    for r in recipes:
        assert r["category"] in CATEGORY_NAMES and r["is_template"] == 0
        assert 2 <= sum(n["type"] == "agent" for n in r["nodes"]) <= 4
        assert len(r["edges"]) == len(r["nodes"]) - 1
        assert all(
            n["kind"] == "mcp"
            and n["data"]["resource_ref"]["url"].startswith(
                "https://agentconcierge.biz/api/owned-data-agents/"
            )
            for n in r["nodes"][1:]
        )


def test_install_covers_every_category_without_replacing_existing_templates(
    reviewed, proof_world, tmp_path
):
    store = Store(str(tmp_path / "target.sqlite3"))
    activate(store, "https://agentconcierge.biz")
    try:
        install(store, proof_world.root / "isolated.sqlite3")
        before = {w["id"]: w for w in store.list_workflows(limit=1000)[0]}
        added = install(
            store,
            reviewed.root / "isolated.sqlite3",
            recipes=definitions,
            minimum_per_category={k: 3 for k in CATEGORY_NAMES},
        )
        assert len(added) == 17 and all(v["created"] for v in added)
        current = store.list_workflows(is_template=1, active_only=True, limit=1000)[0]
        assert (
            len(current) == 25
            and min(Counter(w["category"] for w in current).values()) >= 3
        )
        assert {wid: store.get_workflow(wid) for wid in before} == before
        again = install(
            store,
            reviewed.root / "isolated.sqlite3",
            recipes=definitions,
            minimum_per_category={k: 3 for k in CATEGORY_NAMES},
        )
        assert all(not v["created"] for v in again)
    finally:
        store._db.close()


def test_failed_category_proof_cannot_publish_a_partially_filled_hub(
    reviewed, proof_world, tmp_path
):
    r = definitions()[0]
    wid = reviewed.store.query(
        "SELECT workflow_id FROM workflow_seed_registry WHERE seed_key=?",
        (r["seed_key"],),
    )[0][0]
    with reviewed.store.tx() as db:
        db.execute(
            "UPDATE workflow_runs SET status='failed' WHERE workflow_id=?", (wid,)
        )
    assert r["seed_key"] not in review(
        reviewed.root / "isolated.sqlite3", recipes=definitions
    )
    store = Store(str(tmp_path / "failed.sqlite3"))
    activate(store, "https://agentconcierge.biz")
    try:
        install(store, proof_world.root / "isolated.sqlite3")
        before = store.list_workflows(limit=1000)[1]
        with pytest.raises(ValueError, match="minimum"):
            install(
                store,
                reviewed.root / "isolated.sqlite3",
                recipes=definitions,
                minimum_per_category={k: 3 for k in CATEGORY_NAMES},
            )
        assert store.list_workflows(limit=1000)[1] == before
    finally:
        store._db.close()
