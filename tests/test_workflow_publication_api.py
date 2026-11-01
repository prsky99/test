"""Public connection lifecycle and capabilities use isolated approved MCP agents."""
import copy
from datetime import datetime,timedelta,timezone
import json
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.concierge.front import Front,create_front_app
from agent_market.execution_authority import controls,set_controls
from agent_market.gateway.admin_auth import init_admin_auth_db,create_admin_user
from agent_market.gateway.dashboard import dashboard_router
from agent_market.workflow_publication import PROFILE,TEST_SHARE_NOTICE,TEST_RUN_NOTICE,PUBLISH_NOTICE,SHARE_NOTICE,RUN_NOTICE
from tests.test_admin_security_audit import login,session_headers
from tests.test_workflow_fallback import routing
from tests.test_workflow_runtime import wait
from tests.test_workflow_typed_flow import typed_routing
from tests.conftest import STAFF, staff_session  # individual staff session; the machine token reads aggregates only

H=STAFF
ADMIN='/admin/api/workflow-publications'
PUBLIC='/api/workflow-connections'


@pytest.fixture
def publication_api(typed_routing):
    rt,_,_,calls,modes,*_=typed_routing
    with rt.store._lock:init_admin_auth_db(rt.store._db)
    proxy=rt.proxy
    front=Front(rt.store,allow_private=True);front.proxy=front.workflows.proxy=proxy
    public=TestClient(create_front_app(front),base_url='https://agentconcierge.biz')
    app=FastAPI();app.include_router(dashboard_router(rt.store,rt.store._path,'publication-admin',None,front=front))
    staff_session(rt.store)
    admin=TestClient(app,base_url='https://admin.example')
    yield rt,public,admin,calls,modes
    public.close();admin.close()


def candidate(api):
    rt,public,admin,*_=api
    options=admin.get(ADMIN+'/options',headers=H);assert options.status_code==200,options.text
    body={'source_id':options.json()['news'][0]['id'],'target_id':options.json()['docs'][0]['id'],
        'query':'Python development news','from_utc':(datetime.now(timezone.utc)-timedelta(hours=24)).isoformat().replace('+00:00','Z'),'limit':3}
    result=admin.post(ADMIN+'/prepare',headers=H,json=body);assert result.status_code==200,result.text
    return result.json()


def authorized(prepared,public=False,**overrides):
    return {key:prepared[key] for key in ('proposal','signature')}|{'sharing_authority':True,
        'sharing_notice':SHARE_NOTICE if public else TEST_SHARE_NOTICE,'run_authority':True,
        'run_notice':RUN_NOTICE if public else TEST_RUN_NOTICE,**overrides}


def tested(api):
    rt,public,admin,*_=api;prepared=candidate(api)
    response=admin.post(ADMIN+'/test',headers=H,json=authorized(prepared));assert response.status_code==202,response.text
    job=response.json();result=wait(rt,job);assert result['status']=='succeeded',result
    return job,prepared


tested.__test__=False


def published(api):
    rt,public,admin,*_=api;job,prepared=tested(api)
    plan=admin.post(ADMIN+'/prepare-publication',headers=H,json={'run_id':job['run_id'],'ttl_seconds':3600})
    assert plan.status_code==200,plan.text
    body={key:plan.json()[key] for key in ('proposal','signature')}|{'publication_authority':True,'publication_notice':PUBLISH_NOTICE}
    release=admin.post(ADMIN+'/publish',headers=H,json=body);assert release.status_code==200,release.text
    return release.json(),job,prepared


def public_run(api,release):
    rt,public,*_=api
    preview=public.post(PUBLIC+'/'+release['id']+'/prepare',json={});assert preview.status_code==200,preview.text
    body=authorized(preview.json(),public=True)
    accepted=public.post(PUBLIC+'/'+release['id']+'/runs',json=body);assert accepted.status_code==202,accepted.text
    job=accepted.json();assert wait(rt,job)['status']=='succeeded'
    return job,body,preview.json()


