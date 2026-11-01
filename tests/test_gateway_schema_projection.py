"""Runnable schema admission and public projection preserve offline semantics."""
import copy
import json
from unittest.mock import Mock

import pytest

from agent_market.concierge.connections import project, gateway_agent_url
from agent_market.concierge.execution_policy import (
    ExecutionDenied, safe_registered_tool, supported_schema, validate_arguments,
)
from agent_market.concierge.recommendation_security import public_schema
from agent_market.collector import usage
from tests.test_managed_agent_gateway import managed, catalog, rpc
from tests.test_single_recommendation_security_audit import request as discover


def tool(schema):
    return {'name':'get_weather', 'description':'Read public weather forecast',
            'annotations':{'readOnlyHint':True}, 'inputSchema':schema}


UNSUPPORTED = [
    False, True, 'not a schema', [],
    {'$ref':'https://provider.example/schema'},
    {'type':'object','properties':{'query':{'$ref':'https://provider.example/schema'}}},
    {'type':'object','$dynamicRef':'https://provider.example/schema'},
    {'type':'object','properties':{'query':{'type':'string','pattern':'(a+)+$'}}},
    {'type':'object','patternProperties':{'(a+)+$':{'type':'string'}}},
    {'type':'object','required':'query'},
    {'type':'object','properties':{'query':{'type':'not-a-type'}}},
    {'type':'object','description':'x'*24001},
]


@pytest.mark.parametrize('schema', UNSUPPORTED)
def test_schema_guard_and_argument_validation_share_the_same_offline_refusal(schema, monkeypatch):
    lookup=Mock(side_effect=AssertionError('Schema checks must not perform DNS or fetches'))
    monkeypatch.setattr('socket.getaddrinfo', lookup)
    spec=tool(schema)
    assert not safe_registered_tool(spec)
    with pytest.raises(ExecutionDenied):supported_schema(spec)
    with pytest.raises(ExecutionDenied):validate_arguments(spec,{})
    assert not lookup.called


@pytest.mark.parametrize('field', ['$ref','pattern','patternProperties','$schema','$id','$anchor','default'])
def test_schema_keyword_names_remain_ordinary_required_properties(field):
    schema={'type':'object','properties':{field:{'type':'string'}},'required':[field], 'additionalProperties':False}
    spec=tool(schema)
    assert safe_registered_tool(spec)
    validate_arguments(spec,{field:'literal value'})
    published=public_schema(spec)['inputSchema']
    assert published==schema
    with pytest.raises(ExecutionDenied):validate_arguments(spec,{field:7})


def test_literal_enum_and_const_objects_are_not_executable_schema_nodes():
    literal={'$ref':'literal reference text','pattern':'literal pattern text','$id':'literal identifier'}
    schema={'type':'object','properties':{'data':{'const':literal},'choice':{'enum':[literal]}},'required':['data','choice']}
    spec=tool(schema)
    assert safe_registered_tool(spec)
    validate_arguments(spec,{'data':literal,'choice':literal})
    assert public_schema(spec)['inputSchema']==schema
    with pytest.raises(ExecutionDenied):validate_arguments(spec,{'data':{},'choice':literal})


def test_actual_uri_annotations_are_omitted_without_changing_property_names_or_literals():
    schema={'type':'object','$schema':'https://json-schema.org/draft/2020-12/schema',
            '$id':'https://provider.example/private/schema', '$anchor':'top',
            'properties':{'$id':{'type':'string','$id':'https://provider.example/private/child',
                                  'enum':['ordinary identifier']},
                          'literal':{'const':{'$schema':'literal schema text','$id':'literal id'}}},
            'required':['$id','literal']}
    frozen=copy.deepcopy(schema)
    published=public_schema(schema,context='schema')
    assert set(published)=={'type','properties','required'}
    assert published['properties']['$id']=={'type':'string','enum':['ordinary identifier']}
    assert published['properties']['literal']['const']==schema['properties']['literal']['const']
    assert schema==frozen
    args={'$id':'ordinary identifier','literal':schema['properties']['literal']['const']}
    validate_arguments(tool(schema),args)
    validate_arguments(tool(published),args)


def test_parameter_map_context_preserves_annotation_like_field_names():
    params={'$id':{'type':'string'},'$schema':{'type':'string'},'$ref':{'type':'string'}}
    assert public_schema(params,context='parameter_map')==params
    assert public_schema([{'name':'read','params':params}],context='tool_list')[0]['params']==params


