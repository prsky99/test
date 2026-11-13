"""Hourly necklace watch (design: reports/necklace-watch-2026-11-14/README.md).

Reads data that already exists and calls no provider:

- member health and tool annotations from the resource row (``store.resource``)
- tool-definition fingerprints from the ops file ``gateway-data/fingerprints/pearls.json``

Writes ``<root>/watch/state.json`` (streaks, runtime demotions and exclusions,
watch holds) and appends one observation line per member to
``<root>/watch/<date>.jsonl``.

Runtime ordering only moves members inside the approved chain, so the
definition digest that ops approved does not change. Holds are never lifted
here: the judge treats a hold as released only when ops approves the same
version and digest again after the hold started (two keys).
"""
from __future__ import annotations

import copy
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from . import model
from ..collector.usage import _DENY

WATCHED = ("qualifying", "trial", "live", "held")
DEMOTE_AFTER = 2       # hours in a row unhealthy before a lead member is demoted
RESTORE_AFTER = 6      # hours in a row healthy before a demoted member returns
# PM decision 11-14: an ordinary definition change (dynamic descriptions excluded by
# the ops normalized fingerprint) holds the necklace only when it hits a member that
# is called now (lead or fan-out) and queues a same-day retest of that member; a
# standby member is taken out of the chain instead. True holds on any member change.
HOLD_ON_STANDBY_CHANGE = False
QUIET = ((55, 60), (0, 10))          # minutes of every hour kept free for measurement
QUIET_DAILY = ((3, 50), (5, 10))     # 03:50-05:10 local


def _now_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def in_quiet_window(ts: float) -> bool:
    local = time.localtime(ts)
    minute = local.tm_min
    if any(lo <= minute < hi for lo, hi in QUIET):
        return True
    start, end = QUIET_DAILY
    clock = (local.tm_hour, local.tm_min)
    return start <= clock < end


def member_key(slug: str, slot: str, m: dict) -> str:
    return f"{slug}|{slot}|{m.get('resource_id') or m.get('agent_id')}|{m['tool']}"


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def tool_definition(row: dict, name: str) -> dict | None:
    raw = row.get("usage_full_tools") or row.get("usage_tools")
    try:
        tools = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return None
    if isinstance(tools, dict):
        tools = tools.get("tools")
    for tool in tools or []:
        if isinstance(tool, dict) and tool.get("name") == name:
            return tool
    return None


def annotation_problem(row: dict, member: dict) -> str | None:
    """Why the member's tool is no longer safe to call, or None."""
    if member.get("kind") != "external":
        return None
    tool = tool_definition(row, member["tool"])
    if tool is None:
        return "tool_missing"
    ann = tool.get("annotations") or {}
    if ann.get("readOnlyHint") is not True:
        return "read_only_hint_lost"
    if ann.get("destructiveHint") is True:
        return "destructive"
    if _DENY.search(tool["name"]):
        return "action_verb"
    return None


def fingerprint_status(prints: dict, rid) -> str:
    """'risk', 'changed', 'dynamic' or 'same' from the ops fingerprint file (unknown counts as same)."""
    entry = (prints.get("resources") or prints).get(str(rid)) if isinstance(prints, dict) else None
    if not isinstance(entry, dict):
        return "same"
    if entry.get("risk"):
        return "risk"
    baseline, current = entry.get("baseline"), entry.get("current")
    if baseline and current and baseline != current:
        return "dynamic" if entry.get("classification") == "dynamic" else "changed"
    return "same"


def healthy(row: dict | None) -> bool:
    return bool(row) and int(row.get("active") or 0) == 1 and row.get("health_status") == "healthy"


def runtime_chain(slot: dict, slug: str, state: dict) -> list[dict]:
    """The approved chain in its current order: excluded members dropped, demoted
    members moved behind the other members of their kind (externals stay before AgentValCon fallbacks)."""
    marks = state.get("members", {})
    chain = [m for m in slot["chain"] if m.get("state", "active") == "active"
             and not marks.get(member_key(slug, slot["slot"], m), {}).get("excluded")]
    out = []
    for kind in ("external", "agentcon"):
        group = [m for m in chain if m.get("kind") == kind]
        keep = [m for m in group if not marks.get(member_key(slug, slot["slot"], m), {}).get("demoted")]
        out += keep + [m for m in group if m not in keep]
    return out


def runtime_definition(defn: dict, state: dict) -> dict:
    """A copy of the definition with runtime chains; never used for the digest."""
    copy_ = copy.deepcopy(defn)
    for slot in copy_["slots"]:
        slot["chain"] = runtime_chain(slot, defn["slug"], state)
    return copy_


def _hold(state: dict, slug: str, reason: str, detail: str, now: float):
    holds = state.setdefault("holds", {})
    if slug not in holds or holds[slug].get("released"):
        holds[slug] = {"reason": reason, "detail": detail, "since": _now_iso(now)}


def _alert(state: dict, now: float, slug: str, slot: str, alert: str, count: int):
    """One alert per necklace, slot and kind a day."""
    day = _now_iso(now)[:10]
    alerts = state.setdefault("alerts", [])
    if any(a["slug"] == slug and a["slot"] == slot and a["alert"] == alert and a["at"][:10] == day for a in alerts):
        return
    alerts.append({"at": _now_iso(now), "slug": slug, "slot": slot, "alert": alert, "count": count})


