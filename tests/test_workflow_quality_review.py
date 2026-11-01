"""Actual staff-account review records on explicit synthetic private executions."""
import copy
import sqlite3
import time

import pytest

from agent_market.workflow_quality_review import (WorkflowQualityReview,NOTICE,BIND_NOTICE,INSPECT_NOTICE,
    REVIEW_NOTICE,ADJUDICATE_NOTICE,DIMENSIONS,ReviewerQualification,ReviewedSource)
from agent_market.workspace_access import WorkspaceConflict,WorkspaceDenied,WorkspaceInvalid
from tests.test_workspace_execution import execution_world,call


@pytest.fixture
def quality():
    private=execution_world();store,access,actors,execution,proxy,ws,wd,wv=private
    for uid in (2,4,5):access.set_member(ws,{'user_id':uid,'role':'editor','active':True,'revision':0},actors[1])
    core=WorkflowQualityReview(access,execution)
    yield {'private':private,'store':store,'access':access,'actors':actors,'core':core,'ws':ws,'wd':wd,'wv':wv}
    store._db.close()


def reserve(q):
    return q['core'].reserve(q['ws'],{'draft_id':q['wd'],'snapshot_id':q['wv'],'dataset_hash':'a'*64,
        'case_hash':'b'*64,'source_hash':'c'*64,'source_ref':'synthetic_source_bundle','executor_user_id':1,
        'reviewer_ids':[2,4],'adjudicator_user_id':5,'authorized':True,'notice':NOTICE},q['actors'][1])


def bound(q):
    assignment=reserve(q);job=call(q['private'])
    assert job['status']=='succeeded'
    q['core'].bind(q['ws'],assignment['id'],{'run_id':job['id'],'authorized':True,'notice':BIND_NOTICE},q['actors'][1])
    return assignment,job


def judgment(number=2):
    return {'scores':{key:number for key in DIMENSIONS},'source_observed_at':time.time(),
        'source_reviewed':True,'no_conflict_declared':True,'notes':'Synthetic staff assessment',
        'authorized':True,'notice':REVIEW_NOTICE}


def score(q,assignment,uid,number=2):
    q['core'].inspect(q['ws'],assignment['id'],{'authorized':True,'notice':INSPECT_NOTICE},q['actors'][uid])
    return q['core'].review(q['ws'],assignment['id'],judgment(number),q['actors'][uid])


def test_pre_run_assignment_actual_proof_two_staff_reviews_and_disagreement_reconciliation(quality):
    q=quality;assignment,job=bound(q)
    assert assignment['created']<=job['created']
    score(q,assignment,2,2);score(q,assignment,4,1)
    report=q['core'].status(q['ws'],assignment['id'],q['actors'][1])
    assert report['status']=='needs_adjudication' and report['review_count']==2
    assert not report['qualified_operating_evidence'] and not report['human_expert_reviewed']
    q['core'].inspect(q['ws'],assignment['id'],{'authorized':True,'notice':INSPECT_NOTICE},q['actors'][5])
    result=q['core'].adjudicate(q['ws'],assignment['id'],{'scores':{key:1 for key in DIMENSIONS},
        'reason':'Synthetic disagreement reviewed separately','authorized':True,'notice':ADJUDICATE_NOTICE},q['actors'][5])
    assert result['recorded']
    final=q['core'].status(q['ws'],assignment['id'],q['actors'][1])
    assert final['adjudicated'] and not final['qualified_operating_evidence']
    assert final['holdout_status']=='not_established' and final['automatic_winner'] is None


def test_historical_run_cannot_be_relabelled_as_preallocated(quality):
    q=quality;job=call(q['private']);assignment=reserve(q)
    with pytest.raises(WorkspaceConflict):q['core'].bind(q['ws'],assignment['id'],
        {'run_id':job['id'],'authorized':True,'notice':BIND_NOTICE},q['actors'][1])
    assert q['store']._db.execute('SELECT run_id FROM workspace_quality_assignments').fetchone()[0] is None


