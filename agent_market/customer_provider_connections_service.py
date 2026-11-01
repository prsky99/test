"""Customer session transport for provider connection management."""
import re
from urllib.parse import urlsplit
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import QueryParams
from .broker.server import RateLimiter
from .customer_identity_service import customer_actor, COOKIE
from .workspace_service import WorkspaceRoute
from .workspace_access import WorkspaceDenied, WorkspaceConflict, WorkspaceInvalid
from .workspace_provider_connections import ProviderConnections, ConnectionError, public_https, origin
from .workflow_publication_service import no_store, read_object

BASE='/api/customer-organizations/{ws}/provider-connections'


def router_for(core):
    manager=ProviderConnections(core.access)
    core.provider_connections=manager
    router=APIRouter(route_class=WorkspaceRoute)
    reads,writes=RateLimiter(90),RateLimiter(12)

    def invoke(fn,*args):
        try:
            return fn(*args)
        except ConnectionError as error:
            raise HTTPException(400,{'code':error.code}) from None
        except WorkspaceDenied:
            raise HTTPException(403,{'code':'permission_required'}) from None
        except WorkspaceConflict:
            raise HTTPException(409,{'code':'review_changed'}) from None
        except (WorkspaceInvalid,ValueError,TypeError,KeyError):
            raise HTTPException(400,{'code':'invalid_request'}) from None

    def actor(ws,request,write=False,callback=False,*,document=False):
        if request.headers.get('authorization'):
            raise HTTPException(403,{'code':'permission_required'})
        customer=invoke(core.identity.actor,request.cookies.get(COOKIE)) if callback else customer_actor(request,core.identity,csrf=write,document=document)
        if not (writes if write else reads).allow(customer.customer_id):
            raise HTTPException(429,{'code':'rate_limited'})
        return invoke(core.actor,ws,customer)

    def public_origin():
        configuration=core.identity.config or core.identity.github_config
        url=getattr(configuration,'redirect_uri',None)
        if not public_https(url):
            raise HTTPException(503,{'code':'oauth_setup_required'})
        return origin(url)

    async def body(request):
        try:
            return await read_object(request,16384)
        except (ValueError,TypeError,UnicodeError,TimeoutError):
            raise HTTPException(400,{'code':'invalid_request'}) from None

    def response(**data):
        return JSONResponse({'ok':True,**data},headers=no_store())

    @router.get(BASE)
    def listing(ws:str,request:Request):
        return response(**invoke(manager.listing,ws,actor(ws,request)))

    @router.get(BASE+'/agents')
    def search(ws:str,request:Request,q:str='',after:int=0):
        return response(**invoke(manager.search,ws,actor(ws,request),q,after))

    @router.post(BASE+'/search')
    async def private_search(ws:str,request:Request):
        current=actor(ws,request,True)
        value=await body(request)
        if set(value)!={'q','after'}:
            raise HTTPException(400,{'code':'invalid_request'})
        return response(**await run_in_threadpool(invoke,manager.search,ws,current,value['q'],value['after']))

    @router.get(BASE+'/agents/{rid}')
    def inspect(ws:str,rid:int,request:Request):
        return response(**invoke(manager.inspect,ws,actor(ws,request),rid))

    @router.post(BASE+'/agents/{rid}/key')
    async def save(ws:str,rid:int,request:Request):
        current=actor(ws,request,True)
        return response(connection=await run_in_threadpool(invoke,manager.save_key,ws,current,rid,await body(request)))

    @router.post(BASE+'/agents/{rid}/verify')
    async def verify(ws:str,rid:int,request:Request):
        current=actor(ws,request,True)
        return response(connection=await run_in_threadpool(invoke,manager.verify,ws,current,rid,await body(request)))

    @router.post(BASE+'/agents/{rid}/disconnect')
    async def disconnect(ws:str,rid:int,request:Request):
        current=actor(ws,request,True)
        return response(**await run_in_threadpool(invoke,manager.disconnect,ws,current,rid,await body(request)))

    @router.post(BASE+'/agents/{rid}/oauth/inspect')
    async def oauth_inspect(ws:str,rid:int,request:Request):
        current=actor(ws,request,True)
        value=await body(request)
        if value!={}:
            raise HTTPException(400,{'code':'invalid_request'})
        metadata=await run_in_threadpool(invoke,manager.oauth_metadata,ws,current,rid)
        return response(metadata=metadata,callback=public_origin()+'/api/customer-provider-oauth/'+str(rid)+'/callback')

    @router.post(BASE+'/agents/{rid}/oauth/begin')
    async def oauth_begin(ws:str,rid:int,request:Request):
        current=actor(ws,request,True)
        return response(**await run_in_threadpool(invoke,manager.begin_oauth,ws,current,rid,await body(request),public_origin()))

    @router.get('/api/customer-provider-oauth/clients/{rid}.json')
    def client_metadata(rid:int):
        if rid<=0:
            raise HTTPException(404)
        site=public_origin()
        return response(client_id=site+'/api/customer-provider-oauth/clients/'+str(rid)+'.json',
                        client_name='Agent Concierge',client_uri=site,
                        redirect_uris=[site+'/api/customer-provider-oauth/'+str(rid)+'/callback'],
                        grant_types=['authorization_code'],response_types=['code'],token_endpoint_auth_method='none')

    @router.get('/api/customer-provider-oauth/{rid}/callback')
    async def callback(rid:int,request:Request):
        from .customer_provider_connections_view import callback_page
        raw=request.scope.pop('_customer_provider_callback_query',request.scope.get('query_string',b''))
        request.scope['query_string']=b''
        for name in ('_url','_query_params'):
            if hasattr(request,name):delattr(request,name)
        result='oauth_invalid'
        try:
            pairs=list(QueryParams(raw).multi_items());query=dict(pairs)
            if (len(raw)>8192 or len(query)!=len(pairs) or set(query)-{'code','state','iss','error','error_description','scope'}
                    or ('code' in query)==('error' in query)):
                raise ValueError()
            state=query.get('state','')
            if not re.fullmatch(r'ws_[0-9a-f]{32}\.[A-Za-z0-9_-]{43}',state):raise ValueError()
            ws=state.split('.')[0];current=actor(ws,request,True,True)
            await run_in_threadpool(manager.complete_oauth,ws,current,rid,query)
            result='oauth_connected'
        except ConnectionError as error:
            result=error.code
        except (HTTPException,ValueError,TypeError,KeyError):
            pass
        return callback_page(result)

    @router.get('/customer/organizations/{ws}/connections')
    def page(ws:str,request:Request):
        actor(ws,request,document=True)
        from .customer_provider_connections_view import page_for
        return page_for(ws)

    @router.get('/customer/provider-connections')
    def chooser(request:Request):
        from .customer_provider_connections_view import chooser_page
        return chooser_page()

    return router
