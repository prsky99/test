"""Adversarial adoption contracts on disposable data and in-process providers."""
import json
import time
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from agent_market.agent_access.storage import migrate,enqueue,transaction
from agent_market.agent_access.service import for_front
from agent_market.agent_access.tasks import NOTICE
from agent_market.capability_registry import Registry
from agent_market.concierge.front import Front,create_front_app
from tests.test_workflow_fallback import routing  # noqa: F401
from tests.test_fast_single_recommendation import catalog  # noqa: F401
from tests.test_task_updates_security import updates  # noqa: F401
from tests.test_customer_identity import customer  # noqa: F401


@pytest.fixture
def adoption(routing):
    rt,wf,ids,calls,modes,hooks,remote=routing
    proxy=rt.proxy
    front=Front(rt.store)
    front.proxy=proxy
    front.workflows.proxy=proxy
    migrate(rt.store)
    with rt.store.tx()as db:
        for index,rid in enumerate(ids):
            db.execute('UPDATE resources SET name=?,description=?,eval_grade=?,eval_score=?,last_ok_at=?,last_check_at=? WHERE id=?',
                ('Documentation library '+str(index),'Search documentation for any library or framework','A',95,time.time(),time.time(),rid))
    core=for_front(front)
    active={'value':True}
    class Identity:
        def _session(self,db,session,customer):
            if not active['value']or(session,customer)!=('fixture-session','fixture-customer'):raise ValueError('revoked')
            return {'id':session}
    core.tasks.identity_core=Identity()
    visitor=front.book.create('rest','SyntheticAdoptionFixture','synthetic-adoption')
    client=TestClient(create_front_app(front))
    yield core,visitor,ids,calls,modes,client,active
    front.book.close()


def prep(core,visitor,rid):
    return core.tasks.prepare(visitor.id,rid,'docs.search.v1',{'query':'documentation','language':'en','limit':2})


def grant(core,visitor,prepared):
    return core.tasks.authorize(visitor.id,prepared['preparation_id'],
        SimpleNamespace(session_ref='fixture-session',customer_id='fixture-customer'),
        {'authorized':True,'input_sharing':True,'notice':NOTICE})['grant']


def test_prepare_never_calls_provider_and_grant_is_independent(adoption):
    core,v,ids,calls,*_=adoption
    prepared=prep(core,v,ids[0]);assert not calls
    with pytest.raises(ValueError):core.tasks.execute(v.id,prepared['preparation_id'],'invalid','once')
    assert not calls
    issued=grant(core,v,prepared);assert not calls
    original=core.front.proxy.execute;observed=[]
    def capture(*args,**kwargs):
        value=original(*args,**kwargs);observed.append(value);return value
    core.front.proxy.execute=capture
    result=core.tasks.execute(v.id,prepared['preparation_id'],issued,'once')
    assert result['status']=='succeeded',(result,observed)
    assert len(calls)==1
    assert core.tasks.execute(v.id,prepared['preparation_id'],issued,'once')==result
    assert len(calls)==1


@pytest.mark.parametrize('failure',['other_owner','revoked_customer','expired','schema','kill','bad_input','reuse'])
def test_authority_and_contract_changes_never_dispatch(adoption,failure):
    core,v,ids,calls,modes,client,active=adoption
    prepared=prep(core,v,ids[0]);issued=grant(core,v,prepared)
    store=core.store if hasattr(core,'store')else core.front.store
    if failure=='other_owner':owner='other-owner'
    else:owner=v.id
    if failure=='revoked_customer':active['value']=False
    if failure=='expired':
        with store.tx()as db:db.execute('UPDATE adoption_preparations SET expires=0')
    if failure=='schema':
        with store.tx()as db:db.execute("UPDATE resources SET usage_full_tools='[]' WHERE id=?",(ids[0],))
    if failure=='kill':
        with store.tx()as db:db.execute('UPDATE execution_controls SET invoke_enabled=0')
    if failure=='bad_input':
        with pytest.raises(ValueError):core.tasks.prepare(v.id,ids[0],'docs.search.v1',{'query':'documentation','limit':999,'language':'en'})
        assert not calls;return
    if failure=='reuse':
        core.tasks.execute(v.id,prepared['preparation_id'],issued,'once');calls.clear()
    with pytest.raises(ValueError):core.tasks.execute(owner,prepared['preparation_id'],issued,'twice')
    assert not calls


