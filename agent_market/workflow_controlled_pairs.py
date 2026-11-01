"""Explicit private source-once/document-A/document-B runs and retained inspection.

Preparation signs a bounded catalog-only proposal. One nonce reserves one saved
definition and one durable run; inspection never recovers, invokes or publishes.
"""
import copy
from datetime import datetime,timezone
import hmac
import json
import math
import re
import secrets
import sqlite3
import time

from .capability_contracts import validate
from .capability_registry import canonical,digest
from .workflow_comparison import ComparisonError
from .workflow_composer import Composer,NODE as LITERAL_NODE,objective
from .workflow_paired_flow import PROFILE,NODE,SHARE_NOTICE,RUN_NOTICE,IDS,EDGES,build,verify_definition,expected_scope
from .workflow_resolved_evidence import ResolvedEvidence,display_text
from .workflow_typed_flow import validate_title

PROPOSAL='workflow-controlled-pair-proposal-v1'
TTL=900
NAME='Controlled news and documentation comparison'
DESCRIPTION='One private news search followed by two separately authorized documentation calls with the same verified title.'
READINESS_REASONS=('PUBLIC_TITLE_SHARING_PROFILE_REQUIRED','PUBLIC_PER_RUN_AUTHORIZATION_REQUIRED',
                   'SDK_DEPLOYMENT_AUTHORITY_PROFILE_REQUIRED','SEPARATE_PUBLICATION_CONSENT_REQUIRED')


