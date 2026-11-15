"""The necklace north star from run events, one definition for every reader (PM F09, 11-14/15).

Charter section 0: the north star is successful necklace runs by outside clients per day. The input is the body-free
run event the public run entry writes (gateway-data/necklaces/runs/<YYYYMMDD>.jsonl). The daily summary, the board
(scripts/north_star.py) and the public figures all count with ``count`` below, so their denominators agree:

- one outside run that finished counts once: events are de-duplicated by run_id (a re-collected file or a replayed
  line is not counted twice; an old event without run_id is keyed by its time, necklace, surface and origin)
- QA, our own checks and monitors (source internal, an origin of ours) count 0; crawlers and probes are kept apart
- an answer from the short result cache is a served answer, not a run: counted as cached, not as a success
- a run that failed only because our side was full (our_capacity) is counted apart, not as a members' failure
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

METRIC_ID = "necklace_external_successes"
DEFINITION_VERSION = 1


def _key(event: dict) -> tuple:
    if event.get("run_id"):
        return ("id", event["run_id"])
    return ("line", event.get("at"), event.get("slug"), event.get("surface"), event.get("source"), event.get("origin"),
            event.get("outcome"), event.get("latency_ms"))


def count(events: list[dict], slug: str | None = None) -> dict:
    """Counts for one day's events (all necklaces, or one)."""
    from .runner import OUR_ORIGINS
    seen, out = set(), {"external_runs": 0, "succeeded": 0, "failed": 0, "cached": 0, "our_capacity": 0,
                        "internal": 0, "crawler": 0, "probe": 0, "duplicates": 0, "by_slug": {}}
    for event in events:
        if slug is not None and event.get("slug") != slug:
            continue
        key = _key(event)
        if key in seen:
            out["duplicates"] += 1
            continue
        seen.add(key)
        source = event.get("source")
        if source != "external" or event.get("origin") in OUR_ORIGINS:
            bucket = source if source in ("crawler", "probe") else "internal"
            out[bucket] += 1
            continue
        per = out["by_slug"].setdefault(event.get("slug"), {"external_runs": 0, "succeeded": 0})
        if event.get("cached"):
            out["cached"] += 1
            continue
        out["external_runs"] += 1
        per["external_runs"] += 1
        if event.get("outcome") == "succeeded":
            out["succeeded"] += 1
            per["succeeded"] += 1
        elif event.get("our_capacity"):
            out["our_capacity"] += 1
        else:
            out["failed"] += 1
    return out


def read_day(root: Path, day: str) -> list[dict]:
    """day as YYYYMMDD; unreadable lines are skipped."""
    path = Path(root) / "runs" / f"{day}.jsonl"
    events = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    return events


KST = timezone(timedelta(hours=9))


def kst_day(at: str) -> str | None:
    try:
        return datetime.strptime(at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(KST).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def day_events(root: Path, day: str) -> list[dict]:
    """The events of one KST day (YYYY-MM-DD): run files are named by UTC date, so the day before is read too."""
    date = datetime.strptime(day, "%Y-%m-%d")
    events = read_day(root, (date - timedelta(days=1)).strftime("%Y%m%d")) + read_day(root, date.strftime("%Y%m%d"))
    return [e for e in events if kst_day(e.get("at", "")) == day]


def day_metric(root: Path, day: str) -> dict:
    """The board's line for one KST day (YYYY-MM-DD)."""
    counts = count(day_events(root, day))
    return {"metric_id": METRIC_ID, "definition_version": DEFINITION_VERSION, "day": day,
            "value": counts["succeeded"], **counts}
