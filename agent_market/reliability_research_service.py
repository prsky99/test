"""Named administrator routes for bounded corpus research and metadata shadow."""
import re
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .broker.server import RateLimiter
from .gateway import admin_auth
from .reliability_research import PROFILE, ReliabilityResearch
from .workspace_access import SessionActor, WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid
from .workspace_service import WorkspaceRoute
from .workflow_publication_service import no_store, read_object

BASE = '/admin/api/workflow-workspaces/{workspace_id}/reliability/research'


def router_for(access, evaluation, *, research=None, lineage=None):
    research = research if research is not None else ReliabilityResearch(access, evaluation, lineage=lineage)
    if research.access is not access or research.evaluation is not evaluation:
        raise WorkspaceInvalid()
    router = APIRouter(prefix=BASE, route_class=WorkspaceRoute)
    reads, writes = RateLimiter(120), RateLimiter(30)

    def session(request: Request):
        authorization = request.headers.get('authorization', '')
        if request.headers.get('x-dashboard') != '1' or not re.fullmatch(r'Bearer [a-f0-9]{64}', authorization):
            raise HTTPException(401, 'Use an individual administrator session.')
        with access.store.tx() as db:
            user = admin_auth.get_session_user(db, authorization[7:])
        if not user:
            raise HTTPException(401, 'The individual session is unavailable.')
        if not (reads if request.method == 'GET' else writes).allow(str(user['user_id'])):
            raise HTTPException(429, 'Research request limit reached.')
        return SessionActor(user['user_id'], admin_auth.session_reference(authorization[7:]))

    def invoke(method, *args):
        try:
            return getattr(research, method)(*args)
        except WorkspaceDenied:
            raise HTTPException(404, 'The scoped research object is unavailable.') from None
        except WorkspaceConflict:
            raise HTTPException(409, 'Current research, evidence or authority changed.') from None
        except (WorkspaceInvalid, TypeError, ValueError, KeyError, UnicodeError, RecursionError):
            raise HTTPException(400, 'Provide the exact bounded research fields.') from None
        except sqlite3.DatabaseError:
            raise HTTPException(503, 'Research storage is unavailable.') from None

    def reply(value):
        return JSONResponse({'ok': True, 'profile': PROFILE, 'result': value}, headers=no_store())

    async def body(request):
        try:
            return await read_object(request, 16384)
        except (TypeError, ValueError, UnicodeError, RecursionError, TimeoutError):
            raise HTTPException(400, 'Provide one bounded research JSON object.') from None

    @router.get('/options')
    def options(workspace_id: str, request: Request, actor=Depends(session)):
        if request.query_params:
            raise HTTPException(400, 'Use the scoped research path without extra fields.')
        return reply(invoke('options', workspace_id, actor))

    @router.get('/status')
    def status(workspace_id: str, request: Request, actor=Depends(session)):
        if request.query_params:
            raise HTTPException(400, 'Use the scoped research path without extra fields.')
        return reply(invoke('status', workspace_id, actor))

    @router.post('/manifests')
    async def register(workspace_id: str, request: Request, actor=Depends(session)):
        return reply(await run_in_threadpool(invoke, 'register_manifest', workspace_id, await body(request), actor))

    @router.get('/manifests/{manifest_id}/analyze')
    def analyze(workspace_id: str, manifest_id: str, request: Request, actor=Depends(session)):
        if request.query_params:
            raise HTTPException(400, 'Use the scoped research path without extra fields.')
        return reply(invoke('analyze', workspace_id, manifest_id, actor))

    @router.post('/manifests/{manifest_id}/{action}')
    async def action(workspace_id: str, manifest_id: str, action: str, request: Request, actor=Depends(session)):
        if action not in ('withdraw', 'shadow'):
            raise HTTPException(404, 'The research action is unavailable.')
        return reply(await run_in_threadpool(invoke, action, workspace_id, manifest_id, await body(request), actor))

    return router
