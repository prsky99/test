"""Named staff-only Stripe test controls; webhook ingress mounts separately."""
import asyncio
import re

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .broker.server import RateLimiter
from .gateway import admin_auth
from .stripe_sandbox import PROFILE
from .workspace_access import SessionActor, WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid
from .workspace_service import WorkspaceRoute
from .workflow_publication_service import no_store, read_object


def router_for(core):
    router = APIRouter(prefix='/admin/api/workflow-workspaces/{workspace_id}/stripe-sandbox', route_class=WorkspaceRoute)
    limit = RateLimiter(60)

    def session(request: Request):
        value = request.headers.get('authorization', '')
        if request.headers.get('x-dashboard') != '1' or not re.fullmatch(r'Bearer [a-f0-9]{64}', value):
            raise HTTPException(401, 'Sign in with an individual administrator session.')
        with core.store.tx() as db:
            user = admin_auth.get_session_user(db, value[7:])
        if not user:
            raise HTTPException(401, 'The individual session is unavailable.')
        if not limit.allow(str(user['user_id'])):
            raise HTTPException(429, 'Sandbox request limit reached.')
        return SessionActor(user['user_id'], admin_auth.session_reference(value[7:]))

    def call(method, *args):
        try:
            value = getattr(core, method)(*args)
            return JSONResponse({'ok': True, 'profile': PROFILE, 'result': value}, headers=no_store())
        except WorkspaceDenied:
            raise HTTPException(404, 'The private sandbox object is unavailable.') from None
        except WorkspaceConflict:
            raise HTTPException(409, 'Review current state and reconcile the original request.') from None
        except (WorkspaceInvalid, ValueError, TypeError, KeyError):
            raise HTTPException(400, 'Provide the exact bounded sandbox fields.') from None

    async def body(request):
        try:
            return await read_object(request, 16384)
        except Exception:
            raise HTTPException(400, 'Provide one bounded sandbox request.') from None

    @router.post('/quotes')
    async def quote(workspace_id: str, request: Request, actor=Depends(session)):
        return await run_in_threadpool(call, 'quote', workspace_id, await body(request), actor)

    @router.get('/orders/{order_id}')
    def status(workspace_id: str, order_id: str, request: Request, actor=Depends(session)):
        if request.query_params:
            raise HTTPException(400, 'Read the exact order without extra fields.')
        return call('status', workspace_id, order_id, actor)

    @router.post('/orders/{order_id}/{action}')
    async def order_action(workspace_id: str, order_id: str, action: str, request: Request, actor=Depends(session)):
        if action not in ('execute', 'reconcile', 'balance'):
            raise HTTPException(404, 'Sandbox action unavailable.')
        return await run_in_threadpool(call, 'reconcile_balance' if action == 'balance' else action,
                                       workspace_id, order_id, await body(request), actor)

    return router


def create_webhook_app(core, *, allowed_host=None):
    """A separately deployed, explicit HTTPS host. Not a public frontend route."""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    limit = RateLimiter(120)
    enabled = core.client is not None and type(allowed_host) is str and bool(re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,251}', allowed_host))

    @app.post('/stripe/test/events')
    async def webhook(request: Request):
        hosts = [value for name, value in request.scope.get('headers', ()) if name.lower() == b'host']
        signatures = [value for name, value in request.scope.get('headers', ()) if name.lower() == b'stripe-signature']
        if not enabled or len(hosts) != 1 or request.url.scheme != 'https' or request.headers.get('host') != allowed_host:
            raise HTTPException(404, 'Not found.')
        if len(signatures) != 1:
            raise HTTPException(400, 'Provide one signed test event.')
        if not limit.allow(request.client.host if request.client else ''):
            raise HTTPException(429, 'Request limit reached.')
        raw = bytearray()
        try:
            async with asyncio.timeout(10):
                async for chunk in request.stream():
                    raw.extend(chunk)
                    if len(raw) > 65536:
                        raise HTTPException(413, 'Request too large.')
        except TimeoutError:
            raise HTTPException(408, 'Request timed out.') from None
        try:
            result = await run_in_threadpool(core.webhook, bytes(raw), request.headers.get('stripe-signature', ''))
        except Exception:
            raise HTTPException(400, 'The signed test event could not be accepted.') from None
        return JSONResponse(result, headers=no_store())

    return app
