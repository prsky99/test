"""Isolated real MCP transport, explicit approvals and bounded routing regressions."""
import asyncio
import copy
from concurrent.futures import ThreadPoolExecutor
import json
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime,timezone

import httpx
import pytest

from agent_market.capability_contracts import CONTRACTS,run_test
from agent_market.capability_registry import Registry,canonical
from agent_market.collector import usage
from agent_market.concierge.proxy import McpProxy
from agent_market.gateway.store import Store
from agent_market.workflow_fallback import NOTICE,RoutingDenied,graph_fingerprint
from agent_market.workflows import WorkflowRuntime,WorkflowError,public_template
from tests.test_mcp_proxy import MockRemoteMcp
from tests.test_workflow_runtime import node,save,wait


def tool(contract='docs.search.v1'):
    return {'name':'search_docs' if contract=='docs.search.v1' else 'search_news','description':'Search public informational sources',
            'inputSchema':copy.deepcopy(CONTRACTS[contract]['input_schema']),
            'outputSchema':copy.deepcopy(CONTRACTS[contract]['output_schema']),
            'annotations':{'readOnlyHint':True,'destructiveHint':False,'idempotentHint':True}}


def output(contract='docs.search.v1'):
    now=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    item={'title':'Current documentation','url':'https://sources.example/current','retrieved_at':now}
    item.update({'excerpt':'Current search documentation','version':'v1'} if contract=='docs.search.v1' else {'source':'Current source','summary':'Current report','published_at':now})
    return {'content':[],'structuredContent':{'items':[item],'partial':False}}


@pytest.fixture
def routing(tmp_path):
    store=Store(str(tmp_path/'routing.sqlite3'));tools=[tool()];calls=[];modes={};hooks={}
    remote=MockRemoteMcp(tools,call_result=output())
    original=remote.handle_request
    def handle(request):
        body=json.loads(request.content or '{}');host=request.url.host;method=body.get('method')
        if method in ('initialize','server/discover') and modes.get(host)=='preflight':raise httpx.ConnectError('isolated preflight failure')
        if method=='tools/call':
            calls.append(host)
            if host in hooks:hooks[host](request)
            mode=modes.get(host)
            if mode=='unknown':raise httpx.ReadTimeout('isolated lost response')
            if mode=='error':return httpx.Response(200,json={'jsonrpc':'2.0','id':body['id'],'result':{'isError':True,'content':[{'type':'text','text':'temporary unavailable'}]}})
            if mode=='invalid':return httpx.Response(200,json={'jsonrpc':'2.0','id':body['id'],'result':{'structuredContent':{'items':[{'title':'invalid'}],'partial':False}}})
            if mode=='both':return httpx.Response(200,json={'jsonrpc':'2.0','id':body['id'],'error':{'code':-32000,'message':'isolated failure'}})
            remote.call_result=output()
        return original(request)
    remote.handle_request=handle
    client=httpx.Client(transport=remote);rt=WorkflowRuntime(store,McpProxy(store,allow_private=True,http=client))
    ids=[]
    for host in ('primary.example','alternate.example','third.example'):
        rid=store.upsert_resource({'key':'mcp:https://'+host+'/mcp','kind':'mcp','source':'mcp-registry','name':host,'description':'Public documentation search','category':'dev_tools','url':'https://'+host+'/mcp','price_usdc':0,'details':{}})
        store.record_usage(rid,usage.compact_tools(tools),usage.tools_hash(usage.compact_tools(tools)),{},None,{'ok':True},full_tools=tools)
        with store.tx() as db:db.execute("UPDATE resources SET health_status='healthy' WHERE id=?",(rid,))
        registry=Registry(store);registry.approve(store.resource(rid),'docs.search.v1','search_docs')
        async def runner(identity,**kwargs):
            result=rt.proxy.execute(identity,kwargs['tool'],kwargs['arguments'])
            return {'execution_succeeded':result.get('ok') is True,'simulated':False,'output':result.get('result')}
        with ThreadPoolExecutor(max_workers=1) as pool:
            result=pool.submit(lambda:asyncio.run(run_test(registry,store.resource(rid),'docs.search.v1',{'query':'documentation','language':'en','limit':2},runner))).result(timeout=5)
        assert result['ok'],result
        ids.append(rid)
    calls.clear()
    wf=save(store,[node('search',resource_id=ids[0],tool='search_docs',input={'query':'documentation','language':'en','limit':2})],name='Documentation Search',is_template=1)
    yield rt,wf,ids,calls,modes,hooks,remote
    for future in list(rt.futures.values()):future.result(timeout=5)
    client.close();store._db.close()


