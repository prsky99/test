"""Necklace judge: writes the public snapshot that every surface reads.

Contract: reports/growth-plan-2026-11-14/necklace-contract.md (growth draft) as
settled in reports/necklace-production-2026-11-14/process.md section 3, and the
ops launch gate deploy/NECKLACE_GATE.md.

Only this module writes ``necklaces.json``. Inputs:

- definitions (git): ``agent_market/necklaces/definitions/*.json``
- ops approvals: ``<root>/approvals.json`` entries
  ``{slug, version, definition_digest, gate_record, state, at}``
- quality and completion summaries: ``<root>/results/<slug>/summary.json``

Two keys (PM 2026-11-14): an entry is ``live`` only when the workflow team's
definition says ``live`` and ops approved the same version and digest. Anything
else that the workflow team wants live is written as ``held`` with a reason, so
the page stays up and runs are blocked.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from . import model

SCHEMA = "agentcon-necklaces-v1"
MAX_BYTES = 1_000_000
STALE_HOURS = 48
DEFAULT_ROOT = Path("gateway-data/necklaces")
PUBLIC = ("live", "held", "retired")


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_time(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def load_approvals(path: Path) -> dict[str, dict]:
    """Latest approval entry per slug. A missing or unreadable file means no approvals."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    items = raw.get("approvals", []) if isinstance(raw, dict) else raw
    latest: dict[str, dict] = {}
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not item.get("slug"):
            continue
        current = latest.get(item["slug"])
        if current is None or (_parse_time(item.get("at")) or 0) >= (_parse_time(current.get("at")) or 0):
            latest[item["slug"]] = item
    return latest


