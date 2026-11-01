"""Individual staff-session transport for private typed product compositions."""
import re

from fastapi import APIRouter,Depends,HTTPException,Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .broker.server import RateLimiter
from .gateway import admin_auth
from .workflow_product_semantics_service import bounded_tree
from .workflow_publication_service import no_store,read_object
from .workspace_access import SessionActor,WorkspaceDenied,WorkspaceConflict,WorkspaceInvalid
from .workspace_service import BASE,WorkspaceRoute
from .workflow_product_composer import PROFILE


def router_for(composer):
    router=APIRouter(route_class=WorkspaceRoute);limit=RateLimiter(60)
    def actor(request:Request):
        value=request.headers.get('authorization','')
        if request.headers.get('x-dashboard')!='1' or not re.fullmatch('Bearer [a-f0-9]{64}',value):raise HTTPException(401,'Use an individual administrator session.')
        with composer.store.tx() as db:user=admin_auth.get_session_user(db,value[7:])
        if not user:raise HTTPException(401,'The current individual session is unavailable.')
        if not limit.allow(str(user['user_id'])):raise HTTPException(429,'Private product request limit reached.')
        return SessionActor(user['user_id'],admin_auth.session_reference(value[7:]))
    async def body(request):
        try:return bounded_tree(await read_object(request,65536))
        except (ValueError,TypeError,UnicodeError,RecursionError,TimeoutError):raise HTTPException(400,'Provide exact bounded private product fields.') from None
    def invoke(method,*args):
        try:return method(*args)
        except WorkspaceDenied:raise HTTPException(404,'The current private product object or verified agent is unavailable.') from None
        except WorkspaceConflict:raise HTTPException(409,'The product state changed or outcome is uncertain. Inspect private history.') from None
        except (WorkspaceInvalid,ValueError,TypeError,KeyError):raise HTTPException(400,'The private product request could not be validated.') from None
    def response(value):return JSONResponse({'ok':True,'profile':PROFILE,**value},headers=no_store())
    path=BASE+'/{ws}/product-composer'
    @router.get(path+'/options')
    def options(ws:str,who=Depends(actor)):return response(invoke(composer.options,ws,who))
    @router.post(path+'/prepare')
    async def prepare(ws:str,request:Request,who=Depends(actor)):return response(await run_in_threadpool(invoke,composer.prepare,ws,await body(request),who))
    @router.post(path+'/save')
    async def save(ws:str,request:Request,who=Depends(actor)):return response(await run_in_threadpool(invoke,composer.save,ws,await body(request),who))
    nested=BASE+'/{ws}/drafts/{draft}/snapshots/{snapshot}/product-test'
    @router.post(nested+'/prepare')
    async def test_prepare(ws:str,draft:str,snapshot:str,request:Request,who=Depends(actor)):
        if await body(request)!={}:raise HTTPException(400,'Saved product inputs cannot be replaced at execution.')
        return response(await run_in_threadpool(invoke,composer.prepare_test,ws,draft,snapshot,who))
    @router.post(nested+'/runs')
    async def test_run(ws:str,draft:str,snapshot:str,request:Request,who=Depends(actor)):return response(await run_in_threadpool(invoke,composer.test,ws,draft,snapshot,await body(request),who))
    @router.get(nested+'/runs/{run}')
    def proof(ws:str,draft:str,snapshot:str,run:str,who=Depends(actor)):return response({'contract_proof':invoke(composer.result,ws,draft,snapshot,run,who)})
    return router
