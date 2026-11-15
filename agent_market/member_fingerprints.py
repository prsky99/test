"""Fingerprints of pearls and necklace members, measured every 6 hours (reports/tool-fingerprint-design-2026-11-14,
sections 2-4; PM 11-15 11:5x: the file had not changed since 11-14 04:21 and the necklace watch could not read it).

One read-only tools/list per member (the collector's own MCP handshake, no tool is called), through the shared
provider budget ('fingerprints') with 2 seconds between calls. The result replaces gateway-data/fingerprints/pearls.json
atomically, in the form both readers use:

    {"version", "generated", "source",
     "resources": {rid: {"baseline", "baseline_at", "current", "last_server_fp", "measured_at", "unchanged_since",
                         "classification": same|dynamic|general|risk, "risk": [...], "normalized_same",
                         "tools": {name: tool_fp}, "hints": {name: [readOnlyHint, destructiveHint]}, "version"}},
     "pearls": {...earlier entries, kept}}

necklaces.watch reads baseline/current/risk/classification; verified_registry reads last_server_fp/unchanged_since.
A changed definition also appends one line to changes-<YYYYMMDD>.jsonl (source 'health'), with field names only,
never the provider's text. A member that could not be measured keeps its last values and gets 'error'.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path

from .tool_fingerprint import VERSION, server_fp, tool_fp

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("FINGERPRINT_DATA") or ((ROOT if (ROOT / "gateway-data").is_dir() else Path.cwd())
                                                    / "gateway-data/fingerprints"))
MEMBERS = Path("gateway-data/necklaces/members.json")
PEARLS = Path("exports/pearls/verify-snapshot.json")
EVERY_S = 6 * 3600
SPACING_S = 2.0
BUDGET_SYSTEM = "fingerprints"
_DYNAMIC = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ][\d:.]+Z?)?\b|\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
                      r"|\b[0-9a-f]{16,}\b|\d+(?:[.,]\d+)?", re.I)
_CREDENTIAL = re.compile(r"(passw|secret|token|api_?key|apikey|private_?key|credential|auth)", re.I)


def normalized_fp(tools: list[dict]) -> str:
    """The server fingerprint with numbers, dates, UUIDs and long hex strings in descriptions made placeholders."""
    return server_fp([{**t, "description": _DYNAMIC.sub("#", t.get("description") or "")} for t in tools
                      if isinstance(t, dict) and isinstance(t.get("name"), str)])


def hints(tools: list[dict]) -> dict:
    out = {}
    for t in tools:
        if isinstance(t, dict) and isinstance(t.get("name"), str):
            ann = t.get("annotations") if isinstance(t.get("annotations"), dict) else {}
            out[t["name"]] = [ann.get("readOnlyHint"), ann.get("destructiveHint")]
    return out


def risks(tools: list[dict], before_tools: dict, before_hints: dict) -> list[str]:
    """Design section 2 risk signals, on what changed since the baseline."""
    from .collector import usage
    from .concierge.security import check_malicious_dict
    found = []
    now_fps = {t["name"]: tool_fp(t) for t in tools if isinstance(t, dict) and isinstance(t.get("name"), str)}
    for t in tools:
        if not isinstance(t, dict) or not isinstance(t.get("name"), str):
            continue
        name = t["name"]
        new, changed = name not in before_tools, before_tools.get(name) not in (None, now_fps[name])
        if new or changed:
            bad, _why = check_malicious_dict({"description": t.get("description") or "", "inputSchema": t.get("inputSchema")})
            if bad:
                found.append("injection:" + name)
        read_before, destructive_before = (before_hints.get(name) or [None, None])[:2]
        ann = t.get("annotations") if isinstance(t.get("annotations"), dict) else {}
        if read_before is True and ann.get("readOnlyHint") is False or destructive_before is False and ann.get("destructiveHint") is True:
            found.append("annotation_flip:" + name)
        if new and not usage.is_relay_safe_tool({**t, "required": (t.get("inputSchema") or {}).get("required") or []}):
            found.append("new_unsafe_tool:" + name)
        required_now = set((t.get("inputSchema") or {}).get("required") or [])
        if not new and changed and any(_CREDENTIAL.search(p) for p in required_now):
            found.append("credential_param:" + name)
    return found


def member_ids(root: Path = ROOT, previous: dict | None = None) -> list[int]:
    ids = set()
    try:
        ids.update(int(r) for r in json.loads((root / MEMBERS).read_text()).get("resource_ids") or [] if str(r).isdigit())
    except (OSError, ValueError, AttributeError):
        pass
    try:
        agents = json.loads((root / PEARLS).read_text()).get("agents") or {}
        ids.update(int(rid) for rid, a in agents.items() if rid.isdigit()
                   and any(r.get("verified_pearl") or r.get("final_pearl") for r in a.get("roles") or []))
    except (OSError, ValueError, AttributeError):
        pass
    for key in ("resources", "pearls"):
        ids.update(int(r) for r in ((previous or {}).get(key) or {}) if str(r).isdigit())
    return sorted(ids)


def _iso(at: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(at))


def entry_for(previous: dict, old_pearl: dict, tools: list[dict], now: float) -> tuple[dict, dict | None]:
    """The new entry and, when the definition changed since the last measure, its change line."""
    current = server_fp(tools)
    baseline = previous.get("baseline") or old_pearl.get("server_fp") or current
    before_tools = previous.get("tools") or old_pearl.get("tools") or {}
    before_hints = previous.get("hints") or {}
    base_norm = previous.get("baseline_normalized")
    norm = normalized_fp(tools)
    # Annotations are outside the fingerprint (design section 1), so they are checked on every measure; a risk stays
    # until the member is qualified again (its entry's baseline is reset by the gate), never cleared by a later measure.
    found = risks(tools, before_tools, before_hints) if (current != baseline or before_hints) else []
    found = sorted(set(found) | set(previous.get("risk") or []))
    if found:
        classification = "risk"
    elif current == baseline:
        classification = "same"
    elif base_norm and base_norm == norm:
        classification = "dynamic"
    else:
        classification = "general"
    last = previous.get("current") or previous.get("last_server_fp") or old_pearl.get("server_fp")
    unchanged_since = previous.get("unchanged_since") or old_pearl.get("baseline_at") or _iso(now)
    if last and last != current and classification != "dynamic":
        unchanged_since = _iso(now)
    tool_fps = {t["name"]: tool_fp(t) for t in tools if isinstance(t, dict) and isinstance(t.get("name"), str)}
    entry = {"baseline": baseline, "baseline_at": previous.get("baseline_at") or old_pearl.get("baseline_at") or _iso(now),
             "baseline_normalized": base_norm or (norm if current == baseline else None),
             "current": current, "last_server_fp": current, "measured_at": _iso(now), "unchanged_since": unchanged_since,
             "classification": classification, "risk": found, "normalized_same": bool(base_norm and base_norm == norm),
             "tools": tool_fps, "hints": hints(tools), "version": VERSION}
    change = None
    if (last and last != current) or set(found) - set(previous.get("risk") or []):
        change = {"at": _iso(now), "source": "health", "server_fp": current, "prev_server_fp": last,
                  "normalized_same": entry["normalized_same"],
                  "added": sorted(set(tool_fps) - set(before_tools)), "removed": sorted(set(before_tools) - set(tool_fps)),
                  "changed": [{"name": n} for n in sorted(set(tool_fps) & set(before_tools)) if tool_fps[n] != before_tools[n]],
                  "risk": found, "classification": classification}
    return entry, change


def write_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name + ".")
    try:
        with os.fdopen(handle, "w") as out:
            json.dump(data, out, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def refresh(lookup, fetch, *, data: Path | None = None, root: Path = ROOT, now: float | None = None,
            reserve=None, note=None, sleep=time.sleep, ids: list[int] | None = None) -> dict:
    """Measure every member once. LOOKUP(rid) -> resource row; FETCH(url) -> full tool list (raises on failure)."""
    from . import provider_budget
    reserve = reserve or (lambda url: provider_budget.reserve(url, BUDGET_SYSTEM))
    note = note or (lambda url, status: provider_budget.note(url, BUDGET_SYSTEM, status))
    data = Path(data or DATA)
    path = data / "pearls.json"
    try:
        old = json.loads(path.read_text())
    except (OSError, ValueError):
        old = {}
    now = time.time() if now is None else now
    resources = dict(old.get("resources") or {})
    counts = {"measured": 0, "changed": 0, "risk": 0, "skipped": 0, "failed": 0}
    changes = []
    for i, rid in enumerate(ids if ids is not None else member_ids(root, old)):
        row = lookup(rid)
        if not row or row.get("kind") != "mcp" or not row.get("url"):
            counts["skipped"] += 1
            continue
        ok, why = reserve(row["url"])
        if not ok:
            resources[str(rid)] = {**resources.get(str(rid), {}), "error": "budget:" + why, "error_at": _iso(now)}
            counts["skipped"] += 1
            continue
        if i:
            sleep(SPACING_S)
        try:
            tools = fetch(row["url"])
        except Exception as exc:  # noqa: BLE001 - one member's failure never stops the others
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status == 429:
                note(row["url"], 429)
            resources[str(rid)] = {**resources.get(str(rid), {}), "error": type(exc).__name__, "error_at": _iso(now)}
            counts["failed"] += 1
            continue
        entry, change = entry_for(resources.get(str(rid)) or {}, (old.get("pearls") or {}).get(str(rid)) or {}, tools, now)
        resources[str(rid)] = entry
        counts["measured"] += 1
        if change:
            changes.append({"resource_id": rid, **change})
            counts["changed"] += 1
        if entry["classification"] == "risk":
            counts["risk"] += 1
    write_atomic(path, {"version": VERSION, "generated": _iso(now), "source": "member tools/list every 6 h (read-only)",
                        "resources": resources, "pearls": old.get("pearls") or {}})
    if changes:
        with open(data / time.strftime("changes-%Y%m%d.jsonl", time.localtime(now)), "a") as out:
            for line in changes:
                out.write(json.dumps(line, ensure_ascii=False) + "\n")
    return counts


def fetch_tools(url: str) -> list[dict]:
    """The collector's read-only handshake and tools/list (no tool call)."""
    import httpx
    from .broker.discovery import public_client
    from .collector.capabilities import CapabilityProber
    prober = CapabilityProber(None, trials=False)
    with public_client(False, timeout=httpx.Timeout(12.0, connect=5.0), follow_redirects=False) as http:
        found = prober.probe(url, http)
    tools = found.get("tools") if isinstance(found, dict) else None
    if not isinstance(tools, list):
        raise ValueError("no tool list")
    return tools


