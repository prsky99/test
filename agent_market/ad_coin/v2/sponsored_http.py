"""HTTP route for the public Sponsored slot (no sign-in, no personal data, short public cache)."""

from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .contracts import ContractError
from .http import _error


CLICK_DEDUP_SECONDS = 60
CLICK_MEMORY = 20_000


def router_for(slots, offers=None) -> APIRouter:
    """offers: campaign id -> approved offer from memory (AgentOfferProvider, whose refresh already ran
    check_public_url), so the offer and click routes read no database and resolve no DNS per request (R39)."""
    from .qa_header import is_qa
    from .sponsored_offer import VARY
    router = APIRouter(prefix="/api/ad-coin/v2")
    recent_clicks = {}
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
            qa = is_qa(request.headers.get("x-agentcon-qa"))
            region = ((region if qa and region else "") or request.headers.get("cf-ipcountry", "")).upper()[:2]
            # Answer every request, but count only real visitors: not Early-Data: 1 (RFC 8470, may be a TLS 0-RTT
            # replay) and not our own measurements (X-Agentcon-QA, 11-12 PM). A forged QA header only lowers
            # the sender's own count.
            counted = request.headers.get("early-data", "") != "1" and not qa
            from .sponsored_offer import sensitive
            if sensitive(text=q[:500]):
                # an advice-seeking task (q is only read here, never stored or logged): no ad. There is no opt-out:
                # ads are always shown (user 11-15); an `ads` parameter or header is ignored.
                from .sponsored import AD_DISCLOSURE, DISCLOSURE
                return JSONResponse({"label": "Sponsored", "disclosure": DISCLOSURE, "ad_disclosure": AD_DISCLOSURE,
                                     "reward": None, "placement": placement, "cards": []},
                                    headers={"Cache-Control": "private, max-age=60", "Vary": VARY,
                                             "X-Robots-Tag": "noindex"})
            body = await run_in_threadpool(slots.response, category, region, placement, limit, counted)
            return JSONResponse(body, headers={"Cache-Control": "private, max-age=60", "Vary": VARY,
                                               "X-Robots-Tag": "noindex"})
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    def region_of(request, region):
        qa = is_qa(request.headers.get("x-agentcon-qa"))
        return ((region if qa and region else "") or request.headers.get("cf-ipcountry", "")).upper()[:2]

    @router.get("/sponsored/offer")
    async def sponsored_offer(request: Request, category: str = "", region: str = "", surface: str = "rest",
                              q: str = ""):
        """Agent ads (A): the one `sponsored` object for MCP, A2A and REST answers, after the organic results.
        Facts (grade, report, health) are attached by the response surface; this route never reads them."""
        from .sponsored import SITE_CATEGORIES
        from .sponsored_offer import SURFACES, agent_block, approved_offer, sensitive
        headers = {"Cache-Control": "private, max-age=60", "Vary": VARY, "X-Robots-Tag": "noindex"}
        try:
            if surface not in SURFACES:
                raise ContractError("unsupported_surface", 422)
            where = region_of(request, region)
            # Always 200: no ad is a normal answer, never an outage (PM 11-14). reason says why the slot is empty.
            if sensitive(category, q[:500]):
                return JSONResponse({"sponsored": None, "reason": "sensitive_topic"}, headers=headers)
            mapped = SITE_CATEGORIES.get(category, category)
            if mapped not in slots.taxonomy:                   # an unknown or missing category: no ad, not an error
                return JSONResponse({"sponsored": None, "reason": "no_offer"}, headers=headers)
            body = await run_in_threadpool(slots.response, category, where, "explore", 2, False)
            for card in body["cards"]:
                offer = offers(card["id"]) if offers else await run_in_threadpool(approved_offer, slots.store, card["id"])
                if offer:
                    block = agent_block(card, offer, category=mapped, region=where)
                    block["click_url"] = "/api/ad-coin/v2/sponsored/click/%s?surface=%s&category=%s" % (
                        card["id"], surface, category)
                    return JSONResponse({"sponsored": block}, headers=headers)
            return JSONResponse({"sponsored": None, "reason": "no_offer"}, headers=headers)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    def first_click(request, campaign_id):
        """One counted click per address and campaign a minute (R39); the address is kept hashed, in memory only."""
        import hashlib
        import time as _time
        address = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "")
        minute = int(_time.time() // CLICK_DEDUP_SECONDS)
        key = (hashlib.sha256((address + "|" + str(minute)).encode()).hexdigest()[:16], campaign_id, minute)
        if key in recent_clicks:
            return False
        if len(recent_clicks) >= CLICK_MEMORY:
            for old in [k for k in recent_clicks if k[2] < minute]:
                recent_clicks.pop(old, None)
            if len(recent_clicks) >= CLICK_MEMORY:
                recent_clicks.clear()
        recent_clicks[key] = True
        return True

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
                # Only the approved offer's endpoint, and only while it resolves to public addresses. With the
                # provider that check ran at its last refresh (at most 30 s ago); the target never comes from the
                # request.
                if offers:
                    offer = offers(campaign_id)
                else:
                    offer = await run_in_threadpool(approved_offer, slots.store, campaign_id)
                    offer = offer if offer and await run_in_threadpool(public_endpoint, offer["endpoint"]) else None
                if offer:
                    target = offer["endpoint"]
                # 11-16 (0-RTT): a request that may be a TLS early-data replay (RFC 8470, Early-Data: 1) still gets
                # its redirect but is never counted, like the impression count above
                if target != "/advertise" and not is_qa(request.headers.get("x-agentcon-qa")) \
                        and request.headers.get("early-data", "") != "1" and first_click(request, campaign_id):
                    await run_in_threadpool(lambda: count_click(slots.store, campaign_id, category=mapped, region=where,
                                                                surface=surface))
        except ContractError:
            pass
        return RedirectResponse(target, status_code=302, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})

    return router
