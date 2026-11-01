"""Pure private generation tokens: no Store, clock, transport or configuration."""
from dataclasses import FrozenInstanceError, replace
import json
import math

import pytest

from agent_market.observation_guards import (
    FIELDS, MAX_ROW_FIELDS, MAX_SNAPSHOT_BYTES, MAX_VALUE_BYTES, OWNERS,
    GuardError, ObservationToken, fingerprint, issue, validate,
)

ISSUER = 'a' * 32


def row():
    value = dict.fromkeys(FIELDS)
    value.update(id=7, key='synthetic:guard:seven', kind='mcp',
        url='https://synthetic.example/mcp?token=synthetic-secret', host='synthetic.example',
        active=1, source='synthetic-registry', name='Synthetic reader', description='Reference lookup',
        category='news', networks=',,', details='{}', content_hash='c' * 64,
        first_seen=0.0, usage_tools='[{"name":"lookup"}]', usage_tools_hash='d' * 64,
        usage_full_tools='[{"name":"lookup","inputSchema":{"type":"object"}}]',
        usage_full_hash='e' * 64, usage_guide='{"endpoint":"https://synthetic.example/mcp"}')
    return value


def token(value=None, **changes):
    arguments = dict(owner='survey', generation=3, sequence=5, started_at=100.0, issuer=ISSUER)
    arguments.update(changes)
    return issue(row() if value is None else value, **arguments)


def check(value=None, snapshot=None, **changes):
    arguments = dict(generation=3, sequence=5, applied_sequence=4,
        previous_observed_at=99.0, observed_at=101.0, issuer=ISSUER)
    arguments.update(changes)
    return validate(token() if value is None else value, row() if snapshot is None else snapshot, **arguments)


def refused(call, expected):
    with pytest.raises(GuardError) as caught:
        call()
    assert caught.value.code == expected
    assert str(caught.value) == expected


def test_private_immutable_token_contains_no_raw_resource_text_or_credentials():
    snapshot = row()
    value = token(snapshot)
    snapshot['url'] = 'changed after capture'
    assert check(value) is True
    assert repr(value) == '<ObservationToken private>'
    serialized = json.dumps(vars(value))
    for text in ('synthetic-secret', 'synthetic.example', 'synthetic:guard:seven', 'Synthetic reader'):
        assert text not in serialized
    with pytest.raises(FrozenInstanceError):
        value.generation = 99


@pytest.mark.parametrize('owner', OWNERS)
def test_all_supported_owner_domains_use_one_explicit_generation_contract(owner):
    assert check(token(owner=owner)) is True


@pytest.mark.parametrize('field', FIELDS)
def test_every_bound_field_change_refuses_even_if_generation_was_not_advanced(field):
    original = row()
    changed = dict(original)
    if field == 'id':
        changed[field] = 41
    elif field == 'active':
        changed[field] = 0
    elif type(changed[field]) is str:
        changed[field] += ' changed'
    elif changed[field] is None:
        changed[field] = 'new explicit value'
    else:
        changed[field] += 1
    refused(lambda: check(token(original), changed), 'stale_generation')


def test_endpoint_aba_requires_the_persistent_generation_not_only_matching_digest():
    original = row()
    after = dict(original, url='https://other-synthetic.example/mcp')
    assert fingerprint(after) != fingerprint(original)
    after['url'] = original['url']
    assert fingerprint(after) == fingerprint(original)
    refused(lambda: check(token(original), after, generation=5), 'stale_generation')


def test_last_seen_and_owner_result_columns_are_not_an_implicit_new_binding():
    original = row()
    observed = original | dict(last_seen=999, health_status='healthy', last_check_at=999,
        cap_checked_at=999, eval_at=999, eval_grade='A', trial_ok=1,
        auth_checked_at=999, auth_error=None)
    assert fingerprint(observed) == fingerprint(original)
    assert check(token(original), observed) is True


def test_exact_bytes_and_scalar_types_are_not_silently_normalized():
    original = row()
    reordered = original | {'details': '{ "b": 2, "a": 1 }'}
    canonical = original | {'details': '{"a":1,"b":2}'}
    assert fingerprint(reordered) != fingerprint(canonical)
    assert len({fingerprint(original | {'category': value}) for value in (None, '', 0, 0.0)}) == 4


def test_consumed_token_cannot_replay_even_at_a_later_wall_timestamp():
    refused(lambda: check(applied_sequence=5, observed_at=200), 'stale_sequence')
    refused(lambda: check(applied_sequence=6, observed_at=200), 'stale_sequence')


@pytest.mark.parametrize('sequence', [4, 6])
def test_only_the_latest_reserved_owner_sequence_can_apply(sequence):
    refused(lambda: check(sequence=sequence), 'stale_sequence')


