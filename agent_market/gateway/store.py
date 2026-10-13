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

from ..broker.categories import LEGACY_ALIASES
from .classify import VERSION as CLASSIFIER_VERSION
from .classify import classify, query_terms
from . import constraints as cons

CONSTRAINTS_VERSION = 2  # 추출 규칙이 바뀌면 올린다 → 저장된 에이전트의 제약 정보를 다시 채움

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
CREATE INDEX IF NOT EXISTS feedback_res ON feedback(resource_id);
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
CREATE TABLE IF NOT EXISTS erc8004_tokens (
    chain TEXT NOT NULL, agent_id INTEGER NOT NULL, uri_hash TEXT, uri TEXT, host TEXT,
    status TEXT NOT NULL,  -- pending | resolved | no_service | error | empty
    services TEXT, checked_at REAL, next_at REAL, error TEXT,
    PRIMARY KEY (chain, agent_id)
);
CREATE INDEX IF NOT EXISTS erc8004_pending ON erc8004_tokens(status, next_at);
CREATE TABLE IF NOT EXISTS wellknown_hosts (
    host TEXT PRIMARY KEY, checked_at REAL NOT NULL, found TEXT
);
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
    # 제약 정보 (gateway/constraints.py)
    "desc_lang": "TEXT",  # 설명문 언어
    "regions": "TEXT",  # 설명문에 나온 대상 나라·지역 (',br,us,')
    "auth_declared": "INTEGER",  # 레지스트리 헤더로 본 인증 필요 여부 (1/0/NULL=모름)
    "auth_observed": "INTEGER",  # 헬스체크로 본 인증 필요 여부 (MCP 401/403 → 1, 200 → 0)
    "cap_languages": "TEXT",  # 도구 파라미터로 본 지원 언어
    "cap_regions": "TEXT",  # 도구 파라미터로 본 지원 나라·지역
    "cap_currencies": "TEXT",
    "cap_tool_count": "INTEGER",
    "cap_tool_names": "TEXT",
    "cap_checked_at": "REAL",
    "cap_error": "TEXT",
    # 인증 방법 (collector/auth_discovery.py)
    "auth_method": "TEXT",  # oauth2 | api_key | bearer | basic | none | unknown
    "auth_autonomy": "TEXT",  # agent_autonomous | human_once | none_needed | unknown
    "auth_info": "TEXT",  # JSON: OAuth 주소·지원 방식, API 키 헤더·발급처, 안내 단계
    "auth_checked_at": "REAL",
    "auth_error": "TEXT",
    "auth_scope": "TEXT",  # connection(연결부터 인증) | tool(연결은 되지만 도구 호출에 인증 필요)
    # 사용 안내 (collector/usage.py)
    "usage_tools": "TEXT",  # 정리된 도구 정의 JSON (변경 비교용)
    "usage_tools_hash": "TEXT",
    "usage_guide": "TEXT",  # 연결 방법·도구별 사용법·검증된 예제 JSON
    "usage_updated_at": "REAL",  # 도구 목록(사용법)이 처음 만들어졌거나 바뀐 시각
    "usage_changes": "TEXT",  # 마지막 변경 내역 JSON (추가·삭제·변경된 도구)
    "trial_info": "TEXT",  # 마지막 실제 호출 결과 JSON
    "trial_ok": "INTEGER",
    # 품질 평가 (collector/evaluation.py)
    "eval_score": "REAL",  # 0~100 (정적 평가만 있으면 NULL)
    "eval_grade": "TEXT",  # A~F
    "eval_security": "TEXT",  # ok | review | quarantine | unknown
    "eval_coverage": "TEXT",  # full | definitions | static
    "eval_info": "TEXT",  # 축별 점수·발견 사항 JSON
    "eval_at": "REAL",
}


def host_of(url: str) -> str:
    try:
        return urlparse(url).hostname or url
    except ValueError:
        return url
