"""Functional and adversarial HTTP regressions using disposable DBs and controlled providers."""
import asyncio
import base64
import json
import threading
import time
from unittest.mock import Mock

import httpx
import pytest

from agent_market.collector import usage
from agent_market.concierge.connections import gateway_agent_url, is_gateway_url, project
from agent_market.concierge.execution_policy import ExecutionDenied, validate_arguments
from agent_market.concierge.http_security import bounded_client
from agent_market.concierge.proxy import McpProxy
from tests.test_fast_single_recommendation import catalog
from tests.test_mcp_proxy import MockRemoteMcp, WEATHER_TOOL, DESTRUCTIVE_TOOL
from tests.test_single_recommendation_security_audit import request as discover

SOURCE='https://news.example/articles/latest'
DOC='https://docs.example/research'


@pytest.fixture
def managed(catalog,monkeypatch):
    store,front,client,add,now=catalog
    rid=add('Managed Weather',report_at=now-2)
    tools=[WEATHER_TOOL]
    store.record_usage(rid,tools=usage.compact_tools(tools),digest=usage.tools_hash(usage.compact_tools(tools)),
                       guide={'tools':tools},changes=None,trial={'ok':True})
    calls=[]
    remote=MockRemoteMcp(tools,call_result={'content':[{'type':'text','text':'Current source: '+SOURCE+'; docs '+DOC}],
                                         'structuredContent':{'url':SOURCE}})
    def provider(req):
        calls.append(req)
        return remote.handle_request(req)
    front.proxy=McpProxy(store,allow_private=True,http=httpx.Client(transport=httpx.MockTransport(provider)))
    # Every test targets an independent policy; rate denial is covered explicitly below.
    front.security.allow_probe=lambda *a,**kw:True
    yield store,front,client,add,rid,calls,remote


def rpc(client,path,method,params=None,**kwargs):
    return client.post(path,json={'jsonrpc':'2.0','id':7,'method':method,'params':params or {}},**kwargs)


def test_advertised_mcp_connection_executes_actual_registered_tool(managed):
    store,front,client,_,rid,calls,_=managed
    path=f'/api/gateway/mcp/{rid}'
    original=store.resource(rid)['url']
    assert client.get(path).status_code==405
    init=rpc(client,path,'initialize').json()['result']
    assert init['capabilities']=={'tools':{'listChanged':False}}
    assert rpc(client,path,'tools/list').json()['result']['tools'][0]['name']=='get_weather'
    assert client.post(path,json={'jsonrpc':'2.0','method':'notifications/initialized'}).status_code==202
    assert rpc(client,path,'ping').json()['result']=={}
    result=rpc(client,path,'tools/call',{'name':'get_weather','arguments':{'city':'Tokyo'}})
    assert result.status_code==200 and SOURCE in result.text and DOC in result.text
    assert original not in result.text
    assert sum(json.loads(r.content).get('method')=='tools/call' for r in calls)==1
    assert store.resource(rid)['url']==original
    for method in ('resources/read','tools/cancel','sampling/createMessage'):
        assert rpc(client,path,method).json()['error']['code']==-32601


@pytest.mark.parametrize('channel',['rest','a2a','mcp'])
def test_raw_discovery_json_and_text_hide_bindings_preserve_schema(managed,channel):
    store,_,client,_,rid,_,_=managed
    original=store.resource(rid)['url']
    response,items=discover(client,channel,task='MCP weather')
    assert original not in response.text
    assert items[0]['usage_endpoint']==gateway_agent_url(rid,'mcp')
    assert items[0]['tools_schema'][0]['name']=='get_weather'
    assert store.resource(rid)['url']==original


