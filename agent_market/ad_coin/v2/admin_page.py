"""Korean operator screen for AI AD Coin v2: platform coin holdings and ledger reconciliation
(read only).

The page is a static shell in the Pearl Connection design (shared /new/en/assets files, workspace
layout, no page-local styles). It does no account or database work; the two panels load from the
operator API (/api/ad-coin/v2/admin/overview and /reconcile) in parallel when the button is pressed.
v1's /ad-coin/admin stays frozen (security fixes only), so this screen lives under /ad-coin/v2/admin."""
import hashlib

from fastapi import APIRouter, Request
from starlette.responses import HTMLResponse, Response

from ..advertiser_page import ICON
from .workspace import WEB, _headers

PATH = "/ad-coin/v2/admin"


def _build():
    data = (WEB / "admin.js").read_bytes()
    name = "admin." + hashlib.sha256(data).hexdigest()[:16] + ".js"
    html = (WEB / "admin.html").read_text().replace("@@admin.js@@", PATH + "/assets/" + name)
    for icon in ("sun", "moon", "home", "receipt"):
        html = html.replace("@@" + icon + "@@", ICON.get(icon, ""))
    return html, name, data


def advertise_html():
    """The public advertiser landing page (English). USDC status follows the paid-booking switch."""
    from .paid_bookings import enabled
    html = (WEB / "advertise.html").read_text().replace(
        "@@usdc-status@@", "Pay in USDC on Base from your own wallet." if enabled() else "USDC payments open soon.")
    for icon in ("sun", "moon"):
        html = html.replace("@@" + icon + "@@", ICON.get(icon, ""))
    return html


def reach_card():
    """PM 11-18 19:4x: the measured reach-by-budget table, on this operator screen only (not public until the
    measured outside shows reach PM's bar). From the daily snapshot: no database work on this request."""
    import os
    from . import reach
    from .paid_bookings import data_path
    try:
        price = float(os.environ.get("AD_COIN_PAID_PRICE_USDC", "5") or 5)
    except ValueError:
        price = 5.0
    return reach.table_html(reach.read_snapshot(data_path(reach.SNAPSHOT)), price) if price > 0 else ""


def router_for():
    router = APIRouter()
    html, script_name, script = _build()

    @router.get("/ad-coin/v2/advertise", include_in_schema=False)
    async def advertise():
        return HTMLResponse(advertise_html(), headers=_headers())
    tag = '"' + hashlib.sha256(script).hexdigest() + '"'

    @router.get(PATH, include_in_schema=False)
    async def page():
        return HTMLResponse(html.replace("@@reach@@", reach_card()), headers=_headers())

    @router.get(PATH + "/assets/{name}", include_in_schema=False)
    async def asset(name: str, request: Request):
        if name != script_name:
            return Response(status_code=404, headers=_headers())
        headers = {**_headers(), "Cache-Control": "public,max-age=31536000,immutable", "ETag": tag}
        if request.headers.get("if-none-match") == tag:
            return Response(status_code=304, headers=headers)
        return Response(script, media_type="text/javascript", headers=headers)

    return router
