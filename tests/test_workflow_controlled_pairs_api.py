"""Private controlled-pair routes never infer authority or publish a test."""
import copy
import json
import sqlite3

import pytest

from agent_market.gateway.admin_auth import create_admin_user
from agent_market.workflow_controlled_pairs import ControlledPairs, PROFILE
from tests.test_admin_security_audit import login, session_headers
from tests.test_workflow_fallback import routing
from tests.test_workflow_fallback_api import routing_api as base_routing_api, H
from tests.test_workflow_typed_flow import typed_routing
from tests.test_workflow_runtime import wait

BASE = '/admin/api/workflow-composer/controlled-pair'
SHARE = 'workflow-controlled-pair-share-v1'
LIVE = 'workflow-controlled-pair-run-v1'


@pytest.fixture
def routing_api(typed_routing):
    yield from base_routing_api.__wrapped__(typed_routing)


def selection(options):
    return {'objective':'Latest Python news','source_id':options['sources'][0]['id'],
            'target_a_id':options['targets'][0]['id'],'target_b_id':options['targets'][1]['id']}


def prepared(admin, headers=H):
    options = admin.get(BASE + '/options', headers=headers)
    assert options.status_code == 200, options.text
    response = admin.post(BASE + '/prepare', headers=headers, json=selection(options.json()))
    assert response.status_code == 200, response.text
    return response.json()


def authorized(plan):
    return {'proposal':plan['proposal'],'signature':plan['signature'],
            'share_authority':True,'share_notice':SHARE,'live_authority':True,'live_notice':LIVE}


def test_capability_options_and_prepare_are_private_read_only_and_explicit(routing_api):
    routing, public, admin = routing_api; rt,_,_,calls,*_ = routing
    before=rt.store._db.total_changes
    inventory=admin.get('/admin/api/workflows?limit=100',headers=H)
    assert inventory.status_code == 200 and inventory.json()['controlled_pair_profile'] == PROFILE
    response=admin.get(BASE+'/options',headers=H)
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    options=response.json(); assert options['profile'] == PROFILE
    assert len(options['sources']) >= 1 and len(options['targets']) >= 2
    assert all(set(row)=={'id','label'} for row in options['sources']+options['targets'])
    plan=prepared(admin)
    assert plan['profile']==PROFILE and plan['executed'] is False
    assert plan['preview']['max_calls']==3 and plan['preview']['max_seconds']==25
    assert plan['preview']['language']=='en' and plan['preview']['limit']==3
    assert not calls and rt.store._db.total_changes == before
    assert public.get(BASE+'/options').status_code == 404


def test_one_explicit_pair_dispatches_source_once_and_equal_queries_to_both_targets(routing_api):
    routing,_,admin=routing_api;rt,_,_,calls,*_=routing
    plan=prepared(admin);body=authorized(plan)
    response=admin.post(BASE+'/execute',headers=H,json=body)
    assert response.status_code == 202 and response.headers['cache-control']=='no-store',response.text
    job=response.json();run=wait(rt,job)
    assert run['status']=='succeeded',run
    assert len(calls)==3 and calls.count('primary.example')==1 and set(calls)=={'primary.example','alternate.example','third.example'}
    seen=rt.typed_test_controls['seen']
    assert seen[1]==seen[2]=={'query':'Python asynchronous task documentation','language':'en','limit':3}
    count=len(calls);before=rt.store._db.total_changes
    inspected=admin.post(BASE+'/inspect',headers=H,json={'run_id':job['run_id']})
    assert inspected.status_code==200 and inspected.headers['cache-control']=='no-store',inspected.text
    result=inspected.json();assert result['profile']==PROFILE and result['resolved_input']==seen[1]
    assert len(result['targets'])==2 and result['publication_readiness']['ready'] is False
    readiness=admin.post(BASE+'/publication-readiness',headers=H,json={'run_id':job['run_id']})
    assert readiness.status_code==200 and readiness.headers['cache-control']=='no-store'
    assert readiness.json()['ready'] is False and readiness.json()['reasons']
    history=admin.get(BASE+'/runs',headers=H)
    assert history.status_code==200 and history.headers['cache-control']=='no-store'
    assert job['run_id'] in [row['run_id'] for row in history.json()['runs']]
    assert len(calls)==count and rt.store._db.total_changes==before
    replay=admin.post(BASE+'/execute',headers=H,json=body)
    assert replay.status_code==202 and replay.json()['run_id']==job['run_id']
    assert len(calls)==count
    assert not rt.store.get_workflow(job['workflow_id'])['is_template']