@pytest.mark.parametrize('entry',['testbench','gateway','legacy'])
@pytest.mark.parametrize('denial',['unknown-tool','destructive','inactive','quarantined','security-review','bad-type','missing-required','remote-ref','price'])
def test_shared_admission_denies_before_provider_contact(managed,entry,denial):
    store,front,client,_,rid,calls,remote=managed
    tool='get_weather';args={'city':'Tokyo'}
    if denial=='unknown-tool':tool='missing'
    if denial=='destructive':
        remote.tools=[DESTRUCTIVE_TOOL]
        tool='delete_database';args={}
        store.record_usage(rid,tools=usage.compact_tools(remote.tools),digest=usage.tools_hash(usage.compact_tools(remote.tools)),guide={},changes=None,trial=None)
    if denial in ('inactive','quarantined','security-review','price'):
        column,value={'inactive':('active',0),'quarantined':('health_status','quarantined'),
                      'security-review':('eval_security','review'),'price':('price_usdc',10)}[denial]
        with store.tx() as db:db.execute(f'UPDATE resources SET {column}=? WHERE id=?',(value,rid))
    if denial=='bad-type':args={'city':3}
    if denial=='missing-required':args={}
    if denial=='remote-ref':
        tools=[{**WEATHER_TOOL,'inputSchema':{'$ref':'https://attacker.example/schema'}}]
        with store.tx() as db:db.execute('UPDATE resources SET usage_tools=? WHERE id=?',(json.dumps(tools),rid))
    if entry=='testbench':response=client.post('/api/test/execute',json={'resource_id':rid,'tool':tool,'arguments':args})
    elif entry=='gateway':response=rpc(client,f'/api/gateway/mcp/{rid}','tools/call',{'name':tool,'arguments':args})
    else:response=rpc(client,'/mcp','tools/call',{'name':'call','arguments':{'resource_id':rid,'tool':tool,'arguments':args}})
    if entry=='gateway' and denial in ('quarantined','security-review'):
        assert response.status_code==403
        assert response.json()['error_code']=='POLICY_DENIED'
    else:
        assert response.status_code in (200,400)
    assert not calls
    assert 'Traceback' not in response.text
    if response.status_code==200:
        obj=response.json()
        assert 'error' in obj or obj['result']['structuredContent'].get('ok') is False


def test_schema_change_is_quarantined_without_tool_call(managed):
    store,_,client,_,rid,calls,remote=managed
    remote.tools=[{**WEATHER_TOOL,'description':'Changed remote capability'}]
    response=client.post('/api/test/execute',json={'resource_id':rid,'tool':'get_weather','arguments':{'city':'Tokyo'}})
    assert response.json()['execution_succeeded'] is False
    assert not any(json.loads(r.content).get('method')=='tools/call' for r in calls)
    assert store.resource(rid)['health_status']=='quarantined'


def test_live_full_schema_is_validated_after_hash_check(managed):
    store,_,client,_,rid,calls,remote=managed
    # Compact hashes omit maxLength. Full live schemas must still enforce it.
    remote.tools=[{**WEATHER_TOOL,'inputSchema':{'type':'object','properties':{'city':{'type':'string','maxLength':3}},'required':['city']}}]
    response=rpc(client,f'/api/gateway/mcp/{rid}','tools/call',{'name':'get_weather','arguments':{'city':'Tokyo'}})
    assert 'error' in response.json()
    assert not any(json.loads(r.content).get('method')=='tools/call' for r in calls)


def test_testbench_wire_is_actual_browser_envelope_and_sources_survive(managed):
    store,_,client,_,rid,calls,_=managed
    payload={'resource_id':rid,'tool':'get_weather','arguments':{'city':'Tokyo'},'message':'','timeout_seconds':5}
    response=client.post('/api/test/execute',json=payload)
    result=response.json()
    assert result['ok'] is result['execution_succeeded'] is True
    assert result['transport_ok'] is result['protocol_valid'] is True
    assert result['request_wire']['path']=='/api/test/execute'
    assert result['request_wire']['url']=='https://agentconcierge.biz/api/test/execute'
    assert result['request_wire']['body']==payload
    assert result['request_wire']['scope']=='client-to-gateway'
    assert SOURCE in result['output'] and DOC in result['output']
    assert store.resource(rid)['url'] not in response.text


@pytest.mark.parametrize('rid',[-1,-2,-3,-4])
def test_demos_cannot_claim_live_success_or_executable_binding(managed,rid):
    _,_,client,_,_,calls,_=managed
    agent=client.get(f'/api/agents/{rid}').json()['agent']
    assert agent['simulated'] and not agent['connection_available'] and not agent['url']
    assert agent['eval_grade'] is agent['last_trial'] is None
    result=client.post('/api/test/execute',json={'resource_id':rid}).json()
    assert result['simulated'] and result['task_status']=='simulation'
    assert result['ok'] is result['execution_succeeded'] is result['transport_ok'] is False
    assert result['status_code'] is None and 'No provider' in result['output']
    assert result['request_wire']['body']=={'resource_id':rid} and not calls


