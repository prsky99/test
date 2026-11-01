"""Unscored private review packets retain proof boundaries and minimize identity."""
import copy
from contextlib import contextmanager
import json
import sqlite3
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent_market.capability_registry import Registry
from agent_market.workflow_comparison import Comparison, ComparisonError
from agent_market.workflow_resolved_evidence import ResolvedEvidence
from agent_market.workflow_review_packets import ReviewPackets, PROFILE, RUBRIC_VERSION, RUBRIC_SHA256, DIMENSIONS, MAX_TITLE
from tests.test_workflow_fallback import routing, output
from tests.test_workflow_resolved_evidence import completed, alter_checkpoint, principal_expiry
from tests.test_workflow_typed_flow import typed_routing, saved_typed
from tests.test_workflow_runtime import wait


def test_packet_contains_verified_context_and_blank_rubric_without_private_identity_or_grades(typed_routing):
    rt,_,_,calls,*_=typed_routing;run,body=completed(typed_routing)
    before=rt.store._db.total_changes;count=len(calls);service=ReviewPackets(rt)
    response=service.prepare(body);packet=response['packet']
    assert set(response)=={'ok','packet','download_filename','download_media_type'} and response['ok']
    assert packet['profile']==PROFILE and packet['schema_version']==1 and packet['case_id'].startswith('rwp_')
    assert response['download_filename']=='agent-concierge-review-'+packet['case_id']+'.json'
    assert response['download_media_type']=='application/json'
    assert packet['context']=={'reviewed_objective':'Python news and documentation search','news_window_start_utc':rt.store.get_workflow(run['workflow_id'])['nodes'][1]['data']['input']['from_utc'],
        'language':'en','result_limit':3,'actual_documentation_query':'Python asynchronous task documentation','actual_query_status':'verified'}
    assert packet['context']['reviewed_objective']!=packet['context']['actual_documentation_query']
    assert packet['review']=={'status':'unreviewed','reviewer':None,'human_expert_reviewed':False,'provider_quality_certified':False,
        'holdout_status':'not_established','judgments_recorded':False,'factual_accuracy':'not_assessable_from_metadata','source_fidelity':'not_assessable_from_metadata'}
    assert packet['rubric']['version']==RUBRIC_VERSION and packet['rubric']['sha256']==RUBRIC_SHA256
    assert tuple(row['id'] for row in packet['rubric']['dimensions'])==DIMENSIONS
    for row in packet['rubric']['dimensions']:
        assert row['judgment'] is row['reviewer'] is None and row['notes']==''
        assert row['assessability']==('requires_separately_reviewed_source_material' if row['id']=='source-fidelity' else 'metadata_context_only')
    assert packet['effects']=={'provider_calls':0,'model_calls':0,'evidence_writes':0,'new_runs':0,'publication':False}
    assert packet['results']['source']['assessment']==packet['results']['target']['assessment']=='contract_passed'
    assert packet['results']['source']['items'][0]['label']=='Source result 1'
    assert packet['results']['target']['items'][0]['label']=='Target result 1'
    assert set(packet['results']['target']['items'][0])=={'label','title','title_truncated','published_at','retrieved_at'}
    serialized=json.dumps(packet)
    for private in (run['run_id'],'wr_','ag_','cv_','rse_','cp_','primary.example','alternate.example','third.example','sources.example','https://','structuredContent','binding_hash','signature','latency_ms','eval_grade','eligible_now','agent_label','source_host','excerpt','fromRawProof'):
        # Notices disclose that excerpts are omitted; there is no excerpt field.
        if private=='excerpt':assert not any('excerpt' in key for key in packet['results']['target']['items'][0]);continue
        assert private not in serialized
    assert rt.store._db.total_changes==before and len(calls)==count
    assert service.prepare(body)['packet']==packet and Comparison(rt).runs()['runs']==[]


def test_packet_identity_ignores_current_readiness_but_changes_with_retained_content_and_key(typed_routing):
    rt,*_=typed_routing;run,body=completed(typed_routing);service=ReviewPackets(rt)
    initial=service.prepare(body)['packet']
    wf=rt.store.get_workflow(run['workflow_id']);target=wf['nodes'][-1]
    Registry(rt.store).approve(rt.store.resource(target['resource_id']),'docs.search.v1','search_docs')
    with patch('agent_market.capability_registry.time.time',return_value=time.time()+3*86400):
        assert service.prepare(body)['packet']==initial
    altered=copy.copy(rt);altered.authority=copy.copy(rt.authority);altered.authority.key=b'a separate synthetic packet signing key'
    # Historical proofs must continue using their original key. A pure proxy
    # changes only the case-domain signature, not proof verification.
    original=rt.authority.signature
    def signature(payload):
        return altered.authority.signature(payload) if payload.get('audience')=='workflow-review-case-v1' else original(payload)
    with patch.object(rt.authority,'signature',side_effect=signature):
        assert service.prepare(body)['packet']['case_id']!=initial['case_id']
    def change(cp):
        cp['record']['data']['structuredContent']['items'][0]['title']='Another retained documentation title'
        cp['flow_output']=copy.deepcopy(cp['record']['data'])
    alter_checkpoint(rt,run['run_id'],'search-2',change)
    assert service.prepare(body)['packet']['case_id']!=initial['case_id']