def _retest_request(state: dict, now: float, slug: str, slot: str, m: dict):
    requests = state.setdefault("retest_requests", [])
    key = (slug, slot, m["resource_id"], m["tool"])
    if any((r["slug"], r["slot"], r["resource_id"], r["tool"]) == key and not r.get("done") for r in requests):
        return
    requests.append({"slug": slug, "slot": slot, "resource_id": m["resource_id"], "tool": m["tool"],
                     "reason": "fingerprint_changed", "since": _now_iso(now), "due": _now_iso(now)[:10]})


def observe(definitions: list[dict], fetch, prints: dict, state: dict, now: float) -> list[dict]:
    """One watch round. ``fetch(rid)`` returns the resource row or None. Mutates ``state``."""
    lines = []
    marks = state.setdefault("members", {})
    for defn in definitions:
        if defn.get("status") not in WATCHED:
            continue
        slug = defn["slug"]
        for slot in defn["slots"]:
            order = runtime_chain(slot, slug, state)
            called = {member_key(slug, slot["slot"], m)
                      for m in [x for x in order if x.get("kind") == "external"][:slot.get("fanout", 1)]}
            for m in slot["chain"]:
                if m.get("state", "active") != "active" or not isinstance(m.get("resource_id"), int):
                    continue
                key = member_key(slug, slot["slot"], m)
                mark = marks.setdefault(key, {"fail_streak": 0, "ok_streak": 0})
                row = fetch(m["resource_id"])
                ok = healthy(row)
                problem = annotation_problem(row or {}, m) if row else None
                print_state = fingerprint_status(prints, m["resource_id"]) if m.get("kind") == "external" else "same"
                mark["fail_streak"], mark["ok_streak"] = (0, mark["ok_streak"] + 1) if ok else (mark["fail_streak"] + 1, 0)
                action = None
                if row is not None and int(row.get("active") or 0) != 1:
                    if not mark.get("excluded"):
                        mark["excluded"], action = True, "excluded_inactive"
                if problem:
                    mark["excluded"], action = True, "excluded_" + problem
                    _hold(state, slug, "security", f"{m['resource_id']} {m['tool']}: {problem}", now)
                if print_state == "risk":
                    mark["excluded"], action = True, "excluded_fingerprint_risk"
                    _hold(state, slug, "security", f"{m['resource_id']}: fingerprint risk signal", now)
                elif print_state == "changed":
                    mark["excluded"], action = True, "excluded_fingerprint_changed"
                    if key in called or HOLD_ON_STANDBY_CHANGE:
                        _hold(state, slug, "fingerprint_changed", f"{m['resource_id']}: definition changed", now)
                        # PM 11-14: retest only that member the same day; a pass goes to ops for re-approval.
                        _retest_request(state, now, slug, slot["slot"], m)
                if not mark.get("excluded"):
                    if key in called and mark["fail_streak"] >= DEMOTE_AFTER and not mark.get("demoted"):
                        mark["demoted"], action = True, "demoted"
                    elif mark.get("demoted") and mark["ok_streak"] >= RESTORE_AFTER:
                        mark["demoted"], action = False, "restored"
                mark["last"] = _now_iso(now)
                lines.append({"at": _now_iso(now), "slug": slug, "slot": slot["slot"], "resource_id": m["resource_id"],
                              "tool": m["tool"], "kind": m["kind"], "healthy": ok,
                              "health_status": (row or {}).get("health_status"), "fingerprint": print_state,
                              "problem": problem, "fail_streak": mark["fail_streak"], "action": action})
            if slot.get("required", True) and not runtime_chain(slot, slug, state):
                _hold(state, slug, "no_member", f"slot {slot['slot']} has no usable member", now)
            externals = [m for m in runtime_chain(slot, slug, state) if m.get("kind") == "external"]
            if slot.get("required", True) and len(externals) < 2:
                _alert(state, now, slug, slot["slot"], "external_members_below_two", len(externals))
    state["updated"] = _now_iso(now)
    state["alerts"] = state.get("alerts", [])[-200:]
    return lines


class NecklaceWatch:
    """jobs maintenance-slot task: ``due()`` then ``run()`` (same shape as the insights refresher)."""

    def __init__(self, store, root: Path = Path("gateway-data/necklaces"),
                 fingerprints: Path = Path("gateway-data/fingerprints/pearls.json"),
                 definitions_dir: Path = model.DEFINITIONS, clock=time.time, minute: int = 20):
        self.store, self.root, self.fingerprints = store, Path(root), Path(fingerprints)
        self.definitions_dir, self.clock, self.minute = definitions_dir, clock, minute
        self.last_hour = None

    def due(self) -> bool:
        now = self.clock()
        hour = int(now // 3600)
        return hour != self.last_hour and time.localtime(now).tm_min >= self.minute and not in_quiet_window(now)

    def run(self) -> dict:
        now = self.clock()
        self.last_hour = int(now // 3600)
        definitions = model.load_valid(self.definitions_dir)
        state_path = self.root / "watch" / "state.json"
        state = load_json(state_path, {})
        lines = observe(definitions, self.store.resource, load_json(self.fingerprints, {}), state, now)
        from .judge import write_atomic
        write_atomic(state_path, state)
        day = time.strftime("%Y%m%d", time.localtime(now))
        with (self.root / "watch" / f"{day}.jsonl").open("a", encoding="utf-8") as handle:
            for line in lines:
                handle.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
        return {"members": len(lines), "holds": sorted(k for k, v in state.get("holds", {}).items()
                                                      if not v.get("released"))}
