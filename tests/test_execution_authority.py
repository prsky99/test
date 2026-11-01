"""Runtime controls and purpose-bound workflow delivery use isolated resources."""
import json
import time

import pytest

from agent_market.execution_authority import controls,set_controls,NOTICE
from agent_market.workflows import WorkflowError
from tests.test_managed_agent_gateway import managed,rpc
from tests.test_fast_single_recommendation import catalog
from tests.test_workflow_runtime import runtime,node,save,wait
from tests.test_admin_security_audit import admin,H,login,session_headers
from tests.test_admin_webapp_deployments import app_runtime,start
from tests.test_task_updates_security import updates
from tests.conftest import staff_session


def policy(store,**changes):
    prior=controls(store)
    return set_controls(store,{k:changes.get(k,prior[k]) for k in ('invoke_enabled','workflow_enabled','delivery_enabled','revision')},1)


class Inbox:
    def __init__(self):self.sent=[]
    def resolve(self,channel,url,**kwargs):return {'url':url,'v1':False}
    def send_update(self,channel,secret,payload,event):
        self.sent.append(payload);return True,None


def inbox(rt,wf,*,authorize=True,sources=None,principal=None):
    courier=Inbox();rt.courier=courier
    pending=rt.register_destination(wf['id'],{'channel':'webhook','url':'https://inbox.example/results','authority':True,'notice':'workflow-results-v1'})
    rt.verify_destination(wf['id'],pending['id'],courier.sent[0]['code'])
    data={'mode':'manual','enabled':False,'destination_id':pending['id']}
    if authorize:data.update(delivery_authority=True,delivery_notice=NOTICE,delivery_sources=sources or ['admin'])
    rt.save_schedule(wf['id'],data,principal=principal)
    return courier,pending['id']


def test_switch_denies_managed_legacy_and_preserves_discovery(managed):
    store,front,client,_,rid,calls,_=managed
    policy(store,invoke_enabled=False)
    r=client.post('/api/test/execute',json={'resource_id':rid,'tool':'get_weather','arguments':{'city':'Tokyo'}})
    assert r.json()['error_code']=='POLICY_DENIED' and not calls
    assert not front.proxy.execute(rid,'get_weather',{'city':'Tokyo'})['ok'] and not calls
    assert 'result' in rpc(client,f'/api/gateway/mcp/{rid}','initialize').json()
    body=client.get(f'/api/agents/{rid}').json()['agent']
    assert not body['connection_readiness']['profile_available'] and store.resource(rid)['url'] not in json.dumps(body)
    policy(store,invoke_enabled=True)
    assert client.post('/api/test/execute',json={'resource_id':rid,'tool':'get_weather','arguments':{'city':'Tokyo'}}).json()['execution_succeeded']


@pytest.mark.parametrize('kind',['a2a','x402'])
def test_switch_blocks_each_protocol_before_network(managed,kind):
    store,_,client,add,_,calls,_=managed
    rid=add('Paused '+kind,kind=kind)
    policy(store,invoke_enabled=False)
    response=client.post('/api/test/execute',json={'resource_id':rid,'message':'weather forecast','tool':'probe','arguments':{}})
    assert response.json()['error_code']=='POLICY_DENIED' and not calls


def test_switch_rechecked_after_mcp_handshake(managed):
    store,_,client,_,rid,calls,remote=managed;handle=remote.handle_request
    def turn_off(request):
        response=handle(request)
        if json.loads(request.content).get('method')=='tools/list':policy(store,invoke_enabled=False)
        return response
    remote.handle_request=turn_off
    result=client.post('/api/test/execute',json={'resource_id':rid,'tool':'get_weather','arguments':{'city':'Tokyo'}}).json()
    assert not result['execution_succeeded'] and not any(json.loads(c.content).get('method')=='tools/call' for c in calls)