def test_uncertain_execution_is_retained_without_replay(adoption):
    core,v,ids,calls,modes,*_=adoption
    prepared=prep(core,v,ids[0]);issued=grant(core,v,prepared)
    modes['primary.example']='unknown'
    first=core.tasks.execute(v.id,prepared['preparation_id'],issued,'once')
    assert first['status']=='unknown'
    assert core.tasks.execute(v.id,prepared['preparation_id'],issued,'once')==first
    assert len(calls)==1


def test_simultaneous_same_operation_does_not_duplicate_dispatch(adoption):
    core,v,ids,calls,*_=adoption
    prepared=prep(core,v,ids[0]);issued=grant(core,v,prepared)
    def run(_):
        try:return core.tasks.execute(v.id,prepared['preparation_id'],issued,'same')
        except ValueError:return {'status':'denied'}
    with ThreadPoolExecutor(max_workers=2)as pool:results=list(pool.map(run,range(2)))
    assert len(calls)==1
    assert {r['status']for r in results}<={'succeeded','prepared','dispatched','denied'}


def test_compact_mcp_transport_and_stable_five_tools(adoption):
    core,v,ids,calls,modes,client,*_=adoption
    def rpc(method,params=None,headers=None):return client.post('/mcp/compact',json={'jsonrpc':'2.0','id':1,'method':method,'params':params or{}},headers=headers or{})
    initial=rpc('initialize',{'protocolVersion':'2025-06-18'})
    assert initial.status_code==200
    headers={'Mcp-Session-Id':initial.headers['mcp-session-id']}
    listed=rpc('tools/list',headers=headers).json()['result']['tools']
    assert [t['name']for t in listed]==['discover','describe','execute','resume','report']
    response=rpc('tools/call',{'name':'discover','arguments':{'task':'public documentation search','protocol':'mcp'}},headers)
    value=response.json()['result']['structuredContent']
    assert value['status']=='matched',value
    assert len(value['items'])<=3 and len(json.dumps(value).encode())<=8192
    assert not calls and not any(x in response.text for x in ('vt_','fixture-customer','primary.example'))
    assert rpc('tools/list',headers=headers).json()['result']['tools']==listed
    assert response.headers.get('ratelimit-policy')
    # Authorization is unavailable without a real customer session, even with a visitor token.
    deny=client.post('/api/agent/v1/preparations/ap_'+'0'*32+'/authorize',headers={'X-Visitor-Token':v.token},json={'authorized':True})
    assert deny.status_code in (401,403,404)


def test_feed_uses_committed_publication_and_current_state(adoption):
    core,v,ids,calls,modes,client,*_=adoption
    resource=core.front.store.resource(ids[0]);version=Registry(core.front.store).current(resource)
    Registry(core.front.store).record(version,scope='execution',outcome='succeeded',started=time.time()-1,finished=time.time()-1)
    assert core.events.publish()==1
    first=client.get('/api/feed/verified.json?protocol=mcp')
    assert first.status_code==200 and first.json()['items'][0]['_agentconcierge']['currently_verified']
    # 11-13: the feed is now a shared public read, so its ETag comes back weak (W/) like the other public reads;
    # a reader sends back the tag it got.
    assert first.headers['etag'].startswith('W/"') and 'max-age=60' in first.headers['cache-control']
    assert client.get('/api/feed/verified.json?protocol=mcp',headers={'If-None-Match':first.headers['etag']}).status_code==304
    with core.front.store.tx()as db:db.execute('UPDATE resources SET active=0 WHERE id=?',(ids[0],))
    second=client.get('/api/feed/verified.json?protocol=mcp',headers={'If-None-Match':first.headers['etag']})
    assert second.status_code==200
    assert not second.json()['items'][0]['_agentconcierge']['currently_verified']
    assert not calls


def test_uncommitted_low_source_id_is_not_lost_and_duplicate_ignored(adoption):
    core,v,ids,*_=adoption
    store=core.front.store
    with transaction(store)as db:
        enqueue(store,db,ids[1],'execution_changed',evidence='later')
    core.events.publish()
    with transaction(store)as db:
        enqueue(store,db,ids[0],'execution_changed',evidence='earlier')
    core.events.publish()
    result=core.events.feed('mcp',limit=1);cursor=result['_next_cursor']
    next_page=core.events.feed('mcp',cursor,1)
    assert result['items'][0]['id']!=next_page['items'][0]['id']
    with pytest.raises(ValueError):core.events.feed('mcp',cursor+'x',1)
    assert core.events.publish()==0


