"""Version boundaries, truthful evidence, schema drift and contract fixtures."""
import asyncio
import copy
import json
import sqlite3
import time
from datetime import datetime,timezone

import pytest

from agent_market.capability_registry import Registry,full_tools,digest
from agent_market.capability_contracts import validate,run_test
from agent_market.collector import usage
from agent_market.gateway.store import Store
from tests.test_fast_single_recommendation import catalog,ask,chosen
from tests.test_managed_agent_gateway import managed
from tests.test_admin_security_audit import admin,H
from tests.conftest import staff_session


def stamp(at):return datetime.fromtimestamp(at,timezone.utc).isoformat().replace('+00:00','Z')


def test_stable_agent_identity_and_private_binding_version_change(managed):
    store,_,_,_,rid,_,_=managed;registry=Registry(store);one=registry.current(rid)
    initial=store.query('SELECT COUNT(*) FROM connection_versions')[0][0]
    assert registry.current(rid)==one
    with store.tx() as db:db.execute('UPDATE resources SET url=? WHERE id=?',('https://changed.example/mcp',rid))
    two=registry.current(rid)
    assert one['agent_ref']==two['agent_ref'] and one['id']!=two['id']
    with store.tx() as db:db.execute('UPDATE resources SET auth_observed=1 WHERE id=?',(rid,))
    assert registry.current(rid)['id']!=two['id']
    assert store.query('SELECT COUNT(*) FROM connection_versions')[0][0]==initial+2


def test_full_schema_drift_omitted_from_compact_hash_is_blocked(managed):
    store,_,client,_,rid,calls,remote=managed
    remote.tools=copy.deepcopy(remote.tools)
    original=usage.tools_hash(usage.compact_tools(remote.tools))
    remote.tools[0]['inputSchema']['additionalProperties']=False
    assert usage.tools_hash(usage.compact_tools(remote.tools))==original
    result=client.post('/api/test/execute',json={'resource_id':rid,'tool':'get_weather','arguments':{'city':'Tokyo'}}).json()
    assert result['error_code']=='SCHEMA_CHANGED'
    assert not any(json.loads(c.content).get('method')=='tools/call' for c in calls)
    assert store.resource(rid)['health_status']=='quarantined'


def test_current_success_then_failure_then_schema_change_cannot_inherit(managed):
    store,_,client,_,rid,_,remote=managed;registry=Registry(store)
    assert client.get(f'/api/agents/{rid}').json()['agent']['connection_readiness']['verified_callable'] is False
    assert client.get(f'/api/agents/{rid}').json()['agent']['gateway_ready'] is False
    assert client.post('/api/test/execute',json={'resource_id':rid,'tool':'get_weather','arguments':{'city':'Tokyo'}}).json()['execution_succeeded']
    resource=store.resource(rid);version=registry.current(resource)
    assert registry.projection(resource)['connection_readiness']['verified_callable'] is True
    assert registry.projection(resource)['gateway_ready'] is True
    assert client.get(f'/api/agents/{rid}').json()['agent']['gateway_ready'] is True
    at=time.time();registry.record(version,scope='execution',outcome='failed',started=at,finished=at)
    assert registry.projection(resource)['connection_readiness']['reason']=='latest_failure'
    remote.tools=copy.deepcopy(remote.tools)
    remote.tools[0]['outputSchema']={'type':'object','required':['new-field']}
    compact=usage.compact_tools(remote.tools)
    store.record_usage(rid,compact,usage.tools_hash(compact),{},None,None,full_tools=remote.tools)
    assert registry.current(rid)['id']!=version['id']
    assert registry.projection(store.resource(rid))['connection_readiness']['reason']=='not_verified'


def test_approved_version_change_is_rejected_before_dispatch(managed):
    from agent_market.concierge.execution_policy import ExecutionDenied
    store,front,_,_,rid,calls,_=managed;version=Registry(store).current(rid)
    with store.tx() as db:db.execute('UPDATE resources SET url=? WHERE id=?',('https://changed.example/mcp',rid))
    with pytest.raises(ExecutionDenied):asyncio.run(front.managed_gateway.execute(rid,tool='get_weather',arguments={'city':'Tokyo'},expected_version=version['id']))
    assert not calls


def test_timed_out_mcp_cannot_promote_late_success_evidence(managed,monkeypatch):
    import threading
    store,front,_,_,rid,_,remote=managed
    release=threading.Event();done=threading.Event();original=remote.handle_request
    def delayed(request):
        if json.loads(request.content).get('method')=='tools/call':release.wait(2)
        return original(request)
    remote.handle_request=delayed
    execute=front.proxy._execute_recorded
    def finished(*args,**kwargs):
        try:return execute(*args,**kwargs)
        finally:done.set()
    monkeypatch.setattr(front.proxy,'_execute_recorded',finished)
    result=asyncio.run(front.managed_gateway.execute(rid,tool='get_weather',arguments={'city':'Tokyo'},timeout=.05))
    assert result['task_status']=='timeout'
    release.set();assert done.wait(2)
    registry=Registry(store)
    assert registry.projection(store.resource(rid))['connection_readiness']['reason']=='latest_failure'
    assert registry.inspect(rid)['evidence'][0]['outcome']=='unknown'


