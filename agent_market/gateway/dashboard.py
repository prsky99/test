"""관리 대시보드: 수집 상태·진행 상황·전체 통계·에러를 웹 화면으로 보고, 수집을 관리한다.

    브라우저에서 http://127.0.0.1:8200/admin/ui

모든 경로가 /admin 아래라 배포 환경에서는 Caddy가 외부 접근을 막는다(deploy/Caddyfile).
접근 권한
- ADMIN_TOKEN이 있으면 Authorization: Bearer <token> (화면에서 한 번 입력하면 브라우저 탭에 보관)
- ADMIN_TOKEN이 없으면 같은 PC(loopback)에서 localhost 주소로 접속할 때만 허용
- 모든 API 요청에 X-Dashboard 헤더가 필요하다. 다른 사이트가 브라우저를 통해 몰래 보내는 요청(CSRF)은
  이 헤더를 붙일 수 없고(CORS 사전 요청이 거부됨), Host 검사로 DNS rebinding도 막는다.

조회는 별도의 읽기 전용 SQLite 연결로 해서, 수집기가 쓰는 연결의 잠금을 오래 잡지 않는다(WAL 모드).
"""

import collections
import hmac
import ipaddress
import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from ..broker.categories import CATEGORIES
from ..collector.agent import CollectorAgent
from . import sns
from .classify import query_terms
from .store import Store, host_of

log = logging.getLogger("agent_market.gateway.dashboard")

PAGE = Path(__file__).with_name("dashboard.html")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}
META_KEYS = ["last_health_batch", "last_capabilities_batch", "last_auth_batch", "last_agents_batch",
             "last_erc8004_scan", "last_agent_discovery", "last_rescan", "last_crawl"]
KINDS = ("a2a", "mcp", "x402")  # 화면 표시 순서
INSIGHTS_TTL = 120  # 설명 화면 통계는 2분간 재사용 (큰 표를 여러 번 훑으므로)


class LogBuffer(logging.Handler):
    """최근 경고·오류 로그를 메모리에 보관해 화면에 보여 준다 (프로세스를 다시 시작하면 비워짐)."""

    def __init__(self, capacity: int = 500):
        super().__init__(level=logging.WARNING)
        self.records: collections.deque = collections.deque(maxlen=capacity)
        self.counts: collections.Counter = collections.Counter()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = record.getMessage()
            if record.exc_info and record.exc_info[1] is not None:
                text += f"\n{type(record.exc_info[1]).__name__}: {record.exc_info[1]}"
            self.records.append({"at": record.created, "level": record.levelname, "logger": record.name, "message": text[:2000]})
            self.counts[record.levelname] += 1
        except Exception:  # 로그 기록 실패가 앱을 멈추지 않게
            pass


_log_buffer: LogBuffer | None = None


def log_buffer() -> LogBuffer:
    """프로세스당 하나. 루트 로거에 붙여 모든 모듈의 경고·오류를 모은다."""
    global _log_buffer
    if _log_buffer is None:
        _log_buffer = LogBuffer()
        logging.getLogger().addHandler(_log_buffer)
    return _log_buffer


def _loopback(host: str | None) -> bool:
    try:
        return host is not None and ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _host_name(host_header: str | None) -> str:
    """Host 헤더에서 포트를 뗀 이름 ('[::1]:8200' → '[::1]', 'localhost:8200' → 'localhost')."""
    h = (host_header or "").lower()
    return h.split("]")[0] + "]" if h.startswith("[") else h.rsplit(":", 1)[0]


def _rows(cur) -> list[dict]:
    return [dict(r) for r in cur]


def _meta(value: str | None):
    try:
        return json.loads(value) if value else None
    except ValueError:
        return None


