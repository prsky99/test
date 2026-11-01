"""Managed protocol connections use actual certificate-verified loopback TLS sockets."""
import base64
import json

import httpx
import pytest
from fastapi import Request
from fastapi.responses import JSONResponse

from agent_market.collector import usage
from agent_market.concierge.http_security import bounded_client
from agent_market.concierge.proxy import McpProxy
from tests.test_fast_single_recommendation import catalog
from tests.test_notification_inbox_integration import network
from tests.test_mcp_proxy import WEATHER_TOOL


@pytest.mark.parametrize('kind',['mcp','a2a','x402'])
def test_managed_connection_over_real_tls_with_no_browser_credentials(catalog,network,monkeypatch,kind):
    store,front,client,add,now=catalog
    app,_,_,courier,transport,_=network
    observed=[]
    @app.get('/managed/card.json')
    def card():
        return {'name':'Research','protocolVersion':'0.3.0','url':'https://inbox.example/managed/a2a',
                'preferredTransport':'JSONRPC','capabilities':{},'skills':[]}
    @app.api_route('/managed/{protocol}',methods=['GET','POST','DELETE'])
    async def provider(protocol:str,req:Request):
        assert not req.headers.get('authorization') and not req.headers.get('cookie')
        assert not req.headers.get('x-visitor-token') and not req.headers.get('payment-signature')
        body=await req.json() if req.method=='POST' else {}
        observed.append((protocol,req.method,body))
        if protocol=='x402':
            assert req.method=='GET'
            challenge={'x402Version':2,'resource':{'url':'https://inbox.example/managed/x402'},
                       'accepts':[{'scheme':'exact','network':'eip155:8453','asset':'0xasset','payTo':'0xrecipient',
                                   'amount':'100','maxTimeoutSeconds':60}]}
            return JSONResponse({},status_code=402,headers={'PAYMENT-REQUIRED':base64.b64encode(json.dumps(challenge).encode()).decode()})
        method=body.get('method')
        if protocol=='a2a':
            assert method=='message/send' and body['params']['message']['role']=='user'
            result={'kind':'message','role':'agent','parts':[{'kind':'text','text':'Research source https://news.example/real-tls'}]}
        elif method=='server/discover':
            result={'protocolVersion':'2026-07-28','serverInfo':{'name':'TLS Research'}}
        elif method=='tools/list':result={'tools':[WEATHER_TOOL]}
        elif method=='tools/call':
            assert body['params']=={'name':'get_weather','arguments':{'city':'Tokyo'}}
            result={'content':[{'type':'text','text':'Weather source https://news.example/real-tls'}]}
        else:raise AssertionError('Unexpected managed provider operation')
        return {'jsonrpc':'2.0','id':body['id'],'result':result}
    url='https://inbox.example/managed/card.json' if kind=='a2a' else 'https://inbox.example/managed/'+kind
    rid=add('TLS '+kind,kind=kind,url=url)
    compact=usage.compact_tools([WEATHER_TOOL])
    store.record_usage(rid,tools=compact,digest=usage.tools_hash(compact),guide={},changes=None,trial={'ok':True})
    provider_client=httpx.Client(transport=transport,trust_env=False,timeout=5)
    front.proxy=McpProxy(store,http=provider_client)
    front.courier=courier
    if kind=='x402':
        monkeypatch.setattr('agent_market.concierge.managed_gateway.bounded_client',lambda **kwargs:bounded_client(provider_client,limit=65536))
    path=f'/api/gateway/{kind}/{rid}'
    headers={'Authorization':'Bearer browser-secret','X-Visitor-Token':'browser-session','Cookie':'private=browser'}
    if kind=='x402':
        response=client.get(path,headers=headers)
        assert response.status_code==402
        assert response.json()['resource']['url']=='https://agentconcierge.biz'+path
        assert json.loads(base64.b64decode(response.headers['payment-required']))['x402Version']==2
        assert observed==[('x402','GET',{})]
    else:
        params={'name':'get_weather','arguments':{'city':'Tokyo'}} if kind=='mcp' else {'message':{'parts':[{'kind':'text','text':'Explain the research.'}]}}
        response=client.post(path,headers=headers,json={'jsonrpc':'2.0','id':42,'method':'tools/call' if kind=='mcp' else 'message/send','params':params})
        assert response.status_code==200 and response.json()['id']==42
        assert 'result' in response.json() and 'https://news.example/real-tls' in response.text
        assert any(body.get('method')==('tools/call' if kind=='mcp' else 'message/send') for _,_,body in observed)
    assert transport.requests
    if kind=='x402':
        # Inspection-only x402 discloses the provider for direct payment, only in these labelled fields.
        body=response.json()
        assert body['gateway_mode']=='inspection_only' and body['provider_url']=='https://inbox.example/managed/x402'
        assert response.headers['x-provider-url']==body['provider_url']
        assert 'inbox.example' not in json.dumps({k:v for k,v in body.items() if k!='provider_url'})
    else:
        assert 'inbox.example' not in response.text
