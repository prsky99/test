"""Regressions from the seventh public UX and recommendation review."""
import json
import time

import pytest
from tests.test_fast_single_recommendation import catalog,ask
from tests.test_owned_data_agents import engine
from agent_market.concierge.selection import _service_focus
from agent_market.concierge.fast_chat import agent_display_name
from agent_market.owned_data_agents.engine import DataUnavailable


def schema(name,description,props=None):
    return {'name':name,'description':description,'inputSchema':{'type':'object','properties':props or {'query':{'type':'string'}},'required':list(props or {'query':None})}}


def test_focused_translation_precedes_recent_bundle_and_excludes_translation_library(catalog):
    _,_,client,add,now=catalog
    translate=schema('translate_text','Translate provided text into a requested target language.',{'text':{'type':'string'},'target_language':{'type':'string'}})
    bundle=[translate]+[schema('unrelated_'+str(n),'Send a fax.') for n in range(57)]
    add('Sats4AI - Bitcoin-Powered AI Tools',description='40+ Lightning-paid AI tools for agents: calls, SMS, fax, voice, translation.',
        usage_guide=json.dumps({'tools':bundle}),report_at=now-1,category='media_generation')
    good=add('Faceabot Translate',description='Translate text or a document into about 100 languages.',usage_guide=json.dumps({'tools':[translate]}),report_at=now-100)
    library=schema('search_translations','Search existing translations in a pre-modern library.')
    bad=add('Source Library',description='Search historical texts translated to English.',usage_guide=json.dumps({'tools':[library]}),report_at=now-2)
    for question in ('Translate English text into Korean','Translate a document from Spanish to English'):
        items=ask(client,question,data={'protocol':'mcp'})['data']['recommendations']
        assert items[0]['id']==good
        assert bad not in [item['id'] for item in items]


def test_github_namespace_alone_is_not_focused_and_query_search_is_required(catalog):
    _,_,client,add,now=catalog
    tool=schema('search_github_issues','Search GitHub issues using public search keywords.')
    many=[tool]+[schema('unrelated_'+str(n),'Read a financial statement.') for n in range(20)]
    add('io.github.UnityNodes/canton-ccpedia',description='Canton Network: CIPs, votes and validator upgrades.',usage_guide=json.dumps({'tools':many}),report_at=now-1)
    good=add('GitHub Issues and Pull Requests',description='Search public GitHub issues and pull requests.',usage_guide=json.dumps({'tools':[tool]}),report_at=now-50)
    repo=schema('list_repository_issues','List GitHub issues in one repository.',{'owner':{'type':'string'},'repository':{'type':'string'}})
    wrong=add('Repository Issues',description='List issues in a GitHub repository.',usage_guide=json.dumps({'tools':[repo]}),report_at=now-2)
    reference=add('Landmine',description='Search a curated knowledge base of known library problems.',usage_guide=json.dumps({'tools':[schema('landmine_lookup','Look up known library problems curated from GitHub issues.')]}),report_at=now-1)
    items=ask(client,'Search GitHub issues about React hydration bugs',data={'protocol':'mcp'})['data']['recommendations']
    assert items[0]['id']==good and not {wrong,reference}.intersection(item['id'] for item in items)


def test_small_server_focus_still_requires_its_task():
    row={'kind':'mcp','name':'Weather','description':'Forecast temperatures.', 'usage_full_tools':json.dumps([schema('forecast','Get weather forecasts.')])}
    assert not _service_focus(['github','issues'],row)
    assert _service_focus(['weather','forecast'],row)


def test_display_name_keeps_identity_and_machine_name():
    assert agent_display_name({'name':'Acme Weather - Free API','kind':'mcp','id':7})=='Acme Weather - API'
    assert agent_display_name({'name':'\ubc88\uc5ed','kind':'mcp','id':7})=='MCP agent #7'


def test_github_failure_never_substitutes_another_query(engine):
    core,calls,state=engine
    core.execute('github-issues',{'query':'old topic','limit':2})
    state['fail']=True
    # A different key has no valid cached answer, even if another query succeeded.
    with pytest.raises(DataUnavailable):core.execute('github-issues',{'query':'new topic','limit':2})


def test_owned_revision_recovers_a_failed_local_pin_without_forging_evidence(engine):
    from agent_market.gateway.store import Store
    from agent_market.capability_registry import Registry,known_schema_failure
    from agent_market.owned_data_agents.activation import install
    from agent_market.owned_data_agents.catalog import tool_spec
    from agent_market.collector.usage import compact_tools,tools_hash
    store=Store();ids=install(store,'https://agentconcierge.biz');rid=ids['technology-news']
    # Reproduce the old local binding and its durable schema failure.
    with store.tx() as db:db.execute("UPDATE resources SET details='{}',content_hash='legacy-fixture' WHERE id=?",(rid,))
    registry=Registry(store);old=registry.current(store.resource(rid));now=time.time()
    registry.approve(store.resource(rid),'news.search.v1',tool_spec('technology-news')['name'])
    registry.record(old,scope='execution',outcome='failed',started=now-1,finished=now,code='SCHEMA_CHANGED')
    assert known_schema_failure(store,store.resource(rid))
    install(store,'https://agentconcierge.biz')
    current=registry.current(store.resource(rid))
    assert current['id']!=old['id'] and not known_schema_failure(store,store.resource(rid))
    assert not store.query('SELECT * FROM capability_evidence WHERE version_id=?',(current['id'],))
    assert store.query('SELECT * FROM capability_approvals WHERE version_id=?',(current['id'],))
    # Repeat installation must keep the same pin rather than erasing a new failure.
    registry.record(current,scope='execution',outcome='failed',started=now,finished=now+1,code='SCHEMA_CHANGED')
    install(store,'https://agentconcierge.biz')
    assert registry.current(store.resource(rid))['id']==current['id']
    assert known_schema_failure(store,store.resource(rid))
    store._db.close()


