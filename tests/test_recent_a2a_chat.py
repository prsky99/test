"""Automatic A2A-first policy and strict scopes using synthetic stock/news agents."""
import json

import pytest
from agent_market.gateway.visitor_desk import VisitorDesk
from tests.test_fast_single_recommendation import catalog, chosen  # noqa: F401


def stock_catalog(catalog):
    store,front,client,add,now=catalog
    def stock(name,kind,age,grade='A',**fields):
        return add(name,kind=kind,grade=grade,report_at=now-age,description='Stock news financial market headlines equities news',category='finance_crypto',usage_guide=json.dumps({'tools':[{'name':'stock_news','description':'Stock news and market headlines'}]}),**fields)
    ids={}
    ids['old_a2a']=stock('Older A2A Stock News','a2a',7200)
    ids['a2a']=stock('Recent A2A Stock News','a2a',20,'B')
    ids['old_mcp']=stock('Older MCP Stock News','mcp',3600)
    ids['mcp']=stock('Recent MCP Stock News','mcp',10,'B')
    ids['x402']=stock('Recent x402 Stock News','x402',1)
    return ids


def test_stock_news_defaults_to_recent_a2a_and_explicit_mcp_uses_recent_mcp(catalog):
    store,front,client,_,_=catalog;ids=stock_catalog(catalog)
    first=client.post('/chat',json={'message':'stock news','data':{'protocol':'auto'}}).json()
    assert chosen(first)['id']==ids['a2a'] and first['data']['protocol'] is None
    assert chosen(first)['grade']=='B' and chosen(first)['selection_policy']=='single_recent_verified_first'
    assert 'A2A' in client.get('/.well-known/agent-card.json').text
    assert 'A2A' in client.get('/llms.txt').text
    headers={'X-Visitor-Token':first['visitor']['token']}
    mcp=client.post('/chat',headers=headers,json={'message':'mcp stock news'}).json()
    assert chosen(mcp)['id']==ids['mcp'] and mcp['data']['protocol']=='mcp'
    details=client.post('/chat',headers=headers,json={'message':'details 1'}).json()
    assert chosen(details)['id']==ids['mcp'] and details['data']['protocol']=='mcp'
    again=client.post('/chat',headers=headers,json={'message':'stock news'}).json()
    assert chosen(again)['id']==ids['a2a'] and again['data']['protocol'] is None
    turns=VisitorDesk(store,front.updates).detail(first['visitor']['id'])['chat_turns']
    assert turns[0]['protocol_filter'] is None and turns[1]['protocol_filter']=='mcp'
    assert turns[-1]['question']=='stock news' and turns[-1]['protocol_mode']=='auto'


@pytest.mark.parametrize('data,expected',[({},'a2a'),({'protocol':'auto'},'a2a'),({'protocol':'mcp'},'mcp'),({'protocol':'x402'},'x402'),({'protocol':'any'},'a2a'),({'kind':'mcp'},'mcp')])
def test_default_and_explicit_protocol_compatibility(catalog,data,expected):
    _,_,client,_,_=catalog;ids=stock_catalog(catalog)
    body=client.post('/chat',json={'message':'stock news','data':data}).json()
    assert chosen(body)['id']==ids[expected]


def test_missing_a2a_fills_with_mcp_and_never_silently_uses_x402(catalog):
    store,_,client,_,_=catalog;stock_catalog(catalog)
    with store.tx() as db:db.execute("UPDATE resources SET active=0 WHERE kind='a2a'")
    body=client.post('/chat',json={'message':'stock news'}).json()
    assert body['data']['protocol'] is None
    assert body['data']['recommendations'] and all(item['kind']=='mcp' for item in body['data']['recommendations'])


def test_structured_task_uses_default_and_rejects_ambiguous_protocols(catalog):
    _,_,client,_,_=catalog;ids=stock_catalog(catalog)
    default=client.post('/chat',json={'message':'','data':{'task':'stock news'}}).json()
    assert chosen(default)['id']==ids['a2a']
    mcp=client.post('/chat',json={'message':'','data':{'task':'MCP stock news'}}).json()
    assert chosen(mcp)['id']==ids['mcp']
    invalid=client.post('/chat',json={'message':'','data':{'task':'MCP or A2A stock news'}}).json()
    assert invalid['data']['status']=='invalid_protocol'


def test_recency_does_not_admit_failed_or_unsafe_recent_agent(catalog):
    store,_,client,add,now=catalog;ids=stock_catalog(catalog)
    newest=add('Failed Stock News',kind='a2a',grade='A',report_at=now,report_success=0,description='Stock news market headlines',category='finance_crypto')
    add('Quarantined Stock News',kind='a2a',report_at=now,eval_security='quarantine',description='Stock news market headlines',category='finance_crypto')
    add('Private Stock News',kind='a2a',report_at=now,url='http://127.0.0.1/internal',description='Stock news market headlines',category='finance_crypto')
    result=client.post('/chat',json={'message':'stock news'}).json()
    assert chosen(result)['id']==ids['a2a'] and chosen(result)['id']!=newest