def test_verified_inbox_without_new_grant_is_not_delivery_authorization(runtime):
    rt,rid,_=runtime;wf=save(rt.store,[node(resource_id=rid,action='get_weather',input={'city':'Tokyo'})])
    courier,_=inbox(rt,wf,authorize=False)
    result=wait(rt,rt.submit(wf))
    assert result['status']=='succeeded' and result['final_deliverable']['distribution']['status']=='NOT_REQUESTED'
    assert len(courier.sent)==1


def test_admin_grant_never_inherits_to_public_run(runtime):
    rt,rid,_=runtime;wf=save(rt.store,[node(resource_id=rid,action='get_weather',input={'city':'Tokyo'})])
    courier,_=inbox(rt,wf)
    assert wait(rt,rt.submit(wf))['final_deliverable']['distribution']['status']=='ACCEPTED'
    # Even a caller-supplied admin label cannot override the public capability.
    public=wait(rt,rt.submit(wf,actor='admin',source='admin',public=True))
    assert public['final_deliverable']['distribution']['status']=='NOT_REQUESTED'
    assert len(courier.sent)==2


def test_internal_template_verification_keeps_distinct_authority_without_delivery(runtime):
    rt,rid,_=runtime;wf=save(rt.store,[node(resource_id=rid,action='get_weather',input={'city':'Tokyo'})]);courier,_=inbox(rt,wf)
    job=rt.submit(wf,actor='template-verifier',source='verification');result=wait(rt,job)
    assert result['status']=='succeeded' and result['final_deliverable']['distribution']['status']=='NOT_REQUESTED'
    stored=rt.authority.run(job['run_id'],wf['id'],result['definition_hash'],'verification')
    assert stored['principal']['payload']['kind']=='verification' and not stored['grant_id'] and len(courier.sent)==1


@pytest.mark.parametrize('change',['revoke','expire','destination','digest'])
def test_pending_delivery_rechecks_bound_grant(runtime,monkeypatch,change):
    rt,rid,_=runtime;wf=save(rt.store,[node(resource_id=rid,action='get_weather',input={'city':'Tokyo'})])
    courier,destination=inbox(rt,wf);launch=rt.launch;monkeypatch.setattr(rt,'launch',lambda _:None)
    job=rt.submit(wf)
    if change=='revoke':rt.authority.revoke(wf['id'])
    elif change=='expire':
        with rt.store.tx() as db:db.execute('UPDATE workflow_delivery_grants SET expires=0')
    elif change=='destination':
        with rt.store.tx() as db:db.execute('UPDATE workflow_destinations SET sealed=? WHERE id=?',('changed-destination',destination))
    else:
        with rt.store.tx() as db:db.execute('UPDATE workflow_delivery_grants SET digest=?',('changed-version',))
    monkeypatch.setattr(rt,'launch',launch);rt.launch(job['run_id']);result=wait(rt,job)
    assert result['status']=='succeeded' and result['final_deliverable']['distribution']['status']!='ACCEPTED'
    assert len(courier.sent)==1


def test_delivery_switch_is_independent_of_successful_execution(runtime):
    rt,rid,_=runtime;wf=save(rt.store,[node(resource_id=rid,action='get_weather',input={'city':'Tokyo'})]);courier,_=inbox(rt,wf)
    policy(rt.store,delivery_enabled=False)
    result=wait(rt,rt.submit(wf))
    assert result['status']=='succeeded' and result['final_deliverable']['distribution']['status']=='NOT_AUTHORIZED'
    assert len(courier.sent)==1


def test_queued_workflow_and_new_admission_obey_stop(runtime,monkeypatch):
    rt,rid,_=runtime;wf=save(rt.store,[node(resource_id=rid,action='get_weather',input={'city':'Tokyo'})]);launch=rt.launch
    monkeypatch.setattr(rt,'launch',lambda _:None);job=rt.submit(wf)
    policy(rt.store,workflow_enabled=False)
    with pytest.raises(WorkflowError):rt.submit(wf)
    monkeypatch.setattr(rt,'launch',launch);rt.launch(job['run_id'])
    assert wait(rt,job)['status']=='failed'
    policy(rt.store,workflow_enabled=True)
    assert wait(rt,rt.submit(wf))['status']=='succeeded'


