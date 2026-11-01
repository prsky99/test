"""Bound endpoint-family projection, with citations and isolated HTTP regressions."""
import copy
import json
from urllib.parse import quote, unquote

import pytest

from agent_market.concierge.connections import bindings, project, public_agent
from tests.test_fast_single_recommendation import catalog
from tests.test_managed_agent_gateway import managed, rpc
from tests.test_mcp_proxy import WEATHER_TOOL


GATEWAY='https://agentconcierge.biz/api/gateway/mcp/8'
BASE='https://provider.example/rpc'


@pytest.mark.parametrize('url',[
    BASE, BASE+'/', BASE+'/v1/tools/call', BASE+'?token=synthetic-secret#private',
    BASE+'/v1/tools?token=synthetic-secret!#private',
    'https://PROVIDER.example:443/rpc/tools',
    'https://synthetic-user:synthetic-secret@provider.example/rpc/tools',
    'https://provider.example./rpc/tools',
    'https://provider.example/%72pc/tools',
    'https://provider.example/rpc%2ftools',
    'https://provider.example/rpc%252ftools',
    'https://provider.example/other/../rpc/tools',
    'https://provider.example/rpc\\tools',
    'https://%70rovider.example/rpc/tools',
    quote(BASE+'/tools?token=synthetic-secret',safe=''),
    quote(quote(BASE+'/tools',safe=''),safe=''),
    BASE.replace('/','\\/')+'/tools',
    r'https:\u002f\u002fprovider.example\u002frpc\u002ftools',
])
def test_known_nonroot_family_is_canonical_without_provider_suffix(url):
    assert project(url,GATEWAY,(BASE,))==GATEWAY


@pytest.mark.parametrize('url',[
    'https://provider.example/rpc-docs',
    'https://provider.example/rpc2/tools',
    'https://provider.example/rpc_',
    'https://provider.example/rpc.',
    'https://provider.example/rpc~',
    'https://provider.example/docs/latest',
    'https://provider.example/rpc/../docs/latest',
    'https://provider.example:444/rpc/tools',
    'http://provider.example/rpc/tools',
    'https://provider.example.evil.invalid/rpc/tools',
    'https://other.example/rpc/tools',
])
def test_sibling_sources_different_origins_and_lookalikes_are_unchanged(url):
    assert project(url,GATEWAY,(BASE,))==url


@pytest.mark.parametrize('text,expected',[
    ('Call `'+BASE+'/tools`.','Call `'+GATEWAY+'`.'),
    ('[Invoke]('+BASE+'/tools)','[Invoke]('+GATEWAY+')'),
    ('**'+BASE+'/tools**','**'+GATEWAY+'**'),
    ('_'+BASE+'/tools_','_'+GATEWAY+'_'),
    ('Endpoint | '+BASE+'/tools | Source','Endpoint | '+GATEWAY+' | Source'),
    ('Call '+BASE+'/tools; documentation https://provider.example/docs',
     'Call '+GATEWAY+'; documentation https://provider.example/docs'),
])
def test_markdown_and_prose_preserve_surrounding_punctuation(text,expected):
    assert project(text,GATEWAY,(BASE,))==expected


@pytest.mark.parametrize('key',['endpoint','endpoint_url','base_url','baseUrl','card_url',
    'agent_card','agent_url','usage_endpoint','rpc_url','server_url'])
def test_root_registration_projects_only_connection_field_subpaths(key):
    value={key:'https://provider.example/v1/tool?token=synthetic-secret',
           'source_url':'https://provider.example/docs/latest',
           'items':[{'url':'https://provider.example/articles/latest'}]}
    result=project(value,GATEWAY,('https://provider.example/',))
    assert result[key]==GATEWAY
    assert result['source_url']==value['source_url'] and result['items']==value['items']


def test_root_invocation_collections_override_source_context_only_when_explicit():
    value={'sources':[{'url':'https://provider.example/docs','endpoint':'https://provider.example/v1/tool'}],
           'remotes':[{'url':'https://provider.example/mcp/stream'}],
           'endpoints':{'message':'https://provider.example/a2a/messages'},
           'endpoint_override':{'url':'https://provider.example/v1/override'}}
    result=project(value,GATEWAY,('https://provider.example/',))
    assert result['sources'][0]=={'url':'https://provider.example/docs','endpoint':GATEWAY}
    assert result['remotes'][0]['url']==GATEWAY
    assert result['endpoints']['message']==GATEWAY and result['endpoint_override']['url']==GATEWAY


