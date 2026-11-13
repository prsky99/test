"""Daily necklace aggregation: retest lines -> judge summaries, a readable digest and alerts.

Retest lines (``<root>/retest/<YYYYMMDD>.jsonl``, written by the single retest
runner for live necklaces at 03:10 and trial necklaces at 01:15) come in three types:

- ``{"type": "member", slug, version, slot, resource_id, tool, at, ok, contract_valid,
  latency_ms, fingerprint, fingerprint_changed, error_class}`` (design b-5)
- ``{"type": "case", slug, version, case_id, set, at, ok, completed,
  completed_external_only, latency_ms, slots: {slot: {"rank": n, "kind": k}}}``
- ``{"type": "single", slug, resource_id, tool, case_id, at, ok}`` (weekly baseline)

Run events (``<root>/runs/<YYYYMMDD>.jsonl``, no input or output) add the external
execution counts that feed the north star.

Outputs: ``results/<slug>/summary.json`` (what the judge reads), the day's digest
``logs/ops/necklace-watch/<YYYYMMDD>.md`` and ``alerts.jsonl``.
"""
from __future__ import annotations

import json
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .judge import write_atomic

ALERT_COMPLETION = 0.95
HOLD_SUCCESS = 0.80
WINDOW_DAYS = 7


def wilson_lower(k: int, n: int, z: float = 1.96) -> float | None:
    if n <= 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - r) / d


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1))
    return ordered[idx]


def read_lines(path: Path) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def days_back(day: datetime, n: int) -> list[str]:
    return [(day - timedelta(days=i)).strftime("%Y%m%d") for i in range(n)]


STAGE4_SHARE = 0.20    # share of today's cases where a required slot failed after every fallback


def day_stages(cases: list[dict]) -> tuple[dict[str, int], dict[str, int]]:
    """Charter stages per slot from one day's cases: (worst stage, cases failed after all fallbacks)."""
    stages: dict[str, int] = {}
    failed: dict[str, int] = {}
    for r in cases:
        for slot, used in (r.get("slots") or {}).items():
            used = used or {}
            # The runner writes the stage itself (it knows the fan-out); older lines fall back to rank and kind.
            stage = used.get("stage") or (4 if used.get("failed") else 3 if used.get("kind") == "agentcon"
                                          else 2 if (used.get("rank") or 1) > 1 else 1)
            stages[slot] = max(stages.get(slot, 1), stage)
            if used.get("failed"):
                failed[slot] = failed.get(slot, 0) + 1
    return stages, failed


