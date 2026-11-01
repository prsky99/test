"""First-party private graphs use real local execution with controlled source HTTP."""
import asyncio
import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_market.capability_adapters import profile,arguments,normalize
from agent_market.capability_contracts import run_test
from agent_market.capability_registry import Registry
from agent_market.owned_data_agents.activation import install, check_sources
from agent_market.owned_capability_adapter import TOOL,CONTRACT
from agent_market.workspace_app_factory import NOTICE
from agent_market.workspace_typed_flows import NOTICE as RUN_NOTICE
from tests.test_owned_data_agents import engine  # noqa: F401
from tests.test_customer_typed_authoring import customer_flow,typed_release_world,typed_world,routing  # noqa: F401
from tests.test_customer_ten_workflows import definition


@pytest.fixture
def owned(customer_flow,engine):  # noqa: F811
    x=customer_flow;core,calls,state=engine
    from datetime import datetime,timezone
    core.utc_now=lambda:datetime.now(timezone.utc)
    rid=install(x.w.store,'https://agentconcierge.biz')['research-papers']
    x.w.store._owned_data_engine=core
    check_sources(x.w.store,core,{'research-papers':rid})
    resource=x.w.store.resource(rid);registry=Registry(x.w.store)
    assert registry.projection(resource)['connection_readiness']['verified_callable'] is False
    registry.approve(resource,CONTRACT,TOOL)
    async def runner(identity,**kwargs):
        result=x.w.rt.proxy.execute(identity,kwargs['tool'],kwargs['arguments'],public=True)
        return {'execution_succeeded':result.get('ok') is True,'simulated':False,'output':result.get('result')}
    with ThreadPoolExecutor(1) as pool:
        checked=pool.submit(lambda:asyncio.run(run_test(registry,resource,CONTRACT,{'query':'Public research','language':'en','limit':1},runner))).result(timeout=5)
    assert checked['ok'],checked
    calls.clear()
    yield SimpleNamespace(x=x,rid=rid,resource=resource,core=core,calls=calls,registry=registry)


@pytest.mark.parametrize('steps',[2,5,10])
def test_own_research_graph_preserves_changing_inputs_and_never_calls_public_mcp(owned,steps):
    env=owned;x=env.x;initial=x.core.credits.status(x.s.customer)['balance']
    body={'name':'First-party connected research','definition':definition([env.rid]*steps,'Battery recycling',steps),'base_flow_id':None,'base_revision':None}
    review=x.core.factory.prepare_plan(x.ws,body,x.actor)
    flow=x.core.factory.commit(x.ws,{'review_id':review['review_id'],'authorized':True,'notice':NOTICE},x.actor)
    ticket=x.core.typed.prepare(x.ws,flow['id'],{'revision':1},x.actor)
    run=x.core.typed.execute(x.ws,flow['id'],{'ticket_id':ticket['ticket_id'],'authorized':True,'notice':RUN_NOTICE},x.actor)['run']
    assert run['status']=='succeeded',run
    assert len(run['steps'])==steps
    queries=[r.url.params['query.bibliographic'] for r in env.calls]
    assert len(queries)==steps
    assert queries[1]==run['steps'][0]['output']['items'][0]['title']
    assert all(r.url.host=='api.crossref.org' for r in env.calls)
    assert x.core.credits.status(x.s.customer)['balance']==initial-1


def test_owned_adapter_full_length_query_and_no_silent_truncation(owned):
    env=owned;query='public research '*30;supplied={'query':query,'language':'en','limit':10}
    native=arguments(env.resource,CONTRACT,TOOL,supplied)
    assert native['query']==query and native['limit']==5
    raw=env.core.execute('research-papers',native)
    output=normalize(env.resource,CONTRACT,TOOL,supplied,raw)
    assert output['partial'] and output['items']
    assert output['items'][0]['retrieved_at']==raw['retrieved_at']


@pytest.mark.parametrize('fault',['identity','schema','stale','query','timestamp'])
def test_owned_adapter_denies_spoofed_or_inconsistent_records(owned,fault):
    env=owned;resource=copy.deepcopy(env.resource);supplied={'query':'Public research','language':'en','limit':1}
    raw=env.core.execute('research-papers',{'query':'Public research','limit':1})
    if fault=='identity':resource['source']='other'
    elif fault=='schema':resource['usage_full_tools']='[]'
    elif fault=='stale':raw['retrieved_at']='2020-01-01T00:00:00Z'
    elif fault=='query':raw['data']['query']='Changed question'
    else:raw['retrieved_at']='2026-10-20T00:00:00'
    with pytest.raises(ValueError):normalize(resource,CONTRACT,TOOL,supplied,raw)


