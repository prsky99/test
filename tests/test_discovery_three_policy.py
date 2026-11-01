"""Three-result admission, protocol opt-in and focused workflow ranking."""
# ruff: noqa: F401 -- shared isolated fixtures
import json
import pytest
from tests.test_fast_single_recommendation import catalog, ask
from tests.test_workflow_discovery import discovery, rpc
from agent_market.concierge.front import get_front_explore
from agent_market.concierge.workflow_discovery import relevance


def test_auto_fills_a2a_then_mcp_and_never_x402(catalog):
    _, _, client, add, now = catalog
    a = add('A2A verified', kind='a2a', grade='B', report_at=now-100)
    m = add('MCP verified', kind='mcp', report_at=now-10)
    add('Newest x402', kind='x402', report_at=now-1)
    result = ask(client, 'weather forecast')['data']['recommendations']
    assert [r['id'] for r in result] == [a, m]


@pytest.mark.parametrize('selection', [None, 'auto', 'any', 'a2a', 'mcp', 'x402'])
def test_scope_applies_to_three_outputs_and_more(catalog, selection):
    _, _, client, add, now = catalog
    for kind in ('a2a', 'mcp', 'x402'):
        for index in range(4):
            add(kind+'-'+str(index), kind=kind, report_at=now-1-index)
    data = {} if selection is None else {'protocol': selection}
    first = ask(client, 'weather forecast', data=data)
    assert len(first['data']['recommendations']) == 3
    expected = selection if selection in ('a2a','mcp','x402') else 'a2a'
    assert {r['kind'] for r in first['data']['recommendations']} == {expected}
    token = first['visitor']['token']
    later = client.post('/chat', headers={'X-Visitor-Token': token}, json={'message':'more'}).json()
    assert not ({r['id'] for r in first['data']['recommendations']} & {r['id'] for r in later['data']['recommendations']})
    if selection not in ('x402',):
        assert all(r['kind'] != 'x402' for r in later['data']['recommendations'])


def test_unqualified_second_task_does_not_inherit_x402(catalog):
    _, _, client, add, now = catalog
    add('Explicit x402', kind='x402', report_at=now-1)
    add('Weather A2A', kind='a2a', report_at=now-50)
    first = ask(client, 'weather forecast', data={'protocol':'x402'})
    second = client.post('/chat', headers={'X-Visitor-Token':first['visitor']['token']},json={'message':'Find a weather forecast agent'}).json()
    assert {r['kind'] for r in second['data']['recommendations']} == {'a2a'}


def test_no_padding_with_failed_or_unrelated_candidates(catalog):
    _, _, client, add, now = catalog
    good = add('Good weather', kind='mcp', report_at=now-10)
    add('Failed weather', kind='a2a', report_at=now-1, report_success=0)
    add('Unrelated', kind='a2a', description='Unrelated invoice processing', report_at=now-1)
    values = ask(client, 'weather forecast')['data']['recommendations']
    assert [r['id'] for r in values] == [good]


def test_details_selects_second_and_third_current_recommendation(catalog):
    _, _, client, add, now = catalog
    for index in range(3):
        add('Forecast '+str(index),kind='a2a',report_at=now-1-index)
    first=ask(client,'weather forecast');token=first['visitor']['token']
    for number in (2,3):
        value=client.post('/chat',headers={'X-Visitor-Token':token},json={'message':'details '+str(number)}).json()
        assert value['data']['recommendation']['id']==first['data']['recommendations'][number-1]['id']


def test_micro_payment_copy_is_not_displayed_but_machine_fact_remains(catalog):
    _, _, client, add, now = catalog
    add('Research weather',kind='a2a',description='Weather forecasts via x402 micropayments. Reliable temperature forecasts.',report_at=now-1)
    body=ask(client,'weather forecast')
    assert 'micropayments' not in body['reply'].lower()
    assert 'micropayments' in body['data']['recommendations'][0]['description'].lower()


@pytest.mark.parametrize('kind', [None,'any','auto','a2a','mcp','x402'])
def test_explore_scope_and_default_order(catalog,kind):
    store,_,_,add,now=catalog
    for protocol in ('x402','mcp','a2a'):
        add(protocol+' weather',kind=protocol,report_at=now-1)
    value=get_front_explore(store,'weather forecast',kind,None,False,False)
    assert [r['kind'] for r in value['items']]==([kind] if kind in ('a2a','mcp','x402') else ['a2a','mcp'])
    assert value['total']==len(value['items'])


def test_focused_template_beats_newer_superset_and_returns_three(discovery):
    store,_,client,ids=discovery
    original=store.get_workflow(ids['news'])
    broad=json.loads(json.dumps(original['nodes']))
    broad += [{'id':'extra-country','name':'Country Profile','type':'agent','kind':'mcp','data':{'tool':'country_profile'}},
              {'id':'extra-gdp','name':'GDP Indicators','type':'agent','kind':'mcp','data':{'tool':'indicators'}}]
    for name,nodes in [('Startup Market Background Pack',broad),('Technology Meeting Research Brief',original['nodes']),('Related Technology Research',original['nodes'])]:
        store.create_workflow({'name':name,'description':'Technology news and research papers','nodes':nodes,'edges':[],'is_template':1})
    task='Find a workflow that researches technology news and papers'
    value=client.get('/api/workflows/templates',params={'q':task}).json()['templates']
    assert value[0]['id']==ids['news']
    assert value[-1]['name']=='Startup Market Background Pack'
    chat=client.post('/chat',json={'message':task}).json()
    assert len(chat['data']['workflows'])==3 and chat['data']['workflows'][0]['id']==ids['news']
    assert rpc(client,'search_workflows',{'task':task})['result']['structuredContent']['workflows'][0]['id']==ids['news']


def test_keywords_cannot_invent_node_capabilities(discovery):
    store,_,client,ids=discovery
    country=store.get_workflow(ids['country'])
    store.create_workflow({'name':'News Research Papers Best Workflow','description':'news research papers','nodes':country['nodes'],'edges':[],'is_template':1})
    assert [r['id'] for r in client.get('/api/workflows/templates',params={'q':'news papers'}).json()['templates']]==[ids['news']]


def test_x402_template_is_opt_in(discovery):
    store,_,client,ids=discovery
    graph=json.loads(json.dumps(store.get_workflow(ids['news'])['nodes']))
    for node in graph:node['kind']='x402'
    identity=store.create_workflow({'name':'New x402 News Research','nodes':graph,'edges':[],'is_template':1})
    assert identity not in [r['id'] for r in client.get('/api/workflows/templates',params={'q':'news papers'}).json()['templates']]
    value=client.post('/chat',json={'message':'news papers workflow','data':{'protocol':'x402'}}).json()
    assert [r['id'] for r in value['data']['workflows']]==[identity]
