"""The necklace gate is a connection test (user decisions 11-18 via PM 19:2x): stage 1 joins the steps one by one,
runs the whole chain and checks every step's fallback; stage 2 runs the whole chain three times on different inputs.
A substitute is approved by three runs of its own. Fake runner only: no network, no answer set."""
import json
import time

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
    broken, slow, seen = set(), 0, []

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
        return {"completed": completed, "failed_slot": failed, "latency_ms": FakeRunner.slow or 900, "slots": slots,
                "output": {}}


def setup_function(_):
    FakeRunner.broken, FakeRunner.slow, FakeRunner.seen = set(), 0, []


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
    unknown["slots"][1]["chain"][1].pop("terms")                # terms never read: not usable for the gate
    assert "terms:news" in failed(run_gate(unknown))
    held = run_gate(defn3(), watch_state={"updated": judge._iso(NOW), "holds": {
        "topic-brief": {"since": judge._iso(NOW - 60), "reason": "member_failing"}}})
    assert "watch" in failed(held)
    assert "inputs" in failed(run_gate(defn3(), inputs=INPUTS[:2]))
    FakeRunner.slow = 6000                                                    # over base()'s 5000 ms budget
    assert failed(run_gate(defn3())) == ["whole"]


def test_a_substitute_is_approved_by_three_runs_of_its_own():
    got = cg.substitute_gate(defn3(), "papers", "owned", None, INPUTS, watch_state=FRESH, runner_cls=FakeRunner)
    assert got["ok"] and got["kind"] == "substitute" and got["contract"] == "x.v1" and len(got["stage2"]) == 3
    FakeRunner.broken = {"owned"}
    bad = cg.substitute_gate(defn3(), "papers", "owned", None, INPUTS, watch_state=FRESH, runner_cls=FakeRunner)
    assert not bad["ok"] and all(not r["ok"] for r in bad["stage2"])


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
