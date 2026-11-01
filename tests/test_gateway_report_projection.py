"""Read-only public boundary protections with original report evidence retained."""
import copy
import json
from unittest.mock import Mock

import pytest

from agent_market.concierge.connections import gateway_agent_url
from agent_market.concierge.engine import Reply
from agent_market.concierge.report_projection import public_report
from tests.test_managed_agent_gateway import managed, catalog
from tests.test_single_recommendation_security_audit import request as discover
from tests.report_fixtures import legacy_report_fixture


def test_report_identity_private_rows_historical_target_and_source_preservation(managed):
    store,_,client,_,rid,*_=managed;resource=store.resource(rid);raw=resource['url'];old=raw
    body={'resource_id':rid,'kind':'mcp','title':'Projection fixture','slug':'projected-fixture','agent_url':old,
        'content_md':'## Public findings\nStable tool.\n- **Upstream Provider Target**: `'+old+'`\n### Internal Runtime Configuration\nprivate runtime value\n## Sources\nhttps://docs.example/guide\nEndpoint '+raw+'/v1/tools',
        'input_wire':{'url':old,'headers':{'Authorization':'Bearer synthetic-secret-marker'},'visitor_profile':{'name':'private-person'}},
        'output_wire':{'items':[{'url':'https://sources.example/current'}]},'author':'private-author','is_success':1}
    report_id=legacy_report_fixture(store,body)
    with pytest.raises(ValueError,match='subject'):
        store.create_test_report({'resource_id':rid,'kind':'a2a','title':'Wrong protocol','slug':'wrong-protocol','agent_url':'https://foreign.example/a2a'})
    original=dict(store.query('SELECT * FROM agent_test_reports WHERE id=?',(report_id,))[0]);original_resource=copy.deepcopy(resource)
    response=client.get(f'/api/agents/{rid}');assert response.status_code==200,response.text
    report=response.json()['agent']['test_report'];assert report['id']==report_id and report['kind']=='mcp'
    for hidden in [old,raw,'Upstream Provider Target','private runtime value','private-person','private-author','synthetic-secret-marker','Wrong protocol']:assert hidden not in response.text
    assert 'https://docs.example/guide' in response.text and 'https://sources.example/current' in response.text
    assert report['agent_url']==gateway_agent_url(rid,'mcp') and report['wire_scope']=='historical-sanitized'
    assert report['author']=='Agent Concierge'
    assert dict(store.query('SELECT * FROM agent_test_reports WHERE id=?',(report_id,))[0])==original
    assert store.resource(rid)==original_resource


@pytest.mark.parametrize('change',[{'resource_id':999},{'resource_id':True},{'kind':'a2a'},{'kind':None}])
def test_report_cannot_be_projected_to_a_different_identity(change):
    resource={'id':1,'kind':'mcp','url':'https://provider.example/mcp'}
    report={'resource_id':1,'kind':'mcp','agent_url':resource['url'],**change}
    assert public_report(report,resource) is None


@pytest.mark.parametrize('channel',['rest','a2a','mcp'])
def test_chat_response_boundary_projects_legacy_structured_and_text_replies(managed,monkeypatch,channel):
    store,front,client,_,rid,*_=managed;resource=store.resource(rid);raw=resource['url']
    original=Reply('Endpoint: '+raw+'/v1/tools', 'find',{'recommendations':[{'id':rid,'kind':'mcp','url':raw,'usage_endpoint':raw+'/child','name':'Weather','tools_schema':[{'name':'forecast','inputSchema':{'type':'object'}}]}]},['Details '+raw])
    frozen=copy.deepcopy(original)
    monkeypatch.setattr(front.concierge,'handle',lambda *_:original)
    monkeypatch.setattr(front.concierge,'lookup',lambda *a,**kw:original)
    response,items=discover(client,channel)
    assert raw not in response.text and items[0]['url']==gateway_agent_url(rid,'mcp')
    assert items[0]['usage_endpoint']==gateway_agent_url(rid,'mcp') and items[0]['tools_schema'][0]['name']=='forecast'
    assert original==frozen and store.resource(rid)['url']==raw
    assert not front.llm.mock_calls and not front.rag_engine.mock_calls


