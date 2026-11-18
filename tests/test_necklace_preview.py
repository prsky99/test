"""User 11-18 via PM 11:56: a necklace that has not passed its gate may go public as a preview with its measured
pass count. No gate time, no value claim, the same holds as a live necklace, lower run caps, no public event."""
import json

import pytest

from agent_market.necklaces import judge, limits, model, preview
from tests.test_necklaces_judge import BOTH, NOW, approval, summary


def preview_defn():
    from tests.test_necklaces_model import base
    defn = base()
    defn["status"] = "preview"
    return defn


def rows(defn, *rounds):
    return [{"slug": defn["slug"], "version": defn["version"], "definition_digest": model.digest(defn),
             "split": split, "passed": p, "total": t, "at": f"2026-11-18T{h}:00:00Z"} for split, p, t, h in rounds]


def build(defn, tmp_path, preview_rows, appr=None, watch_state=None):
    return judge.build_entry(defn, appr, judge.load_summary(tmp_path, defn["slug"]), NOW, watch_state,
                             verified=BOTH, preview_rows=preview_rows)


def test_preview_entry_shows_measured_rounds_and_never_a_gate_or_value(tmp_path):
    defn = preview_defn()
    summary(tmp_path, defn["slug"], value={"tokens": {"median": 10}})
    got = build(defn, tmp_path, rows(defn, ("holdout-r3", 26, 30, "08"), ("holdout-r4", 27, 30, "12")))
    assert got["status"] == "preview" and got["held_reason"] is None
    assert got["gate_passed_at"] is None and got["value"] is None and got["comparison"] is None
    assert got["preview"] == {"note": "Preview — test runs in progress", "gate_passed": False,
                              "tests": {"passed": 53, "total": 60},
                              "rounds": [{"split": "holdout-r3", "passed": 26, "total": 30, "at": "2026-11-18T08:00:00Z"},
                                         {"split": "holdout-r4", "passed": 27, "total": 30, "at": "2026-11-18T12:00:00Z"}]}
    # an ops approval does not turn a preview into a gate pass
    assert build(defn, tmp_path, rows(defn, ("holdout-r3", 26, 30, "08")), appr=approval(defn))["gate_passed_at"] is None


def test_preview_without_a_measured_round_shows_the_note_and_no_number(tmp_path):
    """PM 17:2x (11-18): the v2 rounds did not run; the preview goes out with its note only, no count, never 0."""
    defn = preview_defn()
    summary(tmp_path, defn["slug"])
    other = dict(defn, slots=defn["slots"][:1])
    for given in ([], rows(other, ("holdout-r3", 30, 30, "08")), rows(defn, ("holdout-r3", 31, 30, "08"))):
        got = build(defn, tmp_path, given)
        assert got["status"] == "preview" and got["held_reason"] is None
        assert got["preview"] == {"note": "Preview — test runs in progress", "gate_passed": False}
        assert got["gate_passed_at"] is None and got["value"] is None and got["comparison"] is None
        text = json.dumps(got["preview"])
        assert "tests" not in got["preview"] and "rounds" not in got["preview"] and not any(c.isdigit() for c in text)


def test_preview_keeps_the_live_holds(tmp_path):
    defn = preview_defn()
    measured = rows(defn, ("holdout-r3", 28, 30, "08"))
    summary(tmp_path, defn["slug"], quality={"delta_pp": 0, "cases_7d": 5, "tested_at": judge._iso(NOW - 49 * 3600)})
    assert build(defn, tmp_path, measured)["held_reason"] == "stale_retest"
    fresh = tmp_path / "fresh"
    summary(fresh, defn["slug"])
    watch = {"holds": {defn["slug"]: {"since": judge._iso(NOW - 60), "reason": "member_failing"}}}
    got = build(defn, fresh, measured, watch_state=watch)
    assert got["status"] == "held" and got["held_reason"] == "member_failing"
    assert got["preview"]["tests"] == {"passed": 28, "total": 30}


def test_snapshot_reads_the_record_and_makes_no_event_or_gate_time(tmp_path):
    defn = preview_defn()
    summary(tmp_path, defn["slug"])
    preview.record(tmp_path, defn, "holdout-r3", 26, 30, "workflow", now=NOW)
    preview.record(tmp_path, defn, "holdout-r3", 27, 30, "workflow", now=NOW)   # the same split is replaced
    state = {"gate_passed": {defn["slug"]: "2026-11-01T00:00:00Z"}}
    snap = judge.snapshot([defn], {}, tmp_path, NOW, watch_state={"updated": judge._iso(NOW), "holds": {}},
                          judge_state=state, verified=BOTH)
    entry = snap["necklaces"][0]
    assert entry["status"] == "preview" and entry["gate_passed_at"] is None
    assert entry["preview"]["tests"] == {"passed": 27, "total": 30}
    assert snap["events"] == []
    assert json.loads((tmp_path / "preview.json").read_text())["rounds"][0]["by"] == "workflow"


def test_record_refuses_counts_that_do_not_add_up(tmp_path):
    with pytest.raises(ValueError):
        preview.record(tmp_path, preview_defn(), "holdout-r3", 31, 30, "workflow")
    assert not (tmp_path / "preview.json").exists()


def test_preview_status_is_a_valid_definition_status():
    assert "preview" in model.STATUSES and "preview" in judge.PUBLIC


def test_preview_runs_have_a_day_cap_and_a_lower_client_cap(monkeypatch):
    t = [1000.0]
    lim = limits.RunLimiter(clock=lambda: t[0], per_client=100, per_necklace=100, total=100)
    monkeypatch.setattr(limits, "PREVIEW_PER_DAY", 4)
    for _ in range(3):
        lim.admit("wt", "1.1.1.1", preview=True)
    with pytest.raises(limits.Refused):
        lim.admit("wt", "1.1.1.1", preview=True)                 # 3 a minute per client
    lim.admit("wt", "2.2.2.2", preview=True)
    t[0] += 120
    with pytest.raises(limits.Refused) as refused:
        lim.admit("wt", "3.3.3.3", preview=True)                 # 4 a day for the necklace
    assert refused.value.retry_after > 80000
    lim.admit("wt", "3.3.3.3")                                   # the live path keeps its own limits
    t[0] += 86400
    lim.admit("wt", "3.3.3.3", preview=True)


def test_a_preview_needs_no_delta_and_no_retest_before_its_first_one(tmp_path):
    """PM 17:2x: no rounds ran, so no retest summary and no singles delta; the preview still shows. A stale retest
    or the retest's own hold still holds it."""
    defn = preview_defn()
    got = judge.build_entry(defn, None, {}, NOW, None, verified=BOTH, preview_rows=[])
    assert got["status"] == "preview" and got["held_reason"] is None
    summary(tmp_path, defn["slug"], quality={"delta_pp": None, "cases_7d": 5, "tested_at": judge._iso(NOW - 3600)})
    assert build(defn, tmp_path, [])["held_reason"] is None                       # no delta needed
    old = tmp_path / "old"
    summary(old, defn["slug"], quality={"delta_pp": None, "cases_7d": 5, "tested_at": judge._iso(NOW - 49 * 3600)})
    assert build(defn, old, [])["held_reason"] == "stale_retest"
    bad = tmp_path / "bad"
    summary(bad, defn["slug"], held_reason="quality_low", quality={"cases_7d": 5, "tested_at": judge._iso(NOW - 60)})
    assert build(defn, bad, [])["held_reason"] == "quality_low"
    live = dict(defn, status="live")                                               # live keeps its delta rule
    assert judge.build_entry(live, None, {}, NOW, None, verified=BOTH)["status"] == "held"
