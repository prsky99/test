"""PM 11-16 15:02: the gate round exclusion rule, run outside the harness (scripts/gate_round.py)."""
import json

from scripts import gate_round as G

AT = "2026-11-17T06:20:00+09:00"


def line(case, kind, ok=None, split="holdout-r4-wiki", at=AT):
    out = {"slug": "topic-evidence-brief", "version": 1, "set": split, "case_id": case, "type": kind, "at": at}
    if kind == "case":
        out["ok"] = ok
    else:
        out["why"] = "relay_throttled"
    return out


def first(passed, failed, excluded):
    return ([line(f"p{i}", "case", True) for i in range(passed)] + [line(f"f{i}", "case", False) for i in range(failed)]
            + [line(f"x{i}", "excluded") for i in range(excluded)])


def test_the_three_results_and_the_fixed_denominator():
    assert G.result(first(28, 2, 0), "holdout-r4-wiki")["verdict"] == "pass"
    assert G.result(first(27, 3, 0), "holdout-r4-wiki")["verdict"] == "fail"
    body = G.result(first(26, 1, 3), "holdout-r4-wiki")
    assert body["verdict"] == "rerun_due" and body["rerun_due"] == ["x0", "x1", "x2"]
    again = [line("x0", "case", True, "holdout-r4-wiki-rerun"), line("x1", "case", True, "holdout-r4-wiki-rerun"),
             line("x2", "excluded", split="holdout-r4-wiki-rerun")]
    body = G.result(first(26, 1, 3) + again, "holdout-r4-wiki")
    assert (body["verdict"], body["passed"], body["failed"], body["unmeasured"]) == ("pass", 28, 1, 1)
    again[1] = line("x1", "case", False, "holdout-r4-wiki-rerun")
    body = G.result(first(26, 1, 3) + again, "holdout-r4-wiki")
    assert (body["verdict"], body["passed"], body["failed"], body["unmeasured"]) == ("unmeasured", 27, 2, 1)
    # 22 of 30 set apart and still no answer (company v2 round 1, 11-16): unmeasured, not a failure
    still = [line(f"x{i}", "excluded", split="holdout-r4-wiki-rerun") for i in range(22)]
    assert G.result(first(7, 1, 22) + still, "holdout-r4-wiki")["verdict"] == "unmeasured"
    # an excluded case is never a pass; a case with an answer is never measured again
    assert G.result(first(28, 0, 2), "holdout-r4-wiki")["rerun_due"] == ["x0", "x1"]
    assert G.result(first(30, 0, 0), "holdout-r4-wiki")["rerun_due"] == []


def test_the_rerun_window():
    end = G._ts(AT)                                          # 06:20
    assert G.rerun_window(end, end + 5 * 60).startswith("too early")
    assert G.rerun_window(end, end + 10 * 60) is None and G.rerun_window(end, end + 30 * 60) is None
    assert G.rerun_window(end, end + 61 * 60).startswith("too late")
    # ops 11-16: never in the hourly measurement window :55-:10 (06:55 and 07:05 here), 07:10 is fine again
    assert "measurement" in G.rerun_window(end, end + 35 * 60) and "measurement" in G.rerun_window(end, end + 45 * 60)
    assert G.rerun_window(end, end + 50 * 60) is None


def test_rerun_measures_only_the_excluded_cases_once(tmp_path, monkeypatch):
    day = "20261117"
    (tmp_path / "retest").mkdir()
    (tmp_path / "retest" / f"{day}.jsonl").write_text("".join(json.dumps(l) + "\n" for l in first(27, 1, 2)))
    from agent_market.necklaces import model, retest
    monkeypatch.setattr(retest, "load_cases", lambda root, slug, split: [{"case_id": c} for c in
                                                                         ("p0", "f0", "x0", "x1")])
    # The fixture round ran v1; the real topic-evidence-brief is v2 since 11-17 13:15 (a0594a38), and gate_round rightly
    # refuses a rerun of a round that ran an older version ("the round ran v1; the definition is now v2", exit 2).
    # The test must not depend on the live definition's version (it failed at night 11-18 05:05 for that reason).
    monkeypatch.setattr(model, "load_valid", lambda *a, **k: [{"slug": "topic-evidence-brief", "version": 1,
                                                                 "slots": []}])
    asked = []

    def fake(defn, cases, data, split, system, base):
        asked.append(sorted(c["case_id"] for c in cases))
        with (data / "retest" / f"{day}.jsonl").open("a") as handle:
            handle.write(json.dumps(line("x0", "case", True, split + "-rerun")) + "\n")
            handle.write(json.dumps(line("x1", "excluded", split=split + "-rerun")) + "\n")
        return {"cases": 1, "passed": 1, "excluded": 1}
    argv = ["rerun", "topic-evidence-brief", "--split", "holdout-r4-wiki", "--day", day, "--version", "1",
            "--data", str(tmp_path), "--out", str(tmp_path / "out")]
    early = G.main(argv, now=lambda: G._ts(AT) + 60, runner_fn=fake)
    assert early == 75 and asked == []
    assert G.main(argv, now=lambda: G._ts(AT) + 15 * 60, runner_fn=fake) == 0
    assert asked == [["x0", "x1"]]
    saved = json.loads(next((tmp_path / "out").glob("round-*.json")).read_text())
    assert (saved["verdict"], saved["passed"], saved["unmeasured"]) == ("pass", 28, 1)
    # run again: nothing is due any more, nothing is measured again, and the first file stays
    assert G.main(argv, now=lambda: G._ts(AT) + 20 * 60, runner_fn=fake) == 0 and asked == [["x0", "x1"]]
    assert len(list((tmp_path / "out").glob("round-*.json"))) == 2


def test_the_first_line_of_a_case_counts_and_a_short_round_is_incomplete():
    """PM 15:10: running the same split again never turns an answered failure into a pass; under 30 is no verdict."""
    lines = first(27, 3, 0) + [line("f0", "case", True), line("f1", "case", True)]
    body = G.result(lines, "holdout-r4-wiki")
    assert (body["verdict"], body["passed"], body["failed"]) == ("fail", 27, 3)
    assert body["duplicates"] == ["holdout-r4-wiki:f0", "holdout-r4-wiki:f1"] and "first line counts" in body["warning"]
    assert G.result(first(28, 2, 0), "holdout-r4-wiki")["warning"] is None
    short = G.result(first(20, 0, 0), "holdout-r4-wiki")
    assert (short["verdict"], short["measured"]) == ("incomplete", 20)
    assert G.result(first(25, 0, 3), "holdout-r4-wiki")["verdict"] == "incomplete"