def test_new_public_run_capability_cannot_enter_legacy_read_or_cancel_routes(publication_api):
    rt,public,admin,calls,modes=publication_api;release,*_=published(publication_api)
    job,*_=public_run(publication_api,release)
    legacy='/api/workflows/runs/'+job['run_id'];headers={'X-Workflow-Key':job['run_key']}
    assert public.get(legacy,headers=headers).status_code==404
    assert public.post(legacy+'/cancel',headers=headers).status_code==404


def test_explicit_test_publish_and_public_run_are_distinct_purposes(publication_api):
    rt,public,admin,calls,modes=publication_api;prepared=candidate(publication_api)
    assert not calls and not rt.store.query('SELECT id FROM workflow_publication_grants')
    assert public.get(PUBLIC).json()['releases']==[]
    job=admin.post(ADMIN+'/test',headers=H,json=authorized(prepared)).json();assert wait(rt,job)['status']=='succeeded'
    assert len(calls)==2
    inspected=admin.post(ADMIN+'/inspect-test',headers=H,json={'run_id':job['run_id']})
    assert inspected.status_code==200 and inspected.json()['publication_eligible']
    assert not inspected.json()['expert_reviewed'] and not inspected.json()['holdout_verified']
    plan=admin.post(ADMIN+'/prepare-publication',headers=H,json={'run_id':job['run_id'],'ttl_seconds':3600}).json()
    missing={key:plan[key] for key in ('proposal','signature')}
    assert admin.post(ADMIN+'/publish',headers=H,json=missing).status_code==409
    assert not rt.store.query('SELECT id FROM workflow_publication_grants') and len(calls)==2
    release=admin.post(ADMIN+'/publish',headers=H,json=missing|{'publication_authority':True,'publication_notice':PUBLISH_NOTICE}).json()
    assert release['public_url']=='/connections/'+release['id']
    calls.clear();run,body,preview=public_run(publication_api,release)
    assert len(calls)==2 and preview['preview']['source']['input']==prepared['preview']['source']['input']
    assert preview['preview']['target']['settings']=={'language':'en','limit':3}
    assert 'query' not in preview['preview']['target']['settings']
    response=public.get(PUBLIC+'/'+release['id']+'/runs/'+run['run_id'],headers={'X-Workflow-Key':run['run_key']})
    assert response.status_code==200 and response.json()['status']=='succeeded'
    assert '"input"' not in response.text and run['run_key'] not in response.text


@pytest.mark.parametrize('role',['operator','admin'])
def test_publication_administration_requires_current_highest_admin(publication_api,role):
    rt,public,admin,calls,modes=publication_api
    with rt.store.tx() as db:create_admin_user(db,'viewer','viewer-password-long','Viewer',role)
    token=login(admin,'viewer','viewer-password-long').json()['token'];headers=session_headers(token)
    for route in ('options','tests','releases'):
        assert admin.get(ADMIN+'/'+route,headers=headers).status_code==403
        assert admin.get(ADMIN+'/'+route).status_code in (401,403)
    for route in ('prepare','test','inspect-test','prepare-publication','publish'):
        assert admin.post(ADMIN+'/'+route,headers=headers,json={}).status_code==403
    assert not calls


@pytest.mark.parametrize('changes',[{'sharing_authority':False},{'run_authority':False},{'sharing_authority':1},
    {'run_authority':1},{'sharing_notice':'old'},{'run_notice':TEST_RUN_NOTICE},{'input':{}},{'nodes':[]}])
def test_public_per_run_declarations_cannot_be_inferred_or_replaced(publication_api,changes):
    rt,public,admin,calls,modes=publication_api;release,*_=published(publication_api);calls.clear()
    prepared=public.post(PUBLIC+'/'+release['id']+'/prepare',json={}).json()
    before=len(rt.store.query('SELECT id FROM workflow_runs'))
    response=public.post(PUBLIC+'/'+release['id']+'/runs',json=authorized(prepared,public=True,**changes))
    assert response.status_code==400 and not calls and len(rt.store.query('SELECT id FROM workflow_runs'))==before


