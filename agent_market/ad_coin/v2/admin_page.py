"""Korean operator screen for AI AD Coin v2: platform coin holdings, the x402 test condition and
ledger reconciliation (read only).

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
    for icon in ("sun", "moon", "home", "chart", "receipt"):
        html = html.replace("@@" + icon + "@@", ICON.get(icon, ""))
    return html, name, data


def router_for():
    router = APIRouter()
    html, script_name, script = _build()
    tag = '"' + hashlib.sha256(script).hexdigest() + '"'

    @router.get(PATH, include_in_schema=False)
    async def page():
        return HTMLResponse(html, headers=_headers())

    @router.get(PATH + "/assets/{name}", include_in_schema=False)
    async def asset(name: str, request: Request):
        if name != script_name:
            return Response(status_code=404, headers=_headers())
        headers = {**_headers(), "Cache-Control": "public,max-age=31536000,immutable", "ETag": tag}
        if request.headers.get("if-none-match") == tag:
            return Response(status_code=304, headers=headers)
        return Response(script, media_type="text/javascript", headers=headers)

    return router
