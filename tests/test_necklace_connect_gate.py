"""The necklace gate is a connection test (user decisions 11-18 via PM 19:2x): stage 1 joins the steps one by one,
runs the whole chain and checks every step's fallback; stage 2 runs the whole chain three times on different inputs.
A substitute is approved by three runs of its own. Fake runner only: no network, no answer set."""
import json
import time

import pytest

from agent_market.necklaces import connect_gate as cg, judge, model
from tests.test_necklaces_judge import BOTH, approval, summary
from tests.test_necklaces_model import base, ext, own

NOW = time.time()
SILENT = {"status": "silent", "source": "https://a.com/terms", "checked_at": "2026-11-18"}
STATES = {"owned|x.v1": "approved", "owned2|y.v1": "provisional", "own-z|z.v1": "approved"}
FRESH = {"updated": judge._iso(NOW), "holds": {}}
VERIFIED = {(1, "x.v1"), (3, "y.v1"), (5, "z.v1")}
INPUTS = [{"q": "a"}, {"q": "b"}, {"q": "c"}]


def defn3():
    """Three roles; every step has a representative pearl and an outside fallback, then our substitute."""
    defn = base()
    defn["slots"].append({"slot": "extra", "contract": "z.v1", "required": True, "fanout": 1,
                          "chain": [ext(5, "e.com"), ext(6, "f.com"), own("avc:z", agent_id="own-z")]})
    for slot in defn["slots"]:
        for m in slot["chain"]:
            if m["kind"] == "external":
                m["terms"] = dict(SILENT)
    return defn


class FakeRunner:
    """Each step is answered by its first member the run's state does not leave out and that is not broken."""
    broken, slow, seen, step_ms = set(), 0, [], {}

    def __init__(self, caller, watch_state=None):
        self.state = watch_state or {}

    def run(self, defn, values):
        from agent_market.necklaces.watch import member_key, runtime_chain
        FakeRunner.seen.append((len(defn["slots"]), values))
        slots, completed, failed = {}, True, None
        marks = self.state.get("members") or {}
        for slot in defn["slots"]:
            chain = [m for m in runtime_chain(slot, defn["slug"], self.state)
                     if not (marks.get(member_key(defn["slug"], slot["slot"], m)) or {}).get("excluded")]
            used = next((m for m in chain if (m.get("resource_id") if m["kind"] == "external" else m.get("agent_id"))
                         not in FakeRunner.broken), None)
            if used is None:
                slots[slot["slot"]] = {"failed": True, "kind": None, "status": "failed"}
                completed, failed = False, failed or slot["slot"]
            else:
                slots[slot["slot"]] = {"failed": False, "kind": used["kind"], "status": "answered"}
        attempts = {name: [{"kind": used["kind"], "ok": True, "ms": FakeRunner.step_ms.get(name, 300)}]
                    for name, used in slots.items() if not used["failed"]}
        return {"completed": completed, "failed_slot": failed, "latency_ms": FakeRunner.slow or 900, "slots": slots,
                "attempts": attempts, "output": {}}


def setup_function(_):
    FakeRunner.broken, FakeRunner.slow, FakeRunner.seen, FakeRunner.step_ms = set(), 0, [], {}


def run_gate(defn, inputs=INPUTS, **kw):
    args = dict(watch_state=FRESH, states=STATES, verified=VERIFIED, runner_cls=FakeRunner)
    args.update(kw)
    return cg.gate(defn, None, inputs, **args)


def failed(body):
    return [r["check"] for part in ("static", "stage1", "stage2") for r in body.get(part) or [] if not r["ok"]]


def test_a_chain_joined_step_by_step_with_fallbacks_then_three_runs_passes():
    got = run_gate(defn3())
    assert got["ok"] and failed(got) == []
    assert [r["check"] for r in got["stage1"]] == ["join:1:papers", "join:2:news", "join:3:extra", "whole",
                                                    "fallback:papers", "fallback:news", "fallback:extra"]
    assert [r["check"] for r in got["stage2"]] == ["connect:1", "connect:2", "connect:3"]
    assert [n for n, _ in FakeRunner.seen[:3]] == [1, 2, 3]                    # one more step each time
    assert [v for _, v in FakeRunner.seen[-3:]] == INPUTS                       # three different inputs


def test_a_failing_step_stops_the_joining_and_stage_two_does_not_run():
    FakeRunner.broken = {3, 4, "owned2"}                                       # the news step cannot answer
    got = run_gate(defn3())
    assert not got["ok"] and failed(got) == ["join:2:news"] and got["stage2"] == []
    assert [r["check"] for r in got["stage1"]] == ["join:1:papers", "join:2:news"]