def test_legacy_openapi_has_unique_operation_ids(catalog):
    _,_,client,*_=catalog
    value=client.get('/openapi.json').json()
    ids=[operation['operationId']for path in value['paths'].values()for operation in path.values()if isinstance(operation,dict)and'operationId'in operation]
    assert len(ids)==len(set(ids))
    assert client.head('/api/overview').status_code==200


def test_schema_digest_saves_bytes_without_changing_current_evidence(adoption):
    core,v,ids,calls,*_=adoption
    first=core.catalog.discover({'task':'public documentation search','protocol':'mcp'})
    digest=first['selected_contract']['schema_digest']
    second=core.catalog.discover({'task':'public documentation search','protocol':'mcp','known_schema_digests':[digest]})
    assert second['schema_cached']and'tools_schema'not in second['selected_contract']
    assert second['items']==first['items']and not calls
    assert len(json.dumps(second).encode())<len(json.dumps(first).encode())


def test_preparation_and_grant_tampering_is_refused(adoption):
    core,v,ids,calls,*_=adoption
    prepared=prep(core,v,ids[0]);issued=grant(core,v,prepared)
    with core.front.store.tx()as db:db.execute('UPDATE adoption_grants SET expires=expires+1')
    with pytest.raises(ValueError):core.tasks.execute(v.id,prepared['preparation_id'],issued,'tampered')
    with core.front.store.tx()as db:db.execute('UPDATE adoption_preparations SET resource_id=?',(ids[1],))
    with pytest.raises(ValueError):core.tasks.preparation(v.id,prepared['preparation_id'])
    assert not calls


