"""Ten synthetic customer research chains exercise input-dependent MCP results.

No real provider, live customer database, public quality claim or payment is used.
"""
import asyncio
import copy
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from agent_market.capability_contracts import run_test
from agent_market.capability_registry import Registry
from agent_market.collector import usage
from agent_market.workspace_access import WorkspaceInvalid
from agent_market.workspace_app_factory import NOTICE
from agent_market.workspace_typed_flows import NOTICE as RUN_NOTICE
from tests.test_customer_typed_authoring import customer_flow
from tests.test_workspace_typed_release import typed_release_world
from tests.test_workspace_typed_flows import typed_world, routing
from tests.test_workflow_fallback import tool, output

SCENARIOS = (
    ('Daily Technology Research', 'Public AI agent technology documentation', 2),
    ('Stock News Context Research', 'Public stock market news terminology and source documentation', 3),
    ('Security Advisory Research', 'Public software vulnerability advisory documentation', 4),
    ('API Integration Research', 'Public API authentication and integration documentation', 5),
    ('Competitive Product Research', 'Public collaboration software feature documentation', 6),
    ('Ecommerce Operations Research', 'Public ecommerce order fulfillment documentation', 7),
    ('Sustainability Research', 'Public renewable energy reporting documentation', 8),
    ('Learning Resource Research', 'Public introductory machine learning documentation', 9),
    ('Product Launch Research', 'Public software release readiness documentation', 10),
    ('Customer Support Research', 'Public customer support troubleshooting documentation', 10),
)


def definition(ids, query, count, *, limit=1):
    nodes = []
    for index, rid in enumerate(ids[:count]):
        identity = 'step_' + str(index + 1)
        parent = 'step_' + str(index)
        nodes.append({'id': identity, 'resource_id': rid, 'contract_id': 'docs.search.v1',
            'input': {'query': query, 'language': 'en', 'limit': limit} if not index else {'language': 'en', 'limit': limit},
            'bindings': {} if not index else {'query': {'node_id': parent, 'path': ['items', 0, 'title']}},
            'after': [] if not index else [parent], 'when': None})
    return {'nodes': nodes}


@pytest.fixture
def ten_world(customer_flow):
    x = customer_flow; w = x.w; ids = list(w.ids); trace = []
    original = w.remote.handle_request
    def responder(request):
        body = json.loads(request.content or '{}')
        if body.get('method') != 'tools/call':
            return original(request)
        arguments = body['params']['arguments']; host = request.url.host
        w.calls.append(host)
        label = 'Agent ' + str(hosts.index(host) + 1)
        result = output(); item = result['structuredContent']['items'][0]
        item.update(title=arguments['query'] + ' / ' + label,
            excerpt='Synthetic public-source result for: ' + arguments['query'])
        items = []
        for index in range(min(arguments['limit'], 2)):
            entry = dict(item); entry['url'] = 'https://sources.example/agent-' + str(hosts.index(host) + 1) + '/' + str(index)
            items.append(entry)
        result['structuredContent']['items'] = items
        trace.append({'agent': label, 'input': copy.deepcopy(arguments), 'output': copy.deepcopy(result['structuredContent'])})
        return httpx.Response(200, json={'jsonrpc': '2.0', 'id': body['id'], 'result': result})
    hosts = ['primary.example', 'alternate.example', 'third.example'] + ['agent'+str(n)+'.example' for n in range(4, 11)]
    w.remote.handle_request = responder
    registry = Registry(w.store); tools = [tool()]
    for host in hosts[3:]:
        rid = w.store.upsert_resource({'key':'mcp:https://'+host+'/mcp','kind':'mcp','source':'mcp-registry',
            'name':'Synthetic '+host,'description':'Isolated public documentation test responder',
            'category':'dev_tools','url':'https://'+host+'/mcp','price_usdc':0,'details':{}})
        w.store.record_usage(rid,usage.compact_tools(tools),usage.tools_hash(usage.compact_tools(tools)),{},None,{'ok':True},full_tools=tools)
        with w.store.tx() as db:
            db.execute("UPDATE resources SET health_status='healthy' WHERE id=?",(rid,))
        registry.approve(w.store.resource(rid),'docs.search.v1','search_docs')
        async def runner(identity, **kwargs):
            result=w.rt.proxy.execute(identity,kwargs['tool'],kwargs['arguments'])
            return {'execution_succeeded':result.get('ok') is True,'simulated':False,'output':result.get('result')}
        with ThreadPoolExecutor(max_workers=1) as pool:
            result=pool.submit(lambda:asyncio.run(run_test(registry,w.store.resource(rid),'docs.search.v1',
                {'query':'Synthetic connection validation','language':'en','limit':1},runner))).result(timeout=5)
        assert result['ok'], result
        ids.append(rid)
    trace.clear(); w.calls.clear()
    yield SimpleNamespace(x=x, ids=ids, trace=trace)
    w.remote.handle_request = original


