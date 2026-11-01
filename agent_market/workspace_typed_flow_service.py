"""Staff-only transport for explicitly reviewed private typed graph execution."""
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .broker.server import RateLimiter
from .gateway import admin_auth
from .workspace_access import SessionActor, WorkspaceDenied, WorkspaceInvalid, WorkspaceConflict, _tree
from .workspace_service import BASE, WorkspaceRoute
from .workspace_typed_flows import PROFILE
from .workflow_publication_service import read_object, no_store, same_origin


def router_for(core):
    router = APIRouter(prefix=BASE + '/{ws}/typed-flows', route_class=WorkspaceRoute)
    limiter = RateLimiter(60)

    def actor(request: Request):
        value = request.headers.get('authorization', '')
        if not same_origin(request) or request.headers.get('x-dashboard') != '1' or not re.fullmatch('Bearer [a-f0-9]{64}', value):
            raise HTTPException(401, 'Use a current individual workspace session.')
        with core.store.tx() as db:
            user = admin_auth.get_session_user(db, value[7:])
        if not user:
            raise HTTPException(401, 'The individual session is unavailable.')
        if not limiter.allow(str(user['user_id'])):
            raise HTTPException(429, 'Private graph request limit reached.')
        return SessionActor(user['user_id'], admin_auth.session_reference(value[7:]))

    async def body(request):
        try:
            value = await read_object(request, 65536); _tree(value)
            return value
        except Exception:
            raise HTTPException(400, 'Provide the exact bounded graph fields.') from None

    def invoke(method, *args):
        try:
            return getattr(core, method)(*args)
        except WorkspaceDenied:
            raise HTTPException(404, 'The private graph or current authority is unavailable.') from None
        except WorkspaceConflict:
            raise HTTPException(409, 'State changed or the result is uncertain. Review history before another action.') from None
        except (WorkspaceInvalid, ValueError, TypeError, KeyError):
            raise HTTPException(400, 'The private graph fields could not be validated.') from None

    def response(**values):
        return JSONResponse({'ok': True, 'profile': PROFILE, **values}, headers=no_store())

    @router.get('/options')
    def options(ws: str, current=Depends(actor)):
        return response(**invoke('options', ws, current))

    @router.get('')
    def listing(ws: str, current=Depends(actor)):
        return response(flows=invoke('listing', ws, current))

    @router.post('')
    async def save(ws: str, request: Request, current=Depends(actor)):
        return response(flow=await run_in_threadpool(invoke, 'save', ws, await body(request), current))

    @router.get('/{flow}')
    def detail(ws: str, flow: str, current=Depends(actor)):
        return response(flow=invoke('detail', ws, flow, current))

    @router.post('/{flow}/prepare')
    async def prepare(ws: str, flow: str, request: Request, current=Depends(actor)):
        return response(**await run_in_threadpool(invoke, 'prepare', ws, flow, await body(request), current))

    @router.post('/{flow}/disable')
    async def disable(ws: str, flow: str, request: Request, current=Depends(actor)):
        return response(flow=await run_in_threadpool(invoke, 'disable', ws, flow, await body(request), current))

    @router.post('/{flow}/runs')
    async def execute(ws: str, flow: str, request: Request, current=Depends(actor)):
        return response(**await run_in_threadpool(invoke, 'execute', ws, flow, await body(request), current))

    @router.get('/{flow}/runs')
    def history(ws: str, flow: str, current=Depends(actor)):
        return response(runs=invoke('runs', ws, flow, current))

    @router.get('/{flow}/runs/{run}')
    def get(ws: str, flow: str, run: str, current=Depends(actor)):
        return response(run=invoke('get', ws, flow, run, current))

    return router
