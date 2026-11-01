"""Reject inconsistent signed source evidence before sharing it downstream."""
from datetime import datetime, timezone
import json

import pytest

from tests.test_workflow_typed_flow import typed_routing, saved_typed
from tests.test_workflow_fallback import routing
from tests.test_workflow_runtime import wait
from agent_market.workflows import WorkflowError


def restamp(value, seconds):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() + seconds
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat().replace("+00:00", "Z")


@pytest.mark.parametrize("change", [
    "negative_latency", "boolean_latency", "future_observation",
    "wrong_run", "wrong_source_input", "different_flow_output",
])
def test_inconsistent_signed_source_checkpoint_does_not_reach_documentation_agent(
        typed_routing, monkeypatch, change):
    rt, _, _, calls, *_ = typed_routing
    workflow = saved_typed(rt)
    original = rt.composer.resolve_input

    def alter(node, row, snapshot):
        checkpoint = rt.store.query(
            "SELECT payload FROM workflow_checkpoints WHERE run_id=? AND node_id='search-1'",
            (row["id"],),
        )[0]
        value = json.loads(checkpoint["payload"])
        record = value["record"]
        if change == "negative_latency":
            observed = record["started"] + record["latency_ms"] / 1000
            record["started"] = observed + 1
            record["latency_ms"] = -1000
        elif change == "boolean_latency":
            record["latency_ms"] = True
        elif change == "future_observation":
            record["started"] += 3600
            # Keep schema/time rules internally consistent to isolate the
            # missing upper bound on the signed observation time itself.
            for output in (record["data"], value["flow_output"]):
                for item in output["structuredContent"]["items"]:
                    item["retrieved_at"] = restamp(item["retrieved_at"], 3600)
                    if item["published_at"] is not None:
                        item["published_at"] = restamp(item["published_at"], 3600)
        elif change == "wrong_run":
            value["run_id"] = "wr_" + "0" * 32
        elif change == "wrong_source_input":
            record["input"]["query"] = "Unreviewed source objective"
        else:
            value["flow_output"]["structuredContent"]["items"][0]["title"] = "Different source title"
        with rt.store.tx() as db:
            db.execute(
                "UPDATE workflow_checkpoints SET payload=?,signature=? WHERE run_id=? AND node_id='search-1'",
                (json.dumps(value), rt.authority.signature(value), row["id"]),
            )
        return original(node, row, snapshot)

    monkeypatch.setattr(rt.composer, "resolve_input", alter)
    result = wait(rt, rt.submit(workflow))
    assert result["status"] == "failed", result
    assert calls == ["primary.example"]
    assert not rt.store.query(
        "SELECT 1 FROM workflow_execution_attempts WHERE run_id=? AND node_id='search-2'",
        (result["run_id"],),
    )


@pytest.mark.parametrize("role", ["operator", "admin"])
def test_connected_execution_rejects_lower_administrator_roles_before_queueing(typed_routing, role):
    rt, _, _, calls, *_ = typed_routing
    workflow = saved_typed(rt)
    principal = rt.principal("admin", "internal", workflow["id"], role=role)
    with pytest.raises(WorkflowError, match="highest-administrator"):
        rt.submit(workflow, principal=principal)
    assert not calls
    assert not rt.store.query("SELECT id FROM workflow_runs WHERE workflow_id=?", (workflow["id"],))


@pytest.mark.parametrize("change", ["downgrade", "deactivate"])
def test_queued_connected_execution_rechecks_real_admin_account(typed_routing, monkeypatch, change):
    rt, _, _, calls, *_ = typed_routing
    workflow = saved_typed(rt)
    principal = rt.principal("admin", "1", workflow["id"], role="superadmin")
    launch = rt.launch
    monkeypatch.setattr(rt, "launch", lambda _: None)
    job = rt.submit(workflow, principal=principal)
    with rt.store.tx() as db:
        if change == "downgrade":
            db.execute("UPDATE admin_users SET role='operator' WHERE id=1")
        else:
            db.execute("UPDATE admin_users SET active=0 WHERE id=1")
    monkeypatch.setattr(rt, "launch", launch)
    rt.launch(job["run_id"])
    result = wait(rt, job)
    assert result["status"] == "failed"
    assert not calls


def test_source_unknown_blocks_target_and_cannot_be_replayed_automatically(typed_routing):
    rt, _, _, calls, modes, *_ = typed_routing
    workflow = saved_typed(rt)
    modes["primary.example"] = "unknown"
    job = rt.submit(workflow, idempotency="typed-unknown-once")
    result = wait(rt, job)
    assert result["status"] == "failed"
    assert result["execution_outcome"] == "unknown"
    assert calls == ["primary.example"]
    assert not rt.store.query(
        "SELECT 1 FROM workflow_execution_attempts WHERE run_id=? AND node_id='search-2'",
        (job["run_id"],),
    )
    replay = rt.submit(workflow, idempotency="typed-unknown-once")
    assert replay["replayed"] is True and replay["run_id"] == job["run_id"]
    for _ in range(3):
        rt.run_due()
        rt.launch(job["run_id"])
    future = rt.futures.get(job["run_id"])
    if future:
        future.result(timeout=5)
    assert calls == ["primary.example"]
