"""Daily index of our catalog for the agent-record substitute (agent.record.v1; PM 11-17 11:5x decision a).

    run_job(store)   # jobs, once a day, outside the measurement windows

Reads every catalog row once with one registered statement in id pages of 1,000 (one connection, read only) and
writes gateway-data/agent-record/index.sqlite3: a small SQLite file the substitute reads by key, so a request never
touches the production database and holds almost nothing in memory. Only what public pages already show is kept
(PM condition 1): id, name, kind, the 20-hex URL key of /api/agent/v1/check, the official registry name, grade,
reachability status and last check time. No provider contact, notes or security reasons: a row under security
review or quarantine is kept only as reviewing=1 (shown as "under review", without its grade). The file is built
beside the old one and swapped in with os.replace (condition 3).
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import time
from pathlib import Path

SELECT_PAGE = ("SELECT id, name, kind, url, CASE WHEN source='mcp-registry' THEN details END AS details, eval_grade, "
               "eval_security, health_status, last_check_at, active FROM resources WHERE id>? ORDER BY id LIMIT 1000")
PAGE = 1000
VERSION = 1


def path() -> Path:
    return Path(os.environ.get("AGENT_RECORD_INDEX") or "gateway-data/agent-record/index.sqlite3")


def url_key(url: str) -> str:
    return hashlib.sha256(url.rstrip("/").encode()).hexdigest()[:20]


def _registry_name(details) -> str | None:
    if not details:
        return None
    try:
        value = details if isinstance(details, dict) else json.loads(details)
    except (TypeError, ValueError):
        return None
    name = value.get("registry_name") if isinstance(value, dict) else None
    return name.strip().lower()[:200] if isinstance(name, str) and name.strip() else None


def row_values(r: dict):
    reviewing = 1 if r.get("eval_security") in ("quarantine", "review") else 0
    status = r.get("health_status") if r.get("active") else "inactive"
    keys = set()
    url = r.get("url")
    if isinstance(url, str) and url.startswith(("http://", "https://")):
        from .concierge.agent_check import CheckError, normalize
        try:
            canonical, _host = normalize(url)
            keys.add(url_key(canonical))
        except CheckError:
            pass
    grade = None if reviewing else (r.get("eval_grade") if r.get("eval_grade") in tuple("ABCDEF") else None)
    last = r.get("last_check_at")
    record = (int(r["id"]), str(r.get("name") or "")[:200], r.get("kind") if r.get("kind") in ("mcp", "a2a", "x402") else None,
              _registry_name(r.get("details")), grade, str(status or "unknown")[:20],
              float(last) if isinstance(last, (int, float)) else None, reviewing)
    return record, keys


def build(rows, target: Path, now: float) -> dict:
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=str(target.parent), prefix="." + target.name + ".")
    os.close(handle)
    count = keys = reviewing = 0
    try:
        db = sqlite3.connect(tmp)
        db.executescript("""
            CREATE TABLE records (id INTEGER PRIMARY KEY, name TEXT, kind TEXT, registry_name TEXT, grade TEXT,
                                  status TEXT, last_check_at REAL, reviewing INTEGER);
            CREATE TABLE url_keys (key TEXT, id INTEGER);
            CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);""")
        for r in rows:
            record, found = row_values(r)
            db.execute("INSERT OR REPLACE INTO records VALUES (?,?,?,?,?,?,?,?)", record)
            db.executemany("INSERT INTO url_keys VALUES (?,?)", [(k, record[0]) for k in found])
            count += 1
            keys += len(found)
            reviewing += record[7]
        db.executescript("""
            CREATE INDEX url_keys_key ON url_keys(key);
            CREATE INDEX records_name ON records(lower(name));
            CREATE INDEX records_registry ON records(registry_name);""")
        db.executemany("INSERT INTO meta VALUES (?,?)", [("built_at", str(now)), ("version", str(VERSION)),
                                                         ("records", str(count))])
        db.commit()
        db.close()
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return {"records": count, "url_keys": keys, "reviewing": reviewing, "path": str(target)}


def read_rows(store):
    after = 0
    while True:
        page = [dict(r) for r in store.query(SELECT_PAGE, (after,))]
        yield from page
        if len(page) < PAGE:
            return
        after = page[-1]["id"]


def run_job(store, now=None, target: Path | None = None) -> dict:
    """jobs step (once a day, outside the measurement windows)."""
    from .necklaces.watch import in_quiet_window
    now = time.time() if now is None else now
    if in_quiet_window(now):
        return {"skipped": "measurement_window"}
    started = time.time()
    out = build(read_rows(store), Path(target or path()), now)
    out["seconds"] = round(time.time() - started, 1)
    return out


class Index:
    """Read side for the substitute: a read-only connection per lookup (the file is swapped whole once a day)."""

    def __init__(self, target: Path | None = None):
        self.target = target

    def _db(self):
        p = Path(self.target or path())
        if not p.exists():
            return None
        return sqlite3.connect(f"file:{p}?mode=ro", uri=True)

    def built_at(self) -> float | None:
        db = self._db()
        if db is None:
            return None
        try:
            row = db.execute("SELECT v FROM meta WHERE k='built_at'").fetchone()
            return float(row[0]) if row else None
        except sqlite3.Error:
            return None
        finally:
            db.close()

    def find(self, keys=(), name: str | None = None):
        """The record dict for the first URL key, else for the name (catalog or registry name), else None."""
        db = self._db()
        if db is None:
            return None
        try:
            db.row_factory = sqlite3.Row
            for key in keys:
                row = db.execute("SELECT r.* FROM url_keys k JOIN records r ON r.id=k.id WHERE k.key=? ORDER BY r.id LIMIT 1",
                                 (key,)).fetchone()
                if row:
                    return dict(row) | {"matched_by": "url"}
            if name:
                low = name.strip().lower()
                row = (db.execute("SELECT * FROM records WHERE registry_name=? ORDER BY id LIMIT 1", (low,)).fetchone()
                       or db.execute("SELECT * FROM records WHERE lower(name)=? ORDER BY id LIMIT 1", (low,)).fetchone())
                if row:
                    return dict(row) | {"matched_by": "name"}
            return None
        except sqlite3.Error:
            return None
        finally:
            db.close()
