"""Private literal product-v2 compilation and separate actual contract proof."""
import hashlib
import hmac
import json
import secrets
import time

from .capability_registry import Registry,version_parts,digest
from .workflow_product_semantics import CONTRACT_ID,validate,registered_tool,ProductSemantics
from .workspace_access import PROFILE as SNAPSHOT_PROFILE,WorkspaceDenied,WorkspaceConflict,WorkspaceInvalid,LIMITS,_canonical,_hash,_rows,_tree,_safe_text
from .workspace_execution import NOTICE as PRIVATE_NOTICE

PROFILE='workspace-products-compare-v2'
NOTICE='workspace-products-test-v2'
SCHEMA=(
'''CREATE TABLE IF NOT EXISTS workspace_product_compositions(snapshot_id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,draft_id TEXT NOT NULL,proposal_id TEXT UNIQUE NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
'''CREATE TABLE IF NOT EXISTS workspace_product_contract_results(run_id TEXT PRIMARY KEY,snapshot_id TEXT NOT NULL,outcome TEXT NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''')


def stable(value):
    if type(value) is float and value.is_integer():return int(value)
    if type(value) is dict:return {k:stable(v) for k,v in value.items()}
    if type(value) is list:return [stable(v) for v in value]
    return value


class ProductComposer:
    def __init__(self,execution,registry=None):
        self.execution,self.access,self.store=execution,execution.access,execution.store
        self.registry=registry or Registry(self.store)
        self.key=hmac.new(self.access.key,PROFILE.encode(),hashlib.sha256).digest()
        from .private_artifact_keys import ArtifactSigner
        self.signer=ArtifactSigner(self.key,PROFILE)
        with execution._internal() as db:
            for sql in SCHEMA:db.execute(sql)
    def sign(self,value):return self.signer.sign(stable(value))
    def verify(self,value,signature):return self.signer.verify(stable(value),signature)
    def owner(self,actor):return hmac.new(self.key,_canonical({'user_id':actor.user_id,'session_ref':actor.session_ref}).encode('ascii'),hashlib.sha256).hexdigest()
    def pin(self,rid):
        if type(rid) is not int or not 0<rid<2**31:raise WorkspaceInvalid()
        from .concierge.execution_policy import admit
        resource=self.store.resource(rid)
        try:
            admit(resource,'mcp',public=True);parts=version_parts(resource);vid='cv_'+digest([rid,*parts[:3]])[:32]
            rows=_rows(self.store._db,'SELECT v.*,a.agent_ref FROM connection_versions v JOIN connection_agents a ON a.resource_id=v.resource_id WHERE v.id=?',(vid,))
            if len(rows)!=1 or not parts[3] or parts[2]!='mcp-stateless-v1':raise WorkspaceDenied()
            version={k:rows[0][k] for k in ('id','resource_id','agent_ref','binding_hash','schema_hash','profile_version','schema_complete')}
            approvals=_rows(self.store._db,'SELECT tool,created FROM capability_approvals WHERE version_id=? AND contract_id=?',(vid,CONTRACT_ID))
            if len(approvals)!=1 or not registered_tool(resource,approvals[0]['tool']):raise WorkspaceDenied()
            projection=self.registry.projection(resource,version=version)
            if not projection.get('connection_readiness',{}).get('verified_callable') or not any(c['id']==CONTRACT_ID and c['verified'] for c in projection.get('capability_contracts',[])):raise WorkspaceDenied()
            return stable({'resource_id':rid,'version':version,'approval':approvals[0]})
        except (ValueError,TypeError,KeyError):raise WorkspaceDenied() from None
    def options(self,ws,actor):
        with self.access._tx(actor) as (db,user):
            membership,_=self.access._access(ws,actor);items=[]
            rows=_rows(db,'SELECT DISTINCT resource_id FROM connection_versions v JOIN capability_approvals a ON a.version_id=v.id WHERE a.contract_id=? ORDER BY resource_id LIMIT 100',(CONTRACT_ID,))
            for row in rows:
                try:pin=self.pin(row['resource_id'])
                except WorkspaceDenied:continue
                items.append({'resource_id':pin['resource_id'],'label':'Verified product agent '+str(len(items)+1)})
            return {'profile':PROFILE,'available':bool(items),'candidates':items,'can_edit':user['role']!='operator' and membership['member_role'] in ('owner','editor'),'contract_id':CONTRACT_ID,'fallback':False,'publication':False,'deployment':False,'automatic_ranking':False}
    def prepare(self,ws,body,actor):
        _tree(body)
        if type(body) is not dict or set(body)!={'resource_id','input'}:raise WorkspaceInvalid()
        validate(body['input'])
        with self.access._tx(actor,write=True):
            self.access._access(ws,actor,write=True);pin=self.pin(body['resource_id']);now=time.time()
            p=stable({'profile':PROFILE,'id':'pc_'+secrets.token_hex(16),'workspace_id':ws,'owner':self.owner(actor),'created':now,'expires':now+600,'pin':pin,'input':body['input']})
            return {'profile':PROFILE,'proposal':p,'signature':self.sign(p),'preview':{'contract_id':CONTRACT_ID,'tool':pin['approval']['tool'],'resource_id':pin['resource_id'],'input':p['input'],'provider_calls':0,'expert_reviewed':False,'live_contract_pass':False}}
    def unpack(self,ws,body,actor):
        p=body.get('proposal')
        if type(p) is not dict or type(body.get('signature')) is not str:raise WorkspaceInvalid()
        _tree(p)
        if not self.verify(p,body['signature']) or p['profile']!=PROFILE or p['workspace_id']!=ws or p['owner']!=self.owner(actor) or not p['created']<=time.time()<p['expires']:raise WorkspaceDenied()
        validate(p['input'])
        if p['pin']!=self.pin(p['pin']['resource_id']):raise WorkspaceDenied()
        return p
    def save(self,ws,body,actor):
        if type(body) is not dict or set(body)!={'proposal','signature','name','description'}:raise WorkspaceInvalid()
        _safe_text(body['name'],120);_safe_text(body['description'],1000,empty=True)
        with self.access._tx(actor,write=True) as (db,_):
            self.access._access(ws,actor,write=True);p=self.unpack(ws,body,actor)
            old=_rows(db,'SELECT * FROM workspace_product_compositions WHERE proposal_id=?',(p['id'],))
            if old:
                value=self.open_sidecar(old[0]);self.access._version_row(ws,value['draft_id'],value['snapshot_id']);return {'draft_id':value['draft_id'],'snapshot_id':value['snapshot_id'],'replayed':True}
            if db.execute('SELECT COUNT(*) FROM workspace_drafts WHERE workspace_id=?',(ws,)).fetchone()[0]>=LIMITS['drafts']:raise WorkspaceConflict()
            definition={'nodes':[{'id':'start','name':'Manual product test','type':'trigger','kind':'trigger','data':{}},{'id':'products','name':'Selected product evidence','type':'agent','kind':'mcp','resource_id':p['pin']['resource_id'],'data':{'tool':p['pin']['approval']['tool'],'input':p['input']}}],'edges':[{'source':'start','target':'products'}]}
            self.access._definition(definition,db);now=time.time();did='wd_'+secrets.token_hex(16);sid='wv_'+secrets.token_hex(16)
            draft={'id':did,'workspace_id':ws,'name':body['name'],'description':body['description'],'definition':definition,'revision':1,'active':1,'created_by':actor.user_id,'created':now,'updated':now};payload=self.access._draft_payload(draft)
            db.execute('INSERT INTO workspace_drafts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(did,ws,body['name'],body['description'],_canonical(definition),1,1,actor.user_id,now,now,_hash(payload),self.access._sign(payload)))
            snapshot={'profile':SNAPSHOT_PROFILE,'workspace_id':ws,'draft_id':did,'id':sid,'ordinal':1,'draft_revision':1,'created_by':actor.user_id,'created':now,'snapshot':{k:draft[k] for k in ('name','description','definition')}}
            state={'id':sid,'workspace_id':ws,'draft_id':did,'revision':1,'active':1,'revoked':None,'payload_hash':_hash(snapshot)}
            db.execute('INSERT INTO workspace_versions VALUES(?,?,?,?,?,1,1,?,?,NULL,?,?,?,?)',(sid,ws,did,1,1,actor.user_id,now,_canonical(snapshot),state['payload_hash'],self.access._sign(snapshot),self.access._sign(state)))
            sidecar={'profile':PROFILE,'workspace_id':ws,'draft_id':did,'snapshot_id':sid,'snapshot_hash':state['payload_hash'],'definition_hash':_hash(definition),'pin':p['pin'],'input':p['input'],'proposal_id':p['id'],'created':now,'fallback':False,'release_allowed':False}
            db.execute('INSERT INTO workspace_product_compositions VALUES(?,?,?,?,?,?)',(sid,ws,did,p['id'],_canonical(sidecar),self.sign(sidecar)));self.access._audit(db,actor,ws,'product.compile',sid,1)
            self.access._open_draft(self.access._draft_row(ws,did));self.access._open_version(self.access._version_row(ws,did,sid))
            return {'draft_id':did,'snapshot_id':sid,'replayed':False,'contract_id':CONTRACT_ID,'provider_calls':0,'release_allowed':False}
    def open_sidecar(self,row):
        try:
            value=json.loads(row['payload']);_tree(value)
            if type(value) is not dict or value.get('profile')!=PROFILE or not self.verify(value,row['signature']) or any(value[k]!=row[k] for k in ('snapshot_id','workspace_id','draft_id','proposal_id')):raise WorkspaceConflict()
            return value
        except (ValueError,TypeError,KeyError):raise WorkspaceConflict() from None
    def current(self,db,ws,draft,snapshot,actor):
        self.execution._scope(ws,draft,snapshot,actor,write=True);rows=_rows(db,'SELECT * FROM workspace_product_compositions WHERE snapshot_id=? AND workspace_id=? AND draft_id=?',(snapshot,ws,draft))
        if len(rows)!=1:raise WorkspaceDenied()
        value=self.open_sidecar(rows[0]);row=self.access._version_row(ws,draft,snapshot)
        if row['payload_hash']!=value['snapshot_hash'] or self.pin(value['pin']['resource_id'])!=value['pin']:raise WorkspaceDenied()
        return value
    def prepare_test(self,ws,draft,snapshot,actor):
        with self.access._tx(actor,write=True) as (db,_):self.current(db,ws,draft,snapshot,actor)
        result=self.execution.prepare(ws,draft,snapshot,{'snapshot_revision':1},actor)
        with self.access._tx(actor,write=True) as (db,_):self.current(db,ws,draft,snapshot,actor)
        return {**result,'profile':PROFILE,'notice':NOTICE}
    def test(self,ws,draft,snapshot,body,actor):
        if type(body) is not dict or set(body)!={'ticket_id','authorized','notice'} or body['authorized'] is not True or body['notice']!=NOTICE:raise WorkspaceInvalid()
        with self.access._tx(actor,write=True) as (db,_):sidecar=self.current(db,ws,draft,snapshot,actor)
        if self.execution.authority_guard!=self.guard_ticket:raise WorkspaceDenied()
        result=self.execution.execute(ws,draft,snapshot,{**body,'notice':PRIVATE_NOTICE},actor)
        with self.access._tx(actor,write=True) as (db,_):
            old=_rows(db,'SELECT * FROM workspace_product_contract_results WHERE run_id=?',(result['id'],))
            if old:
                proof=json.loads(old[0]['payload'])
                if (not self.verify(proof,old[0]['signature']) or proof.get('run_id')!=result['id'] or proof.get('snapshot_id')!=snapshot or proof.get('outcome')!=old[0]['outcome'] or old[0]['snapshot_id']!=snapshot):raise WorkspaceConflict()
                return {'run':result,'contract_proof':proof,'replayed':True}
            outcome='failed';normalized=None
            if result['status']=='succeeded':
                try:
                    self.current(db,ws,draft,snapshot,actor);raw=result['output'];output=raw.get('structuredContent',raw) if type(raw) is dict else raw
                    normalized=ProductSemantics().validate({'input':sidecar['input'],'output':output})
                    normalized.update(origin='retained_private_execution',assessment='typed_structure_valid');normalized['claims']['live_execution']=True;outcome='passed'
                except (ValueError,TypeError,KeyError):pass
            proof={'profile':PROFILE,'run_id':result['id'],'snapshot_id':snapshot,'input_hash':_hash(sidecar['input']),'sidecar_hash':_hash(sidecar),'outcome':outcome,'transport_status':result['status'],'created':time.time(),'normalized':normalized,'expert_reviewed':False,'source_verified':False,'automatic_ranking':False}
            db.execute('INSERT INTO workspace_product_contract_results VALUES(?,?,?,?,?)',(result['id'],snapshot,outcome,_canonical(proof),self.sign(proof)))
            return {'run':result,'contract_proof':proof,'replayed':False}

    def guard_ticket(self,db,ticket,claims=None):
        claims=claims if claims is not None else json.loads(ticket['payload'])
        rows=_rows(db,'SELECT * FROM workspace_product_compositions WHERE snapshot_id=?',(claims['snapshot_id'],))
        if not rows:return True
        actor=self.execution._actor_from_claims(claims)
        value=self.current(db,claims['workspace_id'],claims['draft_id'],claims['snapshot_id'],actor)
        if any(value[k]!=claims[k] for k in ('workspace_id','draft_id','snapshot_id','snapshot_hash')) or value['definition_hash']!=claims['definition_hash']:raise WorkspaceDenied()
        return True

    def result(self,ws,draft,snapshot,run_id,actor):
        with self.access._tx(actor) as (db,_):
            self.execution._scope(ws,draft,snapshot,actor)
            rows=_rows(db,'SELECT * FROM workspace_product_contract_results WHERE run_id=? AND snapshot_id=?',(run_id,snapshot))
            if len(rows)!=1:raise WorkspaceDenied()
            proof=json.loads(rows[0]['payload'])
            if not self.verify(proof,rows[0]['signature']) or proof.get('run_id')!=run_id or proof.get('snapshot_id')!=snapshot or proof.get('outcome')!=rows[0]['outcome']:raise WorkspaceConflict()
            return proof
