"""Immutable private MCP releases and independently revocable customer app grants."""
import base64
import hashlib
import hmac
import json
import re
import secrets
from urllib.parse import urlsplit

from .workspace_access import WorkspaceConflict,WorkspaceDenied,WorkspaceInvalid,_canonical,_hash,_identity,_revision,_rows,_tree
from .workspace_execution import NOTICE as PRIVATE_NOTICE,_now
from .private_artifact_keys import ArtifactSigner

PROFILE='workspace-executable-release-v1'
SDK_PROFILE='workspace-sdk-v2'
DEPLOY_NOTICE='workspace-sdk-deployment-v2'
RUN_NOTICE='workspace-sdk-run-v2'
SCHEMA=(
'''CREATE TABLE IF NOT EXISTS workspace_release_restore_blocks(authority_id TEXT PRIMARY KEY)''',
'''CREATE TABLE IF NOT EXISTS workspace_executable_releases(id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,draft_id TEXT NOT NULL,snapshot_id TEXT NOT NULL,revision INTEGER NOT NULL,active INTEGER NOT NULL,created REAL NOT NULL,expires REAL NOT NULL,revoked REAL,payload TEXT NOT NULL,signature TEXT NOT NULL,state_signature TEXT NOT NULL)''',
'''CREATE TABLE IF NOT EXISTS workspace_release_deployments(app_id TEXT PRIMARY KEY,release_id TEXT NOT NULL,workspace_id TEXT NOT NULL,revision INTEGER NOT NULL,active INTEGER NOT NULL,created REAL NOT NULL,expires REAL NOT NULL,revoked REAL,payload TEXT NOT NULL,signature TEXT NOT NULL,state_signature TEXT NOT NULL)''',
'''CREATE TABLE IF NOT EXISTS workspace_app_codes(code_hash TEXT PRIMARY KEY,app_id TEXT NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL,consumed REAL)''',
'''CREATE TABLE IF NOT EXISTS workspace_app_tokens(token_hash TEXT PRIMARY KEY,app_id TEXT NOT NULL,audience TEXT NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
'''CREATE TABLE IF NOT EXISTS workspace_app_admissions(ticket_id TEXT PRIMARY KEY,app_id TEXT NOT NULL,created REAL NOT NULL)''',
'''CREATE TABLE IF NOT EXISTS workspace_app_run_links(ticket_id TEXT PRIMARY KEY,app_id TEXT NOT NULL,token_hash TEXT NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
'CREATE INDEX IF NOT EXISTS workspace_release_scope ON workspace_executable_releases(workspace_id,draft_id,snapshot_id)',
'CREATE INDEX IF NOT EXISTS workspace_app_scope ON workspace_release_deployments(release_id)')


def origin(value):
    if type(value) is not str or len(value)>250:raise WorkspaceInvalid()
    try:
        part=urlsplit(value);host=part.hostname
        if (part.username or part.password or not host or not host.isascii() or part.query or part.fragment or part.path not in ('','/') or part.scheme not in ('https','http') or part.scheme=='http' and host not in ('localhost','127.0.0.1','::1')):raise WorkspaceInvalid()
        port=part.port
        rendered='['+host.lower()+']' if ':' in host else host.lower()
        return part.scheme+'://'+rendered+(':'+str(port) if port and port!=(443 if part.scheme=='https' else 80) else '')
    except (ValueError,TypeError):raise WorkspaceInvalid() from None


class WorkspaceReleases:
    def __init__(self,execution,*,customer_identity=None,customer_executor=None):
        self.execution,self.access,self.store=execution,execution.access,execution.store
        self.identity,self.customer_executor=customer_identity,customer_executor
        self.compatibility_guard=None
        self.key=hmac.new(self.access.key,PROFILE.encode(),hashlib.sha256).digest()
        self.signer=ArtifactSigner(self.key,PROFILE)
        with execution._internal() as db:
            for sql in SCHEMA:db.execute(sql)

    def _sign(self,value):return self.signer.sign(value)
    def _ref(self,value):return hmac.new(self.key,str(value).encode(),hashlib.sha256).hexdigest()
    def _open(self,row):
        try:
            value=json.loads(row['payload']);_tree(value)
            if not self.signer.verify(value,row['signature']):raise WorkspaceConflict()
            return value
        except (ValueError,TypeError,KeyError):raise WorkspaceConflict() from None
    def _link(self,row):
        value=self._open(row)
        if any(value.get(k)!=row[k] for k in ('ticket_id','app_id','token_hash')):raise WorkspaceConflict()
        return value
    def _state_value(self,row,kind):return {'kind':kind,**{k:row[k] for k in ('revision','active','revoked')},'id':row['id'] if kind=='release' else row['app_id']}
    def _state(self,row,kind):return self._sign(self._state_value(row,kind))
    def _owner(self,ws,actor):return self.access._access(ws,actor,write=True,owner=True)[0]
    def _release(self,db,rid,*,active=True):
        _identity(rid,'wrl');rows=_rows(db,'SELECT * FROM workspace_executable_releases WHERE id=?',(rid,))
        if len(rows)!=1:raise WorkspaceDenied()
        row=rows[0];value=self._open(row)
        if active and db.execute('SELECT 1 FROM workspace_release_restore_blocks WHERE authority_id=?',(rid,)).fetchone():raise WorkspaceDenied()
        if (not self.signer.verify(self._state_value(row,'release'),row['state_signature']) or any(value[k]!=row[k] for k in ('id','workspace_id','draft_id','snapshot_id','created','expires')) or active and (not row['active'] or row['expires']<=_now())):raise WorkspaceDenied()
        if active and self.compatibility_guard is not None:self.compatibility_guard(db,value)
        return row,value
    def _deployment(self,db,app,*,active=True):
        _identity(app,'wap');rows=_rows(db,'SELECT * FROM workspace_release_deployments WHERE app_id=?',(app,))
        if len(rows)!=1:raise WorkspaceDenied()
        row=rows[0];value=self._open(row)
        if active and db.execute('SELECT 1 FROM workspace_release_restore_blocks WHERE authority_id=?',(app,)).fetchone():raise WorkspaceDenied()
        if (not self.signer.verify(self._state_value(row,'deployment'),row['state_signature']) or any(value[k]!=row[k] for k in ('app_id','release_id','workspace_id','created','expires')) or active and (not row['active'] or row['expires']<=_now())):raise WorkspaceDenied()
        return row,value
    @staticmethod
    def _dto(row,app=False):return {k:row[k] for k in (('app_id','release_id','revision','active','created','expires','revoked') if app else ('id','revision','active','created','expires','revoked'))}
    def _scope(self,value,ws,draft,snapshot):
        if (value['workspace_id'],value['draft_id'],value['snapshot_id'])!=(ws,draft,snapshot):raise WorkspaceDenied()
    def _release_profile(self,db,snapshot,resource_id,tool,*,admission_scope=None):
        # Product compositions require a separately reviewed release contract.
        # Copying their literal graph must not bypass that boundary.
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workspace_product_compositions'").fetchone() and db.execute('SELECT 1 FROM workspace_product_compositions WHERE snapshot_id=?',(snapshot,)).fetchone():raise WorkspaceDenied()
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='reliability_admissions'").fetchone():
            from .reliability_admission import protected_admission
            # Typed releases pass the scope of their already verified version;
            # their version IDs do not belong to the legacy snapshot table.
            scope=admission_scope
            if scope is None:
                scope=db.execute('SELECT workspace_id,draft_id FROM workspace_versions WHERE id=?',(snapshot,)).fetchone()
            if scope is None or len(scope)!=2 or protected_admission(self.access,db,scope[0],scope[1],snapshot) is not None:raise WorkspaceDenied()
        from .workflow_product_semantics import registered_tool
        if registered_tool(self.store.resource(resource_id),tool):raise WorkspaceDenied()
    def create(self,ws,draft,snapshot,body,actor):
        _tree(body)
        if type(body) is not dict or set(body)!={'run_id','ttl_seconds'} or type(body['ttl_seconds']) is not int or not 300<=body['ttl_seconds']<=2592000:raise WorkspaceInvalid()
        with self.access._tx(actor,write=True) as (db,_):
            self._owner(ws,actor);bound,node,_=self.execution._binding(db,ws,draft,snapshot,actor)
            self._release_profile(db,snapshot,bound['resource_id'],node['data']['tool'])
            row,_,claims,result=self.execution._load_run(db,body['run_id'],ws,draft,snapshot)
            if result['status']!='succeeded' or row['dispatched'] is None or any(claims[k]!=bound[k] for k in ('snapshot_revision','snapshot_hash','definition_hash','resource_id','binding_hash')):raise WorkspaceDenied()
            if db.execute('SELECT COUNT(*) FROM workspace_executable_releases WHERE workspace_id=?',(ws,)).fetchone()[0]>=100:raise WorkspaceConflict()
            now=_now();identity='wrl_'+secrets.token_hex(16)
            value={'profile':PROFILE,'id':identity,'workspace_id':ws,'draft_id':draft,'snapshot_id':snapshot,'created':now,'expires':now+body['ttl_seconds'],'snapshot_revision':bound['snapshot_revision'],'snapshot_hash':bound['snapshot_hash'],'definition_hash':bound['definition_hash'],'binding_hash':bound['binding_hash'],'resource_id':bound['resource_id'],'tool':node['data']['tool'],'input':node['data']['input'],'test_run_id':result['id'],'max_calls':1,'seconds':12}
            state={'id':identity,'revision':1,'active':1,'revoked':None}
            db.execute('INSERT INTO workspace_executable_releases VALUES(?,?,?,?,1,1,?,?,NULL,?,?,?)',(identity,ws,draft,snapshot,now,value['expires'],_canonical(value),self._sign(value),self._state(state,'release')))
            self.access._audit(db,actor,ws,'release.create',identity,1)
            return self._dto({**value,**state})
    def releases(self,ws,draft,snapshot,actor):
        with self.access._tx(actor) as (db,_):
            self.execution._scope(ws,draft,snapshot,actor)
            result=[]
            for row in _rows(db,'SELECT * FROM workspace_executable_releases WHERE workspace_id=? AND draft_id=? AND snapshot_id=? ORDER BY created DESC LIMIT 100',(ws,draft,snapshot)):
                self._release(db,row['id'],active=False);result.append(self._dto(row))
            return result
    def revoke(self,ws,draft,snapshot,rid,body,actor):
        if type(body) is not dict or set(body)!={'revision'} or not _revision(body['revision']):raise WorkspaceInvalid()
        with self.access._tx(actor,write=True) as (db,_):
            self._owner(ws,actor);row,value=self._release(db,rid,active=False);self._scope(value,ws,draft,snapshot)
            if row['revision']!=body['revision'] or not row['active']:raise WorkspaceConflict()
            row.update(active=0,revision=row['revision']+1,revoked=_now())
            db.execute('UPDATE workspace_executable_releases SET active=0,revision=?,revoked=?,state_signature=? WHERE id=?',(row['revision'],row['revoked'],self._state(row,'release'),rid));self.access._audit(db,actor,ws,'release.revoke',rid,row['revision']);return self._dto(row)
    def deploy(self,ws,draft,snapshot,rid,body,actor):
        _tree(body)
        if type(body) is not dict or set(body)!={'allowed_origins','ttl_seconds','minute_limit','day_limit','authorized','notice'} or body['authorized'] is not True or body['notice']!=DEPLOY_NOTICE:raise WorkspaceInvalid()
        if type(body['allowed_origins']) is not list or not 1<=len(body['allowed_origins'])<=5 or any(type(body[k]) is not int for k in ('ttl_seconds','minute_limit','day_limit')) or not 300<=body['ttl_seconds']<=86400 or not 1<=body['minute_limit']<=30 or not 1<=body['day_limit']<=100:raise WorkspaceInvalid()
        origins=sorted(set(origin(item) for item in body['allowed_origins']))
        with self.access._tx(actor,write=True) as (db,_):
            self._owner(ws,actor);_,release=self._release(db,rid);self._scope(release,ws,draft,snapshot);self._admin_current(db,release,actor)
            if db.execute('SELECT COUNT(*) FROM workspace_release_deployments WHERE workspace_id=?',(ws,)).fetchone()[0]>=100:raise WorkspaceConflict()
            now=_now();app='wap_'+secrets.token_hex(16);value={'profile':SDK_PROFILE,'app_id':app,'release_id':rid,'workspace_id':ws,'created':now,'expires':min(now+body['ttl_seconds'],release['expires']),'allowed_origins':origins,'minute_limit':body['minute_limit'],'day_limit':body['day_limit']}
            row={**value,'revision':1,'active':1,'revoked':None}
            db.execute('INSERT INTO workspace_release_deployments VALUES(?,?,?,1,1,?,?,NULL,?,?,?)',(app,rid,ws,now,value['expires'],_canonical(value),self._sign(value),self._state(row,'deployment')));self.access._audit(db,actor,ws,'deployment.issue',app,1)
            return {**self._dto(row,True),'allowed_origins':origins,'minute_limit':value['minute_limit'],'day_limit':value['day_limit'],'profile':SDK_PROFILE}
    def _admin_current(self,db,release,actor):
        self._release_profile(db,release['snapshot_id'],release['resource_id'],release['tool'])
        bound,_,_=self.execution._binding(db,release['workspace_id'],release['draft_id'],release['snapshot_id'],actor)
        if any(bound[k]!=release[k] for k in ('snapshot_hash','definition_hash','snapshot_revision','resource_id','binding_hash')):raise WorkspaceDenied()
    def deployments(self,ws,draft,snapshot,rid,actor):
        with self.access._tx(actor) as (db,_):
            self.execution._scope(ws,draft,snapshot,actor);_,value=self._release(db,rid,active=False);self._scope(value,ws,draft,snapshot)
            result=[]
            for row in _rows(db,'SELECT * FROM workspace_release_deployments WHERE release_id=? ORDER BY created DESC LIMIT 100',(rid,)):
                _,v=self._deployment(db,row['app_id'],active=False);result.append({**self._dto(row,True),'allowed_origins':v['allowed_origins']})
            return result
    def revoke_deployment(self,ws,draft,snapshot,app,body,actor):
        if type(body) is not dict or set(body)!={'revision'} or not _revision(body['revision']):raise WorkspaceInvalid()
        with self.access._tx(actor,write=True) as (db,_):
            self._owner(ws,actor);row,value=self._deployment(db,app,active=False);_,release=self._release(db,value['release_id'],active=False);self._scope(release,ws,draft,snapshot)
            if row['revision']!=body['revision'] or not row['active']:raise WorkspaceConflict()
            row.update(active=0,revision=row['revision']+1,revoked=_now());db.execute('UPDATE workspace_release_deployments SET active=0,revision=?,revoked=?,state_signature=? WHERE app_id=?',(row['revision'],row['revoked'],self._state(row,'deployment'),app));return self._dto(row,True)
    def package_config(self,ws,draft,snapshot,app,actor):
        with self.access._tx(actor) as (db,_):
            self._owner(ws,actor);_,value=self._deployment(db,app);_,release=self._release(db,value['release_id']);self._scope(release,ws,draft,snapshot);self._admin_current(db,release,actor)
            return {'app_id':app,'profile':SDK_PROFILE,'sdk_version':'2.0.0','allowed_origins':value['allowed_origins'],'release_id':release['id']}
    def _customer(self,db,actor,ws,purpose='execute'):
        if self.identity is None or self.customer_executor is None or self.customer_executor.authority_guard!=self.guard_ticket:raise WorkspaceDenied()
        from .customer_identity import CustomerActor
        if getattr(actor,'principal_kind',None)=='customer':actor=CustomerActor(actor.customer_id,actor.session_ref,actor.token_ref)
        return self.identity.authorize(db,actor,ws,purpose)
    def _customer_current(self,db,release,actor):
        self._release_profile(db,release['snapshot_id'],release['resource_id'],release['tool'])
        self._customer(db,actor,release['workspace_id'])
        scope=self._customer(db,actor,release['workspace_id'])
        bound,_,_=self.customer_executor._binding(db,release['workspace_id'],release['draft_id'],release['snapshot_id'],self.customer_executor.access.from_scope(scope))
        if any(bound[k]!=release[k] for k in ('snapshot_hash','definition_hash','snapshot_revision','resource_id','binding_hash')):raise WorkspaceDenied()
        return bound
    def authorize(self,app,body,actor):
        if type(body) is not dict or set(body)!={'origin','redirect_uri','challenge','state'}:raise WorkspaceInvalid()
        target=origin(body['origin'])
        if body['redirect_uri']!=target+'/bff/callback' or type(body['challenge']) is not str or not re.fullmatch('[A-Za-z0-9_-]{43}',body['challenge']) or type(body['state']) is not str or not re.fullmatch('[A-Za-z0-9_-]{32,128}',body['state']):raise WorkspaceInvalid()
        with self.execution._internal() as db:
            grant,value=self._deployment(db,app);release_row,release=self._release(db,value['release_id']);self._customer_current(db,release,actor)
            scope=self._customer(db,actor,release['workspace_id'])
            if target not in value['allowed_origins']:raise WorkspaceDenied()
            if db.execute("SELECT COUNT(*) FROM workspace_app_codes WHERE app_id=? AND json_extract(payload,'$.created')>?",(app,_now()-86400)).fetchone()[0]>=1000 or db.execute("SELECT COUNT(*) FROM workspace_app_codes WHERE app_id=? AND consumed IS NULL AND json_extract(payload,'$.expires')>? AND json_extract(payload,'$.customer_id')=?",(app,_now(),actor.customer_id)).fetchone()[0]>=20:raise WorkspaceConflict()
            code=secrets.token_urlsafe(32);claims={'app_id':app,'release_id':release['id'],'grant_revision':grant['revision'],'release_revision':release_row['revision'],'origin':target,'redirect_uri':body['redirect_uri'],'challenge':body['challenge'],'customer_id':actor.customer_id,'session_ref':actor.session_ref,'link_revision':scope['link_revision'],'workspace_revision':scope['workspace_revision'],'code_ref':self._ref(code),'created':_now(),'expires':min(_now()+60,value['expires'],scope['session_expires'])}
            db.execute('INSERT INTO workspace_app_codes VALUES(?,?,?,?,NULL)',(self._ref(code),app,_canonical(claims),self._sign(claims)))
            return {'code':code,'state':body['state'],'redirect_uri':body['redirect_uri'],'expires':claims['expires']}
    def _token(self,db,app,raw,audience,request_origin,*,current=True):
        if type(raw) is not str or not re.fullmatch('[A-Za-z0-9_-]{43}',raw):raise WorkspaceDenied()
        rows=_rows(db,'SELECT * FROM workspace_app_tokens WHERE token_hash=? AND app_id=? AND audience=?',(self._ref(raw),app,audience))
        if len(rows)!=1:raise WorkspaceDenied()
        value=self._open(rows[0])
        if value.get('token_ref')!=self._ref(raw) or value['app_id']!=app or value['audience']!=audience or value['origin']!=origin(request_origin) or value['expires']<=_now():raise WorkspaceDenied()
        from .customer_identity import CustomerActor
        actor=CustomerActor(value['customer_id'],value['session_ref']);_,deployment=self._deployment(db,app,active=current);row,release=self._release(db,deployment['release_id'],active=current)
        if value['release_id']!=release['id']:raise WorkspaceDenied()
        scope=self._customer(db,actor,release['workspace_id'],'execute' if audience=='app-run' else 'read')
        if current:
            grant,_=self._deployment(db,app)
            if value['grant_revision']!=grant['revision'] or value['release_revision']!=row['revision'] or value['link_revision']!=scope['link_revision'] or value['workspace_revision']!=scope['workspace_revision']:raise WorkspaceDenied()
            self._customer_current(db,release,actor)
        return value,actor,release
    def _issue_token(self,db,app,claims,audience,run_id=None):
        if db.execute("SELECT COUNT(*) FROM workspace_app_tokens WHERE app_id=? AND json_extract(payload,'$.created')>?",(app,_now()-86400)).fetchone()[0]>=1000:raise WorkspaceConflict()
        raw=secrets.token_urlsafe(32);value={**claims,'app_id':app,'audience':audience,'run_id':run_id,'token_ref':self._ref(raw),'created':_now(),'expires':min(_now()+300,claims['expires'])}
        db.execute('INSERT INTO workspace_app_tokens VALUES(?,?,?,?,?)',(self._ref(raw),app,audience,_canonical(value),self._sign(value)))
        return {'access_token':raw,'audience':audience,'expires':value['expires']}
    def exchange(self,app,body,request_origin):
        if type(body) is not dict or set(body)!={'code','verifier','redirect_uri'} or type(body['code']) is not str or not re.fullmatch('[A-Za-z0-9_-]{43}',body['code']) or type(body['verifier']) is not str or not re.fullmatch('[A-Za-z0-9_-]{43,128}',body['verifier']):raise WorkspaceInvalid()
        with self.execution._internal() as db:
            rows=_rows(db,'SELECT * FROM workspace_app_codes WHERE code_hash=? AND app_id=?',(self._ref(body['code']),app))
            if len(rows)!=1:raise WorkspaceDenied()
            row=rows[0];value=self._open(row);challenge=base64.urlsafe_b64encode(hashlib.sha256(body['verifier'].encode()).digest()).decode().rstrip('=')
            if value.get('code_ref')!=row['code_hash'] or row['consumed'] is not None or value['expires']<=_now() or value['origin']!=origin(request_origin) or body['redirect_uri']!=value['redirect_uri'] or challenge!=value['challenge']:raise WorkspaceDenied()
            from .customer_identity import CustomerActor
            actor=CustomerActor(value['customer_id'],value['session_ref']);grant,deployment=self._deployment(db,app);release_row,release=self._release(db,deployment['release_id']);self._customer_current(db,release,actor)
            scope=self._customer(db,actor,release['workspace_id'])
            if value['grant_revision']!=grant['revision'] or value['release_revision']!=release_row['revision'] or value['link_revision']!=scope['link_revision'] or value['workspace_revision']!=scope['workspace_revision']:raise WorkspaceDenied()
            if db.execute('UPDATE workspace_app_codes SET consumed=? WHERE code_hash=? AND consumed IS NULL',(_now(),row['code_hash'])).rowcount!=1:raise WorkspaceDenied()
            value['expires']=min(_now()+300,deployment['expires'],scope['session_expires'])
            return self._issue_token(db,app,value,'app-run')
    def prepare(self,app,raw,request_origin):
        with self.execution._internal() as db:
            value,actor,release=self._token(db,app,raw,'app-run',request_origin)
            runtime_actor=self.customer_executor.access.from_scope(self._customer(db,actor,release['workspace_id']))
        plan=self.customer_executor.prepare(release['workspace_id'],release['draft_id'],release['snapshot_id'],{'snapshot_revision':release['snapshot_revision']},runtime_actor)
        with self.execution._internal() as db:
            self._token(db,app,raw,'app-run',request_origin)
            ticket,claims=self.customer_executor._ticket(db,plan['ticket_id'],release['workspace_id'],release['draft_id'],release['snapshot_id'])
            if claims['binding_hash']!=release['binding_hash']:raise WorkspaceDenied()
            link={'ticket_id':ticket['id'],'app_id':app,'token_hash':self._ref(raw),'origin':value['origin'],'customer_id':actor.customer_id,'session_ref':actor.session_ref,'release_id':release['id'],'created':_now()}
            db.execute('INSERT INTO workspace_app_run_links VALUES(?,?,?,?,?)',(ticket['id'],app,self._ref(raw),_canonical(link),self._sign(link)))
        return {**plan,'notice':RUN_NOTICE,'profile':SDK_PROFILE}
    def guard_ticket(self,db,ticket,claims=None):
        tid=ticket['id'] if type(ticket) is dict else ticket
        rows=_rows(db,'SELECT * FROM workspace_app_run_links WHERE ticket_id=?',(tid,))
        if len(rows)!=1:raise WorkspaceDenied()
        link=self._link(rows[0]);tokens=_rows(db,'SELECT * FROM workspace_app_tokens WHERE token_hash=?',(link['token_hash'],))
        if len(tokens)!=1:raise WorkspaceDenied()
        value=self._open(tokens[0])
        if value.get('token_ref')!=link['token_hash'] or value['app_id']!=link['app_id'] or value['audience']!='app-run':raise WorkspaceDenied()
        from .customer_identity import CustomerActor
        actor=CustomerActor(value['customer_id'],value['session_ref']);grant,deployment=self._deployment(db,link['app_id']);row,release=self._release(db,link['release_id'])
        if deployment['release_id']!=release['id'] or value['release_id']!=release['id']:raise WorkspaceDenied()
        ticket_row,ticket_claims=self.customer_executor._ticket(db,tid,release['workspace_id'],release['draft_id'],release['snapshot_id'])
        if ticket_claims.get('actor_kind')!='customer' or ticket_claims['actor_user_id']!=link['customer_id'] or ticket_claims['session_ref']!=link['session_ref'] or any(ticket_claims[k]!=release[k] for k in ('snapshot_hash','definition_hash','snapshot_revision','resource_id','binding_hash')):raise WorkspaceDenied()
        scope=self._customer(db,actor,release['workspace_id'])
        if value['expires']<=_now() or value['grant_revision']!=grant['revision'] or value['release_revision']!=row['revision'] or value['link_revision']!=scope['link_revision'] or value['workspace_revision']!=scope['workspace_revision'] or link['origin']!=value['origin']:raise WorkspaceDenied()
        self._customer_current(db,release,actor)
        return True
    def execute(self,app,raw,body,request_origin):
        if type(body) is not dict or set(body)!={'ticket_id','authorized','notice'} or body['authorized'] is not True or body['notice']!=RUN_NOTICE:raise WorkspaceInvalid()
        with self.execution._internal() as db:
            value,actor,release=self._token(db,app,raw,'app-run',request_origin);rows=_rows(db,'SELECT * FROM workspace_app_run_links WHERE ticket_id=? AND app_id=?',(body['ticket_id'],app))
            if len(rows)!=1 or rows[0]['token_hash']!=self._ref(raw):raise WorkspaceDenied()
            self._link(rows[0]);self.guard_ticket(db,body['ticket_id'])
            deployment=self._deployment(db,app)[1]
            existing=db.execute('SELECT ticket_id FROM workspace_app_admissions WHERE ticket_id=?',(body['ticket_id'],)).fetchone()
            if not existing:
                for seconds,limit in ((60,deployment['minute_limit']),(86400,deployment['day_limit'])):
                    if db.execute('SELECT COUNT(*) FROM workspace_app_admissions WHERE app_id=? AND created>?',(app,_now()-seconds)).fetchone()[0]>=limit:raise WorkspaceConflict()
                db.execute('INSERT INTO workspace_app_admissions VALUES(?,?,?)',(body['ticket_id'],app,_now()))
            runtime_actor=self.customer_executor.access.from_scope(self._customer(db,actor,release['workspace_id']))
        result=self.customer_executor.execute(release['workspace_id'],release['draft_id'],release['snapshot_id'],{**body,'notice':PRIVATE_NOTICE},runtime_actor)
        with self.execution._internal() as db:
            self._customer(db,actor,release['workspace_id'],'read');cap=self._issue_token(db,app,value,'run-status',result['id'])
        return {'profile':SDK_PROFILE,'run':result,'status_capability':cap}
    def history(self,app,raw,request_origin):
        with self.execution._internal() as db:
            value,actor,release=self._token(db,app,raw,'app-run',request_origin,current=False)
            rows=_rows(db,'SELECT l.* FROM workspace_app_run_links l JOIN workspace_private_tickets t ON t.id=l.ticket_id WHERE l.app_id=? AND t.run_id IS NOT NULL ORDER BY l.rowid DESC LIMIT 30',(app,))
            found=[]
            for row in rows:
                link=self._link(row)
                if link['customer_id']!=actor.customer_id or link['session_ref']!=actor.session_ref:continue
                ticket=db.execute('SELECT run_id FROM workspace_private_tickets WHERE id=?',(row['ticket_id'],)).fetchone()
                _,t,_,payload=self.customer_executor._load_run(db,ticket[0],release['workspace_id'],release['draft_id'],release['snapshot_id']);found.append(self.customer_executor._dto(payload,t,output=False))
            return found
    def status_capability(self,app,raw,run_id,request_origin):
        with self.execution._internal() as db:
            value,actor,release=self._token(db,app,raw,'app-run',request_origin,current=False)
            row,_,_,_=self.customer_executor._load_run(db,run_id,release['workspace_id'],release['draft_id'],release['snapshot_id'])
            links=_rows(db,'SELECT * FROM workspace_app_run_links WHERE ticket_id=? AND app_id=?',(row['ticket_id'],app))
            if len(links)!=1:raise WorkspaceDenied()
            link=self._link(links[0])
            if link['customer_id']!=actor.customer_id or link['session_ref']!=actor.session_ref:raise WorkspaceDenied()
            return self._issue_token(db,app,value,'run-status',run_id)
    def status(self,app,raw,run_id,request_origin):
        with self.execution._internal() as db:
            value,actor,release=self._token(db,app,raw,'run-status',request_origin,current=False)
            if value['run_id']!=run_id:raise WorkspaceDenied()
            runtime_actor=self.customer_executor.access.from_scope(self._customer(db,actor,release['workspace_id'],'read'))
        return self.customer_executor.run(release['workspace_id'],release['draft_id'],release['snapshot_id'],run_id,runtime_actor)
