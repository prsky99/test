"""SDK 1.2 uses isolated approved literal agents and explicit purpose grants."""
import copy
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
import time
from unittest.mock import patch
from zipfile import ZipFile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.concierge.front import Front,create_front_app
from agent_market.gateway.admin_auth import init_admin_auth_db
from agent_market.gateway.dashboard import dashboard_router
from agent_market.workflow_apps_v12 import WorkflowAppsV12,GRANT_NOTICE,SHARE_NOTICE,RUN_NOTICE,PROFILE
from agent_market.workflow_composer import Composer,SAVE
from agent_market.execution_authority import controls,set_controls
from agent_market.workflows import WorkflowError
from tests.test_workflow_fallback import routing
from tests.test_workflow_typed_flow import typed_routing
from tests.test_workflow_runtime import wait
from tests.conftest import STAFF, staff_session  # individual staff session; the machine token reads aggregates only

ORIGIN='https://customer.example'
HEADERS=STAFF


@pytest.fixture
def v12_runtime(routing):
    rt,_,_,calls,modes,*_=routing
    rt.v12_test_modes=modes
    with rt.store._lock:init_admin_auth_db(rt.store._db)
    composer=Composer(rt);draft=composer.generate({'prompt':'Python documentation search'},1)
    identity=composer.save({k:draft[k] for k in ('proposal','signature')}|{'authority':True,'notice':SAVE},1)['id']
    wf=rt.store.get_workflow(identity);result=wait(rt,rt.submit(wf));assert result['status']=='succeeded',result
    composer.validate_publish(wf,result['run_id'])
    rt.store.update_workflow(identity,{'is_template':1,'tags':'contract_draft,composer_test:'+result['run_id']})
    calls.clear()
    yield rt,rt.store.get_workflow(identity),WorkflowAppsV12(rt),calls


@pytest.fixture
def v12_api(v12_runtime):
    rt,wf,service,calls=v12_runtime
    proxy=rt.proxy
    front=Front(rt.store,allow_private=True);front.proxy=front.workflows.proxy=proxy
    public=TestClient(create_front_app(front),base_url='https://agentconcierge.biz')
    app=FastAPI();app.include_router(dashboard_router(rt.store,':memory:','deployment-admin',None,front=front))
    staff_session(rt.store)
    admin=TestClient(app,base_url='https://admin.example')
    yield rt,wf,service,calls,public,admin
    public.close();admin.close()


def export_request(service,wf,**options):
    result=service.prepare_admin(wf['id'],{'allowed_origins':[ORIGIN],'minute_limit':10,'day_limit':500,'ttl_seconds':3600,**options},1)
    return {'proposal':result['proposal'],'signature':result['signature'],'grant_authority':True,'grant_notice':GRANT_NOTICE}


def exported(v12_runtime,**options):
    rt,wf,service,calls=v12_runtime
    result=service.export_admin(wf['id'],export_request(service,wf,**options),1)
    return result['deployment']


def run_request(prepared,**options):
    return {'proposal':prepared['proposal'],'signature':prepared['signature'],'share_authority':True,
        'share_notice':SHARE_NOTICE,'live_authority':True,'live_notice':RUN_NOTICE,**options}


def ticket(service,deployment):
    app=service.legacy.authorize(deployment['app_id'],deployment['publish_key'],ORIGIN)
    return app,service.prepare_public(app,{},ORIGIN)


def test_prepare_export_and_fixed_run_have_separate_explicit_authority(v12_runtime):
    rt,wf,service,calls=v12_runtime;request=export_request(service,wf)
    assert not calls and not rt.store.query('SELECT id FROM workflow_apps')
    deployment=service.export_admin(wf['id'],request,1)['deployment']
    assert not calls and len(rt.store.query('SELECT id FROM workflow_deployment_grants'))==1
    app,prepared=ticket(service,deployment)
    assert not calls and prepared['preview']['recipients'][0]['input']=={'query':'Python documentation search','language':'en','limit':3}
    raw=json.dumps(prepared)
    for private in ('composition','pin','owner','primary.example','alternate.example','third.example'):
        assert private not in raw
    job=service.execute(app,run_request(prepared),ORIGIN);result=wait(rt,job)
    assert result['status']=='succeeded' and len(calls)==1
    assert rt.store.query('SELECT source FROM workflow_runs WHERE id=?',(job['run_id'],))[0]['source']=='webapp'
    assert result['final_deliverable']['distribution']['status']=='NOT_REQUESTED'
    assert service.legacy.check_run(app,job['run_id'],job['run_key']) is None
    with pytest.raises(WorkflowError):service.legacy.start(app,{})


