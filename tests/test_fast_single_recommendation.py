"""Evidence-ranked Chat choices preserve admission without model/network calls."""
import json
import time
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from agent_market.concierge.front import Front, create_front_app
from agent_market.gateway.store import Store
from tests.report_fixtures import execution_report, legacy_report_fixture

@pytest.fixture
def catalog():
    store=Store()
    now=time.time()
    def add(name='Weather', grade='A', kind='mcp', health_at=None, report_at=None, report_success=1, **fields):
        description=fields.pop('description','Weather forecast temperature API')
        rid=store.upsert_resource({'key':name,'source':'fixture','kind':kind,'url':f'https://{name.lower().replace(" ","-")}.example/api','name':name,
            'description':description,'category':'travel_maps_weather',
            'networks':['base'],'price_usdc':fields.pop('price',0)})
        defaults={'eval_grade':grade,'eval_score':95,'eval_at':now-1000,'health_status':'healthy','last_ok_at':health_at or now-1,'auth_observed':0,
                  'usage_guide':json.dumps({'tools':[{'name':'forecast','description':description,'inputSchema':{'type':'object','properties':{'city':{'type':'string'}},'required':['city']}}]})}
        defaults.update(fields)
        fixture_tools=json.loads(defaults['usage_guide']).get('tools',[])
        # Synthetic providers publish complete contracts even when a test's
        # guide only abbreviates the parameterless tool it is exercising.
        fixture_tools=[{**t, 'inputSchema':t.get('inputSchema',
            {'type':'object','properties':t.get('params',{}),'required':t.get('required',[])})}
            for t in fixture_tools]
        defaults.setdefault('usage_tools',json.dumps(fixture_tools))
        defaults.setdefault('usage_full_tools',json.dumps(fixture_tools))
        with store.tx() as db:
            db.execute('UPDATE resources SET '+','.join(k+'=?' for k in defaults)+' WHERE id=?',(*defaults.values(),rid))
        if report_at:
            execution_report(store,rid,report_at,title=name,slug=name+'-report',eval_grade=grade,
                             eval_score=95,is_success=report_success,created_at=report_at,status_code=200)
        return rid
    front=Front(store,llm=Mock(),rag_engine=Mock())
    client=TestClient(create_front_app(front))
    yield store,front,client,add,now
    store._db.close()


def ask(client,text='find an MCP weather forecast API',**kwargs):
    response=client.post('/chat',json={'message':text,**kwargs})
    assert response.status_code==200,response.text
    return response.json()


def chosen(body):
    assert 1 <= len(body['data']['recommendations']) <= 3
    return body['data']['recommendations'][0]


def test_explicit_request_filter_precedes_recency_without_promoting_a_customer_tier(catalog):
    _,_,client,add,now=catalog
    best=add('Premium A',kind='x402',price=9000000,auth_observed=1,report_at=now-1)
    add('Free B',kind='x402',grade='B',report_at=now-300)
    body=ask(client,'find a free weather API without an API key',data={'protocol':'x402','auth':'none','limit':100})
    assert chosen(body)['id']!=best and chosen(body)['grade']=='B'
    assert chosen(body)['price_usdc']==0
    assert '9 USDC' not in body['reply'] and 'payment terms' not in body['reply']


def test_latest_report_then_recent_activity_determine_winner(catalog):
    store,_,client,add,now=catalog
    add('Older Report',report_at=now-500,health_at=now)
    newer=add('New Report',report_at=now-10,health_at=now-100)
    assert chosen(ask(client))['id']==newer
    with store.tx() as db:
        # Equal execution evidence, rather than equal publication timestamps.
        db.execute('DELETE FROM agent_test_reports')
        db.execute('DELETE FROM capability_evidence')
    for resource in store.query('SELECT id FROM resources'):
        execution_report(store,resource['id'],now-10,title='Equal measured checks',
                         slug='equal-'+str(resource['id']),created_at=now-10,status_code=200)
    assert chosen(ask(client))['name']=='Older Report'


def test_latest_failed_report_overrides_old_success(catalog):
    store,_,client,add,now=catalog
    failed=add('Failed A',report_at=now-50)
    execution_report(store,failed,now-1,title='New failed test',slug='failed-2',is_success=0,status_code=500,created_at=now-1)
    good=add('Working B',grade='B',report_at=now-5)
    assert chosen(ask(client))['id']==good


