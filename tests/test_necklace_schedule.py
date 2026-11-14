import json
import time

from agent_market.necklace_schedule import NecklaceStep
from agent_market.necklaces import model
from tests.test_necklaces_model import base
from tests.test_necklaces_watch import FakeStore, healthy_rows


def at(h, m):
    return time.mktime((2026, 11, 20, h, m, 0, 0, 0, -1))


def setup(tmp_path, *defns):
    defs = tmp_path / "defs"
    defs.mkdir(exist_ok=True)
    for defn in defns:
        (defs / (defn["slug"] + ".json")).write_text(json.dumps(defn))
    return defs


def lines(tmp_path):
    return [json.loads(x) for p in sorted((tmp_path / "logs").glob("runs-*.jsonl")) for x in p.read_text().splitlines()]


def step(tmp_path, defs, clock):
    return NecklaceStep(FakeStore(healthy_rows()), root=tmp_path / "data", logs=tmp_path / "logs",
                        definitions_dir=defs, fingerprints=tmp_path / "none.json", clock=clock)


def test_nothing_to_watch_still_leaves_one_line_an_hour(tmp_path):
    now = [at(10, 21)]
    s = step(tmp_path, setup(tmp_path), lambda: now[0])
    assert s.run_due()["necklaces"]["ok"] is True
    assert s.run_due() is None                       # same hour
    now[0] = at(11, 5)
    assert s.run_due() is None                       # quiet window :55-:10
    now[0] = at(11, 20)
    s.run_due()
    rows = lines(tmp_path)
    assert len(rows) == 2 and all(r["definitions"] == 0 and r["ok"] for r in rows)
    assert rows[0]["watch"] == {"members": 0, "holds": []} and rows[0]["judge"]["entries"] == {}
    assert json.loads((tmp_path / "data" / "necklaces.json").read_text())["necklaces"] == []


def test_judge_rewrites_the_snapshot_and_daily_runs_once_after_0520(tmp_path):
    trial = base()
    trial["status"] = "trial"
    for slot in trial["slots"]:
        slot["contract"] = "package.advisories.v1"
    now = [at(4, 20)]
    s = step(tmp_path, setup(tmp_path, trial), lambda: now[0])
    assert s.run_due() is None                       # 03:50-05:10 window
    now[0] = at(5, 20)
    first = s.run_due()["necklaces"]
    assert first["retest_targets"] == {"trial": 1, "live": 0} and first["daily"]["necklaces"] == 1
    assert (tmp_path / "logs" / "20261120.md").exists()
    now[0] = at(6, 20)
    assert "daily" not in s.run_due()["necklaces"]
    assert json.loads((tmp_path / "data" / "members.json").read_text())["resource_ids"]


def test_a_broken_definition_is_one_failure_line_an_hour(tmp_path):
    defs = setup(tmp_path)
    (defs / "bad.json").write_text("{}")
    now = [at(10, 21)]
    s = step(tmp_path, defs, lambda: now[0])
    result = s.run_due()["necklaces"]
    assert result["ok"] is False and result["definitions_error"]
    assert s.run_due() is None
    assert len(lines(tmp_path)) == 1


def test_shipped_definitions_load_for_the_step():
    assert model.load_valid() is not None


# ---------------------------------------------------------------- daily retests (PM 11-14 15시: by 11-19)
from agent_market.necklace_schedule import RetestStep  # noqa: E402


def retest_step(tmp_path, defs, clock, calls):
    def run(defn, **kw):
        calls.append((defn["slug"], kw["split"], kw["singles"], round(kw["budget_s"])))
        return {"slug": defn["slug"], "cases": 30, "passed": 29}
    return RetestStep(root=tmp_path / "data", logs=tmp_path / "logs", definitions_dir=defs, clock=clock, run=run,
                      background=False)


def statused(slug, status):
    defn = dict(base(), slug=slug, status=status)
    for slot in defn["slots"]:
        slot["contract"] = "package.advisories.v1"
    return defn


def test_trial_retests_start_at_0115_once_a_day_and_live_at_0310(tmp_path):
    defs = setup(tmp_path, statused("trial-brief", "trial"), statused("live-brief", "live"), statused("idea", "candidate"))
    now, calls = [at(1, 10)], []
    s = retest_step(tmp_path, defs, lambda: now[0], calls)
    assert s.run_due() is None
    now[0] = at(1, 16)
    line = s.run_due()["necklace_retest"]
    assert line["targets"] == 1 and calls == [("trial-brief", line["split"], False, 4140)]   # 01:16 -> 02:25
    assert s.run_due() is None
    fresh = retest_step(tmp_path, defs, lambda: now[0], calls)          # a restarted jobs process
    assert fresh.run_due()["necklace_retest"]["targets"] == 0
    now[0] = at(3, 12)
    s.run_due()
    assert calls[-1][0] == "live-brief" and calls[-1][3] == 36 * 60    # finishes by 03:48
    assert [r["kind"] for r in lines(tmp_path)] == ["trial", "trial", "live"]


def test_no_targets_still_leaves_a_line_per_window(tmp_path):
    now, calls = [at(1, 20)], []
    s = retest_step(tmp_path, setup(tmp_path), lambda: now[0], calls)
    assert s.run_due()["necklace_retest"] == {"step": "retest", "kind": "trial", "ok": True, "targets": 0}
    now[0] = at(3, 15)
    s.run_due()
    assert calls == [] and [(r["kind"], r["targets"]) for r in lines(tmp_path)] == [("trial", 0), ("live", 0)]


def test_mondays_add_the_single_baseline_and_late_targets_are_skipped(tmp_path):
    monday = time.mktime((2026, 11, 16, 3, 19, 0, 0, 0, -1))
    defs = setup(tmp_path, statused("a-brief", "live"), statused("b-brief", "live"))
    clock = iter([monday, monday, time.mktime((2026, 11, 16, 3, 47, 30, 0, 0, -1)), monday + 1800])
    calls = []
    out = retest_step(tmp_path, defs, lambda: next(clock), calls).run_due()["necklace_retest"]
    assert calls[0][2] is True and len(calls) == 1
    assert out["results"][1] == {"slug": "b-brief", "skipped": "no_time"}


def test_daily_split_alternates():
    from agent_market.necklaces import retest
    assert {retest.daily_split(at(12, 0)), retest.daily_split(at(12, 0) + 86400)} == {"holdout-r1", "holdout-r2"}
