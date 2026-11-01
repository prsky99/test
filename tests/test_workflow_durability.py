"""Hard worker death, stale owners, signed resume, outbox and restore regressions."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import pytest

from agent_market.gateway.store import Store
from agent_market.workflows import WorkflowRuntime
from agent_market.workflow_persistence import FenceLost
from agent_market.workflow_backup import backup,restore
from tests.test_workflow_runtime import runtime,node,save,wait
from tests.test_execution_authority import inbox,policy


CHILD=r'''
import json,os,signal,sys,httpx
from pathlib import Path
from agent_market.gateway.store import Store
from agent_market.workflows import WorkflowRuntime
from agent_market.concierge.proxy import McpProxy
from tests.test_mcp_proxy import MockRemoteMcp,WEATHER_TOOL
path,run_id,mode,audit=sys.argv[1:]
def record(data):
 with open(audit,'a') as out:out.write(json.dumps(data)+'\n');out.flush();os.fsync(out.fileno())
def die():os.kill(os.getpid(),signal.SIGKILL)
remote=MockRemoteMcp([WEATHER_TOOL]);handle=remote.handle_request
def provider(req):
 data=json.loads(req.content or '{}')
 if data.get('method')=='tools/call':
  record({'type':'call','city':data['params']['arguments']['city']})
  if mode=='dispatch':die()
 return handle(req)
remote.handle_request=provider
class Courier:
 def send_update(self,channel,secret,payload,event):
  record({'type':'delivery','event':event})
  if mode=='ack':die()
  return True,None
store=Store(path);http=httpx.Client(transport=remote);rt=WorkflowRuntime(store,McpProxy(store,allow_private=True,http=http),Courier())
if mode=='prepared':
 prepare=rt.persistence.prepare
 def prepared(*args,**kwargs):
  prepare(*args,**kwargs);die()
 rt.persistence.prepare=prepared
if mode=='checkpoint':
 checkpoint=rt.persistence.checkpoint
 def saved(*args,**kwargs):
  result=checkpoint(*args,**kwargs)
  if args[3]=='a':die()
  return result
 rt.persistence.checkpoint=saved
if mode=='commit':rt.drain_outbox=lambda *args:die()
rt._execute(run_id)
raise SystemExit('Crash boundary was not reached')
'''


def crash(rt,job,mode,audit):
    path=rt.store.query('PRAGMA database_list')[0]['file']
    child=subprocess.run([sys.executable,'-c',CHILD,path,job['run_id'],mode,str(audit)],capture_output=True,timeout=15)
    assert child.returncode==-signal.SIGKILL,(child.returncode,child.stderr.decode()[-1200:])


def audit_rows(path):return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def queue(rt,wf,monkeypatch):
    launch=rt.launch;monkeypatch.setattr(rt,'launch',lambda _:None);job=rt.submit(wf);monkeypatch.setattr(rt,'launch',launch);return job


def expire_run(rt,job):
    with rt.store.tx() as db:db.execute('UPDATE workflow_runs SET lease_until=0 WHERE id=?',(job['run_id'],))


def test_sigkill_after_checkpoint_resumes_only_remaining_nodes(runtime,monkeypatch,tmp_path):
    rt,rid,remote=runtime;audit=tmp_path/'audit.jsonl'
    wf=save(rt.store,[node('a',resource_id=rid,action='get_weather',input={'city':'A'}),node('b',resource_id=rid,action='get_weather',input={'city':'B'})],[{'source':'a','target':'b'}])
    job=queue(rt,wf,monkeypatch);crash(rt,job,'checkpoint',audit)
    assert audit_rows(audit)==[{'type':'call','city':'A'}]
    original=remote.handle_request
    def provider(request):
        body=json.loads(request.content or '{}')
        if body.get('method')=='tools/call':
            with audit.open('a') as out:out.write(json.dumps({'type':'call','city':body['params']['arguments']['city']})+'\n')
        return original(request)
    remote.handle_request=provider
    prior=rt.store.query('SELECT deadline FROM workflow_runs WHERE id=?',(job['run_id'],))[0][0]
    expire_run(rt,job);rt.run_due();result=wait(rt,job)
    assert result['status']=='succeeded' and [r['city'] for r in audit_rows(audit)]==['A','B']
    assert len(rt.store.query('SELECT * FROM workflow_checkpoints WHERE run_id=?',(job['run_id'],)))==2
    assert rt.store.query('SELECT deadline FROM workflow_runs WHERE id=?',(job['run_id'],))[0][0]==prior
    assert rt.store.get_workflow(wf['id'])['runs_count']==1


def test_sigkill_after_external_acceptance_is_unknown_and_never_repeated(runtime,monkeypatch,tmp_path):
    rt,rid,_=runtime;audit=tmp_path/'audit.jsonl';wf=save(rt.store,[node('a',resource_id=rid,action='get_weather',input={'city':'A'})]);job=queue(rt,wf,monkeypatch)
    crash(rt,job,'dispatch',audit);expire_run(rt,job);rt.run_due();result=rt.get(job['run_id'])
    assert result['status']=='failed' and result['execution_outcome']=='unknown'
    for _ in range(3):rt.run_due()
    assert len(audit_rows(audit))==1
    assert rt.persistence.inspect(job['run_id'])['attempts'][0]['status']=='unknown'


@pytest.mark.parametrize('mode',['commit','ack'])
def test_sigkill_result_outbox_recovers_without_duplicate_delivery(runtime,monkeypatch,tmp_path,mode):
    rt,rid,_=runtime;audit=tmp_path/'audit.jsonl';wf=save(rt.store,[node('a',resource_id=rid,action='get_weather',input={'city':'A'})]);courier,_=inbox(rt,wf)
    job=queue(rt,wf,monkeypatch);crash(rt,job,mode,audit)
    assert rt.get(job['run_id'])['status']=='succeeded'
    with rt.store.tx() as db:db.execute('UPDATE workflow_result_outbox SET lease_until=0 WHERE run_id=?',(job['run_id'],))
    rt.run_due();rt.run_due()
    result=rt.get(job['run_id']);delivery=[x for x in audit_rows(audit) if x['type']=='delivery']
    if mode=='commit':assert result['final_deliverable']['distribution']['status']=='ACCEPTED' and len(courier.sent)==2 and not delivery
    else:assert result['final_deliverable']['distribution']['status']=='UNKNOWN' and len(courier.sent)==1 and len(delivery)==1


def test_stale_owner_cannot_dispatch_or_replace_new_result(runtime,monkeypatch):
    rt,rid,remote=runtime;entered=threading.Event();release=threading.Event();handle=remote.handle_request;blocked=[False];calls=[]
    def provider(request):
        body=json.loads(request.content or '{}')
        if body.get('method')=='tools/list' and not blocked[0]:blocked[0]=True;entered.set();release.wait(5)
        if body.get('method')=='tools/call':calls.append(body)
        return handle(request)
    remote.handle_request=provider
    wf=save(rt.store,[node('a',resource_id=rid,action='get_weather',input={'city':'A'})]);job=rt.submit(wf);assert entered.wait(2)
    old=rt.futures[job['run_id']];expire_run(rt,job);rt.persistence.recover()
    second=WorkflowRuntime(rt.store,rt.proxy,rt.courier)
    try:
        second.launch(job['run_id']);result=wait(second,job);assert result['status']=='succeeded'
    finally:release.set();old.result(timeout=5)
    assert rt.get(job['run_id'])['artifact_sha256']==result['artifact_sha256'] and len(calls)==1


def test_signed_checkpoint_tamper_fails_without_provider_replay(runtime,monkeypatch,tmp_path):
    rt,rid,_=runtime;wf=save(rt.store,[node('a',resource_id=rid,action='get_weather',input={'city':'A'}),node('b',resource_id=rid,action='get_weather',input={'city':'B'})]);job=queue(rt,wf,monkeypatch);audit=tmp_path/'audit'
    crash(rt,job,'checkpoint',audit)
    with rt.store.tx() as db:db.execute('UPDATE workflow_checkpoints SET signature=? WHERE run_id=?',('0'*64,job['run_id']))
    expire_run(rt,job);rt.run_due();result=wait(rt,job)
    assert result['status']=='failed' and len(audit_rows(audit))==1


def test_cross_connection_capacity_and_fencing(runtime,monkeypatch):
    rt,_,_=runtime;wf=save(rt.store,[{'id':'a','type':'trigger','name':'Start','data':{}}]);monkeypatch.setattr(rt,'launch',lambda _:None)
    jobs=[rt.submit(wf) for _ in range(5)];path=rt.store.query('PRAGMA database_list')[0]['file'];other=Store(path)
    from agent_market.workflow_persistence import DurableRuns
    repository=DurableRuns(other)
    try:
        claimed=[repository.claim(j['run_id'],'worker-'+str(i),25) for i,j in enumerate(jobs)]
        assert all(claimed[:4]) and claimed[4] is None
        with pytest.raises(FenceLost):repository.dispatch(jobs[0]['run_id'],'other-worker',claimed[0]['fence'],'a')
    finally:other._db.close()


def test_backup_restore_is_private_integral_and_never_replays_old_pending_delivery(runtime,monkeypatch,tmp_path):
    rt,rid,_=runtime;wf=save(rt.store,[node('a',resource_id=rid,action='get_weather',input={'city':'A'})]);inbox(rt,wf)
    policy(rt.store,delivery_enabled=False);job=rt.submit(wf);assert wait(rt,job)['status']=='succeeded'
    snapshot=tmp_path/'snapshot';manifest=backup(rt.store.query('PRAGMA database_list')[0]['file'],snapshot)
    assert manifest['key_included'] and snapshot.stat().st_mode&0o777==0o700
    assert all(p.stat().st_mode&0o777==0o600 for p in snapshot.iterdir())
    # The source can send after the snapshot. Restoring the older pending state
    # cannot know this; it must quarantine rather than send it again.
    policy(rt.store,delivery_enabled=True);rt.run_due()
    target=tmp_path/'restored.db';assert restore(snapshot,target)['integrity']=='ok'
    restored=Store(str(target));second=WorkflowRuntime(restored,rt.proxy,rt.courier)
    try:
        before=len(rt.courier.sent);second.run_due()
        assert len(rt.courier.sent)==before
        assert second.get(job['run_id'])['final_deliverable']['distribution']['status']=='UNKNOWN'
        assert restored.query("SELECT status FROM workflow_result_outbox")[0][0]=='unknown'
        assert restored.query('PRAGMA integrity_check')[0][0]=='ok'
        assert not restored.query('SELECT invoke_enabled FROM execution_controls')[0][0]
        assert not restored.query('SELECT 1 FROM workflow_delivery_grants WHERE revoked IS NULL')
        assert not restored.query("SELECT 1 FROM workflow_destinations WHERE state='verified'")
        assert second.authority.run(job['run_id'],wf['id'],second.get(job['run_id'])['definition_hash'],'admin')
    finally:restored._db.close()
    with pytest.raises(ValueError):restore(snapshot,target)
    (snapshot/'catalog.sqlite3').write_bytes(b'changed')
    with pytest.raises(ValueError):restore(snapshot,tmp_path/'invalid.db')


def test_sigkill_prepared_without_dispatch_can_resume(runtime,monkeypatch,tmp_path):
    rt,rid,_=runtime;wf=save(rt.store,[node('a',resource_id=rid,action='get_weather',input={'city':'A'})]);job=queue(rt,wf,monkeypatch);audit=tmp_path/'audit'
    crash(rt,job,'prepared',audit);assert not audit_rows(audit)
    expire_run(rt,job);rt.run_due();assert wait(rt,job)['status']=='succeeded'
    assert len(rt.store.query('SELECT * FROM workflow_execution_attempts WHERE run_id=?',(job['run_id'],)))==1


def test_resume_does_not_extend_expired_deadline(runtime,monkeypatch,tmp_path):
    rt,rid,_=runtime;wf=save(rt.store,[node('a',resource_id=rid,action='get_weather',input={'city':'A'}),node('b',resource_id=rid,action='get_weather',input={'city':'B'})]);job=queue(rt,wf,monkeypatch);audit=tmp_path/'audit'
    crash(rt,job,'checkpoint',audit)
    with rt.store.tx() as db:db.execute('UPDATE workflow_runs SET deadline=0 WHERE id=?',(job['run_id'],))
    rt.run_due();assert rt.get(job['run_id'])['status']=='failed' and len(audit_rows(audit))==1


def test_heartbeat_renews_live_lease_without_extending_deadline(runtime):
    rt,rid,remote=runtime;entered=threading.Event();release=threading.Event();handle=remote.handle_request
    def provider(request):
        if json.loads(request.content or '{}').get('method')=='tools/call':entered.set();release.wait(5)
        return handle(request)
    remote.handle_request=provider;wf=save(rt.store,[node('a',resource_id=rid,action='get_weather',input={'city':'A'})]);job=rt.submit(wf);assert entered.wait(2)
    initial=dict(rt.store.query('SELECT lease_until,deadline FROM workflow_runs WHERE id=?',(job['run_id'],))[0])
    try:
        until=time.monotonic()+3
        while time.monotonic()<until:
            current=dict(rt.store.query('SELECT lease_until,deadline FROM workflow_runs WHERE id=?',(job['run_id'],))[0])
            if current['lease_until']>initial['lease_until']:break
            time.sleep(.02)
        assert current['lease_until']>initial['lease_until'] and current['deadline']==initial['deadline']
        assert rt.persistence.recover()==0
    finally:release.set()
    assert wait(rt,job)['status']=='succeeded'


def test_checkpoint_payload_masks_platform_credentials(runtime):
    rt,rid,remote=runtime;secret='workflow-checkpoint-private-value';rt.store.set_credential('CHECKPOINT_SECRET',secret,'test','')
    remote.call_result={'content':[{'type':'text','text':secret}]}
    wf=save(rt.store,[node('a',resource_id=rid,action='get_weather',input={'city':'A'},credential_refs={'extra':'CHECKPOINT_SECRET'})]);job=rt.submit(wf);assert wait(rt,job)['status']=='succeeded'
    payload=rt.store.query('SELECT payload FROM workflow_checkpoints WHERE run_id=?',(job['run_id'],))[0][0]
    assert secret not in payload and '[REDACTED]' in payload


def test_changed_snapshot_cannot_reuse_signed_run_authority(runtime,monkeypatch):
    rt,rid,_=runtime;wf=save(rt.store,[node('a',resource_id=rid,action='get_weather',input={'city':'A'})]);job=queue(rt,wf,monkeypatch)
    with rt.store.tx() as db:
        snapshot=json.loads(db.execute('SELECT snapshot FROM workflow_runs WHERE id=?',(job['run_id'],)).fetchone()[0]);snapshot['name']='Changed after admission'
        db.execute('UPDATE workflow_runs SET snapshot=? WHERE id=?',(json.dumps(snapshot),job['run_id']))
    rt.launch(job['run_id']);assert wait(rt,job)['status']=='failed'
    assert not rt.store.query('SELECT * FROM workflow_execution_attempts WHERE run_id=?',(job['run_id'],))