@pytest.mark.parametrize('arguments',[
    {'task':'documentation','protocol':'invalid'},
    {'task':'documentation','known_schema_digests':['a']},
    {'task':'documentation','known_schema_digests':['a'*64]*17},
    {'task':'documentation','unexpected':'SELECT * FROM private'},
    {'task':'documentation','prepare':1},
    {'task':'documentation','arguments':None},
])
def test_malformed_discovery_has_no_provider_effect(adoption,arguments):
    core,v,ids,calls,modes,client,*_=adoption
    response=client.post('/mcp/compact',headers={'Mcp-Session-Id':v.token},json={
        'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'discover','arguments':arguments}})
    assert response.json()['result']['isError']is True and not calls


def test_page_is_english_safe_and_canonical(adoption):
    core,v,ids,calls,modes,client,*_=adoption
    page=client.get('/agents/category/dev_tools')
    assert page.status_code==200 and'<html lang="en">'in page.text
    assert 'https://agentconcierge.biz/agents/category/dev_tools'in page.text
    assert 'primary.example'not in page.text and 'POLICY_DENIED'not in page.text
    assert client.get('/agents/category/absent').status_code==404
    assert not calls


def test_batch_current_state_reads_do_not_scale_per_item(adoption):
    core,v,ids,*_=adoption
    from agent_market.agent_access.projection import current_states
    original=core.front.store.query;seen=[]
    def query(sql,*args,**kwargs):seen.append(sql);return original(sql,*args,**kwargs)
    core.front.store.query=query
    resources,states=current_states(core.front.store,ids)
    assert len(resources)==3 and all(v['verified']for v in states.values())
    assert len(seen)==3


def test_single_flight_shares_build_but_not_foreign_keys():
    from agent_market.agent_access.cache import BoundedCache
    cache=BoundedCache();count=[]
    def build():count.append(True);time.sleep(.03);return 'immutable-schema'
    with ThreadPoolExecutor(max_workers=4)as pool:values=list(pool.map(lambda _:cache.get('same',build),range(4)))
    assert values==['immutable-schema']*4 and len(count)==1
    cache.get('other-scope',build);assert len(count)==2


def test_dependency_watch_requires_existing_scope_and_dedupes(updates):
    store,front,client,add,headers,courier,data,owner=updates
    migrate(store);core=for_front(front)
    watch=client.post('/api/task-updates',headers=headers,json=data).json()['id']
    rid=store.query('SELECT id FROM resources')[0][0]
    core.events.dependency(owner,watch,rid,authorized=True,notice='agent-dependency-watch-v1')
    with transaction(store)as db:enqueue(store,db,rid,'fixture',evidence='synthetic')
    core.events.publish()
    assert core.events.notify()==1 and core.events.notify()==0
    event=dict(store.query("SELECT * FROM agent_task_events WHERE evidence LIKE 'dependency:%'")[0])
    row=front.updates._get(watch,owner);payload=json.loads(event['payload'])
    assert core.events.delivery_valid(row,event,payload)
    assert not core.events.delivery_valid(row,event,{**payload,'resource_id':rid+1})
    front.updates.action(owner,watch,'stop')
    assert core.events.notify()==0
    with pytest.raises(ValueError):core.events.dependency(owner,watch,rid)


def test_python_client_never_retries_execution_posts():
    import httpx
    from agent_market.agent_access.client import DiscoveryClient,ClientError
    requests=[];sleeps=[]
    def transport(request):
        requests.append(request.method)
        return httpx.Response(429,headers={'Retry-After':'0'})
    client=DiscoveryClient(http=httpx.Client(base_url='https://agentconcierge.biz',transport=httpx.MockTransport(transport)),sleep=sleeps.append)
    client._session='synthetic-session'
    with pytest.raises(ClientError):client.feed()
    assert requests==['GET']*3 and len(sleeps)==2
    requests.clear()
    with pytest.raises(ClientError):client.execute('ap_'+'0'*32,'axg_'+'0'*32,'once')
    assert requests==['POST']and'synthetic-session'not in repr(client)


def test_paginated_feed_etag_and_cursor_are_stable_within_validity(adoption,monkeypatch):
    core,v,ids,*_=adoption
    now=time.time();base=int(now//3600)*3600+120
    with transaction(core.front.store)as db:
        for rid in ids:enqueue(core.front.store,db,rid,'fixture',evidence='page')
    core.events.publish()
    clock={'value':base}
    monkeypatch.setattr('agent_market.agent_access.events.time',SimpleNamespace(time=lambda:clock['value']))
    first=core.events.feed('mcp',limit=1)
    clock['value']=base+61
    second=core.events.feed('mcp',limit=1)
    assert first==second and first['_next_cursor']
    assert core.events.feed('mcp',first['_next_cursor'],1)['items']
    clock['value']=base+3601
    with pytest.raises(ValueError,match='INVALID_CURSOR'):core.events.feed('mcp',first['_next_cursor'],1)


@pytest.mark.parametrize('channel',['webhook','a2a'])
@pytest.mark.parametrize('accepted',[True,False])
def test_verified_dependency_delivery_rechecks_scope_and_never_replays_unknown(updates,channel,accepted):
    store,front,client,add,headers,courier,data,owner=updates
    migrate(store);core=for_front(front)
    watch=client.post('/api/task-updates',headers=headers,json={**data,'channel':channel,'url':'https://inbox.example/updates'}).json()['id']
    assert front.updates._get(watch)['state']!='active'
    with pytest.raises(ValueError):core.events.dependency(owner,watch,1,authorized=True,notice='agent-dependency-watch-v1')
    code=courier.challenges[-1]['verification_code']
    response=client.post(f'/api/task-updates/{watch}/action',headers=headers,json={'action':'verify','code':code})
    assert response.status_code==200 and response.json()['state']=='active'
    rid=store.query('SELECT id FROM resources')[0][0]
    core.events.dependency(owner,watch,rid,authorized=True,notice='agent-dependency-watch-v1')
    with transaction(store)as db:enqueue(store,db,rid,'fixture',evidence='delivery')
    core.events.publish();assert core.events.notify()==1
    event=dict(store.query("SELECT * FROM agent_task_events WHERE evidence LIKE 'dependency:%'")[0])
    courier.result=(accepted,None if accepted else'timeout')
    front.updates._attempt(event)
    assert len(courier.events)==1 and courier.events[0][0]==channel
    raw=store.query('SELECT * FROM agent_task_events WHERE id=?',(event['id'],))[0]
    assert raw['status']==('sent'if accepted else'unknown')
    front.updates._attempt(event)
    assert len(courier.events)==1


def test_status_cannot_read_after_customer_session_revocation(adoption):
    core,v,ids,calls,modes,client,active=adoption
    prepared=prep(core,v,ids[0]);token=grant(core,v,prepared)
    result=core.tasks.execute(v.id,prepared['preparation_id'],token,'status-test')
    assert result['status']=='succeeded'
    active['value']=False
    with pytest.raises(ValueError):core.tasks.operation(v.id,result['operation_id'])
    assert len(calls)==1


def test_protocol_transport_and_oversized_requests_do_not_dispatch(adoption):
    core,v,ids,calls,modes,client,*_=adoption
    rpc={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'resume','arguments':{}}}
    assert client.post('/mcp/compact',headers={'Origin':'https://evil.example','Mcp-Session-Id':v.token},json=rpc).status_code==403
    assert client.post('/mcp/compact?visitor_token='+v.token,json=rpc).status_code==401
    assert client.post('/mcp/compact',json={**rpc,'padding':'a'*16384}).status_code==413
    assert not calls


def test_real_customer_csrf_and_revocation_guard(adoption,customer):
    from fastapi import FastAPI
    from agent_market.customer_identity import CustomerIdentity
    from agent_market.customer_identity_service import COOKIE
    from agent_market.agent_access.service import router_for
    from tests.test_customer_identity import login
    core,v,ids,calls,*_=adoption
    identity=CustomerIdentity(core.front.store,b'synthetic-customer-key-32bytes!!!',customer.config,customer.http)
    auth=login(SimpleNamespace(core=identity,state=customer.state))
    core.identity=identity;core.tasks.identity_core=identity
    app=FastAPI();app.include_router(router_for(core.front,customer_enabled=True))
    client=TestClient(app,base_url='https://agentconcierge.biz')
    token=auth['session_token'];client.cookies.set(COOKIE,token)
    prepared=prep(core,v,ids[0]);url='/api/agent/v1/preparations/'+prepared['preparation_id']+'/authorize'
    headers={'Origin':'https://agentconcierge.biz','X-Visitor-Token':v.token,'X-Customer-CSRF':identity.csrf(token)}
    body={'authorized':True,'input_sharing':True,'notice':NOTICE}
    assert client.post(url,headers={k:val for k,val in headers.items()if k!='X-Customer-CSRF'},json=body).status_code==403
    assert client.post(url,headers={**headers,'Origin':'https://evil.example'},json=body).status_code==403
    assert client.post(url,headers=headers,json={**body,'authorized':1}).status_code==403
    response=client.post(url,headers=headers,json=body)
    assert response.status_code==200 and response.headers['cache-control']=='private, no-store'
    issued=response.json()['grant']
    executed=client.post('/mcp/compact',headers={'Mcp-Session-Id':v.token},json={
        'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'execute','arguments':{
            'action':'run','preparation_id':prepared['preparation_id'],'grant':issued,'idempotency_key':'actual-session'}}})
    assert executed.json()['result']['structuredContent']['status']=='succeeded'
    assert client.request('DELETE','/api/agent/v1/grants',headers=headers,json={'grant':issued}).status_code==200
    with pytest.raises(ValueError):core.tasks.execute(v.id,prepared['preparation_id'],issued,'revoked-actual')
    assert len(calls)==1


