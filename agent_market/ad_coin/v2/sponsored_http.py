"""HTTP route for the public Sponsored slot (no sign-in, no personal data, short public cache)."""

from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .contracts import ContractError
from .http import _error


def router_for(slots) -> APIRouter:
    router = APIRouter(prefix="/api/ad-coin/v2")
    # Served counts are written every minute and once more at shutdown (11-12 PM), so a slot that goes down at
    # deploy keeps nothing in memory. Handlers may run more than once through nested routers; both are idempotent.
    if hasattr(slots, "start_timer"):
        router.add_event_handler("startup", slots.start_timer)
        router.add_event_handler("shutdown", slots.stop)

    @router.get("/sponsored")
    async def sponsored(request: Request, category: str = "", region: str = "", placement: str = "explore",
                        limit: int = 2, q: str = ""):
        """docs/AD_COIN_SPONSORED_CONTRACT.md. The region comes from the Cloudflare country header and is
        neither stored nor logged; only served counts per day, campaign, category, region and placement."""
        try:
            # The country comes from Cloudflare (CF-IPCountry). ?region= only steers our own measurement requests
            # (X-Agentcon-QA), which are never counted, so it cannot be used to inflate or redirect counts (11-12 PM).
            qa = bool(request.headers.get("x-agentcon-qa"))
            region = ((region if qa and region else "") or request.headers.get("cf-ipcountry", "")).upper()[:2]
            # Answer every request, but count only real visitors: not Early-Data: 1 (RFC 8470, may be a TLS 0-RTT
            # replay) and not our own measurements (X-Agentcon-QA, 11-12 PM). A forged QA header only lowers
            # the sender's own count.
            counted = request.headers.get("early-data", "") != "1" and not qa
            from .sponsored_offer import sensitive, wants_ads
            if not wants_ads(dict(request.query_params), dict(request.headers)) or sensitive(text=q[:500]):
                # ads=none, or an advice-seeking task (q is only read here, never stored or logged): no ad
                return JSONResponse({"label": "Sponsored", "reward": None, "placement": placement, "cards": []},
                                    headers={"Cache-Control": "private, max-age=60", "Vary": "CF-IPCountry",
                                             "X-Robots-Tag": "noindex"})
            body = await run_in_threadpool(slots.response, category, region, placement, limit, counted)
            return JSONResponse(body, headers={"Cache-Control": "private, max-age=60", "Vary": "CF-IPCountry",
                                               "X-Robots-Tag": "noindex"})
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    def region_of(request, region):
        qa = bool(request.headers.get("x-agentcon-qa"))
        return ((region if qa and region else "") or request.headers.get("cf-ipcountry", "")).upper()[:2]

    @router.get("/sponsored/offer")
    async def sponsored_offer(request: Request, category: str = "", region: str = "", surface: str = "rest",
                              q: str = ""):
        """Agent ads (A): the one `sponsored` object for MCP, A2A and REST answers, after the organic results.
        Facts (grade, report, health) are attached by the response surface; this route never reads them."""
        from .sponsored import SITE_CATEGORIES
        from .sponsored_offer import SURFACES, agent_block, approved_offer, sensitive, wants_ads
        headers = {"Cache-Control": "private, max-age=60", "Vary": "CF-IPCountry", "X-Robots-Tag": "noindex"}
        try:
            if surface not in SURFACES:
                raise ContractError("unsupported_surface", 422)
            where = region_of(request, region)
            if not wants_ads(dict(request.query_params), dict(request.headers)) or sensitive(category, q[:500]):
                return JSONResponse({"sponsored": None}, headers=headers)
            body = await run_in_threadpool(slots.response, category, where, "explore", 2, False)
            mapped = SITE_CATEGORIES.get(category, category)
            for card in body["cards"]:
                offer = await run_in_threadpool(approved_offer, slots.store, card["id"])
                if offer:
                    block = agent_block(card, offer, category=mapped, region=where)
                    block["click_url"] = "/api/ad-coin/v2/sponsored/click/%s?surface=%s&category=%s" % (
                        card["id"], surface, category)
                    return JSONResponse({"sponsored": block}, headers=headers)
            return JSONResponse({"sponsored": None}, headers=headers)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    @router.get("/sponsored/click/{campaign_id}")
    async def sponsored_click(campaign_id: str, request: Request, surface: str = "explore", category: str = "",
                              region: str = ""):
        """Counts a click on the server (no cookie, no person) and sends the visitor to the offer's endpoint, or to
        the advertising page when the campaign has no approved offer. Only campaigns shown right now are counted."""
        from fastapi.responses import RedirectResponse
        from .sponsored import SITE_CATEGORIES
        from .sponsored_offer import SURFACES, approved_offer, count_click
        target = "/advertise"
        try:
            where = region_of(request, region)
            mapped = SITE_CATEGORIES.get(category, category)
            shown = await run_in_threadpool(slots.cards, mapped, where) if mapped in slots.taxonomy else []
            if surface in SURFACES and any(card["id"] == campaign_id for card in shown):
                from .sponsored_offer import public_endpoint
                offer = await run_in_threadpool(approved_offer, slots.store, campaign_id)
                # Only the approved offer's endpoint, and only while it still resolves to public addresses
                # (check_public_url again at redirect time). The target never comes from the request.
                if offer and await run_in_threadpool(public_endpoint, offer["endpoint"]):
                    target = offer["endpoint"]
                if target != "/advertise" and not request.headers.get("x-agentcon-qa"):
                    await run_in_threadpool(lambda: count_click(slots.store, campaign_id, category=mapped, region=where,
                                                                surface=surface))
        except ContractError:
            pass
        return RedirectResponse(target, status_code=302, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})

    return router
