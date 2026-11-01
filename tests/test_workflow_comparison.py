"""Recorded comparisons are read-only and preserve historical/current distinctions."""
import copy
import json
from unittest.mock import patch

import pytest

from agent_market.workflow_comparison import Comparison,ComparisonError
from agent_market.workflow_composer import Composer,SAVE
from tests.test_workflow_composer import generate,save
from tests.test_workflow_fallback import routing
from tests.test_workflow_fallback_api import routing_api,H
from tests.test_workflow_runtime import wait
from tests.test_admin_security_audit import login,session_headers
from agent_market.gateway.admin_auth import create_admin_user


def paired(routing,second_mode=None,prompt="Python documentation search"):
    rt,_,_,calls,modes,*_=routing;draft=generate(rt,prompt=prompt);contract=draft['proposal']['intent']['contracts'][0]
    first=rt.store.get_workflow(save(rt,draft)['id']);a=wait(rt,rt.submit(first))
    candidate=draft['proposal']['candidates'][1]
    revised=Composer(rt).revise({k:draft[k] for k in ('proposal','signature')}|{'selections':{contract:candidate['id']}},1)
    second=rt.store.get_workflow(save(rt,revised)['id'])
    if second_mode:modes[rt.store.resource(candidate['pin']['resource_id'])['url'].split('/')[2]]=second_mode
    b=wait(rt,rt.submit(second))
    return a,b,{'left_run_id':a['run_id'],'right_run_id':b['run_id'],'contract':contract}


def test_same_input_comparison_reads_signed_results_without_calls_or_writes(routing):
    rt,_,_,calls,*_=routing;a,b,body=paired(routing);before=rt.store._db.total_changes;count=len(calls)
    result=Comparison(rt).compare(body)
    assert result['summary']['both_contracts_passed']
    assert result['left']['metrics']['result_count']==1 and result['summary']['source_overlap']==1
    assert result['summary']['automatic_winner'] is None and result['summary']['factual_accuracy']=='not_assessed'
    assert result['left']['current']=={'definition_matches':True,'eligible_now':True}
    assert rt.store._db.total_changes==before and len(calls)==count
    assert result['comparison_id']==Comparison(rt).compare(body)['comparison_id']
    text=json.dumps(result)
    for private in ['primary.example','alternate.example','third.example','binding_hash','signature','mac','Python documentation search','excerpt','content_md']:
        assert private not in text
    listed=Comparison(rt).runs()['runs'];assert {a['run_id'],b['run_id']}=={x['run_id'] for x in listed}


def test_historical_validity_does_not_expire_or_imply_current_readiness(routing):
    import time
    rt,*_=routing;_,_,body=paired(routing)
    with patch('agent_market.capability_registry.time.time',return_value=time.time()+3*86400):
        result=Comparison(rt).compare(body)
    assert result['summary']['both_contracts_passed']
    assert result['left']['current']['eligible_now'] is False
    assert result['left']['current']['definition_matches'] is True


@pytest.mark.parametrize('mode',['error','unknown','invalid'])
def test_failed_or_unknown_test_is_never_scored_as_success(routing,mode):
    rt,_,_,calls,*_=routing;a,b,body=paired(routing,mode);before=len(calls)
    result=Comparison(rt).compare(body)
    assert not result['summary']['both_contracts_passed'] and result['right']['metrics'] is None
    assert result['summary']['latency_delta_ms'] is None and result['summary']['source_overlap'] is None
    assert result['summary']['automatic_winner'] is None and len(calls)==before
    assert rt.get(b['run_id'])['execution_outcome']==b['execution_outcome']


