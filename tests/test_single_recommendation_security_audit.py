"""Adversarial requests against the single-agent change; only disposable local state."""
import json
from unittest.mock import Mock

import pytest

from agent_market.concierge.recommendation_security import usable_endpoint
from tests.test_fast_single_recommendation import catalog  # noqa: F401

BAD_ENDPOINTS=[
    'http://localhost./mcp','http://LOCALHOST/mcp','http://service.internal/mcp',
    'http://2130706433/mcp','http://0x7f000001/mcp','http://127.1/mcp','http://0177.0.0.1/mcp',
    'http://127.0.0.1/mcp','http://[::1]/mcp','http://169.254.169.254/latest/meta-data/',
    'http://10.1.2.3/mcp','https://good.example:bad/mcp','https://good.example:70000/mcp',
    'https://good.example:0/mcp','https://user:password@good.example/mcp',
    'https://good.example/mcp?api_key=audit-placeholder','https://good.example/mcp?accessToken=audit-placeholder',
    'https://good.example/mcp?api%5Fkey=audit-placeholder','https://good.example/mcp#token=audit-placeholder',
    'https://good.example\\@127.0.0.1/mcp','https://good.example\r\n/mcp',
    'http://\uff11\uff12\uff17\u3002\uff10\u3002\uff10\u3002\uff11/mcp',
]


@pytest.mark.parametrize('url',BAD_ENDPOINTS)
def test_nonpublic_or_credentialed_endpoint_is_rejected_without_dns(url,monkeypatch):
    monkeypatch.setattr('socket.getaddrinfo',Mock(side_effect=AssertionError('No request-time DNS')))
    assert usable_endpoint(url) is False


def request(client,channel,task='MCP weather forecast'):
    if channel=='rest':
        response=client.post('/chat',json={'message':task})
        assert response.status_code==200,response.text
        return response,response.json()['data']['recommendations']
    if channel=='a2a':
        response=client.post('/a2a',json={'jsonrpc':'2.0','id':1,'method':'message/send','params':{'message':{'parts':[{'text':task}]}}})
        assert response.status_code==200,response.text
        return response,response.json()['result']['parts'][1]['data']['recommendations']
    response=client.post('/mcp',json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'search','arguments':{'task':task}}})
    assert response.status_code==200,response.text
    return response,response.json()['result']['structuredContent']['recommendations']


@pytest.mark.parametrize('channel',['rest','a2a','mcp'])
def test_credential_values_removed_but_call_schema_preserved(catalog,channel):
    store,_,client,add,_=catalog
    secret='audit-credential-marker-not-a-real-key'
    add(auth_observed=1,auth_method='api_key',auth_info=json.dumps({'instructions':['Authorization: Bearer '+secret,'api_key='+secret,'API key: '+secret,'key='+secret]}),
        usage_guide=json.dumps({'tools':[{'name':'forecast','inputSchema':{
            'type':'object','properties':{'api_key':{'type':'string','default':secret,'enum':[secret],'const':secret},
            'city':{'type':'string','examples':[secret]},'units':{'type':'string','enum':['C','F']}},'required':['api_key','city']}}]}))
    response,items=request(client,channel)
    assert len(items)==1 and secret not in response.text
    schema=items[0]['tools_schema'][0]['inputSchema']
    assert schema['properties']['api_key']=={'type':'string'}
    assert schema['required']==['api_key','city'] and schema['properties']['units']['enum']==['C','F']
    saved=store.query('SELECT last_results FROM agent_visitors')
    if channel=='mcp':
        assert saved==[]  # Read-only lookup must not create a conversation to inspect.
    else:
        assert secret not in saved[0]['last_results']


@pytest.mark.parametrize('channel',['rest','a2a','mcp'])
@pytest.mark.parametrize('endpoint',['http://localhost./mcp','http://2130706433/mcp','https://unverified.example/mcp','https://weather.example/api?token=audit-placeholder'])
def test_unsafe_or_unverified_guide_endpoint_falls_back_to_verified_origin(catalog,channel,endpoint):
    _,_,client,add,_=catalog
    add(usage_guide=json.dumps({'endpoint':endpoint,'tools':[{'name':'forecast','description':'Weather forecast'}]}))
    _,items=request(client,channel)
    assert len(items)==1 and items[0]['usage_endpoint']=='https://agentconcierge.biz/api/gateway/mcp/1'


