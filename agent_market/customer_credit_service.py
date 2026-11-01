"""Same-origin customer enrollment and individually authenticated staff credit controls."""

import re
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from .customer_credits import CustomerCredits
from .customer_identity_service import customer_actor
from .workspace_access import (
    SessionActor,
    WorkspaceDenied,
    WorkspaceConflict,
    WorkspaceInvalid,
)
from .workspace_service import WorkspaceRoute
from .workflow_publication_service import same_origin, read_object, no_store
from .gateway import admin_auth
from .broker.server import RateLimiter


def router_for(identity, access, *, admin=False):
    core = CustomerCredits(identity)
    core.prune()
    router = APIRouter(route_class=WorkspaceRoute)
    reads, writes = RateLimiter(180), RateLimiter(30)

    def actor(request, write=False):
        if (
            not same_origin(request)
            or request.headers.get("authorization")
            and not admin
        ):
            raise HTTPException(403, "Use the current service session.")
        if admin:
            token = request.headers.get("authorization", "")
            if request.headers.get("x-dashboard") != "1" or not re.fullmatch(
                r"Bearer [a-f0-9]{64}", token
            ):
                raise HTTPException(401, "Use an individual administrator session.")
            with core.store.tx() as db:
                user = admin_auth.get_session_user(db, token[7:])
            if not user:
                raise HTTPException(401, "The administrator session is unavailable.")
            current = SessionActor(
                user["user_id"], admin_auth.session_reference(token[7:])
            )
            key = "staff:" + str(user["user_id"])
        else:
            current = customer_actor(request, identity, csrf=write)
            key = current.customer_id
        if not (writes if write else reads).allow(key):
            raise HTTPException(
                429,
                "Please wait before another credit request.",
                headers={"Retry-After": "60"},
            )
        return current

    async def body(request):
        try:
            return await read_object(request, 4096)
        except (ValueError, TypeError, TimeoutError):
            raise HTTPException(
                400, "Provide the exact credit request fields."
            ) from None

    def call(method, *args):
        try:
            return method(*args)
        except WorkspaceConflict:
            raise HTTPException(
                409, "State changed. Refresh before another action."
            ) from None
        except WorkspaceDenied:
            raise HTTPException(
                403, "The account or current permission is unavailable."
            ) from None
        except (WorkspaceInvalid, ValueError, TypeError, KeyError):
            raise HTTPException(400, "Review the supported credit fields.") from None

    def result(**values):
        return JSONResponse({"ok": True, **values}, headers=no_store())

    if admin:

        @router.get("/admin/api/customer-credits")
        def listing(request: Request, q: str = ""):
            current = actor(request)
            return result(accounts=call(core.admin_list, access, current, q))

        @router.get("/admin/api/customer-credits/{customer}/history")
        def history(customer: str, request: Request):
            current = actor(request)
            with access._tx(current) as (db, _):
                from .workspace_access import _identity, _rows

                call(_identity,customer,"cu")
                events = _rows(
                    db,
                    "SELECT payload,signature FROM customer_credit_events WHERE customer_id=? ORDER BY id DESC LIMIT 100",
                    (customer,),
                )
                agreements = _rows(
                    db,
                    "SELECT payload,signature FROM customer_credit_acceptances WHERE customer_id=? ORDER BY id DESC LIMIT 20",
                    (customer,),
                )
                import json

                def opened(rows):
                    values = []
                    for row in rows:
                        value = json.loads(row["payload"])
                        if not core.signer.verify(value, row["signature"]):
                            raise HTTPException(
                                409, "Record integrity review required."
                            )
                        value.pop("session_ref", None)
                        values.append(value)
                    return values

                return result(events=opened(events), agreements=opened(agreements))

        @router.post("/admin/api/customer-credits/{customer}")
        async def change(customer: str, request: Request):
            current = actor(request, True)
            return result(
                account=call(
                    core.admin_change, access, customer, await body(request), current
                )
            )
    else:

        @router.get("/api/customer-credits")
        def status(request: Request):
            current = actor(request)
            core.prune()
            return result(credits=call(core.status, current))

        @router.get("/api/customer-credits/quote")
        def quote(request: Request, workspace: str = "", artifact: str = ""):
            # Lets the page state the exact charge before the customer confirms a save.
            current = actor(request)
            from .workspace_access import _identity

            def charge():
                _identity(workspace, "ws")
                if artifact:
                    _identity(artifact, "wd")
                return core.quote(workspace, artifact or None, current)

            return result(charge=call(charge), credits=call(core.status, current))

        @router.post("/api/customer-credits/enroll")
        async def enroll(request: Request):
            current = actor(request, True)
            return result(enrollment=call(core.enroll, await body(request), current))

        @router.post("/api/customer-credits/close")
        async def close(request: Request):
            current = actor(request, True)
            return result(enrollment=call(core.close, await body(request), current))

        @router.get("/customer/plan")
        def page():
            from .customer_credit_view import page_for

            return page_for()

    return router
