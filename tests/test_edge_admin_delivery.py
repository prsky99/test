"""Admin authorization stays private; Edge tickets bind one browser and one IO."""
import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from agent_market.edge_gateway import admin_delivery
from agent_market.edge_gateway.config import EdgeError
from tests.test_edge_gateway import edge, catalog, ORIGIN, proposal, prepare
from tests.test_dashboard import dash
from tests.test_admin_next import login

USER={'user_id':8,'username':'operator-fixture','role':'admin','is_authenticated_session':True}
LOCAL='http://localhost:8200'


@pytest.fixture(autouse=True)
def enabled(edge):
    edge.service.config=replace(edge.service.config,direct_result_delivery=True,native_node_delivery=True)


def grant(edge):
    return admin_delivery.prepare(edge.service,USER,LOCAL,{'resource_id':edge.rid,'message':'Weather?'})


def test_admin_grant_is_short_lived_and_bound_to_local_origin_without_session_secrets(edge):
    value=grant(edge)
    assert value['backend']=='worker' and value['base']==ORIGIN
    row=edge.service.authorized(value['access_token'],LOCAL,value['run_id'])
    assert row['origin']==LOCAL and value['expires_in_seconds']<=120
    binding=edge.service.claim(value['access_token'],LOCAL,value['run_id'],value['input'],'worker')
    assert binding['admin_delivery'] is True and not edge.calls
    with pytest.raises(EdgeError):edge.service.authorized(value['access_token'],'https://evil.example',value['run_id'])


def test_foreign_origin_without_private_admin_context_cannot_claim(edge):
    value=edge.service.prepare('a'*64,LOCAL,proposal(edge))
    with pytest.raises(EdgeError) as exc:edge.service.claim(value['access_token'],LOCAL,value['run_id'],proposal(edge)['input'],'worker')
    assert exc.value.code=='AUTH_REQUIRED' and not edge.calls


def test_admin_origin_recovery_claims_the_same_run_once_without_edge_recursion(edge):
    value=grant(edge)
    result=asyncio.run(admin_delivery.finish(edge.service,USER,value['run_id'],recover=True))
    assert result['state']=='succeeded' and result['backend']=='origin'
    assert result['origin_result']['output']['parts']
    assert len(edge.calls)==1
    again=asyncio.run(admin_delivery.finish(edge.service,USER,value['run_id'],recover=True))
    assert 'origin_result' not in again and len(edge.calls)==1


def test_admin_does_not_repeat_an_edge_claimed_or_foreign_run(edge):
    value=grant(edge)
    edge.service.claim(value['access_token'],LOCAL,value['run_id'],value['input'],'worker')
    result=asyncio.run(admin_delivery.finish(edge.service,USER,value['run_id'],recover=True))
    assert result['state']=='dispatch_reserved' and not edge.calls
    with pytest.raises(EdgeError):asyncio.run(admin_delivery.finish(edge.service,{**USER,'user_id':9},value['run_id'],recover=True))
    assert not edge.calls


def test_disabled_or_unsupported_delivery_returns_before_dispatch(edge):
    edge.service.config=replace(edge.service.config,direct_result_delivery=False)
    assert grant(edge)=={'backend':'origin','reason':'EDGE_UNAVAILABLE'}
    assert not edge.store.query('SELECT * FROM edge_gateway_runs') and not edge.calls


def test_managed_gateway_prefers_edge_and_preserves_ambiguous_outcomes(edge,monkeypatch):
    values=[]
    def native(*a,**k):
        values.append(True)
        return {'ok':False,'error_code':'UPSTREAM_PROTOCOL'}
    monkeypatch.setattr('agent_market.edge_gateway.native.execute',native)
    response=asyncio.run(edge.front.managed_gateway.execute(edge.rid,message='Weather?'))
    assert response['execution_succeeded'] is False and response['retry_safe'] is False
    assert len(values)==1 and not edge.calls


def test_public_origin_failure_path_still_executes_exactly_once(edge):
    value=prepare(edge)
    response=edge.client.post('/api/origin-gateway/v1/runs/'+value['run_id']+'/stream',json=proposal(edge)['input'],
        headers={'Origin':ORIGIN,'Authorization':'Bearer '+value['access_token']})
    assert response.status_code==200,response.text
    assert len(edge.calls)==1


