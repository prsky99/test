"""Individual staff-session transport for purpose-bound typed lineage."""
import re
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .broker.server import RateLimiter
from .gateway import admin_auth
from .workflow_publication_service import no_store, read_object
from .workspace_access import SessionActor, WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid
from .workspace_service import WorkspaceRoute
from .workspace_typed_evidence import PROFILE, WorkspaceTypedEvidence

BASE = '/admin/api/workflow-workspaces/{workspace_id}/reliability/typed'


def router_for(core):
    if not isinstance(core, WorkspaceTypedEvidence): raise WorkspaceInvalid()
    router = APIRouter(prefix=BASE, route_class=WorkspaceRoute)
    reads, writes = RateLimiter(240), RateLimiter(30)

    def session(request: Request):
        authorization = request.headers.get('authorization', '')
        if request.headers.get('x-dashboard') != '1' or not re.fullmatch(r'Bearer [a-f0-9]{64}', authorization):
            raise HTTPException(401, 'Sign in with an individual administrator session.')
        with core.store.tx() as db: user = admin_auth.get_session_user(db, authorization[7:])
        if not user: raise HTTPException(401, 'The individual administrator session is unavailable.')
        if not (reads if request.method == 'GET' else writes).allow(str(user['user_id'])):
            raise HTTPException(429, 'Private lineage request limit reached.')
        return SessionActor(user['user_id'], admin_auth.session_reference(authorization[7:]))

    def invoke(method, ws, actor, *args):
        try: return getattr(core, method)(ws, *args, actor)
        except WorkspaceDenied: raise HTTPException(404, 'The private lineage object is unavailable.') from None
        except WorkspaceConflict: raise HTTPException(409, 'Current authority or retained execution evidence changed.') from None
        except WorkspaceInvalid: raise HTTPException(400, 'Provide the exact purpose-bound lineage fields.') from None
        except sqlite3.DatabaseError: raise HTTPException(503, 'Private lineage storage is unavailable.') from None
        except (TypeError, ValueError, KeyError, UnicodeError, RecursionError):
            raise HTTPException(400, 'The private lineage request could not be validated.') from None

    def result(value):
        return JSONResponse({'ok': True, 'profile': PROFILE, 'result': value}, headers=no_store())

    def flow(request):
        query = request.query_params
        if (set(query) != {'flow_id'} or len(query.getlist('flow_id')) != 1
                or not re.fullmatch(r'wtf_[0-9a-f]{32}', query['flow_id'])):
            raise HTTPException(400, 'Choose one private typed flow reference.')
        return query['flow_id']

    @router.get('/options')
    def options(workspace_id: str, actor=Depends(session)):
        return result(invoke('options', workspace_id, actor))

    @router.get('/runs')
    def runs(workspace_id: str, request: Request, actor=Depends(session)):
        return result(invoke('runs', workspace_id, actor, flow(request)))

    @router.get('/runs/{run_id}')
    def report(workspace_id: str, run_id: str, request: Request, actor=Depends(session)):
        value = invoke('current_run', workspace_id, actor, flow(request), run_id)
        tag = '"' + value['source_revision'] + '"'
        headers = {**no_store(), 'ETag': tag, 'Vary': 'Authorization, X-Dashboard, Origin'}
        if request.headers.get('if-none-match') == tag: return Response(status_code=304, headers=headers)
        return JSONResponse({'ok': True, 'profile': PROFILE, 'result': value}, headers=headers)

    @router.post('/captures')
    async def capture(workspace_id: str, request: Request, actor=Depends(session)):
        try: body = await read_object(request, 16384)
        except (TypeError, ValueError, UnicodeError, RecursionError, TimeoutError):
            raise HTTPException(400, 'Provide one bounded typed source capture.') from None
        return result(await run_in_threadpool(invoke, 'capture', workspace_id, actor, body))

    return router
