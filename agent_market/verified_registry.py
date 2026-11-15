"""AgentValCon Verified Registry (docs/VERIFIED_REGISTRY.md, growth experiment E7).

A read-only registry in the official MCP Registry API v0.1 shape that lists only remote MCP servers we called
ourselves: official registry name, grade A, healthy, a keyless real tool call that succeeded within 7 days, no auth,
no definition risk signal. Entries keep the official name and texts (GitHub Copilot's "Registry only" policy matches
on server names); our facts sit only under the response ``_meta`` key META_KEY.

Two halves:
- ``build_snapshot`` (jobs, hourly): reads the catalog with one registered SELECT, in id pages, and writes
  ``gateway-data/registry/verified.json`` atomically. Servers that drop out stay for 30 days as ``listed: false``.
- ``SnapshotIndex`` + ``list_page``/``versions``/``version`` (frontend): answer from the file held in memory, reloaded
  only when the file changes. No database read on a request.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

SCHEMA_URL = "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"
META_KEY = "biz.agentconcierge/verification"
NOTICE = ("Checked by AgentValCon with keyless read-only tool calls. Not affiliated with or endorsed by the MCP "
          "Registry; server names and texts are the publishers' own.")
SITE = "https://agentconcierge.biz"
NAME = re.compile(r"^[a-zA-Z0-9.-]+/[a-zA-Z0-9._-]+$")
FRESH_S = 7 * 86400
KEEP_REMOVED_S = 30 * 86400
DEFAULT_LIMIT, MAX_LIMIT = 30, 100
PAGE_ROWS = 1000
_FORGES = {"github.com": "github", "gitlab.com": "gitlab"}   # the official entries name these sources
HEADER_FIELDS = ("name", "description", "isRequired", "isSecret", "format", "default", "choices")

# One registered statement (application_store_sql.json); the id page keeps every read under the store's row cap.
SELECT_PAGE = ("SELECT id, name, description, url, details, trial_info, eval_grade FROM resources WHERE id>? "
               "AND active=1 AND kind='mcp' AND source='mcp-registry' AND eval_grade='A' AND health_status='healthy' "
               "AND trial_ok=1 AND (auth_method IS NULL OR auth_method IN ('none','unknown')) ORDER BY id LIMIT 1000")


def data_dir() -> Path:
    return Path(os.environ.get("VERIFIED_REGISTRY_DATA", "gateway-data/registry"))


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json(value):
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value) if isinstance(value, str) and value.strip()[:1] in "{[" else None
    except ValueError:
        return None


def _public_https(url) -> bool:
    """Syntactic check only (the collector already reached the server through check_public_url)."""
    try:
        parts = urlsplit(str(url or ""))
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    return (parts.scheme == "https" and bool(host) and not parts.username and not parts.password
            and "." in host and not re.fullmatch(r"[0-9.]+|\[.*\]", host) and host not in ("localhost",))


def exclusion_reason(row: dict, now: float, risky: frozenset = frozenset()) -> str:
    """Why a catalog row that the SELECT returned is not listed (shown in the change feed, never security details)."""
    details = _json(row.get("details")) or {}
    trial = _json(row.get("trial_info")) or {}
    if row.get("id") in risky:
        return "definition_risk"
    try:
        if now - float(trial.get("at")) > FRESH_S:
            return "no_recent_success"
    except (TypeError, ValueError):
        return "no_recent_success"
    remotes = [r for r in details.get("remotes") or [] if isinstance(r, dict)]
    if remotes and all(any(isinstance(h, dict) and h.get("isRequired") is True for h in r.get("headers") or [])
                       for r in remotes):
        return "requires_credentials"
    return "entry_not_valid"


def entry(row: dict, now: float, fingerprints: dict | None = None, risky: frozenset = frozenset(),
          risk_checked: bool = False) -> dict | None:
    """The registry entry for one catalog row, or None when it does not meet the listing rules."""
    details = _json(row.get("details")) or {}
    trial = _json(row.get("trial_info")) or {}
    name = details.get("registry_name")
    if not isinstance(name, str) or not 3 <= len(name) <= 200 or not NAME.fullmatch(name) or name.endswith("/by-name"):
        return None
    if row.get("id") in risky:
        return None   # a definition risk signal in the last 30 days
    description = " ".join(str(row.get("description") or "").split())
    version = str(details.get("version") or "").strip()
    if not 1 <= len(description) <= 100 or not version or len(version) > 255:
        return None
    try:
        tried_at = float(trial.get("at"))
    except (TypeError, ValueError):
        return None
    if now - tried_at > FRESH_S:
        return None
    remotes = []
    for r in details.get("remotes") or []:
        if not (isinstance(r, dict) and r.get("type") in ("streamable-http", "sse") and _public_https(r.get("url"))):
            continue
        headers = [h for h in r.get("headers") or [] if isinstance(h, dict)]
        if any(h.get("isRequired") is True for h in headers):
            continue   # a remote that requires a header is not one we called keyless
        remote = {"type": r["type"], "url": r["url"]}
        if headers:    # optional headers (a key for more tools or limits) stay as the publisher wrote them
            remote["headers"] = [{k: h[k] for k in HEADER_FIELDS if k in h} for h in headers]
        remotes.append(remote)
    if not remotes:
        return None
    server = {"$schema": SCHEMA_URL, "name": name, "description": description, "version": version, "remotes": remotes}
    repo = details.get("repository")
    if isinstance(repo, str):   # the collector keeps the official repository object as its URL
        repo = {"url": repo, "source": _FORGES.get((urlsplit(repo).hostname or "").lower())}
    if isinstance(repo, dict) and isinstance(repo.get("url"), str) and repo["url"].startswith("https://") \
            and isinstance(repo.get("source"), str):
        server["repository"] = {k: repo[k] for k in ("url", "source", "id", "subfolder") if isinstance(repo.get(k), str)}
    if isinstance(details.get("website"), str) and details["website"].startswith("https://"):
        server["websiteUrl"] = details["website"]
    fp = (fingerprints or {}).get(row.get("id")) or {}
    verification = {"listed": True, "last_success_at": _iso(tried_at), "grade": row.get("eval_grade"),
                    "checked_without_headers": True, "evidence": f"{SITE}/agent/{row['id']}"}
    if isinstance(trial.get("tool"), str):
        verification["checked_tool"] = trial["tool"][:100]
    verification["definition_risk_check"] = "clear" if risk_checked else "not_checked_yet"
    if fp.get("server_fp"):
        verification.update(tools_fingerprint="sha256:" + fp["server_fp"], fingerprint_version=fp.get("version"),
                            fingerprint_as_of=fp.get("as_of"))
    return {"server": server, "_meta": {META_KEY: verification}, "_id": row["id"]}


def read_rows(store) -> list[dict]:
    rows, after = [], 0
    while True:
        page = [dict(r) for r in store.query(SELECT_PAGE, (after,))]
        rows.extend(page)
        if len(page) < PAGE_ROWS:
            return rows
        after = page[-1]["id"]


def build_snapshot(rows, now: float, previous: dict | None = None, fingerprints: dict | None = None,
                   risky=frozenset(), risk_checked: bool = False) -> dict:
    """Entries keyed by name (one verified version each), plus servers that dropped out in the last 30 days."""
    items, reasons = {}, {}
    for row in rows:
        item = entry(row, now, fingerprints, frozenset(risky), risk_checked)
        if item is None:
            name = (_json(row.get("details")) or {}).get("registry_name")
            if isinstance(name, str):
                reasons[name] = exclusion_reason(row, now, frozenset(risky))
            continue
        name = item["server"]["name"]
        if name not in items or item["_meta"][META_KEY]["last_success_at"] > items[name]["_meta"][META_KEY]["last_success_at"]:
            items[name] = item
    stamp = _iso(now)
    old = {i["server"]["name"]: i for i in (previous or {}).get("servers") or []}
    for name, item in items.items():   # first listed / last changed time for updated_since
        before = old.get(name)
        same = before and before.get("server") == item["server"] and before.get("_meta", {}).get(META_KEY, {}).get("listed")
        item["_meta"][META_KEY]["updated_at"] = before["_meta"][META_KEY].get("updated_at", stamp) if same else stamp
    removed, events = [], []
    for name, item in items.items():
        before = old.get(name)
        if previous is not None and (before is None or not before.get("_meta", {}).get(META_KEY, {}).get("listed")):
            events.append({"at": stamp, "event": "listed", "name": name, "version": item["server"]["version"]})
    for name, before in old.items():
        if name in items:
            continue
        meta = before.get("_meta", {}).get(META_KEY, {})
        gone_at = meta.get("removed_at") or stamp
        if meta.get("listed"):   # dropped in this snapshot: the most useful signal for an allowlist (PM 11-15)
            events.append({"at": stamp, "event": "delisted", "name": name, "version": before["server"]["version"],
                           "reason": reasons.get(name, "left_catalog_criteria")})
        if now - _ts(gone_at) <= KEEP_REMOVED_S:
            removed.append({"server": before["server"], "_meta": {META_KEY: {
                "listed": False, "removed_at": gone_at, "updated_at": meta.get("removed_at") and meta.get("updated_at") or stamp,
                "reason": meta.get("reason") or reasons.get(name, "left_catalog_criteria")}}, "_id": before.get("_id")})
    servers = sorted(list(items.values()) + removed, key=lambda i: i["server"]["name"])
    for item in servers:
        item["_meta"][META_KEY]["snapshot"] = stamp
        item["_meta"][META_KEY]["notice"] = NOTICE
    return {"profile": "agentvalcon-verified-registry-v1", "generated": stamp, "listed": len(items),
            "servers": servers, "events": events}


def _ts(iso: str) -> float:
    try:
        return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return 0.0


def write_snapshot(snapshot: dict, folder: Path | None = None) -> Path:
    folder = Path(folder or data_dir())
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "verified.json"
    tmp = folder / ".verified.json.tmp"
    tmp.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)
    return path


def run_job(store, now=None, folder: Path | None = None) -> dict:
    """jobs step (hourly, outside the measurement windows): rebuild the snapshot from the catalog."""
    from .necklaces.watch import in_quiet_window
    now = time.time() if now is None else now
    if in_quiet_window(now):
        return {"skipped": "measurement_window"}
    folder = Path(folder or data_dir())
    try:
        previous = json.loads((folder / "verified.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = None
    fingerprints, risky, risk_checked = load_fingerprints(now)
    snapshot = build_snapshot(read_rows(store), now, previous, fingerprints, risky, risk_checked)
    write_events(snapshot.pop("events"), folder, now)
    write_snapshot(snapshot, folder)
    return {"listed": snapshot["listed"], "entries": len(snapshot["servers"])}


def write_events(events: list[dict], folder: Path, now: float) -> int:
    """Listing changes for the tool-change feed (E5): one line per listed or delisted server, by local date.
    The first snapshot has no previous one and writes nothing (it is not news that 7,000 servers exist)."""
    if not events:
        return 0
    path = Path(folder) / ("events-" + time.strftime("%Y%m%d", time.localtime(now)) + ".jsonl")
    with path.open("a", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return len(events)


def load_fingerprints(now=None) -> tuple[dict, frozenset, bool]:
    """(fingerprints by resource id, resource ids with a risk signal in 30 days, risk_check_available).

    Sources are the operations fingerprint records (reports/tool-fingerprint-design-2026-11-14 4):
    ``changes-<date>.jsonl`` (one line per definition change: resource_id, server_fp, classification
    dynamic|general|risk) and ``pearls.json`` (pearl and member baselines). Until the change log is being written (a
    file from the last two days exists) the risk condition cannot be checked: entries then say
    ``definition_risk_check: not_checked_yet`` instead of claiming it. Usage hashes are never substituted."""
    base = Path(os.environ.get("FINGERPRINT_DATA", "gateway-data/fingerprints"))
    now = time.time() if now is None else now
    out, risky = {}, set()
    try:
        pearls = json.loads((base / "pearls.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pearls = {}
    baselines = pearls.get("pearls") if isinstance(pearls, dict) else None
    for rid, value in (baselines or {}).items():
        if isinstance(value, dict) and isinstance(value.get("server_fp"), str):
            try:
                out[int(rid)] = {"server_fp": value["server_fp"], "version": pearls.get("version", "fingerprint-v1"),
                                 "as_of": pearls.get("generated")}
            except ValueError:
                continue
    files = sorted(base.glob("changes-*.jsonl"))
    recent_names = {"changes-" + time.strftime("%Y%m%d", time.localtime(now - d * 86400)) + ".jsonl" for d in (0, 1)}
    available = any(path.name in recent_names for path in files)
    since = now - 30 * 86400
    for path in files[-31:]:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for raw in lines:
            try:
                row = json.loads(raw)
                rid = int(row.get("resource_id"))
            except (ValueError, TypeError, AttributeError):
                continue
            at = _ts(str(row.get("at"))) if isinstance(row.get("at"), str) else float(row.get("at") or 0)
            if row.get("classification") == "risk" and at >= since:
                risky.add(rid)
            if isinstance(row.get("server_fp"), str):
                out[rid] = {"server_fp": row["server_fp"], "version": "fingerprint-v1",
                            "as_of": row.get("at") if isinstance(row.get("at"), str) else _iso(at)}
    return out, frozenset(risky), available


# ---------------------------------------------------------------- answering (frontend, memory only)
class SnapshotIndex:
    def __init__(self, folder: Path | None = None):
        self.path = Path(folder or data_dir()) / "verified.json"
        self._lock = threading.Lock()
        self._mtime, self.snapshot, self.names, self.by_name, self.etag = None, None, [], {}, None

    def current(self):
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return None
        with self._lock:
            if mtime != self._mtime:
                raw = self.path.read_bytes()
                data = json.loads(raw)
                self.snapshot = data
                self.by_name = {i["server"]["name"]: i for i in data.get("servers") or []}
                self.names = sorted(self.by_name)
                import hashlib
                self.etag = '"' + hashlib.sha256(raw).hexdigest()[:32] + '"'
                self._mtime = mtime
            return self


_DEFAULT: SnapshotIndex | None = None
_DEFAULT_LOCK = threading.Lock()


def default_index() -> SnapshotIndex:
    """One index per process, shared by the routes and /status.json (the snapshot is held in memory once)."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            _DEFAULT = SnapshotIndex()
        return _DEFAULT


