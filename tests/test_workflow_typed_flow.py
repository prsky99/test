"""Isolated transport tests for one signed private data connection."""
import asyncio
import copy
from concurrent.futures import ThreadPoolExecutor
import json
import time

import httpx
import pytest

from agent_market.capability_contracts import run_test
from agent_market.capability_registry import Registry, canonical, digest
from agent_market.collector import usage
from agent_market.workflow_composer import Composer, SAVE
from agent_market.workflow_typed_flow import PROFILE, NODE, NOTICE, resolve
from agent_market.workflows import WorkflowError, public_template
from tests.test_mcp_proxy import MockRemoteMcp
from tests.test_workflow_fallback import routing, tool, output
from tests.test_workflow_fallback_api import routing_api, H
from tests.test_workflow_runtime import wait
from tests.test_workflow_composer import save


@pytest.fixture
def typed_routing(routing):
    rt,_,ids,calls,modes,hooks,remote=routing
    news_tool=tool('news.search.v1');docs_tool=tool()
    controls={'title':'Python asynchronous task documentation','seen':[],'news_calls':0}
    def handle(request):
        body=json.loads(request.content or '{}');host=request.url.host
        news=host=='primary.example';remote.tools=[news_tool if news else docs_tool]
        if body.get('method')=='tools/call':
            calls.append(host);controls['seen'].append(copy.deepcopy(body['params']['arguments']))
            if host in hooks:hooks[host](request)
            if modes.get(host)=='invalid':
                return httpx.Response(200,json={'jsonrpc':'2.0','id':body['id'],'result':{'structuredContent':{'items':[{'title':'invalid'}],'partial':False}}})
            if modes.get(host)=='unknown':raise httpx.ReadTimeout('isolated lost response')
            remote.call_result=output('news.search.v1' if news else 'docs.search.v1')
            if news:
                controls['news_calls']+=1
                items=remote.call_result['structuredContent']['items']
                if controls['title'] is None:items.clear()
                else:items[0]['title']=controls['title']
        return MockRemoteMcp.handle_request(remote,request)
    remote.handle_request=handle
    compact=usage.compact_tools([news_tool])
    rt.store.record_usage(ids[0],compact,usage.tools_hash(compact),{},None,{'ok':True},full_tools=[news_tool])
    registry=Registry(rt.store);registry.approve(rt.store.resource(ids[0]),'news.search.v1','search_news')
    async def runner(identity,**kwargs):
        response=rt.proxy.execute(identity,kwargs['tool'],kwargs['arguments'])
        return {'execution_succeeded':response['ok'],'simulated':False,'output':response['result']}
    with ThreadPoolExecutor(max_workers=1) as pool:
        result=pool.submit(lambda:asyncio.run(run_test(registry,rt.store.resource(ids[0]),'news.search.v1',
            {'query':'Python news','language':'en','limit':3,'from_utc':'2026-01-01T00:00:00Z'},runner))).result()
    assert result['ok'],result
    calls.clear();controls['seen'].clear();controls['news_calls']=0
    rt.typed_test_controls=controls
    return routing


def generate_typed(rt):
    return Composer(rt).generate({'prompt':'Python news and documentation search','flow':PROFILE},1)


def saved_typed(rt):
    draft=generate_typed(rt)
    return rt.store.get_workflow(save(rt,draft,flow_authority=True,flow_notice=NOTICE)['id'])


def test_typed_draft_requires_separate_save_consent_and_does_not_call(typed_routing):
    rt,_,_,calls,*_=typed_routing;draft=generate_typed(rt)
    assert not calls and draft['proposal']['intent']['flow']==PROFILE
    assert draft['workflow']['edges'][-1]['source']=='search-1'
    assert draft['workflow']['nodes'][-1]['data']['composition']['payload']['sharing_authorized'] is False
    with pytest.raises(ValueError,match='forward'):save(rt,draft)
    with pytest.raises(ValueError):save(rt,draft,flow_authority=True,flow_notice='wrong')
    preview=copy.deepcopy(draft['workflow']);preview['id']=rt.store.create_workflow(preview)
    with pytest.raises(WorkflowError,match='not authorized'):rt.submit(preview)
    assert not calls


