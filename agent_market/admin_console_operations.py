"""Bounded, individual-staff read models for the task-oriented console.

These endpoints never enqueue work, modify configuration or read customer bodies.
"""

import json
import os
from pathlib import Path
import urllib.request
import time
from fastapi import HTTPException, Request, Query
from .workspace_admin_events import register, rows
from .workflow_publication_service import no_store, same_origin
from fastapi.responses import JSONResponse

register(
    {
        "console_collection_meta": "SELECT key,value FROM meta WHERE key='last_crawl' OR key LIKE 'crawl_pass:%' OR key LIKE 'crawl_last_full:%' OR key LIKE 'crawl_last_start:%' ORDER BY key LIMIT 100",
        "console_collection_runs": "SELECT at,source,ok,seen,new,seconds,error,mode,changed,unchanged,pages FROM crawl_runs ORDER BY at DESC LIMIT 30",
        "console_health_totals": "SELECT kind,health_status AS status,COUNT(*) AS n FROM resources WHERE active=1 GROUP BY kind,health_status",
        "console_health_queue": "SELECT id,name,kind,health_status,last_check_at,next_check_at FROM resources WHERE active=1 AND health_status!='retired' ORDER BY CASE WHEN next_check_at IS NULL THEN 0 ELSE 1 END,next_check_at,id LIMIT 50",
        "console_evaluations": "SELECT id,name,kind,eval_grade,eval_score,eval_at,health_status FROM resources WHERE active=1 ORDER BY CASE WHEN eval_at IS NULL THEN 1 ELSE 0 END,eval_at DESC,id DESC LIMIT 50",
        "console_eval_totals": "SELECT kind,COALESCE(eval_grade,'unrated') AS grade,COUNT(*) AS n FROM resources WHERE active=1 GROUP BY kind,eval_grade",
        "console_operation": "SELECT id,source,protocol,status,error_code,created,finished FROM platform_operations WHERE id=?",
        "console_operation_attempts": "SELECT id,resource_id,protocol,status,error_code,created,finished,elapsed_ms FROM platform_attempts WHERE operation_id=? ORDER BY created,id LIMIT 50",
        "console_workflow_candidates": """SELECT DISTINCT r.id,r.name,r.kind,r.health_status,r.eval_grade,a.contract_id FROM resources r JOIN connection_versions v ON v.resource_id=r.id JOIN capability_approvals a ON a.version_id=v.id WHERE r.active=1 AND v.schema_complete=1 ORDER BY r.id,a.contract_id LIMIT 100""",
        "console_operations": "SELECT id,source,protocol,status,error_code,created,finished FROM platform_operations ORDER BY created DESC,id DESC LIMIT 50",
        "console_recent_workflows": "SELECT d.id,d.workspace_id,d.name,d.revision FROM workspace_drafts d JOIN workspace_memberships m ON m.workspace_id=d.workspace_id WHERE m.user_id=? AND m.active=1 AND d.active=1 ORDER BY d.updated DESC,d.id DESC LIMIT 21",
    }
)


