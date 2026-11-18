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
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import model

SCHEMA = "agentcon-necklaces-v1"
MAX_BYTES = 1_000_000
STALE_HOURS = 48
# Closed verdicts (PM 13:0x, 11-15): information we cannot read or trust holds, it does not pass.
WATCH_STALE_HOURS = 3      # the watch runs hourly at :20; 03:20 -> 05:20 jumps the 03:50-05:10 window
SNAPSHOT_MAX_HOURS = 72    # verified pearls from an older verify snapshot are not trusted
# PM 12:27 (11-15): closing 3 ships only once ops has seen evaluator_version in the 09:12 pearl_daily snapshot of
# 11-16 and equal to the official one. If it has not, a release sets this to False (one line) and closings 1, 2,
# 4 and 5 ship without it; the snapshot is then read as before (no age or version check).
CHECK_PEARL_SNAPSHOT = True
DEFAULT_ROOT = Path("gateway-data/necklaces")
PUBLIC = ("live", "preview", "held", "retired")
# PM 16:55 and 17:0x (11-18, final): the two fortune necklaces are built from our own substitutes; until the outside
# members have role reports, each substitute that passed its gate with an approved fingerprint counts as a member, one
# per role. The definition declares it (own_members {label, counted, until}, the field the surface reads too); this
# list caps which slugs may and until when (Asia/Seoul), so a definition cannot widen it and the rule ends by itself.
OWN_MEMBER_EXCEPTION = {"daily-fortune-brief": "2026-12-18", "personality-fortune-brief": "2026-12-18"}
OWN_MEMBER_LABEL = "Built with AgentValCon agents"
      # preview: user 11-18 via PM (necklaces/preview.py)


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


def load_substitutes(path: Path) -> list[list[str]]:
    """[agent_id, slot_role] of every AgentValCon substitute whose latest entry in approvals.json "substitutes" is
    approved by ops (deploy/NECKLACE_GATE.md section 10). A revoked or held latest entry removes it."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    latest: dict[tuple, dict] = {}
    for item in (raw.get("substitutes") if isinstance(raw, dict) else None) or []:
        if not isinstance(item, dict) or not item.get("agent_id") or not item.get("slot_role"):
            continue
        key = (item["agent_id"], item["slot_role"])
        current = latest.get(key)
        if current is None or (_parse_time(item.get("at")) or 0) >= (_parse_time(current.get("at")) or 0):
            latest[key] = item
    return sorted([list(k) for k, v in latest.items() if v.get("state") == "approved"])


def load_substitute_states(path: Path) -> dict[str, str]:
    """{"<agent_id>|<slot_role>": "approved" | "provisional"} from the latest entry of each substitute in
    approvals.json (ops 11-15: "provisional" = passed the 30-case gate only, PM 16:03 provisional members)."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    latest: dict[tuple, dict] = {}
    for item in (raw.get("substitutes") if isinstance(raw, dict) else None) or []:
        if not isinstance(item, dict) or not item.get("agent_id") or not item.get("slot_role"):
            continue
        key = (item["agent_id"], item["slot_role"])
        current = latest.get(key)
        if current is None or (_parse_time(item.get("at")) or 0) >= (_parse_time(current.get("at")) or 0):
            latest[key] = item
    return {f"{a}|{r}": v["state"] for (a, r), v in latest.items() if v.get("state") in ("approved", "provisional")}


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


def verify_snapshot_path() -> Path:
    """The search team's snapshot next to gateway-data: services run from the project root (launchd WorkingDirectory)."""
    project = os.environ.get("AGENTCON_PROJECT_ROOT")
    return (Path(project) if project else Path(".")) / "exports" / "pearls" / "verify-snapshot.json"


def official_evaluator_version() -> str | None:
    """The evaluator version the pearl reports are graded with now, from this release's own code
    (gate_rules.EVALUATOR_VERSION; PM 16:29: never the working tree under AGENTCON_PROJECT_ROOT)."""
    from .gate_rules import EVALUATOR_VERSION
    return EVALUATOR_VERSION or None


