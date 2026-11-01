"""Verified product templates: signed drafts, live-run acceptance and withdrawal.

The controlled outage affects only a signed private validation run. Public input
cannot choose a provider, mutate a graph, inject a fault or fabricate test proof.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import hmac
import hashlib
from pathlib import Path
import json
import re
import secrets
import time

from .capability_registry import canonical,digest
from .workflow_fallback import graph_fingerprint
from .workflow_transforms import bounded

_scope=ContextVar('workflow_product_run',default=None)
SCHEMA='''CREATE TABLE IF NOT EXISTS workflow_product_templates (
 workflow_id INTEGER PRIMARY KEY,payload TEXT NOT NULL,signature TEXT NOT NULL,
 stage TEXT NOT NULL,created REAL NOT NULL,expires REAL NOT NULL,revoked REAL);
'''
NOTICE='workflow-product-public-input-v1'

def implementation():
    return digest([hashlib.sha256(Path(__file__).parent.joinpath(name).read_bytes()).hexdigest() for name in
        ('owned_data_agents/engine.py','owned_data_agents/source_limits.py','workflow_products.py','workflow_product_blueprints.py','workflow_product_operator.py','workflow_fallback.py','workflows.py','workflow_transforms.py','workflow_io_profiles.py')])


class Products:
    def __init__(self,runtime):
        self.runtime,self.store=runtime,runtime.store
        with self.store._lock:self.store._db.executescript(SCHEMA)

    def _write(self,workflow_id,payload):
        with self.store.tx() as db:
            db.execute('INSERT INTO workflow_product_templates VALUES (?,?,?,?,?,?,NULL) ON CONFLICT(workflow_id) DO UPDATE SET payload=excluded.payload,signature=excluded.signature,stage=excluded.stage,created=excluded.created,expires=excluded.expires,revoked=NULL',
                (workflow_id,canonical(payload),self.runtime.authority.signature(payload),payload['stage'],payload['created'],payload['expires']))

    def candidate(self,workflow_id,spec,actor,guard=lambda:False):
        from .workflows import graph,sensitive
        if guard() is not True:raise ValueError('Current product review authority is required.')
        workflow=self.store.get_workflow(workflow_id);nodes,_,_=graph(workflow)
        if workflow.get('is_template') or workflow.get('trigger_type','manual')!='manual' or sensitive(workflow['nodes']):
            raise ValueError('Review a private manual public-data candidate first.')
        if not isinstance(spec,dict) or set(spec)!={'slug','use_case','inputs'} or not isinstance(spec.get('slug'),str) or not re.fullmatch('[a-z][a-z0-9-]{1,60}',spec['slug']):
            raise ValueError('Provide a product identity, purpose and declared inputs.')
        if not isinstance(spec['use_case'],str) or not 1<=len(spec['use_case'])<=500:raise ValueError('Provide a bounded product purpose.')
        from .owned_data_agents.english import english
        presentation={k:workflow.get(k) for k in ('name','description','category')}
        for text in (*presentation.values(),spec['use_case']):
            if not isinstance(text,str) or not english(text) or re.search(r'/Users/|/home/|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?i:Bearer\s|api[_-]?key\s*[:=])',text):
                raise ValueError('Use reviewed English public product descriptions.')
        fields=spec['inputs']
        if not isinstance(fields,list) or not 1<=len(fields)<=5:raise ValueError('Declare one to five public input fields.')
        names=set()
        for field in fields:
            if not isinstance(field,dict):raise ValueError('Declare structured public inputs.')
            base={'name','node_id','argument','type'}
            extra={'min_length','max_length'} if field.get('type')=='string' else {'minimum','maximum'}
            if (set(field)!=base|extra or not re.fullmatch('[a-z][a-z0-9_]{0,40}',field.get('name',''))
                    or field['name'] in names or field['node_id'] not in nodes or nodes[field['node_id']].get('type')!='agent'
                    or field['argument'] not in ('query','limit')):raise ValueError('Use distinct bounded canonical query/limit bindings.')
            if field['argument']=='query' and (field['type']!='string' or type(field['min_length']) is not int
                    or type(field['max_length']) is not int or not 2<=field['min_length']<=field['max_length']<=160):
                raise ValueError('Use bounded public research text.')
            if field['argument']=='limit' and (field['type']!='integer' or type(field['minimum']) is not int
                    or type(field['maximum']) is not int or not 1<=field['minimum']<=field['maximum']<=5):
                raise ValueError('Use one to five result records.')
            names.add(field['name'])
        policy,_=self.runtime.fallback.policy(workflow_id)
        agents={n['id'] for n in nodes.values() if n.get('type')=='agent'}
        if not policy or policy['mode']!='shadow' or agents!={p['node_id'] for p in policy['pairs']}:
            raise ValueError('Every agent stage needs its own explicit independent shadow pair.')
        if not 1<=len(agents)<=2 or any(n.get('type') not in ('agent','trigger','input_transform','output_transform') for n in nodes.values()):
            raise ValueError('Use one or two read-only searches and local deterministic transforms.')
        expires=min(policy['expires'],time.time()+86400)
        for pair in policy['pairs']:
            self.runtime.fallback.independent_pair(pair['primary'],pair['alternate'])
            for key in ('primary','alternate'):
                pin=pair[key]
                if pin.get('io_profile'):expires=min(expires,self.runtime.io_profiles.get(pin['io_profile'])['expires'])
        payload={'audience':'workflow-product-v1','workflow_id':workflow_id,'graph':graph_fingerprint(workflow),
            'binding':policy['fingerprint'],'presentation':digest(presentation),'implementation':implementation(),'spec':deepcopy(spec),'owner':actor,'stage':'candidate',
            'created':time.time(),'expires':expires,'run_proofs':[]}
        self._write(workflow_id,payload)
        return {'workflow_id':workflow_id,'stage':'candidate','expires':expires}

    def known(self,workflow_id):
        return bool(self.store.query('SELECT workflow_id FROM workflow_product_templates WHERE workflow_id=?',(workflow_id,)))

    def get(self,workflow_id):
        rows=self.store.query('SELECT * FROM workflow_product_templates WHERE workflow_id=?',(workflow_id,))
        if not rows or rows[0]['revoked'] is not None or rows[0]['expires']<=time.time():raise ValueError('Product review expired or was withdrawn.')
        row=rows[0];payload=json.loads(row['payload'])
        if (not hmac.compare_digest(row['signature'],self.runtime.authority.signature(payload))
                or payload.get('audience')!='workflow-product-v1' or payload.get('workflow_id')!=workflow_id
                or payload.get('implementation')!=implementation() or payload.get('stage')!=row['stage'] or payload.get('expires')!=row['expires']):raise ValueError('Product review is invalid.')
        wf=self.store.get_workflow(workflow_id)
        if not wf or not wf.get('is_active') or graph_fingerprint(wf)!=payload['graph'] or digest({k:wf.get(k) for k in ('name','description','category')})!=payload['presentation']:raise ValueError('The reviewed product graph changed.')
        return payload

    def prepare(self,workflow,claims,source,inputs=None,drill=None):
        if inputs is None and drill is None:return None
        product=self.get(workflow['id'])
        if inputs is not None and (not isinstance(inputs,dict) or set(inputs)-{f['name'] for f in product['spec']['inputs']}):
            raise ValueError('Use only the published product inputs.')
        values=inputs or {};bounded(values)
        for field in product['spec']['inputs']:
            if field['name'] not in values:continue
            value=values[field['name']]
            if field['type']=='string':
                from .owned_data_agents.english import english
                valid=(type(value) is str and field['min_length']<=len(value)<=field['max_length'] and english(value)
                    and not re.search(r'https?://|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\{\{|\b(?:Bearer|Basic)\s|/Users/|/home/|[\x00-\x1f]',value,re.I))
            else:valid=type(value) is int and field['minimum']<=value<=field['maximum']
            if not valid:raise ValueError('A declared product input is invalid.')
        fault=None
        if drill is not None:
            if (source!='admin' or claims['kind']!='admin' or claims['role']!='superadmin' or workflow.get('is_template')
                    or type(drill) is not int or drill not in {n.get('resource_id') for n in workflow['nodes'] if n.get('type')=='agent'}):
                raise ValueError('Only a highest-administrator private candidate run may use a controlled preflight drill.')
            fault=drill
        elif product['stage']!='published' and (source!='admin' or claims.get('role')!='superadmin'):
            raise ValueError('This product has not been published.')
        payload={'audience':NOTICE,'workflow_id':workflow['id'],'graph':product['graph'],'binding':product['binding'],
            'inputs':deepcopy(values),'fault_resource':fault,'owner':claims['subject'],'source':source,
            'nonce':secrets.token_hex(16),'expires':min(time.time()+120,product['expires'])}
        return {'payload':payload,'signature':self.runtime.authority.signature(payload)}

    def context(self,run,*,historical=False):
        snapshot=json.loads(run['snapshot']) if isinstance(run['snapshot'],str) else run['snapshot']
        envelope=snapshot.get('product_context')
        if not envelope:return None
        payload=envelope['payload']
        if (not hmac.compare_digest(envelope['signature'],self.runtime.authority.signature(payload))
                or payload.get('audience')!=NOTICE or payload.get('workflow_id')!=run['workflow_id']
                or payload.get('source')!=run['source'] or payload['expires']<=(run.get('started') or run['created'] if historical else time.time())
                or payload['graph']!=graph_fingerprint(snapshot)):raise ValueError('Product execution context changed or expired.')
        if payload['fault_resource'] is not None and run['source']!='admin':raise ValueError('Public executions cannot inject faults.')
        return payload

    def inputs(self,run,node,args):
        context=self.context(run)
        if not context:return args
        product=self.get(run['workflow_id']);result=deepcopy(args)
        for field in product['spec']['inputs']:
            if field['node_id']==node['id'] and field['name'] in context['inputs']:
                result[field['argument']]=context['inputs'][field['name']]
        return result

    @contextmanager
    def call_scope(self,run):
        token=_scope.set(self.context(run))
        try:yield
        finally:_scope.reset(token)

    def before_call(self,node):
        context=_scope.get()
        if context and context['fault_resource']==(node.get('resource_id') or node.get('data',{}).get('resource_id')):
            from .workflows import WorkflowError
            raise WorkflowError('Controlled private product preflight drill.',error_code='UPSTREAM_NETWORK')

    def _proof(self,workflow_id,run_id):
        rows=self.store.query('SELECT * FROM workflow_runs WHERE id=? AND workflow_id=?',(run_id,workflow_id))
        if not rows:raise ValueError('A retained product test run is required.')
        run=dict(rows[0]);snapshot=json.loads(run['snapshot'])
        if (run['status']!='succeeded' or run['source']!='admin' or digest(snapshot)!=run['digest']
                or graph_fingerprint(snapshot)!=self.get(workflow_id)['graph']):raise ValueError('Only successful current private product runs qualify.')
        self.runtime.authority.run(run_id,workflow_id,run['digest'],'admin')
        records=[]
        for node in snapshot['nodes']:
            rows=self.store.query('SELECT payload,signature FROM workflow_checkpoints WHERE run_id=? AND node_id=?',(run_id,node['id']))
            if not rows:raise ValueError('Retain signed checkpoints for every product step.')
            row=rows[0];payload=json.loads(row['payload'])
            if (not hmac.compare_digest(row['signature'],self.runtime.authority.signature(payload)) or payload.get('run_id')!=run_id
                    or payload.get('digest')!=run['digest'] or payload.get('node_id')!=node['id'] or payload.get('audience')!='workflow-checkpoint-v1' or payload['record']['status']!='succeeded'):
                raise ValueError('A product test checkpoint is invalid.')
            records.append(payload['record'])
        return run,self.context(run,historical=True),records

    def accept(self,workflow_id,normal_run,drill_runs,actor,guard=lambda:False):
        if guard() is not True:raise ValueError('Current product review authority is required.')
        product=self.get(workflow_id);policy,_=self.runtime.fallback.policy(workflow_id)
        if not policy or policy['mode']!='canary' or policy['fingerprint']!=product['binding']:raise ValueError('Verify the current bounded canary first.')
        if not isinstance(drill_runs,list) or not 1<=len(drill_runs)<=2 or len(set(drill_runs))!=len(drill_runs):raise ValueError('Retain one controlled successful outage run per primary provider.')
        _,context,records=self._proof(workflow_id,normal_run)
        if (context and context['fault_resource'] is not None) or any(r.get('fallback_used') for r in records):raise ValueError('A normal primary run is required separately.')
        required={p['primary']['resource_id'] for p in policy['pairs']};covered=set();proofs=[]
        for identity in drill_runs:
            run,context,records=self._proof(workflow_id,identity)
            if not context or context['fault_resource'] not in required:raise ValueError('An authenticated controlled outage is required.')
            plan=self.runtime.fallback.plan(run)
            if not plan or not plan['selected'] or not plan['opt_in'] or plan['policy']['fingerprint']!=product['binding']:
                raise ValueError('The outage run must exercise its bound alternative policy with explicit sharing consent.')
            switched=[r for r in records if r.get('fallback_used')]
            if len(switched)!=1 or switched[0].get('requested_resource_id')!=context['fault_resource']:
                raise ValueError('The expected provider did not switch exactly once.')
            attempts=self.runtime.fallback.decisions(identity)['attempts']
            relevant=[a for a in attempts if a['node_id']==switched[0]['node_id']]
            if len(relevant)!=2 or [a['status'] for a in relevant]!=['failed','succeeded'] or relevant[1]['dispatched'] is None:
                raise ValueError('An actual completed alternate business dispatch is required.')
            covered.add(context['fault_resource']);proofs.append(identity)
        if covered!=required:raise ValueError('Every primary provider needs an independent successful outage case.')
        product.update(stage='verified',owner=actor,run_proofs=[normal_run,*proofs],verified_at=time.time())
        self._write(workflow_id,product)
        return {'workflow_id':workflow_id,'stage':'verified','expires':product['expires']}

    def active_ready(self,workflow,policy):
        product=self.get(workflow['id'])
        return product['stage'] in ('verified','published') and product['binding']==policy['fingerprint'] and policy['expires']<=product['expires']

    def publish(self,workflow_id,actor,guard=lambda:False):
        if guard() is not True:raise ValueError('Current product publication authority is required.')
        product=self.get(workflow_id);wf=self.store.get_workflow(workflow_id);policy,_=self.runtime.fallback.policy(workflow_id)
        if not policy or policy['mode']!='active' or not self.active_ready(wf,policy) or not self.runtime.fallback.available(wf):
            raise ValueError('Only an accepted, active and currently executable fallback product may be published.')
        for pair in policy['pairs']:
            plan={'workflow_id':workflow_id,'policy_revision':policy['revision'],'policy':policy}
            self.runtime.fallback.current_pair(plan,pair)
        self.store.update_workflow(workflow_id,{'is_template':1})
        product.update(stage='published',published_at=time.time(),owner=actor);self._write(workflow_id,product)
        return {'workflow_id':workflow_id,'published':True,'expires':product['expires']}

    def projection(self,workflow):
        if not workflow.get('is_template'):return None
        try:
            product=self.get(workflow['id']);policy,_=self.runtime.fallback.policy(workflow['id'])
            if product['stage']!='published' or not policy or policy['mode']!='active' or not self.runtime.fallback.available(workflow):return None
            for pair in policy['pairs']:
                self.runtime.fallback.current_pair({'workflow_id':workflow['id'],'policy_revision':policy['revision'],'policy':policy},pair)
        except (ValueError,KeyError,TypeError):return None
        result={k:workflow.get(k) for k in ('id','name','description','category','trigger_type','is_active','is_template')}
        result.update(author='Agent Concierge',tags='verified-workflow-product',nodes=[],edges=deepcopy(workflow['edges']))
        for n in workflow['nodes']:
            node={k:n[k] for k in ('id','name','type','kind','resource_id','position') if k in n}
            node['data']={'input':deepcopy(n.get('data',{}).get('input',{}))} if n.get('type')=='agent' else {}
            result['nodes'].append(node)
        result['product']={'inputs':deepcopy(product['spec']['inputs']),'use_case':product['spec']['use_case'],
            'verified_at':product['verified_at'],'valid_until':product['expires'],'version':product['binding'][:16]}
        result['definition_hash']=digest([product['graph'],product['binding']]);result['fallback_available']=True
        result['steps']=[{'name':n['name'],'kind':n.get('kind')} for n in result['nodes']]
        return result
