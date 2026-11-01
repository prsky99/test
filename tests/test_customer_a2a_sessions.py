"""Customer long-task sessions share no staff membership or typed DAG run."""
from types import SimpleNamespace

import pytest

from agent_market.capability_registry import Registry
from agent_market.private_artifact_keys import ArtifactCipher,ArtifactKeys
from agent_market.workspace_remote_a2a import RemoteTasks,TaskBinding,TaskClient,PROFILE,NOTICE
from tests.test_private_artifact_keys import config
from tests.test_customer_typed_authoring import customer_flow
from tests.test_workspace_typed_release import typed_release_world
from tests.test_workspace_typed_flows import typed_world,routing
from tests.test_workspace_a2a_sessions import stream_provider


@pytest.fixture
def customer_session(customer_flow):
    x=customer_flow
    rid=x.w.store.upsert_resource({'key':'a2a:customer-isolated-session','source':'synthetic','kind':'a2a',
        'name':'Synthetic customer task','url':'https://customer-task.example/a2a','description':'Synthetic task session',
        'category':'news_media','networks':[]})
    with x.w.store.tx() as db:db.execute("UPDATE resources SET health_status='healthy',auth_observed=0 WHERE id=?",(rid,))
    version=Registry(x.w.store).current(rid)
    core=RemoteTasks(x.core.access,bindings=(TaskBinding(rid,version['id'],TaskClient('https://customer-task.example/a2a',streaming=True)),),
        cipher=ArtifactCipher(PROFILE,ArtifactKeys(config(legacy=True))))
    x.core.remote_tasks=core
    x.remote=SimpleNamespace(core=core,w=SimpleNamespace(remote_rid=rid,store=x.w.store),version=version,calls=[])
    stream_provider(x.remote)
    x.a2a=x.base+'/a2a'
    yield x
    core.bindings[rid].client.http.close()


def send_body(x):
    return {'logical_id':'rat_'+'c'*32,'resource_id':x.remote.w.remote_rid,'version_id':x.remote.version['id'],
        'text':'Public documentation task','authorized':True,'notice':NOTICE}


def test_customer_session_context_and_csrf_and_membership_are_enforced(customer_session):
    x=customer_session
    options=x.client.get(x.a2a+'/options').json()['options']
    assert options['relation_to_typed_flows']=='separate_async_task_history' and options['streaming']
    assert x.client.post(x.a2a+'/tasks',json=send_body(x)).status_code==403
    result=x.client.post(x.a2a+'/tasks',json=send_body(x),headers=x.headers)
    assert result.status_code==200,result.text
    task=result.json()['task'];assert task['state']=='input-required'
    continuation={'revision':task['revision'],'logical_id':'rat_'+'d'*32,'text':'Reviewed follow-up',
        'authorized':True,'notice':NOTICE}
    result=x.client.post(x.a2a+'/tasks/'+task['id']+'/messages',json=continuation,headers=x.headers)
    assert result.status_code==200 and result.json()['task']['state']=='completed'
    assert len(x.remote.calls)==2 and x.remote.calls[-1]['params']['message']['contextId']=='session-context'
    assert x.w.store.query('SELECT COUNT(*) FROM workspace_typed_flow_runs WHERE workspace_id=?',(x.ws,))[0][0]==0
    assert x.w.store.query('SELECT COUNT(*) FROM workspace_memberships WHERE workspace_id=?',(x.ws,))[0][0]==0
    assert x.client.get(x.a2a.replace(x.ws,'ws_'+'f'*32)+'/tasks').status_code==403
    x.s.identity.logout(x.s.raw)
    assert x.client.get(x.a2a+'/tasks').status_code==401


@pytest.mark.parametrize('action,state,method',[('cancel','canceled','tasks/cancel'),('resume','completed','tasks/resubscribe')])
def test_customer_stream_resume_and_explicit_cancel_use_same_task_without_resubmission(customer_session,action,state,method):
    x=customer_session;stream_provider(x.remote,disconnect=True)
    task=x.client.post(x.a2a+'/tasks',json=send_body(x),headers=x.headers).json()['task']
    assert task['state']=='unknown' and task['resume_available'] and task['cancel_available']
    result=x.client.post(x.a2a+'/tasks/'+task['id']+'/commands',headers=x.headers,json={
        'revision':task['revision'],'action':action,'authorized':True,'notice':NOTICE})
    assert result.status_code==200 and result.json()['task']['state']==state
    assert [call['method'] for call in x.remote.calls]==['message/stream',method]