@pytest.mark.parametrize('change',['snapshot','node_mac','authority','principal','checkpoint_mac','checkpoint_scope','checkpoint_input','checkpoint_output','checkpoint_clock'])
def test_tampered_evidence_never_produces_comparison_metrics(routing,change):
    rt,*_=routing;_,b,body=paired(routing);rid=b['run_id']
    with rt.store.tx() as db:
        if change in ('snapshot','node_mac'):
            row=db.execute('SELECT snapshot FROM workflow_runs WHERE id=?',(rid,)).fetchone();snapshot=json.loads(row[0])
            if change=='snapshot':snapshot['name']='Different workflow'
            else:snapshot['nodes'][1]['data']['composition']['mac']='forged'
            db.execute('UPDATE workflow_runs SET snapshot=? WHERE id=?',(json.dumps(snapshot),rid))
            if change=='node_mac':
                from agent_market.capability_registry import digest
                changed_digest=digest(snapshot);db.execute('UPDATE workflow_runs SET digest=? WHERE id=?',(changed_digest,rid))
                original=db.execute('SELECT payload FROM workflow_run_authority WHERE run_id=?',(rid,)).fetchone();proof=json.loads(original[0]);proof['digest']=changed_digest
                db.execute('UPDATE workflow_run_authority SET payload=?,signature=? WHERE run_id=?',(json.dumps(proof),rt.authority.signature(proof),rid))
        elif change in ('authority','principal'):
            row=db.execute('SELECT payload FROM workflow_run_authority WHERE run_id=?',(rid,)).fetchone();p=json.loads(row[0]);signature='forged'
            if change=='principal':p['principal']['signature']='forged';signature=rt.authority.signature(p)
            db.execute('UPDATE workflow_run_authority SET payload=?,signature=? WHERE run_id=?',(json.dumps(p),signature,rid))
        else:
            row=db.execute("SELECT node_id,payload FROM workflow_checkpoints WHERE run_id=? AND node_id!='start'",(rid,)).fetchone();p=json.loads(row['payload']);signature='forged'
            if change=='checkpoint_scope':p['run_id']='wr_'+'0'*32
            elif change=='checkpoint_input':p['record']['input']['query']='Different docs'
            elif change=='checkpoint_output':p['record']['data']={'structuredContent':{'items':[{'title':'invalid'}],'partial':False}}
            elif change=='checkpoint_clock':p['record']['started']=-1
            if change!='checkpoint_mac':signature=rt.authority.signature(p)
            db.execute('UPDATE workflow_checkpoints SET payload=?,signature=? WHERE run_id=? AND node_id=?',(json.dumps(p),signature,rid,row['node_id']))
    with pytest.raises(ComparisonError):Comparison(rt).compare(body)


def test_different_inputs_and_same_agent_tests_are_not_matched(routing):
    rt,*_=routing;a,b,body=paired(routing);draft=generate(rt,prompt='Different documentation query');wf=rt.store.get_workflow(save(rt,draft)['id']);other=wait(rt,rt.submit(wf))
    with pytest.raises(ComparisonError,match='identical'):Comparison(rt).compare({**body,'right_run_id':other['run_id']})
    wf=rt.store.get_workflow(a['workflow_id']);same=wait(rt,rt.submit(wf))
    with pytest.raises(ComparisonError,match='different registered'):Comparison(rt).compare({**body,'right_run_id':same['run_id']})


def test_missing_checkpoint_unknown_and_retention_are_truthful(routing):
    rt,*_=routing;_,b,body=paired(routing)
    with rt.store.tx() as db:
        db.execute("DELETE FROM workflow_checkpoints WHERE run_id=? AND node_id!='start'",(b['run_id'],))
        db.execute("UPDATE workflow_runs SET status='failed',execution_outcome='unknown' WHERE id=?",(b['run_id'],))
    result=Comparison(rt).compare(body)
    assert result['right']['assessment']=='unknown' and result['right']['metrics'] is None
    with rt.store.tx() as db:db.execute('DELETE FROM workflow_run_authority WHERE run_id=?',(b['run_id'],))
    with pytest.raises(ComparisonError):Comparison(rt).compare(body)
    assert b['run_id'] not in [x['run_id'] for x in Comparison(rt).runs()['runs']]


def test_current_approval_drift_does_not_rewrite_historical_assessment(routing):
    from agent_market.capability_registry import Registry
    rt,*_=routing;_,_,body=paired(routing);draft=generate(rt)
    for c in draft['proposal']['candidates']:Registry(rt.store).approve(rt.store.resource(c['pin']['resource_id']),'docs.search.v1','search_docs')
    result=Comparison(rt).compare(body)
    assert result['summary']['both_contracts_passed'] and not result['left']['current']['definition_matches']


@pytest.mark.parametrize('body',[None,[],{}, {'left_run_id':'../etc','right_run_id':'wr_'+'0'*32,'contract':'docs.search.v1'},
 {'left_run_id':'wr_'+'0'*32,'right_run_id':'wr_'+'0'*32,'contract':'docs.search.v1'},
 {'left_run_id':'wr_'+'0'*32,'right_run_id':'wr_'+'1'*32,'contract':'products.compare.v1'},
 {'left_run_id':'wr_'+'0'*32,'right_run_id':'wr_'+'1'*32,'contract':{}},
 {'left_run_id':'wr_'+'0'*32,'right_run_id':'wr_'+'1'*32,'contract':'docs.search.v1','target':'https://evil.example'}])
def test_malformed_comparison_requests_fail_closed(routing,body):
    rt,*_=routing
    with pytest.raises(ComparisonError):Comparison(rt).compare(body)


@pytest.mark.parametrize('role',['operator','admin'])
def test_comparison_is_highest_admin_only_without_public_endpoints(routing_api,role):
    routing,public,admin=routing_api;rt,*_=routing
    with rt.store.tx() as db:create_admin_user(db,'comparison-reader','reader-password-long','Reader',role)
    token=login(admin,'comparison-reader','reader-password-long').json()['token'];headers=session_headers(token)
    for method,path in [('GET','/admin/api/workflow-composer/comparison/runs'),('POST','/admin/api/workflow-composer/comparison')]:
        assert admin.request(method,path,headers=headers).status_code==403
        assert admin.request(method,path).status_code in (401,403)
        assert public.request(method,path).status_code==404


