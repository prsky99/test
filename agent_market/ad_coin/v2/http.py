"""Opt-in partial commercial router. A trusted credential resolver is mandatory."""

from dataclasses import dataclass, field
import inspect
from uuid import uuid4

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from ..db import PoolBusy
from .commercial import PUBLIC_READS, READS, WRITES, etag
from .contracts import ContractError, MAX_BODY
from .fresh import fingerprint
from .identity import Kind, Principal


@dataclass(frozen=True)
class AuthContext:
    principal: Principal
    session_hash: str | None = field(default=None, repr=False)

    def __post_init__(self):
        if not isinstance(self.principal, Principal):
            raise ContractError("invalid_principal", 403)
        if self.principal.kind == Kind.HUMAN:
            fingerprint(self.session_hash)


def _error(code, status, request_id):
    retryable = status in (429, 503)
    action = (
        "reauthenticate"
        if status in (401, 403)
        else "refresh_resource"
        if status in (404, 409)
        else "wait"
        if retryable
        else "contact_support"
        if status >= 500
        else "do_not_retry"
    )
    return {
        "error": {
            "code": code,
            "message": "The request could not be completed.",
            "request_id": request_id,
            "retryable": retryable,
            "recovery": {
                "action": action,
                "operation_id": None,
                "retry_after_seconds": 1 if retryable else None,
            },
        }
    }


def router_for(service, *, resolve_auth, include_workspace=False):
    """Resolver verifies session/CSRF or reviewer token+TLS independently of request claims.

    No default credentials, forwarding-header TLS inference, credential provisioning,
    mint route, or automatic mounting into the public concierge is provided here.
    """
    if not callable(resolve_auth):
        raise ContractError("credential_resolver_required", 503)
    if type(include_workspace) is not bool:
        raise ContractError("invalid_workspace_flag", 503)
    router = APIRouter(prefix="/api/ad-coin/v2")

    def handler(operation):
        async def endpoint(request: Request):
            request_id = str(uuid4())
            headers = {
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "X-AIAC-Contract": "v6.2",
                "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
            }
            try:
                security_headers = {
                    b"authorization",
                    b"cookie",
                    b"x-csrf-token",
                    b"x-aiac-contract",
                    b"content-type",
                    b"content-encoding",
                    b"content-length",
                    b"idempotency-key",
                    b"if-match",
                }
                seen = set()
                for name, _ in request.scope["headers"]:
                    if name in security_headers and name in seen:
                        raise ContractError("duplicate_security_header")
                    seen.add(name)
                if request.url.query:
                    if operation != "getReportingStatus":
                        raise ContractError("query_parameters_forbidden")
                    allowed_queries = {"limit", "cursor"}
                    if not set(request.query_params.keys()) <= allowed_queries:
                        raise ContractError("query_parameters_forbidden")
                if request.headers.get("authorization") and request.headers.get(
                    "cookie"
                ):
                    raise ContractError("mixed_credentials", 403)
                is_public = operation in PUBLIC_READS
                has_credentials = bool(
                    request.headers.get("authorization")
                    or request.headers.get("cookie")
                )
                if not is_public or has_credentials:
                    context = await run_in_threadpool(resolve_auth, request)
                    if inspect.isawaitable(context):
                        context = await context
                    if not isinstance(context, AuthContext):
                        raise ContractError("authentication_required", 401)
                else:
                    context = None
                if operation in WRITES:
                    if context is None:
                        raise ContractError("authentication_required", 401)
                    body = bytearray()
                    async for chunk in request.stream():
                        if len(body) + len(chunk) > MAX_BODY:
                            raise ContractError("body_too_large", 413)
                        body.extend(chunk)
                    value = await run_in_threadpool(
                        service.write,
                        operation,
                        context.principal,
                        bytes(body),
                        key=request.headers.get("idempotency-key"),
                        path_parameters=request.path_params,
                        if_match=request.headers.get("if-match"),
                        session_hash=context.session_hash,
                        contract_version=request.headers.get("x-aiac-contract"),
                        content_type=request.headers.get("content-type", ""),
                        content_encoding=request.headers.get(
                            "content-encoding", "identity"
                        ),
                    )
                else:
                    value = await run_in_threadpool(
                        service.read,
                        operation,
                        context.principal if context is not None else None,
                        path_parameters=request.path_params,
                        query_parameters=dict(request.query_params)
                        if request.url.query
                        else None,
                    )
                if "version" in value:
                    headers["ETag"] = etag(value)
                success_status = (
                    202
                    if "202" in service.contract.operation(operation)["responses"]
                    else 200
                )
                return JSONResponse(value, status_code=success_status, headers=headers)
            except ContractError as exc:
                return JSONResponse(
                    _error(exc.code, exc.status, request_id),
                    status_code=exc.status,
                    headers=headers,
                )
            except PoolBusy:
                return JSONResponse(
                    _error("service_busy", 503, request_id),
                    status_code=503,
                    headers=headers,
                )
            except Exception:
                # Exception text may contain SQL or credentials; never include it in a response.
                return JSONResponse(
                    _error("service_error", 500, request_id),
                    status_code=500,
                    headers=headers,
                )

        return endpoint

    for operation in sorted(READS | WRITES):
        method, path, _ = service.contract._operations[operation]
        router.add_api_route(
            path,
            handler(operation),
            methods=[method],
            operation_id=operation,
            include_in_schema=False,
        )
    if include_workspace:
        from .workspace import router_for as workspace_router

        root = APIRouter()
        root.include_router(router)
        root.include_router(workspace_router(service, resolve_auth=resolve_auth))
        return root
    return router
