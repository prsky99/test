"""Read-only evaluation of retained, signed, same-input informational tests.

This module cannot execute, publish, deliver, approve, or create evidence. A
contract check measures recorded structure/source/time rules, not factual truth.
"""
from contextlib import contextmanager
import hmac
import json
import math
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit, urlunsplit

from .capability_contracts import validate, utc
from .capability_registry import Registry, digest, version_parts
from .workflow_composer import SUPPORTED, NODE

EVALUATOR = 'informational-comparison-v1'
TERMINAL = ('succeeded', 'failed', 'cancelled')


class ComparisonError(ValueError):
    pass


class ReadStore:
    def __init__(self, db):
        self.db = db

    def query(self, sql, parameters=()):
        return self.db.execute(sql, parameters).fetchall()

    def resource(self, identity):
        rows = self.query('SELECT * FROM resources WHERE id=?', (identity,))
        return dict(rows[0]) if rows else None


class Comparison:
    def __init__(self, runtime):
        self.runtime, self.store = runtime, runtime.store

    @contextmanager
    def reader(self):
        if getattr(self.store, 'backend', 'sqlite') == 'postgresql':
            with self.store.tx(readonly=True) as db:
                yield ReadStore(db)
            return
        if self.store._path == ':memory:':
            with self.store._lock:
                db = self.store._db
                db.execute('SAVEPOINT workflow_comparison_read')
                try:
                    yield ReadStore(db)
                finally:
                    db.execute('ROLLBACK TO workflow_comparison_read')
                    db.execute('RELEASE workflow_comparison_read')
        else:
            db = sqlite3.connect(Path(self.store._path).resolve().as_uri() + '?mode=ro', uri=True, timeout=.05)
            db.row_factory = sqlite3.Row
            try:
                db.execute('BEGIN')
                yield ReadStore(db)
            finally:
                db.close()

    def signed(self, row, field='signature'):
        try:
            value = json.loads(row['payload'])
            if not isinstance(value, dict) or not hmac.compare_digest(row[field], self.runtime.authority.signature(value)):
                raise ValueError()
            return value
        except (ValueError, TypeError, KeyError):
            raise ComparisonError('Retained signed evidence is invalid.') from None

    def load(self, store, run_id, contract):
        rows = store.query('SELECT id,workflow_id,digest,substr(snapshot,1,180001) AS snapshot,source,status,execution_outcome,created FROM workflow_runs WHERE id=?', (run_id,))
        if not rows or rows[0]['source'] != 'admin' or rows[0]['status'] not in TERMINAL:
            raise ComparisonError('Choose retained completed administrator tests.')
        row = dict(rows[0])
        try:
            snapshot = json.loads(row['snapshot'])
            if not isinstance(snapshot, dict) or digest(snapshot) != row['digest'] or snapshot.get('id') != row['workflow_id']:
                raise ValueError()
            from .workflow_typed_flow import connected
            if any(connected(n) for n in snapshot['nodes']):
                raise ValueError('Connected drafts require a separate resolved-input comparison profile.')
            nodes = [n for n in snapshot['nodes'] if isinstance(n, dict) and n.get('type') == 'agent'
                     and n.get('data', {}).get('composition', {}).get('payload', {}).get('contract') == contract]
            if len(nodes) != 1:
                raise ValueError()
            node = nodes[0]
            signed = node['data']['composition']
            binding = self.signed({'payload': json.dumps(signed['payload']), 'signature': signed['mac']})
            if (binding.get('audience') != NODE or binding.get('contract') != contract or node.get('kind') != 'mcp'
                    or node.get('resource_id') != binding['pin']['resource_id']
                    or (node['data'].get('tool') or node['data'].get('action')) != binding['pin']['approval']['tool']
                    or node['data'].get('input') != binding['input'] or node['data'].get('output_select')):
                raise ValueError()
            validate(contract, binding['input'], now=self.timestamp(row['created']))
            authorities = store.query('SELECT payload,signature FROM workflow_run_authority WHERE run_id=?', (run_id,))
            if not authorities:
                raise ComparisonError('Execution authority has expired under the retention policy.')
            authority = self.signed(authorities[0])
            if any(authority.get(k) != v for k, v in {'run_id':run_id, 'workflow_id':row['workflow_id'], 'digest':row['digest'], 'source':'admin'}.items()):
                raise ValueError()
            principal = self.signed({'payload':json.dumps(authority['principal']['payload']), 'signature':authority['principal']['signature']})
            if principal.get('kind') != 'admin' or principal.get('workflow_id') != row['workflow_id'] or principal.get('audience') != 'workflow-runtime-v1':
                raise ValueError()
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ComparisonError('The retained definition or execution authority cannot be verified.') from None
        return row, node, binding

    @staticmethod
    def timestamp(value):
        if type(value) not in (int,float) or not math.isfinite(value) or value < 0:
            raise ComparisonError('The recorded timestamp is invalid.')
        return value

    def current(self, store, pin, contract):
        resource = store.resource(pin['resource_id'])
        if not resource:
            return {'definition_matches':False, 'eligible_now':False}
        binding, schema, profile, complete = version_parts(resource)
        version = {'id':'cv_'+digest([resource['id'],binding,schema,profile])[:32], 'resource_id':resource['id'],
                   'binding_hash':binding, 'schema_hash':schema, 'profile_version':profile, 'schema_complete':complete, 'agent_ref':pin['version']['agent_ref']}
        approval = store.query('SELECT tool,created FROM capability_approvals WHERE version_id=? AND contract_id=?', (version['id'],contract))
        matches = version['id'] == pin['version']['id'] and bool(approval) and dict(approval[0]) == pin['approval']
        projection = Registry(store).projection(resource, version=version)
        ready = projection.get('connection_readiness', {}).get('verified_callable') is True
        verified = any(c['id'] == contract and c['verified'] for c in projection.get('capability_contracts', []))
        return {'definition_matches':matches, 'eligible_now':bool(matches and ready and verified)}

    def side(self, store, row, node, binding):
        contract = binding['contract']
        result = {'run_id':row['id'], 'workflow_id':row['workflow_id'], 'agent_label':('News' if contract == SUPPORTED[0] else 'Documentation')+' agent '+binding['pin']['version']['agent_ref'][-8:],
                  'run_status':row['status'], 'execution_outcome':row['execution_outcome'],
                  'recorded_at':self.timestamp(row['created']), 'assessment':'unavailable', 'reason':'checkpoint_unavailable',
                  'metrics':None, 'sources':[], 'current':self.current(store,binding['pin'],contract)}
        evidence = store.query('SELECT substr(payload,1,262145) AS payload,signature FROM workflow_checkpoints WHERE run_id=? AND node_id=?', (row['id'],node['id']))
        if not evidence:
            if row['execution_outcome'] == 'unknown':
                result.update(assessment='unknown',reason='external_outcome_unknown')
            elif row['status'] == 'cancelled':
                result.update(assessment='cancelled',reason='execution_cancelled')
            return result, None, set()
        checkpoint = self.signed(evidence[0])
        try:
            if any(checkpoint.get(k) != v for k,v in {'audience':'workflow-checkpoint-v1','run_id':row['id'],'digest':row['digest'],'node_id':node['id']}.items()):
                raise ValueError()
            record = checkpoint['record']
            if not isinstance(record,dict) or record.get('node_id') != node['id'] or record.get('input') != binding['input']:
                raise ValueError()
            checkpoint_hash = digest(checkpoint)
            if record['status'] != 'succeeded' or row['execution_outcome'] not in ('succeeded','failed','cancelled'):
                result.update(assessment='unknown' if row['execution_outcome'] == 'unknown' else 'unavailable' if row['execution_outcome'] is None else 'not_succeeded', reason='external_outcome_unknown' if row['execution_outcome'] == 'unknown' else 'outcome_not_recorded' if row['execution_outcome'] is None else 'node_not_succeeded')
                return result, checkpoint_hash, set()
            latency = self.timestamp(record['latency_ms'])
            started = self.timestamp(record['started'])
            if latency > 120000:
                raise ValueError()
            output = record['data']
            if not isinstance(output,dict):
                raise ValueError()
            output = output.get('structuredContent',output)
            # Historical validity is evaluated at the signed observation time,
            # separately from current eligibility and elapsed wall-clock age.
            validate(contract,binding['input'],output,now=started+latency/1000)
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ComparisonError('The signed checkpoint does not contain a valid recorded contract result.') from None
        items = output['items']
        urls = {self.source_key(i['url']) for i in items}
        dated = [utc(i['published_at']) for i in items if contract == SUPPORTED[0] and i['published_at'] is not None]
        result.update(assessment='contract_passed',reason='recorded_contract_valid',metrics={
            'latency_ms':round(latency,2), 'result_count':len(items), 'source_count':len(urls),
            'partial':output['partial'], 'dated_count':len(dated) if contract == SUPPORTED[0] else None,
            'newest_published_at':max(dated) if dated else None,
            'oldest_published_at':min(dated) if dated else None,
            'retrieved_oldest_at':min((utc(i['retrieved_at']) for i in items),default=None)},
            sources=[{'title':i['title'], 'source_host':urlsplit(i['url']).hostname,
                      'published_at':i.get('published_at'), 'retrieved_at':i['retrieved_at'],
                      'version':i.get('version')} for i in items])
        return result, checkpoint_hash, urls

    @staticmethod
    def source_key(url):
        parts=urlsplit(url)
        return urlunsplit((parts.scheme,parts.netloc.lower(),parts.path,parts.query,''))

    def runs(self):
        entries=[];unavailable=0
        with self.reader() as store:
            rows=store.query("SELECT id FROM workflow_runs WHERE source='admin' AND status IN ('succeeded','failed','cancelled') ORDER BY created DESC LIMIT 100")
            for row in rows:
                for contract in SUPPORTED:
                    try:
                        run,node,binding=self.load(store,row['id'],contract)
                    except ComparisonError:
                        continue
                    checkpoint=store.query('SELECT 1 FROM workflow_checkpoints WHERE run_id=? AND node_id=?',(row['id'],node['id']))
                    if not checkpoint and run['execution_outcome']!='unknown' and run['status']!='cancelled':
                        unavailable+=1
                        continue
                    entries.append({'run_id':run['id'], 'workflow_id':run['workflow_id'], 'contract':contract,
                        'input_fingerprint':digest(binding['input']), 'agent_ref':binding['pin']['version']['agent_ref'],
                        'agent_label':('News' if contract == SUPPORTED[0] else 'Documentation')+' agent '+binding['pin']['version']['agent_ref'][-8:],
                        'status':run['status'], 'outcome':run['execution_outcome'], 'recorded_at':run['created']})
                    if len(entries)>=30:
                        break
                if len(entries)>=30:
                    break
        return {'ok':True, 'runs':entries, 'limit':30, 'scan_limit':100, 'unavailable_checkpoints':unavailable, 'evaluator':EVALUATOR}

    def compare(self,body):
        if (not isinstance(body,dict) or set(body)!={'left_run_id','right_run_id','contract'}
                or type(body['contract']) is not str or body['contract'] not in SUPPORTED
                or any(not isinstance(body[k],str) or not re.fullmatch(r'wr_[a-f0-9]{32}',body[k]) for k in ('left_run_id','right_run_id'))
                or body['left_run_id']==body['right_run_id']):
            raise ComparisonError('Select two distinct completed tests and a supported news/docs contract.')
        with self.reader() as store:
            left=self.load(store,body['left_run_id'],body['contract'])
            right=self.load(store,body['right_run_id'],body['contract'])
            if left[2]['input'] != right[2]['input']:
                raise ComparisonError('Comparison requires identical reviewed inputs, including language, limits and news period.')
            if left[2]['pin']['resource_id'] == right[2]['pin']['resource_id']:
                raise ComparisonError('Select two different registered agents.')
            a,ah,au=self.side(store,*left);b,bh,bu=self.side(store,*right)
            both=a['assessment']==b['assessment']=='contract_passed'
            overlap=len(au&bu)/len(au|bu) if au|bu else None
            identity=digest([EVALUATOR,body,ah,bh])
            return {'ok':True,'comparison_id':'cmp_'+identity[:32], 'evaluator':EVALUATOR,'contract':body['contract'],
                    'input_fingerprint':digest(left[2]['input']), 'left':a,'right':b,
                    'summary':{'both_contracts_passed':both, 'latency_delta_ms':round(b['metrics']['latency_ms']-a['metrics']['latency_ms'],2) if both else None,
                        'source_overlap':round(overlap,4) if both and overlap is not None else None,
                        'automatic_winner':None, 'factual_accuracy':'not_assessed', 'relevance':'manual_review_required',
                        'provider_calls':0,'evidence_writes':0},
                    'notice':'Recorded structure, source and time checks are not factual or expert quality certification. No candidate is promoted automatically.'}