def test_a_fallback_must_be_outside_unless_the_step_is_own_fallback():
    FakeRunner.broken = {2}                     # the papers fallback is down: our substitute answers instead
    assert failed(run_gate(defn3())) == ["fallback:papers"]
    defn = defn3()
    defn["slots"][0]["own_fallback"] = True     # no outside fallback exists in the market for this role
    defn["slots"][0]["chain"] = [m for m in defn["slots"][0]["chain"] if m.get("resource_id") != 2]
    got = run_gate(defn)
    assert got["ok"], failed(got)


@pytest.mark.real_terms          # a member whose terms were never read must stay unknown here (conftest C14)
def test_static_rules_name_what_is_missing():
    defn = defn3()
    defn["slots"][2]["chain"] = [ext(5, "e.com", terms=dict(SILENT)), own("avc:z", agent_id="own-z")]
    assert "members:extra" in failed(run_gate(defn))                          # no outside fallback
    assert "members:papers" in failed(run_gate(defn3(), verified={(3, "y.v1"), (5, "z.v1")}))   # no pearl
    own_steps = defn3()
    for slot in own_steps["slots"][:2]:
        slot["own_fallback"] = True
    got = run_gate(own_steps, verified={(5, "z.v1")})                          # one outside pearl step only
    assert "outside_pearls" in failed(got)
    bad_terms = defn3()
    bad_terms["slots"][1]["chain"][1]["terms"]["status"] = "prohibits"
    assert "members:news" in failed(run_gate(bad_terms))      # the runtime chain drops it: the step lost its fallback
    unknown = defn3()
    unknown["slots"][1]["chain"][1].pop("terms")     # terms never read: the runtime chain drops it too (C14)
    assert failed(run_gate(unknown)) == ["members:news"]
    held = run_gate(defn3(), watch_state={"updated": judge._iso(NOW), "holds": {
        "topic-brief": {"since": judge._iso(NOW - 60), "reason": "member_failing"}}})
    assert "watch" in failed(held)
    assert "inputs" in failed(run_gate(defn3(), inputs=INPUTS[:2]))
    FakeRunner.slow = 6000                                                    # over base()'s 5000 ms budget
    assert failed(run_gate(defn3())) == ["whole"]


def test_every_outside_member_needs_a_fingerprint_of_the_last_24_hours():
    """PM 20:03 (11-18): a member without a fresh ops reading is named, so ops measures it before the runs."""
    fresh = {"baseline": "h", "current": "h", "measured_at": judge._iso(NOW - 3600)}
    prints = {"resources": {str(r): dict(fresh) for r in (1, 2, 3, 4, 5, 6)}}
    assert failed(run_gate(defn3(), prints=prints, now=NOW)) == []
    calls = len(FakeRunner.seen)
    prints["resources"].pop("4")
    prints["resources"]["6"]["measured_at"] = judge._iso(NOW - 25 * 3600)
    got = run_gate(defn3(), prints=prints, now=NOW)
    assert failed(got) == ["fingerprints:news", "fingerprints:extra"] and got["stage1"] == []
    assert len(FakeRunner.seen) == calls and got["stage2"] == []          # a gate that cannot pass calls nobody
    why = [c["why"] for c in got["static"] if not c["ok"]]
    assert why == ["ask ops to measure before the runs: 4 unknown", "ask ops to measure before the runs: 6 stale"]
    prints["resources"]["6"].update(measured_at=judge._iso(NOW), current="other")
    assert [c["why"] for c in run_gate(defn3(), prints=prints, now=NOW)["static"] if c["check"] == "fingerprints:extra"] \
        == ["tool definitions changed, ops to review: 6 changed"]
    assert "fingerprints:papers" not in failed(run_gate(defn3()))            # no file passed: the old callers


def test_a_substitute_is_approved_by_three_runs_of_its_own():
    got = cg.substitute_gate(defn3(), "papers", "owned", None, INPUTS, watch_state=FRESH, runner_cls=FakeRunner)
    assert got["ok"] and got["kind"] == "substitute" and got["contract"] == "x.v1" and len(got["stage2"]) == 3
    FakeRunner.broken = {"owned"}
    bad = cg.substitute_gate(defn3(), "papers", "owned", None, INPUTS, watch_state=FRESH, runner_cls=FakeRunner)
    assert not bad["ok"] and all(not r["ok"] for r in bad["stage2"])


