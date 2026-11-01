"""Reviewed paper adapter: real transport fixture, strict pins and no fake evidence."""
import asyncio
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone,timedelta
import json
from types import SimpleNamespace

import httpx
import pytest

from agent_market.capability_adapters import (MANIFEST,PROFILE,ENDPOINT,TOOL,CONTRACT,profile,arguments,normalize,evidence_dataset)
from agent_market.capability_contracts import run_test
from agent_market.capability_registry import Registry
from agent_market.collector import usage
from agent_market.workspace_access import WorkspaceDenied
from agent_market.workspace_app_factory import NOTICE
from agent_market.workspace_typed_flows import NOTICE as RUN_NOTICE
from tests.test_customer_typed_authoring import customer_flow
from tests.test_workspace_typed_release import typed_release_world
from tests.test_workspace_typed_flows import typed_world,routing
from tests.test_customer_ten_workflows import definition


def output(query='Public research',limit=1):
    stamp=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    return {'status':'ok','query':query,'count':limit,'results':[
        {'title':query+' / Research','url':'https://sources.example/paper/'+str(i),
         'authors':[],'year':2025,'venue':'Public research index','doi':None,'openAccessUrl':None,
         'license':None,'citedBy':None,'pmcid':None,'source':'Crossref'} for i in range(limit)],
        'notice':'Synthetic records, not endorsements.','source':{'name':'Crossref','url':'https://www.crossref.org/'},'asOf':stamp[:10],'as_of':stamp}


@pytest.fixture
def adapted(customer_flow):
    x=customer_flow;w=x.w;spec=copy.deepcopy(MANIFEST[PROFILE]);calls=[];control={}
    rid=w.store.upsert_resource({'key':'mcp:'+ENDPOINT,'kind':'mcp','source':'mcp-registry',
        'name':'Synthetic public paper search','description':'Isolated paper contract adapter test','category':'dev_tools','url':ENDPOINT,'price_usdc':0,'details':{}})
    compact=usage.compact_tools([spec])
    w.store.record_usage(rid,compact,usage.tools_hash(compact),{},None,{'ok':True},full_tools=[spec])
    with w.store.tx() as db:db.execute("UPDATE resources SET health_status='healthy' WHERE id=?",(rid,))
    prior=w.remote.handle_request
    def handle(request):
        body=json.loads(request.content or '{}')
        if request.url.host!='papers.openkrill.app':return prior(request)
        if body.get('method')=='tools/list':
            return httpx.Response(200,json={'jsonrpc':'2.0','id':body['id'],'result':{'tools':[spec]}})
        if body.get('method')=='tools/call':
            assert body['params']['name']==TOOL
            native=body['params']['arguments'];assert set(native)=={'query','limit'}
            calls.append(copy.deepcopy(native))
            payload=output(native['query'],native['limit'])
            if control.get('unavailable'):payload['status']='unavailable'
            return httpx.Response(200,json={'jsonrpc':'2.0','id':body['id'],
                'result':{'isError':False,'content':[],'structuredContent':payload}})
        return prior(request)
    w.remote.handle_request=handle
    registry=Registry(w.store);registry.approve(w.store.resource(rid),CONTRACT,TOOL)
    async def runner(identity,**kwargs):
        result=w.rt.proxy.execute(identity,kwargs['tool'],kwargs['arguments'])
        return {'execution_succeeded':result.get('ok') is True,'simulated':False,'output':result.get('result')}
    with ThreadPoolExecutor(max_workers=1) as pool:
        result=pool.submit(lambda:asyncio.run(run_test(registry,w.store.resource(rid),CONTRACT,
            {'query':'Public research','language':'en','limit':1},runner))).result(timeout=5)
    assert result['ok'],result
    calls.clear()
    yield SimpleNamespace(x=x,rid=rid,calls=calls,registry=registry,spec=spec,control=control)
    w.remote.handle_request=prior