def snapshot_problem(data: dict, now: float | None = None, official: str | None = None) -> str | None:
    """Why a verify snapshot is not trusted (PM 13:0x): older than SNAPSHOT_MAX_HOURS, without a time, or graded
    with another evaluator version than the official one (or either version unknown)."""
    generated = _parse_time(str(data.get("generated") or "").replace("+0900", "+09:00"))
    now = time.time() if now is None else now
    if generated is None or now - generated > SNAPSHOT_MAX_HOURS * 3600:
        return "snapshot_stale"
    official = official_evaluator_version() if official is None else official
    if not official or data.get("evaluator_version") != official:
        return "snapshot_evaluator_version"
    return None


def verified_pearls(path: Path | None = None, now: float | None = None,
                    official: str | None = None) -> set[tuple[int, str]] | None:
    """(agent id, role) pairs that are verified pearls in the search team's verify snapshot (PM R29), or None when
    the snapshot is missing, unreadable, older than 72 hours or graded with another evaluator version (then no
    member is called a pearl: the gate does not judge and a public necklace is held as pearls_unverified)."""
    try:
        data = json.loads(Path(path or verify_snapshot_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if CHECK_PEARL_SNAPSHOT and snapshot_problem(data, now, official):
        return None
    out = set()
    for agent_id, agent in (data.get("agents") or {}).items():
        for role in (agent or {}).get("roles") or []:
            if isinstance(role, dict) and role.get("verified_pearl") is True and str(agent_id).isdigit():
                out.add((int(agent_id), role.get("role")))
    return out


def pearls(defn: dict, verified: set | None = None) -> list[dict]:
    """One entry per member called first: the fan-out members of each slot, with the rest as alternates. ``pearl``
    is true only when the verify snapshot lists that agent as a verified pearl for the slot's role (contract id)."""
    out = []
    for slot in defn["slots"]:
        externals = model.live_members(slot, "external")
        agentcon = model.live_members(slot, "agentcon")
        fanout = slot.get("fanout", 1)
        # PM 11-16 06:5x (growth): outside members that can run in this step now and count (verified pearl or
        # provisional) -- the running chain already lacks members whose terms prohibit us or the watch excluded
        from .members import COUNTED
        usable = {"external_usable": sum(1 for m in externals if m.get("standing") in COUNTED),
                  "external_listed": len(externals)}
        leads, rest = externals[:fanout], externals[fanout:]
        ordered = model.live_members(slot)
        if any("standing" in m for m in ordered) and ordered and ordered[0].get("kind") == "agentcon":
            leads, rest = [], externals      # PM 16:03: our provisional member leads a step no external one qualifies for
        alternates = [{"resource_id": m["resource_id"], "tool": m["tool"], "kind": "external",
                       "standing": m.get("standing")} for m in rest]
        alternates += [{"resource_id": m.get("resource_id"), "agent_id": m.get("agent_id"), "tool": m["tool"],
                        "kind": "agentcon", "standing": m.get("standing")} for m in agentcon[:model.MAX_AGENTCON]]
        if not leads and agentcon:      # PM 16:03: our own provisional member leads (no qualifying external member)
            lead = agentcon[0]
            out.append({"resource_id": lead.get("resource_id"), "agent_id": lead.get("agent_id"), "role": slot["slot"],
                        "tool": lead["tool"], "kind": "agentcon", "required": bool(slot.get("required", True)),
                        "pearl": False, "standing": lead.get("standing"), **usable,
                        "alternates": [a for a in alternates if not (a["kind"] == "agentcon"
                                                                     and a.get("agent_id") == lead.get("agent_id"))]})
        for lead in leads:
            pearl = bool(verified) and (lead["resource_id"], lead.get("contract") or slot["contract"]) in verified
            # PM 16:03 item 4: verified_pearl or provisional per member (necklaces.members); None = not counted
            out.append({"resource_id": lead["resource_id"], "role": slot["slot"], "tool": lead["tool"],
                        "kind": "external", "required": bool(slot.get("required", True)),
                        "pearl": pearl, "standing": lead.get("standing", "verified_pearl" if pearl else None), **usable,
                        "alternates": alternates})
    return out


def approved_own_roles(running: dict, states: dict | None) -> list[str]:
    """Contracts of the steps an approved substitute leads: no outside member leads the step, its first live
    AgentValCon member is "approved" for the step's contract in approvals.json (a provisional or unapproved one is
    not), and each contract counts once (different roles)."""
    roles = []
    for slot in running.get("slots") or []:
        if model.live_members(slot, "external")[: slot.get("fanout", 1)]:
            continue
        own = model.live_members(slot, "agentcon")
        contract = slot.get("contract")
        if own and contract not in roles and (states or {}).get(f"{own[0].get('agent_id')}|{contract}") == "approved":
            roles.append(contract)
    return roles


def own_members(defn: dict, running: dict, states: dict | None, now: float,
                exceptions: dict | None = None) -> tuple[dict | None, str | None]:
    """(own_members for the entry, hold reason). Nothing (None, None) when the definition declares no own_members,
    its slug is not on the list or the day has passed. Held when the declaration is not the agreed one (label, an
    until later than the list's) or declares more members than judge counts itself (PM 17:0x: the declared number
    is never used above the counted one)."""
    declared = defn.get("own_members")
    cap = (OWN_MEMBER_EXCEPTION if exceptions is None else exceptions).get(defn["slug"])
    if not isinstance(declared, dict) or not cap:
        return None, None
    until = declared.get("until")
    from zoneinfo import ZoneInfo
    try:
        end = datetime.fromisoformat(str(until)).replace(tzinfo=ZoneInfo("Asia/Seoul")) + timedelta(days=1)
    except ValueError:
        return None, "own_members_invalid"
    if now >= end.timestamp():
        return None, None                                   # the exception ended by itself
    counted = declared.get("counted")
    if (str(until) > cap or declared.get("label") != OWN_MEMBER_LABEL or type(counted) is not int or counted < 1):
        return None, "own_members_invalid"
    roles = approved_own_roles(running, states)
    if counted > len(roles):
        return None, "own_members_unapproved"
    return {"counted": counted, "roles": roles, "until": str(until), "label": OWN_MEMBER_LABEL}, None


PREVIEW_FIRST_RETEST_HOURS = 72     # PM 17:3x: a preview with no retest at all is held this long after it began


def _quality_hold(entry: dict, now: float, preview: bool = False, since: float | None = None) -> str | None:
    """A preview (PM 17:2x) claims no value against doing the task yourself, so it needs no positive delta, and before
    its first retest it has no test time to go stale; once retested it is held like a live one when the retest is
    old (and by the retest's own holds, quality_low and the like, through summary held_reason)."""
    quality = entry.get("quality") or {}
    tested = _parse_time(quality.get("tested_at"))
    if preview and tested is None and not quality.get("cases_7d"):
        if since is not None and now - since > PREVIEW_FIRST_RETEST_HOURS * 3600:
            return "stale_retest"           # PM 17:3x: 72 hours as a preview and still no retest summary
        return None
    if tested is None or now - tested > STALE_HOURS * 3600:
        return "stale_retest"
    if preview:
        return None
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


PRICING_MODE = "free"      # user decision 11-15: free while users grow; per-run billing comes later, if at all


def example_fields(defn: dict) -> dict:
    """F17 (growth, PM 11-15 11:22): example_input = the input fields of the definition's public probe_input (staged
    slot values left out); input_help = the definition's optional per-field help, schema fields only."""
    props = set((defn.get("input_schema") or {}).get("properties") or {})
    out = {}
    example = {k: v for k, v in (defn.get("probe_input") or {}).items()
               if k in props and isinstance(v, (str, int, float)) and not isinstance(v, bool)}
    if example:
        out["example_input"] = example
    helps = {k: str(v)[:200] for k, v in (defn.get("input_help") or {}).items() if k in props and str(v).strip()}
    if helps:
        out["input_help"] = helps
    return out


def fallback_depth(running: dict) -> dict:
    """How far a run can fall back (PM 13:53, charter stages): 'agentvalcon' when every required slot has one of our
    own agents usable behind its external members, 'external' when some required slot can only fall back to other
    external members (then a failure of all of them stops the run, stage 4). Shown on the public page."""
    without = [s["slot"] for s in running["slots"] if s.get("required", True)
               and not any(m.get("kind") == "agentcon" for m in s["chain"])]
    # our own agent may cover part of the inputs only (census-geocode: US addresses), said per slot (PM 14:25)
    limited = {s["slot"]: m["coverage"] for s in running["slots"] if s.get("required", True)
               for m in s["chain"] if m.get("kind") == "agentcon" and m.get("coverage")}
    return {"depth": "external" if without else "agentvalcon", "slots_without_own": without,
            "own_coverage": limited}


def terms_hold(defn: dict, running: dict) -> str | None:
    """PM 12:27 (11-15): once a necklace's members were checked (terms_reviewed_at), it is not offered while the
    lead of a required slot has unknown terms. Before the check nothing holds on terms (it would stop every one)."""
    if not defn.get("terms_reviewed_at"):
        return None
    for slot in running["slots"]:
        lead = next(iter(slot["chain"]), None)
        if slot.get("required", True) and lead is not None and model.terms_status(lead) not in model.USABLE_TERMS:
            return "terms_unknown"
    return None


def load_watch_state(root: Path, now: float) -> tuple[dict, str | None]:
    """The hourly watch's state and, when it cannot be trusted, why (PM 13:0x): a missing or broken file, or one
    not updated for WATCH_STALE_HOURS, holds every public necklace instead of reading as 'no holds'."""
    try:
        state = json.loads((Path(root) / "watch" / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, "watch_state_missing"
    if not isinstance(state, dict):
        return {}, "watch_state_missing"
    updated = _parse_time(state.get("updated"))
    if updated is None or now - updated > WATCH_STALE_HOURS * 3600:
        return state, "watch_state_stale"
    return state, None


def build_entry(defn: dict, approval: dict | None, summary: dict, now: float,
                watch_state: dict | None = None, verified: set | None = None,
                watch_problem: str | None = None, preview_rows: list | None = None,
                substitute_states: dict | None = None, preview_since: float | None = None) -> dict | None:
    status = defn["status"]
    if status not in PUBLIC:
        return None
    previewing = status == "preview"
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
        "pearls": pearls(running, verified),
        "input_schema": defn["input_schema"],
        **example_fields(defn),
        # PM 11-15 (user decision): necklace runs are a free event for now; the surface words it (growth team)
        "pricing": {"mode": PRICING_MODE},
        "completion": summary.get("completion"),
        "quality": summary.get("quality"),
        "cost": summary.get("cost"),
        "stage": summary.get("stage"),
        "replaces_templates": list(defn.get("replaces_templates") or []),
        # what the necklace covers, for the page (PM 11-15: national holidays only, territories as their country)
        "scope_notice": defn.get("scope_notice"),
        "replaced_at": defn.get("replaced_at"),
    }
    entry["pearl_count"] = sum(1 for p in entry["pearls"] if p["pearl"])
    from .members import COUNTED
    entry["member_count"] = sum(1 for p in entry["pearls"] if p.get("standing") in COUNTED)   # pearls + provisional
    own, own_hold = own_members(defn, running, substitute_states, now)
    if own:                         # PM 16:55: never in pearl_count, never called verified; the card shows the label
        entry["member_count"] += own["counted"]
        entry["own_members"] = own
    entry["fallback"] = fallback_depth(running)
    from .capacity import capacity                   # PM 17:24: runs a day the providers allow, and the bottleneck
    entry["capacity"] = capacity(running)
    if status == "retired":
        entry["replaced_by"] = defn.get("replaced_by")
        return entry
    approved, reason = approval_state(defn, approval)
    if previewing:
        # A preview has not passed its gate: no gate time, no value against doing it yourself, its measured rounds only
        from .preview import measured, unmeasured
        approved, approval = False, None
        # PM 17:2x: with no measured round the preview still shows, with its note only (no count, never a zero)
        entry["preview"] = measured(defn, preview_rows or []) or unmeasured()
        reason = None
    if approved:
        entry["gate_passed_at"] = _iso(_parse_time(approval.get("at")))
    # plan 3.1 (PM 11-15): measured value only for a necklace that passed the gate, with its cases and dates
    entry["value"] = summary.get("value") if entry["gate_passed_at"] else None
    from .value import comparison                      # growth's display form (design note 11-15)
    entry["comparison"] = comparison(entry["value"])
    if entry["comparison"]:     # PM 16:09: more steps, more calls and merging on the path without the necklace
        entry["comparison"]["slots"] = sum(1 for s in defn["slots"] if s.get("required", True))
    if status == "held":
        entry["held_reason"] = summary.get("held_reason") or "manual"
        return entry
    # The surface contract needs at least two pearls; summary holds come from the
    # daily retest (security, completion_low, quality_low and the like).
    reason = (reason
              or own_hold
              or terms_hold(defn, running)
              or watch_problem
              or watch_hold(defn["slug"], watch_state, approval)
              or ("no_member" if len(entry["pearls"]) < 2 else None)
              # PM 16:03 (user instruction d4670360): two verified pearls are no longer the condition; two counted
              # members (verified pearl or provisional) are. No pearl snapshot at all still holds (nothing judged).
              or ("pearls_unverified" if not verified else None)
              or ("members_unqualified" if entry["member_count"] < max(2, defn.get("min_pearls_answered") or 2)
                  else None)
              or summary.get("held_reason")
              or _quality_hold(entry, now, preview=previewing, since=preview_since))
    if reason:
        entry["status"], entry["held_reason"] = "held", reason
    if previewing:
        # PM 17:3x: a preview shows no token, speed or accuracy number anywhere; only the test time stays (the
        # surface's freshness check) and the measured rounds stay in entry.preview when there are any
        quality = entry.get("quality") or {}
        entry["quality"] = {"tested_at": quality.get("tested_at")} if quality.get("tested_at") else None
        entry["cost"] = entry["completion"] = None
    return entry


TESTING = ("qualifying", "trial")


def testing_entry(defn: dict, summary: dict) -> dict | None:
    """A necklace still before its gate, listed as "In testing" (F17, contract with growth 11-14).

    Only what the listing needs: no pearls, input schema, tools or quality claims, so nothing can run it
    or call it verified. Shown only once it has retest cases."""
    if defn.get("status") not in TESTING:
        return None
    quality = summary.get("quality") or {}
    passed, total = quality.get("success_7d"), quality.get("cases_7d")
    if type(passed) is not int or type(total) is not int or not 0 <= passed <= total or total == 0:
        return None
    entry = {"slug": defn["slug"], "name": defn["name"], "version": defn["version"], "status": "testing",
             "tests": {"passed": passed, "total": total}}
    template_id = summary.get("template_id") or defn.get("template_id")
    if type(template_id) is int:
        entry["template_id"] = template_id
    return entry


EVENT_DAYS = 60


def _sign_event(event: dict, signing_dir: Path | None) -> dict | None:
    """DSSE-sign a held, retired, replaced or restored event (deploy/EVIDENCE_SIGNING.md); pending without a key."""
    if signing_dir is None:
        return None
    from . import evidence
    body = evidence.necklace_event(event)
    if body is None:
        return None
    name = f"{event['slug']}-{body['event']}-{event['at'].replace(':', '').replace('-', '')}"
    try:
        out = evidence.sign_and_store(body, name, signing_dir)
    except FileExistsError:
        return {"signed": True, "path": str(signing_dir / "envelopes" / "necklace_event" / f"{name}.json")}
    return out if out.get("signed") else {"signed": False, "reason": out.get("reason")}


def record_events(entries: list[dict], judge_state: dict, now: float, signing_dir: Path | None = None) -> list[dict]:
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
                event = {"slug": slug, "kind": kind, "at": stamp, "reason": entry.get("held_reason"),
                         "replaced_by": entry.get("replaced_by")}
                event["signature"] = _sign_event(event, signing_dir)
                events.append(event)
            before = {"status": status, "since": stamp, "ever_live": before.get("ever_live") or status == "live"}
            last[slug] = before
        if status == "held":
            entry["held_at"] = before["since"]
    cutoff = now - EVENT_DAYS * 86400
    judge_state["events"] = [e for e in events if (_parse_time(e["at"]) or 0) >= cutoff]
    return judge_state["events"]


def snapshot(definitions: list[dict], approvals: dict[str, dict], root: Path, now: float | None = None,
             judge_commit: str | None = None, watch_state: dict | None = None,
             judge_state: dict | None = None, verified: set | None = None, preview_rows: list | None = None) -> dict:
    now = time.time() if now is None else now
    if preview_rows is None:
        from . import preview
        preview_rows = preview.load(root)
    substitute_states = load_substitute_states(Path(root) / "approvals.json")
    watch_problem = None
    if watch_state is None:
        watch_state, watch_problem = load_watch_state(root, now)
    entries = []
    # PM R22: the last passed gate stays on the entry when ops holds, revokes or the definition changes, so the
    # surface keeps the page and the tool answer with the stop notice instead of a 404 / "Unknown necklace".
    passed = {} if judge_state is None else judge_state.setdefault("gate_passed", {})
    verified = verified_pearls() if verified is None else verified
    # PM 17:3x: when each definition became a preview, kept apart from the status history so a hold in between does
    # not restart the 72 hours; cleared once the definition leaves preview
    since_map = {} if judge_state is None else judge_state.setdefault("preview_since", {})
    for defn in definitions:
        if defn["status"] == "preview":
            since_map.setdefault(defn["slug"], _iso(now))
        else:
            since_map.pop(defn["slug"], None)
        since = _parse_time(since_map.get(defn["slug"])) if defn["status"] == "preview" else None
        entry = build_entry(defn, approvals.get(defn["slug"]), load_summary(root, defn["slug"]), now, watch_state,
                            verified, watch_problem, preview_rows, substitute_states, since)
        if entry is not None:
            if entry.get("gate_passed_at"):
                passed[defn["slug"]] = entry["gate_passed_at"]
            elif passed.get(defn["slug"]) and defn["status"] != "preview":     # a preview never carries a gate time
                entry["gate_passed_at"] = passed[defn["slug"]]
            entries.append(entry)
    signing_dir = Path(root).parent / "signing"
    from . import evidence
    for entry in entries:
        entry["evidence"] = {"gate": evidence.latest_envelope("gate_result", f"{entry['slug']}-v{entry['version']}",
                                                              signing_dir)}
    events = record_events(entries, {} if judge_state is None else judge_state, now, signing_dir)
    # Testing entries never make events or evidence: the first public event stays "launched".
    for defn in definitions:
        found = testing_entry(defn, load_summary(root, defn["slug"]))
        if found is not None:
            entries.append(found)
    from .members import rules as member_rules
    return {"schema": SCHEMA, "generated_at": _iso(now), "judge_commit": judge_commit, "necklaces": entries,
            "events": events, "member_rules": member_rules((watch_state or {}).get("standing"))}


def members(definitions: list[dict], now: float | None = None, standing: dict | None = None) -> dict:
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
                             "registrable_domain": m.get("registrable_domain"), "pearl": bool(m.get("pearl")),
                             # PM 16:03 / ops 11-15: approved and provisional members told apart
                             **_member_standing(m, slot, standing)})
    resource_ids = sorted({r["resource_id"] for r in rows if isinstance(r["resource_id"], int)})
    return {"schema": "agentcon-necklace-members-v1", "generated_at": _iso(time.time() if now is None else now),
            "resource_ids": resource_ids, "members": rows}


def _member_standing(m: dict, slot: dict, block: dict | None) -> dict:
    from . import members as standing_rules
    if block is None:
        return {}
    state = None
    if m.get("kind") == "agentcon":
        state = (block.get("own") or {}).get(f"{m.get('agent_id')}|{m.get('contract') or slot.get('contract')}")
    member = dict(m, state="active", substitute_state=state) if state and m.get("state") == "planned" else \
        dict(m, substitute_state=state)
    return {"substitute_state": state,
            "standing": standing_rules.standing(member, m.get("contract") or slot.get("contract"), block)}


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
    from . import members as standing_rules
    member_list = members(definitions, standing=standing_rules.load())
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
