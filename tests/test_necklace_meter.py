"""scripts.necklace_meter: 30-day outside successes per necklace from run events (PM 11-16 21:13)."""
import json

from scripts import necklace_meter


def day(root, name, events):
    (root / "runs").mkdir(parents=True, exist_ok=True)
    (root / "runs" / f"{name}.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))


def test_sums_outside_successes_in_the_window_and_leaves_callers_open(tmp_path):
    ok = lambda rid, slug="topic": {"run_id": rid, "slug": slug, "source": "external", "outcome": "succeeded"}
    day(tmp_path, "20270101", [ok("a"), ok("a"), ok("b"), {"run_id": "c", "slug": "topic", "source": "external",
                                                            "outcome": "failed"}])
    day(tmp_path, "20270102", [ok("d"), {"run_id": "e", "slug": "topic", "source": "internal", "outcome": "succeeded"},
                               {"run_id": "f", "slug": "topic", "source": "external", "outcome": "succeeded",
                                "cached": True}])
    day(tmp_path, "20261201", [ok("old")])                                       # outside the 30-day window
    out = necklace_meter.meter(tmp_path, "20270102", 30)
    topic = out["necklaces"]["topic"]
    assert topic["succeeded"] == 3 and topic["external_runs"] == 4 and topic["days_with_success"] == 2
    assert topic["success_bar_met"] is False and topic["callers"] is None and out["window"] == ["20261204", "20270102"]
