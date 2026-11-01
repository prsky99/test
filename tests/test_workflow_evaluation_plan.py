"""Synthetic offline governance declarations, never actual human assignments."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts import validate_workflow_evaluation_plan as plan_validator
from scripts import validate_workflow_holdout as holdout_validator

FIXTURES = Path(__file__).parent / 'fixtures'


@pytest.fixture
def documents():
    return (json.loads((FIXTURES / 'workflow_evaluation_plan.json').read_text()),
            json.loads((FIXTURES / 'workflow_holdout_manifest.json').read_text()))


def freeze(plan):
    plan['plan_fingerprint'] = plan_validator.plan_fingerprint(plan)
    return plan


def record(ref):
    return {'ref': ref, 'sha256': hashlib.sha256(ref.encode()).hexdigest()}


def complete_declarations(plan):
    """Only make synthetic claims; tool must still establish no actual review."""
    for index, slot in enumerate(plan['slots']):
        slot['identity_status'] = 'self_declared_unverified'
        slot['identity_commitment'] = hashlib.sha256(f'synthetic-identity-{index}'.encode()).hexdigest()
        for kind in ('qualification', 'conflict'):
            slot[kind + '_status'] = 'self_declared_unverified'
            slot[kind + '_record'] = record(f'synthetic-{kind}-{index}')
    for name, procedure in plan['procedures'].items():
        procedure.update(state='declared_unverified', record=record('synthetic-' + name.replace('_', '-')))
    for allocation in plan['allocations']:
        for material in allocation['source_materials']:
            material.update(availability='separate_source_bundle', bundle=record('source-' + material['case_id']),
                            review_state='declared_reviewed_unverified',
                            review_record=record('review-' + material['case_id']))
    return freeze(plan)


def assert_unestablished(result):
    assert result['status'] == 'needs_human_actions'
    assert result['assessment_scope'] == 'authored_declarations_only'
    for field in ('identity_verification', 'reviewer_qualification_verification',
                  'reviewer_independence_verification', 'access_enforcement', 'pre_run_allocation',
                  'chronological_reservation', 'unseen_holdout_status'):
        assert result[field] == 'not_established'
    for field in ('human_expert_reviewed', 'source_evidence_verified', 'provider_quality_certified',
                  'execution_authorized', 'scores_recorded'):
        assert result[field] is False
    for field in ('human_judgments', 'provider_calls', 'model_calls', 'database_opens', 'artifact_writes'):
        assert result[field] == 0


def test_pending_synthetic_plan_has_explicit_missing_human_actions(documents):
    plan, manifest = documents
    before = copy.deepcopy(documents)
    result = plan_validator.validate_plan(plan, manifest)
    assert_unestablished(result)
    assert result['counts'] == {'cases': 4, 'families': 4, 'candidate_holdout_cases': 2,
                               'role_slots': 7, 'identity_slots_pending': 7,
                               'qualification_slots_pending': 7, 'conflict_slots_pending': 7,
                               'procedures_pending': 6, 'source_cases_missing_bundle': 4,
                               'source_cases_metadata_only': 0, 'source_cases_pending_review': 4,
                               'source_reviews_declared_unverified': 0}
    assert (plan, manifest) == before
    output = json.dumps(result)
    assert all(slot['slot_id'] not in output for slot in plan['slots'])
    assert all(case['task'] not in output and case['case_id'] not in output for case in manifest['cases'])
    assert plan['plan_id'] not in output and manifest['dataset_id'] not in output


def test_complete_self_declarations_are_still_not_ready_or_expert_reviewed(documents):
    plan, manifest = documents
    complete_declarations(plan)
    result = plan_validator.validate_plan(plan, manifest)
    assert_unestablished(result)
    assert result['counts']['identity_slots_pending'] == 0
    assert result['counts']['procedures_pending'] == 0
    assert result['counts']['source_cases_missing_bundle'] == 0
    assert result['counts']['source_reviews_declared_unverified'] == 4
    assert 'ready' not in result and 'approved' not in result
    assert all(slot['identity_commitment'] not in json.dumps(result) for slot in plan['slots'])


@pytest.mark.parametrize('field', ['scores', 'results', 'run_id', 'reviewer_name', 'expert_reviewed',
                                    'created_at', 'reservation_timestamp', 'source_urls', 'private_key'])
def test_unknown_or_result_bearing_top_fields_are_refused(documents, field):
    plan, manifest = documents
    plan[field] = 'synthetic-private-value'
    freeze(plan)
    with pytest.raises(plan_validator.PlanError, match='^invalid_plan_fields$'):
        plan_validator.validate_plan(plan, manifest)


@pytest.mark.parametrize('field,value,code', [
    ('schema_version', True, 'unsupported_plan_schema'),
    ('schema_version', 2, 'unsupported_plan_schema'),
    ('profile', 'public-evaluation', 'unsupported_plan_schema'),
    ('stage', 'post_execution', 'invalid_plan_identity_or_stage'),
    ('version', True, 'invalid_plan_identity_or_stage'),
    ('version', 0, 'invalid_plan_identity_or_stage'),
    ('plan_id', 'wr_' + 'a' * 32, 'invalid_plan_identity_or_stage'),
])
def test_plan_schema_and_pre_execution_stage_are_exact(documents, field, value, code):
    plan, manifest = documents
    plan[field] = value
    freeze(plan)
    with pytest.raises(plan_validator.PlanError, match='^' + code + '$'):
        plan_validator.validate_plan(plan, manifest)


@pytest.mark.parametrize('binding,field,value,code', [
    ('manifest_binding', 'dataset_id', 'another-dataset', 'manifest_binding_mismatch'),
    ('manifest_binding', 'version', True, 'manifest_binding_mismatch'),
    ('manifest_binding', 'manifest_fingerprint', '0' * 64, 'manifest_binding_mismatch'),
    ('rubric_binding', 'version', 'unversioned-rubric', 'rubric_binding_mismatch'),
    ('rubric_binding', 'sha256', '0' * 64, 'rubric_binding_mismatch'),
])
def test_exact_manifest_and_rubric_bindings_are_required(documents, binding, field, value, code):
    plan, manifest = documents
    plan[binding][field] = value
    freeze(plan)
    with pytest.raises(plan_validator.PlanError, match='^' + code + '$'):
        plan_validator.validate_plan(plan, manifest)


def test_bound_manifest_must_itself_pass_safe_task_and_split_guards(documents):
    plan, manifest = documents
    manifest['cases'][2]['inputs']['docs.search.v1']['query'] = 'api_key=synthetic-secret'
    manifest['cases'][2]['input_fingerprint'] = holdout_validator.input_fingerprint(manifest['cases'][2])
    manifest['manifest_fingerprint'] = holdout_validator.manifest_fingerprint(manifest)
    plan['manifest_binding']['manifest_fingerprint'] = manifest['manifest_fingerprint']
    freeze(plan)
    with pytest.raises(plan_validator.PlanError, match='^invalid_bound_manifest$'):
        plan_validator.validate_plan(plan, manifest)


def test_existing_manifest_underscore_identifiers_remain_allocatable(documents):
    plan, manifest = documents
    case = next(row for row in manifest['cases'] if row['split'] == 'candidate_holdout')
    original_family = case['family_id']
    case.update(case_id='case_alpha', family_id='family_alpha')
    manifest['manifest_fingerprint'] = holdout_validator.manifest_fingerprint(manifest)
    assert holdout_validator.validate_manifest(manifest)['status'] == 'structurally_valid_candidate_manifest'
    plan['manifest_binding']['manifest_fingerprint'] = manifest['manifest_fingerprint']
    allocation = next(row for row in plan['allocations'] if row['family_id'] == original_family)
    allocation.update(family_id='family_alpha', case_ids=['case_alpha'])
    allocation['source_materials'][0]['case_id'] = 'case_alpha'
    result = plan_validator.validate_plan(freeze(plan), manifest)
    assert_unestablished(result)
    assert result['counts']['candidate_holdout_cases'] == 2
    assert result['manifest_fingerprint'] == manifest['manifest_fingerprint']
    assert result['plan_fingerprint'] == plan['plan_fingerprint']


def test_role_slot_cannot_self_assign_as_a_reviewer(documents):
    plan, manifest = documents
    plan['allocations'][0]['roles']['reviewer'][0] = plan['allocations'][0]['roles']['executor']
    freeze(plan)
    with pytest.raises(plan_validator.PlanError, match='^role_separation_violation$'):
        plan_validator.validate_plan(plan, manifest)


@pytest.mark.parametrize('role', ['curator', 'executor', 'source_reviewer', 'adjudicator'])
def test_same_declared_identity_cannot_hide_in_different_roles(documents, role):
    plan, manifest = documents
    complete_declarations(plan)
    owner = next(slot for slot in plan['slots'] if slot['role'] == role)
    reviewer = next(slot for slot in plan['slots'] if slot['role'] == 'reviewer')
    reviewer['identity_commitment'] = owner['identity_commitment']
    freeze(plan)
    with pytest.raises(plan_validator.PlanError, match='^declared_identity_collision$'):
        plan_validator.validate_plan(plan, manifest)


@pytest.mark.parametrize('state', ['verified', 'qualified_expert', 'independent', True])
def test_qualification_claims_cannot_be_upgraded_by_the_plan(documents, state):
    plan, manifest = documents
    plan['slots'][0]['qualification_status'] = state
    freeze(plan)
    with pytest.raises(plan_validator.PlanError, match='^unsupported_declaration_state$'):
        plan_validator.validate_plan(plan, manifest)


@pytest.mark.parametrize('ref', ['https://private.invalid/report', '/private/source.json',
                                  '../qualification', 'alice@example.invalid',
                                  'wr_' + 'a' * 32, 'rwp_' + 'b' * 32])
def test_private_record_references_cannot_be_paths_urls_or_history_ids(documents, ref):
    plan, manifest = documents
    plan['slots'][0]['qualification_status'] = 'self_declared_unverified'
    plan['slots'][0]['qualification_record'] = {'ref': ref, 'sha256': 'a' * 64}
    freeze(plan)
    with pytest.raises(plan_validator.PlanError, match='^invalid_private_record_reference$'):
        plan_validator.validate_plan(plan, manifest)


def test_declared_record_files_are_not_opened_or_fetched(documents, monkeypatch):
    plan, manifest = documents
    complete_declarations(plan)
    inventory = holdout_validator.read_json
    reads = []

    def known_inventory_only(path):
        reads.append(Path(path))
        assert Path(path) == Path(__file__).parents[1] / 'docs' / 'workflow-evaluation-cases.json'
        return inventory(path)

    monkeypatch.setattr(holdout_validator, 'read_json', known_inventory_only)
    result = plan_validator.validate_plan(plan, manifest)
    assert_unestablished(result)
    assert len(reads) == 2  # Existing manifest fixture protection and pinned rubric only.


def test_candidate_access_cannot_include_executor_before_execution(documents):
    plan, manifest = documents
    allocation = next(row for row in plan['allocations'] if row['split'] == 'candidate_holdout')
    allocation['access']['before_execution'].append(allocation['roles']['executor'])
    freeze(plan)
    with pytest.raises(plan_validator.PlanError, match='^candidate_pre_execution_access_violation$'):
        plan_validator.validate_plan(plan, manifest)


def test_missing_source_reviewer_access_is_explicit_error(documents):
    plan, manifest = documents
    allocation = plan['allocations'][0]
    allocation['access']['during_review'].remove(allocation['roles']['source_reviewer'])
    freeze(plan)
    with pytest.raises(plan_validator.PlanError, match='^missing_review_access_declaration$'):
        plan_validator.validate_plan(plan, manifest)


def test_metadata_only_material_is_missing_fidelity_evidence(documents):
    plan, manifest = documents
    plan['allocations'][0]['source_materials'][0]['availability'] = 'metadata_only'
    result = plan_validator.validate_plan(freeze(plan), manifest)
    assert_unestablished(result)
    assert result['counts']['source_cases_metadata_only'] == 1
    assert result['counts']['source_cases_missing_bundle'] == 4


@pytest.mark.parametrize('availability', ['pending', 'metadata_only'])
def test_source_review_requires_separate_bundle_even_as_declaration(documents, availability):
    plan, manifest = documents
    source = plan['allocations'][0]['source_materials'][0]
    source.update(availability=availability, review_state='declared_reviewed_unverified',
                  review_record=record('synthetic-review-record'))
    freeze(plan)
    with pytest.raises(plan_validator.PlanError, match='^source_bundle_required_for_review_declaration$'):
        plan_validator.validate_plan(plan, manifest)


def test_family_and_case_coverage_cannot_silently_drop_candidate(documents):
    plan, manifest = documents
    plan['allocations'].pop()
    freeze(plan)
    with pytest.raises(plan_validator.PlanError, match='^family_allocation_coverage_mismatch$'):
        plan_validator.validate_plan(plan, manifest)


def test_procedure_record_is_not_an_assessment_or_chronology_proof(documents):
    plan, manifest = documents
    plan['procedures']['pre_execution_reservation'].update(state='declared_unverified',
                                                          record=record('synthetic-reservation-procedure'))
    result = plan_validator.validate_plan(freeze(plan), manifest)
    assert_unestablished(result)
    assert result['counts']['procedures_pending'] == 5


def test_fingerprint_freezes_all_declared_content_and_never_self_repairs(documents):
    plan, manifest = documents
    plan['version'] += 1
    with pytest.raises(plan_validator.PlanError, match='^plan_fingerprint_mismatch$'):
        plan_validator.validate_plan(plan, manifest)
    assert plan['plan_fingerprint'] != plan_validator.plan_fingerprint(plan)


def test_fingerprint_is_canonical_for_object_order_only(documents):
    plan, manifest = documents

    def reverse_objects(value):
        if isinstance(value, dict):
            return {key: reverse_objects(value[key]) for key in reversed(value)}
        if isinstance(value, list):
            return [reverse_objects(item) for item in value]
        return value

    reordered = reverse_objects(plan)
    assert plan_validator.plan_fingerprint(reordered) == plan['plan_fingerprint']
    assert plan_validator.validate_plan(reordered, manifest)['status'] == 'needs_human_actions'
    reordered['plan_fingerprint'] = '0' * 64
    assert plan_validator.plan_fingerprint(reordered) == plan['plan_fingerprint']
    with pytest.raises(plan_validator.PlanError, match='^plan_fingerprint_mismatch$'):
        plan_validator.validate_plan(reordered, manifest)


@pytest.mark.parametrize('section', ['role_identity', 'qualification', 'procedure', 'source_material',
                                     'access', 'reviewer_order'])
def test_fingerprint_detects_each_otherwise_valid_declaration_change(documents, section):
    plan, manifest = documents
    if section == 'role_identity':
        plan['slots'][0].update(identity_status='self_declared_unverified', identity_commitment='a' * 64)
    elif section == 'qualification':
        plan['slots'][0].update(qualification_status='self_declared_unverified',
                                qualification_record=record('synthetic-private-qualification'))
    elif section == 'procedure':
        plan['procedures']['source_material_review'].update(state='declared_unverified',
                                                           record=record('synthetic-source-procedure'))
    elif section == 'source_material':
        plan['allocations'][0]['source_materials'][0]['availability'] = 'metadata_only'
    elif section == 'access':
        allocation = plan['allocations'][0]
        allocation['access']['before_execution'].append(allocation['roles']['executor'])
    elif section == 'reviewer_order':
        plan['allocations'][0]['roles']['reviewer'].reverse()
    assert plan_validator.plan_fingerprint(plan) != plan['plan_fingerprint']
    with pytest.raises(plan_validator.PlanError, match='^plan_fingerprint_mismatch$'):
        plan_validator.validate_plan(plan, manifest)


@pytest.mark.parametrize('number', [float('nan'), float('inf'), -float('inf')])
def test_nonfinite_plan_data_is_rejected_without_widening(documents, number):
    plan, manifest = documents
    plan['version'] = number
    with pytest.raises(plan_validator.PlanError, match='^invalid_plan_json_value$'):
        plan_validator.validate_plan(plan, manifest)


def test_in_memory_oversize_cannot_bypass_bounded_reader(documents):
    plan, manifest = documents
    plan['plan_id'] = 'x' * (plan_validator.MAX_BYTES + 1)
    with pytest.raises(plan_validator.PlanError, match='^plan_too_large$'):
        plan_validator.validate_plan(plan, manifest)


def test_rubric_drift_does_not_silently_change_review_contract(documents, monkeypatch):
    actual = holdout_validator.read_json(Path(__file__).parents[1] / 'docs' / 'workflow-evaluation-cases.json')
    actual['human_review']['rubric'][0]['question'] = 'A different unversioned question'
    monkeypatch.setattr(holdout_validator, 'read_json', lambda _: actual)
    with pytest.raises(plan_validator.PlanError, match='^rubric_inventory_unavailable$'):
        plan_validator._rubric_inventory()


def test_public_fixture_inventory_drift_cannot_make_plan_look_like_holdout(documents, monkeypatch):
    plan, manifest = documents
    original_read = holdout_validator.read_json

    def drifted_inventory(path):
        document = original_read(path)
        document['cases'][0]['source_title'] = 'An unversioned changed public fixture'
        return document

    monkeypatch.setattr(holdout_validator, 'read_json', drifted_inventory)
    with pytest.raises(plan_validator.PlanError, match='^invalid_bound_manifest$'):
        plan_validator.validate_plan(plan, manifest)


def test_rubric_constants_match_existing_worksheet_contract_without_importing_runtime():
    source = (Path(__file__).parents[1] / 'agent_market' / 'workflow_review_packets.py').read_text()
    assert "RUBRIC_VERSION = '" + plan_validator.RUBRIC_VERSION + "'" in source
    assert "RUBRIC_SHA256 = '" + plan_validator.RUBRIC_SHA256 + "'" in source
    plan_validator._rubric_inventory()
