"""관리 대시보드: 수집 상태·진행 상황·전체 통계·에러를 웹 화면으로 보고, 수집을 관리한다.

    브라우저에서 http://127.0.0.1:8200/admin/ui

모든 경로가 /admin 아래라 배포 환경에서는 Caddy가 외부 접근을 막는다(deploy/Caddyfile).
접근 권한
- ADMIN_TOKEN이 있으면 Authorization: Bearer <token> (화면에서 한 번 입력하면 브라우저 탭에 보관)
- ADMIN_TOKEN이 없으면 같은 PC(loopback)에서 localhost 주소로 접속할 때만 허용
- 모든 API 요청에 X-Dashboard 헤더가 필요하다. 다른 사이트가 브라우저를 통해 몰래 보내는 요청(CSRF)은
  이 헤더를 붙일 수 없고(CORS 사전 요청이 거부됨), Host 검사로 DNS rebinding도 막는다.

조회는 현재 저장소의 별도 읽기 전용 세션을 사용한다. PostgreSQL은 전용 세션 풀을 사용한다.
"""

import asyncio
import collections
import datetime
import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from urllib.parse import urlparse

from ..broker.categories import CATEGORIES
from ..broker.discovery import DiscoveryError
from ..concierge.http_security import (validate_public_url as check_public_url, bounded_client as public_client,
                                       public_async_client, bounded_request)
from .admin_security import AdminRoute, integer, text, validate_graph
from ..broker.server import RateLimiter
from ..collector import a2a, usage
from ..collector.capabilities import parse_jsonrpc
from ..collector.agent import CollectorAgent
from ..collector.health import HealthChecker
from ..concierge.security import SecurityManager
from .sanitizer import sanitize_text
from .visitor_desk import VisitorDesk
from . import admin_auth, sns
from .classify import classify, query_terms
from .rag import RagEngine, RagPipeline, ensure_vec_table, load_sqlite_vec
from .ssl_manager import SSLManager, get_ssl_manager
from .store import Store, host_of

log = logging.getLogger("agent_market.gateway.dashboard")

