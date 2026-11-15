"""E5 tool-definition change feed (docs/VERIFIED_REGISTRY.md 3; growth experiments 2026-11-15).

Built by the verified-registry jobs step after each snapshot, served from memory under the registry address:
``/registry/verified/v0.1/x/biz.agentconcierge/changes`` (JSON Feed 1.1, newest first, 50 items a page).

Two sources, both files (no database read):
  * listing changes written by the snapshot step: ``gateway-data/registry/events-<date>.jsonl``
    (``listed`` / ``delisted`` with a reason). A server dropped from the registry stays visible here for 30 days.
  * definition changes written by operations: ``gateway-data/fingerprints/changes-<date>.jsonl``
    (resource_id, source survey|health|retest|gate, server_fp, prev_server_fp, added, removed,
    changed[{name, fields}], classification same|dynamic|general|risk).

Only meaningful changes are published: a tool added or removed, or a description or input schema changed.
Dynamic descriptions (only numbers, dates or ids moved), annotation- or output-schema-only changes and first
measurements are left out. A risk line is published as an ordinary definition change: its risk detail is never
published (design section 6). Provider texts are never copied, only tool and field names. Scope: servers in the
verified registry (listed, or dropped in the last 30 days) and pearl and necklace members, not the whole catalog.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import threading
import time
from pathlib import Path

from . import verified_registry as R

FILE = "changes-feed.json"
KEEP_S = 30 * 86400
PAGE = 50
FIELDS = ("description", "inputSchema")
SITE = "https://agentconcierge.biz"
FEED_PATH = "/registry/verified/v0.1/x/biz.agentconcierge/changes"
NOTICE = ("Listing and tool-definition changes seen by AgentValCon with keyless read-only checks. Tool and field "
          "names only; read the server's own definitions before use. Not affiliated with the MCP Registry.")


def _fp_dir() -> Path:
    return Path(os.environ.get("FINGERPRINT_DATA", "gateway-data/fingerprints"))


def _lines(folder: Path, prefix: str, since: float):
    """JSON lines from <prefix>-<YYYYMMDD>.jsonl files of the last 31 days, oldest file first."""
    first = time.strftime("%Y%m%d", time.localtime(since - 86400))
    for path in sorted(Path(folder).glob(prefix + "-*.jsonl")):
        if path.stem[len(prefix) + 1:] < first:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for raw in text.splitlines():
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            if isinstance(row, dict):
                yield row


def _at(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return R._ts(str(value))


def _item_id(*parts) -> str:
    return "avc-" + hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:24]


def listing_item(event: dict) -> dict | None:
    name, kind = event.get("name"), event.get("event")
    if not isinstance(name, str) or kind not in ("listed", "delisted"):
        return None
    at = _at(event.get("at"))
    data = {"kind": kind, "server_name": name, "version": event.get("version")}
    if kind == "delisted":
        data["reason"] = event.get("reason") or "left_catalog_criteria"
        text = f"Removed from the AgentValCon verified registry ({data['reason']})."
    else:
        text = "Added to the AgentValCon verified registry."
    return {"id": _item_id("listing", kind, name, event.get("at")), "title": f"{kind.capitalize()}: {name}",
            "content_text": text, "url": SITE + "/registry/verified/v0.1/servers/" + _quote(name) + "/versions/latest",
            "date_published": R._iso(at), "_at": at, "_agentvalcon": data}


def _quote(name: str) -> str:
    from urllib.parse import quote
    return quote(name, safe="")


def definition_item(row: dict, names: dict) -> dict | None:
    """The published item for one change-log line, or None when the line is not a meaningful change."""
    try:
        rid = int(row.get("resource_id"))
    except (TypeError, ValueError):
        return None
    classification = row.get("classification")
    if classification not in ("general", "risk") or not row.get("prev_server_fp") or not row.get("server_fp"):
        return None   # same or dynamic, or a first measurement
    if rid not in names:
        return None   # outside the published scope
    added = sorted(n for n in row.get("added") or [] if isinstance(n, str))
    removed = sorted(n for n in row.get("removed") or [] if isinstance(n, str))
    changed = []
    for c in row.get("changed") or []:
        if not isinstance(c, dict) or not isinstance(c.get("name"), str):
            continue
        fields = sorted(f for f in c.get("fields") or [] if f in FIELDS)
        if fields:
            changed.append({"tool": c["name"], "fields": fields})
    if classification == "general" and not (added or removed or changed):
        return None   # only annotations or the output schema moved
    at = _at(row.get("at"))
    name = names[rid]
    label = name or f"agent {rid}"
    parts = [f"{len(x)} tool{'s' if len(x) != 1 else ''} {verb}" for x, verb in
             ((added, "added"), (removed, "removed"), (changed, "changed")) if x]
    data = {"kind": "definition_changed", "resource_id": rid, "server_name": name,
            "tools_fingerprint": "sha256:" + row["server_fp"], "previous_fingerprint": "sha256:" + row["prev_server_fp"],
            "added": added, "removed": removed, "changed": changed}
    return {"id": _item_id("definition", rid, row["server_fp"], row["prev_server_fp"]),
            "title": f"Tool definitions changed: {label}",
            "content_text": ("; ".join(parts) or "Tool definitions changed") + ". Re-read the tools before use.",
            "url": f"{SITE}/agent/{rid}", "date_published": R._iso(at), "_at": at, "_agentvalcon": data}


def scope(snapshot: dict | None, fp_dir: Path) -> dict:
    """Resource id -> server name (None for a member outside the registry)."""
    names: dict[int, str | None] = {}
    try:
        members = json.loads((fp_dir / "pearls.json").read_text(encoding="utf-8")).get("resources") or {}
    except (OSError, ValueError, AttributeError):
        members = {}
    for rid in members:
        try:
            names[int(rid)] = None
        except ValueError:
            continue
    for item in (snapshot or {}).get("servers") or []:
        if isinstance(item.get("_id"), int):
            names[item["_id"]] = item["server"]["name"]
    return names


def build_feed(snapshot: dict | None, registry_dir: Path, fp_dir: Path, now: float) -> dict:
    since = now - KEEP_S
    names = scope(snapshot, fp_dir)
    items, seen = [], set()
    for event in _lines(registry_dir, "events", since):
        item = listing_item(event)
        if item and item["_at"] >= since and item["id"] not in seen:
            seen.add(item["id"])
            items.append(item)
    for row in _lines(fp_dir, "changes", since):
        item = definition_item(row, names)   # the survey and a member check can log the same change: one item
        if item and item["_at"] >= since and item["id"] not in seen:
            seen.add(item["id"])
            items.append(item)
    items.sort(key=lambda i: (-i["_at"], i["id"]))
    for item in items:
        del item["_at"]
    return {"version": "https://jsonfeed.org/version/1.1", "title": "AgentValCon verified registry changes",
            "home_page_url": SITE + "/registry/verified", "feed_url": SITE + FEED_PATH,
            "description": NOTICE, "items": items}   # no build time: an unchanged feed keeps its ETag


def write_feed(feed: dict, folder: Path) -> Path:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / ("." + FILE + ".tmp")
    tmp.write_text(json.dumps(feed, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, folder / FILE)
    return folder / FILE


def refresh(snapshot: dict | None, folder: Path, now: float, fp_dir: Path | None = None) -> int:
    feed = build_feed(snapshot, Path(folder), Path(fp_dir or _fp_dir()), now)
    write_feed(feed, folder)
    return len(feed["items"])


# ---------------------------------------------------------------- answering (frontend, memory only)
class FeedIndex:
    def __init__(self, folder: Path | None = None):
        self.path = Path(folder or R.data_dir()) / FILE
        self._lock = threading.Lock()
        self._mtime, self.feed, self.etag, self.position = None, None, None, {}

    def current(self):
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return None
        with self._lock:
            if mtime != self._mtime:
                raw = self.path.read_bytes()
                self.feed = json.loads(raw)
                self.position = {item["id"]: i for i, item in enumerate(self.feed.get("items") or [])}
                self.etag = '"' + hashlib.sha256(raw).hexdigest()[:32] + '"'
                self._mtime = mtime
            return self


_DEFAULT: FeedIndex | None = None
_DEFAULT_LOCK = threading.Lock()


def default_index() -> FeedIndex:
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            _DEFAULT = FeedIndex()
        return _DEFAULT


def encode_cursor(item_id: str) -> str:
    return base64.urlsafe_b64encode(item_id.encode()).decode().rstrip("=")


def page(index: FeedIndex, cursor: str | None = None, limit: int = PAGE) -> dict:
    """One page of the feed. CURSOR is the last item id of the previous page; an unknown one raises InvalidCursor
    (it fell out of the 30-day window: start again from the first page)."""
    feed = index.feed
    items = feed.get("items") or []
    start = 0
    if cursor:
        try:
            item_id = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        except (binascii.Error, UnicodeDecodeError, ValueError):
            raise R.InvalidCursor("Invalid cursor parameter") from None
        if item_id not in index.position:
            raise R.InvalidCursor("Invalid cursor parameter")
        start = index.position[item_id] + 1
    chunk = items[start:start + limit]
    out = {k: v for k, v in feed.items() if k != "items"}
    out["items"] = chunk
    if start + limit < len(items):
        out["next_url"] = feed["feed_url"] + "?cursor=" + encode_cursor(chunk[-1]["id"])
    return out
