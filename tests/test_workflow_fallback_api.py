"""Dynamic private/public API boundaries for informational workflow alternatives."""
import time
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.concierge.front import Front,create_front_app,get_front_workflow_templates
from agent_market.gateway.dashboard import dashboard_router
from agent_market.gateway.admin_auth import create_admin_user
from tests.test_admin_security_audit import login,session_headers
from tests.test_workflow_fallback import routing,config,activate,NOTICE  # noqa: F401,F811
from tests.test_workflow_runtime import wait
from tests.conftest import STAFF, staff_session  # individual staff session; the machine token reads aggregates only

H=STAFF


@pytest.fixture
def routing_api(routing):
    rt,wf,*_=routing
    proxy=rt.proxy
    front=Front(rt.store,allow_private=True);front.proxy=front.workflows.proxy=proxy
    public=TestClient(create_front_app(front),base_url='https://agentconcierge.biz')
    app=FastAPI();app.include_router(dashboard_router(rt.store,rt.store._path,'fallback-test-secret',None,front=front,ssl_manager=Mock(get_status=lambda:{})))
    staff_session(rt.store)
    admin=TestClient(app,base_url='https://admin.test')
    yield routing,public,admin
    public.close();admin.close()


@pytest.mark.parametrize('role',['operator','admin'])
def test_policy_control_and_attempt_inspection_need_superadmin(routing_api,role):
    routing,public,admin=routing_api;rt,wf,*_=routing
    with rt.store.tx() as db:create_admin_user(db,'viewer','viewer-long-password','Viewer',role)
    token=login(admin,'viewer','viewer-long-password').json()['token'];headers=session_headers(token)
    job=rt.submit(wf);wait(rt,job)
    for path in ('/admin/api/fallback-control',f"/admin/api/workflows/{wf['id']}/fallback",f"/admin/api/workflows/runs/{job['run_id']}/recovery"):
        assert admin.get(path).status_code in (401,403)
        assert admin.get(path,headers=headers).status_code==403
        assert public.get(path).status_code==404
        allowed=admin.get(path,headers=H);assert allowed.status_code==200 and allowed.headers['cache-control']=='no-store'
    assert admin.put('/admin/api/fallback-control',headers=headers,json={'enabled':True,'revision':0}).status_code==403
    assert not rt.fallback.control()['enabled']


@pytest.mark.parametrize('body',[
    {'allow_fallback':True},{'allow_fallback':'true','fallback_notice':NOTICE},
    {'allow_fallback':True,'fallback_notice':'outdated'}, {'resource_id':123},
    {'fallback_policy':{'mode':'canary'}},{'nodes':[]}, {'allow_fallback':1,'fallback_notice':NOTICE},
])
def test_public_body_cannot_replace_graph_policy_or_consent(routing_api,body):
    routing,public,_=routing_api;rt,wf,*_=routing
    before=len(rt.history(wf['id']))
    response=public.post('/api/workflows/run',json={'template_id':wf['id'],**body})
    assert response.status_code==400,response.text
    assert len(rt.history(wf['id']))==before


def test_public_optin_is_bound_to_capability_and_hides_private_policy(routing_api,monkeypatch):
    routing,public,admin=routing_api;rt,wf,_,calls,modes,*_=routing;activate(routing,monkeypatch)
    assert next(t for t in get_front_workflow_templates(rt.store) if t['id']==wf['id'])['fallback_available']
    modes['primary.example']='error'
    result=public.post('/api/workflows/run',json={'template_id':wf['id'],'allow_fallback':True,'fallback_notice':NOTICE})
    assert result.status_code==202,result.text
    job=result.json();outcome=wait(rt,job);assert outcome['status']=='succeeded'
    route='/api/workflows/runs/'+job['run_id']
    assert public.get(route).status_code==404
    response=public.get(route,headers={'X-Workflow-Key':job['run_key']})
    assert response.status_code==200 and response.json()['node_results'][0]['fallback_used']
    for private in ('connection_version_id','policy_revision','control_revision','"input"','signature','capability_approvals','alternate.example'):
        assert private not in response.text
    inspected=admin.get('/admin/api/workflows/runs/'+job['run_id']+'/recovery',headers=H)
    assert len(inspected.json()['routing']['attempts'])==2
    assert calls==['primary.example','alternate.example']


def test_policy_api_cas_validation_and_invalid_json(routing_api):
    routing,_,admin=routing_api;rt,wf,ids,*_=routing
    # A global switch without a current canary must not report activation.
    assert admin.put('/admin/api/fallback-control',headers=H,json={'enabled':True,'revision':0}).status_code==409
    config(rt,wf,ids);assert wait(rt,rt.submit(wf))['status']=='succeeded'
    config(rt,wf,ids,'canary')
    assert admin.put('/admin/api/fallback-control',headers=H,json={'enabled':True,'revision':0}).status_code==200
    assert admin.put('/admin/api/fallback-control',headers=H,json={'enabled':False,'revision':0}).status_code==409
    for body in ([],None,{'enabled':True,'revision':1,'url':'http://127.0.0.1'}):
        assert admin.put('/admin/api/fallback-control',headers=H,json=body).status_code in (400,409)
    route=f"/admin/api/workflows/{wf['id']}/fallback"
    assert admin.put(route,headers={**H,'Content-Type':'application/json'},content='{').status_code in (400,409)
    assert rt.fallback.inspect(wf['id'])['revision']==2


def test_role_revocation_between_primary_and_alternative_stops_dispatch(routing_api,monkeypatch):
    routing,_,admin=routing_api;rt,wf,_,calls,modes,hooks,_=routing;activate(routing,monkeypatch)
    modes['primary.example']='error'
    def revoke(_):
        with rt.store.tx() as db:db.execute("UPDATE admin_users SET active=0 WHERE username='synthetic-staff'")
    hooks['primary.example']=revoke
    response=admin.post(f"/admin/api/workflows/{wf['id']}/run",headers=H,json={'allow_fallback':True,'fallback_notice':NOTICE})
    assert response.status_code==202,response.text
    result=wait(rt,response.json());assert result['status']=='failed' and calls==['primary.example']
    assert not result['node_results'][0].get('fallback_used')


@pytest.mark.parametrize('contract',[[],{},None,1,True])
def test_nested_contract_types_are_rejected_without_internal_errors(routing_api,contract):
    routing,_,admin=routing_api;rt,wf,ids,*_=routing
    body={'revision':0,'mode':'shadow','pairs':[{'node_id':'search','resource_id':ids[1],'contract_id':contract}],
          'authority':True,'notice':NOTICE,'canary_percent':5,'max_runs':10,'expires':time.time()+3600}
    response=admin.put(f"/admin/api/workflows/{wf['id']}/fallback",headers=H,json=body)
    assert response.status_code==409 and 'Traceback' not in response.text
    assert rt.fallback.inspect(wf['id'])['revision']==0
