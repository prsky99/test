"""Individual-session staff API; no public payment or notification ingress."""
from pathlib import Path
import re
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .broker.server import RateLimiter
from .gateway import admin_auth
from .workspace_access import SessionActor, WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid
from .workspace_protocol_conformance import PROFILE
from .workspace_x402_eip3009 import EIP3009Invalid
from .workspace_service import WorkspaceRoute
from .workflow_publication_service import no_store, read_object

BASE = '/admin/api/workflow-workspaces/{workspace_id}/protocol-conformance'
ASSET = Path(__file__).parent / 'gateway' / 'workspace-protocol-conformance-admin.js'


def router_for(core):
    router = APIRouter(route_class=WorkspaceRoute)
    reads, writes = RateLimiter(120), RateLimiter(20)

    def session(request: Request):
        raw = request.headers.get('authorization', '')
        if request.headers.get('x-dashboard') != '1' or not re.fullmatch(r'Bearer [a-f0-9]{64}', raw):
            raise HTTPException(401, 'Use an individual administrator session.')
        with core.store.tx() as db:
            user = admin_auth.get_session_user(db, raw[7:])
        if not user:
            raise HTTPException(401, 'The individual session is unavailable.')
        if not (reads if request.method == 'GET' else writes).allow(str(user['user_id'])):
            raise HTTPException(429, 'Private review request limit reached.')
        return SessionActor(user['user_id'], admin_auth.session_reference(raw[7:]))

    def invoke(method, *args):
        try:
            return JSONResponse({'ok': True, 'profile': PROFILE, 'result': getattr(core, method)(*args)}, headers=no_store())
        except EIP3009Invalid as exc:
            return JSONResponse({'ok':False,'error_code':exc.error_code,'validation_stage':exc.stage,
                'profile':PROFILE,'verified_payment':False,'settlement_authorized':False},
                status_code=400,headers=no_store())
        except WorkspaceDenied:
            raise HTTPException(404, 'The current workspace or signed sandbox source is unavailable.') from None
        except WorkspaceConflict:
            raise HTTPException(409, 'The signed source changed. Inspect existing history before another action.') from None
        except WorkspaceInvalid:
            raise HTTPException(400, 'Provide the exact bounded synthetic review fields.') from None
        except sqlite3.DatabaseError:
            raise HTTPException(503, 'Private review storage is unavailable.') from None
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
            raise HTTPException(400, 'The private review could not be validated.') from None

    @router.get('/admin/assets/workspace-protocol-conformance-admin.js', include_in_schema=False)
    def asset():
        return Response(ASSET.read_bytes(), media_type='application/javascript', headers=no_store())

    @router.get(BASE)
    def status(workspace_id: str, request: Request, actor=Depends(session)):
        if request.query_params:
            raise HTTPException(400, 'Read current state without extra fields.')
        return invoke('status', workspace_id, actor)

    @router.get(BASE + '/reports/{report_id}')
    def report(workspace_id: str, report_id: str, request: Request, actor=Depends(session)):
        if request.query_params:
            raise HTTPException(400, 'Read one retained report without extra fields.')
        return invoke('report', workspace_id, report_id, actor)

    @router.post(BASE + '/runs')
    async def run(workspace_id: str, request: Request, actor=Depends(session)):
        try:
            if (request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json'
                    or request.headers.get('content-encoding', 'identity').lower() != 'identity'):
                raise ValueError()
            body = await read_object(request, 4096)
        except (ValueError, TypeError, UnicodeError, TimeoutError, RecursionError):
            raise HTTPException(400, 'Provide one bounded JSON object.') from None
        return await run_in_threadpool(invoke, 'run', workspace_id, body, actor)

    @router.post(BASE + '/cryptographic-check')
    async def cryptographic_check(workspace_id: str, request: Request, actor=Depends(session)):
        try:
            body = await read_object(request, 16384)
        except (ValueError, TypeError, UnicodeError, TimeoutError, RecursionError):
            raise HTTPException(400, 'Provide one bounded proof and its independently pinned context.') from None
        return await run_in_threadpool(invoke, 'cryptographic_check', workspace_id, body, actor)

    return router