def test_adapter_ten_step_customer_review_projection_and_replay(adapted):
    env=adapted;x=env.x
    review=x.core.factory.prepare_plan(x.ws,{'name':'Reviewed paper chain',
        'definition':definition([env.rid]*10,'Machine learning',10),'base_flow_id':None,'base_revision':None},x.actor)
    flow=x.core.factory.commit(x.ws,{'review_id':review['review_id'],'authorized':True,'notice':NOTICE},x.actor)
    plan=x.core.typed.prepare(x.ws,flow['id'],{'revision':1},x.actor)
    assert not env.calls and 'input_notice' in plan['review']['destinations'][0]
    command={'ticket_id':plan['ticket_id'],'authorized':True,'notice':RUN_NOTICE}
    run=x.core.typed.execute(x.ws,flow['id'],command,x.actor)['run']
    assert run['status']=='succeeded' and len(env.calls)==10
    steps={row['node_id']:row for row in run['steps']}
    for index in range(1,10):
        assert env.calls[index]['query']==steps['step_'+str(index)]['output']['items'][0]['title']
    assert x.core.typed.execute(x.ws,flow['id'],command,x.actor)['replayed'] and len(env.calls)==10


@pytest.mark.parametrize('fault',['schema','implementation','legacy_evidence','approval'])
def test_adapter_change_or_old_evidence_never_inherits_execution_permission(adapted,monkeypatch,fault):
    env=adapted;x=env.x;resource=x.w.store.resource(env.rid)
    if fault=='schema':
        tools=json.loads(resource['usage_full_tools']);tools[0]['annotations']['readOnlyHint']=False
        resource['usage_full_tools']=json.dumps(tools)
        with pytest.raises(ValueError):profile(resource,CONTRACT,TOOL)
        return
    if fault=='implementation':
        import agent_market.capability_adapters as module
        monkeypatch.setattr(module,'IMPLEMENTATION','0'*64)
    else:
        with x.w.store.tx() as db:
            if fault=='approval':db.execute('DELETE FROM capability_approvals WHERE version_id=?',(env.registry.current(resource)['id'],))
            else:db.execute("UPDATE capability_evidence SET dataset_version='explicit-contract-test-v1' WHERE version_id=? AND scope='contract'",(env.registry.current(resource)['id'],))
    with pytest.raises(WorkspaceDenied):
        x.core.factory.prepare_plan(x.ws,{'name':'Denied changed adapter','definition':definition([env.rid]*2,'Research',2),
            'base_flow_id':None,'base_revision':None},x.actor)
    assert not env.calls


@pytest.mark.parametrize('fault',['old','future','missing_time','unavailable','count','url','oversize_query','query','date'])
def test_adapter_rejects_stale_inconsistent_or_unsupported_data(fault):
    resource={'url':ENDPOINT,'usage_full_tools':[MANIFEST[PROFILE]]}
    supplied={'query':'Public research','language':'en','limit':1};raw=output()
    if fault=='oversize_query':
        supplied['query']='x'*201
        with pytest.raises(ValueError):arguments(resource,CONTRACT,TOOL,supplied)
        return
    if fault=='old':raw['as_of']=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()
    elif fault=='future':raw['as_of']=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
    elif fault=='missing_time':del raw['as_of']
    elif fault=='unavailable':raw['status']='unavailable'
    elif fault=='count':raw['count']=2
    elif fault=='query':raw['query']='Different search'
    elif fault=='date':raw['asOf']='2000-01-01'
    else:raw['results'][0]['url']='https://secret:password@sources.example/paper'
    with pytest.raises(ValueError):normalize(resource,CONTRACT,TOOL,supplied,raw)


def test_adapter_runtime_rejection_blocks_later_calls_and_invalidates_only_contract(adapted):
    env=adapted;x=env.x
    flow=x.core.typed.save(x.ws,{'flow_id':None,'revision':0,'name':'Confirmed semantic failure',
        'definition':definition([env.rid]*2,'Research',2)},x.actor)
    ticket=x.core.typed.prepare(x.ws,flow['id'],{'revision':1},x.actor)
    env.control['unavailable']=True
    result=x.core.typed.execute(x.ws,flow['id'],{'ticket_id':ticket['ticket_id'],'authorized':True,'notice':RUN_NOTICE},x.actor)
    assert result['run']['status']=='failed' and result['run']['error_code']=='CONTRACT_REJECTED'
    assert len(env.calls)==1 and result['run']['steps'][0]['status']=='failed'
    view=env.registry.projection(x.w.store.resource(env.rid))
    assert view['connection_readiness']['verified_callable']
    assert not any(item['verified'] for item in view['capability_contracts'])
    with pytest.raises(WorkspaceDenied):x.core.typed.prepare(x.ws,flow['id'],{'revision':1},x.actor)
    assert len(env.calls)==1
