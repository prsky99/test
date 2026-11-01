"""Real transport, state, authorization and delivery regressions for workflows."""
import hashlib
import hmac
import json
import threading
import time

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.collector import usage
from agent_market.concierge.front import Front, create_front_app, get_front_workflow_templates
from agent_market.concierge.notify import Courier
from agent_market.concierge.proxy import McpProxy
from agent_market.gateway.dashboard import dashboard_router
from agent_market.gateway.store import Store
from agent_market.workflows import WorkflowError, WorkflowRuntime, canonical, graph, next_due, public_template
from tests.test_mcp_proxy import MockRemoteMcp, WEATHER_TOOL
from tests.conftest import STAFF, staff_session  # individual staff session; the machine token reads aggregates only


def wait(runtime, item):
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        result=runtime.get(item['run_id'])
        if result['status'] in ('succeeded','failed','cancelled'):
            # Also wait for the worker callback before closing its database.
            future=runtime.futures.get(item['run_id'])
            if future:future.result(timeout=2)
            return runtime.get(item['run_id'])
        time.sleep(.01)
    pytest.fail('Workflow did not terminate')


def node(nid='agent', **data):
    return {'id':nid,'name':nid.title(),'type':'agent','kind':'mcp','data':data}


def save(store,nodes,edges=None,**fields):
    identity=store.create_workflow({'name':'Weather Pipeline','nodes':nodes,'edges':edges or [],**fields})
    return store.get_workflow(identity)


@pytest.fixture
def runtime(tmp_path):
    store=Store(str(tmp_path/'workflow.db'))
    remote=MockRemoteMcp([WEATHER_TOOL])
    transport=httpx.Client(transport=remote)
    runtime=WorkflowRuntime(store,McpProxy(store,allow_private=True,http=transport),Courier(True,transport))
    rid=store.upsert_resource({'key':'mcp:https://weather.example/mcp','kind':'mcp','source':'mcp-registry','name':'Weather Agent','description':'Weather information','category':'data_utility','url':'https://weather.example/mcp','price_usdc':0,'details':{}})
    compact=usage.compact_tools([WEATHER_TOOL])
    store.record_usage(rid,tools=compact,digest=usage.tools_hash(compact),guide={},changes=None,trial={'ok':True})
    yield runtime,rid,remote
    for future in list(runtime.futures.values()):future.result(timeout=5)
    transport.close();store._db.close()


def test_real_mcp_and_immutable_snapshots(runtime):
    rt,rid,_=runtime
    wf=save(rt.store,[node(resource_id=rid,action='get_weather',input={'city':'Tokyo'})])
    first=wait(rt,rt.submit(wf,idempotency='first'))
    assert first['status']=='succeeded'
    assert 'Tokyo: 22C' in first['node_results'][0]['output']
    assert first['node_results'][0]['attempts']==1
    assert first['final_deliverable']['distribution']['status']=='NOT_REQUESTED'
    assert first['artifact_sha256']==hashlib.sha256(canonical({'workflow_name':wf['name'],'status':'succeeded','nodes':first['node_results']}).encode()).hexdigest()
    rt.store.update_workflow(wf['id'],{'name':'Revised'})
    second=wait(rt,rt.submit(rt.store.get_workflow(wf['id'])))
    assert second['definition_hash']!=first['definition_hash']
    assert rt.get(first['run_id'])['workflow_name']=='Weather Pipeline'
    assert len(rt.history(wf['id']))==2
    with pytest.raises(WorkflowError,match='another definition'):rt.submit(rt.store.get_workflow(wf['id']),idempotency='first')


def test_failure_missing_resource_and_downstream_block(runtime):
    rt,_,_=runtime
    wf=save(rt.store,[node('a',resource_id=999999),node('b',resource_id=999999)], [{'source':'a','target':'b'}])
    result=wait(rt,rt.submit(wf))
    assert result['status']=='failed'
    assert [n['status'] for n in result['node_results']]==['failed','blocked']
    assert result['final_deliverable']['distribution']['status']=='NOT_REQUESTED'


def test_router_disabled_and_invalid_graph(runtime):
    rt,rid,_=runtime
    nodes=[{'id':'route','type':'router','name':'Condition','data':{'condition':False}},node('a',resource_id=rid),{**node('b'),'disabled':True}]
    edges=[{'source':'route','target':'a','condition':True},{'source':'route','target':'b','condition':False}]
    result=wait(rt,rt.submit(save(rt.store,nodes,edges)))
    assert [n['status'] for n in result['node_results']]==['succeeded','skipped','skipped']
    assert sum(n['attempts'] for n in result['node_results'])==0
    with pytest.raises(WorkflowError,match='cycles'):graph({'nodes':[node('a'),node('b')],'edges':[{'source':'a','target':'b'},{'source':'b','target':'a'}]})
    with pytest.raises(WorkflowError):graph({'nodes':[node(),node()],'edges':[]})