def test_a_substitute_not_yet_approved_is_called_by_its_own_gate_and_only_there():
    """PM 21:2x and the agent team (11-18): tls-certificate's three runs called nobody, because the running chain drops
    an unapproved (planned) substitute. The gate of that substitute counts it as approved for this run only."""
    import copy
    defn = defn3()
    for slot in defn["slots"]:
        for m in slot["chain"]:
            if m["kind"] == "agentcon":
                m["state"] = "planned"                     # none approved: FRESH has no substitutes
    watch = copy.deepcopy(FRESH)
    got = cg.substitute_gate(defn, "papers", "owned", None, INPUTS, watch_state=watch, runner_cls=FakeRunner)
    assert got["ok"] and [r["ok"] for r in got["stage2"]] == [True, True, True]
    assert watch == FRESH                                  # the watch state itself is not changed
    state = cg.with_candidate(defn, watch, "papers", "owned")
    assert state["substitutes"] == [["owned", "x.v1"]]     # other unapproved substitutes stay out
    FakeRunner.broken = {"owned"}                          # the candidate itself fails: the step has nobody else
    assert not cg.substitute_gate(defn, "papers", "owned", None, INPUTS, watch_state=watch, runner_cls=FakeRunner)["ok"]
    try:
        cg.with_candidate(defn, watch, "papers", "nobody")
    except ValueError:
        pass
    else:
        raise AssertionError("an agent that is not in the step is refused")


def test_a_substitute_is_judged_on_its_own_step_only():
    """User decision 11-18 and the agent team (21:2x): tls-certificate answered every run but failed on a flaky pearl
    elsewhere (registration) and the run's pearl count. Those are recorded, not held against the substitute; its own
    answer must come within the step budget (base(): 3500 ms)."""
    FakeRunner.broken = {1, 2, "owned"}                    # another step fails: the chain does not complete
    got = cg.substitute_gate(defn3(), "extra", "own-z", None, INPUTS, watch_state=FRESH, runner_cls=FakeRunner)
    assert got["ok"] and all(r["chain"] == "not completed (failed step papers)" for r in got["stage2"])
    FakeRunner.step_ms = {"extra": 4000}                   # the substitute itself is too slow
    slow = cg.substitute_gate(defn3(), "extra", "own-z", None, INPUTS, watch_state=FRESH, runner_cls=FakeRunner)
    assert not slow["ok"] and slow["stage2"][0]["why"].startswith("extra: 4000 ms over the step budget")
    FakeRunner.step_ms, FakeRunner.broken = {}, set()
    no_budget = defn3()
    no_budget.pop("budget_ms")                             # PM 21:28: no budget fails closed, never a TypeError
    got = cg.substitute_gate(no_budget, "extra", "own-z", None, INPUTS, watch_state=FRESH, runner_cls=FakeRunner)
    assert not got["ok"] and {r["why"] for r in got["stage2"]} == {"no step budget in definition"}
    assert {r["chain"] for r in got["stage2"]} == {"no time budget in definition"}


def test_a_failed_attempt_is_kept_with_its_error_time_and_raw_start():
    """Agent team 21:30 (11-18): the reason of a failure elsewhere in the chain is recorded, not only the step name."""
    result = {"attempts": {"registration": [
        {"resource_id": 52559, "tool": "lookup", "kind": "external", "ok": False, "ms": 4100,
         "error_class": "timeout", "raw": "x" * 500},
        {"resource_id": None, "tool": "rdap", "kind": "agentcon", "ok": True, "ms": 30}]}}
    assert cg.trace(result) == [{"slot": "registration", "member": 52559, "kind": "external",
                                 "error_class": "timeout", "ms": 4100, "raw": "x" * 200}]
    assert cg._row({"check": "c", "ok": True}, {"attempts": {}}) == {"check": "c", "ok": True}   # nothing failed
    # PM 21:35 A: the pearl count is recorded, not judged
    assert cg._row({"check": "c", "ok": True}, {"pearls_answered": 1, "value_counted": False}) == {
        "check": "c", "ok": True, "pearls_answered": 1, "value_counted": False}


