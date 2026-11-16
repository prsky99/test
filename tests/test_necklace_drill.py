"""Fallback drill (plan 3.4, PM 11-15): once a week the leads are left out and the run must finish on alternates."""
import json
import time

from agent_market.necklaces import daily, model, retest
from agent_market.necklaces.watch import runtime_chain


def book():
    return model.load("agent_market/necklaces/definitions/book-author-brief.json")


def test_drill_state_leaves_every_slots_lead_out_and_keeps_the_real_state():
    defn, real = book(), {"substitutes": [["wikidata-book", "book.search.v1"]]}
    state = retest.drill_state(defn, real)
    assert [d["resource_id"] for d in state["drill_dropped"]] == [38608, 241601]
    chain = runtime_chain(defn["slots"][0], defn["slug"], state)
    assert [m.get("agent_id") or m.get("resource_id") for m in chain] == ["wikidata-book"]
    assert "members" not in real                                               # the watch state is not changed


def test_a_drill_writes_its_own_lines_and_never_a_quality_case(tmp_path, monkeypatch):
    folder = tmp_path / "gold" / "book-author-brief"
    folder.mkdir(parents=True)
    case = {"case_id": "b1", "input": {"title": "Nineteen Eighty-Four"},
            "truth": {"author": "George Orwell", "year": 1949, "birth_year": 1903}}
    (folder / "holdout-r1.jsonl").write_text(json.dumps(case) + "\n")
    (folder / "manifest.json").write_text(json.dumps({"valid_until": "2999-01-01"}))
    called = []

    class Engine:
        store = None

        def _call_registered(self, node, args, binding=None, *, timeout=None):
            called.append(node.get("resource_id"))
            return {}
    monkeypatch.setattr(retest.runner, "budgeted_caller", lambda caller, system, url_of, budget=None: caller)
    from agent_market.necklaces import judge
    monkeypatch.setattr(judge, "load_substitutes", lambda path: [["wikidata-book", "book.search.v1"],
                                                                 ["wikipedia-summary", "encyclopedia.summary.v1"]])
    out = retest.run_daily(book(), root=tmp_path, split="holdout-r1", singles=False, budget_s=60, path="engine",
                           engine=Engine(), drill=True, sample=(0, 5))
    assert out["drill"] is True and [d["resource_id"] for d in out["dropped"]] == [38608, 241601]
    assert 38608 not in called and 241601 not in called                         # the leads were never called
    lines = [json.loads(x) for x in (tmp_path / "retest").glob("*.jsonl").__next__().read_text().splitlines()]
    assert {x["type"] for x in lines} == {"drill"}


def test_a_live_necklace_without_a_drill_this_week_raises_an_alert(tmp_path):
    defn = dict(book(), status="live")
    now = time.time()
    alerts = lambda: [json.loads(x) for x in ((tmp_path / "logs" / "alerts.jsonl").read_text().splitlines()
                                              if (tmp_path / "logs" / "alerts.jsonl").exists() else [])]
    daily.run([defn], tmp_path, tmp_path / "logs", now - 9 * 86400)    # first seen live, before any drill day
    assert not any(a["alert"] == "drill_missing" for a in alerts())
    daily.run([defn], tmp_path, tmp_path / "logs", now)                   # 9 days on and still no drill
    assert any(a["alert"] == "drill_missing" and a["slug"] == "book-author-brief" for a in alerts())
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 3600))
    (tmp_path / "retest").mkdir(exist_ok=True)
    (tmp_path / "retest" / (time.strftime("%Y%m%d", time.localtime(now)) + ".jsonl")).write_text(
        json.dumps({"type": "drill", "slug": "book-author-brief", "at": stamp, "ok": False}) + "\n")
    (tmp_path / "logs" / "alerts.jsonl").unlink()
    daily.run([defn], tmp_path, tmp_path / "logs", now)
    assert not any(a["alert"] == "drill_missing" for a in alerts())
    assert any(a["alert"] == "drill_failed" for a in alerts())
    summary = json.loads((tmp_path / "results" / "book-author-brief" / "summary.json").read_text())
    assert summary["drill"]["cases_7d"] == 1 and summary["drill"]["passed_7d"] == 0


def test_wednesday_runs_the_drill_after_the_retest_and_logs_a_line(tmp_path):
    """Plan 3.4 / ops fcc77e15: on Wednesdays the live hour also runs the drill; every drill leaves a line in
    drills.jsonl, and an empty drill day still leaves one."""
    from agent_market.necklace_schedule import RetestStep, live_hour
    from tests.test_necklace_schedule import setup, statused
    defs = setup(tmp_path, statused("live-brief", "live"))
    hour = live_hour("live-brief")
    wednesday = time.mktime((2026, 11, 18, hour, 16, 0, 0, 0, -1))
    calls = []

    def run(defn, **kw):
        calls.append(kw.get("drill", False))
        return {"slug": defn["slug"], "cases": 5, "passed": 5, "dropped": [{"slot": "papers", "resource_id": 1}]}
    step = RetestStep(root=tmp_path / "data", logs=tmp_path / "logs", definitions_dir=defs, clock=lambda: wednesday,
                      run=run, background=False)
    step.run_due()
    assert calls == [False, True]
    line = json.loads((tmp_path / "logs" / "drills.jsonl").read_text().splitlines()[-1])
    assert line["ok"] is True and line["slug"] == "live-brief" and line["cases"] == 5
    (tmp_path / "other").mkdir()
    empty = setup(tmp_path / "other")
    early = time.mktime((2026, 11, 18, 1, 20, 0, 0, 0, -1))
    RetestStep(root=tmp_path / "d2", logs=tmp_path / "logs2", definitions_dir=empty, clock=lambda: early, run=run,
               background=False).run_due()
    assert json.loads((tmp_path / "logs2" / "drills.jsonl").read_text())["targets"] == 0
