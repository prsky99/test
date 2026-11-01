"""Isolated purpose, quota and durable automation tests; no live providers."""
import copy
from concurrent.futures import ThreadPoolExecutor
import json
import signal
import subprocess
import sys
import time

import pytest

from agent_market.workflow_connection_automation import PROFILE, SHARE_NOTICE, GRANT_NOTICE, EVENT_NOTICE
from agent_market.workflows import WorkflowError
from tests.test_workflow_fallback import routing
from tests.test_workflow_typed_flow import typed_routing
from tests.test_workflow_publication import publication, published
from tests.test_workflow_runtime import wait


def issue(rt, owner, release, *, trigger='event', maximum=3, interval=300):
    prepared=rt.automation.prepare(release['id'],{'trigger':trigger,'interval_seconds':interval if trigger=='scheduled' else 0,'max_runs':maximum,'ttl_seconds':1800},owner)
    body={'proposal':copy.deepcopy(prepared['proposal']),'signature':prepared['signature'],'sharing_authority':True,
          'sharing_notice':SHARE_NOTICE,'trigger_authority':True,'trigger_notice':GRANT_NOTICE}
    return rt.automation.issue(release['id'],body,owner)['grant'],body


@pytest.fixture
def automation(publication):
    rt,owner,routed=publication; release,proof,*_=published(rt,owner)
    grant,body=issue(rt,owner,release);routed[3].clear();rt.typed_test_controls['seen'].clear()
    return rt,owner,routed,release,proof,grant,body


def event(rt, owner, release, grant, event_id='a'*32):
    return rt.automation.trigger(release['id'],grant['id'],{'event_id':event_id,'authority':True,'notice':EVENT_NOTICE},owner)


def test_independent_event_runs_fixed_window_and_replays_one_admission(automation):
    rt,owner,routed,release,proof,grant,_=automation
    source=rt.publication.current(release['id'])[1]['nodes'][1]['data']['composition']['payload']['input']
    job=event(rt,owner,release,grant);result=wait(rt,job)
    assert result['status']=='succeeded' and len(routed[3])==2
    assert rt.typed_test_controls['seen'][0]==source
    assert rt.typed_test_controls['seen'][1]['query']==rt.typed_test_controls['title']
    replay=event(rt,owner,release,grant)
    assert replay['run_id']==job['run_id'] and replay['replayed'] and len(routed[3])==2
    row=rt.store.query('SELECT * FROM workflow_connection_automation WHERE id=?',(grant['id'],))[0]
    assert row['used']==1 and row['next_run'] is None
    assert len(rt.store.query('SELECT * FROM workflow_connection_automation_admissions'))==1
    assert not rt.store.query('SELECT * FROM workflow_result_outbox WHERE run_id=?',(job['run_id'],))
    authority=rt.authority.run(job['run_id'],proof['workflow_id'],rt.store.query('SELECT digest FROM workflow_runs WHERE id=?',(job['run_id'],))[0]['digest'],'admin')
    assert authority['grant_id'] is None and authority['principal']['payload']['connection_automation']['ticket']['trigger']=='event'
    assert rt.store.get_workflow(proof['workflow_id'])['trigger_type']=='manual'
    assert rt.automation.history(release['id'],owner)['runs'][0]['event_id']=='a'*32


@pytest.mark.parametrize('field,value',[('sharing_authority',False),('sharing_authority',1),('sharing_notice','workflow-public-flow-share-v1'),
                                       ('trigger_authority',False),('trigger_authority',1),('trigger_notice','workflow-connection-app-v13-grant-v1')])
def test_separate_share_and_trigger_grant_required(automation,field,value):
    rt,owner,_,release,_,_,body=automation;body=copy.deepcopy(body);body[field]=value
    with pytest.raises(ValueError):rt.automation.issue(release['id'],body,owner)
    assert rt.store.query('SELECT COUNT(*) FROM workflow_connection_automation')[0][0]==1


