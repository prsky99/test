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


FINGERPRINT_MAX_AGE = 24 * 3600
PASSING_PRINTS = ("same", "dynamic")


def fingerprint_status(prints: dict, rid, now: float | None = None) -> str:
    """'risk', 'changed', 'dynamic', 'same', 'unknown' or 'stale' from the ops fingerprint file, which ops writes as
    resources[rid] = {baseline, current, risk, classification, measured_at, unchanged_since} (PM 12:0x, 11-15).

    Closed, not open: a member missing from the file is 'unknown' and a reading older than 24 hours, or with no time
    at all, is 'stale'. Neither passes: a necklace is held and the gate does not judge. Until 11-15 the watch read
    resources[rid] while the file held pearls[rid], so every member read as 'same' and a changed tool would have gone
    unseen."""
    from .judge import _parse_time
    resources = prints.get("resources") if isinstance(prints, dict) else None
    entry = resources.get(str(rid)) if isinstance(resources, dict) else None
    if not isinstance(entry, dict) or not entry.get("baseline"):
        return "unknown"
    if entry.get("risk"):
        return "risk"                                   # a risk signal holds even on an old reading
    measured = _parse_time(entry.get("measured_at") or prints.get("generated"))
    now = time.time() if now is None else now
    if not measured or now - measured > FINGERPRINT_MAX_AGE:
        return "stale"
    baseline, current = entry.get("baseline"), entry.get("current")
    if not current:
        return "unknown"
    if baseline != current:
        return "dynamic" if entry.get("classification") == "dynamic" else "changed"
    return "same"


HEALTH_MAX_AGE = 24 * 3600     # PM 13:0x (11-15): members are probed every 0.1-12 h today (health_n_24h 2-6)


def health_state(row: dict | None, now: float | None = None) -> str:
    """'missing' (no row), 'unknown' (no probe time or one older than 24 hours), 'healthy' or 'unhealthy'.
    Closed: a health status nobody measured lately is not taken as healthy (PM 13:0x)."""
    from .judge import _parse_time
    if not row:
        return "missing"
    probed = _parse_time(row.get("probed_at"))
    now = time.time() if now is None else now
    if probed is None or now - probed > HEALTH_MAX_AGE:
        return "unknown"
    return "healthy" if healthy(row) else "unhealthy"


def healthy(row: dict | None) -> bool:
    return bool(row) and int(row.get("active") or 0) == 1 and row.get("health_status") == "healthy"


def _usable(member: dict, slot: dict, approved: set, own: dict | None = None) -> dict | None:
    """The member as it runs: active ones as they are; a planned AgentValCon fallback only once ops approved it as a
    substitute for this slot's role (approvals.json "substitutes", copied into the watch state every hour)."""
    state = member.get("state", "active")
    if state == "active":
        return member
    if state == "planned" and member.get("kind") == "agentcon" and (member.get("agent_id"), slot.get("contract")) in approved:
        return dict(member, state="active", substitute_approved=True, substitute_state="approved")
    # PM 16:03 (user instruction d4670360): an own substitute ops marked "provisional" (passed the 30-case gate)
    # runs as a provisional member before its full approval
    if (state == "planned" and member.get("kind") == "agentcon"
            and (own or {}).get(f"{member.get('agent_id')}|{slot.get('contract')}") == "provisional"):
        return dict(member, state="active", substitute_state="provisional")
    return None


def runtime_chain(slot: dict, slug: str, state: dict) -> list[dict]:
    """The approved chain in its current order: excluded members dropped, demoted
    members moved behind the other members of their kind (externals stay before AgentValCon fallbacks)."""
    from . import members as standing_rules
    marks = state.get("members", {})
    approved = {tuple(x) for x in state.get("substitutes") or [] if isinstance(x, (list, tuple)) and len(x) == 2}
    block = state.get("standing") if isinstance(state.get("standing"), dict) else None
    usable = [_usable(m, slot, approved, (block or {}).get("own") or {}) for m in slot["chain"]]
    chain = [m for m in usable if m is not None
             and not marks.get(member_key(slug, slot["slot"], m), {}).get("excluded")
             and model.terms_status(m) != "prohibits"]          # terms forbid automated use (PM 12:27)
    if block is not None:   # PM 16:03: each member says its standing; a verified pearl leads, provisional next
        chain = [dict(m, standing=standing_rules.standing(m, slot.get("contract"), block)) for m in chain]
    rank = {"verified_pearl": 0, "provisional": 1}
    out = []
    if block is not None:
        # PM 16:03: a step with no pearl runs on a provisional member, our own included, before members that pass
        # neither bar; within a standing externals stay before our own and demoted members go last
        for level in (0, 1, 2):
            for kind in ("external", "agentcon"):
                group = [m for m in chain if m.get("kind") == kind and rank.get(m.get("standing"), 2) == level]
                keep = [m for m in group if not marks.get(member_key(slug, slot["slot"], m), {}).get("demoted")]
                out += keep + [m for m in group if m not in keep]
        return out
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


