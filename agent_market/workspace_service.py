"""Authenticated administrative transport for separate private workspace objects."""
import re
import sqlite3
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .broker.server import RateLimiter
from .gateway import admin_auth
from .gateway.admin_security import AdminRoute
from .workflow_product_semantics_service import bounded_tree
from .workflow_publication_service import no_store, read_object
from .workspace_access import (
    PROFILE, SessionActor, WorkspaceAccess,
    WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid,
)

BASE = '/admin/api/workflow-workspaces'
ASSET = Path(__file__).parent / 'gateway' / 'workspace-admin.js'


class WorkspaceRoute(AdminRoute):
    """Keep private responses and every routed failure outside shared caches."""
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def secured(request):
            try:
                response = await handler(request)
            except HTTPException as error:
                return JSONResponse({'detail': error.detail}, status_code=error.status_code,
                                    headers={**(error.headers or {}), **no_store()})
            except RequestValidationError:
                return JSONResponse({'detail': 'Provide a valid private workspace request.'},
                                    status_code=422, headers=no_store())
            except Exception as error:
                reference = uuid.uuid4().hex
                # Log a route template and exception type, never request data or secrets.
                logging.getLogger(__name__).error(
                    'Private route failed reference=%s method=%s route=%s exception=%s',
                    reference, request.method, self.path, type(error).__name__)
                return JSONResponse({'detail': 'Private workspace access is temporarily unavailable.'},
                                    status_code=500, headers={**no_store(), 'X-Request-ID': reference})
            response.headers.update(no_store())
            return response
        return secured