def test_binding_change_during_handshake_does_not_dispatch_tool(managed):
    store,_,client,_,rid,calls,remote=managed;original=remote.handle_request
    def changed(request):
        result=original(request)
        if json.loads(request.content).get('method')=='tools/list':
            with store.tx() as db:db.execute('UPDATE resources SET auth_observed=1 WHERE id=?',(rid,))
        return result
    remote.handle_request=changed
    response=client.post('/api/test/execute',json={'resource_id':rid,'tool':'get_weather','arguments':{'city':'Tokyo'}})
    assert response.json()['error_code']=='SCHEMA_CHANGED'
    assert not any(json.loads(c.content).get('method')=='tools/call' for c in calls)


def test_evidence_expiry_and_authentication_are_not_callable(managed):
    store,_,_,_,rid,_,_=managed;registry=Registry(store);version=registry.current(rid)
    at=time.time()-90000;registry.record(version,scope='execution',outcome='succeeded',started=at,finished=at)
    assert registry.projection(store.resource(rid))['connection_readiness']['reason']=='expired'
    with store.tx() as db:db.execute('UPDATE resources SET auth_observed=1 WHERE id=?',(rid,))
    state=registry.projection(store.resource(rid))['connection_readiness']
    assert not state['profile_available'] and not state['verified_callable']


def test_new_report_documenting_old_execution_does_not_rank_as_new(catalog):
    store,_,client,add,now=catalog
    old=add('Old execution',report_at=now-500);new=add('New execution',report_at=now-5)
    from tests.report_fixtures import legacy_report_fixture
    legacy_report_fixture(store,{'resource_id':old,'kind':'mcp','title':'Written today','slug':'new-document-old-execution',
        'created_at':now,'executed_at':now-10000,'execution_finished_at':now-9999,'is_success':1})
    assert chosen(ask(client))['id']==new
    with pytest.raises(ValueError):store.create_test_report({'title':'Future execution','executed_at':now+100,'execution_finished_at':now+101})


def test_latest_version_failure_removes_chat_candidate(catalog):
    store,_,client,add,now=catalog
    rid=add('Failed latest',kind='a2a',report_at=now-1);good=add('Working latest',kind='a2a',report_at=now-10)
    registry=Registry(store);at=time.time();registry.record(registry.current(rid),scope='execution',outcome='failed',started=at,finished=at)
    assert chosen(client.post('/chat',json={'message':'weather forecast'}).json())['id']==good


def test_recent_actual_execution_ranks_before_a_newer_report_document(catalog):
    store,_,client,add,now=catalog
    recent=add('Recent real execution',kind='a2a',report_at=now-500)
    add('Recent report',kind='a2a',report_at=now-10)
    registry=Registry(store);at=time.time();registry.record(registry.current(recent),scope='execution',outcome='succeeded',started=at,finished=at)
    assert chosen(client.post('/chat',json={'message':'weather forecast'}).json())['id']==recent
    with store.tx() as db:db.execute('UPDATE resources SET url=? WHERE id=?',('https://replacement.example/a2a',recent))
    assert not store.query('SELECT * FROM capability_eligibility WHERE resource_id=?',(recent,))
    assert not registry.projection(store.resource(recent))['connection_readiness']['verified_callable']


def test_cached_catalog_does_not_reuse_a_success_badge(managed):
    from agent_market.concierge.front import get_front_explore,clear_front_caches
    store,_,client,_,rid,_,_=managed;clear_front_caches()
    client.post('/api/test/execute',json={'resource_id':rid,'tool':'get_weather','arguments':{'city':'Tokyo'}})
    one=get_front_explore(store,'',None,None,True,False)
    assert next(i for i in one['items'] if i['id']==rid)['connection_readiness']['verified_callable']
    registry=Registry(store);at=time.time();registry.record(registry.current(rid),scope='execution',outcome='failed',started=at,finished=at)
    two=get_front_explore(store,'',None,None,True,False)
    assert not any(i['id']==rid for i in two['items'])


def test_public_projection_and_reference_lookup_do_not_reveal_private_versions(managed):
    store,_,client,_,rid,_,_=managed
    body=client.get(f'/api/agents/{rid}').json()['agent'];ref=body['agent_ref']
    result=client.get('/api/connections/'+ref)
    assert result.status_code==200 and result.headers['cache-control']=='no-store'
    assert result.json()['endpoint'].startswith('https://agentconcierge.biz/api/gateway/')
    for secret in [store.resource(rid)['url'],'binding_hash','schema_hash','usage_full_tools','cv_']:
        assert secret not in result.text and secret not in json.dumps(body)
    assert client.get('/api/connections/ag_invalid').status_code==404


