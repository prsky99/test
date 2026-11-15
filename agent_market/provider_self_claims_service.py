"""Customer routes for provider self-service claims (docs/PROVIDER_SELF_CLAIM.md).

    GET  /api/customer/provider-claims                          the customer's claims ({"available": false} while off)
    POST /api/customer/provider-claims                          {"resource_id": int, "method": "well_known"|"protocol"}
    POST /api/customer/provider-claims/{claim_id}/verify        one outside request, started by the customer
    POST /api/customer/provider-claims/{claim_id}/withdraw
    GET  /api/customer/provider-claims/resources/{rid}          read-only benefits for a covered resource
    POST /api/customer/provider-claims/resources/{rid}/corrections   {"field", "proposed", "evidence_url"?}

Every route needs the customer session (same-origin, CSRF header on writes). Until operators create the schema the
feature is off: lists are empty and writes answer 409 provider_claims_not_available.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .broker.server import RateLimiter
from .customer_identity_service import customer_actor
from .provider_self_claims import ClaimError, PostgresClaimDB, ProviderSelfClaims
from .workflow_publication_service import no_store, read_object

BASE = "/api/customer/provider-claims"


class _Off:
    backend = "none"

    def ready(self):
        return False


def service_for(store) -> ProviderSelfClaims:
    """Production: the application PostgreSQL store's connection factory, inside the claims schema. Any other
    store (SQLite runs) leaves the feature off unless a service is passed in."""
    factory = getattr(store, "_connection_factory", None)
    db = PostgresClaimDB(factory) if getattr(store, "backend", "") == "postgresql" and factory else _Off()
    return ProviderSelfClaims(db, store.resource)


def recheck_job(store, limit: int = 20, now=None) -> dict:
    """jobs step (operators wire it, about every 30 minutes): verified claims near expiry get one request each.
    Never inside the public measurement windows (:55-:10 and 03:50-05:10)."""
    import time as _time
    from .necklaces.watch import in_quiet_window
    if in_quiet_window(_time.time() if now is None else now):
        return {"skipped": "measurement_window"}
    try:
        return service_for(store).recheck_due(limit)
    except ClaimError as exc:   # busy: the next run picks the due claims up
        return {"skipped": exc.code}


def router_for(identity, store=None, service: ProviderSelfClaims | None = None):
    claims = service or service_for(store)
    router = APIRouter()
    reads, writes = RateLimiter(60), RateLimiter(12)

    def customer(request, write=False):
        if request.headers.get("authorization"):
            raise HTTPException(403, {"code": "permission_required"})
        current = customer_actor(request, identity, csrf=write)
        if not (writes if write else reads).allow(current.customer_id):
            raise HTTPException(429, {"code": "rate_limited"}, headers={"Retry-After": "60"})
        return current.customer_id

    def call(fn, *args):
        try:
            return fn(*args)
        except ClaimError as exc:
            retry = {"Retry-After": "5"} if exc.status == 503 else None
            raise HTTPException(exc.status, {"code": exc.code}, headers=retry) from None

    async def body(request, keys, optional=()):
        try:
            value = await read_object(request, 8192)
        except (ValueError, TypeError, UnicodeError, TimeoutError):
            raise HTTPException(400, {"code": "invalid_request"}) from None
        if not isinstance(value, dict) or not set(keys) <= set(value) <= set(keys) | set(optional):
            raise HTTPException(400, {"code": "invalid_request"})
        return value

    def answer(data, status=200):
        return JSONResponse({"ok": True, **data}, status_code=status, headers=no_store())

    @router.get(BASE)
    def listing(request: Request):
        return answer(call(claims.claims, customer(request)))

    @router.post(BASE)
    async def prepare(request: Request):
        who = customer(request, True)
        value = await body(request, ("resource_id", "method"))
        return answer(await run_in_threadpool(call, claims.prepare, who, value["resource_id"], value["method"]), 201)

    @router.post(BASE + "/{claim_id}/verify")
    async def verify(claim_id: str, request: Request):
        who = customer(request, True)
        return answer(await run_in_threadpool(call, claims.verify, who, claim_id))

    @router.post(BASE + "/{claim_id}/withdraw")
    async def withdraw(claim_id: str, request: Request):
        who = customer(request, True)
        return answer(await run_in_threadpool(call, claims.withdraw, who, claim_id))

    @router.get(BASE + "/resources/{rid}")
    def benefits(rid: int, request: Request):
        return answer(call(claims.benefits, customer(request), rid))

    @router.post(BASE + "/resources/{rid}/corrections")
    async def correction(rid: int, request: Request):
        who = customer(request, True)
        value = await body(request, ("field", "proposed"), ("evidence_url",))
        return answer(await run_in_threadpool(call, claims.request_correction, who, rid, value["field"],
                                              value["proposed"], value.get("evidence_url")), 201)

    return router