def router_for(store, key, proxy=None, *, access=None, execution=None):
    core = access if access is not None else WorkspaceAccess(store, key)
    from .concierge.proxy import McpProxy
    from .workspace_execution import PROFILE as RUN_PROFILE, WorkspaceExecution
    execution = execution if execution is not None else WorkspaceExecution(core, proxy if proxy is not None else McpProxy(store))
    if core.store is not store or execution.access is not core:
        raise WorkspaceInvalid()
    router = APIRouter(prefix=BASE, route_class=WorkspaceRoute)
    reads, writes = RateLimiter(240), RateLimiter(60)

    def session(request: Request):
        # A configured machine token, loopback fallback, visitor or deployment
        # capability is not an individual workspace identity.
        authorization = request.headers.get('authorization', '')
        if request.headers.get('x-dashboard') != '1' or not re.fullmatch(r'Bearer [a-f0-9]{64}', authorization):
            raise HTTPException(401, 'Sign in with an individual administrator session.')
        token = authorization[7:]
        with store.tx() as db:
            user = admin_auth.get_session_user(db, token)
        if not user:
            raise HTTPException(401, 'The individual administrator session is unavailable.')
        actor = SessionActor(user['user_id'], admin_auth.session_reference(token))
        limit = reads if request.method == 'GET' else writes
        if not limit.allow(str(actor.user_id)):
            raise HTTPException(429, 'Private workspace request limit reached.', headers={'Retry-After': '60'})
        return actor

    def invoke(method, actor, *arguments, target=None):
        try:
            return getattr(core if target is None else target, method)(*arguments, actor)
        except WorkspaceDenied:
            raise HTTPException(404, 'The private workspace object is unavailable.') from None
        except WorkspaceConflict:
            raise HTTPException(409, 'The private revision changed. Reload before saving.') from None
        except WorkspaceInvalid:
            raise HTTPException(400, 'Provide the exact bounded private workspace fields.') from None
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
            raise HTTPException(400, 'The private workspace request could not be validated.') from None
        except sqlite3.DatabaseError:
            raise HTTPException(503, 'Private workspace storage is temporarily unavailable.') from None

    async def body(request):
        try:
            # Read raw bytes even when AdminRoute has populated request._json:
            # duplicate keys must not be collapsed by the generic parser.
            return bounded_tree(await read_object(request, 65536))
        except (ValueError, TypeError, UnicodeError, RecursionError, TimeoutError):
            raise HTTPException(400, 'Provide one bounded private workspace JSON object.') from None

    def envelope(**values):
        return JSONResponse({'ok': True, 'profile': PROFILE, **values}, headers=no_store())

    @router.get('/options')
    def options(actor=Depends(session)):
        value = invoke('options', actor)
        value['user'] = {**value['user'], 'can_provision': value['can_provision']}
        return envelope(**value, execution_enabled=False)

    @router.get('')
    def workspaces(actor=Depends(session)):
        return envelope(workspaces=invoke('workspaces', actor))

    @router.post('')
    async def provision(request: Request, actor=Depends(session)):
        value = await run_in_threadpool(invoke, 'provision', actor, await body(request))
        return envelope(workspace=value)

    @router.get('/{workspace_id}')
    def workspace(workspace_id: str, actor=Depends(session)):
        return envelope(workspace=invoke('workspace', actor, workspace_id))

    @router.post('/{workspace_id}/archive')
    async def archive(workspace_id: str, request: Request, actor=Depends(session)):
        value = await run_in_threadpool(invoke, 'set_active', actor, workspace_id, await body(request))
        return envelope(workspace=value)

    @router.get('/{workspace_id}/members')
    def members(workspace_id: str, actor=Depends(session)):
        return envelope(members=invoke('members', actor, workspace_id))

    @router.post('/{workspace_id}/members')
    async def set_member(workspace_id: str, request: Request, actor=Depends(session)):
        value = await run_in_threadpool(invoke, 'set_member', actor, workspace_id, await body(request))
        return envelope(member=value)

    @router.get('/{workspace_id}/audit')
    def audit(workspace_id: str, actor=Depends(session)):
        return envelope(events=invoke('audit', actor, workspace_id))

    @router.get('/{workspace_id}/drafts')
    def drafts(workspace_id: str, actor=Depends(session)):
        return envelope(drafts=invoke('drafts', actor, workspace_id))

    @router.post('/{workspace_id}/drafts')
    async def save_draft(workspace_id: str, request: Request, actor=Depends(session)):
        value = await run_in_threadpool(invoke, 'save_draft', actor, workspace_id, await body(request))
        return envelope(draft=value)

    @router.get('/{workspace_id}/drafts/{draft_id}')
    def draft(workspace_id: str, draft_id: str, actor=Depends(session)):
        return envelope(draft=invoke('draft', actor, workspace_id, draft_id))

    @router.post('/{workspace_id}/drafts/{draft_id}/archive')
    async def archive_draft(workspace_id: str, draft_id: str, request: Request, actor=Depends(session)):
        value = await run_in_threadpool(invoke, 'revoke_draft', actor, workspace_id, draft_id, await body(request))
        return envelope(draft=value)

    @router.get('/{workspace_id}/drafts/{draft_id}/snapshots')
    def snapshots(workspace_id: str, draft_id: str, actor=Depends(session)):
        return envelope(snapshots=invoke('versions', actor, workspace_id, draft_id))

    @router.post('/{workspace_id}/drafts/{draft_id}/snapshots')
    async def snapshot(workspace_id: str, draft_id: str, request: Request, actor=Depends(session)):
        value = await run_in_threadpool(invoke, 'create_snapshot', actor, workspace_id, draft_id, await body(request))
        return envelope(snapshot=value)

    @router.get('/{workspace_id}/drafts/{draft_id}/snapshots/{version_id}')
    def read_snapshot(workspace_id: str, draft_id: str, version_id: str, actor=Depends(session)):
        return envelope(snapshot=invoke('version', actor, workspace_id, draft_id, version_id))

    @router.post('/{workspace_id}/drafts/{draft_id}/snapshots/{version_id}/revoke')
    async def revoke_snapshot(workspace_id: str, draft_id: str, version_id: str, request: Request, actor=Depends(session)):
        value = await run_in_threadpool(invoke, 'revoke_version', actor, workspace_id, draft_id, version_id, await body(request))
        return envelope(snapshot=value)

    @router.get('/{workspace_id}/drafts/{draft_id}/snapshots/{version_id}/artifact')
    def artifact(workspace_id: str, draft_id: str, version_id: str, actor=Depends(session)):
        value = invoke('version', actor, workspace_id, draft_id, version_id)
        # This is an authenticated JSON snapshot, not an executable web app,
        # publication grant or bearer credential for the static client.
        document = {name: value[name] for name in ('id', 'workspace_id', 'draft_id', 'draft_revision',
                    'definition_hash', 'snapshot', 'saved_snapshot', 'executable', 'deployable', 'published')}
        return JSONResponse({'profile': PROFILE, **document}, headers={**no_store(),
            'Content-Disposition': f'attachment; filename="private-snapshot-{value["id"]}.json"'})

    # Private execution never enters legacy workflow/run tables or their global
    # administrator readers. Every operation retains all three object scopes.
    private = '/{workspace_id}/drafts/{draft_id}/snapshots/{version_id}/execution'

    def run_envelope(**values):
        return JSONResponse({'ok': True, 'profile': RUN_PROFILE, **values}, headers=no_store())

    @router.get(private + '/options')
    def execution_options(workspace_id: str, draft_id: str, version_id: str, actor=Depends(session)):
        value = invoke('options', actor, workspace_id, draft_id, version_id, target=execution)
        return run_envelope(**value)

    @router.post(private + '/prepare')
    async def execution_prepare(workspace_id: str, draft_id: str, version_id: str,
                                request: Request, actor=Depends(session)):
        value = await run_in_threadpool(invoke, 'prepare', actor, workspace_id, draft_id, version_id,
                                       await body(request), target=execution)
        return run_envelope(**value)

    @router.post(private + '/runs')
    async def execution_run(workspace_id: str, draft_id: str, version_id: str,
                            request: Request, actor=Depends(session)):
        value = await run_in_threadpool(invoke, 'execute', actor, workspace_id, draft_id, version_id,
                                       await body(request), target=execution)
        return run_envelope(run=value)

    @router.get(private + '/runs')
    def execution_runs(workspace_id: str, draft_id: str, version_id: str, actor=Depends(session)):
        value = invoke('runs', actor, workspace_id, draft_id, version_id, target=execution)
        return run_envelope(runs=value)

    @router.get(private + '/runs/{run_id}')
    def execution_result(workspace_id: str, draft_id: str, version_id: str, run_id: str,
                         actor=Depends(session)):
        value = invoke('run', actor, workspace_id, draft_id, version_id, run_id, target=execution)
        return run_envelope(run=value)

    return router


def asset_response():
    return Response(ASSET.read_bytes(), media_type='application/javascript', headers=no_store())
