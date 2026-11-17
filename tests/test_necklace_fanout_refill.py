"""PM 11-17 (topic v1 round 1): in a fanout slot a lead that fails frees its place at once, so the next member starts
next to a slow lead instead of waiting for it to time out; never more in flight than the leads started together."""
import threading
import time

from agent_market.necklaces import runner
from tests.test_necklaces_runner import Fail, blocking_caller, necklace, timed


def papers_only(defn):
    defn["slots"] = defn["slots"][:1]
    defn["slots"][0]["fanout"] = 2
    return defn


def test_a_failed_lead_frees_its_place_for_the_next_member(monkeypatch):
    monkeypatch.setattr(runner, "MIN_ATTEMPT_MS", 100)
    calls = []
    release = threading.Event()
    answers = {10: "CVE-2021-23337"}
    try:
        started = time.monotonic()
        out = runner.Runner(blocking_caller(answers, release, block={2}, slow={1: (0.05, Fail())}, calls=calls)).run(
            papers_only(timed(necklace(), total=2000, slot=1500)), {"q": "x"})
        took = time.monotonic() - started
    finally:
        release.set()
    assert out["ok"] and out["slots"]["papers"]["kind"] == "agentcon"
    assert sorted(rid for rid, _ in calls) == [1, 2, 10]
    # our member answered next to the slow lead (before: 'deadline', never started); a fanout-2 slot still waits for a
    # second answer until its deadline, as before
    assert took < 1.9
    assert "deadline" not in [a["error_class"] for a in out["attempts"]["papers"]]


def test_never_more_in_flight_than_the_leads_started_together(monkeypatch):
    monkeypatch.setattr(runner, "MIN_ATTEMPT_MS", 100)
    calls = []
    release = threading.Event()
    defn = papers_only(timed(necklace(), total=1000, slot=800))
    defn["slots"][0]["chain"] = [m for m in defn["slots"][0]["chain"] if m.get("resource_id") != 2]   # one external
    try:
        out = runner.Runner(blocking_caller({10: "CVE-2021-23337"}, release, block={1}, calls=calls)).run(defn, {"q": "x"})
    finally:
        release.set()
    # one external lead was started, so our member waits for its place (as before), it does not run next to it
    assert [rid for rid, _ in calls] == [1]
    assert not out["ok"]


def test_fanout_one_is_unchanged_the_next_member_waits_for_the_lead():
    calls = []
    out = runner.Runner(blocking_caller({1: "CVE-2021-23337", 3: "listed in CISA KEV"}, threading.Event(),
                                        calls=calls)).run(necklace(), {"q": "x"})
    assert out["ok"] and [rid for rid, _ in calls if rid in (1, 2, 10)] == [1]