def config(rt,wf,ids,mode='shadow',**changes):
    old=rt.fallback.inspect(wf['id'])
    data={'revision':old['revision'],'mode':mode,'pairs':[{'node_id':'search','resource_id':ids[1],'contract_id':'docs.search.v1'}],
          'authority':True,'notice':NOTICE,'canary_percent':10,'max_runs':3,'expires':time.time()+3600}
    data.update(changes)
    return rt.fallback.configure(wf['id'],data,1)


def activate(routing,monkeypatch):
    rt,wf,ids,calls,_,_,_=routing
    config(rt,wf,ids);assert wait(rt,rt.submit(wf))['status']=='succeeded'
    assert calls==['primary.example'] and rt.fallback.inspect(wf['id'])['shadow_ready']
    config(rt,wf,ids,'canary');rt.fallback.set_control({'enabled':True,'revision':0},1)
    monkeypatch.setattr(rt.fallback,'sample',lambda _:0);calls.clear()


def run(rt,wf,**kwargs):return wait(rt,rt.submit(wf,allow_fallback=True,fallback_notice=NOTICE,**kwargs))


def test_default_off_and_shadow_never_invokes_alternative(routing):
    rt,wf,ids,calls,modes,_,_=routing
    assert not rt.fallback.control()['enabled']
    assert wait(rt,rt.submit(wf))['status']=='succeeded'
    assert calls==['primary.example']
    config(rt,wf,ids);calls.clear();modes['primary.example']='invalid'
    result=wait(rt,rt.submit(wf))
    assert result['status']=='succeeded' and calls==['primary.example']
    assert not rt.fallback.inspect(wf['id'])['shadow_ready']
    assert rt.fallback.decisions(result['run_id'])['decisions'][0]['reason']=='invalid_output'


def test_canary_needs_successful_shadow_and_explicit_optin(routing,monkeypatch):
    rt,wf,ids,calls,modes,_,_=routing
    with pytest.raises(RoutingDenied,match='shadow'):config(rt,wf,ids,'canary')
    activate(routing,monkeypatch);modes['primary.example']='error'
    result=wait(rt,rt.submit(wf))
    assert result['status']=='failed' and calls==['primary.example']
    assert not rt.fallback.decisions(result['run_id'])['attempts']


@pytest.mark.parametrize('failure',['error','invalid','preflight'])
def test_one_sequential_compatible_alternative_and_truthful_summary(routing,monkeypatch,failure):
    rt,wf,_,calls,modes,_,_=routing;activate(routing,monkeypatch);modes['primary.example']=failure
    result=run(rt,wf)
    assert result['status']=='succeeded',result
    assert calls==(['alternate.example'] if failure=='preflight' else ['primary.example','alternate.example'])
    item=result['node_results'][0]
    assert item['fallback_used'] and item['attempts']==2
    assert item['resource_id']!=item['requested_resource_id'] and item['agent_ref'].startswith('ag_')
    audit=rt.fallback.decisions(result['run_id']);assert len(audit['attempts'])==2
    assert audit['attempts'][0]['status']=='failed' and audit['attempts'][1]['status']=='succeeded'
    assert audit['decisions'][0]['decision']=='alternate'
    assert result['execution_outcome']=='succeeded'
    assert rt.store.query("SELECT COUNT(*) FROM workflow_run_events WHERE run_id=? AND event='run.completed'",(result['run_id'],))[0][0]==1
    assert not rt.store.query('SELECT * FROM workflow_result_outbox WHERE run_id=?',(result['run_id'],))


