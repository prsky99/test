"""Actual scoped HTTP assessment workflow with explicit synthetic staff/data."""
import time

import pytest

from agent_market.workspace_service import BASE
from agent_market.workflow_quality_review import (NOTICE,BIND_NOTICE,INSPECT_NOTICE,REVIEW_NOTICE,DIMENSIONS)
from tests.test_workspace_execution_api import private_api,execute


@pytest.fixture
def quality_api(private_api):
    w=private_api
    for person in ('viewer','outsider'):
        row=w.client.post(f'{BASE}/{w.ws["id"]}/members',headers=w.headers['owner'],
            json={'user_id':w.users[person],'role':'editor','active':True,'revision':1 if person=='viewer' else 0})
        assert row.status_code==200,row.text
    w.quality=f'{BASE}/{w.ws["id"]}/quality'
    return w


def reserve_body(w):
    return {'draft_id':w.draft['id'],'snapshot_id':w.snapshot['id'],'dataset_hash':'a'*64,'case_hash':'b'*64,
        'source_hash':'c'*64,'source_ref':'synthetic_source_bundle','executor_user_id':w.users['owner'],
        'reviewer_ids':[w.users['editor'],w.users['viewer']],'adjudicator_user_id':w.users['outsider'],
        'authorized':True,'notice':NOTICE}


def test_http_real_reservation_precedes_certain_run_and_two_actual_account_judgments(quality_api):
    w=quality_api
    response=w.client.post(w.quality+'/assignments',headers=w.headers['owner'],json=reserve_body(w))
    assert response.status_code==200,response.text
    assignment=response.json()['result'];assert not w.calls
    job,_=execute(w)
    assert assignment['created']<=job['created'] and w.calls.count('tools/call')==1
    base=w.quality+'/assignments/'+assignment['id']
    response=w.client.post(base+'/bind',headers=w.headers['owner'],json={'run_id':job['id'],'authorized':True,'notice':BIND_NOTICE})
    assert response.status_code==200,response.text
    assert w.client.post(base+'/inspect',headers=w.headers['owner'],json={'authorized':True,'notice':INSPECT_NOTICE}).status_code==404
    for person in ('editor','viewer'):
        opened=w.client.post(base+'/inspect',headers=w.headers[person],json={'authorized':True,'notice':INSPECT_NOTICE})
        assert opened.status_code==200 and 'Private research result' in str(opened.json()['result']['output'])
        scored=w.client.post(base+'/review',headers=w.headers[person],json={'scores':{key:2 for key in DIMENSIONS},
            'source_observed_at':time.time(),'source_reviewed':True,'no_conflict_declared':True,
            'notes':'Synthetic fixture staff assessment','authorized':True,'notice':REVIEW_NOTICE})
        assert scored.status_code==200,scored.text
    report=w.client.get(base,headers=w.headers['owner'])
    assert report.status_code==200 and report.json()['result']['scores_complete']
    assert report.json()['result']['review_count']==2 and not report.json()['result']['qualified_operating_evidence']
    assert report.headers['cache-control']=='no-store'
    assert w.calls.count('tools/call')==1


def test_http_historical_run_and_forged_expert_status_do_not_become_preallocation(quality_api):
    w=quality_api;job,_=execute(w)
    response=w.client.post(w.quality+'/assignments',headers=w.headers['owner'],json=reserve_body(w));assert response.status_code==200,response.text
    assignment=response.json()['result']
    response=w.client.post(w.quality+'/assignments/'+assignment['id']+'/bind',headers=w.headers['owner'],
        json={'run_id':job['id'],'authorized':True,'notice':BIND_NOTICE})
    assert response.status_code==409
    forged=reserve_body(w)|{'human_expert_reviewed':True}
    assert w.client.post(w.quality+'/assignments',headers=w.headers['owner'],json=forged).status_code==400
    assert w.calls.count('tools/call')==1


@pytest.mark.parametrize('person',['operator'])
def test_readonly_members_cannot_reserve_or_bypass_assigned_score_roles(quality_api,person):
    w=quality_api
    response=w.client.post(w.quality+'/assignments',headers=w.headers[person],json=reserve_body(w))
    assert response.status_code==404 and not w.calls
