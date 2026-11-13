"""Operational improvements use isolated catalogs, agents, recipients and clocks."""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

import pytest

from agent_market.workflows import WorkflowError,canonical
from agent_market.workflow_budgets import NOTICE as BUDGET_NOTICE
from agent_market.workflow_operations import RECONCILE,RESEND
from agent_market.workflow_backup import backup,restore
from tests.test_workflow_runtime import runtime,node,save,wait
from tests.test_workflow_fallback import routing,activate,config,run
from tests.test_execution_authority import inbox
from tests.test_workflow_fallback_api import routing_api,H
from tests.test_admin_security_audit import login,session_headers
from agent_market.gateway.admin_auth import create_admin_user


def principal(rt,wf):return rt.principal('admin','internal',wf['id'],role='superadmin')


def unknown_delivery(rt,wf):
    courier,dest=inbox(rt,wf);send=courier.send_update
    def fail(channel,secret,payload,event):
        send(channel,secret,payload,event)
        return False,'isolated acknowledgement loss'
    courier.send_update=fail
    result=wait(rt,rt.submit(wf));assert result['status']=='succeeded'
    event=rt.store.query('SELECT id,status FROM workflow_result_outbox WHERE run_id=?',(result['run_id'],))[0]
    assert event['status']=='unknown';courier.send_update=send
    return result,event['id'],dest,courier


def review(rt,wf,job,event,disposition='not_received',revision=0):
    return rt.operations.reconcile(job['run_id'],{'subject':event,'revision':revision,'disposition':disposition,
        'evidence_ref':'incident-123','authority':True,'notice':RECONCILE},principal(rt,wf))


def resend(rt,wf,job,event,dest,**changes):
    data={'source_event_id':event,'review_revision':1,'destination_id':dest,'authority':True,'duplicate_risk_ack':True,'notice':RESEND}
    data.update(changes)
    return rt.operations.request_resend(job['run_id'],data,principal(rt,wf))


@pytest.mark.parametrize('failure',['error','invalid','preflight'])
def test_canary_survives_repeated_primary_failure_and_keeps_one_attempt_limit(routing,monkeypatch,failure):
    rt,wf,_,calls,modes,*_=routing;activate(routing,monkeypatch);modes['primary.example']=failure
    for _ in range(3):assert run(rt,wf)['node_results'][0]['fallback_used']
    assert calls.count('alternate.example')==3 and rt.fallback.inspect(wf['id'])['admitted']==3
    # Exhausting the selected-admission cap does not silently widen rollout.
    result=run(rt,wf);assert not result['node_results'][0].get('fallback_used')
    assert calls.count('alternate.example')==3


def test_config_still_requires_both_primary_and_candidate_success(routing,monkeypatch):
    rt,wf,ids,calls,modes,*_=routing;activate(routing,monkeypatch);modes['primary.example']='error';run(rt,wf)
    with pytest.raises(ValueError,match='evidence'):config(rt,wf,ids,'canary')


def test_policy_response_reports_exact_revocations(routing):
    rt,wf,ids,*_=routing;inbox(rt,wf)
    response=config(rt,wf,ids)
    assert response['delivery_grants_revoked']==1 and response['delivery_reapproval_required']
    assert config(rt,wf,ids)['delivery_grants_revoked']==0


def test_extended_budget_is_signed_private_bounded_and_keeps_original_deadline(runtime,monkeypatch):
    rt,rid,_=runtime;wf=save(rt.store,[node(resource_id=rid,action='get_weather',input={'city':'Tokyo'})]);monkeypatch.setattr(rt,'launch',lambda _:None)
    standard=rt.submit(wf);extended=rt.submit(wf,execution_profile='extended',execution_budget_notice=BUDGET_NOTICE)
    one=rt.persistence.claim(standard['run_id'],'one',25);two=rt.persistence.claim(extended['run_id'],'two',60)
    assert round(one['deadline']-one['started'])==25 and round(two['deadline']-two['started'])==60
    assert rt.budgets.get(two)['node_seconds']==15
    with rt.store.tx() as db:db.execute("UPDATE workflow_runs SET status='queued' WHERE id=?",(extended['run_id'],))
    resumed=rt.persistence.claim(extended['run_id'],'three',60);assert resumed['deadline']==two['deadline']
    with rt.store.tx() as db:db.execute("UPDATE workflow_execution_budgets SET payload=replace(payload,'60','120') WHERE run_id=?",(extended['run_id'],))
    with pytest.raises(ValueError,match='invalid'):rt.budgets.get(resumed)