@pytest.mark.parametrize('field,value',[('kind','admin'),('audience','other-service'),('workflow_id',999),('role','superadmin')])
def test_forged_or_wrong_scope_envelope_is_rejected(runtime,field,value):
    rt,rid,_=runtime;wf=save(rt.store,[node(resource_id=rid,action='get_weather',input={'city':'Tokyo'})]);p=rt.principal('public','public',wf['id'])
    p['payload'][field]=value
    with pytest.raises(WorkflowError):rt.submit(wf,source='public',principal=p)
    assert not rt.store.query('SELECT * FROM workflow_runs')


def test_signed_wrong_audience_is_rejected_even_with_valid_signature(runtime):
    rt,rid,_=runtime;wf=save(rt.store,[node(resource_id=rid,action='get_weather',input={'city':'Tokyo'})]);p=rt.principal('public','public',wf['id'])
    p['payload']['audience']='other-service';p['signature']=rt.authority.signature(p['payload'])
    with pytest.raises(WorkflowError):rt.submit(wf,source='public',principal=p)


def test_stored_authority_tampering_stops_worker(runtime,monkeypatch):
    rt,rid,_=runtime;wf=save(rt.store,[node(resource_id=rid,action='get_weather',input={'city':'Tokyo'})]);launch=rt.launch
    monkeypatch.setattr(rt,'launch',lambda _:None);job=rt.submit(wf)
    with rt.store.tx() as db:db.execute('UPDATE workflow_run_authority SET signature=? WHERE run_id=?',('0'*64,job['run_id']))
    monkeypatch.setattr(rt,'launch',launch);rt.launch(job['run_id'])
    assert wait(rt,job)['status']=='failed'


def test_another_admin_cannot_inherit_manual_result_grant(runtime):
    from agent_market.gateway.admin_auth import create_admin_user
    rt,rid,_=runtime;wf=save(rt.store,[node(resource_id=rid,action='get_weather',input={'city':'Tokyo'})])
    with rt.store.tx() as db:other=create_admin_user(db,'another','another-password-123','Another','admin')['id']
    owner=rt.principal('admin','1',wf['id'],role='superadmin');courier,_=inbox(rt,wf,principal=owner)
    result=wait(rt,rt.submit(wf,principal=rt.principal('admin',str(other),wf['id'],role='admin')))
    assert result['final_deliverable']['distribution']['status']=='NOT_REQUESTED' and len(courier.sent)==1


def test_admin_control_api_requires_superadmin_and_current_revision(admin):
    store,client=admin
    assert client.get('/admin/api/execution-controls').status_code in (401,403)
    with store.tx() as db:
        from agent_market.gateway.admin_auth import create_admin_user
        create_admin_user(db,'manager','manager-password-123','Manager','admin')
    token=login(client,'manager','manager-password-123').json()['token']
    assert client.get('/admin/api/execution-controls',headers=session_headers(token)).status_code==403
    old=client.get('/admin/api/execution-controls',headers=H).json()
    data={k:old[k] for k in ('invoke_enabled','workflow_enabled','delivery_enabled','revision')};data['invoke_enabled']=False
    assert client.put('/admin/api/execution-controls',headers=H,json=data).status_code==200
    assert client.put('/admin/api/execution-controls',headers=H,json=data).status_code==409
    assert controls(store)['invoke_enabled'] is False
    assert store.query('SELECT COUNT(*) FROM execution_control_events')[0][0]==1


