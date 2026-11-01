"""Selected remote task polling uses only a controlled transport and test keys."""
import copy
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.capability_registry import Registry
from agent_market.gateway import admin_auth
from agent_market.private_artifact_keys import ArtifactKeys, ArtifactCipher
from agent_market.workspace_access import WorkspaceAccess, SessionActor, WorkspaceDenied, WorkspaceConflict
from agent_market.workspace_remote_a2a import RemoteTasks, TaskClient, TaskBinding, NOTICE, PROFILE
from agent_market.workspace_remote_a2a_service import router_for
from tests.test_private_artifact_keys import config
from tests.test_workspace_execution_api import private_api


@pytest.fixture
def remote(private_api):
    w=private_api
    w.remote_rid=w.store.upsert_resource({'key':'a2a:isolated-task','source':'synthetic','kind':'a2a',
        'name':'Synthetic long task','url':'https://task.example/a2a','description':'Synthetic task lifecycle',
        'category':'news_media','networks':[]})
    with w.store.tx() as db:db.execute("UPDATE resources SET health_status='healthy',auth_observed=0 WHERE id=?",(w.remote_rid,))
    version=Registry(w.store).current(w.remote_rid)
    control={'state':'working','timeout':False,'wrong_id':False};calls=[]
    def provider(request):
        body=json.loads(request.content);calls.append(body)
        if control['timeout']:raise httpx.ReadTimeout('Synthetic uncertainty')
        task={'kind':'task','id':'other' if control['wrong_id'] else 'remote-fixture-task',
              'contextId':'fixture-context','status':{'state':control['state']}}
        if task['status']['state']=='completed':task['artifacts']=[{'artifactId':'a','parts':[{'kind':'text','text':'Synthetic retained result'}]}]
        return httpx.Response(200,json={'jsonrpc':'2.0','id':body['id'],'result':task})
    http=httpx.Client(transport=httpx.MockTransport(provider))
    from agent_market.workflows import runtime_for
    access=WorkspaceAccess(w.store,runtime_for(w.store).key)
    cipher=ArtifactCipher(PROFILE,ArtifactKeys(config(legacy=True)))
    core=RemoteTasks(access,bindings=(TaskBinding(w.remote_rid,version['id'],TaskClient('https://task.example/a2a',http=http)),),cipher=cipher)
    token=w.headers['owner']['Authorization'][7:]
    principal=SessionActor(w.users['owner'],admin_auth.session_reference(token))
    app=FastAPI();app.include_router(router_for(core))
    with TestClient(app,base_url='https://admin.test',raise_server_exceptions=False) as client:
        yield SimpleNamespace(w=w,core=core,actor=principal,version=version,calls=calls,control=control,client=client,
            base='/admin/api/workflow-workspaces/'+w.ws['id']+'/remote-a2a')
    http.close()


def command(x):
    return {'logical_id':'rat_'+'a'*32,'resource_id':x.w.remote_rid,'version_id':x.version['id'],
        'text':'Synthetic public research task','authorized':True,'notice':NOTICE}


def test_send_poll_cancel_retains_same_task_and_encrypts_private_data(remote):
    x=remote;args=(x.w.ws['id'],)
    task=x.core.send(*args,command(x),x.actor)
    assert task['state']=='working' and len(x.calls)==1
    assert x.core.send(*args,command(x),x.actor)['id']==task['id'] and len(x.calls)==1
    text=x.w.store.query('SELECT payload FROM workspace_remote_tasks')[0][0]
    assert 'Synthetic public research task' not in text and 'remote-fixture-task' not in text
    x.control['state']='completed'
    task=x.core.command(*args,task['id'],{'revision':task['revision'],'action':'poll','authorized':True,'notice':NOTICE},x.actor)
    assert task['state']=='completed' and task['remote_output_retained']
    assert x.calls[-1]['method']=='tasks/get' and x.calls[-1]['params']=={'id':'remote-fixture-task','historyLength':0}
    with pytest.raises(WorkspaceConflict):
        x.core.command(*args,task['id'],{'revision':task['revision'],'action':'cancel','authorized':True,'notice':NOTICE},x.actor)


def test_cancel_is_explicit_and_never_resends_message(remote):
    x=remote;task=x.core.send(x.w.ws['id'],command(x),x.actor)
    x.control['state']='canceled'
    result=x.core.command(x.w.ws['id'],task['id'],{'revision':task['revision'],'action':'cancel','authorized':True,'notice':NOTICE},x.actor)
    assert result['state']=='canceled' and [c['method'] for c in x.calls]==['message/send','tasks/cancel']


def test_unknown_is_a_persistent_no_replay_boundary(remote):
    x=remote;x.control['timeout']=True
    task=x.core.send(x.w.ws['id'],command(x),x.actor)
    assert task['state']=='unknown'
    assert x.core.send(x.w.ws['id'],command(x),x.actor)['state']=='unknown' and len(x.calls)==1