@pytest.mark.parametrize('method,params,version',[
    ('initialize',{'protocolVersion':'2025-11-25'},'2025-11-25'),
    ('initialize',{'protocolVersion':'future-version'},'2025-11-25'),
    ('server/discover',{'_meta':{'io.modelcontextprotocol/protocolVersion':'2026-07-28'}},'2026-07-28')])
def test_owned_mcp_negotiates_current_clients(engine,method,params,version):
    from fastapi.testclient import TestClient
    from agent_market.owned_data_agents.service import create_app,PREFIX
    core,_,_=engine
    client=TestClient(create_app(enabled=True,engine=core))
    response=client.post(PREFIX+'/technology-news/mcp',json={'jsonrpc':'2.0','id':1,'method':method,'params':params})
    assert response.json()['result']['protocolVersion']==version


def test_unmeasured_report_defaults_to_not_successful():
    from agent_market.gateway.store import Store
    store=Store()
    rid=store.upsert_resource({'key':'qa-report','source':'fixture','kind':'mcp','url':'https://example.com/mcp','name':'QA fixture','description':'Metadata only','category':'dev_tools'})
    report_id=store.create_test_report({'resource_id':rid,'title':'Metadata without an execution'})
    assert store.get_test_report(report_id)['is_success']==0
    store._db.close()


@pytest.mark.parametrize('accept,markdown', [('text/markdown',True),('application/json, text/markdown;q=0.5',False),('text/markdown;q=0',False)])
def test_markdown_is_explicit_and_does_not_change_default_machine_json(catalog,accept,markdown):
    _,_,client,add,_=catalog;add('Weather Service')
    reply=client.post('/chat',headers={'Accept':accept},json={'message':'weather forecast'})
    assert reply.status_code==200
    assert reply.headers['content-type'].startswith('text/markdown' if markdown else 'application/json')
    if markdown:
        assert 'Weather Service' in reply.text and 'visitor' not in reply.text


def test_admin_api_requires_actual_evidence_before_success_publication():
    from tests.test_gateway import populated
    from tests.conftest import staff_session
    world=populated();client=__import__('fastapi.testclient',fromlist=['TestClient']).TestClient(world.app)
    headers=staff_session(world.store)
    response=client.post('/admin/api/test-reports',headers=headers,json={
        'title':'Unexecuted claim','slug':'qa-unexecuted-claim','kind':'mcp',
        'agent_url':'https://example.com/mcp','agent_name':'QA fixture','is_success':1})
    assert response.status_code==422 and response.json()['error_code']=='EXECUTION_EVIDENCE_REQUIRED'


def test_owned_reverification_recovers_route_failure_only_after_real_source_read(engine, monkeypatch):
    import httpx
    from agent_market.owned_data_agents import docs
    from tests.test_technical_docs_agent import agent, context7
    docs_calls=[];site=context7(docs_calls)
    docs_core,docs_http=agent(lambda request: (docs_calls.append(request.url.path),httpx.Response(200,json={'documents':[{'mdn_url':'/en-US/docs/Web/API/AbortController',
        'title':'AbortController','summary':'Aborts requests.'}]}))[1] if request.url.host=='developer.mozilla.org' else site(request))
    monkeypatch.setattr(docs,'engine',lambda: docs_core)
    from agent_market.gateway.store import Store
    from agent_market.owned_data_agents.activation import install
    from agent_market.concierge.proxy import McpProxy
    from agent_market.model_contract_reverify import ContractReverifier
    core,calls,_=engine
    store=Store();resources=install(store,'https://agentconcierge.biz');store._owned_data_engine=core
    with store.tx() as db:
        db.execute("UPDATE resources SET health_status='down',last_status_code=404 WHERE source='agentconcierge-owned'")
    result=ContractReverifier(store,McpProxy(store),limit=8).run()
    # Seven SPECS agents plus Technical Documentation (docs.py), each after one real source read.
    assert result['succeeded']==8,result
    assert len(calls)==7 and docs_calls
    assert all(store.resource(rid)['health_status']=='healthy' for rid in resources.values())
    rid=store.query('SELECT id FROM resources WHERE key=?',(docs.KEY,))[0]['id']
    assert store.resource(rid)['health_status']=='healthy'
    docs_http.close();store._db.close()


def test_missing_public_api_and_registration_validation_use_problem_details(catalog):
    _,_,client,_,_=catalog
    for method,path,kwargs,status in [('get','/api/agents/2147483647',{},404),
                                    ('post','/api/register',{'json':{'kind':'mcp','url':'https://example.com','name':'QA fixture','description':'No consent should be rejected.','category':'dev_tools'}},400)]:
        response=getattr(client,method)(path,headers={'Accept':'application/problem+json'},**kwargs)
        assert response.status_code==status and response.headers['content-type'].startswith('application/problem+json')
        assert response.json()['status']==status and response.json()['detail']


def test_weather_catalog_is_not_a_weather_forecast():
    from agent_market.concierge.task_capability import matches
    catalog=schema('find_weather_agents','Find weather forecast providers and return their connection URLs.')
    assert not matches('weather forecast for Seoul',catalog,'mcp',{'name':'Weather Marketplace'})
