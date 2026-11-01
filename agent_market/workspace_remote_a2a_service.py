"""Private named-session transport for one selected A2A task profile."""
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .broker.server import RateLimiter
from .gateway import admin_auth
from .workspace_access import SessionActor, WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid
from .workspace_service import WorkspaceRoute
from .workflow_publication_service import read_object, no_store
from .workspace_remote_a2a import NOTICE, PROFILE


def router_for(core):
    router = APIRouter(prefix='/admin/api/workflow-workspaces/{workspace_id}/remote-a2a', route_class=WorkspaceRoute)
    limit = RateLimiter(60)
    def actor(request: Request):
        value = request.headers.get('authorization','')
        if request.headers.get('x-dashboard') != '1' or not re.fullmatch('Bearer [a-f0-9]{64}',value):
            raise HTTPException(401,'Use an individual administrator session.')
        with core.store.tx() as db:user=admin_auth.get_session_user(db,value[7:])
        if not user:
            raise HTTPException(401,'The administrator session is unavailable.')
        if not limit.allow(str(user['user_id'])):
            raise HTTPException(429,'Please wait before another task request.')
        return SessionActor(user['user_id'],admin_auth.session_reference(value[7:]))
    def invoke(method,*args):
        try:return getattr(core,method)(*args)
        except WorkspaceDenied:raise HTTPException(404,'The task or current permission is unavailable.') from None
        except WorkspaceConflict:raise HTTPException(409,'Inspect the retained task before another command.') from None
        except (WorkspaceInvalid,ValueError,TypeError,KeyError):raise HTTPException(400,'Review the supported task fields.') from None
    async def body(request):
        try:return await read_object(request,8192)
        except (ValueError,TypeError,UnicodeError,TimeoutError):raise HTTPException(400,'A bounded JSON task request is required.') from None
    def result(task):return JSONResponse({'ok':True,'task':task},headers=no_store())
    @router.get('/options')
    def options(workspace_id:str,request:Request,principal=Depends(actor)):
        try:
            with core.access._tx(principal) as (db,_):core.scope(workspace_id,principal)
        except WorkspaceDenied:
            raise HTTPException(404,'The task workspace is unavailable.') from None
        except WorkspaceConflict:
            raise HTTPException(409,'The task workspace changed.') from None
        return JSONResponse({'profile':PROFILE,'notice':NOTICE,'bindings':[
            {'resource_id':b.resource_id,'version_id':b.version_id,'streaming':b.client.streaming} for b in core.bindings.values()],
            'encryption_configured':core.cipher.configured,'automatic_retry':False,
            'streaming':any(b.client.streaming for b in core.bindings.values())},headers=no_store())
    @router.post('/tasks')
    async def send(workspace_id:str,request:Request,principal=Depends(actor)):
        return result(await run_in_threadpool(invoke,'send',workspace_id,await body(request),principal))
    @router.get('/tasks')
    def listing(workspace_id:str,request:Request,principal=Depends(actor)):
        return JSONResponse({'ok':True,'tasks':invoke('listing',workspace_id,principal)},headers=no_store())
    @router.get('/tasks/{task_id}')
    def status(workspace_id:str,task_id:str,request:Request,principal=Depends(actor)):
        return result(invoke('status',workspace_id,task_id,principal))
    @router.post('/tasks/{task_id}')
    async def command(workspace_id:str,task_id:str,request:Request,principal=Depends(actor)):
        return result(await run_in_threadpool(invoke,'command',workspace_id,task_id,await body(request),principal))
    @router.post('/tasks/{task_id}/messages')
    async def continuation(workspace_id:str,task_id:str,request:Request,principal=Depends(actor)):
        return result(await run_in_threadpool(invoke,'continue_session',workspace_id,task_id,await body(request),principal))
    return router