def test_registry_reopens_and_online_backup_preserves_versions(tmp_path):
    path=tmp_path/'catalog.sqlite3';store=Store(str(path))
    rid=store.upsert_resource({'key':'a','kind':'a2a','source':'fixture','url':'https://agent.example','name':'Agent','description':'Search','category':'other','networks':[]})
    version=Registry(store).current(rid)
    dest=tmp_path/'restored.sqlite3'
    with sqlite3.connect(dest) as target:store._db.backup(target)
    store._db.close();restored=Store(str(dest))
    assert Registry(restored).current(rid)==version
    assert restored.query('PRAGMA integrity_check')[0][0]=='ok'
    restored._db.close()


def test_legacy_schema_migration_preserves_report_time_without_backfill(tmp_path):
    from agent_market.gateway.store import SCHEMA
    path=tmp_path/'legacy.sqlite3'
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        db.execute("INSERT INTO agent_test_reports (title,slug,kind,source,agent_name,agent_url,category,test_method,summary,content_md,pros,cons,created_at,updated_at) VALUES ('Historical','historical','mcp','fixture','Agent','https://agent.example','other','manual','','','[]','[]',1000,2000)")
    migrated=Store(str(path))
    row=migrated.query('SELECT created_at,updated_at,executed_at,connection_version_id FROM agent_test_reports')[0]
    assert tuple(row)==(1000,2000,None,None)
    assert not migrated.query('SELECT * FROM capability_evidence')
    migrated._db.close();reopened=Store(str(path))
    assert reopened.query('SELECT created_at FROM agent_test_reports')[0][0]==1000
    assert reopened.query('PRAGMA integrity_check')[0][0]=='ok'
    reopened._db.close()


def contract_fixture(contract):
    now=time.time();inputs={'query':'research','language':'en','limit':2}
    item={'url':'https://sources.example/article','retrieved_at':stamp(now)}
    if contract=='news.search.v1':
        inputs['from_utc']=stamp(now-3600);item.update(title='News',source='Journal',published_at=stamp(now-60),summary='A source-backed result.')
    elif contract=='docs.search.v1':item.update(title='Documentation',excerpt='A source-backed excerpt.',version='v1')
    else:inputs['criteria']=['weight'];item.update(name='Product',attributes={'weight':'100 g'})
    return inputs,{'items':[item],'partial':False},now


@pytest.mark.parametrize('contract',['news.search.v1','docs.search.v1','products.compare.v1'])
def test_three_contracts_accept_bounded_source_backed_results(contract):
    inputs,output,now=contract_fixture(contract);validate(contract,inputs,output,now=now)


@pytest.mark.parametrize('contract',['news.search.v1','docs.search.v1','products.compare.v1'])
@pytest.mark.parametrize('fault',['duplicate','private-source','userinfo','stale','future','missing-source','missing-field','unknown-output','wrong-language','boolean-limit'])
def test_contract_security_and_semantic_boundaries(contract,fault):
    inputs,output,now=contract_fixture(contract);item=output['items'][0]
    if fault=='duplicate':output['items'].append(copy.deepcopy(item))
    elif fault=='private-source':item['url']='https://127.0.0.1/private'
    elif fault=='userinfo':item['url']='https://secret@sources.example/a'
    elif fault=='stale':item['retrieved_at']=stamp(now-90000)
    elif fault=='future':item['retrieved_at']=stamp(now+100)
    elif fault=='missing-source':item['url']=''
    elif fault=='missing-field':item.pop('retrieved_at')
    elif fault=='unknown-output':item['private']='unregistered field'
    elif fault=='wrong-language':inputs['language']='ko'
    else:inputs['limit']=True
    with pytest.raises(ValueError):validate(contract,inputs,output,now=now)


def test_news_order_period_and_unknown_publication_time():
    inputs,output,now=contract_fixture('news.search.v1');second=copy.deepcopy(output['items'][0]);second['url']+='2';second['published_at']=stamp(now-20)
    output['items'].append(second)
    with pytest.raises(ValueError):validate('news.search.v1',inputs,output,now=now)
    output['items']=[second];second['published_at']=None
    with pytest.raises(ValueError):validate('news.search.v1',inputs,output,now=now)
    output['partial']=True;validate('news.search.v1',inputs,output,now=now)