def test_detail_is_allowlisted_and_citations_are_not_rewritten(managed):
    store,_,client,_,rid,_,_=managed
    raw=store.resource(rid)['url']
    with store.tx() as db:
        db.execute('UPDATE resources SET details=?,auth_info=?,description=? WHERE id=?',
                   (json.dumps({'deployment_path':'/private/service','model':'private-model','endpoint':raw}),
                    json.dumps({'secret':'never-publish'}),'Endpoint '+raw+'; read '+DOC,rid))
    from tests.report_fixtures import legacy_report_fixture
    legacy_report_fixture(store,{'resource_id':rid,'title':'Source report','slug':'managed-source','kind':'mcp',
        'agent_url':raw,'is_success':1,'created_at':time.time(),'summary':'Read '+SOURCE,
        'content_md':'Sources '+DOC+'\nInvocation '+raw,'output_wire':json.dumps({'url':SOURCE,'endpoint':raw})})
    response=client.get(f'/api/agents/{rid}')
    data=response.json()['agent']
    assert 'details' not in data and 'auth_info' not in data
    for value in (raw,'/private/service','private-model','never-publish'):assert value not in response.text
    assert SOURCE in response.text and DOC in response.text
    assert data['test_report']['agent_url']==gateway_agent_url(rid,'mcp')


@pytest.mark.parametrize('value',[None,-1,0,True,'01',2**31])
def test_missing_or_demo_identity_has_no_fabricated_connection(value):
    assert gateway_agent_url(value,'mcp')==''


@pytest.mark.parametrize('url',['https://agentconcierge.biz.evil.example/mcp','https://agentconcierge.biz@evil.example/mcp',
 'https://evil@agentconcierge.biz/mcp','https://agentconcierge.biz:444/mcp','http://agentconcierge.biz/mcp'])
def test_gateway_origin_comparison_rejects_prefix_lookalikes(url):
    assert not is_gateway_url(url)


def setup_a2a(managed,state,*,mismatch=False):
    store,front,client,add,_,calls,_=managed
    rid=add('Managed A2A',kind='a2a')
    def resolve(*args,**kwargs):return {'url':store.resource(rid)['url'],'v1':False}
    def send(method,url,limit,**kwargs):
        calls.append(kwargs)
        message={'kind':'message','parts':[{'kind':'text','text':'Answer '+SOURCE}]}
        task={'kind':'task','id':'upstream-private-task','status':{'state':state},'artifacts':[{'parts':message['parts']}]}
        result=message if state=='message' else task
        return 200,json.dumps({'jsonrpc':'2.0','id':'wrong' if mismatch else kwargs['json']['id'],'result':result}).encode()
    front.courier.resolve=resolve;front.courier._request=send
    return rid


@pytest.mark.parametrize('state,success',[('message',True),('completed',True),('working',False),('failed',False),('submitted',False),('unknown',False)])
def test_a2a_nested_task_state_is_truthful(managed,state,success):
    _,_,client,_,_,_,_=managed
    rid=setup_a2a(managed,state)
    result=client.post('/api/test/execute',json={'resource_id':rid,'message':'Summarize weather research.'}).json()
    assert result['execution_succeeded'] is result['ok'] is success
    assert result['task_status']==('completed' if success else state)
    assert 'upstream-private-task' not in json.dumps(result)
    path=f'/api/gateway/a2a/{rid}'
    assert client.get(path).json()['capabilities']['streaming'] is False
    direct=rpc(client,path,'message/send',{'message':{'parts':[{'kind':'text','text':'Summarize weather research.'}]}}).json()
    assert ('result' in direct) is success
    assert 'upstream-private-task' not in json.dumps(direct)


def test_a2a_rejects_mismatched_response_id(managed):
    rid=setup_a2a(managed,'completed',mismatch=True)
    response=rpc(managed[2],f'/api/gateway/a2a/{rid}','message/send',{'message':{'parts':[{'text':'Explain the weather.'}]}})
    assert 'error' in response.json()


@pytest.mark.parametrize('message',['Delete the account','Transfer all funds','Email person@example.test','Publish a message'])
def test_a2a_informational_profile_refuses_actions_before_dispatch(managed,message):
    rid=setup_a2a(managed,'message')
    response=managed[2].post('/api/test/execute',json={'resource_id':rid,'message':message})
    assert response.status_code==400 and not managed[5]