def test_typed_upstream_mapping_and_schema_rejection(runtime):
    rt,rid,_=runtime
    nodes=[node('a',resource_id=rid,action='get_weather',input={'city':'Tokyo'}),node('b',resource_id=rid,action='get_weather',input={'city':"{{$node['a'].output.content.0.text}}"})]
    result=wait(rt,rt.submit(save(rt.store,nodes,[{'source':'a','target':'b'}])))
    assert result['status']=='succeeded'
    assert result['node_results'][1]['input']['city']=='Tokyo: 22C, sunny'
    result=wait(rt,rt.submit(save(rt.store,[node(resource_id=rid,action='get_weather',input={'city':12})])))
    assert result['status']=='failed'
    assert 'schema' in result['node_results'][0]['error']


def test_cancellation_does_not_execute_downstream(runtime):
    rt,rid,remote=runtime
    entered=threading.Event();release=threading.Event();original=remote.handle_request
    def blocked(request):
        if json.loads(request.content or '{}').get('method')=='tools/call':entered.set();release.wait(3)
        return original(request)
    remote.handle_request=blocked
    wf=save(rt.store,[node('a',resource_id=rid,action='get_weather',input={'city':'Tokyo'}),node('b',resource_id=rid,action='get_weather',input={'city':'Tokyo'})],[{'source':'a','target':'b'}])
    item=rt.submit(wf);assert entered.wait(2)
    rt.cancel(item['run_id']);release.set();result=wait(rt,item)
    assert result['status']=='cancelled'
    assert result['node_results'][1]['attempts']==0


def test_secret_output_redaction(runtime):
    rt,rid,remote=runtime
    secret='sensitive-quote-"-backslash-\\-suffix'
    rt.store.set_credential('TEST_SECRET',secret,'test','')
    remote.call_result={'content':[{'type':'text','text':secret}]}
    wf=save(rt.store,[node(resource_id=rid,action='get_weather',input={'city':'Tokyo'},credential_refs={'extra':'TEST_SECRET'})])
    result=wait(rt,rt.submit(wf))
    assert result['status']=='succeeded'
    assert secret not in canonical(result) and 'sensitive-quote' not in canonical(result)
    assert '[REDACTED]' in result['node_results'][0]['output']


def test_public_template_boundaries_and_seed_survival(runtime):
    rt,_,_=runtime;store=rt.store
    inactive=save(store,[node()],name='Inactive Public',is_template=1,is_active=0)
    secret=save(store,[node(input={'api_key':'NEVER_PUBLISH'})],name='Credential Public',is_template=1)
    assert public_template(inactive) is None and public_template(secret) is None
    for i in range(55):save(store,[node()],name='Catalog '+str(i),is_template=1)
    assert len(get_front_workflow_templates(store))>=55
    original=next(w for w in store.list_workflows(limit=1000)[0] if w['name']=='Daily Tech News & AI Research Digest')
    store.update_workflow(original['id'],{'description':'My saved changes','runs_count':123})
    reopened=Store(store.query('PRAGMA database_list')[0]['file'])
    assert reopened.get_workflow(original['id'])['description']=='My saved changes'
    assert reopened.get_workflow(original['id'])['runs_count']==123
    reopened._db.close()


def inbox_transport(messages):
    def receive(request):
        body=json.loads(request.content);messages.append((request,body))
        if body.get('jsonrpc'):return httpx.Response(200,json={'jsonrpc':'2.0','id':body['id'],'result':{'kind':'message','parts':[]}})
        return httpx.Response(202,json={'accepted':True})
    return httpx.Client(transport=httpx.MockTransport(receive))


