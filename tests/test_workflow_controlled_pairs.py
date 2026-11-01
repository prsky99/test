"""Actual controlled source-once pairs use isolated MCP transports and stores."""
import copy
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from unittest.mock import patch

import pytest

from agent_market.gateway.admin_auth import init_admin_auth_db
from agent_market.execution_authority import controls,set_controls
from agent_market.workflow_backup import quarantine
from agent_market.workflow_comparison import Comparison,ComparisonError
from agent_market.workflow_controlled_pairs import ControlledPairs
from agent_market.workflow_paired_flow import PROFILE,SHARE_NOTICE,RUN_NOTICE
from tests.test_workflow_fallback import routing
from tests.test_workflow_typed_flow import typed_routing
from tests.test_workflow_runtime import wait
from tests.test_workflow_resolved_evidence import alter_checkpoint,principal_expiry


@pytest.fixture
def controlled_routing(typed_routing):
    rt,*_=typed_routing
    with rt.store._lock:init_admin_auth_db(rt.store._db)
    return typed_routing


def prepared(rt):
    service=ControlledPairs(rt);options=service.options()
    assert options['sources'] and len(options['targets'])>=2
    result=service.prepare({'objective':'Python news and documentation search','source_id':options['sources'][0]['id'],
        'target_a_id':options['targets'][0]['id'],'target_b_id':options['targets'][1]['id']},1)
    return service,result


def authorized(proposal,**overrides):
    return {'proposal':proposal['proposal'],'signature':proposal['signature'],
        'share_authority':True,'share_notice':SHARE_NOTICE,'live_authority':True,'live_notice':RUN_NOTICE,**overrides}


def completed_pair(routing):
    rt,*_=routing;service,proposal=prepared(rt);job=service.execute(authorized(proposal),1);result=wait(rt,job)
    assert result['status']=='succeeded',result
    return service,proposal,result


def test_prepare_is_catalog_only_and_one_live_run_calls_source_once_then_two_distinct_targets(controlled_routing):
    rt,_,_,calls,*_=controlled_routing;before=len(rt.store.query('SELECT id FROM agent_workflows'))
    service,proposal=prepared(rt)
    assert not calls and len(rt.store.query('SELECT id FROM agent_workflows'))==before
    assert proposal['preview']['max_calls']==3 and proposal['preview']['max_seconds']==25
    assert proposal['preview']['limit']==3 and len(proposal['proposal']['workflow']['nodes'])==4
    job=service.execute(authorized(proposal),1);result=wait(rt,job);assert result['status']=='succeeded',result
    assert len(calls)==3 and calls[0]=='primary.example' and calls[1]!=calls[2]
    assert rt.typed_test_controls['seen'][1]==rt.typed_test_controls['seen'][2]=={'query':'Python asynchronous task documentation','language':'en','limit':3}
    cps={row['node_id']:json.loads(row['payload']) for row in rt.store.query('SELECT node_id,payload FROM workflow_checkpoints WHERE run_id=?',(job['run_id'],))}
    assert cps['search-2']['typed_input']['source_checkpoint_hash']==cps['search-3']['typed_input']['source_checkpoint_hash']
    inspected=service.inspect({'run_id':job['run_id']})
    assert inspected['comparison_status']=='complete' and inspected['shared_input_verified']
    assert inspected['resolved_input']['query']=='Python asynchronous task documentation'
    assert [target['assessment'] for target in inspected['targets']]==['contract_passed','contract_passed']
    assert all(target['outcome']=='succeeded' for target in inspected['targets'])
    assert not inspected['publication_readiness']['ready'] and not inspected['publication_readiness']['publication_consent_collected']
    assert not rt.store.query('SELECT * FROM workflow_result_outbox WHERE run_id=?',(job['run_id'],))
    assert Comparison(rt).runs()['runs']==[]