def test_executor_or_unassigned_account_cannot_open_or_score_own_run(quality):
    q=quality;assignment,_=bound(q)
    for uid in (1,3):
        with pytest.raises(WorkspaceDenied):q['core'].inspect(q['ws'],assignment['id'],{'authorized':True,'notice':INSPECT_NOTICE},q['actors'][uid])
        with pytest.raises(WorkspaceDenied):q['core'].review(q['ws'],assignment['id'],judgment(),q['actors'][uid])
    with pytest.raises(WorkspaceDenied):q['core'].review(q['ws'],assignment['id'],judgment(),q['actors'][2])


@pytest.mark.parametrize('bad',[True,3,-1,'2',float('nan')])
def test_scores_are_explicit_bounded_or_unassessed_never_coerced(quality,bad):
    q=quality;assignment,_=bound(q);body=judgment();body['scores'][DIMENSIONS[0]]=bad
    q['core'].inspect(q['ws'],assignment['id'],{'authorized':True,'notice':INSPECT_NOTICE},q['actors'][2])
    with pytest.raises(WorkspaceInvalid):q['core'].review(q['ws'],assignment['id'],body,q['actors'][2])


def test_missing_dimension_remains_unscored_and_cannot_adjudicate(quality):
    q=quality;assignment,_=bound(q)
    q['core'].inspect(q['ws'],assignment['id'],{'authorized':True,'notice':INSPECT_NOTICE},q['actors'][2])
    body=judgment();body['scores'][DIMENSIONS[0]]=None
    q['core'].review(q['ws'],assignment['id'],body,q['actors'][2]);score(q,assignment,4)
    assert not q['core'].status(q['ws'],assignment['id'],q['actors'][1])['scores_complete']
    q['core'].inspect(q['ws'],assignment['id'],{'authorized':True,'notice':INSPECT_NOTICE},q['actors'][5])
    with pytest.raises(WorkspaceConflict):q['core'].adjudicate(q['ws'],assignment['id'],
        {'scores':{key:1 for key in DIMENSIONS},'reason':'Cannot grade missing evidence','authorized':True,'notice':ADJUDICATE_NOTICE},q['actors'][5])


def test_review_actual_accepted_sql_fault_rolls_back_judgment_and_audit(quality,monkeypatch):
    q=quality;assignment,_=bound(q);original=q['access']._audit
    q['core'].inspect(q['ws'],assignment['id'],{'authorized':True,'notice':INSPECT_NOTICE},q['actors'][2])
    def fail(db,actor,ws,action,*args):
        original(db,actor,ws,action,*args)
        if action=='quality.review':
            assert db.execute('SELECT COUNT(*) FROM workspace_quality_judgments').fetchone()[0]==1
            raise sqlite3.OperationalError('Synthetic accepted judgment write failure')
    with monkeypatch.context() as patch:
        patch.setattr(q['access'],'_audit',fail)
        with pytest.raises(WorkspaceConflict):q['core'].review(q['ws'],assignment['id'],judgment(),q['actors'][2])
    assert q['store']._db.execute('SELECT COUNT(*) FROM workspace_quality_judgments').fetchone()[0]==0


def test_scored_account_records_never_imply_real_qualifications_or_source_review(quality):
    q=quality;assignment,_=bound(q);score(q,assignment,2);score(q,assignment,4)
    now=time.time()
    qualifiers=lambda ws,uid,assignment:ReviewerQualification(uid,'d'*64,'e'*64,'f'*64,now+60,'isolated',assignment,format(uid,'064x'))
    sources=lambda ws,h,ref:ReviewedSource(ws,h,'f'*64,now+60,'isolated')
    isolated=WorkflowQualityReview(q['access'],q['private'][3],qualification_source=qualifiers,source_verifier=sources)
    assert not isolated.status(q['ws'],assignment['id'],q['actors'][1])['qualified_operating_evidence']