@pytest.mark.parametrize('channel',['webhook','a2a'])
def test_verified_purpose_specific_delivery_and_revoke(runtime,channel):
    rt,_,_=runtime;messages=[];transport=inbox_transport(messages);rt.courier=Courier(True,transport)
    wf=save(rt.store,[{'id':'trigger','type':'trigger','name':'Manual','data':{}}])
    with pytest.raises(WorkflowError):rt.register_destination(wf['id'],{'channel':channel,'url':'https://inbox.example/inbox','authority':False,'notice':'workflow-results-v1'})
    pending=rt.register_destination(wf['id'],{'channel':channel,'url':'https://inbox.example/inbox','authority':True,'notice':'workflow-results-v1'})
    assert len(messages)==1
    body=messages[0][1]
    challenge=body if channel=='webhook' else body['params']['message']['parts'][0]['data']
    with pytest.raises(WorkflowError):rt.save_schedule(wf['id'],{'mode':'manual','enabled':False,'destination_id':pending['id'],'delivery_authority':True,'delivery_notice':'workflow-result-grant-v1','delivery_sources':['admin']})
    rt.verify_destination(wf['id'],pending['id'],challenge['code'])
    rt.save_schedule(wf['id'],{'mode':'manual','enabled':False,'destination_id':pending['id'],'delivery_authority':True,'delivery_notice':'workflow-result-grant-v1','delivery_sources':['admin']})
    result=wait(rt,rt.submit(wf))
    assert result['final_deliverable']['distribution']['status']=='ACCEPTED'
    request,payload=messages[-1]
    expected='sha256='+hmac.new(challenge['signing_secret'].encode(),request.headers['x-agent-timestamp'].encode()+b'.'+request.content,hashlib.sha256).hexdigest()
    assert hmac.compare_digest(expected,request.headers['x-agent-signature'])
    rt._deliver(result['run_id'],wf['id'],result);assert len(messages)==2
    rt.revoke_destination(wf['id'],pending['id'])
    result=wait(rt,rt.submit(wf));assert result['final_deliverable']['distribution']['status']=='NOT_REQUESTED'
    assert len(messages)==2
    assert 'https://inbox' not in str(rt.schedule(wf['id']))
    transport.close()


def test_wrong_codes_expire_and_private_urls_fail(runtime):
    rt,_,_=runtime;messages=[];rt.courier=Courier(True,inbox_transport(messages));wf=save(rt.store,[node()])
    for url in ('https://127.0.0.1/inbox','https://localhost/inbox','https://inbox.example/inbox?token=secret','https://user:pass@inbox.example/inbox'):
        with pytest.raises(WorkflowError):rt.register_destination(wf['id'],{'channel':'webhook','url':url,'authority':True,'notice':'workflow-results-v1'})
    pending=rt.register_destination(wf['id'],{'channel':'webhook','url':'https://inbox.example/inbox','authority':True,'notice':'workflow-results-v1'})
    correct=messages[0][1]['code'];wrong='111111' if correct!='111111' else '222222'
    for _ in range(5):
        with pytest.raises(WorkflowError):rt.verify_destination(wf['id'],pending['id'],wrong)
    row=rt.store.query('SELECT * FROM workflow_destinations WHERE id=?',(pending['id'],))[0]
    assert row['state']=='expired' and row['sealed'] is None


def test_schedule_persistence_tick_and_signed_event_replay(runtime):
    rt,_,_=runtime;wf=save(rt.store,[{'id':'trigger','type':'trigger','name':'Manual','data':{}}])
    with pytest.raises(WorkflowError):next_due('daily_0900','Invalid/Zone')
    config=rt.save_schedule(wf['id'],{'mode':'scheduled','enabled':True,'preset':'daily_0900','timezone':'America/New_York'})
    due=config['next_run'];assert due>time.time()
    assert rt.run_due(due)['checked']==1
    assert rt.run_due(due)['checked']==0
    for r in rt.history(wf['id']):wait(rt,{'run_id':r['id']})
    config=rt.save_schedule(wf['id'],{'mode':'event_driven','enabled':True,'preset':'hourly','timezone':'UTC'})
    raw=b'{"nodes":[]}' # Signed payload cannot override the saved graph.
    stamp=str(int(time.time()));event='evt_123'
    signature='sha256='+hmac.new(config['event_key'].encode(),stamp.encode()+b'.'+event.encode()+b'.'+raw,hashlib.sha256).hexdigest()
    assert rt.receive_event(wf['id'],raw,stamp,event,signature)['accepted']
    with pytest.raises(WorkflowError):rt.receive_event(wf['id'],raw,stamp,event,signature)
    with pytest.raises(WorkflowError):rt.receive_event(wf['id'],raw,stamp,'other',signature)
    assert 'event_key' not in rt.schedule(wf['id']) and 'event_sealed' not in rt.schedule(wf['id'])
    for r in rt.history(wf['id']):wait(rt,{'run_id':r['id']})


