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
    from .advertiser_applications import welcome_after_payment
    from .economy import CoinEconomy
    economy = CoinEconomy(store, commercial.ledger, access)

    def paid_then_welcome(advertiser, result):
        """PM 11:5x: the welcome grant follows the first confirmed USDC payment; never blocks the answer."""
        try:
            welcome_after_payment(store, economy, advertiser)
        except Exception:                                   # the grant is retried on the next visit
            pass
        return result

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
            return await run_in_threadpool(lambda: paid_then_welcome(
                advertiser, bookings.submit(advertiser, booking_id, body.get("tx_hash"))))
        return await respond(call)

    @router.get(base)
    async def listing(advertiser_id: str, request: Request):
        async def call():
            ctx = await context(request, write=False)
            advertiser = await run_in_threadpool(authority, ctx.principal, advertiser_id, "getCampaign")
            listed = await run_in_threadpool(bookings.list_for, advertiser)
            if request.headers.get("early-data", "") == "1":
                return listed                      # 11-16 (0-RTT): a possibly replayed GET only reads
            return await run_in_threadpool(lambda: paid_then_welcome(advertiser, listed))
        return await respond(call)

    # Custom plans (user decision 11-15): the advertiser names a budget and audiences, picks a proposed plan and pays
    # it once. Proposals work before the plan tables exist; quoting needs them (409 plans_not_open until then).
    from .paid_plans import PaidPlans
    plans = PaidPlans(bookings)
    plans_base = "/advertisers/{advertiser_id}/paid-plans"

    @router.post(plans_base + "/options")
    async def plan_options(advertiser_id: str, request: Request):
        async def call():
            ctx = await context(request, write=True)
            body = await body_of(request)
            advertiser = await run_in_threadpool(authority, ctx.principal, advertiser_id, "activateCampaign")
            return await run_in_threadpool(lambda: plans.options(
                advertiser, campaign_id=str(body.get("campaign_id", "")), budget_usdc=body.get("budget_usdc"),
                categories=body.get("task_categories"), regions=body.get("regions")))
        return await respond(call)

    @router.post(plans_base)
    async def plan_quote(advertiser_id: str, request: Request):
        async def call():
            ctx = await context(request, write=True)
            body = await body_of(request)
            advertiser = await run_in_threadpool(authority, ctx.principal, advertiser_id, "activateCampaign")
            return await run_in_threadpool(lambda: plans.quote(
                advertiser, campaign_id=str(body.get("campaign_id", "")), items=body.get("items")))
        return await respond(call)

    @router.post(plans_base + "/{plan_id}/payment")
    async def plan_payment(advertiser_id: str, plan_id: str, request: Request):
        async def call():
            ctx = await context(request, write=True)
            body = await body_of(request)
            advertiser = await run_in_threadpool(authority, ctx.principal, advertiser_id, "activateCampaign")
            return await run_in_threadpool(lambda: paid_then_welcome(
                advertiser, plans.submit(advertiser, plan_id, body.get("tx_hash"))))
        return await respond(call)

    @router.get(plans_base)
    async def plan_listing(advertiser_id: str, request: Request):
        async def call():
            ctx = await context(request, write=False)
            advertiser = await run_in_threadpool(authority, ctx.principal, advertiser_id, "getCampaign")
            return await run_in_threadpool(plans.list, advertiser)
        return await respond(call)

    @router.get("/admin/paid-plans")
    async def plan_queue(request: Request):
        async def call():
            ctx = await context(request, write=False)
            return await run_in_threadpool(plans.operator_queue, access, ctx.principal)
        return await respond(call)

    @router.post("/admin/paid-plans/{plan_id}/decision")
    async def plan_decide(plan_id: str, request: Request):
        async def call():
            ctx = await context(request, write=True)
            body = await body_of(request)
            return await run_in_threadpool(lambda: plans.operator_decide(
                access, ctx.principal, plan_id, action=body.get("action"), refund_tx_hash=body.get("refund_tx_hash"),
                reason=body.get("reason"), sanctions_ack=body.get("sanctions_ack") is True))
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
                reason=body.get("reason"), sanctions_ack=body.get("sanctions_ack") is True))
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
