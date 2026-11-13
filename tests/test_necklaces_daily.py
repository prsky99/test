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
                "at": "2026-11-17T03:00:00Z", "ok": i < 24} for i in range(30)]
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
