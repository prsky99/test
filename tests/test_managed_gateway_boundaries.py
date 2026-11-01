"""Connection-policy boundaries, malformed challenges, and timeout saturation."""
import asyncio
import base64
import json
import threading

import httpcore
import httpx
import pytest
from fastapi import HTTPException

from agent_market.concierge.managed_gateway import challenge
from agent_market.concierge.notify import Courier
from agent_market.concierge.proxy import McpProxy
from tests.test_fast_single_recommendation import catalog
from tests.test_managed_agent_gateway import managed, rpc


@pytest.mark.parametrize('kind',['mcp','a2a'])
def test_public_execution_cannot_inherit_development_private_network_opt_in(managed,monkeypatch,kind):
    store,front,client,add,rid,calls,_=managed
    resolves=[]
    def private_dns(host,port,timeout):resolves.append(host);return ['127.0.0.1']
    monkeypatch.setattr('agent_market.concierge.http_security._resolve_addresses',private_dns)
    monkeypatch.setattr(httpcore.SyncBackend,'connect_tcp',lambda *a,**kw:pytest.fail('No private TCP connection permitted'))
    if kind=='mcp':front.proxy=McpProxy(store,allow_private=True)
    else:
        rid=add('Private DNS A2A',kind='a2a')
        front.courier=Courier(allow_private=True)
    payload={'resource_id':rid,'tool':'get_weather','arguments':{'city':'Tokyo'},'message':'Explain the weather.'}
    result=client.post('/api/test/execute',json=payload)
    assert result.status_code==200 and result.json()['execution_succeeded'] is False
    assert resolves and not calls
    assert '127.0.0.1' not in result.text


def test_mcp_rebinding_is_blocked_between_preflight_and_socket_connection(managed,monkeypatch):
    store,front,client,_,rid,calls,_=managed
    front.proxy=McpProxy(store,allow_private=True)
    resolves=[]
    def rebinding(host,port,timeout):
        resolves.append(host)
        return ['93.184.216.34'] if len(resolves)==1 else ['127.0.0.1']
    monkeypatch.setattr('agent_market.concierge.http_security._resolve_addresses',rebinding)
    monkeypatch.setattr(httpcore.SyncBackend,'connect_tcp',lambda *a,**kw:pytest.fail('Rebound TCP connection forbidden'))
    result=rpc(client,f'/api/gateway/mcp/{rid}','tools/call',{'name':'get_weather','arguments':{'city':'Tokyo'}})
    assert 'error' in result.json() and len(resolves)>=2 and not calls


def valid_challenge():
    return {'x402Version':2,'resource':{'url':'https://provider.example/data'},'accepts':[
        {'scheme':'exact','network':'eip155:8453','amount':'100','asset':'0xasset','payTo':'0xrecipient','maxTimeoutSeconds':60}]}


@pytest.mark.parametrize('invalid',['version-bool','missing-resource','private-resource','missing-timeout','negative-timeout',
 'nonfinite-timeout','wrong-amount-type','missing-recipient','empty-accepts','l402-only'])
def test_invalid_x402_challenge_cannot_be_reported_as_valid(invalid):
    body=valid_challenge()
    if invalid=='version-bool':body['x402Version']=True
    if invalid=='missing-resource':body.pop('resource')
    if invalid=='private-resource':body['resource']['url']='http://127.0.0.1/admin'
    if invalid=='missing-timeout':body['accepts'][0].pop('maxTimeoutSeconds')
    if invalid=='negative-timeout':body['accepts'][0]['maxTimeoutSeconds']=-10
    if invalid=='nonfinite-timeout':body['accepts'][0]['maxTimeoutSeconds']=float('inf')
    if invalid=='wrong-amount-type':body['accepts'][0]['amount']=True
    if invalid=='missing-recipient':body['accepts'][0].pop('payTo')
    if invalid=='empty-accepts':body['accepts']=[]
    if invalid=='l402-only':body={'error':'L402 macaroon required'}
    response=httpx.Response(402,content=json.dumps(body).encode(),headers={'WWW-Authenticate':'L402 macaroon="not-x402"'})
    assert challenge(response) is None


def test_header_only_x402_v2_challenge_is_supported():
    body=valid_challenge()
    response=httpx.Response(402,headers={'PAYMENT-REQUIRED':base64.b64encode(json.dumps(body).encode()).decode()})
    assert challenge(response)==body


def test_timed_out_workers_retain_all_slots_and_new_work_fails_without_queue(managed,monkeypatch):
    runner=managed[1].managed_gateway;rid=managed[4]
    release=threading.Event();finished=threading.Event();lock=threading.Lock();count=[0]
    def slow(*a):
        release.wait(2)
        with lock:
            count[0]+=1
            if count[0]==4:finished.set()
        return {'ok':False}
    monkeypatch.setattr(runner,'_execute',slow)
    async def exercise():
        results=await asyncio.gather(*(runner.execute(rid,tool='get_weather',arguments={'city':'Tokyo'},timeout=.03) for _ in range(4)))
        assert all(r['task_status']=='timeout' for r in results)
        with pytest.raises(HTTPException) as denied:
            await runner.execute(rid,tool='get_weather',arguments={'city':'Tokyo'})
        assert denied.value.status_code==503
    try:asyncio.run(exercise())
    finally:
        release.set()
        assert finished.wait(2)


def test_registered_a2a_guide_endpoint_and_verified_method_override_are_honored(managed):
    from agent_market.concierge.execution_policy import resolve_a2a
    from agent_market.concierge.connections import public_agent
    from unittest.mock import Mock
    resource={'id':8,'kind':'a2a','url':'https://provider.example/',
        'details':{'spec_version':'1.0'},'usage_guide':{'binding':'JSONRPC','endpoint':'https://provider.example/research',
            'agent_card':'https://provider.example/.well-known/agent-card.json','methods':{'send':'message/send'}},
        'description':'Card https://provider.example/.well-known/agent-card.json; docs https://provider.example/docs'}
    courier=Mock()
    courier.resolve.return_value={'url':'https://provider.example/research','v1':True}
    target=resolve_a2a(resource,courier,public=True)
    courier.resolve.assert_called_once_with('a2a','https://provider.example/research',public_only=True)
    assert target['v1'] is False
    projected=public_agent({'id':8,'kind':'a2a','description':resource['description']},resource)
    assert '/.well-known/agent-card.json' not in projected['description']
    assert 'https://provider.example/docs' in projected['description']


@pytest.mark.parametrize('guide',[{'binding':'GRPC','endpoint':'https://provider.example/'},
 {'binding':'JSONRPC','endpoint':'https://other.example/'},{'binding':'JSONRPC','endpoint':'http://127.0.0.1/admin'}])
def test_unsupported_or_cross_origin_a2a_guides_never_resolve(guide):
    from agent_market.concierge.execution_policy import ExecutionDenied, resolve_a2a
    from unittest.mock import Mock
    courier=Mock(side_effect=AssertionError('Must not resolve unsupported bindings'))
    with pytest.raises(ExecutionDenied):resolve_a2a({'url':'https://provider.example/','usage_guide':guide},courier,public=True)
    assert not courier.resolve.called
