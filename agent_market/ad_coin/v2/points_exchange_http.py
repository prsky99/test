"""HTTP route for exchanging activity points for workspace credits (docs/AD_COIN_BENEFITS.md).

Only a person signed in on the site can exchange, for their own account: the customer id comes from
the site session on this request (never from the body) and must derive the same v2 owner as the
principal. Writes need the CSRF proof and an Idempotency-Key, which becomes the exchange id.
"""

import time
from uuid import UUID, uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .contracts import ContractError
from .http import _error
from .identity import Kind
from .points_exchange import PointsExchange


def router_for(store, *, resolve_auth) -> APIRouter:
    router = APIRouter(prefix="/api/ad-coin/v2")
    exchange = PointsExchange(store)

    def run(request, credits, exchange_id):
        context = resolve_auth(request)
        principal = context.principal
        if principal.kind != Kind.HUMAN or principal.owner_id is None:
            raise ContractError("human_workspace_required", 403)
        if not principal.csrf_verified:
            raise ContractError("csrf_required", 403)
        site_customer = getattr(resolve_auth, "site_customer", None)
        if site_customer is None:
            raise ContractError("site_sign_in_required", 403)
        customer_id, owner_id, _, _ = site_customer(request)
        if owner_id != str(principal.owner_id):
            raise ContractError("principal_binding_mismatch", 403)
        return exchange.request(owner_id=owner_id, customer_id=customer_id, credits=credits,
                                exchange_id=exchange_id, now_ms=int(time.time() * 1000))

    @router.post("/points-exchanges")
    async def create(request: Request):
        try:
            try:
                exchange_id = UUID(request.headers.get("idempotency-key", "")).hex
            except ValueError:
                raise ContractError("idempotency_key_required", 428) from None
            try:
                body = await request.json()
            except ValueError:
                raise ContractError("invalid_json", 400) from None
            credits = body.get("credits") if isinstance(body, dict) else None
            if type(credits) is not int:
                raise ContractError("invalid_points_exchange", 422)
            value = await run_in_threadpool(run, request, credits, exchange_id)
            return JSONResponse(value, headers={"Cache-Control": "no-store"})
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    return router
