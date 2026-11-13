"""Hourly watch of the AgentValCon fallback agents (PM 11-14: the same standing watch as necklace members).

Recorded every hour (jobs maintenance slot, same shape and quiet windows as ``necklaces.watch``):

- source health per agent, from the agent's own usage lines of the last hour (no extra outside calls, so the
  daily per-domain test budget is not spent on watching)
- snapshot age of the local copies: NVD (limit 6 h), airport index (8 days), KEV catalog copy (24 h)
- quota state: GitHub's unauthenticated core allowance through ``/rate_limit`` (that endpoint is not counted)
  and today's shared test-budget ledger for our hosts
- stale failures in the hour

Alerts (at most one a day per key): a snapshot past its age limit, an agent failing several calls in a row
(source_unavailable, rate_limited or stale), and the GitHub allowance used up or nearly so.

Writes ``<data>/watch/state.json`` and appends one line per round to ``<data>/watch/<date>.jsonl``.
``health(agent_id)`` lets the necklace watch read an agent's state.
"""
from __future__ import annotations

import json
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .catalog import SPECS

FAIL_CODES = ("source_unavailable", "rate_limited", "stale")
FAIL_STREAK = 3          # failed calls in a row before an agent counts as failing
GITHUB_LOW = 5           # remaining GitHub calls in the hour below which we alert
GITHUB_AGENTS = ("github-advisory", "software-incident", "github-repo")
SNAPSHOTS = {  # name -> (file under the data folder, age field, limit seconds, agents that read it)
    "nvd": ("nvd-cve.sqlite3", "sqlite:synced_at", 6 * 3600, ("nvd-cve", "software-incident")),
    "airports": ("airports.json", "json:fetched_at", 8 * 86400, ("airport-lookup",)),
    "kev": ("kev-catalog.json", "json:fetched_at", 24 * 3600, ("cisa-kev",)),
}


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def data_root(data_dir=None) -> Path:
    return Path(data_dir or os.environ.get("FALLBACK_AGENTS_DATA", "gateway-data/fallback-agents"))