def test_admin_ticket_origin_cannot_contain_url_credentials_or_paths(edge):
    for value in ('null','https://user:secret@localhost','https://localhost/path','https://localhost?x=1'):
        with pytest.raises(EdgeError):admin_delivery.prepare(edge.service,USER,value,{'resource_id':edge.rid,'message':'Weather?'})
    assert not edge.calls


def test_private_admin_prepare_preserves_real_session_and_cross_origin_checks(dash,edge):
    world,client=dash
    world.store._edge_gateway_service=edge.service
    path='/admin/api/v2/gateway/edge-test/prepare';body={'resource_id':edge.rid,'message':'Weather?'}
    assert client.post(path,json=body,headers={'X-Dashboard':'1','Authorization':'Bearer secret'}).status_code==401
    headers=login(client)
    assert client.post(path,json=body,headers={**headers,'Origin':'https://evil.example'}).status_code==403
    response=client.post(path,json=body,headers=headers)
    assert response.status_code==200,response.text
    assert response.json()['backend']=='worker'
    assert headers['authorization'] not in response.text
    assert not edge.calls


def test_managed_x402_edge_probe_preserves_payment_challenge_without_charging(edge,catalog,monkeypatch):
    import httpx,json
    from agent_market.edge_gateway import native,managed
    from agent_market.workflow_persistence import dispatch_scope
    from tests.test_edge_gateway_catalog import enable
    enable(edge,monkeypatch)
    edge.service.config=replace(edge.service.config,native_node_delivery=True,direct_result_delivery=True)
    rid=catalog[3]('Payment challenge fixture',kind='x402',price=100,auth_observed=1)
    observed=[]
    original={'execution_succeeded':False,'transport_ok':True,'task_status':'payment_required','output':None}
    def request(req):
        observed.append(req)
        assert json.loads(req.content)=={'action':'probe'}
        assert req.headers['x-edge-result-format']=='json'
        assert not any(k in req.headers for k in ('x-payment','payment-signature','cookie','x-visitor-token'))
        run=req.url.path.split('/')[5]
        binding=edge.service.claim(req.headers['authorization'][7:],ORIGIN,run,{'action':'probe'},'worker')
        edge.service.finish(run,binding['attempt_id'],'failed')
        return httpx.Response(200,json={'run_id':run,'state':'failed','output':{'managed':original},'backend':'worker'})
    resource=edge.store.resource(rid)
    with httpx.Client(transport=httpx.MockTransport(request)) as client,dispatch_scope(lambda:None):
        result=native.execute(edge.store,resource,{'action':'probe'},scope='x402-challenge',http=client)
    projected=managed.project(edge.front.managed_gateway,resource,result)
    assert projected=={**original,'delivery_backend':'worker'} and len(observed)==1 and not edge.calls
    with dispatch_scope(lambda:pytest.fail('Paid dispatch is outside probe authority')):
        assert native.execute(edge.store,resource,{'action':'pay'},scope='x402-no-payment') is None


def test_renewal_edge_prepare_keeps_reasoned_session_audit_before_any_io(dash,edge):
    world,client=dash
    world.store._edge_gateway_service=edge.service
    headers=login(client)
    path='/admin/api/v2/catalog-tools/test/edge/prepare';body={'resource_id':edge.rid,'message':'Weather?'}
    assert client.post(path,json=body,headers=headers).status_code==400
    response=client.post(path,json=body,headers={**headers,'X-Admin-Reason':'Reviewed test fixture'})
    assert response.status_code==200,response.text
    assert response.json()['backend']=='worker'
    with world.store.tx() as db:
        logs=db.execute("SELECT status FROM admin_audit_logs WHERE target=? ORDER BY id",(path,)).fetchall()
    assert [row[0] for row in logs]==['REQUESTED','SUCCESS'] and not edge.calls


def test_admin_rejected_tool_input_returns_policy_denial_without_origin_dispatch(edge,monkeypatch):
    from agent_market.concierge.execution_policy import ExecutionDenied
    def denied(*args):raise ExecutionDenied('Unsafe tool input')
    monkeypatch.setattr('agent_market.edge_gateway.catalog.payload_for',denied)
    with pytest.raises(EdgeError) as error:grant(edge)
    assert error.value.status==403 and not edge.calls