@pytest.mark.parametrize('changes',[{'share_authority':False},{'live_authority':False},{'share_authority':1},{'live_authority':1},
    {'share_notice':'old'},{'live_notice':'old'},{'input':{}},{'allow_fallback':True}])
def test_per_run_missing_or_mixed_purpose_never_calls_provider(v12_runtime,changes):
    rt,wf,service,calls=v12_runtime;deployment=exported(v12_runtime);app,prepared=ticket(service,deployment)
    before=len(rt.store.query('SELECT id FROM workflow_runs'))
    with pytest.raises(ValueError):service.execute(app,run_request(prepared,**changes),ORIGIN)
    assert not calls and len(rt.store.query('SELECT id FROM workflow_runs'))==before


def test_same_nonce_replay_recovers_same_run_capability_without_another_start_slot(v12_runtime):
    rt,wf,service,calls=v12_runtime;deployment=exported(v12_runtime,minute_limit=1);app,prepared=ticket(service,deployment)
    first=service.execute(app,run_request(prepared),ORIGIN);wait(rt,first)
    again=service.execute(app,run_request(prepared),ORIGIN)
    assert again['replayed'] and again['run_id']==first['run_id'] and again['run_key']==first['run_key'] and len(calls)==1
    usage=rt.store.query("SELECT n FROM workflow_app_usage WHERE app_id=? AND identity='app' AND operation='start'",(app['id'],))
    assert usage[0]['n']==1


def test_atomic_grant_failure_rolls_back_registered_app(v12_runtime,monkeypatch):
    rt,wf,service,calls=v12_runtime;request=export_request(service,wf)
    def failure(*args,**kwargs):raise ValueError('isolated signing failure')
    monkeypatch.setattr(service.consent,'issue',failure)
    with pytest.raises(ValueError):service.export_admin(wf['id'],request,1)
    assert not rt.store.query('SELECT id FROM workflow_apps') and not rt.store.query('SELECT id FROM workflow_deployment_grants') and not calls


def test_highest_admin_new_routes_package_and_cas_revocation(v12_api):
    rt,wf,service,calls,public,admin=v12_api;base=f"/admin/api/workflows/{wf['id']}/export-app-v12"
    assert admin.get(base+'/options').status_code in (401,403)
    options=admin.get(base+'/options',headers=HEADERS);assert options.status_code==200 and options.json()['available']
    prepared=admin.post(base+'/prepare',headers=HEADERS,json={'allowed_origins':[ORIGIN],'minute_limit':1,'day_limit':5,'ttl_seconds':3600})
    assert prepared.status_code==200,prepared.text
    body={k:prepared.json()[k] for k in ('proposal','signature')}|{'grant_authority':True,'grant_notice':GRANT_NOTICE}
    package=admin.post(base+'/package',headers=HEADERS,json=body);assert package.status_code==200,package.text
    assert package.headers['cache-control']=='no-store'
    with ZipFile(BytesIO(package.content)) as archive:manifest=json.loads(archive.read('app-manifest.json'))
    assert manifest['sdk_version']=='1.2.0' and manifest['profile']==PROFILE
    listed=admin.get(base+'/deployments',headers=HEADERS).json()['deployments'];assert len(listed)==1
    app_id=listed[0]['app_id'];legacy=f"/admin/api/workflows/{wf['id']}/apps/{app_id}"
    assert admin.delete(legacy,headers=HEADERS).status_code==409
    revoke=base+'/deployments/'+app_id+'/revoke'
    assert admin.post(revoke,headers=HEADERS,json={'revision':0}).status_code==409
    response=admin.post(revoke,headers=HEADERS,json={'revision':listed[0]['revision']});assert response.status_code==200
    assert response.json()['revision']==listed[0]['revision']+1 and not calls
    assert admin.post(revoke,headers=HEADERS,json={'revision':listed[0]['revision']}).status_code==409