class MemberFingerprintStep:
    """jobs step: every 6 hours, outside the public measurement windows (:55-:10 and 03:50-05:10)."""

    def __init__(self, store, clock=time.time, refresh_fn=None, background=True):
        self.store, self.clock, self.refresh = store, clock, refresh_fn or refresh
        self.background, self.thread, self.last = background, None, 0.0

    def run_due(self):
        from .necklaces.watch import in_quiet_window
        now = self.clock()
        try:
            generated = json.loads((DATA / "pearls.json").read_text()).get("generated")
            last = time.mktime(time.strptime(generated[:19], "%Y-%m-%dT%H:%M:%S")) if generated else 0.0
        except (OSError, ValueError, TypeError):
            last = 0.0
        if (now - max(self.last, last) < EVERY_S or in_quiet_window(now)
                or (self.thread is not None and self.thread.is_alive())):
            return None
        self.last = now
        work = lambda: self.refresh(self.store.resource, fetch_tools, now=now)   # noqa: E731
        if self.background:   # about 30 members x (2 s + the handshake): never hold the scheduler's other steps
            import threading
            self.thread = threading.Thread(target=work, name="member-fingerprints", daemon=True)
            self.thread.start()
            return {"member_fingerprints": "started"}
        return {"member_fingerprints": work()}
