"""Retained typed proofs are inspected without executing or rewriting history."""
import copy
import json
import sqlite3
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent_market.capability_registry import digest, Registry
from agent_market.gateway.admin_auth import create_admin_user
from agent_market.workflow_comparison import Comparison, ComparisonError
from agent_market.workflow_resolved_evidence import ResolvedEvidence, EVALUATOR
from tests.test_admin_security_audit import login, session_headers
from tests.test_workflow_fallback import routing
from tests.test_workflow_fallback_api import routing_api as base_routing_api, H
from tests.test_workflow_typed_flow import typed_routing, saved_typed
from tests.test_workflow_runtime import wait


@pytest.fixture
def routing_api(typed_routing):
    yield from base_routing_api.__wrapped__(typed_routing)


def completed(routing):
    rt,*_=routing;wf=saved_typed(rt);run=wait(rt,rt.submit(wf))
    assert run['status']=='succeeded',run
    return run,{'run_id':run['run_id']}


def alter_checkpoint(rt,run_id,node_id,change,signature=True):
    with rt.store.tx() as db:
        row=db.execute('SELECT payload FROM workflow_checkpoints WHERE run_id=? AND node_id=?',(run_id,node_id)).fetchone()
        value=json.loads(row[0]);change(value)
        db.execute('UPDATE workflow_checkpoints SET payload=?,signature=? WHERE run_id=? AND node_id=?',
                   (json.dumps(value),rt.authority.signature(value) if signature else 'forged',run_id,node_id))


def principal_expiry(rt,run_id,value,missing=False):
    with rt.store.tx() as db:
        authority=json.loads(db.execute('SELECT payload FROM workflow_run_authority WHERE run_id=?',(run_id,)).fetchone()[0])
        principal=authority['principal']
        if missing:principal['payload'].pop('expires',None)
        else:principal['payload']['expires']=value
        principal['signature']=rt.authority.signature(principal['payload'])
        db.execute('UPDATE workflow_run_authority SET payload=?,signature=? WHERE run_id=?',
                   (json.dumps(authority),rt.authority.signature(authority),run_id))


def test_inspection_proves_actual_input_without_calls_writes_or_comparison_admission(typed_routing):
    rt,_,_,calls,*_=typed_routing;run,body=completed(typed_routing);count=len(calls);before=rt.store._db.total_changes
    result=ResolvedEvidence(rt).inspect(body)
    assert result['evaluator']==EVALUATOR and result['assessment']=='provenance_verified'
    assert result['resolved_input']=={'query':'Python asynchronous task documentation','language':'en','limit':3}
    assert result['source']['assessment']==result['target']['assessment']=='contract_passed'
    assert result['provenance']['status']=='verified' and result['provenance']['source_ref'].startswith('cp_')
    assert result['target']['current']=={'definition_matches':True,'eligible_now':True}
    assert result['summary']=={'provider_calls':0,'model_calls':0,'evidence_writes':0,'automatic_winner':None,
        'factual_accuracy':'not_assessed','relevance':'manual_review_required','paired_comparison_eligible':False}
    assert ResolvedEvidence(rt).inspect(body)['inspection_id']==result['inspection_id']
    assert rt.store._db.total_changes==before and len(calls)==count
    assert Comparison(rt).runs()['runs']==[]
    listed=ResolvedEvidence(rt).runs();assert [entry['run_id'] for entry in listed['runs']]==[run['run_id']]
    serialized=json.dumps(result)
    for private in ('primary.example','alternate.example','third.example','signature','binding_hash','credential','structuredContent','excerpt','https://','source_checkpoint_hash'):
        assert private not in serialized


def test_historical_proof_survives_expiry_and_current_approval_drift(typed_routing):
    rt,*_=typed_routing;_,body=completed(typed_routing)
    with patch('agent_market.capability_registry.time.time',return_value=time.time()+3*86400):
        result=ResolvedEvidence(rt).inspect(body)
    assert result['assessment']=='provenance_verified' and not result['target']['current']['eligible_now']
    assert result['target']['current']['definition_matches']
    wf=rt.store.get_workflow(result['run']['workflow_id']);target=wf['nodes'][-1]
    Registry(rt.store).approve(rt.store.resource(target['resource_id']),'docs.search.v1','search_docs')
    result=ResolvedEvidence(rt).inspect(body)
    assert result['assessment']=='provenance_verified' and not result['target']['current']['definition_matches']