@pytest.mark.parametrize('failure',['unknown','both'])
def test_post_dispatch_uncertainty_never_authorizes_fallback(routing,monkeypatch,failure):
    rt,wf,_,calls,modes,_,_=routing;activate(routing,monkeypatch)
    if failure=='both':modes['alternate.example']='both';modes['primary.example']='error'
    else:modes['primary.example']=failure
    result=run(rt,wf)
    assert result['status']=='failed'
    assert calls==(['primary.example'] if failure=='unknown' else ['primary.example','alternate.example'])
    assert result['execution_outcome']==('unknown' if failure=='unknown' else 'failed')
    assert not result['node_results'][0].get('fallback_used')


@pytest.mark.parametrize('change',['kill','off_on','reapprove','schema','expire','graph','cancel','invoke','deadline'])
def test_dispatch_rechecks_control_authority_evidence_and_original_deadline(routing,monkeypatch,change):
    from agent_market.execution_authority import controls,set_controls
    rt,wf,ids,calls,modes,hooks,_=routing;activate(routing,monkeypatch);modes['primary.example']='error'
    def alter(_):
        if change in ('kill','off_on'):
            rt.fallback.set_control({'enabled':False,'revision':1},1)
            if change=='off_on':rt.fallback.set_control({'enabled':True,'revision':2},1)
        elif change=='reapprove':Registry(rt.store).approve(rt.store.resource(ids[1]),'docs.search.v1','search_docs')
        elif change=='schema':
            with rt.store.tx() as db:db.execute('UPDATE resources SET usage_full_tools=? WHERE id=?',(json.dumps([tool('news.search.v1')]),ids[1]))
        elif change=='expire':
            with rt.store.tx() as db:db.execute('UPDATE capability_evidence SET expires=0 WHERE version_id=?',(Registry(rt.store).current(ids[1])['id'],))
        elif change=='graph':rt.store.update_workflow(wf['id'],{'nodes':[node('changed')]})
        elif change=='cancel':
            run_id=rt.store.query("SELECT id FROM workflow_runs WHERE status='running'")[0][0];rt.cancel(run_id)
        elif change=='invoke':
            c=controls(rt.store);set_controls(rt.store,{k:c[k] for k in ('invoke_enabled','workflow_enabled','delivery_enabled')}|{'invoke_enabled':False,'revision':c['revision']},1)
        elif change=='deadline':
            with rt.store.tx() as db:db.execute("UPDATE workflow_runs SET deadline=? WHERE status='running'",(time.time()-1,))
    hooks['primary.example']=alter
    result=run(rt,wf)
    assert result['status'] in ('failed','cancelled') and calls==['primary.example']
    assert not any(n.get('fallback_used') for n in result['node_results'])


def test_cap_and_percent_apply_at_admission_not_per_node(routing,monkeypatch):
    rt,wf,_,calls,modes,_,_=routing;activate(routing,monkeypatch)
    monkeypatch.setattr(rt.fallback,'sample',lambda _:99)
    assert run(rt,wf)['status']=='succeeded'
    assert rt.fallback.inspect(wf['id'])['admitted']==0
    monkeypatch.setattr(rt.fallback,'sample',lambda _:0)
    for _ in range(5):assert run(rt,wf)['status']=='succeeded'
    assert rt.fallback.inspect(wf['id'])['admitted']==3
    assert calls==['primary.example']*6


@pytest.mark.parametrize('changes',[
    {'canary_percent':11},{'canary_percent':True},{'max_runs':101},{'expires':float('nan')},
    {'expires':time.time()+90000},{'authority':False},{'notice':'other'},
    {'pairs':[{'node_id':'search','resource_id':'https://private.invalid','contract_id':'docs.search.v1'}]},
    {'pairs':[{'node_id':'search','resource_id':1,'contract_id':'products.compare.v1'}]},
    {'mode':'automatic'},{'revision':999},
])
def test_policy_rejects_unsafe_or_unbounded_input(routing,changes):
    rt,wf,ids,*_=routing
    with pytest.raises((RoutingDenied,ValueError)):config(rt,wf,ids,**changes)
    assert rt.fallback.inspect(wf['id'])['revision']==0


