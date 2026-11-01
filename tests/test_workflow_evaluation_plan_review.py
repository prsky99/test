"""Independent adversarial checks: authored governance is never real approval."""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
from unittest.mock import Mock

import pytest

from scripts.validate_workflow_evaluation_plan import PlanError, plan_fingerprint, validate_plan

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def governance():
    return (json.loads((ROOT/'tests/fixtures/workflow_evaluation_plan.json').read_text()),
            json.loads((ROOT/'tests/fixtures/workflow_holdout_manifest.json').read_text()))


def freeze(plan):
    plan['plan_fingerprint']=plan_fingerprint(plan)


def declared_record(ref):
    return {'ref':ref,'sha256':hashlib.sha256(ref.encode()).hexdigest()}


def declare_everything(plan):
    for index,slot in enumerate(plan['slots']):
        slot.update(identity_status='self_declared_unverified',identity_commitment=hashlib.sha256(str(index).encode()).hexdigest(),
            qualification_status='self_declared_unverified',qualification_record=declared_record('qualification-'+str(index)),
            conflict_status='self_declared_unverified',conflict_record=declared_record('conflict-'+str(index)))
    for key,procedure in plan['procedures'].items():
        procedure.update(state='declared_unverified',record=declared_record(key.replace('_','-')))
    for allocation in plan['allocations']:
        for material in allocation['source_materials']:
            material.update(availability='separate_source_bundle',bundle=declared_record('bundle-'+material['case_id']),
                review_state='declared_reviewed_unverified',review_record=declared_record('review-'+material['case_id']))
    freeze(plan)


def test_all_declared_records_still_prove_no_people_access_allocation_sources_or_scores(governance):
    plan,manifest=governance;declare_everything(plan);before=copy.deepcopy(plan)
    result=validate_plan(plan,manifest)
    assert result['status']=='needs_human_actions'
    for key in ('identity_verification','reviewer_qualification_verification','reviewer_independence_verification',
                'access_enforcement','pre_run_allocation','chronological_reservation','unseen_holdout_status'):
        assert result[key]=='not_established'
    for key in ('human_expert_reviewed','source_evidence_verified','provider_quality_certified','execution_authorized','scores_recorded'):
        assert result[key] is False
    assert result['human_judgments']==result['provider_calls']==result['model_calls']==result['database_opens']==result['artifact_writes']==0
    assert result['counts']['identity_slots_pending']==result['counts']['qualification_slots_pending']==result['counts']['procedures_pending']==0
    assert result['counts']['source_cases_missing_bundle']==0 and result['counts']['source_reviews_declared_unverified']==len(manifest['cases'])
    assert result['representativeness']=='not_assessed' and plan==before
    text=json.dumps(result)
    assert not any(slot['slot_id'] in text or slot['identity_commitment'] in text for slot in plan['slots'])
    assert not any(case['task'] in text for case in manifest['cases'])


@pytest.mark.parametrize('collision',['same_reviewer_ref','same_reviewer_identity','cross_role_identity','cross_role_ref'])
def test_aliases_or_repeated_commitments_cannot_bypass_role_independence(governance,collision):
    plan,manifest=governance;declare_everything(plan)
    by_role={slot['role']:slot for slot in plan['slots'] if slot['role']!='reviewer'}
    reviewers=[slot for slot in plan['slots'] if slot['role']=='reviewer']
    if collision=='same_reviewer_ref':plan['allocations'][0]['roles']['reviewer']=[reviewers[0]['slot_id']]*2
    elif collision=='same_reviewer_identity':reviewers[1]['identity_commitment']=reviewers[0]['identity_commitment']
    elif collision=='cross_role_identity':by_role['adjudicator']['identity_commitment']=reviewers[0]['identity_commitment']
    else:plan['allocations'][0]['roles']['adjudicator']=reviewers[0]['slot_id']
    freeze(plan)
    with pytest.raises(PlanError):validate_plan(plan,manifest)


@pytest.mark.parametrize('change',['unknown_case','missing_case','duplicate_case','unknown_family','duplicate_family','missing_family','wrong_split','cross_family_case','source_case_outside','source_duplicate'])
def test_family_case_split_and_source_coverage_are_exact(governance,change):
    plan,manifest=governance;first=plan['allocations'][0];second=plan['allocations'][1]
    if change=='unknown_case':first['case_ids']=['unallocated-case']
    elif change=='missing_case':first['case_ids']=[]
    elif change=='duplicate_case':first['case_ids']*=2
    elif change=='unknown_family':first['family_id']='unknown-family'
    elif change=='duplicate_family':second.update(copy.deepcopy(first))
    elif change=='missing_family':plan['allocations'].pop()
    elif change=='wrong_split':first['split']='candidate_holdout'
    elif change=='cross_family_case':first['case_ids']=copy.deepcopy(second['case_ids'])
    elif change=='source_case_outside':first['source_materials'][0]['case_id']=second['case_ids'][0]
    else:first['source_materials']*=2
    freeze(plan)
    with pytest.raises(PlanError):validate_plan(plan,manifest)