@pytest.mark.parametrize('status,version,valid',[(402,None,False),(402,1,True),(402,2,True),(200,None,True),(500,None,False)])
def test_x402_probe_never_confuses_transport_challenge_and_execution(managed,monkeypatch,status,version,valid):
    store,front,client,add,_,calls,_=managed
    rid=add('Managed x402',kind='x402',price=100)
    body={'x402Version':version,'accepts':[{'scheme':'exact','network':'eip155:8453','asset':'0xasset','payTo':'0xrecipient',
                                          'amount':'100','maxAmountRequired':'100','maxTimeoutSeconds':60,
                                          'resource':store.resource(rid)['url'],'description':'Protected response'}]} if version else {'message':'response '+SOURCE}
    if version==2:body['resource']={'url':store.resource(rid)['url']}
    if version==1:body['error']='Authorization required'
    def provider(req):
        calls.append(req)
        assert req.method=='GET'
        assert not any(k in req.headers for k in ('authorization','cookie','payment-signature','x-payment'))
        return httpx.Response(status,json=body)
    monkeypatch.setattr('agent_market.concierge.managed_gateway.bounded_client',lambda **kw:bounded_client(httpx.Client(transport=httpx.MockTransport(provider)),limit=65536))
    result=client.post('/api/test/execute',json={'resource_id':rid}).json()
    assert result['protocol_valid'] is valid
    assert result['execution_succeeded'] is (status==200)
    direct=client.get(f'/api/gateway/x402/{rid}',headers={'Authorization':'Bearer browser-secret','Cookie':'secret=cookie'})
    assert direct.status_code==status
    if version==2:assert json.loads(base64.b64decode(direct.headers['payment-required']))['x402Version']==2
    assert len(calls)==2
    assert client.post(f'/api/gateway/x402/{rid}',json={'action':'execute','payment':{}}).status_code==400
    assert len(calls)==2


@pytest.mark.parametrize('url',['http://127.0.0.1/admin','http://169.254.169.254/latest/meta-data/',
 'https://name:secret@provider.example/mcp','http://[::1]/rpc','https://service.internal/rpc'])
def test_private_and_credentialed_bindings_never_dispatch(managed,url):
    store,_,client,_,rid,calls,_=managed
    with store.tx() as db:db.execute('UPDATE resources SET url=? WHERE id=?',(url,rid))
    result=client.post('/api/test/execute',json={'resource_id':rid,'tool':'get_weather','arguments':{'city':'Tokyo'}})
    assert result.status_code==400 and not calls
    assert url not in result.text


def test_gateway_rate_limit_and_request_boundaries(managed):
    _,front,client,_,rid,calls,_=managed
    path=f'/api/gateway/mcp/{rid}'
    front.security.allow_probe=lambda *a,**kw:False
    # 11-11 user decision: connection calls are not counted against the execution limit.
    assert rpc(client,path,'ping').status_code==200 and client.get(path).status_code==405
    refused=rpc(client,path,'tools/call',{'name':'get_weather','arguments':{'city':'Tokyo'}})
    assert refused.status_code==429 and refused.headers['retry-after']=='60' and not calls
    assert 'initialize, tools/list and ping are not counted' in refused.text
    front.security.allow_probe=lambda *a,**kw:True
    allow_feature=front.security.allow_feature
    front.security.allow_feature=lambda ip,feature,base_limit:feature!='gateway_connect'
    assert rpc(client,path,'ping').status_code==429 and client.get(path).status_code==429
    front.security.allow_feature=allow_feature
    for body in ('[]','null','{"jsonrpc":"2.0","id":true,"method":"tools/call"}'):
        response=client.post(path,content=body,headers={'Content-Type':'application/json'})
        assert response.status_code==400 or 'error' in response.json()
    assert client.post(path,content='x'*70000).status_code==413
    assert not calls


def test_bounded_execution_slots_are_retained_until_worker_finishes(managed,monkeypatch):
    _,front,_,_,rid,_,_=managed
    runner=front.managed_gateway
    entered=threading.Event();release=threading.Event()
    def slow(*a):entered.set();release.wait(1);return {'ok':False}
    monkeypatch.setattr(runner,'_execute',slow)
    result=asyncio.run(runner.execute(rid,tool='get_weather',arguments={'city':'Tokyo'},timeout=.02))
    assert entered.is_set() and result['task_status']=='timeout' and not result['execution_succeeded']
    release.set()


@pytest.mark.parametrize('phase',['server/discover','initialize','tools/list','tools/call'])
def test_mcp_rejects_mismatched_jsonrpc_ids(managed,phase):
    store,front,client,_,rid,calls,remote=managed
    def provider(req):
        body=json.loads(req.content or '{}');calls.append(req)
        if phase=='initialize' and body.get('method')=='server/discover':
            return httpx.Response(200,json={'jsonrpc':'2.0','id':body['id'],'error':{'code':-32601,'message':'Unsupported'}})
        response=remote.handle_request(req)
        if body.get('method')==phase:
            obj=response.json();obj['id']='wrong'
            return httpx.Response(200,json=obj)
        if phase=='server/discover' and body.get('method')=='initialize':
            return httpx.Response(200,json={'jsonrpc':'2.0','id':'wrong','result':{}})
        return response
    front.proxy=McpProxy(store,allow_private=True,http=httpx.Client(transport=httpx.MockTransport(provider)))
    result=rpc(client,f'/api/gateway/mcp/{rid}','tools/call',{'name':'get_weather','arguments':{'city':'Tokyo'}}).json()
    assert 'error' in result
    if phase!='tools/call':assert not any(json.loads(req.content or '{}').get('method')=='tools/call' for req in calls)


