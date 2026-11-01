"""Historical authority expiry is checked at execution, never at inspection time."""
import json

import pytest

from tests.test_workflow_fallback import routing
from tests.test_workflow_typed_flow import typed_routing, saved_typed
from tests.test_workflow_runtime import wait


@pytest.mark.parametrize("expiry", ["before_admission", "before_target", "boolean", "string", "missing"])
def test_resolved_inspection_requires_authority_that_was_valid_at_recorded_execution(typed_routing, expiry):
    from agent_market.workflow_comparison import ComparisonError
    from agent_market.workflow_resolved_evidence import ResolvedEvidence
    rt, *_ = typed_routing
    workflow = saved_typed(rt)
    result = wait(rt, rt.submit(workflow))
    assert result["status"] == "succeeded"
    run_id = result["run_id"]
    with rt.store.tx() as db:
        value = json.loads(db.execute(
            "SELECT payload FROM workflow_run_authority WHERE run_id=?", (run_id,),
        ).fetchone()[0])
        principal = value["principal"]["payload"]
        if expiry == "missing":
            principal.pop("expires")
        elif expiry == "before_admission":
            principal["expires"] = 0
        elif expiry == "before_target":
            source = json.loads(db.execute(
                "SELECT payload FROM workflow_checkpoints WHERE run_id=? AND node_id='search-1'", (run_id,),
            ).fetchone()[0])["record"]
            target = json.loads(db.execute(
                "SELECT payload FROM workflow_checkpoints WHERE run_id=? AND node_id='search-2'", (run_id,),
            ).fetchone()[0])["record"]
            source_end = source["started"] + source["latency_ms"] / 1000
            principal["expires"] = (source_end + target["started"]) / 2
        else:
            principal["expires"] = True if expiry == "boolean" else "9999999999999"
        value["principal"]["signature"] = rt.authority.signature(principal)
        db.execute("UPDATE workflow_run_authority SET payload=?,signature=? WHERE run_id=?",
                   (json.dumps(value), rt.authority.signature(value), run_id))
    with pytest.raises(ComparisonError):
        ResolvedEvidence(rt).inspect({"run_id": run_id})