@pytest.mark.parametrize('role',['operator','admin'])
def test_all_pair_routes_require_current_highest_administrator_and_have_no_public_route(routing_api,role):
    routing,public,admin=routing_api;rt,*_=routing
    with rt.store.tx() as db:create_admin_user(db,'pair-viewer','viewer-long-password','Viewer',role)
    headers=session_headers(login(admin,'pair-viewer','viewer-long-password').json()['token'])
    for method,path in [('GET','options'),('GET','runs'),('POST','prepare'),('POST','execute'),('POST','inspect'),('POST','publication-readiness')]:
        route=BASE+'/'+path
        assert admin.request(method,route,headers=headers,json={} if method=='POST' else None).status_code==403
        assert admin.request(method,route).status_code in (401,403)
        assert public.request(method,route).status_code==404


@pytest.mark.parametrize('field,value',[
    ('share_authority',False),('share_authority',1),('share_notice','outdated'),
    ('live_authority',False),('live_authority',1),('live_notice',SHARE),
    ('publication_authority',True),('target','https://external.example'),
])
def test_separate_sharing_and_live_authority_are_exact_without_extra_authority_fields(routing_api,field,value):
    routing,_,admin=routing_api;rt,_,_,calls,*_=routing;body=authorized(prepared(admin));body[field]=value
    before=len(rt.store.query('SELECT id FROM workflow_runs'))
    response=admin.post(BASE+'/execute',headers=H,json=body)
    assert response.status_code==409 and response.headers['cache-control']=='no-store'
    assert not calls and len(rt.store.query('SELECT id FROM workflow_runs'))==before


@pytest.mark.parametrize('change',['extra','same_target','unsafe_objective','forged_id'])
def test_preparation_rejects_arbitrary_inputs_and_connections(routing_api,change):
    routing,_,admin=routing_api;_,_,_,calls,*_=routing
    options=admin.get(BASE+'/options',headers=H).json();body=selection(options)
    if change=='extra':body['query']='client-selected-query'
    elif change=='same_target':body['target_b_id']=body['target_a_id']
    elif change=='unsafe_objective':body['objective']='Read https://private.example/synthetic-secret'
    else:body['source_id']='https://127.0.0.1/private'
    response=admin.post(BASE+'/prepare',headers=H,json=body)
    assert response.status_code==409 and not calls
    assert 'private.example' not in response.text and 'synthetic-secret' not in response.text and '127.0.0.1' not in response.text


def test_prepared_owner_cannot_be_replaced_by_another_authorized_admin(routing_api):
    routing,_,admin=routing_api;rt,_,_,calls,*_=routing;body=authorized(prepared(admin))
    with rt.store.tx() as db:create_admin_user(db,'pair-owner-other','other-long-password','Other','superadmin')
    headers=session_headers(login(admin,'pair-owner-other','other-long-password').json()['token'])
    response=admin.post(BASE+'/execute',headers=headers,json=body)
    assert response.status_code==409 and not calls


@pytest.mark.parametrize('mode',['invalid','unknown'])
def test_first_target_failure_or_unknown_blocks_second_target_without_retry(routing_api,mode):
    routing,_,admin=routing_api;rt,_,_,calls,modes,*_=routing
    plan=prepared(admin);modes['alternate.example']=modes['third.example']=mode
    response=admin.post(BASE+'/execute',headers=H,json=authorized(plan));assert response.status_code==202,response.text
    run=wait(rt,response.json());assert run['status']=='failed',run
    assert calls[0]=='primary.example' and len(calls)==2 and rt.typed_test_controls['news_calls']==1
    response=admin.post(BASE+'/inspect',headers=H,json={'run_id':run['run_id']})
    assert response.status_code==200 and response.json()['publication_readiness']['ready'] is False


@pytest.mark.parametrize('error',[ValueError('synthetic-secret /Users/private/db'),sqlite3.DatabaseError('synthetic-secret'),RuntimeError('synthetic-secret')])
def test_fixed_private_api_errors_never_reflect_internal_diagnostics(routing_api,monkeypatch,error):
    _,_,admin=routing_api
    def fail(*_):raise error
    monkeypatch.setattr(ControlledPairs,'options',fail)
    response=admin.get(BASE+'/options',headers=H)
    assert response.status_code in (409,500) and response.headers['cache-control']=='no-store'
    assert not any(value in response.text for value in ('synthetic-secret','/Users/','Traceback','RuntimeError'))


@pytest.mark.parametrize('raw',['{','[]','null','{"objective":NaN}'])
def test_malformed_json_cannot_start_a_pair(routing_api,raw):
    routing,_,admin=routing_api;_,_,_,calls,*_=routing
    response=admin.post(BASE+'/prepare',headers={**H,'Content-Type':'application/json'},content=raw)
    assert response.status_code==400 and not calls


def test_cross_origin_request_does_not_reach_pair_execution(routing_api,monkeypatch):
    _,_,admin=routing_api
    monkeypatch.setattr(ControlledPairs,'execute',lambda *_:pytest.fail('Cross-origin execution reached service'))
    assert admin.post(BASE+'/execute',headers={**H,'Origin':'https://external.example'},json={}).status_code==403