HOLD_EVENTS_KEPT = 20


def _hold(state: dict, slug: str, reason: str, detail: str, now: float):
    """Holds are kept per event (PM R20). A new event starts a new hold after a release; on an open hold a different
    problem is added and moves ``since`` forward, so only an approval later than the newest problem releases it."""
    holds = state.setdefault("holds", {})
    current = holds.get(slug)
    event = {"reason": reason, "detail": detail, "since": _now_iso(now)}
    if current is None or current.get("released"):
        history = (current or {}).get("events") or ([] if current is None else
                                                   [{k: current.get(k) for k in ("reason", "detail", "since",
                                                                                 "released_at", "released_by")}])
        holds[slug] = {**event, "events": (history + [event])[-HOLD_EVENTS_KEPT:]}
        return
    events = current.setdefault("events", [{k: current.get(k) for k in ("reason", "detail", "since")}])
    if (events[-1].get("reason"), events[-1].get("detail")) != (reason, detail):
        events.append(event)
        del events[:-HOLD_EVENTS_KEPT]
        current.update(event)


def release_holds(state: dict, approvals: dict, now: float) -> list[str]:
    """Record the release of an open hold once ops approved the necklace again after its newest problem
    (the judge applies the same rule); the event keeps when and by which approval it was released."""
    from .judge import _parse_time
    released = []
    for slug, hold in (state.get("holds") or {}).items():
        approval = (approvals or {}).get(slug)
        if hold.get("released") or not approval or approval.get("state") != "approved":
            continue
        if (_parse_time(approval.get("at")) or 0) > (_parse_time(hold.get("since")) or 0):
            stamp = {"released_at": _now_iso(now), "released_by": "approval " + str(approval.get("at"))}
            hold.update(stamp, released=True)
            if hold.get("events"):
                hold["events"][-1].update(stamp)
            released.append(slug)
    return released


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


def _default_fallback_spec(agent_id: str) -> dict | None:
    try:
        from ..fallback_agents import tool_spec
        return tool_spec(agent_id)
    except Exception:
        return None


def _default_fallback_health(agent_id: str) -> str:
    """The agent team's hourly fallback watch (278c3aaa): healthy, degraded, failing, idle or unknown."""
    try:
        from ..fallback_agents.watch import health
        return health(agent_id).get("status", "unknown")
    except Exception:
        return "unknown"


def _check_fallback(state: dict, slug: str, slot: str, m: dict, now: float, fallback_spec,
                    fallback_health=_default_fallback_health) -> dict:
    """An in-process AgentValCon fallback: its published tool must still be a safe read-only lookup, and a
    fallback whose source the agent team's watch reports as failing is demoted like an external member
    (two failing hours), then restored after six good ones. Unknown and idle are not failures."""
    key = member_key(slug, slot, m)
    mark = state.setdefault("members", {}).setdefault(key, {"fail_streak": 0, "ok_streak": 0})
    status = fallback_health(m["agent_id"])
    if status == "failing":
        mark["fail_streak"], mark["ok_streak"] = mark.get("fail_streak", 0) + 1, 0
    elif status in ("healthy", "degraded", "idle"):
        mark["fail_streak"], mark["ok_streak"] = 0, mark.get("ok_streak", 0) + 1
    spec = fallback_spec(m["agent_id"])
    ann = (spec or {}).get("annotations") or {}
    problem = ("tool_missing" if not spec or spec.get("name") != m["tool"] else
               "read_only_hint_lost" if ann.get("readOnlyHint") is not True else
               "destructive" if ann.get("destructiveHint") is True else None)
    action = None
    if problem and not mark.get("excluded"):
        mark["excluded"], action = True, "excluded_" + problem
        _alert(state, now, slug, slot, "fallback_" + problem, 0)
    elif not problem:
        if mark["fail_streak"] >= DEMOTE_AFTER and not mark.get("demoted"):
            mark["demoted"], action = True, "demoted"
            _alert(state, now, slug, slot, "fallback_failing", 0)
        elif mark.get("demoted") and mark["ok_streak"] >= RESTORE_AFTER:
            mark["demoted"], action = False, "restored"
    mark["last"] = _now_iso(now)
    return {"at": _now_iso(now), "slug": slug, "slot": slot, "resource_id": None, "agent_id": m["agent_id"],
            "tool": m["tool"], "kind": "agentcon", "healthy": problem is None and status != "failing",
            "health_status": status, "fingerprint": "same", "problem": problem,
            "fail_streak": mark["fail_streak"], "action": action}


