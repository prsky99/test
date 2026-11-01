#!/usr/bin/env python3
"""Check an explicit offline evaluation plan; never authorize or execute it.

This is an authored, content-frozen declaration of role slots and procedures.
It does not verify people, source material, access controls, chronology, hidden
holdouts or human judgments. Referenced private records are never opened.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

MAX_BYTES = 512 * 1024
MAX_SLOTS = 32
PROFILE = 'offline-evaluation-governance-v1'
RUBRIC_VERSION = 'workflow-review-rubric-v1'
RUBRIC_SHA256 = '8feda26ea73dce348bd3b101cb6147e0e59e62f4a68907fc4cac6d0364c8b8dd'
DIMENSIONS = ('task-relevance', 'source-fidelity', 'temporal-fit',
              'missing-data-honesty', 'typed-query-usefulness', 'data-sharing-safety')
IDENTIFIER = re.compile(r'[a-z][a-z0-9._-]{0,63}\Z')
FINGERPRINT = re.compile(r'[a-f0-9]{64}\Z')
ROLES = ('curator', 'custodian', 'executor', 'source_reviewer', 'reviewer', 'adjudicator')
PROCEDURES = ('identity_and_qualification', 'conflict_and_independence',
              'source_material_review', 'candidate_access_control',
              'pre_execution_reservation', 'disagreement_adjudication')
PLAN_FIELDS = frozenset(('schema_version', 'profile', 'plan_id', 'version', 'stage',
                         'manifest_binding', 'rubric_binding', 'slots', 'procedures',
                         'allocations', 'plan_fingerprint'))
SLOT_FIELDS = frozenset(('slot_id', 'role', 'identity_status', 'identity_commitment',
                         'qualification_status', 'qualification_record',
                         'conflict_status', 'conflict_record'))
ALLOCATION_FIELDS = frozenset(('family_id', 'split', 'case_ids', 'roles', 'access', 'source_materials'))
SOURCE_FIELDS = frozenset(('case_id', 'availability', 'bundle', 'review_state', 'review_record'))


class PlanError(ValueError):
    """Only fixed, input-independent reason codes leave validation."""


class SafeParser(argparse.ArgumentParser):
    def error(self, _):
        print(json.dumps({'status': 'invalid', 'error_code': 'invalid_arguments',
                          'mode': 'offline-read-only'}, indent=2), file=sys.stderr)
        self.exit(2)


def _holdout():
    # This dependency has no application initialization or import-time reads.
    from scripts import validate_workflow_holdout
    return validate_workflow_holdout


def _canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=True, allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        raise PlanError('invalid_plan_json_value') from None


def _digest(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def plan_fingerprint(plan):
    """Freeze declared content only; this hash proves no time or approval."""
    if not isinstance(plan, dict):
        raise PlanError('invalid_plan_fields')
    return _digest({key: value for key, value in plan.items() if key != 'plan_fingerprint'})


def _fields(value, expected, code):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise PlanError(code)


def _identifier(value):
    return (isinstance(value, str) and bool(IDENTIFIER.fullmatch(value))
            and not value.startswith(('wr_', 'rwp_')))


def _fingerprint(value):
    return isinstance(value, str) and bool(FINGERPRINT.fullmatch(value))


def _record(value):
    _fields(value, ('ref', 'sha256'), 'invalid_private_record_reference')
    if not _identifier(value['ref']) or not _fingerprint(value['sha256']):
        raise PlanError('invalid_private_record_reference')


def _declaration(status, record, declared='self_declared_unverified'):
    if status == 'pending':
        if record is not None:
            raise PlanError('pending_declaration_has_record')
    elif status == declared:
        _record(record)
    else:
        raise PlanError('unsupported_declaration_state')


def _rubric_inventory():
    """Bind the existing public unreviewed rubric without runtime imports."""
    try:
        document = _holdout().read_json(Path(__file__).absolute().parents[1] / 'docs' / 'workflow-evaluation-cases.json')
        rows = document['human_review']['rubric']
        if (document['dataset_id'] != 'workflow-typed-flow-cases-v1'
                or type(document['schema_version']) is not int or document['schema_version'] != 1
                or document['review_status'] != 'pending-human-review'
                or document['human_expert_reviewed'] is not False
                or document['provider_quality_certified'] is not False
                or document['human_review']['status'] != 'pending-human-review'
                or not isinstance(rows, list) or len(rows) != 6
                or tuple(row['id'] for row in rows) != DIMENSIONS
                or _digest(rows) != RUBRIC_SHA256):
            raise ValueError()
    except (ValueError, KeyError, TypeError, AttributeError, RecursionError):
        raise PlanError('rubric_inventory_unavailable') from None


def validate_plan(plan, manifest):
    """Return aggregate pending actions for a strict declaration, never approval."""
    _fields(plan, PLAN_FIELDS, 'invalid_plan_fields')
    if len(_canonical(plan).encode('utf-8')) > MAX_BYTES:
        raise PlanError('plan_too_large')
    if type(plan['schema_version']) is not int or plan['schema_version'] != 1 or plan['profile'] != PROFILE:
        raise PlanError('unsupported_plan_schema')
    if (not _identifier(plan['plan_id']) or type(plan['version']) is not int
            or not 1 <= plan['version'] <= 1000000 or plan['stage'] != 'pre_execution'):
        raise PlanError('invalid_plan_identity_or_stage')
    try:
        manifest_result = _holdout().validate_manifest(manifest)
    except _holdout().ManifestError:
        raise PlanError('invalid_bound_manifest') from None
    binding = plan['manifest_binding']
    _fields(binding, ('dataset_id', 'version', 'manifest_fingerprint'), 'invalid_manifest_binding')
    if (type(binding['version']) is not int or binding != {
            'dataset_id': manifest['dataset_id'], 'version': manifest['version'],
            'manifest_fingerprint': manifest_result['manifest_fingerprint']}):
        raise PlanError('manifest_binding_mismatch')
    _fields(plan['rubric_binding'], ('version', 'sha256'), 'invalid_rubric_binding')
    if plan['rubric_binding'] != {'version': RUBRIC_VERSION, 'sha256': RUBRIC_SHA256}:
        raise PlanError('rubric_binding_mismatch')
    _rubric_inventory()
    procedures = plan['procedures']
    _fields(procedures, PROCEDURES, 'invalid_procedures')
    pending_procedures = 0
    for procedure in procedures.values():
        _fields(procedure, ('state', 'record'), 'invalid_procedure_declaration')
        _declaration(procedure['state'], procedure['record'], 'declared_unverified')
        pending_procedures += procedure['state'] == 'pending'
    slots = plan['slots']
    if not isinstance(slots, list) or not 7 <= len(slots) <= MAX_SLOTS:
        raise PlanError('invalid_role_slot_count')
    indexed = {}
    commitments = set()
    pending_identity = pending_qualification = pending_conflict = 0
    for slot in slots:
        _fields(slot, SLOT_FIELDS, 'invalid_role_slot_fields')
        if not _identifier(slot['slot_id']) or slot['role'] not in ROLES:
            raise PlanError('invalid_role_slot')
        if slot['slot_id'] in indexed:
            raise PlanError('duplicate_role_slot')
        indexed[slot['slot_id']] = slot
        if slot['identity_status'] == 'pending':
            if slot['identity_commitment'] is not None:
                raise PlanError('pending_identity_has_commitment')
        elif slot['identity_status'] == 'self_declared_unverified':
            commitment = slot['identity_commitment']
            if not _fingerprint(commitment):
                raise PlanError('invalid_identity_commitment')
            if commitment in commitments:
                raise PlanError('declared_identity_collision')
            commitments.add(commitment)
        else:
            raise PlanError('unsupported_identity_state')
        _declaration(slot['qualification_status'], slot['qualification_record'])
        _declaration(slot['conflict_status'], slot['conflict_record'])
        pending_identity += slot['identity_status'] == 'pending'
        pending_qualification += slot['qualification_status'] == 'pending'
        pending_conflict += slot['conflict_status'] == 'pending'
    families = {}
    for case in manifest['cases']:
        family = families.setdefault(case['family_id'], {'split': case['split'], 'cases': set()})
        family['cases'].add(case['case_id'])
    allocations = plan['allocations']
    if not isinstance(allocations, list) or len(allocations) != len(families):
        raise PlanError('family_allocation_coverage_mismatch')
    covered_families = set()
    used_slots = set()
    missing_bundles = metadata_only = pending_source_reviews = declared_source_reviews = 0
    for allocation in allocations:
        _fields(allocation, ALLOCATION_FIELDS, 'invalid_family_allocation_fields')
        family_id = allocation['family_id']
        if not _identifier(family_id) or family_id not in families or family_id in covered_families:
            raise PlanError('invalid_or_duplicate_family_allocation')
        covered_families.add(family_id)
        family = families[family_id]
        cases = allocation['case_ids']
        if (allocation['split'] != family['split'] or not isinstance(cases, list)
                or not cases or any(not _identifier(case) for case in cases)
                or len(cases) != len(set(cases)) or set(cases) != family['cases']):
            raise PlanError('case_allocation_coverage_mismatch')
        roles = allocation['roles']
        _fields(roles, ROLES, 'invalid_assigned_roles')
        reviewers = roles['reviewer']
        if (not isinstance(reviewers, list) or not 2 <= len(reviewers) <= 4
                or any(not _identifier(ref) for ref in reviewers)):
            raise PlanError('invalid_independent_reviewer_slots')
        assignments = [(role, ref) for role, ref in roles.items() if role != 'reviewer']
        assignments += [('reviewer', ref) for ref in reviewers]
        refs = [ref for _, ref in assignments]
        if (any(not _identifier(ref) or ref not in indexed or indexed[ref]['role'] != role
                for role, ref in assignments) or len(set(refs)) != len(refs)):
            raise PlanError('role_separation_violation')
        used_slots.update(refs)
        access = allocation['access']
        _fields(access, ('before_execution', 'during_review'), 'invalid_access_declaration')
        for phase, values in access.items():
            if (not isinstance(values, list) or not values or any(not _identifier(ref) for ref in values)
                    or len(values) != len(set(values)) or not set(values) <= set(refs)):
                raise PlanError('invalid_access_slot_set')
        minimum_before = {roles['curator'], roles['custodian']}
        if not minimum_before <= set(access['before_execution']):
            raise PlanError('missing_curation_access_declaration')
        if family['split'] == 'candidate_holdout' and set(access['before_execution']) != minimum_before:
            raise PlanError('candidate_pre_execution_access_violation')
        minimum_review = {roles['source_reviewer'], roles['adjudicator'], *reviewers}
        if not minimum_review <= set(access['during_review']):
            raise PlanError('missing_review_access_declaration')
        materials = allocation['source_materials']
        if not isinstance(materials, list) or len(materials) != len(cases):
            raise PlanError('source_material_coverage_mismatch')
        material_cases = set()
        for material in materials:
            _fields(material, SOURCE_FIELDS, 'invalid_source_material_fields')
            case_id = material['case_id']
            if not _identifier(case_id) or case_id not in family['cases'] or case_id in material_cases:
                raise PlanError('source_material_coverage_mismatch')
            material_cases.add(case_id)
            availability = material['availability']
            if availability not in ('pending', 'metadata_only', 'separate_source_bundle'):
                raise PlanError('unsupported_source_material_state')
            if availability == 'separate_source_bundle':
                _record(material['bundle'])
                _declaration(material['review_state'], material['review_record'], 'declared_reviewed_unverified')
            elif material['bundle'] is not None or material['review_record'] is not None or material['review_state'] != 'pending':
                raise PlanError('source_bundle_required_for_review_declaration')
            missing_bundles += availability != 'separate_source_bundle'
            metadata_only += availability == 'metadata_only'
            pending_source_reviews += material['review_state'] == 'pending'
            declared_source_reviews += material['review_state'] == 'declared_reviewed_unverified'
    if used_slots != set(indexed):
        raise PlanError('unallocated_role_slots')
    expected = plan_fingerprint(plan)
    if not _fingerprint(plan['plan_fingerprint']) or plan['plan_fingerprint'] != expected:
        raise PlanError('plan_fingerprint_mismatch')
    return {'status': 'needs_human_actions', 'mode': 'offline-read-only',
            'assessment_scope': 'authored_declarations_only',
            'counts': {'cases': len(manifest['cases']), 'families': len(families),
                       'candidate_holdout_cases': manifest_result['counts']['candidate_holdout'],
                       'role_slots': len(indexed), 'identity_slots_pending': pending_identity,
                       'qualification_slots_pending': pending_qualification,
                       'conflict_slots_pending': pending_conflict, 'procedures_pending': pending_procedures,
                       'source_cases_missing_bundle': missing_bundles, 'source_cases_metadata_only': metadata_only,
                       'source_cases_pending_review': pending_source_reviews,
                       'source_reviews_declared_unverified': declared_source_reviews},
            'plan_fingerprint': expected, 'manifest_fingerprint': manifest_result['manifest_fingerprint'],
            'rubric_binding': {'version': RUBRIC_VERSION, 'sha256': RUBRIC_SHA256},
            'identity_verification': 'not_established', 'reviewer_qualification_verification': 'not_established',
            'reviewer_independence_verification': 'not_established', 'access_enforcement': 'not_established',
            'pre_run_allocation': 'not_established', 'chronological_reservation': 'not_established',
            'unseen_holdout_status': 'not_established', 'representativeness': 'not_assessed',
            'human_expert_reviewed': False, 'source_evidence_verified': False,
            'provider_quality_certified': False, 'execution_authorized': False, 'scores_recorded': False,
            'human_judgments': 0, 'provider_calls': 0, 'model_calls': 0, 'database_opens': 0, 'artifact_writes': 0}


def main(argv=None):
    parser = SafeParser(description=__doc__, allow_abbrev=False)
    for option in ('manifest', 'plan'):
        parser.add_argument('--' + option, action='append', required=True, metavar='EXISTING_JSON',
                            help='One explicit existing UTF-8 JSON file, at most 512 KiB; symlinks are refused.')
    args = parser.parse_args(argv)
    if len(args.manifest) != 1 or len(args.plan) != 1:
        parser.error('Provide exactly one manifest and plan.')
    try:
        if __package__ in (None, ''):
            sys.path.insert(0, str(Path(__file__).absolute().parents[1]))
        try:
            manifest = _holdout().read_json(args.manifest[0])
            plan = _holdout().read_json(args.plan[0])
        except _holdout().ManifestError:
            raise PlanError('input_unavailable_or_invalid_json') from None
        result = validate_plan(plan, manifest)
    except PlanError as exc:
        print(json.dumps({'status': 'invalid', 'error_code': str(exc), 'mode': 'offline-read-only',
                          'provider_calls': 0, 'model_calls': 0, 'database_opens': 0,
                          'artifact_writes': 0}, indent=2))
        return 1
    except Exception:
        print(json.dumps({'status': 'invalid', 'error_code': 'validation_unavailable',
                          'mode': 'offline-read-only', 'provider_calls': 0, 'model_calls': 0,
                          'database_opens': 0, 'artifact_writes': 0}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
