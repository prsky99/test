"""Private customer recovery transport; never a staff impersonation endpoint."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .broker.server import RateLimiter
from .workflow_publication_service import read_object, same_origin
from .customer_identity_service import customer_actor, no_store
from .customer_recovery import PROFILE
from .workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid
from .workspace_service import WorkspaceRoute


def router_for(core):
    router = APIRouter(route_class=WorkspaceRoute)
    if core is None or not core.authorities:
        return router
    writes, reads = RateLimiter(30), RateLimiter(120)
    base = '/api/customer-auth/organizations/{workspace_id}/recovery'

    def actor(request, mutation=False):
        limiter = writes if mutation else reads
        if not limiter.allow(request.client.host if request.client else 'unknown'):
            raise HTTPException(429, 'Recovery request limit reached.', headers={'Retry-After': '60'})
        return customer_actor(request, core.identity, csrf=mutation)

    async def body(request):
        if not same_origin(request):
            raise HTTPException(403, 'Use the customer service origin.')
        try:
            return await read_object(request, 8192)
        except Exception:
            raise HTTPException(400, 'Provide one bounded recovery request.') from None

    def invoke(method, *args):
        try:
            result = getattr(core, method)(*args)
        except WorkspaceDenied:
            raise HTTPException(404, 'The recovery request is unavailable.') from None
        except WorkspaceConflict:
            raise HTTPException(409, 'Recovery state changed. Review a fresh request.') from None
        except (WorkspaceInvalid, KeyError, ValueError, TypeError):
            raise HTTPException(400, 'Provide the exact recovery request fields.') from None
        return JSONResponse({'ok': True, 'profile': PROFILE, 'result': result},
                            headers={**no_store(), 'X-Robots-Tag': 'noindex,noarchive'})

    @router.get('/customer/organizations/{workspace_id}/recovery')
    def page(workspace_id: str, request: Request):
        actor(request)
        from .workspace_access import _identity
        from .customer_recovery_view import page as render
        try:
            _identity(workspace_id, 'ws')
        except WorkspaceInvalid:
            raise HTTPException(404, 'The organization is unavailable.') from None
        return render(workspace_id)

    @router.get(base)
    def review(workspace_id: str, request: Request):
        return invoke('review', workspace_id, actor(request))

    @router.post(base + '/enrollment/withdraw')
    async def revoke(workspace_id: str, request: Request):
        person = actor(request, True)
        return await run_in_threadpool(invoke, 'revoke', workspace_id, await body(request), person)

    @router.post(base + '/enrollment')
    async def enroll(workspace_id: str, request: Request):
        person = actor(request, True)
        return await run_in_threadpool(invoke, 'enroll', workspace_id, await body(request), person)

    @router.post(base + '/challenges')
    async def challenge(workspace_id: str, request: Request):
        person = actor(request, True)
        return await run_in_threadpool(invoke, 'challenge', workspace_id, await body(request), person)

    @router.post(base + '/requests/{request_id}/proofs')
    async def submit(workspace_id: str, request_id: str, request: Request):
        person = actor(request, True)
        return await run_in_threadpool(invoke, 'submit', workspace_id, request_id, await body(request), person)

    @router.get(base + '/requests/{request_id}')
    def status(workspace_id: str, request_id: str, request: Request):
        return invoke('status', workspace_id, request_id, actor(request))

    for action in ('contest', 'withdraw', 'finalize'):
        def endpoint(name):
            async def resolve(workspace_id: str, request_id: str, request: Request):
                person = actor(request, True)
                if await body(request) != {}:
                    raise HTTPException(400, 'Provide an empty confirmation request.')
                return await run_in_threadpool(invoke, name, workspace_id, request_id, person)
            return resolve
        router.add_api_route(base + '/requests/{request_id}/' + action,
                             endpoint(action), methods=['POST'], name='customer_recovery_' + action)
    return router
