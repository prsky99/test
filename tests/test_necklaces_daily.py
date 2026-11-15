import json
import time
from datetime import datetime

from agent_market.necklaces import daily, judge
from tests.test_necklaces_model import base

NOW = time.mktime((2026, 11, 20, 9, 15, 0, 0, 0, -1))
DAY = datetime.fromtimestamp(NOW).strftime("%Y%m%d")


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def case(i, ok=True, completed=True, external_only=True, rank=1, kind="external", latency=2000):
    return {"type": "case", "slug": "topic-brief", "version": 1, "case_id": f"c{i}", "set": "holdout-r1",
            "at": "2026-11-20T03:20:00Z", "ok": ok, "completed": completed,
            "completed_external_only": external_only, "latency_ms": latency,
            "slots": {"papers": {"rank": rank, "kind": kind}, "news": {"rank": 1, "kind": "external"}}}


def trial():
    defn = base()
    defn["status"] = "trial"
    return defn


def test_wilson_and_percentile():
    assert round(daily.wilson_lower(29, 30), 3) == 0.833
    assert daily.wilson_lower(0, 0) is None
    assert daily.percentile([1, 2, 3, 4, 100], 0.95) == 100
    assert daily.percentile([], 0.5) is None


def test_summary_digest_and_stage_two_alert(tmp_path):
    rows = [case(i, latency=1000 + i * 10) for i in range(29)] + [case(29, ok=False, rank=2)]
    singles = [{"type": "single", "slug": "topic-brief", "resource_id": 1, "tool": "t", "case_id": f"c{i}",
                "at": "2026-11-20T03:21:00Z", "ok": i < 24} for i in range(30)]
    write(tmp_path / "retest" / f"{DAY}.jsonl", rows + singles)
    write(tmp_path / "runs" / f"{DAY}.jsonl", [{"slug": "topic-brief", "source": "external", "outcome": "succeeded"},
                                               {"slug": "topic-brief", "source": "qa", "outcome": "succeeded"}])
    result = daily.run([trial()], tmp_path, tmp_path / "logs", now=NOW)
    summary = json.loads((tmp_path / "results" / "topic-brief" / "summary.json").read_text())
    q = summary["quality"]
    assert q["success_rate"] == 29 / 30 and q["best_single_rate"] == 0.8 and q["delta_pp"] == 16.7
    assert summary["fallback"]["papers"] == 1 / 30 and summary["external_runs"] == {"total": 1, "succeeded": 1}
    assert "held_reason" not in summary and result["alerts"] == 1  # stage 2 on papers
    line = (tmp_path / "logs" / f"{DAY}.md").read_text()
    assert "topic-brief v1 | trial | 2단계 | 7일 완주율 100%" in line and "AgentValCon 사용률 0%" in line
    assert summary["stage"]["slots"] == {"papers": 2, "news": 1} and summary["stage"]["max"] == 2
    entry = judge.build_entry(dict(trial(), status="live"), None, summary, NOW)
    assert entry["held_reason"] == "not_approved"  # summary alone never makes it live


def test_low_success_holds_and_alerts(tmp_path):
    rows = [case(i, ok=i < 20, completed=i < 25, external_only=False, kind="agentcon", rank=3) for i in range(30)]
    write(tmp_path / "retest" / f"{DAY}.jsonl", rows)
    result = daily.run([trial()], tmp_path, tmp_path / "logs", now=NOW)
    summary = json.loads((tmp_path / "results" / "topic-brief" / "summary.json").read_text())
    assert summary["held_reason"] == "quality_low"
    assert summary["agentvalcon_fallback_rate"] == 0.5
    alerts = [json.loads(l) for l in (tmp_path / "logs" / "alerts.jsonl").read_text().splitlines()]
    assert {a["alert"] for a in alerts} == {"completion_below_95", "hold", "stage3"} and result["alerts"] == 3


def test_candidates_are_skipped_and_missing_retest_is_reported(tmp_path):
    result = daily.run([base(), trial()], tmp_path, tmp_path / "logs", now=NOW)
    assert result["necklaces"] == 1
    assert "no retest today" in (tmp_path / "logs" / f"{DAY}.md").read_text()


def test_stage_alert_only_when_a_slot_gets_worse(tmp_path):
    rows = [case(i) for i in range(29)] + [case(29, rank=2)]
    write(tmp_path / "retest" / f"{DAY}.jsonl", rows)
    first = daily.run([trial()], tmp_path, tmp_path / "logs", now=NOW)
    second = daily.run([trial()], tmp_path, tmp_path / "logs", now=NOW + 60)
    assert first["alerts"] == 1 and second["alerts"] == 0


def test_stage_four_holds_when_a_required_slot_fails_in_a_fifth_of_cases(tmp_path):
    rows = [case(i) for i in range(24)]
    for i in range(24, 30):
        r = case(i, ok=False, completed=False, external_only=False)
        r["slots"]["papers"] = {"rank": 5, "kind": "agentcon", "failed": True}
        rows.append(r)
    write(tmp_path / "retest" / f"{DAY}.jsonl", rows)
    daily.run([trial()], tmp_path, tmp_path / "logs", now=NOW)
    summary = json.loads((tmp_path / "results" / "topic-brief" / "summary.json").read_text())
    assert summary["held_reason"] == "stage4" and summary["stage"]["failed"] == {"papers": 6}
    alerts = [json.loads(l)["alert"] for l in (tmp_path / "logs" / "alerts.jsonl").read_text().splitlines()]
    assert {"stage4", "stage4_hold", "hold"} <= set(alerts)
    assert "4단계" in (tmp_path / "logs" / f"{DAY}.md").read_text()


