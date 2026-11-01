"""Original contracts, ordering and topic/region admission use disposable data."""
from copy import deepcopy
import json

import pytest

from agent_market.capability_registry import digest, full_tools, Registry
from agent_market.collector import usage
from agent_market.concierge.execution_policy import tools_for, validate_arguments, ExecutionDenied
from agent_market.concierge.selection import _advertised_tools
from agent_market.owned_data_agents.catalog import tool_spec
from tests.test_fast_single_recommendation import catalog  # noqa: F401
from tests.test_managed_agent_gateway import managed  # noqa: F401


def registered(tools):
    full = full_tools(tools)
    compact = usage.compact_tools(tools)
    return {'kind':'mcp', 'usage_tools':json.dumps(compact),
            'usage_tools_hash':usage.tools_hash(compact),
            'usage_full_tools':json.dumps(full), 'usage_full_hash':digest(full),
            'usage_guide':json.dumps({'tools':compact})}


def test_complete_contract_survives_compact_guide_without_losing_bounds():
    spec = tool_spec('technology-news')
    resource = registered([spec])
    assert _advertised_tools(resource) == [spec]
    assert tools_for(resource) == [spec]
    with pytest.raises(ExecutionDenied):
        validate_arguments(tools_for(resource)[0], {'query':'a'*161, 'limit':3})


@pytest.mark.parametrize('change', ['full-hash','full-contract','compact-contract','malformed','duplicate'])
def test_inconsistent_contracts_fail_closed(change):
    spec = tool_spec('technology-news')
    resource = registered([spec])
    if change == 'full-hash':resource['usage_full_hash'] = '0'*64
    if change == 'full-contract':
        spec['inputSchema']['properties']['query']['maxLength'] = 1000
        resource['usage_full_tools'] = json.dumps([spec])
    if change == 'compact-contract':resource['usage_tools'] = '[]'
    if change == 'malformed':resource['usage_full_tools'] = '{'
    if change == 'duplicate':resource['usage_full_tools'] = json.dumps([spec,spec])
    assert not tools_for(resource) and not _advertised_tools(resource)


def test_legacy_compact_metadata_is_not_mislabeled_as_a_complete_schema():
    resource = registered([tool_spec('technology-news')])
    del resource['usage_full_tools']
    assert 'inputSchema' not in tools_for(resource)[0]
    assert 'maxLength' not in tools_for(resource)[0]['params']['query']


def test_snake_case_news_search_is_recommended_with_original_schema(catalog):
    store,front,_,add,_ = catalog
    spec = tool_spec('technology-news')
    rid = add('Technology News', description=spec['description'])
    compact = usage.compact_tools([spec])
    store.record_usage(rid,compact,usage.tools_hash(compact),{'tools':compact},None,None,full_tools=[spec])
    items = front.rec.search('technology news search', kind='mcp', limit=3)
    assert [i['id']for i in items] == [rid]
    assert items[0]['tools_schema'][0]['inputSchema'] == spec['inputSchema']


def test_general_weather_does_not_select_betting_tool_or_foreign_region(catalog):
    store,front,_,add,_ = catalog
    def add_tools(name,tools):
        rid = add(name, description='Global weather and financial information.')
        compact = usage.compact_tools(tools)
        store.record_usage(rid,compact,usage.tools_hash(compact),{},None,None,full_tools=tools)
        return rid
    base = {'inputSchema':{'type':'object','properties':{'location':{'type':'string'}}},
            'annotations':{'readOnlyHint':True}}
    add_tools('Regional Markets', [{**base,'name':'kalshi_weather_edge',
        'description':'Prices Kalshi temperature markets against the NWS forecast.'}])
    add_tools('Regional Forecast', [{**base,'name':'get_forecast',
        'description':'Weather forecast for a point. US only, from the National Weather Service.'}])
    good = add_tools('Global Forecast', [{**base,'name':'get_weather',
        'description':'Current weather and multi-day forecast for any location.'}])
    items = front.rec.search('weather forecast Seoul',kind='mcp',limit=3)
    assert [i['id']for i in items] == [good]


def test_news_query_chooses_search_instead_of_company_dossier(catalog):
    store,front,_,add,_ = catalog
    tools = [
        {'name':'company_research','description':'Company dossier: recent news from web search and technologies.',
         'inputSchema':{'type':'object','properties':{'domain':{'type':'string'}}}},
        {'name':'search_news','description':'Search recent technology news by keywords.',
         'inputSchema':{'type':'object','properties':{'query':{'type':'string'}}}}]
    rid = add('Technology News',description='Search technology news and research companies.')
    compact=usage.compact_tools(tools)
    store.record_usage(rid,compact,usage.tools_hash(compact),{},None,None,full_tools=tools)
    items=front.rec.search('technology news search',kind='mcp',limit=3)
    assert items and items[0]['tools']==['search_news']


def test_remote_tool_order_is_not_schema_drift_and_does_not_repin(managed):
    store,_,client,_,rid,calls,remote=managed
    tools=[deepcopy(remote.tools[0]),{'name':'get_status','description':'Read service status.',
        'inputSchema':{'type':'object','properties':{}}}]
    compact=usage.compact_tools(list(reversed(tools)))
    store.record_usage(rid,compact,usage.tools_hash(compact),{},None,None,full_tools=tools)
    remote.tools=tools
    before=store.resource(rid);version=Registry(store).current(before)
    response=client.post('/api/test/execute',json={'resource_id':rid,'tool':'get_weather','arguments':{'city':'Seoul'}})
    assert response.json()['execution_succeeded'],response.text
    after=store.resource(rid)
    assert after['usage_tools_hash']==before['usage_tools_hash']
    assert after['health_status']!='quarantined'
    assert Registry(store).current(after)['id']==version['id']
    assert sum(json.loads(r.content).get('method')=='tools/call'for r in calls)==1


def test_specialized_news_is_not_general_or_cross_topic_news():
    from agent_market.concierge.task_requirements import news_scope_matches
    from agent_market.concierge.selection import search_terms
    tool=tool_spec('technology-news')
    resource={'name':'Technology News','description':tool['description']}
    assert news_scope_matches(search_terms('AI news'),resource,[tool])
    assert not news_scope_matches(search_terms('world news search'),resource,[tool])
    assert not news_scope_matches(search_terms('sports news search'),resource,[tool])
    assert not news_scope_matches(search_terms('technology and sports news'),resource,[tool])


def test_general_news_requires_a_real_topic_input_not_only_search_prose():
    from agent_market.concierge.task_requirements import queryable_news
    tool={'name':'company_research','description':'Search recent company news.',
          'inputSchema':{'type':'object','properties':{'domain':{'type':'string'}}}}
    assert not queryable_news({'name':'Dossier'},[tool])


@pytest.mark.parametrize('schema',[True,False,{'properties':[{}]}])
def test_malformed_news_schema_cannot_crash_scope_checks(schema):
    from agent_market.concierge.task_requirements import queryable_news
    assert not queryable_news({'name':'News'},[{'name':'search_news','inputSchema':schema}])


def test_a2a_news_skill_accepts_a_natural_language_subject_without_mcp_schema():
    from agent_market.concierge.task_requirements import queryable_news
    skill={'name':'News Search','description':'Search recent news articles by keywords.'}
    assert queryable_news({'kind':'a2a','name':'News Search'},[skill])
    assert not queryable_news({'kind':'mcp','name':'News Search'},[skill])
