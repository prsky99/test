"""Shared, bounded workflow execution and explicit public-data boundaries."""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import logging
import re
import secrets
import sqlite3
import threading
import time
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .concierge.recommendation_security import public_data, secret_name
from .concierge.execution_errors import fields as failure_fields, policy_code, reference, record_failure
from .observability import journal_for, stable_reference, attempt_scope, provider_dispatch
from .workflow_persistence import DurableRuns, FenceLost, dispatch_scope

TERMINAL = {'succeeded','failed','cancelled'}
MAX_SECONDS = 25
MAX_OUTPUT = 48000
_POOL = ThreadPoolExecutor(max_workers=4,thread_name_prefix='workflow')
_SLOTS = threading.BoundedSemaphore(12)
_REF = re.compile(r"\{\{\s*\$(?:node\[['\"]([^'\"]+)['\"]\]|(prev))\.(output|id)(?:\.([a-zA-Z0-9_.-]+))?\s*\}\}")
_HANGUL = re.compile(r'[\uac00-\ud7a3]')
SCHEMA = '''
CREATE TABLE IF NOT EXISTS workflow_versions (
 workflow_id INTEGER NOT NULL, digest TEXT NOT NULL, snapshot TEXT NOT NULL, created REAL NOT NULL,
 PRIMARY KEY(workflow_id,digest));
CREATE TABLE IF NOT EXISTS workflow_runs (
 id TEXT PRIMARY KEY,workflow_id INTEGER NOT NULL,digest TEXT NOT NULL,snapshot TEXT NOT NULL,
 actor TEXT NOT NULL,source TEXT NOT NULL,status TEXT NOT NULL,created REAL NOT NULL,
 started REAL,finished REAL,cancel_requested INTEGER NOT NULL DEFAULT 0,
 access_hash TEXT,idempotency_key TEXT,result TEXT,error TEXT,
 UNIQUE(actor,idempotency_key));
CREATE INDEX IF NOT EXISTS workflow_runs_recent ON workflow_runs(workflow_id,created DESC);
CREATE INDEX IF NOT EXISTS workflow_admin_runs_recent ON workflow_runs(source,created DESC);
CREATE TABLE IF NOT EXISTS workflow_node_runs (
 run_id TEXT NOT NULL,node_id TEXT NOT NULL,status TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,
 started REAL,finished REAL,input TEXT,output TEXT,error TEXT,latency_ms REAL NOT NULL DEFAULT 0,
 PRIMARY KEY(run_id,node_id));
CREATE TABLE IF NOT EXISTS workflow_schedules (
 workflow_id INTEGER PRIMARY KEY,mode TEXT NOT NULL,preset TEXT NOT NULL,timezone TEXT NOT NULL,
 enabled INTEGER NOT NULL DEFAULT 0,next_run REAL,last_run REAL,destination_id TEXT,
 event_hash TEXT,event_sealed TEXT,updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS workflow_event_receipts (
 workflow_id INTEGER NOT NULL,event_id TEXT NOT NULL,created REAL NOT NULL,
 PRIMARY KEY(workflow_id,event_id));
CREATE TABLE IF NOT EXISTS workflow_destinations (
 id TEXT PRIMARY KEY,workflow_id INTEGER NOT NULL,channel TEXT NOT NULL,sealed TEXT,
 state TEXT NOT NULL,code_hash TEXT,expires REAL NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,
 confirmed REAL,created REAL NOT NULL,notice TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS workflow_deliveries (
 id TEXT PRIMARY KEY,run_id TEXT NOT NULL,destination_id TEXT NOT NULL,status TEXT NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL,finished REAL,error TEXT,
 UNIQUE(run_id,destination_id));
'''


class WorkflowError(ValueError):
    def __init__(self,message,*,error_code=None,definitive=False):
        super().__init__(message)
        self.error_code=failure_fields(error_code)['error_code'] if error_code else policy_code(message)
        self.definitive=definitive


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False)


def clean(value):
    return public_data(value)


def text(value, limit=MAX_OUTPUT):
    return str(clean(value))[:limit] if not isinstance(value,(dict,list)) else canonical(clean(value))[:limit]


def sensitive(value,depth=0):
    if depth>20:
        return True
    if isinstance(value,dict):
        return any((secret_name(k) and v not in (None,'','[REDACTED]')) or
                   k in ('credential_refs','headers','subscription','signing_secret') and bool(v) or
                   sensitive(v,depth+1) for k,v in value.items())
    if isinstance(value,list):
        return any(sensitive(v,depth+1) for v in value)
    if isinstance(value,str):
        return bool(re.search(r'(?i)\b(?:Bearer|Basic)\s+\S+|\bvt_[A-Za-z0-9_-]+|/Users/|/home/|[A-Z]:\\',value))
    return False


def graph(workflow):
    nodes,edges=workflow.get('nodes',[]),workflow.get('edges',[])
    if not isinstance(nodes,list) or not nodes or len(nodes)>100 or not isinstance(edges,list) or len(edges)>500:
        raise WorkflowError('A workflow needs 1 to 100 nodes and at most 500 edges.')
    by_id={};incoming={};outgoing={}
    for node in nodes:
        if not isinstance(node,dict) or not isinstance(node.get('id'),str) or not 1<=len(node['id'])<=128:
            raise WorkflowError('Each node needs a unique ID.')
        nid=node['id']
        if nid in by_id or not isinstance(node.get('data',{}),dict):
            raise WorkflowError('Duplicate node ID or invalid node data.')
        if node.get('type','agent') not in ('trigger','agent','router','input_transform','output_transform') or not isinstance(node.get('name',''),str):
            raise WorkflowError('Invalid node type or name.')
        if node.get('type') in ('input_transform','output_transform'):
            from .workflow_transforms import review
            try:review(node.get('data',{}).get('transform'))
            except ValueError:raise WorkflowError('Provide a supported input/output transformation recipe.') from None
        if len(node.get('name',''))>500:raise WorkflowError('Node name exceeds the limit.')
        by_id[nid]=node;incoming[nid]=[];outgoing[nid]=[]
    seen=set()
    for edge in edges:
        if not isinstance(edge,dict) or edge.get('source') not in by_id or edge.get('target') not in by_id:
            raise WorkflowError('An edge references an unknown node.')
        if edge.get('condition',True) not in (True,False,'true','false','True','False'):
            raise WorkflowError('Use a true or false branch condition.')
        pair=(edge['source'],edge['target'])
        if pair in seen:
            raise WorkflowError('Duplicate edges are not supported.')
        seen.add(pair);incoming[pair[1]].append(edge);outgoing[pair[0]].append(edge)
    degree={nid:len(incoming[nid]) for nid in by_id}
    queue=[nid for nid in by_id if not degree[nid]];order=[]
    while queue:
        nid=queue.pop(0);order.append(nid)
        for edge in outgoing[nid]:
            degree[edge['target']]-=1
            if not degree[edge['target']]:queue.append(edge['target'])
    if len(order)!=len(nodes):
        raise WorkflowError('Workflow cycles are not allowed.')
    return by_id,incoming,order


def public_template(workflow,runtime=None):
    if runtime is not None and runtime.products.known(workflow['id']):
        return runtime.products.projection(workflow)
    # New mappings remain private until their publication/consent projection is reviewed.
    if any(n.get('type') in ('input_transform','output_transform') or n.get('data',{}).get('io_profile') for n in workflow.get('nodes',[])):return None
    from .workflow_public_flow import is_flow
    if is_flow(workflow):return None
    from .workflow_typed_flow import connected
    if any(connected(n) for n in workflow.get('nodes',[])):return None
    if not workflow.get('is_active') or not workflow.get('is_template'):
        return None
    name=str(workflow.get('name','')).strip()
    tags=str(workflow.get('tags',''))
    if name.startswith('[') or name.lower().startswith('test') or 'test' in [x.strip().lower() for x in tags.split(',')]:
        return None
    try:graph(workflow)
    except WorkflowError:return None
    # Published graphs are allowlisted definitions, never a dump of stored columns.
    if sensitive(workflow.get('nodes',[])):
        return None
    def english(value,fallback=''):
        value=str(clean(value or ''))
        return fallback if _HANGUL.search(value) else value[:1600]
    result={k:workflow.get(k) for k in ('id','category','trigger_type','is_active','is_template','parent_workflow_id')}
    result.update(name=english(name,'Agent Workflow'),description=english(workflow.get('description')),
                  tags=english(tags),author='Community',nodes=[],edges=[])
    for node in workflow.get('nodes',[]):
        data=node.get('data',{})
        projected={k:clean(node[k]) for k in ('id','type','kind','resource_id','position','disabled','is_active') if k in node}
        projected.update(name=english(node.get('name'),'Agent Step'),data={
            k:clean(data[k]) for k in ('action','tool','input','condition','trigger_type','resource_id','output_select','disabled','is_active') if k in data})
        result['nodes'].append(projected)
    result['edges']=[{k:e[k] for k in ('id','source','target','condition','label') if k in e} for e in workflow.get('edges',[])]
    result['steps']=[{'name':n['name'],'kind':n.get('kind'),**n['data']} for n in result['nodes'] if n.get('type')!='trigger']
    result['definition_hash']=hashlib.sha256(canonical(result['nodes']+result['edges']).encode()).hexdigest()
    return result