def test_cumulative_counts_live_retests_once_a_day_and_restarts_on_a_new_version(tmp_path):
    live = dict(trial(), status="live")
    write(tmp_path / "retest" / f"{DAY}.jsonl", [case(i, ok=i != 0) for i in range(30)])
    daily.run([live], tmp_path, tmp_path / "logs", now=NOW)
    daily.run([live], tmp_path, tmp_path / "logs", now=NOW + 600)          # same day again: no double count
    q = json.loads((tmp_path / "results" / "topic-brief" / "summary.json").read_text())["quality"]
    assert q["cumulative"]["cases"] == 30 and q["cumulative"]["passed"] == 29
    assert q["success_7d"] == 29 and q["cases_7d"] == 30
    next_day = NOW + 86400
    write(tmp_path / "retest" / f"{datetime.fromtimestamp(next_day).strftime('%Y%m%d')}.jsonl", [case(i) for i in range(30)])
    daily.run([live], tmp_path, tmp_path / "logs", now=next_day)
    q = json.loads((tmp_path / "results" / "topic-brief" / "summary.json").read_text())["quality"]
    assert q["cumulative"] == {"cases": 60, "passed": 59, "since": q["cumulative"]["since"]}
    daily.run([dict(live, version=2)], tmp_path, tmp_path / "logs", now=next_day + 60)
    q = json.loads((tmp_path / "results" / "topic-brief" / "summary.json").read_text())["quality"]
    assert q["cumulative"]["cases"] == 0                                    # a new version starts over


def test_cumulative_is_absent_before_launch(tmp_path):
    write(tmp_path / "retest" / f"{DAY}.jsonl", [case(i) for i in range(30)])
    daily.run([trial()], tmp_path, tmp_path / "logs", now=NOW)
    q = json.loads((tmp_path / "results" / "topic-brief" / "summary.json").read_text())["quality"]
    assert q["cumulative"] is None


def test_digest_has_a_body_with_nothing_to_summarize(tmp_path):
    result = daily.run([base(), base()], tmp_path, tmp_path / "logs", now=NOW)
    text = (tmp_path / "logs" / f"{DAY}.md").read_text()
    assert result == {"necklaces": 0, "alerts": 0, "digest": str(tmp_path / "logs" / f"{DAY}.md")}
    assert "목걸이 0개 집계, 경보 0건. 정의 2개(candidate 2)." in text and "집계할 것이 없습니다(정상)" in text


# ---------------------------------------------------------------- R23: the delta is paired and never inflated
def test_delta_needs_the_same_cases_on_the_same_day():
    cases = [case(i) for i in range(12)]
    other_day = [{"type": "single", "slug": "topic-brief", "resource_id": 1, "tool": "t", "case_id": f"c{i}",
                  "at": "2026-11-17T03:00:00Z", "ok": False} for i in range(12)]
    assert daily.paired_delta("topic-brief", cases, other_day) is None            # no pairs: no delta, no claim
    same_day = [dict(r, at="2026-11-20T03:21:00Z") for r in other_day[:9]]
    assert daily.paired_delta("topic-brief", cases, same_day) is None             # fewer than MIN_PAIRS


def test_all_correct_members_give_no_delta_even_when_our_budget_refused_some_singles(tmp_path):
    """PM R23 reproduction: with every member always right the delta must be about 0 (it was +13.3 when budget
    refusals counted as single failures)."""
    from agent_market.necklaces import model, retest, runner
    import copy
    defn = copy.deepcopy(next(d for d in model.load_valid() if d["slug"] == "package-risk-audit"))
    for slot in defn["slots"]:                  # every member counts here (the shipped health slot waits for members)
        for m in slot["chain"]:
            m["state"] = "active"
    cases = [{"case_id": f"p{i}", "input": {"package": f"pkg{i}", "ecosystem": "npm"},
              "truth": {"advisories": [], "latest_version": "9.9.9"}} for i in range(15)]
    calls = {"n": 0}

    def caller(member, args, timeout):
        calls["n"] += 1
        if calls["n"] % 4 == 0:
            raise runner.BudgetDenied("domain_total")          # our ledger said no: says nothing about the member
        return {"vulns": [], "version": "9.9.9", "latest": "9.9.9"}
    out = retest.run_set(defn, cases, caller, root=tmp_path, split="tuning", singles=True)
    lines = [json.loads(x) for x in next((tmp_path / "retest").glob("*.jsonl")).read_text().splitlines()]
    singles = [x for x in lines if x["type"] == "single"]
    assert any(x["ok"] is None for x in singles) and not any(x["ok"] is False for x in singles)
    paired = daily.paired_delta("package-risk-audit", lines, singles)
    assert out["passed"] + out["excluded"] == 15
    assert paired is not None and paired["delta_pp"] == 0.0