def test_public_run_capability_cors_and_admin_routes(runtime):
    rt,rid,_=runtime;store=rt.store
    front=Front(store,allow_private=True)
    # Front intentionally reuses the Store singleton runtime; restore the controlled transport.
    front.workflows.proxy=rt.proxy=McpProxy(store,allow_private=True,http=httpx.Client(transport=MockRemoteMcp([WEATHER_TOOL])))
    public=TestClient(create_front_app(front))
    wf=save(store,[node(resource_id=rid,action='get_weather',input={'city':'Tokyo'})],is_template=1)
    assert public.post('/api/workflows/run',json={'nodes':[node()]}).status_code==400
    response=public.post('/api/workflows/run',json={'template_id':wf['id']},headers={'Origin':'null'})
    assert response.status_code==202 and response.headers['access-control-allow-origin']=='*'
    item=response.json();result=wait(rt,item)
    path='/api/workflows/runs/'+item['run_id']
    assert public.get(path).status_code==404
    assert public.get(path,headers={'X-Workflow-Key':'incorrect'}).status_code==404
    observed=public.get(path,headers={'X-Workflow-Key':item['run_key']}).json()
    assert observed['status']=='succeeded' and 'input' not in observed['node_results'][0]
    assert public.options(path,headers={'Origin':'null','Access-Control-Request-Headers':'X-Workflow-Key'}).status_code==204
    app=FastAPI();app.include_router(dashboard_router(store,':memory:','test-admin',None,front=front))
    staff_session(store)
    admin=TestClient(app);headers=STAFF
    assert admin.get('/admin/api/workflows/runs/'+item['run_id']).status_code in (401,403)
    assert admin.get('/admin/api/workflows/runs/'+item['run_id'],headers=headers).json()['status']=='succeeded'
    stale=admin.post('/admin/api/workflows/'+str(wf['id'])+'/run',json={'nodes':[node('different')]},headers=headers)
    assert stale.status_code==409
    assert admin.get('/admin/api/workflows/'+str(wf['id'])+'/runs',headers=headers).json()['runs']
    assert admin.post('/admin/api/workflows',json={'name':'Cycle','nodes':[node('a'),node('b')],'edges':[{'source':'a','target':'b'},{'source':'b','target':'a'}]},headers=headers).status_code==400
    assert admin.post('/admin/api/workflows',json={'name':'Secret','nodes':[node(input={'api_key':'DO_NOT_SAVE'})]},headers=headers).status_code==400
    draft=admin.post('/admin/api/workflows/ai-generate',json={'prompt':'Weather research'},headers=headers)
    # The contract compiler must refuse unrelated weather/popularity matches.
    # Approved news/docs generation and its positive execution/export path are
    # covered by the isolated composer regressions.
    assert draft.status_code==422
    assert 'No matching registered agents' in draft.json()['detail']
    alternatives=admin.get('/admin/api/workflows/agents/alternatives',headers=headers).json()['alternatives']
    assert all(a['id']>0 for a in alternatives)
    config=admin.post('/admin/api/workflows/'+str(wf['id'])+'/export-app',json={},headers=headers).json()['config']
    assert config['execution_mode']=='server' and 'sample_output' not in canonical(config)
    public.close();admin.close()


@pytest.mark.parametrize('version',['0.3','1.0'])
def test_real_a2a_messages_and_completed_artifacts(runtime,version):
    rt,_,_=runtime;calls=[]
    def remote(request):
        if request.method=='GET':
            card={'name':'Weather Agent','skills':[]}
            if version=='1.0':card['supportedInterfaces']=[{'url':'https://agent.example/rpc','protocolBinding':'JSONRPC','protocolVersion':'1.0'}]
            else:card.update(protocolVersion='0.3',url='https://agent.example/rpc',preferredTransport='JSONRPC')
            return httpx.Response(200,json=card)
        body=json.loads(request.content);calls.append(body)
        assert body['method']==('SendMessage' if version=='1.0' else 'message/send')
        assert body['params']['configuration'].get('returnImmediately',False) is False
        task={'kind':'task','status':{'state':'TASK_STATE_COMPLETED' if version=='1.0' else 'completed'},'artifacts':[{'parts':[{'text':'Verified A2A weather'}]}]}
        return httpx.Response(200,json={'jsonrpc':'2.0','id':body['id'],'result':{'task':task} if version=='1.0' else task})
    transport=httpx.Client(transport=httpx.MockTransport(remote));rt.courier=Courier(True,transport)
    rid=rt.store.upsert_resource({'key':'a2a:https://agent.example/card.json','kind':'a2a','source':'agent-card','name':'Weather Agent','description':'Weather','category':'data_utility','url':'https://agent.example/card.json','price_usdc':0,'details':{}})
    wf=save(rt.store,[{**node(resource_id=rid,input={'query':'weather'}),'kind':'a2a'}])
    result=wait(rt,rt.submit(wf));assert result['status']=='succeeded'
    assert 'Verified A2A weather' in result['node_results'][0]['output'] and len(calls)==1
    transport.close()