def observe(definitions: list[dict], fetch, prints: dict, state: dict, now: float,
            fallback_spec=_default_fallback_spec, fallback_health=_default_fallback_health,
            approvals: dict | None = None) -> list[dict]:
    """One watch round. ``fetch(rid)`` returns the resource row or None. Mutates ``state``.
    Releases recorded first, so a problem seen in this round after a re-approval starts a new hold."""
    if approvals is not None:
        release_holds(state, approvals, now)
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
                if m.get("state", "active") != "active":
                    continue
                if not isinstance(m.get("resource_id"), int):
                    if m.get("kind") == "agentcon":
                        lines.append(_check_fallback(state, slug, slot["slot"], m, now, fallback_spec, fallback_health))
                    continue
                key = member_key(slug, slot["slot"], m)
                mark = marks.setdefault(key, {"fail_streak": 0, "ok_streak": 0})
                row = fetch(m["resource_id"])
                if row:          # PM 17:28: the tool's required arguments, for runner.connection_empty
                    tool = tool_definition(row, m["tool"]) or {}
                    required = (tool.get("inputSchema") or tool.get("input_schema") or {}).get("required")
                    state.setdefault("tool_required", {})[f"{m['resource_id']}|{m['tool']}"] = \
                        [str(x) for x in required] if isinstance(required, list) else []
                health = health_state(row, now)
                ok = health == "healthy"
                problem = annotation_problem(row or {}, m) if row else None
                print_state = fingerprint_status(prints, m["resource_id"], now) if m.get("kind") == "external" else "same"
                mark["fail_streak"], mark["ok_streak"] = (0, mark["ok_streak"] + 1) if ok else (mark["fail_streak"] + 1, 0)
                action = None
                if row is None and not mark.get("excluded"):
                    # gone from the catalogue: nothing to check its tools against, so it leaves the chain; a slot
                    # left empty holds the necklace below (no_member)
                    mark["excluded"], action = True, "excluded_missing"
                if health == "unknown" and key in called and slot.get("required", True):
                    _hold(state, slug, "health_unknown", f"{m['resource_id']}: no health probe in 24 h", now)
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
                elif print_state in ("unknown", "stale"):
                    # nothing to compare against: not the member's fault, so it stays in the chain, but the
                    # necklace does not run on a definition nobody checked (PM 12:0x); ops re-approves after refresh
                    _hold(state, slug, "fingerprint_unverified", f"{m['resource_id']}: fingerprint {print_state}", now)
                if not mark.get("excluded"):
                    if key in called and mark["fail_streak"] >= DEMOTE_AFTER and not mark.get("demoted"):
                        mark["demoted"], action = True, "demoted"
                    elif mark.get("demoted") and mark["ok_streak"] >= RESTORE_AFTER:
                        mark["demoted"], action = False, "restored"
                mark["last"] = _now_iso(now)
                lines.append({"at": _now_iso(now), "slug": slug, "slot": slot["slot"], "resource_id": m["resource_id"],
                              "tool": m["tool"], "kind": m["kind"], "healthy": ok, "health": health,
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


UPGRADES = Path("logs/ops/necklace-watch/upgrades.jsonl")


def upgrade_lines(definitions: list[dict], block: dict, now: float, path: Path | None = None) -> list[dict]:
    """One line per slot whose provisional member can give way to a verified pearl, when the pearl snapshot changes
    (in_chain true: it leads from now on; false: the pearl is not in the chain yet, a definition change and gate)."""
    from . import members as standing_rules
    try:
        roles = json.loads(Path("reports/pearls-2026-11-14/role_groups.json").read_text(encoding="utf-8")).get("roles")
    except (OSError, ValueError):
        roles = None
    found = standing_rules.upgrades(definitions, block, roles)
    target = Path(path or UPGRADES)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(now)),
                                     "snapshot": block.get("snapshot_generated"), "slots": found},
                                    ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        pass
    return found


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
        from .judge import load_approvals, load_substitutes
        state["substitutes"] = load_substitutes(self.root / "approvals.json")
        from . import members as standing_rules
        before = (state.get("standing") or {}).get("snapshot_generated")
        state["standing"] = standing_rules.load(now=now)
        if state["standing"].get("snapshot_generated") != before:     # PM 16:03 item 5: a new pearl snapshot
            upgrade_lines(definitions, state["standing"], now)
        lines = observe(definitions, self.store.resource, load_json(self.fingerprints, {}), state, now,
                        approvals=load_approvals(self.root / "approvals.json"))
        from .judge import write_atomic
        write_atomic(state_path, state)
        day = time.strftime("%Y%m%d", time.localtime(now))
        with (self.root / "watch" / f"{day}.jsonl").open("a", encoding="utf-8") as handle:
            for line in lines:
                handle.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
        return {"members": len(lines), "holds": sorted(k for k, v in state.get("holds", {}).items()
                                                      if not v.get("released"))}