def test_unknown_private_run_cannot_be_accepted_as_quality_proof(quality):
    q=quality;assignment=reserve(q);q['private'][4].result={'ok':False,'error_code':'UPSTREAM_TIMEOUT'}
    job=call(q['private'])
    assert job['status']=='unknown'
    with pytest.raises(WorkspaceConflict):q['core'].bind(q['ws'],assignment['id'],
        {'run_id':job['id'],'authorized':True,'notice':BIND_NOTICE},q['actors'][1])


@pytest.mark.parametrize('change',['membership_aba','workspace_revision','provider_binding_aba','controls_aba'])
def test_preallocated_authority_and_provider_generation_cannot_be_revived_by_restoration(quality,change):
    q=quality;assignment,job=bound(q);db=q['store']._db
    with db:
        if change=='membership_aba':db.execute('UPDATE workspace_memberships SET revision=revision+2 WHERE workspace_id=? AND user_id=2',(q['ws'],))
        elif change=='workspace_revision':db.execute('UPDATE organization_workspaces SET revision=revision+2 WHERE id=?',(q['ws'],))
        elif change=='provider_binding_aba':db.execute('UPDATE resource_observation_generations SET generation=generation+2')
        else:db.execute('UPDATE execution_controls SET revision=revision+2')
    state=q['core'].status(q['ws'],assignment['id'],q['actors'][1])
    assert state['status']=='retained_assignment_not_current' and not state['qualified_operating_evidence']
    assert state['reviews']==[]
    with pytest.raises(WorkspaceDenied):q['core'].inspect(q['ws'],assignment['id'],{'authorized':True,'notice':INSPECT_NOTICE},q['actors'][2])
    assert len(q['core'].assignments(q['ws'],q['actors'][1]))==1


def test_archived_snapshot_history_is_metadata_only_and_scores_not_current(quality):
    q=quality;assignment,_=bound(q);score(q,assignment,2);score(q,assignment,4)
    q['access'].revoke_version(q['ws'],q['wd'],q['wv'],{'revision':1},q['actors'][1])
    state=q['core'].status(q['ws'],assignment['id'],q['actors'][1])
    assert state['status']=='retained_assignment_not_current' and state['reviews']==[]
    assert 'output' not in q['core'].assignments(q['ws'],q['actors'][1])[0]


def test_audited_operating_qualification_is_case_bound_and_requires_distinct_real_identity_commitments(quality):
    q=quality;assignment,_=bound(q);score(q,assignment,2);score(q,assignment,4);now=time.time()
    qualifier=lambda ws,uid,case:ReviewerQualification(uid,'d'*64,'e'*64,'f'*64,now+60,'operating',case,format(uid,'064x'))
    verifier=lambda ws,h,ref:ReviewedSource(ws,h,'f'*64,now+60,'operating')
    core=WorkflowQualityReview(q['access'],q['private'][3],qualification_source=qualifier,source_verifier=verifier)
    assert core.status(q['ws'],assignment['id'],q['actors'][1])['qualified_operating_evidence']
    core.qualification_source=lambda ws,uid,case:ReviewerQualification(uid,'d'*64,'e'*64,'f'*64,now+60,'operating',case,'0'*64)
    assert not core.status(q['ws'],assignment['id'],q['actors'][1])['qualified_operating_evidence']


def test_provider_change_during_qualification_lookup_cannot_publish_a_stale_verified_status(quality):
    q=quality;assignment,_=bound(q);score(q,assignment,2);score(q,assignment,4);now=time.time()
    def qualifier(ws,uid,case):
        if uid==2:
            with q['store']._db as db:db.execute('UPDATE resource_observation_generations SET generation=generation+1')
        return ReviewerQualification(uid,'d'*64,'e'*64,'f'*64,now+60,'operating',case,format(uid,'064x'))
    verifier=lambda ws,h,ref:ReviewedSource(ws,h,'f'*64,now+60,'operating')
    core=WorkflowQualityReview(q['access'],q['private'][3],qualification_source=qualifier,source_verifier=verifier)
    report=core.status(q['ws'],assignment['id'],q['actors'][1])
    assert report['status']=='retained_assignment_not_current' and not report['qualified_operating_evidence']
