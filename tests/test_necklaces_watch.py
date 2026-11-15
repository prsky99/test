import json
import time

from agent_market.necklaces import judge, model, watch
from tests.test_necklaces_model import base, ext, own

NOW = 1_800_000_000.0


def tools(name="search_items", **ann):
    annotations = {"readOnlyHint": True, "destructiveHint": False}
    annotations.update(ann)
    return json.dumps([{"name": name, "annotations": annotations}])


def row(health="healthy", active=1, probed_at=NOW, **ann):
    """A catalogue row probed now (the watch takes a probe older than 24 hours as unknown health, PM 13:0x)."""
    return {"active": active, "health_status": health, "probed_at": probed_at, "usage_full_tools": tools(**ann)}


def trial():
    defn = base()
    defn["status"] = "trial"
    return defn


def fresh(prints=None, ids=range(1, 21), at=NOW):
    """A fingerprint file as ops writes it (resources[rid], measured now) with every member unchanged; entries in
    PRINTS override. The watch is closed: a member missing from the file holds the necklace (PM 12:0x, 11-15)."""
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(at))
    resources = {str(i): {"baseline": "a", "current": "a", "measured_at": stamp} for i in ids}
    for rid, entry in ((prints or {}).get("resources") or {}).items():
        resources[rid] = dict(resources.get(rid, {"measured_at": stamp}), **entry)
    return {"resources": resources}


def run(defn, rows, prints=None, state=None, hours=1):
    state = {} if state is None else state
    for h in range(hours):
        watch.observe([defn], lambda rid: rows.get(rid), fresh(prints), state, NOW + h * 3600)
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
    assert [(r["resource_id"], r["reason"]) for r in state["retest_requests"]] == [(1, "fingerprint_changed")]
    run(defn, rows, prints={"resources": {"1": {"baseline": "a", "current": "b"}}}, state=state)
    assert len(state["retest_requests"]) == 1


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
    both = {(1, "x.v1"), (3, "y.v1")}
    held = judge.build_entry(defn, approval, summary, time.time(), state, verified=both)
    assert held["status"] == "held" and held["held_reason"] == "security"
    again = dict(approval, at="2026-11-20T06:00:00Z")
    assert judge.build_entry(defn, again, summary, time.time(), state, verified=both)["status"] == "live"


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
    prints = tmp_path / "pearls.json"
    prints.write_text(json.dumps(fresh(at=clock())))
    task = watch.NecklaceWatch(FakeStore(healthy_rows()), root=tmp_path, fingerprints=prints,
                               definitions_dir=defs, clock=clock)
    assert task.due()
    result = task.run()
    assert result == {"members": 6, "holds": []}
    assert not task.due()
    assert (tmp_path / "watch" / "state.json").exists()
    assert len((tmp_path / "watch" / "20261120.jsonl").read_text().splitlines()) == 6


def test_failing_fallback_is_demoted_after_two_hours_and_restored_after_six():
    defn = trial()
    slot = defn["slots"][0]
    slot["chain"] = [ext(1, "a.com"), ext(2, "b.com"),
                     dict(own(None, agent_id="fb1"), resource_id=None, tool="t1"),
                     dict(own(None, agent_id="fb2"), resource_id=None, tool="t2")]
    status = {"fb1": "failing", "fb2": "healthy"}
    spec = lambda agent_id: {"name": {"fb1": "t1", "fb2": "t2"}[agent_id],
                             "annotations": {"readOnlyHint": True, "destructiveHint": False}}
    state, rows = {}, healthy_rows()

    def hour(h):
        watch.observe([defn], lambda rid: rows.get(rid), fresh(), state, NOW + h * 3600,
                      fallback_spec=spec, fallback_health=lambda a: status[a])
    hour(0)
    order = lambda: [m.get("agent_id") for m in watch.runtime_chain(slot, "topic-brief", state) if m["kind"] == "agentcon"]
    assert order() == ["fb1", "fb2"]
    hour(1)
    assert order() == ["fb2", "fb1"]
    status["fb1"] = "unknown"
    for h in range(2, 8):
        hour(h)
    assert order() == ["fb2", "fb1"]          # unknown is neither failing nor good
    status["fb1"] = "healthy"
    for h in range(8, 14):
        hour(h)
    assert order() == ["fb1", "fb2"]