def test_downloaded_app_never_inherits_admin_inbox_and_revocation_stops_queued_run(app_runtime,monkeypatch):
    rt,wf,apps,public,_=app_runtime;courier,_=inbox(rt,wf)
    app=apps.create(wf['id'],{})
    response=start(public,app);assert response.status_code==202
    result=wait(rt,response.json())
    assert result['status']=='succeeded' and result['final_deliverable']['distribution']['status']=='NOT_REQUESTED'
    assert len(courier.sent)==1
    launch=rt.launch;monkeypatch.setattr(rt,'launch',lambda _:None)
    queued=start(public,app).json()
    apps.revoke(wf['id'],app['app_id'])
    monkeypatch.setattr(rt,'launch',launch);rt.launch(queued['run_id'])
    assert wait(rt,queued)['status']=='cancelled' and len(courier.sent)==1


@pytest.mark.parametrize('change',['grant','control'])
def test_revoke_at_last_delivery_boundary_preserves_success_without_sending(runtime,monkeypatch,change):
    rt,rid,_=runtime;wf=save(rt.store,[node(resource_id=rid,action='get_weather',input={'city':'Tokyo'})]);courier,_=inbox(rt,wf)
    open_secret=rt._open
    def change_before_dispatch(*args):
        value=open_secret(*args)
        if change=='grant':rt.authority.revoke(wf['id'])
        else:policy(rt.store,delivery_enabled=False)
        return value
    monkeypatch.setattr(rt,'_open',change_before_dispatch)
    result=wait(rt,rt.submit(wf))
    assert result['status']=='succeeded' and result['final_deliverable']['distribution']['status']=='NOT_AUTHORIZED'
    assert rt.store.query('SELECT status FROM workflow_deliveries')[0][0]=='denied'
    assert len(courier.sent)==1


def test_task_delivery_pause_preserves_pending_event_and_resumes(updates):
    store,front,client,add,headers,courier,data,vid=updates
    row=client.post('/api/task-updates',headers=headers,json={**data,'channel':'webhook','url':'https://inbox.example/updates'}).json();wid=row['id']
    code=courier.challenges[-1]['verification_code']
    assert client.post(f'/api/task-updates/{wid}/action',headers=headers,json={'action':'verify','code':code}).status_code==200
    add('New Weather',report_at=time.time());front.updates.refresh()
    event=dict(store.query('SELECT * FROM agent_task_events WHERE watch_id=?',(wid,))[0])
    policy(store,delivery_enabled=False)
    assert front.updates._attempt(event) is None and not courier.events
    pending=store.query('SELECT status,attempts FROM agent_task_events WHERE id=?',(event['id'],))[0]
    assert tuple(pending)==('pending',0)
    policy(store,delivery_enabled=True)
    assert front.updates._attempt(event)=='sent' and len(courier.events)==1


@pytest.mark.parametrize('source',['schedule','event'])
def test_automation_permission_is_bound_to_current_schedule(runtime,monkeypatch,source):
    rt,rid,_=runtime;wf=save(rt.store,[node(resource_id=rid,action='get_weather',input={'city':'Tokyo'})]);courier,dest=inbox(rt,wf)
    mode='scheduled' if source=='schedule' else 'event_driven'
    data={'mode':mode,'enabled':True,'destination_id':dest,'delivery_authority':True,'delivery_notice':NOTICE,'delivery_sources':[source]}
    rt.save_schedule(wf['id'],data);wf=rt.store.get_workflow(wf['id'])
    result=wait(rt,rt.submit(wf,source=source))
    assert result['final_deliverable']['distribution']['status']=='ACCEPTED'
    launch=rt.launch;monkeypatch.setattr(rt,'launch',lambda _:None);job=rt.submit(wf,source=source)
    rt.save_schedule(wf['id'],{**data,'delivery_authority':False,'enabled':False})
    monkeypatch.setattr(rt,'launch',launch);rt.launch(job['run_id'])
    assert wait(rt,job)['status']=='failed' and len(courier.sent)==2


