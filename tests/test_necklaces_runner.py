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
        value = answers.get(member.get("resource_id") or member.get("agent_id"))
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
    assert out["slots"]["papers"] == {"rank": 1, "kind": "external", "failed": False, "stage": 1, "status": "answered"}
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
    assert out["slots"]["news"] == {"rank": None, "kind": None, "failed": True, "stage": 4, "status": "failed"}
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


def test_shipped_definition_runs_once_its_fallbacks_pass_the_gate():
    defn = next(d for d in model.load_valid() if d["slug"] == "package-risk-audit")
    for slot in defn["slots"]:
        for m in slot["chain"]:
            if m["kind"] == "agentcon":
                m["state"] = "active"        # what the ops substitute gate turns on
    answers = {367249: "CVE-2021-23337", 286623: "GHSA-35jh-r3h4-6jhm CVE-2021-23337",
               "package-registry": {"latest_version": "4.17.21", "source": "npm"}}
    out = runner.Runner(caller_from(answers)).run(defn, {"package": "lodash", "ecosystem": "npm", "version": "4.17.20"})
    assert out["ok"] and out["slots"]["advisories"]["stage"] == 1
    assert out["slots"]["health"]["stage"] == 3 and out["slots"]["health"]["kind"] == "agentcon"
    assert own(1)["kind"] == "agentcon" and ext(1, "a")["kind"] == "external"


def test_our_runs_never_count_as_external():
    for origin in runner.OUR_ORIGINS:
        assert runner.classify_source(origin, ua="Mozilla/5.0 Chrome/120") == ("internal", origin)
    assert runner.classify_source(None) == ("internal", "unknown")      # unknown origin is not external
    assert runner.classify_source("public", ua="Mozilla/5.0", qa="real_task_score")[0] == "internal"
    assert runner.classify_source("public", ua="AgentValCon-Check/1.0")[0] == "internal"
    assert runner.classify_source("public", ua="Mozilla/5.0", ip="10.0.0.5", internal_ips={"10.0.0.5"})[0] == "internal"
    assert runner.classify_source("public", ua="curl/8", principal="p1", internal_principals={"p1"})[0] == "internal"
    assert runner.classify_source("public", ua="Mozilla/5.0 (compatible; GPTBot/1.2)")[0] == "crawler"
    assert runner.classify_source("public", ua="Mozilla/5.0 (Macintosh) AppleWebKit Chrome/120 Safari/537")[0] == "external"


def test_daily_north_star_counts_external_clients_only(tmp_path):
    from agent_market.necklaces import daily
    out = runner.Runner(caller_from({1: "CVE-2020-28500", 3: "kev"})).run(necklace(), {"q": "x"})
    now = 1_800_000_000
    events = [runner.run_event(out, *runner.classify_source("public", ua="Mozilla/5.0 Chrome/120 Safari/537"), at=now)]
    events.append(runner.run_event(out, *runner.classify_source("retest"), at=now))
    events.append(runner.run_event(out, *runner.classify_source("public", ua="x", qa="user_slo"), at=now))
    forged = runner.run_event(out, "external", at=now, origin="gate")    # an internal origin can never be external
    events.append(forged)
    summary = daily.summarize("topic-brief", [], [], [], events)
    assert summary["external_runs"] == {"total": 1, "succeeded": 1}


class FakeBudget:
    def __init__(self, allow=lambda url: True):
        self.allow, self.reserved, self.noted = allow, [], []

    def reserve(self, url, system, n=1):
        self.reserved.append((url, system))
        return (True, "ok") if self.allow(url) else (False, "system_share")

    def note(self, url, system, status):
        self.noted.append((url, system, status))


def test_budget_wraps_external_calls_only_and_denial_moves_on():
    budget = FakeBudget(allow=lambda url: not url.endswith("/1"))
    rate_limited = Fail("PROVIDER_429")        # a pause the provider asked for (our relay's 429 never counts)
    answers = {1: "CVE-1", 2: "CVE-2020-28500", 3: rate_limited, 4: Fail(), 11: "not in the CISA KEV catalog"}
    call = runner.budgeted_caller(caller_from(answers), "necklace_retest",
                                  lambda m: f"https://p{m['resource_id']}.example/{m['resource_id']}", budget)
    out = runner.Runner(call).run(necklace(), {"q": "x"})
    assert out["attempts"]["papers"][0]["error_class"] == "budget_system_share"
    assert out["slots"]["papers"]["stage"] == 2
    assert ("https://p3.example/3", "necklace_retest", 429) in budget.noted
    assert all(not url.endswith("/11") for url, _ in budget.reserved)   # AgentValCon fallback not counted
    assert out["slots"]["news"]["stage"] == 3