def test_explicit_citations_under_nonroot_family_remain_sources_not_fake_endpoints():
    base='https://provider.example/project'
    source=base+'/docs/source-paper'
    value={'endpoint':base+'/tools/search?api_key=synthetic',
           'citations':[{'url':source}],
           'source_url':source,'documentation_url':source,
           'text':'Unlabeled '+base+'/tools/search'}
    result=project(value,GATEWAY,(base,))
    assert result['endpoint']==GATEWAY and result['text']=='Unlabeled '+GATEWAY
    assert result['citations']==value['citations']
    assert result['source_url']==result['documentation_url']==source


@pytest.mark.parametrize('encode',[json.dumps,lambda value:json.dumps(json.dumps(value))])
def test_nested_json_citation_purpose_preserves_descendant_source_links(encode):
    base='https://provider.example/project';source=base+'/docs/paper'
    value={'endpoint':base+'/tools/search','sources':[{'url':source}],
           'citations':{'reference':{'url':source}}}
    wire=project(encode(value),GATEWAY,(base,))
    decoded=json.loads(wire)
    if isinstance(decoded,str):decoded=json.loads(decoded)
    assert decoded=={**value,'endpoint':GATEWAY}


def test_exact_known_binding_cannot_be_hidden_by_a_citation_label():
    value={'citations':[{'url':BASE}], 'source_url':BASE+'?token=synthetic'}
    assert project(value,GATEWAY,(BASE,))=={'citations':[{'url':GATEWAY}],'source_url':GATEWAY}


def test_credentialed_descendant_source_is_redacted_and_never_treated_as_execution_authority():
    base='https://provider.example/project'
    value={'citations':[{'url':'https://synthetic:private-marker@provider.example/project/docs/paper'}]}
    assert project(value,GATEWAY,(base,))=={'citations':[{'url':'[REDACTED]'}]}


@pytest.mark.parametrize('text,expected',[
    ('Call https://provider.example/v1/tool','Call '+GATEWAY),
    ('Connect to https://provider.example/v1/tool','Connect to '+GATEWAY),
    ('[Endpoint](https://provider.example/v1/tool)','[Endpoint]('+GATEWAY+')'),
    ('Docs https://provider.example/docs','Docs https://provider.example/docs'),
    ('Call this agent; source https://provider.example/docs','Call this agent; source https://provider.example/docs'),
    ('Documentation https://provider.example/docs; endpoint https://provider.example/v1/tool',
     'Documentation https://provider.example/docs; endpoint '+GATEWAY),
    ('Related https://provider.example/v1/tool','Related https://provider.example/v1/tool'),
])
def test_root_prose_uses_nearest_explicit_purpose_and_retains_ambiguous_links(text,expected):
    assert project(text,GATEWAY,('https://provider.example/',))==expected


@pytest.mark.parametrize('layers',[1,2,3])
def test_encoded_json_preserves_wire_format_and_connection_field_context(layers):
    original={'endpoint':'https://provider.example/v1/tool?secret=synthetic',
              'source_url':'https://provider.example/docs/latest'}
    wire=json.dumps(original)
    for _ in range(layers):wire=quote(wire,safe='')
    result=project(wire,GATEWAY,('https://provider.example/',))
    for _ in range(layers):result=unquote(result)
    assert json.loads(result)=={**original,'endpoint':GATEWAY}


def test_nested_json_and_slash_escaping_preserve_independent_citations():
    source='https://provider.example/docs/latest'
    wire=json.dumps(json.dumps({'endpoint':BASE+'/tools','url':source})).replace('/','\\/')
    projected=project(wire,GATEWAY,(BASE,))
    assert json.loads(json.loads(projected))=={'endpoint':GATEWAY,'url':source}


def test_nested_query_binding_is_projected_without_changing_source_origin():
    value='https://sources.example/article?endpoint='+quote(BASE+'/tools?secret=synthetic',safe='')
    assert project(value,GATEWAY,(BASE,))=='https://sources.example/article?endpoint='+GATEWAY


def test_nested_query_connection_context_does_not_become_a_blanket_root_rule():
    endpoint='https://provider.example/v1/tool'
    doc='https://provider.example/docs/latest'
    prefix='https://sources.example/article?'
    assert project(prefix+'endpoint='+quote(endpoint,safe=''),GATEWAY,('https://provider.example/',))==prefix+'endpoint='+GATEWAY
    assert project(prefix+'source='+quote(doc,safe=''),GATEWAY,('https://provider.example/',))==prefix+'source='+quote(doc,safe='')