def test_existing_paper_adapter_implementation_digest_is_preserved():
    from agent_market import paper_capability_adapter as paper
    from agent_market.capability_adapters import MANIFEST,PROFILE,ENDPOINT as OLD_ENDPOINT,TOOL as OLD_TOOL
    resource={'url':OLD_ENDPOINT,'usage_full_tools':[MANIFEST[PROFILE]]}
    assert profile(resource,CONTRACT,OLD_TOOL)['implementation_hash']==hashlib.sha256(Path(paper.__file__).read_bytes()).hexdigest()


def test_operator_activation_requires_exact_review_and_records_actual_evidence(owned):
    from scripts.activate_owned_workspace_contract import activate,reviewed
    env=owned;before=len(env.calls)
    with pytest.raises(ValueError,match='version changed'):
        activate(env.x.w.store,'cv_'+'0'*32,proxy=env.x.w.rt.proxy)
    assert len(env.calls)==before
    proof=reviewed(env.x.w.store.resource(env.rid))
    result=activate(env.x.w.store,proof['version_id'],proxy=env.x.w.rt.proxy)
    assert result['verified'] and result['local_execution'] and not result['public_navigation_changed']
    assert env.x.w.store.query("SELECT COUNT(*) FROM admin_audit_logs WHERE action='OWNED_WORKSPACE_CONTRACT'")[0][0]==1


def test_owned_schema_upgrade_is_exact_and_does_not_fabricate_verification(owned):
    from agent_market.owned_data_agents.catalog import tool_spec
    from agent_market.collector import usage
    env=owned;store=env.x.w.store
    original=env.registry.current(env.rid)['id']
    with store.tx() as db:
        db.execute('DELETE FROM capability_evidence WHERE version_id=?',(original,))
        db.execute('DELETE FROM capability_approvals WHERE version_id=?',(original,))
        db.execute('DELETE FROM capability_eligibility WHERE resource_id=?',(env.rid,))
    legacy=tool_spec('research-papers')
    legacy['inputSchema']['properties']['query']['maxLength']=160
    legacy['outputSchema']['properties']['data']['properties']['query']['maxLength']=160
    compact=usage.compact_tools([legacy])
    store.record_usage(env.rid,compact,usage.tools_hash(compact),{},None,None,full_tools=[legacy])
    old=env.registry.current(env.rid)['id']
    install(store,'https://agentconcierge.biz')
    new=env.registry.current(env.rid)['id'];assert new!=old
    assert not env.registry.projection(store.resource(env.rid))['connection_readiness']['verified_callable']
    assert not store.query('SELECT 1 FROM capability_approvals WHERE version_id=?',(new,))


@pytest.mark.parametrize('missing_protocol_proof',[False,True])
def test_activation_requires_actual_protocol_proof_when_optional_analytics_are_skipped(owned,monkeypatch,missing_protocol_proof):
    from scripts.activate_owned_workspace_contract import activate,reviewed
    from agent_market.owned_data_agents.dispatch import OwnedDispatch
    env=owned;store=env.x.w.store;version=env.registry.current(env.rid)['id']
    with store.tx() as db:
        db.execute("DELETE FROM capability_evidence WHERE version_id=? AND scope='execution'",(version,))
        db.execute('DELETE FROM capability_eligibility WHERE resource_id=?',(env.rid,))
    monkeypatch.setattr(OwnedDispatch,'bookkeep',lambda *args:False)
    if missing_protocol_proof:
        execute=env.x.w.rt.proxy.execute
        def without_proof(*args,**kwargs):
            result=execute(*args,**kwargs);result.pop('protocol_valid',None);return result
        monkeypatch.setattr(env.x.w.rt.proxy,'execute',without_proof)
    result=activate(store,reviewed(store.resource(env.rid))['version_id'],proxy=env.x.w.rt.proxy)
    assert result['verified'] is (not missing_protocol_proof)
    assert result['error_code']==('CONNECTION_NOT_VERIFIED' if missing_protocol_proof else None)
    status=store.query("SELECT status FROM admin_audit_logs WHERE action='OWNED_WORKSPACE_CONTRACT'")[0][0]
    assert status==('FAILED' if missing_protocol_proof else 'SUCCESS')
