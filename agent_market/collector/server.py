"""수집 에이전트 단독 실행 + 조회 API.

    COLLECTOR_DB=gateway-data/gateway.sqlite3 python -m agent_market.collector.server   # :8300

게이트웨이와 같은 DB를 쓰면 게이트웨이가 최신 수집·헬스 정보를 바로 활용한다
(게이트웨이를 실행하면 기본으로 이 수집 에이전트가 내장되어 함께 돈다).

API
  GET  /health                         수집 에이전트 자체 상태
  GET  /agents?q=&category=&kind=&status=&language=&region=&auth=none&limit=
                                       에이전트 검색 (헬스 상태·제약 정보 포함, retired는 status=retired로만)
  GET  /agents/{id}                    상세 + 최근 점검 기록
  GET  /stats                          헬스 상태별 개수, 최근 1시간 점검 수, 최근 수집 기록
  POST /admin/crawl, /admin/check/{id} 즉시 수집 / 즉시 점검 (ADMIN_TOKEN)
"""

import hmac
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query

from ..gateway import constraints as cons
from ..gateway.classify import query_terms
from ..gateway.ranking import agent_languages, agent_regions, auth_required
from ..gateway.crawler import Crawler
from ..gateway.store import Store
from .agent import CollectorAgent
from .capabilities import CapabilityProber
from .health import HealthChecker, Schedule

log = logging.getLogger("agent_market.collector.server")

PUBLIC_FIELDS = [
    "id", "kind", "source", "name", "url", "description", "category", "price_usdc", "pay_to", "method",
    "calls_30d", "payers_30d", "first_seen", "last_seen", "health_status", "consecutive_failures", "failing_since",
    "last_check_at", "last_ok_at", "last_status_code", "probe_latency_ms", "health_ok_24h", "health_n_24h",
]


def public(r: dict) -> dict:
    out = {k: r.get(k) for k in PUBLIC_FIELDS}
    out["networks"] = [n for n in (r.get("networks") or "").strip(",").split(",") if n]
    out["uptime_24h"] = round(r["health_ok_24h"] / r["health_n_24h"], 3) if r.get("health_n_24h") else None
    out["constraints"] = {
        "auth_required": auth_required(r), "languages": agent_languages(r), "regions": agent_regions(r),
        "currencies": cons.unpack(r.get("cap_currencies")), "tool_count": r.get("cap_tool_count"),
        "capabilities_checked_at": r.get("cap_checked_at"),
    }
    return out