def test_public_nonce_replay_reuses_capability_and_does_not_consume_another_start_slot(publication_api):
    rt,public,admin,calls,modes=publication_api;release,*_=published(publication_api);calls.clear()
    job,body,_=public_run(publication_api,release)
    again=public.post(PUBLIC+'/'+release['id']+'/runs',json=body);assert again.status_code==202
    assert again.json()['run_id']==job['run_id'] and again.json()['run_key']==job['run_key'] and again.json()['replayed']
    assert len(calls)==2
    usage=rt.store.query("SELECT n FROM workflow_app_usage WHERE app_id=? AND identity='app' AND operation='start'",('release:'+release['id'],))
    assert usage[0]['n']==1


def test_run_capability_cannot_cross_release_and_cas_revocation_is_enforced(publication_api):
    rt,public,admin,calls,modes=publication_api;first,*_=published(publication_api);second,*_=published(publication_api)
    job,*_=public_run(publication_api,first);headers={'X-Workflow-Key':job['run_key']}
    for suffix in ('','/cancel'):
        action=public.post if suffix else public.get
        assert action(PUBLIC+'/'+second['id']+'/runs/'+job['run_id']+suffix,headers=headers).status_code==404
    path=ADMIN+'/releases/'+first['id']+'/revoke'
    assert admin.post(path,headers=H,json={'revision':0}).status_code==409
    assert admin.post(path,headers=H,json={'revision':first['revision']}).status_code==200
    assert admin.post(path,headers=H,json={'revision':first['revision']}).status_code==409
    assert public.get(PUBLIC+'/'+first['id']+'/runs/'+job['run_id'],headers=headers).status_code==404
    assert all(item['id']!=first['id'] for item in public.get(PUBLIC).json()['releases'])


@pytest.mark.parametrize('failure',['invalid','unknown'])
def test_failed_and_unknown_public_runs_remain_readable_and_are_not_repeated(publication_api,failure):
    rt,public,admin,calls,modes=publication_api;release,*_=published(publication_api);calls.clear()
    preview=public.post(PUBLIC+'/'+release['id']+'/prepare',json={}).json()
    host=rt.store.resource(rt.store.get_workflow(rt.publication.metadata(release['id'])['workflow_id'])['nodes'][2]['resource_id'])['url'].split('/')[2]
    modes[host]=failure
    accepted=public.post(PUBLIC+'/'+release['id']+'/runs',json=authorized(preview,public=True));assert accepted.status_code==202
    job=accepted.json();assert wait(rt,job)['status']=='failed' and len(calls)==2
    path=PUBLIC+'/'+release['id']+'/runs/'+job['run_id'];headers={'X-Workflow-Key':job['run_key']}
    with patch.object(rt.publication,'current',side_effect=AssertionError('historical access must not require current providers')):
        response=public.get(path,headers=headers)
        assert response.status_code==200 and response.json()['status']=='failed'
        if failure=='unknown':assert response.json()['execution_outcome']=='unknown'
        assert public.post(path+'/cancel',headers=headers).status_code==200
    assert len(calls)==2


@pytest.mark.parametrize('raw',['[]','null','{"limit":NaN}','{"input":{}}','{"input":{},"input":{}}','x'*16001])
def test_public_prepare_rejects_unbounded_or_unreviewed_json_without_calls(publication_api,raw):
    rt,public,admin,calls,modes=publication_api;release,*_=published(publication_api);calls.clear()
    response=public.post(PUBLIC+'/'+release['id']+'/prepare',content=raw)
    assert response.status_code==400 and response.headers['cache-control']=='no-store' and not calls


def test_cross_origin_and_csrf_requests_are_rejected_without_calls(publication_api):
    rt,public,admin,calls,modes=publication_api;release,*_=published(publication_api);calls.clear()
    path=PUBLIC+'/'+release['id']+'/prepare'
    for headers in ({'Origin':'https://attacker.example'},{'Origin':'null'},{'Sec-Fetch-Site':'cross-site'}):
        assert public.post(path,headers=headers,json={}).status_code==403
    assert admin.post(ADMIN+'/prepare',headers={**H,'Origin':'https://attacker.example'},json={}).status_code==403
    assert not calls


