"""Individual-session-only controls for evaluation, trust preview and routing shadow."""
import re
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .broker.server import RateLimiter
from .capability_registry import digest
from .gateway import admin_auth
from .reliability_evaluation import PROFILE as EVALUATION_PROFILE, ReliabilityEvaluation
from .reliability_routing import PROFILE as ROUTING_PROFILE, ReliabilityRouting
from .reliability_trust import PROFILE as TRUST_PROFILE, ReliabilityTrust, safe_badge
from .workspace_access import SessionActor, WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid
from .workspace_service import WorkspaceRoute
from .workflow_publication_service import no_store, read_object

BASE = '/admin/api/workflow-workspaces/{workspace_id}/reliability'


def router_for(access, runtime, *, evaluation=None, trust=None, routing=None, evidence_source=None,
               evidence=None, circuit=None, early_stop=None, publication=None):
    evaluation = evaluation if evaluation is not None else ReliabilityEvaluation(access, runtime)
    trust = trust if trust is not None else ReliabilityTrust(access, evidence_source=evidence_source)
    routing = routing if routing is not None else ReliabilityRouting(access, runtime, evidence_source=evidence_source)
    if any(core.access is not access for core in (evaluation, trust, routing)):
        raise WorkspaceInvalid()
    if any(core is not None and core.access is not access for core in (evidence, circuit, early_stop, publication)):
        raise WorkspaceInvalid()
    router = APIRouter(prefix=BASE, route_class=WorkspaceRoute)
    reads, writes = RateLimiter(240), RateLimiter(60)

    def session(request: Request):
        authorization = request.headers.get('authorization', '')
        if request.headers.get('x-dashboard') != '1' or not re.fullmatch(r'Bearer [a-f0-9]{64}', authorization):
            raise HTTPException(401, 'Sign in with an individual administrator session.')
        with access.store.tx() as db:
            user = admin_auth.get_session_user(db, authorization[7:])
        if not user:
            raise HTTPException(401, 'The individual session is unavailable.')
        if not (reads if request.method == 'GET' else writes).allow(str(user['user_id'])):
            raise HTTPException(429, 'Reliability control request limit reached.')
        return SessionActor(user['user_id'], admin_auth.session_reference(authorization[7:]))

    def invoke(core, method, *args):
        try:
            return getattr(core, method)(*args)
        except WorkspaceDenied:
            raise HTTPException(404, 'The scoped reliability object is unavailable.') from None
        except WorkspaceConflict:
            raise HTTPException(409, 'Current evidence, approval or authority changed. Read current state.') from None
        except WorkspaceInvalid:
            raise HTTPException(400, 'Provide the exact bounded reliability fields.') from None
        except sqlite3.DatabaseError:
            raise HTTPException(503, 'Reliability storage is unavailable.') from None
        except (TypeError, ValueError, KeyError, UnicodeError, RecursionError):
            raise HTTPException(400, 'Reliability data could not be validated.') from None

    def reply(profile, result):
        return JSONResponse({'ok': True, 'profile': profile, 'result': result}, headers=no_store())

    async def body(request):
        try:
            return await read_object(request, 32768)
        except (TypeError, ValueError, UnicodeError, RecursionError, TimeoutError):
            raise HTTPException(400, 'Provide one bounded reliability JSON object.') from None

    @router.get('/evaluation/options')
    def evaluation_options(workspace_id: str, actor=Depends(session)):
        return reply(EVALUATION_PROFILE, invoke(evaluation, 'options', workspace_id, actor))

    @router.get('/evaluation/status')
    def evaluation_status(workspace_id: str, actor=Depends(session)):
        return reply(EVALUATION_PROFILE, invoke(evaluation, 'status', workspace_id, actor))

    @router.post('/evaluation/{action}')
    async def evaluation_action(workspace_id: str, action: str, request: Request, actor=Depends(session)):
        methods = {'control': 'set_control', 'corpora': 'register_corpus', 'plans': 'configure_plan', 'reserve': 'reserve'}
        if action not in methods:
            raise HTTPException(404, 'Evaluation action unavailable.')
        result = await run_in_threadpool(invoke, evaluation, methods[action], workspace_id, await body(request), actor)
        return reply(EVALUATION_PROFILE, result)

    @router.post('/evaluation/jobs/{job_id}/{action}')
    async def job_action(workspace_id: str, job_id: str, action: str, request: Request, actor=Depends(session)):
        if action not in ('prepare', 'dispatch', 'cancel'):
            raise HTTPException(404, 'Evaluation job action unavailable.')
        result = await run_in_threadpool(invoke, evaluation, action, workspace_id, job_id, await body(request), actor)
        return reply(EVALUATION_PROFILE, result)

    worker = getattr(evaluation, 'worker', None)
    if worker is not None:
        @router.get('/evaluation/worker/status')
        def worker_status(workspace_id: str, request: Request, actor=Depends(session)):
            if request.query_params:
                raise HTTPException(400, 'Read the current worker state without extra fields.')
            return reply(EVALUATION_PROFILE, invoke(worker, 'status', workspace_id, actor))

        @router.post('/evaluation/worker/{action}')
        async def worker_action(workspace_id: str, action: str, request: Request, actor=Depends(session)):
            if action not in ('activate', 'deactivate'):
                raise HTTPException(404, 'The private worker action is unavailable.')
            result = await run_in_threadpool(invoke, worker, action + '_for', workspace_id, await body(request), actor)
            return reply(EVALUATION_PROFILE, result)

    def trust_read(ws, rid, actor, request, svg=False):
        # Authority and current evidence are recomputed before conditional response.
        result, tag = invoke(trust, 'projection', ws, rid, actor)
        tag = '"'+digest([tag, 'svg' if svg else 'json'])+'"'
        headers = {**no_store(), 'ETag': tag, 'Vary': 'Authorization, X-Dashboard, Origin',
                   'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "default-src 'none'; sandbox"}
        if request.headers.get('if-none-match') == tag:
            return Response(status_code=304, headers=headers)
        if svg:
            return Response(safe_badge(result), media_type='image/svg+xml', headers=headers)
        return JSONResponse({'ok': True, 'profile': TRUST_PROFILE, 'result': result}, headers=headers)

    @router.get('/trust/{resource_id}/badge.svg')
    def badge(workspace_id: str, resource_id: int, request: Request, actor=Depends(session)):
        return trust_read(workspace_id, resource_id, actor, request, svg=True)

    @router.get('/trust/{resource_id}')
    def trust_preview(workspace_id: str, resource_id: int, request: Request, actor=Depends(session)):
        return trust_read(workspace_id, resource_id, actor, request)

    @router.get('/routing/status')
    def routing_status(workspace_id: str, actor=Depends(session)):
        return reply(ROUTING_PROFILE, invoke(routing, 'status', workspace_id, actor))

    @router.post('/routing/{action}')
    async def routing_action(workspace_id: str, action: str, request: Request, actor=Depends(session)):
        if action not in ('configure', 'decide', 'replay'):
            raise HTTPException(404, 'Routing action unavailable.')
        result = await run_in_threadpool(invoke, routing, 'offline_replay' if action == 'replay' else action,
                                        workspace_id, await body(request), actor)
        return reply(ROUTING_PROFILE, result)

    if evidence is not None:
        from .workspace_reliability import PROFILE as EVIDENCE_PROFILE

        @router.get('/operating/{resource_id}')
        def operating_status(workspace_id: str, resource_id: int, request: Request, actor=Depends(session)):
            if request.query_params:
                raise HTTPException(400, 'Read current qualification without extra fields.')
            return reply(EVIDENCE_PROFILE, invoke(evidence, 'operating_status', workspace_id, resource_id, actor))

        @router.post('/operating/{action}')
        async def operating_action(workspace_id: str, action: str, request: Request, actor=Depends(session)):
            methods = {'qualify': 'qualify_operating', 'withdraw': 'withdraw_operating'}
            if action not in methods:
                raise HTTPException(404, 'Operating evidence action unavailable.')
            result = await run_in_threadpool(invoke, evidence, methods[action], workspace_id, await body(request), actor)
            return reply(EVIDENCE_PROFILE, result)

    if circuit is not None:
        from .reliability_circuit import PROFILE as CIRCUIT_PROFILE

        @router.get('/circuits/{resource_id}')
        def circuit_status(workspace_id: str, resource_id: int, request: Request, actor=Depends(session)):
            if request.query_params:
                raise HTTPException(400, 'Read the exact circuit without extra fields.')
            return reply(CIRCUIT_PROFILE, invoke(circuit, 'status', workspace_id, resource_id, actor))

        @router.post('/circuits/{resource_id}/{action}')
        async def circuit_action(workspace_id: str, resource_id: int, action: str, request: Request, actor=Depends(session)):
            methods = {'configure': 'configure', 'ingest': 'ingest', 'bind-probe': 'bind_probe', 'refresh-probe': 'refresh_probe'}
            if action not in methods:
                raise HTTPException(404, 'The private circuit action is unavailable.')
            payload = await body(request)
            if action == 'configure':
                if payload.get('resource_id') != resource_id:
                    raise HTTPException(400, 'Choose the exact circuit resource.')
                args = (workspace_id, payload, actor)
            else:
                args = (workspace_id, resource_id, payload, actor)
            result = await run_in_threadpool(invoke, circuit, methods[action], *args)
            return reply(CIRCUIT_PROFILE, result)

    automation = getattr(worker, 'circuit_automation', None)
    if automation is not None:
        from .reliability_automation import PROFILE as AUTOMATION_PROFILE

        @router.get('/circuit-automation/status')
        def automation_status(workspace_id: str, request: Request, actor=Depends(session)):
            if request.query_params:
                raise HTTPException(400, 'Read current automation without extra fields.')
            return reply(AUTOMATION_PROFILE, invoke(automation, 'status', workspace_id, actor))

        @router.post('/circuit-automation/{action}')
        async def automation_action(workspace_id: str, action: str, request: Request, actor=Depends(session)):
            if action not in ('activate', 'deactivate'):
                raise HTTPException(404, 'Circuit automation action unavailable.')
            value = await run_in_threadpool(invoke, automation, action, workspace_id, await body(request), actor)
            return reply(AUTOMATION_PROFILE, value)

    if early_stop is not None:
        from .reliability_early_stop import PROFILE as STOP_PROFILE

        @router.get('/early-stop/status')
        def stop_status(workspace_id: str, request: Request, actor=Depends(session)):
            if request.query_params:
                raise HTTPException(400, 'Read current intervention state without extra fields.')
            return reply(STOP_PROFILE, invoke(early_stop, 'status', workspace_id, actor))

        @router.get('/early-stop/comparisons')
        def stop_comparisons(workspace_id: str, request: Request, actor=Depends(session)):
            if request.query_params:
                raise HTTPException(400, 'Read current comparison evidence without extra fields.')
            return reply(STOP_PROFILE, invoke(early_stop, 'comparison_report', workspace_id, actor))

        @router.post('/early-stop/{action}')
        async def stop_action(workspace_id: str, action: str, request: Request, actor=Depends(session)):
            if action not in ('configure', 'watch'):
                raise HTTPException(404, 'Intervention action unavailable.')
            value = await run_in_threadpool(invoke, early_stop, action, workspace_id, await body(request), actor)
            return reply(STOP_PROFILE, value)

        @router.post('/early-stop/runs/{run_id}/advance')
        async def stop_advance(workspace_id: str, run_id: str, request: Request, actor=Depends(session)):
            value = await run_in_threadpool(invoke, early_stop, 'advance', workspace_id, run_id, await body(request), actor)
            return reply(STOP_PROFILE, value)

        @router.post('/early-stop/runs/{run_id}/{action}')
        async def stop_comparison_action(workspace_id: str, run_id: str, action: str, request: Request, actor=Depends(session)):
            if action not in ('pair', 'assess-pair'):
                raise HTTPException(404, 'Comparison action unavailable.')
            method = 'assess_pair' if action == 'assess-pair' else 'pair'
            value = await run_in_threadpool(invoke, early_stop, method, workspace_id, run_id, await body(request), actor)
            return reply(STOP_PROFILE, value)

    if publication is not None:
        from .reliability_publication import PROFILE as PUBLICATION_PROFILE

        @router.post('/publication/{action}')
        async def publication_action(workspace_id: str, action: str, request: Request, actor=Depends(session)):
            methods = {'keys': 'publish_key', 'disclosures': 'disclose'}
            if action not in methods:
                raise HTTPException(404, 'Publication authority action unavailable.')
            value = await run_in_threadpool(invoke, publication, methods[action], workspace_id, await body(request), actor)
            return reply(PUBLICATION_PROFILE, value)

    return router
