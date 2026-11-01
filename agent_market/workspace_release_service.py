"""Separate staff management and customer-only SDK 2 gateway transport."""
from io import BytesIO
import json
from pathlib import Path
import re
import secrets
from zipfile import ZipFile,ZipInfo,ZIP_DEFLATED

from fastapi import APIRouter,Depends,HTTPException,Request
from fastapi.responses import HTMLResponse,JSONResponse,Response
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool

from .customer_workspace_pearl import pearl_response
from .gateway import admin_auth
from .broker.server import RateLimiter
from .workspace_access import SessionActor,WorkspaceDenied,WorkspaceConflict,WorkspaceInvalid
from .workspace_release import SDK_PROFILE
from .workspace_service import WorkspaceRoute,BASE
from .workflow_publication_service import no_store,read_object
from .workflow_product_semantics_service import bounded_tree

ASSET=Path(__file__).parent/'gateway'/'workspace-release-admin.js'
PUBLIC='/api/workspace-apps-v2'


def build_package(config):
    typed = config.get('profile') == 'workspace-typed-sdk-v2'
    root=Path(__file__).parent
    files={name:(root/'gateway'/'webapp'/name).read_bytes() for name in ('sdk-v2.js','app-v2.js','styles-v2.css','index-v2.html')}
    files['index.html']=files.pop('index-v2.html')
    if typed:
        files['app-v2.js']=(root/'gateway'/'webapp'/'app-typed-v2.js').read_bytes()
        files['sdk-v2.js']=files['sdk-v2.js'].replace(b'15000',b'75000')
        files['index.html']=files['index.html'].replace(b'Review one task',b'Review whole workflow').replace(b'one private read-only agent task',b'one reviewed private typed workflow').replace(b'one private agent run',b'one reviewed private graph run').replace(b'Each task sends the reviewed input to the selected external agent only after your consent.',b'Each workflow shares the reviewed literal inputs and declared prior outputs with every listed external agent only after your consent.').replace(b'I authorize the reviewed input to be sent to the selected external agent for one private read-only run.',b'I authorize the exact literals and selected prior outputs to be shared with every listed agent for this one reviewed private workflow.')
    files['bff.py']=(root/'workspace_sdk_bff.py').read_bytes()
    files['app-manifest.json']=(json.dumps(config,sort_keys=True,indent=2)+'\n').encode()
    files['requirements.txt']=b'fastapi>=0.115,<1\nhttpx>=0.28,<1\nuvicorn>=0.34,<1\n'
    files['README.txt']=b'''Workspace SDK 2\n\nInstall requirements, set SDK2_ORIGIN to an exact approved origin, and run bff.py. Place a TLS reverse proxy in front of the loopback BFF. Configure HTTPS, preserve its CSP/frame-ancestors/no-store headers, and never publish the BFF cookie or memory tokens. The package contains no administrator password, API key or embedded bearer credential.\n\nCustomers sign in on Agent Concierge using a configured identity provider, then explicitly authorize this app. Workspace linkage is granted separately by its current owner. Identity-provider configuration is required; unavailable configuration denies sign-in. Each run requires a new review and unchecked consent before sending the exact input to the selected external agent.\n\nThis fixed private release supports one read-only MCP tool call. It does not grant publication, scheduled execution, webhooks, notifications, payments or result delivery. Unknown or uncertain submissions are never automatically repeated. Use app history to inspect an accepted run. Closing the page clears local review state, not a server-side cancellation. App session tokens are short-lived and kept only in BFF memory; restarting the BFF signs app users out.\n'''
    if typed:
        files['README.txt']=files['README.txt'].replace(b'This fixed private release supports one read-only MCP tool call.',b'This separate typed profile supports two to ten reviewed read-only MCP steps within sixty seconds, with explicit primitive prior-output bindings and branches. The whole graph and all destinations require fresh consent.').replace(b'the exact input to the selected external agent',b'the exact literal inputs and selected prior outputs to every listed external agent')
    output=BytesIO()
    with ZipFile(output,'w',ZIP_DEFLATED) as archive:
        for name,data in files.items():
            item=ZipInfo(name);item.external_attr=0o644<<16;item.compress_type=ZIP_DEFLATED;archive.writestr(item,data)
    return output.getvalue(),('agent-concierge-workspace-typed-sdk-v2.zip' if typed else 'agent-concierge-workspace-sdk-v2.zip')