def test_repeated_and_concurrent_execute_reserves_one_definition_and_one_run(controlled_routing):
    rt,_,_,calls,*_=controlled_routing;service,proposal=prepared(rt)
    with ThreadPoolExecutor(max_workers=5) as pool:jobs=list(pool.map(lambda _:service.execute(authorized(proposal),1),range(5)))
    assert len({job['run_id'] for job in jobs})==len({job['workflow_id'] for job in jobs})==1
    result=wait(rt,jobs[0]);assert result['status']=='succeeded',result
    assert len(calls)==3 and len(rt.store.query('SELECT id FROM agent_workflows WHERE tags=?',(proposal['proposal']['workflow']['tags'],)))==1
    assert service.execute(authorized(proposal),1)['run_id']==jobs[0]['run_id'] and len(calls)==3


def test_two_processes_reserve_and_admit_one_nonce_without_starting_a_provider(controlled_routing,tmp_path):
    rt,_,_,calls,*_=controlled_routing;_,proposal=prepared(rt)
    payload=tmp_path/'pair.json';payload.write_text(json.dumps(authorized(proposal)))
    start=tmp_path/'start';ready=[tmp_path/'ready-a',tmp_path/'ready-b']
    script="""
import json,sys,time
from pathlib import Path
from agent_market.gateway.store import Store
from agent_market.workflows import WorkflowRuntime
from agent_market.workflow_controlled_pairs import ControlledPairs
store=Store(sys.argv[1]);runtime=WorkflowRuntime(store);runtime.launch=lambda _:None
body=json.loads(Path(sys.argv[2]).read_text());Path(sys.argv[3]).touch()
for _ in range(1000):
    if Path(sys.argv[4]).exists():break
    time.sleep(.01)
else:raise RuntimeError('isolated barrier timeout')
print(json.dumps(ControlledPairs(runtime).execute(body,1)))
store._db.close()
"""
    processes=[subprocess.Popen([sys.executable,'-B','-c',script,rt.store._path,str(payload),str(flag),str(start)],
        cwd=Path(__file__).resolve().parents[1],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
        env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'}) for flag in ready]
    try:
        for _ in range(1000):
            if all(flag.exists() for flag in ready):break
            if any(process.poll() is not None for process in processes):break
            time.sleep(.01)
        assert all(flag.exists() for flag in ready)
        start.touch();jobs=[]
        for process in processes:
            out,err=process.communicate(timeout=15);assert process.returncode==0,err
            jobs.append(json.loads(out))
        assert len({job['run_id'] for job in jobs})==len({job['workflow_id'] for job in jobs})==1
        assert len(rt.store.query('SELECT id FROM agent_workflows WHERE tags=?',(proposal['proposal']['workflow']['tags'],)))==1
        assert len(rt.store.query('SELECT id FROM workflow_runs'))==1 and not calls
    finally:
        for process in processes:
            if process.poll() is None:process.kill()
            process.communicate(timeout=5)


@pytest.mark.parametrize('change',[{'share_authority':False},{'live_authority':False},{'share_authority':1},{'live_authority':1},
    {'share_notice':'wrong'},{'live_notice':'wrong'},{'include_fallback':True}])
def test_separate_exact_consent_is_checked_before_reservation_or_calls(controlled_routing,change):
    rt,_,_,calls,*_=controlled_routing;service,proposal=prepared(rt);before=len(rt.store.query('SELECT id FROM agent_workflows'))
    with pytest.raises(ComparisonError):service.execute(authorized(proposal,**change),1)
    assert not calls and len(rt.store.query('SELECT id FROM agent_workflows'))==before


@pytest.mark.parametrize('change',['mac','owner','expiry','input','target','duplicate_target'])
def test_changed_or_expired_proposals_cannot_create_a_new_run(controlled_routing,change):
    rt,_,_,calls,*_=controlled_routing;service,proposal=prepared(rt);body=authorized(copy.deepcopy(proposal));p=body['proposal']
    if change=='mac':body['signature']='forged'
    elif change=='owner':p['owner']='2'
    elif change=='expiry':p['created']-=1000;p['expires']-=1000;body['signature']=rt.authority.signature(p)
    elif change=='input':p['workflow']['nodes'][1]['data']['input']['query']='Different objective'
    elif change=='target':p['workflow']['nodes'][-1]['resource_id']+=100
    else:p['workflow']['nodes'][-1]=copy.deepcopy(p['workflow']['nodes'][-2])
    with pytest.raises(ComparisonError):service.execute(body,1)
    assert not calls and not rt.store.query('SELECT id FROM workflow_runs')


@pytest.mark.parametrize('mode',['invalid','unknown'])
def test_failed_or_uncertain_a_never_dispatches_b_and_remains_unscored(controlled_routing,mode):
    rt,_,_,calls,modes,*_=controlled_routing;service,proposal=prepared(rt)
    node=proposal['proposal']['workflow']['nodes'][2];modes[rt.store.resource(node['resource_id'])['url'].split('/')[2]]=mode
    job=service.execute(authorized(proposal),1);result=wait(rt,job);assert result['status']=='failed',result
    assert len(calls)==2
    inspected=service.inspect({'run_id':job['run_id']})
    assert inspected['comparison_status']=='unscored' and not inspected['shared_input_verified']
    assert all(target['latency_ms'] is None for target in inspected['targets'])
    assert inspected['summary']['automatic_winner'] is None


def test_crash_after_definition_reservation_reuses_it_before_one_admission(controlled_routing,monkeypatch):
    rt,_,_,calls,*_=controlled_routing;service,proposal=prepared(rt);submit=rt.submit
    def interrupted(*args,**kwargs):raise RuntimeError('isolated crash before durable admission')
    monkeypatch.setattr(rt,'submit',interrupted)
    with pytest.raises(RuntimeError):service.execute(authorized(proposal),1)
    assert len(rt.store.query('SELECT id FROM agent_workflows WHERE tags=?',(proposal['proposal']['workflow']['tags'],)))==1
    assert not rt.store.query('SELECT id FROM workflow_runs') and not calls
    monkeypatch.setattr(rt,'submit',submit);result=wait(rt,service.execute(authorized(proposal),1))
    assert result['status']=='succeeded' and len(calls)==3


def test_saved_definition_changes_and_duplicate_nonce_rows_fail_closed(controlled_routing,monkeypatch):
    rt,*_=controlled_routing;service,proposal=prepared(rt);p=proposal['proposal'];wf=service._reserve(p)
    with rt.store.tx() as db:db.execute('UPDATE agent_workflows SET is_template=1 WHERE id=?',(wf['id'],))
    with pytest.raises(ComparisonError,match='changed'):service.execute(authorized(proposal),1)
    with rt.store.tx() as db:
        db.execute('UPDATE agent_workflows SET is_template=0 WHERE id=?',(wf['id'],))
        db.execute('INSERT INTO agent_workflows (name,steps,tags,created_at,updated_at) VALUES (?,?,?,?,?)',('duplicate','{}',p['workflow']['tags'],time.time(),time.time()))
    with pytest.raises(ComparisonError,match='ambiguous'):service.execute(authorized(proposal),1)


def test_current_role_revocation_and_new_nonce_limit_precede_execution(controlled_routing):
    rt,_,_,calls,*_=controlled_routing;service,proposal=prepared(rt)
    with rt.store.tx() as db:db.execute("UPDATE admin_users SET role='admin' WHERE id=1")
    with pytest.raises(ComparisonError):service.execute(authorized(proposal),1)
    assert not calls
    with rt.store.tx() as db:
        db.execute("UPDATE admin_users SET role='superadmin' WHERE id=1")
        for i in range(20):db.execute('INSERT INTO agent_workflows (name,steps,tags,author,created_at,updated_at) VALUES (?,?,?,?,?,?)',('reserved','{}','controlled-pair:'+str(i),'Controlled pair owner 1',time.time(),time.time()))
    with pytest.raises(ComparisonError,match='limit'):service.execute(authorized(proposal),1)
    assert not calls


def test_active_outer_transaction_is_refused_without_rolling_it_back(controlled_routing):
    rt,*_=controlled_routing;service,proposal=prepared(rt)
    with rt.store._lock:
        rt.store._db.execute('BEGIN')
        try:
            with pytest.raises(ComparisonError,match='reservation'):service._reserve(proposal['proposal'])
            assert rt.store._db.in_transaction
        finally:rt.store._db.rollback()


@pytest.mark.parametrize('change',['source_mac','target_input','target_provenance','attempt_hash','principal_expiry','budget'])
def test_retained_inspection_does_not_score_tampered_proofs(controlled_routing,change):
    rt,*_=controlled_routing;service,_,run=completed_pair(controlled_routing);rid=run['run_id']
    if change=='source_mac':alter_checkpoint(rt,rid,'search-1',lambda cp:None,signature=False)
    elif change=='target_input':alter_checkpoint(rt,rid,'search-3',lambda cp:cp['record']['input'].update(query='Another documentation query'))
    elif change=='target_provenance':alter_checkpoint(rt,rid,'search-3',lambda cp:cp['typed_input'].update(source_checkpoint_hash='0'*64))
    elif change=='attempt_hash':
        with rt.store.tx() as db:db.execute("UPDATE workflow_execution_attempts SET input_hash='forged' WHERE run_id=? AND node_id='search-3'",(rid,))
    elif change=='principal_expiry':principal_expiry(rt,rid,0)
    else:
        with rt.store.tx() as db:
            payload=json.loads(db.execute('SELECT payload FROM workflow_execution_budgets WHERE run_id=?',(rid,)).fetchone()[0]);payload.update(profile='extended',total_seconds=60,node_seconds=15)
            db.execute('UPDATE workflow_execution_budgets SET payload=?,signature=? WHERE run_id=?',(json.dumps(payload),rt.authority.signature(payload),rid))
    with pytest.raises(ComparisonError):service.inspect({'run_id':rid})


@pytest.mark.parametrize('node',['search-1','search-2','search-3'])
def test_pruned_checkpoint_or_attempt_is_never_inferred_as_a_successful_pair(controlled_routing,node):
    rt,*_=controlled_routing;service,_,run=completed_pair(controlled_routing);rid=run['run_id']
    with rt.store.tx() as db:db.execute('DELETE FROM workflow_checkpoints WHERE run_id=? AND node_id=?',(rid,node))
    result=service.inspect({'run_id':rid});assert result['comparison_status']=='unscored' and not result['shared_input_verified']


def test_inspection_is_readonly_historical_and_publication_remains_blocked(controlled_routing):
    rt,_,_,calls,*_=controlled_routing;service,_,run=completed_pair(controlled_routing);count=len(calls);before=rt.store._db.total_changes
    with patch('agent_market.capability_registry.time.time',return_value=time.time()+3*86400):
        result=service.inspect({'run_id':run['run_id']})
    assert result['comparison_status']=='complete' and not result['targets'][0]['current']['eligible_now']
    assert not service.publication_readiness({'run_id':run['run_id']})['ready']
    assert service.runs()['runs'][0]['run_id']==run['run_id']
    assert rt.store._db.total_changes==before and len(calls)==count
    for private in ('primary.example','alternate.example','third.example','signature','source_checkpoint_hash','binding_hash','structuredContent'):
        assert private not in json.dumps(result)


def test_inspection_rejects_second_target_before_the_first_target_completion(controlled_routing):
    rt,*_=controlled_routing;service,_,run=completed_pair(controlled_routing);rid=run['run_id']
    a=json.loads(rt.store.query("SELECT payload FROM workflow_checkpoints WHERE run_id=? AND node_id='search-2'",(rid,))[0][0])
    alter_checkpoint(rt,rid,'search-3',lambda cp:cp['record'].update(started=a['record']['started']))
    with pytest.raises(ComparisonError,match='precedes'):service.inspect({'run_id':rid})


@pytest.mark.parametrize('certainty',['unknown','failed','unavailable'])
def test_b_cannot_be_scored_without_certain_successful_a_predecessor(controlled_routing,certainty):
    rt,*_=controlled_routing;service,_,run=completed_pair(controlled_routing);rid=run['run_id']
    with rt.store.tx() as db:
        if certainty=='unavailable':db.execute("DELETE FROM workflow_execution_attempts WHERE run_id=? AND node_id='search-2'",(rid,))
        else:db.execute("UPDATE workflow_execution_attempts SET status=? WHERE run_id=? AND node_id='search-2'",(certainty,rid))
    if certainty=='unavailable':
        result=service.inspect({'run_id':rid});assert result['comparison_status']=='unscored' and result['targets'][1]['latency_ms'] is None
    else:
        with pytest.raises(ComparisonError,match='predecessor'):service.inspect({'run_id':rid})


def test_retained_resolved_input_after_pre_dispatch_refusal_is_not_a_successful_b_call(controlled_routing):
    rt,*_=controlled_routing;service,_,run=completed_pair(controlled_routing);rid=run['run_id']
    def refused(cp):
        cp['record'].update(status='failed',data=None,error='Policy denied before dispatch')
        cp['flow_output']=None
    alter_checkpoint(rt,rid,'search-3',refused)
    with rt.store.tx() as db:
        db.execute("UPDATE workflow_execution_attempts SET status='unknown' WHERE run_id=? AND node_id='search-2'",(rid,))
        db.execute("UPDATE workflow_execution_attempts SET status='failed',dispatched=NULL WHERE run_id=? AND node_id='search-3'",(rid,))
    result=service.inspect({'run_id':rid})
    assert result['comparison_status']=='unscored' and not result['shared_input_verified']
    assert result['targets'][1]['assessment']=='unavailable' and result['targets'][1]['latency_ms'] is None
    assert result['resolved_input']['query']=='Python asynchronous task documentation'


@pytest.mark.parametrize('policy_change',['quarantine','pause_resume'])
def test_control_epoch_revokes_unadmitted_proposal_and_fresh_review_can_execute(controlled_routing,policy_change):
    rt,_,_,calls,*_=controlled_routing;service,proposal=prepared(rt)
    if policy_change=='quarantine':
        with rt.store.tx() as db:quarantine(db)
    else:
        revision=controls(rt.store)['revision']
        set_controls(rt.store,{'invoke_enabled':False,'workflow_enabled':False,'delivery_enabled':False,'revision':revision},1)
    revision=controls(rt.store)['revision']
    current=set_controls(rt.store,{'invoke_enabled':True,'workflow_enabled':True,'delivery_enabled':True,'revision':revision},1)
    assert current['updated']>proposal['proposal']['created']
    with pytest.raises(ComparisonError,match='expired, changed'):service.execute(authorized(proposal),1)
    assert not rt.store.query("SELECT id FROM agent_workflows WHERE tags LIKE 'controlled-pair:%'")
    assert not rt.store.query('SELECT id FROM workflow_runs') and not calls
    fresh_service,fresh=prepared(rt)
    result=wait(rt,fresh_service.execute(authorized(fresh),1))
    assert result['status']=='succeeded' and len(calls)==3


@pytest.mark.parametrize('invalid_epoch',['invalid',-1,float('inf')])
def test_invalid_control_epoch_fails_closed_before_reservation(controlled_routing,invalid_epoch):
    rt,_,_,calls,*_=controlled_routing;service,proposal=prepared(rt)
    with rt.store.tx() as db:db.execute('UPDATE execution_controls SET updated=? WHERE id=1',(invalid_epoch,))
    with pytest.raises(ComparisonError):service.execute(authorized(proposal),1)
    assert not rt.store.query("SELECT id FROM agent_workflows WHERE tags LIKE 'controlled-pair:%'")
    assert not rt.store.query('SELECT id FROM workflow_runs') and not calls


def test_proposal_and_dispatch_descriptor_require_the_same_signed_review_epoch(controlled_routing):
    rt,_,_,calls,*_=controlled_routing;service,proposal=prepared(rt)
    assert all(node['data']['composition']['payload']['pair']['reviewed_at']==proposal['proposal']['created']
        for node in proposal['proposal']['workflow']['nodes'][2:])
    changed=copy.deepcopy(proposal)
    for node in changed['proposal']['workflow']['nodes'][2:]:
        composition=node['data']['composition']
        composition['payload']['pair']['reviewed_at']-=1
        composition['mac']=rt.authority.signature(composition['payload'])
    changed['signature']=rt.authority.signature(changed['proposal'])
    with pytest.raises(ComparisonError):service.execute(authorized(changed),1)
    assert not rt.store.query("SELECT id FROM agent_workflows WHERE tags LIKE 'controlled-pair:%'")
    assert not rt.store.query('SELECT id FROM workflow_runs') and not calls