def status_line(base: str, index: SnapshotIndex | None = None) -> dict | None:
    """The /status.json line: registry address, listed servers and snapshot time (None before the first snapshot)."""
    try:
        current = (index or default_index()).current()
    except (OSError, ValueError):
        return None
    if current is None or not current.snapshot:
        return None
    return {"url": base.rstrip("/") + "/registry/verified", "spec": "MCP Registry API v0.1",
            "listed": current.snapshot.get("listed"), "snapshot": current.snapshot.get("generated")}


def public(item: dict) -> dict:
    return {"server": item["server"], "_meta": item["_meta"]}


class InvalidCursor(ValueError):
    pass


def encode_cursor(name: str) -> str:
    return base64.urlsafe_b64encode(name.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> str:
    try:
        name = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise InvalidCursor("Invalid cursor parameter") from None
    if not NAME.fullmatch(name):
        raise InvalidCursor("Invalid cursor parameter")
    return name


def list_page(index: SnapshotIndex, *, cursor=None, limit=None, search=None, version=None, updated_since=None,
              include_deleted=False) -> dict:
    """GET /v0.1/servers. Listed servers only, unless updated_since (then servers that dropped out are included,
    as the official API includes deleted ones there)."""
    try:
        limit = DEFAULT_LIMIT if limit in (None, "") else int(limit)
    except (TypeError, ValueError):
        raise ValueError("limit must be a number") from None
    limit = max(1, min(MAX_LIMIT, limit))
    after = decode_cursor(cursor) if cursor else None
    since = None
    if updated_since:
        since = _ts(str(updated_since).replace("+00:00", "Z").split(".")[0].rstrip("Z") + "Z")
        if not since:
            raise ValueError("updated_since must be RFC 3339")
    needle = str(search or "").lower()
    out, last = [], None
    for name in index.names:
        if after is not None and name <= after:
            continue
        item = index.by_name[name]
        meta = item["_meta"][META_KEY]
        if not meta.get("listed") and not (since is not None or include_deleted):
            continue
        if needle and needle not in name.lower():
            continue
        if version not in (None, "", "latest") and item["server"]["version"] != version:
            continue
        if since is not None and _ts(meta.get("updated_at", "")) < since:
            continue
        if len(out) == limit:
            return {"servers": out, "metadata": {"nextCursor": encode_cursor(last), "count": len(out)}}
        out.append(public(item))
        last = name
    return {"servers": out, "metadata": {"count": len(out)}}   # the last page has no nextCursor (a string when present)


def versions(index: SnapshotIndex, name: str) -> dict | None:
    item = index.by_name.get(name)
    if item is None or not item["_meta"][META_KEY].get("listed"):
        return None
    return {"servers": [public(item)], "metadata": {"count": 1}}


def version(index: SnapshotIndex, name: str, wanted: str) -> dict | None:
    item = index.by_name.get(name)
    if item is None or not item["_meta"][META_KEY].get("listed"):
        return None
    if wanted != "latest" and item["server"]["version"] != wanted:
        return None
    return public(item)