@pytest.mark.parametrize('url',BAD_ENDPOINTS[:10])
def test_bad_catalog_endpoint_cannot_be_recommended(catalog,url):
    _,_,client,add,_=catalog
    add(url=url)
    _,items=request(client,'rest')
    assert items==[]


def test_same_origin_guide_is_kept_private_behind_callable_gateway(catalog):
    _,_,client,add,_=catalog
    add(usage_guide=json.dumps({'endpoint':'https://weather.example/mcp?transport=http','tools':[{'name':'forecast','description':'Weather forecast'}]}))
    _,items=request(client,'rest')
    assert items[0]['usage_endpoint']=='https://agentconcierge.biz/api/gateway/mcp/1'


@pytest.mark.parametrize('payload',["weather OR 1=1",'weather " OR "*','weather; DROP TABLE resources; --',"weather ' UNION SELECT password FROM users --"])
def test_search_metacharacters_cannot_change_sql_or_schema(catalog,payload):
    store,_,client,add,_=catalog
    rid=add()
    response=client.post('/chat',json={'message':payload})
    assert response.status_code in (200,400)
    assert store.resource(rid)['name']=='Weather'
    assert store.query('SELECT count(*) n FROM resources')[0]['n']==1
    assert 'Traceback' not in response.text and 'sqlite3' not in response.text


def test_search_does_not_initiate_external_network_or_model_calls(catalog,monkeypatch):
    _,front,client,add,_=catalog
    add()
    monkeypatch.setattr('socket.getaddrinfo',Mock(side_effect=AssertionError('No DNS allowed during search')))
    for channel in ('rest','a2a','mcp'):
        _,items=request(client,channel)
        assert len(items)==1
    assert not front.llm.mock_calls and not front.rag_engine.mock_calls


@pytest.mark.parametrize('rid,ok',[(True,False),(1,'false'),(1,0),(-1,False),(999999,True)])
def test_feedback_types_and_resource_are_validated_before_any_write(catalog,rid,ok):
    store,_,client,add,_=catalog
    add()
    response=client.post('/mcp',json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'report','arguments':{'resource_id':rid,'ok':ok}}})
    assert response.status_code==200 and response.json()['error']['code']==-32602
    assert store.query('SELECT count(*) n FROM feedback')[0]['n']==0
    assert store.query('SELECT count(*) n FROM agent_outcomes')[0]['n']==0


def test_false_string_cannot_be_recorded_as_success(catalog):
    store,_,client,add,_=catalog
    add()
    first,_=request(client,'rest')
    token=first.json()['visitor']['token']
    response=client.post('/chat',json={'message':'','data':{'intent':'outcome','success':'false'}},headers={'X-Visitor-Token':token})
    assert response.json()['data']['status']=='invalid_request'
    assert store.query('SELECT count(*) n FROM agent_outcomes')[0]['n']==0


@pytest.mark.parametrize('channel',['rest','a2a','mcp'])
def test_nonfinite_provider_schema_cannot_break_public_json_response(catalog,channel):
    _,_,client,add,_=catalog
    add(usage_guide=json.dumps({'tools':[{'name':'forecast','inputSchema':{'type':'object','properties':{
        'temperature':{'type':'number','maximum':float('nan')},'mode':{'enum':[float('inf'),'auto']}}}}]}))
    response,items=request(client,channel)
    json.loads(response.text,parse_constant=lambda v:pytest.fail('Nonstandard JSON escaped: '+v))
    # An invalid constraint must not become a wider advertised call contract.
    # A listing without a callable schema must not be a Chat recommendation.
    assert items == []
    store=catalog[0]
    assert all(row['schema_complete']==0 for row in store.query('SELECT schema_complete FROM connection_versions'))


def test_calling_detail_and_recommendation_share_credential_redaction(catalog):
    _,_,client,add,_=catalog
    secret='audit-detail-placeholder-not-a-real-key'
    rid=add(auth_observed=1,auth_method='api_key',auth_info=json.dumps({'instructions':['Authorization: Bearer '+secret]}),
        usage_guide=json.dumps({'tools':[{'name':'forecast','inputSchema':{'type':'object','properties':{
            'apiKey':{'type':'string','default':secret},'city':{'type':'string','examples':[secret]}},'required':['apiKey']}}]}))
    response=client.get(f'/api/agents/{rid}')
    assert response.status_code==200 and secret not in response.text
    _,items=request(client,'rest')
    assert items[0]['tools_schema'][0]['inputSchema']['properties']['apiKey']=={'type':'string'}
