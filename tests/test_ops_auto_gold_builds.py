"""workflow 11-15 (PM 16:42): answer-set builders run from the ops watch, once an hour, outside the quiet stretches."""
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ops_auto  # noqa: E402


def at(h, m):
    return time.mktime((2026, 11, 16, h, m, 0, 0, 0, -1))


def test_builders_run_hourly_until_their_split_is_in_the_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(ops_auto, "ACTIONS", tmp_path / "actions.md")
    gold = tmp_path / "gold"
    (gold / "s1").mkdir(parents=True)
    (gold / "s1" / "manifest.json").write_text(json.dumps({"files": {"done-split": {}}}))
    builds = (("m.one", "s1", "done-split"), ("m.two", "s2", "new"))
    ran = []

    def run(module):
        ran.append(module)
        return subprocess.CompletedProcess([], 0, json.dumps({"done": 2, "left": 27, "stopped": "system_share"}), "")
    kw = dict(run=run, state_path=tmp_path / "st.json", log_path=tmp_path / "log.jsonl", gold=gold, builds=builds)
    for quiet in (at(0, 20), at(1, 50), at(4, 20), at(6, 51), at(6, 57), at(7, 5)):
        assert ops_auto.gold_builds(clock=lambda q=quiet: q, **kw) is None
    lines = ops_auto.gold_builds(clock=lambda: at(2, 20), **kw)
    assert ran == ["m.two"] and lines[0]["result"]["left"] == 27 and lines[0]["builder"] == "two"
    assert ops_auto.gold_builds(clock=lambda: at(2, 40), **kw) == []        # once an hour
    ops_auto.gold_builds(clock=lambda: at(3, 20), **kw)
    assert ran == ["m.two", "m.two"]


def test_a_failing_builder_leaves_an_error_line(tmp_path, monkeypatch):
    monkeypatch.setattr(ops_auto, "ACTIONS", tmp_path / "actions.md")
    lines = ops_auto.gold_builds(clock=lambda: at(6, 20), run=lambda m: subprocess.CompletedProcess([], 1, "", "boom"),
                                 state_path=tmp_path / "st.json", log_path=tmp_path / "log.jsonl", gold=tmp_path,
                                 builds=(("m.x", "s", "p"),))
    assert lines[0]["ok"] is False and "exit 1" in lines[0]["error"]


def test_one_builder_per_round_taking_turns(tmp_path, monkeypatch):
    """ops review 11-15: a watch round runs one builder at most (it stays within 4 minutes)."""
    monkeypatch.setattr(ops_auto, "ACTIONS", tmp_path / "actions.md")
    ran = []

    def run(module):
        ran.append(module)
        return subprocess.CompletedProcess([], 0, json.dumps({"left": 1}), "")
    kw = dict(run=run, state_path=tmp_path / "st.json", log_path=tmp_path / "log.jsonl", gold=tmp_path,
              builds=(("m.a", "s", "p"), ("m.b", "s", "p"), ("m.c", "s", "p")))
    for minute in (10, 20, 30, 40):
        ops_auto.gold_builds(clock=lambda m=minute: at(6, m), **kw)
    assert ran == ["m.a", "m.b", "m.c"]                     # one each, then nothing left this hour


def test_holdout_r4_rests_on_1117_only_so_r5_gets_the_openalex_share(tmp_path, monkeypatch):
    """PM 11-16 17:36: OpenAlex allows 50 a day; on 11-17 holdout-r5 (round 2's answers, 40) builds first and r4 rests."""
    monkeypatch.setattr(ops_auto, "ACTIONS", tmp_path / "actions.md")
    builds = (("m.r4", "topic", "holdout-r4"), ("m.r5", "topic", "holdout-r5"))
    ran = []

    def run(module):
        ran.append(module)
        return subprocess.CompletedProcess([], 0, json.dumps({"done": 1, "left": 1}), "")
    kw = dict(run=run, state_path=tmp_path / "st.json", log_path=tmp_path / "log.jsonl", gold=tmp_path, builds=builds)
    day = lambda d, h, m: time.mktime((2026, 11, d, h, m, 0, 0, 0, -1))   # noqa: E731
    ops_auto.gold_builds(clock=lambda: day(17, 2, 20), **kw)
    ops_auto.gold_builds(clock=lambda: day(17, 3, 20), **kw)
    assert ran == ["m.r5", "m.r5"]                                  # r4 never on 11-17
    ops_auto.gold_builds(clock=lambda: day(18, 2, 20), **kw)
    assert ran[-1] == "m.r4"                                        # back in turn on 11-18