def test_projected_url_keys_do_not_leak_or_overwrite_colliding_values():
    value={BASE+'/first':{'value':1},BASE+'/second':{'value':2},GATEWAY:{'value':3},
           '[Projected connection key 1]':{'value':4}}
    result=project(value,GATEWAY,(BASE,))
    assert len(result)==4 and sorted(v['value'] for v in result.values())==[1,2,3,4]
    assert BASE not in json.dumps(result)
    assert project(result,GATEWAY,(BASE,))==result


def test_registered_alternate_bindings_and_public_connection_fields_project():
    resource={'id':8,'kind':'mcp','url':BASE,
        'gateway_bound_urls':['https://alternate.example/v2/mcp'],
        'details':json.dumps({'remotes':[{'url':'https://remote.example/stream'}],
                              'endpoint_override':{'url':'https://override.example/api'}}),
        'usage_guide':{'endpoints':{'jsonrpc':'https://rpc.example/v1'},
                       'agent_card':'https://card.example/.well-known/agent-card.json'}}
    expected={BASE,'https://alternate.example/v2/mcp','https://remote.example/stream',
              'https://override.example/api','https://rpc.example/v1','https://card.example/.well-known/agent-card.json'}
    assert bindings(resource)==expected
    value={'id':8,'kind':'mcp','url':'https://unlisted.example/mcp',
           'usage_endpoint':'https://unlisted.example/stream','agent_url':'https://unlisted.example/agent',
           'description':'Endpoints '+', '.join(url+'/subpath' for url in expected)}
    result=public_agent(value,resource)
    assert result['url']==result['usage_endpoint']==result['agent_url']==GATEWAY
    assert result['connection_available'] is True
    for url in expected:assert url not in result['description']


def test_binding_metadata_handles_uppercase_schemes_and_unusable_extra_container():
    assert bindings({'url':'HTTPS://Provider.Example:443/rpc','gateway_bound_urls':None})=={'HTTPS://Provider.Example:443/rpc'}
    assert project('https://provider.example/rpc/tools',GATEWAY,bindings({'url':'HTTPS://Provider.Example:443/rpc'}))==GATEWAY


@pytest.mark.parametrize('url',[
    'https://synthetic-user:synthetic-private-marker@sources.example/article',
    'https://provider.example@evil.invalid/rpc/tools',
    'https://synthetic-user@sources.example/article',
    'https://:synthetic-private-marker@sources.example/article',
    'https://synthetic-user:synthetic-private-marker@sources.example:bad/article',
    'https://synthetic-user:synthetic-private-marker@[malformed/article',
    quote('https://synthetic-user:synthetic-private-marker@sources.example/article',safe=''),
    r'https:\u002f\u002fsynthetic-user:synthetic-private-marker@sources.example/article',
    'http://synthetic-user:synthetic-private-marker@localhost/private',
])
def test_unbound_credentialed_urls_are_wholly_redacted_even_in_source_context(url):
    value={'source_url':url,'documentation_url':'https://sources.example/documentation'}
    result=project(value,GATEWAY,(BASE,))
    assert result['source_url']=='[REDACTED]'
    assert result['documentation_url']==value['documentation_url']
    assert 'synthetic-private-marker' not in json.dumps(result)


@pytest.mark.parametrize('value',[
    {'endpoint':'https://provider.example:bad/rpc/tools'},
    {'endpoint':'https://[malformed/rpc/tools'},
    {'remotes':[{'url':'https://provider.example:999999/rpc/tools'}]},
    {'base_url':'https://provider.example:bad/rpc/tools'},
    {'text':'Endpoint https://provider.example:bad/rpc/tools'},
    {'text':'Invoke `https://provider.example:bad/rpc/tools`.'},
])
def test_malformed_explicit_connection_urls_are_redacted_without_inventing_targets(value):
    result=project(value,GATEWAY,(BASE,))
    assert '[REDACTED]' in json.dumps(result)
    assert 'provider.example' not in json.dumps(result) and '[malformed' not in json.dumps(result)
    assert GATEWAY not in json.dumps(result)


def test_malformed_unmarked_noncredentialed_prose_remains_a_bounded_limit():
    value='Related https://provider.example:bad/rpc/tools'
    assert project(value,GATEWAY,(BASE,))==value
    assert project('Source https://provider.example:bad/docs',GATEWAY,(BASE,))=='Source https://provider.example:bad/docs'


def test_literal_at_in_source_path_or_query_is_not_treated_as_url_userinfo():
    value='https://sources.example/authors/@public?query=hello@example.org'
    assert project(value,GATEWAY,(BASE,))==value


def descriptor(name='get_docs',schema=None):
    return {'name':name,'description':'Search public documentation',
            'inputSchema':schema or {'type':'object','properties':{'topic':{'type':'string'}}}}