def test_new_store_issuer_refuses_an_old_in_memory_token():
    refused(lambda: check(issuer='b' * 32), 'invalid_token')


def test_equal_wall_timestamps_are_allowed_only_with_an_unconsumed_sequence():
    assert check(observed_at=100, previous_observed_at=100) is True
    assert check(observed_at=100, previous_observed_at=None) is True
    refused(lambda: check(observed_at=100, previous_observed_at=100, applied_sequence=5), 'stale_sequence')


@pytest.mark.parametrize('changes', [
    {'observed_at': 99}, {'previous_observed_at': 102},
])
def test_wall_clock_rollback_is_refused_without_rewriting_facts(changes):
    refused(lambda: check(**changes), 'stale_observation')


@pytest.mark.parametrize('value', [None, True, -1, math.inf, -math.inf, math.nan, '101', 2**53])
def test_observation_wall_timestamp_is_finite_numeric_nonnegative_and_bounded(value):
    refused(lambda: check(observed_at=value), 'invalid_token')


@pytest.mark.parametrize('value', [True, -1, math.inf, math.nan, '99', 2**53])
def test_previous_owner_wall_timestamp_must_be_null_or_valid(value):
    refused(lambda: check(previous_observed_at=value), 'invalid_token')


@pytest.mark.parametrize('field,value', [
    ('generation', True), ('generation', 0), ('generation', 2**63),
    ('sequence', 0), ('sequence', '5'), ('applied_sequence', -1),
    ('applied_sequence', True), ('applied_sequence', 2**63),
    ('issuer', None), ('issuer', 'a' * 31), ('issuer', 'A' * 32),
])
def test_current_guard_state_is_not_coerced_from_invalid_types(field, value):
    refused(lambda: check(**{field: value}), 'invalid_token')


@pytest.mark.parametrize('field,value', [
    ('owner', 'unknown'), ('owner', None), ('generation', True), ('generation', 0),
    ('sequence', 0), ('sequence', 2**63), ('started_at', True), ('started_at', -1),
    ('started_at', math.nan), ('issuer', 'not-an-issuer'),
])
def test_invalid_token_reservation_is_refused(field, value):
    refused(lambda: token(**{field: value}), 'invalid_token')


def test_mutated_token_fields_are_revalidated_at_application():
    value = token()
    object.__setattr__(value, 'generation', True)
    refused(lambda: check(value), 'invalid_token')
    refused(lambda: check({'generation': 3}), 'invalid_token')


@pytest.mark.parametrize('value', [None, [], object(), {'id': 7, 'active': 1}])
def test_missing_or_nonmapping_snapshots_fail_with_fixed_errors(value):
    refused(lambda: fingerprint(value), 'invalid_snapshot')
    # validate uses the same shape check and does not leak an AttributeError.
    if value is not None:
        refused(lambda: check(snapshot=value), 'invalid_snapshot')


@pytest.mark.parametrize('field,value', [
    ('id', 0), ('id', True), ('id', 2**63), ('active', True), ('active', 2),
    ('details', {}), ('name', '\ud800'), ('name', 'bad\0text'),
    ('price_usdc', math.inf), ('price_usdc', 2**63),
])
def test_snapshot_values_have_bounded_scalar_types_without_implicit_conversion(field, value):
    refused(lambda: fingerprint(row() | {field: value}), 'invalid_snapshot')


def test_snapshot_field_and_byte_limits_are_real_and_fail_before_unbounded_work():
    too_many = row() | {f'extra_{number}': None for number in range(MAX_ROW_FIELDS)}
    refused(lambda: fingerprint(too_many), 'invalid_snapshot')
    value = dict.fromkeys(FIELDS)
    value.update(id=7, active=1, description='a' * MAX_VALUE_BYTES)
    assert len(fingerprint(value)) == 64
    refused(lambda: fingerprint(value | {'description': 'a' * (MAX_VALUE_BYTES + 1)}), 'invalid_snapshot')
    refused(lambda: fingerprint(value | {'description': '\u20ac' * (MAX_VALUE_BYTES // 3 + 1)}), 'invalid_snapshot')
    value.update(source='b' * (MAX_VALUE_BYTES - 2))
    assert MAX_SNAPSHOT_BYTES == 2 * MAX_VALUE_BYTES
    assert len(fingerprint(value)) == 64
    refused(lambda: fingerprint(value | {'category': 'x'}), 'invalid_snapshot')


def test_public_token_constructor_does_not_turn_digest_or_issuer_into_a_raw_snapshot():
    value = token()
    refused(lambda: replace(value, fingerprint='x' * 64), 'invalid_token')
    assert isinstance(value, ObservationToken)
    assert not hasattr(value, 'url') and not hasattr(value, 'details')
