"""Standalone SDK 2 BFF; customer app tokens remain in server memory only."""
import asyncio
import base64
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import secrets
import threading
import time
from urllib.parse import urlencode,urlsplit

import httpx
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse,RedirectResponse,Response

GATEWAY='https://agentconcierge.biz'
PROFILE='workspace-sdk-v2'
COOKIE='ac_workspace_app'
FLOW_COOKIE='ac_workspace_flow'


def _bounded_object(raw, limit):
    """Both browser commands and gateway responses use the same strict boundary."""
    if type(raw) not in (bytes, bytearray) or not 1 <= len(raw) <= limit:
        raise ValueError('Invalid bounded response.')
    def pairs(items):
        value={}
        for key,item in items:
            if key in value:raise ValueError('Duplicate fields are unavailable.')
            value[key]=item
        return value
    try:
        value=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
    except RecursionError:
        raise ValueError('Object limit reached.') from None
    if type(value) is not dict:raise ValueError('Use one bounded object.')
    count=0
    def walk(item,depth=0):
        nonlocal count
        count+=1
        if count>2000 or depth>12:raise ValueError('Object limit reached.')
        if type(item) is float and not math.isfinite(item):raise ValueError('Nonfinite values are unavailable.')
        if type(item) is dict:
            for nested in item.values():walk(nested,depth+1)
        elif type(item) is list:
            for nested in item:walk(nested,depth+1)
    walk(value)
    return value


