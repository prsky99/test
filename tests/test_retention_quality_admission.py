"""Real retained failures become hard negatives without weakening evidence gates."""
import json
from agent_market.concierge.selection import search_terms,capability_terms,task_scope_matches
from agent_market.concierge.task_requirements import input_requirements_match,recommendation_identity
from tests.test_selection_capability_rules import resource,admits


def test_ai_abbreviation_survives_retrieval_and_does_not_mean_crypto_ai_written():
    assert search_terms('ai news')==['artificial','intelligence','news']
    assert capability_terms('AI news')==['news']
    crypto=resource('Crypto news scored by market impact.',[{'name':'Top stories','description':'Latest crypto news with tickers and sentiment.'},{'name':'Market digest','description':'AI-written market digest.'}])
    assert not admits('ai news',crypto)
    local=resource('Digital Ethiopia platform.',[{'name':'Amharic news','description':'Latest headlines in Amharic.'}])
    assert not admits('AI news',local)


def test_general_queryable_news_and_specific_subject_are_both_eligible():
    search=resource('Independent web and news search.',[{'name':'News Search','description':'Search recent news articles by keywords.'}])
    assert admits('AI news',search)
    assert admits('sports news',search)
    tech=resource('Global technology news.',[{'name':'Global Tech News','description':'Latest AI and cloud news.'}])
    assert admits('AI news',tech)
    assert not admits('sports news',tech)


def test_news_about_ai_not_ai_generated_broad_local_digest():
    item=resource('News produced by an AI-powered assistant.',[{'name':'Headlines','description':'General top stories, no search input.'}])
    assert not admits('ai news',item)


def test_no_api_key_is_a_technical_constraint_not_a_price_preference():
    keyed=resource('Weather forecast.',[{'name':'Forecast','description':'Weather forecast for a location.'}]);keyed.update(auth_observed=1)
    assert not input_requirements_match('weather without an API key',keyed)
    assert input_requirements_match('weather',keyed)
    open_agent={**keyed,'auth_observed':0,'auth_type':None}
    assert input_requirements_match('weather without an API key',open_agent)
    assert input_requirements_match('weather at any price',keyed)


def test_mirrored_listing_identity_does_not_depend_on_record_or_url():
    one=resource('General news search.',[{'name':'Search','description':'Search news.'}],name='News Agent')
    two={**one,'id':22,'url':'https://mirror.example/a2a'}
    assert recommendation_identity(one)==recommendation_identity(two)
    assert recommendation_identity(one)!=recommendation_identity({**one,'name':'Another independent agent'})

from tests.test_fast_single_recommendation import catalog,ask


def test_mirrored_agents_fill_remaining_choices_without_duplicates(catalog):
    store,front,_,add,now=catalog
    first=add('Mirror Forecast',kind='a2a',report_at=now-1)
    second=add('Mirror Forecast copy',kind='a2a',report_at=now-2)
    third=add('Independent Forecast',kind='a2a',report_at=now-3)
    with store.tx() as db:db.execute('UPDATE resources SET name=? WHERE id=?',('Mirror Forecast',second))
    values=front.rec.search('weather forecast',kind='a2a',limit=3)
    assert [x['id']for x in values]==[first,third]
    assert [x['id']for x in front.rec.search('weather forecast',kind='a2a',limit=3,offset=1)]==[third]


def test_vague_ai_request_asks_for_a_task_instead_of_arbitrary_matches(catalog):
    _,_,client,add,now=catalog
    add('AI chatbot',kind='a2a',report_at=now-1)
    response=ask(client,'recommend an AI agent')
    assert response['data']['status']=='needs_task'
    assert not response['data']['recommendations']


def test_no_key_constraint_is_applied_before_freshness_ranking(catalog):
    _,front,_,add,now=catalog
    add('Keyed forecast',kind='mcp',report_at=now-1,auth_observed=1)
    available=add('Open forecast',kind='mcp',report_at=now-5)
    values=front.rec.search('weather forecast without an API key',kind='mcp',limit=3)
    assert [x['id']for x in values]==[available]


def test_provider_onboarding_is_not_general_software_documentation_search():
    from agent_market.concierge.task_requirements import documentation_scope_matches
    one=resource('Onboard to Smarter Weather: docs, plans, API keys.',[{'name':'get_documentation','description':'Search Smarter Weather developer documentation.'}],name='Smarter Weather Developer Onboarding')
    assert not documentation_scope_matches(search_terms('search official software documentation with sources'),one)
    assert documentation_scope_matches(search_terms('Smarter Weather documentation'),one)
    site=resource('Read-only index of public documentation and section pages on life.ayushrai.site.',[{'name':'read_doc','description':'Find documentation pages matching a query.'}],name='life.ayushrai.site docs MCP')
    assert not documentation_scope_matches(search_terms('documentation search'),site)


