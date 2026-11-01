"""Explicit private customer authoring transport; never mounted by default."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .broker.server import RateLimiter
from .customer_identity_service import customer_actor
from .customer_authoring import authoring_for
from .customer_workspace_runtime import CustomerRuntimeActor
from .workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid, WorkspaceLimit
from .workspace_release_service import build_package
from .workspace_service import WorkspaceRoute
from .workflow_publication_service import no_store, read_object, same_origin

BASE = '/api/customer-organizations/{ws}/authoring'


def router_for(platform):
    core = authoring_for(platform)
    router = APIRouter(route_class=WorkspaceRoute)
    from .customer_provider_connections_service import router_for as provider_router
    router.include_router(provider_router(core))
    limit = RateLimiter(60)

    def actor(ws, request, write=False, *, document=False):
        if request.headers.get('authorization'):
            raise HTTPException(403, 'Use your customer service session.')
        customer = customer_actor(request, core.identity, csrf=write, document=document)
        if not limit.allow(customer.customer_id):
            raise HTTPException(429, 'Please wait before another workspace request.', headers={'Retry-After':'60'})
        return invoke(core.actor, ws, customer)

    async def body(request):
        try:
            return await read_object(request, 65536)
        except (ValueError, TypeError, UnicodeError, TimeoutError):
            raise HTTPException(400, 'Provide one bounded workspace request.') from None

    def invoke(method, *args):
        from .customer_credits import CreditRequired
        try:
            return method(*args)
        except CreditRequired:
            raise HTTPException(409, 'Join the Free plan or review your available credits before saving or downloading.') from None
        except WorkspaceDenied:
            raise HTTPException(403, 'The workspace or current permission is unavailable.') from None
        except WorkspaceLimit as error:
            raise HTTPException(409, str(error)) from None
        except WorkspaceConflict:
            raise HTTPException(409, 'State changed or the outcome is uncertain. Inspect history.') from None
        except (WorkspaceInvalid, ValueError, TypeError, KeyError):
            raise HTTPException(400, 'Review the supported workspace fields.') from None

    def response(**value):
        return JSONResponse({'ok': True, 'profile': 'customer-authoring-v1', **value}, headers=no_store())

    scope = BASE + '/drafts/{draft}/snapshots/{snapshot}'

    @router.get(scope + '/options')
    def options(ws: str, draft: str, snapshot: str, request: Request):
        principal = actor(ws, request)
        return response(options=invoke(core.execution.options, ws, draft, snapshot, principal))

    @router.post(scope + '/prepare')
    async def prepare(ws: str, draft: str, snapshot: str, request: Request):
        principal = actor(ws, request, True)
        return response(review=await run_in_threadpool(invoke, core.execution.prepare,
            ws, draft, snapshot, await body(request), principal))

    @router.post(scope + '/runs')
    async def execute(ws: str, draft: str, snapshot: str, request: Request):
        principal = actor(ws, request, True)
        return response(run=await run_in_threadpool(invoke, core.execution.execute,
            ws, draft, snapshot, await body(request), principal))

    @router.get(scope + '/runs')
    def history(ws: str, draft: str, snapshot: str, request: Request):
        return response(runs=invoke(core.execution.runs, ws, draft, snapshot, actor(ws, request)))

    @router.get(scope + '/runs/{run}')
    def retained(ws: str, draft: str, snapshot: str, run: str, request: Request):
        return response(run=invoke(core.execution.run, ws, draft, snapshot, run, actor(ws, request)))

    @router.get(scope + '/releases')
    def releases(ws: str, draft: str, snapshot: str, request: Request):
        return response(releases=invoke(core.releases.releases, ws, draft, snapshot, actor(ws, request)))

    @router.post(scope + '/releases')
    async def release(ws: str, draft: str, snapshot: str, request: Request):
        principal = actor(ws, request, True)
        return response(release=await run_in_threadpool(invoke, core.releases.create,
            ws, draft, snapshot, await body(request), principal))

    @router.post(scope + '/releases/{release}/revoke')
    async def revoke(ws: str, draft: str, snapshot: str, release: str, request: Request):
        principal = actor(ws, request, True)
        return response(release=await run_in_threadpool(invoke, core.releases.revoke,
            ws, draft, snapshot, release, await body(request), principal))

    @router.get(scope + '/releases/{release}/deployments')
    def deployments(ws: str, draft: str, snapshot: str, release: str, request: Request):
        return response(deployments=invoke(core.releases.deployments,
            ws, draft, snapshot, release, actor(ws, request)))

    @router.post(scope + '/releases/{release}/deployments')
    async def deploy(ws: str, draft: str, snapshot: str, release: str, request: Request):
        principal = actor(ws, request, True)
        return response(deployment=await run_in_threadpool(invoke, core.releases.deploy,
            ws, draft, snapshot, release, await body(request), principal))

    @router.post(scope + '/deployments/{app}/revoke')
    async def revoke_app(ws: str, draft: str, snapshot: str, app: str, request: Request):
        principal = actor(ws, request, True)
        return response(deployment=await run_in_threadpool(invoke, core.releases.revoke_deployment,
            ws, draft, snapshot, app, await body(request), principal))

    @router.get(scope + '/deployments/{app}/package')
    def package(ws: str, draft: str, snapshot: str, app: str, request: Request):
        principal = actor(ws, request)
        config = invoke(core.releases.package_config, ws, draft, snapshot, app, principal)
        data, filename = build_package(config)
        def draft_revision():
            with core.access._tx(principal):
                return core.access._version_row(ws,draft,snapshot)['draft_revision']
        revision = invoke(draft_revision)
        invoke(core.credits.downloaded,ws,draft,revision,principal)
        return Response(data, media_type='application/zip', headers={**no_store(),
            'Content-Disposition': 'attachment; filename="' + filename + '"'})

    @router.post(BASE + '/meter')
    async def meter(ws: str, request: Request):
        principal = actor(ws, request, True)
        return response(policy=await run_in_threadpool(invoke, core.meter.configure,
            ws, await body(request), principal))

    @router.get('/customer/organizations/{ws}/build')
    def page(ws: str, request: Request):
        actor(ws, request, document=True)
        from .customer_authoring_view import page_for
        return page_for(ws)

    hub = BASE + '/templates'

    @router.get(hub)
    def template_catalog(ws: str, request: Request):
        return response(hub=invoke(core.templates.catalog, ws, actor(ws, request)))

    @router.get(hub + '/drafts')
    def template_drafts(ws: str, request: Request):
        return response(drafts=invoke(core.templates.listing, ws, actor(ws, request)))

    @router.post(hub + '/prepare')
    async def template_review(ws: str, request: Request):
        principal = actor(ws, request, True)
        return response(review=await run_in_threadpool(invoke, core.templates.prepare, ws, await body(request), principal))

    @router.post(hub + '/drafts')
    async def template_save(ws: str, request: Request):
        principal = actor(ws, request, True)
        return response(draft=await run_in_threadpool(invoke, core.templates.save, ws, await body(request), principal))

    @router.post(hub + '/drafts/{draft}/runs')
    async def template_run(ws: str, draft: str, request: Request):
        principal = actor(ws, request, True)
        return response(run=await run_in_threadpool(invoke, core.templates.execute, ws, draft, await body(request), principal))

    @router.get(hub + '/drafts/{draft}/runs')
    def template_history(ws: str, draft: str, request: Request):
        return response(runs=invoke(core.templates.runs, ws, draft, actor(ws, request)))

    @router.get(hub + '/drafts/{draft}/versions/{revision}/package')
    def template_package(ws: str, draft: str, revision: str, request: Request):
        data, filename = invoke(core.templates.package, ws, draft, revision, actor(ws, request))
        return Response(data, media_type='application/zip', headers={**no_store(),
            'Content-Disposition': 'attachment; filename="' + filename + '"'})

    typed = BASE + '/typed'

    @router.get(typed + '/options')
    def typed_options(ws: str, request: Request):
        principal=actor(ws,request)
        options = invoke(core.typed.options,ws,principal)
        hub = invoke(core.templates.catalog,ws,principal)
        for candidate in options['candidates']:
            candidate['fallback_template_ids'] = [p['id'] for p in hub['templates']
                if p.get('product') and p.get('fallback_available') and any(n.get('type') == 'agent' and n.get('resource_id') == candidate['resource_id'] for n in p['nodes'])]
            candidate['fallback_scope'] = 'verified_template_only'
        return response(options=options,factory=invoke(core.factory.options,ws,principal),hub=hub)

    @router.get(typed + '/flows')
    def typed_flows(ws: str, request: Request):
        return response(flows=invoke(core.typed.listing,ws,actor(ws,request)))

    @router.get(typed + '/flows/{flow}')
    def typed_detail(ws: str, flow: str, request: Request):
        return response(flow=invoke(core.typed.detail,ws,flow,actor(ws,request)))

    @router.post(typed + '/reviews/{kind}')
    async def typed_review(ws: str, kind: str, request: Request):
        methods={'plan':core.factory.prepare_plan,'intent':core.factory.prepare_intent,
                 'model':core.factory.prepare_model_proposal,'support':core.factory.prepare_support_patch}
        if kind not in methods:
            raise HTTPException(404,'The selected review is unavailable.')
        principal=actor(ws,request,True)
        value=await run_in_threadpool(invoke,methods[kind],ws,await body(request),principal)
        return response(review=value)

    @router.post(typed + '/commits')
    async def typed_commit(ws: str, request: Request):
        principal=actor(ws,request,True)
        return response(flow=await run_in_threadpool(invoke,core.factory.commit,ws,await body(request),principal))

    @router.post(typed + '/flows/{flow}/prepare')
    async def typed_prepare(ws: str, flow: str, request: Request):
        principal=actor(ws,request,True)
        return response(**await run_in_threadpool(invoke,core.typed.prepare,ws,flow,await body(request),principal))

    @router.post(typed + '/flows/{flow}/runs')
    async def typed_run(ws: str, flow: str, request: Request):
        principal=actor(ws,request,True)
        return response(**await run_in_threadpool(invoke,core.typed.execute,ws,flow,await body(request),principal))

    @router.get(typed + '/flows/{flow}/runs')
    def typed_history(ws: str, flow: str, request: Request):
        return response(runs=invoke(core.typed.runs,ws,flow,actor(ws,request)))

    @router.get(typed + '/flows/{flow}/runs/{run}')
    def typed_run_detail(ws: str, flow: str, run: str, request: Request):
        return response(run=invoke(core.typed.get,ws,flow,run,actor(ws,request)))

    @router.post(typed + '/flows/{flow}/disable')
    async def typed_disable(ws: str, flow: str, request: Request):
        principal=actor(ws,request,True)
        return response(flow=await run_in_threadpool(invoke,core.typed.disable,ws,flow,await body(request),principal))

    typed_scope=typed+'/flows/{flow}/versions/{version}'

    @router.post(typed_scope+'/releases')
    async def typed_release(ws: str, flow: str, version: str, request: Request):
        principal=actor(ws,request,True)
        return response(release=await run_in_threadpool(invoke,core.typed_releases.create,ws,flow,version,await body(request),principal))

    @router.get(typed_scope+'/releases')
    def typed_releases(ws: str, flow: str, version: str, request: Request):
        return response(releases=invoke(core.typed_releases.releases,ws,flow,version,actor(ws,request)))

    @router.post(typed_scope+'/releases/{release}/revoke')
    async def typed_release_revoke(ws: str, flow: str, version: str, release: str, request: Request):
        principal=actor(ws,request,True)
        return response(release=await run_in_threadpool(invoke,core.typed_releases.revoke,ws,flow,version,release,await body(request),principal))

    @router.get(typed_scope+'/releases/{release}/deployments')
    def typed_deployments(ws: str, flow: str, version: str, release: str, request: Request):
        return response(deployments=invoke(core.typed_releases.deployments,ws,flow,version,release,actor(ws,request)))

    @router.post(typed_scope+'/releases/{release}/deployments')
    async def typed_deploy(ws: str, flow: str, version: str, release: str, request: Request):
        principal=actor(ws,request,True)
        return response(deployment=await run_in_threadpool(invoke,core.typed_releases.deploy,ws,flow,version,release,await body(request),principal))

    @router.get(typed_scope+'/deployments/{app}/package')
    def typed_package(ws: str, flow: str, version: str, app: str, request: Request):
        principal=actor(ws,request)
        config=invoke(core.typed_releases.package_config,ws,flow,version,app,principal)
        data,filename=build_package(config)
        def flow_revision():
            with core.access._tx(principal) as (db,_):
                return core.typed._version(db,ws,flow,version)['revision']
        revision=invoke(flow_revision)
        invoke(core.credits.downloaded,ws,flow,revision,principal)
        return Response(data,media_type='application/zip',headers={**no_store(),
            'Content-Disposition':'attachment; filename="'+filename+'"'})

    @router.get(BASE+'/task-outcomes')
    def outcomes(ws: str, request: Request):
        return response(outcomes=invoke(core.outcomes.report,ws,actor(ws,request)))

    @router.post(BASE+'/support-guides')
    async def support_guides(ws: str, request: Request):
        principal=actor(ws,request,True)
        return response(guides=await run_in_threadpool(invoke,core.support.search,ws,await body(request),principal))

    @router.post(BASE+'/task-outcomes')
    async def outcome_record(ws: str, request: Request):
        principal=actor(ws,request,True)
        return response(outcome=await run_in_threadpool(invoke,core.outcomes.record,ws,await body(request),principal))

    @router.post(BASE+'/task-outcomes/withdrawals')
    async def outcome_withdraw(ws: str, request: Request):
        if not same_origin(request) or request.headers.get('authorization'):
            raise HTTPException(403,'Use your customer service session.')
        customer=customer_actor(request,core.identity,csrf=True)
        if not limit.allow(customer.customer_id):
            raise HTTPException(429,'Please wait before another workspace request.')
        principal=CustomerRuntimeActor(customer.customer_id,customer.session_ref,ws)
        return response(outcome=await run_in_threadpool(invoke,core.outcomes.withdraw,ws,await body(request),principal))

    @router.get('/customer/organizations/{ws}/flows')
    def typed_page(ws: str, request: Request):
        # A browser without a current session is sent to sign-in, not shown an API error body.
        try:
            actor(ws,request,document=True)
        except HTTPException as error:
            if error.status_code != 401:
                raise
            from fastapi.responses import RedirectResponse
            from .customer_navigation import sign_in_location
            return RedirectResponse(sign_in_location(request), status_code=303, headers={'Cache-Control': 'no-store'})
        from .customer_typed_authoring_view import page_for
        return page_for(ws)

    a2a=BASE+'/a2a'

    @router.get(a2a+'/options')
    def a2a_options(ws: str, request: Request):
        return response(options=invoke(core.remote_tasks.options,ws,actor(ws,request)))

    @router.get(a2a+'/tasks')
    def a2a_history(ws: str, request: Request):
        return response(tasks=invoke(core.remote_tasks.listing,ws,actor(ws,request)))

    @router.get(a2a+'/tasks/{task}')
    def a2a_status(ws: str, task: str, request: Request):
        return response(task=invoke(core.remote_tasks.status,ws,task,actor(ws,request)))

    @router.post(a2a+'/tasks')
    async def a2a_send(ws: str, request: Request):
        principal=actor(ws,request,True)
        return response(task=await run_in_threadpool(invoke,core.remote_tasks.send,ws,await body(request),principal))

    @router.post(a2a+'/tasks/{task}/commands')
    async def a2a_command(ws: str, task: str, request: Request):
        principal=actor(ws,request,True)
        return response(task=await run_in_threadpool(invoke,core.remote_tasks.command,ws,task,await body(request),principal))

    @router.post(a2a+'/tasks/{task}/messages')
    async def a2a_continue(ws: str, task: str, request: Request):
        principal=actor(ws,request,True)
        return response(task=await run_in_threadpool(invoke,core.remote_tasks.continue_session,ws,task,await body(request),principal))

    from .customer_credit_service import router_for as credit_routes
    router.include_router(credit_routes(core.identity,platform.access))
    return router
