"""Exercise actual authorized runtime paths with the new delivery boundary."""
import pytest

from agent_market.observability import provider_dispatch
from tests.test_workflow_runtime import runtime, save as save_workflow, node, wait
from tests.test_workspace_execution import private, call as private_call
from tests.test_workspace_typed_flows import typed_world, save as save_typed, run as run_typed
from tests.test_workflow_fallback import routing, output


def test_workflow_runtime_routes_one_authorized_node_to_edge(runtime,monkeypatch):
    rt,rid,remote=runtime;seen=[]
    def edge(store,resource,payload,**kw):
        provider_dispatch();seen.append((resource['id'],payload))
        return {'ok':True,'result':{'content':[{'type':'text','text':'Edge weather result'}]},'hash_verified':True}
    monkeypatch.setattr('agent_market.edge_gateway.native.execute',edge)
    wf=save_workflow(rt.store,[node(resource_id=rid,action='get_weather',input={'city':'Tokyo'})])
    result=wait(rt,rt.submit(wf))
    assert result['status']=='succeeded' and len(seen)==1
    assert seen[0]==(rid,{'tool':'get_weather','arguments':{'city':'Tokyo'}})
    assert 'Edge weather result' in result['node_results'][0]['output']


def test_private_workspace_uses_edge_without_calling_native_proxy(private,monkeypatch):
    seen=[]
    def edge(store,resource,payload,**kw):
        provider_dispatch();seen.append(kw['scope'])
        return {'ok':True,'result':{'content':[{'type':'text','text':'Edge private result'}]},'hash_verified':True}
    monkeypatch.setattr('agent_market.edge_gateway.native.execute',edge)
    result=private_call(private)
    assert result['status']=='succeeded' and result['dispatched'] is not None
    assert result['output']['content'][0]['text']=='Edge private result'
    assert len(seen)==1 and private[4].calls==private[4].requests==0


def test_typed_graph_preserves_contracts_and_dispatches_each_edge_node_once(typed_world,monkeypatch):
    w=typed_world;seen=[]
    def edge(store,resource,payload,**kw):
        provider_dispatch();seen.append((kw['scope'],payload))
        return {'ok':True,'result':output(),'hash_verified':True}
    monkeypatch.setattr('agent_market.edge_gateway.native.execute',edge)
    result,_=run_typed(w,save_typed(w))
    assert result['run']['status']=='succeeded'
    assert len(seen)==len({x[0] for x in seen})==2
    assert not w.calls
    assert all(step['status']=='succeeded' for step in result['run']['steps'])


def test_private_edge_uncertainty_is_not_reexecuted_by_native_proxy(private,monkeypatch):
    seen=[]
    def edge(*a,**kw):
        provider_dispatch();seen.append(True)
        return {'ok':False,'error_code':'UPSTREAM_PROTOCOL'}
    monkeypatch.setattr('agent_market.edge_gateway.native.execute',edge)
    result=private_call(private)
    assert result['status']=='unknown' and len(seen)==1
    assert private[4].calls==private[4].requests==0


def test_workflow_explicit_credential_bindings_keep_the_original_transport(runtime,monkeypatch):
    rt,rid,_=runtime
    rt.store.set_credential('EDGE_TEST_SECRET','synthetic-private-value','test','')
    monkeypatch.setattr('agent_market.edge_gateway.native.execute',lambda *a,**kw:pytest.fail('Credential binding must stay Native'))
    wf=save_workflow(rt.store,[node(resource_id=rid,action='get_weather',input={'city':'Tokyo'},credential_refs={'extra':'EDGE_TEST_SECRET'})])
    result=wait(rt,rt.submit(wf))
    assert result['status']=='succeeded'