def test_report_code_fences_headers_personal_fields_and_large_fields():
    resource={'id':1,'kind':'mcp','url':'https://provider.example/api'}
    report={'resource_id':1,'kind':'mcp','agent_url':resource['url'],'content_md':'## Sample\n```text\n# Upstream Provider Target: https://provider.example/api\nkeep public sample\n```\n## Sources\nhttps://docs.example/guide',
        'input_wire':json.dumps({'headers':{'Host':'private-host.example','X-Forwarded-For':'192.0.2.12','Content-Type':'application/json'},'email':'person@example.org','query':'Public news'}),
        'output_wire':'x'*262145}
    result=public_report(report,resource)
    assert result['content_md'].count('```')==2 and 'keep public sample' in result['content_md']
    assert 'https://docs.example/guide' in result['content_md']
    assert 'Upstream' not in result['content_md']
    wire=json.loads(result['input_wire'])
    assert wire['headers']['Host']==wire['headers']['X-Forwarded-For']=='[REDACTED]'
    assert wire['headers']['Content-Type']=='application/json' and wire['query']=='Public news'
    assert 'person@example.org' not in json.dumps(result) and '192.0.2.12' not in json.dumps(result)
    assert result['output_wire']=='This historical field is unavailable for public display.'


@pytest.mark.parametrize('change',[{'id':'1'},{'kind':'wrong'},{'id':2147483646},{'id':True}])
def test_malformed_or_missing_recommendation_identity_fails_closed(managed,monkeypatch,change):
    store,front,client,_,rid,*_=managed;raw=store.resource(rid)['url']
    item={'id':rid,'kind':'mcp','url':raw+'/child',**change}
    monkeypatch.setattr(front.concierge,'handle',lambda *_:Reply('Endpoint '+raw,'find',{'recommendations':[item],'diagnostic':raw},['See '+raw]))
    response=client.post('/chat',json={'message':'MCP weather'})
    assert response.status_code==200,response.text
    assert response.json()['data']=={'recommendations':[],'status':'no_match'}
    assert raw not in response.text and response.json()['visitor']['token']


def test_uppercase_historical_target_is_masked_independently_of_current_binding():
    resource={'id':1,'kind':'mcp','url':'https://old.example/rpc'}
    report={'resource_id':1,'kind':'mcp','agent_url':'HTTPS://OLD.EXAMPLE/rpc',
        'content_md':'Endpoint https://old.example/rpc/v1/tools; source https://old.example/docs'}
    result=public_report(report,resource)
    assert 'old.example/rpc' not in json.dumps(result).lower() and 'https://old.example/docs' in result['content_md']


@pytest.mark.parametrize('channel',['rest','a2a','mcp'])
@pytest.mark.parametrize('shape',['object','string','null','reply_list'])
def test_malformed_recommendation_container_fails_closed_for_every_transport(managed,monkeypatch,channel,shape):
    store,front,client,_,rid,*_=managed;raw=store.resource(rid)['url']
    item={'id':rid,'kind':'mcp','url':raw}
    data={'recommendations':{'object':item,'string':raw,'null':None}.get(shape)} if shape!='reply_list' else [item]
    original=Reply('Endpoint '+raw,'find',data,['See '+raw]);frozen=copy.deepcopy(original)
    monkeypatch.setattr(front.concierge,'handle',lambda *_:original)
    monkeypatch.setattr(front.concierge,'lookup',lambda *a,**kw:original)
    response,items=discover(client,channel)
    assert response.status_code==200 and items==[] and raw not in response.text
    assert original==frozen and not front.llm.mock_calls and not front.rag_engine.mock_calls


