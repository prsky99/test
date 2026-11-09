"""HTTP routes for AI AD Coin v2 agent payments and mandates."""

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from .agent_payments import AgentPaymentGateway
from .contracts import ContractError
from .http import AuthContext, _error
from .identity import Kind


def router_for(payment_gateway: AgentPaymentGateway, *, resolve_auth: Any) -> APIRouter:
    router = APIRouter(prefix="/api/ad-coin/v2/agent-payments")

    async def get_context(request: Request) -> AuthContext:
        ctx = await run_in_threadpool(resolve_auth, request)
        if not isinstance(ctx, AuthContext):
            raise ContractError("authentication_required", 401)
        return ctx

    @router.get("/mandates")
    async def list_mandates(request: Request):
        try:
            ctx = await get_context(request)
            if ctx.principal.kind != Kind.HUMAN:
                raise ContractError("human_session_required", 403)
            mandates = await run_in_threadpool(payment_gateway.get_mandates, str(ctx.principal.owner_id))
            return JSONResponse({"mandates": mandates})
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    @router.post("/mandates")
    async def create_mandate(request: Request):
        try:
            ctx = await get_context(request)
            if ctx.principal.kind != Kind.HUMAN:
                raise ContractError("human_session_required", 403)
            body = await request.json()
            mandate = await run_in_threadpool(
                payment_gateway.create_mandate,
                owner_id=str(ctx.principal.owner_id),
                agent_principal_id=body["agent_principal_id"],
                total_atoms=int(body["total_atoms"]),
                per_task_atoms=int(body["per_task_atoms"]),
                providers=body.get("providers"),
                duration_seconds=int(body.get("duration_seconds", 86400 * 30)),
            )
            return JSONResponse(mandate, status_code=201)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    @router.post("/mandates/{mandate_id}/revoke")
    async def revoke_mandate(request: Request, mandate_id: str):
        try:
            ctx = await get_context(request)
            if ctx.principal.kind != Kind.HUMAN:
                raise ContractError("human_session_required", 403)
            mandate = await run_in_threadpool(
                payment_gateway.revoke_mandate,
                mandate_id=mandate_id,
                owner_id=str(ctx.principal.owner_id),
            )
            return JSONResponse(mandate)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    @router.post("/executions/hold")
    async def hold_execution(request: Request):
        try:
            ctx = await get_context(request)
            body = await request.json()
            idem = request.headers.get("idempotency-key") or str(uuid4())

            actor = "agent" if ctx.principal.kind == Kind.AGENT else "user"
            owner_id = str(ctx.principal.owner_id)

            execution = await run_in_threadpool(
                payment_gateway.hold_execution,
                owner_id=owner_id,
                provider_id=body["provider_id"],
                task_ref=body["task_ref"],
                price_atoms=int(body["price_atoms"]),
                idem_key=idem,
                actor=actor,
                agent_principal_id=str(ctx.principal.id) if actor == "agent" else None,
                mandate_id=body.get("mandate_id"),
            )
            return JSONResponse(execution, status_code=202)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    @router.post("/executions/{execution_id}/settle")
    async def settle_execution(request: Request, execution_id: str):
        try:
            await get_context(request)
            body = await request.json()
            ok = bool(body.get("ok", True))
            result_digest = body.get("result_digest")

            execution = await run_in_threadpool(
                payment_gateway.settle_execution,
                execution_id=execution_id,
                ok=ok,
                result_digest=result_digest,
            )
            return JSONResponse(execution)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    return router
