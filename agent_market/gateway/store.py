"""게이트웨이 저장소 (SQLite + FTS5 검색 색인)."""

import json
import math
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager

from .classify import tokens

SCHEMA = """
CREATE TABLE IF NOT EXISTS resources (
    id INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL, source TEXT NOT NULL, kind TEXT NOT NULL,
    url TEXT NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL, category TEXT NOT NULL,
    networks TEXT NOT NULL, price_usdc INTEGER, pay_to TEXT, method TEXT, details TEXT NOT NULL,
    calls_30d INTEGER, payers_30d INTEGER, last_called REAL,
    first_seen REAL NOT NULL, last_seen REAL NOT NULL, active INTEGER NOT NULL DEFAULT 1,
    probe_ok INTEGER NOT NULL DEFAULT 0, probe_fail INTEGER NOT NULL DEFAULT 0,
    probe_latency_ms INTEGER, probed_at REAL
);
CREATE INDEX IF NOT EXISTS resources_cat ON resources(category, active);
CREATE VIRTUAL TABLE IF NOT EXISTS resources_fts USING fts5(name, description);
CREATE VIRTUAL TABLE IF NOT EXISTS resources_vocab USING fts5vocab(resources_fts, 'row');
CREATE TABLE IF NOT EXISTS needs (
    need_id TEXT PRIMARY KEY, client TEXT NOT NULL, task TEXT NOT NULL, category TEXT NOT NULL,
    max_price INTEGER, networks TEXT NOT NULL, kinds TEXT NOT NULL, webhook TEXT,
    status TEXT NOT NULL, current_resource INTEGER, current_score REAL,
    free_used INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, updated REAL NOT NULL, ip TEXT
);
CREATE INDEX IF NOT EXISTS needs_client ON needs(client, category);
CREATE TABLE IF NOT EXISTS offers (
    offer_id TEXT PRIMARY KEY, need_id TEXT NOT NULL, resource_id INTEGER NOT NULL, prev_resource_id INTEGER,
    score REAL NOT NULL, prev_score REAL, teaser TEXT NOT NULL, fee INTEGER NOT NULL, free INTEGER NOT NULL,
    status TEXT NOT NULL, created REAL NOT NULL, decided_at REAL, payer TEXT, tx_hash TEXT
);
CREATE INDEX IF NOT EXISTS offers_need ON offers(need_id, status);
CREATE TABLE IF NOT EXISTS feedback (
    need_id TEXT NOT NULL, resource_id INTEGER NOT NULL, success INTEGER NOT NULL, rating INTEGER,
    created REAL NOT NULL, PRIMARY KEY (need_id, resource_id)
);
CREATE TABLE IF NOT EXISTS fee_state (
    category TEXT PRIMARY KEY, fee INTEGER NOT NULL, window_offers INTEGER NOT NULL DEFAULT 0,
    window_accepted INTEGER NOT NULL DEFAULT 0, updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS fee_history (
    category TEXT NOT NULL, old_fee INTEGER NOT NULL, new_fee INTEGER NOT NULL, conversion REAL NOT NULL, at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

RESOURCE_COLS = [
    "id", "key", "source", "kind", "url", "name", "description", "category", "networks", "price_usdc", "pay_to",
    "method", "details", "calls_30d", "payers_30d", "last_called", "first_seen", "last_seen", "active",
    "probe_ok", "probe_fail", "probe_latency_ms", "probed_at",
]


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(18)}"


class Store:
    def __init__(self, path: str = ":memory:"):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._db:
            self._db.execute("PRAGMA journal_mode=WAL") if path != ":memory:" else None
            self._db.executescript(SCHEMA)

    @contextmanager
    def tx(self):
        with self._lock, self._db:
            yield self._db

    def query(self, sql: str, params=()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, params).fetchall()

    # ---------------- resources ----------------
    def upsert_resource(self, r: dict, now: float | None = None) -> int:
        """r: key, source, kind, url, name, description, category, networks(list), price_usdc, pay_to, method,
        details(dict), calls_30d, payers_30d, last_called"""
        now = now or time.time()
        networks = "," + ",".join(sorted(set(r.get("networks") or []))) + ","
        with self.tx() as db:
            row = db.execute("SELECT id, name, description FROM resources WHERE key=?", (r["key"],)).fetchone()
            values = (
                r["source"], r["kind"], r["url"], r["name"][:200], r["description"][:2000], r["category"], networks,
                r.get("price_usdc"), (r.get("pay_to") or "").lower() or None, r.get("method"),
                json.dumps(r.get("details") or {})[:8000], r.get("calls_30d"), r.get("payers_30d"), r.get("last_called"),
            )
            if row is None:
                cur = db.execute(
                    """INSERT INTO resources (source, kind, url, name, description, category, networks, price_usdc, pay_to,
                       method, details, calls_30d, payers_30d, last_called, key, first_seen, last_seen, active)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
                    (*values, r["key"], now, now),
                )
                rid = cur.lastrowid
                db.execute("INSERT INTO resources_fts(rowid, name, description) VALUES (?,?,?)", (rid, r["name"], r["description"]))
            else:
                rid = row["id"]
                db.execute(
                    """UPDATE resources SET source=?, kind=?, url=?, name=?, description=?, category=?, networks=?,
                       price_usdc=?, pay_to=?, method=?, details=?, calls_30d=?, payers_30d=?, last_called=?,
                       last_seen=?, active=1 WHERE id=?""",
                    (*values, now, rid),
                )
                if row["name"] != r["name"][:200] or row["description"] != r["description"][:2000]:
                    db.execute("DELETE FROM resources_fts WHERE rowid=?", (rid,))
                    db.execute("INSERT INTO resources_fts(rowid, name, description) VALUES (?,?,?)", (rid, r["name"], r["description"]))
        return rid

    def deactivate_unseen(self, source: str, before: float) -> int:
        with self.tx() as db:
            return db.execute("UPDATE resources SET active=0 WHERE source=? AND last_seen<? AND active=1", (source, before)).rowcount

    def resource(self, rid: int) -> dict | None:
        rows = self.query("SELECT * FROM resources WHERE id=?", (rid,))
        return dict(rows[0]) if rows else None

    def record_probe(self, rid: int, ok: bool, latency_ms: int | None) -> None:
        col = "probe_ok" if ok else "probe_fail"
        with self.tx() as db:
            db.execute(f"UPDATE resources SET {col}={col}+1, probe_latency_ms=?, probed_at=? WHERE id=?", (latency_ms, time.time(), rid))

    def search(self, text: str, category: str, max_price: int | None, networks: list[str], kinds: list[str], limit: int = 200) -> list[dict]:
        """FTS로 관련 후보를 뽑고, 부족하면 같은 카테고리 인기순으로 채운다."""
        terms = [t for t in dict.fromkeys(tokens(text)) if len(t) > 1][:32]
        conds = ["r.active=1", f"r.kind IN ({','.join('?' * len(kinds))})"]
        params: list = list(kinds)
        if max_price is not None:
            conds.append("(r.price_usdc IS NOT NULL AND r.price_usdc <= ?)")
            params.append(max_price)
        if networks:
            conds.append("(r.kind != 'x402' OR " + " OR ".join("r.networks LIKE ?" for _ in networks) + ")")
            params += [f"%,{n},%" for n in networks]
        where = " AND ".join(conds)
        found: dict[int, dict] = {}
        if terms:
            match = " OR ".join('"' + t.replace('"', "") + '"' for t in terms)
            for row in self.query(
                f"""SELECT r.* FROM resources_fts f JOIN resources r ON r.id=f.rowid
                    WHERE resources_fts MATCH ? AND {where} ORDER BY bm25(resources_fts) LIMIT ?""",
                (match, *params, limit),
            ):
                found[row["id"]] = dict(row)
        if len(found) < limit:
            for row in self.query(
                f"SELECT r.* FROM resources r WHERE r.category=? AND {where} ORDER BY COALESCE(r.payers_30d,0) DESC LIMIT ?",
                (category, *params, limit - len(found)),
            ):
                found.setdefault(row["id"], dict(row))
        return list(found.values())

    def idf(self, terms: list[str]) -> dict[str, float]:
        if not terms:
            return {}
        n = self.query("SELECT COUNT(*) AS n FROM resources_fts")[0]["n"] or 1
        rows = self.query(f"SELECT term, doc FROM resources_vocab WHERE term IN ({','.join('?' * len(terms))})", terms)
        docs = {r["term"]: r["doc"] for r in rows}
        return {t: math.log((n + 1) / (docs.get(t, 0) + 1)) + 1 for t in terms}

    def feedback_stats(self, rid: int) -> tuple[int, int, float | None]:
        row = self.query("SELECT COUNT(*) AS n, COALESCE(SUM(success),0) AS s, AVG(rating) AS r FROM feedback WHERE resource_id=?", (rid,))[0]
        return row["n"], row["s"], row["r"]

    def resource_counts(self) -> dict:
        rows = self.query("SELECT kind, category, COUNT(*) AS n FROM resources WHERE active=1 GROUP BY kind, category")
        out: dict = {}
        for r in rows:
            out.setdefault(r["kind"], {})[r["category"]] = r["n"]
        return out

    # ---------------- meta ----------------
    def get_meta(self, key: str, default=None):
        rows = self.query("SELECT value FROM meta WHERE key=?", (key,))
        return json.loads(rows[0]["value"]) if rows else default

    def set_meta(self, key: str, value) -> None:
        with self.tx() as db:
            db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, json.dumps(value)))