def test_public_projection_page_and_local_asset_exclude_private_authority(publication_api):
    rt,public,admin,calls,modes=publication_api;release,*_=published(publication_api);calls.clear()
    listing=public.get(PUBLIC);detail=public.get(PUBLIC+'/'+release['id']);page=public.get(release['public_url'])
    assert listing.status_code==detail.status_code==page.status_code==200
    assert page.headers['cache-control']=='no-store' and page.headers['x-frame-options']=='DENY'
    assert "frame-ancestors 'none'" in page.headers['content-security-policy'] and 'unsafe-inline' not in page.headers['content-security-policy']
    asset=public.get('/assets/public-connection.js');assert asset.status_code==200 and 'javascript' in asset.headers['content-type']
    for text in (listing.text,detail.text,page.text):
        for private in ('primary.example','alternate.example','third.example','composition','credential_refs','"nodes"','"pin"','"owner"','"proof"'):
            assert private not in text
    assert not calls


@pytest.mark.parametrize('change',['expired_ticket','pause_resume','after_validation_pause_resume'])
def test_expiry_and_execution_control_changes_refuse_public_call_before_admission(publication_api,change,monkeypatch):
    rt,public,admin,calls,modes=publication_api;release,*_=published(publication_api);calls.clear()
    prepared=public.post(PUBLIC+'/'+release['id']+'/prepare',json={}).json();body=authorized(prepared,public=True)
    before=len(rt.store.query('SELECT id FROM workflow_runs'))
    def toggle():
        flags=controls(rt.store)
        set_controls(rt.store,{**{key:flags[key] for key in ('invoke_enabled','workflow_enabled','delivery_enabled','revision')},'workflow_enabled':False},1)
        flags=controls(rt.store)
        set_controls(rt.store,{**{key:flags[key] for key in ('invoke_enabled','workflow_enabled','delivery_enabled','revision')},'workflow_enabled':True},1)
    if change=='pause_resume':toggle()
    elif change=='after_validation_pause_resume':
        accepted=rt.publication.accepted_run
        def changed(*args):
            result=accepted(*args);toggle();return result
        monkeypatch.setattr(rt.publication,'accepted_run',changed)
    path=PUBLIC+'/'+release['id']+'/runs'
    if change=='expired_ticket':
        with patch('agent_market.workflow_publication.time.time',return_value=prepared['proposal']['expires']+1):
            response=public.post(path,json=body)
    else:response=public.post(path,json=body)
    assert response.status_code==400 and not calls
    assert len(rt.store.query('SELECT id FROM workflow_runs'))==before


def test_new_public_profile_cannot_be_downgraded_to_legacy_templates_or_sdk_exports(publication_api):
    rt,public,admin,calls,modes=publication_api;release,job,_=published(publication_api);calls.clear()
    identity=rt.store.query('SELECT workflow_id FROM workflow_runs WHERE id=?',(job['run_id'],))[0]['workflow_id']
    rt.store.update_workflow(identity,{'is_template':1})
    assert public.post('/api/workflows/run',json={'template_id':identity}).status_code==404
    assert admin.post(f'/admin/api/workflows/{identity}/export-app/package',headers=H,json={}).status_code==400
    options=admin.get(f'/admin/api/workflows/{identity}/export-app-v12/options',headers=H)
    assert options.status_code==200 and not options.json()['available']
    assert not calls


def test_unavailable_provider_readiness_does_not_hide_release_metadata_or_page(publication_api):
    rt,public,admin,calls,modes=publication_api;release,*_=published(publication_api);calls.clear()
    with patch.object(rt.publication,'current',side_effect=ValueError('isolated provider eligibility withdrawal')):
        detail=public.get(PUBLIC+'/'+release['id'])
        page=public.get(release['public_url'])
        assert detail.status_code==200 and detail.json()['release']['available'] is False
        assert page.status_code==200
    assert not calls
