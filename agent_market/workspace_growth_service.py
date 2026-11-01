"""Named staff transport for reviewed app composition and support outcomes."""
import re
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .broker.server import RateLimiter
from .gateway import admin_auth
from .workspace_access import SessionActor, WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid
from .workspace_service import WorkspaceRoute
from .workflow_publication_service import no_store, read_object

BASE = '/admin/api/workflow-workspaces/{workspace_id}'


def router_for(factory, support):
    access = factory.access
    if support.access is not access: raise WorkspaceInvalid()
    router = APIRouter(prefix=BASE, route_class=WorkspaceRoute)
    reads, writes = RateLimiter(240), RateLimiter(40)

    def session(request: Request):
        value = request.headers.get('authorization', '')
        if request.headers.get('x-dashboard') != '1' or not re.fullmatch(r'Bearer [a-f0-9]{64}', value):
            raise HTTPException(401, 'Use an individual administrator session.')
        with access.store.tx() as db: user = admin_auth.get_session_user(db, value[7:])
        if not user: raise HTTPException(401, 'The current administrator session is unavailable.')
        if not (reads if request.method == 'GET' else writes).allow(str(user['user_id'])):
            raise HTTPException(429, 'Private workspace request limit reached.')
        return SessionActor(user['user_id'], admin_auth.session_reference(value[7:]))

    def invoke(core, method, ws, actor, value=None):
        try:
            result = getattr(core, method)(ws, actor) if value is None else getattr(core, method)(ws, value, actor)
            return JSONResponse({'ok': True, 'result': result}, headers=no_store())
        except WorkspaceDenied: raise HTTPException(404, 'The current private workspace object is unavailable.') from None
        except WorkspaceConflict: raise HTTPException(409, 'Private state changed. Inspect current state before another action.') from None
        except WorkspaceInvalid: raise HTTPException(400, 'Provide exact bounded private workspace fields.') from None
        except sqlite3.DatabaseError: raise HTTPException(503, 'Private workspace storage is unavailable.') from None
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, OverflowError):
            raise HTTPException(400, 'The private request could not be validated.') from None

    async def command(request, core, method, ws, actor):
        try: value = await read_object(request, 16384)
        except (ValueError, TypeError, UnicodeError, TimeoutError, RecursionError):
            raise HTTPException(400, 'Provide one bounded JSON command.') from None
        return await run_in_threadpool(invoke, core, method, ws, actor, value)

    @router.get('/app-factory/options')
    def options(workspace_id: str, actor=Depends(session)):
        return invoke(factory, 'options', workspace_id, actor)

    @router.post('/app-factory/reviews')
    async def prepare(workspace_id: str, request: Request, actor=Depends(session)):
        return await command(request, factory, 'prepare', workspace_id, actor)

    @router.post('/app-factory/commits')
    async def commit(workspace_id: str, request: Request, actor=Depends(session)):
        return await command(request, factory, 'commit', workspace_id, actor)

    @router.post('/app-factory/plan-reviews')
    async def plan_review(workspace_id: str, request: Request, actor=Depends(session)):
        return await command(request, factory, 'prepare_plan', workspace_id, actor)

    @router.post('/app-factory/intent-reviews')
    async def intent_review(workspace_id: str, request: Request, actor=Depends(session)):
        return await command(request, factory, 'prepare_intent', workspace_id, actor)

    @router.post('/app-factory/model-proposals')
    async def model_proposal(workspace_id: str, request: Request, actor=Depends(session)):
        return await command(request, factory, 'prepare_model_proposal', workspace_id, actor)

    @router.get('/sdk-lifecycle')
    def catalog(workspace_id: str, actor=Depends(session)):
        return invoke(factory, 'catalog', workspace_id, actor)

    @router.post('/sdk-lifecycle')
    async def configure(workspace_id: str, request: Request, actor=Depends(session)):
        return await command(request, factory, 'configure_sdk', workspace_id, actor)

    @router.get('/support-outcomes')
    def outcomes(workspace_id: str, actor=Depends(session)):
        return invoke(support, 'report', workspace_id, actor)

    @router.post('/support-outcomes/records')
    async def record(workspace_id: str, request: Request, actor=Depends(session)):
        return await command(request, support, 'record', workspace_id, actor)

    @router.post('/support-outcomes/withdrawals')
    async def withdraw(workspace_id: str, request: Request, actor=Depends(session)):
        return await command(request, support, 'withdraw', workspace_id, actor)

    return router