def test_explicit_approval_is_not_success_until_real_contract_runner_passes(managed):
    store,front,_,_,rid,calls,remote=managed;registry=Registry(store)
    inputs,output,_=contract_fixture('docs.search.v1')
    spec={'name':'search_docs','description':'Search documentation','inputSchema':{'type':'object','properties':{'query':{'type':'string'},'language':{'const':'en'},'limit':{'type':'integer'}}},'annotations':{'readOnlyHint':True}}
    remote.tools=[spec,{**spec,'name':'lookup_docs'}];compact=usage.compact_tools(remote.tools);store.record_usage(rid,compact,usage.tools_hash(compact),{},None,None,full_tools=remote.tools)
    remote.call_result={'structuredContent':output};resource=store.resource(rid)
    with pytest.raises(ValueError):asyncio.run(run_test(registry,resource,'docs.search.v1',inputs,front.managed_gateway.execute))
    assert not calls
    registry.approve(resource,'docs.search.v1','search_docs')
    assert not registry.projection(resource)['capability_contracts'][0]['verified']
    result=asyncio.run(run_test(registry,resource,'docs.search.v1',inputs,front.managed_gateway.execute))
    assert result['ok'] and registry.projection(resource)['capability_contracts'][0]['verified']
    registry.approve(resource,'docs.search.v1','lookup_docs')
    assert not registry.projection(resource)['capability_contracts'][0]['verified']
    registry.approve(resource,'docs.search.v1','search_docs')
    assert not registry.projection(resource)['capability_contracts'][0]['verified']
    remote.call_result={'structuredContent':{'items':[],'partial':False,'fabricated':True}}
    assert not asyncio.run(run_test(registry,resource,'docs.search.v1',inputs,front.managed_gateway.execute))['ok']
    assert not registry.projection(resource)['capability_contracts'][0]['verified']
    assert inputs['query'] not in json.dumps([dict(r) for r in store.query('SELECT * FROM capability_evidence')])


def test_admin_contract_endpoints_auth_and_input_boundary(admin):
    _,client=admin
    assert client.get('/admin/api/capability-contracts').status_code in (401,403)
    assert len(client.get('/admin/api/capability-contracts',headers=H).json()['contracts'])==4
    assert client.post('/admin/api/connections/1/contracts/docs.search.v1',headers={**H,'Content-Type':'application/json'},content='{').status_code==400
    assert client.get('/admin/api/connections/999',headers=H).status_code==404


def test_authenticated_admin_contract_test_calls_registered_fixture_only(managed):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from unittest.mock import Mock
    from agent_market.gateway.dashboard import dashboard_router
    store,front,_,_,rid,calls,remote=managed
    inputs,output,_=contract_fixture('docs.search.v1')
    remote.tools=[{'name':'search_docs','description':'Search documentation','inputSchema':{'type':'object'},'annotations':{'readOnlyHint':True}}]
    compact=usage.compact_tools(remote.tools);store.record_usage(rid,compact,usage.tools_hash(compact),{},None,None,full_tools=remote.tools)
    remote.call_result={'structuredContent':output}
    app=FastAPI();app.include_router(dashboard_router(store,':memory:','system-test-secret',None,front=front,ssl_manager=Mock(get_status=lambda:{})))
    staff=staff_session(store)
    with TestClient(app,base_url='https://admin.test') as client:
        path=f'/admin/api/connections/{rid}/contracts/docs.search.v1'
        assert client.post(path,headers=staff,json={'tool':'search_docs'}).status_code==200
        assert not calls
        response=client.post(path+'/test',headers=staff,json={'input':inputs})
        assert response.status_code==200 and response.json()['ok']
        assert sum(json.loads(c.content).get('method')=='tools/call' for c in calls)==1


def test_one_transient_failure_after_success_keeps_readiness_but_not_two(managed):
    # 2026-10-21: one burst-limit tool error removed the only workspace agent.
    store,_,client,_,rid,_,_=managed;registry=Registry(store)
    assert client.post('/api/test/execute',json={'resource_id':rid,'tool':'get_weather','arguments':{'city':'Tokyo'}}).json()['execution_succeeded']
    resource=store.resource(rid);version=registry.current(resource)
    readiness=lambda:registry.projection(resource)['connection_readiness']
    at=time.time();registry.record(version,scope='execution',outcome='failed',started=at,finished=at,code='UPSTREAM_TOOL_ERROR')
    assert readiness()['verified_callable'] is True
    registry.record(version,scope='execution',outcome='failed',started=at+1,finished=at+1,code='UPSTREAM_TIMEOUT')
    assert readiness()['reason']=='latest_failure'
    assert client.post('/api/test/execute',json={'resource_id':rid,'tool':'get_weather','arguments':{'city':'Tokyo'}}).json()['execution_succeeded']
    registry.record(version,scope='execution',outcome='failed',started=at+5,finished=at+5,code='SCHEMA_CHANGED')
    assert readiness()['reason']=='latest_failure'