@pytest.mark.parametrize('value',[1,'true',None,{},[]])
def test_optin_is_a_strict_boolean_and_failure_is_atomic(routing,value):
    rt,wf,*_=routing;before=rt.store.query('SELECT COUNT(*) FROM workflow_runs')[0][0]
    with pytest.raises(WorkflowError):rt.submit(wf,allow_fallback=value,fallback_notice=NOTICE)
    assert rt.store.query('SELECT COUNT(*) FROM workflow_runs')[0][0]==before


def test_unsupported_sources_bad_notice_and_idempotency_cannot_inherit_consent(routing):
    rt,wf,*_=routing
    for source in ('webapp','verification','schedule','event'):
        with pytest.raises(WorkflowError,match='consent'):rt.submit(wf,source=source,allow_fallback=True,fallback_notice=NOTICE)
    job=rt.submit(wf,idempotency='same');wait(rt,job)
    with pytest.raises(WorkflowError,match='authorization'):rt.submit(wf,idempotency='same',allow_fallback=True,fallback_notice=NOTICE)
    with pytest.raises(WorkflowError,match='consent'):rt.submit(wf,allow_fallback=True,fallback_notice='stale')


def test_policy_change_updates_digest_and_revokes_old_delivery_grants(routing):
    rt,wf,ids,*_=routing;one=rt.snapshot(wf)[1];config(rt,wf,ids);two=rt.snapshot(wf)[1]
    assert one!=two and graph_fingerprint(wf)==graph_fingerprint(public_template(wf))
    with rt.store.tx() as db:
        db.execute('INSERT INTO workflow_delivery_grants VALUES (?,?,?,?,?,?,?,?,?,?)',('test',wf['id'],two,'none','hash','admin','actor',time.time(),time.time()+1000,None))
    config(rt,wf,ids)
    assert rt.store.query('SELECT revoked FROM workflow_delivery_grants WHERE id=?',('test',))[0][0]
    assert rt.snapshot(wf)[1]!=two


def test_multi_node_run_cannot_make_two_alternative_calls(routing,monkeypatch):
    rt,wf,ids,calls,modes,_,_=routing
    nodes=copy.deepcopy(wf['nodes']);nodes.append({**copy.deepcopy(nodes[0]),'id':'second','name':'Second'})
    rt.store.update_workflow(wf['id'],{'nodes':nodes});wf=rt.store.get_workflow(wf['id'])
    pairs=[{'node_id':nid,'resource_id':ids[1],'contract_id':'docs.search.v1'} for nid in ('search','second')]
    config(rt,wf,ids,pairs=pairs);assert wait(rt,rt.submit(wf))['status']=='succeeded'
    config(rt,wf,ids,'canary',pairs=pairs);rt.fallback.set_control({'enabled':True,'revision':0},1);monkeypatch.setattr(rt.fallback,'sample',lambda _:0)
    # Use completed but semantically invalid output: the primary remains reachable,
    # yet fresh evidence is required for later nodes after this contract failure.
    modes['primary.example']='error';calls.clear();result=run(rt,wf)
    assert calls.count('alternate.example')==1
    assert sum(bool(n.get('fallback_used')) for n in result['node_results'])==1


@pytest.mark.parametrize('target',['plan','policy','receipt'])
def test_signed_admission_policy_and_shadow_cannot_be_tampered(routing,monkeypatch,target):
    rt,wf,ids,calls,_,_,_=routing;config(rt,wf,ids);result=wait(rt,rt.submit(wf));calls.clear()
    if target=='receipt':
        with rt.store.tx() as db:db.execute("UPDATE workflow_fallback_shadow SET payload=replace(payload,'workflow-shadow-v1','forged-shadow-v1')")
        with pytest.raises(RoutingDenied):config(rt,wf,ids,'canary')
    elif target=='policy':
        with rt.store.tx() as db:db.execute('UPDATE workflow_fallback_policies SET revision=revision+1')
        with pytest.raises(RoutingDenied):rt.submit(wf)
    else:
        monkeypatch.setattr(rt,'launch',lambda _:None);job=rt.submit(wf)
        with rt.store.tx() as db:db.execute("UPDATE workflow_fallback_runs SET payload=replace(payload,'workflow-fallback-run-v1','forged') WHERE run_id=?",(job['run_id'],))
        rt._execute(job['run_id']);assert rt.get(job['run_id'])['status']=='failed'
        assert not calls