def test_public_route_prepare_run_replay_and_legacy_start_downgrade_refusal(v12_api):
    rt,wf,service,calls,public,admin=v12_api;deployment=exported((rt,wf,service,calls),minute_limit=1)
    root='/api/workflow-apps-v12/'+deployment['app_id'];headers={'Origin':ORIGIN,'X-Publish-Key':deployment['publish_key']}
    prepared=public.post(root+'/prepare',headers=headers,json={});assert prepared.status_code==200,prepared.text
    body=run_request(prepared.json());first=public.post(root+'/runs',headers=headers,json=body);assert first.status_code==202,first.text
    job=first.json();wait(rt,job)
    again=public.post(root+'/runs',headers=headers,json=body);assert again.status_code==202 and again.json()['run_key']==job['run_key']
    legacy=public.post('/api/workflow-apps/'+deployment['app_id']+'/runs',headers=headers,json={})
    assert legacy.status_code in (400,429) and len(calls)==1
    observed=public.get(root+'/runs/'+job['run_id'],headers={**headers,'X-Workflow-Key':job['run_key']})
    assert observed.status_code==200 and 'input' not in observed.json()['node_results'][0]
    assert public.get(root+'/runs/'+job['run_id'],headers={**headers,'X-Workflow-Key':'x'*43}).status_code==404


@pytest.mark.parametrize('change',['unchecked','integer_consent','old_notice','signature','owner','expired','controls','empty_origin'])
def test_admin_plan_cannot_change_owner_purpose_window_or_policy(v12_runtime,change):
    rt,wf,service,calls=v12_runtime;body=export_request(service,wf)
    if change=='unchecked':body['grant_authority']=False
    elif change=='integer_consent':body['grant_authority']=1
    elif change=='old_notice':body['grant_notice']='old'
    elif change=='signature':body['proposal']['definition_hash']='0'*64
    else:
        p=body['proposal']
        if change=='owner':p['owner']='2'
        elif change=='expired':p['created']-=2000;p['expires']-=2000;p['grant_expires']-=2000
        elif change=='empty_origin':p['allowed_origins']=[]
        else:
            flags=controls(rt.store)
            set_controls(rt.store,{key:flags[key] for key in ('invoke_enabled','workflow_enabled','delivery_enabled','revision')},1)
        body['signature']=rt.authority.signature(p)
    with pytest.raises(ValueError):service.export_admin(wf['id'],body,1)
    assert not calls and not rt.store.query('SELECT id FROM workflow_apps') and not rt.store.query('SELECT id FROM workflow_deployment_grants')


@pytest.mark.parametrize('change',['signature','origin','app_id','inputs_hash','expiry','epoch'])
def test_public_ticket_is_exact_app_origin_input_and_expiry_scoped(v12_runtime,change):
    rt,wf,service,calls=v12_runtime;deployment=exported(v12_runtime);app,prepared=ticket(service,deployment)
    body=run_request(copy.deepcopy(prepared));p=body['proposal']
    if change=='signature':body['signature']='forged'
    else:
        if change=='origin':p['origin']='https://other.example'
        elif change=='app_id':p['app_id']='app_'+'0'*32
        elif change=='inputs_hash':p['inputs_hash']='0'*64
        elif change=='expiry':p['created']-=400;p['expires']-=400;p['reviewed_at']=p['created']
        else:p['reviewed_at']-=1
        body['signature']=rt.authority.signature(p)
    before=len(rt.store.query('SELECT id FROM workflow_runs'))
    with pytest.raises(ValueError):service.execute(app,body,ORIGIN)
    assert not calls and len(rt.store.query('SELECT id FROM workflow_runs'))==before


def test_concurrent_valid_ticket_reuses_one_run_and_one_capability(v12_runtime):
    rt,wf,service,calls=v12_runtime;deployment=exported(v12_runtime);app,prepared=ticket(service,deployment)
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs=list(pool.map(lambda _:service.execute(app,run_request(prepared),ORIGIN),range(4)))
    assert len({job['run_id'] for job in jobs})==len({job['run_key'] for job in jobs})==1
    assert wait(rt,jobs[0])['status']=='succeeded' and len(calls)==1
    assert len(rt.store.query('SELECT run_id FROM workflow_app_runs WHERE app_id=?',(app['id'],)))==1


