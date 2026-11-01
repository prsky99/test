"""Named-session staff transport for independently authorized machine notices."""

from pathlib import Path
import re
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .broker.server import RateLimiter
from .gateway import admin_auth
from .workspace_access import SessionActor, WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid
from .workspace_machine_updates import PROFILE
from .workspace_service import WorkspaceRoute
from .workflow_publication_service import no_store, read_object

BASE = '/admin/api/workflow-workspaces/{workspace_id}/machine-updates'
ASSET = Path(__file__).parent / 'gateway' / 'workspace-machine-updates-admin.js'


def router_for(core, *, receiver=None):
    if receiver is not None and receiver.access is not core.access:
        raise WorkspaceInvalid()
    router = APIRouter(route_class=WorkspaceRoute)
    reads, writes = RateLimiter(240), RateLimiter(60)

    def session(request: Request):
        value = request.headers.get('authorization', '')
        if request.headers.get('x-dashboard') != '1' or not re.fullmatch(r'Bearer [a-f0-9]{64}', value):
            raise HTTPException(401, 'Sign in with an individual administrator session.')
        with core.store.tx() as db:
            user = admin_auth.get_session_user(db, value[7:])
        if not user:
            raise HTTPException(401, 'The individual administrator session is unavailable.')
        if not (reads if request.method == 'GET' else writes).allow(str(user['user_id'])):
            raise HTTPException(429, 'Machine update request limit reached.')
        return SessionActor(user['user_id'], admin_auth.session_reference(value[7:]))

    def invoke(method, *args, target=None):
        try:
            return getattr(target if target is not None else core, method)(*args)
        except WorkspaceDenied:
            raise HTTPException(404, 'The current workspace, evidence or verified destination is unavailable.') from None
        except WorkspaceConflict:
            raise HTTPException(409, 'State changed or delivery is uncertain. Inspect current history.') from None
        except WorkspaceInvalid:
            raise HTTPException(400, 'Provide the exact bounded machine update fields.') from None
        except sqlite3.DatabaseError:
            raise HTTPException(503, 'Machine update storage is unavailable.') from None
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
            raise HTTPException(400, 'The machine update request could not be validated.') from None

    def response(result):
        return JSONResponse({'ok': True, 'profile': PROFILE, 'result': result}, headers=no_store())

    async def body(request):
        try:
            return await read_object(request, 4096)
        except (ValueError, TypeError, UnicodeError, RecursionError, TimeoutError):
            raise HTTPException(400, 'Provide one bounded machine update JSON object.') from None

    @router.get('/admin/assets/workspace-machine-updates-admin.js', include_in_schema=False)
    def asset():
        return Response(ASSET.read_bytes(), media_type='application/javascript', headers=no_store())

    @router.get(BASE + '/status')
    def status(workspace_id: str, request: Request, actor=Depends(session)):
        if request.query_params:
            raise HTTPException(400, 'Read the current workspace machine update state without extra fields.')
        return response(invoke('status', workspace_id, actor))

    @router.post(BASE + '/subscriptions')
    async def subscribe(workspace_id: str, request: Request, actor=Depends(session)):
        return response(await run_in_threadpool(invoke, 'subscribe', workspace_id, await body(request), actor))

    @router.post(BASE + '/events/prepare')
    async def prepare(workspace_id: str, request: Request, actor=Depends(session)):
        return response(await run_in_threadpool(invoke, 'prepare', workspace_id, await body(request), actor))

    @router.post(BASE + '/events/dispatch')
    async def dispatch(workspace_id: str, request: Request, actor=Depends(session)):
        return response(await run_in_threadpool(invoke, 'dispatch', workspace_id, await body(request), actor))

    @router.post(BASE + '/subscriptions/withdraw')
    async def withdraw(workspace_id: str, request: Request, actor=Depends(session)):
        return response(await run_in_threadpool(invoke, 'withdraw', workspace_id, await body(request), actor))

    @router.post(BASE + '/subscriptions/automatic-grant')
    async def automatic_grant(workspace_id: str, request: Request, actor=Depends(session)):
        automation = getattr(core, 'automation', None)
        if automation is None:
            raise HTTPException(404, 'Automatic evidence updates are unavailable.')
        return response(await run_in_threadpool(invoke, 'authorize', workspace_id,
            await body(request), actor, target=automation))

    if receiver is not None:
        @router.get(BASE + '/receivers/status')
        def receiver_status(workspace_id: str, request: Request, actor=Depends(session)):
            if request.query_params:
                raise HTTPException(400, 'Read the current receiver state without extra fields.')
            return response(invoke('status', workspace_id, actor, target=receiver))

        @router.post(BASE + '/receivers/{action}')
        async def receiver_action(workspace_id: str, action: str, request: Request, actor=Depends(session)):
            if action not in ('activate', 'revoke'):
                raise HTTPException(404, 'The private receiver action is unavailable.')
            result = await run_in_threadpool(invoke, action, workspace_id, await body(request), actor, target=receiver)
            return response(result)

    return router