def test_typed_transport_forwards_only_verified_title_with_provenance(typed_routing):
    rt,_,_,calls,*_=typed_routing;wf=saved_typed(rt);run=wait(rt,rt.submit(wf))
    assert run['status']=='succeeded',run
    assert calls==['primary.example','third.example'] or calls==['primary.example','alternate.example']
    assert rt.typed_test_controls['seen'][1]=={'query':'Python asynchronous task documentation','language':'en','limit':3}
    records=rt.store.query('SELECT payload,signature FROM workflow_checkpoints WHERE run_id=? AND node_id=?',(run['run_id'],'search-2'))
    checkpoint=json.loads(records[0]['payload']);source=json.loads(rt.store.query('SELECT payload FROM workflow_checkpoints WHERE run_id=? AND node_id=?',(run['run_id'],'search-1'))[0][0])
    assert checkpoint['typed_input']=={'profile':PROFILE,'source_id':'search-1','source_checkpoint_hash':digest(source)}
    assert checkpoint['record']['input']['query']==source['flow_output']['structuredContent']['items'][0]['title']
    assert rt.authority.signature(checkpoint)==records[0]['signature']
    assert public_template(wf|{'is_template':1}) is None
    with pytest.raises(ValueError,match='private'):Composer(rt).validate_publish(wf,run['run_id'])
    from agent_market.workflow_comparison import Comparison,ComparisonError
    with Comparison(rt).reader() as store:
        with pytest.raises(ComparisonError):Comparison(rt).load(store,run['run_id'],'news.search.v1')


@pytest.mark.parametrize('title',[None,'x'*501,'https://unsafe.example','a@example.org','{{ $prev.output }}','<script>bad</script>','Bearer synthetic-token'])
def test_unsafe_or_empty_source_never_calls_downstream(typed_routing,title):
    rt,_,_,calls,*_=typed_routing;wf=saved_typed(rt);rt.typed_test_controls['title']=title
    run=wait(rt,rt.submit(wf));assert run['status']=='failed',run
    assert calls==['primary.example'] and rt.typed_test_controls['news_calls']==1
    assert not rt.store.query("SELECT * FROM workflow_execution_attempts WHERE run_id=? AND node_id='search-2'",(run['run_id'],))


@pytest.mark.parametrize('source',['public','schedule','event','webapp','verification'])
def test_no_public_automatic_or_deployment_authority(typed_routing,source):
    rt,_,_,calls,*_=typed_routing;wf=saved_typed(rt)
    with pytest.raises(WorkflowError):rt.submit(wf,source=source,public=source=='public')
    assert not calls


@pytest.mark.parametrize('attack',['path','target','source','mac','input','output_select'])
def test_typed_binding_tamper_fails_before_downstream(typed_routing,attack):
    rt,_,_,calls,*_=typed_routing;wf=saved_typed(rt);node=wf['nodes'][-1];p=node['data']['composition']['payload']
    if attack=='path':p['connection']['path']=['items',0,'url']
    elif attack=='target':p['connection']['target_field']='endpoint'
    elif attack=='source':p['connection']['source_id']='start'
    elif attack=='input':node['data']['input']['query']='different'
    elif attack=='output_select':node['data']['output_select']={'type':'string'}
    else:node['data']['composition']['mac']='bad'
    with pytest.raises(WorkflowError):rt.submit(wf)
    assert not calls