def load_summary(root: Path, slug: str) -> dict:
    try:
        return json.loads((root / "results" / slug / "summary.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def approval_state(defn: dict, approval: dict | None) -> tuple[bool, str | None]:
    """(approved, held_reason) for the ops key."""
    if not approval:
        return False, "not_approved"
    state = approval.get("state")
    if state == "revoked":
        return False, "approval_revoked"
    if state == "held":
        return False, "gate_held"
    if state != "approved":
        return False, "not_approved"
    if approval.get("version") != defn["version"] or approval.get("definition_digest") != model.digest(defn):
        return False, "approval_mismatch"
    return True, None


def pearls(defn: dict) -> list[dict]:
    """One entry per pearl called first: the fan-out members of each slot, with the rest as alternates."""
    out = []
    for slot in defn["slots"]:
        externals = model.live_members(slot, "external")
        agentcon = model.live_members(slot, "agentcon")
        fanout = slot.get("fanout", 1)
        leads, rest = externals[:fanout], externals[fanout:]
        alternates = [{"resource_id": m["resource_id"], "tool": m["tool"], "kind": "external"} for m in rest]
        alternates += [{"resource_id": m.get("resource_id"), "agent_id": m.get("agent_id"), "tool": m["tool"],
                        "kind": "agentcon"} for m in agentcon[:model.MAX_AGENTCON]]
        for lead in leads:
            out.append({"resource_id": lead["resource_id"], "role": slot["slot"], "tool": lead["tool"],
                        "required": bool(slot.get("required", True)), "pearl": bool(lead.get("pearl")),
                        "alternates": alternates})
    return out


def _quality_hold(entry: dict, now: float) -> str | None:
    quality = entry.get("quality") or {}
    tested = _parse_time(quality.get("tested_at"))
    if tested is None or now - tested > STALE_HOURS * 3600:
        return "stale_retest"
    delta = quality.get("delta_pp")
    if not isinstance(delta, (int, float)) or delta <= 0:
        return "delta_nonpositive"
    return None


def watch_hold(slug: str, watch_state: dict | None, approval: dict | None) -> str | None:
    """An open watch hold, unless ops approved again after it started (two keys)."""
    hold = ((watch_state or {}).get("holds") or {}).get(slug)
    if not hold or hold.get("released"):
        return None
    since = _parse_time(hold.get("since")) or 0
    if approval and approval.get("state") == "approved" and (_parse_time(approval.get("at")) or 0) > since:
        return None
    return hold.get("reason") or "manual"


def build_entry(defn: dict, approval: dict | None, summary: dict, now: float,
                watch_state: dict | None = None) -> dict | None:
    status = defn["status"]
    if status not in PUBLIC:
        return None
    from .watch import runtime_definition
    running = runtime_definition(defn, watch_state or {})
    entry = {
        "slug": defn["slug"],
        "name": defn["name"],
        "summary": defn["summary"],
        "version": defn["version"],
        "definition_digest": model.digest(defn),
        "template_id": summary.get("template_id") or defn.get("template_id"),
        "status": status,
        "held_reason": None,
        "gate_passed_at": None,
        "pearls": pearls(running),
        "input_schema": defn["input_schema"],
        "completion": summary.get("completion"),
        "quality": summary.get("quality"),
        "cost": summary.get("cost"),
        "stage": summary.get("stage"),
        "replaces_templates": list(defn.get("replaces_templates") or []),
        "replaced_at": defn.get("replaced_at"),
    }
    if status == "retired":
        entry["replaced_by"] = defn.get("replaced_by")
        return entry
    approved, reason = approval_state(defn, approval)
    if approved:
        entry["gate_passed_at"] = _iso(_parse_time(approval.get("at")))
    if status == "held":
        entry["held_reason"] = summary.get("held_reason") or "manual"
        return entry
    # The surface contract needs at least two pearls; summary holds come from the
    # daily retest (security, completion_low, quality_low and the like).
    reason = (reason
              or watch_hold(defn["slug"], watch_state, approval)
              or ("no_member" if len(entry["pearls"]) < 2 else None)
              or summary.get("held_reason")
              or _quality_hold(entry, now))
    if reason:
        entry["status"], entry["held_reason"] = "held", reason
    return entry


EVENT_DAYS = 60


def record_events(entries: list[dict], judge_state: dict, now: float) -> list[dict]:
    """Status changes as public events (launched, held, resumed, retired) and held_at.

    ``judge_state`` keeps the last status per slug and the events of the last 60 days;
    the growth team builds /api/feed/necklaces.json from these events only."""
    stamp = _iso(now)
    last = judge_state.setdefault("status", {})
    events = judge_state.setdefault("events", [])
    for entry in entries:
        slug, status = entry["slug"], entry["status"]
        before = last.get(slug, {})
        if status != before.get("status"):
            kind = {"live": "resumed" if before.get("ever_live") else "launched",
                    "held": "held", "retired": "retired"}.get(status)
            if kind and not (kind == "held" and not before.get("ever_live")):
                events.append({"slug": slug, "kind": kind, "at": stamp, "reason": entry.get("held_reason"),
                               "replaced_by": entry.get("replaced_by")})
            before = {"status": status, "since": stamp, "ever_live": before.get("ever_live") or status == "live"}
            last[slug] = before
        if status == "held":
            entry["held_at"] = before["since"]
    cutoff = now - EVENT_DAYS * 86400
    judge_state["events"] = [e for e in events if (_parse_time(e["at"]) or 0) >= cutoff]
    return judge_state["events"]


def snapshot(definitions: list[dict], approvals: dict[str, dict], root: Path, now: float | None = None,
             judge_commit: str | None = None, watch_state: dict | None = None,
             judge_state: dict | None = None) -> dict:
    now = time.time() if now is None else now
    if watch_state is None:
        try:
            watch_state = json.loads((root / "watch" / "state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            watch_state = {}
    entries = []
    for defn in definitions:
        entry = build_entry(defn, approvals.get(defn["slug"]), load_summary(root, defn["slug"]), now, watch_state)
        if entry is not None:
            entries.append(entry)
    events = record_events(entries, {} if judge_state is None else judge_state, now)
    return {"schema": SCHEMA, "generated_at": _iso(now), "judge_commit": judge_commit, "necklaces": entries,
            "events": events}


def members(definitions: list[dict], now: float | None = None) -> dict:
    """Every chain member of every necklace in a non-retired state, for the ops fingerprint
    watch (reports/tool-fingerprint-design-2026-11-14, section 3) and the hourly necklace watch."""
    rows = []
    for defn in definitions:
        if defn.get("status") == "retired":
            continue
        for slot in defn["slots"]:
            for rank, m in enumerate(slot["chain"], start=1):
                rows.append({"slug": defn["slug"], "version": defn["version"], "necklace_status": defn["status"],
                             "slot": slot["slot"], "required": bool(slot.get("required", True)), "rank": rank,
                             "kind": m["kind"], "resource_id": m.get("resource_id"), "agent_id": m.get("agent_id"),
                             "tool": m["tool"], "state": m.get("state", "active"),
                             "registrable_domain": m.get("registrable_domain"), "pearl": bool(m.get("pearl"))})
    resource_ids = sorted({r["resource_id"] for r in rows if isinstance(r["resource_id"], int)})
    return {"schema": "agentcon-necklace-members-v1", "generated_at": _iso(time.time() if now is None else now),
            "resource_ids": resource_ids, "members": rows}


def write_atomic(path: Path, payload: dict) -> int:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(data) > MAX_BYTES:
        raise ValueError(f"snapshot is {len(data)} bytes, above the {MAX_BYTES} byte cap")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".necklaces-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return len(data)


def _commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              cwd=model.ROOT, timeout=5).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def run_once(root: Path = DEFAULT_ROOT, definitions_dir: Path = model.DEFINITIONS) -> dict:
    definitions = model.load_valid(definitions_dir)
    try:
        judge_state = json.loads((root / "judge_state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        judge_state = {}
    payload = snapshot(definitions, load_approvals(root / "approvals.json"), root, judge_commit=_commit(),
                       judge_state=judge_state)
    write_atomic(root / "judge_state.json", judge_state)
    size = write_atomic(root / "necklaces.json", payload)
    member_list = members(definitions)
    write_atomic(root / "members.json", member_list)
    return {"written": str(root / "necklaces.json"), "bytes": size, "member_resources": len(member_list["resource_ids"]),
            "entries": {e["slug"]: e["status"] for e in payload["necklaces"]}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the public necklace snapshot once.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--definitions", type=Path, default=model.DEFINITIONS)
    args = parser.parse_args(argv)
    print(json.dumps(run_once(args.root, args.definitions), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