@pytest.mark.parametrize('identity',['0','-1','2147483648','999999999999999999999999999999999999999'])
def test_gateway_path_ids_are_bounded_before_database_lookup(managed,identity):
    assert managed[2].get('/api/gateway/mcp/'+identity).status_code==400
    assert not managed[5]


def test_a2a_v1_connection_returns_v1_message_parts_without_upstream_handles(managed):
    rid=setup_a2a(managed,'message')
    response=rpc(managed[2],f'/api/gateway/a2a/{rid}','SendMessage',{'message':{'role':'ROLE_USER','messageId':'public-message',
        'parts':[{'text':'Explain the weather.'}]}}).json()['result']['message']
    assert response['role']=='ROLE_AGENT' and 'kind' not in response
    assert response['parts']==[{'text':'Answer '+SOURCE}]
    assert 'contextId' not in response and 'taskId' not in response


@pytest.mark.parametrize('parameters',[{'configuration':{'blocking':False}},{'configuration':{'pushNotificationConfig':{'url':'http://localhost/receive'}}},
 {'metadata':{'url':'https://unregistered.example'}}])
def test_a2a_unsupported_continuation_or_delivery_configuration_is_not_forwarded(managed,parameters):
    rid=setup_a2a(managed,'message')
    response=rpc(managed[2],f'/api/gateway/a2a/{rid}','message/send',{
        'message':{'parts':[{'text':'Explain the weather.'}]},**parameters})
    assert 'error' in response.json() and not managed[5]


@pytest.mark.parametrize('schema',[{'pattern':'.*'},{'$ref':'https://attacker.example/schema'},{'type':'object','properties':{'x':{'pattern':'(a+)+$'}}},False])
def test_unsafe_or_false_schemas_fail_closed_without_dns(schema,monkeypatch):
    monkeypatch.setattr('socket.getaddrinfo',Mock(side_effect=AssertionError('Schema validation must stay offline')))
    with pytest.raises(ExecutionDenied):validate_arguments({'inputSchema':schema},{})


def test_projection_preserves_sources_on_provider_origin_and_nested_json():
    binding='https://provider.example/rpc'
    source='https://provider.example/docs/latest'
    value={'text':'Call '+binding+'; source '+source,'wire':json.dumps(json.dumps({'endpoint':binding,'url':source}))}
    result=project(value,'https://agentconcierge.biz/api/gateway/mcp/1',(binding,))
    assert binding not in json.dumps(result) and source in result['text']
    assert json.loads(json.loads(result['wire']))['url']==source


def test_mcp_tool_error_is_separate_from_valid_transport_and_protocol(managed):
    _,_,client,_,rid,_,remote=managed
    remote.call_result={'isError':True,'content':[{'type':'text','text':'The requested record is unavailable.'}]}
    response=client.post('/api/test/execute',json={'resource_id':rid,'tool':'get_weather','arguments':{'city':'Tokyo'}}).json()
    assert response['transport_ok'] is response['protocol_valid'] is True
    assert response['ok'] is response['execution_succeeded'] is False
    assert response['task_status']=='failed'


def test_ten_mcp_tasks_from_one_address_pass_and_the_eleventh_execution_is_limited(managed):
    """11-11: one MCP task is initialize + tools/list + tools/call; counting all three let an agent do only
    three tasks a minute (7 of 30 real tasks failed). Only Provider calls count, ten a minute."""
    _,front,client,_,rid,calls,_=managed
    del front.security.allow_probe          # the real sliding-window limiter again
    path=f'/api/gateway/mcp/{rid}'
    for task in range(10):
        assert rpc(client,path,'initialize').status_code==200
        assert rpc(client,path,'tools/list').status_code==200
        result=rpc(client,path,'tools/call',{'name':'get_weather','arguments':{'city':'Tokyo'}})
        assert result.status_code==200, (task, result.text)
    assert len(calls)>=10
    eleventh=rpc(client,path,'tools/call',{'name':'get_weather','arguments':{'city':'Tokyo'}})
    assert eleventh.status_code==429 and eleventh.headers['retry-after']=='60'
    assert rpc(client,path,'tools/list').status_code==200   # connection calls still answer