def test_watch_event_scope_and_schema_changes_are_distinct(updates):
    store,front,client,add,headers,courier,data,owner=updates
    migrate(store);core=for_front(front)
    watch=client.post('/api/task-updates',headers=headers,json=data).json()['id']
    rid=store.query('SELECT id FROM resources')[0][0]
    registered=core.events.dependency(owner,watch,rid,authorized=True,notice='agent-dependency-watch-v1',event_types=['schema_changed'])
    assert registered['version_id'].startswith('cv_')
    with transaction(store)as db:enqueue(store,db,rid,'fixture',evidence='initial')
    core.events.publish();assert core.events.notify()==0
    with store.tx()as db:
        db.execute('UPDATE resources SET usage_full_tools=? WHERE id=?',(json.dumps([{'name':'new_tool','inputSchema':{'type':'object'}}]),rid))
        enqueue(store,db,rid,'catalog_changed',evidence='schema')
    assert core.events.publish()==1 and core.events.notify()==1
    event=dict(store.query("SELECT * FROM agent_task_events WHERE evidence LIKE 'dependency:%'")[0])
    assert json.loads(event['payload'])['event_type']=='schema_changed'
    with pytest.raises(ValueError):core.events.dependency(owner,watch,rid,authorized=True,notice='agent-dependency-watch-v1',event_types=['verified'])


def test_failure_followed_by_success_before_publication_is_not_collapsed(adoption):
    core,v,ids,*_=adoption
    store=core.front.store;registry=Registry(store);version=registry.current(store.resource(ids[0]))
    with transaction(store)as db:enqueue(store,db,ids[0],'fixture',evidence='baseline')
    core.events.publish()
    now=time.time()
    registry.record(version,scope='execution',outcome='failed',started=now,finished=now,code='UPSTREAM_TIMEOUT')
    registry.record(version,scope='execution',outcome='succeeded',started=now,finished=time.time())
    core.events.publish()
    items=[item['_agentconcierge']for item in core.events.feed('mcp')['items']]
    assert [item['recorded_outcome']for item in items if'recorded_outcome'in item]==['failed','succeeded']
    assert all(item['currently_verified']for item in items)


