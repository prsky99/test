"""Opt-in English workspace shell and bounded, read-only human UI projections."""

from collections import defaultdict
import hashlib
import inspect
import json
import time
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import HTMLResponse, JSONResponse, Response

from ..advertiser_page import ICON
from .contracts import ContractError
from .http import AuthContext, _error
from .identity import Kind
from .ledger import identifier

WEB = Path(__file__).with_name("web")


def _headers():
    return {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "X-Frame-Options": "DENY",
        "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; "
        "connect-src 'self'; img-src 'self'; font-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
    }


def bootstrap(service, principal):
    if principal.kind != Kind.HUMAN:
        raise ContractError("human_workspace_required", 403)
    store = service.store
    with store.atomic():
        from .access import PLATFORM_OPERATORS_ID
        rows = [r for r in store.all("ui_advertisers", (str(principal.id),))
                if r["advertiser_id"] != PLATFORM_OPERATORS_ID]  # operator membership is not an advertiser
        ids = {r["advertiser_id"] for r in rows}
        store.lock(
            *("0:authority:" + value for value in sorted(ids | {str(principal.id)}))
        )
        current = service.access.current(principal)
        if current.expires_at <= time.time() or current.audience != "aiac-v2-model":
            raise ContractError("authority_expired", 403)
        grants = defaultdict(list)
        for row in store.all("ui_advertisers", (str(principal.id),)):  # re-read under the locks
            if row["advertiser_id"] in ids:
                grants[row["advertiser_id"]].append(row["capability"])
        advertisers = []
        for key, caps in grants.items():
            try:
                service.access.guards.current(key)
            except ContractError:
                continue
            row = store.one("advertiser_get", (key,))
            advertisers.append(
                {
                    "id": key,
                    "label": "Advertising account " + str(len(advertisers) + 1),
                    "capabilities": caps,
                    "status": row["status"] if row else "suspended",  # suspended = application pending
                }
            )
        pref = store.one("preference_by_owner", (str(current.owner_id),))
        preferences = None
        if pref:
            preferences = {
                **service._preferences_view(pref),
                "context_fields": json.loads(pref["context_fields_json"]),
                "max_offers_per_day": pref["max_offers_per_day"],
            }
        wallets = (
            store.all("ui_wallets", (str(current.owner_id),))
            if "wallet.read" in current.capabilities
            else []
        )
        return {
            "preferences": preferences,
            "wallets": [
                {
                    "id": w["id"],
                    "label": "Agent wallet " + str(i + 1)
                    if w["manager_binding_id"]
                    else "Your wallet",
                    "available_atoms": str(w["available_atoms"]),
                    "locked_atoms": str(w["locked_atoms"]),
                }
                for i, w in enumerate(wallets)
            ],
            "advertisers": advertisers,
            "categories": sorted(service.taxonomy),
            "regions": sorted(service.regions),
            "languages": sorted(service.languages),
        }


def campaigns(service, principal, advertiser_id, cursor):
    advertiser_id = identifier(advertiser_id)
    cursor = identifier(cursor) if cursor else ""
    with service._context("getCampaign", principal, {"advertiser_id": advertiser_id}):
        rows = service.store.all("ui_campaigns", (advertiser_id, cursor))
        result = []
        for row in rows[:10]:
            body = json.loads(row["payload_json"])
            result.append(
                {
                    "id": row["id"],
                    "advertiser_id": row["advertiser_id"],
                    "version": row["version"],
                    "revision_hash": row["revision_hash"],
                    "state": row["state"],
                    "approval_status": row["approval_status"],
                    **{
                        name: body[name]
                        for name in (
                            "name",
                            "total_budget_atoms",
                            "daily_budget_atoms",
                            "gross_p1_atoms",
                            "starts_at",
                            "ends_at",
                        )
                    },
                }
            )
        return {
            "items": result,
            "next_cursor": rows[9]["id"] if len(rows) > 10 else None,
        }


def router_for(service, *, resolve_auth):
    router = APIRouter(prefix="/ad-coin/v2")
    assets = {}
    for name, mime in (("app.js", "text/javascript"),):
        data = (WEB / name).read_bytes()
        stem, extension = name.split(".")
        assets[stem + "." + hashlib.sha256(data).hexdigest()[:16] + "." + extension] = (
            data,
            mime,
        )
    html = (WEB / "index.html").read_text()
    for name in ("app.js",):
        extension = name.split(".")[-1]
        url = next(path for path in assets if path.endswith("." + extension))
        html = html.replace("@@" + name + "@@", "/ad-coin/v2/assets/" + url)
    for name in ("sun", "moon", "megaphone", "receipt", "chart", "user", "plus", "team", "home", "info", "arrow"):
        if name in ICON:
            html = html.replace("@@" + name + "@@", ICON[name])

    @router.get("", include_in_schema=False)
    async def page():
        # This static shell performs no account/database work or background prefetch.
        return HTMLResponse(html, headers=_headers())

    @router.get("/assets/{name}", include_in_schema=False)
    async def asset(name: str, request: Request):
        found = assets.get(name)
        if found is None:
            return Response(status_code=404, headers=_headers())
        tag = '"' + hashlib.sha256(found[0]).hexdigest() + '"'
        headers = {
            **_headers(),
            "Cache-Control": "public,max-age=31536000,immutable",
            "ETag": tag,
        }
        if request.headers.get("if-none-match") == tag:
            return Response(status_code=304, headers=headers)
        return Response(found[0], media_type=found[1], headers=headers)

    async def project(request, action):
        headers = _headers()
        try:
            if request.headers.get("authorization"):
                raise ContractError("browser_session_required", 403)
            for name in ("cookie", "authorization"):
                if len(request.headers.getlist(name)) > 1:
                    raise ContractError("duplicate_security_header")
            context = await run_in_threadpool(resolve_auth, request)
            if inspect.isawaitable(context):
                context = await context
            if (
                not isinstance(context, AuthContext)
                or context.principal.kind != Kind.HUMAN
            ):
                raise ContractError("authentication_required", 401)
            value = await run_in_threadpool(action, context.principal)
            return JSONResponse(value, headers=headers)
        except ContractError as exc:
            return JSONResponse(
                _error(exc.code, exc.status, str(uuid4())),
                status_code=exc.status,
                headers=headers,
            )
        except Exception:
            return JSONResponse(
                _error("service_error", 500, str(uuid4())),
                status_code=500,
                headers=headers,
            )

    @router.get("/ui/session", include_in_schema=False)
    async def session(request: Request):
        if request.url.query:
            return JSONResponse(
                _error("query_parameters_forbidden", 422, str(uuid4())),
                status_code=422,
                headers=_headers(),
            )
        return await project(request, lambda principal: bootstrap(service, principal))

    @router.get("/ui/advertisers/{advertiser_id}/campaigns", include_in_schema=False)
    async def listing(request: Request, advertiser_id: str):
        if (
            set(request.query_params) - {"cursor"}
            or len(request.query_params.getlist("cursor")) > 1
        ):
            return JSONResponse(
                _error("query_parameters_forbidden", 422, str(uuid4())),
                status_code=422,
                headers=_headers(),
            )
        return await project(
            request,
            lambda principal: campaigns(
                service,
                principal,
                advertiser_id,
                request.query_params.get("cursor", ""),
            ),
        )

    return router