def test_a_new_problem_after_a_re_approval_holds_again(tmp_path):
    """PM R20 reproduction: hold (1000) -> re-approval (2000) -> new security problem (3000) must hold."""
    defn = trial()
    defn["status"] = "live"
    iso = lambda t: judge._iso(NOW + t)
    state, rows = {}, healthy_rows()
    rows[2] = row(readOnlyHint=False)
    watch.observe([defn], lambda rid: rows.get(rid), fresh(), state, NOW + 1000)
    approval = {"slug": "topic-brief", "version": 1, "definition_digest": model.digest(defn), "state": "approved",
                "at": iso(2000)}
    rows[2] = row()
    rows[4] = row(destructiveHint=True)
    watch.observe([defn], lambda rid: rows.get(rid), fresh(), state, NOW + 3000, approvals={"topic-brief": approval})
    hold = state["holds"]["topic-brief"]
    assert hold["since"] == iso(3000) and not hold.get("released")
    assert [e["since"] for e in hold["events"]] == [iso(1000), iso(3000)]
    assert hold["events"][0]["released_by"] == "approval " + iso(2000)
    assert judge.watch_hold("topic-brief", state, approval) == "security"


def test_a_second_problem_on_an_open_hold_moves_since_forward():
    defn = trial()
    state, rows = {}, healthy_rows()
    rows[2] = row(readOnlyHint=False)
    watch.observe([defn], lambda rid: rows.get(rid), fresh(), state, NOW)
    watch.observe([defn], lambda rid: rows.get(rid), fresh(), state, NOW + 3600)
    assert len(state["holds"]["topic-brief"]["events"]) == 1          # the same problem is one event
    rows[4] = row(destructiveHint=True)
    watch.observe([defn], lambda rid: rows.get(rid), fresh(), state, NOW + 7200)
    hold = state["holds"]["topic-brief"]
    assert len(hold["events"]) == 2 and hold["since"] == judge._iso(NOW + 7200)
    approval_between = {"state": "approved", "at": judge._iso(NOW + 3600)}
    assert judge.watch_hold("topic-brief", state, approval_between) == "security"


def test_ops_approved_substitutes_join_the_runtime_chain(tmp_path):
    """approvals.json "substitutes" (deploy/NECKLACE_GATE.md 10): a planned AgentValCon fallback runs only once ops
    approved it for the slot's role; the latest entry per agent and role wins."""
    approvals = tmp_path / "approvals.json"
    approvals.write_text(json.dumps({"approvals": [], "substitutes": [
        {"agent_id": "fb1", "slot_role": "x.v1", "state": "approved", "at": "2026-11-15T08:00:00+0900"},
        {"agent_id": "fb2", "slot_role": "x.v1", "state": "approved", "at": "2026-11-15T08:00:00+0900"},
        {"agent_id": "fb2", "slot_role": "x.v1", "state": "revoked", "at": "2026-11-15T09:00:00+0900"},
        {"agent_id": "fb3", "slot_role": "other.v1", "state": "approved", "at": "2026-11-15T08:00:00+0900"}]}))
    assert judge.load_substitutes(approvals) == [["fb1", "x.v1"], ["fb3", "other.v1"]]
    defn = trial()
    slot = defn["slots"][0]
    slot["chain"] = [ext(1, "a.com"), ext(2, "b.com"),
                     dict(own(None, agent_id="fb1"), resource_id=None, tool="t1", state="planned"),
                     dict(own(None, agent_id="fb2"), resource_id=None, tool="t2", state="planned")]
    state = {"substitutes": judge.load_substitutes(approvals)}
    chain = watch.runtime_chain(slot, "topic-brief", state)
    assert [m.get("agent_id") or m["resource_id"] for m in chain] == [1, 2, "fb1"]
    assert chain[-1]["state"] == "active" and chain[-1]["substitute_approved"] is True
    assert [m.get("agent_id") or m["resource_id"] for m in watch.runtime_chain(slot, "topic-brief", {})] == [1, 2]
    alternates = judge.pearls(watch.runtime_definition(defn, state))[0]["alternates"]
    assert [a.get("agent_id") for a in alternates if a["kind"] == "agentcon"] == ["fb1"]
    assert slot["chain"][2]["state"] == "planned"                      # the definition itself is unchanged


