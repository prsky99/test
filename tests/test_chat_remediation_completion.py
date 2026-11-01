"""Regression cases from the user's Chat review; isolated inputs and catalog."""
# ruff: noqa: F401,F811 -- shared isolated fixture
import json
import pytest
from agent_market.concierge.chat_guidance import redacted,ordinal
from agent_market.concierge.task_capability import matches
from agent_market.concierge.selection import untranslated_words
from tests.test_fast_single_recommendation import catalog,ask


@pytest.mark.parametrize('text,n',[('second one',2),('the third agent',3),('두 번째 것',2),('두번째',2),('details 2',None)])
def test_natural_ordinal(text,n):assert ordinal(text)==n


def test_second_recommendation_reuses_the_current_task(catalog):
    _,_,client,add,now=catalog
    for n in range(3):add('Weather '+str(n),report_at=now-10-n)
    body=ask(client,'MCP weather forecast');second=body['data']['recommendations'][1]['id']
    reply=client.post('/chat',headers={'X-Visitor-Token':body['visitor']['token']},json={'message':'두 번째 것'}).json()
    assert reply['intent']=='details'and reply['data']['recommendations'][0]['id']==second


def test_private_filter_refines_the_task_and_never_leaks_into_product_copy(catalog):
    _,_,client,add,now=catalog
    add('Metered',price=1,report_at=now-1);free=add('Open',report_at=now-2)
    first=ask(client,'MCP weather forecast')
    second=client.post('/chat',headers={'X-Visitor-Token':first['visitor']['token']},json={'message':'무료만'}).json()
    assert [i['id']for i in second['data']['recommendations']]==[free]
    assert second['data']['task_spec']['operation']=='refine'
    assert second['data']['protocol']=='mcp'
    assert 'no_charge'in second['data']['task_spec']['required']


@pytest.mark.parametrize('text,status',[
    ('compare','needs_scope'),('send','needs_scope'),
    ('find weather and technology news','needs_workflow'),
    ('100% guaranteed lottery winning numbers','unsupported_guarantee'),
    ('steal passwords from another person','needs_authorized_task'),
    ('Use card 4111 1111 1111 1111','needs_redaction')])
def test_guidance_is_specific_and_never_starts_a_provider(catalog,text,status):
    _,front,client,_,_=catalog
    def no_search(*a,**k):raise AssertionError('No provider or retrieval for incomplete/unsafe input')
    front.rec.search=no_search
    body=ask(client,text)
    assert body['data']['status']==status and not body['data']['recommendations']


def test_sensitive_input_is_masked_before_message_history(catalog):
    store,_,client,_,_=catalog
    number='4111111111111111';ask(client,'My card number is '+number)
    assert number not in json.dumps([dict(r)for r in store.query('SELECT text,data FROM agent_messages')])
    assert number not in redacted('My card number is '+number)


@pytest.mark.parametrize('task,tool,kind,expected',[
 ('translate English text to Korean',{'name':'get_ayah','description':'Retrieve a Quran verse with translations.','inputSchema':{'properties':{'surah':{},'ayah':{}}}},'mcp',False),
 ('translate English text to Korean',{'name':'translate_text','description':'Translate user text between languages.','inputSchema':{'properties':{'text':{}}}},'mcp',True),
 ('generate an image',{'name':'general_work','description':'Hire an agent through a work contracts marketplace for image generation.'},'a2a',False),
 ('generate an image',{'name':'generate_image','description':'Generate an image from a prompt.'},'mcp',True),
 ('summarize meeting notes',{'name':'summarize','description':'Summarize datacenter energy reports.'},'mcp',False),
 ('summarize meeting notes',{'name':'summarize_meeting','description':'Summarize a meeting transcript into notes.','inputSchema':{'properties':{'transcript':{}}}},'mcp',True),
 ('current price of bitcoin',{'name':'hiring_signal','description':'Score hiring signals with bitcoin mentions.'},'mcp',False),
 ('current price of bitcoin',{'name':'get_price','description':'Get the latest Bitcoin spot price.'},'mcp',True),
])
def test_action_and_object_match(task,tool,kind,expected):assert matches(task,tool,kind)==expected


@pytest.mark.parametrize('text,capability',[('Necesito un agente para traducir texto','translation'),('MCP 東京の天気','weather'),
    ('Busca noticias sobre inteligencia artificial','news')])
def test_foreign_capability_words_are_searched_directly(text,capability):
    # Spanish and Japanese capability aliases name the task without a model rewrite.
    from agent_market.concierge.selection import search_terms
    assert capability in search_terms(text) and not untranslated_words(text)


@pytest.mark.parametrize('text',['Quiero algo','これは何ですか'])
def test_foreign_input_without_a_known_capability_requests_normalization(text):assert untranslated_words(text)