def summarize(slug: str, today: list[dict], window: list[dict], singles: list[dict], runs: list[dict]) -> dict:
    cases_today = [r for r in today if r.get("type") == "case" and r.get("slug") == slug]
    cases_week = [r for r in window if r.get("type") == "case" and r.get("slug") == slug]
    ok_today = sum(1 for r in cases_today if r.get("ok"))
    ok_week = sum(1 for r in cases_week if r.get("ok"))
    success_today = ok_today / len(cases_today) if cases_today else None
    by_member: dict[tuple, list[bool]] = {}
    for r in singles:
        if r.get("slug") == slug and r.get("type") == "single":
            by_member.setdefault((r.get("resource_id"), r.get("tool")), []).append(bool(r.get("ok")))
    best_single = max((sum(v) / len(v) for v in by_member.values() if v), default=None)
    week_rate = ok_week / len(cases_week) if cases_week else None
    delta = round((week_rate - best_single) * 100, 1) if week_rate is not None and best_single is not None else None
    latencies = [r["latency_ms"] for r in cases_week if isinstance(r.get("latency_ms"), (int, float))]
    slot_counts: dict[str, list[int]] = {}
    fallback_uses = agentcon_uses = slot_total = 0
    for r in cases_week:
        for slot, used in (r.get("slots") or {}).items():
            slot_counts.setdefault(slot, [0, 0])
            slot_counts[slot][1] += 1
            slot_total += 1
            if (used or {}).get("rank", 1) > 1:
                slot_counts[slot][0] += 1
                fallback_uses += 1
            if (used or {}).get("kind") == "agentcon":
                agentcon_uses += 1
    stages, failed = day_stages(cases_today)
    # North star: external clients only. Our own runs carry an internal origin and are never counted.
    from .runner import OUR_ORIGINS
    external = [r for r in runs if r.get("slug") == slug and r.get("source") == "external"
                and r.get("origin") not in OUR_ORIGINS]
    summary = {
        "quality": {
            "cases_today": len(cases_today), "success_today": success_today,
            "cases_7d": len(cases_week), "success_7d": ok_week, "success_rate": week_rate,
            "lower_bound": wilson_lower(ok_week, len(cases_week)),
            "best_single_rate": best_single, "delta_pp": delta,
            "baseline_at": max((r.get("at", "") for r in singles if r.get("slug") == slug), default=None),
            # The judge holds a necklace whose last retest is older than 48 hours, so this is
            # the latest case in the window, not only today's.
            "tested_at": max((r.get("at", "") for r in cases_week), default=None) or None,
        },
        "completion": {
            "runs": len(cases_week),
            "completed": sum(1 for r in cases_week if r.get("completed")),
            "completed_external_only": sum(1 for r in cases_week if r.get("completed_external_only")),
        },
        "cost": {"usdc_per_run": 0, "p50_ms": percentile(latencies, 0.5), "p95_ms": percentile(latencies, 0.95)},
        "fallback": {slot: (c[0] / c[1] if c[1] else None) for slot, c in slot_counts.items()},
        # Charter stages (user 11-14) from today's cases: 1 normal, 2 an external fallback ran,
        # 3 an AgentValCon fallback ran, 4 the slot failed even after every fallback.
        "stage": {"slots": stages, "failed": failed, "max": max(stages.values(), default=1)},
        "agentvalcon_fallback_rate": agentcon_uses / slot_total if slot_total else None,
        "external_runs": {"total": len(external), "succeeded": sum(1 for r in external if r.get("outcome") == "succeeded")},
    }
    if success_today is not None and success_today < HOLD_SUCCESS:
        summary["held_reason"] = "quality_low"
    return summary


def cumulate(root: Path, defn: dict, today: list[dict], day: str, stamp: str) -> dict | None:
    """Retest cases since the necklace went live, added once per day and restarted for a new version.

    The surface writes "Verified 95%" only when cases >= 110 and at most one failed (PM 11-14)."""
    path = root / "results" / defn["slug"] / "cumulative.json"
    try:
        acc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        acc = {}
    if defn.get("status") != "live":
        return acc.get("public") if acc.get("version") == defn["version"] else None
    if acc.get("version") != defn["version"]:
        acc = {"version": defn["version"], "days": [], "public": {"cases": 0, "passed": 0, "since": stamp}}
    if day not in acc["days"]:
        cases = [r for r in today if r.get("type") == "case" and r.get("slug") == defn["slug"]
                 and r.get("version") == defn["version"]]
        acc["public"]["cases"] += len(cases)
        acc["public"]["passed"] += sum(1 for r in cases if r.get("ok"))
        acc["days"] = (acc["days"] + [day])[-400:]
        write_atomic(path, acc)
    return acc["public"]


def digest_line(slug: str, version, status: str, s: dict) -> str:
    q, c = s["quality"], s["completion"]
    completion = c["completed"] / c["runs"] if c["runs"] else None
    worst = max((v for v in s["fallback"].values() if v is not None), default=None)
    problems = []
    if s.get("held_reason"):
        problems.append(s["held_reason"])
    if completion is not None and completion < ALERT_COMPLETION:
        problems.append("completion below 95%")
    if q["cases_today"] == 0:
        problems.append("no retest today")

    def pct(v):
        return "-" if v is None else f"{v * 100:.0f}%"
    delta = "-" if q["delta_pp"] is None else f"{q['delta_pp']:+.1f}%p ({(q['baseline_at'] or '-')[:10]})"
    p95 = "-" if s["cost"]["p95_ms"] is None else f"{s['cost']['p95_ms'] / 1000:.1f}s"
    return (f"{slug} v{version} | {status} | {s['stage']['max']}단계 | 7일 완주율 {pct(completion)} | Δ {delta} | p95 {p95} | "
            f"대체 발생률 최대 {pct(worst)} | AgentValCon 사용률 {pct(s['agentvalcon_fallback_rate'])} | "
            f"외부 실행 성공 {s['external_runs']['succeeded']} | 문제 {', '.join(problems) or '없음'}")


