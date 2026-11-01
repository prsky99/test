"""Opt-in full customer API generation matrix with real model and isolated data."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json,os,time
from pathlib import Path

import httpx,pytest
from agent_market.capability_registry import Registry
from agent_market.capability_contracts import run_test
from agent_market.collector import usage
from agent_market.workspace_app_factory import AppFactory,MODEL_NOTICE
from agent_market.workflow_model_proposer import OllamaGraphProposer
from scripts.agentcon_config import read_local_model_settings
from tests.test_customer_typed_authoring import customer_flow
from tests.test_workspace_typed_release import typed_release_world
from tests.test_workspace_typed_flows import typed_world,routing
from tests.test_workflow_fallback import tool,output
from tests.test_mcp_proxy import MockRemoteMcp
from tests.workflow_generation_cases import CASES,assess
from scripts.benchmark_macmini_model import Probe

pytestmark=pytest.mark.skipif(os.environ.get('LIVE_WORKFLOW_MATRIX')!='1',reason='Explicit real model opt-in required')


@pytest.fixture
def matrix_world(customer_flow):
    x=customer_flow;w=x.w;spec=tool('news.search.v1');original=w.remote.handle_request;trace=[]
    def handle(req):
        if req.url.host!='matrix-news.example':return original(req)
        body=json.loads(req.content or '{}')
        if body.get('method')=='tools/call':trace.append(body['params']['arguments'])
        remote=MockRemoteMcp([spec],call_result=output('news.search.v1'))
        return remote.handle_request(req)
    w.remote.handle_request=handle
    rid=w.store.upsert_resource({'key':'mcp:https://matrix-news.example/mcp','kind':'mcp','source':'mcp-registry','name':'Synthetic news','url':'https://matrix-news.example/mcp','description':'Isolated public news search','category':'news_media','price_usdc':0,'details':{}})
    compact=usage.compact_tools([spec]);w.store.record_usage(rid,compact,usage.tools_hash(compact),{},None,{'ok':True},full_tools=[spec])
    with w.store.tx() as db:db.execute("UPDATE resources SET health_status='healthy' WHERE id=?",(rid,))
    registry=Registry(w.store);registry.approve(w.store.resource(rid),'news.search.v1','search_news')
    async def runner(identity,**kwargs):
        response=w.rt.proxy.execute(identity,kwargs['tool'],kwargs['arguments']);return {'execution_succeeded':response['ok'],'simulated':False,'output':response['result']}
    with ThreadPoolExecutor(max_workers=1) as pool:
        checked=pool.submit(lambda:asyncio.run(run_test(registry,w.store.resource(rid),'news.search.v1',{'query':'Synthetic news','language':'en','limit':1,'from_utc':'2026-01-01T00:00:00Z'},runner))).result()
    assert checked['ok'];trace.clear();w.calls.clear()
    yield x,trace
    w.remote.handle_request=original


def test_generation_matrix_records_actual_outputs(matrix_world):
    x,trace=matrix_world;s=read_local_model_settings('gateway-data/local-model.env');probe=Probe()
    client=probe.client;calls=probe.requests
    x.core.factory.model_source=AppFactory(x.w.core,model_proposer=OllamaGraphProposer(s['WORKSPACE_MODEL_URL'],s['WORKSPACE_MODEL_NAME'],client,provider='openai',allow_http=True))
    dest=Path(os.environ['WORKFLOW_MATRIX_OUTPUT']);dest.mkdir(parents=True,exist_ok=True);rows=[]
    try:
        selected=set(filter(None,os.environ.get('WORKFLOW_MATRIX_CASES','').split(',')))
        for case in CASES:
            if selected and case['id'] not in selected:continue
            before=len(calls);started=time.monotonic()
            body={'objective':case['prompt'],'name':'Matrix '+case['id'],'authorized':True,'notice':MODEL_NOTICE,'data_attestation':'public_objective_without_personal_or_private_data'}
            response=x.client.post(x.base+'/typed/reviews/model',json=body,headers=x.headers);value=response.json();result=value.get('review',{})
            checks=assess(case,result,response.status_code)
            row={'case':case,'status':response.status_code,'seconds':round(time.monotonic()-started,4),'model_calls':len(calls)-before,'checks':checks,'passed':all(checks.values()),'response':value,'model_responses':probe.responses[before:]}
            rows.append(row);(dest/'results.json').write_text(json.dumps(rows,indent=2)+'\n');print(json.dumps({'id':case['id'],'status':response.status_code,'passed':row['passed'],'checks':checks}),flush=True)
        (dest/'summary.json').write_text(json.dumps({'cases':len(rows),'passed':sum(r['passed'] for r in rows),'failed':[r['case']['id'] for r in rows if not r['passed']],'model_calls':len(calls),'agent_calls':len(x.w.calls)+len(trace),'customer_data_modified':False},indent=2)+'\n')
        assert not x.w.calls and not trace
        if os.environ.get('WORKFLOW_MATRIX_ASSERT')=='1':assert all(r['passed'] for r in rows)
    finally:client.close()