def test_summary_excerpt_host_and_private_provider_metadata_are_not_exported(typed_routing,monkeypatch):
    marker='private-summary-excerpt-marker'
    def provider(contract):
        result=output(contract);item=result['structuredContent']['items'][0]
        if contract=='docs.search.v1':item.update(excerpt=marker,title='Docs token=synthetic-secret https://user:pass@docs.example/private person@example.org',version='/Users/synthetic/private')
        else:item.update(summary=marker,source='Internal provider marker')
        return result
    monkeypatch.setattr('tests.test_workflow_typed_flow.output',provider)
    rt,*_=typed_routing;_,body=completed(typed_routing);packet=ReviewPackets(rt).prepare(body)['packet'];serialized=json.dumps(packet)
    for value in (marker,'synthetic-secret','user:pass','person@example.org','docs.example','Internal provider marker','/Users/'):
        assert value not in serialized
    assert '[REDACTED]' in packet['results']['target']['items'][0]['title']


def test_titles_are_bounded_and_explicitly_marked_truncated(typed_routing,monkeypatch):
    def provider(contract):
        result=output(contract)
        if contract=='docs.search.v1':result['structuredContent']['items'][0]['title']='D'*1000
        return result
    monkeypatch.setattr('tests.test_workflow_typed_flow.output',provider)
    rt,*_=typed_routing;_,body=completed(typed_routing);packet=ReviewPackets(rt).prepare(body)['packet']
    item=packet['results']['target']['items'][0]
    assert item['title']=='D'*MAX_TITLE and item['title_truncated'] is True
    assert packet['results']['source']['items'][0]['title_truncated'] is False


@pytest.mark.parametrize('field',['objective','actual_query'])
def test_exact_export_context_refuses_known_privacy_transformation_independently_of_producer(typed_routing,monkeypatch,field):
    rt,*_=typed_routing;_,body=completed(typed_routing);service=ReviewPackets(rt)
    proof=service.evidence.inspect(body)
    # These are deliberately mocked verified historic producer outputs. The
    # current durable runtime already masks these values and prevents a valid
    # typed connection; this test isolates the export-purpose boundary.
    if field=='actual_query':proof['resolved_input']['query']='Documentation token=synthetic-export-secret'
    monkeypatch.setattr(service.evidence,'inspect_store',lambda store,request:proof)
    original=service.evidence.load_typed
    if field=='objective':
        def load(store,run_id):
            row,source,target,bindings=original(store,run_id);bindings=copy.deepcopy(bindings)
            bindings[0]['input']['query']='Documentation password=synthetic-export-secret'
            return row,source,target,bindings
        monkeypatch.setattr(service.evidence,'load_typed',load)
    with pytest.raises(ComparisonError,match='privacy minimization'):
        service.prepare(body)


@pytest.mark.parametrize('mode',['invalid','unknown'])
def test_unsuccessful_target_is_never_scored_or_retried(typed_routing,mode):
    rt,_,_,calls,modes,*_=typed_routing;wf=saved_typed(rt)
    modes[rt.store.resource(wf['nodes'][-1]['resource_id'])['url'].split('/')[2]]=mode
    run=wait(rt,rt.submit(wf));count=len(calls);packet=ReviewPackets(rt).prepare({'run_id':run['run_id']})['packet']
    assert packet['execution']['external_outcome'] in ('failed','unknown')
    assert packet['results']['target']['assessment'] in ('not_succeeded','unknown')
    assert packet['results']['target']['result_count'] is None and packet['results']['target']['items']==[]
    assert packet['context']['actual_query_status']=='verified' and packet['review']['status']=='unreviewed'
    assert len(calls)==count


@pytest.mark.parametrize('node',['search-1','search-2'])
def test_missing_retained_proof_has_no_fabricated_actual_query(typed_routing,node):
    rt,*_=typed_routing;run,body=completed(typed_routing)
    with rt.store.tx() as db:db.execute('DELETE FROM workflow_checkpoints WHERE run_id=? AND node_id=?',(run['run_id'],node))
    packet=ReviewPackets(rt).prepare(body)['packet']
    assert packet['context']['actual_documentation_query'] is None and packet['context']['actual_query_status']=='unavailable'
    assert packet['results']['target']['items']==[] and packet['results']['target']['result_count'] is None
    assert packet['review']['holdout_status']=='not_established'


