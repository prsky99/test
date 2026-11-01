"""Named administrator transport for private bounded evaluation contracts."""
import re
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .broker.server import RateLimiter
from .gateway import admin_auth
from .workflow_publication_service import no_store, read_object
from .workspace_access import SessionActor, WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid
from .workspace_reliability import PROFILE, ReliabilityEvidence
from .workspace_service import WorkspaceRoute

BASE = '/admin/api/workflow-workspaces/{workspace_id}/reliability'


def router_for(access, execution, *, core=None, evaluator=None):
    core = core if core is not None else ReliabilityEvidence(access, execution, evaluator=evaluator)
    if core.access is not access or core.execution is not execution: raise WorkspaceInvalid()
    router = APIRouter(prefix=BASE, route_class=WorkspaceRoute)
    reads, writes = RateLimiter(240), RateLimiter(60)

    def session(request: Request):
        authorization = request.headers.get('authorization', '')
        if request.headers.get('x-dashboard') != '1' or not re.fullmatch(r'Bearer [a-f0-9]{64}', authorization):
            raise HTTPException(401, 'Sign in with an individual administrator session.')
        with access.store.tx() as db: user = admin_auth.get_session_user(db, authorization[7:])
        if not user: raise HTTPException(401, 'The individual administrator session is unavailable.')
        if not (reads if request.method == 'GET' else writes).allow(str(user['user_id'])):
            raise HTTPException(429, 'Private evidence request limit reached.')
        return SessionActor(user['user_id'], admin_auth.session_reference(authorization[7:]))

    def invoke(method, ws, actor, *args):
        try: return getattr(core, method)(ws, *args, actor)
        except WorkspaceDenied: raise HTTPException(404, 'The private evidence object is unavailable.') from None
        except WorkspaceConflict: raise HTTPException(409, 'Evidence or current authority changed. Read current state.') from None
        except WorkspaceInvalid: raise HTTPException(400, 'Provide the exact bounded evaluation fields.') from None
        except sqlite3.DatabaseError: raise HTTPException(503, 'Private evidence storage is unavailable.') from None
        except (TypeError, ValueError, KeyError, UnicodeError, RecursionError):
            raise HTTPException(400, 'The private evidence request could not be validated.') from None

    def result(value):
        return JSONResponse({'ok': True, 'profile': PROFILE, 'result': value}, headers=no_store())

    @router.get('/options')
    def options(workspace_id: str, actor=Depends(session)):
        return result(invoke('options', workspace_id, actor))

    @router.get('/objects')
    def objects(workspace_id: str, actor=Depends(session)):
        return result(invoke('list_objects', workspace_id, actor))

    @router.get('/inventory')
    def inventory(workspace_id: str, actor=Depends(session)):
        return result(invoke('inventory', workspace_id, actor))

    @router.get('/report')
    def report(workspace_id: str, request: Request, actor=Depends(session)):
        query = request.query_params
        if set(query) != {'resource_id'} or len(query.getlist('resource_id')) != 1 or not re.fullmatch(r'[1-9][0-9]{0,9}', query['resource_id']):
            raise HTTPException(400, 'Choose one catalog resource reference.')
        value = invoke('current_report', workspace_id, actor, int(query['resource_id']))
        tag = '"' + value['source_revision'] + '"'
        headers = {**no_store(), 'ETag': tag, 'Vary': 'Authorization, X-Dashboard, Origin'}
        if request.headers.get('if-none-match') == tag: return Response(status_code=304, headers=headers)
        return JSONResponse({'ok': True, 'profile': PROFILE, 'result': value}, headers=headers)

    @router.post('/{action}')
    async def write(workspace_id: str, action: str, request: Request, actor=Depends(session)):
        actions = {'objects': 'save_object', 'consents': 'authorize_cohort', 'sources': 'retain_source',
                   'observations': 'observe', 'erasures': 'erase', 'retention-cleanup': 'erase_expired'}
        if action not in actions: raise HTTPException(404, 'The evaluation action is unavailable.')
        try: body = await read_object(request, 49152)
        except (TypeError, ValueError, UnicodeError, RecursionError, TimeoutError):
            raise HTTPException(400, 'Provide one bounded private evaluation object.') from None
        return result(await run_in_threadpool(invoke, actions[action], workspace_id, actor, body))

    @router.post('/sources/{source_id}/inspect')
    async def inspect(workspace_id: str, source_id: str, request: Request, actor=Depends(session)):
        try: body = await read_object(request, 2048)
        except (TypeError, ValueError, UnicodeError, RecursionError, TimeoutError):
            raise HTTPException(400, 'Provide explicit source inspection authorization.') from None
        return result(await run_in_threadpool(invoke, 'inspect_source', workspace_id, actor, source_id, body))

    return router
