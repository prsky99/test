"""Native administrative public-service facade; all state changes are explicit."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from .workflow_publication_service import no_store, read_object, same_origin
from .workspace_admin_reviewed import ReviewConflict, ReviewDenied, ReviewUnavailable
from .workspace_service import WorkspaceRoute

BASE = "/admin/api/v2/public/operations"
log = logging.getLogger(__name__)


def install(router, *, store, authorize, changes, reviews, log_op):
    def actor(request, write=False):
        if not same_origin(request):
            raise HTTPException(403, "동일 출처의 직원 화면에서 요청하세요.")
        user = authorize(
            request,
            request.headers.get("authorization"),
            request.headers.get("x-dashboard"),
        )
        allowed = ("superadmin",) if write else ("superadmin", "admin")
        if not user.get("is_authenticated_session") or user["role"] not in allowed:
            raise HTTPException(403, "현재 개인 직원 권한이 필요합니다.")
        request.state.admin_user = user
        return user

    def error(exc):
        if isinstance(exc, ReviewUnavailable):
            return HTTPException(409, "공통 승인 저장소를 먼저 준비하세요.")
        if isinstance(exc, ReviewDenied):
            return HTTPException(403, "현재 직원 권한으로 처리할 수 없습니다.")
        if isinstance(exc, ReviewConflict):
            return HTTPException(409, "이미 진행 중이거나 만료된 승인 요청입니다.")
        return HTTPException(409, str(exc)[:300])

    def request_change(request, domain, body):
        user = actor(request, True)
        try:
            payload, reason = changes.prepare(user, domain, body)
            request.state.audit_reason = reason
            # Stop/strengthen now; release authority is reviewed. Drafts do not publish.
            immediate = (
                changes.restrictive(payload)
                or domain == "template"
                and (
                    payload["action"] == "create"
                    or payload["action"] == "update"
                    and not payload["fields"].get("is_template")
                )
            )
            if immediate:
                log_op(
                    request,
                    "PUBLIC_OPERATION_INTENT",
                    "공개 서비스 변경 의도",
                    target=str(payload["target"]),
                    status="REQUESTED",
                    details={"domain": domain, "action": payload["action"]},
                )
                result = changes.apply(payload, user["user_id"])
                log_op(
                    request,
                    "PUBLIC_OPERATION_APPLY",
                    "공개 서비스 제한·초안 변경",
                    target=str(payload["target"]),
                    details={
                        "domain": domain,
                        "action": payload["action"],
                        "reason": reason,
                    },
                )
                return JSONResponse(
                    {
                        "ok": True,
                        "result": result,
                        "invalidate": ["public", "security", "reviews"],
                    },
                    headers=no_store(),
                )
            identity = domain + ":" + str(payload["target"])
            item = reviews.request(
                user["user_id"], "public_service_change", identity, payload, reason
            )
            log_op(
                request,
                "REVIEWED_REQUEST",
                "공개 서비스 변경 승인 요청",
                target=item["id"],
                details={"domain": domain, "action": payload["action"]},
            )
            return JSONResponse(
                {"review": item, "invalidate": ["reviews", "public"]},
                status_code=202,
                headers=no_store(),
            )
        except (ValueError, ReviewUnavailable, ReviewDenied, ReviewConflict) as exc:
            raise error(exc) from None

    def task_request(request, visitor, watch, body):
        user = actor(request, True)
        try:
            reason = body.get("reason") or request.state.__dict__.get("_state", {}).get(
                "audit_reason"
            )
            if not reason:
                from urllib.parse import unquote

                reason = unquote(request.headers.get("x-admin-reason", ""))
            payload = changes.task_request(
                user, visitor, watch, body.get("preview_token"), reason
            )
            request.state.audit_reason = payload["reason"]
            item = reviews.request(
                user["user_id"],
                "public_service_change",
                "task:" + watch,
                payload,
                payload["reason"],
            )
            log_op(
                request,
                "REVIEWED_REQUEST",
                "동의된 단건 작업 알림 승인 요청",
                target=item["id"],
                details={"watch_id": watch},
            )
            return JSONResponse(
                {"review": item, "preview_expires_at": payload["expires_at"]},
                status_code=202,
                headers=no_store(),
            )
        except (ValueError, ReviewUnavailable, ReviewDenied, ReviewConflict) as exc:
            raise error(exc) from None

    native = APIRouter(route_class=WorkspaceRoute)

    @native.get(BASE + "/options")
    def options(request: Request):
        user = actor(request)
        return {
            "can_change": user["role"] == "superadmin",
            "review_available": reviews.ready(),
            "advertising_enabled": False,
            "consent_grant_enabled": False,
            "bulk_delivery_enabled": False,
            "task_preview_seconds": 300,
        }

    @native.get(BASE + "/templates")
    def templates(
        request: Request,
        offset: int = Query(0, ge=0, le=1000000),
        q: str = Query("", max_length=200),
        category: str = Query("", max_length=100),
        is_template: int | None = Query(None, ge=0, le=1),
    ):
        actor(request)
        found, total = store.list_workflows(
            limit=100,
            offset=offset,
            active_only=False,
            q=q or None,
            category=category or None,
            is_template=is_template,
        )
        keys = (
            "id",
            "name",
            "description",
            "category",
            "is_template",
            "is_active",
            "updated_at",
            "runs_count",
        )
        return {
            "items": [{k: row.get(k) for k in keys} for row in found],
            "total": total,
            "limit": 100,
            "offset": offset,
            "has_more": offset + len(found) < total,
        }

    @native.get(BASE + "/templates/{identity}")
    def template(identity: int, request: Request):
        actor(request)
        try:
            return changes.template(identity)
        except ValueError as exc:
            raise error(exc) from None

    @native.post(BASE + "/{domain}")
    async def operation(domain: str, request: Request):
        actor(request, True)
        try:
            body = await read_object(request, 160000)
        except (ValueError, TimeoutError):
            raise HTTPException(
                400, "중복 필드 없는 제한된 JSON을 입력하세요."
            ) from None
        return request_change(request, domain, body)

    # Read-only aliases preserve source filtering and projection policies, while
    # preventing shared monitor credentials/viewers from opening contact records.
    allowed = {
        "/admin/api/sns/feed",
        "/admin/api/sns/thread",
        "/admin/api/sns/sidebar",
        "/admin/api/visitors",
        "/admin/api/needs/notifications",
        "/admin/api/security/rules",
        "/admin/api/security/status",
        "/admin/api/security/events",
    }

    async def private_read(request: Request):
        actor(request, "/source/security/" in request.url.path)

    import re

    for route in tuple(router.routes):
        if not isinstance(route, APIRoute) or route.methods != {"GET"}:
            continue
        if route.path not in allowed and not re.fullmatch(
            r"/admin/api/(?:visitors/\{vid\}|needs/notifications/\{watch_id\}|visitors/\{vid\}/task-updates/\{watch_id\}/preview)",
            route.path,
        ):
            continue
        native.add_api_route(
            BASE + "/source" + route.path.removeprefix("/admin/api"),
            route.endpoint,
            methods=["GET"],
            dependencies=[Depends(private_read), *route.dependencies],
            include_in_schema=False,
        )
    router.include_router(native)
    return request_change, task_request
