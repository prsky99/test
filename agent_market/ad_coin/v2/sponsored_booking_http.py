"""HTTP routes for Sponsored day bookings paid with coins (coin economy step 3).

Advertisers book and cancel with the same authority as activating a campaign (it spends their
coins) and need the CSRF proof; listing uses the campaign read authority. Platform staff
(platform.operate) can return a day's coins after an outage on the platform side.
"""

from uuid import UUID, uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .contracts import ContractError
from .http import _error
from .identity import authorize


def router_for(commercial, bookings, *, resolve_auth=None) -> APIRouter:
    router = APIRouter(prefix="/api/ad-coin/v2")
    store = commercial.store

    async def context(request):
        if resolve_auth is None:
            raise ContractError("auth_resolver_not_configured", 503)
        return await run_in_threadpool(resolve_auth, request)

    def advertiser_authority(principal, advertiser_id, operation):
        try:
            advertiser_uuid = UUID(advertiser_id)
        except ValueError:
            raise ContractError("unknown_resource", 404) from None
        with store.atomic():
            store.lock(*("0:authority:" + key for key in sorted({str(principal.id), str(advertiser_uuid)})))
            current = commercial.access.current(principal, str(advertiser_uuid))
            commercial.access.guards.current(str(advertiser_uuid))
            authorize(commercial.contract, operation, current, advertiser_id=advertiser_uuid,
                      current_epoch=current.epoch)
        return str(advertiser_uuid)

    async def body_of(request):
        try:
            body = await request.json()
        except ValueError:
            raise ContractError("invalid_json", 400) from None
        if not isinstance(body, dict):
            raise ContractError("invalid_json", 400)
        return body

    def request_id_of(request):
        try:
            return UUID(request.headers.get("idempotency-key", "")).hex
        except ValueError:
            raise ContractError("idempotency_key_required", 428) from None

    async def respond(call):
        try:
            return JSONResponse(await call(), status_code=200, headers={"Cache-Control": "no-store"})
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    base = "/advertisers/{advertiser_id}/sponsored-bookings"

    @router.post(base)
    async def book(advertiser_id: str, request: Request):
        async def call():
            ctx = await context(request)
            body = await body_of(request)
            request_id = request_id_of(request)
            advertiser = await run_in_threadpool(advertiser_authority, ctx.principal, advertiser_id, "activateCampaign")
            return await run_in_threadpool(
                lambda: bookings.book(advertiser, campaign_id=str(body.get("campaign_id", "")),
                                      day=body.get("day"), task_category=body.get("task_category"),
                                      region=body.get("region"), request_id=request_id))
        return await respond(call)

    @router.get(base)
    async def listing(advertiser_id: str, request: Request):
        async def call():
            ctx = await context(request)
            advertiser = await run_in_threadpool(advertiser_authority, ctx.principal, advertiser_id, "getCampaign")
            return await run_in_threadpool(bookings.list, advertiser)
        return await respond(call)

    @router.post(base + "/{booking_id}/cancel")
    async def cancel(advertiser_id: str, booking_id: str, request: Request):
        async def call():
            ctx = await context(request)
            advertiser = await run_in_threadpool(advertiser_authority, ctx.principal, advertiser_id, "activateCampaign")
            return await run_in_threadpool(lambda: bookings.cancel(advertiser, booking_id))
        return await respond(call)

    @router.post("/admin/sponsored-bookings/{booking_id}/refund")
    async def operator_refund(booking_id: str, request: Request):
        async def call():
            ctx = await context(request)
            await run_in_threadpool(commercial.access.require_operator, ctx.principal)
            if not ctx.principal.csrf_verified:
                raise ContractError("csrf_required", 403)
            body = await body_of(request)
            return await run_in_threadpool(
                lambda: bookings.operator_refund(ctx.principal, booking_id, reason=body.get("reason")))
        return await respond(call)

    return router