@pytest.mark.parametrize('change',['version','restore','role','pause','review','price','declared_auth'])
def test_stale_authority_or_version_blocks_commands(remote,change):
    x=remote;task=x.core.send(x.w.ws['id'],command(x),x.actor)
    with x.w.store.tx() as db:
        if change=='version':db.execute("UPDATE resources SET url='https://changed.example/a2a' WHERE id=?",(x.w.remote_rid,))
        if change=='restore':db.execute('INSERT INTO workspace_remote_task_restore_blocks VALUES(?)',(task['id'],))
        if change=='role':db.execute("UPDATE workspace_memberships SET role='viewer',revision=revision+1 WHERE workspace_id=? AND user_id=?",(x.w.ws['id'],x.w.users['owner']))
        if change=='pause':db.execute('UPDATE execution_controls SET invoke_enabled=0 WHERE id=1')
        if change=='review':db.execute("UPDATE resources SET eval_security='review' WHERE id=?",(x.w.remote_rid,))
        if change=='price':db.execute('UPDATE resources SET price_usdc=100 WHERE id=?',(x.w.remote_rid,))
        if change=='declared_auth':db.execute('UPDATE resources SET auth_observed=NULL,auth_declared=1 WHERE id=?',(x.w.remote_rid,))
    with pytest.raises((WorkspaceDenied,WorkspaceConflict,ValueError)):
        x.core.command(x.w.ws['id'],task['id'],{'revision':task['revision'],'action':'poll','authorized':True,'notice':NOTICE},x.actor)
    assert len(x.calls)==1


def test_packet_guard_rechecks_policy_after_preparation(remote,monkeypatch):
    x=remote;client=x.core.bindings[x.w.remote_rid].client;call=client.call
    def changed(method,params,**kwargs):
        with x.w.store.tx() as db:db.execute("UPDATE resources SET eval_security='review' WHERE id=?",(x.w.remote_rid,))
        return call(method,params,**kwargs)
    monkeypatch.setattr(client,'call',changed)
    task=x.core.send(x.w.ws['id'],command(x),x.actor)
    assert task['state']=='unknown' and not x.calls


def test_expired_before_packet_and_late_reply_never_commit_success(remote,monkeypatch):
    import agent_market.workspace_remote_a2a as module
    x=remote;now=module.clock();client=x.core.bindings[x.w.remote_rid].client;call=client.call
    def late(method,params,**kwargs):
        result=call(method,params,**kwargs)
        monkeypatch.setattr(module,'clock',lambda:now+1000)
        return result
    monkeypatch.setattr(client,'call',late)
    task=x.core.send(x.w.ws['id'],command(x),x.actor)
    assert task['state']=='unknown' and len(x.calls)==1


def test_large_unicode_private_output_stays_encrypted_and_readable(remote):
    x=remote
    x.control['state']='completed'
    client=x.core.bindings[x.w.remote_rid].client
    call=client.call
    def output(method,params,**kwargs):
        result=call(method,params,**kwargs)
        result['artifacts']=[{'artifactId':'a','parts':[{'kind':'text','text':'\u2603'*16000}]}]
        return result
    client.call=output
    task=x.core.send(x.w.ws['id'],command(x)|{'text':'\u2603'*1000},x.actor)
    assert task['state']=='completed' and task['remote_output_retained']
    assert x.core.status(x.w.ws['id'],task['id'],x.actor)['state']=='completed'


def test_private_routes_require_named_session_and_fresh_consent(remote):
    x=remote
    assert x.client.get(x.base+'/options').status_code==401
    result=x.client.post(x.base+'/tasks',headers=x.w.headers['owner'],json=command(x)|{'authorized':False})
    assert result.status_code==400 and not x.calls
    assert x.client.post(x.base+'/tasks',headers=x.w.headers['owner'],json=command(x)).status_code==200
    assert x.client.post(x.base+'/tasks',headers=x.w.headers['owner'],json=command(x)|{'text':'Changed'}).status_code==409


def test_retained_history_and_result_do_not_repeat_provider_calls(remote):
    x=remote;x.control['state']='completed'
    task=x.core.send(x.w.ws['id'],command(x),x.actor)
    headers=x.w.headers['owner']
    history=x.client.get(x.base+'/tasks',headers=headers)
    result=x.client.get(x.base+'/tasks/'+task['id'],headers=headers)
    assert history.status_code==result.status_code==200 and len(x.calls)==1
    assert history.json()['tasks'][0]['id']==task['id']
    assert 'output_preview' not in history.json()['tasks'][0]
    assert result.json()['task']['output_preview']=='Synthetic retained result'
    assert 'remote-fixture-task' not in result.text


def test_global_dispatch_admission_and_shared_pool_bound_calls(remote):
    from agent_market.workspace_execution import _slots
    x=remote
    for _ in range(4):
        assert _slots.acquire(blocking=False)
    try:
        with pytest.raises(WorkspaceConflict):x.core.send(x.w.ws['id'],command(x),x.actor)
        assert not x.calls
    finally:
        for _ in range(4):_slots.release()
    task=x.core.send(x.w.ws['id'],command(x),x.actor)
    with x.core.access._tx(x.actor,write=True) as (db,_):
        original=x.core._load(db,x.w.ws['id'],task['id'])
        for i in range(4):
            value=copy.deepcopy(original)
            value.update(id='rtk_'+str(i)*32,logical_id='rat_'+str(i)*32,state='dispatched')
            x.core._save(db,value)
    with pytest.raises(WorkspaceConflict):
        x.core.send(x.w.ws['id'],command(x)|{'logical_id':'rat_'+'b'*32},x.actor)
    assert len(x.calls)==1