@pytest.mark.parametrize('constraint',[
    {'const':BASE}, {'enum':[BASE,'other']},
    {'type':'object','properties':{BASE:{'type':'string'}},'required':[BASE]},
    {'const':'https://synthetic:private-marker@sources.example/article'},
    {'const':{'token':'synthetic-secret'}},
    {'enum':['Bearer synthetic-secret']},
])
def test_private_schema_literals_omit_whole_tool_without_fabricating_constraints(constraint):
    schema={'type':'object','properties':{'target':constraint}}
    tool=descriptor(schema=schema);original=copy.deepcopy(tool)
    assert project([tool],GATEWAY,(BASE,))==[]
    assert tool==original


def test_unbound_uri_and_literal_ref_constraints_keep_exact_validation_semantics():
    schema={'type':'object','properties':{
        '$ref':{'type':'string'},
        'source':{'const':'https://sources.example/paper'},
        'literal':{'enum':[{'$ref':'ordinary-data','default':'ordinary-data'}]},
        'serialized':{'const':'{"key":1}'}},'required':['$ref']}
    tool=descriptor(schema=schema)
    assert project([tool],GATEWAY,(BASE,))==[tool]


@pytest.mark.parametrize('output',[
    {'type':'array','items':{'type':'string'}},
    {'$ref':'https://schemas.example/output'},
])
def test_output_schemas_keep_their_own_shape_without_input_object_admission(output):
    tool={**descriptor(),'outputSchema':output}
    assert project([tool],GATEWAY,(BASE,))==[tool]


@pytest.mark.parametrize('output',[
    {'type':'array','items':{'const':BASE}},
    {'$ref':BASE+'/schema'},
])
def test_output_binding_literals_and_uris_omit_tool_instead_of_mutating_output_schema(output):
    tool={**descriptor(),'outputSchema':output};original=copy.deepcopy(tool)
    assert project([tool],GATEWAY,(BASE,))==[] and tool==original


def test_schema_uri_annotations_are_omitted_but_named_arguments_remain_intact():
    schema={'type':'object','$schema':BASE+'/schema','$id':BASE+'/id','$anchor':'input',
        'properties':{'$id':{'type':'string','$id':BASE+'/property-id'},'$schema':{'type':'string'},
                      '$ref':{'type':'string'}},'required':['$ref'],
        'description':'Endpoint '+BASE+'/tools'}
    tool=descriptor(schema=schema);expected=copy.deepcopy(tool)
    expected['inputSchema']={'type':'object','properties':{'$id':{'type':'string'},'$schema':{'type':'string'},
        '$ref':{'type':'string'}},'required':['$ref'],'description':'Endpoint '+GATEWAY}
    assert project([tool],GATEWAY,(BASE,))==[expected]


@pytest.mark.parametrize('key',['params','parameters'])
def test_compact_parameter_maps_preserve_ref_named_arguments(key):
    tool={'name':'get_docs',key:{'$ref':{'type':'string'},'type':{'type':'string'},'properties':{'type':'string'}},'required':['$ref']}
    assert project([tool],GATEWAY,(BASE,))==[tool]


@pytest.mark.parametrize('schema',[
    {'type':'object','$ref':BASE+'/schema'},
    {'type':'object','$ref':'#/$defs/local'},
    {'type':'object','properties':{'topic':{'$dynamicRef':BASE+'/schema'}}},
    {'type':'object','properties':{'topic':{'$recursiveRef':'#local'}}},
    {'type':'object','properties':{'topic':{'type':'string','pattern':'.*'}}},
])
def test_unsupported_executable_schemas_are_omitted_not_boolean_roots(schema):
    assert project({'tools_schema':[descriptor(schema=schema)]},GATEWAY,(BASE,))=={'tools_schema':[]}


def test_plain_user_data_outside_tool_metadata_lists_is_not_reinterpreted_as_a_schema():
    value={'records':[{'name':'ordinary','inputSchema':{'$ref':'ordinary-data'}}],
           'arguments':{'$ref':'ordinary-data','$schema':'ordinary-data'},
           'payload':{'$dynamicRef':'ordinary-data'}}
    assert project(value,GATEWAY,(BASE,))==value


def test_public_agent_keeps_tool_names_aligned_with_surviving_literal_safe_schemas():
    safe=descriptor('get_public')
    hidden=descriptor('get_private',{'type':'object','properties':{'target':{'const':BASE}}})
    value={'id':8,'kind':'mcp','url':BASE,'tools':['get_private','get_public'],'tools_schema':[hidden,safe]}
    original=copy.deepcopy(value);result=public_agent(value)
    assert result['tools']==['get_public'] and result['tools_schema']==[safe]
    assert value==original