@pytest.mark.parametrize('raw',['[]','null','{"input":NaN}','{"input":{}}','x'*48001])
def test_new_public_prepare_rejects_unreviewed_or_unbounded_inputs(v12_api,raw):
    rt,wf,service,calls,public,admin=v12_api;deployment=exported((rt,wf,service,calls))
    response=public.post('/api/workflow-apps-v12/'+deployment['app_id']+'/prepare',content=raw,
        headers={'Origin':ORIGIN,'X-Publish-Key':deployment['publish_key']})
    assert response.status_code==400 and response.headers['cache-control']=='no-store' and not calls
    assert 'NaN' not in response.text and 'Traceback' not in response.text


@pytest.mark.parametrize('failure',['invalid','unknown'])
def test_failed_or_unknown_provider_run_remains_readable_without_new_calls(v12_api,failure):
    rt,wf,service,calls,public,admin=v12_api;deployment=exported((rt,wf,service,calls))
    path='/api/workflow-apps-v12/'+deployment['app_id'];headers={'Origin':ORIGIN,'X-Publish-Key':deployment['publish_key']}
    prepared=public.post(path+'/prepare',headers=headers,json={});assert prepared.status_code==200
    host=rt.store.resource(wf['nodes'][1]['resource_id'])['url'].split('/')[2]
    rt.v12_test_modes[host]=failure
    accepted=public.post(path+'/runs',headers=headers,json=run_request(prepared.json()));assert accepted.status_code==202
    job=accepted.json();result=wait(rt,job);assert result['status']=='failed' and len(calls)==1
    access={**headers,'X-Workflow-Key':job['run_key']}
    for prefix in ('/api/workflow-apps-v12/','/api/workflow-apps/'):
        response=public.get(prefix+deployment['app_id']+'/runs/'+job['run_id'],headers=access)
        assert response.status_code==200,response.text
        assert response.json()['status']=='failed'
        if failure=='unknown':assert response.json()['execution_outcome']=='unknown'
    cancelled=public.post(path+'/runs/'+job['run_id']+'/cancel',headers=access)
    assert cancelled.status_code==200 and cancelled.json()['cancel_requested'] is True
    assert len(calls)==1


def test_independent_news_and_docs_preserve_fixed_query_and_reviewed_news_window(typed_routing):
    rt,_,_,calls,*_=typed_routing
    with rt.store._lock:init_admin_auth_db(rt.store._db)
    composer=Composer(rt);draft=composer.generate({'prompt':'Python news and documentation search'},1)
    identity=composer.save({k:draft[k] for k in ('proposal','signature')}|{'authority':True,'notice':SAVE},1)['id']
    wf=rt.store.get_workflow(identity);proof=wait(rt,rt.submit(wf));assert proof['status']=='succeeded'
    rt.store.update_workflow(identity,{'is_template':1,'tags':'contract_draft,composer_test:'+proof['run_id']})
    wf=rt.store.get_workflow(identity);service=WorkflowAppsV12(rt);calls.clear();rt.typed_test_controls['seen'].clear()
    deployment=service.export_admin(identity,export_request(service,wf),1)['deployment'];app,prepared=ticket(service,deployment)
    recipients=prepared['preview']['recipients'];assert len(recipients)==2
    news=next(row for row in recipients if row['contract']=='news.search.v1')
    assert news['input']['from_utc']==wf['nodes'][1]['data']['input']['from_utc']
    job=service.execute(app,run_request(prepared),ORIGIN);assert wait(rt,job)['status']=='succeeded'
    assert len(calls)==2 and len(rt.typed_test_controls['seen'])==2
    assert all(args['query']=='Python news and documentation search' for args in rt.typed_test_controls['seen'])
    assert rt.typed_test_controls['seen'][0]['from_utc']==news['input']['from_utc']


def test_export_proposal_survives_browser_json_numbers_without_exposing_private_graph(v12_runtime):
    rt,wf,service,calls=v12_runtime
    with patch('agent_market.workflow_apps_v12.time.time',return_value=float(int(time.time()))):
        body=export_request(service,wf)
    def browser_numbers(value):
        if isinstance(value,dict):return {key:browser_numbers(item) for key,item in value.items()}
        if isinstance(value,list):return [browser_numbers(item) for item in value]
        return int(value) if type(value) is float and value.is_integer() else value
    serialized=json.dumps(body['proposal'])
    for private in ('"workflow"','"nodes"','"composition"','"pin"','estimated_cost','primary.example'):
        assert private not in serialized
    result=service.export_admin(wf['id'],browser_numbers(body),1)
    assert result['deployment']['sdk_version']=='1.2.0' and not calls