def test_signed_shadow_receipt_cannot_transfer_to_different_pair(routing):
    rt,wf,ids,_,_,_,_=routing;config(rt,wf,ids);wait(rt,rt.submit(wf))
    old=rt.fallback.policy(wf['id'])[0]['fingerprint']
    config(rt,wf,ids,pairs=[{'node_id':'search','resource_id':ids[2],'contract_id':'docs.search.v1'}])
    new=rt.fallback.policy(wf['id'])[0]['fingerprint']
    with rt.store.tx() as db:db.execute('UPDATE workflow_fallback_shadow SET fingerprint=? WHERE fingerprint=?',(new,old))
    assert not rt.fallback.inspect(wf['id'])['shadow_ready']


def test_restore_disables_routes_and_requires_new_shadow(routing,tmp_path):
    from agent_market.workflow_backup import backup,restore
    rt,wf,ids,*_=routing;config(rt,wf,ids);wait(rt,rt.submit(wf))
    config(rt,wf,ids,'canary')
    rt.fallback.set_control({'enabled':True,'revision':0},1)
    source=rt.store.query('PRAGMA database_list')[0]['file'];directory=tmp_path/'backup';backup(source,directory)
    restored=tmp_path/'restored.sqlite3';restore(directory,restored)
    other=Store(str(restored));new=WorkflowRuntime(other)
    try:assert not new.fallback.control()['enabled'] and new.fallback.inspect(wf['id'])['policy'] is None
    finally:other._db.close()


def test_disable_stale_policy_and_kill_switch_do_not_need_working_providers(routing):
    rt,wf,ids,*_=routing;config(rt,wf,ids)
    with rt.store.tx() as db:db.execute("UPDATE resources SET health_status='down'")
    assert config(rt,wf,ids,'disabled')['policy']['mode']=='disabled'
    assert rt.fallback.set_control({'enabled':False,'revision':0},1)['revision']==1
    with pytest.raises(RoutingDenied):rt.fallback.set_control({'enabled':True,'revision':0},1)


def test_no_sensitive_input_or_raw_output_in_routing_metadata(routing,monkeypatch):
    rt,wf,ids,calls,modes,hooks,_=routing;activate(routing,monkeypatch);modes['primary.example']='error'
    result=run(rt,wf);metadata=canonical(rt.fallback.decisions(result['run_id']))
    for private in ('documentation','https://','structuredContent','signature','Bearer','input_hash','Current search'):assert private not in metadata
    assert rt.store.query('SELECT payload FROM workflow_fallback_runs WHERE run_id=?',(result['run_id'],))


CHILD=r'''
import os,sys,json,signal,httpx
from agent_market.gateway.store import Store
from agent_market.workflows import WorkflowRuntime
from agent_market.concierge.proxy import McpProxy
from tests.test_workflow_fallback import tool,output
from tests.test_mcp_proxy import MockRemoteMcp
path,run_id,audit,mode=sys.argv[1:]
remote=MockRemoteMcp([tool()],call_result=output());original=remote.handle_request
rt=None
def die():os.kill(os.getpid(),signal.SIGKILL)
def handle(request):
 body=json.loads(request.content or '{}')
 if body.get('method')=='tools/call':
  with open(audit,'a') as out:out.write(request.url.host+'\n');out.flush();os.fsync(out.fileno())
  if request.url.host=='primary.example':return httpx.Response(200,json={'jsonrpc':'2.0','id':body['id'],'result':{'isError':True,'content':[]}})
  if mode=='dispatched':die()
 return original(request)
remote.handle_request=handle
store=Store(path);http=httpx.Client(transport=remote);rt=WorkflowRuntime(store,McpProxy(store,allow_private=True,http=http))
if mode=='reserved':
 original_attempt=rt.fallback.attempt
 def reserve(*args,**kwargs):
  result=original_attempt(*args,**kwargs)
  if args[2]==2:die()
  return result
 rt.fallback.attempt=reserve
if mode=='checkpoint':
 original_cp=rt.persistence.checkpoint
 def cp(*args,**kwargs):original_cp(*args,**kwargs);die()
 rt.persistence.checkpoint=cp
rt._execute(run_id)
raise SystemExit('Crash boundary not reached')
'''


