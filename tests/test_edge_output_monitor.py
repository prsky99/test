"""Output routing observations are private, idempotent and separate from execution."""
import json
import secrets
from types import SimpleNamespace

from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
import httpx
import pytest

from agent_market.edge_gateway.output_monitor import dashboard,record
from agent_market.edge_gateway import output_relay
from agent_market.edge_gateway.config import EdgeError
from agent_market.edge_gateway.auth import verify_service,service_mac,canonical
from tests.test_edge_gateway import edge,catalog,service_request,prepare,proposal,ORIGIN
from tests.test_dashboard import dash
from tests.test_admin_next import login


def event(**extra):return {'id':'eo_'+secrets.token_hex(16),'outcome':'edge','source':'admin','reason':'delivered','bytes':12,**extra}


def test_delivery_observations_are_idempotent_and_do_not_infer_origin_from_missing_data(edge):
    value=event();record(edge.service,value);record(edge.service,value)
    record(edge.service,event(outcome='origin',reason='cache_miss'))
    record(edge.service,event(outcome='error',reason='edge_error'))
    result=dashboard(edge.service,hours=1)
    assert result['totals']=={'edge':1,'origin':1,'error':1,'edge_origin_relay':0,'confirmed':2,'edge_share':0.5}
    assert result['fallback_reasons']==[{'reason':'cache_miss','count':1}]
    assert result['coverage']['execution_is_not_delivery'] and result['coverage']['unobserved_is_not_origin']
    assert sum(row['edge'] for row in result['timeline'])==1
    assert edge.endpoint not in json.dumps(result) and edge.token not in json.dumps(result)
    with pytest.raises(EdgeError):record(edge.service,event(source='https://secret.example'))


def test_observations_require_existing_service_mac_and_replay_nonce(edge):
    path='/api/edge-gateway-internal/v1/output-observation'
    assert edge.client.post(path,json=event()).status_code==401
    identity=secrets.token_hex(16);value=event()
    assert service_request(edge,'output-observation',value,nonce=identity).status_code==200
    assert service_request(edge,'output-observation',value,nonce=identity).status_code==401
    assert dashboard(edge.service)['totals']['edge']==1


@pytest.mark.parametrize('reason',['origin_http_502','origin_http_503','edge_http_503','origin_unavailable','stream_error','client_cancelled'])
def test_error_stage_is_private_and_preserved_without_changing_history(edge,reason):
    legacy=event(outcome='error',source='chat',reason='edge_error')
    record(edge.service,legacy)
    value=event(outcome='error',source='chat',reason=reason)
    record(edge.service,value);record(edge.service,value)
    result=dashboard(edge.service)
    assert result['totals']['error']==2
    assert result['totals']['edge']==0
    assert {r['reason']:r['count'] for r in result['failure_reasons']}=={'edge_error':1,reason:1}
    assert {r['reason'] for r in result['recent']}=={'edge_error',reason}
    assert not edge.calls
    for invalid in ('origin_http_200','origin_http_600','origin_http_https://private.example','stream_error:secret'):
        with pytest.raises(EdgeError):record(edge.service,event(outcome='error',reason=invalid))


def test_worker_origin_relay_is_verified_and_only_actual_origin_fallback_is_counted(edge):
    payload=proposal(edge)['input'];grant=prepare(edge);path='/api/origin-gateway/v1/runs/'+grant['run_id']+'/stream'
    headers={'Origin':ORIGIN,'Authorization':'Bearer '+grant['access_token'],'X-Edge-Origin-Relay':'v1'}
    assert edge.client.post(path,json=payload,headers=headers).status_code==401 and not edge.calls
    raw=canonical(payload).encode();stamp=str(int(edge.clock[0]));nonce=secrets.token_hex(16)
    headers.update({'Content-Type':'application/json','X-Edge-Time':stamp,'X-Edge-Nonce':nonce,'X-Edge-Signature':service_mac(edge.config.key,'POST',path,stamp,nonce,raw)})
    assert edge.client.post(path,content=raw,headers=headers).status_code==200
    assert dashboard(edge.service)['totals']['origin']==0 and len(edge.calls)==1
    assert edge.client.post(path,content=raw,headers=headers).status_code==401 and len(edge.calls)==1
    other=prepare(edge)
    response=edge.client.post('/api/origin-gateway/v1/runs/'+other['run_id']+'/stream',json=payload,headers={'Origin':ORIGIN,'Authorization':'Bearer '+other['access_token']})
    assert response.status_code==200 and dashboard(edge.service)['totals']['origin']==1 and len(edge.calls)==2