@pytest.mark.parametrize('body',[{'trigger':'event','interval_seconds':300,'max_runs':1,'ttl_seconds':1800},
                                 {'trigger':'scheduled','interval_seconds':299,'max_runs':1,'ttl_seconds':1800},
                                 {'trigger':'scheduled','interval_seconds':True,'max_runs':1,'ttl_seconds':1800},
                                 {'trigger':'event','interval_seconds':0,'max_runs':101,'ttl_seconds':1800},
                                 {'trigger':'event','interval_seconds':0,'max_runs':1,'ttl_seconds':86401},
                                 {'trigger':'webhook','interval_seconds':0,'max_runs':1,'ttl_seconds':1800}])
def test_bounded_configuration_refuses_extra_trigger_or_implicit_window(automation,body):
    rt,owner,_,release,*_=automation
    with pytest.raises(ValueError):rt.automation.prepare(release['id'],body,owner)
    body={**body,'from_utc':'2020-01-01T00:00:00Z'}
    with pytest.raises(ValueError):rt.automation.prepare(release['id'],body,owner)


@pytest.mark.parametrize('body',[{'event_id':'a'*32,'authority':1,'notice':EVENT_NOTICE},
                                 {'event_id':'a'*32,'authority':True,'notice':GRANT_NOTICE},
                                 {'event_id':'https://callback.example','authority':True,'notice':EVENT_NOTICE},
                                 {'event_id':'a'*32,'authority':True,'notice':EVENT_NOTICE,'payload':{}}])
def test_event_is_explicit_fixed_authenticated_identifier_only(automation,body):
    rt,owner,routed,release,_,grant,_=automation
    with pytest.raises(ValueError):rt.automation.trigger(release['id'],grant['id'],body,owner)
    assert not routed[3]


def test_atomic_run_and_quota_rollback_if_admission_receipt_fails(automation,monkeypatch):
    rt,owner,routed,release,_,grant,_=automation
    original=rt.automation.commit
    def fail(db,*args):
        original(db,*args);raise ValueError('isolated rejection after quota write')
    monkeypatch.setattr(rt.automation,'commit',fail)
    with pytest.raises(ValueError):event(rt,owner,release,grant)
    assert rt.store.query('SELECT used FROM workflow_connection_automation WHERE id=?',(grant['id'],))[0]['used']==0
    assert not rt.store.query('SELECT * FROM workflow_connection_automation_admissions')
    assert not rt.store.query('SELECT * FROM workflow_runs WHERE actor=?',('automation:'+grant['id'],)) and not routed[3]


def test_same_event_parallel_admission_has_one_receipt_and_two_calls(automation):
    rt,owner,routed,release,_,grant,_=automation
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs=list(pool.map(lambda _:event(rt,owner,release,grant),range(4)))
    assert len({j['run_id'] for j in jobs})==1
    assert wait(rt,jobs[0])['status']=='succeeded' and len(routed[3])==2
    assert rt.store.query('SELECT used FROM workflow_connection_automation WHERE id=?',(grant['id'],))[0]['used']==1


def test_new_event_is_rate_limited_and_maximum_enforced(automation):
    rt,owner,routed,release,_,grant,_=automation
    assert wait(rt,event(rt,owner,release,grant))['status']=='succeeded'
    with pytest.raises(ValueError):event(rt,owner,release,grant,'b'*32)
    assert len(routed[3])==2
    with rt.store.tx() as db:
        # Restore-style counter tampering cannot bypass the signed admission ledger.
        db.execute('UPDATE workflow_connection_automation SET used=0,last_admitted=NULL WHERE id=?',(grant['id'],))
    with pytest.raises(ValueError):event(rt,owner,release,grant,'c'*32)
    assert len(routed[3])==2