def dashboard_router(store: Store, db_path: str, admin_token: str | None, collector: CollectorAgent | None,
                     service=None, crawler=None, front=None) -> APIRouter:
    router = APIRouter()
    logs = log_buffer()
    started = time.time()
    actions: dict[str, dict] = {}  # 백그라운드로 돌린 관리 작업의 상태 (수집·재평가)

    @contextmanager
    def reader():
        """읽기 전용 연결. 메모리 DB(테스트)는 저장소 연결을 그대로 쓴다."""
        if db_path == ":memory:":
            with store._lock:
                yield store._db
            return
        db = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    def authorize(request: Request, authorization: str | None, x_dashboard: str | None) -> None:
        if not x_dashboard:
            raise HTTPException(403, "X-Dashboard 헤더가 필요합니다.")
        if admin_token:
            if authorization is None or not hmac.compare_digest(authorization, f"Bearer {admin_token}"):
                raise HTTPException(401, "ADMIN_TOKEN이 필요합니다.")
            return
        if not _loopback(request.client.host if request.client else None) or _host_name(request.headers.get("host")) not in LOCAL_HOSTS:
            raise HTTPException(401, "ADMIN_TOKEN이 설정되지 않아 이 PC에서 localhost 주소로만 접속할 수 있습니다.")

    def guard(request: Request, authorization: str | None = Header(default=None), x_dashboard: str | None = Header(default=None)):
        authorize(request, authorization, x_dashboard)

    auth = [Depends(guard)]

    # ---------------- 화면 ----------------
    @router.get("/admin/ui", response_class=HTMLResponse, include_in_schema=False)
    def page():
        return HTMLResponse(PAGE.read_text(encoding="utf-8"), headers={
            "cache-control": "no-store", "x-frame-options": "DENY", "referrer-policy": "no-referrer",
            "content-security-policy": "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                                       "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"})

    @router.get("/admin/api/session", dependencies=auth)
    def session():
        return {"ok": True, "token_required": bool(admin_token)}

    # ---------------- 개요 ----------------
    @router.get("/admin/api/overview", dependencies=auth)
    def overview():
        now = time.time()
        with reader() as db:
            q = lambda sql, p=(): _rows(db.execute(sql, p))  # noqa: E731
            by_kind_status = q("""SELECT kind, active, health_status AS status, COUNT(*) AS n FROM resources
                                  GROUP BY kind, active, health_status""")
            checks_1h = q("""SELECT COUNT(*) AS n, COALESCE(SUM(outcome IN ('healthy','reachable')),0) AS ok
                             FROM health_checks WHERE at>?""", (now - 3600,))[0]
            checks_5m = q("SELECT COUNT(*) AS n FROM health_checks WHERE at>?", (now - 300,))[0]["n"]
            backlog = q("""SELECT
                             SUM(next_check_at IS NULL) AS never,
                             SUM(next_check_at <= ?) AS due,
                             SUM(next_check_at < ?) AS overdue_1h
                           FROM resources WHERE active=1 AND health_status != 'retired'""", (now, now - 3600))[0]
            categories = q("""SELECT category, kind, COUNT(*) AS n FROM resources WHERE active=1 AND health_status != 'retired'
                              GROUP BY category, kind""")
            erc = q("SELECT chain, status, COUNT(*) AS n FROM erc8004_tokens GROUP BY chain, status")
            wk = q("SELECT COUNT(*) AS checked, SUM(found IS NOT NULL) AS found FROM wellknown_hosts")[0]
            grades = q("""SELECT kind, COALESCE(eval_grade, 'static') AS grade, COUNT(*) AS n FROM resources
                          WHERE active=1 AND health_status != 'retired' AND eval_at IS NOT NULL GROUP BY kind, grade""")
            security = q("""SELECT eval_security AS security, COUNT(*) AS n FROM resources
                            WHERE active=1 AND eval_at IS NOT NULL GROUP BY eval_security""")
            surveys = q("""SELECT
                             SUM(cap_checked_at > ?) AS capabilities_24h, SUM(auth_checked_at > ?) AS auth_24h,
                             SUM(eval_at > ?) AS evaluations_24h, SUM(usage_guide IS NOT NULL) AS usage_guides,
                             SUM(trial_ok = 1) AS verified_working, SUM(trial_ok = 0) AS trial_failed
                           FROM resources WHERE active=1""", (now - 86400,) * 3)[0]
            needs = q("SELECT status, COUNT(*) AS n FROM needs GROUP BY status")
            offers = q("SELECT status, COUNT(*) AS n FROM offers GROUP BY status")
            meta = {r["key"]: _meta(r["value"]) for r in q(
                f"SELECT key, value FROM meta WHERE key IN ({','.join('?' * len(META_KEYS))}) OR key LIKE 'crawl_pass:%' "
                "OR key LIKE 'erc8004_next:%' OR key LIKE 'erc8004_rescan:%'", META_KEYS)}
            crawl_runs = q("SELECT * FROM crawl_runs ORDER BY at DESC LIMIT 30")
        erc_chains: dict = {}
        for r in erc:
            c = erc_chains.setdefault(r["chain"], {"statuses": {}, "next_id": meta.get(f"erc8004_next:{r['chain']}"),
                                                    "rescan_cursor": meta.get(f"erc8004_rescan:{r['chain']}")})
            c["statuses"][r["status"]] = r["n"]
        return {
            "now": now, "started_at": started,
            "collector": None if collector is None else {
                "paused": collector.paused.is_set(), "started_at": collector.started_at, "threads": collector.thread_status()},
            "policy": None if service is None else ("free" if service.policy.free else "paid"),
            "resources": by_kind_status,
            "health": {"checks_1h": checks_1h["n"], "ok_1h": checks_1h["ok"], "checks_5m": checks_5m,
                       "never_checked": backlog["never"] or 0, "due_now": backlog["due"] or 0, "overdue_1h": backlog["overdue_1h"] or 0},
            "crawl": {"in_progress": {k.split(":", 1)[1]: v for k, v in meta.items() if k.startswith("crawl_pass:") and v},
                      "last": meta.get("last_crawl"), "runs": crawl_runs},
            "loops": {k: meta.get(k) for k in META_KEYS if k != "last_crawl"},
            "categories": categories,
            "erc8004": erc_chains,
            "wellknown": {"checked": wk["checked"], "found": wk["found"] or 0},
            "evaluation": {"grades": grades, "security": security},
            "surveys": surveys,
            "needs": {r["status"]: r["n"] for r in needs},
            "offers": {r["status"]: r["n"] for r in offers},
            "log_counts": dict(logs.counts),
            "actions": actions,
        }

    @router.get("/admin/api/timeseries", dependencies=auth)
    def timeseries(hours: int = Query(6, ge=1, le=168)):
        """헬스체크 처리량 (구간별 성공·응답·실패 수)."""
        now = time.time()
        bucket = 300 if hours <= 6 else 900 if hours <= 24 else 3600
        start = (now - hours * 3600) // bucket * bucket
        with reader() as db:
            rows = _rows(db.execute(
                f"""SELECT CAST(at / {bucket} AS INT) * {bucket} AS t, outcome, COUNT(*) AS n FROM health_checks
                    WHERE at >= ? GROUP BY t, outcome ORDER BY t""", (start,)))
        series: dict = {}
        for r in rows:
            series.setdefault(r["t"], {"t": r["t"], "healthy": 0, "reachable": 0, "fail": 0})[
                r["outcome"] if r["outcome"] in ("healthy", "reachable") else "fail"] += r["n"]
        return {"bucket_seconds": bucket, "start": start, "points": list(series.values())}

    # ---------------- 에러 ----------------
    @router.get("/admin/api/errors", dependencies=auth)
    def errors(hours: int = Query(1, ge=1, le=168)):
        since = time.time() - hours * 3600
        with reader() as db:
            q = lambda sql, p=(): _rows(db.execute(sql, p))  # noqa: E731
            health = q("""SELECT COALESCE(substr(h.error, 1, 90), 'HTTP ' || h.status_code, '(no detail)') AS error,
                                 COUNT(*) AS n, COUNT(DISTINCT h.resource_id) AS agents, MAX(h.at) AS last_at,
                                 MIN(r.url) AS sample_url
                          FROM health_checks h JOIN resources r ON r.id=h.resource_id
                          WHERE h.at>? AND h.outcome NOT IN ('healthy','reachable')
                          GROUP BY 1 ORDER BY n DESC LIMIT 25""", (since,))
            hosts = q("""SELECT host, COUNT(*) AS n, SUM(health_status='down') AS down, MIN(last_error) AS sample_error
                         FROM resources WHERE active=1 AND health_status IN ('failing','down')
                         GROUP BY host ORDER BY n DESC LIMIT 20""")
            erc = q("""SELECT substr(replace(error, '|', ' '), 1, 90) AS error, status, COUNT(*) AS n FROM erc8004_tokens
                       WHERE status IN ('error','no_service') AND error IS NOT NULL
                       GROUP BY 1, status ORDER BY n DESC LIMIT 20""")
            caps = q("""SELECT substr(cap_error, 1, 90) AS error, COUNT(*) AS n FROM resources
                        WHERE active=1 AND cap_error IS NOT NULL GROUP BY 1 ORDER BY n DESC LIMIT 15""")
            auths = q("""SELECT substr(auth_error, 1, 90) AS error, COUNT(*) AS n FROM resources
                         WHERE active=1 AND auth_error IS NOT NULL GROUP BY 1 ORDER BY n DESC LIMIT 15""")
            crawls = q("SELECT * FROM crawl_runs WHERE ok=0 ORDER BY at DESC LIMIT 20")
        return {"hours": hours, "health": health, "failing_hosts": hosts, "erc8004": erc, "capabilities": caps,
                "auth": auths, "crawl_failures": crawls, "logs": list(reversed(logs.records))[:200]}

    # ---------------- 에이전트 ----------------
    SORTS = {"recent": "r.last_check_at DESC", "name": "r.name COLLATE NOCASE", "quality": "r.eval_score DESC",
             "failures": "r.consecutive_failures DESC", "popular": "COALESCE(r.payers_30d,0) DESC", "new": "r.first_seen DESC"}

    @router.get("/admin/api/agents", dependencies=auth)
    def agents(q: str | None = None, kind: str | None = None, status: str | None = None, category: str | None = None,
               source: str | None = None, grade: str | None = None, active: str = Query("1", pattern="^(0|1|all)$"),
               sort: str = "recent", offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
        conds, params = [], []
        if active != "all":
            conds.append("r.active=?"); params.append(int(active))
        for col, val in (("kind", kind), ("health_status", status), ("category", category), ("source", source),
                         ("eval_grade", grade)):
            if val:
                conds.append(f"r.{col}=?"); params.append(val)
        if q:
            conds.append("(r.name LIKE ? OR r.url LIKE ? OR r.description LIKE ?)"); params += [f"%{q}%"] * 3
        where = " AND ".join(conds) or "1=1"
        order = SORTS.get(sort, SORTS["recent"])
        with reader() as db:
            total = db.execute(f"SELECT COUNT(*) FROM resources r WHERE {where}", params).fetchone()[0]
            rows = _rows(db.execute(
                f"""SELECT r.id, r.kind, r.source, r.name, r.url, r.category, r.active, r.health_status, r.consecutive_failures,
                           r.last_check_at, r.last_ok_at, r.last_status_code, r.last_error, r.health_ok_24h, r.health_n_24h,
                           r.probe_latency_ms, r.eval_grade, r.eval_score, r.eval_security, r.trial_ok, r.price_usdc,
                           r.payers_30d, r.first_seen
                    FROM resources r WHERE {where} ORDER BY {order} NULLS LAST, r.id LIMIT ? OFFSET ?""",
                (*params, limit, offset)))
        return {"total": total, "offset": offset, "limit": limit, "items": rows}

    @router.get("/admin/api/agents/{rid}", dependencies=auth)
    def agent(rid: int):
        with reader() as db:
            row = db.execute("SELECT * FROM resources WHERE id=?", (rid,)).fetchone()
            if row is None:
                raise HTTPException(404, "없는 에이전트")
            history = _rows(db.execute("""SELECT at, outcome, status_code, latency_ms, error FROM health_checks
                                          WHERE resource_id=? ORDER BY at DESC LIMIT 50""", (rid,)))
        r = dict(row)
        for k in ("details", "auth_info", "usage_guide", "usage_changes", "trial_info", "eval_info"):
            r[k] = _meta(r.get(k))
        for k in ("usage_tools", "cap_tool_names"):
            r.pop(k, None)  # 크고 화면에 필요 없음
        return {"agent": r, "history": history}

    # ---------------- 알아보기·탐색 ----------------
    CARD_COLS = """r.id, r.kind, r.source, r.name, r.url, r.description, r.category, r.health_status, r.price_usdc,
                   r.payers_30d, r.calls_30d, r.eval_grade, r.eval_score, r.trial_ok, r.cap_tool_count, r.first_seen,
                   r.auth_method, r.auth_autonomy, COALESCE(r.auth_observed, r.auth_declared) AS auth_required"""
    LIVE = "r.active=1 AND r.health_status IN ('healthy','reachable') AND COALESCE(r.eval_security,'') != 'quarantine'"

    insights_cache: dict = {}

    def _diverse(rows: list[dict], limit: int, per_host: int = 2) -> list[dict]:
        """한 호스트의 비슷한 엔드포인트가 결과를 다 차지하지 않게 호스트당 per_host개까지만."""
        seen: collections.Counter = collections.Counter()
        out = []
        for r in rows:
            h = host_of(r["url"])
            if seen[h] < per_host:
                seen[h] += 1
                out.append(r)
                if len(out) >= limit:
                    break
        return out

    def _card(row: dict) -> dict:
        row = dict(row)
        row["description"] = (row.get("description") or "")[:400]
        return row

    @router.get("/admin/api/insights", dependencies=auth)
    def insights():
        """종류별로 '숫자로 보기'와 눈여겨볼 에이전트 (설명 화면용)."""
        now = time.time()
        featured_sql = {
            "x402": [
                ("most_paid", "최근 30일 결제자가 가장 많은 API", "r.payers_30d IS NOT NULL", "r.payers_30d DESC"),
                ("cheapest", "가장 싸게 쓸 수 있는 API", "r.price_usdc > 0 AND r.health_status='healthy'", "r.price_usdc ASC, COALESCE(r.payers_30d,0) DESC"),
                ("newest", "새로 발견된 API", "1=1", "r.first_seen DESC"),
            ],
            "mcp": [
                ("verified", "실제 호출까지 확인된 고품질 서버", "r.trial_ok=1 AND r.eval_score IS NOT NULL", "r.eval_score DESC"),
                ("open", "계정 없이 바로 쓰는 서버", "COALESCE(r.auth_observed, r.auth_declared, 1)=0 AND r.eval_grade='A'", "r.cap_tool_count DESC"),
                ("newest", "새로 등록된 서버", "1=1", "r.first_seen DESC"),
            ],
            "a2a": [
                ("verified", "실제로 대답한 에이전트", "r.trial_ok=1", "COALESCE(r.eval_score,0) DESC"),
                ("top", "품질 평가가 높은 에이전트", "r.eval_score IS NOT NULL", "r.eval_score DESC"),
                ("newest", "새로 발견된 에이전트", "1=1", "r.first_seen DESC"),
            ],
        }
        cached = insights_cache.get("value")
        if cached and now - insights_cache["at"] < INSIGHTS_TTL:
            return cached
        out: dict = {"now": now, "categories": {**{c.id: c.name for c in CATEGORIES.values()}, "other": "기타"}, "kinds": {}}
        with reader() as db:
            q = lambda sql, p=(): _rows(db.execute(sql, p))  # noqa: E731
            # 큰 표를 여러 번 훑지 않도록 종류별 집계는 한 번에
            base = "FROM resources r WHERE r.active=1 AND r.health_status != 'retired'"
            stats = {r["kind"]: r for r in q(f"""SELECT r.kind, COUNT(*) AS total,
                            SUM(r.health_status IN ('healthy','reachable')) AS live,
                            SUM(r.first_seen > ?) AS new_24h,
                            SUM(r.first_seen > ?) AS new_7d,
                            SUM(r.trial_ok = 1) AS verified,
                            SUM(COALESCE(r.auth_observed, r.auth_declared) = 0) AS no_auth,
                            SUM(r.auth_autonomy = 'agent_autonomous') AS agent_autonomous,
                            SUM(r.eval_grade = 'A') AS grade_a,
                            SUM(r.cap_tool_count) AS tools,
                            SUM(COALESCE(r.payers_30d, 0)) AS payers_30d,
                            SUM(COALESCE(r.calls_30d, 0)) AS calls_30d,
                            MIN(CASE WHEN r.price_usdc > 0 THEN r.price_usdc END) AS min_price,
                            SUM(r.price_usdc > 0 AND r.price_usdc <= 10000) AS under_1cent,
                            SUM(r.price_usdc > 0) AS priced
                          {base} GROUP BY r.kind""", (now - 86400, now - 7 * 86400))}
            prices: dict = {}
            for r in q(f"SELECT r.kind, r.price_usdc {base} AND r.price_usdc > 0 ORDER BY r.price_usdc"):
                prices.setdefault(r["kind"], []).append(r["price_usdc"])
            cats: dict = {}
            for r in q(f"SELECT r.kind, r.category, COUNT(*) AS n {base} GROUP BY r.kind, r.category ORDER BY n DESC"):
                cats.setdefault(r["kind"], []).append({"category": r["category"], "n": r["n"]})
            sources: dict = {}
            for r in q("SELECT kind, source, COUNT(*) AS n FROM resources WHERE active=1 GROUP BY kind, source ORDER BY n DESC"):
                sources.setdefault(r["kind"], []).append({"source": r["source"], "n": r["n"]})
            for kind in KINDS:
                s = stats.get(kind) or {"total": 0}
                kp = prices.get(kind, [])
                s["median_price"] = kp[len(kp) // 2] if kp else None
                featured = []
                for key, title, cond, order in featured_sql[kind]:
                    rows = q(f"SELECT {CARD_COLS} FROM resources r WHERE {LIVE} AND r.kind=? AND {cond} ORDER BY {order} LIMIT 30",
                             (kind,))
                    featured.append({"key": key, "title": title, "items": [_card(r) for r in _diverse(rows, 6)]})
                out["kinds"][kind] = {"stats": s, "top_categories": cats.get(kind, [])[:6], "sources": sources.get(kind, []),
                                      "featured": featured}
        insights_cache.update(value=out, at=now)
        return out

    @router.get("/admin/api/explore", dependencies=auth)
    def explore(q: str = "", kind: str | None = None, category: str | None = None, verified: bool = False,
                no_auth: bool = False, limit: int = Query(30, ge=1, le=100)):
        """에이전트 찾기: 검색어는 이름·설명 전문 검색(관련도순), 없으면 품질·인기순. 서비스 가능한 것만."""
        conds, params = [LIVE], []
        if kind:
            conds.append("r.kind=?"); params.append(kind)
        if category:
            conds.append("r.category=?"); params.append(category)
        if verified:
            conds.append("r.trial_ok=1")
        if no_auth:
            conds.append("(COALESCE(r.auth_observed, r.auth_declared, 0)=0 OR r.kind='x402')")
        where = " AND ".join(conds)
        terms = query_terms(q, limit=12)
        with reader() as db:
            if terms:
                match = " OR ".join('"' + t.replace('"', "") + '"' for t in terms)
                rows = _rows(db.execute(
                    f"""SELECT {CARD_COLS} FROM resources_fts f JOIN resources r ON r.id=f.rowid
                        WHERE resources_fts MATCH ? AND {where}
                        ORDER BY bm25(resources_fts) - COALESCE(r.eval_score, 50) / 100.0 - (r.trial_ok IS 1) * 0.5 LIMIT ?""",
                    (match, *params, limit * 5)))
            else:
                rows = _rows(db.execute(
                    f"""SELECT {CARD_COLS} FROM resources r WHERE {where}
                        ORDER BY (r.trial_ok IS 1) DESC, COALESCE(r.eval_score, 0) DESC, COALESCE(r.payers_30d, 0) DESC LIMIT ?""",
                    (*params, limit * 5)))
        return {"query": q, "terms": terms, "items": [_card(r) for r in _diverse(rows, limit)]}

    # ---------------- SNS (의견·평가 피드) ----------------
    def _sns(fn):
        try:
            return fn()
        except sns.SnsError as exc:
            raise HTTPException(400, str(exc))

    @router.get("/admin/api/sns/feed", dependencies=auth)
    def sns_feed(tab: str = Query("for_you", pattern="^(for_you|latest|popular)$"), protocol: str | None = None,
                 role: str | None = Query(None, pattern="^(agent|community|user|developer)$"), q: str | None = None,
                 offset: int = Query(0, ge=0, le=1000), limit: int = Query(20, ge=1, le=50), client: str | None = None):
        with reader() as db:
            return _sns(lambda: sns.feed(db, tab, protocol or None, role, q, offset, limit, client))

    @router.get("/admin/api/sns/thread", dependencies=auth)
    def sns_thread(key: str, client: str | None = None):
        with reader() as db:
            return _sns(lambda: sns.thread(db, key, client))

    @router.get("/admin/api/sns/sidebar", dependencies=auth)
    def sns_sidebar():
        with reader() as db:
            return sns.sidebar(db)

    @router.post("/admin/api/sns/posts", dependencies=auth)
    async def sns_post(request: Request):
        data = await request.json()
        if not isinstance(data, dict):
            raise HTTPException(400, "JSON 객체가 필요합니다.")
        role = data.get("role", "user")
        if role not in sns.WRITER_ROLES:  # 에이전트 글은 지갑 서명이 있는 POST /sns/posts로만
            raise HTTPException(400, "role은 user 또는 developer입니다.")
        return _sns(lambda: sns.create_post(store, data.get("body"), data.get("author"), role, data.get("client"),
                                            data.get("protocol") or None, data.get("rating"), data.get("parent_key"),
                                            data.get("resource_id")))

    @router.post("/admin/api/sns/like", dependencies=auth)
    async def sns_like(request: Request):
        data = await request.json()
        return _sns(lambda: sns.toggle_like(store, str(data.get("key", "")), str(data.get("client", ""))))

    @router.post("/admin/api/sns/delete", dependencies=auth)
    async def sns_delete(request: Request):
        data = await request.json()
        _sns(lambda: sns.delete_post(store, str(data.get("key", "")), str(data.get("client", ""))))
        return {"ok": True}

    # ---------------- 방문 에이전트 (에이전트 전용 프론트, AGENT_FRONT.md) ----------------
    @router.get("/admin/api/visitors", dependencies=auth)
    def visitors(q: str | None = None, tier: str | None = Query(None, pattern="^(new|returning|regular)$"),
                 limit: int = Query(100, ge=1, le=500)):
        now = time.time()
        conds, params = [], []
        if tier:
            conds.append("v.tier=?"); params.append(tier)
        if q:
            conds.append("(v.name LIKE ? OR v.id LIKE ? OR v.user_agent LIKE ?)"); params += [f"%{q}%"] * 3
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        with reader() as db:
            rows = _rows(db.execute(f"""SELECT v.id, v.name, v.channel, v.user_agent, v.lang, v.first_seen, v.last_seen, v.visits,
                       v.visit_days, v.messages, v.tier, v.notify, v.last_notified,
                       (SELECT COUNT(*) FROM agent_interests i WHERE i.visitor_id=v.id AND i.active=1) AS interests,
                       (SELECT task FROM agent_interests i WHERE i.visitor_id=v.id ORDER BY updated DESC LIMIT 1) AS last_task,
                       (SELECT status FROM agent_contacts c WHERE c.visitor_id=v.id ORDER BY id DESC LIMIT 1) AS contact_status,
                       (SELECT COUNT(*) FROM agent_notifications n WHERE n.visitor_id=v.id AND n.kind='digest' AND n.status='sent') AS digests
                       FROM agent_visitors v {where} ORDER BY v.last_seen DESC LIMIT ?""", (*params, limit)))
            stats = db.execute("""SELECT COUNT(*) AS total, SUM(tier='new') AS new, SUM(tier='returning') AS "returning",
                       SUM(tier='regular') AS regular, SUM(visits >= 2) AS came_back, SUM(last_seen > ?) AS active_24h,
                       SUM(first_seen > ?) AS new_24h FROM agent_visitors""", (now - 86400, now - 86400)).fetchone()
            extra = db.execute("""SELECT
                       (SELECT COUNT(*) FROM agent_messages WHERE role='agent' AND at > ?) AS messages_24h,
                       (SELECT COUNT(DISTINCT visitor_id) FROM agent_contacts WHERE status='verified') AS verified_contacts,
                       (SELECT COUNT(*) FROM agent_notifications WHERE kind='digest' AND status='sent' AND at > ?) AS digests_7d,
                       (SELECT COUNT(*) FROM agent_hits) AS anonymous_readers,
                       (SELECT COALESCE(SUM(hits), 0) FROM agent_hits) AS anonymous_reads""", (now - 86400, now - 7 * 86400)).fetchone()
            channels = {r["channel"]: r["n"] for r in db.execute("SELECT channel, COUNT(*) AS n FROM agent_visitors GROUP BY channel")}
        return {"stats": {**dict(stats), **dict(extra), "channels": channels}, "items": rows}

    @router.get("/admin/api/visitors/{vid}", dependencies=auth)
    def visitor(vid: str):
        with reader() as db:
            row = db.execute("SELECT * FROM agent_visitors WHERE id=?", (vid,)).fetchone()
            if row is None:
                raise HTTPException(404, "없는 방문자")
            v = dict(row)
            v.pop("token_hash", None)
            v.pop("last_results", None)
            interests = _rows(db.execute("SELECT id, task, category, kind, auth_pref, created, updated, best_score, active, recommended "
                                         "FROM agent_interests WHERE visitor_id=? ORDER BY updated DESC", (vid,)))
            for i in interests:
                i["recommended"] = _meta(i["recommended"]) or []
            contacts = _rows(db.execute("SELECT id, type, url, status, created, verified_at, failures, last_error FROM agent_contacts "
                                        "WHERE visitor_id=? ORDER BY id DESC", (vid,)))
            messages = _rows(db.execute("SELECT at, role, channel, text FROM agent_messages WHERE visitor_id=? ORDER BY id DESC LIMIT 100",
                                        (vid,)))
            notes = _rows(db.execute("SELECT at, kind, status, detail FROM agent_notifications WHERE visitor_id=? ORDER BY at DESC LIMIT 30",
                                     (vid,)))
            outcomes = _rows(db.execute("""SELECT o.resource_id, o.success, o.at, r.name FROM agent_outcomes o
                                           LEFT JOIN resources r ON r.id=o.resource_id WHERE o.visitor_id=? ORDER BY o.at DESC""", (vid,)))
        return {"visitor": v, "interests": interests, "contacts": contacts, "messages": list(reversed(messages)),
                "notifications": notes, "outcomes": outcomes}

    @router.post("/admin/api/visitors/{vid}/digest", dependencies=auth)
    def visitor_digest(vid: str):
        if front is None:
            raise HTTPException(503, "에이전트 프론트가 없습니다.")
        return front.digest.run_due(force_visitor=vid)

    @router.post("/admin/api/visitors/{vid}/notify", dependencies=auth)
    async def visitor_notify(vid: str, request: Request):
        data = await request.json()
        with store.tx() as db:
            if not db.execute("UPDATE agent_visitors SET notify=? WHERE id=?", (int(bool(data.get("enabled"))), vid)).rowcount:
                raise HTTPException(404, "없는 방문자")
        return {"notify": bool(data.get("enabled"))}

    # ---------------- 고객 요청 ----------------
    @router.get("/admin/api/needs", dependencies=auth)
    def needs(limit: int = Query(50, ge=1, le=200)):
        with reader() as db:
            rows = _rows(db.execute(
                """SELECT n.need_id, n.client, n.task, n.category, n.status, n.created, n.updated, n.rescanned_at,
                          n.current_score, r.name AS current_name, r.url AS current_url,
                          (SELECT COUNT(*) FROM offers o WHERE o.need_id=n.need_id) AS offers
                   FROM needs n LEFT JOIN resources r ON r.id=n.current_resource ORDER BY n.created DESC LIMIT ?""", (limit,)))
        return {"items": rows}

    # ---------------- 관리 작업 ----------------
    def run_background(name: str, fn) -> dict:
        state = actions.get(name)
        if state and state.get("running"):
            return {"started": False, "reason": "이미 실행 중입니다.", **state}

        def work():
            actions[name] = {"running": True, "started_at": time.time()}
            try:
                result = fn()
                actions[name] = {"running": False, "started_at": actions[name]["started_at"], "finished_at": time.time(),
                                 "result": result}
            except Exception as exc:
                log.exception("dashboard action %s failed", name)
                actions[name] = {"running": False, "finished_at": time.time(), "error": f"{type(exc).__name__}: {exc}"[:300]}

        threading.Thread(target=work, name=f"dashboard-{name}", daemon=True).start()
        return {"started": True}

    @router.post("/admin/api/actions/crawl", dependencies=auth)
    def crawl_now():
        if crawler is None:
            raise HTTPException(503, "수집기가 없습니다.")
        return run_background("crawl", crawler.crawl_all)

    @router.post("/admin/api/actions/rescan", dependencies=auth)
    def rescan_now():
        if service is None:
            raise HTTPException(503, "게이트웨이 서비스가 없습니다.")
        return run_background("rescan", service.rescan)

    @router.post("/admin/api/actions/pause", dependencies=auth)
    def pause():
        if collector is None:
            raise HTTPException(503, "수집기가 없습니다.")
        collector.pause()
        return {"paused": True}

    @router.post("/admin/api/actions/resume", dependencies=auth)
    def resume():
        if collector is None:
            raise HTTPException(503, "수집기가 없습니다.")
        collector.resume()
        return {"paused": False}

    @router.post("/admin/api/actions/erc8004-retry", dependencies=auth)
    def erc8004_retry():
        """받기에 실패한 등록 파일을 지금 다시 받도록 대기열에 돌려놓는다."""
        with store.tx() as db:
            n = db.execute("""UPDATE erc8004_tokens SET status='pending', next_at=NULL, error=NULL
                              WHERE status='error' AND uri IS NOT NULL""").rowcount
        log.info("dashboard: %d erc8004 registrations requeued", n)
        return {"requeued": n}

    @router.post("/admin/api/agents/{rid}/check", dependencies=auth)
    def check(rid: int):
        if collector is None:
            raise HTTPException(503, "수집기가 없습니다.")
        r = store.resource(rid)
        if r is None:
            raise HTTPException(404, "없는 에이전트")
        return collector.checker.check_and_record(r)

    @router.post("/admin/api/agents/{rid}/deactivate", dependencies=auth)
    def deactivate(rid: int):
        with store.tx() as db:
            if not db.execute("UPDATE resources SET active=0 WHERE id=?", (rid,)).rowcount:
                raise HTTPException(404, "없는 에이전트")
        log.info("dashboard: agent %d deactivated", rid)
        return {"active": False}

    @router.post("/admin/api/agents/{rid}/activate", dependencies=auth)
    def activate(rid: int):
        """다시 활성화하고 점검 상태를 초기화해 바로 다시 점검하게 한다 (retired 복구에도 씀)."""
        with store.tx() as db:
            if not db.execute("""UPDATE resources SET active=1, health_status='unknown', consecutive_failures=0,
                                 failing_since=NULL, next_check_at=NULL WHERE id=?""", (rid,)).rowcount:
                raise HTTPException(404, "없는 에이전트")
        log.info("dashboard: agent %d activated", rid)
        return {"active": True}

    @router.post("/admin/api/logs/clear", dependencies=auth)
    def clear_logs():
        logs.records.clear()
        logs.counts.clear()
        return {"ok": True}

    return router