@pytest.mark.parametrize('phase',['reserved','dispatched','checkpoint'])
def test_sigkill_never_repeats_primary_or_alternative(routing,monkeypatch,tmp_path,phase):
    rt,wf,_,calls,_,_,_=routing;activate(routing,monkeypatch);monkeypatch.setattr(rt,'launch',lambda _:None)
    job=rt.submit(wf,allow_fallback=True,fallback_notice=NOTICE);audit=tmp_path/'calls.txt'
    child=subprocess.run([sys.executable,'-c',CHILD,rt.store._path,job['run_id'],str(audit),phase],capture_output=True,timeout=15)
    assert child.returncode==-signal.SIGKILL,child.stderr.decode()[-1000:]
    with rt.store.tx() as db:db.execute('UPDATE workflow_runs SET lease_until=0 WHERE id=?',(job['run_id'],))
    rt.persistence.recover();rt._execute(job['run_id']);result=rt.get(job['run_id'])
    expected=['primary.example'] if phase=='reserved' else ['primary.example','alternate.example']
    assert audit.read_text().splitlines()==expected and not calls
    assert result['status']==('succeeded' if phase=='checkpoint' else 'failed')
    assert result.get('execution_outcome')==('succeeded' if phase=='checkpoint' else 'unknown')


def test_late_primary_response_never_starts_alternative(routing,monkeypatch):
    import agent_market.workflow_fallback as routing_module
    rt,wf,_,calls,_,hooks,_=routing;activate(routing,monkeypatch)
    monkeypatch.setattr(routing_module,'PRIMARY_SECONDS',.02)
    hooks['primary.example']=lambda _:time.sleep(.04)
    result=run(rt,wf)
    assert result['status']=='failed' and result['execution_outcome']=='unknown'
    assert calls==['primary.example']