def test_fingerprint_verdict_is_closed():
    """PM 12:0x (11-15): the watch read resources[rid] while the file held pearls[rid], so every member read 'same'."""
    at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW))
    old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - 25 * 3600))
    same = {"baseline": "a", "current": "a", "measured_at": at}
    assert watch.fingerprint_status({"resources": {"1": same}}, 1, NOW) == "same"
    assert watch.fingerprint_status({"resources": {"1": same}}, 2, NOW) == "unknown"
    assert watch.fingerprint_status({"pearls": {"1": {"server_fp": "x", "tools": {}}}}, 1, NOW) == "unknown"
    assert watch.fingerprint_status({}, 1, NOW) == "unknown"
    assert watch.fingerprint_status({"resources": {"1": dict(same, measured_at=old)}}, 1, NOW) == "stale"
    assert watch.fingerprint_status({"resources": {"1": {"baseline": "a", "current": "a"}}}, 1, NOW) == "stale"
    assert watch.fingerprint_status({"generated": at, "resources": {"1": {"baseline": "a", "current": "a"}}}, 1, NOW) == "same"
    assert watch.fingerprint_status({"resources": {"1": dict(same, measured_at=old, risk=["x"])}}, 1, NOW) == "risk"
    assert watch.fingerprint_status({"resources": {"1": dict(same, current="b")}}, 1, NOW) == "changed"


def test_unknown_or_stale_fingerprint_holds_the_necklace_but_keeps_the_member():
    defn, rows = trial(), healthy_rows()
    state = {}
    watch.observe([defn], lambda rid: rows.get(rid), {"pearls": {}}, state, NOW)
    assert state["holds"]["topic-brief"]["reason"] == "fingerprint_unverified"
    assert not any(m.get("excluded") for m in state["members"].values())
    state = {}
    stale = fresh(at=NOW - 30 * 3600)
    watch.observe([defn], lambda rid: rows.get(rid), stale, state, NOW)
    assert "stale" in state["holds"]["topic-brief"]["detail"]


def test_a_member_gone_from_the_catalogue_leaves_and_stale_health_holds():
    """PM 13:0x (11-15): a missing row is excluded at once (no tools to check); a called member of a required slot
    without a health probe in 24 hours holds the necklace."""
    defn, rows = trial(), healthy_rows()
    called = lead(defn, {})
    gone = {rid: r for rid, r in rows.items() if rid != called}
    state = run(defn, gone)
    key = next(k for k in state["members"] if k.endswith(f"|{called}|search_items"))
    assert state["members"][key]["excluded"] is True
    assert called not in [m["resource_id"] for m in watch.runtime_chain(defn["slots"][0], "topic-brief", state)]
    stale = {**rows, called: row(probed_at=NOW - 25 * 3600)}
    state = run(defn, stale)
    assert state["holds"]["topic-brief"]["reason"] == "health_unknown"
    assert watch.health_state(None, NOW) == "missing" and watch.health_state(row(), NOW) == "healthy"
    assert watch.health_state(row(probed_at=None), NOW) == "unknown"