def create_app(config,*,app_origin,http=None,root=None):
    profile=config.get('profile')
    if profile not in (PROFILE,'workspace-typed-sdk-v2'):raise ValueError('Invalid application profile.')
    typed=profile=='workspace-typed-sdk-v2'
    run_notice='workspace-sdk-whole-graph-run-v2' if typed else 'workspace-sdk-run-v2'
    budget=75 if typed else 15
    route_base='workspace-flow-apps-v2' if typed else 'workspace-apps-v2'
    app_id=config.get('app_id')
    if type(app_id) is not str or not re.fullmatch('wap_[0-9a-f]{32}',app_id) or app_origin not in config.get('allowed_origins',[]):raise ValueError('Invalid application configuration.')
    parsed=urlsplit(app_origin)
    if parsed.scheme!='https' and not(parsed.scheme=='http' and parsed.hostname in ('localhost','127.0.0.1','::1')):raise ValueError('Use an approved secure origin.')
    client=http or httpx.Client(timeout=budget,follow_redirects=False,trust_env=False)
    base=Path(root) if root is not None else Path(__file__).parent
    app=FastAPI();sessions={};flows={};lock=threading.RLock();secure=parsed.scheme=='https'
    prefix='/api/'+route_base+'/'+app_id
    headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY','Content-Security-Policy':"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"}
    def result(value,status=200):return JSONResponse(value,status_code=status,headers=headers)
    def trim():
        now=time.time()
        for table in (sessions,flows):
            for key in list(table):
                if table[key]['expires']<=now:table.pop(key,None)
    def same_origin(request):
        if request.headers.get('origin')!=app_origin or request.headers.get('sec-fetch-site','same-origin') not in ('same-origin','none'):raise ValueError()
    async def body(request):
        if request.headers.get('content-type','').split(';')[0].strip().lower()!='application/json' or request.headers.get('content-encoding','identity').lower()!='identity':raise ValueError()
        length=request.headers.get('content-length','0')
        if not re.fullmatch('[0-9]{1,8}',length) or int(length)>65536:raise ValueError()
        async def bounded():
            data=bytearray()
            async for chunk in request.stream():
                if len(data)+len(chunk)>65536:raise ValueError()
                data.extend(chunk)
            return bytes(data)
        raw=await asyncio.wait_for(bounded(),timeout=5)
        return _bounded_object(raw or b'{}',65536)
    def session(request,write=False):
        with lock:
            trim();value=sessions.get(request.cookies.get(COOKIE,''))
            if not value:raise PermissionError()
            if write:
                same_origin(request)
                if not hmac.compare_digest(request.headers.get('x-app-csrf',''),value['csrf']):raise PermissionError()
            return value
    def gateway(method,path,*,token=None,data=None):
        started=time.monotonic()
        with client.stream(method,GATEWAY+prefix+path,headers={'Origin':app_origin,'Accept-Encoding':'identity',**({'Authorization':'Bearer '+token} if token else {})},json=data) as response:
            if response.status_code>=400 or response.headers.get('content-encoding','identity').lower()!='identity' or response.headers.get('content-type','').split(';')[0].strip().lower()!='application/json':raise PermissionError()
            content=bytearray()
            for chunk in response.iter_bytes():
                if time.monotonic()-started>budget or len(content)+len(chunk)>131072:raise PermissionError()
                content.extend(chunk)
        value=_bounded_object(content,131072)
        if type(value) is not dict or value.get('ok') is not True or value.get('profile')!=profile:raise PermissionError()
        return value
    @app.get('/')
    def index():
        return Response((base/'index.html').read_bytes(),media_type='text/html',headers=headers)
    @app.get('/{asset}')
    def asset(asset:str):
        if asset not in ('sdk-v2.js','app-v2.js','styles-v2.css'):return result({'ok':False,'error':'unavailable'},404)
        return Response((base/asset).read_bytes(),media_type='application/javascript' if asset.endswith('.js') else 'text/css',headers=headers)
    @app.post('/bff/login')
    async def login(request:Request):
        try:
            same_origin(request)
            if await body(request)!={}:raise ValueError()
            verifier=secrets.token_urlsafe(32);state=secrets.token_urlsafe(32);flow=secrets.token_urlsafe(32)
            challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
            with lock:
                trim()
                if len(flows)>=100 or len(sessions)>=100:raise ValueError()
                flows[flow]={'state':state,'verifier':verifier,'expires':time.time()+300}
            url=GATEWAY+'/'+route_base+'/'+app_id+'/authorize?'+urlencode({'origin':app_origin,'redirect_uri':app_origin+'/bff/callback','challenge':challenge,'state':state})
            response=result({'ok':True,'authorization_url':url});response.set_cookie(FLOW_COOKIE,flow,max_age=300,httponly=True,secure=secure,samesite='lax',path='/bff');return response
        except (ValueError,TypeError,TimeoutError):return result({'ok':False,'error':'Sign-in could not be started.'},400)
    @app.get('/bff/callback')
    def callback(request:Request):
        pairs=list(request.query_params.multi_items());request.scope['query_string']=b''
        try:
            values=dict(pairs)
            if set(values)!= {'code','state'} or len(pairs)!=2:raise ValueError()
            with lock:
                trim();flow=flows.pop(request.cookies.get(FLOW_COOKIE,''),None)
            if not flow or not hmac.compare_digest(values['state'],flow['state']):raise PermissionError()
            value=gateway('POST','/exchange',data={'code':values['code'],'verifier':flow['verifier'],'redirect_uri':app_origin+'/bff/callback'})
            token=value['access_token']
            if type(token) is not str or not re.fullmatch('[A-Za-z0-9_-]{43}',token) or value.get('audience')!='app-run' or not time.time()<value['expires']<=time.time()+301:raise ValueError()
            raw=secrets.token_urlsafe(32)
            with lock:
                trim()
                if len(sessions)>=100:raise ValueError()
                sessions[raw]={'token':token,'expires':value['expires'],'csrf':secrets.token_urlsafe(32),'tickets':set(),'status':{}}
            response=RedirectResponse('/',status_code=303,headers=headers);response.set_cookie(COOKIE,raw,max_age=max(1,int(value['expires']-time.time())),httponly=True,secure=secure,samesite='strict',path='/');response.delete_cookie(FLOW_COOKIE,path='/bff',secure=secure,httponly=True,samesite='lax');return response
        except (ValueError,TypeError,KeyError,PermissionError,TimeoutError,httpx.HTTPError,httpx.StreamError):return result({'ok':False,'error':'The current customer sign-in could not be verified.'},403)
    @app.get('/bff/session')
    def current(request:Request):
        try:
            value=session(request);return result({'ok':True,'authenticated':True,'expires':value['expires'],'csrf_token':value['csrf']})
        except PermissionError:return result({'ok':True,'authenticated':False})
    @app.post('/bff/prepare')
    async def prepare(request:Request):
        try:
            value=session(request,True)
            if await body(request)!={}:raise ValueError()
            plan=gateway('POST','/prepare',token=value['token'],data={})
            if len(value['tickets'])>=20:raise ValueError()
            value['tickets'].add(plan['ticket_id']);return result(plan)
        except (ValueError,TypeError,KeyError,PermissionError,TimeoutError,httpx.HTTPError,httpx.StreamError):return result({'ok':False,'error':'A current customer session and approved deployment are required.'},403)
    @app.post('/bff/runs')
    async def run(request:Request):
        try:
            value=session(request,True);data=await body(request)
            if set(data)!={'ticket_id','authorized','notice'} or data['ticket_id'] not in value['tickets'] or data['authorized'] is not True or data['notice']!=run_notice:raise ValueError()
            response=gateway('POST','/runs',token=value['token'],data=data)
            capability=response['status_capability'];value['status'][response['run']['id']]=capability['access_token']
            return result({'ok':True,'profile':profile,'run':response['run']})
        except (ValueError,TypeError,KeyError,PermissionError,TimeoutError,httpx.HTTPError,httpx.StreamError):return result({'ok':False,'error':'Submission outcome is uncertain. Inspect history before another action.'},409)
    @app.get('/bff/history')
    def history(request:Request):
        try:
            value=session(request);return result(gateway('GET','/history',token=value['token']))
        except (PermissionError,ValueError,httpx.HTTPError,httpx.StreamError):return result({'ok':False,'error':'History is unavailable for this session.'},403)
    @app.post('/bff/status')
    async def status(request:Request):
        try:
            value=session(request,True);data=await body(request)
            if set(data)!={'run_id'} or type(data['run_id']) is not str or not re.fullmatch(('wtr_' if typed else 'wpr_')+'[0-9a-f]{32}',data['run_id']):raise ValueError()
            capability=value['status'].get(data['run_id'])
            if not capability:
                response=gateway('POST','/status-capability',token=value['token'],data=data);capability=response['access_token'];value['status'][data['run_id']]=capability
            return result(gateway('GET','/runs/'+data['run_id'],token=capability))
        except (PermissionError,ValueError,TypeError,KeyError,TimeoutError,httpx.HTTPError,httpx.StreamError):return result({'ok':False,'error':'That retained result is unavailable.'},403)
    @app.post('/bff/logout')
    async def logout(request:Request):
        try:
            session(request,True)
            if await body(request)!={}:raise ValueError()
            with lock:sessions.pop(request.cookies.get(COOKIE,''),None)
            response=result({'ok':True});response.delete_cookie(COOKIE,path='/',secure=secure,httponly=True,samesite='strict');return response
        except (PermissionError,ValueError):return result({'ok':False,'error':'The app session is unavailable.'},403)
    return app


if __name__=='__main__':
    import uvicorn
    directory=Path(__file__).parent
    configuration=json.loads((directory/'app-manifest.json').read_text())
    uvicorn.run(create_app(configuration,app_origin=os.environ['SDK2_ORIGIN'],root=directory),host='127.0.0.1',port=8080)