def test_recommendations_refuse_known_unexecutable_or_quarantined_bindings():
    from agent_market.concierge.task_requirements import supported_discovery_connection as accepts
    assert accepts({'kind':'a2a','url':'https://example.com/a2a','usage_guide':{'binding':'JSONRPC'}})
    assert not accepts({'kind':'a2a','usage_guide':{'binding':'HTTP+JSON'}})
    assert not accepts({'kind':'a2a','eval_security':'review'})
    assert not accepts({'kind':'a2a','url':'https://example.com/a2a','usage_guide':{'endpoint':'http://127.0.0.1/'}})


def test_no_response_placeholder_is_not_a_completed_task():
    from agent_market.concierge.result_quality import usable_a2a_parts
    for value in ('','[]','[MCP \uc751\ub2f5 \uc5c6\uc74c]','No response','[No response from MCP]','null'):
        assert not usable_a2a_parts([{'kind':'text','text':value}])
    assert usable_a2a_parts([{'kind':'text','text':'No articles matched your query. Try a broader topic.'}])
    assert usable_a2a_parts([{'kind':'data','data':{'results':[]}}])
    assert usable_a2a_parts([{'kind':'text','text':'Forecast: 18 C.'}])


def test_known_non_answer_samples_do_not_get_promoted_as_executable_agents():
    from agent_market.concierge.task_requirements import supported_discovery_connection as accepts
    base={'kind':'a2a','usage_guide':{'binding':'JSONRPC'}}
    assert not accepts({**base,'trial_info':json.dumps({'ok':True,'sample_output':'[MCP \uc751\ub2f5 \uc5c6\uc74c]'})})
    assert not accepts({**base,'trial_info':{'sample_output':"Sorry, I can't respond to your query directly. Use the mcp tools to interact."}})
    assert accepts({**base,'trial_info':{'sample_output':'No matching articles. Try a broader topic.'}})


def test_a2a_discovery_only_tool_is_not_a_weather_execution_capability():
    item=resource('Authoritative US seven-day weather forecast.',[{'name':'Buy weather data','description':'Discover x402 forecast routes. A2A is discovery-only and never retrieves weather data.'}])
    assert not admits('weather forecast',item)


def test_generic_docs_search_does_not_mean_any_vendor_docs_or_single_framework():
    one=resource('Svelte 5 and SvelteKit documentation.',[{'name':'get_documentation','description':'Search Svelte documentation.'}],kind='mcp',name='Svelte MCP')
    assert not admits('Find official software documentation with sources',one)
    assert admits('Svelte documentation',one)


def test_marine_forecast_is_not_an_inland_city_weather_answer():
    one=resource('Recreational marine navigation and weather forecasts for the Mediterranean.',[{'name':'Marine Forecast','description':'Weather forecast at any coordinate.'}])
    assert not admits('weather forecast for Seoul',one)
    assert admits('marine weather forecast',one)


def test_canned_protocol_ack_is_not_news_but_health_ping_is_allowed():
    from agent_market.concierge.result_quality import usable_a2a_parts
    for parts in ([{'text':'pong'}],[{'text':'{"response":"pong","status":"ok"}'}],[{'data':{'response':'pong','status':'ok'}}],[{'data':{'findings':'Node executed task deterministically with 100% schema conformance.'}}]):
        assert not usable_a2a_parts(parts,'Find current AI news')
    assert usable_a2a_parts([{'text':'pong'}],'ping')
    assert usable_a2a_parts([{'text':'{"results":[]}'}],'Search AI news')


def test_a2a_handshake_alone_does_not_displace_a_tested_task_provider(catalog):
    _,front,_,add,now=catalog
    add('Only a card',kind='a2a',health_at=now)
    tested=add('Measured Forecast',kind='mcp',report_at=now-5)
    assert [r['id']for r in front.rec.search('weather forecast',limit=3)]==[tested]


def test_query_input_does_not_turn_a_technology_feed_into_sports_news():
    one=resource('Search technology news through Hacker News.',[{'name':'search_technology_news','description':'Search technology news by keywords.','inputSchema':{'type':'object','properties':{'query':{'type':'string'}}}}],kind='mcp',name='Technology News')
    assert admits('AI news',one)
    assert not admits('sports news',one)