def execute(x, flow):
    plan=x.core.typed.prepare(x.ws,flow['id'],{'revision':flow['revision']},x.actor)
    return x.core.typed.execute(x.ws,flow['id'],{'ticket_id':plan['ticket_id'],
        'authorized':True,'notice':RUN_NOTICE},x.actor), plan


def test_ten_common_research_workflows_ten_distinct_agents_and_changed_input(ten_world):
    env=ten_world; x=env.x; evidence=[]
    assert len(set(env.ids))==10
    for name, query, count in SCENARIOS:
        review=x.core.factory.prepare_plan(x.ws,{'name':name,'definition':definition(env.ids,query,count),
            'base_flow_id':None,'base_revision':None},x.actor)
        before=len(env.trace)
        flow=x.core.factory.commit(x.ws,{'review_id':review['review_id'],'authorized':True,'notice':NOTICE},x.actor)
        assert len(env.trace)==before
        result, plan=execute(x,flow); run=result['run']; calls=copy.deepcopy(env.trace[before:])
        assert run['status']=='succeeded' and len(calls)==count
        assert plan['review']['max_calls']==count and plan['review']['seconds']==60
        for index, call in enumerate(calls):
            expected=query if not index else calls[index-1]['output']['items'][0]['title']
            assert call['input']['query']==expected
            assert call['output']['items'][0]['title']!=expected
            assert len(call['output']['items'])==1
        replay,_=execute_with_ticket(x,flow,plan)
        assert replay['replayed'] and len(env.trace)==before+count
        revised=x.core.typed.save(x.ws,{'flow_id':flow['id'],'revision':1,'name':name,
            'definition':definition(env.ids,query+' with revised focus',count,limit=2)},x.actor)
        changed_before=len(env.trace); changed,_=execute(x,revised)
        changed_calls=copy.deepcopy(env.trace[changed_before:])
        assert changed['run']['status']=='succeeded' and len(changed_calls)==count
        for index, call in enumerate(changed_calls):
            assert call['input']['query']!=calls[index]['input']['query']
            assert call['output']['items'][0]['title']!=calls[index]['output']['items'][0]['title']
            assert len(call['output']['items'])==2
            if index:
                assert call['input']['query']==changed_calls[index-1]['output']['items'][0]['title']
        if count==10:
            from agent_market.workspace_reliability import ReliabilityEvidence
            from agent_market.workspace_typed_evidence import WorkspaceTypedEvidence
            plane=ReliabilityEvidence(x.core.access,x.core.execution)
            lineage=WorkspaceTypedEvidence(plane,x.core.typed)
            with x.core.access._tx(x.actor) as (db,_):
                _,_,version,steps,_=lineage._snapshot(db,x.ws,revised['id'],changed['run']['id'])
            assert len(version['definition']['nodes'])==len(steps)==10
        evidence.append({'name':name,'agents':count,'status':run['status'],'changed_status':changed['run']['status'],
            'input':query,'original_calls':calls,'changed_calls':changed_calls,
            'replayed_without_extra_calls':True,'scope':'synthetic MCP transport in isolated database'})
    assert len(x.core.typed.listing(x.ws,x.actor))==10
    assert len(env.trace)==sum(item[2] for item in SCENARIOS)*2
    if os.environ.get('AC_WORKFLOW_TEST_REPORT'):
        Path(os.environ['AC_WORKFLOW_TEST_REPORT']).write_text(json.dumps(evidence,indent=2)+'\n')


def execute_with_ticket(x,flow,ticket):
    return x.core.typed.execute(x.ws,flow['id'],{'ticket_id':ticket['ticket_id'],'authorized':True,'notice':RUN_NOTICE},x.actor),ticket


def test_eleven_steps_and_unsafe_bindings_remain_blocked(ten_world):
    env=ten_world; x=env.x
    too_many=definition(env.ids+[env.ids[0]],'Public documentation',11)
    with pytest.raises(WorkspaceInvalid):
        x.core.factory.prepare_plan(x.ws,{'name':'Over limit','definition':too_many,'base_flow_id':None,'base_revision':None},x.actor)
    invalid=definition(env.ids,'Public documentation',10)
    invalid['nodes'][-1]['bindings']['query']['path']=['items',0]
    with pytest.raises(WorkspaceInvalid):
        x.core.factory.prepare_plan(x.ws,{'name':'Object coercion blocked','definition':invalid,'base_flow_id':None,'base_revision':None},x.actor)
    assert not env.trace


def test_customer_authoring_rate_limit_has_retry_hint_without_provider_call(ten_world,monkeypatch):
    from agent_market.customer_authoring_service import RateLimiter
    env=ten_world; x=env.x
    monkeypatch.setattr(RateLimiter,'allow',lambda *_:False)
    response=x.client.get(x.base+'/typed/options',headers=x.headers)
    assert response.status_code==429 and response.headers['Retry-After']=='60'
    assert not env.trace