def test_legacy_implicit_object_schema_and_shared_validator_are_preserved():
    spec=tool({'properties':{'query':{'type':'string'}},'required':['query']})
    assert safe_registered_tool(spec)
    assert supported_schema(spec) is supported_schema(copy.deepcopy(spec))
    validate_arguments(spec,{'query':'public query'})
    with pytest.raises(ExecutionDenied):validate_arguments(spec,{'query':1})


@pytest.mark.parametrize('schema', UNSUPPORTED[:11])
def test_gateway_lists_and_detail_omit_unsupported_tools_without_provider_or_schema_fetch(managed,schema):
    store,_,client,_,rid,calls,_=managed
    spec=tool(schema)
    # Legacy compact records can contain malformed schema types that the newer
    # full-version writer already refuses; exercise their read boundary too.
    if isinstance(schema,(dict,bool)):
        store.record_usage(rid,tools=[spec],digest='unsupported-schema',guide={'tools':[spec]},changes=None,trial={'ok':True},full_tools=[spec])
    else:
        with store.tx() as db:
            db.execute('UPDATE resources SET usage_tools=?,usage_guide=? WHERE id=?',
                       (json.dumps([spec]),json.dumps({'tools':[spec]}),rid))
    frozen=store.resource(rid)
    response=rpc(client,f'/api/gateway/mcp/{rid}','tools/list')
    assert response.status_code==200,response.text
    assert response.json()['result']['tools']==[]
    detail=client.get(f'/api/agents/{rid}')
    assert detail.status_code==200 and detail.json()['agent']['tools']==[]
    assert not calls and store.resource(rid)==frozen


def test_gateway_lists_a_real_object_schema_and_legitimate_keyword_properties(managed):
    store,_,client,_,rid,calls,remote=managed
    schema={'type':'object','properties':{'$ref':{'type':'string'},'pattern':{'type':'string'}},'required':['$ref','pattern']}
    spec=tool(schema)
    remote.tools=[spec]
    compact=usage.compact_tools([spec])
    store.record_usage(rid,tools=compact,digest=usage.tools_hash(compact),guide={'tools':[spec]},changes=None,trial={'ok':True},full_tools=[spec])
    response=rpc(client,f'/api/gateway/mcp/{rid}','tools/list')
    listed=response.json()['result']['tools']
    assert len(listed)==1 and isinstance(listed[0]['inputSchema'],dict)
    assert listed[0]['inputSchema']==schema
    assert not calls
    args={'$ref':'literal field value','pattern':'ordinary search data'}
    executed=rpc(client,f'/api/gateway/mcp/{rid}','tools/call',{'name':'get_weather','arguments':args})
    assert 'result' in executed.json(),executed.text
    actual=[json.loads(request.content) for request in calls if json.loads(request.content).get('method')=='tools/call']
    assert len(actual)==1 and actual[0]['params']['arguments']==args


def test_recommendation_does_not_offer_an_mcp_listing_without_a_callable_schema(catalog):
    # Chat admits MCP listings only through a callable, supported tool contract; an inherited
    # unsupported schema is neither offered nor silently stripped into a tool-less recommendation.
    store,front,client,add,_=catalog
    spec=tool({'type':'object','properties':{'city':{'$ref':'https://schemas.example/schema'}}})
    add('Weather',usage_guide=json.dumps({'tools':[spec]}),usage_tools=json.dumps([spec]))
    response,items=discover(client,'rest')
    assert response.status_code==200 and items==[]
    assert not front.llm.mock_calls and not front.rag_engine.mock_calls


def test_recommendation_keeps_a2a_skills_without_mcp_schema_assumptions(catalog):
    _,_,client,add,now=catalog
    rid=add('Weather',kind='a2a',report_at=now-1,
            usage_guide=json.dumps({'skills':[{'id':'weather_summary','name':'Weather summary','description':'Weather forecast'}]}))
    response,items=discover(client,'rest',task='A2A weather forecast')
    assert response.status_code==200 and items[0]['id']==rid
    assert items[0]['tools']==['Weather summary'] and items[0]['tools_schema']


def test_bound_uri_validation_literal_is_omitted_as_descriptor_instead_of_rewritten():
    raw='https://provider.example/project'
    descriptor=tool({'type':'object','properties':{'target':{'const':raw+'/tools/lookup'}},'required':['target']})
    projected=project([public_schema(descriptor)],gateway_agent_url(1,'mcp'),(raw,))
    assert projected==[]
    assert descriptor['inputSchema']['properties']['target']['const']==raw+'/tools/lookup'
