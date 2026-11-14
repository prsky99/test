"""Public ad library /ads/library and /ads/library.json (agent ad plan, trust measures; PM 11-14).

The data side for agent_market/concierge/ads_library_page.py (renderer, organic side): every Sponsored placement of
the last 180 days, coin bookings and confirmed USDC bookings alike, one row per campaign, task category and region
with its first and last day, state, the exact text, why it was shown, where it appeared and the approved agent offer.
Read from the database at most once a minute in this process (the edge keeps the page 10 minutes).
"""
import json
from threading import Lock
import time

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from .sponsored import DAY_MS
from .sponsored_offer import why_shown

WINDOW_DAYS = 180
ROW_LIMIT = 5000
CACHE_SECONDS = 60
HUMAN_SURFACES = ["explore", "chat"]
AGENT_SURFACES = ["mcp", "a2a", "rest"]


def _day(ms):
    return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))


def entries(store, now_ms=None):
    """Rows in the renderer's ENTRY shape, newest first."""
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    today = now_ms - now_ms % DAY_MS
    since = today - WINDOW_DAYS * DAY_MS
    with store.atomic():
        rows = list(store.all("ads_library_coin", (since, ROW_LIMIT)))
        if store.one("paid_bookings_table")["present"]:     # the USDC table exists only after migrate-paid
            rows += list(store.all("ads_library_paid", (since, ROW_LIMIT)))
        offers = {}
        if store.one("sponsored_offers_table")["present"]:
            offers = {r["campaign_id"]: json.loads(r["offer_json"]) for r in store.all("sponsored_offers_approved", (ROW_LIMIT,))}
    groups = {}
    for row in rows:
        key = (row["campaign_id"], row["task_category"], row["region"])
        group = groups.setdefault(key, {"days": [], "states": set(), "payload": row["payload_json"]})
        group["days"].append(int(row["day_ms"]))
        group["states"].add(row["state"])
    out = []
    for (campaign_id, category, region), group in groups.items():
        payload = json.loads(group["payload"])
        first, last = min(group["days"]), max(group["days"])
        live = group["states"] - {"refunded", "refund_due"}
        if not live:
            state = "refunded"
        elif last < today:
            state = "ended"
        elif first <= today:
            state = "running"
        else:
            state = "scheduled"
        offer = offers.get(campaign_id)
        name = str(payload.get("name", ""))[:100]
        out.append({"campaign_id": campaign_id, "advertiser": name, "paid_by": name, "task_category": category,
                    "region": region, "starts": _day(first), "ends": _day(last), "state": state,
                    "text": str(payload.get("creative_text", ""))[:280], "why_shown": why_shown(category, region),
                    "surfaces": HUMAN_SURFACES + (AGENT_SURFACES if offer else []),
                    "offer": {k: offer.get(k, "") for k in ("tool", "endpoint", "price", "free_trial", "sla")} if offer else None,
                    "_sort": last})
    out.sort(key=lambda e: (-e["_sort"], e["campaign_id"], e["task_category"], e["region"]))
    for entry in out:
        entry.pop("_sort")
    return out


def router_for(store, *, clock=None):
    clock = clock or time.time
    router = APIRouter()
    cache = {"at": None, "entries": None, "updated": None}
    lock = Lock()

    def current():
        now = clock()
        with lock:
            if cache["at"] is None or now - cache["at"] >= CACHE_SECONDS:
                cache["entries"] = entries(store, int(now * 1000))
                cache["at"], cache["updated"] = now, time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(now))
            return cache["entries"], cache["updated"]

    headers = {"Cache-Control": "public, max-age=600"}

    @router.get("/ads/library", response_class=HTMLResponse)
    async def library_page():
        from ...concierge.ads_library_page import page_html
        found, updated = await run_in_threadpool(current)
        return HTMLResponse(page_html(found, updated=updated), headers=headers)

    @router.get("/ads/library.json")
    async def library_json():
        from ...concierge.ads_library_page import machine
        found, updated = await run_in_threadpool(current)
        return JSONResponse(machine(found, updated=updated), headers=headers)

    return router