@pytest.mark.parametrize('source',['public','webapp','schedule','event','verification'])
def test_extended_budget_cannot_be_requested_by_other_sources(runtime,source):
    rt,rid,_=runtime;wf=save(rt.store,[node(resource_id=rid)])
    with pytest.raises(WorkflowError):rt.submit(wf,source=source,execution_profile='extended',execution_budget_notice=BUDGET_NOTICE)
    assert not rt.history(wf['id'])


def test_heartbeat_reuses_only_its_scoped_connection(runtime,monkeypatch):
    import agent_market.workflow_persistence as module
    rt,rid,_=runtime;wf=save(rt.store,[node(resource_id=rid)]);monkeypatch.setattr(rt,'launch',lambda _:None);job=rt.submit(wf)
    row=rt.persistence.claim(job['run_id'],'owner',25);connect=module.sqlite3.connect;opened=[]
    def count(*args,**kw):db=connect(*args,**kw);opened.append(db);return db
    monkeypatch.setattr(module.sqlite3,'connect',count)
    with rt.persistence.heartbeat_connection() as connection:
        for _ in range(3):assert rt.persistence.pulse(job['run_id'],'owner',row['fence'],connection)
        assert connection.execute('PRAGMA synchronous').fetchone()[0]!=0
    assert len(opened)==1
    with pytest.raises(sqlite3.ProgrammingError):opened[0].execute('SELECT 1')


def test_reconcile_does_not_change_unknown_and_resend_is_new_event_once(runtime):
    rt,rid,_=runtime;wf=save(rt.store,[node(resource_id=rid,action='get_weather',input={'city':'Tokyo'})])
    job,event,dest,courier=unknown_delivery(rt,wf);before=len(courier.sent)
    review(rt,wf,job,event);manual=resend(rt,wf,job,event,dest)
    assert manual['id'].startswith('wm_') and manual['id']!=event
    rt.operations.drain();rt.operations.drain()
    assert len(courier.sent)==before+1 and courier.sent[-1]['manual_resend']
    assert courier.sent[-1]['source_event_id']==event
    assert rt.store.query('SELECT status FROM workflow_result_outbox WHERE id=?',(event,))[0][0]=='unknown'
    assert rt.operations.inspect(job['run_id'])['manual_deliveries'][0]['status']=='accepted'
    with pytest.raises(ValueError,match='already'):resend(rt,wf,job,event,dest)
    with pytest.raises(ValueError,match='revision'):review(rt,wf,job,event)


@pytest.mark.parametrize('change',['no_review','received','no_ack','destination','revoked','result_changed','review_changed','signature','expired','delivery_paused'])
def test_manual_delivery_approval_is_specific_and_revalidated(runtime,change):
    from agent_market.execution_authority import controls,set_controls
    rt,rid,_=runtime;wf=save(rt.store,[node(resource_id=rid,action='get_weather',input={'city':'Tokyo'})]);job,event,dest,courier=unknown_delivery(rt,wf);before=len(courier.sent)
    if change=='no_review':
        with pytest.raises(ValueError):resend(rt,wf,job,event,dest)
        return
    review(rt,wf,job,event,'received' if change=='received' else 'not_received')
    if change in ('received','no_ack','destination'):
        changes={'duplicate_risk_ack':False} if change=='no_ack' else {'destination_id':'wd_'+'a'*32} if change=='destination' else {}
        with pytest.raises(ValueError):resend(rt,wf,job,event,dest,**changes)
        return
    manual=resend(rt,wf,job,event,dest)
    if change=='revoked':rt.revoke_destination(wf['id'],dest)
    elif change=='result_changed':
        with rt.store.tx() as db:db.execute('UPDATE workflow_runs SET result=? WHERE id=?',('{}',job['run_id']))
    elif change=='review_changed':review(rt,wf,job,event,'received',revision=1)
    elif change=='signature':
        with rt.store.tx() as db:db.execute("UPDATE workflow_manual_deliveries SET signature='forged'")
    elif change=='expired':
        row=rt.store.query('SELECT * FROM workflow_manual_deliveries WHERE id=?',(manual['id'],))[0];p=json.loads(row['payload']);p['expires']=0
        with rt.store.tx() as db:db.execute('UPDATE workflow_manual_deliveries SET payload=?,signature=? WHERE id=?',(json.dumps(p),rt.authority.signature(p),manual['id']))
    elif change=='delivery_paused':
        c=controls(rt.store);set_controls(rt.store,{k:c[k] for k in ('invoke_enabled','workflow_enabled','delivery_enabled')}|{'delivery_enabled':False,'revision':c['revision']},1)
    rt.operations.drain();assert len(courier.sent)==before