def test_a_new_version_moves_into_definitions_only_with_both_keys(tmp_path, monkeypatch):
    """PM 21:35 (11-18): website-trust v3 stays in drafts/ until its gate passed and ops approved v3; v2 stays public."""
    import json as _json
    monkeypatch.setattr(cg.model, "validate", lambda d: [])      # the fake definition; the keys are under test
    defs, root = tmp_path / "definitions", tmp_path / "root"
    defs.mkdir()
    root.mkdir()
    v2 = defn3()
    (defs / f"{v2['slug']}.json").write_text(_json.dumps(v2))
    v3 = dict(defn3(), version=v2["version"] + 1)
    draft = tmp_path / "draft.json"
    draft.write_text(_json.dumps(v3))
    assert cg.promote(root, draft, defs, now=NOW)["why"].startswith("connect_not_passed")
    cg.record(root, {"slug": v3["slug"], "version": v3["version"], "digest": model.digest(v3), "kind": "gate",
                     "ok": True}, now=NOW)
    assert cg.promote(root, draft, defs, now=NOW)["why"].startswith("ops approval for this version")
    (root / "approvals.json").write_text(_json.dumps({"approvals": [
        {"slug": v3["slug"], "state": "approved", "version": v2["version"], "definition_digest": model.digest(v2),
         "at": "2026-11-18T10:00:00Z"}]}))
    assert "approval_mismatch" in cg.promote(root, draft, defs, now=NOW)["why"]      # v2's approval is not v3's
    assert model.load(defs / f"{v2['slug']}.json")["version"] == v2["version"]      # v2 untouched so far
    (root / "approvals.json").write_text(_json.dumps({"approvals": [
        {"slug": v3["slug"], "state": "approved", "version": v3["version"], "definition_digest": model.digest(v3),
         "at": "2026-11-18T13:00:00Z"}]}))
    got = cg.promote(root, draft, defs, now=NOW)
    assert got["promoted"] and got["replaced_version"] == v2["version"]
    assert model.load(defs / f"{v2['slug']}.json")["version"] == v3["version"]
    assert "already has version" in cg.promote(root, draft, defs, now=NOW)["why"]


def test_inputs_come_from_tuning_only(tmp_path):
    folder = tmp_path / "gold" / "topic-brief"
    folder.mkdir(parents=True)
    (folder / "tuning.jsonl").write_text("".join(json.dumps({"input": {"q": q}}) + "\n" for q in ("a", "a", "b", "c", "d")))
    (folder / "holdout-r1.jsonl").write_text(json.dumps({"input": {"q": "secret"}}) + "\n")
    assert cg.tuning_inputs(tmp_path, "topic-brief") == [{"q": "a"}, {"q": "b"}, {"q": "c"}]


def test_the_judge_needs_the_gate_and_an_ops_approval_then_the_daily_run_keeps_it(tmp_path):
    defn = dict(defn3(), status="live")
    summary(tmp_path, defn["slug"], quality={"delta_pp": None})           # no accuracy, no delta asked
    cg.record(tmp_path, run_gate(defn), now=NOW - 3600)
    state = cg.state_of(tmp_path, defn, NOW)
    no_ops = judge.build_entry(defn, None, judge.load_summary(tmp_path, defn["slug"]), NOW, verified=BOTH,
                               connect_state=state)
    assert no_ops["status"] == "held" and no_ops["held_reason"] == "not_approved"     # two keys
    live = judge.build_entry(defn, approval(defn), judge.load_summary(tmp_path, defn["slug"]), NOW, verified=BOTH,
                             connect_state=state)
    assert live["status"] == "live" and live["held_reason"] is None and live["gate_passed_at"]
    assert live["connect"]["last_ok"] is True and live["value"] is None and live["comparison"] is None
    late = judge.build_entry(defn, approval(defn), {}, NOW + 49 * 3600, verified=BOTH,
                             connect_state=cg.state_of(tmp_path, defn, NOW + 49 * 3600))
    assert late["held_reason"] == "connect_stale"
    FakeRunner.broken = {1, 2, "owned"}
    cg.record(tmp_path, cg.gate(defn, None, INPUTS, watch_state=FRESH, states=STATES, daily=True,
                                runner_cls=FakeRunner), now=NOW - 60)
    down = judge.build_entry(defn, approval(defn), {}, NOW, verified=BOTH, connect_state=cg.state_of(tmp_path, defn, NOW))
    assert down["status"] == "held" and down["held_reason"] == "connect_failed"
    not_yet = judge.build_entry(defn, approval(defn), {}, NOW, verified=BOTH,
                                connect_state={"passed_at": None, "last_at": None, "last_ok": None,
                                               "hold": "connect_not_passed"})
    assert not_yet["held_reason"] == "connect_not_passed"
    other = dict(defn, slots=defn["slots"][:2])                              # another digest: its own gate
    assert cg.state_of(tmp_path, other, NOW)["hold"] == "connect_not_passed"
    assert model.digest(other) != model.digest(defn)


