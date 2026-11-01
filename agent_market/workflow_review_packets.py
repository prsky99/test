"""Identity-minimized, unscored worksheets from retained private typed proof.

No provider content is fetched or graded. Source summaries, excerpts, hosts and
raw proofs stay outside this metadata-only export profile.
"""
import copy
import json
from pathlib import Path
import re

from .capability_registry import digest
from .workflow_comparison import ComparisonError
from .workflow_resolved_evidence import ResolvedEvidence, display_text
from .workflow_typed_flow import validate_title

PROFILE = 'workflow-review-preparation-v1'
RUBRIC_VERSION = 'workflow-review-rubric-v1'
RUBRIC_SHA256 = '8feda26ea73dce348bd3b101cb6147e0e59e62f4a68907fc4cac6d0364c8b8dd'
RUBRIC_FILE = Path(__file__).resolve().parent.parent / 'docs' / 'workflow-evaluation-cases.json'
DIMENSIONS = ('task-relevance','source-fidelity','temporal-fit','missing-data-honesty','typed-query-usefulness','data-sharing-safety')
MAX_TITLE = 240


def rubric():
    """Fail closed if this fixed, unreviewed rubric changes without versioning."""
    try:
        with RUBRIC_FILE.open('rb') as source:raw=source.read(65537)
        if len(raw)>65536:raise ValueError()
        document=json.loads(raw)
        rows=document['human_review']['rubric']
        if (document['dataset_id']!='workflow-typed-flow-cases-v1' or type(document['schema_version']) is not int or document['schema_version']!=1
                or document['review_status']!='pending-human-review' or document['human_expert_reviewed'] is not False
                or document['provider_quality_certified'] is not False
                or document['human_review']['status']!='pending-human-review'
                or not isinstance(rows,list) or len(rows)!=6
                or tuple(row['id'] for row in rows)!=DIMENSIONS
                or any(not isinstance(row,dict) or set(row)!={'id','question','meets','partial','fails'}
                       or any(not isinstance(value,str) or not 1<=len(value)<=600 for value in row.values()) for row in rows)
                or digest(rows)!=RUBRIC_SHA256):
            raise ValueError()
        return copy.deepcopy(rows)
    except (OSError,UnicodeError,ValueError,KeyError,TypeError,AttributeError,RecursionError):
        raise ComparisonError('The versioned review rubric is unavailable.') from None


class ReviewPackets:
    def __init__(self,runtime):
        self.runtime=runtime
        self.evidence=ResolvedEvidence(runtime)

    @staticmethod
    def results(label,result):
        metrics=result['metrics']
        items=[]
        for index,source in enumerate(result['sources'],1):
            title=display_text(source['title'])
            items.append({'label':f'{label} result {index}','title':title[:MAX_TITLE],
                'title_truncated':len(title)>MAX_TITLE,'published_at':source.get('published_at'),
                'retrieved_at':source['retrieved_at']})
        return {'label':label,'contract':result['contract'],'assessment':result['assessment'],'reason':result['reason'],
                'partial':metrics['partial'] if metrics else None,'result_count':metrics['result_count'] if metrics else None,
                'items':items}

    def prepare(self,body):
        if (not isinstance(body,dict) or set(body)!={'run_id'} or not isinstance(body['run_id'],str)
                or not re.fullmatch(r'wr_[a-f0-9]{32}',body['run_id'])):
            raise ComparisonError('Provide one retained private typed test reference.')
        dimensions=rubric()
        with self.evidence.reader() as store:
            proof=self.evidence.inspect_store(store,body)
            row,source,target,bindings=self.evidence.load_typed(store,body['run_id'])
            try:objective=validate_title(bindings[0]['input']['query'])
            except (ValueError,TypeError,KeyError):
                raise ComparisonError('The retained reviewed objective is outside this export profile.') from None
            actual=proof['resolved_input']['query'] if proof['resolved_input'] else None
            # Export context must preserve the exact verified input. Refuse a
            # value needing privacy transformation instead of relabelling its
            # masked form as the original query, regardless of producer age.
            if display_text(objective)!=objective or actual is not None and (not isinstance(actual,str) or display_text(actual)!=actual):
                raise ComparisonError('The retained context requires privacy minimization and cannot be exported as exact input.')
            for dimension in dimensions:
                dimension.update(judgment=None,notes='',reviewer=None,
                    assessability='requires_separately_reviewed_source_material' if dimension['id']=='source-fidelity'
                        else 'metadata_context_only')
            packet={'schema_version':1,'profile':PROFILE,
                'review':{'status':'unreviewed','reviewer':None,'human_expert_reviewed':False,
                    'provider_quality_certified':False,'holdout_status':'not_established','judgments_recorded':False,
                    'factual_accuracy':'not_assessable_from_metadata','source_fidelity':'not_assessable_from_metadata'},
                'context':{'reviewed_objective':objective,'news_window_start_utc':bindings[0]['input']['from_utc'],
                    'language':bindings[0]['input']['language'],'result_limit':bindings[0]['input']['limit'],
                    'actual_documentation_query':actual,
                    'actual_query_status':'verified' if proof['resolved_input'] else 'unavailable'},
                'execution':{'workflow_status':row['status'],'external_outcome':row['execution_outcome'] or 'not_recorded',
                    'input_provenance':proof['provenance']['status']},
                'results':{'source':self.results('Source',proof['source']),'target':self.results('Target',proof['target'])},
                'rubric':{'version':RUBRIC_VERSION,'sha256':RUBRIC_SHA256,'dimensions':dimensions},
                'limitations':[
                    'This is an identity-minimized single-run worksheet, not a guaranteed blind or anonymous evaluation. The task and result titles may identify their topic or origin.',
                    'Only reviewed task context, verified actual input and bounded title/date/partial metadata are included. Source summaries, excerpts, URLs, hosts and raw proofs are omitted.',
                    'Factual accuracy and source fidelity cannot be assessed from this metadata. Separately reviewed source material and qualified independent human judgments are required.',
                    'The rubric is unscored. No expert review, provider quality certification, grade, winner, candidate promotion or controlled comparison eligibility is established.',
                    'Holdout status is not established: no pre-run reservation or protected test split is proved by this worksheet.',
                    'Missing, failed, cancelled and unknown evidence remains explicit. A valid input or node contract result does not prove whole-run success.',
                    'Title text is minimized and may be truncated as flagged. Known-pattern masking is not a complete personal-data detector; an administrator must review the packet before local download.',
                    'No source was fetched and no provider/model call, new run, evidence write, publication or notification was performed. External sharing is not authorized by preparing this packet.'],
                'effects':{'provider_calls':0,'model_calls':0,'evidence_writes':0,'new_runs':0,'publication':False}}
            identity=self.runtime.authority.signature({'audience':'workflow-review-case-v1','profile':PROFILE,
                'retained_proof':proof['inspection_id'],'rubric_hash':RUBRIC_SHA256,'packet_hash':digest(packet)})
            packet['case_id']='rwp_'+identity[:32]
        return {'ok':True,'packet':packet,'download_filename':'agent-concierge-review-'+packet['case_id']+'.json',
                'download_media_type':'application/json'}