@pytest.mark.parametrize('expiry',[0,False,True,'9999999999',None,'missing'])
def test_signed_expiry_must_be_finite_numeric_nonboolean_after_admission(typed_routing,expiry):
    rt,*_=typed_routing;run,body=completed(typed_routing)
    principal_expiry(rt,run['run_id'],expiry,missing=expiry=='missing')
    with pytest.raises(ComparisonError,match='authority'):ResolvedEvidence(rt).inspect(body)


@pytest.mark.parametrize('node_id',['search-1','search-2'])
def test_successful_node_cannot_be_certified_if_authority_expired_at_its_start(typed_routing,node_id):
    rt,*_=typed_routing;run,body=completed(typed_routing)
    cp=json.loads(rt.store.query('SELECT payload FROM workflow_checkpoints WHERE run_id=? AND node_id=?',(run['run_id'],node_id))[0][0])
    principal_expiry(rt,run['run_id'],cp['record']['started'])
    with pytest.raises(ComparisonError,match='checkpoint'):ResolvedEvidence(rt).inspect(body)


def test_historical_start_authority_accepts_later_expiry_without_requiring_response_before_expiry(typed_routing):
    rt,*_=typed_routing;run,body=completed(typed_routing)
    target=json.loads(rt.store.query("SELECT payload FROM workflow_checkpoints WHERE run_id=? AND node_id='search-2'",(run['run_id'],))[0][0])
    record=target['record'];expiry=record['started']+record['latency_ms']/2000
    assert record['started']<expiry<record['started']+record['latency_ms']/1000
    principal_expiry(rt,run['run_id'],expiry)
    with patch('agent_market.workflow_resolved_evidence.time.time',return_value=time.time()+3*86400):
        result=ResolvedEvidence(rt).inspect(body)
    assert result['assessment']=='provenance_verified' and result['target']['assessment']=='contract_passed'
    assert not result['target']['current']['eligible_now']


def test_failed_node_after_historical_expiry_remains_unscored_with_valid_admission(typed_routing):
    rt,*_=typed_routing;run,body=completed(typed_routing)
    target=json.loads(rt.store.query("SELECT payload FROM workflow_checkpoints WHERE run_id=? AND node_id='search-2'",(run['run_id'],))[0][0])
    principal_expiry(rt,run['run_id'],target['record']['started'])
    alter_checkpoint(rt,run['run_id'],'search-2',lambda cp:cp['record'].update(status='failed',data=None))
    with rt.store.tx() as db:db.execute("UPDATE workflow_runs SET status='failed',execution_outcome='failed' WHERE id=?",(run['run_id'],))
    result=ResolvedEvidence(rt).inspect(body)
    assert result['source']['assessment']=='contract_passed' and result['target']['assessment']=='not_succeeded'
    assert result['target']['metrics'] is None and result['assessment']=='not_succeeded'


def test_source_metadata_does_not_return_credentials_inline_urls_or_private_paths(typed_routing,monkeypatch):
    from tests.test_workflow_fallback import output
    def private_metadata(contract):
        value=output(contract)
        if contract=='docs.search.v1':
            value['structuredContent']['items'][0].update(title='Docs token=synthetic-secret https://user:pass@docs.example/private',version='/Users/synthetic/private')
        return value
    monkeypatch.setattr('tests.test_workflow_typed_flow.output',private_metadata)
    rt,*_=typed_routing;_,body=completed(typed_routing);result=ResolvedEvidence(rt).inspect(body)
    text=json.dumps(result)
    for private in ('synthetic-secret','https://','user:pass','/Users/'):
        assert private not in text
    assert result['target']['assessment']=='contract_passed'


@pytest.mark.parametrize('mode',['invalid','unknown'])
def test_failed_and_unknown_target_are_unscored_without_retry(typed_routing,mode):
    rt,_,_,calls,modes,*_=typed_routing;wf=saved_typed(rt);target=rt.store.resource(wf['nodes'][-1]['resource_id'])
    modes[target['url'].split('/')[2]]=mode;run=wait(rt,rt.submit(wf));count=len(calls)
    result=ResolvedEvidence(rt).inspect({'run_id':run['run_id']})
    assert result['target']['assessment'] in ('not_succeeded','unknown') and result['target']['metrics'] is None
    assert result['assessment'] in ('not_succeeded','unknown') and result['provenance']['status']=='verified'
    assert result['summary']['automatic_winner'] is None and len(calls)==count