def project_output(value,spec):
    if spec is None:return value
    if not isinstance(spec,dict):raise WorkflowError('Invalid output selection.')
    def get(item,path):
        if not isinstance(path,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,200}',path):raise WorkflowError('Invalid output field path.')
        for part in path.split('.'):
            if isinstance(item,dict) and part in item:item=item[part]
            elif isinstance(item,list) and part.isdigit() and int(part)<len(item):item=item[int(part)]
            else:raise WorkflowError('The agent response is missing a required output field.')
        return item
    selected=get(value,spec.get('path',''))
    maximum=spec.get('max_text',8000);limit=spec.get('limit',3)
    if type(maximum) is not int or not 100<=maximum<=16000 or type(limit) is not int or not 1<=limit<=10:
        raise WorkflowError('Invalid output selection limit.')
    if isinstance(selected,str):return {'text':selected[:maximum],'truncated':len(selected)>maximum}
    fields=spec.get('fields')
    if not isinstance(selected,list) or not isinstance(fields,dict) or not 1<=len(fields)<=12:
        raise WorkflowError('Output selection requires a list and explicit fields.')
    items=[];truncated=False
    for item in selected[:limit]:
        row={}
        for name,path in fields.items():
            field=get(item,path)
            if isinstance(field,str) and len(field)>maximum:field=field[:maximum];truncated=True
            row[name]=field
        items.append(row)
    return {'items':items,'truncated':truncated or len(selected)>limit}


def public_outcome(result):
    def scrub(value):
        if isinstance(value,dict):return {k:scrub(v) for k,v in value.items() if k not in ('input','run_key','final_deliverable')}
        if isinstance(value,list):return [scrub(v) for v in value]
        if isinstance(value,str):
            value=str(clean(value))
            value=re.sub(r'(?i)(?:/Users/|/home/|/private/|/var/)[^\s"<>]+|[A-Z]:\\[^\s"<>]+','[REDACTED]',value)
            value=re.sub(r'(?i)[a-z0-9.+_-]+@([a-z0-9.-]+\.[a-z]{2,})',lambda m:m[0] if m[1].lower()=='agentconcierge.biz' else '[REDACTED]',value)
            if 'Traceback (most recent call last)' in value:return 'The agent returned content that cannot be displayed.'
        return value
    return scrub(result)


def next_due(preset,zone,now=None):
    try:tz=ZoneInfo(zone)
    except (ZoneInfoNotFoundError,ValueError,TypeError):raise WorkflowError('Choose a valid IANA time zone.')
    current=datetime.fromtimestamp(time.time() if now is None else now,timezone.utc)
    local=current.astimezone(tz)
    if preset=='hourly':target=(current+timedelta(hours=1)).astimezone(tz).replace(minute=0,second=0,microsecond=0)
    elif preset=='every_6h':return current.timestamp()+6*3600
    elif preset in ('daily_0900','weekly_mon_0900'):
        target=local.replace(hour=9,minute=0,second=0,microsecond=0)
        if preset=='weekly_mon_0900':target+=timedelta(days=(0-local.weekday())%7)
        if target<=local:target+=timedelta(days=7 if preset=='weekly_mon_0900' else 1)
    else:raise WorkflowError('Choose a supported schedule preset.')
    return max(current.timestamp()+1,target.timestamp())