def test_manual_post_dispatch_response_loss_never_auto_resends(runtime):
    rt,rid,_=runtime;wf=save(rt.store,[node(resource_id=rid,action='get_weather',input={'city':'Tokyo'})]);job,event,dest,courier=unknown_delivery(rt,wf)
    review(rt,wf,job,event);resend(rt,wf,job,event,dest);before=len(courier.sent);send=courier.send_update
    def lost(*args):send(*args);raise TimeoutError('isolated lost acknowledgement')
    courier.send_update=lost;rt.operations.drain();rt.operations.drain()
    assert len(courier.sent)==before+1 and rt.operations.inspect(job['run_id'])['manual_deliveries'][0]['status']=='unknown'


def test_retention_is_bounded_keeps_replay_guards_and_unknowns(runtime,monkeypatch):
    rt,rid,_=runtime;wf=save(rt.store,[node(resource_id=rid,action='get_weather',input={'city':'Tokyo'})])
    job=rt.submit(wf,idempotency='retained-operation');result=wait(rt,job)
    with rt.store.tx() as db:db.execute('UPDATE workflow_runs SET finished=? WHERE id=?',(time.time()-100*86400,job['run_id']))
    preview=rt.maintenance.run();assert preview['body_candidates']==1 and not preview['bodies_compacted']
    assert rt.store.query('SELECT * FROM workflow_checkpoints WHERE run_id=?',(job['run_id'],))
    applied=rt.maintenance.run(apply=True);assert applied['bodies_compacted']==1
    compact=rt.get(job['run_id']);assert compact['retained_summary'] and compact['artifact_sha256']==result['artifact_sha256']
    assert not rt.store.query('SELECT * FROM workflow_checkpoints WHERE run_id=?',(job['run_id'],))
    assert rt.store.query('SELECT * FROM workflow_execution_attempts WHERE run_id=?',(job['run_id'],))
    assert rt.submit(wf,idempotency='retained-operation')['replayed']
    assert rt.maintenance.run(apply=True)['metadata_pruned']==1
    assert rt.submit(wf,idempotency='retained-operation')['replayed']
    proof=rt.store.query('SELECT * FROM workflow_run_archives WHERE run_id=?',(job['run_id'],))[0]
    assert rt.authority.signature(json.loads(proof['payload']))==proof['signature']
    unknown,event,dest,_=unknown_delivery(rt,wf)
    with rt.store.tx() as db:db.execute('UPDATE workflow_runs SET finished=? WHERE id=?',(time.time()-100*86400,unknown['run_id']))
    assert rt.maintenance.run(apply=True)['bodies_compacted']==0
    assert rt.store.query('SELECT * FROM workflow_checkpoints WHERE run_id=?',(unknown['run_id'],))


