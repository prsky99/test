"""HTTP route for the public Sponsored slot (no sign-in, no personal data, short public cache)."""

from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .contracts import ContractError
from .http import _error


def router_for(slots) -> APIRouter:
    router = APIRouter(prefix="/api/ad-coin/v2")

    @router.get("/sponsored")
    async def sponsored(request: Request, category: str = "", region: str = ""):
        try:
            body = await run_in_threadpool(slots.response, category, region)
            return JSONResponse(body, headers={"Cache-Control": "public, max-age=60", "X-Robots-Tag": "noindex"})
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    return router