@pytest.mark.parametrize('title',[None,'https://unsafe.example','x'*501])
def test_valid_news_without_safe_title_has_no_invented_downstream_query(typed_routing,title):
    rt,_,_,calls,*_=typed_routing;wf=saved_typed(rt);rt.typed_test_controls['title']=title
    run=wait(rt,rt.submit(wf));count=len(calls);result=ResolvedEvidence(rt).inspect({'run_id':run['run_id']})
    assert result['resolved_input'] is None and result['target']['metrics'] is None
    assert result['assessment']=='not_succeeded' and len(calls)==count==1
    assert result['provenance']['status']=='unavailable'


@pytest.mark.parametrize('node',['search-1','search-2'])
def test_pruned_checkpoint_is_unavailable_not_success(typed_routing,node):
    rt,*_=typed_routing;run,body=completed(typed_routing)
    with rt.store.tx() as db:db.execute('DELETE FROM workflow_checkpoints WHERE run_id=? AND node_id=?',(run['run_id'],node))
    result=ResolvedEvidence(rt).inspect(body)
    assert result['assessment']=='unavailable' and result['resolved_input'] is None
    assert result['target']['metrics'] is None
    assert result['provenance']['status']==('source_checkpoint_unavailable' if node=='search-1' else 'unavailable')


@pytest.mark.parametrize('change',['mac','run','digest','node','resource','input','output','full_output','started','latency','provenance'])
def test_invalid_signed_target_proof_never_produces_success(typed_routing,change):
    rt,*_=typed_routing;run,body=completed(typed_routing)
    def tamper(cp):
        if change=='run':cp['run_id']='wr_'+'0'*32
        elif change=='digest':cp['digest']='changed'
        elif change=='node':cp['record']['node_id']='search-1'
        elif change=='resource':cp['record']['resource_id']+=1
        elif change=='input':cp['record']['input']['query']='Different documentation query'
        elif change=='output':cp['record']['data']={'items':[],'partial':False};cp['flow_output']=copy.deepcopy(cp['record']['data']);cp['record']['input']['query']='different'
        elif change=='full_output':cp['flow_output']={'items':[],'partial':False}
        elif change=='started':cp['record']['started']=True
        elif change=='latency':cp['record']['latency_ms']=60001
        elif change=='provenance':cp['typed_input']['source_checkpoint_hash']='0'*64
    alter_checkpoint(rt,run['run_id'],'search-2',tamper,signature=change!='mac')
    with pytest.raises(ComparisonError):ResolvedEvidence(rt).inspect(body)


@pytest.mark.parametrize('change',['resource','input','full_output','future','before_run','latency','contract'])
def test_invalid_source_proof_cannot_authorize_downstream_evaluation(typed_routing,change):
    rt,*_=typed_routing;run,body=completed(typed_routing)
    def tamper(cp):
        if change=='resource':cp['record']['resource_id']+=1
        elif change=='input':cp['record']['input']['query']='Changed source objective'
        elif change=='full_output':cp['flow_output']={}
        elif change=='future':cp['record']['started']=time.time()+60
        elif change=='before_run':cp['record']['started']=1
        elif change=='latency':cp['record']['latency_ms']=-1
        else:cp['record']['data']['structuredContent']['items'][0]['url']='http://127.0.0.1/private';cp['flow_output']=copy.deepcopy(cp['record']['data'])
    alter_checkpoint(rt,run['run_id'],'search-1',tamper)
    with pytest.raises(ComparisonError):ResolvedEvidence(rt).inspect(body)


