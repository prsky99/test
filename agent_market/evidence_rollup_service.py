"""Named-session-only current evidence projection with revalidated conditional reads."""
import re
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .broker.server import RateLimiter
from .evidence_rollups import EvidenceRollups, PROFILE
from .gateway import admin_auth
from .workspace_access import SessionActor, WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid
from .workspace_service import WorkspaceRoute
from .workflow_publication_service import no_store, read_object

BASE = '/admin/api/workflow-workspaces/{workspace_id}/evidence'


def router_for(access, execution, *, core=None):
    core = core if core is not None else EvidenceRollups(access, execution)
    if core.access is not access or core.execution is not execution: raise WorkspaceInvalid()
    router = APIRouter(prefix=BASE, route_class=WorkspaceRoute)
    reads, writes = RateLimiter(240), RateLimiter(60)

    def session(request: Request):
        value = request.headers.get('authorization', '')
        if request.headers.get('x-dashboard') != '1' or not re.fullmatch(r'Bearer [a-f0-9]{64}', value):
            raise HTTPException(401, 'Sign in with an individual administrator session.')
        with access.store.tx() as db: user = admin_auth.get_session_user(db, value[7:])
        if not user: raise HTTPException(401, 'The individual session is unavailable.')
        if not (reads if request.method == 'GET' else writes).allow(str(user['user_id'])):
            raise HTTPException(429, 'Evidence request limit reached.')
        return SessionActor(user['user_id'], admin_auth.session_reference(value[7:]))

    def invoke(method, *args):
        try: return getattr(core, method)(*args)
        except WorkspaceDenied: raise HTTPException(404, 'The scoped evidence is unavailable.') from None
        except WorkspaceConflict: raise HTTPException(409, 'Evidence or authority changed. Read current state.') from None
        except WorkspaceInvalid: raise HTTPException(400, 'Provide the exact bounded evidence fields.') from None
        except sqlite3.DatabaseError: raise HTTPException(503, 'Evidence storage is unavailable.') from None
        except (TypeError, ValueError, KeyError, UnicodeError, RecursionError):
            raise HTTPException(400, 'Evidence data could not be validated.') from None

    @router.get('/options')
    def options(workspace_id: str, actor=Depends(session)):
        return JSONResponse({'ok': True, 'profile': PROFILE, 'result': invoke('options', workspace_id, actor)}, headers=no_store())

    @router.get('/rollup')
    def rollup(workspace_id: str, request: Request, actor=Depends(session)):
        query = request.query_params
        if (set(query) - {'scope', 'resource_id'} or any(len(query.getlist(key)) != 1 for key in query)
                or not re.fullmatch(r'[1-9][0-9]{0,9}', query.get('resource_id', ''))):
            raise HTTPException(400, 'Choose one resource reference and evidence scope.')
        result, tag = invoke('rollup', workspace_id, int(query['resource_id']), query.get('scope', 'workspace'), actor)
        headers = {**no_store(), 'ETag': tag, 'Vary': 'Authorization, X-Dashboard, Origin'}
        # No cached summary bypasses the current source/authority read above.
        # Wildcard and weak validators never authorize retaining a prior body.
        if request.headers.get('if-none-match') == tag:
            return Response(status_code=304, headers=headers)
        return JSONResponse({'ok': True, 'profile': PROFILE, 'result': result}, headers=headers)

    @router.post('/withdrawals')
    async def withdraw(workspace_id: str, request: Request, actor=Depends(session)):
        try: value = await read_object(request, 4096)
        except (ValueError, TypeError, UnicodeError, RecursionError, TimeoutError):
            raise HTTPException(400, 'Provide one bounded evidence withdrawal object.') from None
        result = await run_in_threadpool(invoke, 'withdraw', workspace_id, value, actor)
        return JSONResponse({'ok': True, 'profile': PROFILE, 'result': result}, headers=no_store())

    return router
