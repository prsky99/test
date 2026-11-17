import json
import time

import pytest

from agent_market.necklace_schedule import NecklaceStep
from agent_market.necklaces import model, watch
from tests.test_necklaces_model import base
from tests.test_necklaces_watch import FakeStore, healthy_rows


@pytest.fixture(autouse=True)
def _upgrades_in_tmp(tmp_path, monkeypatch):
    """11-18 04:19: the night full pytest ran NecklaceWatch here with a 2026-11-20 clock and the upgrade lines went to
    the real logs/ops/necklace-watch/upgrades.jsonl (the path is not under the task's root). Every test here writes
    them under tmp_path."""
    monkeypatch.setattr(watch, "UPGRADES", tmp_path / "upgrades.jsonl")


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
        calls.append((defn["slug"], kw["split"], kw["singles"], round(kw["budget_s"]), kw.get("sample"),
                      kw.get("shared_cache") is not None))
        return {"slug": defn["slug"], "cases": 30, "passed": 29}
    return RetestStep(root=tmp_path / "data", logs=tmp_path / "logs", definitions_dir=defs, clock=clock, run=run,
                      background=False)


def statused(slug, status):
    defn = dict(base(), slug=slug, status=status)
    for slot in defn["slots"]:
        slot["contract"] = "package.advisories.v1"
    return defn


def test_trial_retests_start_at_0115_once_a_day(tmp_path):
    defs = setup(tmp_path, statused("trial-brief", "trial"), statused("live-brief", "live"), statused("idea", "candidate"))
    now, calls = [at(1, 10)], []
    s = retest_step(tmp_path, defs, lambda: now[0], calls)
    assert s.run_due() is None
    now[0] = at(1, 16)
    line = s.run_due()["necklace_retest"]
    assert line["targets"] == 1 and calls == [("trial-brief", line["split"], False, 4140, None, True)]   # -> 02:25
    assert s.run_due() is None
    fresh = retest_step(tmp_path, defs, lambda: now[0], calls)          # a restarted jobs process
    assert fresh.run_due()["necklace_retest"]["targets"] == 0
    assert [r["kind"] for r in lines(tmp_path)] == ["trial", "trial"]


def test_live_necklaces_retest_in_their_own_hour_on_five_sample_cases(tmp_path):
    """PM 11:4x decisions 1-3: own hour 06-22 (:15-:50), 5 cases walking a held-out set in 6 days, shared cache."""
    from agent_market.necklace_schedule import LIVE_HOURS, live_hour
    from agent_market.necklaces import retest
    defs = setup(tmp_path, statused("live-brief", "live"))
    hour = live_hour("live-brief")
    assert hour in LIVE_HOURS and live_hour("live-brief") == hour
    other = LIVE_HOURS[(LIVE_HOURS.index(hour) + 1) % len(LIVE_HOURS)]
    now, calls = [at(other, 16)], []
    s = retest_step(tmp_path, defs, lambda: now[0], calls)
    assert s.run_due()["necklace_retest"]["targets"] == 0 and calls == []
    now[0] = at(hour, 16)
    s.run_due()
    split, first = retest.sample_window(now[0])
    assert calls == [("live-brief", split, calls[0][2], 34 * 60, (first, 5), True)]      # 16 past -> 50 past
    assert s.run_due() is None
    assert all(r["kind"] == "live" for r in lines(tmp_path))


def test_sample_window_walks_a_held_out_set_in_six_days():
    from agent_market.necklaces import retest
    day0 = 6 * 86400 * 10                       # a cycle start
    seen = [retest.sample_window(day0 + d * 86400) for d in range(12)]
    assert [s for s, _ in seen[:6]] == ["holdout-r1"] * 6 and [s for s, _ in seen[6:]] == ["holdout-r2"] * 6
    assert [f for _, f in seen[:6]] == [0, 5, 10, 15, 20, 25]


def test_no_targets_still_leaves_a_line_per_trial_window(tmp_path):
    now, calls = [at(1, 20)], []
    s = retest_step(tmp_path, setup(tmp_path), lambda: now[0], calls)
    assert s.run_due()["necklace_retest"] == {"step": "retest", "kind": "trial", "ok": True, "targets": 0}
    assert calls == [] and [(r["kind"], r["targets"]) for r in lines(tmp_path)] == [("trial", 0)]


def test_mondays_add_the_single_baseline_and_late_targets_are_skipped(tmp_path):
    monday = time.mktime((2026, 11, 16, 1, 19, 0, 0, 0, -1))
    defs = setup(tmp_path, statused("a-brief", "trial"), statused("b-brief", "trial"))
    clock = iter([monday, monday, time.mktime((2026, 11, 16, 2, 24, 30, 0, 0, -1)), monday + 1800])
    calls = []
    out = retest_step(tmp_path, defs, lambda: next(clock), calls).run_due()["necklace_retest"]
    assert calls[0][2] is True and len(calls) == 1
    assert out["results"][1] == {"slug": "b-brief", "skipped": "no_time"}


def test_daily_split_alternates():
    from agent_market.necklaces import retest
    assert {retest.daily_split(at(12, 0)), retest.daily_split(at(12, 0) + 86400)} == {"holdout-r1", "holdout-r2"}


def test_recent_kev_refresh_runs_once_a_day_after_0620(tmp_path):
    from agent_market.necklace_schedule import RoleTaskRefresh
    now, calls = [at(6, 0)], []
    step = RoleTaskRefresh(clock=lambda: now[0], refresh=lambda: calls.append(1) or {"refreshed": False},
                           logs=tmp_path / "logs")
    assert step.run_due() is None
    now[0] = at(6, 21)
    assert step.run_due()["role_tasks"]["ok"] is True and step.run_due() is None and calls == [1]
    assert lines(tmp_path)[-1]["step"] == "role_tasks_recent_kev"


def test_a_deferred_whole_set_runs_in_a_later_free_hour_and_then_leaves_the_list(tmp_path):
    """PM 12:50: a whole-set rerun without provider room waits for the next free live hour."""
    from agent_market.necklace_schedule import LIVE_HOURS, live_hour
    defs = setup(tmp_path, statused("live-brief", "live"))
    hour = live_hour("live-brief")
    later = LIVE_HOURS[(LIVE_HOURS.index(hour) + 1) % len(LIVE_HOURS)]
    now, calls, answers = [at(hour, 16)], [], [{"deferred": {"why": "provider_share"}}]

    def run(defn, **kw):
        calls.append((kw.get("sample"), kw.get("require_room")))
        out = answers.pop(0) if answers else {"cases": 30, "passed": 30}
        return {"slug": defn["slug"], **out}
    s = RetestStep(root=tmp_path / "data", logs=tmp_path / "logs", definitions_dir=defs, clock=lambda: now[0], run=run,
                   background=False)
    s.run_due()
    assert json.loads((tmp_path / "data" / "retest" / "deferred.json").read_text())["live-brief"]["split"]
    now[0] = at(later, 16)
    s.run_due()
    assert calls[-1] == (None, True)
    assert json.loads((tmp_path / "data" / "retest" / "deferred.json").read_text()) == {}
