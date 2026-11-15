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


def entry(row: dict, now: float, fingerprints: dict | None = None, risky: frozenset = frozenset()) -> dict | None:
    """The registry entry for one catalog row, or None when it does not meet the listing rules."""
    details = _json(row.get("details")) or {}
    trial = _json(row.get("trial_info")) or {}
    name = details.get("registry_name")
    if not isinstance(name, str) or not 3 <= len(name) <= 200 or not NAME.fullmatch(name) or name.endswith("/by-name"):
        return None
    if name in risky:
        return None
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
    if isinstance(repo, dict) and isinstance(repo.get("url"), str) and repo["url"].startswith("https://"):
        server["repository"] = {k: repo[k] for k in ("url", "source", "id", "subfolder") if isinstance(repo.get(k), str)}
    if isinstance(details.get("website"), str) and details["website"].startswith("https://"):
        server["websiteUrl"] = details["website"]
    fp = (fingerprints or {}).get(row.get("id")) or {}
    verification = {"listed": True, "last_success_at": _iso(tried_at), "grade": row.get("eval_grade"),
                    "checked_without_headers": True, "evidence": f"{SITE}/agent/{row['id']}"}
    if isinstance(trial.get("tool"), str):
        verification["checked_tool"] = trial["tool"][:100]
    if fp.get("server_fp"):
        verification.update(tools_fingerprint="sha256:" + fp["server_fp"], fingerprint_version=fp.get("version"),
                            fingerprint_unchanged_since=fp.get("unchanged_since"))
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
                   risky=frozenset()) -> dict:
    """Entries keyed by name (one verified version each), plus servers that dropped out in the last 30 days."""
    items = {}
    for row in rows:
        item = entry(row, now, fingerprints, frozenset(risky))
        if item is None:
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
    removed = []
    for name, before in old.items():
        if name in items:
            continue
        meta = before.get("_meta", {}).get(META_KEY, {})
        gone_at = meta.get("removed_at") or stamp
        if now - _ts(gone_at) <= KEEP_REMOVED_S:
            removed.append({"server": before["server"], "_meta": {META_KEY: {
                "listed": False, "removed_at": gone_at, "updated_at": meta.get("removed_at") and meta.get("updated_at") or stamp,
                "reason": meta.get("reason") or "no_longer_meets_listing_rules"}}, "_id": before.get("_id")})
    servers = sorted(list(items.values()) + removed, key=lambda i: i["server"]["name"])
    for item in servers:
        item["_meta"][META_KEY]["snapshot"] = stamp
        item["_meta"][META_KEY]["notice"] = NOTICE
    return {"profile": "agentvalcon-verified-registry-v1", "generated": stamp, "listed": len(items),
            "servers": servers}


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
    fingerprints, risky = load_fingerprints()
    snapshot = build_snapshot(read_rows(store), now, previous, fingerprints, risky)
    write_snapshot(snapshot, folder)
    return {"listed": snapshot["listed"], "entries": len(snapshot["servers"])}


def load_fingerprints() -> tuple[dict, frozenset]:
    """Server fingerprints and recent risk signals from the operations fingerprint records (fingerprint-v1), when
    they exist. Missing records leave the fields empty; usage hashes are never substituted (different definition)."""
    base = Path(os.environ.get("FINGERPRINT_DATA", "gateway-data/fingerprints"))
    out, risky = {}, set()
    try:
        pearls = json.loads((base / "pearls.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pearls = {}
    for rid, value in (pearls.get("resources") or {}).items() if isinstance(pearls, dict) else []:
        if isinstance(value, dict) and value.get("last_server_fp"):
            try:
                out[int(rid)] = {"server_fp": value["last_server_fp"], "version": value.get("version", "fingerprint-v1"),
                                 "unchanged_since": value.get("unchanged_since")}
            except ValueError:
                continue
    since = time.time() - 30 * 86400
    for path in sorted(base.glob("changes-*.jsonl"))[-31:]:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for raw in lines:
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("risk") and isinstance(row.get("registry_name"), str) \
                    and _ts(str(row.get("at"))) >= since:
                risky.add(row["registry_name"])
    return out, frozenset(risky)


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
    return {"servers": out, "metadata": {"nextCursor": None, "count": len(out)}}


def versions(index: SnapshotIndex, name: str) -> dict | None:
    item = index.by_name.get(name)
    if item is None or not item["_meta"][META_KEY].get("listed"):
        return None
    return {"servers": [public(item)], "metadata": {"nextCursor": None, "count": 1}}


def version(index: SnapshotIndex, name: str, wanted: str) -> dict | None:
    item = index.by_name.get(name)
    if item is None or not item["_meta"][META_KEY].get("listed"):
        return None
    if wanted != "latest" and item["server"]["version"] != wanted:
        return None
    return public(item)
