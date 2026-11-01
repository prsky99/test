"""Edge-first delivery of already-authorized private Agent output, never replay IO."""
import hashlib
import hmac
import base64
import json
import re
import secrets

from fastapi import HTTPException
from starlette.requests import Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse,Response,StreamingResponse

from .auth import b64,canonical,derived,service_mac
from .config import EdgeError,parse
from .result_transport import read,write_once,sql
from .state import transaction
from .output_monitor import note

CONTEXT='edge-output-relay-v1'
MEDIA='application/vnd.agentconcierge.edge-output+json'
LIMIT=65536
FALLBACK={'OUTPUT_LIMIT':'output_limit','EDGE_NOT_READY':'edge_not_ready'}
# Only Agent execution/results, never secrets, billing, audit, membership or configuration.
OUTPUT=re.compile(r'/admin/api/(?:v2/catalog-tools/)?test-reports(?:/[^/]+)?\Z|/admin/api/(?:v2/catalog-tools/)?test/execute\Z|/admin/api/(?:v2/catalog-tools/)?connections/[1-9][0-9]*/contracts/[^/]+/test\Z|/admin/api/workflows/(?:[1-9][0-9]*/run|runs/[^/]+)\Z|/admin/api/(?:workflow-workspaces|v2/(?:workspace-panels|staff-workspaces))/[^/]+/(?:.*?/)?(?:runs(?:/[^/]+)?|product-test(?:/[^/]+)?|app-factory/model-proposals(?:/[^/]+)?|advancement/support/assistant|remote-a2a/tasks(?:/[^/]+(?:/messages)?)?)\Z')


def owner(service,token):
    return hmac.new(derived(service.config.key,CONTEXT),token.encode(),hashlib.sha256).hexdigest()


def actor(service,request):
    from ..gateway import admin_auth
    from ..gateway.admin_security import check_origin
    check_origin(request)
    header=request.headers.get('authorization','')
    if request.headers.get('x-dashboard')!='1' or not re.fullmatch(r'Bearer [a-f0-9]{64}',header):raise HTTPException(401,'Use a current individual session.')
    # A session check only reads; the writer lock made it wait behind bulk catalog writes (lock timeout, 500).
    readonly={'readonly':True} if getattr(service.store,'backend',None)=='postgresql' else {}
    with service.store.tx(**readonly) as db:user=admin_auth.get_session_user(db,header[7:],upgrade_legacy=False)
    if user and user.pop('_legacy_session',False):
        with service.store.tx() as db:user=admin_auth.get_session_user(db,header[7:])
    if not user or user.get('password_change_required'):raise HTTPException(401,'Use a current individual session.')
    return owner(service,header[7:])


def publish(service,principal,client_origin,body,status,*,client=None):
    from .admin_delivery import origin
    from ..concierge.http_security import bounded_client,OutboundBudget
    client_origin=origin(client_origin)
    readiness=service.summary()
    # Readiness policy (stale observation, reserve, CPU guard) is an intended Origin path, not a publish fault.
    if readiness['preferred_backend']!='worker' and readiness['reason']!='operator_origin':raise EdgeError('EDGE_NOT_READY')
    run='er_'+secrets.token_hex(16);expires=int(service.clock()+120)
    wire=canonical({'status':status,'body':body});digest=hashlib.sha256(wire.encode()).hexdigest()
    if len(wire.encode())>LIMIT:raise EdgeError('OUTPUT_LIMIT',413)
    write_once(service,run,CONTEXT,{'owner':principal,'expires':expires,'wire':wire})
    # The short capability contains no Admin session or Provider credentials.
    payload=b64(canonical({'aud':CONTEXT,'run':run,'origin':client_origin,'hash':digest,'exp':expires}).encode())
    token=payload+'.'+b64(hmac.new(derived(service.config.key,CONTEXT),payload.encode(),hashlib.sha256).digest())
    path='/api/edge-gateway/v1/output-publish';raw=canonical({'run':run,'wire':wire,'hash':digest}).encode()
    stamp=str(int(service.clock()));nonce=secrets.token_hex(16)
    http=bounded_client(client,allow_private=False,limit=4096,budget=OutboundBudget(6))
    try:
        response=http.post(service.config.origin+path,content=raw,headers={'Content-Type':'application/json',
            'X-Edge-Time':stamp,'X-Edge-Nonce':nonce,'X-Edge-Signature':service_mac(service.config.key,'POST',path,stamp,nonce,raw)})
        if response.status_code!=200 or response.json()!={'ok':True,'run':run,'hash':digest}:raise EdgeError('EDGE_UNAVAILABLE')
    finally:http.close()
    return {'_edge_output_v1':True,'base':service.config.origin,'run_id':run,
        'path':'/api/edge-gateway/v1/outputs/'+run,'access_token':token}


def cleanup(service):
    with transaction(service.store) as db:
        candidates=sql(db,"SELECT run_id,payload FROM workflow_checkpoints WHERE node_id=? AND substr(run_id,1,3)='er_' LIMIT 100",(CONTEXT,)).fetchall()
        for run,payload in candidates:
            try:expired=json.loads(payload)['expires']<service.clock()
            except Exception:expired=False
            if expired:sql(db,'DELETE FROM workflow_checkpoints WHERE run_id=? AND node_id=?',(run,CONTEXT))