def snapshot_age(root: Path, file: str, field: str, now: float):
    path = root / file
    if not path.exists():
        return None
    try:
        if field == "sqlite:synced_at":
            import sqlite3
            db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1.0)
            try:
                row = db.execute("SELECT value FROM meta WHERE key='synced_at'").fetchone()
            finally:
                db.close()
            return max(0.0, now - float(row[0])) if row else None
        if field == "json:fetched_at":
            with path.open(encoding="utf-8") as fh:
                head = fh.read(200)  # fetched_at is written first; avoid parsing a 15 MB index every hour
            mark = head.find('"fetched_at":')
            if mark >= 0:
                value = head[mark + 13:].split(",")[0].split("}")[0]
                return max(0.0, now - float(value))
            return max(0.0, now - float(json.loads(path.read_text(encoding="utf-8"))["fetched_at"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return None


def usage_lines(root: Path, since: float, now: float) -> list[dict]:
    lines = []
    for day in sorted({_iso(since)[:10], _iso(now)[:10]}):  # each day file once
        path = root / "usage" / f"{day}.jsonl"
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for raw in text.splitlines():
            try:
                row = json.loads(raw)
                at = datetime.strptime(row["at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
            except (ValueError, KeyError, TypeError):
                continue
            if since < at <= now:
                row["_ts"] = at
                lines.append(row)
    lines.sort(key=lambda r: r["_ts"])
    return lines


def github_quota(fetch=None):
    """(remaining, limit, reset epoch) of the unauthenticated core allowance, or None. /rate_limit is not counted."""
    try:
        if fetch is None:
            from .limits import limiters
            from .net import get
            response = get("https://api.github.com/rate_limit", limiters=limiters(), seconds=5, limit=65536)
            data = json.loads(response.content)
        else:
            data = fetch()
        core = data["resources"]["core"]
        return int(core["remaining"]), int(core["limit"]), int(core["reset"])
    except Exception:
        return None


def observe(state: dict, root: Path, now: float, quota) -> dict:
    """One round; mutates ``state``; returns the observation line."""
    agents = state.setdefault("agents", {})
    lines = usage_lines(root, now - 3600, now)
    by_agent: dict[str, list[dict]] = {}
    for row in lines:
        by_agent.setdefault(row.get("agent"), []).append(row)
    alerts, report = [], {}
    for agent_id in sorted(SPECS):
        mark = agents.setdefault(agent_id, {"fail_streak": 0})
        rows = by_agent.get(agent_id, [])
        for row in rows:  # streak over calls, carried across hours
            mark["fail_streak"] = mark["fail_streak"] + 1 if row.get("code") in FAIL_CODES else 0
        codes = Counter(row.get("code") or "ok" for row in rows)
        # not_found and invalid_input are answers about the request, not source trouble.
        source_failures = sum(codes[c] for c in FAIL_CODES)
        status = ("failing" if mark["fail_streak"] >= FAIL_STREAK else "idle" if not rows else
                  "degraded" if source_failures > len(rows) / 2 else "healthy")
        mark.update(status=status, last=_iso(now), calls=len(rows))
        report[agent_id] = {"status": status, "calls": len(rows), "ok": codes["ok"], "source_failures": source_failures,
                            "stale": codes["stale"],
                            "rate_limited": codes["rate_limited"], "fail_streak": mark["fail_streak"]}
        if status == "failing":
            alerts.append(("source_failing:" + agent_id, f"{agent_id} failed {mark['fail_streak']} calls in a row"))
    snapshots = {}
    for name, (file, field, limit, readers) in SNAPSHOTS.items():
        age = snapshot_age(root, file, field, now)
        over = age is not None and age > limit
        snapshots[name] = {"age_seconds": None if age is None else int(age), "limit_seconds": limit,
                           "over_limit": over, "present": age is not None}
        if over:
            alerts.append(("snapshot_stale:" + name, f"{name} snapshot is {int(age)} s old (limit {limit} s), "
                                                     f"used by {', '.join(readers)}"))
    quotas = {}
    if quota:
        remaining, limit, reset = quota
        quotas["github_core"] = {"remaining": remaining, "limit": limit, "reset": _iso(reset)}
        if remaining < GITHUB_LOW:
            alerts.append(("quota_low:github", f"GitHub unauthenticated allowance {remaining}/{limit} left until "
                                               f"{_iso(reset)}; affects {', '.join(GITHUB_AGENTS)}"))
    else:
        quotas["github_core"] = None
    try:
        from ..provider_budget import status as ledger
        hosts = {"nvd.nist.gov", "services.nvd.nist.gov", "cveawg.mitre.org", "www.cisa.gov", "api.first.org",
                 "api.github.com", "api.deps.dev", "api.scorecard.dev", "api.gleif.org", "data.sec.gov"}
        from ..provider_budget import domain
        mine = {domain("https://" + h) for h in hosts}
        quotas["test_budget"] = {d: v for d, v in (ledger().get("domains") or {}).items() if d in mine}
    except Exception:
        quotas["test_budget"] = None
    sent = state.setdefault("alerts_sent", {})
    day = _iso(now)[:10]
    fresh = []
    for key, text in alerts:
        if sent.get(key) != day:  # one alert a day per key
            sent[key] = day
            fresh.append({"key": key, "text": text})
    line = {"at": _iso(now), "agents": report, "snapshots": snapshots, "quotas": quotas,
            "stale_failures": sum(r["stale"] for r in report.values()), "alerts": fresh,
            "open_problems": sorted(k for k, _ in alerts)}
    state["last"] = line
    return line


def health(agent_id: str, data_dir=None) -> dict:
    """The agent's last watched state for the necklace watch: {"status": healthy|degraded|failing|idle|unknown}."""
    try:
        state = json.loads((data_root(data_dir) / "watch" / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "unknown"}
    mark = (state.get("agents") or {}).get(agent_id) or {}
    problems = set((state.get("last") or {}).get("open_problems") or [])
    snapshot_problem = any(agent_id in readers and f"snapshot_stale:{name}" in problems
                           for name, (_, _, _, readers) in SNAPSHOTS.items())
    status = "failing" if snapshot_problem else mark.get("status", "unknown")
    return {"status": status, "fail_streak": mark.get("fail_streak", 0), "last": mark.get("last"),
            "snapshot_problem": snapshot_problem}


class FallbackWatch:
    """jobs maintenance-slot task: ``due()`` then ``run()`` (same shape as necklaces.watch.NecklaceWatch)."""

    def __init__(self, data_dir=None, clock=time.time, minute: int = 25, quota=github_quota):
        self.root, self.clock, self.minute, self.quota = data_root(data_dir), clock, minute, quota
        self.last_hour = None

    def due(self) -> bool:
        from ..necklaces.watch import in_quiet_window
        now = self.clock()
        return (int(now // 3600) != self.last_hour and time.localtime(now).tm_min >= self.minute
                and not in_quiet_window(now))

    def run(self) -> dict:
        now = self.clock()
        self.last_hour = int(now // 3600)
        folder = self.root / "watch"
        folder.mkdir(parents=True, exist_ok=True)
        try:
            state = json.loads((folder / "state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
        line = observe(state, self.root, now, self.quota())
        tmp = folder / "state.json.tmp"
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, folder / "state.json")
        with (folder / f"{_iso(now)[:10]}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
        return {"alerts": [a["key"] for a in line["alerts"]], "open_problems": line["open_problems"],
                "failing": sorted(a for a, r in line["agents"].items() if r["status"] == "failing")}


if __name__ == "__main__":
    print(json.dumps(FallbackWatch().run(), ensure_ascii=False))
