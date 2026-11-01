"""Bounded transport for independently granted connected SDK 1.3 apps."""
import json
import re
import sqlite3

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .workflow_connection_deployment import PROFILE
from .workflow_publication_service import read_object, no_store
from .workflows import WorkflowError

APP = re.compile(r'capp_[a-f0-9]{32}')
RELEASE = re.compile(r'pub_[a-f0-9]{32}')
RUN = re.compile(r'wr_[a-f0-9]{32}')
ERROR = 'The connected app request could not be completed. Review its recorded status before retrying.'


async def read_request(request, limit=64000):
    body = await read_object(request, limit)
    # JSON exponent overflow also produces non-finite floats, separately from
    # the explicit NaN/Infinity tokens rejected by the streaming decoder.
    json.dumps(body, allow_nan=False)
    return body


class ConnectionDeploymentService:
    def __init__(self, runtime):
        from .workflow_apps import service_for
        self.runtime, self.core = runtime, runtime.connection_deployments
        self.quota = service_for(runtime.store, runtime)

    @staticmethod
    def identity(value, pattern):
        if not isinstance(value, str) or not pattern.fullmatch(value):
            raise ValueError('The connected deployment is unavailable.')
        return value

    def admin(self, method, release_id, actor, body=None, app_id=None):
        self.identity(release_id, RELEASE)
        if method in ('options', 'deployments'):
            return getattr(self.core, method)(release_id, actor)
        if method == 'revoke':
            self.identity(app_id, APP)
            if not isinstance(body, dict) or set(body) != {'revision'} or type(body['revision']) is not int:
                raise ValueError('Use the exact current deployment revision.')
            return self.core.revoke(release_id, app_id, body['revision'], actor)
        if method not in ('prepare_admin', 'issue'):
            raise ValueError('Choose an available connected deployment action.')
        return getattr(self.core, method)(release_id, body, actor)

    def authorize(self, app_id, publish_key, origin, *, read=False):
        self.identity(app_id, APP)
        return self.core.authorize(app_id, publish_key, origin, read=read)

    def prepare(self, app_id, body, publish_key, origin, ip):
        if not isinstance(body, dict) or body:
            raise ValueError('Review the fixed connected app settings.')
        app = self.authorize(app_id, publish_key, origin)
        self.quota.quota(app, ip, 'prepare')
        return self.core.prepare_run(app_id, origin)

    def execute(self, app_id, body, publish_key, origin, ip):
        with self.runtime.lock:
            app = self.authorize(app_id, publish_key, origin)
            accepted = self.core.accepted_run(app_id, body, origin)
            self.quota.quota(app, ip, 'poll' if accepted else 'start')
            return self.core.execute_run(app_id, body, origin)

    def read(self, app_id, run_id, publish_key, run_key, origin, ip, cancel=False):
        self.identity(run_id, RUN)
        app = self.authorize(app_id, publish_key, origin, read=True)
        self.quota.quota(app, ip, 'cancel' if cancel else 'poll')
        action = self.core.cancel_run if cancel else self.core.read_run
        return action(app_id, run_id, run_key, origin)


def public_router_for(front):
    router = APIRouter(prefix='/api/workflow-connection-apps-v13')
    service = ConnectionDeploymentService(front.workflows)

    def cors():
        return {**no_store(), 'Access-Control-Allow-Origin': '*', 'Access-Control-Expose-Headers': 'Retry-After'}

    def failure(status=400, limited=False, read=False):
        message = 'Connected app request limit reached.' if limited else 'Run unavailable.' if read else ERROR
        return JSONResponse({'error': message}, status_code=status,
                            headers={**cors(), **({'Retry-After': '60'} if limited else {})})

    @router.options('/{app_id}/prepare')
    @router.options('/{app_id}/runs')
    @router.options('/{app_id}/runs/{run_id}')
    @router.options('/{app_id}/runs/{run_id}/cancel')
    def preflight(app_id: str, request: Request, run_id: str = ''):
        try:
            # A browser preflight has no publish key. Verify the registered origin
            # and active signed grants without requiring provider readiness.
            service.identity(app_id, APP)
            service.core.metadata(app_id, request.headers.get('origin'))
            requested = {item.strip().lower() for item in request.headers.get('access-control-request-headers', '').split(',') if item.strip()}
            if (request.headers.get('access-control-request-method', '').upper() not in ('GET', 'POST')
                    or requested - {'content-type', 'x-publish-key', 'x-workflow-key'}):
                raise ValueError('Use the declared connected app transport.')
        except (ValueError, TypeError, KeyError, sqlite3.DatabaseError):
            return failure(403)
        except Exception:
            return failure(500)
        return Response(status_code=204, headers={**cors(), 'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type, X-Publish-Key, X-Workflow-Key', 'Access-Control-Max-Age': '600'})

    async def action(app_id, request, operation, run_id=None):
        origin, publish_key = request.headers.get('origin'), request.headers.get('x-publish-key')
        is_read = operation in ('read', 'cancel')
        try:
            # Reject missing or unregistered origins before reading request bodies
            # or creating usage records. Origin is a deployment control, not identity.
            await run_in_threadpool(service.authorize, app_id, publish_key, origin, read=is_read)
        except (ValueError, TypeError, KeyError, sqlite3.DatabaseError):
            return failure(404 if is_read else 403, read=is_read)
        except Exception:
            return failure(500, read=is_read)
        try:
            ip = front.security.resolve_ip(request)
            if operation in ('prepare', 'execute'):
                body = await read_request(request, 16000)
                method = service.prepare if operation == 'prepare' else service.execute
                result = await run_in_threadpool(method, app_id, body, publish_key, origin, ip)
            else:
                if operation == 'cancel':
                    body = await read_request(request, 1024)
                    if body: raise ValueError('Use one scoped cancellation request.')
                result = await run_in_threadpool(service.read, app_id, run_id, publish_key,
                    request.headers.get('x-workflow-key'), origin, ip, operation == 'cancel')
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, TimeoutError, sqlite3.DatabaseError) as exc:
            limited = isinstance(exc, WorkflowError) and 'rate limit' in str(exc)
            return failure(429 if limited else 404 if is_read else 400, limited, is_read)
        except Exception:
            return failure(500, read=is_read)
        return JSONResponse(result, status_code=202 if operation == 'execute' else 200, headers=cors())

    @router.post('/{app_id}/prepare')
    async def prepare(app_id: str, request: Request): return await action(app_id, request, 'prepare')

    @router.post('/{app_id}/runs')
    async def execute(app_id: str, request: Request): return await action(app_id, request, 'execute')

    @router.get('/{app_id}/runs/{run_id}')
    async def read(app_id: str, run_id: str, request: Request): return await action(app_id, request, 'read', run_id)

    @router.post('/{app_id}/runs/{run_id}/cancel')
    async def cancel(app_id: str, run_id: str, request: Request): return await action(app_id, request, 'cancel', run_id)

    return router
