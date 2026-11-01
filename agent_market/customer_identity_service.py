"""Same-origin customer OIDC/BFF routes and explicit staff-controlled links."""
import hmac
import re
import secrets
import sqlite3
import time
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.datastructures import QueryParams
from starlette.concurrency import run_in_threadpool

from .customer_identity import CustomerIdentity, PROFILE, GITHUB_AUTHORIZATION_ISSUER
from .customer_identity_view import sign_in_page, workspaces_page
from .broker.server import RateLimiter
from .gateway import admin_auth
from .workspace_access import SessionActor, WorkspaceAccess, WorkspaceDenied, WorkspaceConflict, WorkspaceInvalid
from .workspace_service import WorkspaceRoute
from .workflow_publication_service import no_store, read_object, same_origin
from .customer_navigation import destination, sign_in_location

COOKIE = '__Host-ac_customer_session'
FLOW_COOKIE = '__Host-ac_oidc_flow'


def customer_actor(request, core, csrf=False, *, document=False):
    # An OAuth redirect chain can retain cross-site Fetch Metadata on the
    # landing document. Only explicitly selected read-only HTML handlers may
    # accept top-level navigation; API reads and mutations remain same-origin.
    navigation = (document and not csrf and request.method == 'GET'
                  and request.headers.get('origin') is None
                  and request.headers.get('sec-fetch-mode') == 'navigate'
                  and request.headers.get('sec-fetch-dest') == 'document')
    if not navigation and not same_origin(request):
        raise HTTPException(403, 'Use the customer service origin.')
    token = request.cookies.get(COOKIE)
    try:
        actor = core.actor(token)
    except WorkspaceDenied:
        raise HTTPException(401, 'Sign in to continue.', headers={'WWW-Authenticate': 'Session realm="customer"'}) from None
    except sqlite3.DatabaseError:
        # A busy store is temporary: ask the browser to retry instead of reporting an internal error.
        raise HTTPException(503, 'Your workspace is briefly busy. Please try again.', headers={'Retry-After': '2'}) from None
    proof = request.headers.get('x-customer-csrf', '')
    if csrf and (type(token) is not str or not re.fullmatch(r'cst_[A-Za-z0-9_-]{43}', token)
                 or not re.fullmatch(r'[0-9a-f]{64}', proof)
                 or not hmac.compare_digest(proof, core.csrf(token))):
        raise HTTPException(403, 'Review the current customer session.')
    return actor


def customer_entry_guard(identity):
    """Authenticate the customer surface before endpoint field validation."""
    def guard(request: Request):
        path = request.url.path
        if path in ('/customer/sign-in', '/api/customer-auth/options', '/api/customer-auth/status',
                    '/api/customer-auth/begin', '/api/customer-auth/callback', '/api/customer-auth/github/callback'):
            return
        if re.fullmatch(r'/api/customer-provider-oauth/(?:clients/[0-9]+\.json|[0-9]+/callback)', path):
            return
        document = request.method == 'GET' and path.startswith('/customer/')
        if not document and not path.startswith('/api/customer-'):
            return
        try:
            customer_actor(request, identity, csrf=request.method not in ('GET', 'HEAD'), document=document)
        except HTTPException as error:
            if document and error.status_code == 401:
                raise HTTPException(303, 'Sign in to continue.', headers={'Location': sign_in_location(request), **no_store()}) from None
            raise
    return guard