def test_monitor_requires_personal_role_and_supported_window(dash,edge):
    world,client=dash;world.store._edge_gateway_service=edge.service
    path='/admin/api/v2/gateway/edge-monitor'
    assert client.get(path).status_code in (401,403)
    headers=login(client)
    assert client.get(path+'?hours=3',headers=headers).status_code==400
    response=client.get(path+'?hours=24',headers=headers)
    assert response.status_code==200 and response.json()['totals']['edge_share'] is None
    assert 'no-store' in response.headers['cache-control'] and not edge.calls


@pytest.fixture
def relay(edge):
    from agent_market.gateway import admin_auth
    with edge.store.tx() as db:
        admin_auth.init_admin_auth_db(db)
        user=admin_auth.create_admin_user(db,'relay-user','Relay-test-password','Fixture','admin')
        token=admin_auth.create_session(db,user['id'],user['username'],user['role'],user['name'])
        other=admin_auth.create_session(db,user['id'],user['username'],user['role'],user['name'])
    app=FastAPI();calls=[]
    @app.post('/admin/api/test/execute')
    def execute(request:Request):
        output_relay.actor(edge.service,request);calls.append(True)
        return JSONResponse({'ok':True,'output_text':'Local or private-credential Agent output'})
    output_relay.install(app,edge.front)
    client=TestClient(app,base_url='http://localhost:8200')
    return SimpleNamespace(client=client,headers={'X-Dashboard':'1','Authorization':'Bearer '+token,'X-Edge-Output-Transport':'v1'},other=other,calls=calls)


def test_private_computed_output_is_offered_to_edge_and_cache_failure_reads_same_saved_result(edge,relay,monkeypatch):
    actual=output_relay.publish;sent=[]
    def publish(service,principal,origin,body,status):
        def upstream(request):
            assert 'authorization' not in request.headers and 'cookie' not in request.headers
            value=json.loads(request.content);sent.append(value)
            verify_service(service.config.key,'POST',request.url.path,request.headers,request.content,now=service.clock())
            return httpx.Response(200,json={'ok':True,'run':value['run'],'hash':value['hash']})
        return actual(service,principal,origin,body,status,client=httpx.Client(transport=httpx.MockTransport(upstream)))
    monkeypatch.setattr(output_relay,'publish',publish)
    response=relay.client.post('/admin/api/test/execute',json={},headers=relay.headers)
    assert response.headers['content-type'].startswith(output_relay.MEDIA)
    grant=response.json();assert 'output_text' not in response.text and len(sent)==1 and len(relay.calls)==1
    value={'run':grant['run_id'],'capability':grant['access_token'],'origin':'http://localhost:8200'}
    through_worker=service_request(edge,'output-relay-read',value)
    assert through_worker.status_code==200 and through_worker.json()['body']['ok']
    assert service_request(edge,'output-relay-read',{**value,'origin':'https://evil.example'}).status_code==401
    path='/admin/api/v2/gateway/edge-output/'+grant['run_id']
    foreign={**relay.headers,'Authorization':'Bearer '+relay.other}
    assert relay.client.get(path,headers=foreign).status_code==404
    restored=relay.client.get(path,headers=relay.headers)
    assert restored.json()['output_text']=='Local or private-credential Agent output'
    assert len(relay.calls)==1 and dashboard(edge.service)['totals']['origin']==1