class ControlledPairs(ResolvedEvidence):
    def _owner(self,actor):
        owner=str(actor) if type(actor) is int else actor
        if not isinstance(owner,str) or not re.fullmatch(r'[1-9][0-9]{0,9}',owner):
            raise ComparisonError('A current highest-administrator identity is required.')
        rows=self.store.query('SELECT role,active FROM admin_users WHERE id=?',(int(owner),))
        if not rows or not rows[0]['active'] or rows[0]['role']!='superadmin':
            raise ComparisonError('A current highest-administrator identity is required.')
        return owner

    def _catalog(self,*,allow_empty=False):
        composer=Composer(self.runtime)
        return (composer.candidates('news.search.v1',allow_empty=allow_empty),
                composer.candidates('docs.search.v1',allow_empty=allow_empty))

    def options(self):
        sources,targets=self._catalog(allow_empty=True)
        def safe(rows):return [{'id':row['id'],'label':row['label']} for row in rows]
        reasons=[]
        if not sources:reasons.append('NEWS_SOURCE_UNAVAILABLE')
        if len(targets)<2:reasons.append('DOCUMENTATION_TARGETS_UNAVAILABLE')
        return {'ok':True,'profile':PROFILE,'sources':safe(sources),'targets':safe(targets),
                'available':not reasons,'unavailable_reasons':reasons}

    def _literal(self,nid,contract,candidate,args,label):
        binding={'audience':LITERAL_NODE,'contract':contract,'pin':copy.deepcopy(candidate['pin']),'input':copy.deepcopy(args)}
        return {'id':nid,'name':label,'type':'agent','kind':'mcp','resource_id':candidate['pin']['resource_id'],
            'position':{'x':360 if nid==IDS[1] else 660,'y':180 if nid!=IDS[3] else 380},
            'data':{'tool':binding['pin']['approval']['tool'],'input':copy.deepcopy(args),
                'composition':{'payload':binding,'mac':self.runtime.authority.signature(binding)}}}

    def prepare(self,body,actor):
        owner=self._owner(actor)
        if (not isinstance(body,dict) or set(body)!={'objective','source_id','target_a_id','target_b_id'}
                or any(not isinstance(body[key],str) for key in ('source_id','target_a_id','target_b_id'))):
            raise ComparisonError('Select one news source, two distinct documentation targets and a public objective.')
        try:query=validate_title(objective(body['objective']))
        except (ValueError,TypeError):raise ComparisonError('Use a public objective without addresses, secrets or executable content.') from None
        if display_text(query)!=query:raise ComparisonError('The reviewed objective requires privacy minimization.')
        sources,targets=self._catalog();news={row['id']:row for row in sources};docs={row['id']:row for row in targets}
        if body['source_id'] not in news or body['target_a_id'] not in docs or body['target_b_id'] not in docs or body['target_a_id']==body['target_b_id']:
            raise ComparisonError('Choose currently eligible source and distinct documentation targets.')
        created=time.time();nonce=secrets.token_hex(16);args={'query':query,'language':'en','limit':3}
        news_args={**args,'from_utc':datetime.fromtimestamp(created-86400,timezone.utc).isoformat().replace('+00:00','Z')}
        source=self._literal(IDS[1],'news.search.v1',news[body['source_id']],news_args,'News source')
        a=self._literal(IDS[2],'docs.search.v1',docs[body['target_a_id']],args,'Target A')
        b=self._literal(IDS[3],'docs.search.v1',docs[body['target_b_id']],args,'Target B')
        a,b=build(self.runtime.composer,source,[a,b],owner=owner,nonce=nonce,reviewed_at=created)
        workflow={'name':NAME,'description':DESCRIPTION,'category':'data_utility','trigger_type':'manual',
            'nodes':[{'id':'start','name':'Manual controlled test','type':'trigger','kind':'trigger','position':{'x':60,'y':180},'data':{}},source,a,b],
            'edges':[{'id':edge,'source':parent,'target':child} for edge,parent,child in EDGES],
            'is_active':1,'is_template':0,'tags':'controlled-pair:'+nonce,'author':'Controlled pair owner '+owner}
        proposal={'audience':PROPOSAL,'nonce':nonce,'owner':owner,'created':created,'expires':created+TTL,'workflow':workflow}
        return {'ok':True,'profile':PROFILE,'proposal':proposal,'signature':self.runtime.authority.signature(proposal),
            'preview':{'objective':query,'source_label':news[body['source_id']]['label'],'target_a_label':docs[body['target_a_id']]['label'],
                'target_b_label':docs[body['target_b_id']]['label'],'news_from_utc':news_args['from_utc'],'language':'en','limit':3,
                'max_calls':3,'max_seconds':25,'expires':created+TTL},'executed':False}

    def _proposal(self,body,owner):
        try:
            p=body['proposal'];signature=body['signature']
            if (not isinstance(p,dict) or set(p)!={'audience','nonce','owner','created','expires','workflow'}
                    or p['audience']!=PROPOSAL or p['owner']!=owner
                    or not isinstance(p['nonce'],str) or not re.fullmatch(r'[a-f0-9]{32}',p['nonce'])
                    or not isinstance(signature,str) or not hmac.compare_digest(signature,self.runtime.authority.signature(p))):
                raise ValueError()
            created=self.timestamp(p['created']);expires=self.timestamp(p['expires']);now=time.time()
            if created>now+5 or expires!=created+TTL or expires<=now:raise ValueError()
            controls=self.store.query('SELECT updated FROM execution_controls WHERE id=1')
            if len(controls)!=1 or self.timestamp(controls[0]['updated'])>created:raise ValueError()
            wf=p['workflow'];binding,_=verify_definition(self.runtime.composer,wf,now=created)
            if binding['pair']['reviewed_at']!=created:raise ValueError()
            scope=expected_scope(wf)
            if scope['owner']!=owner or scope['nonce']!=p['nonce'] or set(wf)!={'name','description','category','trigger_type','nodes','edges','is_active','is_template','tags','author'}:
                raise ValueError()
            if (wf['name']!=NAME or wf['description']!=DESCRIPTION or wf['category']!='data_utility'
                    or wf['is_active']!=1 or wf['is_template']!=0 or wf['tags']!='controlled-pair:'+p['nonce']
                    or wf['author']!='Controlled pair owner '+owner):raise ValueError()
            args=wf['nodes'][1]['data']['input']
            expected=datetime.fromtimestamp(created-86400,timezone.utc).isoformat().replace('+00:00','Z')
            if args['language']!='en' or args['limit']!=3 or args['from_utc']!=expected or validate_title(args['query'])!=args['query'] or display_text(args['query'])!=args['query']:
                raise ValueError()
            return p
        except (ValueError,TypeError,KeyError,AttributeError,IndexError,OverflowError):
            raise ComparisonError('The controlled-pair proposal expired, changed or belongs to another administrator.') from None

    def _reserve(self,p):
        from .gateway.store import _graph_to_steps
        wf=p['workflow'];packaged={'nodes':wf['nodes'],'edges':wf['edges'],'steps':_graph_to_steps(wf['nodes'],wf['edges'])}
        # Store.tx alone starts its writer transaction only on DML. Acquire an
        # explicit writer lock before the nonce lookup across server processes.
        with self.store._lock:
            if self.store._db.in_transaction:raise ComparisonError('A private definition reservation is temporarily unavailable.')
            with self.store.tx() as db:
                db.execute('BEGIN IMMEDIATE')
                rows=db.execute('SELECT id,name,description,category,trigger_type,substr(steps,1,180001) AS steps,tags,is_active,is_template,author FROM agent_workflows WHERE tags=? LIMIT 2',(wf['tags'],)).fetchall()
                if len(rows)>1:raise ComparisonError('The controlled-pair reservation is ambiguous.')
                if rows:
                    row=dict(rows[0])
                    try:
                        if any(row[key]!=wf[key] for key in ('name','description','category','trigger_type','tags','is_active','is_template','author')) or len(row['steps'])>180000 or json.loads(row['steps'])!=packaged:
                            raise ValueError()
                    except (ValueError,TypeError):raise ComparisonError('The saved controlled-pair definition changed.') from None
                    identity=row['id']
                else:
                    count=db.execute("SELECT COUNT(*) FROM agent_workflows WHERE author=? AND tags LIKE 'controlled-pair:%' AND created_at>?",(wf['author'],time.time()-3600)).fetchone()[0]
                    if count>=20:raise ComparisonError('The private controlled-pair preparation limit has been reached.')
                    now=time.time()
                    cur=db.execute('INSERT INTO agent_workflows (name,description,category,trigger_type,steps,tags,is_active,is_template,author,created_at,updated_at) VALUES (?,?,?,?,?,?,1,0,?,?,?)',
                        (wf['name'],wf['description'],wf['category'],wf['trigger_type'],canonical(packaged),wf['tags'],wf['author'],now,now))
                    identity=cur.lastrowid
        return {**copy.deepcopy(wf),'id':identity}

    def execute(self,body,actor):
        owner=self._owner(actor)
        if (not isinstance(body,dict) or set(body)!={'proposal','signature','share_authority','share_notice','live_authority','live_notice'}
                or body['share_authority'] is not True or body['share_notice']!=SHARE_NOTICE
                or body['live_authority'] is not True or body['live_notice']!=RUN_NOTICE):
            raise ComparisonError('Separate input-sharing and one live controlled-run authorizations are required.')
        p=self._proposal(body,owner);wf=self._reserve(p)
        principal=self.runtime.principal('admin',owner,wf['id'],role='superadmin')
        arguments={'source':'admin','actor':'controlled-pair:'+owner,'idempotency':'controlled-pair:'+p['nonce'],
            'principal':principal,'pair_authority':True,'pair_notice':RUN_NOTICE}
        try:job=self.runtime.submit(wf,**arguments)
        except sqlite3.IntegrityError:
            # The UNIQUE actor/key boundary chooses one durable run if separate
            # processes raced after reserving the same immutable definition.
            job=self.runtime.submit(wf,**arguments)
        return {'ok':True,**job,'workflow_id':wf['id'],'replayed':bool(job.get('replayed'))}

    def _load(self,store,run_id):
        rows=store.query('SELECT id,workflow_id,digest,substr(snapshot,1,180001) AS snapshot,source,status,execution_outcome,created FROM workflow_runs WHERE id=?',(run_id,))
        if not rows or rows[0]['source']!='admin' or rows[0]['status'] not in ('queued','running','succeeded','failed','cancelled'):
            raise ComparisonError('Choose a retained private controlled-pair run.')
        row=dict(rows[0])
        try:
            self.timestamp(row['created'])
            if len(row['snapshot'])>180000 or row['execution_outcome'] not in ('succeeded','failed','cancelled','unknown',None):raise ValueError()
            wf=json.loads(row['snapshot'])
            if digest(wf)!=row['digest'] or wf.get('id')!=row['workflow_id']:raise ValueError()
            a,source=verify_definition(self.runtime.composer,wf,now=row['created']);scope=expected_scope(wf)
            proof=store.query('SELECT substr(payload,1,16385) AS payload,signature FROM workflow_run_authority WHERE run_id=?',(run_id,))
            if not proof or len(proof[0]['payload'])>16384:raise ValueError()
            authority=self.signed(proof[0])
            if any(authority.get(key)!=value for key,value in {'run_id':run_id,'workflow_id':row['workflow_id'],'digest':row['digest'],'source':'admin','grant_id':None}.items()):raise ValueError()
            principal=self.signed({'payload':json.dumps(authority['principal']['payload']),'signature':authority['principal']['signature']})
            if (principal.get('kind')!='admin' or principal.get('role')!='superadmin' or principal.get('subject')!=scope['owner']
                    or principal.get('workflow_id')!=row['workflow_id'] or principal.get('audience')!='workflow-runtime-v1'
                    or principal.get('controlled_pair')!=scope):raise ValueError()
            row['authority_expires']=self.timestamp(principal.get('expires'))
            if row['authority_expires']<=row['created']:raise ValueError()
            budgets=store.query('SELECT payload,signature FROM workflow_execution_budgets WHERE run_id=?',(run_id,))
            if not budgets:raise ValueError()
            budget=self.signed(budgets[0])
            if budget!={'audience':'workflow-budget-v1','run_id':run_id,'digest':row['digest'],'source':'admin','profile':'standard','total_seconds':25,'node_seconds':25}:raise ValueError()
        except (ValueError,KeyError,TypeError,AttributeError,IndexError,OverflowError):
            raise ComparisonError('The retained controlled-pair definition or execution authority cannot be verified.') from None
        return row,wf,source

    def _attempt(self,store,row,node,args):
        rows=store.query('SELECT input_hash,status FROM workflow_execution_attempts WHERE run_id=? AND node_id=?',(row['id'],node['id']))
        if not rows:return 'unavailable'
        attempt=rows[0]
        if attempt['status'] not in ('prepared','dispatched','succeeded','failed','unknown'):raise ComparisonError('The retained external-attempt certainty is invalid.')
        if args is not None:
            expected=self.runtime.authority.signature({'audience':'workflow-input-v1','digest':row['digest'],'node_id':node['id'],'input':args})
            if not hmac.compare_digest(attempt['input_hash'],expected):raise ComparisonError('The retained attempted input does not match the controlled input.')
        return attempt['status']

    @staticmethod
    def _readiness():
        return {'ready':False,'reasons':list(READINESS_REASONS),'published':False,'publication_consent_collected':False}

    def publication_readiness(self,body):
        # Validate retained identity/proof before explaining the fixed barriers;
        # this is not an inert consent receipt or publication authorization.
        result=self.inspect(body)
        return {'ok':True,'profile':PROFILE,'run':result['run'],**self._readiness()}

    def runs(self):
        results=[]
        with self.reader() as store:
            for item in store.query("SELECT id FROM workflow_runs WHERE source='admin' ORDER BY created DESC LIMIT 100"):
                try:row,_,_=self._load(store,item['id'])
                except ComparisonError:continue
                results.append({'run_id':row['id'],'status':row['status'],'outcome':row['execution_outcome'],
                    'recorded_at':row['created'],'label':'Controlled news to documentation pair'})
                if len(results)>=30:break
        return {'ok':True,'profile':PROFILE,'runs':results}

    def inspect(self,body):
        if (not isinstance(body,dict) or set(body)!={'run_id'} or not isinstance(body['run_id'],str)
                or not re.fullmatch(r'wr_[a-f0-9]{32}',body['run_id'])):
            raise ComparisonError('Provide one retained controlled-pair run reference.')
        with self.reader() as store:
            row,wf,source=self._load(store,body['run_id']);source_binding=source['data']['composition']['payload']
            source_cp=self.checkpoint(store,row,source);source_attempt=self._attempt(store,row,source,source_binding['input'])
            source_result=self.node_result(store,row,source,source_binding,source_cp,source_binding['input'])
            args=None
            if source_cp and source_cp['record']['status']=='succeeded' and source_attempt=='succeeded':
                try:
                    record=source_cp['record'];output=record['data'];normalized=output.get('structuredContent',output)
                    validate('news.search.v1',source_binding['input'],normalized,now=record['started']+record['latency_ms']/1000)
                    args=copy.deepcopy(wf['nodes'][2]['data']['input']);args['query']=validate_title(normalized['items'][0]['title'])
                    validate('docs.search.v1',args)
                    if display_text(args['query'])!=args['query']:raise ValueError()
                except (ValueError,KeyError,TypeError,AttributeError,IndexError):args=None
            if source_attempt!='succeeded':source_result.update(assessment='unknown' if source_attempt in ('unknown','dispatched') else 'unavailable',reason='source_attempt_certainty_unavailable',metrics=None,sources=[])
            targets=[];verified=[];provenances=[];previous=None
            for node in wf['nodes'][2:]:
                binding=node['data']['composition']['payload'];cp=self.checkpoint(store,row,node);provenance=False;ordered=True
                if cp:
                    record=cp['record'];retained=cp.get('typed_input')
                    if retained is not None or record['input']!={} or record['status']=='succeeded':
                        if source_cp is not None and args is not None:
                            expected={'profile':PROFILE,'source_id':source['id'],'source_checkpoint_hash':digest(source_cp),'pair_hash':digest(binding['pair']),'side':binding['side']}
                            if retained!=expected or record['input']!=args or record['started']<source_cp['record']['started']+source_cp['record']['latency_ms']/1000:
                                raise ComparisonError('The retained controlled target does not share the signed source and exact input.')
                            provenance=True
                attempt=self._attempt(store,row,node,args if provenance else None)
                if binding['side']=='b' and cp and (cp.get('typed_input') is not None or cp['record']['input']!={} or cp['record']['status']=='succeeded'):
                    if previous is None or previous['checkpoint'] is None or previous['attempt']=='unavailable' or not previous['provenance']:
                        ordered=False
                    elif previous['checkpoint']['record']['status']!='succeeded' or previous['attempt']!='succeeded':
                        # Resolved input can be retained after a fail-closed
                        # pre-dispatch refusal. It is not proof of a provider
                        # call. A successful B claim would be inconsistent.
                        if cp['record']['status']=='succeeded' or attempt=='succeeded':
                            raise ComparisonError('The second target has no certain successful first-target predecessor.')
                        ordered=False
                    else:
                        a=previous['checkpoint']['record'];a_output=a['data']
                        if not isinstance(a_output,dict):raise ComparisonError('The first controlled target proof is invalid.')
                        try:validate('docs.search.v1',args,a_output.get('structuredContent',a_output),now=a['started']+a['latency_ms']/1000)
                        except (ValueError,TypeError,KeyError):raise ComparisonError('The first controlled target proof is invalid.') from None
                        if cp['record']['started']<a['started']+a['latency_ms']/1000:
                            raise ComparisonError('The second controlled target observation precedes the first target result.')
                result=self.node_result(store,row,node,binding,cp,args,allowed=provenance and attempt=='succeeded' and ordered)
                if not ordered:result.update(assessment='unavailable',reason='first_target_predecessor_unavailable',metrics=None,sources=[])
                if attempt!='succeeded' and result['assessment']=='contract_passed':result.update(assessment='unknown' if attempt in ('unknown','dispatched') else 'unavailable',reason='target_attempt_certainty_unavailable',metrics=None,sources=[])
                if attempt=='unavailable' and cp and cp['record'].get('attempts')==0 and cp['record']['input']=={}:
                    attempt='not_dispatched';result.update(assessment='not_succeeded',reason='target_not_dispatched',metrics=None,sources=[])
                metrics=result['metrics'] or {}
                targets.append({'label':'Target '+binding['side'].upper(),'assessment':result['assessment'],'reason':result['reason'],
                    'outcome':attempt,'latency_ms':metrics.get('latency_ms'),'partial':metrics.get('partial'),'result_count':metrics.get('result_count'),
                    'source_count':metrics.get('source_count'),'sources':result['sources'],'current':result['current']})
                provenances.append(provenance)
                verified.append(provenance and attempt=='succeeded' and result['assessment']=='contract_passed' and ordered)
                previous={'checkpoint':cp,'attempt':attempt,'provenance':provenance}
            source_metrics=source_result['metrics'] or {};sources=source_result['sources']
            complete=all(verified) and row['status']=='succeeded' and row['execution_outcome']=='succeeded'
            return {'ok':True,'profile':PROFILE,'run':{'run_id':row['id'],'workflow_id':row['workflow_id'],'status':row['status'],'outcome':row['execution_outcome']},
                'comparison_status':'complete' if complete else 'in_progress' if row['status'] in ('queued','running') else 'unscored',
                'shared_input_verified':all(verified),'resolved_input':args if any(provenances) else None,
                'source':{'assessment':source_result['assessment'],'reason':source_result['reason'],'partial':source_metrics.get('partial'),
                    'result_count':source_metrics.get('result_count'),'published_at':sources[0].get('published_at') if sources else None,
                    'retrieved_at':sources[0].get('retrieved_at') if sources else None,'current':source_result['current']},
                'targets':targets,'publication_readiness':self._readiness(),
                'summary':{'automatic_winner':None,'factual_accuracy':'not_assessed','expert_review':'not_established','holdout_status':'not_established'},
                'effects':{'provider_calls':0,'model_calls':0,'evidence_writes':0,'publication':False},
                'notice':'Two targets are compared only against one retained signed source and exact resolved input. Failed, unknown or missing evidence remains unscored; no automatic winner or publication is authorized.'}
