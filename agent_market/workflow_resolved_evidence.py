"""Read-only inspection of retained private typed-input evidence.

This profile never admits a pair, runs a provider, updates evidence or publishes.
Historical proof and current eligibility are deliberately separate observations.
"""
import copy
import json
import math
import re
import time

from .capability_contracts import validate
from .capability_registry import digest
from .concierge.recommendation_security import public_data
from .workflow_comparison import Comparison, ComparisonError, TERMINAL
from .workflow_composer import NODE as LITERAL_NODE
from .workflow_typed_flow import NODE, NOTICE, PROFILE, connection, validate_title

EVALUATOR = 'resolved-input-evidence-v1'


def display_text(value):
    """Minimize provider metadata before returning its text-only projection."""
    if not isinstance(value,str):return value
    value=public_data(value)
    from .workflows import sensitive
    if sensitive(value):return '[REDACTED]'
    return re.sub(r'(?i)https?://[^\s<>"\']+|\b[^\s<>"\']+@[^\s<>"\']+', '[REDACTED]', value)


class ResolvedEvidence(Comparison):
    def load_typed(self, store, run_id):
        rows = store.query('SELECT id,workflow_id,digest,substr(snapshot,1,180001) AS snapshot,source,status,execution_outcome,created FROM workflow_runs WHERE id=?', (run_id,))
        if not rows or rows[0]['source'] != 'admin' or rows[0]['status'] not in TERMINAL:
            raise ComparisonError('Choose a retained completed private administrator test.')
        row = dict(rows[0])
        try:
            self.timestamp(row['created'])
            if len(row['snapshot'])>180000 or row['execution_outcome'] not in (*TERMINAL,'unknown',None):
                raise ValueError()
            snapshot = json.loads(row['snapshot'])
            if (not isinstance(snapshot, dict) or digest(snapshot) != row['digest']
                    or snapshot.get('id') != row['workflow_id'] or snapshot.get('trigger_type') != 'manual'
                    or snapshot.get('fallback_policy_fingerprint')
                    or len(snapshot['nodes']) != 3 or len(snapshot['edges']) != 2):
                raise ValueError()
            nodes = {node['id']: node for node in snapshot['nodes']}
            if (set(nodes) != {'start', 'search-1', 'search-2'} or nodes['start'].get('type') != 'trigger'
                    or nodes['start'].get('kind') != 'trigger' or nodes['start'].get('data') != {}
                    or any(set(edge) != {'id', 'source', 'target'} for edge in snapshot['edges'])
                    or {(edge['id'],edge['source'],edge['target']) for edge in snapshot['edges']}
                    != {('start-search-1','start','search-1'),('search-1-search-2','search-1','search-2')}):
                raise ValueError()
            source, target = nodes['search-1'], nodes['search-2']
            bindings = []
            for node, audience, contract in [(source, LITERAL_NODE, 'news.search.v1'), (target, NODE, 'docs.search.v1')]:
                data = node['data']; signed = data['composition']
                binding = self.signed({'payload':json.dumps(signed['payload']), 'signature':signed['mac']})
                fields = {'audience', 'contract', 'pin', 'input'}
                if audience == NODE:
                    fields |= {'connection', 'sharing_authorized', 'sharing_notice'}
                if (set(binding) != fields or set(data) != {'tool', 'input', 'composition'}
                        or binding.get('audience') != audience or binding.get('contract') != contract
                        or node.get('type') != 'agent' or node.get('kind') != 'mcp'
                        or node.get('resource_id') != binding['pin']['resource_id']
                        or data['tool'] != binding['pin']['approval']['tool']
                        or data['input'] != binding['input']):
                    raise ValueError()
                validate(contract, binding['input'], now=row['created'])
                bindings.append(binding)
            if (bindings[1]['sharing_authorized'] is not True or bindings[1]['sharing_notice'] != NOTICE
                    or bindings[1]['connection'] != connection(source, target['id'])):
                raise ValueError()
            authorities = store.query('SELECT substr(payload,1,16385) AS payload,signature FROM workflow_run_authority WHERE run_id=?', (run_id,))
            if not authorities:
                raise ComparisonError('Execution authority is unavailable under the retention policy.')
            if len(authorities[0]['payload'])>16384:
                raise ValueError()
            authority = self.signed(authorities[0])
            if any(authority.get(key) != value for key, value in {'run_id':run_id, 'workflow_id':row['workflow_id'], 'digest':row['digest'], 'source':'admin'}.items()):
                raise ValueError()
            envelope = authority['principal']
            principal = self.signed({'payload':json.dumps(envelope['payload']), 'signature':envelope['signature']})
            if (principal.get('kind') != 'admin' or principal.get('role') != 'superadmin'
                    or principal.get('workflow_id') != row['workflow_id'] or principal.get('audience') != 'workflow-runtime-v1'):
                raise ValueError()
            # Historical expiry is compared with admission and recorded call
            # starts, never with the wall clock of this read-only inspection.
            row['authority_expires']=self.timestamp(principal.get('expires'))
            if row['authority_expires']<=row['created']:
                raise ValueError()
        except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
            raise ComparisonError('The retained typed definition or execution authority cannot be verified.') from None
        return row, source, target, bindings

    def checkpoint(self, store, row, node):
        rows = store.query('SELECT substr(payload,1,262145) AS payload,signature FROM workflow_checkpoints WHERE run_id=? AND node_id=?', (row['id'],node['id']))
        if not rows:
            return None
        if len(rows[0]['payload'])>262144:
            raise ComparisonError('The retained typed checkpoint exceeds the inspection limit.')
        checkpoint = self.signed(rows[0])
        try:
            if any(checkpoint.get(key) != value for key,value in {'audience':'workflow-checkpoint-v1', 'run_id':row['id'], 'digest':row['digest'], 'node_id':node['id']}.items()):
                raise ValueError()
            record = checkpoint['record']
            if (record['node_id'] != node['id'] or record['resource_id'] != node['resource_id']
                    or record['kind'] != 'mcp' or record['type'] != 'agent'
                    or record['status'] not in ('succeeded','failed','blocked','cancelled')
                    or record['status']=='succeeded' and record['data'] != checkpoint['flow_output']):
                raise ValueError()
            started = self.timestamp(record['started']); latency = self.timestamp(record['latency_ms'])
            if (latency > 60000 or started < row['created'] or not math.isfinite(started+latency/1000)
                    or started+latency/1000 > time.time()+5
                    or record['status']=='succeeded' and row['authority_expires']<=started):
                raise ValueError()
        except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
            raise ComparisonError('The retained typed checkpoint has invalid scope or observation metadata.') from None
        return checkpoint

    def node_result(self, store, row, node, binding, checkpoint, inputs=None, allowed=True):
        result = {'agent_label':('News' if binding['contract']=='news.search.v1' else 'Documentation')+' agent '+binding['pin']['version']['agent_ref'][-8:],
                  'contract':binding['contract'], 'assessment':'unavailable', 'reason':'checkpoint_unavailable',
                  'metrics':None, 'sources':[], 'current':self.current(store,binding['pin'],binding['contract'])}
        if checkpoint is None:
            if row['execution_outcome']=='unknown':result.update(assessment='unknown',reason='external_outcome_unknown')
            elif row['status']=='cancelled':result.update(assessment='cancelled',reason='execution_cancelled')
            return result
        record = checkpoint['record']
        if row['execution_outcome']=='unknown' and record['status']!='succeeded':
            result.update(assessment='unknown',reason='external_outcome_unknown')
        elif record['status']!='succeeded':
            result.update(assessment='not_succeeded',reason='node_not_succeeded')
        elif row['execution_outcome'] is None:
            result.update(reason='outcome_not_recorded')
        elif not allowed:
            result.update(reason='source_provenance_unavailable')
        else:
            try:
                output = record['data']
                if not isinstance(output,dict) or inputs != record['input']:
                    raise ValueError()
                validate(binding['contract'], inputs, output.get('structuredContent',output),
                         now=record['started']+record['latency_ms']/1000)
            except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
                raise ComparisonError('The signed typed checkpoint does not contain a valid recorded contract result.') from None
            normalized = output.get('structuredContent',output)
            from urllib.parse import urlsplit
            from .capability_contracts import utc
            items=normalized['items'];urls={self.source_key(i['url']) for i in items}
            dated=[utc(i['published_at']) for i in items if binding['contract']=='news.search.v1' and i['published_at'] is not None]
            result.update(assessment='contract_passed',reason='recorded_contract_valid',metrics={
                'latency_ms':round(record['latency_ms'],2),'result_count':len(items),'source_count':len(urls),'partial':normalized['partial'],
                'dated_count':len(dated) if binding['contract']=='news.search.v1' else None,
                'newest_published_at':max(dated) if dated else None,
                'retrieved_oldest_at':min((utc(i['retrieved_at']) for i in items),default=None)},
                sources=[{'title':display_text(i['title']),'source_host':urlsplit(i['url']).hostname,'published_at':i.get('published_at'),
                          'retrieved_at':i['retrieved_at'],'version':display_text(i.get('version'))} for i in items])
        return result

    def runs(self):
        entries=[]
        with self.reader() as store:
            rows=store.query("SELECT id FROM workflow_runs WHERE source='admin' AND status IN ('succeeded','failed','cancelled') ORDER BY created DESC LIMIT 100")
            for entry in rows:
                try:row,source,target,bindings=self.load_typed(store,entry['id'])
                except ComparisonError:continue
                entries.append({'run_id':row['id'],'workflow_id':row['workflow_id'],'status':row['status'],
                    'outcome':row['execution_outcome'],'recorded_at':row['created'],
                    'agent_label':'News to documentation · '+bindings[1]['pin']['version']['agent_ref'][-8:]})
                if len(entries)>=30:break
        return {'ok':True,'runs':entries,'limit':30,'scan_limit':100,'evaluator':EVALUATOR}

    def inspect(self, body):
        if (not isinstance(body,dict) or set(body)!={'run_id'} or not isinstance(body['run_id'],str)
                or not re.fullmatch(r'wr_[a-f0-9]{32}',body['run_id'])):
            raise ComparisonError('Provide one retained private typed test reference.')
        with self.reader() as store:
            return self.inspect_store(store,body)

    def inspect_store(self, store, body):
        """Use an existing read snapshot without weakening any proof checks."""
        if (not isinstance(body,dict) or set(body)!={'run_id'} or not isinstance(body['run_id'],str)
                or not re.fullmatch(r'wr_[a-f0-9]{32}',body['run_id'])):
            raise ComparisonError('Provide one retained private typed test reference.')
        row,source,target,bindings=self.load_typed(store,body['run_id'])
        source_checkpoint=self.checkpoint(store,row,source);target_checkpoint=self.checkpoint(store,row,target)
        source_result=self.node_result(store,row,source,bindings[0],source_checkpoint,bindings[0]['input'])
        args=None; derived=None; provenance='unavailable'
        if source_checkpoint is not None:
            source_record=source_checkpoint['record']
            if source_record['input'] not in ({},bindings[0]['input']):
                raise ComparisonError('The retained source input does not match its reviewed binding.')
            if source_record['status']=='succeeded':
                try:
                    output=source_record['data']; normalized=output.get('structuredContent',output)
                    validate('news.search.v1',bindings[0]['input'],normalized,now=source_record['started']+source_record['latency_ms']/1000)
                    args=copy.deepcopy(bindings[1]['input']);args['query']=validate_title(normalized['items'][0]['title'])
                    validate('docs.search.v1',args)
                    derived={'profile':PROFILE,'source_id':source['id'],'source_checkpoint_hash':digest(source_checkpoint)}
                except (ValueError,KeyError,TypeError,IndexError,AttributeError):
                    # A valid empty/unsafe news title legitimately stops the
                    # live connection. Never invent a downstream query.
                    args=None
        if target_checkpoint is not None:
            target_record=target_checkpoint['record']; retained=target_checkpoint.get('typed_input')
            if retained is not None or target_record['input']!={} or target_record['status']=='succeeded':
                if source_checkpoint is None:
                    provenance='source_checkpoint_unavailable'
                elif derived is None or retained!=derived or target_record['input']!=args:
                    raise ComparisonError('The retained documentation input does not match its signed source provenance.')
                elif target_record['started']<source_checkpoint['record']['started']+source_checkpoint['record']['latency_ms']/1000:
                    raise ComparisonError('The retained documentation observation precedes its source result.')
                else:provenance='verified'
        target_result=self.node_result(store,row,target,bindings[1],target_checkpoint,args,allowed=provenance=='verified')
        complete=provenance=='verified' and source_result['assessment']==target_result['assessment']=='contract_passed'
        assessment='provenance_verified' if complete and row['execution_outcome']!='unknown' else 'unknown' if row['execution_outcome']=='unknown' else 'not_succeeded' if row['status'] in ('failed','cancelled') else 'unavailable'
        hashes=[digest(cp) if cp is not None else None for cp in (source_checkpoint,target_checkpoint)]
        return {'ok':True,'evaluator':EVALUATOR,'profile':PROFILE,'inspection_id':'rse_'+digest([EVALUATOR,row['id'],hashes])[:32],
            'run':{'run_id':row['id'],'workflow_id':row['workflow_id'],'status':row['status'],'outcome':row['execution_outcome'],'recorded_at':row['created']},
            'assessment':assessment,'resolved_input':args if provenance=='verified' else None,
            'source':source_result,'target':target_result,
            'provenance':{'status':provenance,'source_node_id':source['id'],'target_node_id':target['id'],
                'source_ref':'cp_'+hashes[0][:32] if hashes[0] is not None else None,
                'actual_input_fingerprint':digest(args) if provenance=='verified' else None},
            'summary':{'provider_calls':0,'model_calls':0,'evidence_writes':0,'automatic_winner':None,
                'factual_accuracy':'not_assessed','relevance':'manual_review_required','paired_comparison_eligible':False},
            'notice':'Retained input provenance and contract checks do not certify factual accuracy, relevance or expert quality. This single-run inspection does not establish a controlled comparison pair.'}