def test_unbound_url_document_does_not_promote_verification(catalog):
    store,_,client,add,now=catalog
    older=add('Old Report',report_at=now-200)
    newest=add('URL Report',report_at=now-500)
    report_id=legacy_report_fixture(store,{'title':'Unlinked','slug':'url-new','kind':'mcp','agent_url':store.resource(newest)['url'],'eval_grade':'A','is_success':1,'created_at':now-1})
    item=chosen(ask(client))
    assert item['id']==older and item['test_report']['id']!=report_id


def test_no_model_embedding_or_live_probe_is_called(catalog):
    _,front,client,add,now=catalog
    add(kind='a2a',report_at=now-1)
    front.llm.extract.side_effect=AssertionError('No LLM in request path')
    front.rag_engine.hybrid_search.side_effect=AssertionError('No embeddings in request path')
    front.rag_engine.generate_rag_answer.side_effect=AssertionError('No RAG generation')
    response=client.post('/chat',json={'message':'서울 날씨 알려줘'})
    assert chosen(response.json())['name']=='Weather'
    assert 'Server-Timing' in response.headers
    assert not front.llm.mock_calls and not front.rag_engine.mock_calls


def test_single_output_is_independent_of_customer_tier_and_does_not_upsell(catalog):
    store,_,client,add,_=catalog
    for n in range(6):add('Weather '+str(n))
    first=ask(client)
    token=first['visitor']['token']
    with store.tx() as db:
        db.execute("UPDATE agent_visitors SET visits=9,visit_days=5,messages=20,tier='regular' WHERE id=?",(first['visitor']['id'],))
    response=client.post('/chat',headers={'X-Visitor-Token':token},json={'message':'MCP weather forecast'})
    later=response.json()
    assert chosen(first)['id']==chosen(later)['id']
    assert not first['suggested_replies'] and set(first['visitor'])=={'id','token'}
    for text in (first['reply'],later['reply']):
        assert all(word not in text for word in ('contact','regular','visitor token','Pro SLA','Best matches'))


def test_pricing_keyword_does_not_intercept_task(catalog):
    _,_,client,add,_=catalog
    add()
    assert chosen(ask(client,'find an MCP weather API with pricing information'))['name']=='Weather'


@pytest.mark.parametrize('bad', ['down','retired','failing','unknown'])
def test_inactive_or_failed_health_is_not_recommended(catalog,bad):
    _,_,client,add,_=catalog
    add(health_status=bad)
    assert ask(client)['data']['recommendations']==[]


def test_stale_or_unrelated_candidates_are_not_substituted(catalog):
    _,_,client,add,now=catalog
    add('Stale',health_at=now-90000)
    add('Map',description='Street maps and geocoding locations')
    assert ask(client)['data']['recommendations']==[]


def test_new_data_immediately_changes_selection(catalog):
    store,_,client,add,now=catalog
    first=add('First',report_at=now-100)
    second=add('Second',report_at=now-200)
    assert chosen(ask(client))['id']==first
    execution_report(store,second,now,title='Fresh',slug='fresh-second',eval_grade='A',is_success=1,created_at=now)
    assert chosen(ask(client))['id']==second


def test_mcp_search_is_capped_at_three_regardless_of_k(catalog):
    _,_,client,add,_=catalog
    for n in range(4):add('Weather '+str(n))
    response=client.post('/mcp',json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'search','arguments':{'task':'MCP weather forecast','k':5}}})
    result=response.json()['result']['structuredContent']
    assert len(result['recommendations'])==3


def test_details_and_failure_return_one_current_candidate(catalog):
    _,_,client,add,now=catalog
    a=add('First',report_at=now-1);b=add('Second',report_at=now-2)
    first=ask(client);h={'X-Visitor-Token':first['visitor']['token']}
    assert chosen(client.post('/chat',headers=h,json={'message':'details 1'}).json())['id']==a
    assert chosen(client.post('/chat',headers=h,json={'message':'failed 1'}).json())['id']==b


def test_iso_report_dates_rank_with_numeric_dates(catalog):
    from datetime import datetime,timezone
    _,_,client,add,now=catalog
    add('Numeric',report_at=now-100)
    best=add('ISO',report_at=datetime.fromtimestamp(now-5,timezone.utc).strftime('%Y-%m-%d %H:%M:%S'))
    item=chosen(ask(client))
    assert item['id']==best and abs(item['test_report']['created_at']-(now-5))<1


def test_latest_report_grade_overrides_older_evaluation(catalog):
    store,_,client,add,now=catalog
    downgraded=add('Downgraded',report_at=now-1)
    good=add('Good B',grade='B',report_at=now-1)
    with store.tx() as db:
        db.execute("UPDATE agent_test_reports SET eval_grade='C' WHERE resource_id=?",(downgraded,))
    assert chosen(ask(client))['id']==good


