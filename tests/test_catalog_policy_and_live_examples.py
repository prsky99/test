"""Catalog noun collisions, destructive mutations and real-example browser controls."""
import json
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest

from agent_market.collector import usage
from agent_market.concierge.execution_policy import safe_registered_tool
from agent_market.concierge.execution_policy import validate_arguments, ExecutionDenied
from agent_market.concierge.proxy import McpProxy
from agent_market.concierge.testbench_examples import RECIPES
from tests.test_fast_single_recommendation import catalog
from tests.test_front_workflow_browser import browser
from tests.test_managed_agent_gateway import rpc
from tests.test_mcp_proxy import MockRemoteMcp

NOUN_NAMES = ['list_skills','get_skill','get_agent_skill','search_skills','get_credit_score',
    'get_account_credits','get_design_guidelines','list_design_systems','retrieveAssignmentList',
    'search_assignments','getSignatureStatuses','get_blog_posts','get_order_status','read_book',
    'list_books','get_booking_link','get_playbook_status','search_startups','get_top_traders',
    'list_trades','get_orderbook','get_postcode','get_price_movements','get_framework_updates',
    'dataset.describe','dataset.get','get-dataset-items','get_dataset_items','checkOpenAccess',
    'open-weather.getCurrentWeather','getRunEvaluation','alpha_signals','get_design_run','get_skill_run']


def readonly(name):
    return {'name':name,'annotations':{'readOnlyHint':True,'destructiveHint':False},
            'inputSchema':{'type':'object','properties':{}}}


def test_all_reviewed_catalog_names_and_destructive_variants():
    names=json.loads((Path(__file__).parent/'fixtures/catalog_readonly_tool_names.json').read_text())
    assert len(names)>1000
    for name in names:
        assert safe_registered_tool(readonly(name)),name
        for changed in ('delete_'+name,name+'_delete',name+'_sign_transaction',name+'_send_message','create_'+name):
            assert not safe_registered_tool(readonly(changed)),changed


@pytest.mark.parametrize('name',NOUN_NAMES)
def test_confirmed_readonly_query_nouns_are_not_actions(name):
    assert safe_registered_tool(readonly(name)),name


@pytest.mark.parametrize('name',NOUN_NAMES)
def test_same_nouns_do_not_hide_actual_actions(name):
    for changed in ('delete_'+name, name+'_delete', name+'_sign_transaction', name+'_send_message', 'create_'+name):
        assert not safe_registered_tool(readonly(changed)),changed
    assert not safe_registered_tool({**readonly(name),'annotations':{'readOnlyHint':True,'destructiveHint':True}})


@pytest.mark.parametrize('name',['deleteAll','ns_deleteall','get_and_delete','getCreateInvoice',
    'get_signalsDelete','sign_transaction','book_hotel','post_review','get_and_send_message',
    'get_latest_signals;sign_transaction','get_skills_delete_database','create_credit_report',
    'get_credit_score_update_database','order_list','book_list','get_and_order',
    'getPlaceOrder','get_then_post','getAndBookHotel','get_prepare_claim'])
def test_action_words_are_not_query_objects_before_the_query(name):
    assert not safe_registered_tool(readonly(name))


@pytest.mark.parametrize('field',['pattern','$ref','patternProperties'])
def test_parameter_names_are_not_schema_execution_keywords(field):
    spec={**readonly('search_text'),'inputSchema':{'type':'object','properties':{field:{'type':'string'}},'required':[field]}}
    validate_arguments(spec,{field:'example'})
    with pytest.raises(ExecutionDenied):validate_arguments(spec,{field:12})


@pytest.mark.parametrize('schema',[{'type':'string','pattern':'(a+)+$'}, {'$ref':'https://internal.example/schema'},
    {'type':'object','properties':{'value':{'$ref':'https://internal.example/schema'}}}])
def test_actual_regex_and_remote_reference_constraints_remain_refused(schema):
    with pytest.raises(ExecutionDenied):validate_arguments({'inputSchema':schema},{})


@pytest.fixture
def examples(catalog):
    store,front,client,add,now=catalog
    tools={};calls=[]
    for _,title,_,url,tool,args in RECIPES:
        rid=add(title,url=url)
        schema={'type':'object','properties':{k:{'type':'integer' if type(v) is int else 'string'} for k,v in args.items()},'required':list(args)}
        spec={**readonly(tool),'inputSchema':schema};tools[url]=spec
        compact=usage.compact_tools([spec]);store.record_usage(rid,tools=compact,digest=usage.tools_hash(compact),guide={},changes=None,trial={'ok':True})
    def provider(request):
        body=json.loads(request.content or '{}')
        if body.get('method')=='tools/call':calls.append(body['params'])
        remote=MockRemoteMcp([tools[str(request.url)]],{'content':[{'type':'text','text':'Verified controlled informational response.'}]})
        return remote.handle_request(request)
    front.proxy=McpProxy(store,allow_private=True,http=httpx.Client(transport=httpx.MockTransport(provider)))
    front.security.allow_probe=lambda *a,**kw:True
    yield store,front,client,calls


def test_all_four_examples_use_positive_registered_ids_and_execute(examples):
    _,_,client,calls=examples
    response=client.get('/api/test/presets').json()
    assert len(response['live_examples'])==4 and all(x['simulated'] for x in response['presets'])
    for recipe in response['live_examples']:
        assert recipe['available'] and recipe['resource_id']>0 and recipe['simulated'] is False
        payload={'resource_id':recipe['resource_id'],'tool':recipe['tool'],'arguments':recipe['args']}
        result=client.post('/api/test/execute',json=payload).json()
        assert result['execution_succeeded'] and result['simulated'] is False
        assert 'No provider was contacted' not in result['output']
    assert len(calls)==4


