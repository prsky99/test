"""HTTP endpoints for advertiser platform advancement: multi-stage rewards,

A/B experiments, conversions, funnel analytics, budget pacing, and market benchmarks.
"""

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .advertiser_platform import AdvertiserPlatformGateway
from .contracts import ContractError
from .http import _error


def router_for(
    platform_gateway: AdvertiserPlatformGateway,
    *,
    resolve_auth: Any | None = None,
) -> APIRouter:
    """Create FastAPI router for advanced advertiser platform and multi-stage reward endpoints."""
    router = APIRouter(prefix="/api/ad-coin/v2/advertiser")

    async def get_context(request: Request):
        if resolve_auth is None:
            raise ContractError("auth_resolver_not_configured", 503)
        return await run_in_threadpool(resolve_auth, request)

    # -------------------------------------------------------------------------
    # 1. Multi-Stage Rewards
    # -------------------------------------------------------------------------

    @router.post("/stages/claim")
    async def claim_stage_reward(request: Request):
        try:
            ctx = await get_context(request)
            body = await request.json()
            claim = await run_in_threadpool(
                platform_gateway.claim_stage_reward,
                offer_id=body["offer_id"],
                owner_id=str(ctx.principal.owner_id),
                stage_type=body["stage_type"],
                evidence=body.get("evidence", {}),
            )
            return JSONResponse(claim, status_code=201)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    @router.get("/stages/{offer_id}")
    async def list_stages(offer_id: str, request: Request):
        try:
            await get_context(request)
            claims = await run_in_threadpool(platform_gateway.list_stage_claims_for_offer, offer_id)
            return JSONResponse({"offer_id": offer_id, "stages": claims}, status_code=200)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    # -------------------------------------------------------------------------
    # 2. Campaign A/B Experiments
    # -------------------------------------------------------------------------

    @router.post("/campaigns/{campaign_id}/experiments")
    async def create_experiment(campaign_id: str, request: Request):
        try:
            ctx = await get_context(request)
            body = await request.json()
            exp = await run_in_threadpool(
                platform_gateway.create_experiment,
                advertiser_id=str(ctx.principal.owner_id),
                campaign_id=campaign_id,
                name=body["name"],
                variants=body["variants"],
            )
            return JSONResponse(exp, status_code=201)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    @router.get("/campaigns/{campaign_id}/experiments")
    async def list_experiments(campaign_id: str, request: Request):
        try:
            await get_context(request)
            experiments = await run_in_threadpool(platform_gateway.list_experiments, campaign_id)
            return JSONResponse({"campaign_id": campaign_id, "experiments": experiments}, status_code=200)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    @router.get("/experiments/{experiment_id}")
    async def get_experiment(experiment_id: str, request: Request):
        try:
            await get_context(request)
            exp = await run_in_threadpool(platform_gateway.get_experiment, experiment_id)
            return JSONResponse(exp, status_code=200)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    @router.post("/experiments/{experiment_id}/route")
    async def route_variant(experiment_id: str, request: Request):
        try:
            ctx = await get_context(request)
            variant = await run_in_threadpool(
                platform_gateway.route_variant_for_user,
                experiment_id,
                str(ctx.principal.owner_id),
            )
            return JSONResponse({"experiment_id": experiment_id, "assigned_variant": variant}, status_code=200)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    # -------------------------------------------------------------------------
    # 3. Conversion Measurement & Attribution
    # -------------------------------------------------------------------------

    @router.post("/conversions")
    async def record_conversion(request: Request):
        try:
            ctx = await get_context(request)
            body = await request.json()
            conv = await run_in_threadpool(
                platform_gateway.record_conversion,
                advertiser_id=str(ctx.principal.owner_id),
                campaign_id=body["campaign_id"],
                offer_id=body["offer_id"],
                owner_id=body.get("owner_id", str(ctx.principal.owner_id)),
                conversion_event=body["conversion_event"],
                value_atoms=int(body.get("value_atoms", 0)),
                order_id=body.get("order_id"),
                attribution_window_seconds=int(body.get("attribution_window_seconds", 2592000)),
            )
            return JSONResponse(conv, status_code=201)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    # -------------------------------------------------------------------------
    # 4. Performance Analytics & Funnel Reporting
    # -------------------------------------------------------------------------

    @router.get("/campaigns/{campaign_id}/analytics")
    async def get_analytics(campaign_id: str, request: Request):
        try:
            ctx = await get_context(request)
            analytics = await run_in_threadpool(
                platform_gateway.get_campaign_analytics,
                str(ctx.principal.owner_id),
                campaign_id,
            )
            return JSONResponse(analytics, status_code=200)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    # -------------------------------------------------------------------------
    # 5. Budget Optimization & Pacing
    # -------------------------------------------------------------------------

    @router.get("/campaigns/{campaign_id}/optimization")
    async def get_optimization(campaign_id: str, request: Request):
        try:
            ctx = await get_context(request)
            optimization = await run_in_threadpool(
                platform_gateway.get_budget_optimization,
                str(ctx.principal.owner_id),
                campaign_id,
            )
            return JSONResponse(optimization, status_code=200)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    # -------------------------------------------------------------------------
    # 6. Market Statistics & Category Benchmarks
    # -------------------------------------------------------------------------

    @router.get("/market-benchmarks")
    async def get_benchmarks(category: str | None = Query(None)):
        try:
            benchmarks = await run_in_threadpool(platform_gateway.get_market_benchmarks, category)
            return JSONResponse(benchmarks, status_code=200)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    return router