def test_checkpoint_tamper_is_not_forwarded_and_context_cannot_escape(typed_routing,monkeypatch):
    rt,_,_,calls,*_=typed_routing;wf=saved_typed(rt);original=rt.composer.resolve_input
    def tamper(node,row,workflow):
        with rt.store.tx() as db:db.execute("UPDATE workflow_checkpoints SET signature='tampered' WHERE run_id=? AND node_id='search-1'",(row['id'],))
        return original(node,row,workflow)
    monkeypatch.setattr(rt.composer,'resolve_input',tamper)
    run=wait(rt,rt.submit(wf));assert run['status']=='failed' and calls==['primary.example']
    with pytest.raises(ValueError):rt.composer.validate_node(wf['nodes'][-1],{'query':'forged','language':'en','limit':3})


def test_resume_uses_signed_source_checkpoint_without_second_news_call(typed_routing,monkeypatch):
    rt,_,_,calls,*_=typed_routing;wf=saved_typed(rt)
    class ProcessExit(BaseException):pass
    original=rt.composer.resolve_input;interrupted=[]
    def stop(node,row,workflow):
        if not interrupted:interrupted.append(row['id']);raise ProcessExit('isolated process exit before target preparation')
        return original(node,row,workflow)
    monkeypatch.setattr(rt.composer,'resolve_input',stop)
    job=rt.submit(wf)
    for _ in range(200):
        if interrupted:break
        time.sleep(.01)
    future=rt.futures.get(job['run_id'])
    if future:
        with pytest.raises(ProcessExit):future.result(timeout=5)
    with rt.store.tx() as db:db.execute('UPDATE workflow_runs SET lease_until=0 WHERE id=?',(job['run_id'],))
    rt.persistence.recover();rt.launch(job['run_id'])
    result=wait(rt,job);assert result['status']=='succeeded',result
    assert calls.count('primary.example')==1 and len(calls)==2


def test_connected_checkpoints_round_trip_existing_postgres_boundary(typed_routing,monkeypatch):
    import os
    from pathlib import Path
    from scripts.rehearse_workflow_postgres import rehearse,TABLES
    rt,*_=typed_routing;wf=saved_typed(rt);result=wait(rt,rt.submit(wf))
    assert result['status']=='succeeded',result
    monkeypatch.setenv('PATH','/opt/homebrew/opt/postgresql@14/bin:'+os.environ.get('PATH',''))
    proof=rehearse(rt.store._path)
    assert set(proof['tables']) == set(TABLES) and proof['round_trip_equal'] and proof['tables']['workflow_checkpoints']>=3
    Path('reports/advancement-r07-typed-flow-2026-10-18/postgres-typed-flow.json').write_text(json.dumps(proof,indent=2)+'\n')


@pytest.mark.parametrize('mode',['scheduled','event_driven'])
def test_unsupported_automation_is_rejected_before_creating_schedule_data(typed_routing,mode):
    rt,_,_,calls,*_=typed_routing;wf=saved_typed(rt)
    with pytest.raises(WorkflowError,match='manual'):
        rt.save_schedule(wf['id'],{'mode':mode,'enabled':True})
    assert not rt.store.query('SELECT * FROM workflow_schedules WHERE workflow_id=?',(wf['id'],))
    assert rt.save_schedule(wf['id'],{'mode':'manual','enabled':False})['enabled']==0
    assert not calls


def test_sharing_review_cannot_be_reused_with_another_valid_source_objective(typed_routing):
    rt,_,_,calls,*_=typed_routing;wf=saved_typed(rt)
    other=Composer(rt).generate({'prompt':'Kubernetes release news and documentation search','flow':PROFILE},1)
    source=copy.deepcopy(other['workflow']['nodes'][1])
    assert source['data']['composition']['payload']['pin']==wf['nodes'][1]['data']['composition']['payload']['pin']
    assert source['data']['input']['query']!=wf['nodes'][1]['data']['input']['query']
    assert Composer(rt).validate_node(source,source['data']['input'])
    wf['nodes'][1]=source
    with pytest.raises(WorkflowError,match='connection'):rt.submit(wf)
    assert not calls and not rt.store.query('SELECT id FROM workflow_runs WHERE workflow_id=?',(wf['id'],))