@pytest.mark.parametrize('change',['snapshot','target_mac','connection','consent','authority','principal'])
def test_changed_definition_authority_or_sharing_proof_is_refused(typed_routing,change):
    rt,*_=typed_routing;run,body=completed(typed_routing);run_id=run['run_id']
    with rt.store.tx() as db:
        if change in ('authority','principal'):
            value=json.loads(db.execute('SELECT payload FROM workflow_run_authority WHERE run_id=?',(run_id,)).fetchone()[0])
            signature='forged'
            if change=='principal':value['principal']['payload']['role']='operator';signature=rt.authority.signature(value)
            db.execute('UPDATE workflow_run_authority SET payload=?,signature=? WHERE run_id=?',(json.dumps(value),signature,run_id))
        else:
            value=json.loads(db.execute('SELECT snapshot FROM workflow_runs WHERE id=?',(run_id,)).fetchone()[0])
            signed=value['nodes'][-1]['data']['composition']
            if change=='snapshot':value['name']='changed'
            elif change=='target_mac':signed['mac']='forged'
            elif change=='connection':signed['payload']['connection']['source_binding_hash']='0'*64;signed['mac']=rt.authority.signature(signed['payload'])
            elif change=='consent':signed['payload']['sharing_authorized']=False;signed['mac']=rt.authority.signature(signed['payload'])
            db.execute('UPDATE workflow_runs SET snapshot=? WHERE id=?',(json.dumps(value),run_id))
            if change!='snapshot':
                changed=digest(value);db.execute('UPDATE workflow_runs SET digest=? WHERE id=?',(changed,run_id))
                authority=json.loads(db.execute('SELECT payload FROM workflow_run_authority WHERE run_id=?',(run_id,)).fetchone()[0]);authority['digest']=changed
                db.execute('UPDATE workflow_run_authority SET payload=?,signature=? WHERE run_id=?',(json.dumps(authority),rt.authority.signature(authority),run_id))
    with pytest.raises(ComparisonError):ResolvedEvidence(rt).inspect(body)


@pytest.mark.parametrize('body',[None,[],{}, {'run_id':'../private'}, {'run_id':'wr_'+'0'*32,'url':'https://evil.example'}, {'run_id':1}])
def test_inspector_accepts_only_a_single_bounded_reference(typed_routing,body):
    rt,*_=typed_routing
    with pytest.raises(ComparisonError):ResolvedEvidence(rt).inspect(body)


def test_missing_authority_independent_runs_and_unknown_retention_remain_unscored(typed_routing):
    rt,wf,*_=typed_routing;ordinary=wait(rt,rt.submit(wf))
    with pytest.raises(ComparisonError):ResolvedEvidence(rt).inspect({'run_id':ordinary['run_id']})
    run,body=completed(typed_routing)
    with rt.store.tx() as db:
        db.execute('DELETE FROM workflow_checkpoints WHERE run_id=?',(run['run_id'],))
        db.execute("UPDATE workflow_runs SET status='failed',execution_outcome='unknown' WHERE id=?",(run['run_id'],))
    result=ResolvedEvidence(rt).inspect(body)
    assert result['assessment']=='unknown' and result['source']['assessment']==result['target']['assessment']=='unknown'
    with rt.store.tx() as db:db.execute('DELETE FROM workflow_run_authority WHERE run_id=?',(run['run_id'],))
    with pytest.raises(ComparisonError):ResolvedEvidence(rt).inspect(body)
    assert ResolvedEvidence(rt).runs()['runs']==[]


def test_readonly_in_memory_store_leaves_no_transaction_or_changes(typed_routing):
    rt,*_=typed_routing;_,body=completed(typed_routing)
    db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
    with rt.store._lock:rt.store._db.backup(db)
    memory=SimpleNamespace(_path=':memory:',_db=db,_lock=threading.RLock())
    try:
        before=db.total_changes;result=ResolvedEvidence(SimpleNamespace(store=memory,authority=rt.authority)).inspect(body)
        assert result['assessment']=='provenance_verified' and db.total_changes==before and not db.in_transaction
    finally:db.close()


@pytest.mark.parametrize('table,column,limit',[
    ('workflow_runs','snapshot',180000),('workflow_checkpoints','payload',262144),('workflow_run_authority','payload',16384)])
def test_raw_retained_payload_limits_cannot_be_bypassed_with_json_whitespace(typed_routing,table,column,limit):
    rt,*_=typed_routing;run,body=completed(typed_routing)
    # Fixed test-only names exercise all three bounded read sentinels.
    with rt.store.tx() as db:
        if table=='workflow_runs':
            row=db.execute('SELECT snapshot FROM workflow_runs WHERE id=?',(run['run_id'],)).fetchone()
            db.execute('UPDATE workflow_runs SET snapshot=? WHERE id=?',(row[0]+' '*limit,run['run_id']))
        elif table=='workflow_checkpoints':
            row=db.execute("SELECT payload FROM workflow_checkpoints WHERE run_id=? AND node_id='search-1'",(run['run_id'],)).fetchone()
            db.execute("UPDATE workflow_checkpoints SET payload=? WHERE run_id=? AND node_id='search-1'",(row[0]+' '*limit,run['run_id']))
        else:
            row=db.execute('SELECT payload FROM workflow_run_authority WHERE run_id=?',(run['run_id'],)).fetchone()
            db.execute('UPDATE workflow_run_authority SET payload=? WHERE run_id=?',(row[0]+' '*limit,run['run_id']))
    with pytest.raises(ComparisonError):ResolvedEvidence(rt).inspect(body)