def test_operation_deadline_and_schema_remote_reference_fail_closed(runtime,monkeypatch):
    rt,rid,remote=runtime
    monkeypatch.setattr('agent_market.workflows.MAX_SECONDS',.01)
    original=remote.handle_request
    def slow(request):
        if json.loads(request.content or '{}').get('method')=='tools/list':time.sleep(.025)
        return original(request)
    remote.handle_request=slow
    wf=save(rt.store,[node(resource_id=rid,action='get_weather',input={'city':'Tokyo'})])
    assert wait(rt,rt.submit(wf))['status']=='failed'
    monkeypatch.setattr('agent_market.workflows.MAX_SECONDS',25)
    remote.handle_request=original
    with rt.store.tx() as db:db.execute('UPDATE resources SET usage_tools=? WHERE id=?',(json.dumps([{'name':'get_weather','inputSchema':{'$ref':'http://127.0.0.1/private'}}]),rid))
    result=wait(rt,rt.submit(wf))
    assert result['status']=='failed' and 'schema' in result['node_results'][0]['error']


def test_restart_lease_preserves_active_worker_and_marks_expired(runtime):
    rt,_,_=runtime
    wf=save(rt.store,[{'id':'trigger','type':'trigger','name':'Manual','data':{}}])
    item=wait(rt,rt.submit(wf))
    with rt.store.tx() as db:
        # A legacy interrupted run has no persisted execution deadline/proof.
        db.execute("UPDATE workflow_runs SET status='running',result=NULL,deadline=NULL,lease_until=? WHERE id=?",(time.time()+90,item['run_id']))
    second=WorkflowRuntime(rt.store,rt.proxy,rt.courier)
    assert second.get(item['run_id'])['status']=='running'
    with rt.store.tx() as db:db.execute('UPDATE workflow_runs SET lease_until=0 WHERE id=?',(item['run_id'],))
    second.run_due()
    assert second.get(item['run_id'])['status']=='failed'
    assert 'interrupted' in second.get(item['run_id'])['error']


def test_public_results_hide_private_provider_content(runtime):
    from agent_market.workflows import public_outcome
    result=public_outcome({'input':{'key':'private'},'node_results':[{'output':'Contact person@example.com at /Users/private/project with Bearer hidden-value','input':{'city':'Tokyo'}}]})
    wire=canonical(result)
    assert 'person@example.com' not in wire and '/Users/private' not in wire and 'hidden-value' not in wire
    assert 'input' not in result['node_results'][0] and 'input' not in result


def test_hourly_schedule_handles_repeated_dst_hour():
    from datetime import datetime,timezone
    now=datetime(2026,11,1,5,15,tzinfo=timezone.utc).timestamp()
    due=next_due('hourly','America/New_York',now)
    assert due==datetime(2026,11,1,6,0,tzinfo=timezone.utc).timestamp()


def test_resource_endpoint_and_schema_are_pinned_in_version(runtime,monkeypatch):
    rt,rid,_=runtime
    wf=save(rt.store,[node(resource_id=rid,action='get_weather',input={'city':'Tokyo'})])
    original_launch=rt.launch;monkeypatch.setattr(rt,'launch',lambda identity:None)
    item=rt.submit(wf)
    with rt.store.tx() as db:db.execute('UPDATE resources SET url=? WHERE id=?',('https://changed.example/mcp',rid))
    monkeypatch.setattr(rt,'launch',original_launch);rt.launch(item['run_id'])
    result=wait(rt,item)
    assert result['status']=='failed' and 'connection changed' in result['node_results'][0]['error']


def test_seed_identity_preserves_renamed_and_disabled_template(runtime):
    rt,_,_=runtime;store=rt.store
    default=next(w for w in store.list_workflows(limit=1000)[0] if w['name']=='Daily Tech News & AI Research Digest')
    store.update_workflow(default['id'],{'name':'My preserved digest','is_active':0,'runs_count':77})
    before=store.list_workflows(limit=1000)[1]
    reopened=Store(store.query('PRAGMA database_list')[0]['file'])
    assert reopened.list_workflows(limit=1000)[1]==before
    saved=reopened.get_workflow(default['id'])
    assert saved['name']=='My preserved digest' and saved['is_active']==0 and saved['runs_count']==77
    reopened._db.close()
