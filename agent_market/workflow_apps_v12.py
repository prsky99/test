"""Opt-in fixed-input informational deployments with independent run consent.

Public configuration and tickets never contain a workflow graph or provider pin.
The existing public SDK and registered-app 1.1 protocol keep their own boundary.
"""
import asyncio
import base64
import copy
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time

from fastapi import APIRouter,Request
from fastapi.responses import JSONResponse,Response
from starlette.concurrency import run_in_threadpool

from .capability_registry import canonical,digest
from .workflow_apps import normalize_origins,service_for
from .workflow_deployment_consent import PROFILE,GRANT_NOTICE,SHARE_NOTICE,RUN_NOTICE
from .workflow_resolved_evidence import display_text
from .workflows import WorkflowError,public_template,public_outcome

EXPORT='workflow-app-v12-export-proposal-v1'
EXPORT_TTL=900
DEFAULTS={'minute_limit':10,'day_limit':500,'ttl_seconds':86400}


class WorkflowAppsV12:
    def __init__(self,runtime):
        self.runtime,self.store=runtime,runtime.store
        self.legacy=service_for(self.store,runtime)
        self.consent=runtime.deployment_consent

    def _owner(self,actor):
        owner=str(actor) if type(actor) is int else actor
        if not isinstance(owner,str) or not re.fullmatch(r'[1-9][0-9]{0,9}',owner):raise WorkflowError('A current highest administrator is required.')
        rows=self.store.query('SELECT active,role FROM admin_users WHERE id=?',(int(owner),))
        if len(rows)!=1 or not rows[0]['active'] or rows[0]['role']!='superadmin':raise WorkflowError('A current highest administrator is required.')
        return owner

    @staticmethod
    def _stamp(value):
        from .workflow_comparison import Comparison
        return Comparison.timestamp(value)

    @staticmethod
    def _definition_hash(workflow):
        return digest({key:workflow.get(key) for key in ('id','name','description','category','trigger_type','nodes','edges')})

    @staticmethod
    def _json_stamp(value):
        return int(value) if type(value) is float and value.is_integer() else value

    @staticmethod
    def _config(workflow):
        projected=public_template(workflow)
        if projected is None:raise WorkflowError('A safe active published definition is required.')
        return {'workflow_id':workflow['id'],'title':projected['name'],'description':projected['description'],'api_origin':'https://agentconcierge.biz'}

    @staticmethod
    def _recipients(workflow):
        recipients=[]
        for node in workflow['nodes']:
            if node.get('type')=='trigger':continue
            binding=node['data']['composition']['payload'];args=copy.deepcopy(binding['input'])
            if any(isinstance(value,str) and display_text(value)!=value for value in args.values()):raise WorkflowError('The reviewed input requires privacy minimization.')
            label='News search' if binding['contract']=='news.search.v1' else 'Documentation search'
            recipients.append({'label':label,'contract':binding['contract'],'input':args})
        return recipients

    def options(self,identity):
        try:
            workflow=self.consent.definition(identity);config=self._config(workflow)
            self._recipients(workflow);available=True
        except (ValueError,TypeError,KeyError):
            config={'workflow_id':identity,'title':'Informational workflow','description':''};available=False
        deployments=self.consent.list(identity)
        return {'ok':True,'profile':PROFILE,'workflow_id':identity,'available':available,
            'unavailable_reasons':[] if available else ['PUBLISHED_APPROVED_LITERAL_INFORMATIONAL_TEMPLATE_REQUIRED'],
            'config':config,'defaults':dict(DEFAULTS),'deployments':deployments,
            'notices':{'grant':GRANT_NOTICE,'share':SHARE_NOTICE,'run':RUN_NOTICE}}

    def prepare_admin(self,identity,body,actor):
        owner=self._owner(actor)
        if not isinstance(body,dict) or set(body)!={'allowed_origins','minute_limit','day_limit','ttl_seconds'}:raise WorkflowError('Review exact origins, limits and expiry.')
        origins=normalize_origins(body['allowed_origins'])
        minute,day,ttl=body['minute_limit'],body['day_limit'],body['ttl_seconds']
        if (not origins or type(minute) is not int or not 1<=minute<=30 or type(day) is not int or not 1<=day<=5000
                or type(ttl) is not int or not 300<=ttl<=86400):raise WorkflowError('Use bounded deployment origins, limits and expiry.')
        workflow=self.consent.definition(identity);config=self._config(workflow);recipients=self._recipients(workflow)
        created=self._json_stamp(time.time());expires=self._json_stamp(min(created+ttl,self.consent.expiry_limit(workflow)))
        if expires-created<300:raise WorkflowError('A fresh retained informational test is required for this deployment duration.')
        proposal={'audience':EXPORT,'profile':PROFILE,'workflow_id':identity,'owner':owner,'nonce':secrets.token_hex(16),
            'created':created,'expires':min(created+EXPORT_TTL,expires),'grant_expires':expires,'definition_hash':self._definition_hash(workflow),
            'allowed_origins':origins,'minute_limit':minute,'day_limit':day}
        return {'ok':True,'profile':PROFILE,'proposal':proposal,'signature':self.runtime.authority.signature(proposal),
            'preview':{**{k:config[k] for k in ('workflow_id','title','description')},'recipients':recipients,
                'allowed_origins':origins,'minute_limit':minute,'day_limit':day,'expires':expires},'executed':False,
            'notices':{'grant':GRANT_NOTICE,'share':SHARE_NOTICE,'run':RUN_NOTICE}}

    def _export_proposal(self,identity,body,owner):
        if (not isinstance(body,dict) or set(body)!={'proposal','signature','grant_authority','grant_notice'}
                or body['grant_authority'] is not True or body['grant_notice']!=GRANT_NOTICE):raise WorkflowError('Explicit deployment grant review is required.')
        try:
            p=body['proposal'];signature=body['signature']
            if (not isinstance(p,dict) or set(p)!={'audience','profile','workflow_id','owner','nonce','created','expires','grant_expires','definition_hash','allowed_origins','minute_limit','day_limit'}
                    or p['audience']!=EXPORT or p['profile']!=PROFILE or p['workflow_id']!=identity or p['owner']!=owner
                    or not isinstance(p['nonce'],str) or not re.fullmatch(r'[a-f0-9]{32}',p['nonce'])
                    or not isinstance(signature,str) or not hmac.compare_digest(signature,self.runtime.authority.signature(p))):raise ValueError()
            created=self._stamp(p['created']);expires=self._stamp(p['expires']);grant_expires=self._stamp(p['grant_expires']);now=time.time()
            controls=self.store.query('SELECT updated FROM execution_controls WHERE id=1')
            if (created>now+5 or expires!=min(created+EXPORT_TTL,grant_expires) or expires<=now
                    or not 300<=grant_expires-created<=86400 or len(controls)!=1 or self._stamp(controls[0]['updated'])>created
                    or normalize_origins(p['allowed_origins'])!=p['allowed_origins'] or not p['allowed_origins']
                    or type(p['minute_limit']) is not int or not 1<=p['minute_limit']<=30
                    or type(p['day_limit']) is not int or not 1<=p['day_limit']<=5000):raise ValueError()
            current=self.consent.definition(identity)
            if self._definition_hash(current)!=p['definition_hash']:raise ValueError()
            self._recipients(current)
            return p,current
        except (ValueError,TypeError,KeyError,OverflowError):raise WorkflowError('Review a new current deployment proposal.') from None

    def export_admin(self,identity,body,actor):
        owner=self._owner(actor);p,workflow=self._export_proposal(identity,body,owner)
        config=self._config(workflow);projection_hash=public_template(workflow)['definition_hash']
        app_id,key='app_'+secrets.token_hex(16),'wfpk_'+secrets.token_urlsafe(32)
        principal=self.runtime.principal('admin',owner,identity,role='superadmin')
        with self.store._lock:
            if self.store._db.in_transaction:raise WorkflowError('Deployment registration is temporarily unavailable.')
            with self.store.tx() as db:
                db.execute('BEGIN IMMEDIATE')
                # A nested catalog refresh may commit its caller's transaction.
                # Keep this row unusable until a signed grant has been stored.
                db.execute('INSERT INTO workflow_apps VALUES (?,?,?,?,?,?,?,?,0,?)',
                    (app_id,identity,hashlib.sha256(key.encode()).hexdigest(),projection_hash,
                     canonical(p['allowed_origins']),'[]',p['minute_limit'],p['day_limit'],time.time()))
                grant=self.consent.issue(db,app_id,workflow,principal,expires=p['grant_expires'],authority=True,notice=GRANT_NOTICE,reviewed_at=p['created'])
                signed=db.execute('SELECT 1 FROM workflow_deployment_grants WHERE app_id=? AND id=? AND revision=? AND active=1',
                    (app_id,grant['grant_id'],grant['revision'])).fetchone()
                if not signed:raise WorkflowError('The deployment grant could not be registered.')
                # No catalog, signing or other fallible validation follows this
                # activation. Failed issuance leaves only inactive orphan rows.
                db.execute('UPDATE workflow_apps SET active=1 WHERE id=? AND active=0',(app_id,))
        deployment={'app_id':app_id,'publish_key':key,'workflow_id':identity,'allowed_origins':p['allowed_origins'],
            'input_fields':[],'minute_limit':p['minute_limit'],'day_limit':p['day_limit'],'expires':grant['expires'],
            'profile':PROFILE,'sdk_version':'1.2.0','grant_id':grant['grant_id'],'revision':grant['revision']}
        return {'config':config,'deployment':deployment}

    def prepare_public(self,app,body,origin):
        if not isinstance(body,dict) or body:raise WorkflowError('This application uses only its fixed reviewed inputs.')
        result=self.consent.prepare(app['id'],origin)
        preview=copy.deepcopy(result['preview'])
        preview['recipients']=[{'label':row['alias'],'contract':row['contract'],'input':row['input']} for row in preview['recipients']]
        return {'ok':True,'profile':PROFILE,'proposal':result['ticket'],'signature':result['signature'],
            'preview':preview,'executed':False,'notices':{'share':SHARE_NOTICE,'run':RUN_NOTICE}}

    def deployments(self,identity):
        return {'ok':True,'profile':PROFILE,'deployments':self.consent.list(identity)}

    def revoke(self,identity,app_id,body,actor):
        self._owner(actor)
        if not isinstance(body,dict) or set(body)!={'revision'} or type(body['revision']) is not int:raise WorkflowError('Use the current deployment grant revision.')
        rows=self.store.query('SELECT workflow_id FROM workflow_apps WHERE id=?',(app_id,))
        if len(rows)!=1 or rows[0]['workflow_id']!=identity or not self.consent.is_v12(app_id):raise WorkflowError('The deployment grant is unavailable.')
        return {'ok':True,**self.consent.revoke(app_id,body['revision'])}

    def execute(self,app,body,origin,ip=None):
        if (not isinstance(body,dict) or set(body)!={'proposal','signature','share_authority','share_notice','live_authority','live_notice'}
                or body['share_authority'] is not True or body['share_notice']!=SHARE_NOTICE
                or body['live_authority'] is not True or body['live_notice']!=RUN_NOTICE):raise WorkflowError('Review the fixed inputs and authorize this one live execution.')
        current=self.consent.current(app['id'],origin=origin);workflow=current['workflow'];ticket=body['proposal']
        if not isinstance(ticket,dict) or not isinstance(ticket.get('nonce'),str) or not re.fullmatch(r'[a-f0-9]{32}',ticket['nonce']):raise WorkflowError('Review a new application execution request.')
        if not isinstance(body['signature'],str) or not hmac.compare_digest(body['signature'],self.runtime.authority.signature(ticket)):raise WorkflowError('The application execution request changed.')
        prior=self.store.query('SELECT id FROM workflow_runs WHERE actor=? AND idempotency_key=?',('webapp-v12:'+app['id'],ticket['nonce']))
        if not prior:self.legacy.quota(app,ip,'start')
        context={'ticket':ticket,'signature':body['signature'],'sharing_authority':True,'sharing_notice':SHARE_NOTICE,
            'run_authority':True,'run_notice':RUN_NOTICE,'origin':origin}
        principal=self.runtime.principal('deployment',app['id'],workflow['id'])
        arguments={'actor':'webapp-v12:'+app['id'],'source':'webapp','idempotency':ticket['nonce'],
            'principal':principal,'deployment_consent':context}
        try:job=self.runtime.submit(workflow,**arguments)
        except sqlite3.IntegrityError:job=self.runtime.submit(workflow,**arguments)
        raw=hmac.new(self.runtime.key,('workflow-app-v12-run-key-v1\0'+app['id']+'\0'+ticket['nonce']+'\0'+job['run_id']).encode(),hashlib.sha256).digest()
        key=base64.urlsafe_b64encode(raw).decode().rstrip('=');key_hash=hashlib.sha256(key.encode()).hexdigest()
        rows=self.store.query('SELECT created FROM workflow_runs WHERE id=?',(job['run_id'],))
        expires=min(rows[0]['created']+3600,current['grant']['expires'])
        with self.store.tx() as db:
            old=db.execute('SELECT app_id,key_hash,expires FROM workflow_app_runs WHERE run_id=?',(job['run_id'],)).fetchone()
            if old and (old['app_id']!=app['id'] or not hmac.compare_digest(old['key_hash'],key_hash) or old['expires']!=expires):raise WorkflowError('The retained application capability changed.')
            db.execute('INSERT OR IGNORE INTO workflow_app_runs VALUES (?,?,?,?)',(job['run_id'],app['id'],key_hash,expires))
        return {'ok':True,'profile':PROFILE,**job,'run_key':key}


