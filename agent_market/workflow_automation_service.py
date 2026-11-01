"""Private bounded HTTP transport for explicit published-connection automation."""
import json
import re
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .gateway.admin_security import AdminRoute
from .workflow_connection_automation import PROFILE
from .workflow_publication_service import read_object, same_origin, no_store

RELEASE = re.compile(r'pub_[a-f0-9]{32}')
GRANT = re.compile(r'aut_[a-f0-9]{32}')
ERROR = 'The automation request could not be verified. Inspect its read-only history before repeating an event.'


async def read_request(request):
    body = await read_object(request, 64000)
    # Exponent overflow is non-finite too, even without NaN/Infinity tokens.
    json.dumps(body, allow_nan=False)
    return body


class AutomationService:
    def __init__(self, runtime):
        self.core = runtime.automation

    @staticmethod
    def identity(value, pattern):
        if not isinstance(value, str) or not pattern.fullmatch(value):
            raise ValueError('Choose a retained publication and automation grant.')

    def admin(self, method, release_id, actor, body=None, grant_id=None):
        self.identity(release_id, RELEASE)
        if method in ('options', 'history'):
            return getattr(self.core, method)(release_id, actor)
        if method in ('revoke', 'trigger'):
            self.identity(grant_id, GRANT)
            if method == 'revoke':
                if not isinstance(body, dict) or set(body) != {'revision'} or type(body['revision']) is not int:
                    raise ValueError('Use the current exact automation revision.')
                return self.core.revoke(release_id, grant_id, body['revision'], actor)
            return self.core.trigger(release_id, grant_id, body, actor)
        if method not in ('prepare', 'issue'):
            raise ValueError('Choose a supported automation action.')
        return getattr(self.core, method)(release_id, body, actor)


class AutomationRoute(AdminRoute):
    """Keep authority, CSRF and bounded-body refusals out of caches too."""
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def secured(request):
            try:
                return await handler(request)
            except HTTPException as exc:
                exc.headers = {**(exc.headers or {}), **no_store()}
                raise
        return secured


def router_for(runtime, require_sadmin):
    service = AutomationService(runtime)
    router = APIRouter(prefix='/admin/api/workflow-publications/releases/{release_id}/automation',
                       route_class=AutomationRoute, dependencies=[Depends(require_sadmin)])

    def result(method, release_id, actor, body=None, grant_id=None):
        try:
            return service.admin(method, release_id, actor, body, grant_id)
        except (ValueError, TypeError, KeyError, sqlite3.DatabaseError):
            raise HTTPException(409, ERROR, headers=no_store()) from None
        except Exception:
            raise HTTPException(500, 'Automation is temporarily unavailable. Inspect its read-only history before repeating an event.',
                                headers=no_store()) from None

    async def action(release_id, request, method, grant_id=None):
        if not same_origin(request):
            raise HTTPException(403, 'Use this administrator action from its original service page.', headers=no_store())
        try:
            body = await read_request(request)
        except (ValueError, TypeError, UnicodeError, RecursionError, TimeoutError):
            raise HTTPException(400, 'Provide one bounded automation request.', headers=no_store()) from None
        value = await run_in_threadpool(result, method, release_id, request.state.admin_user['user_id'], body, grant_id)
        return JSONResponse(value, status_code=202 if method == 'trigger' else 200, headers=no_store())

    @router.get('/options')
    def options(release_id: str, request: Request):
        return JSONResponse(result('options', release_id, request.state.admin_user['user_id']), headers=no_store())

    @router.get('/history')
    def history(release_id: str, request: Request):
        return JSONResponse(result('history', release_id, request.state.admin_user['user_id']), headers=no_store())

    @router.post('/prepare')
    async def prepare(release_id: str, request: Request):
        return await action(release_id, request, 'prepare')

    @router.post('/issue')
    async def issue(release_id: str, request: Request):
        return await action(release_id, request, 'issue')

    @router.post('/grants/{grant_id}/revoke')
    async def revoke(release_id: str, grant_id: str, request: Request):
        return await action(release_id, request, 'revoke', grant_id)

    @router.post('/grants/{grant_id}/trigger')
    async def trigger(release_id: str, grant_id: str, request: Request):
        return await action(release_id, request, 'trigger', grant_id)

    return router