def run(definitions: list[dict], root: Path, logs: Path, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    day = datetime.fromtimestamp(now)
    names = days_back(day, WINDOW_DAYS)
    today = read_lines(root / "retest" / f"{names[0]}.jsonl")
    window = [r for name in names for r in read_lines(root / "retest" / f"{name}.jsonl")]
    singles = [r for name in days_back(day, 14) for r in read_lines(root / "retest" / f"{name}.jsonl")
               if r.get("type") == "single"]
    runs = [r for name in names for r in read_lines(root / "runs" / f"{name}.jsonl")]
    lines, alerts = [], []
    stage_path = root / "watch" / "stages.json"
    try:
        stage_state = json.loads(stage_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stage_state = {}
    stamp = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for defn in definitions:
        if defn.get("status") not in ("qualifying", "trial", "live", "held"):
            continue
        slug = defn["slug"]
        summary = summarize(slug, today, window, singles, runs)
        previous = {}
        try:
            previous = json.loads((root / "results" / slug / "summary.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        for key in ("template_id",):
            if key in previous:
                summary[key] = previous[key]
        summary["quality"]["cumulative"] = cumulate(root, defn, today, names[0], stamp)
        # Stage alerts only when a slot reaches a higher stage than it had (the first stage 2
        # goes to PM the same day so the agent team can build that slot's fallback). A required
        # slot that failed after every fallback in 20% of today's cases, or two days running,
        # holds the necklace at once (stage 4); retiring and replacing it is a workflow-team call.
        required = {sl["slot"] for sl in defn["slots"] if sl.get("required", True)}
        cases_today = summary["quality"]["cases_today"]
        if cases_today:
            for slot, stage in summary["stage"]["slots"].items():
                key = f"{slug}|{slot}"
                before = stage_state.get(key, {})
                streak4 = before.get("stage4_days", 0) + 1 if stage == 4 else 0
                if stage >= 2 and stage > before.get("stage", 1):
                    alerts.append({"at": stamp, "slug": slug, "alert": f"stage{stage}", "slot": slot})
                stage_state[key] = {"stage": stage, "stage4_days": streak4,
                                    "since": before.get("since") if stage == before.get("stage") else stamp}
                share = summary["stage"]["failed"].get(slot, 0) / cases_today
                if slot in required and stage == 4 and (streak4 >= 2 or share >= STAGE4_SHARE):
                    summary["held_reason"] = "stage4"
                    alerts.append({"at": stamp, "slug": slug, "alert": "stage4_hold", "slot": slot,
                                   "share": round(share, 3), "days": streak4})
        write_atomic(root / "results" / slug / "summary.json", summary)
        lines.append(digest_line(slug, defn["version"], defn["status"], summary))
        c = summary["completion"]
        if c["runs"] and c["completed"] / c["runs"] < ALERT_COMPLETION:
            alerts.append({"at": stamp, "slug": slug, "alert": "completion_below_95", "value": c["completed"] / c["runs"]})
        if summary.get("held_reason"):
            alerts.append({"at": stamp, "slug": slug, "alert": "hold", "reason": summary["held_reason"]})
    write_atomic(stage_path, stage_state)
    logs.mkdir(parents=True, exist_ok=True)
    (logs / f"{names[0]}.md").write_text("# 목걸이 점검 " + day.strftime("%Y-%m-%d") + "\n\n" +
                                         "".join(f"- {line}\n" for line in lines), encoding="utf-8")
    if alerts:
        with (logs / "alerts.jsonl").open("a", encoding="utf-8") as handle:
            for alert in alerts:
                handle.write(json.dumps(alert, ensure_ascii=False, sort_keys=True) + "\n")
    return {"necklaces": len(lines), "alerts": len(alerts), "digest": str(logs / f"{names[0]}.md")}
