"""Public behavior fixes with isolated catalogs and truthful evidence."""
# ruff: noqa: F811 -- imported pytest fixtures.
import time
from types import SimpleNamespace

import httpx
from tests.test_fast_single_recommendation import catalog,ask  # noqa: F401


def test_pronoun_retains_selected_second_and_feedback_targets_its_id(catalog):
    store,_,client,add,now=catalog
    for name in ('Weather One','Weather Two','Weather Three'):add(name,report_at=now)
    first=ask(client,'weather forecast');token=first['visitor']['token'];items=first['data']['recommendations']
    assert len(items)>=2
    headers={'X-Visitor-Token':token}
    second=client.post('/chat',headers=headers,json={'message':'the second one'}).json()
    again=client.post('/chat',headers=headers,json={'message':'it'}).json()
    assert second['intent']==again['intent']=='details'
    assert again['data']['recommendations'][0]['id']==items[1]['id']
    response=client.post('/chat',headers=headers,json={'message':'worked 1','data':{'intent':'outcome','resource_id':items[1]['id'],'success':True,'feedback_reason':'matched_task'}}).json()
    assert response['data']['resource_id']==items[1]['id']
    assert any('matched_task' in (row['data'] or '') for row in store.query('SELECT data FROM agent_messages'))
    rejected=client.post('/chat',headers=headers,json={'message':'worked 1','data':{'intent':'outcome','resource_id':2147483647,'success':True}}).json()
    assert rejected['data']['status']=='invalid_request'


def test_rest_problem_cache_and_protocol_boundaries(catalog):
    _,_,client,_,_=catalog
    result=client.post('/api/workflows/run',json={'template_id':0})
    assert result.status_code==400 and result.headers['content-type']=='application/problem+json'
    assert result.json()['retryable'] is False and result.json()['type'].endswith('/http-400')
    first=client.get('/api/test/presets')
    assert first.headers['cache-control'].startswith('public, max-age=30')
    assert 'etag' in first.headers and 'ratelimit' in first.headers
    conditional=client.get('/api/test/presets',headers={'If-None-Match':first.headers['etag']})
    assert conditional.status_code==304 and conditional.content==b''
    assert 'content-length' not in conditional.headers
    private=client.get('/api/test/presets',headers={'Cookie':'__Host-ac_customer_session=fixture'})
    assert private.headers['cache-control']=='no-store'
    head=client.head('/llms.txt');get=client.get('/llms.txt')
    assert head.content==b'' and head.headers['etag']==get.headers['etag']
    rpc=client.post('/mcp',json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'search','arguments':{}}})
    assert rpc.headers['content-type'].startswith('application/json') and rpc.json()['error']['code']==-32602


def test_retention_reads_and_cleanup_exclude_old_messages_without_removing_outcomes(catalog):
    store,front,_,add,now=catalog
    v=front.book.create('rest','RetentionFixture/1','fixture-retention');rid=add('Weather')
    first=front.book.add_message(v,'agent','rest','expired')
    front.book.add_message(v,'agent','rest','current')
    front.book.record_outcome(v,rid,True)
    cutoff=time.time()-90*86400
    with store.tx() as db:db.execute('UPDATE agent_messages SET at=? WHERE id=?',(cutoff-10,first))
    assert [m['text'] for m in front.book.messages(v.id)]==['current']
    report=front.book.prune_conversations()
    assert report['messages']==1 and store.query('SELECT COUNT(*) FROM agent_outcomes')[0][0]==1
    assert store.query('SELECT id FROM agent_visitors WHERE id=?',(v.id,))


def test_public_status_uses_real_probe_observations(catalog):
    from agent_market.public_availability import AvailabilityMonitor,projection
    store,_,_,_,_=catalog
    assert projection(store)['availability']['availability_percent'] is None
    now=[time.time()];code=[200]
    transport=httpx.MockTransport(lambda req:httpx.Response(code[0],json={'service':'Agent Concierge'}))
    with httpx.Client(transport=transport) as http:
        front=SimpleNamespace(store=store,public_url='https://agentconcierge.biz')
        monitor=AvailabilityMonitor(front,http=http,clock=lambda:now[0])
        monitor.run();now[0]+=60;code[0]=503;monitor.run()
    value=projection(store,now[0])
    assert value['availability']['observation_count']==2 and value['availability']['availability_percent']==50
    assert value['status']=='degraded' and len(value['recent_incidents'])==1
    assert value['recent_incidents'][0]['resolved_at'] is None


def test_expired_recommendation_context_does_not_revive_when_a_visitor_returns(catalog):
    store,front,_,add,now=catalog
    visitor=front.book.create('rest','RetentionFixture/1','expired-context-fixture')
    rid=add('Weather')
    front.book.save_results(visitor,[{'id':rid,'task':'old task'}],1)
    front.book.save_last_tool(visitor,rid,'forecast')
    visitor.last_seen=now-91*86400
    with store.tx() as db:db.execute('UPDATE agent_visitors SET last_seen=? WHERE id=?',(visitor.last_seen,visitor.id))
    visitor.new=False
    front.book.touch(visitor,'rest','RetentionFixture/1','expired-context-fixture')
    assert front.book.last_results(visitor.id)==([],0)
    assert front.book.get_last_tool(visitor.id)==(None,None)


def test_explore_keeps_task_gates_independent_from_capability_registry(catalog,monkeypatch):
    from agent_market.concierge import hybrid_explore
    store,front,_,add,now=catalog
    rid=add('Weather Focus',report_at=now)
    resource=dict(store.query('SELECT * FROM resources WHERE id=?',(rid,))[0])
    monkeypatch.setattr(hybrid_explore,'candidates',lambda *args,**kwargs:[resource])
    # A provider candidate is not sufficient: it must actually advertise the task.
    value=hybrid_explore.explore(store,SimpleNamespace(),'translate a document','mcp',None,False,False,3)
    assert not value['items']
    symbols=hybrid_explore.explore(store,SimpleNamespace(),'???','mcp',None,False,False,3)
    assert not symbols['items']
    matching=hybrid_explore.explore(store,SimpleNamespace(),'weather forecast','mcp',None,False,False,3)
    assert matching['items'][0]['id']==rid


def test_natural_language_correction_never_changes_current_into_currency():
    from agent_market.concierge.explore_search import corrected_task
    assert corrected_task('Research current technology news with source links.') is None
    assert corrected_task('Find current gihtub issues')=='Find current github issues'


def test_cross_protocol_discovery_preserves_task_focus_before_protocol():
    from agent_market.concierge.protocols import merge_discovery_results
    bundle={'id':1,'kind':'a2a','name':'Intelligence Mesh','description':'A marketplace with many products.'}
    focused={'id':2,'kind':'mcp','name':'GitHub Issues and Pull Requests','description':'Search public GitHub issues by keywords.'}
    groups=[{'query':'Search GitHub issues','items':[bundle],'total':1},{'query':'Search GitHub issues','items':[focused],'total':1}]
    assert merge_discovery_results(groups,1)['items'][0]['id']==2
    a2a={**focused,'id':3,'kind':'a2a'}
    groups[0]['items']=[a2a,bundle];groups[0]['total']=2
    assert [item['id'] for item in merge_discovery_results(groups,3)['items']]==[3,2,1]
    for group in groups:group['query']=''
    assert [item['id'] for item in merge_discovery_results(groups,3)['items']]==[3,1,2]