@pytest.mark.parametrize('channel',['rest','a2a','mcp'])
def test_legacy_auxiliary_usage_and_text_credentials_are_redacted(managed,monkeypatch,channel):
    store,front,client,_,rid,*_=managed;raw=store.resource(rid)['url'];secret='synthetic-legacy-credential'
    original=Reply('Endpoint '+raw+' Authorization: Bearer '+secret,'details',{
        'recommendations':[{'id':rid,'kind':'mcp','url':raw}],
        'usage':{'endpoint':raw,'headers':{'Authorization':'Bearer '+secret},'params':{'city':{'type':'string'}}}},['api_key='+secret])
    frozen=copy.deepcopy(original);monkeypatch.setattr(front.concierge,'handle',lambda *_:original)
    monkeypatch.setattr(front.concierge,'lookup',lambda *a,**kw:original)
    response,items=discover(client,channel)
    assert response.status_code==200 and items[0]['url']==gateway_agent_url(rid,'mcp')
    assert secret not in response.text and raw not in response.text and original==frozen


def test_diagnostic_blocks_do_not_hide_independent_source_sections():
    resource={'id':1,'kind':'mcp','url':'https://provider.example/api'}
    report={'resource_id':1,'kind':'mcp','agent_url':resource['url'],'content_md':'## Findings\nPublic result\n```text\nTraceback (most recent call last):\nFile "/Users/private/service.py", line 42\nRuntimeError: private implementation\n```\n## Sources\nhttps://docs.example/home/reference',
        'summary':'Local file /Users/private/notes.txt is not public.'}
    result=public_report(report,resource);text=json.dumps(result)
    assert 'Traceback' not in text and 'private implementation' not in text and '/Users/' not in text
    assert 'https://docs.example/home/reference' in text and 'Public result' in text
    assert result['content_md'].count('```')==0


@pytest.mark.parametrize('uri',['file:///Users/synthetic/service.py','FILE:///var/private/config.json','file://private-host/home/synthetic/log.txt','file:///C:/Users/synthetic/service.py'])
def test_report_file_uris_are_private_without_hiding_web_source_paths(uri):
    resource={'id':1,'kind':'mcp','url':'https://provider.example/api'}
    report={'resource_id':1,'kind':'mcp','agent_url':resource['url'],'summary':'Log artifact '+uri,
            'output_wire':json.dumps({'path':uri,'source':'https://docs.example/home/reference'})}
    result=public_report(report,resource)
    assert uri not in json.dumps(result) and 'https://docs.example/home/reference' in result['output_wire']


def test_report_dynamic_personal_keys_are_masked_without_silent_collision():
    resource={'id':1,'kind':'mcp','url':'https://provider.example/api'}
    report={'resource_id':1,'kind':'mcp','agent_url':resource['url'],'output_wire':{'customers':{
        'one@example.org':'Private record one','two@example.org':'Private record two',
        'file:///Users/synthetic/customer.json':'Private file record','Authorization: Bearer synthetic-key':'Private auth record'},
        'source':'https://docs.example/home/reference'}}
    result=public_report(report,resource);text=json.dumps(result)
    assert len(result['output_wire']['customers'])==4
    assert all(v=='[REDACTED]' for v in result['output_wire']['customers'].values())
    assert not any(v in text for v in ['one@example.org','two@example.org','/Users/','synthetic-key','Private record','Private file record','Private auth record'])
    assert 'https://docs.example/home/reference' in text


def test_explore_report_badges_filters_and_grades_share_detail_protocol_scope(managed):
    from agent_market.concierge.front import get_front_explore,_front_explore_cache
    store,_,_,_,rid,*_=managed
    with store.tx() as db:db.execute('DELETE FROM agent_test_reports WHERE resource_id=?',(rid,))
    with pytest.raises(ValueError,match='subject'):
        store.create_test_report({'resource_id':rid,'kind':'a2a','title':'Unrelated protocol','slug':'wrong-kind-badge','eval_grade':'A'})
    _front_explore_cache.clear()
    result=get_front_explore(store,'',None,None,False,False,45,has_report=True)
    assert all(item['id']!=rid for item in result['items'])
    result=get_front_explore(store,'',None,None,False,False,45)
    item=next(item for item in result['items'] if item['id']==rid)
    assert item['report_count']==0 and item['report_grade'] is None