def test_stale_fallback_moves_to_the_next_member():
    class Stale(Exception):
        code = "stale"
    defn = necklace()
    defn["slots"][1]["chain"].append(own(12, agent_id="owned3"))
    answers = {1: "CVE-2020-28500", 3: Fail(), 4: Fail(), 11: Stale(), 12: "listed in CISA KEV"}
    out = runner.Runner(caller_from(answers)).run(defn, {"q": "x"})
    news = out["attempts"]["news"]
    assert [a["error_class"] for a in news][-2:] == ["stale", None] and out["slots"]["news"]["stage"] == 3


def test_relay_throttle_does_not_pause_the_provider():
    budget = FakeBudget()
    call = runner.budgeted_caller(caller_from({1: Fail("relay_throttled"), 2: "CVE-1", 3: "kev"}), "necklace_retest",
                                  lambda m: f"https://p{m['resource_id']}.example/", budget)
    runner.Runner(call).run(necklace(), {"q": "x"})
    assert budget.noted == []


def test_cvss_score_is_never_the_cvss_version():
    nvd_like = {"metrics": {"cvssMetricV31": [{"cvssData": {"version": "3.1", "vectorString": "CVSS:3.1/AV:N/AC:L",
                                                           "baseScore": 10.0}}]}}
    assert runner.find_score(nvd_like) == 10.0
    assert runner.find_score("CVSS:3.1/AV:N/AC:L/PR:N base score 9.8 (critical)") == 9.8
    assert runner.find_score("cvssV3_1 vector only, no score") is None
    assert runner.find_score({"version": "3.1", "severity": "HIGH"}) is None
    assert runner.norm_record({"id": "CVE-2021-44228", "score": 10.0}, {"cve_id": "CVE-2021-44228"})["cvss_score"] == 10.0


def test_raw_answers_are_kept_on_attempts_for_self_tests():
    out = runner.Runner(caller_from({1: "CVE-2020-28500 raw", 3: "kev"}), keep_raw=10).run(necklace(), {"q": "x"})
    assert out["attempts"]["papers"][0]["raw"] == "CVE-2020-2"
    plain = runner.Runner(caller_from({1: "CVE-2020-28500", 3: "kev"})).run(necklace(), {"q": "x"})
    assert plain["attempts"]["papers"][0]["raw"] is None


# ---------------------------------------------------------------- deadlines (PM F04, 11-14)
def timed(defn, total=1000, slot=800):
    defn["budget_ms"] = {"total": total, "slot": slot}
    return defn


def blocking_caller(answers, release, block=(), slow=None, calls=None):
    """Members in ``block`` ignore their timeout and wait for ``release`` (a caller that does not cooperate);
    ``slow`` maps a member to (seconds, then) where ``then`` is an answer or an exception."""
    slow = slow or {}

    def call(member, args, timeout):
        rid = member.get("resource_id")
        if calls is not None:
            calls.append((rid, round(timeout, 2)))
        if rid in block:
            release.wait(5)
            return answers.get(rid, "late answer")
        if rid in slow:
            seconds, then = slow[rid]
            time.sleep(seconds)
            if isinstance(then, Exception):
                raise then
            return then
        value = answers.get(rid)
        if value is None:
            raise Fail()
        return value
    return call


ANSWERS = {1: "CVE-2021-23337", 2: "CVE-2021-23337", 3: "listed in CISA KEV", 4: "listed in CISA KEV"}


def test_a_caller_that_ignores_its_timeout_cannot_hold_the_run(monkeypatch):
    monkeypatch.setattr(runner, "MIN_ATTEMPT_MS", 100)
    release = threading.Event()
    try:
        started = time.monotonic()
        out = runner.Runner(blocking_caller(ANSWERS, release, block={1})).run(timed(necklace()), {"q": "x"})
        took = time.monotonic() - started
    finally:
        release.set()
    assert took < 1.0                                   # slot budget 0.8s, total 1.0s
    assert not out["ok"] and out["failed_slot"] == "papers"
    assert out["slots"]["papers"]["status"] == "timeout"
    assert [a["error_class"] for a in out["attempts"]["papers"]] == ["timeout", "deadline"]   # member 2 not sent
    assert out["abandoned_calls"] == 1 and out["pending_at_return"] == 1
    assert out["slots"]["news"]["status"] == "answered"


