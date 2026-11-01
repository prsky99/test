"""Only exact successful read-only operator recipes can be added to the hub."""
# ruff: noqa: F401,F811 -- shared disposable fixtures

import json
import time

import pytest

from agent_market.capability_registry import digest
from agent_market.gateway.store import Store
from agent_market.owned_data_agents.activation import install as install_owned
from agent_market.owned_data_agents.verification import isolated_world, wait, ORIGIN
from agent_market.operator_workflow_templates import (
    definitions,
    review,
    install,
    fingerprint,
)
from agent_market.workflow_templates import bind_resources
from tests.test_owned_data_agents import engine  # noqa: F401
from tests.test_owned_data_agents_activation import operating


@pytest.fixture
def proof_world(tmp_path, engine):
    core, _, _ = engine
    with isolated_world(tmp_path / "proof", engine=core) as world:
        for recipe in definitions(ORIGIN):
            recipe = bind_resources(world.store, recipe)
            wid = world.store.create_workflow(recipe)
            with world.store.tx() as db:
                db.execute(
                    "INSERT INTO workflow_seed_registry VALUES (?,?)",
                    (recipe["seed_key"], wid),
                )
            result = wait(
                world.runtime,
                world.runtime.submit(
                    world.store.get_workflow(wid), source="verification"
                ),
            )
            assert result["status"] == "succeeded", result
        yield world


def test_five_connected_readonly_recipes_have_successful_exact_proof(proof_world):
    approved = review(proof_world.root / "isolated.sqlite3")
    assert set(approved) == {r["seed_key"] for r in definitions()}
    for recipe in definitions():
        assert recipe["is_template"] == 0 and recipe["is_active"] == 1
        assert len(recipe["nodes"]) in (3, 4, 5)
        assert len(recipe["edges"]) == len(recipe["nodes"]) - 1
        assert "Operator-provided" in recipe["description"]
        assert "Operations" in recipe["author"]


@pytest.mark.parametrize(
    "mutation", ["graph", "schema", "failed", "expired", "pending"]
)
def test_tampered_failed_stale_or_incomplete_recipe_cannot_be_published(
    proof_world, mutation
):
    store = proof_world.store
    recipe = definitions()[0]
    wid = store.query(
        "SELECT workflow_id FROM workflow_seed_registry WHERE seed_key=?",
        (recipe["seed_key"],),
    )[0][0]
    run = store.query("SELECT * FROM workflow_runs WHERE workflow_id=?", (wid,))[0]
    with store.tx() as db:
        if mutation == "graph":
            snapshot = json.loads(run["snapshot"])
            snapshot["nodes"][1]["data"]["input"]["country_code"] = "CA"
            db.execute(
                "UPDATE workflow_runs SET snapshot=?,digest=? WHERE id=?",
                (json.dumps(snapshot), digest(snapshot), run["id"]),
            )
        elif mutation == "schema":
            db.execute("UPDATE resources SET usage_tools_hash='changed'")
        elif mutation == "failed":
            db.execute(
                "UPDATE workflow_node_runs SET status='failed' WHERE run_id=? AND node_id='gdp'",
                (run["id"],),
            )
        elif mutation == "pending":
            db.execute(
                "UPDATE workflow_runs SET status='running' WHERE id=?", (run["id"],)
            )
        else:
            db.execute(
                "UPDATE workflow_runs SET finished=? WHERE id=?",
                (time.time() - 86401, run["id"]),
            )
    assert recipe["seed_key"] not in review(proof_world.root / "isolated.sqlite3")


def test_additive_install_is_idempotent_and_does_not_touch_existing_work(
    proof_world, tmp_path
):
    store = Store(str(tmp_path / "target.sqlite3"))
    install_owned(store, "https://agentconcierge.biz")
    private = store.create_workflow(
        {"name": "Customer private work", "is_template": 0, "nodes": [], "edges": []}
    )
    existing = {w["id"]: w for w in store.list_workflows(limit=1000)[0]}
    try:
        first = install(store, proof_world.root / "isolated.sqlite3")
        assert len(first) == 5 and all(r["created"] for r in first)
        assert len(install(store, proof_world.root / "isolated.sqlite3")) == 5
        assert all(
            not r["created"]
            for r in install(store, proof_world.root / "isolated.sqlite3")
        )
        assert store.list_workflows(is_template=1, active_only=True)[1] == 8
        assert {wid: store.get_workflow(wid) for wid in existing} == existing
        assert store.get_workflow(private)["is_template"] == 0
        for row in first:
            w = store.get_workflow(row["id"])
            assert w["is_template"] == 1 and fingerprint(w) in {
                fingerprint(r) for r in definitions()
            }
            assert all(n.get("resource_id") for n in w["nodes"][1:])
    finally:
        store._db.close()


def test_missing_operating_binding_rolls_back_all_additions(proof_world, tmp_path):
    store = Store(str(tmp_path / "missing.sqlite3"))
    install_owned(store, "https://agentconcierge.biz")
    before = store.list_workflows(limit=1000)[1]
    with store.tx() as db:
        db.execute(
            "UPDATE resources SET active=0 WHERE key='agentconcierge-owned:package-advisories'"
        )
    try:
        with pytest.raises(ValueError, match="unavailable"):
            install(store, proof_world.root / "isolated.sqlite3")
        assert store.list_workflows(limit=1000)[1] == before
        assert not store.query(
            "SELECT workflow_id FROM workflow_seed_registry WHERE seed_key=?",
            (definitions()[0]["seed_key"],),
        )
    finally:
        store._db.close()


def test_public_catalog_run_download_and_scope_are_preserved(proof_world, operating):
    front, client, _, _, _ = operating
    added = install(front.store, proof_world.root / "isolated.sqlite3")
    templates = client.get("/api/workflows/templates").json()["templates"]
    assert len(templates) == 8
    selected = next(t for t in templates if t["id"] == added[0]["id"])
    assert selected["execution_availability"]["available"]
    assert "Operator-provided" in selected["description"]
    assert "operator_agent_id" not in json.dumps(selected)
    assert "resource_ref" not in json.dumps(selected)
    denied = client.post(
        "/api/workflows/run", json={"template_id": selected["id"], "nodes": []}
    )
    assert denied.status_code == 400
    started = client.post(
        "/api/workflows/run",
        json={
            "template_id": selected["id"],
            "definition_hash": selected["definition_hash"],
        },
    )
    assert started.status_code == 202
    result = wait(front.workflows, started.json())
    assert result["status"] == "succeeded" and result["executed_nodes"] == 5
    run_id = started.json()["run_id"]
    assert client.get("/api/workflows/runs/" + run_id).status_code == 404
    status = client.get(
        "/api/workflows/runs/" + run_id,
        headers={"X-Workflow-Key": started.json()["run_key"]},
    )
    assert status.status_code == 200 and status.json()["status"] == "succeeded"
    archive = client.get(f"/api/workflows/{selected['id']}/webapp")
    assert archive.status_code == 200 and archive.content.startswith(b"PK")
