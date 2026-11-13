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
    external = [r for r in runs if r.get("slug") == slug and r.get("source") == "external"]
    summary = {
        "quality": {
            "cases_today": len(cases_today), "success_today": success_today,
            "cases_7d": len(cases_week), "success_rate": week_rate,
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
        "agentvalcon_fallback_rate": agentcon_uses / slot_total if slot_total else None,
        "external_runs": {"total": len(external), "succeeded": sum(1 for r in external if r.get("outcome") == "succeeded")},
    }
    if success_today is not None and success_today < HOLD_SUCCESS:
        summary["held_reason"] = "quality_low"
    return summary


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
    return (f"{slug} v{version} | {status} | 7일 완주율 {pct(completion)} | Δ {delta} | p95 {p95} | "
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
        write_atomic(root / "results" / slug / "summary.json", summary)
        lines.append(digest_line(slug, defn["version"], defn["status"], summary))
        c = summary["completion"]
        if c["runs"] and c["completed"] / c["runs"] < ALERT_COMPLETION:
            alerts.append({"at": stamp, "slug": slug, "alert": "completion_below_95", "value": c["completed"] / c["runs"]})
        if summary.get("held_reason"):
            alerts.append({"at": stamp, "slug": slug, "alert": "hold", "reason": summary["held_reason"]})
    logs.mkdir(parents=True, exist_ok=True)
    (logs / f"{names[0]}.md").write_text("# 목걸이 점검 " + day.strftime("%Y-%m-%d") + "\n\n" +
                                         "".join(f"- {line}\n" for line in lines), encoding="utf-8")
    if alerts:
        with (logs / "alerts.jsonl").open("a", encoding="utf-8") as handle:
            for alert in alerts:
                handle.write(json.dumps(alert, ensure_ascii=False, sort_keys=True) + "\n")
    return {"necklaces": len(lines), "alerts": len(alerts), "digest": str(logs / f"{names[0]}.md")}