PAGE = Path(__file__).with_name("dashboard.html")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}
META_KEYS = ["last_health_batch", "last_health_batch_a2a", "last_health_batch_mcp", "last_health_batch_x402",
             "last_capabilities_batch", "last_auth_batch", "last_agents_batch",
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
            elif record.exc_text:
                text += "\n" + record.exc_text
            from ..logger import redact_log_message
            text = redact_log_message(text)
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
                     service=None, crawler=None, front=None, front_url: str | None = None,
                     rag_engine: RagEngine | None = None, ssl_manager: SSLManager | None = None) -> APIRouter:
    from ..workflow_product_semantics_service import ProductV2AdminRoute,ProductSemanticsService,read_request as product_v2_request
    router = APIRouter(route_class=ProductV2AdminRoute)
    from ..workflows import runtime_for, graph as workflow_graph, public_template, sensitive as workflow_sensitive, WorkflowError
    from ..concierge.proxy import McpProxy
    from ..concierge.notify import Courier
    workflows_runtime = runtime_for(store, getattr(front, 'proxy', None) or McpProxy(store),
                                    getattr(front, 'courier', None) or Courier())
    from ..workflow_composer import Composer, PUBLISH as COMPOSER_PUBLISH
    composer = Composer(workflows_runtime, rag_engine)
    if front is not None:
        front._workspace_support_engine = rag_engine
    from ..workflow_comparison import Comparison, ComparisonError
    workflow_comparison = Comparison(workflows_runtime)
    from ..workflow_resolved_evidence import ResolvedEvidence
    workflow_resolved_evidence = ResolvedEvidence(workflows_runtime)
    from ..workflow_review_packets import ReviewPackets, PROFILE as REVIEW_PREPARATION_PROFILE
    workflow_review_packets = ReviewPackets(workflows_runtime)
    from ..workflow_controlled_pairs import ControlledPairs, PROFILE as CONTROLLED_PAIR_PROFILE
    workflow_controlled_pairs = ControlledPairs(workflows_runtime)
    from ..workflow_apps import service_for as workflow_apps_for
    workflow_apps = workflow_apps_for(store, workflows_runtime)
    from ..workflow_apps_v12 import WorkflowAppsV12, PROFILE as SDK_V12_PROFILE
    workflow_apps_v12 = WorkflowAppsV12(workflows_runtime)
    from ..workflow_publication_service import PublicationService,read_object as publication_body,same_origin as publication_same_origin
    from ..workflow_publication import PROFILE as PUBLICATION_PROFILE
    workflow_publication=PublicationService(workflows_runtime)
    from ..workflow_connection_deployment_service import ConnectionDeploymentService,read_request as connected_app_request
    from ..workflow_connection_deployment import PROFILE as CONNECTED_SDK_PROFILE
    connected_apps=ConnectionDeploymentService(workflows_runtime)
    from ..workflow_connection_automation import PROFILE as CONNECTED_AUTOMATION_PROFILE
    from ..workflow_product_semantics import PROFILE as PRODUCT_SEMANTICS_PROFILE
    product_semantics=ProductSemanticsService(store)

    def validate_workflow_definition(body, existing=None):
        candidate = {**(existing or {}), **body}
        if 'steps' in body and 'nodes' not in body:
            from .store import _steps_to_graph
            if not isinstance(body['steps'], list):raise HTTPException(400, 'Use graph nodes or a list of steps.')
            candidate['nodes'],candidate['edges'] = _steps_to_graph(body['steps'], candidate.get('trigger_type','manual'))
        if isinstance(body.get('graph_data'), dict):candidate.update(body['graph_data'])
        candidate.pop('graph_data',None)
        # Blank drafts can be saved; execution and publication require a valid DAG.
        if candidate.get('nodes'):
            try:workflow_graph(candidate)
            except WorkflowError as exc:raise HTTPException(400,str(exc)) from exc
        elif candidate.get('edges'):raise HTTPException(400,'Edges require nodes.')
        check_nodes=json.loads(json.dumps(candidate.get('nodes',[])))
        for n in check_nodes:
            n.get('data',{}).pop('credential_refs',None)
        if workflow_sensitive(check_nodes):raise HTTPException(400,'Use credential references instead of literal secrets.')
        if candidate.get('is_template'):
            if any(n.get('data',{}).get('composition') is not None for n in candidate.get('nodes',[])):
                run_id=next((t.removeprefix('composer_test:') for t in str(candidate.get('tags','')).split(',') if t.startswith('composer_test:')),'')
                try:composer.validate_publish(candidate,run_id)
                except ValueError as exc:raise HTTPException(400,str(exc)) from None
            try:workflow_graph(candidate)
            except WorkflowError as exc:raise HTTPException(400,str(exc)) from exc
            if public_template({**candidate,'name':'Public validation','tags':'','is_active':1,'is_template':1}) is None:
                raise HTTPException(400,'Public templates require a safe English definition without credentials.')
        return candidate

    logs = log_buffer()
    from ..admin_read_cache import AdminReadCache
    overview_cache = AdminReadCache()
    # Hash-verified vector counts take about 26 s on PostgreSQL; refresh them in the background.
    vector_stats_cache = AdminReadCache(ttl=600, stale=86400)
    started = time.time()
    actions: dict[str, dict] = {}  # 백그라운드로 돌린 관리 작업의 상태 (수집·재평가)
    rag_engine = rag_engine or RagEngine()
    composer.engine = rag_engine
    login_limit = RateLimiter(10)
    password_limit = RateLimiter(5)
    login_global_limit = RateLimiter(60)
    rag_limit = RateLimiter(60)       # 60 req/min
    explore_limit = RateLimiter(120)  # 120 req/min
    index_limit = RateLimiter(10)     # 10 req/min

    @contextmanager
    def reader():
        """읽기 전용 연결. 메모리 DB(테스트)는 저장소 연결을 그대로 쓴다."""
        if getattr(store, 'backend', None) == 'postgresql':
            pool = getattr(store, '_admin_read_pool', None)
            if pool is not None:
                with pool.reader() as db: yield db
                return
            with store.tx(readonly=True) as db:
                yield db
            return
        if db_path == ":memory:":
            with store._lock:
                yield store._db
            return
        db = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True, timeout=10)
        db.row_factory = sqlite3.Row
        load_sqlite_vec(db)
        try:
            yield db
        finally:
            db.close()

    from .admin_policy import MACHINE_READS, ROLES, enforce_staff_scope, aggregate_overview, development_banner

    def authorize(request: Request, authorization: str | None, x_dashboard: str | None) -> dict:
        if not x_dashboard:
            raise HTTPException(403, "X-Dashboard 헤더가 필요합니다.")

        # 1. Bearer Token 확인 (사용자 세션 토큰 또는 시스템 ADMIN_TOKEN)
        if authorization and authorization.startswith("Bearer "):
            token = authorization[7:].strip()
            if admin_token and hmac.compare_digest(authorization.encode(), f"Bearer {admin_token}".encode()):
                if request.method != 'GET' or request.url.path not in MACHINE_READS:
                    raise HTTPException(401, "이 경로는 개인 관리자 로그인이 필요합니다.")
                return {"username": "machine", "role": "operator", "name": "집계 모니터링", "is_authenticated_session": False}
            # 1-1. DB 사용자 세션 확인
            with reader() as db:
                user = admin_auth.get_session_user(db, token, upgrade_legacy=False, allow_password_change=True)
            if user and user.pop('_legacy_session', False):
                with store.tx() as db:
                    user = admin_auth.get_session_user(db, token, allow_password_change=True)
            if user:
                user["is_authenticated_session"] = True
                enforce_staff_scope(user, request.method, request.url.path)
                return user
            raise HTTPException(401, "유효하지 않거나 만료된 관리자 세션 토큰입니다.")

        # 2. Authorization 헤더가 없는 경우
        if authorization:
            raise HTTPException(401, "Invalid authorization header.")
        if admin_token:
            raise HTTPException(401, "ADMIN_TOKEN 또는 관리자 로그인 인증이 필요합니다.")
        if os.environ.get("AGENTCON_ADMIN_DEV") != "1" or os.environ.get("DEPLOYMENT_MODE") == "production":
            raise HTTPException(401, "개인 관리자 로그인이 필요합니다.")
        if not _loopback(request.client.host if request.client else None) or _host_name(request.headers.get("host")) not in LOCAL_HOSTS:
            raise HTTPException(401, "로그인이 필요하거나 localhost 주소로만 접속할 수 있습니다.")
        return {"user_id": 1, "username": "sadmin", "role": "superadmin", "name": "개발 모드 · 로컬 관리자", "is_authenticated_session": False, "development_mode": True}

    def guard(request: Request, authorization: str | None = Header(default=None), x_dashboard: str | None = Header(default=None)) -> dict:
        user = authorize(request, authorization, x_dashboard)
        request.state.admin_user = user
        path = request.url.path
        write = request.method not in ("GET", "HEAD", "OPTIONS")
        self_service = path in ("/admin/api/auth/logout", "/admin/api/auth/change-password", "/admin/api/v2/auth/logout", "/admin/api/v2/auth/change-password")
        sensitive = path.startswith(("/admin/api/payments", "/admin/api/security", "/admin/api/ssl", "/admin/api/credentials", "/admin/api/actions"))
        if write and not user.get("is_authenticated_session"):
            raise HTTPException(401, "관리자 로그인이 필요합니다.")
        if user.get("role") not in ROLES:
            raise HTTPException(403, "Invalid administrator role.")
        if (sensitive and user.get("role") != "superadmin") or (write and not self_service and user.get("role") in ("operator", "viewer")):
            raise HTTPException(403, "이 작업에 필요한 관리자 권한이 없습니다.")
        if write:
            overview_cache.invalidate()
        return user

    def require_sadmin(request: Request, user: dict = Depends(guard)) -> dict:
        if not user.get("is_authenticated_session"):
            raise HTTPException(401, "관리자 로그인이 필요합니다.")
        if user.get("role") != "superadmin":
            raise HTTPException(403, "sadmin(최고관리자) 권한만 접근할 수 있는 메뉴입니다.")
        return user

    from ..workflow_automation_service import router_for as automation_router_for
    router.include_router(automation_router_for(workflows_runtime,require_sadmin))
    from ..workflow_storage import router_for as workflow_storage_router_for
    router.include_router(workflow_storage_router_for(db_path,require_sadmin,store=store))
    from ..workflow_product_semantics_service import router_for as product_semantics_router_for
    router.include_router(product_semantics_router_for(store,require_sadmin))
    from ..workspace_platform import admin_router_for as workspace_platform_router
    router.include_router(workspace_platform_router(front,store=store,runtime=workflows_runtime))

    auth = [Depends(guard)]

    def log_op(request: Request, action: str, action_name: str, target: str | None = None, status: str = "SUCCESS", details: Any = None):
        overview_cache.invalidate()
        user = getattr(request.state, "admin_user", None) or {"username": "sadmin", "role": "superadmin"}
        client_ip = request.client.host if request.client else None
        reason = getattr(request.state, "audit_reason", None)  # 리뉴얼 어드민의 변경 사유
        if reason:
            details = {**(details if isinstance(details, dict) else ({} if details is None else {"value": details})), "reason": reason, "via": "admin-next"}
        with store.tx() as db:
            admin_auth.record_audit(
                db,
                username=user.get("username", "sadmin"),
                role=user.get("role", "superadmin"),
                action=action,
                action_name=action_name,
                target=target,
                ip=client_ip,
                status=status,
                details=details,
            )

    # ---------------- 화면 ----------------
    def require_development_action(request):
        user = getattr(request.state, 'admin_user', {})
        if (os.environ.get('AGENTCON_ADMIN_DEV') != '1' or os.environ.get('DEPLOYMENT_MODE') == 'production'
                or not user.get('is_authenticated_session') or user.get('role') != 'superadmin'):
            raise HTTPException(403, '개인 최고관리자의 명시적인 개발 모드에서만 사용할 수 있습니다.')

    @router.get("/admin/ui", response_class=HTMLResponse, include_in_schema=False)
    def page():
        nonce = secrets.token_urlsafe(24)
        html = PAGE.read_text(encoding="utf-8").replace('<script>', f'<script nonce="{nonce}">', 1)
        if os.environ.get('AGENTCON_ADMIN_DEV') != '1' or os.environ.get('DEPLOYMENT_MODE') == 'production':
            html = html.replace('id="developmentSimulator"', 'id="developmentSimulator" hidden', 1)
            for identity in ('clearLogs', 'simText', 'simSend', 'simReset', 'simProtocol'):
                html = html.replace(f'id="{identity}"', f'id="{identity}" hidden disabled', 1)
        for asset in ('workspace-operations-admin.js', 'customer-credits-admin.js', 'workspace-admin.js', 'workspace-identity-admin.js', 'workspace-release-admin.js', 'advancement-admin.js', 'workflow-quality-admin.js', 'workspace-product-admin.js', 'workspace-flow-admin.js', 'workspace-agreement-admin.js', 'workspace-evidence-admin.js', 'workspace-typed-release-admin.js', 'workspace-reliability-admin.js', 'workspace-reliability-controls-admin.js', 'workspace-growth-admin.js', 'workspace-machine-updates-admin.js', 'workspace-typed-evidence-admin.js', 'workspace-reliability-research-admin.js', 'workspace-research-controls-admin.js', 'workspace-remote-a2a-admin.js', 'workspace-protocol-conformance-admin.js', 'privacy-review-admin.js'):
            html = html.replace(f'<script src="/admin/assets/{asset}"></script>',
                                f'<script nonce="{nonce}" src="/admin/assets/{asset}"></script>', 1)
        return HTMLResponse(development_banner(html), headers={
            "cache-control": "no-store",
            "x-frame-options": "DENY",
            "referrer-policy": "no-referrer",
            "x-content-type-options": "nosniff",
            "strict-transport-security": "max-age=31536000; includeSubDomains",
            "permissions-policy": "camera=(), microphone=(), geolocation=()",
            "content-security-policy": (
                f"default-src 'none'; script-src 'nonce-{nonce}'; script-src-attr 'none'; style-src 'unsafe-inline'; "
                "img-src 'self' data:; connect-src 'self' https://agentconcierge.biz; frame-ancestors 'none'; "
                "object-src 'none'; base-uri 'none'; form-action 'self'"
            )})

    @router.get('/admin/assets/workspace-operations-admin.js', include_in_schema=False)
    def workspace_operations_script():
        from ..workspace_admin_service import script_response
        return script_response()

    @router.get('/admin/assets/workspace-admin.js', include_in_schema=False)
    def workspace_script():
        from ..workspace_service import asset_response
        return asset_response()

    @router.get('/admin/assets/customer-credits-admin.js', include_in_schema=False)
    @router.get('/admin/assets/workspace-identity-admin.js', include_in_schema=False)
    @router.get('/admin/assets/workspace-release-admin.js', include_in_schema=False)
    @router.get('/admin/assets/advancement-admin.js', include_in_schema=False)
    @router.get('/admin/assets/workflow-quality-admin.js', include_in_schema=False)
    @router.get('/admin/assets/workspace-product-admin.js', include_in_schema=False)
    @router.get('/admin/assets/workspace-flow-admin.js', include_in_schema=False)
    @router.get('/admin/assets/workspace-agreement-admin.js', include_in_schema=False)
    @router.get('/admin/assets/workspace-evidence-admin.js', include_in_schema=False)
    @router.get('/admin/assets/workspace-typed-release-admin.js', include_in_schema=False)
    @router.get('/admin/assets/workspace-reliability-admin.js', include_in_schema=False)
    @router.get('/admin/assets/workspace-reliability-controls-admin.js', include_in_schema=False)
    @router.get('/admin/assets/workspace-growth-admin.js', include_in_schema=False)
    @router.get('/admin/assets/workspace-machine-updates-admin.js', include_in_schema=False)
    @router.get('/admin/assets/workspace-typed-evidence-admin.js', include_in_schema=False)
    @router.get('/admin/assets/workspace-reliability-research-admin.js', include_in_schema=False)
    @router.get('/admin/assets/workspace-research-controls-admin.js', include_in_schema=False)
    @router.get('/admin/assets/workspace-remote-a2a-admin.js', include_in_schema=False)
    @router.get('/admin/assets/privacy-review-admin.js', include_in_schema=False)
    def workspace_extension_script(request: Request):
        # Only the fixed routes above are registered; request text is never a path.
        assets = {name: PAGE.parent / name for name in (
            'customer-credits-admin.js', 'workspace-identity-admin.js', 'workspace-release-admin.js', 'advancement-admin.js', 'workflow-quality-admin.js', 'workspace-product-admin.js', 'workspace-flow-admin.js', 'workspace-agreement-admin.js', 'workspace-evidence-admin.js', 'workspace-typed-release-admin.js', 'workspace-reliability-admin.js', 'workspace-reliability-controls-admin.js', 'workspace-growth-admin.js', 'workspace-machine-updates-admin.js', 'workspace-typed-evidence-admin.js', 'workspace-reliability-research-admin.js', 'workspace-research-controls-admin.js', 'workspace-remote-a2a-admin.js', 'workspace-protocol-conformance-admin.js', 'privacy-review-admin.js')}
        path = assets.get(request.url.path.rsplit('/', 1)[-1])
        if path is None or not path.is_file():
            raise HTTPException(404, 'Workspace interface unavailable.')
        return Response(path.read_bytes(), media_type='application/javascript', headers={
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'Cross-Origin-Resource-Policy': 'same-origin',
            'Content-Security-Policy': "default-src 'none'; frame-ancestors 'none'"})

    @router.get("/admin/api/session", dependencies=auth)
    def session():
        return {"ok": True, "token_required": bool(admin_token)}

    # ---------------- 관리자 인증 & 세션 & 마이페이지 ----------------
    @router.post("/admin/api/v2/auth/login")
    @router.post("/admin/api/auth/login")
    async def auth_login(request: Request, x_dashboard: str | None = Header(default=None)):
        if not x_dashboard:
            raise HTTPException(403, "X-Dashboard 헤더가 필요합니다.")
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "요청 형식이 잘못되었습니다.")

        username = (body.get("username") or "").strip()
        password = body.get("password") or ""
        client_ip = request.client.host if request.client else "unknown"
        if not login_limit.allow(client_ip) or not login_global_limit.allow("all"):
            raise HTTPException(429, "로그인 요청이 너무 많습니다.", headers={"Retry-After":"60"})
        with store.tx() as db:
            user = admin_auth.authenticate_user(db, username, password)
        if not user:
            with store.tx() as db:
                admin_auth.record_audit(
                    db,
                    username=username or "unknown",
                    role="none",
                    action="LOGIN_FAIL",
                    action_name="로그인 실패",
                    ip=client_ip,
                    status="FAILED",
                    details={"reason": "Invalid credentials or inactive account"},
                )
            raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않거나 비활성화된 계정입니다.")

        with store.tx() as db:
            token = admin_auth.create_session(
                db,
                user_id=user["id"],
                username=user["username"],
                role=user["role"],
                name=user["name"],
                ip=client_ip,
                user_agent=request.headers.get("user-agent"),
            )
            admin_auth.record_audit(
                db,
                username=user["username"],
                role=user["role"],
                action="LOGIN",
                action_name="로그인 성공",
                ip=client_ip,
                status="SUCCESS",
            )
            return {
                "ok": True,
                "token": token,
                "user": {
                    "id": user["id"],
                    "username": user["username"],
                    "role": user["role"],
                    "name": user["name"],
                    "is_sadmin": (user["role"] == "superadmin"),
                    "password_change_required": user["password_change_required"],
                },
            }

    @router.post("/admin/api/v2/auth/logout", dependencies=auth)
    @router.post("/admin/api/auth/logout", dependencies=auth)
    def auth_logout(request: Request, authorization: str | None = Header(default=None)):
        user = getattr(request.state, "admin_user", {"username": "sadmin", "role": "superadmin"})
        client_ip = request.client.host if request.client else None
        token = authorization[7:].strip() if authorization and authorization.startswith("Bearer ") else ""
        with store.tx() as db:
            if token:
                admin_auth.delete_session(db, token)
            admin_auth.record_audit(
                db,
                username=user.get("username", "unknown"),
                role=user.get("role", "admin"),
                action="LOGOUT",
                action_name="로그아웃",
                ip=client_ip,
                status="SUCCESS",
            )
        return {"ok": True}

    @router.get("/admin/api/v2/auth/me", dependencies=auth)
    @router.get("/admin/api/auth/me", dependencies=auth)
    def auth_me(request: Request):
        user = getattr(request.state, "admin_user", None)
        if not user or not user.get("is_authenticated_session"):
            raise HTTPException(401, "관리자 로그인이 필요합니다.")
        is_sadmin = user.get("role") == "superadmin"
        return {"ok": True, "user": user, "is_sadmin": is_sadmin}

    @router.post("/admin/api/v2/auth/change-password", dependencies=auth)
    @router.post("/admin/api/auth/change-password", dependencies=auth)
    async def auth_change_password(request: Request):
        user = getattr(request.state, "admin_user", None)
        if not user or not user.get("is_authenticated_session") or not user.get("user_id"):
            raise HTTPException(401, "관리자 로그인이 필요합니다.")
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "요청 형식이 잘못되었습니다.")

        curr_pwd = body.get("current_password") or ""
        new_pwd = body.get("new_password") or ""
        client_ip = request.client.host if request.client else None

        if not password_limit.allow(str(user["user_id"])):
            raise HTTPException(429, "Too many password attempts.", headers={"Retry-After":"60"})
        try:
            admin_auth.validate_password(new_pwd)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

        try:
            with store.tx() as db:
                ok = admin_auth.change_user_password(db, user["user_id"], curr_pwd, new_pwd)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        if not ok:
            with store.tx() as db:
                admin_auth.record_audit(
                    db,
                    username=user["username"],
                    role=user["role"],
                    action="PASSWORD_CHANGE_FAIL",
                    action_name="비밀번호 변경 실패",
                    ip=client_ip,
                    status="FAILED",
                    details={"reason": "Current password mismatch"},
                )
            raise HTTPException(400, "현재 비밀번호가 일치하지 않습니다.")

        with store.tx() as db:
            admin_auth.record_audit(
                db,
                username=user["username"],
                role=user["role"],
                action="PASSWORD_CHANGE",
                action_name="비밀번호 재등록 완료",
                ip=client_ip,
                status="SUCCESS",
            )
        return {"ok": True, "message": "비밀번호가 성공적으로 변경되었습니다."}

    # ---------------- 관리자 계정 관리 (sadmin 전용) ----------------
    @router.get("/admin/api/users", dependencies=[Depends(require_sadmin)])
    def get_users():
        with reader() as db:
            users = admin_auth.list_admin_users(db)
        return {"ok": True, "users": users}

    async def request_account_change(request, action, uid=None):
        from ..workspace_admin_reviewed import ReviewUnavailable, ReviewConflict
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "요청 형식이 잘못되었습니다.") from None
        try:
            account_reviews._key()
            actor = request.state.admin_user
            target, payload, reason = account_changes.prepare(actor['user_id'], action, uid, body)
            item = account_reviews.request(actor['user_id'], 'admin_account_change', target, payload, reason)
        except ReviewUnavailable:
            raise HTTPException(409, '승인 저장소 마이그레이션 후 계정 변경을 요청할 수 있습니다.') from None
        except ReviewConflict:
            raise HTTPException(409, '같은 계정의 승인 요청이 진행 중입니다.') from None
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        return JSONResponse({'ok': True, 'review_required': True, 'item': item,
                             'review_url': '/admin/next#/security/s01'}, status_code=202,
                            headers={'Cache-Control': 'no-store'})

    @router.post("/admin/api/users", dependencies=[Depends(require_sadmin)])
    async def create_user(request: Request):
        return await request_account_change(request, 'create')

    @router.put("/admin/api/users/{uid}", dependencies=[Depends(require_sadmin)])
    async def update_user(uid: int, request: Request):
        return await request_account_change(request, 'update', uid)

    @router.delete("/admin/api/users/{uid}", dependencies=[Depends(require_sadmin)])
    async def delete_user(uid: int, request: Request):
        return await request_account_change(request, 'delete', uid)

    # ---------------- 관리자 감사 로그 (sadmin 전용) ----------------
    @router.get("/admin/api/audit/logs", dependencies=[Depends(require_sadmin)])
    def get_audit_logs(
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        action: str | None = Query(default=None),
        username: str | None = Query(default=None),
        status: str | None = Query(default=None),
    ):
        with reader() as db:
            logs, total = admin_auth.list_audit_logs(db, limit=limit, offset=offset, action=action, username=username, status=status)
        return {"ok": True, "logs": logs, "count": total}

    # ---------------- 개요 ----------------
    @router.get("/admin/api/overview", dependencies=auth)
    def overview(request: Request, response: Response):
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Vary"] = "Authorization, X-Dashboard"
        try:
            data = overview_cache.get(overview_data, force=request.headers.get('x-admin-refresh') == '1')
            return aggregate_overview(data) if request.state.admin_user.get('username') == 'machine' else data
        except (sqlite3.DatabaseError, TimeoutError):
            raise HTTPException(503, 'Overview temporarily unavailable. Please retry.',
                                headers={'Cache-Control': 'no-store', 'Retry-After': '5'}) from None

    def vector_stats_data():
        def load():
            with reader() as db:
                stats = store.vec_stats(rag_engine.model_descriptor(), read_db=db)
            return {**stats, 'available': True, 'captured_at': time.time()}
        try:
            return vector_stats_cache.get(load)
        except (sqlite3.DatabaseError, TimeoutError):
            log.warning('Administrator vector statistics temporarily unavailable')
            return {'available': False, 'vector_count': None, 'raw_vector_count': None,
                    'outbox_count': None, 'active_count': None, 'pct': None}

    def overview_data():
        now = time.time()
        from ..config import health_interval_seconds
        checker = getattr(collector, 'checker', None)
        health_interval = checker.schedule.interval if checker is not None else health_interval_seconds()
        with reader() as db:
            q = lambda sql, p=(): _rows(db.execute(sql, p))  # noqa: E731
            by_kind_status = q("""SELECT kind, active, health_status AS status, COUNT(*) AS n FROM resources
                                  GROUP BY kind, active, health_status""")
            checks_1h = q("""SELECT COUNT(*) AS n, COALESCE(SUM(outcome IN ('healthy','reachable')),0) AS ok
                             FROM health_checks WHERE at>?""", (now - 3600,))[0]
            checks_2h = q("""SELECT COUNT(*) AS n, COALESCE(SUM(outcome IN ('healthy','reachable')),0) AS ok
                             FROM health_checks WHERE at>?""", (now - 7200,))[0]
            checks_6h = q("""SELECT COUNT(*) AS n, COALESCE(SUM(outcome IN ('healthy','reachable')),0) AS ok
                             FROM health_checks WHERE at>?""", (now - 21600,))[0]
            checks_5m = q("SELECT COUNT(*) AS n FROM health_checks WHERE at>?", (now - 300,))[0]["n"]
            backlog = q("""SELECT
                             SUM(next_check_at IS NULL) AS never,
                             SUM(next_check_at <= ?) AS due,
                             SUM(next_check_at < ?) AS overdue_1h,
                             SUM(next_check_at < ?) AS overdue_2h,
                             SUM(next_check_at < ?) AS overdue_6h
                           FROM resources WHERE active=1 AND health_status != 'retired'""", (now, now - 3600, now - 7200, now - 21600))[0]
            backlog_by_kind = q("""SELECT
                                     kind,
                                     SUM(next_check_at <= ?) AS due,
                                     SUM(next_check_at < ?) AS overdue_2h,
                                     SUM(next_check_at < ?) AS overdue_6h
                                   FROM resources WHERE active=1 AND health_status != 'retired'
                                   GROUP BY kind""", (now, now - 7200, now - 21600))
            by_source = q("""SELECT source,active,COUNT(*) AS n,
                SUM(registry_missing_since IS NOT NULL) AS registry_missing,
                SUM(managed_at IS NOT NULL) AS managed_checked
                FROM resources GROUP BY source,active""")
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
                             SUM(eval_at > ?) AS evaluations_24h,
                             SUM(trial_ok = 1) AS verified_working, SUM(trial_ok = 0) AS trial_failed
                           FROM resources WHERE active=1""", (now - 86400,) * 3)[0]
            surveys['usage_guides'] = q("SELECT COUNT(*) AS n FROM resources WHERE active=1 AND usage_guide IS NOT NULL")[0]['n']
            needs = q("SELECT status, COUNT(*) AS n FROM needs GROUP BY status")
            offers = q("SELECT status, COUNT(*) AS n FROM offers GROUP BY status")
            meta = {r["key"]: _meta(r["value"]) for r in q(
                f"SELECT key, value FROM meta WHERE key IN ({','.join('?' * len(META_KEYS))}) OR key LIKE 'crawl_pass:%' "
                "OR key LIKE 'erc8004_next:%' OR key LIKE 'erc8004_rescan:%'", META_KEYS)}
            crawl_runs = q("SELECT * FROM crawl_runs ORDER BY at DESC LIMIT 30")
            scavenger = store.scavenger_stats(read_db=db)
            # Reuse the live public projection, not historical trial flags or a
            # second definition of active/retired catalog membership.
            from ..concierge.pearl_view import _catalog_status
            from types import SimpleNamespace
            current_store = getattr(db, '_store', None)
            public_catalog = _catalog_status(current_store or SimpleNamespace(query=q))
            customer_requests = (current_store or store).get_customer_requests_summary()
        # Optional index diagnostics have an independent transaction and cache;
        # a timeout must not abort the catalog and operational dashboard.
        vector_stats = vector_stats_data()
        erc_chains: dict = {}
        for r in erc:
            c = erc_chains.setdefault(r["chain"], {"statuses": {}, "next_id": meta.get(f"erc8004_next:{r['chain']}"),
                                                    "rescan_cursor": meta.get(f"erc8004_rescan:{r['chain']}")})
            c["statuses"][r["status"]] = r["n"]
        return {
            "now": now, "started_at": started,
            "collector": store._service_control.status('jobs') if getattr(store, '_service_control', None) else None if collector is None else {
                "paused": collector.paused.is_set(), "started_at": collector.started_at, "threads": collector.thread_status()},
            "policy": None if service is None else ("free" if service.policy.free else "paid"),
            "resources": by_kind_status,
            "public_catalog": public_catalog,
            "customer_requests": customer_requests,
            "storage": {'backend': getattr(store, 'backend', 'sqlite')},
            "health": {
                "interval": health_interval,
                "checks_1h": checks_1h["n"], "ok_1h": checks_1h["ok"],
                "checks_2h": checks_2h["n"], "ok_2h": checks_2h["ok"],
                "checks_6h": checks_6h["n"], "ok_6h": checks_6h["ok"],
                "checks_5m": checks_5m,
                "never_checked": backlog["never"] or 0, "due_now": backlog["due"] or 0,
                "overdue_1h": backlog["overdue_1h"] or 0, "overdue_2h": backlog["overdue_2h"] or 0,
                "overdue_6h": backlog["overdue_6h"] or 0,
                "by_kind": {r["kind"]: {"due": r["due"] or 0, "overdue_2h": r["overdue_2h"] or 0,
                                           "overdue_6h": r["overdue_6h"] or 0} for r in backlog_by_kind},
            },
            "crawl": {"in_progress": {k.split(":", 1)[1]: v for k, v in meta.items() if k.startswith("crawl_pass:") and v},
                      "last": meta.get("last_crawl"), "runs": crawl_runs},
            "loops": {k: meta.get(k) for k in META_KEYS if k != "last_crawl"},
            "by_source": by_source,
            "categories": categories,
            "category_names": {**{c.id: c.name for c in CATEGORIES.values()}, "other": "기타"},
            "erc8004": erc_chains,
            "wellknown": {"checked": wk["checked"], "found": wk["found"] or 0},
            "evaluation": {"grades": grades, "security": security},
            "surveys": surveys,
            "scavenger": scavenger,
            "needs": {r["status"]: r["n"] for r in needs},
            "rag": {**vector_stats, "embed_model": rag_engine.embed_model, "generation_model": rag_engine.generation_model},
            "log_counts": dict(logs.counts),
            "ssl": (ssl_manager or get_ssl_manager()).get_status(),
            "actions": store._service_control.actions() if getattr(store, '_service_control', None) else actions,
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
    @router.get('/admin/api/execution-controls',dependencies=[Depends(require_sadmin)])
    def execution_controls():
        from ..execution_authority import controls
        return JSONResponse({**controls(store),'events':[dict(r) for r in store.query('SELECT * FROM execution_control_events ORDER BY revision DESC LIMIT 20')]},headers={'Cache-Control':'no-store'})

    @router.put('/admin/api/execution-controls',dependencies=[Depends(require_sadmin)])
    async def execution_controls_save(request:Request):
        from ..execution_authority import set_controls
        try:result=set_controls(store,await request.json(),request.state.admin_user['user_id'])
        except ValueError as exc:raise HTTPException(409,str(exc)) from None
        log_op(request,'execution_controls','실행·전달 제어 변경',details={k:result[k] for k in ('invoke_enabled','workflow_enabled','delivery_enabled','revision')})
        return JSONResponse(result,headers={'Cache-Control':'no-store'})

    @router.get('/admin/api/workflows/{workflow_id}/delivery-grants',dependencies=[Depends(require_sadmin)])
    def workflow_delivery_grants(workflow_id:int):
        return JSONResponse({'grants':workflows_runtime.authority.grants(workflow_id)},headers={'Cache-Control':'no-store'})

    @router.get('/admin/api/fallback-control',dependencies=[Depends(require_sadmin)])
    def fallback_control():
        return JSONResponse(workflows_runtime.fallback.control_status(),headers={'Cache-Control':'no-store'})

    @router.put('/admin/api/fallback-control',dependencies=[Depends(require_sadmin)])
    async def fallback_control_save(request:Request):
        try:result=workflows_runtime.fallback.set_control(await request.json(),request.state.admin_user['user_id'])
        except ValueError as exc:raise HTTPException(409,str(exc)) from None
        log_op(request,'fallback_control','Informational fallback control updated',details={'revision':result['revision'],'enabled':result['enabled']})
        return JSONResponse(result,headers={'Cache-Control':'no-store'})

    @router.get('/admin/api/workflows/{workflow_id}/fallback',dependencies=[Depends(require_sadmin)])
    def workflow_fallback_inspect(workflow_id:int):
        if not store.get_workflow(workflow_id):raise HTTPException(404,'Workflow not found.')
        return JSONResponse(workflows_runtime.fallback.inspect(workflow_id),headers={'Cache-Control':'no-store'})

    @router.put('/admin/api/workflows/{workflow_id}/fallback',dependencies=[Depends(require_sadmin)])
    async def workflow_fallback_save(workflow_id:int,request:Request):
        try:result=workflows_runtime.fallback.configure(workflow_id,await request.json(),request.state.admin_user['user_id'])
        except ValueError as exc:raise HTTPException(409,str(exc)) from None
        log_op(request,'workflow_fallback','Informational routing policy updated',details={'workflow_id':workflow_id,'revision':result['revision']})
        return JSONResponse(result,headers={'Cache-Control':'no-store'})

    @router.get('/admin/api/workflow-io-profiles',dependencies=[Depends(require_sadmin)])
    def workflow_io_profiles():
        return JSONResponse({'profiles':workflows_runtime.io_profiles.list()},headers={'Cache-Control':'no-store'})

    @router.get('/admin/api/workflow-io-profiles/schemas',dependencies=[Depends(require_sadmin)])
    def workflow_io_schemas(resource_id:int,tool:str,contract_id:str):
        from ..capability_contracts import CONTRACTS
        if contract_id not in ('docs.search.v1','news.search.v1'):raise HTTPException(400,'Use a supported contract.')
        try:spec=workflows_runtime.io_profiles.spec(store.resource(resource_id),tool)
        except (ValueError,TypeError,AttributeError):raise HTTPException(409,'Review the current registered tool and supported read-only schemas.') from None
        return JSONResponse({'canonical':CONTRACTS[contract_id],'native':spec},headers={'Cache-Control':'no-store'})

    @router.post('/admin/api/workflow-io-profiles/verify',dependencies=[Depends(require_sadmin)])
    async def workflow_io_verify(request:Request):
        raw=await request.body()
        if len(raw)>64000:raise HTTPException(413,'Use a bounded transformation test request.')
        user=request.state.admin_user
        def current_authority():
            current=authorize(request,request.headers.get('authorization'),request.headers.get('x-dashboard'))
            return current.get('is_authenticated_session') is True and current.get('user_id')==user['user_id'] and current.get('role')=='superadmin'
        try:
            body=json.loads(raw)
            from starlette.concurrency import run_in_threadpool
            result=await run_in_threadpool(workflows_runtime.io_profiles.create,body,user['user_id'],current_authority)
        except (ValueError,TypeError,KeyError,RecursionError,OverflowError):raise HTTPException(409,'Review the schemas, transformations, current tool approval and real test result.') from None
        log_op(request,'workflow_io_profile','Verified generic input/output transformations',details={'profile_id':result['id'],'cases':result['cases']})
        return JSONResponse(result,headers={'Cache-Control':'no-store'})

    @router.post('/admin/api/workflow-io-profiles/preview',dependencies=[Depends(require_sadmin)])
    async def workflow_io_preview(request:Request):
        raw=await request.body()
        if len(raw)>64000:raise HTTPException(413,'Use a bounded transformation preview.')
        try:
            body=json.loads(raw)
            if not isinstance(body,dict) or set(body)!={'recipe','input'}:raise ValueError()
            from ..workflow_transforms import apply as transform
            result=transform(body['recipe'],body['input'])
        except (ValueError,TypeError,KeyError,RecursionError,OverflowError):raise HTTPException(400,'The transformation or input does not match the declared schemas.') from None
        return JSONResponse({'output':result,'provider_calls':0},headers={'Cache-Control':'no-store'})

    @router.delete('/admin/api/workflow-io-profiles/{profile_id}',dependencies=[Depends(require_sadmin)])
    def workflow_io_revoke(profile_id:str,request:Request):
        try:result=workflows_runtime.io_profiles.revoke(profile_id)
        except ValueError:raise HTTPException(400,'Use a verified transformation profile reference.') from None
        log_op(request,'workflow_io_profile_revoke','Revoked generic input/output transformations',details={'profile_id':profile_id})
        return JSONResponse(result,headers={'Cache-Control':'no-store'})

    @router.delete('/admin/api/workflows/{workflow_id}/delivery-grants/{grant_id}',dependencies=[Depends(require_sadmin)])
    def workflow_grant_revoke(workflow_id:int,grant_id:str):
        workflows_runtime.authority.revoke(workflow_id,grant_id)
        return {'ok':True}

    @router.get('/admin/api/workflows/runs/{run_id}/recovery',dependencies=[Depends(require_sadmin)])
    def workflow_recovery_inspect(run_id:str):
        if not re.fullmatch(r'wr_[0-9a-f]{32}',run_id):raise HTTPException(400,'Invalid run reference.')
        result=workflows_runtime.persistence.inspect(run_id)
        if result is None:raise HTTPException(404,'Run not found.')
        result['routing']=workflows_runtime.fallback.decisions(run_id)
        result['operations']=workflows_runtime.operations.inspect(run_id)
        row=dict(store.query('SELECT * FROM workflow_runs WHERE id=?',(run_id,))[0])
        result['workflow_id']=row['workflow_id']
        result['execution_budget']={k:v for k,v in workflows_runtime.budgets.get(row).items() if k in ('profile','total_seconds','node_seconds')}
        return JSONResponse(result,headers={'Cache-Control':'no-store'})

    @router.post('/admin/api/workflows/runs/{run_id}/reconciliation',dependencies=[Depends(require_sadmin)])
    async def workflow_reconcile(run_id:str,request:Request):
        if not re.fullmatch(r'wr_[0-9a-f]{32}',run_id):raise HTTPException(400,'Invalid run reference.')
        rows=store.query('SELECT workflow_id FROM workflow_runs WHERE id=?',(run_id,))
        if not rows:raise HTTPException(404,'Run not found.')
        user=request.state.admin_user
        principal=workflows_runtime.principal('admin',str(user['user_id']),rows[0]['workflow_id'],role=user['role'])
        try:result=workflows_runtime.operations.reconcile(run_id,await request.json(),principal)
        except ValueError as exc:raise HTTPException(409,str(exc)) from None
        log_op(request,'workflow_reconcile','External outcome review recorded',details={'run_id':run_id})
        return JSONResponse(result,headers={'Cache-Control':'no-store'})

    @router.post('/admin/api/workflows/runs/{run_id}/manual-deliveries',dependencies=[Depends(require_sadmin)])
    async def workflow_manual_resend(run_id:str,request:Request):
        if not re.fullmatch(r'wr_[0-9a-f]{32}',run_id):raise HTTPException(400,'Invalid run reference.')
        rows=store.query('SELECT workflow_id FROM workflow_runs WHERE id=?',(run_id,))
        if not rows:raise HTTPException(404,'Run not found.')
        user=request.state.admin_user
        principal=workflows_runtime.principal('admin',str(user['user_id']),rows[0]['workflow_id'],role=user['role'])
        try:result=workflows_runtime.operations.request_resend(run_id,await request.json(),principal)
        except ValueError as exc:raise HTTPException(409,str(exc)) from None
        log_op(request,'workflow_manual_delivery','Single result resend authorized',details={'run_id':run_id,'event_id':result['id']})
        return JSONResponse(result,status_code=202,headers={'Cache-Control':'no-store'})

    @router.get('/admin/api/workflows/maintenance',dependencies=[Depends(require_sadmin)])
    def workflow_retention_preview():
        return JSONResponse(workflows_runtime.maintenance.run(),headers={'Cache-Control':'no-store'})

    @router.post('/admin/api/workflows/maintenance',dependencies=[Depends(require_sadmin)])
    async def workflow_retention_apply(request:Request):
        try:
            body=await request.json()
            if not isinstance(body,dict) or set(body)!={'authority','notice'} or body['authority'] is not True or body['notice']!='workflow-retention-v1':raise ValueError('Explicit retention authorization is required.')
            result=workflows_runtime.maintenance.run(apply=True,actor=request.state.admin_user['user_id'])
        except ValueError as exc:raise HTTPException(409,str(exc)) from None
        log_op(request,'workflow_retention','Bounded retention batch applied',details={'bodies':result['bodies_compacted'],'metadata':result['metadata_pruned']})
        return JSONResponse(result,headers={'Cache-Control':'no-store'})

    @router.get('/admin/api/workflows/runs/{run_id}/authority',dependencies=[Depends(require_sadmin)])
    def workflow_authority_inspect(run_id:str):
        rows=store.query('SELECT workflow_id,digest,source FROM workflow_runs WHERE id=?',(run_id,))
        if not rows:raise HTTPException(404,'Run not found.')
        row=rows[0]
        try:authority=workflows_runtime.authority.run(run_id,row['workflow_id'],row['digest'],row['source'])
        except ValueError:authority=None
        principal=authority['principal']['payload'] if authority else {}
        return JSONResponse({'authority_valid':bool(authority),'principal_kind':principal.get('kind'),'audience':principal.get('audience'),
            'workflow_id':row['workflow_id'],'source':row['source'],'grant_id':authority.get('grant_id') if authority else None,
            'expires':principal.get('expires')},headers={'Cache-Control':'no-store'})
    @router.get('/admin/api/connections/{rid}',dependencies=[Depends(require_sadmin)])
    def connection_evidence(rid:int):
        from ..capability_registry import Registry
        result=Registry(store).inspect(rid)
        if result is None:raise HTTPException(404,'Agent not found.')
        return JSONResponse(result,headers={'Cache-Control':'no-store'})

    @router.get('/admin/api/capability-contracts',dependencies=[Depends(require_sadmin)])
    def capability_contracts():
        from ..capability_contracts import CONTRACTS
        return JSONResponse({'contracts':CONTRACTS},headers={'Cache-Control':'no-store'})

    @router.post('/admin/api/connections/{rid}/contracts/{contract_id}',dependencies=[Depends(require_sadmin)])
    async def approve_capability(rid:int,contract_id:str,request:Request):
        from ..capability_registry import Registry
        if contract_id=='products.compare.v2':
            try:
                product_semantics.current_actor(request.state.admin_user['user_id'])
                body=await product_v2_request(request)
            except PermissionError:
                raise HTTPException(403,'Current highest-administrator access is required.',headers={'Cache-Control':'no-store'}) from None
            except (ValueError,TypeError,UnicodeError,RecursionError,TimeoutError):
                raise HTTPException(400,'Provide one bounded product-contract approval request.',headers={'Cache-Control':'no-store'}) from None
            if set(body)!={'tool'} or not isinstance(body['tool'],str) or not 1<=len(body['tool'])<=100:
                raise HTTPException(400,'Choose one exact registered product tool.',headers={'Cache-Control':'no-store'})
            resource=store.resource(rid)
            if not resource:raise HTTPException(404,'Agent not found.',headers={'Cache-Control':'no-store'})
            try:
                product_semantics.current_actor(request.state.admin_user['user_id'])
                version=Registry(store).approve(resource,contract_id,body['tool'],
                    guard=lambda:product_semantics.current_actor(request.state.admin_user['user_id']))
                product_semantics.current_actor(request.state.admin_user['user_id'])
            except PermissionError:
                raise HTTPException(403,'Current highest-administrator access is required.',headers={'Cache-Control':'no-store'}) from None
            except (ValueError,TypeError,KeyError,sqlite3.DatabaseError):
                raise HTTPException(409,'This version does not satisfy the strict product-contract approval requirements.',headers={'Cache-Control':'no-store'}) from None
            return JSONResponse({'ok':True,'agent_ref':version['agent_ref'],'contract_id':contract_id},headers={'Cache-Control':'no-store'})
        try:body=await request.json()
        except ValueError:raise HTTPException(400,'Provide valid JSON.') from None
        if not isinstance(body,dict) or set(body)!={'tool'}:raise HTTPException(400,'Provide one registered tool.')
        resource=store.resource(rid)
        if not resource:raise HTTPException(404,'Agent not found.')
        try:version=Registry(store).approve(resource,contract_id,body['tool'])
        except ValueError as exc:raise HTTPException(400,str(exc)) from None
        return {'ok':True,'agent_ref':version['agent_ref'],'contract_id':contract_id}

    admin_data_agents = {}

    @router.post('/admin/api/owned-data/github-issues/search',dependencies=[Depends(require_sadmin)])
    async def admin_github_issues(request:Request):
        """Administrator-only GitHub issue and pull request search; never listed or offered publicly.

        Unauthenticated GitHub search allows ten requests a minute, so a public visitor could see
        a source limit as a service failure. Answers are cached for ten minutes."""
        from ..owned_data_agents.engine import DataAgents, DataUnavailable
        from starlette.concurrency import run_in_threadpool
        try:body=await request.json()
        except ValueError:raise HTTPException(400,'Provide valid JSON.') from None
        allowed={'query','limit','repository','type','state'}
        if not isinstance(body,dict) or not {'query','limit'}<=set(body)<=allowed:
            raise HTTPException(400,'Provide query and limit, with optional repository, type and state.')
        engine=admin_data_agents.setdefault('engine',DataAgents())
        try:return JSONResponse(await run_in_threadpool(engine.execute,'github-issues',body),headers={'Cache-Control':'no-store'})
        except DataUnavailable:
            raise HTTPException(503,'GitHub search is unavailable or its ten-per-minute limit is reached; try again shortly.',headers={'Cache-Control':'no-store'}) from None
        except (ValueError,TypeError,KeyError):
            raise HTTPException(400,'Use public keywords, a 1-5 limit and an owner/repository name.',headers={'Cache-Control':'no-store'}) from None

    @router.post('/admin/api/connections/{rid}/contracts/{contract_id}/test',dependencies=[Depends(require_sadmin)])
    async def test_capability(rid:int,contract_id:str,request:Request):
        from ..capability_registry import Registry
        from ..capability_contracts import run_test
        from ..concierge.managed_gateway import ManagedGateway
        from types import SimpleNamespace
        if contract_id=='products.compare.v2':
            actor=request.state.admin_user['user_id']
            try:
                product_semantics.current_actor(actor)
                body=await product_v2_request(request)
            except PermissionError:
                raise HTTPException(403,'Current highest-administrator access is required.',headers={'Cache-Control':'no-store'}) from None
            except (ValueError,TypeError,UnicodeError,RecursionError,TimeoutError):
                raise HTTPException(400,'Provide one bounded product-contract test request.',headers={'Cache-Control':'no-store'}) from None
            if set(body)!={'input'} or not isinstance(body['input'],dict):
                raise HTTPException(400,'Provide exact typed product-contract input.',headers={'Cache-Control':'no-store'})
            resource=store.resource(rid)
            if not resource:raise HTTPException(404,'Agent not found.',headers={'Cache-Control':'no-store'})
            gateway=getattr(front,'managed_gateway',None) or ManagedGateway(SimpleNamespace(store=store,proxy=workflows_runtime.proxy,courier=workflows_runtime.courier))
            async def guarded_runner(*args,**kwargs):
                product_semantics.current_actor(actor)
                value=await gateway.execute(*args,**kwargs)
                product_semantics.current_actor(actor)
                return value
            try:
                product_semantics.current_actor(actor)
                result=await run_test(Registry(store),resource,contract_id,body['input'],guarded_runner)
                product_semantics.current_actor(actor)
            except PermissionError:
                raise HTTPException(403,'Current highest-administrator access is required.',headers={'Cache-Control':'no-store'}) from None
            except (ValueError,TypeError,KeyError,sqlite3.DatabaseError):
                raise HTTPException(409,'The current product-contract test requirements or result could not be verified.',headers={'Cache-Control':'no-store'}) from None
            return JSONResponse(result,headers={'Cache-Control':'no-store'})
        resource=store.resource(rid)
        if not resource:raise HTTPException(404,'Agent not found.')
        try:body=await request.json()
        except ValueError:raise HTTPException(400,'Provide valid JSON.') from None
        if not isinstance(body,dict) or set(body)!={'input'}:raise HTTPException(400,'Provide contract input only.')
        gateway=getattr(front,'managed_gateway',None) or ManagedGateway(SimpleNamespace(store=store,proxy=workflows_runtime.proxy,courier=workflows_runtime.courier))
        try:result=await run_test(Registry(store),resource,contract_id,body['input'],gateway.execute)
        except ValueError as exc:raise HTTPException(400,str(exc)) from None
        return JSONResponse(result,headers={'Cache-Control':'no-store'})

    @router.get('/admin/api/observations',dependencies=[Depends(require_sadmin)])
    def operational_observations(hours:int=Query(24,ge=1,le=168),
                                 reference:str|None=Query(None,pattern=r'^ex_[0-9a-f]{24}$'),
                                 limit:int=Query(20,ge=1,le=50)):
        from ..observability import journal_for, snapshot
        try:
            journal=journal_for(store)
            journal.flush()
            with reader() as db:
                started_transaction=not db.in_transaction
                if started_transaction:db.execute('BEGIN')
                try:result=snapshot(db,hours=hours,identity=reference,limit=limit,journal=journal)
                finally:
                    if started_transaction:db.rollback()
        except sqlite3.Error:
            raise HTTPException(503,'Operational metadata is temporarily unavailable.')
        return JSONResponse(result,headers={'Cache-Control':'no-store'})

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
                f"""SELECT r.id, r.kind, r.source, r.name, r.url, r.description, r.category, r.active, r.health_status, r.consecutive_failures,
                           r.last_check_at, r.last_ok_at, r.last_status_code, r.last_error, r.health_ok_24h, r.health_n_24h,
                           r.probe_latency_ms, r.eval_grade, r.eval_score, r.eval_security, r.trial_ok, r.price_usdc,
                           r.payers_30d, r.first_seen
                    FROM resources r WHERE {where} ORDER BY {order} NULLS LAST, r.id LIMIT ? OFFSET ?""",
                (*params, limit, offset)))
        return {"total": total, "offset": offset, "limit": limit, "items": rows}

    @router.get("/admin/api/v2/catalog/agents/{rid}", dependencies=auth)
    @router.get("/admin/api/agents/{rid}", dependencies=auth)
    def agent(rid: int, request: Request):
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
        if request.url.path.startswith('/admin/api/v2/'):
            return {'item':r,'related':{'health_checks':history},'captured_at':time.time()}
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
                ("newest", "새로 발견된 API", "1=1", "r.first_seen DESC, r.id DESC"),
                ("verified", "실제 검증된 고품질 유료 API", "r.trial_ok=1 AND r.eval_score IS NOT NULL", "r.first_seen DESC, r.eval_score DESC"),
                ("most_paid", "최근 30일 결제자가 가장 많은 API", "r.payers_30d IS NOT NULL", "r.payers_30d DESC, r.first_seen DESC"),
                ("cheapest", "가장 싸게 쓸 수 있는 API", "r.price_usdc > 0 AND r.health_status='healthy'", "r.price_usdc ASC, r.first_seen DESC"),
            ],
            "mcp": [
                ("newest", "새로 등록된 서버", "1=1", "r.first_seen DESC, r.id DESC"),
                ("verified", "실제 호출까지 확인된 고품질 서버", "r.trial_ok=1 AND r.eval_score IS NOT NULL", "r.first_seen DESC, r.eval_score DESC"),
                ("open", "계정 없이 바로 쓰는 서버", "COALESCE(r.auth_observed, r.auth_declared, 1)=0 AND r.eval_grade='A'", "r.first_seen DESC, r.cap_tool_count DESC"),
            ],
            "a2a": [
                ("newest", "새로 발견된 에이전트", "1=1", "r.first_seen DESC, r.id DESC"),
                ("verified", "실제로 대답한 에이전트", "r.trial_ok=1", "r.first_seen DESC, COALESCE(r.eval_score,0) DESC"),
                ("top", "품질 평가가 높은 에이전트", "r.eval_score IS NOT NULL", "r.first_seen DESC, r.eval_score DESC"),
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
            median_rows = getattr(store, 'insight_price_medians', None)
            price_rows = median_rows() if callable(median_rows) else q(
                f"SELECT r.kind, r.price_usdc {base} AND r.price_usdc > 0 ORDER BY r.price_usdc")
            for r in price_rows:
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
    def explore(request: Request, q: str = Query("", max_length=500), kind: str | None = None, category: str | None = None, verified: bool = False,
                no_auth: bool = False, limit: int = Query(30, ge=1, le=100)):
        """에이전트 찾기: 검색어는 이름·설명 전문 검색(관련도순), 없으면 품질·인기순. 서비스 가능한 것만."""
        ip = request.client.host if request.client else "unknown"
        if not explore_limit.allow(ip):
            raise HTTPException(429, "검색 요청 한도를 초과했습니다. 잠시 후 다시 시도해 주세요.")
        q = (q or "").replace("\x00", "").strip()[:500]
        conds, params = [LIVE], []
        if category:
            conds.append("r.category=?"); params.append(category)
        if verified:
            conds.append("r.trial_ok=1")
        if no_auth:
            conds.append("(COALESCE(r.auth_observed, r.auth_declared, 0)=0 OR r.kind='x402')")

        target_kinds = [kind] if kind else ["a2a", "mcp", "x402"]
        terms = query_terms(q, limit=12)

        with reader() as db:
            if len(target_kinds) == 1:
                k_conds = conds + ["r.kind=?"]
                k_params = params + [target_kinds[0]]
                where = " AND ".join(k_conds)
                if terms:
                    match = " OR ".join('"' + t.replace('"', "") + '"' for t in terms)
                    rows = _rows(db.execute(
                        f"""SELECT {CARD_COLS} FROM resources_fts f JOIN resources r ON r.id=f.rowid
                            WHERE resources_fts MATCH ? AND {where}
                            ORDER BY bm25(resources_fts) - COALESCE(r.eval_score, 50) / 100.0 - (r.trial_ok IS 1) * 0.5 LIMIT ?""",
                        (match, *k_params, limit * 5)))
                else:
                    rows = _rows(db.execute(
                        f"""SELECT {CARD_COLS} FROM resources r WHERE {where}
                            ORDER BY r.first_seen DESC, (r.trial_ok IS 1) DESC, COALESCE(r.eval_score, 0) DESC, r.id DESC LIMIT ?""",
                        (*k_params, limit * 5)))
                items = _diverse(rows, limit)
            else:
                by_kind: dict[str, list[dict]] = {}
                for k in target_kinds:
                    k_conds = conds + ["r.kind=?"]
                    k_params = params + [k]
                    where = " AND ".join(k_conds)
                    if terms:
                        match = " OR ".join('"' + t.replace('"', "") + '"' for t in terms)
                        k_rows = _rows(db.execute(
                            f"""SELECT {CARD_COLS} FROM resources_fts f JOIN resources r ON r.id=f.rowid
                                WHERE resources_fts MATCH ? AND {where}
                                ORDER BY bm25(resources_fts) - COALESCE(r.eval_score, 50) / 100.0 - (r.trial_ok IS 1) * 0.5 LIMIT ?""",
                            (match, *k_params, limit * 3)))
                    else:
                        k_rows = _rows(db.execute(
                            f"""SELECT {CARD_COLS} FROM resources r WHERE {where}
                                ORDER BY r.first_seen DESC, (r.trial_ok IS 1) DESC, COALESCE(r.eval_score, 0) DESC, r.id DESC LIMIT ?""",
                            (*k_params, limit * 3)))
                    by_kind[k] = _diverse(k_rows, limit)

                # 라운드로빈 인터리빙으로 a2a, mcp, x402가 균형있게 추천되도록 구성
                interleaved = []
                max_len = max((len(v) for v in by_kind.values()), default=0)
                for i in range(max_len):
                    for k in target_kinds:
                        if i < len(by_kind[k]):
                            interleaved.append(by_kind[k][i])
                            if len(interleaved) >= limit:
                                break
                    if len(interleaved) >= limit:
                        break
                items = interleaved

        return {"query": q, "terms": terms, "items": [_card(r) for r in items]}

    # ---------------- RAG (sqlite-vec 하이브리드 검색 및 로컬 LLM 답변) ----------------
    @router.get("/admin/api/rag/ask", dependencies=auth)
    def rag_ask(request: Request, q: str = Query("", max_length=500), kind: str | None = None, category: str | None = None,
                verified: bool = False, model: str | None = None, limit: int = Query(10, ge=1, le=50)):
        """자연어 질의에 대해 sqlite-vec 밀집 벡터 + FTS5 BM25 하이브리드 RRF 검색 후 로컬 LLM(Gemma) 답변을 생성한다."""
        ip = request.client.host if request.client else "unknown"
        if not rag_limit.allow(ip):
            raise HTTPException(429, "RAG 질의 요청 한도를 초과했습니다. 잠시 후 다시 시도해 주세요.")
        q = (q or "").replace("\x00", "").strip()[:500]
        chosen_model = (model or "").replace("\x00", "").strip()[:50] or rag_engine.generation_model
        if not q:
            return {
                "query": "",
                "answer": "검색할 질문이나 필요한 작업(예: '날씨 조회 무료 API', 'stock forecast mcp')을 입력해 주세요.",
                "model": chosen_model,
                "duration_ms": 0,
                "items": [],
                "total_matches": 0,
            }
        query_descriptor = rag_engine.model_descriptor()
        query_embedding = rag_engine.embed_query(q)
        with reader() as db:
            items = rag_engine.hybrid_search(
                db, query=q, limit=limit, kind=kind, category=category, verified_only=verified,
                query_embedding=query_embedding,
                query_descriptor=query_descriptor,
            )
        ans = rag_engine.generate_rag_answer(query=q, context_items=items, model=chosen_model)
        return {
            "query": q,
            "answer": ans.get("answer", ""),
            "model": ans.get("model", chosen_model),
            "duration_ms": ans.get("duration_ms", 0),
            "items": [_card(r) for r in items],
            "total_matches": len(items),
        }

    @router.get("/admin/api/rag/stats", dependencies=auth)
    def rag_stats():
        """벡터 인덱스 상태, 적재 건수 및 모델 정보."""
        st = vector_stats_data()
        if not st['available']:
            raise HTTPException(503, 'Index statistics temporarily unavailable.',
                                headers={'Cache-Control': 'no-store', 'Retry-After': '5'})
        return {
            'available': True, 'captured_at': st['captured_at'], '_cache': st['_cache'],
            "vector_count": st["vector_count"],
            "outbox_count": st["outbox_count"],
            "total_active": st["active_count"],
            "pct": st["pct"],
            "embed_model": rag_engine.embed_model,
            "generation_model": rag_engine.generation_model,
            "engine": ('PostgreSQL · fenced vector publication · 768-dim cosine'
                       if getattr(store, 'backend', None) == 'postgresql' else 'sqlite-vec · 768-dim cosine'),
        }

    @router.post("/admin/api/rag/index", dependencies=auth)
    def rag_index(request: Request, batch_size: int = Query(100, ge=10, le=1000)):
        """미색인된 리소스들을 배치로 Ollama 임베딩 후 vec_resources에 적재하는 백그라운드 작업."""
        ip = request.client.host if request.client else "unknown"
        if not index_limit.allow(ip):
            raise HTTPException(429, "인덱스 요청 한도를 초과했습니다.")
        pipeline = RagPipeline(rag_engine, batch_size=batch_size)
        def work():
            res = pipeline.step(store)
            st = store.vec_stats(rag_engine.model_descriptor())
            return {"step_result": res, "stats": st}

        return run_background("rag_index", work)

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

    async def legacy_public_body(request):
        from ..workflow_publication_service import read_object
        try:
            return await read_object(request, 160000)
        except (ValueError, TimeoutError):
            raise HTTPException(400, '중복 필드 없는 JSON 객체를 입력하세요.') from None

    def legacy_public_change(request, domain, action, target, fields, body):
        from urllib.parse import unquote
        return request_public_change(request, domain, {'action': action, 'target': target, 'fields': fields,
            'revision': body.get('revision'), 'reason': body.get('reason') or unquote(request.headers.get('x-admin-reason', ''))})

    @router.post("/admin/api/sns/posts", dependencies=auth)
    async def sns_post(request: Request):
        data = await legacy_public_body(request)
        return legacy_public_change(request, 'sns', 'create', None,
            {k: v for k, v in data.items() if k != 'reason'}, data)

    @router.post("/admin/api/sns/like", dependencies=auth)
    async def sns_like(request: Request):
        try:
            data = await request.json()
        except Exception:
            raise HTTPException(400, "유효한 JSON 객체가 필요합니다.")
        if not isinstance(data, dict):
            raise HTTPException(400, "JSON 객체가 필요합니다.")
        return _sns(lambda: sns.toggle_like(store, str(data.get("key", "")), str(data.get("client", ""))))

    @router.post("/admin/api/sns/delete", dependencies=auth)
    async def sns_delete(request: Request):
        data = await legacy_public_body(request)
        return legacy_public_change(request, 'sns', 'delete', data.get('key'), {}, data)

    # ---------------- 방문 에이전트 (에이전트 전용 프론트, AGENT_FRONT.md) ----------------
    @router.get("/admin/api/visitors", dependencies=auth)
    def visitors(q: str | None = Query(None,max_length=200), tier: str | None = Query(None, pattern="^(new|returning|regular)$"),
                 limit: int = Query(100, ge=1, le=500),offset: int=Query(0,ge=0,le=1000000),
                 contact: str=Query('all',pattern='^(all|registered|authorized|marketing|pending|legacy|none)$'),
                 protocol: str=Query('',pattern='^(|any|a2a|mcp|x402)$'),
                 case_state: str=Query('',pattern='^(|new|reviewing|waiting|resolved|archived)$'),
                 source: str=Query('all',pattern='^(all|live|simulation)$')):
        now = time.time()
        with reader() as db:
            stats = db.execute("""SELECT COUNT(*) AS total, SUM(tier='new') AS new, SUM(tier='returning') AS "returning",
                       SUM(tier='regular') AS regular, SUM(visits >= 2) AS came_back, SUM(last_seen > ?) AS active_24h,
                       SUM(first_seen > ?) AS new_24h FROM agent_visitors""", (now - 86400, now - 86400)).fetchone()
            extra = db.execute("""SELECT
                       (SELECT COUNT(*) FROM agent_messages WHERE role='agent' AND at > ?) AS messages_24h,
                       (SELECT COUNT(DISTINCT visitor_id) FROM agent_contacts WHERE status='verified') AS verified_contacts,
                       (SELECT COUNT(*) FROM agent_notifications WHERE status='sent' AND at > ?) AS digests_7d,
                       (SELECT COUNT(*) FROM agent_notifications WHERE kind IN ('welcome_audit', 'health_advisory', 'weekly_intelligence', 'pro_sla_invitation') AND status='sent' AND at > ?) AS nurture_dispatches_7d,
                       (SELECT COUNT(*) FROM agent_hits) AS anonymous_readers,
                       (SELECT COALESCE(SUM(hits), 0) FROM agent_hits) AS anonymous_reads""", (now - 86400, now - 7 * 86400, now - 7 * 86400)).fetchone()
            nurture_stages = {r["stage"] or "onboarded": r["n"] for r in db.execute(
                "SELECT COALESCE(nurture_stage, 'onboarded') AS stage, COUNT(*) AS n FROM agent_visitors GROUP BY nurture_stage")}
            channels = {r["channel"]: r["n"] for r in db.execute("SELECT channel, COUNT(*) AS n FROM agent_visitors GROUP BY channel")}
            watch_stats = dict(db.execute("""SELECT
                SUM(state='active' AND expires>?) AS active_task_watches,
                SUM(state='pending_verification' AND code_expires>?) AS pending_task_watches,
                SUM(state='paused') AS paused_task_watches FROM agent_task_watches""",(now,now)).fetchone())
        llm = front.llm.status() if front is not None and front.llm is not None else None
        clean_front_url = front_url
        if clean_front_url and ":8080" in clean_front_url:
            clean_front_url = clean_front_url.replace(":8080", "")
            if clean_front_url.startswith("http://"):
                clean_front_url = "https://" + clean_front_url[7:]
        desk=VisitorDesk(store,front.updates if front else None).list(q or '',contact,protocol,case_state,offset,limit,tier or '',source)
        return {"stats": {**dict(stats), **dict(extra), **watch_stats, "channels": channels, "nurture_stages": nurture_stages, "nurture_active": extra["verified_contacts"]},
                **desk, "front_url": clean_front_url, "llm": llm}

    @router.post("/admin/api/visitors/simulate", dependencies=auth)
    async def visitor_simulate(request: Request):
        """에이전트 입장에서 대화해 보기: 에이전트 전용 프론트(다른 포트)를 거치지 않고 같은 엔진으로 답한다."""
        require_development_action(request)
        if front is None:
            raise HTTPException(503, "에이전트 프론트가 없습니다.")
        try:
            data = await request.json()
        except Exception:
            raise HTTPException(400, "유효한 JSON 요청이 필요합니다.")
        if not isinstance(data, dict):
            raise HTTPException(400, "JSON 객체가 필요합니다.")
        from ..admin_next import reason_text
        request.state.audit_reason = reason_text(data.get('reason'))
        log_op(request, 'DEV_SIMULATE_INTENT', '개발용 방문 시뮬레이션 요청', status='REQUESTED')
        message = str(data.get("message") or "").replace("\x00", "")[:2000]
        token = data.get("token")
        if token is not None and not isinstance(token, str):
            token = None
        result = front.simulate(message, token, {'protocol':data.get('protocol') or 'auto'})
        log_op(request, 'DEV_SIMULATE', '개발용 방문 시뮬레이션 완료')
        return result

    @router.get("/admin/api/visitors/{vid}", dependencies=auth)
    def visitor(vid: str):
        with reader() as db:
            row = db.execute("SELECT * FROM agent_visitors WHERE id=?", (vid,)).fetchone()
            if row is None:
                raise HTTPException(404, "없는 방문자")
            v = dict(row)
            v.pop("token_hash", None)
            v.pop("last_results", None)
            v.pop("fingerprint", None)
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
            watches = _rows(db.execute("SELECT id,task,protocol,channel,state,created,expires,notice_version,authority FROM agent_task_watches WHERE visitor_id=? ORDER BY created DESC LIMIT 20",(vid,)))
            permissions = _rows(db.execute("SELECT watch_id,action,purpose,notice_version,at FROM agent_task_permissions WHERE visitor_id=? ORDER BY at DESC LIMIT 30",(vid,)))
            task_events = _rows(db.execute("SELECT e.id,e.watch_id,e.created,e.status,e.attempts,e.error FROM agent_task_events e JOIN agent_task_watches w ON w.id=e.watch_id WHERE w.visitor_id=? ORDER BY e.created DESC LIMIT 30",(vid,)))
        for contact in contacts:
            contact['url'] = '[Legacy destination hidden]'
            contact['status'] = 'legacy_unscoped'
            contact['last_error'] = None

        nurture_info = {
            "stage":"task_updates", "stage_label":"작업 알림",
            "recommended_action":"동의된 작업의 검증 변경 확인", "recommended_campaign":"task_update",
            "sent_campaigns":[], "marketing_enabled":False
        }

        return {"visitor": v, "interests": interests, "contacts": contacts, "messages": list(reversed(messages)),
                "notifications": notes, "outcomes": outcomes, "nurture_info": nurture_info,
                "task_watches":watches,"task_permissions":permissions,"task_events":task_events,"marketing_enabled":False,
                **VisitorDesk(store,front.updates if front else None).detail(vid)}

    @router.post('/admin/api/visitors/{vid}/case',dependencies=auth)
    async def visitor_case_save(vid: str,request: Request):
        try:
            data=await request.json()
        except ValueError:
            raise HTTPException(400,'An object is required.')
        if not isinstance(data,dict):
            raise HTTPException(400,'An object is required.')
        try:
            result=VisitorDesk(store).save_case(vid,data,request.state.admin_user['username'])
        except LookupError as exc:
            raise HTTPException(404,str(exc))
        except ValueError as exc:
            raise HTTPException(400,str(exc))
        except RuntimeError as exc:
            raise HTTPException(409,str(exc))
        log_op(request,'VISITOR_CASE_SAVE','개별 방문 에이전트 대응 기록',target=vid,details={'status':data['status']})
        return result

    @router.get('/admin/api/visitors/{vid}/task-updates/{watch_id}/preview',dependencies=auth)
    def visitor_task_preview(vid: str,watch_id: str,request: Request):
        if front is None:
            raise HTTPException(503,'Task updates unavailable.')
        from ..concierge.task_updates import UpdateError
        try:
            return front.updates.preview(vid,watch_id,request.state.admin_user['username'])
        except UpdateError as exc:
            raise HTTPException(404,str(exc))

    @router.post('/admin/api/visitors/{vid}/task-updates/{watch_id}/process',dependencies=auth)
    async def visitor_task_process(vid: str,watch_id: str,request: Request):
        body = await legacy_public_body(request)
        return request_task_change(request, vid, watch_id, body)

    @router.post('/admin/api/visitors/{vid}/task-updates/{watch_id}/action',dependencies=auth)
    async def visitor_task_action(vid: str,watch_id: str,request: Request):
        if front is None:
            raise HTTPException(503,'Task updates unavailable.')
        data=await request.json()
        if not isinstance(data,dict) or data.get('action') not in ('pause','stop','delete','withdraw_marketing'):
            raise HTTPException(400,'Operators may pause, stop or delete; permission must come from the visitor.')
        from ..workspace_admin_public import text as public_reason
        from urllib.parse import unquote
        try:
            request.state.audit_reason = public_reason(data.get('reason') or unquote(request.headers.get('x-admin-reason', '')))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        log_op(request,'VISITOR_PERMISSION_INTENT','연락처 권한 제한 요청',target=vid,status='REQUESTED',details={'watch_id':watch_id,'action':data['action']})
        from ..concierge.task_updates import UpdateError
        try:
            result=front.updates.action(vid,watch_id,data['action'])
            log_op(request,'VISITOR_PERMISSION_ACTION','방문 에이전트 권한 관리',target=vid,details={'watch_id':watch_id,'action':data['action']})
            return result
        except UpdateError as exc:
            raise HTTPException(400,str(exc))

    @router.post("/admin/api/visitors/{vid}/digest", dependencies=auth)
    def visitor_digest(vid: str):
        if front is None:
            raise HTTPException(503, "에이전트 프론트가 없습니다.")
        return {'status':'selection_required','checked':0,'sent':0,'failed':0,'nothing_new':0}

    @router.post("/admin/api/visitors/{vid}/nurture", dependencies=auth)
    async def visitor_nurture(vid: str, request: Request):
        if front is None:
            raise HTTPException(503, "에이전트 프론트가 없습니다.")
        try:
            data = await request.json()
        except Exception:
            data = {}
        campaign = str(data.get("campaign") or "").strip()
        if not campaign:
            campaign = front.digest.determine_campaign(vid)
        res = {'status':'permission_denied','error':'Select and preview an explicitly authorized task update.'}
        return {"ok": res.get("status") == "sent", **res}

    @router.post("/admin/api/visitors/nurture/run", dependencies=auth)
    def visitor_nurture_run():
        if front is None:
            raise HTTPException(503, "에이전트 프론트가 없습니다.")
        raise HTTPException(403,'Bulk manual dispatch is disabled. Review one visitor and task at a time.')

    @router.post("/admin/api/visitors/{vid}/notify", dependencies=auth)
    async def visitor_notify(vid: str, request: Request):
        try:
            data = await request.json()
        except Exception:
            raise HTTPException(400, "유효한 JSON 객체가 필요합니다.")
        if not isinstance(data, dict):
            raise HTTPException(400, "JSON 객체가 필요합니다.")
        if data.get('enabled') is not False:
            raise HTTPException(403,'Only the visitor may authorize task updates.')
        if front is not None:
            front.updates.stop_all(vid)
        with store.tx() as db:
            if not db.execute("UPDATE agent_visitors SET notify=? WHERE id=?", (int(bool(data.get("enabled"))), vid)).rowcount:
                raise HTTPException(404, "없는 방문자")
        return {"notify": bool(data.get("enabled"))}

    @router.get("/admin/api/agent-telemetry", dependencies=auth)
    def agent_telemetry(
        days: int = Query(7, ge=1, le=90),
        source: str = Query("live", pattern="^(all|live|simulation)$"),
    ):
        """Autonomous agent visit funnel, post-visit activity trajectories, and automated AX improvement discovery."""
        from ..concierge.token_hygiene import redact_visitor_tokens

        if front is not None and getattr(front, "book", None) is not None:
            try:
                front.book.flush_hits(timeout=0.4)
            except Exception:
                pass

        now = time.time()
        since = now - days * 86400
        if source == "live":
            src_cond = "COALESCE(v.channel, '') != 'admin-test'"
        elif source == "simulation":
            src_cond = "v.channel = 'admin-test'"
        else:
            src_cond = "1=1"

        def _classify_ua(ua_raw: str | None) -> str:
            u = (ua_raw or "").lower()
            if not u:
                return "Unknown / Empty UA"
            if any(k in u for k in ("claude", "anthropic")):
                return "Claude / Anthropic Agent"
            if any(k in u for k in ("openai", "gpt", "codex", "chatgpt")):
                return "OpenAI / GPT Agent"
            if "mcp" in u or "modelcontextprotocol" in u:
                return "MCP Client"
            if any(k in u for k in ("a2a", "agent2agent")):
                return "A2A Client"
            if any(k in u for k in ("langchain", "langgraph", "crewai", "autogen", "llamaindex", "pydantic")):
                return "Agent Framework (LangChain/CrewAI)"
            if any(k in u for k in ("python-httpx", "httpx", "aiohttp", "python-requests", "urllib", "node-fetch", "axios", "go-http-client")):
                return "Programmatic SDK / HTTP Client"
            if any(k in u for k in ("curl", "wget", "httpie")):
                return "CLI / cURL Probe"
            if any(k in u for k in ("mozilla", "chrome", "safari", "edg", "firefox")):
                return "Browser / Web Inspector"
            return "Custom Autonomous Agent"

        native_telemetry = getattr(store, "agent_telemetry_raw", None)
        if callable(native_telemetry):
            raw_t = native_telemetry(since, now, source)
            hit_summary = raw_t["hit_summary"]
            entry_paths = raw_t["entry_paths"]
            hit_uas = raw_t["hit_uas"]
            v_stats = raw_t["v_stats"]
            channel_rows = raw_t["channel_rows"]
            visitor_uas = raw_t["visitor_uas"]
            msg_rows = raw_t["msg_rows"]
            interest_rows = raw_t["interest_rows"]
            outcome_rows = raw_t["outcome_rows"]
            inertia_rows = raw_t["inertia_rows"]
            watch_visitors = raw_t["watch_visitors"]
            returning_visitor_ids = raw_t["returning_visitor_ids"]
            supply_by_kind = raw_t["supply_by_kind"]
            workflow_count = raw_t["workflow_count"]
            recent_visitors = raw_t["recent_visitors"]
        else:
            with reader() as db:
                # 1. Anonymous discovery & manifest hits (Stage 1)
                hit_summary = dict(db.execute(
                    """SELECT COUNT(*) AS readers,
                              COALESCE(SUM(hits), 0) AS total_reads,
                              COALESCE(SUM(CASE WHEN last_seen >= ? THEN 1 ELSE 0 END), 0) AS readers_period,
                              COALESCE(SUM(CASE WHEN last_seen >= ? THEN hits ELSE 0 END), 0) AS reads_period
                       FROM agent_hits""",
                    (since, since),
                ).fetchone() or {})

                entry_paths = _rows(db.execute(
                    """SELECT COALESCE(NULLIF(last_path, ''), '/') AS path,
                              COUNT(*) AS unique_agents,
                              COALESCE(SUM(hits), 0) AS total_hits,
                              MAX(last_seen) AS last_seen
                       FROM agent_hits
                       WHERE last_seen >= ?
                       GROUP BY COALESCE(NULLIF(last_path, ''), '/')
                       ORDER BY total_hits DESC, unique_agents DESC
                       LIMIT 12""",
                    (since,),
                ))

                hit_uas = _rows(db.execute(
                    "SELECT user_agent, hits FROM agent_hits WHERE last_seen >= ? ORDER BY last_seen DESC LIMIT 500",
                    (since,),
                ))

                # 2. Visitor session & retention stats (Stages 2..5)
                v_stats = dict(db.execute(
                    f"""SELECT COUNT(*) AS total_visitors,
                               COALESCE(SUM(CASE WHEN first_seen >= ? THEN 1 ELSE 0 END), 0) AS new_visitors,
                               COALESCE(SUM(CASE WHEN last_seen >= ? THEN 1 ELSE 0 END), 0) AS active_24h,
                               COALESCE(SUM(CASE WHEN visits >= 2 THEN 1 ELSE 0 END), 0) AS returning_visitors,
                               COALESCE(SUM(CASE WHEN visit_days >= 2 THEN 1 ELSE 0 END), 0) AS multi_day_visitors,
                               COALESCE(SUM(CASE WHEN visits = 1 AND messages <= 1 THEN 1 ELSE 0 END), 0) AS single_turn_bounce,
                               COALESCE(SUM( CASE WHEN tier='regular' THEN 1 ELSE 0 END ), 0) AS tier_regular,
                               COALESCE(SUM( CASE WHEN tier='returning' THEN 1 ELSE 0 END ), 0) AS tier_returning,
                               COALESCE(SUM( CASE WHEN tier='new' THEN 1 ELSE 0 END ), 0) AS tier_new,
                               COALESCE(SUM(messages), 0) AS total_messages
                        FROM agent_visitors v
                        WHERE v.last_seen >= ? AND {src_cond}""",
                    (since, now - 86400, since),
                ).fetchone() or {})

                channel_rows = _rows(db.execute(
                    f"""SELECT COALESCE(NULLIF(v.channel, ''), 'unknown') AS channel,
                               COUNT(*) AS visitors,
                               COALESCE(SUM(v.visits), 0) AS visits,
                               COALESCE(SUM(v.messages), 0) AS messages,
                               COALESCE(SUM(CASE WHEN v.visits >= 2 THEN 1 ELSE 0 END), 0) AS returning_count
                        FROM agent_visitors v
                        WHERE v.last_seen >= ? AND {src_cond}
                        GROUP BY COALESCE(NULLIF(v.channel, ''), 'unknown')
                        ORDER BY visitors DESC""",
                    (since,),
                ))

                visitor_uas = _rows(db.execute(
                    f"SELECT v.user_agent, v.visits FROM agent_visitors v WHERE v.last_seen >= ? AND {src_cond} LIMIT 500",
                    (since,),
                ))

                msg_rows = _rows(db.execute(
                    f"""SELECT m.id, m.visitor_id, m.at, m.role, m.channel, m.text, m.data
                        FROM agent_messages m
                        JOIN agent_visitors v ON v.id = m.visitor_id
                        WHERE m.at >= ? AND {src_cond}
                        ORDER BY m.id DESC
                        LIMIT 1500""",
                    (since,),
                ))

                interest_rows = _rows(db.execute(
                    f"""SELECT i.visitor_id, i.task, i.category, COALESCE(i.kind, 'any') AS protocol,
                               i.recommended, i.best_score, i.updated
                        FROM agent_interests i
                        JOIN agent_visitors v ON v.id = i.visitor_id
                        WHERE i.updated >= ? AND {src_cond}
                        ORDER BY i.updated DESC
                        LIMIT 500""",
                    (since,),
                ))

                outcome_rows = _rows(db.execute(
                    f"""SELECT o.visitor_id, o.resource_id, o.success, o.at,
                               r.name, r.kind, r.category, r.eval_grade AS grade, r.health_status
                        FROM agent_outcomes o
                        LEFT JOIN agent_visitors v ON v.id = o.visitor_id
                        LEFT JOIN resources r ON r.id = o.resource_id
                        WHERE o.at >= ? AND (SUBSTR(o.visitor_id, 1, 11) = '__admin_cb_' OR {src_cond})
                        ORDER BY o.at DESC""",
                    (since,),
                ))

                inertia_rows = _rows(db.execute(
                    """SELECT ti.from_resource_id, ti.from_tool, ti.to_resource_id, ti.to_tool,
                              ti.count, ti.last_transition,
                              r1.name AS from_name, r1.kind AS from_kind, r1.category AS from_category,
                              r2.name AS to_name, r2.kind AS to_kind, r2.category AS to_category
                       FROM tool_inertia ti
                       LEFT JOIN resources r1 ON r1.id = ti.from_resource_id
                       LEFT JOIN resources r2 ON r2.id = ti.to_resource_id
                       ORDER BY ti.count DESC, ti.last_transition DESC
                       LIMIT 15"""
                ))

                watch_visitors = {
                    r["visitor_id"]
                    for r in _rows(db.execute(
                        f"""SELECT DISTINCT w.visitor_id
                            FROM agent_task_watches w
                            JOIN agent_visitors v ON v.id = w.visitor_id
                            WHERE w.state IN ('active', 'pending_verification') AND {src_cond}"""
                    ))
                }
                returning_visitor_ids = {
                    r["id"]
                    for r in _rows(db.execute(
                        f"SELECT v.id FROM agent_visitors v WHERE v.last_seen >= ? AND v.visits >= 2 AND {src_cond}",
                        (since,),
                    ))
                }
                supply_by_kind = {
                    r["kind"]: dict(r)
                    for r in _rows(db.execute(
                        """SELECT kind,
                                  COUNT(*) AS active_total,
                                  COALESCE(SUM(CASE WHEN health_status IN ('healthy', 'reachable') THEN 1 ELSE 0 END), 0) AS healthy_total,
                                  COALESCE(SUM(CASE WHEN COALESCE(trial_ok, 0) = 1 THEN 1 ELSE 0 END), 0) AS verified_total,
                                  COALESCE(SUM(CASE WHEN eval_grade = 'A' THEN 1 ELSE 0 END), 0) AS grade_a_total
                           FROM resources
                           WHERE active = 1 AND COALESCE(eval_security, '') != 'quarantine'
                           GROUP BY kind"""
                    ))
                }
                workflow_count = int((db.execute(
                    "SELECT COUNT(*) AS n FROM agent_workflows WHERE is_active = 1"
                ).fetchone() or {"n": 0})["n"] or 0)
                recent_visitors = _rows(db.execute(
                    f"""SELECT v.id, v.name, v.channel, v.user_agent, v.first_seen, v.last_seen,
                               v.visits, v.visit_days, v.messages, v.tier,
                               (SELECT i.task FROM agent_interests i WHERE i.visitor_id = v.id ORDER BY i.updated DESC LIMIT 1) AS last_task,
                               (SELECT i.kind FROM agent_interests i WHERE i.visitor_id = v.id ORDER BY i.updated DESC LIMIT 1) AS requested_protocol,
                               (SELECT COUNT(*) FROM agent_task_watches w WHERE w.visitor_id = v.id AND w.state = 'active' AND w.expires > ?) AS active_watches,
                               (SELECT COUNT(*) FROM agent_outcomes o WHERE o.visitor_id = v.id AND o.success = 1) AS outcomes_ok,
                               (SELECT COUNT(*) FROM agent_outcomes o WHERE o.visitor_id = v.id AND o.success = 0) AS outcomes_fail
                        FROM agent_visitors v
                        WHERE v.last_seen >= ? AND {src_cond}
                        ORDER BY v.last_seen DESC
                        LIMIT 25""",
                    (now, since),
                ))

        # Combine UA family distribution
        ua_counter: dict[str, dict] = {}
        for r in hit_uas:
            fam = _classify_ua(r.get("user_agent"))
            bucket = ua_counter.setdefault(fam, {"family": fam, "anonymous_reads": 0, "sessions": 0})
            bucket["anonymous_reads"] += int(r.get("hits") or 1)
        for r in visitor_uas:
            fam = _classify_ua(r.get("user_agent"))
            bucket = ua_counter.setdefault(fam, {"family": fam, "anonymous_reads": 0, "sessions": 0})
            bucket["sessions"] += 1
        ua_breakdown = sorted(
            ua_counter.values(),
            key=lambda x: (x["sessions"], x["anonymous_reads"]),
            reverse=True,
        )

        from ..concierge.selection import QualityRecommender, search_terms
        from ..concierge.workflow_discovery import recommend as recommend_workflows, wants_workflow

        _adversarial_re = re.compile(
            r"(?is)(?:<!doctype|<!entity|&xxe;|169\.254\.169\.254|\bdoctype\s+entity\s+xxe\b|\bxxe\s+system\b|<\s*script|\bjavascript\s*:|\bunion\s+(?:all\s+)?select\b|;\s*drop\s+table)"
        )

        def _norm_key(t: str) -> str:
            return " ".join(str(t or "").lower().split())[:120]

        def _terms_key(t: str) -> str:
            return " ".join(search_terms(t))[:120]

        msg_by_id = {r["id"]: r for r in msg_rows}
        intent_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        protocol_stats: dict[str, dict] = {}
        matched_visitors: set[str] = set()
        deep_visitors: set[str] = set()
        unmet_bucket: dict[tuple[str, str], dict] = {}
        matched_task_keys: set[tuple[str, str]] = set()
        matched_term_keys: set[tuple[str, str]] = set()
        visitor_steps: dict[str, list[dict]] = {}
        simulation_visitors = {r['visitor_id'] for r in msg_rows if r.get('channel') == 'admin-test'}

        for r in reversed(msg_rows):
            vid = r["visitor_id"]
            d = _meta(r.get("data")) or {}
            if r["role"] != "concierge":
                continue
            intent = str(d.get("intent") or "chat").strip().lower()
            status = str(d.get("status") or "").strip().lower()
            proto = str(d.get("protocol_filter") or d.get("protocol") or "any").strip().lower() or "any"
            task = redact_visitor_tokens(str(d.get("task") or "").strip())[:160]
            wfs = d.get("workflows") if isinstance(d.get("workflows"), list) else []
            recs = (
                d.get("recommendations")
                if isinstance(d.get("recommendations"), list)
                else (d.get("picks") if isinstance(d.get("picks"), list) else [])
            ) or wfs
            if not task and d.get("request_message_id") in msg_by_id:
                q_row = msg_by_id[d["request_message_id"]]
                task = redact_visitor_tokens(str(q_row.get("text") or "").strip())[:160]

            if not status:
                if intent in ("find", "find_workflow", "more"):
                    status = "matched" if recs else "no_match"
                else:
                    status = "ok"

            intent_counts[intent] = intent_counts.get(intent, 0) + 1
            status_counts[status] = status_counts.get(status, 0) + 1

            if intent in ("find", "find_workflow"):
                p_entry = protocol_stats.setdefault(proto, {"protocol": proto, "queries": 0, "matched": 0, "no_match": 0})
                p_entry["queries"] += 1
                if status in ("matched", "recommended") or len(recs) > 0:
                    p_entry["matched"] += 1
                    matched_visitors.add(vid)
                    if task:
                        nk = _norm_key(task)
                        tk = _terms_key(task)
                        for p_scope in (proto, "any"):
                            matched_task_keys.add((nk, p_scope))
                            if tk:
                                matched_term_keys.add((tk, p_scope))
                else:
                    p_entry["no_match"] += 1
                    if task:
                        key = (_norm_key(task), proto)
                        ub = unmet_bucket.setdefault(key, {
                            "task": task,
                            "protocol": proto,
                            "category": str(d.get("category") or "general"),
                            "occurrences": 0,
                            "last_seen": 0.0,
                            "status_reason": status or "no_match",
                            "sample_visitor_id": vid,
                            "simulation_occurrences": 0,
                        })
                        ub["occurrences"] += 1
                        if r.get('channel') == 'admin-test':
                            ub['simulation_occurrences'] += 1
                        if float(r["at"] or 0) >= ub["last_seen"]:
                            ub["last_seen"] = float(r["at"] or 0)
                            ub["sample_visitor_id"] = vid

            if intent in ("details", "more", "whats_new", "outcome"):
                deep_visitors.add(vid)

            steps = visitor_steps.setdefault(vid, [])
            if len(steps) < 8:
                steps.append({
                    "intent": intent,
                    "status": status,
                    "protocol": proto,
                    "task": task[:80],
                    "rec_count": len(recs),
                    "at": r["at"],
                })

        for ir in interest_rows:
            vid = ir["visitor_id"]
            recs = _meta(ir.get("recommended")) or []
            proto = str(ir.get("protocol") or "any").lower()
            task_clean = redact_visitor_tokens(str(ir.get("task") or "").strip())[:160]
            raw_best = ir.get("best_score")
            best_score = float(raw_best) if raw_best is not None else (1.0 if recs else 0.0)
            if recs and best_score >= 0.25:
                matched_visitors.add(vid)
                if task_clean:
                    nk = _norm_key(task_clean)
                    tk = _terms_key(task_clean)
                    for p_scope in (proto, "any"):
                        matched_task_keys.add((nk, p_scope))
                        if tk:
                            matched_term_keys.add((tk, p_scope))
            elif (not recs or best_score < 0.25) and task_clean:
                key = (_norm_key(task_clean), proto)
                ub = unmet_bucket.setdefault(key, {
                    "task": task_clean,
                    "protocol": proto,
                    "category": str(ir.get("category") or "other"),
                    "occurrences": 0,
                    "last_seen": 0.0,
                    "status_reason": "no_match" if not recs else "low_relevance_score",
                    "sample_visitor_id": vid,
                    "simulation_occurrences": 0,
                })
                ub["occurrences"] += 1
                if vid in simulation_visitors or source == 'simulation':
                    ub['simulation_occurrences'] += 1
                if float(ir["updated"] or 0) >= ub["last_seen"]:
                    ub["last_seen"] = float(ir["updated"] or 0)
                    ub["sample_visitor_id"] = vid

        # Test provenance is a stored server channel, never inferred from task wording.
        adversarial_blocked_count = 0
        synthetic_probe_count = 0
        resolved_historical_count = 0
        filtered_unmet_candidates: list[dict] = []
        for (nk, proto), ub in unmet_bucket.items():
            t_str = ub["task"]
            if _adversarial_re.search(t_str):
                adversarial_blocked_count += ub["occurrences"]
                continue
            simulated = ub.pop('simulation_occurrences', 0)
            synthetic_probe_count += simulated
            ub['occurrences'] -= simulated
            if not ub['occurrences']:
                continue
            if (nk, proto) in matched_task_keys:
                resolved_historical_count += 1
                continue
            filtered_unmet_candidates.append(ub)

        filtered_unmet_candidates.sort(key=lambda x: (x["occurrences"], x["last_seen"]), reverse=True)
        rec_engine = QualityRecommender(store)
        from ..concierge.memory import VisitorBook
        from ..concierge.recommendation_circuit import controls_for, LEGACY_MANUAL_VISITORS
        circuit_excluded_ids = VisitorBook(store).global_failing_resources()
        circuit_controls = controls_for(store)
        unmet_queries: list[dict] = []
        rechecked_queries = 0
        pending_review = 0
        for candidate_index, ub in enumerate(filtered_unmet_candidates):
            if candidate_index >= 20:
                # Keep unassessed demand in the total while bounding catalog work.
                ub['status_reason'] = 'pending_catalog_recheck'
                ub['remediation_hint'] = '기록된 미매칭 요청입니다. 현재 카탈로그 재확인이 필요합니다.'
                unmet_queries.append(ub)
                pending_review += 1
                continue
            rechecked_queries += 1
            t_str = ub["task"]
            proto = ub["protocol"]
            req_kind = proto if proto in ("a2a", "mcp", "x402") else None
            try:
                if wants_workflow(t_str):
                    wf_res = recommend_workflows(store, t_str)
                    if wf_res.get("workflows"):
                        resolved_historical_count += 1
                        continue
                live_matches = rec_engine.search(t_str, kind=req_kind, limit=1, exclude=circuit_excluded_ids)
                if live_matches:
                    resolved_historical_count += 1
                    continue
                if req_kind in ("a2a", "mcp"):
                    alt_matches = rec_engine.search(t_str, kind=None, limit=1, exclude=circuit_excluded_ids)
                    if alt_matches:
                        alt_k = alt_matches[0].get("kind") or "any"
                        ub["alt_protocol"] = alt_k
                        ub["status_reason"] = f"protocol_scope_gap ({alt_k.upper()} 대체 가능)"
                        ub["remediation_hint"] = f"{proto.upper()} 전용 후보 부재 — {alt_k.upper()} 프로토콜에 검증 완료 에이전트 존재 (Cross-Protocol 자동 안내 작동 중)"
            except Exception:
                pass
            if "remediation_hint" not in ub:
                ub["remediation_hint"] = (
                    "복합 도메인 질의 — 워크플로우 템플릿 구성 또는 복합 에이전트 등록 권장"
                    if len(search_terms(t_str)) >= 4
                    else "신규 에이전트 수집 또는 연결 검증 필요"
                )
            unmet_queries.append(ub)

        outcomes_ok = sum(1 for r in outcome_rows if r.get("success") and not str(r.get("visitor_id") or "").startswith("__admin_cb_"))
        outcomes_fail = sum(1 for r in outcome_rows if not r.get("success") and not str(r.get("visitor_id") or "").startswith("__admin_cb_"))
        for r in outcome_rows:
            if not str(r.get("visitor_id") or "").startswith("__admin_cb_"):
                deep_visitors.add(r["visitor_id"])

        failing_map: dict[int, dict] = {}
        for r in outcome_rows:
            if r.get('visitor_id') in LEGACY_MANUAL_VISITORS:
                continue
            rid = int(r["resource_id"])
            entry = failing_map.setdefault(rid, {
                "resource_id": rid,
                "name": r.get("name") or f"Resource #{rid}",
                "kind": r.get("kind") or "unknown",
                "category": r.get("category") or "other",
                "grade": r.get("grade") or "–",
                "health_status": r.get("health_status") or "unknown",
                "fail_count": 0,
                "success_count": 0,
                "last_reported_at": 0.0,
            })
            if r.get("success"):
                entry["success_count"] += 1
            else:
                entry["fail_count"] += 1
            if float(r.get("at") or 0) > entry["last_reported_at"]:
                entry["last_reported_at"] = float(r.get("at") or 0)

        # Manual controls can exist without synthetic outcome rows or recent failures.
        for rid in circuit_excluded_ids:
            if rid not in failing_map:
                resource = store.resource(rid)
                if not resource:
                    continue
                failing_map[rid] = {'resource_id': rid, 'name': resource.get('name') or f'Resource #{rid}',
                    'kind': resource.get('kind'), 'category': resource.get('category'),
                    'grade': resource.get('eval_grade') or '–', 'health_status': resource.get('health_status'),
                    'fail_count': 0, 'success_count': 0,
                    'last_reported_at': circuit_controls.get(str(rid), {}).get('updated_at', 0)}

        failing_agents = sorted(
            [
                {
                    **item,
                    "fail_rate": round(item["fail_count"] / max(1, item["fail_count"] + item["success_count"]) * 100, 1),
                    "circuit_open": item['resource_id'] in circuit_excluded_ids,
                    "circuit_label": (
                        "서킷브레이커 작동 (추천 자동 차단)"
                        if item['resource_id'] in circuit_excluded_ids
                        else "주의 관찰 (임계치 미만)"
                    ),
                }
                for item in failing_map.values()
                if item["fail_count"] > 0 or item['resource_id'] in circuit_excluded_ids
            ],
            key=lambda x: (x["fail_count"], x["last_reported_at"]),
            reverse=True,
        )[:15]
        circuit_open_count = len(circuit_excluded_ids)
        unprotected_failing = [item for item in failing_agents if not item.get("circuit_open")]

        retained_visitors = returning_visitor_ids | watch_visitors

        recent_trajectories = []
        for rv in recent_visitors:
            vid = rv["id"]
            recent_trajectories.append({
                "visitor_id": vid,
                "name": rv.get("name") or "(익명 에이전트)",
                "channel": rv.get("channel") or "rest",
                "ua_family": _classify_ua(rv.get("user_agent")),
                "user_agent": redact_visitor_tokens((rv.get("user_agent") or "")[:140]),
                "tier": rv.get("tier") or "new",
                "visits": int(rv.get("visits") or 1),
                "visit_days": int(rv.get("visit_days") or 1),
                "messages": int(rv.get("messages") or 0),
                "first_seen": rv.get("first_seen"),
                "last_seen": rv.get("last_seen"),
                "last_task": redact_visitor_tokens(str(rv.get("last_task") or "")[:140]),
                "requested_protocol": rv.get("requested_protocol") or "any",
                "active_watches": int(rv.get("active_watches") or 0),
                "outcomes_ok": int(rv.get("outcomes_ok") or 0),
                "outcomes_fail": int(rv.get("outcomes_fail") or 0),
                "steps": visitor_steps.get(vid, []),
            })

        # Build 5-stage Experience Funnel
        total_v = int(v_stats.get("total_visitors") or 0)
        anon_readers = int(hit_summary.get("readers_period") or 0)
        stage1_count = max(anon_readers + total_v, total_v)
        stage2_count = total_v
        stage3_count = len(matched_visitors)
        stage4_count = len(deep_visitors)
        stage5_count = len(retained_visitors)

        def _pct(num: int, den: int) -> float:
            return round((num / den) * 100.0, 1) if den > 0 else 0.0

        funnel = [
            {
                "stage": 1,
                "key": "discovery_entry",
                "label": "1단계: 디스커버리 매니페스트·문서 진입",
                "count": stage1_count,
                "rate_from_prev": 100.0,
                "rate_from_entry": 100.0,
                "dropoff": max(0, stage1_count - stage2_count),
                "desc": "익명 문서 조회(/llms.txt, /skill.md, /.well-known/*) 및 초기 접속 에이전트",
            },
            {
                "stage": 2,
                "key": "session_created",
                "label": "2단계: 에이전트 세션 수립 및 대화/호출 진입",
                "count": stage2_count,
                "rate_from_prev": _pct(stage2_count, stage1_count),
                "rate_from_entry": _pct(stage2_count, stage1_count),
                "dropoff": max(0, stage2_count - stage3_count),
                "desc": "X-Visitor-Token 발급 및 MCP / A2A / REST 채널을 통한 목적 질의 시작",
            },
            {
                "stage": 3,
                "key": "task_matched",
                "label": "3단계: 적격 에이전트·워크플로우 매칭 성공",
                "count": stage3_count,
                "rate_from_prev": _pct(stage3_count, stage2_count),
                "rate_from_entry": _pct(stage3_count, stage1_count),
                "dropoff": max(0, stage3_count - stage4_count),
                "desc": "24시간 내 성공 검증·활동 확인 기준 상위 에이전트 또는 워크플로우 추천 획득",
            },
            {
                "stage": 4,
                "key": "deep_inspection_or_outcome",
                "label": "4단계: 심층 규격 탐색 및 실행 피드백(Self-Reflection)",
                "count": stage4_count,
                "rate_from_prev": _pct(stage4_count, stage3_count),
                "rate_from_entry": _pct(stage4_count, stage1_count),
                "dropoff": max(0, stage4_count - stage5_count),
                "desc": "details/more/what's new 후속 탐색 또는 실행 성공·실패(report) 피드백 기록",
            },
            {
                "stage": 5,
                "key": "retained_agent",
                "label": "5단계: 재방문(Resume) 및 작업 알림 구독 안착",
                "count": stage5_count,
                "rate_from_prev": _pct(stage5_count, stage4_count if stage4_count > 0 else stage2_count),
                "rate_from_entry": _pct(stage5_count, stage1_count),
                "dropoff": 0,
                "desc": "2회 이상 재방문(visits>=2), /api/agent/v1/resume 점검 또는 작업 알림(Watch) 활성화",
            },
        ]

        total_find_queries = sum(p["queries"] for p in protocol_stats.values())
        total_matched_queries = sum(p["matched"] for p in protocol_stats.values())
        query_match_rate = _pct(total_matched_queries, total_find_queries)
        revisit_rate = _pct(int(v_stats.get("returning_visitors") or 0), total_v)
        bounce_count = int(v_stats.get("single_turn_bounce") or 0)
        bounce_rate = _pct(bounce_count, total_v)
        filtered_noise_total = adversarial_blocked_count + synthetic_probe_count

        # 9. Synthesize Actionable AX Improvements (자동 발견된 자율형 에이전트 개선사항)
        improvements = []

        if unmet_queries:
            top_unmet = unmet_queries[:3]
            sample_tasks = ", ".join(f"'{u['task'][:40]}' ({u['protocol'].upper()})" for u in top_unmet)
            noise_note = (
                f" · 보안·시뮬레이션 기록 {filtered_noise_total}건 제외 · 현재 후보 확인 {resolved_historical_count}유형 별도 집계"
                if filtered_noise_total > 0 or resolved_historical_count > 0
                else ""
            )
            improvements.append({
                "id": "unmet_capability_gap",
                "priority": "high",
                "category": "catalog_gap",
                "category_label": "카탈로그 공백 보강",
                "title": f"미해결 에이전트 탐색 질의 {len(unmet_queries)}건 감지 (복합 도메인·프로토콜 공백)",
                "finding": (
                    f"방문한 자율형 에이전트가 요청한 작업 중 {sample_tasks} 등 {sum(u['occurrences'] for u in unmet_queries)}회의 질의에서 "
                    f"미매칭이 기록됐습니다. 현재 카탈로그 재확인 대기는 {pending_review}유형입니다.{noise_note}"
                ),
                "evidence": f"최근 기록 내 탐색 매칭률 {query_match_rate}% · 미해결·재확인 대상 {len(unmet_queries)}유형 · 표 최대 15유형 · 업무 실행 성공은 별도 검증",
                "recommendation": (
                    "동의어 확장(currency/forex, resume/CV, hotel/accommodation) 및 프로토콜 간 자동 대안 안내(Cross-Protocol Recovery Hint)가 활성화되었습니다. "
                    "남은 복합 도메인 질의(항공+호텔 통합 등)는 '워크플로우'에서 다중 에이전트 템플릿으로 조합하거나 신규 전문 에이전트를 등록하세요."
                ),
                "action_tab": "register",
                "action_label": "신규 에이전트 등록하기",
                "secondary_tab": "workflows",
                "secondary_label": "복합 워크플로우 구성",
                "sample_query": top_unmet[0]["task"][:60],
            })

        if failing_agents:
            top_fail = failing_agents[:3]
            fail_names = ", ".join(
                f"{a['name']} (#{a['resource_id']}, 실패 {a['fail_count']}건{' · 차단됨' if a.get('circuit_open') else ''})"
                for a in top_fail
            )
            improvements.append({
                "id": "runtime_failing_agents",
                "priority": "high" if unprotected_failing else "medium",
                "category": "reliability_fix",
                "category_label": "런타임 신뢰성 · 서킷브레이커",
                "title": (
                    f"실행 실패 보고 에이전트 {len(failing_agents)}개 감지 "
                    f"(서킷브레이커 자동 차단 {circuit_open_count}개 · 주의 관찰 {len(unprotected_failing)}개)"
                ),
                "finding": (
                    f"자율형 에이전트 Self-Reflection(report/failed) 피드백 분석 결과: {fail_names}. "
                    f"반복 실패 임계치(3회 이상 & 실패율 >66.7%)에 도달한 {circuit_open_count}개 에이전트는 크라우드소싱 런타임 서킷브레이커에 의해 신규 방문자 추천에서 자동 제외되었습니다."
                ),
                "evidence": (
                    f"실행 피드백 총 {outcomes_ok + outcomes_fail}건 중 실패 {outcomes_fail}건 · "
                    f"자동 격리(Circuit Open) {circuit_open_count}개 · 관찰 중 {len(unprotected_failing)}개"
                ),
                "recommendation": (
                    "하단 '런타임 실패 보고 에이전트' 표에서 개별 에이전트의 서킷브레이커를 즉시 수동 차단(Trip)하거나, "
                    "'에이전트 테스트'에서 정상화 확인 후 서킷을 해제(Reset)할 수 있습니다."
                ),
                "action_tab": "test",
                "action_label": "에이전트 테스트벤치 열기",
                "secondary_tab": "agents",
                "secondary_label": "에이전트 상태 관리",
                "target_resource_id": top_fail[0]["resource_id"],
            })

        if inertia_rows:
            top_chain = inertia_rows[0]
            chain_desc = f"{top_chain.get('from_name') or '#' + str(top_chain['from_resource_id'])} ({top_chain['from_tool']}) → {top_chain.get('to_name') or '#' + str(top_chain['to_resource_id'])} ({top_chain['to_tool']})"
            improvements.append({
                "id": "inertia_workflow_synthesis",
                "priority": "medium",
                "category": "workflow_opportunity",
                "category_label": "워크플로우 자동화 기회",
                "title": f"자율형 에이전트 반복 연쇄 도구 호출 패턴 {len(inertia_rows)}종 발견",
                "finding": f"방문 에이전트들이 단일 호출에 그치지 않고 '{chain_desc}' 순으로 총 {top_chain['count']}회 연쇄 호출(Tool Inertia)하고 있습니다.",
                "evidence": f"기록된 도구 전이 경로 {len(inertia_rows)}개 · 현재 활성 워크플로우 템플릿 {workflow_count}개",
                "recommendation": "자율형 에이전트가 매번 개별 도구를 수동으로 조합하지 않도록, 상위 연쇄 호출 경로를 공식 '워크플로우 템플릿'으로 승격·발행하여 원클릭 파이프라인으로 제공하세요.",
                "action_tab": "workflows",
                "action_label": "워크플로우 템플릿 관리",
                "secondary_tab": "explore",
                "secondary_label": "연관 에이전트 보기",
            })

        if bounce_count > 0 or (anon_readers > 0 and total_v < anon_readers):
            improvements.append({
                "id": "retention_and_entry_conversion",
                "priority": "medium" if bounce_rate >= 40.0 else "low",
                "category": "retention_loop",
                "category_label": "재방문·정착률 최적화",
                "title": f"단발성 방문 비율 {bounce_rate}% ({bounce_count}/{total_v}명) · 다회차 유도(Continuation Plan) 가동 중",
                "finding": (
                    f"익명 매니페스트(/llms.txt, /skill.md 등) 조회 지문 {anon_readers}개 대비 활성 세션 {total_v}명이 생성되었으며, "
                    f"재방문율(2회 이상)은 {revisit_rate}%입니다. 1턴 추천 응답에 기계 판독형 다회차 행동 계획(continuation_plan: details 1, more, report, /api/agent/v1/resume)과 영문 글로벌 우선 랭킹이 적용되었습니다."
                ),
                "evidence": f"1회 후 이탈 {bounce_count}명 · 재방문 에이전트 {v_stats.get('returning_visitors') or 0}명 · 활성 작업 알림 {len(watch_visitors)}명",
                "recommendation": "단발 방문 에이전트의 최근 관심 작업을 확인하고, 목적별 작업 알림(Task Updates) 수신 권한 안내 및 /skill.md 부트스트랩 규칙 배포 상태를 점검하세요.",
                "action_tab": "visitors",
                "action_label": "방문 에이전트 개별 검토",
                "secondary_tab": "learn",
                "secondary_label": "프로토콜 가이드 확인",
            })

        # Check protocol verification balance
        low_verified_protos = [
            k.upper()
            for k in ("a2a", "mcp", "x402")
            if int((supply_by_kind.get(k) or {}).get("verified_total") or 0) < 3
        ]
        if low_verified_protos:
            improvements.append({
                "id": "protocol_verification_coverage",
                "priority": "medium",
                "category": "catalog_gap",
                "category_label": "프로토콜 검증 풀 확충",
                "title": f"{', '.join(low_verified_protos)} 프로토콜의 검증 완료(Verified) 후보 풀 보강 필요",
                "finding": f"자율형 에이전트는 최근 성공 검증(Verified) 및 활동이 확인된 에이전트를 최우선 추천받습니다. 현재 {', '.join(low_verified_protos)} 프로토콜의 검증 완료 리소스 수가 적어 추천 다양성이 제한될 수 있습니다.",
                "evidence": " · ".join(
                    f"{k.upper()}: 활성 {(supply_by_kind.get(k) or {}).get('active_total', 0)}개 중 검증 {(supply_by_kind.get(k) or {}).get('verified_total', 0)}개"
                    for k in ("a2a", "mcp", "x402")
                ),
                "recommendation": "'에이전트 테스트' 및 '테스트 결과' 메뉴에서 상위 등급 에이전트에 대한 실호출 검증 보고서를 생성하여 자율형 에이전트 추천 적격 풀을 확대하세요.",
                "action_tab": "test_reports",
                "action_label": "테스트 결과·검증 관리",
                "secondary_tab": "test",
                "secondary_label": "실호출 검증 실행",
            })

        if not improvements:
            improvements.append({
                "id": "healthy_autonomous_ecosystem",
                "priority": "low",
                "category": "healthy",
                "category_label": "정상 운영",
                "title": "자율형 에이전트 탐색·매칭·실행 지표가 안정적으로 유지되고 있습니다",
                "finding": "선택한 기간 동안 미해결 질의나 런타임 실패 급증 없이 자율형 에이전트 세션이 원활하게 처리되었습니다.",
                "evidence": f"탐색 매칭률 {query_match_rate}% · 재방문율 {revisit_rate}%",
                "recommendation": "지속적인 품질 유지를 위해 주간 인기 탐색 카테고리와 신규 등록 에이전트의 검증 상태를 정기 모니터링하세요.",
                "action_tab": "visitors",
                "action_label": "방문 에이전트 목록 보기",
            })

        return {
            "period_days": days,
            "source": source,
            "generated_at": now,
            "kpis": {
                "anonymous_readers": anon_readers,
                "anonymous_reads": int(hit_summary.get("reads_period") or 0),
                "total_visitors": total_v,
                "new_visitors": int(v_stats.get("new_visitors") or 0),
                "active_24h": int(v_stats.get("active_24h") or 0),
                "returning_visitors": int(v_stats.get("returning_visitors") or 0),
                "revisit_rate": revisit_rate,
                "bounce_rate": bounce_rate,
                "total_messages": int(v_stats.get("total_messages") or 0),
                "query_match_rate": query_match_rate,
                "total_find_queries": total_find_queries,
                "unmet_query_count": len(unmet_queries),
                "unmet_queries_displayed": min(15, len(unmet_queries)),
                "unmet_queries_rechecked": rechecked_queries,
                "unmet_queries_pending_review": pending_review,
                "catalog_matched_historical_count": resolved_historical_count,
                "unmet_scope": "bounded_recent_records",
                "filtered_noise_queries": filtered_noise_total,
                "adversarial_blocked_count": adversarial_blocked_count,
                "synthetic_probe_count": synthetic_probe_count,
                "resolved_historical_count": resolved_historical_count,
                "outcomes_ok": outcomes_ok,
                "outcomes_fail": outcomes_fail,
                "circuit_open_count": circuit_open_count,
                "active_watches": len(watch_visitors),
                "improvement_count": len([i for i in improvements if i["category"] != "healthy"]),
            },
            "funnel": funnel,
            "entry_paths": entry_paths,
            "ua_breakdown": ua_breakdown,
            "channels": channel_rows,
            "intents": [
                {"intent": k, "count": v}
                for k, v in sorted(intent_counts.items(), key=lambda x: x[1], reverse=True)
            ],
            "statuses": [
                {"status": k, "count": v}
                for k, v in sorted(status_counts.items(), key=lambda x: x[1], reverse=True)
            ],
            "protocols": sorted(protocol_stats.values(), key=lambda x: x["queries"], reverse=True),
            "supply_by_kind": supply_by_kind,
            "improvements": improvements,
            "unmet_queries": unmet_queries[:15],
            "failing_agents": failing_agents,
            "inertia_chains": inertia_rows,
            "recent_trajectories": recent_trajectories,
        }

    @router.post("/admin/api/agent-telemetry/remediate", dependencies=auth)
    async def remediate_agent_telemetry(request: Request):
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "Invalid JSON payload")
        if not isinstance(body, dict):
            raise HTTPException(400, "JSON object required")
        action = str(body.get("action") or "").strip()
        if action not in ("trip_circuit", "reset_circuit", "resolve_unmet"):
            raise HTTPException(400, "Unsupported action")
        now = time.time()
        rid = body.get("resource_id")
        rid_text = str(rid)
        rid_int = (int(rid_text) if type(rid) in (int, str) and rid_text.isascii()
                   and rid_text.isdecimal() and len(rid_text) <= 19 else None)
        task_str = str(body.get("task") or "").strip()[:300]
        task_norm = " ".join(task_str.lower().split())[:200] if task_str else None
        proto = str(body.get("protocol") or "any").strip().lower()
        if proto not in ('any', 'a2a', 'mcp', 'x402'):
            raise HTTPException(400, 'Unsupported protocol')
        req_kind = proto if proto in ("a2a", "mcp", "x402") else None
        if action in ('trip_circuit', 'reset_circuit'):
            if rid_int is None or not 0 < rid_int < 2**63 or not store.resource(rid_int):
                raise HTTPException(400, 'Existing resource_id required')

        rec_json = None
        best_score = None
        if action == "resolve_unmet" and task_str:
            from ..concierge.selection import QualityRecommender
            from ..concierge.memory import VisitorBook
            matches = QualityRecommender(store).search(task_str, kind=req_kind, limit=3,
                                                       exclude=VisitorBook(store).global_failing_resources())
            if matches:
                rec_json = json.dumps([
                    {
                        "id": m.get("id"),
                        "score": m.get("score") if m.get("score") is not None else m.get("quality_score"),
                        "grade": m.get("grade"),
                        "verified": m.get("verified_working"),
                    }
                    for m in matches
                ])
                scores = [
                    float(s)
                    for m in matches
                    if (s := (m.get("score") if m.get("score") is not None else m.get("quality_score"))) is not None
                ]
                best_score = max(scores, default=1.0)
        if action == 'resolve_unmet' and not rec_json:
            raise HTTPException(409, 'No current catalog match; demand remains unresolved')

        if hasattr(store, "remediate_agent_telemetry"):
            res = store.remediate_agent_telemetry(
                action,
                resource_id=rid_int,
                task_norm=task_norm,
                recommended_json=rec_json,
                best_score=best_score,
                protocol=proto,
                now=now,
            )
            if not res.get("ok"):
                raise HTTPException(400, res.get("error") or "Remediation failed")
            log_op(request, 'AGENT_TELEMETRY_REMEDIATE', '에이전트 추천 상태 조정',
                   target=str(rid_int or ''), details={'action': action, 'history_preserved': True})
            return res

        if action in ('trip_circuit', 'reset_circuit'):
            from ..concierge.recommendation_circuit import remediate_sqlite
            res = remediate_sqlite(store, rid_int, action, now)
            log_op(request, 'AGENT_TELEMETRY_REMEDIATE', '에이전트 추천 상태 조정',
                   target=str(rid_int), details={'action': action, 'history_preserved': True})
            return res

        with store.tx() as db:
            if action == "resolve_unmet" and task_norm:
                if rec_json and best_score is not None:
                    cur = db.execute(
                        """UPDATE agent_interests
                           SET recommended = ?, best_score = MAX(COALESCE(best_score, 0), ?), last_checked = ?
                           WHERE task_norm = ? AND COALESCE(kind,'any') = ?
                             AND (recommended = '[]' OR best_score IS NULL)""",
                        (rec_json, best_score, now, task_norm, proto),
                    )
                return {"ok": True, "action": action, "task_norm": task_norm, "updated": int(cur.rowcount or 0),
                        'status': 'catalog_match_found', 'execution_verified': False}
        raise HTTPException(400, "Invalid remediation parameters")

    # ---------------- SSL/TLS 인증서 & 443 포트 관리 (매년 자동 갱신) ----------------
    @router.get("/admin/api/ssl", dependencies=auth)
    def ssl_status():
        mgr = ssl_manager or get_ssl_manager()
        return mgr.get_status()

    @router.post("/admin/api/ssl/renew", dependencies=auth)
    def ssl_renew(request: Request, days: int = Query(365, ge=1, le=1095)):
        if os.environ.get("DEPLOYMENT_MODE") == "production":
            raise HTTPException(403, "Production certificates must be renewed through the configured TLS provider.")
        mgr = ssl_manager or get_ssl_manager()
        res = mgr.renew_certificate(days=days)
        log_op(request, "SSL_RENEW", "개발 인증서 갱신", details={"days":days})
        return {
            "ok": True,
            "message": f"OpenSSL certificate renewed successfully for {days} days (valid until {res.get('expires_at_iso')}).",
            "details": res,
        }

    # ---------------- Explore 검색 문서 적재 현황 ----------------
    @router.get("/admin/api/explore-documents/status", dependencies=auth)
    def explore_documents_status(response: Response):
        """검색 문서 적재 진행(건수만). 미룸·보류가 늘면 적재 정체를 의심한다."""
        response.headers["Cache-Control"] = "private, no-store"
        if getattr(store, "backend", None) != "postgresql":
            return {"installed": False}
        from ..explore_document_refresher import load_status
        return load_status(store)

    # ---------------- 접속자 보안 & DDoS 방어 관리 (443 포트) ----------------
    @router.get("/admin/api/security/status", dependencies=auth)
    def security_status():
        sec = getattr(front, "security", None) or SecurityManager(store)
        return sec.get_status()

    @router.get("/admin/api/security/rules", dependencies=auth)
    def security_rules(action: str | None = Query(None, pattern="^(block|allow)$"),
                       limit: int = Query(100, ge=1, le=500)):
        sec = getattr(front, "security", None) or SecurityManager(store)
        return {"rules": sec.get_rules(action=action, limit=limit)}

    @router.post("/admin/api/security/rules", dependencies=auth)
    async def security_add_rule(request: Request):
        data = await legacy_public_body(request)
        return legacy_public_change(request, 'security', data.get('action', 'block'), data.get('ip'),
                                    {'duration': data.get('duration')}, data)

    @router.delete("/admin/api/security/rules/{ip}", dependencies=auth)
    def security_remove_rule(ip: str, request: Request):
        return legacy_public_change(request, 'security', 'remove', ip, {}, {})

    @router.post("/admin/api/security/under-attack", dependencies=auth)
    async def security_toggle_under_attack(request: Request):
        data = await legacy_public_body(request)
        return legacy_public_change(request, 'security', 'under_attack', 'defense', {'enabled': data.get('enabled')}, data)

    @router.post("/admin/api/security/rate-multiplier", dependencies=auth)
    async def security_set_multiplier(request: Request):
        data = await legacy_public_body(request)
        return legacy_public_change(request, 'security', 'rate', 'defense', {'multiplier': data.get('multiplier')}, data)

    @router.get("/admin/api/security/events", dependencies=auth)
    def security_events(event_type: str | None = None, ip: str | None = None,
                        limit: int = Query(100, ge=1, le=500)):
        sec = getattr(front, "security", None) or SecurityManager(store)
        return {"events": sec.get_events(event_type=event_type, ip=ip, limit=limit)}

    @router.post("/admin/api/security/clear-expired", dependencies=auth)
    def security_clear_expired(request: Request):
        from ..workspace_admin_public import text as public_reason
        from urllib.parse import unquote
        try:
            request.state.audit_reason=public_reason(unquote(request.headers.get('x-admin-reason','')))
        except ValueError as exc:
            raise HTTPException(400,str(exc)) from None
        log_op(request,'SECURITY_EXPIRED_CLEANUP','만료된 규칙 정리 요청',status='REQUESTED')
        sec = getattr(front, "security", None) or SecurityManager(store)
        cleared = sec.clear_expired_rules()
        return {"cleared": cleared}

    # ---------------- 고객 요청 및 문의/권리 행사 허브 ----------------
    @router.get("/admin/api/needs/notifications", dependencies=auth)
    def notification_preferences(q: str = Query('', max_length=160),
            state: str = Query('all', pattern='^(all|active|paused|pending_verification|revoked|expired|failed)$'),
            channel: str = Query('all', pattern='^(all|poll|browser|webhook|a2a)$'),
            limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
        from .notification_preferences import NotificationPreferences
        return NotificationPreferences(store,getattr(front,'updates',None)).list(q,state,channel,limit,offset)

    @router.get("/admin/api/needs/notifications/{watch_id}", dependencies=auth)
    def notification_preference_detail(watch_id: str):
        from .notification_preferences import NotificationPreferences
        if not re.fullmatch(r'tw_[0-9a-f]{32}',watch_id):
            raise HTTPException(404, "알림 설정을 찾을 수 없습니다.")
        try:
            return NotificationPreferences(store,getattr(front,'updates',None)).detail(watch_id)
        except LookupError:
            raise HTTPException(404, "알림 설정이 삭제되었거나 존재하지 않습니다.")

    @router.get("/admin/api/needs/summary", dependencies=auth)
    def needs_summary():
        return store.get_customer_requests_summary()

    @router.get("/admin/api/needs", dependencies=auth)
    def needs(status: str | None = None, category: str | None = None, q: str | None = None,
              limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
        conds = []
        params = []
        if status and status != "all":
            conds.append("n.status = ?")
            params.append(status)
        if category and category != "all":
            conds.append("n.category = ?")
            params.append(category)
        if q:
            kw = f"%{q.strip()}%"
            conds.append("(n.task LIKE ? OR n.client LIKE ? OR r.name LIKE ?)")
            params.extend([kw, kw, kw])
        where_clause = ("WHERE " + " AND ".join(conds)) if conds else ""

        with reader() as db:
            count_query = f"SELECT COUNT(*) AS total FROM needs n LEFT JOIN resources r ON r.id=n.current_resource {where_clause}"
            total = db.execute(count_query, params).fetchone()["total"]

            data_query = f"""SELECT n.need_id, n.client, n.task, n.category, n.status, n.created, n.updated, n.rescanned_at,
                                    n.current_score, n.max_price, n.networks, n.kinds,
                                    r.id AS current_resource_id, r.name AS current_name, r.url AS current_url, r.kind AS current_kind,
                                    (SELECT COUNT(*) FROM offers o WHERE o.need_id=n.need_id) AS offers
                             FROM needs n LEFT JOIN resources r ON r.id=n.current_resource
                             {where_clause}
                             ORDER BY n.created DESC LIMIT ? OFFSET ?"""
            rows = _rows(db.execute(data_query, params + [limit, offset]))
        return {"items": rows, "total": total}

    @router.get("/admin/api/needs/{need_id}/offers", dependencies=auth)
    def need_offers(need_id: str):
        with reader() as db:
            rows = _rows(db.execute(
                """SELECT o.offer_id, o.need_id, o.resource_id, o.score, o.teaser, o.fee, o.free, o.status, o.created,
                          r.name AS resource_name, r.url AS resource_url, r.kind AS resource_kind, r.category AS resource_cat
                   FROM offers o LEFT JOIN resources r ON r.id=o.resource_id
                   WHERE o.need_id = ? ORDER BY o.score DESC""", (need_id,)))
        return {"items": rows}

    INQUIRY_STATUSES = ("pending", "in_progress", "resolved", "archived")

    @router.get("/admin/api/needs/inquiries", dependencies=auth)
    def needs_inquiries(status: str | None = None, category: str | None = None, q: str | None = None,
                        limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
        rows, total = store.list_customer_inquiries(status=status, category=category, search=q, limit=limit, offset=offset)
        return {"items": rows, "total": total}

    @router.patch("/admin/api/needs/inquiries/{inquiry_id}", dependencies=auth)
    async def update_inquiry(request: Request, inquiry_id: str):
        body = await request.json()
        status = body.get("status")
        admin_response = sanitize_text(body.get("admin_response"), max_length=4000) if body.get("admin_response") is not None else None
        # The guard stores the individual staff account as admin_user; record who handled the inquiry.
        user = (getattr(request.state, "admin_user", None) or {}).get("username") or "admin"
        if status not in INQUIRY_STATUSES:
            raise HTTPException(422, "상태값은 pending, in_progress, resolved, archived 중 하나입니다.")
        ok = store.update_customer_inquiry(inquiry_id, status=status, admin_response=admin_response, resolved_by=str(user))
        if not ok:
            raise HTTPException(404, "문의 내역을 찾을 수 없습니다.")
        log_op(request, "INQUIRY_UPDATE", "고객 문의 처리", target=inquiry_id, details={"status": status, "responded": admin_response is not None})
        return {"ok": True, "inquiry_id": inquiry_id, "status": status}

    @router.get("/admin/api/needs/cancellations", dependencies=auth)
    def needs_cancellations(status: str | None = None, q: str | None = None,
                            limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
        rows, total = store.list_cancellation_requests(status=status, search=q, limit=limit, offset=offset)
        return {"items": rows, "total": total}

    @router.post("/admin/api/needs/cancellations/{request_id}/reactivate", dependencies=auth)
    async def reactivate_cancellation(request: Request, request_id: str):
        raise HTTPException(409, "연락처 재활성화는 고객이 새로 신청하고 주소를 확인해야 합니다. 관리자 메모로 동의를 복구할 수 없습니다.")

    @router.get("/admin/api/needs/privacy", dependencies=auth)
    def needs_privacy(status: str | None = None, request_type: str | None = None, q: str | None = None,
                      limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
        rows, total = store.list_privacy_requests(status=status, request_type=request_type, search=q, limit=limit, offset=offset)
        return {"items": rows, "total": total}

    @router.patch("/admin/api/needs/privacy/{request_id}", dependencies=auth)
    async def update_privacy(request: Request, request_id: str):
        from ..privacy_requests import parse_request
        try:
            body = parse_request(await request.body())
        except (ValueError, RecursionError) as exc:
            raise HTTPException(422, "A JSON review is required.") from exc
        if type(body) is not dict or set(body) - {'status', 'notes', 'proof_hash'}:
            raise HTTPException(422, "Invalid privacy review fields.")
        status = body.get("status")
        notes = body.get("notes")
        proof_hash = body.get("proof_hash")
        if not status:
            raise HTTPException(422, "상태값이 필요합니다.")
        try:
            ok = store.update_privacy_request(request_id, status=status, notes=notes, proof_hash=proof_hash)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if not ok:
            raise HTTPException(404, "개인정보 처리 요청을 찾을 수 없습니다.")
        log_op(request, "PRIVACY_UPDATE", "개인정보 요청 처리", target=request_id, details={"status": status, "proof": bool(proof_hash)})
        return {"ok": True, "request_id": request_id, "status": status}

    # ---------------- 관리 작업 ----------------
    def run_background(name: str, fn, payload=None) -> dict:
        control = getattr(store, '_service_control', None)
        if control is not None:
            return control.enqueue(name, payload)
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
    def crawl_now(request: Request, force_full: bool = Query(False)):
        if crawler is None:
            raise HTTPException(503, "수집기가 없습니다.")
        mode_desc = "전체 동기화(Full)" if force_full else "증분 수집(Incremental)"
        log_op(request, "CRAWL_RUN", f"수집기 실행 ({mode_desc})")
        return run_background("crawl", lambda: crawler.crawl_all(force_full=force_full), {'force_full': force_full})

    @router.post("/admin/api/actions/rescan", dependencies=auth)
    def rescan_now(request: Request):
        if service is None:
            raise HTTPException(503, "게이트웨이 서비스가 없습니다.")
        log_op(request, "RESCAN_RUN", "게이트웨이 에이전트 재검색 실행")
        return run_background("rescan", service.rescan)

    @router.post("/admin/api/actions/pause", dependencies=auth)
    def pause(request: Request):
        if getattr(store, '_service_control', None) is not None:
            log_op(request, "COLLECTOR_PAUSE", "Collector pause requested")
            return store._service_control.enqueue('pause')
        if collector is None:
            raise HTTPException(503, "수집기가 없습니다.")
        collector.pause()
        log_op(request, "COLLECTOR_PAUSE", "수집기 일시 정지")
        return {"paused": True}

    @router.post("/admin/api/actions/resume", dependencies=auth)
    def resume(request: Request):
        if getattr(store, '_service_control', None) is not None:
            log_op(request, "COLLECTOR_RESUME", "Collector resume requested")
            return store._service_control.enqueue('resume')
        if collector is None:
            raise HTTPException(503, "수집기가 없습니다.")
        collector.resume()
        log_op(request, "COLLECTOR_RESUME", "수집기 재개")
        return {"paused": False}

    @router.get("/admin/api/scavenger", dependencies=auth)
    def scavenger_info():
        return {
            "stats": store.scavenger_stats(),
            "last_batch": store.get_meta("last_scavenge_batch"),
        }

    @router.post("/admin/api/actions/scavenge", dependencies=auth)
    def scavenge_now(request: Request):
        if collector is None or collector.checker is None:
            raise HTTPException(503, "헬스체커가 준비되지 않았습니다.")
        log_op(request, "SCAVENGE_RUN", "미사용 에이전트 정리(Scavenge) 실행")
        return run_background("scavenge", lambda: collector.checker.scavenge_retired(limit=50))

    @router.post("/admin/api/actions/erc8004-retry", dependencies=auth)
    def erc8004_retry(request: Request):
        """받기에 실패한 등록 파일을 지금 다시 받도록 대기열에 돌려놓는다."""
        with store.tx() as db:
            n = db.execute("""UPDATE erc8004_tokens SET status='pending', next_at=NULL, error=NULL
                              WHERE status='error' AND uri IS NOT NULL""").rowcount
        log.info("dashboard: %d erc8004 registrations requeued", n)
        log_op(request, "ERC8004_RETRY", "ERC-8004 재시도 큐 재등록", details={"requeued": n})
        return {"requeued": n}

    @router.post("/admin/api/agents/{rid}/check", dependencies=auth)
    def check(rid: int, request: Request):
        if collector is None:
            raise HTTPException(503, "수집기가 없습니다.")
        r = store.resource(rid)
        if r is None:
            raise HTTPException(404, "없는 에이전트")
        log_op(request, "AGENT_CHECK", "에이전트 단일 헬스체크", target=f"agent:{rid}")
        return collector.checker.check_and_record(r)

    @router.post("/admin/api/agents/{rid}/deactivate", dependencies=auth)
    def deactivate(rid: int, request: Request):
        with store.tx() as db:
            if not db.execute("UPDATE resources SET active=0,inactive_reason='operator' WHERE id=?", (rid,)).rowcount:
                raise HTTPException(404, "없는 에이전트")
        log.info("dashboard: agent %d deactivated", rid)
        log_op(request, "AGENT_DEACTIVATE", "에이전트 비활성화", target=f"agent:{rid}")
        return {"active": False}

    @router.post("/admin/api/agents/{rid}/activate", dependencies=auth)
    def activate(rid: int, request: Request):
        """다시 활성화하고 점검 상태를 초기화해 바로 다시 점검하게 한다 (retired 복구에도 씀)."""
        with store.tx() as db:
            if not db.execute("""UPDATE resources SET active=1,inactive_reason=NULL, health_status='unknown', consecutive_failures=0,
                                 failing_since=NULL, next_check_at=NULL WHERE id=?""", (rid,)).rowcount:
                raise HTTPException(404, "없는 에이전트")
        log.info("dashboard: agent %d activated", rid)
        log_op(request, "AGENT_ACTIVATE", "에이전트 활성화", target=f"agent:{rid}")
        return {"active": True}

    # ---------------- 에이전트 직접 등록 (A2A, MCP, x402) ----------------
    register_limit = RateLimiter(30)  # 분당 30회 등록 제한

    @router.post("/admin/api/register/inspect", dependencies=auth)
    async def register_inspect(request: Request):
        """URL을 안전하게 사전 조사(SSRF 차단)하여 에이전트 종류, 이름, 설명, 카테고리를 자동 분석하여 제안한다."""
        try:
            data = await request.json()
        except Exception:
            raise HTTPException(400, "유효한 JSON 객체가 필요합니다.")
        if not isinstance(data, dict):
            raise HTTPException(400, "JSON 객체가 필요합니다.")

        raw_url = str(data.get("url") or "").strip().replace("\x00", "")
        if not raw_url:
            raise HTTPException(400, "URL을 입력해주세요.")

        return await asyncio.to_thread(_inspect_url, raw_url)

    def _inspect_url(raw_url):
        try:
            check_public_url(raw_url)
        except DiscoveryError as exc:
            raise HTTPException(400, f"보안 검증 실패: {exc}")
        except Exception as exc:
            raise HTTPException(400, f"유효하지 않은 URL입니다: {exc}")

        client = public_client(allow_private=False, timeout=6.0, follow_redirects=False)
        try:
            detected_kind = "mcp"
            name = ""
            desc = ""
            category = "ai_models"
            price_usdc = 0
            pay_to = None
            details = {}
            networks = ["base"]

            parsed = urlparse(raw_url)
            base_host = f"{parsed.scheme}://{parsed.netloc}"
            card_urls = []
            if raw_url.endswith(".json"):
                card_urls.append(raw_url)
            else:
                card_urls.extend([
                    f"{raw_url.rstrip('/')}/.well-known/agent-card.json",
                    f"{raw_url.rstrip('/')}/.well-known/agent.json",
                    f"{base_host}/.well-known/agent-card.json",
                ])

            card_found = False
            for cu in card_urls:
                try:
                    check_public_url(cu)
                    res = client.get(cu)
                    if res.status_code == 200 and "application/json" in (res.headers.get("content-type") or ""):
                        card_data = res.json()
                        if isinstance(card_data, dict) and ("name" in card_data or "skills" in card_data or "supportedInterfaces" in card_data):
                            detected_kind = "a2a"
                            name = str(card_data.get("name") or "").strip()
                            desc = str(card_data.get("description") or "").strip()
                            skills = [s.get("id") or s.get("name") for s in card_data.get("skills", []) if isinstance(s, dict)]
                            details = {"card_url": cu, "skills": skills}
                            card_found = True
                            break
                except Exception:
                    continue

            if not card_found:
                try:
                    res = client.get(raw_url)
                    auth_hdr = res.headers.get("www-authenticate", "") or res.headers.get("x-payment-address", "")
                    if res.status_code == 402 or "x402" in auth_hdr.lower():
                        detected_kind = "x402"
                        desc = f"x402 paid API endpoint at {parsed.netloc}"
                        if "x-payment-address" in res.headers:
                            pay_to = res.headers["x-payment-address"].strip().lower()
                        if "x-payment-amount" in res.headers:
                            try:
                                price_usdc = int(res.headers["x-payment-amount"])
                            except ValueError:
                                price_usdc = 1000
                    elif res.status_code == 200:
                        text = res.text[:3000]
                        if "<title>" in text.lower():
                            t_start = text.lower().find("<title>") + 7
                            t_end = text.lower().find("</title>", t_start)
                            if t_end > t_start:
                                name = text[t_start:t_end].strip()
                        if "mcp" in raw_url.lower() or "tools" in text.lower():
                            detected_kind = "mcp"
                            if not desc:
                                desc = f"MCP tool server at {parsed.netloc}"
                except Exception:
                    pass

            if not name:
                name = parsed.netloc.split(":")[0]
            if not desc:
                desc = f"{name} {detected_kind.upper()} service endpoint"

            category = classify(f"{name} {desc}")
            if category not in CATEGORIES:
                category = "ai_models"

            return {
                "ok": True,
                "kind": detected_kind,
                "url": raw_url,
                "name": name[:100],
                "description": desc[:1000],
                "category": category,
                "price_usdc": price_usdc,
                "pay_to": pay_to,
                "networks": networks,
                "details": details,
            }
        finally:
            client.close()

    @router.post("/admin/api/register", dependencies=auth)
    async def register_agent(request: Request):
        """A2A, MCP, x402 에이전트/도구/API를 수동으로 직접 등록한다.
        수집 과정과 동일하게 실제 활성 상태(Health Check)를 검증하며, 중복 등록은 차단된다."""
        ip = request.client.host if request.client else "unknown"
        if not register_limit.allow(ip):
            raise HTTPException(429, "등록 요청이 너무 많습니다. 잠시 후 다시 시도해주세요.")
        try:
            data = await request.json()
        except Exception:
            raise HTTPException(400, "유효한 JSON 객체가 필요합니다.")
        if not isinstance(data, dict):
            raise HTTPException(400, "JSON 객체가 필요합니다.")

        kind = str(data.get("kind") or "").strip().lower()
        if kind not in KINDS:
            raise HTTPException(400, "올바른 kind를 선택해주세요. (a2a, mcp, x402)")

        raw_url = str(data.get("url") or "").strip().replace("\x00", "")
        if not raw_url:
            raise HTTPException(400, "URL은 필수입니다.")
        if not raw_url.startswith(("http://", "https://")):
            raise HTTPException(400, "URL은 http:// 또는 https://로 시작해야 합니다.")
        if len(raw_url) > 1000:
            raise HTTPException(400, "URL 길이가 너무 깁니다. (최대 1000자)")

        # 1. SSRF 차단 검증
        try:
            check_public_url(raw_url)
        except DiscoveryError as exc:
            raise HTTPException(400, f"보안 검증 실패: {exc}")
        except Exception as exc:
            raise HTTPException(400, f"유효하지 않은 URL입니다: {exc}")

        # 2. 중복 등록 방지 (수집기 수집 건 + 수동 등록 건 모두 차단)
        key = f"{kind}:{raw_url}"
        with reader() as db:
            existing = db.execute(
                "SELECT id, name, kind, source, url FROM resources WHERE url=? OR key=?",
                (raw_url, key)
            ).fetchone()
            if existing:
                raise HTTPException(
                    409,
                    f"이미 등록되어 있는 에이전트 URL입니다: '{existing['name']}' "
                    f"(ID: {existing['id']}, 종류: {existing['kind'].upper()}, 수집출처: {existing['source']})"
                )

        name = str(data.get("name") or "").strip().replace("\x00", "")
        if not name:
            raise HTTPException(400, "이름을 입력해주세요.")
        name = name[:100]

        description = str(data.get("description") or "").strip().replace("\x00", "")
        if not description:
            raise HTTPException(400, "설명을 입력해주세요.")
        description = description[:2000]

        category = str(data.get("category") or "").strip().lower()
        if category not in CATEGORIES:
            category = classify(f"{name} {description}")

        networks = data.get("networks") or ["base"]
        if isinstance(networks, str):
            networks = [n.strip() for n in networks.split(",") if n.strip()]
        networks = [str(n)[:20] for n in networks if n] or ["base"]

        price_usdc = data.get("price_usdc")
        if price_usdc is not None:
            try:
                price_usdc = max(0, int(price_usdc))
            except (ValueError, TypeError):
                price_usdc = 0
        else:
            price_usdc = 0 if kind != "x402" else 1000

        pay_to = str(data.get("pay_to") or "").strip().lower()[:100] or None
        method = str(data.get("method") or "POST").strip().upper()[:10]
        details = data.get("details") if isinstance(data.get("details"), dict) else {}

        # 3. 수집 과정과 동일한 실제 활성 상태 검증 (Live Health Check)
        checker = collector.checker if (collector and hasattr(collector, "checker")) else HealthChecker(store, allow_private=False)
        temp_resource = {
            "kind": kind,
            "url": raw_url,
            "method": method,
            "details": json.dumps(details),
        }
        check_res = checker.check(temp_resource)
        if check_res.outcome not in ("healthy", "reachable"):
            err = check_res.error or (f"HTTP {check_res.status_code}" if check_res.status_code else "서버 응답 없음")
            raise HTTPException(
                422,
                f"에이전트 활성 검증 실패: 실제 엔드포인트 연결에 실패했거나 비정상 응답입니다 ({err}). "
                "에이전트 서버가 정상 가동 중인지 확인해주세요."
            )

        # 4. 활성 상태 확인 완료 -> 헬스체크 대상에 포함하여 DB 적재
        now = time.time()
        record = {
            "key": key,
            "source": "manual",
            "kind": kind,
            "url": raw_url,
            "name": name,
            "description": description,
            "category": category,
            "networks": networks,
            "price_usdc": price_usdc,
            "pay_to": pay_to,
            "method": method,
            "details": details,
            "calls_30d": 0,
            "payers_30d": 0,
            "last_called": None,
        }

        # 신규 적재
        counts = store.upsert_page([record], now=now)

        with reader() as db:
            row = db.execute("SELECT id FROM resources WHERE key=?", (key,)).fetchone()
            rid = row["id"] if row else None

        if rid is not None:
            with store.tx() as db:
                db.execute(
                    """UPDATE resources SET
                        health_status=?,
                        last_check_at=?,
                        last_ok_at=?,
                        next_check_at=?,
                        last_status_code=?,
                        last_error=NULL,
                        health_ok_24h=1,
                        health_n_24h=1,
                        probe_latency_ms=?,
                        consecutive_failures=0
                    WHERE id=?""",
                    (check_res.outcome, now, now, now + 3600, check_res.status_code, check_res.latency_ms, rid)
                )
                db.execute(
                    """INSERT INTO health_checks (resource_id, at, outcome, status_code, latency_ms, error)
                       VALUES (?, ?, ?, ?, ?, NULL)""",
                    (rid, now, check_res.outcome, check_res.status_code, check_res.latency_ms)
                )

        log.info("dashboard: manual agent registered & health verified: %s (id=%s, kind=%s, status=%s)", name, rid, kind, check_res.outcome)
        return {
            "ok": True,
            "id": rid,
            "kind": kind,
            "name": name,
            "status": check_res.outcome,
            "message": f"성공적으로 등록되었습니다! 실제 활성 상태({check_res.outcome})가 확인되어 헬스체크 대기열 및 실시간 추천 풀에 즉시 반영되었습니다."
        }

    @router.post("/admin/api/logs/clear", dependencies=auth)
    async def clear_logs(request: Request):
        require_development_action(request)
        from ..admin_next import reason_text
        try:
            data = await request.json()
        except ValueError:
            raise HTTPException(400, '개발 작업 사유를 입력하세요.') from None
        request.state.audit_reason = reason_text(data.get('reason') if isinstance(data, dict) else None)
        log_op(request, 'DEV_LOG_BUFFER_CLEAR_INTENT', '개발용 로그 버퍼 초기화 요청', status='REQUESTED')
        logs.records.clear()
        logs.counts.clear()
        log_op(request, 'DEV_LOG_BUFFER_CLEAR', '개발용 로그 버퍼 초기화 완료')
        return {"ok": True}

    # ---------------- 에이전트 라이브 테스트벤치 (Agent Testbench) ----------------
    @router.get('/admin/api/test/examples', dependencies=auth)
    def test_examples():
        from ..concierge.testbench_examples import live_examples
        return {'examples': live_examples(store)}

    @router.get("/admin/api/test/agents", dependencies=auth)
    def test_agents(q: str = Query("", max_length=100), kind: str | None = None,
                    agent_id: int | None = Query(None), limit: int = Query(100, ge=1, le=300)):
        """테스트 가능한 에이전트 목록을 검색하거나 반환한다."""
        conds = ["r.active = 1"]
        params: list = []
        if kind and kind in KINDS:
            conds.append("r.kind = ?")
            params.append(kind)

        q_clean = q.strip()
        if q_clean:
            if q_clean.isdigit():
                conds.append("(r.id = ? OR r.name LIKE ? OR r.url LIKE ?)")
                term = f"%{q_clean}%"
                params.extend([int(q_clean), term, term])
            else:
                matched_cats = [cid for cid, cat in CATEGORIES.items() if q_clean in cat.name or q_clean in cid]
                try:
                    c_guess = classify(q_clean)
                    if c_guess and c_guess != "other" and c_guess not in matched_cats:
                        matched_cats.append(c_guess)
                except Exception:
                    pass

                term = f"%{q_clean}%"
                clauses = ["r.name LIKE ?", "r.url LIKE ?", "r.description LIKE ?"]
                clause_params = [term, term, term]
                if matched_cats:
                    clauses.append(f"r.category IN ({','.join('?' for _ in matched_cats)})")
                    clause_params.extend(matched_cats)
                else:
                    clauses.append("r.category LIKE ?")
                    clause_params.append(term)

                conds.append(f"({' OR '.join(clauses)})")
                params.extend(clause_params)

        sql = f"""SELECT r.id, r.kind, r.name, r.url, r.category, r.health_status,
                         r.cap_tool_count, r.price_usdc, r.eval_grade, r.eval_score, r.trial_ok
                  FROM resources r
                  WHERE {' AND '.join(conds)}
                  ORDER BY (r.health_status='healthy') DESC, (r.trial_ok IS 1) DESC, r.eval_score DESC, r.id DESC
                  LIMIT ?"""
        params.append(limit)
        with reader() as db:
            rows = _rows(db.execute(sql, params))

            if agent_id and not any(r['id'] == agent_id for r in rows):
                target = store.resource(agent_id)
                if target and target.get('active'):
                    rows.insert(0, {key: target.get(key) for key in ('id', 'kind', 'name', 'url', 'category',
                        'health_status', 'cap_tool_count', 'price_usdc', 'eval_grade', 'eval_score', 'trial_ok')})

        return {"agents": rows, "count": len(rows)}

    @router.get("/admin/api/test/agents/{rid}/spec", dependencies=auth)
    async def test_agent_spec(rid: int, refresh: bool = Query(default=False)):
        """선택된 에이전트의 상세 명세(도구 목록, 스키마, 샘플 인자, 직전 테스트 이력)를 반환한다.
        도구 목록이 비어 있거나 refresh=True인 경우 라이브 엔드포인트에 tools/list 조사를 시도한다."""
        r = store.resource(rid)
        if r is None:
            raise HTTPException(404, "에이전트를 찾을 수 없습니다.")

        tools_list = []
        skills_list = []
        sample_args = {}
        try:
            details = json.loads(r.get("details") or "{}")
            if not isinstance(details, dict):
                details = {}
        except Exception:
            details = {}
        try:
            guide = json.loads(r.get("usage_guide") or "{}")
            if not isinstance(guide, dict):
                guide = {}
        except Exception:
            guide = {}

        if r["kind"] == "mcp":
            raw_tools = []
            from ..owned_data_agents.dispatch import is_owned
            local_resource = is_owned(r)
            if local_resource:
                raw_tools = json.loads(r.get('usage_full_tools') or '[]')
                if not raw_tools:
                    raise HTTPException(409, 'The local capability schema needs review.')
            elif not refresh:
                raw_tools = guide.get("tools") or (json.loads(r.get("usage_tools") or "[]")) or details.get("tools") or []

            # 사전 저장된 도구가 없거나 명시적 새로고침 요청 시 라이브 서버에 tools/list 실시간 질의
            if not raw_tools:
                try:
                    url = r["url"]
                    check_public_url(url)

                    async with public_async_client(timeout=httpx.Timeout(3.0, connect=2.0)) as client:
                        headers = {"Content-Type": "application/json", "User-Agent": "AgentConcierge-AdminTestbench/1.0"}
                        # 1. 최신 사양 server/discover 시도
                        try:
                            disc_resp = await bounded_request(client, "POST", url, json={"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {}}, headers=headers)
                            disc_data = parse_jsonrpc(disc_resp) or {}
                            if isinstance(disc_data.get("result"), dict):
                                pv = disc_data["result"].get("protocolVersion")
                                if pv:
                                    headers["mcp-protocol-version"] = str(pv)
                        except Exception:
                            pass

                        # 2. 직결 tools/list 시도
                        tools_candidate = None
                        try:
                            list_resp = await bounded_request(client, "POST", url, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, headers=headers)
                            list_data = parse_jsonrpc(list_resp) or {}
                            tools_candidate = (list_data.get("result") or {}).get("tools")
                        except Exception:
                            tools_candidate = None

                        # 3. 직결이 안 되면 initialize 세션 핸드셰이크 시도
                        if not isinstance(tools_candidate, list):
                            try:
                                init_resp = await bounded_request(client, "POST", url, json={
                                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                                    "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                                               "clientInfo": {"name": "admin-testbench", "version": "1.0"}}
                                }, headers=headers)
                                init_data = parse_jsonrpc(init_resp) or {}
                                if init_data.get("result"):
                                    sid = init_resp.headers.get("mcp-session-id")
                                    if sid:
                                        headers["mcp-session-id"] = sid
                                    await bounded_request(client, "POST", url, json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=headers)
                                    list_resp2 = await bounded_request(client, "POST", url, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, headers=headers)
                                    list_data2 = parse_jsonrpc(list_resp2) or {}
                                    tools_candidate = (list_data2.get("result") or {}).get("tools")
                            except Exception:
                                pass

                        if isinstance(tools_candidate, list) and tools_candidate:
                            raw_tools = usage.compact_tools(tools_candidate)
                            try:
                                with store.tx() as db:
                                    db.execute("UPDATE resources SET usage_tools=?, cap_tool_count=? WHERE id=?",
                                               (json.dumps(raw_tools), len(raw_tools), rid))
                            except Exception:
                                pass
                except Exception as e:
                    log.debug("on-demand tools probe failed for agent %s: %s", rid, e)

            for t in raw_tools:
                t_name = t.get("name")
                if not t_name:
                    continue
                if "params" not in t and "inputSchema" in t:
                    norm = usage.compact_tools([t])
                    tool_dict = norm[0] if norm else dict(t)
                else:
                    tool_dict = dict(t)
                tool_dict.setdefault("params", {})
                tool_dict.setdefault("required", [])

                sample = {}
                try:
                    sample = usage.example_arguments(tool_dict, r.get("category")) or usage.placeholder_arguments(tool_dict) or {}
                except Exception:
                    sample = {}

                tools_list.append({
                    "name": t_name,
                    "description": tool_dict.get("description") or "",
                    "params": tool_dict.get("params") or tool_dict.get("inputSchema") or {},
                    "required": tool_dict.get("required") or [],
                    "sample": sample,
                })
            if tools_list and not sample_args:
                sample_args = tools_list[0].get("sample") or {}
        elif r["kind"] == "a2a":
            card = details.get("card") or details.get("agent_card") or details
            skills = card.get("skills") or [] if isinstance(card, dict) else []
            for s in skills:
                skills_list.append({
                    "name": s.get("name") or s.get("id"),
                    "title": s.get("title") or s.get("name"),
                    "description": s.get("description") or "",
                    "examples": s.get("examples") or [],
                })
            sample_picked = a2a.pick_message(card) if isinstance(card, dict) and "skills" in card else None
            sample_msg = sample_picked[1] if sample_picked else "Hello! Can you report your current capabilities?"
            sample_args["message"] = sample_msg

        return {
            "id": r["id"],
            "name": r["name"],
            "kind": r["kind"],
            "url": r["url"],
            "category": r["category"],
            "health_status": r["health_status"],
            "eval_grade": r.get("eval_grade"),
            "eval_score": r.get("eval_score"),
            "tools": tools_list,
            "skills": skills_list,
            "sample_args": sample_args,
            "last_trial": json.loads(r.get("trial_info") or "null"),
        }

    @router.post("/admin/api/test/execute", dependencies=auth)
    async def test_execute(request: Request):
        """선택된 에이전트에 대해 실시간 라이브 프로브를 실행하고 지연시간, 원시 와이어 페이로드 및 가공된 결과를 반환한다."""
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "JSON 형식이 올바르지 않습니다.")
        if not isinstance(body, dict):
            raise HTTPException(400, "JSON 객체가 필요합니다.")

        rid = body.get("resource_id")
        if type(rid) is not int:
            raise HTTPException(400, "resource_id(정수)가 필요합니다.")

        r = store.resource(rid)
        if r is None or not r.get('active'):
            raise HTTPException(404, "활성 에이전트를 찾을 수 없습니다.")

        action = str(body.get("action") or "").strip()
        tool_name = str(body.get("tool") or "").strip()
        args = body.get("arguments") if isinstance(body.get("arguments"), dict) else {}
        message_text = str(body.get("message") or "").strip()
        timeout_sec = min(max(float(body.get("timeout_seconds") or 10.0), 2.0), 30.0)

        from ..edge_gateway.admin_delivery import server_test
        edge_result=await server_test(front,r,body,getattr(request.state,'admin_user',{}))
        if edge_result is not None:
            overview_cache.invalidate()
            return edge_result

        url = r["url"]
        started = time.monotonic()
        tested_at = time.time()
        kind = r["kind"]
        request_wire = {}
        response_wire = {}
        output_text = ""
        status_code = None
        is_error = False
        error_msg = None

        headers = {"User-Agent": "AgentConcierge-AdminTestbench/1.0", "Accept": "application/json"}

        from ..owned_data_agents.dispatch import is_owned
        if is_owned(r):
            if not tool_name:
                raise HTTPException(400, 'Choose a registered MCP tool.')
            result = await asyncio.to_thread(workflows_runtime.proxy.execute, rid, tool_name, args, public=True)
            is_error = not result.get('ok', False)
            status_code = 200 if not is_error else None
            error_msg = result.get('error') if is_error else None
            request_wire = {'execution': 'local', 'resource_id': rid, 'tool': tool_name, 'arguments': args}
            response_wire = result.get('result') or {'error': error_msg, 'error_code': result.get('error_code')}
            output_text = result.get('sample_output') or error_msg or ''
        else:
            try:
                check_public_url(url)
            except DiscoveryError:
                raise HTTPException(400, "보안 정책에 따라 테스트할 수 없는 주소입니다.")

            try:
                async with public_async_client(timeout=httpx.Timeout(timeout_sec, connect=5.0)) as client:
                    if kind == "mcp":
                        if not tool_name:
                            raise HTTPException(400, "호출할 MCP 도구(tool) 이름을 지정해주세요.")
                        req_id = f"test-{rid}-{int(tested_at)}"
                        payload = {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "method": "tools/call",
                            "params": {"name": tool_name, "arguments": args}
                        }
                        request_wire = {"url": url, "method": "POST", "headers": headers, "body": payload}
                        resp = await bounded_request(client, "POST", url, json=payload, headers=headers)
                        status_code = resp.status_code
                        try:
                            data = resp.json()
                            response_wire = data
                        except Exception:
                            response_wire = {"raw": resp.text[:4000]}
                            data = {}

                        if isinstance(data, dict):
                            err = data.get("error")
                            if err:
                                is_error = True
                                error_msg = str(err.get("message") if isinstance(err, dict) else err)
                                output_text = f"JSON-RPC Error: {error_msg}"
                            elif "result" in data:
                                res = data["result"]
                                is_error = bool(res.get("isError"))
                                output_text = usage.result_text(res) or json.dumps(res, ensure_ascii=False, indent=2)
                                if is_error and not output_text:
                                    output_text = "Tool execution returned an error (isError=true)"
                            else:
                                is_error = status_code >= 400
                                error_msg = f"Unexpected response format (HTTP {status_code})"
                                output_text = resp.text[:2000]
                        else:
                            is_error = status_code >= 400
                            output_text = resp.text[:2000]

                    elif kind == "a2a":
                        try:
                            details = json.loads(r.get("details") or "{}")
                            if not isinstance(details, dict):
                                details = {}
                        except Exception:
                            details = {}
                        card = details.get("card") or details.get("agent_card") or details
                        msg = message_text or "Hello! What services or capabilities do you provide?"
                        req_id = f"test-{rid}-{int(tested_at)}"
                        mid = str(uuid.uuid4())

                        ep_url = url
                        if isinstance(card, dict) and "endpoints" in card:
                            for ep in card.get("endpoints", []):
                                if ep.get("binding") == "JSONRPC":
                                    ep_url = ep.get("url") or url
                                    break

                        payload = {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "method": "message/send",
                            "params": {
                                "message": {
                                    "role": "user",
                                    "parts": [{"text": msg}],
                                    "messageId": mid
                                }
                            }
                        }
                        check_public_url(ep_url)
                        request_wire = {"url": ep_url, "method": "POST", "headers": headers, "body": payload}
                        resp = await bounded_request(client, "POST", ep_url, json=payload, headers=headers)
                        status_code = resp.status_code
                        try:
                            data = resp.json()
                            response_wire = data
                        except Exception:
                            response_wire = {"raw": resp.text[:4000]}
                            data = {}

                        if isinstance(data, dict):
                            if data.get("error"):
                                is_error = True
                                error_msg = str(data["error"].get("message") if isinstance(data["error"], dict) else data["error"])
                                output_text = f"A2A Error: {error_msg}"
                            elif "result" in data:
                                summary = a2a.response_summary(data["result"])
                                output_text = summary.get("text") or json.dumps(data["result"], ensure_ascii=False, indent=2)
                                is_error = summary.get("state") in ("failed", "rejected")
                                if is_error:
                                    error_msg = f"Task terminated with state: {summary.get('state')}"
                            else:
                                is_error = status_code >= 400
                                output_text = resp.text[:2000]
                        else:
                            is_error = status_code >= 400
                            output_text = resp.text[:2000]

                    elif kind == "x402":
                        request_wire = {"url": url, "method": "GET", "headers": headers}
                        resp = await bounded_request(client, "GET", url, headers=headers)
                        status_code = resp.status_code
                        try:
                            data = resp.json()
                            response_wire = data
                        except Exception:
                            response_wire = {"raw": resp.text[:4000]}
                            data = {}

                        if resp.status_code == 402:
                            auth_header = resp.headers.get("www-authenticate", "")
                            output_text = f"HTTP 402 Payment Required\nWWW-Authenticate: {auth_header}\n\n{resp.text[:2000]}"
                            is_error = False
                        else:
                            is_error = resp.status_code >= 400
                            output_text = resp.text[:2000]

            except httpx.TimeoutException:
                is_error = True
                error_msg = 'The provider did not respond within the execution time limit.'
                output_text = error_msg
            except httpx.HTTPError:
                is_error = True
                error_msg = 'The provider connection failed. Review its current availability.'
                output_text = error_msg
            except HTTPException:
                raise
            except Exception:
                is_error = True
                error_msg = 'The provider response could not be processed.'
                output_text = error_msg

        latency_ms = int((time.monotonic() - started) * 1000)

        user = getattr(request.state, "admin_user", {"username": "sadmin", "role": "superadmin"})
        client_ip = request.client.host if request.client else None
        with store.tx() as db:
            admin_auth.record_audit(
                db,
                username=user.get("username", "sadmin"),
                role=user.get("role", "superadmin"),
                action="AGENT_TEST",
                action_name=f"에이전트 라이브 테스트 ({kind.upper()})",
                target=f"agent:{r['id']}",
                ip=client_ip,
                status="SUCCESS" if not is_error else "FAILED",
                details={
                    "agent_id": r["id"],
                    "agent_name": r["name"],
                    "kind": kind,
                    "tool": tool_name,
                    "latency_ms": latency_ms,
                    "status_code": status_code,
                    "error": error_msg or None,
                },
            )

        overview_cache.invalidate()
        try:
            wire_str = json.dumps(response_wire, ensure_ascii=False)
            if len(wire_str) > 1_000_000:
                response_wire = {"_notice": "Payload exceeds 1MB and was truncated", "preview": wire_str[:5000]}
        except Exception:
            pass

        return {
            "ok": not is_error,
            "simulated": False,
            "execution_succeeded": not is_error,
            "status_code": status_code,
            "latency_ms": latency_ms,
            "protocol": kind,
            "target_url": url,
            "request_wire": request_wire,
            "response_wire": response_wire,
            "output_text": output_text,
            "is_error": is_error,
            "error_message": error_msg,
            "tested_at": tested_at,
        }

    # ---------------- 에이전트 테스트 결과 보고서 (블로그 스타일) ----------------
    @router.get("/admin/api/test-reports", dependencies=auth)
    def get_test_reports(
        limit: int = 50,
        offset: int = 0,
        kind: str | None = None,
        category: str | None = None,
        grade: str | None = None,
        q: str | None = None,
        is_success: int | None = None,
        tag: str | None = None,
    ):
        reports, total = store.list_test_reports(
            limit=limit,
            offset=offset,
            kind=kind,
            category=category,
            grade=grade,
            q=q,
            is_success=is_success,
            tag=tag,
        )
        return {"ok": True, "reports": reports, "total": total, "limit": limit, "offset": offset}

    @router.get("/admin/api/test-reports/existing", dependencies=auth)
    def existing_test_report(resource_id: int | None = Query(None, gt=0, lt=2**31),
                             kind: str | None = Query(None, max_length=32),
                             agent_url: str | None = Query(None, max_length=2048)):
        try:
            # The native store exposes only reviewed entry points, so the same duplicate check is run
            # through the reviewed primitives it allows (resource lookup and the catalogued claim queries).
            from ..report_creation import find_existing, subject as report_subject
            report_id = find_existing(store, report_subject(store, resource_id, kind, agent_url))
        except (ValueError, KeyError) as exc:
            # Record only the failure class and stable code so a storage fault is not mistaken for bad input.
            log.warning('report existence check rejected: %s code=%s', type(exc).__name__, getattr(exc, 'code', None))
            raise HTTPException(400, 'Choose a valid report subject before creating a report.') from None
        return {'ok': True, 'exists': report_id is not None,
                'can_create': report_id is None, 'existing_report_id': report_id}

    @router.get("/admin/api/test-reports/{report_id}", dependencies=auth)
    def get_test_report(report_id: int):
        report = store.get_test_report(report_id)
        if not report:
            raise HTTPException(404, "테스트 결과 보고서를 찾을 수 없습니다.")
        return {"ok": True, "report": report}

    @router.post("/admin/api/test-reports", dependencies=auth)
    async def create_test_report(request: Request):
        from ..report_creation import ReportAlreadyExists, ReportSlugConflict
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "JSON 형식이 올바르지 않습니다.")
        if not isinstance(body, dict):
            raise HTTPException(400, "JSON 객체가 필요합니다.")
        if body.get('is_success') in (True, 1) and body.get('evidence_scope') not in ('execution','contract'):
            return JSONResponse({'ok':False,'error_code':'EXECUTION_EVIDENCE_REQUIRED',
                'error':'A successful test report requires a completed, recorded execution for the current connection. A connection-only check is not task execution.'},status_code=422)
        try:report_id = store.create_test_report(body)
        except ReportAlreadyExists as exc:
            return JSONResponse({'ok':False,'error_code':'REPORT_ALREADY_EXISTS',
                'error':'A report already exists for this agent. Open the existing report instead.',
                'existing_report_id':exc.report_id},status_code=409)
        except ReportSlugConflict:
            return JSONResponse({'ok':False,'error_code':'REPORT_SLUG_CONFLICT',
                'error':'This report link is already in use. Choose a different link.'},status_code=409)
        except (ValueError,KeyError,TypeError,OverflowError,sqlite3.IntegrityError,sqlite3.ProgrammingError):
            raise HTTPException(400,'Provide a valid report and actual execution timestamps.') from None
        return {"ok": True, "id": report_id}

    # ---------------- 에이전트 워크플로우 (Chaining & Automation) ----------------
    @router.get("/admin/api/workflows", dependencies=auth)
    def get_workflows(
        limit: int = 50,
        offset: int = 0,
        active_only: bool = True,
        is_template: int | None = None,
        author: str | None = None,
        category: str | None = None,
        q: str | None = None,
        sort_by: str = "updated_at",
    ):
        if not 1 <= limit <= 1000 or offset < 0:raise HTTPException(400,'Invalid workflow page.')
        workflows, total = store.list_workflows(
            limit=limit,
            offset=offset,
            active_only=active_only,
            is_template=is_template,
            author=author,
            category=category,
            q=q,
            sort_by=sort_by,
        )
        return {"ok": True, "workflows": workflows_runtime.metrics(workflows), "total": total, "limit": limit, "offset": offset,
                "controlled_pair_profile": CONTROLLED_PAIR_PROFILE,"publication_profile":PUBLICATION_PROFILE,
                "connected_sdk_profile":CONNECTED_SDK_PROFILE,"connected_automation_profile":CONNECTED_AUTOMATION_PROFILE,
                "product_semantics_profile":PRODUCT_SEMANTICS_PROFILE}

    @router.post("/admin/api/workflows/{workflow_id}/fork", dependencies=auth)
    async def fork_workflow_endpoint(workflow_id: int, request: Request):
        req_body = {}
        try:
            req_body = await request.json()
        except Exception:
            pass
        if not isinstance(req_body, dict):
            req_body = {}
        author = req_body.get("author", "Me")
        custom_name = req_body.get("name")
        forked = store.fork_workflow(workflow_id, author=author, custom_name=custom_name)
        if not forked:
            raise HTTPException(404, "원본 워크플로우를 찾을 수 없습니다.")
        return {"ok": True, "workflow": forked}

    @router.post("/admin/api/workflows/{workflow_id}/publish-template", dependencies=auth)
    async def publish_workflow_to_template(workflow_id: int, request: Request):
        data = await legacy_public_body(request)
        current = public_changes.template(workflow_id)
        return request_public_change(request, 'template', {'action': 'publish', 'target': workflow_id,
            'fields': {k: data[k] for k in ('name','description','category','tags','nodes','edges') if k in data},
            'revision': data.get('revision', current['revision']), 'reason': data.get('reason')})

    @router.post("/admin/api/workflows/{workflow_id}/reviews", dependencies=auth)
    async def review_workflow(workflow_id: int, request: Request):
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "JSON 형식이 올바르지 않습니다.")
        if not isinstance(body, dict):
            raise HTTPException(400, "JSON 객체가 필요합니다.")
        reviewer = body.get("reviewer", "Verified Agent")
        rating = int(body.get("rating", 5))
        comment = body.get("comment", "")
        review_id = store.add_workflow_review(workflow_id, reviewer=reviewer, rating=rating, comment=comment)
        return {"ok": True, "review_id": review_id}

    @router.get("/admin/api/workflows/{workflow_id}/reviews", dependencies=auth)
    def get_workflow_reviews(workflow_id: int):
        reviews = store.list_workflow_reviews(workflow_id)
        return {"ok": True, "reviews": reviews}

    @router.post('/admin/api/workflows/ai-generate', dependencies=[Depends(require_sadmin)])
    async def ai_generate_workflow(request: Request):
        from starlette.concurrency import run_in_threadpool
        if not rag_limit.allow(request.client.host if request.client else 'unknown'):raise HTTPException(429,'Please try again later.')
        try:
            body=await request.json()
            result=await run_in_threadpool(composer.generate,body,request.state.admin_user['user_id'])
        except ValueError as exc:raise HTTPException(422,str(exc)) from None
        return JSONResponse(result,headers={'Cache-Control':'no-store'})

    @router.post('/admin/api/workflow-composer/revise', dependencies=[Depends(require_sadmin)])
    async def revise_composer(request: Request):
        try:
            body=await request.json()
            if not isinstance(body,dict):raise ValueError('A signed proposal is required.')
            result=composer.revise(body,request.state.admin_user['user_id'])
        except (ValueError,TypeError,KeyError):raise HTTPException(400,'The selections or proposal are invalid; generate a new proposal.') from None
        return JSONResponse(result,headers={'Cache-Control':'no-store'})

    @router.post('/admin/api/workflow-composer/save', dependencies=[Depends(require_sadmin)])
    async def save_composer(request: Request):
        try:
            body=await request.json()
            if not isinstance(body,dict):raise ValueError('A signed proposal is required.')
            result=composer.save(body,request.state.admin_user['user_id'])
        except (ValueError,TypeError,KeyError) as exc:raise HTTPException(400,str(exc) if isinstance(exc,ValueError) else 'Invalid proposal.') from None
        log_op(request,'workflow_composer_save','Reviewed contract draft saved',details={'workflow_id':result['id']})
        return JSONResponse(result,headers={'Cache-Control':'no-store'})

    @router.post('/admin/api/workflow-composer/publish', dependencies=[Depends(require_sadmin)])
    async def publish_composer(request: Request):
        body = await legacy_public_body(request)
        try:
            if (set(body) - {'workflow_id','run_id','authority','notice','reason'} or type(body.get('workflow_id')) is not int
                    or not isinstance(body.get('run_id'),str) or not re.fullmatch(r'wr_[a-f0-9]{32}',body['run_id'])
                    or body.get('authority') is not True or body.get('notice') != COMPOSER_PUBLISH):
                raise ValueError('Explicit publication of a tested saved definition is required.')
            wf=store.get_workflow(body['workflow_id'])
            if not wf or not wf['is_active']:raise ValueError('An active saved draft is required.')
            composer.validate_publish(wf,body['run_id'])
            current=public_changes.template(wf['id'])
        except (ValueError,TypeError,KeyError) as exc:
            raise HTTPException(400,str(exc) if isinstance(exc,ValueError) else 'Invalid test proof.') from None
        return request_public_change(request,'template',{'action':'publish','target':wf['id'],
            'revision':current['revision'],'fields':{'tags':'contract_draft,composer_test:'+body['run_id']},'reason':body.get('reason')})

    @router.get('/admin/api/workflow-composer/comparison/runs', dependencies=[Depends(require_sadmin)])
    def list_comparison_runs():
        try:result=workflow_comparison.runs()
        except (ValueError,TypeError,KeyError,sqlite3.DatabaseError):raise HTTPException(409,'Retained comparison evidence is temporarily unavailable.',headers={'Cache-Control':'no-store'}) from None
        return JSONResponse(result,headers={'Cache-Control':'no-store'})

    @router.post('/admin/api/workflow-composer/comparison', dependencies=[Depends(require_sadmin)])
    async def compare_completed_workflow_tests(request: Request):
        from starlette.concurrency import run_in_threadpool
        try:
            body=await request.json()
            result=await run_in_threadpool(workflow_comparison.compare,body)
        except ComparisonError as exc:raise HTTPException(409,str(exc),headers={'Cache-Control':'no-store'}) from None
        except (ValueError,TypeError,KeyError,sqlite3.DatabaseError):raise HTTPException(400,'Provide a valid retained same-input comparison request.',headers={'Cache-Control':'no-store'}) from None
        return JSONResponse(result,headers={'Cache-Control':'no-store'})

    @router.get('/admin/api/workflow-composer/resolved-input/runs', dependencies=[Depends(require_sadmin)])
    def list_resolved_input_runs():
        try:result=workflow_resolved_evidence.runs()
        except (ValueError,TypeError,KeyError,sqlite3.DatabaseError):raise HTTPException(409,'Retained typed-input evidence is temporarily unavailable.',headers={'Cache-Control':'no-store'}) from None
        return JSONResponse({**result,'review_preparation_profile':REVIEW_PREPARATION_PROFILE},headers={'Cache-Control':'no-store'})

    @router.post('/admin/api/workflow-composer/resolved-input', dependencies=[Depends(require_sadmin)])
    async def inspect_resolved_input(request: Request):
        from starlette.concurrency import run_in_threadpool
        try:
            body=await request.json()
            result=await run_in_threadpool(workflow_resolved_evidence.inspect,body)
        except ComparisonError as exc:raise HTTPException(409,str(exc),headers={'Cache-Control':'no-store'}) from None
        except (ValueError,TypeError,KeyError,sqlite3.DatabaseError):raise HTTPException(400,'Provide a valid retained typed-input inspection request.',headers={'Cache-Control':'no-store'}) from None
        return JSONResponse(result,headers={'Cache-Control':'no-store'})

    @router.post('/admin/api/workflow-composer/review-packet', dependencies=[Depends(require_sadmin)])
    async def prepare_workflow_review_packet(request: Request):
        from starlette.concurrency import run_in_threadpool
        headers={'Cache-Control':'no-store'}
        try:
            body=await request.json()
            if (not isinstance(body,dict) or set(body)!={'run_id'}
                    or not isinstance(body['run_id'],str) or not re.fullmatch(r'wr_[0-9a-f]{32}',body['run_id'])):
                raise ValueError()
        except (ValueError,TypeError,KeyError):
            raise HTTPException(400,'Provide one valid retained connected test reference.',headers=headers) from None
        try:
            result=await run_in_threadpool(workflow_review_packets.prepare,body)
        except ComparisonError:
            raise HTTPException(409,'Retained review material could not be verified. No worksheet was prepared.',headers=headers) from None
        except (ValueError,TypeError,KeyError,sqlite3.DatabaseError):
            raise HTTPException(409,'Retained review material is unavailable. No worksheet was prepared.',headers=headers) from None
        except Exception:
            raise HTTPException(500,'The review worksheet could not be prepared.',headers=headers) from None
        return JSONResponse(result,headers=headers)

    def controlled_pair_result(method, body=None, actor=None):
        headers={'Cache-Control':'no-store'}
        try:
            action=getattr(workflow_controlled_pairs,method)
            return action() if body is None else action(body,actor) if actor is not None else action(body)
        except (ValueError,TypeError,KeyError,sqlite3.DatabaseError):
            raise HTTPException(409,'The controlled pair request could not be verified. Refresh its options and review a new plan.',headers=headers) from None
        except Exception:
            raise HTTPException(500,'The controlled pair request is temporarily unavailable.',headers=headers) from None

    async def controlled_pair_body(request):
        try:
            body=await request.json()
            if not isinstance(body,dict):raise ValueError()
            return body
        except (ValueError,TypeError):
            raise HTTPException(400,'Provide a valid controlled pair request.',headers={'Cache-Control':'no-store'}) from None

    @router.get('/admin/api/workflow-composer/controlled-pair/options', dependencies=[Depends(require_sadmin)])
    def controlled_pair_options():
        return JSONResponse(controlled_pair_result('options'),headers={'Cache-Control':'no-store'})

    @router.post('/admin/api/workflow-composer/controlled-pair/prepare', dependencies=[Depends(require_sadmin)])
    async def prepare_controlled_pair(request:Request):
        body=await controlled_pair_body(request)
        from starlette.concurrency import run_in_threadpool
        result=await run_in_threadpool(controlled_pair_result,'prepare',body,request.state.admin_user['user_id'])
        return JSONResponse(result,headers={'Cache-Control':'no-store'})

    @router.post('/admin/api/workflow-composer/controlled-pair/execute', dependencies=[Depends(require_sadmin)])
    async def execute_controlled_pair(request:Request):
        body=await controlled_pair_body(request)
        from starlette.concurrency import run_in_threadpool
        result=await run_in_threadpool(controlled_pair_result,'execute',body,request.state.admin_user['user_id'])
        return JSONResponse(result,status_code=202,headers={'Cache-Control':'no-store'})

    @router.get('/admin/api/workflow-composer/controlled-pair/runs', dependencies=[Depends(require_sadmin)])
    def controlled_pair_runs():
        return JSONResponse(controlled_pair_result('runs'),headers={'Cache-Control':'no-store'})

    @router.post('/admin/api/workflow-composer/controlled-pair/inspect', dependencies=[Depends(require_sadmin)])
    async def inspect_controlled_pair(request:Request):
        body=await controlled_pair_body(request)
        from starlette.concurrency import run_in_threadpool
        result=await run_in_threadpool(controlled_pair_result,'inspect',body)
        return JSONResponse(result,headers={'Cache-Control':'no-store'})

    @router.post('/admin/api/workflow-composer/controlled-pair/publication-readiness', dependencies=[Depends(require_sadmin)])
    async def controlled_pair_publication_readiness(request:Request):
        body=await controlled_pair_body(request)
        from starlette.concurrency import run_in_threadpool
        result=await run_in_threadpool(controlled_pair_result,'publication_readiness',body)
        return JSONResponse(result,headers={'Cache-Control':'no-store'})

    def publication_result(method,actor,body=None,release_id=None):
        headers={'Cache-Control':'no-store'}
        try:return workflow_publication.admin(method,actor,body,release_id)
        except (ValueError,TypeError,KeyError,sqlite3.DatabaseError):
            raise HTTPException(409,'The public connection request could not be verified. Review its recorded status before retrying.',headers=headers) from None
        except Exception:
            raise HTTPException(500,'The public connection request is temporarily unavailable.',headers=headers) from None

    async def publication_action(request,method,release_id=None):
        if not publication_same_origin(request):
            raise HTTPException(403,'Use this administrator action from its original service page.',headers={'Cache-Control':'no-store'})
        try:body=await publication_body(request)
        except (ValueError,TypeError,UnicodeError,RecursionError,TimeoutError):
            raise HTTPException(400,'Provide a bounded public connection request.',headers={'Cache-Control':'no-store'}) from None
        from starlette.concurrency import run_in_threadpool
        result=await run_in_threadpool(publication_result,method,request.state.admin_user['user_id'],body,release_id)
        return JSONResponse(result,status_code=202 if method=='test' else 200,headers={'Cache-Control':'no-store'})

    @router.get('/admin/api/workflow-publications/options',dependencies=[Depends(require_sadmin)])
    def public_connection_options(request:Request):
        return JSONResponse({**publication_result('options',request.state.admin_user['user_id']),
                             'connected_sdk_profile':CONNECTED_SDK_PROFILE,
                             'connected_automation_profile':CONNECTED_AUTOMATION_PROFILE},headers={'Cache-Control':'no-store'})

    @router.post('/admin/api/workflow-publications/prepare',dependencies=[Depends(require_sadmin)])
    async def public_connection_prepare(request:Request):return await publication_action(request,'candidate')

    @router.post('/admin/api/workflow-publications/test',dependencies=[Depends(require_sadmin)])
    async def public_connection_test(request:Request):return await publication_action(request,'test')

    @router.get('/admin/api/workflow-publications/tests',dependencies=[Depends(require_sadmin)])
    def public_connection_tests(request:Request):
        return JSONResponse(publication_result('test_history',request.state.admin_user['user_id']),headers={'Cache-Control':'no-store'})

    @router.post('/admin/api/workflow-publications/inspect-test',dependencies=[Depends(require_sadmin)])
    async def public_connection_inspect_test(request:Request):return await publication_action(request,'inspect_test')

    @router.post('/admin/api/workflow-publications/prepare-publication',dependencies=[Depends(require_sadmin)])
    async def public_connection_prepare_publication(request:Request):return await publication_action(request,'publication_candidate')

    @router.post('/admin/api/workflow-publications/publish',dependencies=[Depends(require_sadmin)])
    async def public_connection_publish(request:Request):return await publication_action(request,'publish')

    @router.get('/admin/api/workflow-publications/releases',dependencies=[Depends(require_sadmin)])
    def public_connection_releases(request:Request):
        return JSONResponse(publication_result('releases',request.state.admin_user['user_id']),headers={'Cache-Control':'no-store'})

    @router.post('/admin/api/workflow-publications/releases/{release_id}/revoke',dependencies=[Depends(require_sadmin)])
    async def public_connection_revoke(release_id:str,request:Request):return await publication_action(request,'revoke',release_id)

    def connected_app_result(method,release_id,actor,body=None,app_id=None):
        try:return connected_apps.admin(method,release_id,actor,body,app_id)
        except (ValueError,TypeError,KeyError,sqlite3.DatabaseError):
            raise HTTPException(409,'The connected SDK deployment could not be verified. Review its recorded status before retrying.',headers={'Cache-Control':'no-store'}) from None
        except Exception:
            raise HTTPException(500,'The connected SDK deployment is temporarily unavailable.',headers={'Cache-Control':'no-store'}) from None

    async def connected_app_body(request):
        if not publication_same_origin(request):
            raise HTTPException(403,'Use this administrator action from its original service page.',headers={'Cache-Control':'no-store'})
        try:return await connected_app_request(request,64000)
        except (ValueError,TypeError,UnicodeError,RecursionError,TimeoutError):
            raise HTTPException(400,'Provide a bounded connected SDK deployment request.',headers={'Cache-Control':'no-store'}) from None

    @router.get('/admin/api/workflow-publications/releases/{release_id}/export-app-v13/options',dependencies=[Depends(require_sadmin)])
    def connected_app_options(release_id:str,request:Request):
        return JSONResponse(connected_app_result('options',release_id,request.state.admin_user['user_id']),headers={'Cache-Control':'no-store'})

    @router.get('/admin/api/workflow-publications/releases/{release_id}/export-app-v13/deployments',dependencies=[Depends(require_sadmin)])
    def connected_app_deployments(release_id:str,request:Request):
        return JSONResponse(connected_app_result('deployments',release_id,request.state.admin_user['user_id']),headers={'Cache-Control':'no-store'})

    @router.post('/admin/api/workflow-publications/releases/{release_id}/export-app-v13/prepare',dependencies=[Depends(require_sadmin)])
    async def connected_app_prepare(release_id:str,request:Request):
        body=await connected_app_body(request)
        from starlette.concurrency import run_in_threadpool
        result=await run_in_threadpool(connected_app_result,'prepare_admin',release_id,request.state.admin_user['user_id'],body)
        return JSONResponse(result,headers={'Cache-Control':'no-store'})

    @router.post('/admin/api/workflow-publications/releases/{release_id}/export-app-v13/deployments/{app_id}/revoke',dependencies=[Depends(require_sadmin)])
    async def connected_app_revoke(release_id:str,app_id:str,request:Request):
        body=await connected_app_body(request)
        from starlette.concurrency import run_in_threadpool
        result=await run_in_threadpool(connected_app_result,'revoke',release_id,request.state.admin_user['user_id'],body,app_id)
        log_op(request,'workflow_connection_app_v13_revoke','Connected SDK deployment revoked',details={'release_id':release_id,'app_id':app_id,'revision':result['revision']})
        return JSONResponse(result,headers={'Cache-Control':'no-store'})

    @router.post('/admin/api/workflow-publications/releases/{release_id}/export-app-v13/package',dependencies=[Depends(require_sadmin)])
    @router.post('/admin/api/workflow-publications/releases/{release_id}/export-app-v13/html',dependencies=[Depends(require_sadmin)])
    async def connected_app_package(release_id:str,request:Request):
        body=await connected_app_body(request)
        from starlette.concurrency import run_in_threadpool
        actor=request.state.admin_user['user_id']
        result=await run_in_threadpool(connected_app_result,'issue',release_id,actor,body)
        from ..admin_workflow_webapp_v13 import build_admin_package_v13
        try:
            content,filename=await run_in_threadpool(build_admin_package_v13,result['config'],result['deployment'],request.url.path.endswith('/html'))
        except Exception:
            try:
                connected_apps.core.revoke(release_id,result['deployment']['app_id'],result['deployment']['revision'],actor)
            except (ValueError,TypeError,KeyError,sqlite3.DatabaseError):
                logging.getLogger(__name__).warning('Connected SDK failed-export grant cleanup is unavailable.')
            raise HTTPException(500,'The connected SDK package could not be prepared. Review deployment history before retrying.',headers={'Cache-Control':'no-store'}) from None
        log_op(request,'workflow_connection_app_v13_export','Explicit connected SDK deployment issued',details={'release_id':release_id,'app_id':result['deployment']['app_id']})
        return Response(content,media_type='text/html' if request.url.path.endswith('/html') else 'application/zip',headers={
            'Content-Disposition':f'attachment; filename="{filename}"','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})

    async def app_v12_body(request):
        try:
            raw=bytearray()
            async with asyncio.timeout(10):
                async for chunk in request.stream():
                    raw.extend(chunk)
                    if len(raw)>200000:raise ValueError()
            body=json.loads(raw,parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(body,dict):raise ValueError()
            return body
        except (ValueError,TypeError,UnicodeError,RecursionError,TimeoutError):
            raise HTTPException(400,'Provide a bounded SDK 1.2 deployment request.',headers={'Cache-Control':'no-store'}) from None

    def app_v12_result(method,*arguments):
        try:return getattr(workflow_apps_v12,method)(*arguments)
        except (ValueError,TypeError,KeyError,sqlite3.DatabaseError):
            raise HTTPException(409,'The SDK 1.2 deployment request could not be verified. Review a new deployment plan.',headers={'Cache-Control':'no-store'}) from None
        except Exception:
            raise HTTPException(500,'The SDK 1.2 deployment request is temporarily unavailable.',headers={'Cache-Control':'no-store'}) from None

    @router.get('/admin/api/workflows/{workflow_id}/export-app-v12/options',dependencies=[Depends(require_sadmin)])
    def app_v12_options(workflow_id:int):
        return JSONResponse(app_v12_result('options',workflow_id),headers={'Cache-Control':'no-store'})

    @router.get('/admin/api/workflows/{workflow_id}/export-app-v12/deployments',dependencies=[Depends(require_sadmin)])
    def app_v12_deployments(workflow_id:int):
        return JSONResponse(app_v12_result('deployments',workflow_id),headers={'Cache-Control':'no-store'})

    @router.post('/admin/api/workflows/{workflow_id}/export-app-v12/deployments/{app_id}/revoke',dependencies=[Depends(require_sadmin)])
    async def app_v12_revoke(workflow_id:int,app_id:str,request:Request):
        body=await app_v12_body(request)
        from starlette.concurrency import run_in_threadpool
        result=await run_in_threadpool(app_v12_result,'revoke',workflow_id,app_id,body,request.state.admin_user['user_id'])
        log_op(request,'workflow_app_v12_revoke','SDK 1.2 deployment grant revoked',details={'workflow_id':workflow_id,'app_id':app_id,'revision':result['revision']})
        return JSONResponse(result,headers={'Cache-Control':'no-store'})

    @router.post('/admin/api/workflows/{workflow_id}/export-app-v12/prepare',dependencies=[Depends(require_sadmin)])
    async def app_v12_prepare(workflow_id:int,request:Request):
        body=await app_v12_body(request)
        from starlette.concurrency import run_in_threadpool
        result=await run_in_threadpool(app_v12_result,'prepare_admin',workflow_id,body,request.state.admin_user['user_id'])
        return JSONResponse(result,headers={'Cache-Control':'no-store'})

    @router.post('/admin/api/workflows/{workflow_id}/export-app-v12/package',dependencies=[Depends(require_sadmin)])
    @router.post('/admin/api/workflows/{workflow_id}/export-app-v12/html',dependencies=[Depends(require_sadmin)])
    async def app_v12_package(workflow_id:int,request:Request):
        body=await app_v12_body(request)
        from starlette.concurrency import run_in_threadpool
        result=await run_in_threadpool(app_v12_result,'export_admin',workflow_id,body,request.state.admin_user['user_id'])
        from ..admin_workflow_webapp_v12 import build_admin_package_v12
        try:
            content,filename=build_admin_package_v12(result['config'],result['deployment'],single_html=request.url.path.endswith('/html'))
        except Exception:
            try:workflow_apps_v12.revoke(workflow_id,result['deployment']['app_id'],{'revision':result['deployment']['revision']},request.state.admin_user['user_id'])
            except (ValueError,TypeError,KeyError):
                logging.getLogger(__name__).warning('SDK 1.2 failed-export grant cleanup is unavailable.')
            workflow_apps.revoke(workflow_id,result['deployment']['app_id'])
            raise HTTPException(500,'The SDK 1.2 package could not be prepared.',headers={'Cache-Control':'no-store'}) from None
        log_op(request,'workflow_app_v12_export','Explicit SDK 1.2 deployment grant issued',details={'workflow_id':workflow_id,'app_id':result['deployment']['app_id']})
        return Response(content,media_type='text/html' if request.url.path.endswith('/html') else 'application/zip',headers={
            'Content-Disposition':f'attachment; filename="{filename}"','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})

    @router.post('/admin/api/workflows/{workflow_id}/product-package', dependencies=auth)
    async def workflow_product_package(workflow_id: int, request: Request):
        from ..workflows import public_template
        from ..workflow_product_package import build_product_package
        try:body=await request.json()
        except (ValueError,TypeError):raise HTTPException(400,'Use an empty product download request.') from None
        if body!={}:raise HTTPException(400,'Product downloads do not issue grants or embed input overrides.')
        wf=store.get_workflow(workflow_id)
        projected=public_template(wf,workflows_runtime) if wf else None
        if not projected or 'product' not in projected:
            raise HTTPException(404,'A currently verified published product is required.')
        content,filename=build_product_package(projected)
        log_op(request,'workflow_product_download','Verified public product package downloaded',details={'workflow_id':workflow_id})
        return Response(content,media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="{filename}"',
            'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})

    @router.post("/admin/api/workflows/{workflow_id}/export-app", dependencies=auth)
    @router.post("/admin/api/workflows/{workflow_id}/export-app/package", dependencies=auth)
    @router.post("/admin/api/workflows/{workflow_id}/export-app/html", dependencies=auth)
    async def export_workflow_app(workflow_id: int, request: Request):
        wf = store.get_workflow(workflow_id)
        if not wf:
            raise HTTPException(404, "워크플로우를 찾을 수 없습니다.")
        req_body = {}
        try:
            req_body = await request.json()
        except Exception:
            pass
        if not isinstance(req_body, dict):
            req_body = {}

        from ..workflow_webapp import export_config
        try:
            config = export_config(wf)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if req_body.get('require_google_auth') or req_body.get('is_paid'):
            raise HTTPException(400,'This export uses the public workflow API. Authentication and payment gates are not supported.')
        if request.url.path.endswith(('/export-app/package', '/export-app/html')):
            from ..admin_workflow_webapp import build_admin_package
            try:
                deployment = workflow_apps.create(workflow_id, req_body)
            except WorkflowError as exc:
                raise HTTPException(400, str(exc)) from exc
            html = request.url.path.endswith('/export-app/html')
            try:
                archive, filename = build_admin_package(config, deployment, single_html=html)
            except Exception:
                workflow_apps.revoke(workflow_id, deployment['app_id'])
                raise
            return Response(archive, media_type='text/html' if html else 'application/zip', headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
        return {'ok':True,'config':config}

    @router.get('/admin/api/workflows/{workflow_id}/export-app/options', dependencies=auth)
    def workflow_app_options(workflow_id: int):
        try:
            workflow = workflow_apps.published(workflow_id)
        except WorkflowError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {'fields':[{k:f[k] for k in ('id','label','type')} for f in workflow_apps.candidates(workflow)],
                'deployments':[row for row in workflow_apps.list(workflow_id) if not workflow_apps_v12.consent.is_v12(row['id'])],
                'sdk_v12_profile':SDK_V12_PROFILE}

    @router.delete('/admin/api/workflows/{workflow_id}/apps/{app_id}', dependencies=auth)
    def revoke_workflow_app(workflow_id: int, app_id: str):
        if workflow_apps_v12.consent.is_v12(app_id):
            raise HTTPException(409,'Use the highest-administrator SDK 1.2 grant revision to revoke this deployment.',headers={'Cache-Control':'no-store'})
        try:
            workflow_apps.revoke(workflow_id, app_id)
        except WorkflowError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {'ok':True}

    @router.get("/admin/api/workflows/agents/alternatives", dependencies=auth)
    def get_workflow_agent_alternatives(
        agent_id: int | None = Query(None),
        category: str | None = Query(None),
        kind: str | None = Query(None),
        q: str | None = Query("", max_length=100),
        limit: int = Query(30, ge=1, le=100),
    ):
        """서비스 중지 또는 비활성화된 에이전트 노드를 대체하기 위한 동일·유사 추천 에이전트 목록을 계산하여 반환한다."""
        cur_agent = None
        target_category = category
        target_kind = kind
        target_name = ""

        if agent_id is not None:
            r = store.resource(agent_id)
            if r:
                cur_agent = dict(r)
            if cur_agent:
                target_category = target_category or cur_agent.get("category")
                target_kind = target_kind or cur_agent.get("kind")
                target_name = cur_agent.get("name") or ""

        q_clean = q.strip().lower() if q else ""

        where_clauses = ["r.active = 1", "r.health_status IN ('healthy','reachable')"]
        params = []
        if kind and kind != "all":
            where_clauses.append("r.kind = ?")
            params.append(kind)
        if target_category and target_category != "all":
            where_clauses.append("(r.category = ? OR r.category LIKE ?)")
            params.extend([target_category, f"{target_category}%"])
        if q_clean:
            where_clauses.append("(r.name LIKE ? OR r.description LIKE ? OR r.url LIKE ?)")
            q_like = f"%{q_clean}%"
            params.extend([q_like, q_like, q_like])

        where_sql = " AND ".join(where_clauses)
        sql = f"""SELECT r.id, r.kind, r.name, r.url, r.category, r.description, r.health_status,
                        r.cap_tool_count, r.price_usdc, r.eval_grade, r.eval_score, r.trial_ok,
                        r.usage_tools, r.details
                 FROM resources r
                 WHERE {where_sql}
                 ORDER BY (r.health_status='healthy') DESC, (r.trial_ok IS 1) DESC, r.eval_score DESC, r.id DESC
                 LIMIT 80"""
        with reader() as db:
            rows = _rows(db.execute(sql, tuple(params)))
            if not rows and target_category and q_clean:
                fallback_where = ["r.active = 1", "r.health_status IN ('healthy','reachable')"]
                f_params = []
                if kind and kind != "all":
                    fallback_where.append("r.kind = ?")
                    f_params.append(kind)
                fallback_where.append("(r.name LIKE ? OR r.description LIKE ? OR r.url LIKE ?)")
                q_like = f"%{q_clean}%"
                f_params.extend([q_like, q_like, q_like])
                rows = _rows(db.execute(f"""SELECT r.id, r.kind, r.name, r.url, r.category, r.description, r.health_status,
                                                    r.cap_tool_count, r.price_usdc, r.eval_grade, r.eval_score, r.trial_ok,
                                                    r.usage_tools, r.details
                                             FROM resources r
                                             WHERE {' AND '.join(fallback_where)}
                                             ORDER BY (r.health_status='healthy') DESC, (r.trial_ok IS 1) DESC, r.eval_score DESC, r.id DESC
                                             LIMIT 80""", tuple(f_params)))

        candidates = []
        # Only registered resources can be bound to executable workflow nodes.
        for row in rows:
            if agent_id is not None and row["id"] == agent_id:
                continue
            tools = []
            try:
                if row.get("usage_tools"):
                    tools = json.loads(row["usage_tools"])
                elif row.get("details"):
                    details = json.loads(row["details"])
                    tools = details.get("tools") or []
            except Exception:
                tools = []

            candidates.append({
                "id": row["id"],
                "kind": row["kind"],
                "name": row["name"],
                "url": row["url"],
                "category": row["category"],
                "description": row.get("description") or "",
                "health_status": row.get("health_status") or "unknown",
                "cap_tool_count": row.get("cap_tool_count") or len(tools),
                "price_usdc": row.get("price_usdc") or 0,
                "eval_grade": row.get("eval_grade") or "Unrated",
                "eval_score": row.get("eval_score") or 0,
                "trial_ok": row.get("trial_ok") or 0,
                "tools": tools,
                "skills": [],
                "sample_args": {},
                "is_preset": False,
            })

        scored = []
        for cand in candidates:
            if kind and cand.get("kind") != kind:
                continue

            if q_clean:
                cand_text = f"{cand['name']} {cand.get('url', '')} {cand['category']} {cand['description']} {cand['kind']}".lower()
                tool_names = " ".join([t.get("name", "").lower() for t in cand.get("tools") or [] if isinstance(t, dict)])
                if q_clean not in cand_text and q_clean not in tool_names:
                    continue

            score = 45.0
            reasons = []

            # 1. 카테고리 일치
            if target_category and cand.get("category") == target_category:
                score += 35.0
                reasons.append(f"동일 카테고리 ({cand.get('category')})")
            elif target_category and any(part in str(cand.get("category")) for part in target_category.split("_")):
                score += 15.0
                reasons.append("유사 도메인")

            # 2. 프로토콜 일치
            if target_kind and cand.get("kind") == target_kind:
                score += 20.0
                reasons.append(f"동일 프로토콜 ({cand.get('kind').upper()})")
            elif cand.get("kind") in ("mcp", "a2a"):
                score += 8.0

            # 3. 헬스 상태
            if cand.get("health_status") == "healthy":
                score += 15.0
                reasons.append("최근 상태: Healthy")
            if cand.get("trial_ok") == 1:
                score += 10.0
                reasons.append("호출 검증 통과 (Trial OK)")

            # 4. 평가 점수
            eval_score = float(cand.get("eval_score") or 0)
            score += min(15.0, eval_score * 0.15)
            if cand.get("eval_grade") in ("A", "A+", "S"):
                reasons.append(f"우수 등급 ({cand.get('eval_grade')})")

            # 5. 이름 / 텍스트 키워드 유사도
            if target_name:
                keywords = [k for k in target_name.replace("[", " ").replace("]", " ").split() if len(k) > 1]
                cand_full = f"{cand['name']} {cand['description']}".lower()
                overlap = [kw for kw in keywords if kw.lower() in cand_full]
                if overlap:
                    score += min(15.0, len(overlap) * 5.0)
                    reasons.append(f"키워드 일치 ({overlap[0]})")

            similarity_pct = min(99, max(60, int(score)))
            primary_reason = " · ".join(reasons[:2]) if reasons else "표준 프로토콜 호환"

            cand_data = dict(cand)
            cand_data["similarity_pct"] = similarity_pct
            cand_data["match_reason"] = primary_reason
            cand_data["is_recommended"] = similarity_pct >= 80
            scored.append((score, cand_data))

        scored.sort(key=lambda x: (x[0], x[1].get("eval_score", 0)), reverse=True)
        results = [c for _, c in scored[:limit]]

        return {
            "ok": True,
            "target_agent": {
                "id": agent_id,
                "name": target_name,
                "category": target_category,
                "kind": target_kind,
            } if cur_agent else None,
            "total": len(results),
            "alternatives": results,
        }

    # ---------------- 플랫폼 인증 키 & LLM 자격증명 (Credentials) ----------------
    @router.get("/admin/api/credentials", dependencies=auth)
    def list_credentials():
        creds = store.list_credentials()
        return {"ok": True, "credentials": creds}

    @router.post("/admin/api/credentials", dependencies=auth)
    async def set_credential(request: Request):
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "JSON 형식이 올바르지 않습니다.")
        if not isinstance(body, dict):
            raise HTTPException(400, "JSON 객체가 필요합니다.")
        key_name = (body.get("key_name") or "").strip()
        key_value = (body.get("key_value") or "").strip()
        provider = (body.get("provider") or "custom").strip()
        desc = (body.get("description") or "").strip()
        if not key_name or not key_value:
            raise HTTPException(400, "key_name과 key_value는 필수입니다.")
        store.set_credential(key_name, key_value, provider, desc)
        log_op(request, "CREDENTIAL_SET", "인증키 설정", target=key_name)
        return {"ok": True}

    @router.delete("/admin/api/credentials/{key_name}", dependencies=auth)
    def delete_credential(key_name: str, request: Request):
        ok = store.delete_credential(key_name)
        if not ok:
            raise HTTPException(404, "인증키를 찾을 수 없습니다.")
        log_op(request, "CREDENTIAL_DELETE", "인증키 삭제", target=key_name)
        return {"ok": True}

    @router.get("/admin/api/workflows/{workflow_id}", dependencies=auth)
    def get_workflow(workflow_id: int):
        wf = store.get_workflow(workflow_id)
        if not wf:
            raise HTTPException(404, "워크플로우를 찾을 수 없습니다.")
        return {"ok": True, "workflow": wf}

    @router.post("/admin/api/workflows", dependencies=auth)
    async def create_workflow(request: Request):
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "JSON 형식이 올바르지 않습니다.")
        if not isinstance(body, dict):
            raise HTTPException(400, "JSON 객체가 필요합니다.")
        candidate=validate_workflow_definition(body)
        if any(n.get('data',{}).get('credential_refs') for n in candidate.get('nodes',[])) and request.state.admin_user['role']!='superadmin':
            raise HTTPException(403,'Credential bindings require superadmin authorization.')
        if candidate.get('is_template'):
            return request_public_change(request, 'template', {'action':'create_public','target':None,
                'fields':{k:candidate[k] for k in ('name','description','category','trigger_type','tags','nodes','edges') if k in candidate},
                'reason':body.get('reason')})
        wf_id = store.create_workflow(candidate)
        return {"ok": True, "id": wf_id}

    @router.put("/admin/api/workflows/{workflow_id}", dependencies=auth)
    async def update_workflow(workflow_id: int, request: Request):
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "JSON 형식이 올바르지 않습니다.")
        if not isinstance(body, dict):
            raise HTTPException(400, "JSON 객체가 필요합니다.")
        wf=store.get_workflow(workflow_id)
        if not wf:raise HTTPException(404,'Workflow not found.')
        candidate=validate_workflow_definition(body,wf)
        if any(n.get('data',{}).get('credential_refs') for n in candidate.get('nodes',[])) and request.state.admin_user['role']!='superadmin':
            raise HTTPException(403,'Credential bindings require superadmin authorization.')
        if any(n.get('data',{}).get('credential_refs') for n in candidate.get('nodes',[])) and workflows_runtime.schedule(workflow_id)['enabled']:
            raise HTTPException(400,'Disable automatic runs before binding platform credentials.')
        if wf.get('is_template') or candidate.get('is_template'):
            current = public_changes.template(workflow_id)
            return request_public_change(request, 'template', {'action':'unpublish' if not candidate.get('is_template') or not candidate.get('is_active') else 'update',
                'target':workflow_id,'fields':{k:candidate[k] for k in ('name','description','category','trigger_type','tags','nodes','edges') if k in candidate},
                'revision':body.get('revision',current['revision']),'reason':body.get('reason')})
        saved_definition={k:v for k,v in candidate.items() if k not in ('id','runs_count','likes_count','forks_count','rating_avg','created_at','updated_at','steps')}
        ok = store.update_workflow(workflow_id, saved_definition)
        if not ok:
            raise HTTPException(404, "워크플로우를 수정할 수 없습니다.")
        return {"ok": True}

    @router.delete("/admin/api/workflows/{workflow_id}", dependencies=auth)
    def delete_workflow(workflow_id: int, request: Request):
        wf = store.get_workflow(workflow_id)
        if wf and wf.get('is_template'):
            current = public_changes.template(workflow_id)
            from urllib.parse import unquote
            return request_public_change(request,'template',{'action':'unpublish','target':workflow_id,'fields':{},
                'revision':current['revision'],'reason':unquote(request.headers.get('x-admin-reason',''))})
        ok = store.delete_workflow(workflow_id)
        if not ok:
            raise HTTPException(404, "삭제할 워크플로우를 찾을 수 없습니다.")
        return {"ok": True}

    @router.post('/admin/api/workflows/{workflow_id}/run', dependencies=auth)
    async def run_workflow(workflow_id: int, request: Request):
        wf=store.get_workflow(workflow_id)
        if not wf:raise HTTPException(404,'Workflow not found.')
        data=await request.json() if await request.body() else {}
        if not isinstance(data,dict) or set(data)-{'idempotency_key','nodes','edges','allow_fallback','fallback_notice','execution_profile','execution_budget_notice'}:raise HTTPException(400,'Only saved graph confirmation and explicit run options may be submitted.')
        if data.get('execution_profile')=='extended' and request.state.admin_user['role']!='superadmin':raise HTTPException(403,'Extended execution requires superadmin authorization.')
        # Runs always use a saved definition. Save edits before executing.
        if 'nodes' in data and data['nodes']!=wf['nodes'] or 'edges' in data and data['edges']!=wf['edges']:
            raise HTTPException(409,'Save the edited graph before running it.')
        if any(n.get('data',{}).get('credential_refs') for n in wf.get('nodes',[])) and request.state.admin_user['role']!='superadmin':
            raise HTTPException(403,'Credential-bound execution requires superadmin authorization.')
        try:
            user=request.state.admin_user
            principal=workflows_runtime.principal('admin',str(user['user_id']),workflow_id,role=user['role'])
            result=workflows_runtime.submit(wf,actor=user['username'],idempotency=data.get('idempotency_key'),principal=principal,
                allow_fallback=data.get('allow_fallback',False),fallback_notice=data.get('fallback_notice'),
                execution_profile=data.get('execution_profile','standard'),execution_budget_notice=data.get('execution_budget_notice'))
        except WorkflowError as exc:raise HTTPException(400,str(exc)) from exc
        return JSONResponse({'ok':True,**result},status_code=202)

    @router.get('/admin/api/workflows/runs/{run_id}', dependencies=auth)
    def workflow_run_status(run_id: str):
        try:return workflows_runtime.get(run_id)
        except WorkflowError as exc:raise HTTPException(404,str(exc)) from exc

    @router.post('/admin/api/workflows/runs/{run_id}/cancel', dependencies=auth)
    def workflow_run_cancel(run_id: str):
        try:return workflows_runtime.cancel(run_id)
        except WorkflowError as exc:raise HTTPException(404,str(exc)) from exc

    @router.get('/admin/api/workflows/{workflow_id}/runs', dependencies=auth)
    def workflow_run_history(workflow_id: int):
        return {'ok':True,'runs':workflows_runtime.history(workflow_id)}

    @router.get('/admin/api/workflows/{workflow_id}/schedule', dependencies=auth)
    def workflow_schedule(workflow_id: int):
        return {'ok':True,'schedule':workflows_runtime.schedule(workflow_id)}

    @router.put('/admin/api/workflows/{workflow_id}/schedule', dependencies=auth)
    async def workflow_schedule_save(workflow_id: int,request: Request):
        wf=store.get_workflow(workflow_id)
        if wf and any(n.get('data',{}).get('credential_refs') for n in wf.get('nodes',[])):
            raise HTTPException(400,'Scheduled and event runs cannot use platform credential bindings.')
        try:
            user=request.state.admin_user
            data=await request.json()
            if not isinstance(data,dict):raise HTTPException(400,'Provide a schedule object.')
            if data.get('delivery_authority') is True and user['role']!='superadmin':raise HTTPException(403,'Result delivery grants require superadmin authorization.')
            principal=workflows_runtime.principal('admin',str(user['user_id']),workflow_id,role=user['role'])
            return {'ok':True,'schedule':workflows_runtime.save_schedule(workflow_id,data,principal=principal)}
        except WorkflowError as exc:raise HTTPException(400,str(exc)) from exc
        except ValueError:raise HTTPException(400,'Provide a valid schedule object.') from None

    @router.post('/admin/api/workflows/{workflow_id}/destinations', dependencies=auth)
    async def workflow_destination(workflow_id: int,request: Request):
        data=await request.json()
        try:return await asyncio.to_thread(workflows_runtime.register_destination,workflow_id,data)
        except WorkflowError as exc:raise HTTPException(400,str(exc)) from exc
        except Exception as exc:raise HTTPException(400,'Inbox verification could not be delivered.') from exc

    @router.post('/admin/api/workflows/{workflow_id}/destinations/{identity}/verify', dependencies=auth)
    async def workflow_destination_verify(workflow_id: int,identity: str,request: Request):
        try:return workflows_runtime.verify_destination(workflow_id,identity,(await request.json()).get('code'))
        except WorkflowError as exc:raise HTTPException(400,str(exc)) from exc

    @router.delete('/admin/api/workflows/{workflow_id}/destinations/{identity}', dependencies=auth)
    def workflow_destination_revoke(workflow_id: int,identity: str):
        return workflows_runtime.revoke_destination(workflow_id,identity)

    # ---------------- 결제 및 코인 전자지갑 관리 (Payment & Wallet Management) ----------------
    @router.get("/admin/api/payments/overview", dependencies=auth)
    def payments_overview():
        ledger_stats = {}
        if service and hasattr(service, "ledger") and service.ledger:
            try:
                ledger_stats = service.ledger.stats()
            except Exception as e:
                log.warning("Failed to fetch ledger stats: %s", e)

        clearing_overview = {}
        reserve_audit = {}
        if front and hasattr(front, "clearinghouse") and front.clearinghouse:
            try:
                clearing_overview = front.clearinghouse.stats()
                reserve_audit = front.clearinghouse.reserve_audit()
            except Exception as e:
                log.warning("Failed to fetch clearinghouse stats: %s", e)
        else:
            clearing_overview = store.get_clearing_overview()

        # Network info
        net_info = {
            "name": "base-sepolia",
            "chain_id": 84532,
            "token_symbol": "USDC",
            "token_address": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
            "decimals": 6,
            "pay_to": getattr(service, "pay_to", None) if service else None,
        }
        if service and hasattr(service, "config") and hasattr(service.config, "network"):
            net = service.config.network
            net_info["name"] = net.name
            net_info["chain_id"] = net.chain_id
            net_info["token_address"] = net.token
            net_info["is_testnet"] = net.is_testnet

        return {
            "ok": True,
            "ledger": ledger_stats,
            "clearinghouse": clearing_overview,
            "reserve_audit": reserve_audit,
            "network": net_info,
        }

    @router.get("/admin/api/payments/ledger", dependencies=auth)
    def payments_ledger(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=100000), status: str | None = None, service_name: str | None = None):
        if service and hasattr(service, "ledger") and service.ledger:
            items, total = service.ledger.list_payments(limit=limit, offset=offset, status=status, service=service_name)
            return {"items": items, "total": total, "limit": limit, "offset": offset}
        return {"items": [], "total": 0, "limit": limit, "offset": offset}

    @router.get("/admin/api/payments/clearinghouse", dependencies=auth)
    def payments_clearinghouse(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=100000), status: str | None = None, account_id: str | None = None):
        items, total = store.list_clearing_transactions(limit=limit, offset=offset, status=status, account_id=account_id)
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    @router.get("/admin/api/payments/accounts", dependencies=auth)
    def payments_accounts(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=100000), q: str | None = Query(None, max_length=120)):
        items, total = store.list_agent_credits(limit=limit, offset=offset, q=q)
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    @router.post("/admin/api/payments/deposit", dependencies=auth)
    async def payments_deposit(request: Request):
        data = await request.json()
        account_id = str(data.get("account_id") or data.get("agent_id") or "").strip()
        amount = integer(data.get("amount", data.get("amount_credits")), "amount")
        if not account_id:
            raise HTTPException(400, "account_id is required.")
        if amount <= 0:
            raise HTTPException(400, "amount must be greater than zero.")

        try:
            if front and hasattr(front, "clearinghouse") and front.clearinghouse:
                res = front.clearinghouse.deposit(account_id, amount)
            else:
                res = store.deposit_credit(account_id, amount)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

        log_op(request, "PAYMENT_DEPOSIT", f"크레딧 충전 ({amount} micro-USDC)", target=f"account:{account_id}", details={"amount": amount})
        balance = res.get("balance") or (store.get_credit(account_id).get("balance") if hasattr(store, "get_credit") else amount)
        return {"ok": True, "balance": balance, "account": res}

    @router.post("/admin/api/payments/withdraw", dependencies=auth)
    async def payments_withdraw(request: Request):
        data = await request.json()
        account_id = str(data.get("account_id") or data.get("agent_id") or "").strip()
        amount = integer(data.get("amount", data.get("amount_credits")), "amount")
        to_address = str(data.get("to_address") or data.get("payout_address") or "").strip()
        if not account_id:
            raise HTTPException(400, "account_id is required.")
        if amount <= 0:
            raise HTTPException(400, "amount must be greater than zero.")

        try:
            if front and hasattr(front, "clearinghouse") and front.clearinghouse:
                res = front.clearinghouse.withdraw(account_id, amount, to_address)
            else:
                res = store.withdraw_credit(account_id, amount, to_address)
        except Exception as exc:
            raise HTTPException(400, str(exc))

        log_op(request, "PAYMENT_WITHDRAW", f"크레딧 출금 ({amount} micro-USDC)", target=f"account:{account_id}", details={"amount": amount, "to_address": to_address})
        remaining_balance = store.get_credit(account_id).get("balance", 0) if hasattr(store, "get_credit") else 0
        return {"ok": True, "remaining_balance": remaining_balance, "withdrawal_tx_id": res.get("tx_id"), "result": res}

    @router.post("/admin/api/payments/sweep", dependencies=auth)
    async def payments_sweep(request: Request):
        data = {}
        try:
            data = await request.json()
        except Exception:
            pass
        ttl_seconds = float(data.get("ttl_seconds") or 900)

        ledger_swept = 0
        if service and hasattr(service, "ledger") and service.ledger:
            try:
                ledger_swept = service.ledger.sweep_orphaned_pending(ttl_seconds)
            except Exception as e:
                log.warning("Ledger sweep error: %s", e)

        ch_swept = []
        if front and hasattr(front, "clearinghouse") and front.clearinghouse:
            try:
                ch_swept = front.clearinghouse.sweep_orphaned_holds(ttl_seconds)
            except Exception as e:
                log.warning("Clearinghouse sweep error: %s", e)
        else:
            ch_swept = store.sweep_orphaned_holds(ttl_seconds)

        log_op(request, "PAYMENT_SWEEP", "고아 에스크로/결제 일괄 정리", details={"ledger_swept": ledger_swept, "clearing_swept_count": len(ch_swept)})
        return {"ok": True, "ledger_swept_count": ledger_swept, "clearing_swept_ids": ch_swept}

    @router.post("/admin/api/payments/refund", dependencies=auth)
    async def payments_refund(request: Request):
        data = await request.json()
        tx_id = str(data.get("tx_id") or "").strip()
        reason = str(data.get("reason") or "Admin manual refund").strip()
        if not tx_id:
            raise HTTPException(400, "tx_id is required.")

        try:
            res = store.refund_credit(tx_id, reason=reason)
        except Exception as exc:
            raise HTTPException(400, str(exc))

        log_op(request, "PAYMENT_REFUND", f"에스크로 수동 환불 ({tx_id})", target=f"tx:{tx_id}", details={"reason": reason})
        return {"ok": True, "result": res}

    def renewal_public_summary():
        # Aggregate allowlist only: no visitor records, contact addresses or draft configuration.
        raw = visitors(q=None, tier=None, limit=1, offset=0, contact='all', protocol='', case_state='', source='live')
        visitor_keys = ('total', 'active_24h', 'new_24h', 'messages_24h', 'verified_contacts',
                        'active_task_watches', 'pending_task_watches', 'paused_task_watches')
        templates, total = store.list_workflows(limit=50, offset=0, active_only=True, is_template=1,
                                                sort_by='updated_at')
        return {'visitors': {key: (raw['stats'][key] if raw['stats'][key] is not None else 0)
                             if key in raw['stats'] else None for key in visitor_keys},
                'requests': store.get_customer_requests_summary(),
                'templates': [{key: row.get(key) for key in ('id', 'name', 'category', 'runs_count', 'updated_at')}
                              for row in templates], 'template_total': total,
                'advertising_delivery_enabled': False, 'captured_at': time.time()}

    # 리뉴얼 어드민(P1): 기존 화면과 병행. 개인 관리자 세션만 허용한다.
    from ..admin_next import install as install_admin_next
    from ..execution_authority import controls as execution_state, set_controls as save_execution_state
    from ..workspace_admin_reviewed import ReviewedCommands
    from ..workspace_admin_summaries import HealthSummaries
    from ..workspace_admin_retention import Retention
    from ..workspace_admin_accounts import AccountChanges
    from ..workspace_admin_public import PublicChanges
    retention = Retention(store)
    account_changes = AccountChanges(store)
    public_changes = PublicChanges(store, getattr(front, 'security', None) or SecurityManager(store),
                                   getattr(front, 'updates', None), validate_workflow_definition)
    from ..admin_finance_workbench import FinanceWorkbench
    finance_workbench = FinanceWorkbench(store)
    account_reviews = ReviewedCommands(store, {
        'execution_release': lambda payload, uid: save_execution_state(store, payload, uid),
        'retention_policy': retention.apply, 'admin_account_change': account_changes.apply,
        'public_service_change': public_changes.apply, 'finance_change': finance_workbench.apply})
    from ..workspace_admin_public_service import install as install_public_operations
    request_public_change, request_task_change = install_public_operations(router, store=store, authorize=authorize,
        changes=public_changes, reviews=account_reviews, log_op=log_op)
    install_admin_next(router, store=store, authorize=authorize, admin_token=admin_token,
                       overview=lambda: overview_cache.get(overview_data), reader=reader, rows=_rows, log_op=log_op,
                       agent_actions={'activate': activate, 'deactivate': deactivate, 'check': check},
                       collector_actions={'pause': pause, 'resume': resume},
                       controls={'execution': lambda: execution_state(store), 'save_execution': lambda body, uid: save_execution_state(store, body, uid),
                                 'fallback': workflows_runtime.fallback.control_status, 'save_fallback': workflows_runtime.fallback.set_control},
                       audit=lambda db, limit: admin_auth.list_audit_logs(db, limit=limit, offset=0)[0],
                       public_summary=renewal_public_summary,
                       reviews=account_reviews,
                       summaries=HealthSummaries(store), retention=retention, finance=finance_workbench)

    from ..admin_console_operations import install as install_console_operations
    install_console_operations(router, store=store, authorize=authorize, reader=reader,
                               collector=collector, crawler=crawler, vector_stats=vector_stats_data,
                               actions=actions, public_origin=front_url, engine=rag_engine, service=service, logs=logs)

    from ..workspace_admin_insights import install as install_insights
    install_insights(router,store=store,authorize=authorize,reader=reader,log_op=log_op,reviews=account_reviews)

    from ..admin_completion import install as install_completion
    install_completion(router, store=store, authorize=authorize, reader=reader)

    from ..edge_gateway.admin import install as install_edge_delivery_admin
    install_edge_delivery_admin(router, store=store, authorize=authorize, admin_token=admin_token, front=front)
    from ..workspace_admin_specialists import router_for as renewal_tools
    router.include_router(renewal_tools(store, router, catalog_tools=True))
    return router
