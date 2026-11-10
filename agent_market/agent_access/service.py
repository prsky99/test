"""Shared compact MCP/REST adapters with transport-only visitor capabilities."""
import json
import threading
from urllib.parse import urlsplit

from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import JSONResponse,Response,HTMLResponse
from starlette.concurrency import run_in_threadpool
from jsonschema import Draft202012Validator

from ..capability_registry import digest
from ..concierge.agent_entry import resumed_context
from ..concierge.conditional_http import etag_matches
from ..concierge.recovery import report_outcome
from ..customer_identity import customer_identity_for
from ..customer_identity_service import customer_actor
from .contracts import PROFILE,tools
from .catalog import Catalog,bounded
from .tasks import Tasks,SUPPORTED
from .events import Events
from .storage import ready,transaction

_LOCK=threading.RLock()
PRIVATE={'Cache-Control':'private, no-store','Vary':'X-Visitor-Token, Mcp-Session-Id, Authorization'}
# Category pages: static HTML with one same-origin stylesheet and a JSON-LD block (data, never run).
CATEGORY_CSP=("default-src 'none'; img-src 'self' data:; script-src 'none'; script-src-attr 'none'; object-src 'none'; "
    "style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


class Adoption:
    def __init__(self,front):
        self.front=front;self.catalog=Catalog(front);self.events=Events(front)
        self.identity=customer_identity_for(front.store,front.updates.key)
        self.tasks=Tasks(front,self.identity)

    def invoke(self,name,body,visitor):
        operation=self.front.proxy.journal.begin('recommendation','agent_discovery')
        try:
            result=self._invoke(name,body,visitor)
            operation.finish('no_match'if result.get('status')=='no_match'else'matched')
            return result
        except Exception:
            operation.finish('denied','POLICY_DENIED');raise

    def _invoke(self,name,body,visitor):
        if not ready(self.front.store):raise ValueError('SCHEMA_NOT_READY')
        definition=next((t for t in tools()if t['name']==name),None)
        if not definition or list(Draft202012Validator(definition['inputSchema']).iter_errors(body)):
            raise ValueError('INVALID_INPUT')
        if name=='discover':
            result=self.catalog.discover(body)
            if result.get('resource_type')=='agent'and result['items']:
                self.front.book.save_results(visitor,[{'id':r['id'],'task':body['task'],
                    'protocol_filter':body.get('protocol'),'resource_type':'agent'}for r in result['items']],len(result['items']))
            elif result.get('resource_type')=='workflow'and result['items']:
                self.front.book.save_results(visitor,[{'id':r['id'],'task':body['task'],
                    'protocol_filter':body.get('protocol'),'resource_type':'workflow','definition_hash':r.get('definition_hash'),
                    'availability_code':(r.get('execution_availability')or{}).get('reason_code')}for r in result['items']],len(result['items']))
            if body.get('prepare')and result.get('resource_type')=='agent'and result['items']:
                selected=result['items'][0]
                definitions=self.front.store.query('SELECT contract_id FROM capability_approvals WHERE version_id=?',(selected['version_id'],))
                contract=next((r[0]for r in definitions if r[0]in SUPPORTED),None)
                if contract is None:result['preparation']={'status':'unsupported_contract','execution_authorized':False}
                elif 'arguments'not in body:result['preparation']={'status':'needs_input','execution_authorized':False}
                else:result['preparation']=self.tasks.prepare(visitor.id,selected['id'],contract,body['arguments'])
            definition=result.get('selected_contract')or{}
            if 'tools_schema'in definition and len(json.dumps(result,ensure_ascii=True).encode())>7800:
                definition.pop('tools_schema');result['schema_deferred']=True
            return bounded(result)
        if name=='describe':return self.catalog.describe(body['resource_id'],body.get('version_id'))
        if name=='resume':return resumed_context(self.front,visitor.token)
        if name=='report':return report_outcome(self.front,visitor,body)
        if name=='execute':
            if body['action']in ('status','cancel'):
                if set(body)!={'action','operation_id'}:raise ValueError('INVALID_INPUT')
                return getattr(self.tasks,body['action']if body['action']=='cancel'else'operation')(visitor.id,body['operation_id'])
            if set(body)!={'action','preparation_id','grant','idempotency_key'}:raise ValueError('INVALID_INPUT')
            return self.tasks.execute(visitor.id,body['preparation_id'],body['grant'],body['idempotency_key'])
        raise ValueError('INVALID_INPUT')


def for_front(front):
    with _LOCK:
        if not hasattr(front,'_adoption_service'):front._adoption_service=Adoption(front)
        return front._adoption_service


def router_for(front,*,customer_enabled=False):
    router=APIRouter(); core=for_front(front)

    def visitor(request,create=False):
        origin=request.headers.get('origin')
        if origin and origin.rstrip('/')not in ('https://agentconcierge.biz',front.public_url):
            raise HTTPException(403,'Use the service origin.')
        token=request.headers.get('x-visitor-token')or request.headers.get('mcp-session-id')
        authorization=request.headers.get('authorization','')
        if not token and authorization.lower().startswith('bearer '):token=authorization[7:]
        found=front.book.by_token(token)if token else None
        if token and not found:raise HTTPException(401,'A valid session header is required.')
        if not found and create:found=front.identify(request,'mcp')
        if found is None:raise HTTPException(401,'A valid session header is required.')
        found.token=token or found.token
        return found

    async def read(request):
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>16384:raise HTTPException(413,'Use a bounded request.')
        try:
            body=json.loads(raw)
            if type(body)is not dict:raise ValueError()
            return body
        except (ValueError,RecursionError):raise HTTPException(400,'Use a JSON object.')from None

    def rate(request):
        from ..concierge.security import quota_headers
        allowed=front.security.allow_explore(front.security.resolve_ip(request),base_limit=120)
        headers=quota_headers();request.scope['agent_adoption_quota']=headers
        if not allowed:
            raise HTTPException(429,'Request limit reached.',headers={**headers,'Retry-After':'60','Cache-Control':'private, no-store'})

    def error_code(error):
        known={'INVALID_INPUT','NOT_FOUND','NOT_VERIFIED','SCHEMA_CHANGED','SCHEMA_NOT_READY',
               'EXPIRED','UNSUPPORTED_CONTRACT','AUTHORIZATION_REQUIRED','IDEMPOTENCY_CONFLICT',
               'RESPONSE_TOO_LARGE','SERVICE_BUSY','INVALID_CURSOR','RESYNC_REQUIRED'}
        return str(error)if str(error)in known else'REQUEST_REFUSED'

    @router.post('/api/agent/v1/discover',operation_id='discoverAgentTask')
    async def discover(request:Request):
        rate(request);body=await read(request);v=await run_in_threadpool(visitor,request,True)
        try:result=await run_in_threadpool(core.invoke,'discover',body,v)
        except ValueError as error:raise HTTPException(400,error_code(error))from None
        return JSONResponse(result,headers={**PRIVATE,'X-Visitor-Token':v.token})

    @router.post('/mcp/compact',include_in_schema=False)
    async def compact(request:Request):
        rate(request)
        origin=request.headers.get('origin')
        if origin and origin.rstrip('/')not in ('https://agentconcierge.biz',front.public_url):raise HTTPException(403,'Use the service origin.')
        message=await read(request);rid=message.get('id');method=message.get('method');params=message.get('params',{})
        if (message.get('jsonrpc')!='2.0'or type(params)is not dict or type(rid)not in (int,str,type(None))or
                type(rid)is str and len(rid)>128 or type(rid)is int and not -(2**53)<rid<2**53):
            return JSONResponse({'jsonrpc':'2.0','id':None,'error':{'code':-32600,'message':'Invalid request'}},headers=PRIVATE)
        result=None;headers=dict(PRIVATE)
        if method=='initialize':
            v=await run_in_threadpool(visitor,request,True)
            asked=params.get('protocolVersion')
            result={'protocolVersion':asked if asked in ('2025-06-18','2025-11-25')else'2025-11-25',
                'capabilities':{'tools':{'listChanged':False}},'serverInfo':{'name':'agent-concierge-compact','version':'1.0.0'},
                'instructions':'Discover a task, review evidence and inputs, and execute only with an explicit customer grant. x402 requires an explicit discovery choice.'}
            headers['Mcp-Session-Id']=v.token
        elif method=='notifications/initialized':return Response(status_code=202,headers=PRIVATE)
        elif method=='ping':result={}
        elif method=='tools/list':result={'tools':tools()}
        elif method=='tools/call':
            v=await run_in_threadpool(visitor,request,params.get('name')=='discover')
            try:
                result=await run_in_threadpool(core.invoke,params.get('name'),params.get('arguments',{}),v)
                result={'structuredContent':result,'content':[{'type':'text','text':'Task information is available in structuredContent.'}],'isError':False}
                headers['Mcp-Session-Id']=v.token
            except ValueError as error:
                result={'structuredContent':{'error_code':error_code(error),'execution_authorized':False},
                    'content':[{'type':'text','text':'The request was refused. Review the task, current evidence and authorization.'}],'isError':True}
        else:return JSONResponse({'jsonrpc':'2.0','id':rid,'error':{'code':-32601,'message':'Method not found'}},headers=headers)
        return JSONResponse({'jsonrpc':'2.0','id':rid,'result':result},headers=headers)

    @router.post('/api/agent/v1/preparations/{preparation_id}/authorize',operation_id='authorizePreparedAgentTask')
    async def authorize(preparation_id:str,request:Request):
        if not customer_enabled:raise HTTPException(404,'Not Found')
        rate(request);v=await run_in_threadpool(visitor,request)
        actor=await run_in_threadpool(customer_actor,request,core.identity,True)
        body=await read(request)
        try:value=await run_in_threadpool(core.tasks.authorize,v.id,preparation_id,actor,body)
        except ValueError as error:raise HTTPException(403,error_code(error))from None
        return JSONResponse(value,headers=PRIVATE)

    @router.delete('/api/agent/v1/grants',operation_id='revokeAgentTaskGrant')
    async def revoke(request:Request):
        import hashlib,re
        if not customer_enabled:raise HTTPException(404,'Not Found')
        v=await run_in_threadpool(visitor,request)
        actor=await run_in_threadpool(customer_actor,request,core.identity,True)
        body=await read(request);grant=body.get('grant')
        if set(body)!={'grant'}or type(grant)is not str or not re.fullmatch('axg_[0-9a-f]{32}',grant):raise HTTPException(400,'Invalid grant.')
        def action():
            with transaction(front.store)as db:
                db.execute('UPDATE adoption_grants SET revoked=1 WHERE id=? AND owner=? AND customer_id=?',
                           (hashlib.sha256(grant.encode()).hexdigest(),v.id,actor.customer_id))
        await run_in_threadpool(action)
        return JSONResponse({'revoked':True},headers=PRIVATE)

    @router.get('/api/feed/verified.json',operation_id='getVerifiedAgentFeed')
    async def feed(request:Request,protocol:str|None=None,cursor:str|None=None,limit:int=30):
        rate(request)
        if not ready(front.store):raise HTTPException(503,'The change feed is preparing.',headers={'Retry-After':'60'})
        try:payload=await run_in_threadpool(core.events.feed,protocol,cursor,limit)
        except ValueError as error:raise HTTPException(400,error_code(error))from None
        tag='"'+digest(payload)+'"';headers={'Cache-Control':'no-cache','ETag':tag}
        if etag_matches(request.headers.get('if-none-match'),tag):return Response(status_code=304,headers=headers)
        return JSONResponse(payload,media_type='application/feed+json',headers=headers)

    @router.get('/api/agent/v1/openapi.json',include_in_schema=False)
    async def schema(request:Request):
        from .contracts import openapi_profile
        payload=openapi_profile(request.app.openapi())
        tag='"'+digest(payload)+'"';headers={'Cache-Control':'public, max-age=300','ETag':tag}
        if etag_matches(request.headers.get('if-none-match'),tag):return Response(status_code=304,headers=headers)
        return JSONResponse(payload,headers=headers)

    @router.post('/api/agent/v1/dependencies',operation_id='watchAgentDependency')
    async def dependencies(request:Request):
        rate(request);v=await run_in_threadpool(visitor,request);body=await read(request)
        if not {'watch_id','resource_id','authorized','notice'}<=set(body)or set(body)-{'watch_id','resource_id','authorized','notice','version_id','contract_id','event_types'}:
            raise HTTPException(400,'Review the dependency watch notice.')
        try:result=await run_in_threadpool(core.events.dependency,v.id,body['watch_id'],body['resource_id'],
            authorized=body['authorized'],notice=body['notice'],version_id=body.get('version_id'),
            contract_id=body.get('contract_id'),event_types=body.get('event_types'))
        except ValueError as error:raise HTTPException(400,error_code(error))from None
        return JSONResponse(result,headers=PRIVATE)

    @router.get('/agents/category/{category}',include_in_schema=False)
    async def category(category:str,request:Request):
        rate(request)
        from .pages import cached_category_page
        try:page=await run_in_threadpool(cached_category_page,front,category)
        except ValueError:raise HTTPException(404,'This category has no current public preview.')from None
        # 11-11: the page links /new/en/assets/styles.css, so its policy allows same-origin stylesheets;
        # the site default (style-src 'unsafe-inline') blocked it and left a console error.
        return HTMLResponse(page,headers={'Cache-Control':'no-cache','Content-Security-Policy':CATEGORY_CSP})

    return router