def authorize_page(app_id,query,*,typed=False):
    if not re.fullmatch('wap_[0-9a-f]{32}',app_id) or set(query)!={'origin','redirect_uri','challenge','state'} or len(query.multi_items())!=4:raise HTTPException(400,'Review a valid app sign-in request.')
    nonce=secrets.token_urlsafe(24)
    data=json.dumps({'app_id':app_id,**dict(query)},ensure_ascii=True).replace('<','\\u003c')
    html='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Authorize private workspace app | Agent Concierge</title><meta name="description" content="Review a separately approved private workspace app using your current customer session."><style nonce="NONCE">:root{color-scheme:light dark;font:16px system-ui}body{margin:0;min-height:100vh;display:grid;place-items:center;background:light-dark(#f3f6fb,#101620);color:light-dark(#19243a,#eef3ff)}main{max-width:35rem;padding:2rem;margin:1rem;border:1px solid #8796b344;border-radius:1.2rem;background:light-dark(white,#172235)}button,a{font:inherit;border-radius:.7rem;padding:.7rem;border:1px solid #8ba0bc66;color:inherit;background:transparent}button:disabled{opacity:.5}button{cursor:pointer;margin:.3rem}p{line-height:1.6}:focus-visible{outline:3px solid #579bff;outline-offset:3px}footer{margin-top:1.4rem;display:flex;gap:1rem}</style></head><body><main><h1>Authorize a private workspace app</h1><p>This app can request one reviewed read-only agent call at a time. Every run still requires a separate input review and your explicit consent. This does not publish your workspace.</p><p id="destination"></p><p id="status" role="status">Check your customer sign-in to continue.</p><a href="/customer/sign-in" target="_blank" rel="noopener noreferrer">Sign in as a customer</a><p>After signing in, return here and check your session.</p><button id="check">Check sign-in</button><button id="authorize" disabled>Authorize this app</button><footer><a href="/#privacy">Privacy</a><a href="/#tos">Terms</a></footer></main><script nonce="NONCE">const configuration=DATA;let csrf='';const status=document.getElementById('status'),authorize=document.getElementById('authorize');document.getElementById('destination').textContent='Approved app origin: '+configuration.origin;async function check(){authorize.disabled=true;try{const r=await fetch('/api/customer-auth/session',{credentials:'same-origin',cache:'no-store'}),v=await r.json();if(!r.ok||typeof v.session?.csrf_token!=='string')throw Error();csrf=v.session.csrf_token;status.textContent='Customer session confirmed. Authorize only the app you opened.';authorize.disabled=false}catch{csrf='';status.textContent='A current customer sign-in and explicit workspace access are required.'}}document.getElementById('check').addEventListener('click',check);authorize.addEventListener('click',async()=>{authorize.disabled=true;try{const {app_id,...body}=configuration,r=await fetch('/api/workspace-apps-v2/'+app_id+'/authorize',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Customer-CSRF':csrf},body:JSON.stringify(body)}),v=await r.json();if(!r.ok||typeof v.code!=='string'||v.redirect_uri!==configuration.redirect_uri||v.state!==configuration.state)throw Error();const target=new URL(v.redirect_uri);if(target.origin!==configuration.origin||target.pathname!=='/bff/callback')throw Error();target.search=new URLSearchParams({code:v.code,state:v.state}).toString();location.assign(target.href)}catch{status.textContent='App authorization could not be verified. No agent was called.'}});</script></body></html>'''.replace('NONCE',nonce).replace('DATA',data)
    if typed:
        html=html.replace('This app can request one reviewed read-only agent call at a time. Every run still requires a separate input review and your explicit consent.', 'This app can request one reviewed private workflow of two to ten read-only agent steps. Every run requires review of every destination, literal input, selected prior output and branch, plus your explicit whole-graph consent.').replace('/api/workspace-apps-v2/','/api/workspace-flow-apps-v2/')
    return pearl_response(HTMLResponse(html,headers={**no_store(),'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY','Content-Security-Policy':f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"}),nonce,section='account',auth=True)


class AppGatewayRoute(APIRoute):
    def get_route_handler(self):
        handler=super().get_route_handler()
        async def safe(request):
            try:response=await handler(request)
            except HTTPException as error:response=JSONResponse({'detail':error.detail},status_code=error.status_code)
            except Exception:response=JSONResponse({'detail':'The current app request is unavailable. Inspect history before another action.'},status_code=500)
            response.headers.update(no_store());response.headers['X-Content-Type-Options']='nosniff';response.headers['Referrer-Policy']='no-referrer';return response
        return safe


def router_for(releases,lifecycle,*,public=True,admin=True,typed=False):
    profile='workspace-typed-sdk-v2' if typed else SDK_PROFILE
    public_prefix='/api/workspace-flow-apps-v2' if typed else PUBLIC
    page_prefix='/workspace-flow-apps-v2' if typed else '/workspace-apps-v2'
    router=APIRouter(route_class=WorkspaceRoute);store=releases.store;staff_limit=RateLimiter(60);app_limit=RateLimiter(120)
    def response(value=None,**values):return JSONResponse({'ok':True,'profile':profile,**(value or {}),**values},headers=no_store())
    def staff(request:Request):
        value=request.headers.get('authorization','')
        if request.headers.get('x-dashboard')!='1' or not re.fullmatch('Bearer [a-f0-9]{64}',value):raise HTTPException(401,'Use an individual administrator session.')
        with store.tx() as db:user=admin_auth.get_session_user(db,value[7:])
        if not user:raise HTTPException(401,'The current administrator session is unavailable.')
        if not staff_limit.allow(str(user['user_id'])):raise HTTPException(429,'Private app request limit reached.')
        return SessionActor(user['user_id'],admin_auth.session_reference(value[7:]))
    async def body(request):
        try:return bounded_tree(await read_object(request,65536))
        except (ValueError,TypeError,UnicodeError,RecursionError,TimeoutError):raise HTTPException(400,'Provide exact bounded fields.') from None
    def invoke(method,*args):
        try:return method(*args)
        except WorkspaceDenied:raise HTTPException(404,'The private app object or current authority is unavailable.') from None
        except WorkspaceConflict:raise HTTPException(409,'State changed or outcome is uncertain. Inspect history before another action.') from None
        except (WorkspaceInvalid,ValueError,TypeError,KeyError):raise HTTPException(400,'The private app request could not be validated.') from None
    scope=BASE+('/{ws}/typed-flows/{draft}/versions/{snapshot}/release-v2' if typed else '/{ws}/drafts/{draft}/snapshots/{snapshot}/release-v2')
    if admin:
        @router.get('/admin/assets/workspace-release-admin.js',include_in_schema=False)
        def asset():return Response(ASSET.read_bytes(),media_type='application/javascript',headers=no_store())
        @router.get(scope+'/options')
        def options(ws:str,draft:str,snapshot:str,actor=Depends(staff)):
            def current():
                with releases.access._tx(actor) as (db,_):
                    releases._owner(ws,actor)
                    if typed:
                        binding,version=releases.typed._binding(db,ws,draft,actor)
                        if version['id']!=snapshot:raise WorkspaceDenied()
                    else:releases.execution._scope(ws,draft,snapshot,actor)
            invoke(current)
            return response(can_manage=True,customer_auth_enabled=releases.identity is not None and releases.identity.options()['configured'])
        @router.get(scope+'/releases')
        def listing(ws:str,draft:str,snapshot:str,actor=Depends(staff)):return response(releases=invoke(releases.releases,ws,draft,snapshot,actor))
        @router.post(scope+'/releases')
        async def create(ws:str,draft:str,snapshot:str,request:Request,actor=Depends(staff)):
            return response(release=await run_in_threadpool(invoke,releases.create,ws,draft,snapshot,await body(request),actor))
        @router.post(scope+'/releases/{rid}/revoke')
        async def revoke(ws:str,draft:str,snapshot:str,rid:str,request:Request,actor=Depends(staff)):return response(release=await run_in_threadpool(invoke,releases.revoke,ws,draft,snapshot,rid,await body(request),actor))
        @router.get(scope+'/releases/{rid}/deployments')
        def deployments(ws:str,draft:str,snapshot:str,rid:str,actor=Depends(staff)):return response(deployments=invoke(releases.deployments,ws,draft,snapshot,rid,actor))
        @router.post(scope+'/releases/{rid}/deployments')
        async def deploy(ws:str,draft:str,snapshot:str,rid:str,request:Request,actor=Depends(staff)):return response(deployment=await run_in_threadpool(invoke,releases.deploy,ws,draft,snapshot,rid,await body(request),actor))
        @router.post(scope+'/deployments/{app}/revoke')
        async def revoke_app(ws:str,draft:str,snapshot:str,app:str,request:Request,actor=Depends(staff)):return response(deployment=await run_in_threadpool(invoke,releases.revoke_deployment,ws,draft,snapshot,app,await body(request),actor))
        @router.get(scope+'/deployments/{app}/package')
        def package(ws:str,draft:str,snapshot:str,app:str,actor=Depends(staff)):
            config=invoke(releases.package_config,ws,draft,snapshot,app,actor);data,name=build_package(config)
            return Response(data,media_type='application/zip',headers={**no_store(),'Content-Disposition':f'attachment; filename="{name}"'})
        if lifecycle is not None:
            @router.get(BASE+'/{ws}/lifecycle/preview')
            def preview(ws:str,actor=Depends(staff)):return response(invoke(lifecycle.preview,ws,actor))
            @router.post(BASE+'/{ws}/lifecycle/maintain')
            async def maintain(ws:str,request:Request,actor=Depends(staff)):return response(await run_in_threadpool(invoke,lifecycle.maintain,ws,await body(request),actor))
            @router.get(scope+'/reconcile/{run}')
            def notes(ws:str,draft:str,snapshot:str,run:str,actor=Depends(staff)):return response(notes=invoke(lifecycle.notes,ws,draft,snapshot,run,actor))
            @router.post(scope+'/reconcile/{run}')
            async def note(ws:str,draft:str,snapshot:str,run:str,request:Request,actor=Depends(staff)):return response(note=await run_in_threadpool(invoke,lifecycle.reconcile,ws,draft,snapshot,run,await body(request),actor))
            @router.post(scope+'/restore-review/prepare')
            async def restore_prepare(ws:str,draft:str,snapshot:str,request:Request,actor=Depends(staff)):
                if await body(request)!={}:raise HTTPException(400,'No mutable restore authority is accepted.')
                return response(invoke(lifecycle.prepare_restore_review,ws,draft,snapshot,actor))
            @router.post(scope+'/restore-review/approve')
            async def restore_approve(ws:str,draft:str,snapshot:str,request:Request,actor=Depends(staff)):return response(invoke(lifecycle.approve_restore_review,ws,await body(request),actor))
    if public:
        management=router
        def limited(request:Request):
            if not app_limit.allow(request.client.host if request.client else 'unknown'):raise HTTPException(429,'App request limit reached.')
        router=APIRouter(route_class=AppGatewayRoute,dependencies=[Depends(limited)])
        @router.get(page_prefix+'/{app}/authorize')
        def authorization_page(app:str,request:Request):return authorize_page(app,request.query_params,typed=typed)
        @router.post(public_prefix+'/{app}/authorize')
        async def authorize(app:str,request:Request):
            from .customer_identity_service import customer_actor
            if releases.identity is None:raise HTTPException(403,'Customer sign-in is unavailable.')
            actor=customer_actor(request,releases.identity,csrf=True)
            return response(invoke(releases.authorize,app,await body(request),actor))
        @router.post(public_prefix+'/{app}/exchange')
        async def exchange(app:str,request:Request):return response(invoke(releases.exchange,app,await body(request),request.headers.get('origin')))
        def token(request):
            header=request.headers.get('authorization','')
            if not re.fullmatch('Bearer [A-Za-z0-9_-]{43}',header):raise HTTPException(401,'A current app capability is required.')
            return header[7:]
        @router.post(public_prefix+'/{app}/prepare')
        async def prepare(app:str,request:Request):
            if await body(request)!={}:raise HTTPException(400,'No mutable run inputs are accepted.')
            return response(await run_in_threadpool(invoke,releases.prepare,app,token(request),request.headers.get('origin')))
        @router.post(public_prefix+'/{app}/runs')
        async def run(app:str,request:Request):return response(await run_in_threadpool(invoke,releases.execute,app,token(request),await body(request),request.headers.get('origin')))
        @router.get(public_prefix+'/{app}/history')
        def history(app:str,request:Request):return response(runs=invoke(releases.history,app,token(request),request.headers.get('origin')))
        @router.post(public_prefix+'/{app}/status-capability')
        async def capability(app:str,request:Request):
            data=await body(request)
            if set(data)!={'run_id'}:raise HTTPException(400,'Select one retained run.')
            return response(invoke(releases.status_capability,app,token(request),data['run_id'],request.headers.get('origin')))
        @router.get(public_prefix+'/{app}/runs/{run}')
        def status(app:str,run:str,request:Request):return response(run=invoke(releases.status,app,token(request),run,request.headers.get('origin')))
    if public:
        management.include_router(router);return management
    return router
