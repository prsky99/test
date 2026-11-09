"""HTTP endpoints for external agent ad distribution, A2A/MCP relay partners, and platform viewing."""

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .ad_relay import AdRelayGateway
from .contracts import ContractError
from .http import _error


def router_for(
    relay_gateway: AdRelayGateway,
    *,
    resolve_auth: Any | None = None,
) -> APIRouter:
    """Create FastAPI router for A2A and MCP ad distribution and relay endpoints."""
    router = APIRouter(prefix="/api/ad-coin/v2/relays")

    async def get_context(request: Request):
        if resolve_auth is None:
            raise ContractError("auth_resolver_not_configured", 503)
        return await run_in_threadpool(resolve_auth, request)

    async def require_operator(ctx):
        if relay_gateway.access is None:
            raise ContractError("operator_required", 403)
        await run_in_threadpool(relay_gateway.access.require_operator, ctx.principal)

    @router.post("/partners")
    async def register_partner(request: Request):
        try:
            ctx = await get_context(request)
            await require_operator(ctx)

            body = await request.json()
            partner = await run_in_threadpool(
                relay_gateway.register_partner,
                name=body["name"],
                protocol=body["protocol"],
                endpoint_url=body["endpoint_url"],
                fee_basis_points=int(body.get("fee_basis_points", 0)),
                operator_account_id=body["operator_account_id"],
                partner_id=body.get("partner_id"),
            )
            return JSONResponse(partner, status_code=201)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    @router.get("/partners")
    async def list_partners(request: Request):
        try:
            await require_operator(await get_context(request))
            partners = await run_in_threadpool(relay_gateway.list_partners)
            return JSONResponse({"partners": partners})
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    @router.post("/partners/{partner_id}/revoke")
    async def revoke_partner(request: Request, partner_id: str):
        try:
            ctx = await get_context(request)
            await require_operator(ctx)
            partner = await run_in_threadpool(relay_gateway.revoke_partner, partner_id)
            return JSONResponse(partner)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    @router.post("/dispatch")
    async def dispatch_ad_offer(request: Request):
        try:
            ctx = await get_context(request)
            body = await request.json()
            owner_id = str(ctx.principal.owner_id)

            result = await run_in_threadpool(
                relay_gateway.dispatch_ad_offer,
                partner_id=body["partner_id"],
                owner_id=owner_id,
                campaign_id=body["campaign_id"],
                offer_id=body["offer_id"],
                user_reward_atoms=int(body["user_reward_atoms"]),
                headline=body.get("headline", "Sponsored Recommendation"),
                summary=body.get("summary", ""),
                hop_count=int(body.get("hop_count", 1)),
                duration_seconds=int(body.get("duration_seconds", 1800)),
            )
            return JSONResponse(result, status_code=201)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    @router.get("/dispatches")
    async def list_dispatches(request: Request):
        try:
            ctx = await get_context(request)
            owner_id = str(ctx.principal.owner_id)
            dispatches = await run_in_threadpool(
                relay_gateway.list_dispatches_for_owner, owner_id
            )
            return JSONResponse({"dispatches": dispatches})
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    @router.post("/{dispatch_id}/consent")
    async def consent_dispatch(request: Request, dispatch_id: str):
        try:
            ctx = await get_context(request)
            owner_id = str(ctx.principal.owner_id)
            dispatch = await run_in_threadpool(
                relay_gateway.consent_relay_dispatch, dispatch_id, owner_id
            )
            return JSONResponse(dispatch)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    @router.get("/{dispatch_id}/view")
    async def open_viewer(request: Request, dispatch_id: str):
        try:
            relay_token = request.query_params.get("token")
            if not relay_token:
                raise ContractError("missing_relay_token", 400)
            viewer_session = await run_in_threadpool(
                relay_gateway.open_viewer_session, dispatch_id, relay_token
            )
            return JSONResponse(viewer_session)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    @router.post("/{dispatch_id}/settle")
    async def settle_dispatch(request: Request, dispatch_id: str):
        try:
            await require_operator(await get_context(request))
            dispatch = await run_in_threadpool(relay_gateway.settle_relay_dispatch, dispatch_id)
            return JSONResponse(dispatch)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    @router.post("/{dispatch_id}/reject")
    async def reject_dispatch(request: Request, dispatch_id: str):
        try:
            ctx = await get_context(request)
            owner_id = str(ctx.principal.owner_id)
            dispatch = await run_in_threadpool(
                relay_gateway.reject_dispatch, dispatch_id, owner_id
            )
            return JSONResponse(dispatch)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    return router
