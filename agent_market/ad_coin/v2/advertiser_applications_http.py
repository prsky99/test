"""HTTP routes for advertiser applications (signed-in person) and their approval (platform operator)."""

from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from . import advertiser_applications as applications
from .contracts import ContractError
from .economy import CoinEconomy
from .http import _error


def router_for(commercial, *, resolve_auth) -> APIRouter:
    router = APIRouter(prefix="/api/ad-coin/v2")
    access = commercial.access
    economy = CoinEconomy(commercial.store, commercial.ledger, access)

    async def write_context(request):
        ctx = await run_in_threadpool(resolve_auth, request)
        if not ctx.principal.csrf_verified:
            raise ContractError("csrf_required", 403)
        try:
            body = await request.json()
        except ValueError:
            raise ContractError("invalid_json", 400) from None
        if not isinstance(body, dict):
            raise ContractError("invalid_json", 400)
        return ctx, body

    async def respond(call):
        try:
            return JSONResponse(await call(), headers={"Cache-Control": "no-store"})
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    @router.post("/advertiser-applications")
    async def apply(request: Request):
        async def call():
            ctx, body = await write_context(request)
            return await run_in_threadpool(lambda: applications.apply(
                access, ctx.principal, display_name=body.get("display_name"), listing_url=body.get("listing_url")))
        return await respond(call)

    @router.get("/admin/applications")
    async def pending(request: Request):
        async def call():
            ctx = await run_in_threadpool(resolve_auth, request)
            return await run_in_threadpool(applications.pending, access, ctx.principal)
        return await respond(call)

    @router.post("/admin/applications/{application_id}/decision")
    async def decide(application_id: str, request: Request):
        async def call():
            ctx, body = await write_context(request)
            approve = body.get("approve")
            if type(approve) is not bool:
                raise ContractError("invalid_application_decision", 422)
            return await run_in_threadpool(lambda: applications.decide(
                access, economy, ctx.principal, application_id, approve=approve, reason=body.get("reason", "")))
        return await respond(call)

    return router
