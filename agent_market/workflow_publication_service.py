"""Transport orchestration for separately authorized public title connections.

Signed definitions, execution purpose and release proof belong to Publication.
Only safe release projections, reviewed input rules and scoped run capabilities
cross the public routes here. Existing workflow and SDK routes stay separate.
"""
import asyncio
import json
from pathlib import Path
import re
import secrets
import sqlite3

from fastapi import APIRouter,Request
from fastapi.responses import HTMLResponse,JSONResponse,Response
from starlette.concurrency import run_in_threadpool

from .workflow_publication import PROFILE
from .workflows import WorkflowError

RELEASE=re.compile(r'pub_[a-f0-9]{32}')
RUN=re.compile(r'wr_[a-f0-9]{32}')
ASSET=Path(__file__).parent/'gateway'/'webapp'/'public-connection.js'
ERROR='The public connection request could not be completed. Review its recorded status before retrying.'


def no_store():
    return {'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer'}


def exact_pairs(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Duplicate request fields are unavailable.')
        result[key]=value
    return result


async def read_object(request,limit=64000):
    raw=bytearray()
    async with asyncio.timeout(10):
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>limit:raise ValueError('Request limit reached.')
    body=json.loads(raw,object_pairs_hook=exact_pairs,parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    if not isinstance(body,dict):raise ValueError('Use one request object.')
    return body


def same_origin(request):
    from .workflow_apps import normalize_origins
    if request.headers.get('sec-fetch-site')=='cross-site':return False
    origin=request.headers.get('origin')
    if origin is None:return True
    try:
        return normalize_origins([origin])[0]==normalize_origins([str(request.base_url).rstrip('/')])[0]
    except (ValueError,TypeError):return False


class PublicationService:
    def __init__(self,runtime):
        from .workflow_apps import service_for
        self.runtime,self.store,self.core=runtime,runtime.store,runtime.publication
        self.quota=service_for(self.store,runtime)

    def admin(self,method,actor,body=None,release_id=None):
        if method in ('options','test_history','releases'):
            return getattr(self.core,method)(actor)
        if method=='inspect_test':
            if not isinstance(body,dict) or set(body)!={'run_id'} or not isinstance(body['run_id'],str) or not RUN.fullmatch(body['run_id']):raise ValueError('Choose one retained public connection test.')
            return self.core.inspect_test(body['run_id'],actor)
        if method=='revoke':
            if (not isinstance(release_id,str) or not RELEASE.fullmatch(release_id) or not isinstance(body,dict)
                    or set(body)!={'revision'} or type(body['revision']) is not int):raise ValueError('Use one exact release revision.')
            return self.core.revoke(release_id,body['revision'],actor)
        if method not in ('candidate','test','publication_candidate','publish'):raise ValueError('Unsupported public connection action.')
        return getattr(self.core,method)(body,actor)

    @staticmethod
    def release_id(identity):
        if not isinstance(identity,str) or not RELEASE.fullmatch(identity):raise ValueError('Release unavailable.')
        return identity

    @staticmethod
    def run_id(identity):
        if not isinstance(identity,str) or not RUN.fullmatch(identity):raise ValueError('Run unavailable.')
        return identity

    def prepare(self,identity,body,ip):
        self.release_id(identity)
        if not isinstance(body,dict) or body:raise ValueError('Review the fixed connection settings.')
        self.core.public_projection(identity)
        self.limit(identity,ip,'prepare')
        return self.core.prepare_run(identity)

    def limit(self,identity,ip,operation):
        # This reuses bounded existing counters without creating an SDK app.
        self.quota.quota({'id':'release:'+identity,'minute_limit':10,'day_limit':500},ip,operation)

    def execute(self,identity,body,ip):
        self.release_id(identity)
        with self.runtime.lock:
            accepted=self.core.accepted_run(identity,body)
            self.limit(identity,ip,'poll' if accepted else 'start')
            return self.core.execute_run(identity,body)

    def read(self,identity,run_id,key,ip,cancel=False):
        self.release_id(identity);self.run_id(run_id)
        self.core.metadata(identity)
        self.limit(identity,ip,'cancel' if cancel else 'poll')
        action=self.core.cancel_run if cancel else self.core.read_run
        return action(identity,run_id,key)


def public_router_for(front):
    router=APIRouter();service=PublicationService(front.workflows)
    def failure(status=400,message=ERROR,limited=False):
        return JSONResponse({'error':message},status_code=status,headers={**no_store(),**({'Retry-After':'60'} if limited else {})})

    @router.get('/api/workflow-connections')
    def public_connections(request:Request):
        if not front.security.allow_read('public-connections:'+front.security.resolve_ip(request),base_limit=120):return failure(429,'Connection browsing is temporarily limited.',True)
        try:return JSONResponse(service.core.public_list(),headers=no_store())
        except (ValueError,TypeError,KeyError,sqlite3.DatabaseError):return failure(404,'Public connections are unavailable.')
        except Exception:return failure(500,'Public connections are temporarily unavailable.')

    @router.get('/api/workflow-connections/{release_id}')
    def public_connection(release_id:str,request:Request):
        if not front.security.allow_read('public-connection-detail:'+front.security.resolve_ip(request),base_limit=120):return failure(429,'Connection browsing is temporarily limited.',True)
        try:
            service.release_id(release_id)
            projection=service.core.public_projection(release_id)
            try:service.core.current(release_id);available=True
            except (ValueError,TypeError,KeyError,IndexError,sqlite3.DatabaseError):available=False
            return JSONResponse({'ok':True,'profile':PROFILE,'release':{**projection,'available':available}},headers=no_store())
        except (ValueError,TypeError,KeyError,sqlite3.DatabaseError):return failure(404,'Public connection unavailable.')
        except Exception:return failure(500,'Public connection is temporarily unavailable.')

    @router.options('/api/workflow-connections/{release_id}/prepare')
    @router.options('/api/workflow-connections/{release_id}/runs')
    @router.options('/api/workflow-connections/{release_id}/runs/{run_id}')
    @router.options('/api/workflow-connections/{release_id}/runs/{run_id}/cancel')
    def public_preflight(release_id:str,request:Request,run_id:str=''):
        if not same_origin(request):return failure(403,'Use this connection from its original service page.')
        return Response(status_code=204,headers={**no_store(),'Access-Control-Allow-Methods':'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers':'Content-Type, X-Workflow-Key'})

    async def action(release_id,request,operation,run_id=None):
        if not same_origin(request):return failure(403,'Use this connection from its original service page.')
        ip=front.security.resolve_ip(request)
        try:
            if operation in ('prepare','execute'):
                body=await read_object(request,16000)
                method=service.prepare if operation=='prepare' else service.execute
                result=await run_in_threadpool(method,release_id,body,ip)
            else:
                result=await run_in_threadpool(service.read,release_id,run_id,request.headers.get('x-workflow-key'),ip,operation=='cancel')
        except (ValueError,TypeError,KeyError,UnicodeError,RecursionError,TimeoutError,sqlite3.DatabaseError) as exc:
            limited=isinstance(exc,WorkflowError) and 'rate limit' in str(exc)
            return failure(429 if limited else 404 if operation in ('read','cancel') else 400,
                'Connection request limit reached.' if limited else 'Run unavailable.' if operation in ('read','cancel') else ERROR,limited)
        except Exception:return failure(500,'The public connection is temporarily unavailable. Review its recorded status before retrying.')
        return JSONResponse(result,status_code=202 if operation=='execute' else 200,headers=no_store())

    @router.post('/api/workflow-connections/{release_id}/prepare')
    async def prepare(release_id:str,request:Request):return await action(release_id,request,'prepare')
    @router.post('/api/workflow-connections/{release_id}/runs')
    async def execute(release_id:str,request:Request):return await action(release_id,request,'execute')
    @router.get('/api/workflow-connections/{release_id}/runs/{run_id}')
    async def read(release_id:str,run_id:str,request:Request):return await action(release_id,request,'read',run_id)
    @router.post('/api/workflow-connections/{release_id}/runs/{run_id}/cancel')
    async def cancel(release_id:str,run_id:str,request:Request):return await action(release_id,request,'cancel',run_id)

    @router.get('/assets/public-connection.js')
    def public_script():
        try:return Response(ASSET.read_bytes(),media_type='application/javascript',headers=no_store())
        except OSError:return failure(404,'The connection page is unavailable.')

    @router.get('/connections/{release_id}')
    def page(release_id:str):
        try:
            from .public_workflow_connection import build_public_connection_page
            service.release_id(release_id);service.core.public_projection(release_id)
            nonce=secrets.token_urlsafe(24);content=build_public_connection_page(release_id,nonce=nonce)
        except (ValueError,TypeError,KeyError,sqlite3.DatabaseError):return failure(404,'Public connection unavailable.')
        except Exception:return failure(500,'The connection page is temporarily unavailable.')
        csp=(f"default-src 'none'; script-src 'nonce-{nonce}'; script-src-attr 'none'; style-src 'nonce-{nonce}'; "
             "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        return HTMLResponse(content,headers={**no_store(),'Content-Security-Policy':csp,'X-Frame-Options':'DENY'})
    return router
