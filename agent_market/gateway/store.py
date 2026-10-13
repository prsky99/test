"""게이트웨이 저장소 (SQLite + FTS5 검색 색인)."""

import hashlib
import json
import math
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from urllib.parse import urlparse

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
CREATE TABLE IF NOT EXISTS health_checks (
    resource_id INTEGER NOT NULL, at REAL NOT NULL, outcome TEXT NOT NULL, status_code INTEGER,
    latency_ms INTEGER, error TEXT, observed_price INTEGER
);
CREATE INDEX IF NOT EXISTS health_checks_res ON health_checks(resource_id, at);
CREATE INDEX IF NOT EXISTS health_checks_at ON health_checks(at);
CREATE TABLE IF NOT EXISTS crawl_runs (
    at REAL NOT NULL, source TEXT NOT NULL, ok INTEGER NOT NULL, seen INTEGER, new INTEGER,
    deactivated INTEGER, seconds REAL, error TEXT
);
"""

# 헬스체크 상태 컬럼 (기존 DB에는 ALTER TABLE로 추가)
HEALTH_COLUMNS = {
    "health_status": "TEXT NOT NULL DEFAULT 'unknown'",  # unknown | healthy | reachable | failing | down | retired
    "consecutive_failures": "INTEGER NOT NULL DEFAULT 0",
    "failing_since": "REAL",  # 연속 실패가 시작된 시각 (성공하면 초기화)
    "last_check_at": "REAL",
    "last_ok_at": "REAL",
    "next_check_at": "REAL",
    "last_status_code": "INTEGER",
    "last_error": "TEXT",
    "health_ok_24h": "INTEGER NOT NULL DEFAULT 0",
    "health_n_24h": "INTEGER NOT NULL DEFAULT 0",
    "content_hash": "TEXT",  # 수집한 내용의 지문. 같으면 다시 쓰지 않고 last_seen만 갱신
    "host": "TEXT",  # URL의 호스트 (호스트별로 나눠 점검하기 위해)
}


def host_of(url: str) -> str:
    try:
        return urlparse(url).hostname or url
    except ValueError:
        return url
CRAWL_RUN_COLUMNS = {"mode": "TEXT", "changed": "INTEGER", "unchanged": "INTEGER", "pages": "INTEGER"}
HEALTH_UP = ("healthy", "reachable")

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
            existing = {r[1] for r in self._db.execute("PRAGMA table_info(resources)")}
            for col, decl in HEALTH_COLUMNS.items():
                if col not in existing:
                    self._db.execute(f"ALTER TABLE resources ADD COLUMN {col} {decl}")
            self._db.execute("CREATE INDEX IF NOT EXISTS resources_due ON resources(active, next_check_at)")
            self._db.execute("CREATE INDEX IF NOT EXISTS resources_host_due ON resources(host, next_check_at)")
            missing = self._db.execute("SELECT id, url FROM resources WHERE host IS NULL").fetchall()
            if missing:  # 기존 DB: 호스트 채우기
                self._db.executemany("UPDATE resources SET host=? WHERE id=?", [(host_of(r["url"]), r["id"]) for r in missing])
            runs = {r[1] for r in self._db.execute("PRAGMA table_info(crawl_runs)")}
            for col, decl in CRAWL_RUN_COLUMNS.items():
                if col not in runs:
                    self._db.execute(f"ALTER TABLE crawl_runs ADD COLUMN {col} {decl}")

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
        with self.tx() as db:
            return self._upsert(db, r, now or time.time())[1]

    def upsert_page(self, records: list[dict], now: float | None = None) -> dict:
        """수집한 한 페이지를 한 트랜잭션으로 반영. {"new": n, "changed": n, "unchanged": n}"""
        now = now or time.time()
        counts = {"new": 0, "changed": 0, "unchanged": 0}
        with self.tx() as db:
            for r in records:
                counts[self._upsert(db, r, now)[0]] += 1
        return counts

    def _upsert(self, db, r: dict, now: float) -> tuple[str, int]:
        networks = "," + ",".join(sorted(set(r.get("networks") or []))) + ","
        values = (
            r["source"], r["kind"], r["url"], r["name"][:200], r["description"][:2000], r["category"], networks,
            r.get("price_usdc"), (r.get("pay_to") or "").lower() or None, r.get("method"),
            json.dumps(r.get("details") or {}, sort_keys=True)[:8000], r.get("calls_30d"), r.get("payers_30d"), r.get("last_called"),
        )
        digest = hashlib.sha1(json.dumps(values, default=str).encode()).hexdigest()
        row = db.execute("SELECT id, name, description, url, content_hash FROM resources WHERE key=?", (r["key"],)).fetchone()
        if row is None:
            cur = db.execute(
                """INSERT INTO resources (source, kind, url, name, description, category, networks, price_usdc, pay_to,
                   method, details, calls_30d, payers_30d, last_called, key, first_seen, last_seen, active, content_hash, host)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)""",
                (*values, r["key"], now, now, digest, host_of(r["url"])),
            )
            rid = cur.lastrowid
            db.execute("INSERT INTO resources_fts(rowid, name, description) VALUES (?,?,?)", (rid, r["name"], r["description"]))
            return "new", rid
        rid = row["id"]
        if row["content_hash"] == digest:  # 바뀐 게 없으면 확인 시각만 갱신
            db.execute("UPDATE resources SET last_seen=?, active=1 WHERE id=?", (now, rid))
            return "unchanged", rid
        db.execute(
            """UPDATE resources SET source=?, kind=?, url=?, name=?, description=?, category=?, networks=?,
               price_usdc=?, pay_to=?, method=?, details=?, calls_30d=?, payers_30d=?, last_called=?,
               last_seen=?, active=1, content_hash=?, host=? WHERE id=?""",
            (*values, now, digest, host_of(r["url"]), rid),
        )
        if row["url"] != r["url"]:  # 주소가 바뀌면 헬스 상태를 새로 시작 (제외됐던 에이전트도 다시 점검)
            db.execute(
                """UPDATE resources SET health_status='unknown', consecutive_failures=0, failing_since=NULL,
                   next_check_at=NULL, health_ok_24h=0, health_n_24h=0 WHERE id=?""", (rid,))
        if row["name"] != r["name"][:200] or row["description"] != r["description"][:2000]:
            db.execute("DELETE FROM resources_fts WHERE rowid=?", (rid,))
            db.execute("INSERT INTO resources_fts(rowid, name, description) VALUES (?,?,?)", (rid, r["name"], r["description"]))
        return "changed", rid

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
        conds = ["r.active=1", "r.health_status NOT IN ('down','retired')", f"r.kind IN ({','.join('?' * len(kinds))})"]
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

    # ---------------- 헬스체크 ----------------
    def due_for_check(self, now: float, limit: int, per_host: int | None = None) -> list[dict]:
        """점검 시각이 된 에이전트. 한 번도 점검하지 않은 것(새로 수집된 것)이 먼저, 그다음 오래 기다린 순.
        per_host를 주면 호스트마다 그 개수까지만 뽑는다 (엔드포인트가 수천 개인 호스트가 앞을 다 차지하지 않게)."""
        order = "next_check_at IS NOT NULL, next_check_at"
        if per_host is None:
            rows = self.query(
                f"""SELECT * FROM resources WHERE active=1 AND health_status != 'retired'
                    AND (next_check_at IS NULL OR next_check_at <= ?) ORDER BY {order}, random() LIMIT ?""",
                (now, limit))
        else:
            rows = self.query(
                f"""SELECT * FROM (
                      SELECT *, ROW_NUMBER() OVER (PARTITION BY host ORDER BY {order}) AS rn FROM resources
                      WHERE active=1 AND health_status != 'retired' AND (next_check_at IS NULL OR next_check_at <= ?))
                    WHERE rn <= ? ORDER BY {order}, random() LIMIT ?""",
                (now, per_host, limit))
        return [{k: r[k] for k in r.keys() if k != "rn"} for r in rows]

    def in_use_ids(self) -> set[int]:
        """게이트웨이 고객에게 현재 소개됐거나 제안 중인 에이전트 (더 자주 점검)."""
        rows = self.query(
            """SELECT current_resource AS id FROM needs WHERE status IN ('watching','active') AND current_resource IS NOT NULL
               UNION SELECT resource_id FROM offers WHERE status='pending'"""
        )
        return {r["id"] for r in rows}

    def record_health(self, rid: int, outcome: str, status_code: int | None, latency_ms: int | None,
                      error: str | None, next_check_at: float, down_after: int = 3, retire_after: float = 7 * 86400,
                      observed_price: int | None = None, observed_pay_to: str | None = None) -> dict:
        """점검 결과 저장. outcome: healthy | reachable | fail. 갱신된 상태를 돌려준다.

        down_after번 연속 실패하면 down, 실패가 retire_after(기본 7일) 넘게 이어지면 retired(점검·추천에서 제외).
        """
        now = time.time()
        with self.tx() as db:
            row = db.execute("SELECT consecutive_failures, failing_since, health_status, price_usdc FROM resources WHERE id=?",
                             (rid,)).fetchone()
            if row is None:
                return {}
            if outcome in HEALTH_UP:
                failures, status, last_ok, failing_since = 0, outcome, now, None
            else:
                failures = row["consecutive_failures"] + 1
                failing_since = row["failing_since"] or now
                last_ok = None
                if failures >= down_after and now - failing_since >= retire_after:
                    status = "retired"
                else:
                    status = "down" if failures >= down_after else "failing"
            db.execute(
                "INSERT INTO health_checks VALUES (?,?,?,?,?,?,?)",
                (rid, now, outcome, status_code, latency_ms, (error or "")[:300] or None, observed_price),
            )
            agg = db.execute(
                "SELECT COUNT(*) AS n, SUM(outcome IN ('healthy','reachable')) AS ok FROM health_checks WHERE resource_id=? AND at>?",
                (rid, now - 86400),
            ).fetchone()
            db.execute(
                """UPDATE resources SET health_status=?, consecutive_failures=?, failing_since=?, last_check_at=?,
                   last_ok_at=COALESCE(?, last_ok_at), next_check_at=?, last_status_code=?, last_error=?,
                   health_ok_24h=?, health_n_24h=?, probe_latency_ms=COALESCE(?, probe_latency_ms), probed_at=?
                   WHERE id=?""",
                (status, failures, failing_since, now, last_ok, None if status == "retired" else next_check_at, status_code, (error or "")[:300] or None,
                 agg["ok"] or 0, agg["n"], latency_ms, now, rid),
            )
            price_changed = observed_price is not None and observed_price != row["price_usdc"]
            if price_changed:
                db.execute("UPDATE resources SET price_usdc=?, pay_to=COALESCE(?, pay_to) WHERE id=?",
                           (observed_price, (observed_pay_to or "").lower() or None, rid))
        return {"status": status, "previous": row["health_status"], "consecutive_failures": failures, "failing_since": failing_since,
                "price_changed": price_changed, "health_ok_24h": agg["ok"] or 0, "health_n_24h": agg["n"]}

    def postpone(self, ids: list[int], at: float) -> None:
        """점검 결과를 기록하지 않고 나중에 다시 점검하도록 미룬다 (우리 쪽 네트워크 문제일 때)."""
        with self.tx() as db:
            db.executemany("UPDATE resources SET next_check_at=? WHERE id=?", [(at, i) for i in ids])

    def health_history(self, rid: int, limit: int = 20) -> list[dict]:
        return [dict(r) for r in self.query(
            "SELECT at, outcome, status_code, latency_ms, error, observed_price FROM health_checks WHERE resource_id=? ORDER BY at DESC LIMIT ?",
            (rid, limit))]

    def prune_health(self, before: float) -> int:
        with self.tx() as db:
            return db.execute("DELETE FROM health_checks WHERE at<?", (before,)).rowcount

    def record_crawl_run(self, source: str, report: dict) -> None:
        with self.tx() as db:
            db.execute(
                """INSERT INTO crawl_runs (at, source, ok, seen, new, deactivated, seconds, error, mode, changed, unchanged, pages)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (time.time(), source, int(report.get("ok", False)), report.get("seen"), report.get("new"),
                 report.get("deactivated"), report.get("seconds"), report.get("error"), report.get("mode"),
                 report.get("changed"), report.get("unchanged"), report.get("pages")),
            )

    def collector_stats(self) -> dict:
        q = self.query
        status = {r["health_status"]: r["n"] for r in q(
            "SELECT health_status, COUNT(*) AS n FROM resources WHERE active=1 GROUP BY health_status")}
        checked_1h = q("SELECT COUNT(*) AS n, SUM(outcome IN ('healthy','reachable')) AS ok FROM health_checks WHERE at>?",
                       (time.time() - 3600,))[0]
        overdue = q("""SELECT COUNT(*) AS n FROM resources WHERE active=1 AND health_status != 'retired'
                       AND (next_check_at IS NULL OR next_check_at < ?)""",
                    (time.time() - 3600,))[0]["n"]
        runs = [dict(r) for r in q("SELECT * FROM crawl_runs ORDER BY at DESC LIMIT 10")]
        return {
            "active_agents": sum(status.values()),
            "by_health": status,
            "by_kind_category": self.resource_counts(),
            "checks_last_hour": {"total": checked_1h["n"], "ok": checked_1h["ok"] or 0},
            "overdue_over_1h": overdue,
            "recent_crawls": runs,
        }

    # ---------------- meta ----------------
    def get_meta(self, key: str, default=None):
        rows = self.query("SELECT value FROM meta WHERE key=?", (key,))
        return json.loads(rows[0]["value"]) if rows else default

    def set_meta(self, key: str, value) -> None:
        with self.tx() as db:
            db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, json.dumps(value)))
