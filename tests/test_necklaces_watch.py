import json
import time

from agent_market.necklaces import judge, model, watch
from tests.test_necklaces_model import base

NOW = 1_800_000_000.0


def tools(name="search_items", **ann):
    annotations = {"readOnlyHint": True, "destructiveHint": False}
    annotations.update(ann)
    return json.dumps([{"name": name, "annotations": annotations}])


def row(health="healthy", active=1, **ann):
    return {"active": active, "health_status": health, "usage_full_tools": tools(**ann)}


def trial():
    defn = base()
    defn["status"] = "trial"
    return defn


def run(defn, rows, prints=None, state=None, hours=1):
    state = {} if state is None else state
    for h in range(hours):
        watch.observe([defn], lambda rid: rows.get(rid), prints or {}, state, NOW + h * 3600)
    return state


def lead(defn, state, slot=0):
    chain = watch.runtime_chain(defn["slots"][slot], defn["slug"], state)
    return chain[0]["resource_id"]


def healthy_rows():
    return {rid: row() for rid in (1, 2, 3, 4, 10, 11)}


def test_lead_is_demoted_after_two_bad_hours_and_restored_after_six_good():
    defn, rows = trial(), healthy_rows()
    rows[1] = row(health="failing")
    state = run(defn, rows, hours=1)
    assert lead(defn, state) == 1
    run(defn, rows, state=state, hours=1)
    assert lead(defn, state) == 2
    rows[1] = row()
    run(defn, rows, state=state, hours=5)
    assert lead(defn, state) == 2
    run(defn, rows, state=state, hours=1)
    assert lead(defn, state) == 1
    assert "holds" not in state or not state["holds"]


def test_runtime_reordering_keeps_the_definition_digest():
    defn, rows = trial(), healthy_rows()
    before = model.digest(defn)
    rows[1] = row(health="failing")
    state = run(defn, rows, hours=2)
    assert model.digest(defn) == before
    assert [m["resource_id"] for m in watch.runtime_definition(defn, state)["slots"][0]["chain"]] == [2, 1, 10]


def test_lost_read_only_hint_holds_at_once():
    defn, rows = trial(), healthy_rows()
    rows[2] = row(readOnlyHint=False)
    state = run(defn, rows)
    assert state["holds"]["topic-brief"]["reason"] == "security"
    assert all(m["resource_id"] != 2 for m in watch.runtime_chain(defn["slots"][0], "topic-brief", state))


def test_fingerprint_change_on_called_member_holds_on_standby_only_excludes():
    defn, rows = trial(), healthy_rows()
    state = run(defn, rows, prints={"resources": {"2": {"baseline": "a", "current": "b"}}})
    assert "topic-brief" not in state.get("holds", {})
    assert [m["resource_id"] for m in watch.runtime_chain(defn["slots"][0], "topic-brief", state)] == [1, 10]
    state = run(defn, rows, prints={"resources": {"1": {"baseline": "a", "current": "b"}}})
    assert state["holds"]["topic-brief"]["reason"] == "fingerprint_changed"


def test_dynamic_description_and_risk_signal():
    defn, rows = trial(), healthy_rows()
    state = run(defn, rows, prints={"resources": {"1": {"baseline": "a", "current": "b", "classification": "dynamic"}}})
    assert not state.get("holds")
    state = run(defn, rows, prints={"resources": {"4": {"baseline": "a", "current": "a", "risk": ["injection"]}}})
    assert state["holds"]["topic-brief"]["reason"] == "security"


def test_alert_when_a_required_slot_drops_below_two_externals_once_a_day():
    defn, rows = trial(), healthy_rows()
    rows[3] = row(active=0)
    state = run(defn, rows, hours=3)
    alerts = [a for a in state["alerts"] if a["slot"] == "news"]
    assert len(alerts) == 1 and alerts[0]["count"] == 1


def test_watch_hold_is_released_only_by_a_later_approval():
    defn = trial()
    defn["status"] = "live"
    state = {"holds": {"topic-brief": {"reason": "security", "since": "2026-11-20T05:00:00Z"}}}
    approval = {"slug": "topic-brief", "version": 1, "definition_digest": model.digest(defn),
                "state": "approved", "at": "2026-11-20T03:00:00Z"}
    summary = {"quality": {"delta_pp": 5, "tested_at": judge._iso(time.time() - 60)}}
    held = judge.build_entry(defn, approval, summary, time.time(), state)
    assert held["status"] == "held" and held["held_reason"] == "security"
    again = dict(approval, at="2026-11-20T06:00:00Z")
    assert judge.build_entry(defn, again, summary, time.time(), state)["status"] == "live"


def test_quiet_windows():
    def at(h, m):
        return time.mktime((2026, 11, 20, h, m, 0, 0, 0, -1))
    assert watch.in_quiet_window(at(10, 57)) and watch.in_quiet_window(at(11, 5))
    assert watch.in_quiet_window(at(4, 30))
    assert not watch.in_quiet_window(at(10, 20)) and not watch.in_quiet_window(at(5, 20))


class FakeStore:
    def __init__(self, rows):
        self.rows = rows

    def resource(self, rid):
        return self.rows.get(rid)


def test_task_writes_state_and_daily_lines(tmp_path):
    defs = tmp_path / "defs"
    defs.mkdir()
    defn = trial()
    for slot in defn["slots"]:
        slot["contract"] = "package.advisories.v1"
    (defs / "topic-brief.json").write_text(json.dumps(defn))
    clock = lambda: time.mktime((2026, 11, 20, 10, 25, 0, 0, 0, -1))
    task = watch.NecklaceWatch(FakeStore(healthy_rows()), root=tmp_path, fingerprints=tmp_path / "none.json",
                               definitions_dir=defs, clock=clock)
    assert task.due()
    result = task.run()
    assert result == {"members": 6, "holds": []}
    assert not task.due()
    assert (tmp_path / "watch" / "state.json").exists()
    assert len((tmp_path / "watch" / "20261120.jsonl").read_text().splitlines()) == 6