def test_high_grade_unrelated_candidate_does_not_win(catalog):
    _,_,client,add,now=catalog
    add('News',description='Weather news journalism search articles',report_at=now-1,category='web_search')
    good=add('Forecast B',grade='B',report_at=now-100)
    assert chosen(ask(client,'MCP weather forecast temperature'))['id']==good


def test_quarantined_or_private_endpoint_is_excluded(catalog):
    _,_,client,add,_=catalog
    add('Quarantined',eval_security='quarantine')
    add('Local',url='http://127.0.0.1/mcp')
    assert ask(client)['data']['recommendations']==[]


def test_future_activity_does_not_make_stale_candidate_fresh(catalog):
    _,_,client,add,now=catalog
    add('Future',health_at=now+86400)
    assert ask(client)['data']['recommendations']==[]


def test_task_relevant_tool_precedes_unrelated_reported_tool(catalog):
    store,_,client,add,now=catalog
    rid=add('Two Tools',report_at=now-1,usage_guide=json.dumps({'tools':[
        {'name':'health_check','description':'Connection check','inputSchema':{'type':'object','properties':{}}},
        {'name':'forecast','description':'Weather forecast','inputSchema':{'type':'object','properties':{'city':{'type':'string'}}}}]}))
    with store.tx() as db:db.execute("UPDATE agent_test_reports SET tool_name='health_check' WHERE resource_id=?",(rid,))
    item=chosen(ask(client))
    assert item['tools']==['forecast'] and len(item['tools_schema'])==1


def test_relevant_winner_is_not_lost_behind_arbitrary_candidate_limit(catalog):
    _,front,_,add,now=catalog
    for index in range(520):
        add('Weather News '+str(index),description='Weather news articles',category='web_search')
    best=add('Temperature Forecast',grade='B')
    assert front.rec.search('weather forecast temperature')[0]['id']==best


def test_trial_without_timestamp_records_fresh_verification(catalog):
    store,front,_,add,now=catalog
    rid=add('New Trial',health_at=now-90000)
    store.record_usage(rid,tools=[{'name':'forecast','description':'Weather forecast'}],digest='trial',guide={},changes=None,trial={'ok':True})
    assert now-1<=json.loads(store.resource(rid)['trial_info'])['at']<=time.time()
    assert front.rec.search('weather forecast')[0]['id']==rid


def test_commercial_quality_and_speed_modifiers_do_not_obscure_task(catalog):
    _,_,client,add,_=catalog
    add()
    assert chosen(ask(client,'Please recommend the fastest highly rated premium MCP agent providing accurate weather forecasts today'))['name']=='Weather'


def test_contact_capability_query_is_not_contact_registration(catalog):
    _,_,client,add,now=catalog
    best=add('Contacts',kind='a2a',description='Contact enrichment and email lookup',category='productivity',report_at=now-1)
    assert chosen(ask(client,'contact enrichment agent'))['id']==best


@pytest.mark.parametrize('dedicated',[True,False])
def test_recent_construction_weather_window_is_not_a_general_forecast(catalog,dedicated):
    _,front,_,add,now=catalog
    restricted=add('Construction company',kind='a2a',report_at=now-1,category='finance_crypto',
        description='Residential remodeling contractor offering weather windows and permits.',
        usage_guide=json.dumps({'tools':[{'name':'get_weather_window','description':'Checks 14-day Seattle weather forecast for suitability of exterior construction projects (painting, roofing).'}]}))
    if dedicated:good=add('Weather forecast service',kind='a2a',report_at=now-300)
    result=front.rec.search('weather forecast agent',kind='a2a')
    assert ([item['id'] for item in result]==[good]) if dedicated else result==[]
    assert front.rec.search('weather forecast for construction roofing in Seattle',kind='a2a')[0]['id']==restricted


def test_broad_questions_read_listing_contracts_in_bounded_ranked_batches(catalog,monkeypatch):
    # Production matched ~29k listings (150 MB) for "translate text"; one bulk read exceeded the store limit.
    from agent_market.concierge import selection
    store,front,client,add,now=catalog
    ids=[add(f'Weather {n}',health_at=now-100+n) for n in range(7)]
    batches=[]
    def bulk(batch):
        batches.append(list(batch))
        return {rid:store.resource(rid) for rid in batch}
    monkeypatch.setattr(store,'recommendation_resources',bulk,raising=False)
    monkeypatch.setattr(selection,'RESOURCE_BATCH',3)
    assert ask(client)['data']['recommendations'][0]['id']==ids[-1]
    assert batches and all(len(batch)<=3 for batch in batches)
    assert batches[0]==[ids[6],ids[5],ids[4]]