def test_unknown_without_checkpoints_and_empty_source_remain_unscored(typed_routing):
    rt,*_=typed_routing;run,body=completed(typed_routing)
    with rt.store.tx() as db:
        db.execute('DELETE FROM workflow_checkpoints WHERE run_id=?',(run['run_id'],))
        db.execute("UPDATE workflow_runs SET status='failed',execution_outcome='unknown' WHERE id=?",(run['run_id'],))
    packet=ReviewPackets(rt).prepare(body)['packet']
    assert packet['execution']['external_outcome']=='unknown' and packet['results']['source']['assessment']==packet['results']['target']['assessment']=='unknown'
    assert packet['context']['actual_documentation_query'] is None
    rt.typed_test_controls['title']=None;wf=saved_typed(rt);empty=wait(rt,rt.submit(wf));packet=ReviewPackets(rt).prepare({'run_id':empty['run_id']})['packet']
    assert packet['results']['source']['result_count']==0 and packet['context']['actual_query_status']=='unavailable'


@pytest.mark.parametrize('change',['signature','source_input','target_input','source_provenance','source_output','expired_before_admission','expired_before_target'])
def test_packet_cannot_bypass_historical_proof_and_authority_gates(typed_routing,change):
    rt,*_=typed_routing;run,body=completed(typed_routing)
    if change=='expired_before_admission':principal_expiry(rt,run['run_id'],0)
    elif change=='expired_before_target':
        cp=json.loads(rt.store.query("SELECT payload FROM workflow_checkpoints WHERE run_id=? AND node_id='search-2'",(run['run_id'],))[0][0])
        principal_expiry(rt,run['run_id'],cp['record']['started'])
    else:
        node='search-1' if change in ('source_input','source_output') else 'search-2'
        def modify(cp):
            if change in ('source_input','target_input'):cp['record']['input']['query']='Different reviewed task'
            elif change=='source_provenance':cp['typed_input']['source_checkpoint_hash']='0'*64
            elif change=='source_output':cp['flow_output']={}
        alter_checkpoint(rt,run['run_id'],node,modify,signature=change!='signature')
    with pytest.raises(ComparisonError):ReviewPackets(rt).prepare(body)


@pytest.mark.parametrize('body',[None,[],{}, {'run_id':1},{'run_id':'../private'}, {'run_id':'wr_'+'0'*32,'include_excerpts':True}, {'run_id':'wr_'+'0'*32,'reviewer':'Private Name'}])
def test_packet_request_accepts_only_one_bounded_reference(typed_routing,body):
    rt,*_=typed_routing
    with pytest.raises(ComparisonError):ReviewPackets(rt).prepare(body)


@pytest.mark.parametrize('change',['hash','shape','expert','version','missing','oversize','malformed'])
def test_rubric_is_version_pinned_bounded_and_never_promoted_to_expert_review(typed_routing,tmp_path,monkeypatch,change):
    import agent_market.workflow_review_packets as packets
    document=json.loads(packets.RUBRIC_FILE.read_text());target=tmp_path/'rubric.json'
    if change=='hash':document['human_review']['rubric'][0]['question']='A different question'
    elif change=='shape':document['human_review']['rubric'][0]['score']=5
    elif change=='expert':document['human_expert_reviewed']=True
    elif change=='version':document['schema_version']=True
    raw=json.dumps(document)
    if change=='oversize':raw+=' '*65537
    elif change=='malformed':raw='{'
    if change!='missing':target.write_text(raw)
    monkeypatch.setattr(packets,'RUBRIC_FILE',target)
    rt,*_=typed_routing;_,body=completed(typed_routing)
    with pytest.raises(ComparisonError,match='versioned review rubric'):packets.ReviewPackets(rt).prepare(body)


def test_packet_uses_one_read_snapshot_even_if_live_row_changes_between_proof_reads(typed_routing,monkeypatch):
    rt,*_=typed_routing;run,body=completed(typed_routing);service=ReviewPackets(rt)
    original=service.evidence.load_typed;calls=[]
    def load(store,run_id):
        result=original(store,run_id);calls.append(id(store))
        if len(calls)==1:
            other=sqlite3.connect(rt.store._path,timeout=.1)
            try:
                other.execute('UPDATE workflow_runs SET snapshot=? WHERE id=?',('{}',run_id));other.commit()
            finally:other.close()
        return result
    monkeypatch.setattr(service.evidence,'load_typed',load)
    packet=service.prepare(body)['packet']
    assert len(calls)==2 and len(set(calls))==1 and packet['context']['actual_query_status']=='verified'
    with pytest.raises(ComparisonError):ResolvedEvidence(rt).inspect(body)


def test_memory_packet_leaves_no_transaction_or_mutations(typed_routing):
    rt,*_=typed_routing;_,body=completed(typed_routing);db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
    with rt.store._lock:rt.store._db.backup(db)
    memory=SimpleNamespace(_path=':memory:',_db=db,_lock=threading.RLock())
    try:
        before=db.total_changes;packet=ReviewPackets(SimpleNamespace(store=memory,authority=rt.authority)).prepare(body)['packet']
        assert packet['context']['actual_query_status']=='verified' and db.total_changes==before and not db.in_transaction
    finally:db.close()