def test_the_holdout_gate_round_is_switched_off(monkeypatch):
    from agent_market.necklaces import retest
    monkeypatch.delenv("NECKLACE_HOLDOUT_GATE", raising=False)
    assert retest.holdout_gate_off("gate", "holdout-r5") and not retest.holdout_gate_off("gate", "tuning")
    assert not retest.holdout_gate_off("necklace_retest", "holdout-r1")
    monkeypatch.setenv("NECKLACE_HOLDOUT_GATE", "1")
    assert not retest.holdout_gate_off("gate", "holdout-r5")


def test_a_fallback_that_answered_a_public_run_opens_one_substitute_task_per_role(tmp_path):
    from agent_market.necklaces.substitute_tasks import open_tasks
    defn = defn3()
    runs = tmp_path / "runs"
    runs.mkdir()
    day = time.strftime("%Y%m%d", time.gmtime(NOW))
    at = judge._iso(NOW - 60)
    events = [{"slug": "topic-brief", "source": "external", "at": at, "stages": {"papers": 2, "news": 1, "extra": 2}},
              {"slug": "topic-brief", "source": "external", "at": at, "stages": {"papers": 2}},
              {"slug": "topic-brief", "source": "internal", "at": at, "stages": {"news": 2}}]   # ours: not counted
    (runs / f"{day}.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    (tmp_path / "approvals.json").write_text(json.dumps({"substitutes": [
        {"agent_id": "own-z", "slot_role": "z.v1", "state": "approved", "at": "2026-11-18T00:00:00Z"}]}))
    opened = open_tasks(tmp_path, [defn], NOW)
    assert [(t["role"], t["runs"]) for t in opened] == [("x.v1", 2)]          # z.v1 has a substitute already
    assert open_tasks(tmp_path, [defn], NOW) == []                           # once per role
    assert len((tmp_path / "substitute-tasks.jsonl").read_text().splitlines()) == 1


def test_the_methodology_gate_says_connection_test_and_no_held_out_number():
    """PM 19:5x: the methodology page shows the connection gate (stages, fallbacks, the daily run), no 57 of 60."""
    from agent_market.necklaces import gate_rules
    gate = gate_rules.summary()
    assert gate["necklace"]["gate"] == "connection test" and gate["necklace"]["stage_2_connection_runs"] == cg.CONNECT_RUNS
    assert gate["after_opening"]["connection_runs_a_day"] == 1 and gate["substitute"]["gate"] == "connection test"
    text = json.dumps(gate)
    assert "held_out" not in text and "57" not in text and "pass_total" not in text
    assert gate["necklace"]["accuracy_regraded_at_this_stage"] is False


def test_a_read_only_email_name_exception_is_one_pair_bound_to_its_tool_fingerprint():
    """PM 21:44 (11-18): _DENY stays; (resource_id, tool) pairs read as domain-only DNS lookups are allowed, and the
    connection gate blocks one again when the measured tool fingerprint is not the one it was read from."""
    member = ext(37141, "contrastcyber.com", tool="email_auth_check", terms=dict(SILENT))
    assert not [e for e in model._member_errors("m", 0, member) if "looks like an action" in e]
    for other in (ext(37141, "contrastcyber.com", tool="send_email"), ext(99, "x.com", tool="email_auth_check")):
        assert any("looks like an action" in e for e in model._member_errors("m", 0, other))      # only the pair
    rule = model.READ_ONLY_EXCEPTIONS[(37141, "email_auth_check")]
    assert len(rule["tool_fp"]) == 64 and rule["reason"] and rule["schema"]
    defn = defn3()
    defn["slots"][1]["chain"].insert(1, member)
    fresh = {"baseline": "h", "current": "h", "measured_at": judge._iso(NOW - 60)}
    prints = {"resources": {str(r): dict(fresh) for r in (1, 2, 3, 4, 5, 6)}}
    prints["resources"]["37141"] = dict(fresh, tools={"email_auth_check": rule["tool_fp"]})
    assert "fingerprints:news" not in failed(run_gate(defn, prints=prints, now=NOW))
    prints["resources"]["37141"]["tools"] = {"email_auth_check": "0" * 64}        # the provider changed the tool
    got = run_gate(defn, prints=prints, now=NOW)
    assert "fingerprints:news" in failed(got) and "37141 exception_fingerprint_changed" in str(got["static"])