def router_for(front):
    router=APIRouter(prefix='/api/workflow-apps-v12');service=WorkflowAppsV12(front.workflows)
    def headers():return {'Access-Control-Allow-Origin':'*','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}
    @router.options('/{app_id}/prepare')
    @router.options('/{app_id}/runs')
    @router.options('/{app_id}/runs/{run_id}')
    @router.options('/{app_id}/runs/{run_id}/cancel')
    def options(app_id:str,run_id:str=''):
        return Response(status_code=204,headers={**headers(),'Access-Control-Allow-Methods':'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers':'Content-Type, X-Publish-Key, X-Workflow-Key','Access-Control-Expose-Headers':'Retry-After','Access-Control-Max-Age':'600'})
    async def dispatch(app_id,request,operation,run_id=None):
        origin=request.headers.get('origin')
        try:
            reading=operation in ('status','cancel')
            app=service.legacy.authorize(app_id,request.headers.get('x-publish-key'),origin,read=reading)
            (service.consent.read_access if reading else service.consent.current)(app_id,origin=origin)
            if run_id:service.legacy.check_run(app,run_id,request.headers.get('x-workflow-key'))
            service.legacy.quota(app,front.security.resolve_ip(request),'prepare' if operation=='prepare' else 'cancel' if operation=='cancel' else 'poll')
        except (ValueError,TypeError,KeyError,sqlite3.DatabaseError) as exc:
            limited=isinstance(exc,WorkflowError) and 'rate limit' in str(exc)
            return JSONResponse({'error':'Deployment rate limit reached.' if limited else 'Deployment or run unavailable.'},status_code=429 if limited else 404,
                headers={**headers(),**({'Retry-After':'60','Access-Control-Expose-Headers':'Retry-After'} if limited else {})})
        try:
            if operation in ('prepare','run'):
                raw=bytearray()
                async with asyncio.timeout(10):
                    async for chunk in request.stream():
                        raw.extend(chunk)
                        if len(raw)>48000:raise ValueError()
                body=json.loads(raw,parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                if not isinstance(body,dict):raise ValueError()
                method=service.prepare_public if operation=='prepare' else service.execute
                arguments=(app,body,origin,front.security.resolve_ip(request)) if operation=='run' else (app,body,origin)
                result=await run_in_threadpool(method,*arguments)
            elif operation=='cancel':
                await run_in_threadpool(service.runtime.cancel,run_id);result={'ok':True,'cancel_requested':True}
            else:result=public_outcome(await run_in_threadpool(service.runtime.get,run_id))
        except (ValueError,TypeError,KeyError,UnicodeError,RecursionError,TimeoutError,sqlite3.DatabaseError) as exc:
            limited=isinstance(exc,WorkflowError) and 'rate limit' in str(exc)
            return JSONResponse({'error':'Deployment rate limit reached.' if limited else 'Review a new fixed-input application execution request.'},status_code=429 if limited else 400,
                headers={**headers(),**({'Retry-After':'60','Access-Control-Expose-Headers':'Retry-After'} if limited else {})})
        except Exception:
            return JSONResponse({'error':'The application request is temporarily unavailable.'},status_code=500,headers=headers())
        return JSONResponse(result,status_code=202 if operation=='run' else 200,headers=headers())
    @router.post('/{app_id}/prepare')
    async def prepare(app_id:str,request:Request):return await dispatch(app_id,request,'prepare')
    @router.post('/{app_id}/runs')
    async def run(app_id:str,request:Request):return await dispatch(app_id,request,'run')
    @router.get('/{app_id}/runs/{run_id}')
    async def status(app_id:str,run_id:str,request:Request):return await dispatch(app_id,request,'status',run_id)
    @router.post('/{app_id}/runs/{run_id}/cancel')
    async def cancel(app_id:str,run_id:str,request:Request):return await dispatch(app_id,request,'cancel',run_id)
    return router