def router_for(store, key, config=None, http=None, *, identity=None, github_config=None, public=True, admin=True):
    core = identity if identity is not None else CustomerIdentity(store, key, config, http, github_config=github_config)
    access = WorkspaceAccess(store, key)
    router = APIRouter(route_class=WorkspaceRoute)
    signins, callbacks, reads, mutations = RateLimiter(20), RateLimiter(30), RateLimiter(240), RateLimiter(60)

    def limit(request, limiter):
        if not limiter.allow(request.client.host if request.client else 'unknown'):
            raise HTTPException(429, 'Customer request limit reached.', headers={'Retry-After': '60'})

    async def body(request):
        if not same_origin(request):
            raise HTTPException(403, 'Use the customer service origin.')
        try:
            value = await read_object(request, 16384)
            from .workspace_access import _tree
            _tree(value)
            return value
        except Exception:
            raise HTTPException(400, 'Provide one exact bounded customer request.') from None

    def invoke(method, *args):
        try:
            return getattr(core, method)(*args)
        except WorkspaceDenied:
            raise HTTPException(401, 'Customer identity or requested scope is unavailable.') from None
        except WorkspaceConflict:
            raise HTTPException(409, 'Customer state changed. Review a fresh request.') from None
        except (WorkspaceInvalid, ValueError, TypeError, KeyError):
            raise HTTPException(400, 'Provide the exact customer request fields.') from None

    def response(**value):
        return JSONResponse({'ok': True, 'profile': PROFILE, **value}, headers={**no_store(), 'X-Robots-Tag': 'noindex,noarchive'})

    @router.get('/api/customer-auth/options')
    def options():
        return response(**core.options())

    @router.get('/customer/sign-in')
    def sign_in(request: Request):
        return sign_in_page(destination(request.query_params.get('next')))

    @router.get('/customer/workspaces')
    def customer_workspaces(request: Request):
        try:
            customer_actor(request, core, document=True)
        except HTTPException as error:
            if error.status_code != 401:
                raise
            return RedirectResponse(sign_in_location(request), status_code=303, headers=no_store())
        return workspaces_page()

    @router.post('/api/customer-auth/begin')
    async def begin(request: Request):
        limit(request, signins)
        value = await body(request)
        if set(value) - {'provider', 'next'} or value.get('provider', 'google') not in ('google', 'github'):
            raise HTTPException(400, 'Choose Google or GitHub sign-in.')
        browser = secrets.token_hex(32)
        value = await run_in_threadpool(invoke, 'begin', browser, value.get('provider', 'google'), destination(value.get('next')))
        result = response(**value)
        result.set_cookie(FLOW_COOKIE, browser, max_age=300, secure=True, httponly=True, samesite='lax', path='/')
        return result

    async def callback_action(request, provider):
        # Uvicorn formats access paths from this ASGI scope when sending the
        # response. Remove one-use codes/state even for a refused callback.
        raw_query = request.scope.pop('_customer_auth_callback_query', request.scope.get('query_string', b''))
        request.scope['query_string'] = b''
        for name in ('_url', '_query_params'):
            if hasattr(request, name):
                delattr(request, name)
        limit(request, callbacks)
        # OIDC top-level GET callback is deliberately allowed across sites; the
        # one-use state and host-only browser cookie bind the initiating browser.
        if len(raw_query) > 8192:
            raise HTTPException(400, 'The sign-in response could not be verified.')
        pairs = list(QueryParams(raw_query).multi_items())
        query = dict(pairs)
        # Keep the longstanding account namespace separate from GitHub's RFC
        # 9207 authorization-server issuer. Neither is inferred from the input.
        expected_issuer = (core.config.issuer if provider == 'google' and core.config is not None
                           else GITHUB_AUTHORIZATION_ISSUER if provider == 'github' and core.github_config is not None
                           else None)
        if (len(query) != len(pairs)
                or 'state' not in query or ('code' in query) == ('error' in query)
                or set(query) - {'state', 'code', 'iss', 'scope', 'authuser', 'prompt', 'error', 'error_description'}
                or any(len(value) > 2048 or any(ord(char) < 32 for char in value) for value in query.values())
                or 'iss' in query and query['iss'] != expected_issuer):
            raise HTTPException(400, 'The sign-in response could not be verified.')
        if 'error' in query:
            value = await run_in_threadpool(invoke, 'cancel', query['state'], request.cookies.get(FLOW_COOKIE), provider)
            target = destination(value.pop('return_to', None))
            result = response(**value)
            result.delete_cookie(FLOW_COOKIE, secure=True, httponly=True, samesite='lax', path='/')
            if 'text/html' in request.headers.get('accept', ''):
                result.status_code = 303
                result.headers['location'] = '/customer/sign-in?' + urlencode({'result': 'cancelled', **({'next': target} if target != '/customer/workspaces' else {})})
            return result
        value = await run_in_threadpool(invoke, 'complete', query['state'], query['code'], request.cookies.get(FLOW_COOKIE), provider)
        token = value.pop('session_token')
        target = destination(value.pop('return_to', None))
        result = response(authenticated=True, **value)
        result.set_cookie(COOKIE, token, max_age=max(0, int(value['absolute_expires'] - time.time())),
                          secure=True, httponly=True, samesite='lax', path='/')
        result.delete_cookie(FLOW_COOKIE, secure=True, httponly=True, samesite='lax', path='/')
        if 'text/html' in request.headers.get('accept', ''):
            result.status_code = 303
            result.headers['location'] = target
        return result

    async def browser_callback(request, provider):
        try:
            return await callback_action(request, provider)
        except HTTPException:
            if 'text/html' not in request.headers.get('accept', ''):
                raise
            result = response(authenticated=False)
            result.status_code = 303
            result.headers['location'] = '/customer/sign-in?result=failed'
            result.delete_cookie(FLOW_COOKIE, secure=True, httponly=True, samesite='lax', path='/')
            return result

    @router.get('/api/customer-auth/callback')
    async def google_callback(request: Request):
        return await browser_callback(request, 'google')

    @router.get('/api/customer-auth/github/callback')
    async def github_callback(request: Request):
        return await browser_callback(request, 'github')

    @router.get('/api/customer-auth/session')
    def session(request: Request):
        limit(request, reads)
        # A read-only check: one short retry absorbs a transient storage error, and a
        # second failure is "try again", never a reason to send a signed-in customer to sign-in.
        for attempt in (1, 2):
            try:
                customer_actor(request, core)
                return response(session=invoke('session', request.cookies.get(COOKIE)))
            except sqlite3.DatabaseError:
                if attempt == 2:
                    raise HTTPException(503, 'The session check is temporarily unavailable. Try again.',
                                        headers={**no_store(), 'Retry-After': '2'}) from None
                time.sleep(.2)

    @router.get('/api/customer-auth/status')
    def status(request: Request):
        limit(request, reads)
        try:
            customer_actor(request, core)
        except HTTPException as error:
            if error.status_code != 401:
                raise
            return response(authenticated=False)
        return response(authenticated=True)

    @router.post('/api/customer-auth/logout')
    async def logout(request: Request):
        limit(request, mutations)
        customer_actor(request, core, csrf=True)
        if await body(request) != {}:
            raise HTTPException(400, 'Use an empty sign-out request.')
        value = await run_in_threadpool(invoke, 'logout', request.cookies.get(COOKIE))
        result = response(**value)
        result.delete_cookie(COOKIE, secure=True, httponly=True, samesite='lax', path='/')
        return result

    @router.post('/api/customer-auth/workspaces/{workspace_id}/token')
    async def token(workspace_id: str, request: Request):
        limit(request, mutations)
        customer_actor(request, core, csrf=True)
        value = await body(request)
        if set(value) != {'purpose'} or value['purpose'] not in ('read', 'execute'):
            raise HTTPException(400, 'Choose one customer workspace purpose.')
        return response(**await run_in_threadpool(invoke, 'issue_token', request.cookies.get(COOKIE), workspace_id, value['purpose']))

    def staff(request):
        if not same_origin(request) or request.headers.get('x-dashboard') != '1':
            raise HTTPException(403, 'Use the authenticated dashboard origin.')
        header = request.headers.get('authorization', '')
        if not re.fullmatch('Bearer [a-f0-9]{64}', header):
            raise HTTPException(401, 'An individual administrator session is required.')
        with store.tx() as db:
            user = admin_auth.get_session_user(db, header[7:])
        if not user:
            raise HTTPException(401, 'An individual administrator session is required.')
        return SessionActor(user['user_id'], admin_auth.session_reference(header[7:]))

    @router.get('/admin/api/workflow-workspaces/{workspace_id}/customers')
    def links(workspace_id: str, request: Request):
        return response(customers=invoke('links', access, workspace_id, staff(request)))

    @router.post('/admin/api/workflow-workspaces/{workspace_id}/customers')
    async def set_link(workspace_id: str, request: Request):
        limit(request, mutations)
        actor = staff(request)
        return response(customer=await run_in_threadpool(invoke, 'set_link', access, workspace_id, await body(request), actor))

    router.customer_identity = core
    router.routes[:] = [route for route in router.routes
                        if admin and route.path.startswith('/admin/') or public and not route.path.startswith('/admin/')]
    if public:
        from .customer_organization_service import router_for as organizations
        router.include_router(organizations(core, access))
        # Wherever the customer API is served, its opening reads can share one round trip (11-01).
        from .customer_batch import router_for as batch
        router.include_router(batch())
    return router