def test_relay_failure_returns_original_output_without_reexecuting_agent(edge,relay,monkeypatch):
    monkeypatch.setattr(output_relay,'publish',lambda *a,**k:(_ for _ in ()).throw(EdgeError('EDGE_UNAVAILABLE')))
    response=relay.client.post('/admin/api/test/execute',json={},headers=relay.headers)
    assert response.json()['ok'] and response.headers['x-execution-delivery']=='origin-fallback'
    assert len(relay.calls)==1 and dashboard(edge.service)['fallback_reasons']==[{'reason':'publish_failed','count':1}]


def test_readiness_policy_fallback_is_recorded_apart_from_publish_failures(edge,relay,monkeypatch):
    monkeypatch.setattr(output_relay,'publish',lambda *a,**k:(_ for _ in ()).throw(EdgeError('EDGE_NOT_READY')))
    response=relay.client.post('/admin/api/test/execute',json={},headers=relay.headers)
    assert response.json()['ok'] and response.headers['x-execution-delivery']=='origin-fallback'
    assert dashboard(edge.service)['fallback_reasons']==[{'reason':'edge_not_ready','count':1}]


def test_unauthenticated_output_does_not_execute_or_return_an_envelope(edge,relay):
    response=relay.client.post('/admin/api/test/execute',json={},headers={'X-Edge-Output-Transport':'v1'})
    assert response.status_code==401 and not relay.calls


def test_legacy_api_without_browser_negotiation_still_passes_its_output_through_edge(edge,relay,monkeypatch):
    seen=[]
    def publish(service,principal,origin,body,status):
        seen.append('publish');return {'body':body,'status':status}
    def compatibility(service,envelope,origin):seen.append('edge-read');return envelope
    monkeypatch.setattr(output_relay,'publish',publish);monkeypatch.setattr(output_relay,'compatibility',compatibility)
    headers={k:v for k,v in relay.headers.items() if k!='X-Edge-Output-Transport'}
    response=relay.client.post('/admin/api/test/execute',json={},headers=headers)
    assert response.json()['ok'] and response.headers['x-execution-delivery']=='edge'
    assert seen==['publish','edge-read'] and len(relay.calls)==1


@pytest.mark.parametrize('error,stage,reason',[
    (EdgeError('PUBLISH_HTTP',503),'publish','publish_http_503'),
    (EdgeError('PUBLISH_HTTP',401),'publish','publish_http_401'),
    (EdgeError('READBACK_HTTP',503),'readback','readback_http_503'),
    (EdgeError('PUBLISH_MISMATCH'),'publish','publish_mismatch'),
    (EdgeError('RESULT_INVALID'),'readback','readback_mismatch'),
    (httpx.ReadTimeout('secret https://x/y'),'publish','publish_timeout'),
    (httpx.ConnectError('down'),'readback','readback_connect'),
    (httpx.RemoteProtocolError('bad'),'publish','publish_transport'),
    (ValueError('bad json'),'readback','readback_invalid'),
    (EdgeError('EDGE_NOT_READY'),'publish','edge_not_ready'),
    (RuntimeError('x'),'publish','publish_failed')])
def test_fallback_records_a_safe_cause_instead_of_one_publish_failed(edge,relay,monkeypatch,error,stage,reason):
    # 11-09: 717 fallbacks were all "publish_failed", so their cause was never recorded (11-11).
    from agent_market.edge_gateway.output_monitor import REASONS
    assert output_relay.failure_reason(error,stage)==reason and reason in REASONS
    monkeypatch.setattr(output_relay,'publish',lambda *a,**k:(_ for _ in ()).throw(error))
    response=relay.client.post('/admin/api/test/execute',json={},headers=relay.headers)
    assert response.status_code==200 and response.headers['x-execution-delivery']=='origin-fallback'
    if stage=='publish':
        assert dashboard(edge.service)['fallback_reasons']==[{'reason':reason,'count':1}]


def test_store_busy_is_its_own_cause():
    from agent_market.application_store_postgres import WriterBusy
    assert output_relay.failure_reason(WriterBusy(),'publish')=='publish_store_busy'