@pytest.mark.parametrize('change',['manifest_digest','manifest_dataset','manifest_version','rubric_hash','rubric_version'])
def test_plan_cannot_be_reused_with_another_inventory_or_rubric(governance,change):
    plan,manifest=governance
    if change=='manifest_digest':plan['manifest_binding']['manifest_fingerprint']='0'*64
    elif change=='manifest_dataset':plan['manifest_binding']['dataset_id']='other-inventory'
    elif change=='manifest_version':plan['manifest_binding']['version']+=1
    elif change=='rubric_hash':plan['rubric_binding']['sha256']='0'*64
    else:plan['rubric_binding']['version']='invented-rubric-v2'
    freeze(plan)
    with pytest.raises(PlanError):validate_plan(plan,manifest)


@pytest.mark.parametrize('change',['top_score','certification','run_reference','reservation_date','slot_verified','source_grade','post_execution'])
def test_results_historical_runs_dates_and_certification_cannot_be_smuggled_into_a_plan(governance,change):
    plan,manifest=governance
    if change=='top_score':plan['scores']={'factual_accuracy':1.0}
    elif change=='certification':plan['human_expert_reviewed']=True
    elif change=='run_reference':plan['run_id']='wr_'+'0'*32
    elif change=='reservation_date':plan['reserved_before_execution_at']='2026-01-01T00:00:00Z'
    elif change=='slot_verified':plan['slots'][0]['qualification_status']='verified'
    elif change=='source_grade':plan['allocations'][0]['source_materials'][0]['factual_accuracy']=1.0
    else:plan['stage']='post_execution'
    freeze(plan)
    with pytest.raises(PlanError):validate_plan(plan,manifest)


@pytest.mark.parametrize('availability',['pending','metadata_only'])
def test_metadata_or_absent_source_cannot_be_declared_reviewed_material(governance,availability):
    plan,manifest=governance;source=plan['allocations'][0]['source_materials'][0]
    source.update(availability=availability,review_state='declared_reviewed_unverified',review_record=declared_record('reviewed-context'))
    freeze(plan)
    with pytest.raises(PlanError,match='source_bundle_required_for_review_declaration'):validate_plan(plan,manifest)


@pytest.mark.parametrize('role',['executor','source_reviewer','reviewer','adjudicator'])
def test_candidate_pre_execution_access_is_not_granted_to_measured_or_review_roles(governance,role):
    plan,manifest=governance;candidate=next(row for row in plan['allocations'] if row['split']=='candidate_holdout')
    reference=candidate['roles'][role]
    if isinstance(reference,list):reference=reference[0]
    candidate['access']['before_execution'].append(reference);freeze(plan)
    with pytest.raises(PlanError,match='candidate_pre_execution_access_violation'):validate_plan(plan,manifest)


@pytest.mark.parametrize('ref',['https://private.example/reviewer','person@example.org','/Users/private/qualification.json'])
def test_private_reference_records_are_opaque_and_never_paths_or_contacts(governance,ref):
    plan,manifest=governance;slot=plan['slots'][0]
    slot.update(qualification_status='self_declared_unverified',qualification_record={'ref':ref,'sha256':'0'*64});freeze(plan)
    with pytest.raises(PlanError,match='invalid_private_record_reference'):validate_plan(plan,manifest)


def test_validation_does_not_fetch_references_or_initialize_runtime(governance,monkeypatch):
    from agent_market.gateway.store import Store
    from agent_market.workflows import WorkflowRuntime
    from agent_market.execution_authority import Authority
    plan,manifest=governance;declare_everything(plan)
    reject=Mock(side_effect=AssertionError('Offline authored plan cannot initialize runtime or retrieve evidence'))
    monkeypatch.setattr(Store,'__init__',reject);monkeypatch.setattr(WorkflowRuntime,'__init__',reject)
    monkeypatch.setattr(Authority,'__init__',reject);monkeypatch.setattr(sqlite3,'connect',reject)
    monkeypatch.setattr('socket.getaddrinfo',reject);monkeypatch.setattr('httpx.Client.__init__',reject)
    assert validate_plan(plan,manifest)['source_evidence_verified'] is False and not reject.called
