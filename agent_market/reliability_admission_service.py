"""Private staff-only single-admission transport; no customer/public activation."""
import re
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .broker.server import RateLimiter
from .gateway import admin_auth
from .reliability_admission import PROFILE
from .workspace_access import SessionActor, WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid
from .workspace_service import WorkspaceRoute
from .workflow_publication_service import no_store, read_object


def router_for(core):
    access = core.access
    router = APIRouter(prefix='/admin/api/workflow-workspaces/{workspace_id}/reliability/admission', route_class=WorkspaceRoute)
    reads, writes = RateLimiter(240), RateLimiter(30)

    def session(request: Request):
        value = request.headers.get('authorization', '')
        if request.headers.get('x-dashboard') != '1' or not re.fullmatch(r'Bearer [a-f0-9]{64}', value):
            raise HTTPException(401, 'Use an individual administrator session.')
        with access.store.tx() as db:
            user = admin_auth.get_session_user(db, value[7:])
        if not user:
            raise HTTPException(401, 'The current administrator session is unavailable.')
        if not (reads if request.method == 'GET' else writes).allow(str(user['user_id'])):
            raise HTTPException(429, 'The private admission request limit was reached.')
        return SessionActor(user['user_id'], admin_auth.session_reference(value[7:]))

    def invoke(method, *args):
        try:
            return JSONResponse({'ok': True, 'profile': PROFILE, 'result': getattr(core, method)(*args)}, headers=no_store())
        except WorkspaceDenied:
            raise HTTPException(404, 'The current private admission object is unavailable.') from None
        except WorkspaceConflict:
            raise HTTPException(409, 'Current evidence or authority changed. Inspect retained state.') from None
        except WorkspaceInvalid:
            raise HTTPException(400, 'Provide exact bounded admission fields.') from None
        except sqlite3.DatabaseError:
            raise HTTPException(503, 'Private admission storage is unavailable.') from None
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, OverflowError):
            raise HTTPException(400, 'The admission request could not be validated.') from None

    async def body(request):
        try:
            return await read_object(request, 16384)
        except (ValueError, TypeError, UnicodeError, RecursionError, TimeoutError):
            raise HTTPException(400, 'Provide one bounded JSON command.') from None

    @router.get('/status')
    def status(workspace_id: str, actor=Depends(session)):
        return invoke('status', workspace_id, actor)

    @router.get('/{admission_id}/review')
    def review(workspace_id: str, admission_id: str, request: Request, actor=Depends(session)):
        if request.query_params:
            raise HTTPException(400, 'Read the exact retained admission without extra fields.')
        return invoke('review', workspace_id, admission_id, actor)

    @router.post('/{action}')
    async def action(workspace_id: str, action: str, request: Request, actor=Depends(session)):
        if action not in ('configure', 'prepare'):
            raise HTTPException(404, 'Private admission action unavailable.')
        return await run_in_threadpool(invoke, action, workspace_id, await body(request), actor)

    @router.post('/{admission_id}/execute')
    async def execute(workspace_id: str, admission_id: str, request: Request, actor=Depends(session)):
        return await run_in_threadpool(invoke, 'execute', workspace_id, admission_id, await body(request), actor)

    return router