@pytest.mark.parametrize('change',['grant','publication','role','controls'])
def test_live_withdrawal_after_source_stops_docs_and_retains_history(automation,change):
    rt,owner,routed,release,_,grant,_=automation
    def withdraw():
        if change=='grant':rt.automation.revoke(release['id'],grant['id'],grant['revision'],owner)
        elif change=='publication':rt.publication.revoke(release['id'],release['revision'],owner)
        elif change=='role':
            with rt.store.tx() as db:db.execute("UPDATE admin_users SET role='operator' WHERE id=?",(owner,))
        else:
            from agent_market.execution_authority import controls,set_controls
            current=controls(rt.store)
            set_controls(rt.store,{'invoke_enabled':False,'workflow_enabled':True,'delivery_enabled':False,'revision':current['revision']},owner)
            current=controls(rt.store)
            set_controls(rt.store,{'invoke_enabled':True,'workflow_enabled':True,'delivery_enabled':False,'revision':current['revision']},owner)
    routed[5]['primary.example']=lambda request:withdraw()
    job=event(rt,owner,release,grant);result=wait(rt,job)
    assert result['status']!='succeeded' and routed[3]==['primary.example']
    assert not rt.store.query("SELECT * FROM workflow_execution_attempts WHERE run_id=? AND node_id='search-2'",(job['run_id'],))
    if change!='role':assert rt.automation.history(release['id'],owner)['runs'][0]['run_id']==job['run_id']


def test_unknown_does_not_repeat_or_admit_later_events(automation):
    rt,owner,routed,release,_,grant,_=automation
    routed[4].update({'third.example':'unknown','alternate.example':'unknown'})
    job=event(rt,owner,release,grant);wait(rt,job)
    assert rt.store.query('SELECT execution_outcome FROM workflow_runs WHERE id=?',(job['run_id'],))[0][0]=='unknown'
    assert event(rt,owner,release,grant)['run_id']==job['run_id']
    with pytest.raises(ValueError):event(rt,owner,release,grant,'b'*32)
    assert len(rt.store.query('SELECT * FROM workflow_connection_automation_admissions'))==1


def test_generic_manual_schedule_and_sdk_authority_cannot_infer_automation(automation):
    rt,owner,routed,release,proof,grant,_=automation;wf=rt.store.get_workflow(proof['workflow_id'])
    with pytest.raises(WorkflowError):rt.submit(wf,actor='automation:'+grant['id'],principal=rt.principal('admin',owner,wf['id'],role='superadmin'))
    with pytest.raises(WorkflowError):rt.save_schedule(wf['id'],{'mode':'scheduled','preset':'hourly','timezone':'UTC','enabled':True},rt.principal('admin',owner,wf['id'],role='superadmin'))
    assert not routed[3]


def test_scheduled_slot_is_separate_and_no_catchup_burst(publication,monkeypatch):
    rt,owner,routed=publication;release,proof,*_=published(rt,owner)
    grant,_=issue(rt,owner,release,trigger='scheduled',maximum=2);routed[3].clear()
    row=rt.store.query('SELECT next_run FROM workflow_connection_automation WHERE id=?',(grant['id'],))[0];due=row['next_run']
    real=time.time
    # A coherent wall-clock advance leaves fixed source dates untouched.
    advance=due+10-real()
    monkeypatch.setattr('agent_market.workflow_connection_automation.time.time',lambda:real()+advance)
    result=rt.automation.run_due(due+10)
    jobs=rt.automation.history(release['id'],owner)['runs']
    assert result['checked']==1 and len(jobs)==1
    assert wait(rt,{'run_id':jobs[0]['run_id']})['status']=='succeeded'
    assert rt.automation.run_due(due+10)['checked']==0 and len(routed[3])==2
    assert rt.store.query('SELECT next_run FROM workflow_connection_automation WHERE id=?',(grant['id'],))[0]['next_run']>due+300


def test_restore_tombstone_keeps_history_and_never_reactivates(automation):
    from agent_market.workflow_backup import quarantine,restored_inventory
    rt,owner,routed,release,_,grant,_=automation;job=event(rt,owner,release,grant);wait(rt,job)
    with rt.store.tx() as db:
        inventory=restored_inventory(db);quarantine(db)
    assert inventory['items']['workflow_connection_automation']['count']==1
    assert 'owner' not in json.dumps(inventory['items']['workflow_connection_automation'])
    row=rt.store.query('SELECT * FROM workflow_connection_automation WHERE id=?',(grant['id'],))[0]
    assert row['active']==0 and row['revision']==2 and row['next_run'] is None
    assert rt.automation.history(release['id'],owner)['runs'][0]['run_id']==job['run_id']
    assert rt.automation.run_due()['checked']==0
    with pytest.raises(ValueError):event(rt,owner,release,grant,'b'*32)


