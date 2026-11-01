"""Native orchestration keeps durable fences and never retries uncertain Edge IO."""
import json
from dataclasses import replace

import httpx
import pytest

from agent_market.edge_gateway import native
from agent_market.concierge.execution_policy import ExecutionDenied
from agent_market.workflow_persistence import dispatch_scope, FenceLost
from tests.test_edge_gateway import edge, catalog, ORIGIN


@pytest.fixture(autouse=True)
def native_enabled(edge):
    edge.service.config=replace(edge.service.config,native_node_delivery=True)


def call(edge, client, scope='node-1'):
    return native.execute(edge.store, edge.store.resource(edge.rid), {'message':'Weather?'},
                          scope=scope, http=client)


def transport(edge, seen, *, broken=False, foreign=False):
    def request(req):
        seen.append(req)
        assert req.url.host=='agentconcierge.biz'
        assert not any(k in req.headers for k in ('cookie','x-visitor-token','x-real-ip'))
        assert req.headers['x-edge-result-format']=='json'
        rid=req.url.path.split('/')[5]
        binding=edge.service.claim(req.headers['authorization'][7:], ORIGIN, rid,
                                   json.loads(req.content), 'worker')
        if broken:
            raise httpx.ReadTimeout('Isolated accepted request',request=req)
        edge.service.finish(rid,binding['attempt_id'],'succeeded')
        return httpx.Response(200,json={'run_id':'er_'+'0'*32 if foreign else rid,
            'state':'succeeded','output':{'parts':[{'kind':'text','text':'Ready'}]},'backend':'worker'})
    return httpx.Client(transport=httpx.MockTransport(request),cookies={'private':'browser-secret'})


def test_native_edge_requires_a_parent_dispatch_fence(edge):
    assert native.execute(edge.store,edge.store.resource(edge.rid),{'message':'Weather?'},scope='node') is None


def test_native_rollout_defaults_to_existing_delivery(edge):
    edge.service.config=replace(edge.service.config,native_node_delivery=False)
    with dispatch_scope(lambda:pytest.fail('No dispatch while rollout is disabled')):
        assert native.execute(edge.store,edge.store.resource(edge.rid),{'message':'Weather?'},scope='node') is None


@pytest.mark.parametrize('payload',[{'tool':'read','arguments':{'api_key':'private'}},
    {'message':'Bearer private-token'}, {'tool':'read','arguments':{'nested':{'password':'private'}}},
    {'tool':'read','arguments':{'url':'https://public.example/?api_key=private'}},
    {'tool':'read','arguments':{'url':'https://user:private@public.example/'}}])
def test_native_keeps_credential_bearing_inputs_on_existing_authorized_path(edge,payload):
    with dispatch_scope(lambda:pytest.fail('No Edge dispatch for credentials')):
        assert native.execute(edge.store,edge.store.resource(edge.rid),payload,scope='node') is None


def test_native_uses_one_short_ticket_and_preserves_the_parent_dispatch(edge):
    seen=[];fenced=[]
    with transport(edge,seen) as client,dispatch_scope(lambda:fenced.append(True)):
        result=call(edge,client)
    assert result['ok'] and result['result']['parts'][0]['text']=='Ready'
    assert len(seen)==len(fenced)==1
    assert edge.endpoint not in seen[0].content.decode()
    assert edge.config.key.hex() not in str(seen[0].headers)
    assert not edge.calls


def test_native_free_limit_uses_original_transport_before_dispatch(edge):
    edge.service.observe(100000,edge.clock[0],healthy=True)
    seen=[];fenced=[]
    with transport(edge,seen) as client,dispatch_scope(lambda:fenced.append(True)):
        assert call(edge,client) is None
    assert not seen and not fenced


def test_native_timeout_after_claim_never_requests_origin_reexecution(edge):
    seen=[];fenced=[]
    with transport(edge,seen,broken=True) as client,dispatch_scope(lambda:fenced.append(True)):
        result=call(edge,client)
    assert result is not None and result['ok'] is False
    assert result['error_code']=='UPSTREAM_PROTOCOL'
    assert len(seen)==len(fenced)==1 and not edge.calls


def test_native_result_from_another_execution_is_not_accepted(edge):
    seen=[]
    with transport(edge,seen,foreign=True) as client,dispatch_scope(lambda:None):
        assert call(edge,client)['ok'] is False
    assert len(seen)==1


def test_native_scope_cannot_claim_a_completed_execution_again(edge):
    seen=[]
    with transport(edge,seen) as client,dispatch_scope(lambda:None):
        assert call(edge,client)['ok']
        with pytest.raises(ExecutionDenied) as denied:call(edge,client)
        assert denied.value.error_code=='POLICY_DENIED'
    assert len(seen)==1


def test_native_quota_fallback_cannot_repeat_a_completed_scope(edge):
    seen=[]
    with transport(edge,seen) as client,dispatch_scope(lambda:None):
        assert call(edge,client)['ok']
        edge.service.observe(100000,edge.clock[0],healthy=True)
        with pytest.raises(ExecutionDenied):call(edge,client)
    assert len(seen)==1 and not edge.calls


def test_native_parent_fence_failure_is_propagated_without_http(edge):
    def revoked():raise FenceLost('Isolated revoked parent')
    seen=[]
    with transport(edge,seen) as client,dispatch_scope(revoked),pytest.raises(FenceLost):
        call(edge,client)
    assert not seen


def test_native_queue_role_reuses_explicit_config_without_http_front(edge,monkeypatch):
    monkeypatch.setattr(edge.store,'_edge_gateway_service',None)
    monkeypatch.setattr(native,'load',lambda:replace(edge.config,providers=(),catalog_protocols=('mcp',)))
    service=native.service_for(edge.store)
    assert service.store is edge.store and service.front.courier is None
    assert service.summary()['preferred_backend']=='worker'


def test_native_ticket_uses_origin_once_when_cloudflare_route_fails_open(edge):
    seen=[];fenced=[]
    def route(req):
        seen.append(req)
        response=edge.client.post(req.url.path,content=req.content,headers=dict(req.headers))
        return httpx.Response(response.status_code,headers=response.headers,content=response.content)
    with httpx.Client(transport=httpx.MockTransport(route)) as client,dispatch_scope(lambda:fenced.append(True)):
        result=call(edge,client)
    assert result['ok'] and result['delivery_backend']=='origin'
    assert len(seen)==len(fenced)==len(edge.calls)==1
    assert edge.endpoint not in json.dumps(result)


@pytest.mark.parametrize('marker',[{'source':'agentconcierge-owned'},{'key':'agentconcierge-owned:research-papers'}])
def test_first_party_binding_never_creates_an_edge_ticket_or_dispatch(edge,monkeypatch,marker):
    resource={**edge.store.resource(edge.rid),**marker}
    monkeypatch.setattr(native,'service_for',lambda *args,**kwargs:pytest.fail('Local bindings cannot enter Edge admission.'))
    with dispatch_scope(lambda:pytest.fail('No Edge packet for a first-party handler.')):
        assert native.execute(edge.store,resource,{'tool':'search_research_papers','arguments':{'query':'public research','limit':2}},scope='owned-node') is None
    assert not edge.calls