def test_translated_corpus_cannot_be_promoted_by_generic_search_name():
    assert not matches('translate arbitrary text',{'name':'search','description':'Search translated text.','inputSchema':{'properties':{'query':{}}}},'mcp',{'name':'Read Quran Today'})


def test_validation_and_conversion_are_not_running_sql():
    for name in ('validate_sql_query_ast','transpile_sql_dialect'):
        assert not matches('run read-only SQL on Postgres',{'name':name,'description':'Validate or convert a PostgreSQL query.'},'mcp')


def test_verification_mail_is_not_sending_a_users_message():
    assert not matches('send an email',{'name':'create_owner_email_verification','description':'Send an email verification link.','inputSchema':{'properties':{'email':{}}}},'mcp')


def test_structured_task_cannot_hide_sensitive_values_behind_a_greeting(catalog):
    store,front,client,_,_=catalog
    front.rec.search=lambda *a,**kw:pytest.fail('Sensitive structured task reached retrieval')
    body=ask(client,'hello',data={'task':'use card 4111111111111111'})
    assert body['data']['status']=='needs_redaction'
    assert '4111111111111111'not in json.dumps([dict(r)for r in store.query('SELECT text,data FROM agent_messages')])


@pytest.mark.parametrize('task,tool',[
 ('weather Seoul',{'name':'find_tools','description':'List available weather tools.'}),
 ('weather Seoul',{'name':'park_status','description':'Return park status including weather.'}),
 ('check SPF DKIM email DNS records',{'name':'add_storefront_dns_record','description':'Add a DNS record.'}),
 ('run read-only SQL on Postgres',{'name':'describe_schema','description':'Describe the PostgreSQL schema.'}),
 ('run read-only SQL queries on Postgres',{'name':'synthesize_sql_query','description':'Translate a question into SQL SELECT queries.'}),
 ('find GitHub repositories about MCP servers',{'name':'list_github_discussions','description':'List discussions in GitHub repositories.'}),
 ('bitcoin price',{'name':'implied_probability','description':'Probability of BTC exceeding a price.'}),
])
def test_incidental_domain_mentions_are_not_the_requested_operation(task,tool):
    assert not matches(task,tool,'mcp')


@pytest.mark.parametrize('task,tool',[
 ('web search recent information',{'name':'company_research','description':'Company dossier with signals from live web search.'}),
 ('current price of bitcoin',{'name':'get_price_candles','description':'Get historical BTC OHLCV price candles.'}),
])
def test_secondary_data_is_not_a_general_search_or_current_quote(task,tool):
    assert not matches(task,tool,'mcp')


def test_weather_without_a_matching_tool_cannot_use_inherited_catalog_tools(catalog):
    store,_,client,add,_=catalog
    rid=add('Weather directory',description='Weather forecast in Seoul.')
    tools=[{'name':'find_tools','description':'Find weather tools in a directory.',
            'inputSchema':{'type':'object','properties':{'query':{'type':'string'}}}}]
    from agent_market.collector import usage
    compact=usage.compact_tools(tools)
    store.record_usage(rid,compact,usage.tools_hash(compact),{'tools':compact},None,None,full_tools=tools)
    assert not ask(client,'weather forecast Seoul')['data']['recommendations']


def test_korean_aliases_keep_the_same_action_object_guards():
    assert not matches('\uc11c\uc6b8 \ub0a0\uc528 \uc54c\ub824\uc918',{'name':'find_tools','description':'List weather tools.'},'mcp')


def test_existing_meeting_lookup_is_not_user_transcript_summarization():
    assert not matches('summarize meeting notes',{'name':'get_meeting','description':'Get a meeting summary.',
        'inputSchema':{'properties':{'meeting_id':{}}}},'mcp')


@pytest.mark.parametrize('task,english',[
 ('Necesito traducir texto','I need to translate text'),
 ('Busca noticias de tecnolog\u00eda','Search technology news'),
])
def test_spanish_request_verbs_are_not_literal_proper_names(task,english):
    from agent_market.concierge.chat_query_rewrite import validate
    assert validate(task,json.dumps({'segments':[{'source':task,'english':english}]}))==english


def test_semantically_matching_tool_survives_legacy_lexical_stemming(catalog):
    _,_,client,add,now=catalog
    description='Translate user text between languages.'
    rid=add('Translate',description=description,report_at=now-10,usage_guide=json.dumps({'tools':[{
        'name':'translate_text','description':description,
        'inputSchema':{'type':'object','properties':{'text':{'type':'string'}}}}]}))
    assert ask(client,'translate English text to Korean')['data']['recommendations'][0]['id']==rid