def test_oldest_ineligible_schedules_do_not_starve_later_valid_grant(publication,monkeypatch):
    rt,owner,routed=publication;release,*_=published(rt,owner)
    grants=[issue(rt,owner,release,trigger='scheduled')[0] for _ in range(6)]
    with rt.store.tx() as db:
        for grant in grants[:5]:db.execute("UPDATE workflow_connection_automation SET signature='invalid' WHERE id=?",(grant['id'],))
    due=rt.store.query('SELECT MAX(next_run) FROM workflow_connection_automation')[0][0];real=time.time;advance=due+1-real()
    monkeypatch.setattr('agent_market.workflow_connection_automation.time.time',lambda:real()+advance)
    monkeypatch.setattr(rt,'launch',lambda _:None)
    assert rt.automation.run_due()['checked']==1
    rows=rt.store.query('SELECT grant_id FROM workflow_connection_automation_admissions')
    assert len(rows)==1 and rows[0]['grant_id']==grants[-1]['id']
    assert rt.automation.run_due()['checked']==0


def test_maximum_run_count_survives_later_event_spacing(publication,monkeypatch):
    rt,owner,routed=publication;release,*_=published(rt,owner);grant,_=issue(rt,owner,release,maximum=1)
    assert wait(rt,event(rt,owner,release,grant))['status']=='succeeded'
    real=time.time;monkeypatch.setattr('agent_market.workflow_connection_automation.time.time',lambda:real()+61)
    with pytest.raises(ValueError):event(rt,owner,release,grant,'b'*32)
    assert rt.store.query('SELECT used FROM workflow_connection_automation WHERE id=?',(grant['id'],))[0][0]==1


@pytest.mark.parametrize('phase',['source-checkpoint','docs-dispatched'])
def test_real_sigkill_automation_reuses_only_certain_source_and_never_unknown_dispatch(automation,monkeypatch,tmp_path,phase):
    from tests.test_workflow_connection_deployment import CHILD
    rt,owner,routed,release,_,grant,_=automation
    monkeypatch.setattr(rt,'launch',lambda _:None)
    job=event(rt,owner,release,grant);audit=tmp_path/'calls.txt'
    child=subprocess.run([sys.executable,'-B','-c',CHILD,rt.store._path,job['run_id'],str(audit),phase],capture_output=True,timeout=15)
    assert child.returncode==-signal.SIGKILL,child.stderr.decode()[-1600:]
    before=audit.read_text().splitlines();deadline=rt.store.query('SELECT deadline FROM workflow_runs WHERE id=?',(job['run_id'],))[0][0]
    with rt.store.tx() as db:db.execute('UPDATE workflow_runs SET lease_until=0 WHERE id=?',(job['run_id'],))
    rt.persistence.recover();rt._execute(job['run_id']);result=rt.get(job['run_id'])
    if phase=='source-checkpoint':
        assert before==['primary.example'] and len(routed[3])==1 and routed[3][0]!='primary.example'
        assert result['status']=='succeeded',result
    else:
        assert len(before)==2 and not routed[3]
        assert result['status']=='failed' and result['execution_outcome']=='unknown'
        for _ in range(2):rt.persistence.recover();rt._execute(job['run_id'])
        assert not routed[3]
    assert len(before)+len(routed[3])==2
    assert rt.store.query('SELECT deadline FROM workflow_runs WHERE id=?',(job['run_id'],))[0][0]==deadline
    assert rt.store.query('SELECT used FROM workflow_connection_automation WHERE id=?',(grant['id'],))[0][0]==1
    assert len(rt.store.query('SELECT * FROM workflow_connection_automation_admissions'))==1
    assert event(rt,owner,release,grant)['run_id']==job['run_id']
