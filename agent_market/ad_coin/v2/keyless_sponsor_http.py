"""HTTP routes for keyless Sponsored orders (mounted only when AD_COIN_PAID_BOOKING_ENABLED is on).

No session, cookie or CSRF: the order's read key (header X-Read-Key, shown once at creation) is the only credential.
A request marked Early-Data: 1 (RFC 8470, a possible TLS early-data replay) or carrying X-Agentcon-QA (our own
measurements) writes nothing: creation answers 425 or a dry run, a status read only reads, a payment is refused.
"""

from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .contracts import ContractError
from .http import _error

MAX_ORDER_BODY = 4096


def router_for(sponsor) -> APIRouter:
    from .qa_header import is_qa
    router = APIRouter(prefix="/api/ad-coin/v2")
    headers = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex", "Referrer-Policy": "no-referrer"}

    def early(request):
        return request.headers.get("early-data", "") == "1"

    def qa(request):
        return is_qa(request.headers.get("x-agentcon-qa"))

    def address(request):
        return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "")

    async def body_of(request):
        raw = await request.body()
        if len(raw) > MAX_ORDER_BODY:
            raise ContractError("body_too_large", 413)
        try:
            import json
            body = json.loads(raw or b"null")
        except ValueError:
            raise ContractError("invalid_json", 400) from None
        if not isinstance(body, dict):
            raise ContractError("invalid_json", 400)
        return body

    async def respond(call, status=200):
        try:
            return JSONResponse(await call(), status_code=status, headers=headers)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status, headers=headers)

    @router.post("/sponsor")
    async def create(request: Request):
        """{name, text, url, category, region, day | budget_usdc} -> order_id, status_url, read_key (shown once)."""
        if early(request):
            return JSONResponse(_error("too_early", 425, str(uuid4())), status_code=425, headers=headers)
        if request.headers.get("idempotency-key"):
            # The site's Idempotency-Key layer would keep this answer, with its read key, for 24 hours; the read key
            # is never kept anywhere, so an order is placed without that header.
            return JSONResponse(_error("idempotency_key_not_supported", 422, str(uuid4())), status_code=422,
                                headers=headers)

        async def call():
            body = await body_of(request)
            return await run_in_threadpool(lambda: sponsor.create(body, address=address(request),
                                                                  write=not qa(request)))
        return await respond(call, status=201 if not qa(request) else 200)

    @router.get("/sponsor/{order_id}")
    async def status(order_id: str, request: Request):
        async def call():
            return await run_in_threadpool(lambda: sponsor.status(
                order_id, request.headers.get("x-read-key"), write=not (early(request) or qa(request))))
        return await respond(call)

    @router.post("/sponsor/{order_id}/payment")
    async def payment(order_id: str, request: Request):
        async def call():
            body = await body_of(request)
            if early(request) or qa(request):
                await run_in_threadpool(sponsor.authenticate, order_id, request.headers.get("x-read-key"))
                raise ContractError("too_early" if early(request) else "qa_request_writes_nothing",
                                    425 if early(request) else 409)
            return await run_in_threadpool(lambda: sponsor.pay(order_id, request.headers.get("x-read-key"),
                                                               body.get("tx_hash")))
        return await respond(call)

    return router
