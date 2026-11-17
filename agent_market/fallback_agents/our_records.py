"""AgentValCon's own published records of an agent or MCP server, for the agent-record substitute (agent.record.v1,
agent team 11-17; mcp-server-trust-check our_record seat).

Nothing is called. Three files the services already publish are read (each re-read only when it changes):
- the task-page snapshot catalog (logs/service-frontend/public-pages/task-pages.json, built daily by jobs): grade,
  reachability status, last check time and the URL key of about 8,800 listed agents;
- the verified registry snapshot (gateway-data/registry/verified.json, hourly): official MCP Registry servers we
  called ourselves, by registry name and remote URL;
- the verify snapshot (exports/pearls/verify-snapshot.json): role test scores of the agents we tested.
Paths are relative to the service working directory (the repository root), with environment overrides for tests.
A URL is matched through the same normalization and key as /api/agent/v1/check (agent_check.variants, url_key);
a name through the catalog name or the official registry name, case-insensitively. Records not in these files
are answered as not found in our published records; the database is never read here.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path

CATALOG = ("AGENT_RECORD_CATALOG", "logs/service-frontend/public-pages/task-pages.json")
REGISTRY = ("AGENT_RECORD_REGISTRY", "gateway-data/registry/verified.json")
VERIFY = ("AGENT_RECORD_VERIFY", "exports/pearls/verify-snapshot.json")


def _path(spec) -> Path:
    return Path(os.environ.get(spec[0]) or spec[1])


class _File:
    def __init__(self, spec):
        self.spec, self.key, self.value, self.lock = spec, None, None, threading.Lock()

    def read(self):
        path = _path(self.spec)
        try:
            st = path.stat()
        except OSError:
            return None
        key = (str(path), st.st_mtime_ns, st.st_size)
        with self.lock:
            if key != self.key:
                try:
                    self.value = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    self.value = None
                self.key = key
            return self.value


class Records:
    def __init__(self):
        self.catalog, self.registry, self.verify = _File(CATALOG), _File(REGISTRY), _File(VERIFY)
        self._index_key, self._index = None, None

    def index(self):
        cat, reg, ver = self.catalog.read() or {}, self.registry.read() or {}, self.verify.read() or {}
        key = (id(cat), id(reg), id(ver))
        if key == self._index_key:
            return self._index
        by_id, by_key, by_name = {}, {}, {}
        for a in cat.get("catalog") or []:
            if isinstance(a, dict) and isinstance(a.get("id"), int):
                by_id[a["id"]] = {"catalog": a}
                if a.get("url_key"):
                    by_key.setdefault(a["url_key"], a["id"])
                if isinstance(a.get("name"), str):
                    by_name.setdefault(a["name"].strip().lower(), a["id"])
        for item in reg.get("servers") or []:
            rid, server = item.get("_id"), item.get("server") or {}
            if not isinstance(rid, int):
                continue
            entry = by_id.setdefault(rid, {})
            entry["registry"] = item
            if isinstance(server.get("name"), str):
                by_name.setdefault(server["name"].strip().lower(), rid)
            for remote in server.get("remotes") or []:
                url = str(remote.get("url") or "").rstrip("/")
                if url:
                    by_key.setdefault(hashlib.sha256(url.encode()).hexdigest()[:20], rid)
        for sid, agent in (ver.get("agents") or {}).items():
            try:
                rid = int(sid)
            except (TypeError, ValueError):
                continue
            by_id.setdefault(rid, {})["verify"] = agent
        self._index_key, self._index = key, (by_id, by_key, by_name)
        return self._index

    def find(self, url: str | None = None, name: str | None = None):
        """(resource id, matched_by) or (None, None)."""
        by_id, by_key, by_name = self.index()
        if url:
            from ..concierge.agent_check import normalize, variants
            canonical, _host = normalize(url)
            for value in variants(canonical):
                rid = by_key.get(hashlib.sha256(value.rstrip("/").encode()).hexdigest()[:20])
                if rid is not None:
                    return rid, "url"
        if name:
            rid = by_name.get(name.strip().lower())
            if rid is not None:
                return rid, "name"
        return None, None

    def entry(self, rid: int) -> dict:
        return self.index()[0].get(rid) or {}


RECORDS = Records()
