"""Actual local evaluation pairs and conservative offline replay boundaries."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from agent_market.workspace_access import _hash
from scripts import rehearse_reliability_experiment as experiment


@pytest.fixture(scope='module')
def owned_evidence():
    return experiment.produce_owned_fixture()


def test_concrete_existing_worker_arms_are_paired_once_with_unknown_and_partial_retained(owned_evidence):
    report = experiment.analyze_evidence(owned_evidence)
    assert report['evaluation_packets'] == 16 and report['business_packets'] == 0
    assert report['planned_pairs'] == report['paired_observed_count'] == 8
    assert report['paired_fully_assessable_count'] == 6
    assert report['paired_categories'] == {'both_goal_pass': 3, 'both_failed': 0,
        'goal_regression': 3, 'goal_improvement': 0, 'unknown': 1, 'unassessable': 1,
        'oracle_error': 0, 'missing': 0}
    assert report['arm_outcomes']['baseline']['goal_pass'] == 8
    assert report['arm_outcomes']['perturbed']['agent_failure'] == 3
    assert report['arm_outcomes']['perturbed']['unknown'] == 1
    assert report['arm_outcomes']['perturbed']['unassessable'] == 1
    assert report['all_k_goal_success']['baseline']['numerator'] == 4
    assert report['all_k_goal_success']['perturbed']['numerator'] == 0
    assert all(arm['second_tick_attempts'] == 0 for arm in report['source_binding'].values())
    assert report['within_arm_original_variant_mr']['perturbed']['categories']['both_failed'] == 1
    assert not report['within_arm_original_variant_mr']['perturbed']['both_failed_is_goal_success']
    assert sum(cell['planned_denominator'] for cell in report['surface_cells']) == 16


def test_replay_sensitivity_is_not_an_operating_threshold_or_real_intervention(owned_evidence):
    report = experiment.analyze_evidence(owned_evidence)
    baseline = {row['fixture_threshold']: row for row in report['replay_policies'] if row['arm'] == 'baseline'}
    # The fixture deliberately exposes the unsafe early-prefix threshold.
    assert baseline[2]['replay_false_stop'] == {'numerator': 8, 'denominator': 8, 'value': 1.0}
    assert baseline[3]['replay_false_stop'] == {'numerator': 0, 'denominator': 8, 'value': 0.0}
    assert baseline[2]['scope'] == 'same_trajectory_prefix_counterfactual_replay'
    assert baseline[2]['replay_successful_goal_loss_if_suffix_discarded']['numerator'] == 8
    assert baseline[2]['saved_business_calls'] is None and not baseline[2]['remote_cancellation_confirmed']
    assert report['actual_interventions'] == 0
    assert report['actual_paired_intervention_false_stop'] is None
    assert report['actual_paired_intervention_goal_loss'] is None
    assert report['actual_paired_intervention_judge_overhead_seconds'] is None
    assert report['analyzer_elapsed_seconds'] >= 0
    assert report['elapsed_scope'] == 'local_artifact_analysis_only_not_live_judge_or_intervention_overhead'
    assert report['synthetic'] and not report['promotion_qualified'] and not report['controller_enabled']
    assert not report['operating_qualification'] and not report['public_activation']
    assert report['independent_quality'] == 'unassessed'
    assert report['uncertainty']['confidence_interval'] is None


def test_real_observed_job_and_trace_bindings_cover_seed_inputs_schema_oracle_and_closure(owned_evidence):
    report = experiment.analyze_evidence(owned_evidence)
    assert report['manifest_hash'] == _hash(report['manifest'])
    content = dict(report); content.pop('report_binding_hash')
    assert report['report_binding_hash'] == _hash(content)
    manifest = report['manifest']
    assert manifest['seed'] == 19 and len(manifest['episode_input_hashes']) == 8
    assert manifest['oracle_version'] == 'exact-approved-item-goal-v1'
    assert len(manifest['source_hashes']) == 4
    assert manifest['surface_axes']['lambda'] == 'categorical_fixture_fault_not_calibrated_severity'
    for arm, rows in report['observed_episode_metadata'].items():
        for row in rows:
            assert row['input_hash'] == manifest['episode_input_hashes'][row['case_id']]
            assert [event['sequence'] for event in row['events']] == list(range(1, len(row['events'])+1))
            assert row['events'][0]['event_type'] == 'packet_dispatched'
            assert row['events'][-1]['event_type'] == 'terminal_observation'
            closed = any(event['event_type'] == 'closed_action' for event in row['events'])
            assert closed == (row['state'] in ('completed', 'failed'))
            assert len(row['source_revision']) == 64
    assert 'chain_of_thought' not in json.dumps(report) and 'private_prompt' not in json.dumps(report)


@pytest.mark.parametrize('value', [{}, {'success': True}, b'{}', None])
def test_external_json_or_claimed_success_is_not_an_experiment_source(value):
    with pytest.raises(ValueError):
        experiment.analyze_evidence(value)


def test_tampered_or_cross_owner_immutable_envelope_is_rejected(owned_evidence):
    for changed in (replace(owned_evidence, owner=object()),
                    replace(owned_evidence, payload=owned_evidence.payload+b' '),
                    replace(owned_evidence, signature='0'*64)):
        with pytest.raises(ValueError):
            experiment.analyze_evidence(changed)
    with pytest.raises(TypeError):
        experiment.produce_owned_fixture(path='an-operating-database')


def test_missing_episode_keeps_original_admitted_pair_and_all_k_denominators(owned_evidence):
    value = experiment._opened(owned_evidence)
    value['arms']['baseline']['episodes'] = value['arms']['baseline']['episodes'][1:]
    report = experiment.analyze_evidence(experiment._seal(value))
    assert report['planned_pairs'] == 8 and report['paired_observed_count'] == 7
    assert report['paired_categories']['missing'] == 1
    assert report['missing_episodes']['baseline'] == 1
    assert report['all_k_goal_success']['baseline']['denominator'] == 4
    assert report['all_k_goal_success']['baseline']['numerator'] == 3
    assert report['within_arm_original_variant_mr']['baseline']['categories']['missing'] == 1
    assert all(row['planned_denominator'] == 8 for row in report['replay_policies'])


def test_no_observed_success_leaves_replay_success_denominator_empty(owned_evidence):
    value = experiment._opened(owned_evidence)
    value['arms']['baseline']['episodes'] = []
    report = experiment.analyze_evidence(experiment._seal(value))
    assert report['paired_categories']['missing'] == 8
    baseline = [row for row in report['replay_policies'] if row['arm'] == 'baseline']
    assert all(row['replay_false_stop'] == {'numerator': 0, 'denominator': 0, 'value': None} for row in baseline)
    assert all(row['missing_trace_count'] == 8 for row in baseline)
    assert report['all_k_goal_success']['baseline']['denominator'] == 4


def test_missing_trace_is_separate_from_the_existing_verified_goal_observation(owned_evidence):
    value = experiment._opened(owned_evidence)
    row = value['arms']['baseline']['episodes'][0]
    row['events'] = row['source']['events'] = []
    row['source_revision'] = _hash(row['source'])
    report = experiment.analyze_evidence(experiment._seal(value))
    assert report['arm_outcomes']['baseline']['goal_pass'] == 8
    assert report['missing_episodes']['baseline'] == 0
    assert report['paired_observed_count'] == 8
    for policy in report['replay_policies']:
        if policy['arm'] == 'baseline':
            assert policy['missing_trace_count'] == 1
            assert policy['replay_false_stop']['denominator'] == 7
            assert policy['planned_denominator'] == 8


@pytest.mark.parametrize('mutation', ['input', 'seed', 'fault', 'event', 'goal', 'pin'])
def test_even_internal_producer_mistakes_cannot_change_pair_or_manifest_contract(owned_evidence, mutation):
    value = deepcopy(experiment._opened(owned_evidence))
    arm = value['arms']['perturbed']; row = arm['episodes'][0]
    if mutation == 'input':
        row['input_hash'] = row['source']['input_hash'] = '0'*64
    elif mutation == 'seed':
        arm['research_binding']['seed'] += 1
    elif mutation == 'fault':
        row['fault'] = 'undeclared_fault'
    elif mutation == 'event':
        row['events'][0]['sequence'] = True
    elif mutation == 'goal':
        row['outcome'] = 'agent_failure'
    else:
        arm['pin_hash'] = '0'*64
        for episode in arm['episodes']:
            episode['source']['pin_hash'] = '0'*64
            episode['source_revision'] = _hash(episode['source'])
    row['source_revision'] = _hash(row['source'])
    with pytest.raises(ValueError):
        experiment.analyze_evidence(experiment._seal(value))