def install(
    router,
    *,
    store,
    authorize,
    reader,
    collector=None,
    crawler=None,
    vector_stats=None,
    actions=None,
    public_origin=None,
    engine=None,
    service=None,
    logs=None,
):
    def staff(request, roles=("superadmin", "admin")):
        if not same_origin(request):
            raise HTTPException(403, "동일 출처에서 요청하세요.")
        user = authorize(
            request,
            request.headers.get("authorization"),
            request.headers.get("x-dashboard"),
        )
        if not user.get("is_authenticated_session") or user.get("role") not in roles:
            raise HTTPException(403, "현재 업무에 필요한 개인 관리자 권한이 없습니다.")
        return user

    def read(name, params=()):
        with reader() as db:
            return rows(db, name, params)

    def reply(value):
        return JSONResponse({**value, "captured_at": time.time()}, headers=no_store())

    def worker():
        control = getattr(store, "_service_control", None)
        if control is not None:
            return control.status("jobs")
        return (
            None
            if collector is None
            else {
                "available": True,
                "paused": collector.paused.is_set(),
                "started_at": collector.started_at,
                "threads": collector.thread_status(),
                "vector_index": getattr(collector, "rag_status", None),
            }
        )

    @router.get("/admin/api/v2/console/collection")
    def collection(request: Request):
        staff(request)
        meta = {}
        for row in read("console_collection_meta"):
            try:
                meta[row["key"]] = json.loads(row["value"])
            except (ValueError, TypeError):
                meta[row["key"]] = None
        state = worker()
        control = getattr(store, "_service_control", None)
        pending = control.actions() if control else dict(actions or {})
        active = {
            k.split(":", 1)[1]: v
            for k, v in meta.items()
            if k.startswith("crawl_pass:") and isinstance(v, dict)
        }
        settings = {}
        for name in (
            "interval",
            "full_interval",
            "max_pages",
            "incremental_mcp_max_pages",
            "incremental_x402_max_pages",
        ):
            value = getattr(crawler, name, None)
            if isinstance(value, (int, float)):
                settings[name] = value
        return reply(
            {
                "worker": state,
                "progress": active,
                "runs": read("console_collection_runs"),
                "actions": {
                    k: v
                    for k, v in pending.items()
                    if k in ("crawl", "rescan", "pause", "resume")
                },
                "last_completed": meta.get("last_crawl"),
                "schedule": settings,
                "crawl_available": bool(
                    crawler is not None
                    and (control is None or state and state.get("available"))
                ),
                "rescan_available": bool(
                    service is not None
                    and (control is None or state and state.get("available"))
                ),
            }
        )

    @router.get("/admin/api/v2/console/health")
    def health(request: Request):
        staff(request, ("superadmin", "admin", "operator"))
        from .config import health_interval_seconds

        return reply(
            {
                "worker": worker(),
                "interval_seconds": health_interval_seconds(),
                "totals": read("console_health_totals"),
                "items": read("console_health_queue"),
                "limit": 50,
                "scope": "다음 점검 대상 중 최대 50개",
            }
        )

    @router.get("/admin/api/v2/console/evaluations")
    def evaluations(request: Request):
        staff(request)
        return reply(
            {
                "items": read("console_evaluations"),
                "totals": read("console_eval_totals"),
                "limit": 50,
                "worker": worker(),
            }
        )

    @router.get("/admin/api/v2/console/search-index")
    def search_index(request: Request):
        staff(request)
        data = vector_stats() if vector_stats else {"available": False}
        return reply({"index": data, "worker": worker()})

    @router.get("/admin/api/v2/console/workflows/recent")
    def recent_workflows(request: Request):
        user = staff(request)
        found = read("console_recent_workflows", (user["user_id"],))
        return reply(
            {
                "items": found[:20],
                "truncated": len(found) > 20,
                "scope": "현재 직원 멤버십으로 접근 가능한 최근 초안",
            }
        )

    @router.get("/admin/api/v2/console/services")
    def services(request: Request):
        staff(request, ("superadmin", "admin", "operator", "viewer"))
        items = []
        control = getattr(store, "_service_control", None)
        for role, label in (
            ("jobs", "수집·평가 작업자"),
            ("execution", "워크플로 실행 작업자"),
        ):
            status = (
                control.status(role)
                if control
                else (worker() if role == "jobs" else None)
            )
            items.append(
                {
                    "service": role,
                    "name": label,
                    "available": status.get("available") if status else None,
                    "updated": status.get("updated") if status else None,
                    "paused": status.get("paused") if status else None,
                }
            )
        # Fixed local readiness targets; no user URL, redirect or probe secret reaches the browser.
        project = os.environ.get("AGENTCON_PROJECT_ROOT")
        state = {}
        if project:
            try:
                path = Path(project) / "gateway-data/services/state.json"
                if path.stat().st_size < 65536:
                    loaded = json.loads(path.read_text())
                    if isinstance(loaded, dict) and isinstance(
                        loaded.get("services"), dict
                    ):
                        state = loaded["services"]
            except (OSError, ValueError, TypeError):
                state = {}
        for role, label, ports in (
            ("frontend", "프론트엔드", {"a": 8401, "b": 8402}),
            ("admin", "어드민", {"a": 8201, "b": 8202}),
        ):
            status = {
                "service": role,
                "name": label,
                "available": None,
                "updated": None,
            }
            entry = state.get(role, {})
            if not isinstance(entry, dict):
                entry = {}
            slot = entry.get("active")
            if slot in ports:
                try:
                    from .application_runtime import _private_bytes
                    from .service_host import probe_token

                    key = _private_bytes(
                        os.environ.get("APPLICATION_WORKFLOW_KEY_FILE"), 32
                    )

                    class NoRedirect(urllib.request.HTTPRedirectHandler):
                        def redirect_request(self, req, fp, code, msg, headers, newurl):
                            return None

                    req = urllib.request.Request(
                        "http://127.0.0.1:%d/internal/service/ready" % ports[slot],
                        headers={"X-Service-Probe": probe_token(key)},
                    )
                    with urllib.request.build_opener(
                        urllib.request.ProxyHandler({}), NoRedirect()
                    ).open(req, timeout=1) as response:
                        found = json.loads(response.read(4096))
                    status.update(
                        available=found.get("ready") is True
                        and found.get("role") == role,
                        updated=time.time(),
                    )
                except (OSError, ValueError, TypeError):
                    status.update(available=False, updated=time.time())
            items.insert(0, status)
        return reply(
            {
                "items": items,
                "database": getattr(store, "backend", "sqlite"),
                "admin_request": "responding",
                "public_origin": public_origin,
                "scope": "작업자 상태는 최근 응답 기준입니다. 웹 서비스의 외부 접속은 별도로 확인하세요.",
            }
        )

    @router.get("/admin/api/v2/console/settings")
    def settings(request: Request):
        staff(request, ("superadmin",))
        from .config import health_interval_seconds
        from .customer_credits import WELCOME_CREDITS

        return reply(
            {
                "items": [
                    {
                        "name": "기본 상태 확인 주기",
                        "value": str(health_interval_seconds() / 3600) + "시간",
                        "scope": "에이전트 상태 점검",
                        "change": "독립 작업자 운영 설정",
                    },
                    {
                        "name": "생성 모델",
                        "value": getattr(engine, "generation_model", None),
                        "scope": "AI 제안",
                        "change": "서비스 운영 설정",
                    },
                    {
                        "name": "검색 모델",
                        "value": getattr(engine, "embed_model", None),
                        "scope": "검색 반영",
                        "change": "검색 버전 검증 후 운영 전환",
                    },
                    {
                        "name": "데이터베이스",
                        "value": getattr(store, "backend", "sqlite"),
                        "scope": "서비스 데이터",
                        "change": "검증된 별도 전환",
                    },
                    {
                        "name": "신규 무료 플랜 지급",
                        "value": WELCOME_CREDITS,
                        "scope": "계정당 최초 가입 1회",
                        "change": "기존 잔액 유지",
                    },
                ]
            }
        )

    @router.get("/admin/api/v2/console/executions")
    def executions(request: Request):
        staff(request, ("superadmin", "admin", "operator"))
        return reply(
            {
                "items": read("console_operations"),
                "limit": 50,
                "scope": "최근 실행 상태만 표시합니다. 입력·출력 원문은 포함하지 않습니다.",
            }
        )

    @router.get("/admin/api/v2/console/executions/{operation_id}")
    def execution(request: Request, operation_id: str):
        staff(request, ("superadmin", "admin", "operator"))
        if not 1 <= len(operation_id) <= 120:
            raise HTTPException(400, "실행 참조를 확인하세요.")
        found = read("console_operation", (operation_id,))
        if not found:
            raise HTTPException(404, "이 실행 기록을 찾을 수 없습니다.")
        return reply(
            {
                "operation": found[0],
                "attempts": read("console_operation_attempts", (operation_id,)),
            }
        )

    @router.get("/admin/api/v2/console/logs")
    def recent_logs(
        request: Request,
        limit: int = Query(50, ge=1, le=100),
        level: str = Query("WARNING", pattern="^(WARNING|ERROR|CRITICAL|ALL)$"),
    ):
        staff(request, ("superadmin",))
        from .logger import redact_log_message

        records = list(logs.records) if logs else []
        items = [
            r for r in reversed(records) if level == "ALL" or r.get("level") == level
        ][:limit]
        return reply(
            {
                "items": [
                    {
                        "at": r.get("at"),
                        "level": r.get("level"),
                        "logger": r.get("logger"),
                        "message": redact_log_message(str(r.get("message", "")))[:2000],
                    }
                    for r in items
                ],
                "scope": "현재 어드민 프로세스의 메모리 로그. 다른 작업자의 파일 로그는 포함하지 않습니다.",
            }
        )

    @router.get("/admin/api/v2/console/workflow-candidates")
    def workflow_candidates(request: Request):
        staff(request)
        from .capability_contracts import CONTRACTS
        from .workspace_typed_flows import ALLOWED

        return reply(
            {
                "items": [
                    r
                    for r in read("console_workflow_candidates")
                    if r["contract_id"] in ALLOWED
                ],
                "contracts": {key: CONTRACTS[key] for key in ALLOWED},
                "scope": "저장된 계약 승인 후보입니다. 저장·실행 전에 현재 연결과 유효한 근거를 다시 검증합니다.",
            }
        )
