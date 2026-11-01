"""Current named-session transport for scoped pre-run review and human scoring."""
import re
import sqlite3

from fastapi import APIRouter,Depends,HTTPException,Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .broker.server import RateLimiter
from .gateway import admin_auth
from .workspace_access import SessionActor,WorkspaceConflict,WorkspaceDenied,WorkspaceInvalid
from .workspace_service import WorkspaceRoute
from .workflow_product_semantics_service import bounded_tree
from .workflow_publication_service import no_store,read_object
from .workflow_quality_review import PROFILE,WorkflowQualityReview

BASE='/admin/api/workflow-workspaces/{workspace_id}/quality'


def router_for(access,execution,*,qualification_source=None,source_verifier=None):
    core=WorkflowQualityReview(access,execution,qualification_source=qualification_source,source_verifier=source_verifier)
    router=APIRouter(prefix=BASE,route_class=WorkspaceRoute);reads,writes=RateLimiter(240),RateLimiter(60)
    def session(request:Request):
        authorization=request.headers.get('authorization','')
        if request.headers.get('x-dashboard')!='1' or not re.fullmatch(r'Bearer [a-f0-9]{64}',authorization):
            raise HTTPException(401,'Sign in with an individual administrator session.')
        with access.store.tx() as db:user=admin_auth.get_session_user(db,authorization[7:])
        if not user:raise HTTPException(401,'The individual session is unavailable.')
        actor=SessionActor(user['user_id'],admin_auth.session_reference(authorization[7:]))
        if not(reads if request.method=='GET' else writes).allow(str(actor.user_id)):raise HTTPException(429,'Review request limit reached.')
        return actor
    def invoke(method,ws,actor,*args):
        try:return JSONResponse({'ok':True,'profile':PROFILE,'result':getattr(core,method)(ws,*args,actor)},headers=no_store())
        except WorkspaceDenied:raise HTTPException(404,'The private review object is unavailable.') from None
        except WorkspaceConflict:raise HTTPException(409,'Review state changed or proof is unavailable. Read current state.') from None
        except WorkspaceInvalid:raise HTTPException(400,'Provide the exact bounded review fields.') from None
        except sqlite3.DatabaseError:raise HTTPException(503,'Private review storage is unavailable.') from None
        except(TypeError,ValueError,KeyError,UnicodeError,RecursionError):raise HTTPException(400,'Review data could not be validated.') from None
    @router.get('/options')
    def options(workspace_id:str,actor=Depends(session)):return invoke('options',workspace_id,actor)
    @router.get('/assignments')
    def assignments(workspace_id:str,actor=Depends(session)):return invoke('assignments',workspace_id,actor)
    @router.get('/assignments/{assignment_id}')
    def status(workspace_id:str,assignment_id:str,actor=Depends(session)):return invoke('status',workspace_id,actor,assignment_id)
    async def body(request):
        try:return bounded_tree(await read_object(request,65536))
        except(TypeError,ValueError,UnicodeError,RecursionError,TimeoutError):raise HTTPException(400,'Provide one bounded review JSON object.') from None
    @router.post('/assignments')
    async def reserve(workspace_id:str,request:Request,actor=Depends(session)):
        return await run_in_threadpool(invoke,'reserve',workspace_id,actor,await body(request))
    @router.post('/assignments/{assignment_id}/{action}')
    async def action(workspace_id:str,assignment_id:str,action:str,request:Request,actor=Depends(session)):
        if action not in ('bind','inspect','review','adjudicate'):raise HTTPException(404,'Review action unavailable.')
        return await run_in_threadpool(invoke,action,workspace_id,actor,assignment_id,await body(request))
    return router