def create_app(store: Store, agent: CollectorAgent | None, admin_token: str | None, run_background: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if agent and run_background:
            agent.start()
        yield
        if agent:
            agent.stop()

    app = FastAPI(title="Agent Info Collector", lifespan=lifespan)

    def require_admin(authorization: str | None):
        expected = f"Bearer {admin_token}" if admin_token else None
        if expected is None or authorization is None or not hmac.compare_digest(authorization, expected):
            raise HTTPException(401, "ADMIN_TOKEN 필요")

    @app.get("/health")
    def health():
        crawl = store.get_meta("last_crawl") or {}
        progress = {n: store.get_meta(f"crawl_pass:{n}") for n in ("x402-bazaar", "mcp-registry")}
        return {"ok": True, "last_crawl_at": crawl.get("at"), "crawl_in_progress": {k: v for k, v in progress.items() if v},
                "last_health_batch": store.get_meta("last_health_batch"), "now": time.time()}

    @app.get("/agents")
    def agents(q: str | None = None, category: str | None = None, kind: str | None = None,
               status: str | None = None, language: str | None = None, region: str | None = None,
               auth: str | None = None, limit: int = Query(20, ge=1, le=100)):
        conds, params = ["r.active=1"], []
        if language:
            lang = cons.normalize_language(language)
            if lang is None:
                raise HTTPException(400, "알 수 없는 language")
            conds.append("(r.cap_languages LIKE ? OR r.desc_lang = ?)"); params += [f"%,{lang},%", lang]
        if region:
            reg = cons.normalize_region(region)
            if reg is None:
                raise HTTPException(400, "알 수 없는 region")
            conds.append("(r.regions LIKE ? OR r.cap_regions LIKE ?)"); params += [f"%,{reg},%"] * 2
        if auth == "none":
            conds.append("COALESCE(r.auth_observed, r.auth_declared, 0) = 0")
        if category:
            conds.append("r.category=?"); params.append(category)
        if kind:
            conds.append("r.kind=?"); params.append(kind)
        if status:
            conds.append("r.health_status=?"); params.append(status)
        else:
            conds.append("r.health_status != 'retired'")  # 7일 넘게 다운된 에이전트는 기본 목록에서 제외
        where = " AND ".join(conds)
        terms = query_terms(q or "", limit=16)
        if terms:
            match = " OR ".join('"' + t.replace('"', "") + '"' for t in terms)
            rows = store.query(
                f"""SELECT r.* FROM resources_fts f JOIN resources r ON r.id=f.rowid
                    WHERE resources_fts MATCH ? AND {where} ORDER BY bm25(resources_fts) LIMIT ?""",
                (match, *params, limit))
        else:
            rows = store.query(f"SELECT r.* FROM resources r WHERE {where} ORDER BY COALESCE(r.payers_30d,0) DESC LIMIT ?",
                               (*params, limit))
        return [public(dict(r)) for r in rows]

    @app.get("/agents/{rid}")
    def agent_detail(rid: int):
        r = store.resource(rid)
        if r is None:
            raise HTTPException(404, "없는 에이전트")
        return {**public(r), "active": bool(r["active"]), "details": json.loads(r["details"]),
                "last_error": r.get("last_error"), "history": store.health_history(rid)}

    @app.get("/stats")
    def stats():
        return store.collector_stats()

    @app.post("/admin/crawl")
    def crawl_now(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        if agent is None:
            raise HTTPException(503, "수집기가 없습니다.")
        return agent.crawler.crawl_all()  # 이미 수집 중이면 {"busy": true}

    @app.post("/admin/check/{rid}")
    def check_now(rid: int, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        r = store.resource(rid)
        if r is None or agent is None:
            raise HTTPException(404, "없는 에이전트")
        return agent.checker.check_and_record(r)

    return app


def build_agent(store: Store, health_interval: float, allow_private: bool = False, workers: int = 32,
                min_gap: float = 60, page_delay: float = 1.0, full_interval: float = 86400,
                capability_max_age: float = 86400, capability_workers: int = 8) -> CollectorAgent:
    checker = HealthChecker(store, allow_private=allow_private, workers=workers,
                            schedule=Schedule(interval=health_interval))
    crawler = Crawler(store, page_delay=page_delay, full_interval=full_interval)
    caps = CapabilityProber(store, allow_private=allow_private, max_age=capability_max_age, workers=capability_workers)
    return CollectorAgent(store, crawler, checker, min_gap=min_gap, capabilities=caps)


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db = os.environ.get("COLLECTOR_DB", "gateway-data/gateway.sqlite3")
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    store = Store(db)
    agent = build_agent(
        store,
        min_gap=float(os.environ.get("CRAWL_MIN_GAP_SECONDS", "60")),
        page_delay=float(os.environ.get("CRAWL_PAGE_DELAY", "1.0")),
        full_interval=float(os.environ.get("CRAWL_FULL_INTERVAL_HOURS", "24")) * 3600,
        health_interval=float(os.environ.get("HEALTH_INTERVAL_MINUTES", "60")) * 60,
        allow_private=os.environ.get("ALLOW_PRIVATE_AGENT_URLS") == "1",
        workers=int(os.environ.get("HEALTH_WORKERS", "32")),
        capability_max_age=float(os.environ.get("CAPABILITY_MAX_AGE_HOURS", "24")) * 3600,
        capability_workers=int(os.environ.get("CAPABILITY_WORKERS", "8")),
    )
    uvicorn.run(create_app(store, agent, os.environ.get("ADMIN_TOKEN")),
                host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8300")))


if __name__ == "__main__":
    main()
