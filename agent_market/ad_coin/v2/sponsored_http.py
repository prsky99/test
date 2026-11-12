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
    async def sponsored(request: Request, category: str = "", region: str = "", placement: str = "explore",
                        limit: int = 2):
        """docs/AD_COIN_SPONSORED_CONTRACT.md. The region comes from the Cloudflare country header and is
        neither stored nor logged; only served counts per day, campaign, category, region and placement."""
        try:
            region = (region or request.headers.get("cf-ipcountry", "")).upper()[:2]
            # Answer every request, but count only real visitors: not Early-Data: 1 (RFC 8470, may be a TLS 0-RTT
            # replay) and not our own measurements (X-Agentcon-QA, 11-12 PM). A forged QA header only lowers
            # the sender's own count.
            counted = request.headers.get("early-data", "") != "1" and not request.headers.get("x-agentcon-qa")
            body = await run_in_threadpool(slots.response, category, region, placement, limit, counted)
            return JSONResponse(body, headers={"Cache-Control": "private, max-age=60", "Vary": "CF-IPCountry",
                                               "X-Robots-Tag": "noindex"})
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    return router
