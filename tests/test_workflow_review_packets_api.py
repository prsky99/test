"""Review preparation is private, read-only and never accepts external targets."""
import json
import sqlite3

import pytest

from agent_market.gateway.admin_auth import create_admin_user
from agent_market.workflow_comparison import ComparisonError
from agent_market.workflow_review_packets import ReviewPackets
from tests.test_admin_security_audit import login, session_headers
from tests.test_workflow_fallback import routing
from tests.test_workflow_fallback_api import routing_api as base_routing_api, H
from tests.test_workflow_resolved_evidence import completed, alter_checkpoint
from tests.test_workflow_typed_flow import typed_routing


PATH='/admin/api/workflow-composer/review-packet'


@pytest.fixture
def routing_api(typed_routing):
    yield from base_routing_api.__wrapped__(typed_routing)


def test_review_preparation_returns_only_unscored_worksheet_without_effects(routing_api):
    routing,public,admin=routing_api;rt,_,_,calls,*_=routing;run,body=completed(routing)
    expected=ReviewPackets(rt).prepare(body);count=len(calls);before=rt.store._db.total_changes
    inventory=admin.get('/admin/api/workflow-composer/resolved-input/runs',headers=H)
    assert inventory.status_code==200 and inventory.headers['cache-control']=='no-store'
    assert inventory.json()['review_preparation_profile']=='workflow-review-preparation-v1'
    response=admin.post(PATH,headers=H,json=body)
    assert response.status_code==200 and response.headers['cache-control']=='no-store'
    result=response.json();assert result==expected
    packet=result['packet'];review=packet['review']
    assert review['status']=='unreviewed' and not review['human_expert_reviewed'] and not review['judgments_recorded']
    assert review['holdout_status']=='not_established' and review['source_fidelity']=='not_assessable_from_metadata'
    assert len(packet['rubric']['dimensions'])==6
    assert all(row['judgment'] is None and row['reviewer'] is None and row['notes']=='' for row in packet['rubric']['dimensions'])
    assert packet['context']['actual_documentation_query']=='Python asynchronous task documentation'
    assert packet['results']['source']['label']=='Source' and packet['results']['target']['label']=='Target'
    serialized=json.dumps(result)
    for private in (run['run_id'],'primary.example','alternate.example','third.example','agent_ref','resource_id','version_id',
                    'source_host','latency_ms','eval_grade','signature','source_checkpoint_hash','https://'):
        assert private not in serialized
    assert rt.store._db.total_changes==before and len(calls)==count
    assert public.post(PATH,json=body).status_code==404


@pytest.mark.parametrize('role',['operator','admin'])
def test_review_preparation_requires_current_highest_admin(routing_api,role):
    routing,_,admin=routing_api;rt,*_=routing;_,body=completed(routing)
    with rt.store.tx() as db:create_admin_user(db,'review-viewer','viewer-long-password','Viewer',role)
    token=login(admin,'review-viewer','viewer-long-password').json()['token']
    assert admin.post(PATH,headers=session_headers(token),json=body).status_code==403
    assert admin.post(PATH,json=body).status_code in (401,403)


def test_review_preparation_rechecks_revoked_admin_role(routing_api):
    routing,_,admin=routing_api;rt,*_=routing;_,body=completed(routing)
    with rt.store.tx() as db:create_admin_user(db,'review-admin','viewer-long-password','Reviewer','superadmin')
    token=login(admin,'review-admin','viewer-long-password').json()['token'];headers=session_headers(token)
    assert admin.post(PATH,headers=headers,json=body).status_code==200
    with rt.store.tx() as db:db.execute("UPDATE admin_users SET role='admin' WHERE username='review-admin'")
    assert admin.post(PATH,headers=headers,json=body).status_code==403


@pytest.mark.parametrize('body',[
    {},{'run_id':1},{'run_id':'../private'}, {'run_id':'wr_'+'0'*32,'url':'https://external.example/upload'},
    {'run_id':'wr_'+'0'*32,'authority':True}, {'run_id':'wr_'+'0'*32,'judgment':'meets'},
    {'run_id':'wr_'+'0'*32,'reviewer':'Expert'}, {'run_id':'wr_'+'0'*32,'notes':'private-note'},
])
def test_api_accepts_only_one_exact_retained_reference_without_review_or_target_fields(routing_api,body):
    routing,_,admin=routing_api;rt,_,_,calls,*_=routing;before=rt.store._db.total_changes
    response=admin.post(PATH,headers=H,json=body)
    assert response.status_code==400 and response.headers['cache-control']=='no-store'
    assert response.json()=={'detail':'Provide one valid retained connected test reference.'}
    assert not calls and rt.store._db.total_changes==before


@pytest.mark.parametrize('raw',['{','[]','null','{"run_id":NaN}'])
def test_malformed_json_is_refused_without_reflecting_the_body(routing_api,raw):
    routing,_,admin=routing_api;_,_,_,calls,*_=routing
    response=admin.post(PATH,headers={**H,'Content-Type':'application/json'},content=raw)
    assert response.status_code==400 and 'Traceback' not in response.text and not calls


@pytest.mark.parametrize('error',[
    ComparisonError('synthetic-secret /Users/private/database.sqlite3'),
    sqlite3.DatabaseError('synthetic-secret /Users/private/database.sqlite3'),
    RuntimeError('synthetic-secret /Users/private/database.sqlite3'),
])
def test_preparation_errors_are_fixed_and_do_not_publish_diagnostics(routing_api,monkeypatch,error):
    routing,_,admin=routing_api;_,body=completed(routing)
    def fail(*_args):raise error
    monkeypatch.setattr(ReviewPackets,'prepare',fail)
    response=admin.post(PATH,headers=H,json=body)
    assert response.status_code in (409,500) and response.headers['cache-control']=='no-store'
    for private in ('synthetic-secret','/Users/','Traceback','RuntimeError','DatabaseError'):assert private not in response.text


def test_invalid_retained_proof_has_no_packet_and_does_not_run_again(routing_api):
    routing,_,admin=routing_api;rt,_,_,calls,*_=routing;run,body=completed(routing);count=len(calls)
    alter_checkpoint(rt,run['run_id'],'search-2',lambda cp:cp.update(run_id='wr_'+'0'*32))
    response=admin.post(PATH,headers=H,json=body)
    assert response.status_code==409 and response.headers['cache-control']=='no-store'
    assert 'packet' not in response.json() and len(calls)==count


def test_cross_origin_cannot_prepare_or_upload_review_context(routing_api,monkeypatch):
    routing,_,admin=routing_api;_,body=completed(routing)
    monkeypatch.setattr(ReviewPackets,'prepare',lambda *_:pytest.fail('Cross-origin request reached preparation'))
    assert admin.post(PATH,headers={**H,'Origin':'https://external.example'},json=body).status_code==403
