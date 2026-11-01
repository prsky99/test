"""Encrypted single-use preparations and customer-approved durable execution."""
import hashlib
import hmac
import json
import re
import time
import logging

from ..capability_registry import Registry,digest
from ..capability_contracts import CONTRACTS,validate
from ..concierge.discovery_state import execution_state,registered_tools
from ..concierge.execution_policy import admit_tool,ExecutionDenied
from ..workflow_persistence import dispatch_scope
from .storage import transaction,identity

NOTICE='agent-informational-execution-v1'
SUPPORTED=('news.search.v1','docs.search.v1')


class Tasks:
    def __init__(self,front,identity_core=None):
        self.front=front;self.store=front.store;self.identity_core=identity_core

    def pin(self,rid,contract,arguments):
        resource=self.store.resource(rid)
        state=execution_state(self.store,resource)
        if not state['verified']or resource.get('kind')!='mcp'or contract not in SUPPORTED:
            raise ValueError('UNSUPPORTED_CONTRACT')
        version=Registry(self.store).current(resource,create=False)
        if not version:raise ValueError('NOT_VERIFIED')
        projection=Registry(self.store).projection(resource,version=version,strict=True)
        if not any(c['id']==contract and c['verified']for c in projection['capability_contracts']):
            raise ValueError('NOT_VERIFIED')
        approvals=self.store.query('SELECT tool FROM capability_approvals WHERE version_id=? AND contract_id=?',(version['id'],contract))
        if len(approvals)!=1:raise ValueError('UNSUPPORTED_CONTRACT')
        tool=approvals[0]['tool'];spec=next((t for t in registered_tools(resource)if t.get('name')==tool),{})
        if spec.get('inputSchema')!=CONTRACTS[contract]['input_schema']or spec.get('outputSchema')!=CONTRACTS[contract]['output_schema']:
            raise ValueError('SCHEMA_CHANGED')
        hints=spec.get('annotations')or{}
        if hints.get('readOnlyHint')is not True or hints.get('destructiveHint')is not False or hints.get('idempotentHint')is not True:
            raise ValueError('POLICY_DENIED')
        admit_tool(resource,tool,arguments);validate(contract,arguments)
        return {'resource_id':rid,'version_id':version['id'],'tool':tool,'contract_id':contract,
                'input_hash':digest(arguments),'expires':min(time.time()+300,state['expires_at'])}

    def prepare(self,owner,rid,contract,arguments):
        pin=self.pin(rid,contract,arguments);ident=identity('ap')
        sealed=self.front.updates._seal({'arguments':arguments,'pin':pin,'owner':owner},ident)
        with transaction(self.store)as db:
            if db.execute('SELECT COUNT(*) FROM adoption_preparations WHERE owner=? AND expires>?',(owner,time.time())).fetchone()[0]>=20:
                raise ValueError('SERVICE_BUSY')
            db.execute('INSERT INTO adoption_preparations VALUES (?,?,?,?,?,?,?,?,?,?)',
                (ident,owner,pin['resource_id'],pin['version_id'],pin['tool'],pin['contract_id'],pin['input_hash'],sealed,time.time(),pin['expires']))
        return {'preparation_id':ident,'resource_id':rid,'expires_at':pin['expires'],
                'status':'authorization_required','notice':NOTICE,'execution_authorized':False}

    def preparation(self,owner,ident):
        if type(ident)is not str or not re.fullmatch('ap_[0-9a-f]{32}',ident):raise ValueError('INVALID_INPUT')
        rows=self.store.query('SELECT * FROM adoption_preparations WHERE id=? AND owner=?',(ident,owner))
        if not rows:raise ValueError('NOT_FOUND')
        row=dict(rows[0])
        if row['expires']<=time.time():raise ValueError('EXPIRED')
        saved=self.front.updates._open(row['sealed'],ident)
        if saved['owner']!=owner or any(saved['pin'][k]!=row[k]for k in ('resource_id','version_id','tool','contract_id','input_hash','expires')):
            raise ValueError('POLICY_DENIED')
        arguments=saved['arguments']
        pin=self.pin(row['resource_id'],row['contract_id'],arguments)
        if any(pin[k]!=row[k]for k in ('version_id','tool','input_hash')):raise ValueError('SCHEMA_CHANGED')
        return row,arguments

    def authorize(self,owner,ident,actor,body):
        if (type(body)is not dict or set(body)!={'authorized','input_sharing','notice'}or
                body['authorized']is not True or body['input_sharing']is not True or body['notice']!=NOTICE):raise ValueError('AUTHORIZATION_REQUIRED')
        row,_=self.preparation(owner,ident)
        token=identity('axg');key=hashlib.sha256(token.encode()).hexdigest()
        with transaction(self.store)as db:
            self.identity_core._session(db,actor.session_ref,actor.customer_id)
            created=time.time()
            proof=self._proof(key,owner,ident,actor.customer_id,actor.session_ref,created,row['expires'])
            db.execute('INSERT INTO adoption_grants VALUES (?,?,?,?,?,?,?,?,?,?)',
                (key,owner,ident,actor.customer_id,actor.session_ref,created,row['expires'],0,0,proof))
        return {'grant':token,'expires_at':row['expires'],'single_use':True}

    def _proof(self,*fields):
        return hmac.new(self.front.updates.key,('adoption-grant-v1:'+json.dumps(fields,separators=(',',':'))).encode(),hashlib.sha256).hexdigest()

    def _grant(self,db,owner,prep,token,*,used=False):
        if type(token)is not str or not re.fullmatch('axg_[0-9a-f]{32}',token):raise ValueError('AUTHORIZATION_REQUIRED')
        key=hashlib.sha256(token.encode()).hexdigest()
        rows=db.execute('SELECT * FROM adoption_grants WHERE id=? AND owner=? AND preparation_id=?',(key,owner,prep)).fetchall()
        if not rows:raise ValueError('AUTHORIZATION_REQUIRED')
        row=dict(rows[0])
        return self._validated_grant(db,row,used=used)

    def _validated_grant(self,db,row,*,used=False):
        proof=self._proof(*[row[k]for k in ('id','owner','preparation_id','customer_id','session_ref','created','expires')])
        if not hmac.compare_digest(row['proof'],proof):raise ValueError('AUTHORIZATION_REQUIRED')
        if row['revoked']or row['expires']<=time.time()or not used and row['used']:raise ValueError('AUTHORIZATION_REQUIRED')
        if self.identity_core is None:raise ValueError('AUTHORIZATION_REQUIRED')
        self.identity_core._session(db,row['session_ref'],row['customer_id'])
        return row

    def operation(self,owner,ident):
        rows=self.store.query('SELECT * FROM adoption_operations WHERE id=? AND owner=?',(ident,owner))
        if not rows:raise ValueError('NOT_FOUND')
        row=dict(rows[0]);status=row['status']
        with self.store.tx()as db:
            grants=db.execute('SELECT * FROM adoption_grants WHERE id=? AND owner=? AND preparation_id=?',
                              (row['grant_id'],owner,row['preparation_id'])).fetchall()
            if not grants:raise ValueError('AUTHORIZATION_REQUIRED')
            self._validated_grant(db,dict(grants[0]),used=True)
        if status in ('prepared','dispatched')and row['updated']<time.time()-120:
            with transaction(self.store)as db:
                db.execute("UPDATE adoption_operations SET status='unknown',updated=? WHERE id=? AND status IN ('prepared','dispatched')",(time.time(),ident))
            status='unknown'
        result={'operation_id':ident,'status':status,'retry_safe':False}
        if row['sealed']:result['result']=self.front.updates._open(row['sealed'],ident)
        return result

    def cancel(self,owner,ident):
        self.operation(owner,ident)
        with transaction(self.store)as db:
            db.execute("UPDATE adoption_operations SET status='cancelled',updated=? WHERE id=? AND owner=? AND status='prepared'",(time.time(),ident,owner))
        return self.operation(owner,ident)

    def execute(self,owner,prep,token,request_key):
        if type(request_key)is not str or not re.fullmatch('[A-Za-z0-9_.:-]{1,128}',request_key):raise ValueError('INVALID_INPUT')
        request_key=digest(request_key)
        with transaction(self.store)as db:
            old=db.execute('SELECT * FROM adoption_operations WHERE owner=? AND request_key=?',(owner,request_key)).fetchone()
            if old:
                if old['preparation_id']!=prep:raise ValueError('IDEMPOTENCY_CONFLICT')
                self._grant(db,owner,prep,token,used=True)
                return self.operation(owner,old['id'])
        row,arguments=self.preparation(owner,prep);ident=identity('axo')
        with transaction(self.store)as db:
            old=db.execute('SELECT id,preparation_id FROM adoption_operations WHERE owner=? AND request_key=?',(owner,request_key)).fetchone()
            if old:
                if old['preparation_id']!=prep:raise ValueError('IDEMPOTENCY_CONFLICT')
                self._grant(db,owner,prep,token,used=True)
                return self.operation(owner,old['id'])
            grant=self._grant(db,owner,prep,token)
            if db.execute('SELECT id FROM adoption_operations WHERE preparation_id=?',(prep,)).fetchone():raise ValueError('IDEMPOTENCY_CONFLICT')
            db.execute('UPDATE adoption_grants SET used=1 WHERE id=? AND used=0',(grant['id'],))
            db.execute('INSERT INTO adoption_operations VALUES (?,?,?,?,?,?,?,?,?,?)',
                (ident,owner,prep,request_key,grant['id'],'prepared',None,time.time(),time.time(),None))
        dispatched=[False]
        def guard():
            self.preparation(owner,prep)
            with transaction(self.store)as db:
                self._grant(db,owner,prep,token,used=True)
                changed=db.execute("UPDATE adoption_operations SET status='dispatched',updated=?,dispatched=? WHERE id=? AND status='prepared'",(time.time(),time.time(),ident)).rowcount
                if changed!=1:raise ExecutionDenied('The execution is no longer active.')
            dispatched[0]=True
        outcome='unknown';output=None
        try:
            from ..edge_gateway.machine import execute as gateway_execute
            from ..concierge.http_security import outbound_operation
            with dispatch_scope(guard),outbound_operation(25):
                response=gateway_execute(self.front,row['resource_id'],row['tool'],arguments,principal='adoption:'+owner,idempotency_key=ident)
                if response is None:
                    response=self.front.proxy.execute(row['resource_id'],row['tool'],arguments,public=True)
            if response.get('ok'):
                value=response.get('result',{})
                value=value.get('structuredContent',value)if isinstance(value,dict)else value
                validate(row['contract_id'],arguments,value)
                from ..concierge.connections import project,bindings,gateway_agent_url
                resource=self.store.resource(row['resource_id'])
                output=project(value,gateway_agent_url(row['resource_id'],'mcp'),bindings(resource))
                if len(json.dumps(output,ensure_ascii=True,allow_nan=False).encode())>65536:
                    raise ValueError('RESPONSE_TOO_LARGE')
                outcome='succeeded'
            else:
                from ..concierge.execution_errors import failure_code
                output={'error_code':failure_code(response.get('error_code'))}
                outcome='unknown'if dispatched[0]or response.get('outcome')=='unknown'else'failed'
        except Exception as error:
            logging.getLogger(__name__).warning('Informational execution stopped (%s).',type(error).__name__)
            outcome='unknown'if dispatched[0]else'failed'
        sealed=self.front.updates._seal(output,ident)if output is not None else None
        with transaction(self.store)as db:
            db.execute("UPDATE adoption_operations SET status=?,sealed=?,updated=? WHERE id=? AND status IN ('prepared','dispatched')",(outcome,sealed,time.time(),ident))
        return self.operation(owner,ident)