def test_concurrent_admission_cannot_exceed_canary_cap(routing,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    rt,wf,_,calls,_,_,_=routing;activate(routing,monkeypatch);monkeypatch.setattr(rt,'launch',lambda _:None)
    # A second runtime represents an independent process using the same database.
    store=Store(rt.store._path);other=WorkflowRuntime(store)
    monkeypatch.setattr(other,'launch',lambda _:None);monkeypatch.setattr(other.fallback,'sample',lambda _:0)
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            jobs=list(pool.map(lambda i:(rt if i%2 else other).submit(wf,allow_fallback=True,fallback_notice=NOTICE),range(8)))
        assert len(jobs)==8 and rt.fallback.inspect(wf['id'])['admitted']==3
        assert not calls
    finally:store._db.close()


def test_news_contract_preserves_period_and_newest_first_gate(routing,monkeypatch):
    rt,wf,ids,calls,modes,_,remote=routing;spec=tool('news.search.v1');remote.tools=[spec]
    original=remote.handle_request
    def news(request):
        body=json.loads(request.content or '{}')
        if body.get('method')=='tools/call':
            calls.append(request.url.host)
            value=output('news.search.v1')
            if modes.get(request.url.host)=='old_news':value['structuredContent']['items'][0]['published_at']='2020-01-01T00:00:00Z'
            return httpx.Response(200,json={'jsonrpc':'2.0','id':body['id'],'result':value})
        return original(request)
    remote.handle_request=news
    inputs={'query':'technology news','language':'en','limit':2,'from_utc':datetime.fromtimestamp(time.time()-86400,timezone.utc).isoformat()}
    registry=Registry(rt.store)
    for rid in ids[:2]:
        rt.store.record_usage(rid,usage.compact_tools([spec]),usage.tools_hash(usage.compact_tools([spec])),{},None,{'ok':True},full_tools=[spec])
        registry.approve(rt.store.resource(rid),'news.search.v1','search_news')
        async def runner(identity,**kwargs):
            result=rt.proxy.execute(identity,kwargs['tool'],kwargs['arguments'])
            return {'execution_succeeded':result.get('ok') is True,'simulated':False,'output':result.get('result')}
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(lambda:asyncio.run(run_test(registry,rt.store.resource(rid),'news.search.v1',inputs,runner))).result()['ok']
    rt.store.update_workflow(wf['id'],{'nodes':[node('search',resource_id=ids[0],tool='search_news',input=inputs)]});wf=rt.store.get_workflow(wf['id'])
    pairs=[{'node_id':'search','resource_id':ids[1],'contract_id':'news.search.v1'}]
    config(rt,wf,ids,pairs=pairs);assert wait(rt,rt.submit(wf))['status']=='succeeded'
    config(rt,wf,ids,'canary',pairs=pairs);rt.fallback.set_control({'enabled':True,'revision':0},1);monkeypatch.setattr(rt.fallback,'sample',lambda _:0)
    calls.clear();modes['primary.example']='old_news';result=run(rt,wf)
    assert result['status']=='succeeded' and result['node_results'][0]['fallback_used']
    assert calls==['primary.example','alternate.example']
    assert '2020-01-01' not in result['node_results'][0]['output']


def test_one_final_result_delivery_after_two_provider_attempts(routing,monkeypatch):
    from tests.test_execution_authority import inbox
    rt,wf,_,calls,modes,_,_=routing;activate(routing,monkeypatch);courier,_=inbox(rt,wf)
    modes['primary.example']='error';result=run(rt,wf)
    assert result['status']=='succeeded' and result['final_deliverable']['distribution']['status']=='ACCEPTED'
    assert calls==['primary.example','alternate.example'] and len(courier.sent)==2
    assert courier.sent[-1]['type']=='workflow_result'
    rt._deliver(result['run_id'],wf['id'],result);assert len(courier.sent)==2
    assert len(rt.store.query('SELECT * FROM workflow_result_outbox WHERE run_id=?',(result['run_id'],)))==1


def test_kill_switch_during_alternative_handshake_blocks_tools_call(routing,monkeypatch):
    rt,wf,_,calls,modes,_,remote=routing;activate(routing,monkeypatch);modes['primary.example']='error'
    original=remote.handle_request
    def handshake(request):
        result=original(request)
        if request.url.host=='alternate.example' and json.loads(request.content or '{}').get('method')=='tools/list':
            rt.fallback.set_control({'enabled':False,'revision':1},1)
        return result
    remote.handle_request=handshake
    result=run(rt,wf)
    assert result['status']=='failed' and calls==['primary.example']
    assert not result['node_results'][0].get('fallback_used')


def test_alternative_response_loss_is_unknown_without_third_call(routing,monkeypatch):
    rt,wf,_,calls,modes,_,_=routing;activate(routing,monkeypatch)
    modes.update({'primary.example':'error','alternate.example':'unknown'});result=run(rt,wf)
    assert result['status']=='failed' and result['execution_outcome']=='unknown'
    assert calls==['primary.example','alternate.example']
    rt.run_due();assert calls==['primary.example','alternate.example']


def test_output_alias_and_trigger_changes_invalidate_shadow_fingerprint(routing):
    rt,wf,ids,*_=routing;config(rt,wf,ids);wait(rt,rt.submit(wf));original=graph_fingerprint(wf)
    renamed=copy.deepcopy(wf);renamed['nodes'][0]['name']='Different output alias'
    assert graph_fingerprint(renamed)!=original
    triggered=copy.deepcopy(wf);triggered['trigger_type']='scheduled'
    assert graph_fingerprint(triggered)!=original
    rt.store.update_workflow(wf['id'],{'nodes':renamed['nodes']})
    with pytest.raises(RoutingDenied,match='shadow'):config(rt,renamed,ids,'canary')
    assert not rt.fallback.available(renamed)
