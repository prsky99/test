import json
import threading
import time

from agent_market.necklaces import model, runner
from tests.test_necklaces_model import base, ext, own


class Fail(Exception):
    def __init__(self, code="UPSTREAM_TOOL_ERROR"):
        super().__init__(code)
        self.error_code = code


def necklace():
    defn = base()
    defn["slots"][0]["contract"] = "package.advisories.v1"
    defn["slots"][1]["contract"] = "cve.exploited.v1"
    for slot in defn["slots"]:
        for m in slot["chain"]:
            m["input_map"] = {"q": "{{input.q}}", "fixed": 1, "absent": "{{input.missing}}"}
    return defn


def caller_from(answers, calls=None, delay=0.0):
    lock = threading.Lock()

    def call(member, args, timeout):
        with lock:
            if calls is not None:
                calls.append((member.get("resource_id"), args))
        if delay:
            time.sleep(delay)
        value = answers.get(member.get("resource_id"))
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise Fail()
        return value
    return call


def test_render_fills_templates_and_drops_absent_inputs():
    assert runner.render({"q": "{{input.q}}", "n": 3, "v": "{{input.v}}"}, {"q": "x"}) == {"q": "x", "n": 3}


def test_all_leads_answer_stage_one_and_merge_marks_agreement():
    calls = []
    answers = {1: "GHSA-29mw-wpgm-hmr9 and CVE-2021-23337", 2: {"ids": ["CVE-2021-23337"]},
               3: "listed in CISA KEV", 4: "x"}
    defn = necklace()
    defn["slots"][0]["fanout"] = 2
    out = runner.Runner(caller_from(answers, calls)).run(defn, {"q": "lodash"})
    assert out["ok"] and out["completed_external_only"]
    assert out["slots"]["papers"] == {"rank": 1, "kind": "external", "failed": False, "stage": 1}
    items = {i["id"]: i for i in out["output"]["papers"]["items"]}
    assert items["CVE-2021-23337"]["agreed"] and not items["GHSA-29MW-WPGM-HMR9"]["agreed"]
    assert out["output"]["news"]["kev"] is True
    assert {rid for rid, _ in calls} == {1, 2, 3}          # news fanout 1: member 4 not called
    assert all(args == {"q": "lodash", "fixed": 1} for _, args in calls)


def test_external_fallback_is_stage_two_and_agentvalcon_is_stage_three():
    answers = {1: Fail(), 2: "CVE-2020-28500", 3: Fail(), 4: Fail(), 11: "not in the CISA KEV catalog"}
    out = runner.Runner(caller_from(answers)).run(necklace(), {"q": "x"})
    assert out["slots"]["papers"]["stage"] == 2 and out["slots"]["papers"]["rank"] == 2
    assert out["slots"]["news"]["stage"] == 3 and out["slots"]["news"]["kind"] == "agentcon"
    assert out["output"]["news"]["kev"] is False
    assert out["ok"] and not out["completed_external_only"]


def test_every_member_failing_is_stage_four_and_the_run_fails():
    answers = {1: "CVE-2020-28500", 3: Fail(), 4: Fail(), 11: Fail()}
    out = runner.Runner(caller_from(answers)).run(necklace(), {"q": "x"})
    assert out["slots"]["news"] == {"rank": None, "kind": None, "failed": True, "stage": 4}
    assert not out["ok"] and out["failed_slot"] == "news"
    assert [a["resource_id"] for a in out["attempts"]["news"]] == [3, 4, 11]


def test_an_empty_answer_is_not_a_success():
    answers = {1: "   ", 2: "CVE-2020-28500", 3: "kev", 4: "x"}
    out = runner.Runner(caller_from(answers)).run(necklace(), {"q": "x"})
    assert out["attempts"]["papers"][0]["error_class"] == "contract_invalid"
    assert out["slots"]["papers"]["stage"] == 2


def test_watch_demotion_and_exclusion_change_the_order_not_the_digest():
    defn = necklace()
    state = {"members": {"topic-brief|papers|1|search_items": {"demoted": True},
                         "topic-brief|news|3|search_items": {"excluded": True}}}
    calls = []
    answers = {1: "CVE-1", 2: "CVE-2020-28500", 4: "known exploited", 3: "kev"}
    out = runner.Runner(caller_from(answers, calls), watch_state=state).run(defn, {"q": "x"})
    assert out["digest"] == model.digest(defn)
    assert [rid for rid, _ in calls if rid in (1, 2)] == [2]
    assert 3 not in [rid for rid, _ in calls]


def test_coverage_skips_members_outside_their_region():
    defn = necklace()
    defn["slots"][0]["chain"][0]["coverage"] = {"q": ["only-this"]}
    calls = []
    runner.Runner(caller_from({2: "CVE-2020-28500", 3: "kev"}, calls)).run(defn, {"q": "x"})
    assert 1 not in [rid for rid, _ in calls]


def test_slots_run_in_parallel_under_the_deadline():
    answers = {1: "CVE-2020-28500", 3: "kev"}
    started = time.monotonic()
    out = runner.Runner(caller_from(answers, delay=0.3)).run(necklace(), {"q": "x"})
    assert time.monotonic() - started < 0.55 and out["ok"]


def test_deadline_stops_further_fallbacks():
    defn = necklace()
    defn["budget_ms"] = {"total": 700, "slot": 700}
    answers = {1: Fail(), 2: Fail(), 3: "kev"}
    out = runner.Runner(caller_from(answers, delay=0.2)).run(defn, {"q": "x"})
    classes = [a["error_class"] for a in out["attempts"]["papers"]]
    assert "deadline" in classes and out["slots"]["papers"]["stage"] == 4


def test_run_event_has_no_input_or_output(tmp_path):
    out = runner.Runner(caller_from({1: "CVE-2020-28500", 3: "kev"})).run(necklace(), {"q": "secret-topic"})
    event = runner.run_event(out, "external", at=1_800_000_000)
    runner.append_event(tmp_path, event)
    text = (tmp_path / "runs" / "20270115.jsonl").read_text()
    assert "secret-topic" not in text and "CVE-2020-28500" not in text
    assert json.loads(text)["stages"] == {"papers": 1, "news": 1}


def test_shipped_definition_runs_with_a_fake_caller():
    defn = next(d for d in model.load_valid() if d["slug"] == "package-risk-audit")
    answers = {367249: "CVE-2021-23337", 286623: "GHSA-35jh-r3h4-6jhm CVE-2021-23337",
               133021: {"version": "4.17.21"}}
    out = runner.Runner(caller_from(answers)).run(defn, {"package": "lodash", "ecosystem": "npm", "version": "4.17.20"})
    assert out["ok"] and out["slots"]["advisories"]["stage"] == 1
    assert out["slots"]["health"]["stage"] == 3      # only the AgentValCon fallback is active there today
    assert own(1)["kind"] == "agentcon" and ext(1, "a")["kind"] == "external"
