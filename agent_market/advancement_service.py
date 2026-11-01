"""Private workspace transport for simulation, reviewed support and readiness."""
import re
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .broker.server import RateLimiter
from .gateway import admin_auth
from .workspace_service import WorkspaceRoute
from .workflow_product_semantics_service import bounded_tree
from .workflow_publication_service import no_store, read_object
from .workspace_access import SessionActor, WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid
from .shadow_ledger import ShadowLedger
from .workflow_support import WorkflowSupport
from .advancement_readiness import AdvancementReadiness

BASE = '/admin/api/workflow-workspaces/{workspace_id}/advancement'
PROFILE = 'workspace-advancement-tools-v1'


def router_for(access, *, evidence_sources=None, meter=None, support_engine=None, agreements=None,
               sandbox_payments=None, identity=None, preparation_sources=None):
    ledger, support = ShadowLedger(access), WorkflowSupport(access)
    readiness = AdvancementReadiness(access, evidence_sources=evidence_sources)
    from .workspace_ai_support import WorkspaceAISupport
    assistant = WorkspaceAISupport(access, support_engine)
    from .workspace_operating_preparation import OperatingPreparation
    preparation = OperatingPreparation(access, readiness, identity=identity,
        sandbox_payments=sandbox_payments, sources=preparation_sources)
    if meter is None:
        from .workspace_metering import WorkspaceMetering
        meter = WorkspaceMetering(access)
    router = APIRouter(prefix=BASE, route_class=WorkspaceRoute)
    reads, writes = RateLimiter(240), RateLimiter(60)

    def session(request: Request):
        authorization = request.headers.get('authorization', '')
        if request.headers.get('x-dashboard') != '1' or not re.fullmatch(r'Bearer [a-f0-9]{64}', authorization):
            raise HTTPException(401, 'Sign in with an individual administrator session.')
        with access.store.tx() as db:
            user = admin_auth.get_session_user(db, authorization[7:])
        if not user: raise HTTPException(401, 'The individual session is unavailable.')
        actor = SessionActor(user['user_id'], admin_auth.session_reference(authorization[7:]))
        if not (reads if request.method == 'GET' else writes).allow(str(actor.user_id)):
            raise HTTPException(429, 'Workspace request limit reached.')
        return actor

    def invoke(target, method, ws, actor, *arguments):
        try:
            value = getattr(target, method)(ws, *arguments, actor)
            return JSONResponse({'ok': True, 'profile': PROFILE, 'result': value}, headers=no_store())
        except WorkspaceDenied:
            raise HTTPException(404, 'The private workspace object is unavailable.') from None
        except WorkspaceConflict:
            raise HTTPException(409, 'The private state changed or could not be confirmed. Reload before proceeding.') from None
        except WorkspaceInvalid:
            raise HTTPException(400, 'Provide the exact bounded workspace fields.') from None
        except sqlite3.DatabaseError:
            raise HTTPException(503, 'Private storage is temporarily unavailable.') from None
        except (TypeError, ValueError, KeyError, UnicodeError, RecursionError):
            raise HTTPException(400, 'The workspace request could not be validated.') from None

    async def body(request):
        try: return bounded_tree(await read_object(request, 65536))
        except (TypeError, ValueError, UnicodeError, RecursionError, TimeoutError):
            raise HTTPException(400, 'Provide one bounded workspace JSON object.') from None

    @router.get('/ledger/options')
    def ledger_options(workspace_id: str, actor=Depends(session)):
        return invoke(ledger, 'options', workspace_id, actor)

    @router.get('/runtime-meter')
    def meter_summary(workspace_id: str, actor=Depends(session)):
        return invoke(meter, 'summary', workspace_id, actor)

    @router.post('/runtime-meter')
    async def meter_configure(workspace_id: str, request: Request, actor=Depends(session)):
        return await run_in_threadpool(invoke, meter, 'configure', workspace_id, actor, await body(request))

    @router.post('/runtime-meter/recover')
    async def meter_recover(workspace_id: str, request: Request, actor=Depends(session)):
        if await body(request) != {}:
            raise HTTPException(400, 'Use the current owner recovery action without replacement outcomes.')
        return await run_in_threadpool(invoke, meter, 'recover', workspace_id, actor)

    @router.get('/ledger')
    def ledger_summary(workspace_id: str, actor=Depends(session)):
        return invoke(ledger, 'summary', workspace_id, actor)

    @router.post('/ledger/{action}')
    async def ledger_change(workspace_id: str, action: str, request: Request, actor=Depends(session)):
        if action not in ('approve', 'post', 'reverse', 'reconcile'): raise HTTPException(404, 'Action unavailable.')
        return await run_in_threadpool(invoke, ledger, action, workspace_id, actor, await body(request))

    @router.get('/support')
    def support_options(workspace_id: str, actor=Depends(session)):
        return invoke(support, 'options', workspace_id, actor)

    @router.get('/support/assistant')
    def assistant_options(workspace_id: str, actor=Depends(session)):
        return invoke(assistant, 'options', workspace_id, actor)

    @router.post('/support/assistant')
    async def assistant_suggest(workspace_id: str, request: Request, actor=Depends(session)):
        value = await body(request)
        if type(value) is not dict or not {'draft_id', 'snapshot_id'} <= set(value):
            raise HTTPException(400, 'Select a scoped draft and snapshot.')
        value = dict(value); wd, wv = value.pop('draft_id'), value.pop('snapshot_id')
        return await run_in_threadpool(invoke, assistant, 'suggest', workspace_id, actor, wd, wv, value)

    @router.get('/support/proposals')
    def support_history(workspace_id: str, actor=Depends(session)):
        return invoke(support, 'proposals', workspace_id, actor)

    @router.get('/support/proposals/{proposal_id}')
    def support_proposal(workspace_id: str, proposal_id: str, actor=Depends(session)):
        return invoke(support, 'proposal', workspace_id, actor, proposal_id)

    @router.post('/support/proposals')
    async def support_propose(workspace_id: str, request: Request, actor=Depends(session)):
        value = await body(request)
        if type(value) is not dict or not {'draft_id', 'snapshot_id'} <= set(value):
            raise HTTPException(400, 'Select a scoped draft and snapshot.')
        value = dict(value); wd, wv = value.pop('draft_id'), value.pop('snapshot_id')
        return await run_in_threadpool(invoke, support, 'propose', workspace_id, actor, wd, wv, value)

    @router.post('/support/proposals/{proposal_id}/apply')
    async def support_apply(workspace_id: str, proposal_id: str, request: Request, actor=Depends(session)):
        return await run_in_threadpool(invoke, support, 'apply', workspace_id, actor, proposal_id, await body(request))

    @router.get('/readiness')
    def current_readiness(workspace_id: str, actor=Depends(session)):
        return invoke(readiness, 'status', workspace_id, actor)

    @router.get('/operating-preparation')
    def operating_preparation(workspace_id: str, actor=Depends(session)):
        return invoke(preparation, 'status', workspace_id, actor)

    if sandbox_payments is not None:
        @router.get('/sandbox-payments')
        def sandbox_status(workspace_id: str, actor=Depends(session)):
            return invoke(sandbox_payments, 'status', workspace_id, actor)

        @router.post('/sandbox-payments/{action}')
        async def sandbox_command(workspace_id: str, action: str, request: Request, actor=Depends(session)):
            if action not in ('prepare', 'dispatch', 'withdraw'):
                raise HTTPException(404, 'Sandbox action unavailable.')
            return await run_in_threadpool(invoke, sandbox_payments, action, workspace_id, actor, await body(request))

    @router.post('/readiness/declarations')
    async def readiness_declare(workspace_id: str, request: Request, actor=Depends(session)):
        return await run_in_threadpool(invoke, readiness, 'record', workspace_id, actor, await body(request))

    if agreements is not None:
        @router.get('/agreements/options')
        def agreement_options(workspace_id: str, actor=Depends(session)):
            return invoke(agreements, 'options', workspace_id, actor)

        @router.get('/agreements')
        def agreement_versions(workspace_id: str, actor=Depends(session)):
            return invoke(agreements, 'versions', workspace_id, actor)

        @router.get('/agreements/summary')
        def agreement_summary(workspace_id: str, actor=Depends(session)):
            return invoke(agreements, 'summary', workspace_id, actor)

        @router.post('/agreements')
        async def agreement_create(workspace_id: str, request: Request, actor=Depends(session)):
            return await run_in_threadpool(invoke, agreements, 'create', workspace_id, actor, await body(request))

        @router.post('/agreements/{agreement_id}/{action}')
        async def agreement_action(workspace_id: str, agreement_id: str, action: str,
                                   request: Request, actor=Depends(session)):
            if action not in ('quote', 'settle', 'revoke'):
                raise HTTPException(404, 'Agreement action unavailable.')
            return await run_in_threadpool(invoke, agreements, action, workspace_id, actor,
                                          agreement_id, await body(request))

        @router.post('/agreement-settlements/{settlement_id}/refund')
        async def agreement_refund(workspace_id: str, settlement_id: str, request: Request,
                                   actor=Depends(session)):
            return await run_in_threadpool(invoke, agreements, 'refund', workspace_id, actor,
                                          settlement_id, await body(request))

    return router