def test_each_call_gets_the_time_left_in_its_slot(monkeypatch):
    monkeypatch.setattr(runner, "MIN_ATTEMPT_MS", 100)
    calls = []
    caller = blocking_caller(ANSWERS, threading.Event(), slow={1: (0.3, Fail())}, calls=calls)
    out = runner.Runner(caller).run(timed(necklace()), {"q": "x"})
    timeouts = dict(calls)
    assert timeouts[1] <= 0.8 and timeouts[2] <= 0.5          # member 2 starts after member 1 failed at 0.3s
    assert out["ok"] and out["slots"]["papers"] == {"rank": 2, "kind": "external", "failed": False, "stage": 2,
                                                    "status": "answered"}


def test_a_slow_first_candidate_leaves_no_time_for_the_next(monkeypatch):
    monkeypatch.setattr(runner, "MIN_ATTEMPT_MS", 300)
    calls = []
    caller = blocking_caller(ANSWERS, threading.Event(), slow={1: (0.6, Fail())}, calls=calls)
    started = time.monotonic()
    out = runner.Runner(caller).run(timed(necklace()), {"q": "x"})
    assert time.monotonic() - started < 1.0
    assert 2 not in dict(calls)                         # 0.2s left < 0.3s minimum: not sent
    assert [a["error_class"] for a in out["attempts"]["papers"]][-1] == "deadline"
    assert out["slots"]["papers"]["status"] == "timeout" and not out["ok"]


def test_a_slow_optional_slot_returns_by_the_slot_deadline_and_the_run_succeeds(monkeypatch):
    monkeypatch.setattr(runner, "MIN_ATTEMPT_MS", 100)
    defn = timed(necklace())
    defn["slots"][1]["required"] = False
    release = threading.Event()
    try:
        started = time.monotonic()
        out = runner.Runner(blocking_caller(ANSWERS, release, block={3})).run(defn, {"q": "x"})
        took = time.monotonic() - started
    finally:
        release.set()
    assert took < 1.0
    assert out["ok"] and out["completed"] and out["failed_slot"] is None
    assert out["slots"]["news"]["status"] == "timeout" and out["output"]["news"] == {"missing": True}


def test_partial_fanout_keeps_the_answer_that_came_in_time(monkeypatch):
    monkeypatch.setattr(runner, "MIN_ATTEMPT_MS", 100)
    defn = timed(necklace())
    defn["slots"][0]["fanout"] = 2
    release = threading.Event()
    try:
        out = runner.Runner(blocking_caller(ANSWERS, release, block={2})).run(defn, {"q": "x"})
    finally:
        release.set()
    assert out["ok"] and out["slots"]["papers"]["status"] == "partial" and out["slots"]["papers"]["stage"] == 1
    assert sorted(a["error_class"] or "ok" for a in out["attempts"]["papers"]) == ["ok", "timeout"]
    assert out["pending_at_return"] == 1


def test_an_answer_after_the_deadline_is_late_and_never_counts():
    ticks = iter([0.0, 2.0])
    r = runner.Runner(lambda m, a, t: "CVE-2021-23337", clock=lambda: next(ticks))
    attempt, canon = r._call(ext(1, "a.com"), 1, {"q": "x"}, "package.advisories.v1", 1.0)
    assert canon is None and not attempt.ok and attempt.error_class == "late"


def test_the_process_wide_cap_refuses_calls_instead_of_queueing(monkeypatch):
    monkeypatch.setattr(runner, "MIN_ATTEMPT_MS", 100)
    defn = timed(necklace())
    defn["slots"] = defn["slots"][:1]
    defn["slots"][0]["fanout"] = 2
    calls = []
    cap = threading.BoundedSemaphore(1)
    caller = blocking_caller(ANSWERS, threading.Event(), slow={1: (0.1, "CVE-2021-23337")}, calls=calls)
    out = runner.Runner(caller, inflight=cap).run(defn, {"q": "x"})
    assert [rid for rid, _ in calls] == [1]
    assert [a["error_class"] for a in out["attempts"]["papers"]].count("capacity") == 1
    assert out["ok"]
    assert cap.acquire(blocking=False)                  # released once the call ended