def test_unavailable_example_never_falls_back_to_demo(examples):
    store,_,client,calls=examples
    with store.tx() as db:db.execute("UPDATE resources SET health_status='quarantined'")
    recipes=client.get('/api/test/presets').json()['live_examples']
    assert len(recipes)==4 and all(not r['available'] and r['resource_id'] is None for r in recipes)
    assert not calls


def test_catalog_query_names_execute_via_managed_routes(catalog):
    store,front,client,add,now=catalog
    front.security.allow_probe=lambda *a,**kw:True
    for i,name in enumerate(NOUN_NAMES):
        rid=add(name,url=f'https://query-{i}.example/mcp');spec=readonly(name);compact=usage.compact_tools([spec]);calls=[]
        store.record_usage(rid,tools=compact,digest=usage.tools_hash(compact),guide={},changes=None,trial={'ok':True})
        remote=MockRemoteMcp([spec])
        def provider(req):calls.append(req);return remote.handle_request(req)
        front.proxy=McpProxy(store,allow_private=True,http=httpx.Client(transport=httpx.MockTransport(provider)))
        listed=rpc(client,f'/api/gateway/mcp/{rid}','tools/list').json()['result']['tools']
        assert listed[0]['name']==name
        result=rpc(client,f'/api/gateway/mcp/{rid}','tools/call',{'name':name,'arguments':{}})
        assert 'result' in result.json(),result.text
        assert any(json.loads(r.content).get('method')=='tools/call' for r in calls)


@pytest.mark.parametrize('entry',['testbench','gateway','workflow'])
def test_literal_pattern_argument_executes_through_every_shared_path(catalog,entry):
    store,front,client,add,_=catalog;front.security.allow_probe=lambda *a,**kw:True
    rid=add('Pattern search');spec={**readonly('search_text'),'inputSchema':{
        'type':'object','properties':{'pattern':{'type':'string'}},'required':['pattern']}}
    compact=usage.compact_tools([spec]);store.record_usage(rid,tools=compact,digest=usage.tools_hash(compact),guide={},changes=None,trial={'ok':True})
    calls=[];remote=MockRemoteMcp([spec])
    def provider(req):calls.append(req);return remote.handle_request(req)
    front.proxy=front.workflows.proxy=McpProxy(store,allow_private=True,http=httpx.Client(transport=httpx.MockTransport(provider)))
    if entry=='testbench':
        result=client.post('/api/test/execute',json={'resource_id':rid,'tool':'search_text','arguments':{'pattern':'example'}}).json()
        assert result['execution_succeeded']
    elif entry=='gateway':
        assert 'result' in rpc(client,f'/api/gateway/mcp/{rid}','tools/call',{'name':'search_text','arguments':{'pattern':'example'}}).json()
    else:
        wid=store.create_workflow({'name':'Pattern search','is_template':1,'nodes':[{
            'id':'search','type':'agent','kind':'mcp','name':'Search','resource_id':rid,
            'data':{'tool':'search_text','input':{'pattern':'example'}}}],'edges':[]})
        handle=client.post('/api/workflows/run',json={'template_id':wid}).json()
        for _ in range(200):
            result=client.get('/api/workflows/runs/'+handle['run_id'],headers={'X-Workflow-Key':handle['run_key']}).json()
            if result['status'] in ('succeeded','failed','cancelled'):break
            time.sleep(.01)
        assert result['status']=='succeeded',result
    assert any(json.loads(r.content).get('method')=='tools/call' for r in calls)


@pytest.mark.parametrize('presentation', ['legacy', 'published'])
def test_four_run_now_buttons_really_call_registered_agents(browser,examples,monkeypatch,presentation):
    from playwright.sync_api import expect
    if presentation == 'legacy':
        from agent_market.concierge import pearl_view
        monkeypatch.setattr(pearl_view, 'public_page_available', lambda: False)
    _,_,client,calls=examples;context=browser.new_context();page=context.new_page();errors=[];external=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    def serve(route):
        req=route.request;url=urlsplit(req.url)
        if url.hostname!='agentconcierge.biz':external.append(req.url);return route.abort()
        response=client.request(req.method,url.path+('?' +url.query if url.query else ''),content=req.post_data,
            headers={k:v for k,v in req.headers.items() if k in ('accept','content-type')})
        route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items() if k not in ('content-length','content-encoding','transfer-encoding')})
    context.route('**/*',serve)
    page.goto('https://agentconcierge.biz/#test')
    selector = '.testbench-recipe-card' if presentation == 'legacy' else '.pearl-example-choice'
    expect(page.locator('#testbenchRecipesGrid '+selector)).to_have_count(4)
    expect(page.locator('#tbAgentMetaBox')).not_to_contain_text('Demo')
    for i in range(4):
        example = page.locator('#testbenchRecipesGrid '+selector).nth(i)
        if presentation == 'legacy':
            example.get_by_role('button',name='Run Now',exact=True).click()
        else:
            assert len(calls) == i
            example.click()
            expect(page.locator('#tbRunBtn')).to_be_enabled()
            assert len(calls) == i
            page.locator('#tbRunBtn').click()
        expect(page.locator('#tbKpiStatus')).to_have_text('Completed')
        expect(page.locator('#tbRunBtn')).to_be_enabled()
        assert len(calls)==i+1
        assert calls[-1]['name'] == RECIPES[i][4]
        assert page.evaluate('tbLastResult.simulated') is False
    Path('reports/final-nine-execution-2026-10-19').mkdir(exist_ok=True)
    page.screenshot(path='reports/final-nine-execution-2026-10-19/four-live-examples-'+presentation+'.png')
    assert not errors and not external
    context.close()