def test_tools_list_keeps_object_schema_shape_omits_refs_and_denied_execution_never_fetches(managed,monkeypatch):
    store,_,client,_,rid,calls,remote=managed
    original=store.resource(rid)['url'];valid=copy.deepcopy(WEATHER_TOOL)
    unsafe={**copy.deepcopy(WEATHER_TOOL),'name':'get_reference','inputSchema':{'type':'object','$ref':original+'/schema'}}
    remote.tools=[valid,unsafe]
    # The pinned complete contract is authoritative; compact and full lists change together.
    from agent_market.capability_registry import full_tools, digest
    with store.tx() as db:db.execute('UPDATE resources SET usage_tools=?,usage_full_tools=?,usage_full_hash=? WHERE id=?',
                                     (json.dumps(remote.tools),json.dumps(remote.tools),digest(full_tools(remote.tools)),rid))
    monkeypatch.setattr('socket.getaddrinfo',lambda *_args,**_kwargs:pytest.fail('Schema metadata and denial must not fetch URLs'))
    response=rpc(client,f'/api/gateway/mcp/{rid}','tools/list')
    assert response.status_code==200
    tools=response.json()['result']['tools'];assert [tool['name'] for tool in tools]==['get_weather']
    assert isinstance(tools[0]['inputSchema'],dict) and tools[0]['inputSchema']['type']=='object'
    assert original not in response.text
    denied=rpc(client,f'/api/gateway/mcp/{rid}','tools/call',{'name':'get_reference','arguments':{}})
    assert denied.json()['error']['code']==-32602 and not calls
    assert store.resource(rid)['url']==original


@pytest.mark.parametrize('entry',['testbench','gateway','legacy'])
def test_public_http_result_hides_provider_subpaths_but_keeps_shared_origin_sources(managed,entry):
    store,_,client,_,rid,calls,remote=managed
    original=store.resource(rid)['url'];source=original.rsplit('/',1)[0]+'/docs/current';descendant_source=original+'/docs/paper'
    remote.call_result={'content':[{'type':'text','text':'Call '+original+'/v1/tools?token=synthetic-secret; source '+source}],
                        'structuredContent':{'endpoint':original+'/stream?token=synthetic-secret','source_url':source,
                                             'citations':[{'url':descendant_source}]}}
    if entry=='testbench':response=client.post('/api/test/execute',json={'resource_id':rid,'tool':'get_weather','arguments':{'city':'Tokyo'}})
    elif entry=='gateway':response=rpc(client,f'/api/gateway/mcp/{rid}','tools/call',{'name':'get_weather','arguments':{'city':'Tokyo'}})
    else:response=rpc(client,'/mcp','tools/call',{'name':'call','arguments':{'resource_id':rid,'tool':'get_weather','arguments':{'city':'Tokyo'}}})
    assert response.status_code==200 and source in response.text and descendant_source in response.text
    assert original+'/v1/tools' not in response.text and original+'/stream' not in response.text
    assert 'synthetic-secret' not in response.text
    assert store.resource(rid)['url']==original
    assert sum(json.loads(call.content).get('method')=='tools/call' for call in calls)==1


@pytest.mark.parametrize('entry',['testbench','gateway','legacy'])
def test_public_http_result_removes_unbound_url_credentials_and_malformed_endpoint(managed,entry):
    store,_,client,_,rid,calls,remote=managed
    source='https://sources.example/documentation'
    remote.call_result={'content':[{'type':'text','text':'Source https://synthetic-user:synthetic-private-marker@sources.example/article; endpoint https://bad-target.example:invalid/rpc; source '+source}],
                        'structuredContent':{'endpoint':'https://bad-target.example:invalid/rpc',
                            'source_url':'https://synthetic-user:synthetic-private-marker@sources.example/article','citation_url':source}}
    if entry=='testbench':response=client.post('/api/test/execute',json={'resource_id':rid,'tool':'get_weather','arguments':{'city':'Tokyo'}})
    elif entry=='gateway':response=rpc(client,f'/api/gateway/mcp/{rid}','tools/call',{'name':'get_weather','arguments':{'city':'Tokyo'}})
    else:response=rpc(client,'/mcp','tools/call',{'name':'call','arguments':{'resource_id':rid,'tool':'get_weather','arguments':{'city':'Tokyo'}}})
    assert response.status_code==200 and source in response.text
    for private in ('synthetic-user','synthetic-private-marker','bad-target.example'):assert private not in response.text
    assert '[REDACTED]' in response.text
    assert sum(json.loads(call.content).get('method')=='tools/call' for call in calls)==1
