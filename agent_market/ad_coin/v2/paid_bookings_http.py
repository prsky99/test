"""HTTP routes for paid Sponsored bookings (mounted only when AD_COIN_PAID_BOOKING_ENABLED is on)."""

from uuid import UUID, uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .contracts import ContractError
from .http import _error
from .identity import authorize


def router_for(commercial, bookings, *, resolve_auth) -> APIRouter:
    router = APIRouter(prefix="/api/ad-coin/v2")
    store, access = commercial.store, commercial.access

    def authority(principal, advertiser_id, operation):
        try:
            advertiser = str(UUID(advertiser_id))
        except ValueError:
            raise ContractError("unknown_resource", 404) from None
        with store.atomic():
            store.lock(*("0:authority:" + key for key in sorted({str(principal.id), advertiser})))
            current = access.current(principal, advertiser)
            access.guards.current(advertiser)
            authorize(commercial.contract, operation, current, advertiser_id=UUID(advertiser), current_epoch=current.epoch)
        return advertiser

    async def context(request, *, write):
        ctx = await run_in_threadpool(resolve_auth, request)
        if write and not ctx.principal.csrf_verified:
            raise ContractError("csrf_required", 403)
        return ctx

    async def body_of(request):
        try:
            body = await request.json()
        except ValueError:
            raise ContractError("invalid_json", 400) from None
        if not isinstance(body, dict):
            raise ContractError("invalid_json", 400)
        return body

    async def respond(call):
        try:
            return JSONResponse(await call(), headers={"Cache-Control": "no-store"})
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    base = "/advertisers/{advertiser_id}/paid-bookings"

    @router.post(base)
    async def quote(advertiser_id: str, request: Request):
        async def call():
            ctx = await context(request, write=True)
            body = await body_of(request)
            advertiser = await run_in_threadpool(authority, ctx.principal, advertiser_id, "activateCampaign")
            return await run_in_threadpool(lambda: bookings.quote(
                advertiser, campaign_id=str(body.get("campaign_id", "")), day=body.get("day"),
                task_category=body.get("task_category"), region=body.get("region")))
        return await respond(call)

    @router.post(base + "/{booking_id}/payment")
    async def payment(advertiser_id: str, booking_id: str, request: Request):
        async def call():
            ctx = await context(request, write=True)
            body = await body_of(request)
            advertiser = await run_in_threadpool(authority, ctx.principal, advertiser_id, "activateCampaign")
            return await run_in_threadpool(lambda: bookings.submit(advertiser, booking_id, body.get("tx_hash")))
        return await respond(call)

    @router.get(base)
    async def listing(advertiser_id: str, request: Request):
        async def call():
            ctx = await context(request, write=False)
            advertiser = await run_in_threadpool(authority, ctx.principal, advertiser_id, "getCampaign")
            return await run_in_threadpool(bookings.list_for, advertiser)
        return await respond(call)

    @router.get("/admin/paid-bookings")
    async def queue(request: Request):
        async def call():
            ctx = await context(request, write=False)
            return await run_in_threadpool(bookings.operator_queue, access, ctx.principal)
        return await respond(call)

    @router.post("/admin/paid-bookings/{booking_id}/decision")
    async def decide(booking_id: str, request: Request):
        async def call():
            ctx = await context(request, write=True)
            body = await body_of(request)
            return await run_in_threadpool(lambda: bookings.operator_decide(
                access, ctx.principal, booking_id, action=body.get("action"), refund_tx_hash=body.get("refund_tx_hash"),
                reason=body.get("reason")))
        return await respond(call)

    @router.get("/admin/paid-bookings/export")
    async def export(request: Request, month: str = ""):
        try:
            ctx = await context(request, write=False)
            text = await run_in_threadpool(bookings.monthly_csv, access, ctx.principal, month)
            return Response(text, media_type="text/csv", headers={
                "Cache-Control": "no-store", "Content-Disposition": 'attachment; filename="paid-bookings-%s.csv"' % month})
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    return router