def test_private_comparison_api_has_no_store_and_no_side_effects(routing_api):
    routing,_,admin=routing_api;rt,_,_,calls,*_=routing;_,_,body=paired(routing);count=len(calls);runs=len(rt.store.query('SELECT * FROM workflow_runs'));evidence=len(rt.store.query('SELECT * FROM capability_evidence'))
    listed=admin.get('/admin/api/workflow-composer/comparison/runs',headers=H);assert listed.status_code==200,listed.text
    assert listed.headers['cache-control']=='no-store'
    result=admin.post('/admin/api/workflow-composer/comparison',headers=H,json=body);assert result.status_code==200,result.text
    assert result.headers['cache-control']=='no-store' and result.json()['summary']['provider_calls']==0
    assert len(calls)==count and len(rt.store.query('SELECT * FROM workflow_runs'))==runs and len(rt.store.query('SELECT * FROM capability_evidence'))==evidence
    assert admin.post('/admin/api/workflow-composer/comparison',headers=H,json={**body,'url':'http://127.0.0.1'}).status_code in (400,409)


def test_in_memory_comparison_retains_no_transaction_or_writes(routing):
    import sqlite3,threading
    from types import SimpleNamespace
    rt,*_=routing;_,_,body=paired(routing)
    db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
    with rt.store._lock:rt.store._db.backup(db)
    memory=SimpleNamespace(_path=':memory:',_db=db,_lock=threading.RLock())
    try:
        before=db.total_changes
        result=Comparison(SimpleNamespace(store=memory,authority=rt.authority)).compare(body)
        assert result['summary']['both_contracts_passed'] and db.total_changes==before and not db.in_transaction
    finally:db.close()


def test_unrecorded_outcome_and_empty_sources_are_not_quality_scores(routing,monkeypatch):
    def empty():return {'content':[],'structuredContent':{'items':[],'partial':False}}
    monkeypatch.setattr('tests.test_workflow_fallback.output',empty)
    rt,*_=routing;_,b,body=paired(routing);result=Comparison(rt).compare(body)
    assert result['left']['metrics']['result_count']==0 and result['summary']['source_overlap'] is None
    assert result['summary']['automatic_winner'] is None
    with rt.store.tx() as db:db.execute('UPDATE workflow_runs SET execution_outcome=NULL WHERE id=?',(b['run_id'],))
    result=Comparison(rt).compare(body);assert result['right']['assessment']=='unavailable' and result['right']['metrics'] is None


def test_news_period_and_historical_date_metrics_are_preserved(routing,monkeypatch):
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from agent_market.collector import usage
    from agent_market.capability_registry import Registry
    from agent_market.capability_contracts import run_test
    from tests.test_workflow_fallback import tool,output
    rt,_,ids,_,_,_,remote=routing;spec=tool('news.search.v1')
    monkeypatch.setattr('tests.test_workflow_fallback.output',lambda:output('news.search.v1'));remote.tools=[spec]
    for rid in ids:
        compact=usage.compact_tools([spec]);rt.store.record_usage(rid,compact,usage.tools_hash(compact),{},None,{'ok':True},full_tools=[spec])
        registry=Registry(rt.store);registry.approve(rt.store.resource(rid),'news.search.v1','search_news')
        async def runner(identity,**kwargs):
            response=rt.proxy.execute(identity,kwargs['tool'],kwargs['arguments'])
            return {'execution_succeeded':response['ok'],'simulated':False,'output':response['result']}
        with ThreadPoolExecutor(max_workers=1) as pool:
            result=pool.submit(lambda:asyncio.run(run_test(registry,rt.store.resource(rid),'news.search.v1',{'query':'AI news','language':'en','limit':3,'from_utc':'2026-01-01T00:00:00Z'},runner))).result()
        assert result['ok']
    _,_,body=paired(routing,prompt='AI news');result=Comparison(rt).compare(body)
    assert result['contract']=='news.search.v1' and result['left']['metrics']['dated_count']==1
    assert result['left']['metrics']['newest_published_at'] is not None
    independent=generate(rt,prompt='AI news');wf=rt.store.get_workflow(save(rt,independent)['id']);run=wait(rt,rt.submit(wf))
    with pytest.raises(ComparisonError,match='identical'):Comparison(rt).compare({**body,'right_run_id':run['run_id']})


def test_recent_inventory_uses_index_and_bounded_metadata_projection(routing):
    rt,*_=routing
    plan=rt.store.query("EXPLAIN QUERY PLAN SELECT id FROM workflow_runs WHERE source='admin' AND status IN ('succeeded','failed','cancelled') ORDER BY created DESC LIMIT 100")
    assert any('workflow_admin_runs_recent' in row['detail'] for row in plan)
    assert not any('TEMP B-TREE' in row['detail'] for row in plan)
    assert Comparison(rt).runs()['runs']==[]