def compatibility(service,envelope,client_origin):
    from ..concierge.http_security import bounded_client,OutboundBudget
    client=bounded_client(allow_private=False,limit=131072,budget=OutboundBudget(6))
    try:
        response=client.get(envelope['base']+envelope['path'],headers={'Origin':client_origin,'Authorization':'Bearer '+envelope['access_token']})
        if response.status_code!=200:raise EdgeError('EDGE_UNAVAILABLE')
        return response.json()
    finally:client.close()


def retained(service,value):
    """Worker-only recovery of an already-authorized output, never Agent execution."""
    if type(value) is not dict or set(value)!={'run','capability','origin'}:raise EdgeError('INVALID_INPUT',400)
    token=value['capability']
    if type(token) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,1024}\.[A-Za-z0-9_-]{43}',token):raise EdgeError('AUTH_REQUIRED',401)
    payload,proof=token.split('.')
    expected=b64(hmac.new(derived(service.config.key,CONTEXT),payload.encode(),hashlib.sha256).digest())
    if not hmac.compare_digest(proof,expected):raise EdgeError('AUTH_REQUIRED',401)
    claims=parse(base64.urlsafe_b64decode(payload+'='*(-len(payload)%4)))
    if (set(claims)!={'aud','run','origin','hash','exp'} or claims['aud']!=CONTEXT or claims['run']!=value['run']
            or claims['origin']!=value['origin'] or type(claims['exp']) is not int or not service.clock()<claims['exp']<=service.clock()+125):raise EdgeError('AUTH_REQUIRED',401)
    saved=read(service,value['run'],CONTEXT)
    if not saved or saved.get('expires',0)<=service.clock() or hashlib.sha256(saved['wire'].encode()).hexdigest()!=claims['hash']:raise EdgeError('RESULT_UNAVAILABLE',404)
    return json.loads(saved['wire'])


def install(app,front):
    @app.middleware('http')
    async def relay(request,call_next):
        selected=OUTPUT.fullmatch(request.url.path)
        response=await call_next(request)
        if not selected or request.method not in ('GET','POST') or response.status_code in (401,403) or not response.headers.get('content-type','').startswith('application/json'):return response
        service=getattr(front,'edge_gateway',None)
        if service is None:
            response.headers['X-Execution-Delivery']='origin-fallback';return response
        try:principal=await run_in_threadpool(actor,service,request)
        except HTTPException as exc:return JSONResponse({'detail':exc.detail},status_code=exc.status_code,headers={'Cache-Control':'no-store'})
        raw=bytearray();iterator=response.body_iterator
        async for chunk in iterator:
            raw.extend(chunk)
            if len(raw)>LIMIT:
                async def rest():
                    yield bytes(raw)
                    async for tail in iterator:yield tail
                note(service,'origin','admin','output_limit')
                return StreamingResponse(rest(),status_code=response.status_code,headers={**response.headers,'X-Execution-Delivery':'origin-fallback'})
        headers=dict(response.headers);headers.pop('content-length',None)
        try:
            client_origin=request.headers.get('origin') or str(request.url).split('/admin/',1)[0]
            envelope=await run_in_threadpool(publish,service,principal,client_origin,json.loads(raw),response.status_code)
            try:
                if secrets.randbelow(64)==0:await run_in_threadpool(cleanup,service)
            except Exception:pass
            retained={k:v for k,v in headers.items() if k not in ('content-type','content-encoding','etag')}
            if request.headers.get('x-edge-output-transport')!='v1':
                delivered=await run_in_threadpool(compatibility,service,envelope,client_origin)
                if delivered!={'status':response.status_code,'body':json.loads(raw)}:raise EdgeError('RESULT_INVALID')
                return Response(bytes(raw),status_code=response.status_code,headers={**headers,'X-Execution-Delivery':'edge','X-Edge-Compatibility-Relay':'1'})
            return JSONResponse(envelope,media_type=MEDIA,headers={**retained,'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})
        except Exception as error:
            note(service,'origin','admin',FALLBACK.get(getattr(error,'code',None),'publish_failed'),len(raw))
            return Response(bytes(raw),status_code=response.status_code,headers={**headers,'X-Execution-Delivery':'origin-fallback'})

    @app.get('/admin/api/v2/gateway/edge-output/{run_id}',include_in_schema=False)
    async def recover(run_id:str,request:Request):
        service=getattr(front,'edge_gateway',None)
        if service is None or not re.fullmatch(r'er_[a-f0-9]{32}',run_id):raise HTTPException(404,'The retained output is unavailable.')
        principal=await run_in_threadpool(actor,service,request)
        value=await run_in_threadpool(read,service,run_id,CONTEXT)
        if not value or value.get('owner')!=principal or value.get('expires',0)<=service.clock():raise HTTPException(404,'The retained output is unavailable.')
        note(service,'origin','admin','cache_miss')
        result=json.loads(value['wire'])
        return JSONResponse(result['body'],status_code=result['status'],headers={'Cache-Control':'private, no-store','X-Execution-Delivery':'origin-fallback'})