def test_large_schema_is_deferred_with_a_bounded_wire_response(adoption):
    core,v,ids,calls,modes,client,*_=adoption
    from agent_market.collector import usage
    store=core.front.store;rid=ids[0]
    tools=json.loads(store.resource(rid)['usage_full_tools'])
    tools[0]['inputSchema']['description']='Documentation field. '*600
    store.record_usage(rid,usage.compact_tools(tools),usage.tools_hash(usage.compact_tools(tools)),{},None,None,full_tools=tools)
    version=Registry(store).current(store.resource(rid));now=time.time()
    Registry(store).record(version,scope='execution',outcome='succeeded',started=now,finished=now)
    # Isolate response framing from the existing ranker: this selected agent has
    # genuine current fixture evidence and is checked again by the projection.
    core.front.rec.search=lambda *args,**kwargs:[{'id':rid,'name':'Documentation library','kind':'mcp',
        'url':'https://agentconcierge.biz/api/gateway/mcp/'+str(rid),'grade':'A',
        'capability_contract':{'connection_version_id':version['id'],'verified_at':now,'expires_at':now+86400}}]
    response=client.post('/mcp/compact',headers={'Mcp-Session-Id':v.token},json={'jsonrpc':'2.0','id':'i'*128,
        'method':'tools/call','params':{'name':'discover','arguments':{'task':'documentation','protocol':'mcp'}}})
    result=response.json()['result']['structuredContent']
    assert result['schema_deferred']and'tools_schema'not in result['selected_contract']
    assert len(response.content)<=8192 and not calls
    assert core.catalog.describe(rid)['tools_schema']


def test_transient_health_failure_and_recovery_are_retained(adoption):
    core,v,ids,*_=adoption
    store=core.front.store
    with transaction(store)as db:enqueue(store,db,ids[0],'fixture',evidence='baseline')
    core.events.publish()
    store.record_health(ids[0],'fail',503,1,None,time.time()+21600)
    store.record_health(ids[0],'healthy',200,1,None,time.time()+21600)
    core.events.publish()
    observed=[item['_agentconcierge'].get('recorded_health')for item in core.events.feed('mcp')['items']]
    assert [status for status in observed if status]==['failing','healthy']


def test_small_openapi_profile_reuses_routes_and_closed_tool_inputs(adoption):
    core,v,ids,calls,modes,client,*_=adoption
    from agent_market.agent_access.contracts import tools
    response=client.get('/api/agent/v1/openapi.json');schema=response.json()
    assert response.status_code==200 and schema['x-agentconcierge-profile']=='agent-discovery-v1'
    assert set(schema['paths'])=={'/api/agent/v1/discover','/api/agent/v1/resume','/api/agent/v1/report','/api/agents/{rid}',
        '/api/feed/verified.json','/api/agent/v1/entry','/api/agent/v1/openapi.json','/api/agent/v1/badge/{resource_id}.svg',
        '/api/agent/v1/check'}  # 11-11 check before you call
    assert not any(key in response.text for key in ('/admin','/api/customer','workspace_id'))
    actual=schema['paths']['/api/agent/v1/discover']['post']['requestBody']['content']['application/json']['schema']
    assert actual==tools()[0]['inputSchema']and actual['additionalProperties']is False
    assert client.get('/api/agent/v1/openapi.json',headers={'If-None-Match':response.headers['etag']}).status_code==304
    assert not calls


def test_client_bounded_jitter_and_cancellation_without_post_replay():
    import httpx
    from agent_market.agent_access.client import DiscoveryClient,ClientError
    sleeps=[];calls=[];stopped={'value':False}
    def transport(request):calls.append(request);return httpx.Response(503)
    client=DiscoveryClient(http=httpx.Client(base_url='https://agentconcierge.biz',transport=httpx.MockTransport(transport)),
        sleep=sleeps.append,jitter=lambda:.5,cancelled=lambda:stopped['value'])
    with pytest.raises(ClientError,match='HTTP_503'):client.feed()
    assert sleeps==[1.125,2.125]and len(calls)==3
    stopped['value']=True
    with pytest.raises(ClientError,match='CANCELLED'):client.feed()
    assert len(calls)==3