def test_preview_cli_does_not_recover_or_write_live_state(runtime,monkeypatch):
    rt,rid,_=runtime;wf=save(rt.store,[node(resource_id=rid)]);monkeypatch.setattr(rt,'launch',lambda _:None);job=rt.submit(wf)
    rt.persistence.claim(job['run_id'],'old',25)
    with rt.store.tx() as db:db.execute('UPDATE workflow_runs SET lease_until=0 WHERE id=?',(job['run_id'],))
    before=dict(rt.store.query('SELECT * FROM workflow_runs WHERE id=?',(job['run_id'],))[0])
    result=subprocess.run([sys.executable,'-m','agent_market.workflow_maintenance','--db',rt.store._path],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['dry_run']
    assert dict(rt.store.query('SELECT * FROM workflow_runs WHERE id=?',(job['run_id'],))[0])==before


def test_restore_inventory_has_private_permissions_and_no_credentials(runtime,tmp_path):
    rt,rid,_=runtime;wf=save(rt.store,[node(resource_id=rid,action='get_weather',input={'city':'Tokyo'})]);job,event,dest,courier=unknown_delivery(rt,wf)
    review(rt,wf,job,event);resend(rt,wf,job,event,dest)
    backup_dir=tmp_path/'backup';backup(rt.store._path,backup_dir);target=tmp_path/'restored.sqlite3';restore(backup_dir,target)
    path=Path(str(target)+'.restored-inventory.json');inventory=json.loads(path.read_text())
    assert path.stat().st_mode&0o777==0o600 and not inventory['automatic_reactivation']
    assert inventory['items']['workflow_destinations']['records'][0]['id']==dest
    for private in ('https://','sealed','signing_secret','publish_key','payload','incident-123'):assert private not in path.read_text()
    db=sqlite3.connect(target)
    try:assert db.execute('SELECT status FROM workflow_manual_deliveries').fetchone()[0]=='unknown'
    finally:db.close()


def test_operational_endpoints_enforce_superadmin_and_explicit_consent(routing_api):
    routing,public,admin=routing_api;rt,wf,*_=routing
    with rt.store.tx() as db:create_admin_user(db,'operator','operator-password','Operator','operator')
    token=login(admin,'operator','operator-password').json()['token'];headers=session_headers(token)
    for path in ('/admin/api/workflows/maintenance',f"/admin/api/workflows/runs/wr_{'a'*32}/reconciliation",f"/admin/api/workflows/runs/wr_{'a'*32}/manual-deliveries"):
        assert admin.post(path,headers=headers,json={}).status_code==403
        assert public.post(path,json={}).status_code==404
    assert admin.get('/admin/api/workflows/maintenance',headers=H).headers['cache-control']=='no-store'
    assert admin.post('/admin/api/workflows/maintenance',headers=H,json={}).status_code==409
    assert admin.post('/api/workflows/run',json={'template_id':wf['id'],'execution_profile':'extended'}).status_code==404
    assert public.post('/api/workflows/run',json={'template_id':wf['id'],'execution_profile':'extended'}).status_code==400


def test_postgres_round_trip_includes_routing_operations_budgets_and_retention(routing,monkeypatch):
    import os
    from scripts.rehearse_workflow_postgres import rehearse,TABLES
    rt,wf,ids,calls,modes,*_=routing;activate(routing,monkeypatch)
    modes['primary.example']='error';fallback=run(rt,wf);assert fallback['node_results'][0]['fallback_used']
    modes.clear();job,event,dest,_=unknown_delivery(rt,wf);review(rt,wf,job,event);resend(rt,wf,job,event,dest)
    extra=save(rt.store,[{'id':'start','type':'trigger','name':'Start','data':{}}],name="Quoted ' title \\ fixture")
    archived=wait(rt,rt.submit(extra))
    with rt.store.tx() as db:db.execute('UPDATE workflow_runs SET finished=? WHERE id=?',(time.time()-100*86400,archived['run_id']))
    assert rt.maintenance.run(apply=True)['bodies_compacted']==1
    pg_bins='/opt/homebrew/opt/postgresql@14/bin';monkeypatch.setenv('PATH',pg_bins+os.pathsep+os.environ.get('PATH',''))
    result=rehearse(rt.store._path)
    assert set(result['tables']) == set(TABLES) and result['round_trip_equal']
    assert result['claim_winners']==1 and result['canary_admission_winners']==2 and result['duplicate_manual_delivery_rejected']
    assert result['tables']['workflow_run_archives']==1 and result['tables']['workflow_reconciliation_events']==1
    Path('reports/operations-hardening-2026-10-18/postgres-rehearsal.json').write_text(json.dumps(result,indent=2)+'\n')


def test_apply_cli_preserves_signatures_and_idempotency(runtime):
    rt,rid,_=runtime;wf=save(rt.store,[node(resource_id=rid,action='get_weather',input={'city':'Tokyo'})]);job=rt.submit(wf,idempotency='cli-retained');wait(rt,job)
    with rt.store.tx() as db:db.execute('UPDATE workflow_runs SET finished=? WHERE id=?',(time.time()-20*86400,job['run_id']))
    result=subprocess.run([sys.executable,'-m','agent_market.workflow_maintenance','--db',rt.store._path,'--apply'],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['bodies_compacted']==1
    proof=rt.store.query('SELECT * FROM workflow_run_archives WHERE run_id=?',(job['run_id'],))[0]
    assert rt.authority.signature(json.loads(proof['payload']))==proof['signature']
    assert rt.submit(wf,idempotency='cli-retained')['replayed']


MANUAL_CHILD=r'''
import json,os,signal,sys
from agent_market.gateway.store import Store
from agent_market.workflows import WorkflowRuntime
path,audit,phase=sys.argv[1:]
class Courier:
 def send_update(self,channel,secret,payload,event):
  with open(audit,'a') as out:out.write(event+'\n');out.flush();os.fsync(out.fileno())
  os.kill(os.getpid(),signal.SIGKILL)
store=Store(path);runtime=WorkflowRuntime(store,courier=Courier())
if phase=='claimed':
 original=runtime.operations.validate_delivery
 def before(*args):
  original(*args);os.kill(os.getpid(),signal.SIGKILL)
 runtime.operations.validate_delivery=before
runtime.operations.drain()
raise SystemExit('Boundary not reached')
'''


@pytest.mark.parametrize('phase',['claimed','dispatched'])
def test_sigkill_manual_delivery_recovery_respects_dispatch_boundary(runtime,tmp_path,phase):
    import signal
    rt,rid,_=runtime;wf=save(rt.store,[node(resource_id=rid,action='get_weather',input={'city':'Tokyo'})]);job,event,dest,courier=unknown_delivery(rt,wf)
    review(rt,wf,job,event);manual=resend(rt,wf,job,event,dest);before=len(courier.sent);audit=tmp_path/'manual-audit.txt'
    child=subprocess.run([sys.executable,'-c',MANUAL_CHILD,rt.store._path,str(audit),phase],capture_output=True,timeout=15)
    assert child.returncode==-signal.SIGKILL,child.stderr.decode()[-1000:]
    with rt.store.tx() as db:db.execute('UPDATE workflow_manual_deliveries SET lease_until=0 WHERE id=?',(manual['id'],))
    rt.operations.recover();rt.operations.drain();rt.operations.drain()
    row=rt.operations.inspect(job['run_id'])['manual_deliveries'][0]
    assert row['status']==('accepted' if phase=='claimed' else 'unknown')
    assert len(courier.sent)==before+(phase=='claimed')
    assert (audit.read_text().splitlines() if audit.exists() else [])==([] if phase=='claimed' else [manual['id']])


def test_transient_heartbeat_busy_does_not_abandon_a_valid_long_run(runtime,monkeypatch):
    rt,rid,remote=runtime;wf=save(rt.store,[node(resource_id=rid,action='get_weather',input={'city':'Tokyo'})]);original=remote.handle_request
    def slow(request):
        if json.loads(request.content or '{}').get('method')=='tools/call':time.sleep(9)
        return original(request)
    remote.handle_request=slow;actual=rt.persistence.pulse;calls=[]
    def busy_once(*args,**kwargs):
        calls.append(args[3])
        if len(calls)==1:raise sqlite3.OperationalError('database is locked')
        return actual(*args,**kwargs)
    monkeypatch.setattr(rt.persistence,'pulse',busy_once)
    job=rt.submit(wf);future=rt.futures[job['run_id']];future.result(timeout=13)
    assert rt.get(job['run_id'])['status']=='succeeded' and len(calls)>=3
    assert all(connection is calls[0] for connection in calls)


def test_manual_unknown_can_be_reviewed_without_an_unbounded_resend_chain(runtime):
    rt,rid,_=runtime;wf=save(rt.store,[node(resource_id=rid,action='get_weather',input={'city':'Tokyo'})]);job,event,dest,courier=unknown_delivery(rt,wf)
    review(rt,wf,job,event);manual=resend(rt,wf,job,event,dest)
    courier.send_update=lambda *args:(False,'lost');rt.operations.drain()
    notes=review(rt,wf,job,manual['id'],'reviewed')
    assert any(r['subject']==manual['id'] for r in notes['reviews'])
    with pytest.raises(ValueError):resend(rt,wf,job,manual['id'],dest)


def test_retention_does_not_hold_writer_work_against_active_execution(runtime,monkeypatch):
    rt,rid,_=runtime;wf=save(rt.store,[node(resource_id=rid,action='get_weather',input={'city':'Tokyo'})]);old=wait(rt,rt.submit(wf))
    with rt.store.tx() as db:db.execute('UPDATE workflow_runs SET finished=? WHERE id=?',(time.time()-20*86400,old['run_id']))
    monkeypatch.setattr(rt,'launch',lambda _:None);rt.submit(wf)
    result=rt.maintenance.run(apply=True)
    assert result['busy'] and not result['bodies_compacted']
    assert rt.store.query('SELECT * FROM workflow_checkpoints WHERE run_id=?',(old['run_id'],))


@pytest.mark.parametrize('tamper',['signature','scope','snapshot'])
def test_retention_preserves_tampered_checkpoint_for_investigation(runtime,tamper):
    rt,rid,_=runtime;wf=save(rt.store,[node(resource_id=rid,action='get_weather',input={'city':'Tokyo'})]);job=wait(rt,rt.submit(wf))
    with rt.store.tx() as db:
        db.execute('UPDATE workflow_runs SET finished=? WHERE id=?',(time.time()-20*86400,job['run_id']))
        if tamper=='signature':db.execute("UPDATE workflow_checkpoints SET signature='tampered' WHERE run_id=?",(job['run_id'],))
        elif tamper=='snapshot':db.execute("UPDATE workflow_runs SET snapshot='{}' WHERE id=?",(job['run_id'],))
        else:
            row=db.execute('SELECT * FROM workflow_checkpoints WHERE run_id=?',(job['run_id'],)).fetchone();payload=json.loads(row['payload']);payload['run_id']='wr_'+'a'*32
            db.execute('UPDATE workflow_checkpoints SET payload=?,signature=? WHERE run_id=?',(json.dumps(payload),rt.authority.signature(payload),job['run_id']))
    result=rt.maintenance.run(apply=True)
    assert result['held_invalid_evidence']==1 and not result['bodies_compacted']
    assert rt.store.query('SELECT * FROM workflow_checkpoints WHERE run_id=?',(job['run_id'],))


def test_unknown_outcome_bodies_go_after_30_days_and_the_run_stays(runtime):
    """PM 11-14: an unknown (or unrecorded) execution outcome keeps its body 30 days, then only the body goes."""
    rt,rid,_=runtime;wf=save(rt.store,[node(resource_id=rid,action='get_weather',input={'city':'Tokyo'})])
    old=wait(rt,rt.submit(wf));young=wait(rt,rt.submit(wf));unset=wait(rt,rt.submit(wf))
    with rt.store.tx() as db:
        for run_id,days,outcome in ((old['run_id'],31,'unknown'),(young['run_id'],20,'unknown'),(unset['run_id'],45,None)):
            db.execute('UPDATE workflow_runs SET finished=?,execution_outcome=? WHERE id=?',(time.time()-days*86400,outcome,run_id))
    preview=rt.maintenance.run()
    assert preview['unknown_candidates']==2 and preview['unknown_days']==30 and not preview['bodies_compacted']
    applied=rt.maintenance.run(apply=True);assert applied['bodies_compacted']==2
    for run_id in (old['run_id'],unset['run_id']):
        row=rt.store.query('SELECT status,finished,execution_outcome,result FROM workflow_runs WHERE id=?',(run_id,))[0]
        assert row['status']=='succeeded' and row['finished'] and json.loads(row['result'])['retained_summary']
        assert not rt.store.query('SELECT * FROM workflow_checkpoints WHERE run_id=?',(run_id,))
    assert rt.store.query('SELECT * FROM workflow_checkpoints WHERE run_id=?',(young['run_id'],))   # 20 days: kept
    assert rt.maintenance.run(apply=True)['metadata_pruned']==0     # events of unknown runs are never pruned
    assert rt.store.query('SELECT 1 FROM workflow_run_events WHERE run_id=?',(old['run_id'],))