NEEDS_COLUMNS = {"language": "TEXT", "region": "TEXT", "auth_pref": "TEXT",  # 요청 조건 (언어·지역·인증)
                 "min_grade": "TEXT",  # 요청 조건: 최소 품질 등급 (A~F)
                 "usage_seen_at": "REAL",  # 고객에게 사용법 변경을 마지막으로 알린 시각
                 "rescanned_at": "REAL"}  # 마지막 재평가 시각 (오래된 것부터 나눠서 재평가)
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
            self._db.execute("CREATE INDEX IF NOT EXISTS resources_eval_score ON resources(eval_score)")
            missing = self._db.execute("SELECT id, url FROM resources WHERE host IS NULL").fetchall()
            if missing:  # 기존 DB: 호스트 채우기
                self._db.executemany("UPDATE resources SET host=? WHERE id=?", [(host_of(r["url"]), r["id"]) for r in missing])
            self._reclassify_if_needed()
            self._backfill_constraints_if_needed()
            need_cols = {r[1] for r in self._db.execute("PRAGMA table_info(needs)")}
            for col, decl in NEEDS_COLUMNS.items():
                if col not in need_cols:
                    self._db.execute(f"ALTER TABLE needs ADD COLUMN {col} {decl}")
            self._db.execute("CREATE INDEX IF NOT EXISTS needs_rescan ON needs(status, rescanned_at)")
            runs = {r[1] for r in self._db.execute("PRAGMA table_info(crawl_runs)")}
            for col, decl in CRAWL_RUN_COLUMNS.items():
                if col not in runs:
                    self._db.execute(f"ALTER TABLE crawl_runs ADD COLUMN {col} {decl}")

    @staticmethod
    def _text_constraints(kind: str, name: str, description: str, details: dict | str | None) -> tuple:
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except ValueError:
                details = {}
        details = details or {}
        text = f"{name} {description}"
        if kind == "mcp":
            auth = cons.declared_auth(details.get("remotes"))
        elif kind == "x402":
            auth = False  # 결제는 필요하지만 계정·API 키는 필요 없음
        else:
            auth = None
        return cons.detect_language(text), cons.pack(cons.regions_in_text(text)), None if auth is None else int(auth)

    def _backfill_constraints_if_needed(self) -> None:
        row = self._db.execute("SELECT value FROM meta WHERE key='constraints_version'").fetchone()
        if row and json.loads(row["value"]) == CONSTRAINTS_VERSION:
            return
        rows = self._db.execute("SELECT id, kind, name, description, details FROM resources").fetchall()
        self._db.executemany(
            "UPDATE resources SET desc_lang=?, regions=?, auth_declared=? WHERE id=?",
            [(*self._text_constraints(r["kind"], r["name"], r["description"], r["details"]), r["id"]) for r in rows],
        )
        self._db.execute("INSERT OR REPLACE INTO meta VALUES ('constraints_version', ?)", (json.dumps(CONSTRAINTS_VERSION),))

    def _reclassify_if_needed(self) -> None:
        """분류 기준(카테고리·키워드)이 바뀌었으면 저장된 에이전트를 다시 분류한다 (한 번만)."""
        row = self._db.execute("SELECT value FROM meta WHERE key='classifier_version'").fetchone()
        if row and json.loads(row["value"]) == CLASSIFIER_VERSION:
            return
        rows = self._db.execute("SELECT id, source, kind, name, description, category, usage_tools FROM resources").fetchall()
        updates = []
        for r in rows:
            if r["source"] == "registered":  # 직접 등록한 에이전트는 자기가 밝힌 카테고리를 유지 (예전 ID만 변환)
                new = LEGACY_ALIASES.get(r["category"], r["category"])
            else:
                text = f"{r['name']} {r['description']}"
                if r["kind"] == "a2a" and r["usage_tools"]:  # A2A는 조사한 card의 스킬까지 (등록부 설명은 짧다)
                    try:
                        text += " " + " ".join(f"{s.get('title', '')} {s.get('description', '')} {' '.join(s.get('tags') or [])}"
                                               for s in json.loads(r["usage_tools"]))
                    except (ValueError, AttributeError, TypeError):
                        pass
                new = classify(text)
            if new != r["category"]:
                updates.append((new, r["id"]))
        self._db.executemany("UPDATE resources SET category=? WHERE id=?", updates)
        for old, new in LEGACY_ALIASES.items():
            self._db.execute("UPDATE needs SET category=? WHERE category=?", (new, old))
        self._db.execute("INSERT OR REPLACE INTO meta VALUES ('classifier_version', ?)", (json.dumps(CLASSIFIER_VERSION),))

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
        lang, regions, auth = self._text_constraints(r["kind"], r["name"], r["description"], r.get("details"))
        row = db.execute("SELECT id, name, description, url, content_hash FROM resources WHERE key=?", (r["key"],)).fetchone()
        if row is None:
            cur = db.execute(
                """INSERT INTO resources (source, kind, url, name, description, category, networks, price_usdc, pay_to,
                   method, details, calls_30d, payers_30d, last_called, key, first_seen, last_seen, active, content_hash, host,
                   desc_lang, regions, auth_declared)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?,?)""",
                (*values, r["key"], now, now, digest, host_of(r["url"]), lang, regions, auth),
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
               last_seen=?, active=1, content_hash=?, host=?, desc_lang=?, regions=?, auth_declared=? WHERE id=?""",
            (*values, now, digest, host_of(r["url"]), lang, regions, auth, rid),
        )
        if r["kind"] in ("mcp", "a2a"):  # 레지스트리 항목(버전·저장소 등)이 바뀌면 기능 조사·품질 평가를 다시
            db.execute("UPDATE resources SET cap_checked_at=NULL, eval_at=NULL WHERE id=?", (rid,))
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

    def search(self, text: str, category: str, max_price: int | None, networks: list[str], kinds: list[str], limit: int = 200,
               region: str | None = None, auth_free: bool = False, agent_usable: bool = False,
               min_grade: str | None = None) -> list[dict]:
        """FTS로 관련 후보를 뽑고, 부족하면 같은 카테고리 인기순으로 채운다.

        region: 다른 나라·지역 전용 데이터를 다루는 에이전트는 뺀다 (지역 표시가 없는 전 세계 공통 에이전트는 남김).
        auth_free: 계정·API 키가 필요한 것으로 확인된 에이전트는 뺀다 (모르는 것은 남김).
        agent_usable: 사람 없이 에이전트 혼자 쓸 수 있는 것만 (인증 불필요 또는 OAuth client_credentials + 자동 등록).
        min_grade: 품질 평가 등급이 이 이상인 것만 (평가가 없는 x402 등은 남김). 보안 격리된 서버는 항상 뺀다.
        """
        terms = query_terms(text)
        conds = ["r.active=1", "r.health_status NOT IN ('down','retired')", f"r.kind IN ({','.join('?' * len(kinds))})",
                 "COALESCE(r.eval_security, '') != 'quarantine'"]
        params: list = list(kinds)
        if min_grade and min_grade.upper() in "ABCDF":
            allowed = "ABCDF"[:"ABCDF".index(min_grade.upper()) + 1]
            conds.append(f"(r.eval_grade IS NULL OR r.eval_grade IN ({','.join('?' * len(allowed))}))")
            params += list(allowed)
        if region:
            conds.append("((r.regions IS NULL AND r.cap_regions IS NULL) OR r.regions LIKE ? OR r.cap_regions LIKE ?)")
            params += [f"%,{region},%"] * 2
        if auth_free:
            conds.append("COALESCE(r.auth_observed, r.auth_declared, 0) = 0")
        if agent_usable:
            conds.append("(COALESCE(r.auth_observed, r.auth_declared, 0) = 0 OR r.auth_autonomy = 'agent_autonomous')")
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

    def feedback_stats_many(self, rids: list[int]) -> dict[int, tuple[int, int, float | None]]:
        """여러 후보의 고객 평가를 한 번에 (후보마다 쿼리하지 않게). 평가가 없는 후보는 결과에 없다."""
        if not rids:
            return {}
        rows = self.query(f"""SELECT resource_id, COUNT(*) AS n, COALESCE(SUM(success),0) AS s, AVG(rating) AS r FROM feedback
                              WHERE resource_id IN ({','.join('?' * len(rids))}) GROUP BY resource_id""", list(rids))
        return {r["resource_id"]: (r["n"], r["s"], r["r"]) for r in rows}

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
                      observed_price: int | None = None, observed_pay_to: str | None = None,
                      auth_observed: bool | None = None) -> dict:
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
            if auth_observed is not None:
                db.execute("UPDATE resources SET auth_observed=? WHERE id=?", (int(auth_observed), rid))
            price_changed = observed_price is not None and observed_price != row["price_usdc"]
            if price_changed:
                db.execute("UPDATE resources SET price_usdc=?, pay_to=COALESCE(?, pay_to) WHERE id=?",
                           (observed_price, (observed_pay_to or "").lower() or None, rid))
        return {"status": status, "previous": row["health_status"], "consecutive_failures": failures, "failing_since": failing_since,
                "price_changed": price_changed, "health_ok_24h": agg["ok"] or 0, "health_n_24h": agg["n"]}

    # ---------------- 기능 조사 (tools/list) ----------------
    def due_for_capability(self, now: float, max_age: float, limit: int, per_host: int = 2, kind: str = "mcp") -> list[dict]:
        """기능을 조사할 에이전트: MCP는 인증 없이 응답하는(healthy) 서버, A2A는 agent card가 열리는(healthy) 에이전트 중
        조사한 지 max_age가 지난 것. 호스트당 per_host개."""
        rows = self.query(
            """SELECT * FROM (
                 SELECT *, ROW_NUMBER() OVER (PARTITION BY host ORDER BY cap_checked_at IS NOT NULL, cap_checked_at) AS rn
                 FROM resources WHERE active=1 AND kind=? AND health_status='healthy'
                 AND (cap_checked_at IS NULL OR cap_checked_at < ?))
               WHERE rn <= ? ORDER BY cap_checked_at IS NOT NULL, cap_checked_at, random() LIMIT ?""",
            (kind, now - max_age, per_host, limit))
        return [{k: r[k] for k in r.keys() if k != "rn"} for r in rows]

    def record_capability(self, rid: int, caps: dict | None, error: str | None = None) -> None:
        with self.tx() as db:
            if caps is None:
                db.execute("UPDATE resources SET cap_checked_at=?, cap_error=? WHERE id=?", (time.time(), (error or "")[:300], rid))
                return
            db.execute(
                """UPDATE resources SET cap_languages=?, cap_regions=?, cap_currencies=?, cap_tool_count=?, cap_tool_names=?,
                   cap_checked_at=?, cap_error=NULL WHERE id=?""",
                (cons.pack(caps["languages"]), cons.pack(caps["regions"]), cons.pack(caps["currencies"]), caps["tool_count"],
                 json.dumps(caps["tool_names"]), time.time(), rid))

    # ---------------- 인증 방법 조사 ----------------
    def due_for_auth(self, now: float, max_age: float, limit: int, per_host: int = 1) -> list[dict]:
        """인증이 필요한 것으로 보이는 MCP 중 인증 방법을 조사한 지 max_age가 지난 것. 호스트당 per_host개."""
        rows = self.query(
            """SELECT * FROM (
                 SELECT *, ROW_NUMBER() OVER (PARTITION BY host ORDER BY auth_checked_at IS NOT NULL, auth_checked_at) AS rn
                 FROM resources WHERE active=1 AND kind='mcp' AND health_status NOT IN ('down','retired')
                 AND COALESCE(auth_observed, auth_declared) = 1
                 AND (auth_checked_at IS NULL OR auth_checked_at < ?))
               WHERE rn <= ? ORDER BY auth_checked_at IS NOT NULL, auth_checked_at, random() LIMIT ?""",
            (now - max_age, per_host, limit))
        return [{k: r[k] for k in r.keys() if k != "rn"} for r in rows]

    def record_auth(self, rid: int, found: dict | None, error: str | None = None) -> None:
        with self.tx() as db:
            if found is None:
                db.execute("UPDATE resources SET auth_checked_at=?, auth_error=? WHERE id=?", (time.time(), (error or "")[:300], rid))
                return
            db.execute(
                "UPDATE resources SET auth_method=?, auth_autonomy=?, auth_info=?, auth_checked_at=?, auth_error=NULL WHERE id=?",
                (found["method"], found["autonomy"], json.dumps(found["info"]), time.time(), rid))  # 자르지 않음 (조사 단계에서 줄임)
            if found["method"] == "none":  # 실제로는 인증 없이 동작 (도구 단계 인증이 확인된 경우는 제외)
                db.execute("UPDATE resources SET auth_observed=0 WHERE id=? AND COALESCE(auth_scope,'') != 'tool'", (rid,))

    def set_category(self, rid: int, category: str) -> None:
        with self.tx() as db:
            db.execute("UPDATE resources SET category=? WHERE id=?", (category, rid))

    def set_auth_observed(self, rid: int, required: bool) -> None:
        with self.tx() as db:
            db.execute("UPDATE resources SET auth_observed=?, auth_scope='connection' WHERE id=?", (int(required), rid))

    def mark_tool_level_auth(self, rid: int) -> None:
        """연결은 인증 없이 되지만 도구 호출에서 인증을 요구함 → 인증 필요로 표시하고 인증 방법을 다시 조사."""
        with self.tx() as db:
            db.execute("UPDATE resources SET auth_observed=1, auth_scope='tool', auth_checked_at=NULL WHERE id=?", (rid,))

    # ---------------- 사용 안내 ----------------
    def record_usage(self, rid: int, tools: list[dict], digest: str, guide: dict, changes: dict | None,
                     trial: dict | None) -> bool:
        """사용 안내 저장. 도구 목록이 바뀌었으면 usage_updated_at을 갱신하고 True를 돌려준다."""
        now = time.time()
        with self.tx() as db:
            row = db.execute("SELECT usage_tools_hash FROM resources WHERE id=?", (rid,)).fetchone()
            changed = row is not None and row["usage_tools_hash"] != digest
            db.execute(
                """UPDATE resources SET usage_tools=?, usage_tools_hash=?, usage_guide=?,
                   usage_updated_at=CASE WHEN ? THEN ? ELSE usage_updated_at END,
                   usage_changes=CASE WHEN ? THEN ? ELSE usage_changes END WHERE id=?""",
                (json.dumps(tools), digest, json.dumps(guide), changed, now, changed and changes is not None,
                 json.dumps(changes) if changes else None, rid))
            if trial is not None:
                db.execute("UPDATE resources SET trial_info=?, trial_ok=? WHERE id=?", (json.dumps(trial), int(bool(trial.get("ok"))), rid))
        return changed

    # ---------------- 품질 평가 ----------------
    def record_evaluation(self, rid: int, ev: dict) -> None:
        with self.tx() as db:
            db.execute("""UPDATE resources SET eval_score=?, eval_grade=?, eval_security=?, eval_coverage=?, eval_info=?, eval_at=?
                          WHERE id=?""",
                       (ev.get("score"), ev.get("grade"), ev.get("security"), ev.get("coverage"),
                        json.dumps(ev, ensure_ascii=False), ev.get("at") or time.time(), rid))

    def score_percentile(self, score: float, kind: str = "mcp") -> float | None:
        """같은 종류에서 평가 점수가 이보다 낮은 비율 (0~1). 등급이 A에 몰려도 상대 위치를 알 수 있게."""
        row = self.query("""SELECT COUNT(*) AS n, SUM(eval_score < ?) AS lower FROM resources
                            WHERE active=1 AND kind=? AND eval_score IS NOT NULL""", (score, kind))[0]
        return round((row["lower"] or 0) / row["n"], 3) if row["n"] >= 20 else None

    def due_for_static_evaluation(self, now: float, max_age: float, limit: int) -> list[dict]:
        """연결부터 인증이 필요해 도구를 볼 수 없는 MCP: 출처 정적 평가만 (네트워크 요청 없음)."""
        return [dict(r) for r in self.query(
            """SELECT * FROM resources WHERE active=1 AND kind='mcp' AND health_status NOT IN ('down','retired')
               AND COALESCE(auth_observed, auth_declared, 0) = 1 AND COALESCE(auth_scope, 'connection') != 'tool'
               AND (eval_at IS NULL OR eval_at < ?) ORDER BY eval_at IS NOT NULL, eval_at LIMIT ?""",
            (now - max_age, limit))]

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
        c = q("""SELECT
                   SUM(COALESCE(auth_observed, auth_declared) = 1) AS auth_required,
                   SUM(COALESCE(auth_observed, auth_declared) = 0) AS auth_free,
                   SUM(COALESCE(auth_observed, auth_declared) IS NULL) AS auth_unknown,
                   SUM(regions IS NOT NULL OR cap_regions IS NOT NULL) AS region_specific,
                   SUM(cap_checked_at IS NOT NULL AND cap_error IS NULL) AS capabilities_checked,
                   SUM(cap_languages IS NOT NULL) AS with_language_options,
                   SUM(auth_method IS NOT NULL) AS auth_method_known,
                   SUM(auth_autonomy = 'agent_autonomous') AS auth_agent_autonomous,
                   SUM(usage_guide IS NOT NULL) AS usage_guides,
                   SUM(trial_ok = 1) AS verified_working,
                   SUM(trial_ok = 0) AS trial_failed,
                   SUM(usage_changes IS NOT NULL AND usage_updated_at > strftime('%s','now') - 86400) AS usage_changed_24h
                 FROM resources WHERE active=1 AND health_status != 'retired'""")[0]
        langs = {r["desc_lang"]: r["n"] for r in q(
            "SELECT desc_lang, COUNT(*) AS n FROM resources WHERE active=1 AND desc_lang IS NOT NULL GROUP BY desc_lang ORDER BY n DESC LIMIT 10")}
        return {
            "active_agents": sum(status.values()),
            "by_health": status,
            "by_kind_category": self.resource_counts(),
            "checks_last_hour": {"total": checked_1h["n"], "ok": checked_1h["ok"] or 0},
            "overdue_over_1h": overdue,
            "recent_crawls": runs,
            "constraints": {**{k: c[k] or 0 for k in c.keys()}, "description_languages": langs,
                            "auth_methods": {r["auth_method"]: r["n"] for r in q(
                                "SELECT auth_method, COUNT(*) AS n FROM resources WHERE active=1 AND auth_method IS NOT NULL GROUP BY auth_method")}},
            "evaluation": self.evaluation_stats(),
            "evaluation_by_kind": {k: self.evaluation_stats(k) for k in ("mcp", "a2a")},
            "agent_sources": self.agent_source_stats(),
        }

    def evaluation_stats(self, kind: str | None = None) -> dict:
        q = self.query
        base = "FROM resources WHERE active=1 AND health_status != 'retired' AND eval_at IS NOT NULL" + \
            (f" AND kind='{kind}'" if kind in ("mcp", "a2a") else "")
        avg = q(f"SELECT COUNT(*) AS n, AVG(eval_score) AS avg, SUM(eval_at > strftime('%s','now') - 86400) AS last_24h {base}")[0]
        return {
            "evaluated": avg["n"],
            "evaluated_24h": avg["last_24h"] or 0,
            "average_score": round(avg["avg"], 1) if avg["avg"] is not None else None,
            "by_grade": {r["g"]: r["n"] for r in q(f"SELECT COALESCE(eval_grade, 'static') AS g, COUNT(*) AS n {base} GROUP BY g ORDER BY g")},
            "by_security": {r["eval_security"]: r["n"] for r in q(f"SELECT eval_security, COUNT(*) AS n {base} GROUP BY eval_security")},
            "by_coverage": {r["eval_coverage"]: r["n"] for r in q(f"SELECT eval_coverage, COUNT(*) AS n {base} GROUP BY eval_coverage")},
        }

    def agent_source_stats(self) -> dict:
        """A2A 에이전트 수집 현황: 출처별 수, ERC-8004 체인별 조사 진행."""
        q = self.query
        return {
            "a2a_by_source": {r["source"]: r["n"] for r in q(
                "SELECT source, COUNT(*) AS n FROM resources WHERE active=1 AND kind='a2a' GROUP BY source")},
            "erc8004": {f"{r['chain']}:{r['status']}": r["n"] for r in q(
                "SELECT chain, status, COUNT(*) AS n FROM erc8004_tokens GROUP BY chain, status")},
            "wellknown_hosts_checked": q("SELECT COUNT(*) AS n FROM wellknown_hosts")[0]["n"],
            "wellknown_hosts_found": q("SELECT COUNT(*) AS n FROM wellknown_hosts WHERE found IS NOT NULL")[0]["n"],
        }

    # ---------------- meta ----------------
    def get_meta(self, key: str, default=None):
        rows = self.query("SELECT value FROM meta WHERE key=?", (key,))
        return json.loads(rows[0]["value"]) if rows else default

    def set_meta(self, key: str, value) -> None:
        with self.tx() as db:
            db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, json.dumps(value)))
