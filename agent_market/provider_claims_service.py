"""Current named-owner API for explicit endpoint-control verification."""
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .gateway import admin_auth
from .broker.server import RateLimiter
from .provider_claims import PROFILE, ProviderClaims
from .workspace_access import SessionActor, WorkspaceDenied, WorkspaceInvalid, WorkspaceConflict, _tree
from .workspace_service import WorkspaceRoute
from .workflow_publication_service import read_object, same_origin, no_store


def router_for(store, key, http=None, *, claims=None):
    core = claims if claims is not None else ProviderClaims(store, key, http)
    router = APIRouter(prefix='/admin/api/workflow-workspaces/{workspace_id}/provider-claims', route_class=WorkspaceRoute)
    quota = RateLimiter(60)

    def actor(request):
        if not same_origin(request) or request.headers.get('x-dashboard') != '1':
            raise HTTPException(403, 'Use the authenticated workspace origin.')
        header = request.headers.get('authorization', '')
        if not re.fullmatch('Bearer [a-f0-9]{64}', header):
            raise HTTPException(401, 'An individual administrator session is required.')
        with store.tx() as db:
            user = admin_auth.get_session_user(db, header[7:])
        if not user:
            raise HTTPException(401, 'The individual session is unavailable.')
        if not quota.allow(str(user['user_id'])):
            raise HTTPException(429, 'Endpoint-control request limit reached.', headers={'Retry-After': '60'})
        return SessionActor(user['user_id'], admin_auth.session_reference(header[7:]))

    async def body(request):
        try:
            value = await read_object(request, 16384)
            _tree(value)
            return value
        except Exception:
            raise HTTPException(400, 'Provide one exact bounded endpoint-control request.') from None

    def invoke(method, *args):
        try:
            value = getattr(core, method)(*args)
            return JSONResponse({'ok': True, 'profile': PROFILE, **value}, headers=no_store())
        except WorkspaceDenied:
            raise HTTPException(404, 'The endpoint-control request is unavailable.') from None
        except WorkspaceConflict:
            raise HTTPException(409, 'Endpoint-control state changed. Review a new request.') from None
        except (WorkspaceInvalid, ValueError, TypeError, KeyError):
            raise HTTPException(400, 'Provide the exact endpoint-control fields.') from None

    @router.get('/options')
    def options(workspace_id: str, request: Request):
        return invoke('options', workspace_id, actor(request))

    @router.get('')
    def listing(workspace_id: str, request: Request):
        try:
            return JSONResponse({'ok': True, 'profile': PROFILE, 'claims': core.claims(workspace_id, actor(request))}, headers=no_store())
        except WorkspaceDenied:
            raise HTTPException(404, 'The endpoint-control history is unavailable.') from None

    @router.post('/prepare')
    async def prepare(workspace_id: str, request: Request):
        current = actor(request)
        return await run_in_threadpool(invoke, 'prepare', workspace_id, await body(request), current)

    @router.post('/verify')
    async def verify(workspace_id: str, request: Request):
        current = actor(request)
        return await run_in_threadpool(invoke, 'verify', workspace_id, await body(request), current)

    @router.post('/{claim_id}/revoke')
    async def revoke(workspace_id: str, claim_id: str, request: Request):
        current = actor(request)
        return await run_in_threadpool(invoke, 'revoke', workspace_id, claim_id, await body(request), current)

    @router.post('/{claim_id}/rechallenge')
    async def rechallenge(workspace_id: str, claim_id: str, request: Request):
        current = actor(request)
        return await run_in_threadpool(invoke, 'rechallenge', workspace_id, claim_id, await body(request), current)

    @router.post('/{claim_id}/transfer')
    async def transfer(workspace_id: str, claim_id: str, request: Request):
        current = actor(request)
        return await run_in_threadpool(invoke, 'transfer', workspace_id, claim_id, await body(request), current)

    @router.post('/transfers/{transfer_id}/accept')
    async def accept_transfer(workspace_id: str, transfer_id: str, request: Request):
        current = actor(request)
        return await run_in_threadpool(invoke, 'accept_transfer', workspace_id, transfer_id, await body(request), current)

    @router.post('/expire')
    async def expire(workspace_id: str, request: Request):
        current = actor(request)
        return await run_in_threadpool(invoke, 'expire', workspace_id, await body(request), current)

    router.provider_claims = core
    return router