def test_historical_dependency_time_and_explicit_highest_role_are_verified(typed_routing):
    rt,*_=typed_routing;run,body=completed(typed_routing)
    source=json.loads(rt.store.query("SELECT payload FROM workflow_checkpoints WHERE run_id=? AND node_id='search-1'",(run['run_id'],))[0][0])
    alter_checkpoint(rt,run['run_id'],'search-2',lambda cp:cp['record'].update(started=source['record']['started']))
    with pytest.raises(ComparisonError,match='precedes'):ResolvedEvidence(rt).inspect(body)
    with rt.store.tx() as db:
        value=json.loads(db.execute('SELECT payload FROM workflow_run_authority WHERE run_id=?',(run['run_id'],)).fetchone()[0])
        value['principal']['payload']['role']='operator';value['principal']['signature']=rt.authority.signature(value['principal']['payload'])
        db.execute('UPDATE workflow_run_authority SET payload=?,signature=? WHERE run_id=?',(json.dumps(value),rt.authority.signature(value),run['run_id']))
    with pytest.raises(ComparisonError,match='authority'):ResolvedEvidence(rt).inspect(body)


def test_cancelled_after_output_is_unscored_even_when_flow_output_was_retained(typed_routing):
    rt,*_=typed_routing;run,body=completed(typed_routing)
    alter_checkpoint(rt,run['run_id'],'search-2',lambda cp:cp['record'].update(status='cancelled',data=None))
    with rt.store.tx() as db:db.execute("UPDATE workflow_runs SET status='cancelled',execution_outcome='cancelled' WHERE id=?",(run['run_id'],))
    result=ResolvedEvidence(rt).inspect(body)
    assert result['target']['metrics'] is None and result['target']['assessment']=='not_succeeded'
    assert result['run']['status']=='cancelled' and result['summary']['automatic_winner'] is None


@pytest.mark.parametrize('role',['operator','admin'])
def test_inspector_has_only_private_highest_admin_routes(routing_api,role):
    routing,public,admin=routing_api;rt,*_=routing
    with rt.store.tx() as db:create_admin_user(db,'resolved-viewer','long-reader-password','Reader',role)
    headers=session_headers(login(admin,'resolved-viewer','long-reader-password').json()['token'])
    for method,path in [('GET','/admin/api/workflow-composer/resolved-input/runs'),('POST','/admin/api/workflow-composer/resolved-input')]:
        assert admin.request(method,path,headers=headers).status_code==403
        assert admin.request(method,path).status_code in (401,403)
        assert public.request(method,path).status_code==404


def test_dynamic_api_has_no_store_and_never_runs_or_creates_quality_evidence(routing_api):
    routing,_,admin=routing_api;rt,_,_,calls,*_=routing;_,body=completed(routing)
    count=len(calls);runs=len(rt.store.query('SELECT id FROM workflow_runs'));evidence=len(rt.store.query('SELECT id FROM capability_evidence'))
    listed=admin.get('/admin/api/workflow-composer/resolved-input/runs',headers=H)
    assert listed.status_code==200 and listed.headers['cache-control']=='no-store'
    response=admin.post('/admin/api/workflow-composer/resolved-input',headers=H,json=body)
    assert response.status_code==200,response.text
    assert response.headers['cache-control']=='no-store' and response.json()['assessment']=='provenance_verified'
    bad=admin.post('/admin/api/workflow-composer/resolved-input',headers=H,json={**body,'execute':True})
    assert bad.status_code==409 and bad.headers['cache-control']=='no-store'
    malformed=admin.post('/admin/api/workflow-composer/resolved-input',headers={**H,'content-type':'application/json'},content='{')
    # The common AdminRoute rejects malformed JSON before invoking this API.
    assert malformed.status_code==400 and malformed.json()['detail']=='A valid JSON object is required.'
    assert len(calls)==count and len(rt.store.query('SELECT id FROM workflow_runs'))==runs and len(rt.store.query('SELECT id FROM capability_evidence'))==evidence