def test_control_persists_across_store_handles_and_invalid_flags_fail_closed(tmp_path):
    from agent_market.gateway.store import Store
    from agent_market.execution_authority import require_enabled
    path=str(tmp_path/'shared-policy.sqlite3');first=Store(path);second=Store(path)
    try:
        policy(first,invoke_enabled=False)
        with pytest.raises(ValueError):require_enabled(second,'invoke')
        with pytest.raises(ValueError):set_controls(second,{'invoke_enabled':1,'workflow_enabled':True,'delivery_enabled':True,'revision':1},1)
        policy(second,invoke_enabled=True);require_enabled(first,'invoke')
        with first.tx() as db:db.execute('DELETE FROM execution_controls')
        with pytest.raises(ValueError):require_enabled(second,'invoke')
    finally:first._db.close();second._db.close()


def test_detached_worker_cannot_dispatch_even_without_observation_storage(runtime):
    from agent_market.observability import Operation,attempt_scope,provider_dispatch
    rt,_,_=runtime;operation=Operation(rt.journal,None,'execution');attempt=operation.attempt();operation.detach_attempts()
    with attempt_scope(attempt),pytest.raises(ValueError):provider_dispatch()


def test_admin_http_body_cannot_forge_source_or_principal(app_runtime):
    rt,wf,_,_,admin=app_runtime;headers=staff_session(rt.store)
    route=f"/admin/api/workflows/{wf['id']}/run"
    for body in ({'source':'admin'},{'actor':'sadmin'},{'principal':{'kind':'admin'}},{'authority':True}):
        assert admin.post(route,headers=headers,json=body).status_code==400
    assert not rt.history(wf['id'])


@pytest.mark.parametrize('change',['deactivate','downgrade'])
def test_real_admin_authority_rechecks_current_account_before_queued_execution(runtime,monkeypatch,change):
    rt,rid,_=runtime;wf=save(rt.store,[node(resource_id=rid,action='get_weather',input={'city':'Tokyo'})]);launch=rt.launch
    principal=rt.principal('admin','1',wf['id'],role='superadmin')
    monkeypatch.setattr(rt,'launch',lambda _:None);job=rt.submit(wf,principal=principal)
    with rt.store.tx() as db:
        if change=='deactivate':db.execute('UPDATE admin_users SET active=0 WHERE id=1')
        else:db.execute("UPDATE admin_users SET role='operator' WHERE id=1")
    monkeypatch.setattr(rt,'launch',launch);rt.launch(job['run_id'])
    assert wait(rt,job)['status']=='failed'


def test_dispatch_pause_applies_even_if_observations_were_dropped(runtime):
    from agent_market.observability import Operation,attempt_scope,provider_dispatch
    rt,_,_=runtime;operation=Operation(rt.journal,None,'workflow')
    policy(rt.store,workflow_enabled=False)
    with attempt_scope(operation.attempt()),pytest.raises(ValueError):provider_dispatch()


def test_delivery_grant_api_rejects_non_object_and_non_superadmin(app_runtime):
    from agent_market.gateway.admin_auth import create_admin_user
    rt,wf,_,_,admin=app_runtime;headers=staff_session(rt.store)
    _,destination=inbox(rt,wf,authorize=False)
    route=f"/admin/api/workflows/{wf['id']}/schedule"
    for value in ([],None,'invalid'):
        assert admin.put(route,headers=headers,json=value).status_code==400
    with rt.store.tx() as db:create_admin_user(db,'scope-admin','scope-admin-password','Scope','admin')
    token=login(admin,'scope-admin','scope-admin-password').json()['token']
    data={'mode':'manual','enabled':False,'destination_id':destination,'delivery_authority':True,'delivery_notice':NOTICE,'delivery_sources':['admin']}
    assert admin.put(route,headers=session_headers(token),json=data).status_code==403
    assert not rt.authority.grants(wf['id'])