class WorkflowRuntime:
    def __init__(self,store,proxy=None,courier=None):
        self.store,self.proxy,self.courier=store,proxy,courier
        self.journal=journal_for(store)
        self.lock=threading.RLock();self.destination_lock=threading.RLock();self.futures={};self.worker_seen=0;self.instance=secrets.token_hex(16)
        from .concierge.task_updates import TaskUpdates
        self.key=hmac.new(TaskUpdates._load_key(self),b'workflow-results-v1',hashlib.sha256).digest()
        from .execution_authority import Authority
        self.authority=Authority(store,self.key)
        with store._lock:
            store._db.executescript(SCHEMA)
            columns={r[1] for r in store._db.execute('PRAGMA table_info(workflow_runs)')}
            for column,declaration in (('lease_until','REAL NOT NULL DEFAULT 0'),('owner','TEXT')):
                if column in columns:continue
                try:store._db.execute(f'ALTER TABLE workflow_runs ADD COLUMN {column} {declaration}')
                except sqlite3.OperationalError:
                    if column not in {r[1] for r in store._db.execute('PRAGMA table_info(workflow_runs)')}:raise
        store._workflow_runtime=self
        self.persistence=DurableRuns(store)
        from .workflow_io_profiles import IOProfiles
        self.io_profiles=IOProfiles(self)
        from .workflow_fallback import FallbackRouter
        self.fallback=FallbackRouter(self)
        from .workflow_products import Products
        self.products=Products(self)
        from .workflow_budgets import Budgets
        self.budgets=Budgets(self)
        from .workflow_operations import Operations
        self.operations=Operations(self)
        from .workflow_maintenance import Maintenance
        self.maintenance=Maintenance(self)
        from .workflow_composer import Composer
        self.composer=Composer(self)
        from .workflow_deployment_consent import DeploymentConsent
        self.deployment_consent=DeploymentConsent(self)
        from .workflow_publication import Publication
        self.publication=Publication(self)
        from .workflow_connection_deployment import ConnectionDeployments
        self.connection_deployments=ConnectionDeployments(self)
        from .workflow_connection_automation import ConnectionAutomation
        self.automation=ConnectionAutomation(self)
        self.persistence.recover()
        self.operations.recover()

    def snapshot(self,workflow,product_context=None):
        graph(workflow)
        snapshot={k:workflow.get(k) for k in ('id','name','description','category','trigger_type','nodes','edges')}
        snapshot['bindings']={}
        for node in snapshot['nodes']:
            if node.get('type') in ('trigger','router','input_transform','output_transform'):continue
            rid=node.get('resource_id') or node.get('data',{}).get('resource_id')
            resource=self.store.resource(rid) if type(rid) is int and 0<rid<2**31 else None
            if resource:
                from .capability_registry import Registry
                version=Registry(self.store).current(resource)
                snapshot['bindings'][node['id']]={**{k:resource.get(k) for k in ('id','kind','usage_tools_hash')},'url_hash':hashlib.sha256(resource['url'].encode()).hexdigest(),
                    **({'connection_version_id':version['id']} if version else {})}
        routing=self.fallback.fingerprint(workflow['id'])
        if routing:snapshot['fallback_policy_fingerprint']=routing
        if product_context is not None:snapshot['product_context']=product_context
        raw=canonical(snapshot)
        if len(raw.encode())>180000:raise WorkflowError('Workflow definition exceeds the size limit.')
        digest=hashlib.sha256(raw.encode()).hexdigest()
        with self.store.tx() as db:
            db.execute('INSERT OR IGNORE INTO workflow_versions VALUES (?,?,?,?)',(workflow['id'],digest,raw,time.time()))
        return snapshot,digest

    def principal(self,kind,subject,workflow_id,*,role='operator'):
        return self.authority.principal(kind,subject,workflow_id,role=role)

    def submit(self,workflow,actor='admin',source='admin',idempotency=None,public=False,principal=None,allow_fallback=False,fallback_notice=None,execution_profile='standard',execution_budget_notice=None,pair_authority=False,pair_notice=None,deployment_consent=None,publication_context=None,connection_deployment=None,connection_automation=None,product_input=None,product_drill=None):
        from . import workflow_paired_flow as paired_flow
        paired=paired_flow.is_pair(workflow)
        if type(pair_authority) is not bool or paired and (execution_profile!='standard' or allow_fallback):
            raise WorkflowError('Controlled pairs require an explicit standard private test without fallback.',error_code='POLICY_DENIED')
        from .workflow_budgets import NOTICE as BUDGET_NOTICE
        if execution_profile!='standard' and (execution_profile!='extended' or public or source!='admin' or execution_budget_notice!=BUDGET_NOTICE):
            raise WorkflowError('Extended execution requires explicit private administrator authorization.',error_code='POLICY_DENIED')
        from .workflow_fallback import NOTICE
        if type(allow_fallback) is not bool or allow_fallback and (fallback_notice!=NOTICE or source not in ('admin','public')):
            raise WorkflowError('Explicit informational sharing consent is required.',error_code='POLICY_DENIED')
        from .execution_authority import require_enabled
        try:require_enabled(self.store,'workflow')
        except ValueError as exc:raise WorkflowError(str(exc),error_code='POLICY_DENIED') from None
        if public:source='public'
        if source not in ('admin','public','schedule','event','webapp','verification'):raise WorkflowError('Unsupported execution source.')
        from .workflow_typed_flow import connected, definition as typed_definition
        from . import workflow_public_flow as public_flow
        public_connection=public_flow.is_flow(workflow)
        if public_connection and source not in ('admin','public'):
            raise WorkflowError('Canonical public connections require their separate manual test or publication purpose.',error_code='POLICY_DENIED')
        linked=[n for n in workflow.get('nodes',[]) if connected(n)]
        if linked and source!='admin' and not public_connection:
            raise WorkflowError('Connected drafts require a private highest-administrator test.',error_code='POLICY_DENIED')
        kind='deployment' if source=='webapp' else source
        subject=actor.removeprefix('webapp:') if source=='webapp' else str(workflow['id']) if source in ('schedule','event') else 'public' if source=='public' else 'internal'
        principal=principal or self.principal(kind,subject,workflow['id'],role='superadmin' if source=='admin' else 'operator')
        try:claims=self.authority.validate(principal,workflow['id'],source)
        except ValueError as exc:raise WorkflowError(str(exc),error_code='POLICY_DENIED') from None
        if linked and not public_connection:
            if source!='admin' or claims['kind']!='admin' or claims['role']!='superadmin':
                raise WorkflowError('Connected drafts require a private highest-administrator test.',error_code='POLICY_DENIED')
            try:
                for node in linked:typed_definition(self.composer,node,workflow)
            except (ValueError,KeyError,TypeError) as exc:
                raise WorkflowError('The reviewed input connection is not authorized.',error_code='POLICY_DENIED') from exc
        if any(n.get('data',{}).get('credential_refs') for n in workflow.get('nodes',[])) and (claims['kind']!='admin' or claims['role']!='superadmin'):
            raise WorkflowError('This execution cannot use platform credentials.',error_code='POLICY_DENIED')
        if not workflow.get('is_active'):
            raise WorkflowError('This workflow is inactive.')
        if source in ('schedule','event') and any(n.get('data',{}).get('credential_refs') for n in workflow.get('nodes',[])):
            raise WorkflowError('Automatic runs cannot use platform credential bindings.')
        try:product_context=self.products.prepare(workflow,claims,source,product_input,product_drill)
        except (ValueError,KeyError,TypeError):raise WorkflowError('The declared product input or review authority is invalid.',error_code='POLICY_DENIED') from None
        snapshot,digest=self.snapshot(workflow,product_context)
        try:
            automation_scope=self.automation.admit(snapshot,claims,connection_automation,source=source,profile=execution_profile,fallback=allow_fallback,public=public)
            connection_scope=self.connection_deployments.admit(snapshot,claims,connection_deployment,source=source,profile=execution_profile,fallback=allow_fallback)
            if automation_scope:
                if connection_scope or publication_context is not None or actor!='automation:'+automation_scope['ticket']['grant_id'] or idempotency!=automation_scope['ticket']['nonce']:
                    raise ValueError('Use the exact independent automation actor and slot.')
                publication_scope=None
            elif connection_scope:
                if publication_context is not None or actor!='connection-app:'+claims['subject'] or idempotency!=connection_scope['proposal']['nonce']:
                    raise ValueError('Use the exact independent connected-deployment purpose and nonce.')
                publication_scope=None
            else:
                publication_scope=self.publication.admit(snapshot,claims,publication_context,source=source,profile=execution_profile,fallback=allow_fallback)
            if publication_scope:
                expected_actor=('publication-test:'+publication_scope['owner']) if publication_scope['mode']=='test' else 'public-flow:'+publication_scope['proposal']['release_id']
                expected_nonce=publication_scope['nonce'] if publication_scope['mode']=='test' else publication_scope['proposal']['nonce']
                if actor!=expected_actor or idempotency!=expected_nonce:raise ValueError('Use the exact canonical run nonce and actor.')
        except (ValueError,TypeError,KeyError,AttributeError) as exc:raise WorkflowError('The canonical connection authorization is unavailable.',error_code='POLICY_DENIED') from None
        try:pair_scope=paired_flow.admit(self,snapshot,claims,pair_authority,pair_notice)
        except ValueError as exc:raise WorkflowError(str(exc),error_code='POLICY_DENIED') from None
        try:
            deployment_scope=self.deployment_consent.admit(snapshot,claims,deployment_consent,source=source,profile=execution_profile,fallback=allow_fallback)
            if deployment_scope and (actor!='webapp-v12:'+claims['subject'] or idempotency!=deployment_scope['ticket']['nonce']):
                raise ValueError('Use the exact deployment run ticket idempotency scope.')
        except (ValueError,KeyError,TypeError,AttributeError) as exc:raise WorkflowError('The deployment run authorization is unavailable.',error_code='POLICY_DENIED') from None
        if pair_scope:
            principal=copy.deepcopy(principal)
            principal['payload']['controlled_pair']=pair_scope
            principal['signature']=self.authority.signature(principal['payload'])
        if deployment_scope:
            principal=copy.deepcopy(principal)
            principal['payload']['deployment_consent']=deployment_scope
            principal['payload']['expires']=min(principal['payload']['expires'],deployment_scope['ticket']['expires'])
            principal['signature']=self.authority.signature(principal['payload'])
        if publication_scope:
            principal=copy.deepcopy(principal)
            principal['payload']['public_connection']=publication_scope
            principal['payload']['expires']=min(principal['payload']['expires'],publication_scope['proposal']['expires'] if publication_scope['mode']=='public' else publication_scope['expires'])
            principal['signature']=self.authority.signature(principal['payload'])
        if connection_scope:
            principal=copy.deepcopy(principal)
            principal['payload']['connection_deployment']=connection_scope
            principal['payload']['expires']=min(principal['payload']['expires'],connection_scope['proposal']['expires'])
            principal['signature']=self.authority.signature(principal['payload'])
        if automation_scope:
            principal=copy.deepcopy(principal)
            principal['payload']['connection_automation']=automation_scope
            principal['payload']['expires']=min(principal['payload']['expires'],automation_scope['ticket']['expires'])
            principal['signature']=self.authority.signature(principal['payload'])
        if len(canonical(snapshot))>180000:
            raise WorkflowError('Workflow definition exceeds the size limit.')
        if public and idempotency is not None and not publication_scope and not connection_scope:
            raise WorkflowError('Public runs do not accept idempotency keys.')
        if idempotency is not None and (not isinstance(idempotency,str) or not 1<=len(idempotency)<=128):
            raise WorkflowError('Invalid idempotency key.')
        run_id='wr_'+secrets.token_hex(16);key=secrets.token_urlsafe(32) if public else None
        if publication_scope and publication_scope['mode']=='public':key=self.publication.run_key({'id':run_id},publication_scope)
        if connection_scope:key=self.connection_deployments.run_key({'id':run_id},connection_scope)
        with self.lock,self.store.tx() as db:
            if automation_scope:db.execute('BEGIN IMMEDIATE')
            if idempotency:
                old=db.execute('SELECT id FROM workflow_runs WHERE actor=? AND idempotency_key=?',(actor,idempotency)).fetchone()
                if old:
                    prior=self.store.query('SELECT workflow_id,digest FROM workflow_runs WHERE id=?',(old['id'],))[0]
                    if prior['workflow_id']!=workflow['id'] or prior['digest']!=digest:raise WorkflowError('Idempotency key belongs to another definition.')
                    plan=self.fallback.plan(dict(self.store.query('SELECT * FROM workflow_runs WHERE id=?',(old['id'],))[0]))
                    if type(allow_fallback) is not bool or (plan or {}).get('opt_in',False)!=allow_fallback:raise WorkflowError('Idempotency key belongs to another sharing authorization.')
                    prior_run=dict(self.store.query('SELECT * FROM workflow_runs WHERE id=?',(old['id'],))[0])
                    if self.budgets.get(prior_run)['profile']!=execution_profile:raise WorkflowError('Idempotency key belongs to another execution profile.')
                    if pair_scope:
                        try:paired_flow.replay_scope(self,prior_run,pair_scope)
                        except ValueError as exc:raise WorkflowError(str(exc),error_code='POLICY_DENIED') from None
                    if deployment_scope:
                        try:self.deployment_consent.replay_scope(prior_run,deployment_scope)
                        except ValueError as exc:raise WorkflowError('The deployment replay authority changed.',error_code='POLICY_DENIED') from None
                    if automation_scope:
                        try:self.automation.replay_scope(prior_run,automation_scope)
                        except (ValueError,KeyError,TypeError):raise WorkflowError('The automation replay purpose changed.',error_code='POLICY_DENIED') from None
                        return {'run_id':old['id'],'status':self.get(old['id'])['status'],'replayed':True}
                    if publication_scope:
                        try:self.publication.replay_scope(prior_run,publication_scope)
                        except (ValueError,KeyError,TypeError) as exc:raise WorkflowError('The canonical replay purpose changed.',error_code='POLICY_DENIED') from None
                        return {'run_id':old['id'],'status':self.get(old['id'])['status'],'replayed':True,**({'run_key':self.publication.run_key(prior_run,publication_scope)} if publication_scope['mode']=='public' else {})}
                    if connection_scope:
                        try:self.connection_deployments.replay_scope(prior_run,connection_scope)
                        except (ValueError,KeyError,TypeError) as exc:raise WorkflowError('The connected-deployment replay purpose changed.',error_code='POLICY_DENIED') from None
                        return {'run_id':old['id'],'status':self.get(old['id'])['status'],'replayed':True,'run_key':self.connection_deployments.run_key(prior_run,connection_scope)}
                    return {'run_id':old['id'],'status':self.get(old['id'])['status'],'replayed':True}
            if db.execute("SELECT COUNT(*) FROM workflow_runs WHERE status IN ('queued','running')").fetchone()[0]>=12:
                raise WorkflowError('Workflow execution is busy. Please try again.')
            db.execute('INSERT INTO workflow_runs (id,workflow_id,digest,snapshot,actor,source,status,created,access_hash,idempotency_key) VALUES (?,?,?,?,?,?,\'queued\',?,?,?)',
                (run_id,workflow['id'],digest,canonical(snapshot),actor,source,time.time(),hashlib.sha256(key.encode()).hexdigest() if key and not publication_scope and not connection_scope else None,idempotency))
            if automation_scope:
                try:self.automation.commit(db,run_id,automation_scope)
                except (ValueError,KeyError,TypeError):raise WorkflowError('Automation admission is unavailable; inspect its history.',error_code='POLICY_DENIED') from None
            grant=None if paired or deployment_scope or publication_scope or connection_scope or automation_scope else self.authority.choose(workflow['id'],digest,source,claims)
            self.authority.save_run(db,run_id,workflow['id'],digest,source,principal,grant)
            try:self.fallback.admit(db,run_id,workflow,digest,source,allow_fallback,fallback_notice)
            except ValueError as exc:raise WorkflowError(str(exc),error_code='POLICY_DENIED') from None
            try:self.budgets.admit(db,run_id,digest,source,claims,execution_profile,execution_budget_notice)
            except ValueError as exc:raise WorkflowError(str(exc),error_code='POLICY_DENIED') from None
            for n in snapshot['nodes']:
                db.execute('INSERT INTO workflow_node_runs (run_id,node_id,status) VALUES (?,?,?)',(run_id,n['id'],'queued'))
        observation=self.journal.begin('workflow','workflow_automation' if automation_scope else 'workflow_deployment' if source=='webapp' else 'workflow_'+source,
                                       identity=stable_reference('workflow',run_id),workflow_id=workflow['id'])
        observation.finish('pending')
        self.launch(run_id)
        return {'run_id':run_id,'status':'queued',**({'run_key':key} if key else {})}

    def launch(self,run_id):
        # Split web processes admit persisted runs; only the execution service
        # consumes them. Legacy embedded operation keeps its existing behavior.
        if getattr(self.store, '_service_role', 'legacy') in ('frontend', 'admin', 'jobs'):
            return
        with self.lock:
            if run_id in self.futures or not _SLOTS.acquire(blocking=False):return
            future=_POOL.submit(self._execute,run_id);self.futures[run_id]=future
            def done(_):
                _SLOTS.release()
                with self.lock:self.futures.pop(run_id,None)
            future.add_done_callback(done)

    def authorized(self,run_id,key):
        rows=self.store.query('SELECT access_hash FROM workflow_runs WHERE id=?',(run_id,))
        return bool(rows and rows[0]['access_hash'] and isinstance(key,str) and len(key)<=100 and hmac.compare_digest(rows[0]['access_hash'],hashlib.sha256(key.encode()).hexdigest()))

    def cancel(self,run_id):
        with self.store.tx() as db:
            if not db.execute('SELECT 1 FROM workflow_runs WHERE id=?',(run_id,)).fetchone():raise WorkflowError('Run not found.')
            db.execute("UPDATE workflow_runs SET cancel_requested=1 WHERE id=? AND status IN ('queued','running')",(run_id,))
        return self.get(run_id)

    def get(self,run_id):
        from .edge_gateway.result_transport import note_parent
        note_parent(run_id)
        rows=self.store.query('SELECT * FROM workflow_runs WHERE id=?',(run_id,))
        if not rows:raise WorkflowError('Run not found.')
        r=dict(rows[0]);snapshot=json.loads(r['snapshot'])
        if r['status']=='running' and (r['lease_until']<=time.time() or r.get('deadline') is not None and r['deadline']<=time.time()):
            self.persistence.recover();return self.get(run_id)
        if r['status']=='queued':self.launch(run_id)
        if r['result']:return json.loads(r['result'])
        stored={n['node_id']:dict(n) for n in self.store.query('SELECT * FROM workflow_node_runs WHERE run_id=?',(run_id,))}
        nodes=[]
        for n in snapshot['nodes']:
            row=stored.get(n['id'],{'node_id':n['id'],'status':'queued'})
            nodes.append({**row,'name':n.get('name',n['id']),'type':n.get('type','agent')})
        return {'ok':r['status']!='failed','run_id':run_id,'workflow_id':r['workflow_id'],'workflow_name':snapshot['name'],
                'status':r['status'],'execution_outcome':r.get('execution_outcome'),'created_at':r['created'],'node_results':nodes,'error':r['error']}

    def history(self,workflow_id,limit=50):
        return [dict(r) for r in self.store.query('''SELECT id,workflow_id,digest,source,status,execution_outcome,created,started,finished,error
            FROM workflow_runs WHERE workflow_id=? ORDER BY created DESC LIMIT ?''',(workflow_id,limit))]

    def metrics(self,items):
        runs={r['workflow_id']:dict(r) for r in self.store.query("SELECT workflow_id,COUNT(*) total,SUM(status='succeeded') succeeded FROM workflow_runs GROUP BY workflow_id")}
        ratings={r['workflow_id']:dict(r) for r in self.store.query('SELECT workflow_id,AVG(rating) rating,SUM(CASE WHEN rating>=4 THEN 1 ELSE 0 END) likes FROM workflow_reviews GROUP BY workflow_id')}
        forks={r['parent_workflow_id']:r['n'] for r in self.store.query('SELECT parent_workflow_id,COUNT(*) n FROM agent_workflows WHERE parent_workflow_id IS NOT NULL GROUP BY parent_workflow_id')}
        for item in items:
            item['legacy_runs_count']=item.get('runs_count',0)
            item['runs_count']=runs.get(item['id'],{}).get('total',0)
            item['verified_runs_count']=runs.get(item['id'],{}).get('succeeded',0)
            item['rating_avg']=ratings.get(item['id'],{}).get('rating',0) or 0
            item['forks_count']=forks.get(item['id'],0)
            item['likes_count']=ratings.get(item['id'],{}).get('likes',0) or 0
        return items

    def _cancelled(self,run_id):
        rows=self.store.query('SELECT cancel_requested FROM workflow_runs WHERE id=?',(run_id,))
        return not rows or bool(rows[0]['cancel_requested'])

    def _resolve(self,value,outputs,allowed,parents,names):
        def reference(match):
            nid=match[1] or (parents[0] if match[2] and len(parents)==1 else '')
            nid=nid if nid in allowed else names.get(nid,nid)
            if nid not in allowed or nid not in outputs:raise WorkflowError('Input references an unavailable upstream node.')
            result=nid if match[3]=='id' else outputs[nid]
            for part in (match[4] or '').split('.'):
                if not part:continue
                if isinstance(result,dict) and part in result:result=result[part]
                elif isinstance(result,list) and part.isdigit() and int(part)<len(result):result=result[int(part)]
                else:raise WorkflowError('An upstream output field is unavailable.')
            return result
        if isinstance(value,dict):return {k:self._resolve(v,outputs,allowed,parents,names) for k,v in value.items()}
        if isinstance(value,list):return [self._resolve(v,outputs,allowed,parents,names) for v in value]
        if isinstance(value,str):
            exact=_REF.fullmatch(value)
            if exact:return reference(exact)
            value=_REF.sub(lambda m:text(reference(m)),value)
            if '{{$' in value:raise WorkflowError('Unsupported output reference.')
        return value

    def _condition(self,condition,outputs,allowed,parents,names):
        if type(condition) is bool:return condition
        if not isinstance(condition,dict) or condition.get('op') not in ('eq','ne','contains','gt','lt','exists'):
            raise WorkflowError('Use a structured router condition.')
        left=self._resolve(condition.get('left'),outputs,allowed,parents,names);right=self._resolve(condition.get('right'),outputs,allowed,parents,names)
        op=condition['op']
        try:
            if op=='eq':return left==right
            if op=='ne':return left!=right
            if op=='contains':return right in left
            if op=='gt':return left>right
            if op=='lt':return left<right
            return left is not None
        except (TypeError,ValueError):raise WorkflowError('Router condition types do not match.')

    def _call(self,node,args,binding=None):
        self.products.before_call(node)
        from .capability_registry import Registry, digest
        from .observability import current_attempt
        rid=node.get('resource_id') or node.get('data',{}).get('resource_id')
        resource=self.store.resource(rid) if type(rid) is int else None
        registry=Registry(self.store);version=registry.current(resource) if resource and resource['kind']=='a2a' else None
        started=time.time();attempt=current_attempt(self.store)
        io_profile=None
        if node.get('data',{}).get('io_profile'):
            if node.get('data',{}).get('composition') is not None:raise WorkflowError('Use one reviewed transformation profile per agent.')
            io_profile=self.io_profiles.get(node['data']['io_profile'],resource_id=rid,
                tool=node['data'].get('tool') or node['data'].get('action'))
            from .workflow_transforms import apply as transform
            validate_input=args
            args=transform(io_profile['input_transform'],args)
        compiled=self.composer.validate_node(node,args)
        if compiled:version=compiled['pin']['version']
        try:
            with (dispatch_scope(lambda:self.io_profiles.get(io_profile['id'],resource_id=rid,tool=io_profile['tool']),extend=True) if io_profile else nullcontext()):
                result=self._call_registered(node,args,binding)
            if io_profile:
                from .capability_contracts import validate
                self.io_profiles.get(io_profile['id'],resource_id=rid,tool=io_profile['tool'])
                try:
                    result={'content':[], 'structuredContent':self.io_profiles.output(io_profile,result.get('structuredContent',result),validate_input)}
                    validate(io_profile['contract_id'],validate_input,result['structuredContent'])
                except ValueError:
                    if attempt and attempt.was_dispatched:
                        registry.record(io_profile['version'],scope='contract',outcome='failed',started=started,finished=time.time(),
                            operation_ref=attempt.id,contract_id=io_profile['contract_id'],code='UPSTREAM_PROTOCOL',dataset='generic-io-transform-v1')
                    raise WorkflowError('The converted provider result did not satisfy the reviewed contract.',error_code='UPSTREAM_PROTOCOL',definitive=True) from None
            if compiled:
                from .capability_contracts import validate
                self.composer.validate_node(node,args)
                validate(compiled['contract'],args,result.get('structuredContent',result))
        except Exception as exc:
            if compiled and attempt and attempt.was_dispatched:
                registry.record(version,scope='contract',outcome='failed',started=started,finished=time.time(),operation_ref=attempt.id,contract_id=compiled['contract'],code=getattr(exc,'error_code','UPSTREAM_PROTOCOL'))
            if version and not compiled and attempt and attempt.was_dispatched:
                registry.record(version,scope='execution',outcome='failed',started=started,finished=time.time(),operation_ref=attempt.id,code=getattr(exc,'error_code','EXECUTION_FAILED'))
            raise
        if compiled:
            registry.record(version,scope='contract',outcome='succeeded',started=started,finished=time.time(),operation_ref=attempt.id if attempt else None,contract_id=compiled['contract'],artifact_hash=digest(result),dataset='composer-live-test-v1')
        elif version:registry.record(version,scope='execution',outcome='succeeded',started=started,finished=time.time(),operation_ref=attempt.id if attempt else None)
        return result

    def _call_registered(self,node,args,binding=None):
        from .execution_authority import require_enabled
        require_enabled(self.store,'workflow');require_enabled(self.store,'invoke')
        data=node.get('data',{});rid=node.get('resource_id') or data.get('resource_id')
        if type(rid) is not int or not 0<rid<2**31:raise WorkflowError('Bind this node to a registered agent.')
        resource=self.store.resource(rid)
        from .capability_registry import known_schema_failure
        if known_schema_failure(self.store,resource):
            raise WorkflowError('The agent connection changed. Review it before retrying.',
                                error_code='SCHEMA_CHANGED')
        from .concierge.execution_policy import admit, ExecutionDenied
        try:admit(resource,node.get('kind'))
        except ExecutionDenied as exc:raise WorkflowError(str(exc),error_code=exc.error_code) from exc
        if not resource or not resource.get('active'):raise WorkflowError('The registered agent is unavailable.')
        from .concierge.recommendation_security import usable_endpoint
        if not usable_endpoint(resource.get('url')):raise WorkflowError('Use a public agent connection without embedded credentials.')
        if node.get('kind') and node['kind']!=resource['kind']:raise WorkflowError('The node protocol does not match its registered agent.')
        if binding and (any(binding.get(k)!=resource.get(k) for k in ('id','kind','usage_tools_hash')) or binding.get('url_hash')!=hashlib.sha256(resource['url'].encode()).hexdigest()):
            raise WorkflowError('The agent connection changed. Review it before starting a new run.')
        if binding and binding.get('connection_version_id'):
            from .capability_registry import Registry
            version=Registry(self.store).current(resource)
            if not version or version['id']!=binding['connection_version_id']:raise WorkflowError('The full agent contract changed. Review it before starting a new run.')
        if resource.get('health_status') in ('quarantined','unhealthy','dead','retired','down','suspended'):
            raise WorkflowError('This agent is not eligible for execution.')
        if resource.get('price_usdc',0):raise WorkflowError('Additional provider authorization is required for this agent.')
        if resource['kind']=='a2a':
            if self.courier is None:raise WorkflowError('A2A execution is unavailable.')
            from .concierge.execution_policy import resolve_a2a
            try:target=resolve_a2a(resource,self.courier)
            except ExecutionDenied as exc:raise WorkflowError(str(exc),error_code=exc.error_code) from exc
            from .concierge.recommendation_security import same_site_origin
            if not same_site_origin(target['url'],resource['url']):raise WorkflowError('The A2A endpoint must match the registered origin.')
            from .edge_gateway.native import execute as edge_execute
            try:edge_result=None if data.get('credential_refs') else edge_execute(self.store,resource,{'message':text(args)},courier=self.courier)
            except ExecutionDenied as exc:raise WorkflowError(str(exc),error_code=exc.error_code) from exc
            if edge_result is not None:
                if not edge_result['ok']:raise WorkflowError(edge_result['error'],error_code=edge_result['error_code'])
                return edge_result['result']['parts']
            from .collector.a2a import message_request
            mid=secrets.token_hex(16);v1=target.get('v1')
            provider_dispatch()
            status,raw=self.courier._request('POST',target['url'],65536,json=message_request(
                {'spec_version':'1.0' if v1 else '0.3'},text(args),request_id=mid),
                headers={'Content-Type':'application/json',**({'A2A-Version':'1.0'} if v1 else {})})
            if not 200<=status<300:raise WorkflowError('The A2A agent rejected the request.')
            response=json.loads(raw)
            if not isinstance(response,dict) or response.get('id')!=mid or response.get('error') or 'result' not in response:
                raise WorkflowError('The A2A agent returned an invalid response or error.')
            result=response['result'];obj=(result.get('message') or result.get('task') or result) if isinstance(result,dict) else None
            if not isinstance(obj,dict):raise WorkflowError('The A2A agent returned no final result.')
            if isinstance(obj.get('parts'),list):return obj['parts']
            state=str((obj.get('status') or {}).get('state','')).lower().replace('task_state_','')
            if state=='completed':
                parts=[part for artifact in obj.get('artifacts',[]) if isinstance(artifact,dict) for part in artifact.get('parts',[])]
                if parts:return parts
            raise WorkflowError('The A2A task returned no completed output. Check the agent before retrying.')
        if self.proxy is None:raise WorkflowError('Tool execution is unavailable.')
        tool=data.get('tool') or data.get('action')
        registered=resource.get('usage_tools') or []
        if isinstance(registered,str):registered=json.loads(registered)
        if not tool or tool=='execute':
            if len(registered)==1:tool=registered[0].get('name')
            else:raise WorkflowError('Select a registered tool for this node.')
        spec=next((t for t in registered if t.get('name')==tool),None)
        schema=(spec.get('inputSchema') or {'type':'object','properties':spec.get('params',{}),'required':spec.get('required',[])}) if spec else None
        if schema:
            from .concierge.execution_policy import validate_arguments
            try:validate_arguments(spec,args)
            except ExecutionDenied as exc:raise WorkflowError(str(exc),error_code=exc.error_code) from exc
        from .edge_gateway.native import execute as edge_execute
        result=None if data.get('credential_refs') else edge_execute(self.store,resource,{'tool':tool,'arguments':args},courier=self.courier)
        if result is None:result=self.proxy.execute(rid,tool,args)
        if not isinstance(result,dict) or not result.get('ok'):
            fault=failure_fields(result.get('error_code') if isinstance(result,dict) else None)
            raise WorkflowError(fault['error_message'],error_code=fault['error_code'],
                definitive=isinstance(result,dict) and result.get('hash_verified') is True and fault['error_code']=='UPSTREAM_TOOL_ERROR')
        return result.get('result',result.get('output',result.get('data',result)))

    def _seal(self,value,identity):
        from .concierge.task_updates import TaskUpdates
        return TaskUpdates._seal(self,value,identity)

    def _open(self,value,identity):
        from .concierge.task_updates import TaskUpdates
        return TaskUpdates._open(self,value,identity)

    def schedule(self,workflow_id):
        rows=self.store.query('SELECT * FROM workflow_schedules WHERE workflow_id=?',(workflow_id,))
        result=dict(rows[0]) if rows else {'workflow_id':workflow_id,'mode':'manual','preset':'daily_0900','timezone':'UTC','enabled':0,'next_run':None,'destination_id':None}
        result.pop('event_sealed',None);result.pop('event_hash',None)
        control = getattr(self.store, '_service_control', None)
        result['worker_active'] = (bool(control.status('execution').get('available')) if control is not None
                                   else time.time()-self.worker_seen<120)
        result['destinations']=[{'id':r['id'],'channel':r['channel'],'state':r['state'],'confirmed':r['confirmed']} for r in self.store.query('SELECT * FROM workflow_destinations WHERE workflow_id=? ORDER BY created DESC',(workflow_id,))]
        result['delivery_grants']=self.authority.grants(workflow_id)
        return result

    def save_schedule(self,workflow_id,data,principal=None):
        if not isinstance(data,dict):raise WorkflowError('Provide a schedule object.')
        wf=self.store.get_workflow(workflow_id)
        if not wf or not wf.get('is_active'):raise WorkflowError('Workflow not found or inactive.')
        graph(wf)
        mode=data.get('mode','manual');preset=data.get('preset','daily_0900');zone=data.get('timezone','UTC')
        if mode not in ('manual','scheduled','event_driven') or type(data.get('enabled',False)) is not bool:
            raise WorkflowError('Invalid schedule mode or enabled flag.')
        from .workflow_typed_flow import connected
        if mode!='manual' and any(connected(n) for n in wf['nodes']):
            raise WorkflowError('Connected drafts support private manual tests only; automatic schedules and events are unavailable.')
        from .workflow_paired_flow import is_pair
        if is_pair(wf) and (data.get('destination_id') or data.get('delivery_authority')):
            raise WorkflowError('Controlled pairs do not support result delivery.')
        due=next_due(preset,zone);enabled=bool(data.get('enabled')) and mode!='manual'
        dest=data.get('destination_id') or None
        if dest and (not isinstance(dest,str) or not re.fullmatch(r'wd_[0-9a-f]{32}',dest)):raise WorkflowError('Invalid workflow result inbox.')
        if dest:
            valid=self.store.query("SELECT 1 FROM workflow_destinations WHERE id=? AND workflow_id=? AND state='verified'",(dest,workflow_id))
            if not valid:raise WorkflowError('Choose a verified workflow result inbox.')
        old=self.store.query('SELECT * FROM workflow_schedules WHERE workflow_id=?',(workflow_id,))
        old=dict(old[0]) if old else {}
        grants=None
        if data.get('delivery_authority') is True:
            from .execution_authority import NOTICE
            if not dest or data.get('delivery_notice')!=NOTICE:raise WorkflowError('Review the result delivery permission notice.')
            principal=principal or self.principal('admin','internal',workflow_id,role='superadmin')
            try:claims=self.authority.validate(principal,workflow_id,'admin')
            except ValueError as exc:raise WorkflowError(str(exc)) from None
            if claims['role']!='superadmin':raise WorkflowError('Result delivery grants require superadmin authorization.')
            sources=data.get('delivery_sources',['admin'])
            if not isinstance(sources,list) or not sources or any(type(s) is not str for s in sources) or set(sources)-{'admin','schedule','event'}:raise WorkflowError('Choose explicit result delivery sources.')
            destination=dict(self.store.query('SELECT * FROM workflow_destinations WHERE id=? AND workflow_id=?',(dest,workflow_id))[0])
            grants=(destination,sources,claims)
        elif 'delivery_authority' in data and data['delivery_authority'] is not False:raise WorkflowError('Result delivery permission must be a boolean.')
        event_key=None;sealed=old.get('event_sealed');eh=old.get('event_hash')
        if mode=='event_driven' and (not sealed or data.get('rotate_event_key') is True):
            event_key=secrets.token_urlsafe(32);sealed=self._seal(event_key,'event:'+str(workflow_id));eh=hashlib.sha256(event_key.encode()).hexdigest()
        with self.store.tx() as db:
            db.execute('INSERT OR REPLACE INTO workflow_schedules VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (workflow_id,mode,preset,zone,int(enabled),due if enabled and mode=='scheduled' else None,old.get('last_run'),dest,eh,sealed,time.time()))
            db.execute('UPDATE agent_workflows SET trigger_type=? WHERE id=?',(mode,workflow_id))
        result=self.schedule(workflow_id)
        if grants:self.authority.issue(workflow_id,self.snapshot(self.store.get_workflow(workflow_id))[1],*grants)
        elif old.get('destination_id')!=dest:self.authority.revoke(workflow_id)
        result['delivery_grants']=self.authority.grants(workflow_id)
        if event_key:result['event_key']=event_key
        return result

    def register_destination(self,workflow_id,data):
        from .concierge.task_updates import TaskUpdates,UpdateError
        from urllib.parse import urlsplit
        if not self.store.get_workflow(workflow_id):raise WorkflowError('Workflow not found.')
        from .workflow_paired_flow import is_pair
        if is_pair(self.store.get_workflow(workflow_id)):
            raise WorkflowError('Controlled pairs do not support result delivery.')
        if data.get('authority') is not True or data.get('notice')!='workflow-results-v1':
            raise WorkflowError('Authorize workflow result delivery to this dedicated inbox.')
        if data.get('channel') not in ('webhook','a2a') or self.courier is None:raise WorkflowError('Choose Webhook or A2A.')
        try:TaskUpdates.validate_destination(data.get('url'))
        except UpdateError as exc:raise WorkflowError(str(exc)) from exc
        host=urlsplit(data['url']).hostname;now=time.time()
        with self.destination_lock:
            recent=self.store.query('SELECT COUNT(*) n FROM workflow_destinations WHERE created>?',(now-3600,))[0]['n']
            if recent>=10:raise WorkflowError('Inbox verification limit reached. Try again later.')
            target=self.courier.resolve(data['channel'],data['url'])
            try:TaskUpdates.validate_destination(target['url'])
            except UpdateError as exc:raise WorkflowError(str(exc)) from exc
            if urlsplit(target['url']).hostname!=host:raise WorkflowError('The inbox must use the registered host.')
            identity='wd_'+secrets.token_hex(16);code=str(secrets.randbelow(1000000)).zfill(6)
            secret={'target':target,'secret':secrets.token_urlsafe(32)}
            sealed=self._seal(secret,identity)
            with self.store.tx() as db:
                db.execute('INSERT INTO workflow_destinations (id,workflow_id,channel,sealed,state,code_hash,expires,created,notice) VALUES (?,?,?,?,?,?,?,?,?)',
                    (identity,workflow_id,data['channel'],sealed,'pending',hmac.new(self.key,(identity+code).encode(),hashlib.sha256).hexdigest(),now+3600,now,'workflow-results-v1'))
            # Fixed verification payload only. No workflow content before proof of control.
            sent,_=self.courier.send_update(data['channel'],secret,{'type':'workflow_inbox_verification','code':code,'purpose':'workflow_results','notice':'workflow-results-v1','signing_secret':secret['secret']},identity)
            if not sent:
                self.revoke_destination(workflow_id,identity)
                raise WorkflowError('Inbox verification could not be delivered.')
            return {'id':identity,'state':'pending','expires':now+3600}

    def verify_destination(self,workflow_id,identity,code):
        if not isinstance(code,str) or not re.fullmatch(r'[0-9]{6}',code):raise WorkflowError('Enter the six-digit inbox verification code.')
        with self.destination_lock,self.store.tx() as db:
            row=db.execute('SELECT * FROM workflow_destinations WHERE id=? AND workflow_id=?',(identity,workflow_id)).fetchone()
            if not row or row['state']!='pending':raise WorkflowError('Pending inbox not found.')
            valid=row['expires']>time.time() and row['attempts']<5 and hmac.compare_digest(row['code_hash'],hmac.new(self.key,(identity+code).encode(),hashlib.sha256).hexdigest())
            if valid:db.execute("UPDATE workflow_destinations SET state='verified',confirmed=?,code_hash=NULL WHERE id=?",(time.time(),identity))
            else:
                expired=row['expires']<=time.time() or row['attempts']>=4
                db.execute("UPDATE workflow_destinations SET attempts=attempts+1,state=?,sealed=CASE WHEN ? THEN NULL ELSE sealed END WHERE id=?",('expired' if expired else 'pending',int(expired),identity))
        if not valid:raise WorkflowError('Verification failed or expired.')
        return {'id':identity,'state':'verified'}

    def revoke_destination(self,workflow_id,identity):
        with self.destination_lock,self.store.tx() as db:
            db.execute("UPDATE workflow_destinations SET state='revoked',sealed=NULL,code_hash=NULL WHERE id=? AND workflow_id=?",(identity,workflow_id))
            db.execute('UPDATE workflow_schedules SET destination_id=NULL WHERE workflow_id=? AND destination_id=?',(workflow_id,identity))
            db.execute('UPDATE workflow_delivery_grants SET revoked=? WHERE workflow_id=? AND destination_id=? AND revoked IS NULL',(time.time(),workflow_id,identity))
        return {'id':identity,'state':'revoked'}

    def _delivery_target(self,run_id,workflow_id):
        row=self.store.query('SELECT digest,source FROM workflow_runs WHERE id=?',(run_id,))
        if not row:return None
        try:authority=self.authority.run(run_id,workflow_id,row[0]['digest'],row[0]['source'])
        except ValueError:return None
        if authority and any(authority['principal']['payload'].get(key) is not None for key in ('controlled_pair','deployment_consent','public_connection','connection_deployment','connection_automation')):return None
        if not authority or not authority.get('grant_id'):return None
        rows=self.store.query("SELECT d.* FROM workflow_delivery_grants g JOIN workflow_destinations d ON d.id=g.destination_id AND d.workflow_id=g.workflow_id WHERE g.id=? AND g.workflow_id=?",(authority['grant_id'],workflow_id))
        if not rows or not self.authority.delivery(authority,dict(rows[0])):return None
        destination=dict(rows[0])
        return {'id':'we_'+hashlib.sha256((run_id+destination['id']).encode()).hexdigest()[:32], 'destination_id':destination['id']}

    def drain_outbox(self,run_id=None):
        from .execution_authority import require_enabled
        try:require_enabled(self.store,'delivery')
        except ValueError:return
        if self.courier is None:return
        rows=self.store.query("SELECT id FROM workflow_result_outbox WHERE status='pending' AND (? IS NULL OR run_id=?) ORDER BY created LIMIT 12",(run_id,run_id))
        for item in rows:
            event=self.persistence.claim_delivery(item['id'],self.instance)
            if not event:continue
            observation=self.journal.begin('delivery','workflow_delivery',identity=stable_reference('workflow-delivery',event['id']),parent_id=stable_reference('workflow',event['run_id']))
            attempt=observation.attempt()
            try:
                run=dict(self.store.query('SELECT * FROM workflow_runs WHERE id=?',(event['run_id'],))[0])
                result=json.loads(run['result'])
                authority=self.authority.run(run['id'],run['workflow_id'],run['digest'],run['source'])
                if authority and any(authority['principal']['payload'].get(key) is not None for key in ('controlled_pair','deployment_consent','public_connection','connection_deployment','connection_automation')):
                    raise WorkflowError('This execution purpose does not support result delivery.',error_code='POLICY_DENIED')
                destinations=self.store.query('SELECT * FROM workflow_destinations WHERE id=? AND workflow_id=?',(event['destination_id'],run['workflow_id']))
                destination=dict(destinations[0]) if destinations else None
                if run['status']!='succeeded' or not destination or not self.authority.delivery(authority,destination):
                    raise WorkflowError('Result delivery authorization changed.',error_code='POLICY_DENIED')
                secret=self._open(destination['sealed'],destination['id'])
                with attempt_scope(attempt),dispatch_scope(lambda:self.persistence.delivery_dispatch(event)):
                    if not self.authority.delivery(authority,destination):raise WorkflowError('Result delivery authorization changed.',error_code='POLICY_DENIED')
                    provider_dispatch()
                    sent,error=self.courier.send_update(destination['channel'],secret,{'type':'workflow_result','run_id':run['id'],'workflow_id':run['workflow_id'],'artifact_sha256':result['artifact_sha256'],'content':result['final_deliverable']['content_md']},event['id'])
                    attempt.finish('accepted' if sent else 'unknown',None if sent else 'UPSTREAM_NETWORK')
                state='accepted' if sent else 'unknown'
                self.persistence.delivery_finish(event,state,{'status':'ACCEPTED' if sent else 'UNKNOWN','channel':destination['channel'],'destination_id':destination['id'],'event_id':event['id']})
                observation.finish(state,None if sent else 'UPSTREAM_NETWORK')
            except FenceLost:
                observation.finish('unknown','EXECUTION_FAILED')
            except Exception as exc:
                # A failure after durable dispatch is uncertain, never auto-retried.
                current=self.store.query('SELECT status FROM workflow_result_outbox WHERE id=?',(event['id'],))
                state='unknown' if current and current[0]['status']=='dispatched' else 'denied'
                try:self.persistence.delivery_finish(event,state,{'status':'UNKNOWN' if state=='unknown' else 'NOT_AUTHORIZED','event_id':event['id']})
                except FenceLost:pass
                observation.finish('unknown' if state=='unknown' else 'denied',getattr(exc,'error_code','EXECUTION_FAILED'))

    def _deliver(self,run_id,workflow_id,result):
        # Compatibility entry point: only drain an already committed event.
        rows=self.store.query('SELECT workflow_id FROM workflow_runs WHERE id=?',(run_id,))
        if rows and rows[0]['workflow_id']==workflow_id:self.drain_outbox(run_id)

    def receive_event(self,workflow_id,raw,stamp,event_id,signature):
        if not isinstance(event_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',event_id):raise WorkflowError('Invalid event.')
        try:valid_time=abs(time.time()-int(stamp))<=300
        except (ValueError,TypeError):valid_time=False
        rows=self.store.query("SELECT * FROM workflow_schedules WHERE workflow_id=? AND mode='event_driven' AND enabled=1",(workflow_id,))
        if not rows or not valid_time or not rows[0]['event_sealed']:raise WorkflowError('Event authorization failed.')
        key=self._open(rows[0]['event_sealed'],'event:'+str(workflow_id))
        expected='sha256='+hmac.new(key.encode(),str(stamp).encode()+b'.'+event_id.encode()+b'.'+raw,hashlib.sha256).hexdigest()
        if not isinstance(signature,str) or not re.fullmatch(r'sha256=[0-9a-f]{64}',signature) or not hmac.compare_digest(expected,signature):raise WorkflowError('Event authorization failed.')
        # Payload is authenticated but cannot replace the saved graph or tool inputs.
        with self.lock:
            if self.store.query('SELECT 1 FROM workflow_event_receipts WHERE workflow_id=? AND event_id=?',(workflow_id,event_id)):
                raise WorkflowError('Event already received.')
            result=self.submit(self.store.get_workflow(workflow_id),actor='event:'+str(workflow_id),source='event',idempotency=event_id)
            with self.store.tx() as db:db.execute('INSERT INTO workflow_event_receipts VALUES (?,?,?)',(workflow_id,event_id,time.time()))
        return {'accepted':True,'replayed':bool(result.get('replayed'))}

    def run_due(self,now=None):
        now=time.time() if now is None else now;self.worker_seen=time.time();checked=0
        self.persistence.recover()
        self.drain_outbox()
        self.operations.drain()
        with self.store.tx() as db:
            db.execute("UPDATE workflow_destinations SET state='expired',sealed=NULL,code_hash=NULL WHERE state='pending' AND expires<?",(time.time(),))
        for row in self.store.query("SELECT id FROM workflow_runs WHERE status='queued' ORDER BY created LIMIT 12"):
            self.launch(row['id'])
        with self.lock:
            for r in self.store.query("SELECT * FROM workflow_schedules WHERE enabled=1 AND mode='scheduled' AND next_run<=? ORDER BY next_run LIMIT 8",(now,)):
                wf=self.store.get_workflow(r['workflow_id'])
                if not wf or not wf.get('is_active'):continue
                try:self.submit(wf,actor='schedule:'+str(wf['id']),source='schedule',idempotency=str(r['next_run']))
                except WorkflowError:continue
                with self.store.tx() as db:db.execute('UPDATE workflow_schedules SET last_run=?,next_run=? WHERE workflow_id=? AND next_run=?',(now,next_due(r['preset'],r['timezone'],now),wf['id'],r['next_run']))
                checked+=1
        automation=self.automation.run_due(now)
        return {'checked':checked+automation['checked']}

    def _execute(self,run_id):
        from .concierge.http_security import outbound_operation
        pending=self.store.query('SELECT * FROM workflow_runs WHERE id=?',(run_id,))
        if not pending:return
        try:budget=self.budgets.get(dict(pending[0]))
        except ValueError:
            with self.store.tx() as db:db.execute("UPDATE workflow_runs SET status='failed',execution_outcome='failed',finished=?,error='Execution authorization is invalid.' WHERE id=? AND status='queued'",(time.time(),run_id))
            return
        seconds=60 if budget['profile']=='extended' else MAX_SECONDS
        row=self.persistence.claim(run_id,self.instance,seconds)
        if not row:return
        stop=threading.Event()
        def heartbeat():
            try:
                with self.persistence.heartbeat_connection() as connection:
                    delay = 2
                    contention_reported = False
                    while not stop.wait(delay):
                        try:
                            if not self.persistence.pulse(run_id,self.instance,row['fence'],connection):return
                            delay = 2
                        except sqlite3.OperationalError as exc:
                            if not any(word in str(exc).lower() for word in ('locked','busy')):
                                logging.getLogger(__name__).warning('Workflow heartbeat unavailable (%s).', getattr(exc,'sqlite_errorname',type(exc).__name__))
                                return
                            # Three busy samples spaced two seconds apart can
                            # exhaust a short lease. Retry briefly to
                            # catch a writer gap; pulse still rejects expired
                            # owners, fences and the original run deadline.
                            delay = .2
                            if not contention_reported:
                                logging.getLogger(__name__).warning('Workflow heartbeat writer contention; retrying within the active lease.')
                                contention_reported = True
                            continue
            except Exception:return
        worker=threading.Thread(target=heartbeat,daemon=True,name='workflow-lease');worker.start()
        try:
            with outbound_operation(min(seconds,max(.001,row['deadline']-time.time()))):self._execute_bounded(run_id,row)
        except Exception:self.persistence.fail_owned(run_id,self.instance,row['fence'])
        finally:stop.set();worker.join(timeout=3)

    def _execute_bounded(self,run_id,row):
        from . import workflow_paired_flow as paired_flow
        from . import workflow_public_flow as public_flow
        budget=self.budgets.get(row)
        started=row['started'];deadline=time.monotonic()+min(60 if budget['profile']=='extended' else MAX_SECONDS,max(0,row['deadline']-time.time()))
        results=[];outputs={};states={};ancestors={};routing={};transfers=[]
        wf=json.loads(row['snapshot'])
        if hashlib.sha256(canonical(wf).encode()).hexdigest()!=row['digest']:raise FenceLost('The saved execution definition changed.')
        by_id,incoming,order=graph(wf)
        names={n['name']:nid for nid,n in by_id.items() if n.get('name') and sum(x.get('name')==n['name'] for x in by_id.values())==1}
        checkpoints={r['node_id']:dict(r) for r in self.store.query('SELECT * FROM workflow_checkpoints WHERE run_id=?',(run_id,))}
        source='workflow_deployment' if row['source']=='webapp' else 'workflow_'+row['source']
        observation=self.journal.begin('workflow',source,identity=stable_reference('workflow',run_id),workflow_id=wf['id'])
        secrets_used=[]
        def redact(value):
            def visit(item):
                if isinstance(item,dict):return {k:visit(v) for k,v in item.items()}
                if isinstance(item,list):return [visit(v) for v in item]
                if isinstance(item,str):
                    for secret in secrets_used:item=item.replace(secret,'[REDACTED]')
                return item
            return visit(clean(value))
        try:
            for nid in order:
                node=by_id[nid];data=node.get('data',{});parents=[e['source'] for e in incoming[nid]]
                ancestors[nid]=set(parents)
                for parent in parents:ancestors[nid].update(ancestors[parent])
                live=[]
                for edge in incoming[nid]:
                    parent=edge['source'];expect=edge.get('condition',edge.get('label','true'))
                    desired=False if expect in (False,'false','False') else True
                    if parent not in routing or routing[parent] is desired:live.append(parent)
                if nid in checkpoints:
                    checkpoint=checkpoints[nid];payload=json.loads(checkpoint['payload'])
                    if not hmac.compare_digest(checkpoint['signature'],self.authority.signature(payload)) or payload.get('run_id')!=run_id or payload.get('digest')!=row['digest'] or payload.get('node_id')!=nid or payload.get('audience')!='workflow-checkpoint-v1':raise FenceLost('Stored checkpoint is invalid.')
                    # Every resumed step still needs current run authority and policy.
                    from .execution_authority import require_enabled
                    require_enabled(self.store,'workflow');self.authority.run(run_id,wf['id'],row['digest'],row['source'])
                    if paired_flow.is_pair(wf):paired_flow.run_scope(self,row,wf)
                    if row['source']=='webapp':self.deployment_consent.dispatch_guard(row,wf)
                    self.publication.dispatch_guard(row,wf,node,payload['record'].get('input'),payload.get('typed_input'))
                    record=payload['record'];results.append(record);states[nid]=record['status'];transfers.extend(payload['transfers'])
                    if record['status']=='succeeded':outputs[nid]=payload['flow_output']
                    if payload['routing'] is not None:routing[nid]=payload['routing']
                    continue
                transfer_start=len(transfers)
                status='succeeded';output=None;dataflow_output=None;error=None;args={};attempted=False;fault={};routing_summary={};typed_input=None;t0=time.monotonic();node_started=time.time()
                with self.store.tx() as db:
                    self.persistence.owned(db,run_id,self.instance,row['fence'])
                    db.execute("UPDATE workflow_node_runs SET status='running',started=? WHERE run_id=? AND node_id=?",(node_started,run_id,nid))
                if self._cancelled(run_id):status='cancelled';error='Execution cancelled.'
                elif time.monotonic()>=deadline:status='failed';error='Workflow execution time limit reached.'
                elif node.get('disabled') or node.get('is_active',True) in (False,0) or data.get('disabled') or data.get('is_active',True) in (False,0):
                    status='skipped';error='Node disabled.'
                elif parents and (not live or all(states[p]=='skipped' for p in live)):
                    status='skipped';error='Branch condition was not selected.'
                elif any(states[p] in ('failed','cancelled','blocked') for p in live):
                    status='blocked';error='An upstream step did not succeed.'
                else:
                    try:
                        from .execution_authority import require_enabled
                        require_enabled(self.store,'workflow')
                        authority=self.authority.run(run_id,wf['id'],row['digest'],row['source'])
                        if row['source']=='webapp':self.deployment_consent.dispatch_guard(row,wf)
                        paired_flow.dispatch_guard(self,row,wf,node)
                        self.publication.dispatch_guard(row,wf,node)
                        if data.get('credential_refs') and (not authority or authority['principal']['payload']['kind']!='admin' or authority['principal']['payload']['role']!='superadmin'):
                            raise WorkflowError('This execution cannot use platform credentials.',error_code='POLICY_DENIED')
                        from .workflow_typed_flow import connected
                        if connected(node):args,typed_input=self.composer.resolve_input(node,row,wf)
                        else:args=self._resolve(data.get('input',{}),outputs,ancestors[nid],live,names)
                        if node.get('type')=='agent':args=self.products.inputs(row,node,args)
                        if not isinstance(args,dict):raise WorkflowError('Tool inputs must be an object.')
                        if len(canonical(args).encode())>MAX_OUTPUT:raise WorkflowError('Resolved input exceeds the workflow size limit.')
                        count=[0]
                        def bounded_input(value,depth=0):
                            count[0]+=1
                            if depth>15 or count[0]>2000 or isinstance(value,list) and len(value)>100 or isinstance(value,str) and len(value)>8192:
                                raise WorkflowError('Resolved input exceeds the workflow complexity limit.')
                            if isinstance(value,dict):
                                for item in value.values():bounded_input(item,depth+1)
                            elif isinstance(value,list):
                                for item in value:bounded_input(item,depth+1)
                        bounded_input(args)
                        if node.get('type')=='trigger':output={'trigger':wf.get('trigger_type','manual')}
                        elif node.get('type')=='router':
                            output=self._condition(data.get('condition'),outputs,ancestors[nid],live,names);routing[nid]=output
                        elif node.get('type') in ('input_transform','output_transform'):
                            from .workflow_transforms import apply as transform
                            output=transform(data['transform'],args)
                        else:
                            refs=data.get('credential_refs',{})
                            if not isinstance(refs,dict):raise WorkflowError('Invalid credential references.')
                            for field,key in refs.items():
                                if not isinstance(key,str):raise WorkflowError('Invalid credential reference.')
                                secret=self.store.get_credential(key)
                                if not secret:raise WorkflowError('A configured credential is unavailable.')
                                secrets_used.append(secret);args[field]=secret
                            paired_flow.dispatch_guard(self,row,wf,node)
                            if row['source']=='webapp':self.deployment_consent.dispatch_guard(row,wf)
                            self.publication.dispatch_guard(row,wf,node,args,typed_input)
                            attempted=True
                            input_hash=self.authority.signature({'audience':'workflow-input-v1','digest':row['digest'],'node_id':nid,'input':args})
                            self.persistence.prepare(run_id,self.instance,row['fence'],nid,input_hash)
                            def invoke(selected,arguments,binding):
                                from .concierge.http_security import outbound_operation
                                attempt=observation.attempt(selected.get('resource_id') or selected.get('data',{}).get('resource_id'),selected.get('kind'))
                                with attempt_scope(attempt),dispatch_scope(lambda:(self.composer.validate_node(selected,arguments),paired_flow.dispatch_guard(self,row,wf,node),self.deployment_consent.dispatch_guard(row,wf) if row['source']=='webapp' else None,self.publication.dispatch_guard(row,wf,node,arguments,typed_input),self.persistence.dispatch(run_id,self.instance,row['fence'],nid))):
                                    call_started=time.monotonic()
                                    from .edge_gateway.result_transport import parent_scope
                                    with parent_scope(run_id,nid),outbound_operation(min(budget['node_seconds'],max(.001,deadline-time.monotonic()))):value=self._call(selected,arguments,binding)
                                    if time.monotonic()-call_started>budget['node_seconds']:raise WorkflowError('The node execution time limit was reached.',error_code='UPSTREAM_TIMEOUT')
                                    attempt.finish('succeeded')
                                    return value
                            with self.composer.input_scope(row,wf),self.products.call_scope(row):
                                output,routing_summary=self.fallback.execute(row,node,args,wf.get('bindings',{}).get(nid),observation,deadline,invoke)
                            if len(canonical(output).encode())>MAX_OUTPUT:raise WorkflowError('Agent output exceeds the workflow size limit.')
                            dataflow_output=output
                            output=project_output(output,data.get('output_select'))
                            if time.monotonic()>=deadline:raise WorkflowError('Workflow execution time limit reached.')
                        if len(canonical(output).encode())>MAX_OUTPUT:raise WorkflowError('Agent output exceeds the workflow size limit.')
                        outputs[nid]=redact(dataflow_output if attempted else output)
                        for parent in live:
                            if parent in outputs:transfers.append({'source_id':parent,'target_id':nid,'source_name':by_id[parent].get('name',parent),
                                'target_name':node.get('name',nid),
                                'passed_data_summary':'Verified news title used as the documentation query.' if paired_flow.paired(node) or public_flow.connected(node) else 'Upstream output received.',
                                'size_bytes':len(canonical(args if paired_flow.paired(node) or public_flow.connected(node) else outputs[parent]).encode()),'status':'PASSED'})
                    except FenceLost:raise
                    except Exception as exc:
                        status='blocked' if isinstance(exc,paired_flow.PairBlocked) else 'failed';error=str(exc) if isinstance(exc,WorkflowError) else 'Agent execution could not be completed.'
                        correlation_id=observation.id or reference()
                        fault=failure_fields(exc.error_code if isinstance(exc,(WorkflowError,paired_flow.PairBlocked)) else 'EXECUTION_FAILED',correlation_id)
                        record_failure(correlation_id,node.get('resource_id') or data.get('resource_id'),node.get('kind'),
                                       fault['error_code'],stage='workflow',exception=exc)
                if self._cancelled(run_id):status='cancelled';error='Execution cancelled.';output=None
                states[nid]=status
                safe_args=redact(args);safe_output=redact(output)
                route_count=self.store.query('SELECT COUNT(*) FROM workflow_routing_attempts WHERE run_id=? AND node_id=?',(run_id,nid))[0][0]
                result={'node_id':nid,'name':node.get('name',nid),'type':node.get('type','agent'),
                    'kind':node.get('kind','agent'),'resource_id':node.get('resource_id') or data.get('resource_id'),
                    'status':status,'attempts':max(int(attempted),route_count),'latency_ms':round((time.monotonic()-t0)*1000,2),
                    'output':text(safe_output) if output is not None else '', 'data':safe_output,'input':safe_args,'error':error,
                    **({k:fault[k] for k in ('error_code','correlation_id')} if fault else {})}
                if status=='succeeded':result.update(routing_summary)
                results.append(result)
                result['started']=node_started
                payload={'audience':'workflow-checkpoint-v1','run_id':run_id,'digest':row['digest'],'node_id':nid,'record':result,'flow_output':outputs.get(nid),'routing':routing.get(nid),'transfers':transfers[transfer_start:]}
                if typed_input is not None:payload['typed_input']=typed_input
                self.persistence.checkpoint(run_id,self.instance,row['fence'],nid,canonical(payload),self.authority.signature(payload),result)
            final_status='cancelled' if self._cancelled(run_id) else 'failed' if any(s in ('failed','blocked','cancelled') for s in states.values()) else 'succeeded'
            total=round((time.time()-started)*1000,2)
            artifact={'workflow_name':wf.get('name'),'status':final_status,'nodes':results}
            checksum=hashlib.sha256(canonical(artifact).encode()).hexdigest()
            result={'ok':final_status=='succeeded','status':final_status,'run_id':run_id,'workflow_id':wf['id'],
                'workflow_name':wf.get('name'),'definition_hash':row['digest'],'node_results':results,
                'step_results':[{**n,'step':i+1} for i,n in enumerate(results) if n['type']!='trigger'],
                'results':results,'steps_count':len(results),'nodes_count':len(results),'edges_count':len(wf.get('edges',[])),
                'executed_nodes':sum(n['status']=='succeeded' for n in results),'total_latency_ms':total,'duration_ms':total,
                'executed_at':started,'data_flow_trace':transfers,'artifact_sha256':checksum,
                'final_deliverable':{'title':wf.get('name'),'executive_summary':[n['name']+': '+n['status'] for n in results],
                    'content_md':'\n\n'.join(n['name']+' — '+n['status']+'\n'+(n['output'] or n['error'] or '') for n in results),
                    'distribution':{'status':'NOT_REQUESTED','channel':None,'target':None},'schedule_info':'See the saved schedule configuration.','schedule_badge':wf.get('trigger_type','manual')}}
            target=self._delivery_target(run_id,wf['id']) if final_status=='succeeded' else None
            if target:
                from .execution_authority import controls
                result['final_deliverable']['distribution']['status']='PENDING' if controls(self.store)['delivery_enabled'] else 'NOT_AUTHORIZED'
            self.persistence.finish(run_id,self.instance,row['fence'],result,target)
            observation.finish('succeeded' if final_status=='succeeded' else 'cancelled' if final_status=='cancelled' else 'failed')
            if target:self.drain_outbox(run_id)
        except FenceLost:
            observation.finish('unknown','EXECUTION_FAILED')
            self.persistence.fail_owned(run_id,self.instance,row['fence'])
        except Exception:
            observation.finish('failed','EXECUTION_FAILED')
            self.persistence.fail_owned(run_id,self.instance,row['fence'])


def runtime_for(store,proxy=None,courier=None):
    with store._lock:
        runtime=getattr(store,'_workflow_runtime',None)
        if runtime is None:runtime=WorkflowRuntime(store,proxy,courier)
        if proxy is not None:runtime.proxy=proxy
        if courier is not None:runtime.courier=courier
        return runtime
