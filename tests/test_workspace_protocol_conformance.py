"""Synthetic transport checks never send payments or create a second ledger."""
import base64
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import time

import pytest

from agent_market.workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid
from agent_market.workspace_protocol_conformance import (
    ProtocolConformance, NOTICE, WIRE_PROFILES, decode_header,
    validate_fixture_headers, validate_fixture_mandate, wire_suite)
from tests.test_workspace_sandbox_payments import sandbox, prepare, dispatch
from tests.test_workspace_agreements import agreement
from tests.test_provider_claims import provider


@pytest.fixture
def conformance(sandbox):
    w = sandbox
    w.conformance = ProtocolConformance(w.access, w.payments)
    return w


def command(w, capture, refund=None, profile=0, reference='conformance_fixture'):
    return {'profile_id': WIRE_PROFILES[profile]['id'], 'capture_intent_id': capture['id'],
        'refund_intent_id': refund['id'] if refund else None, 'event_reference': reference,
        'authorized': True, 'notice': NOTICE}


def test_exact_wire_and_partial_refund_reconcile_existing_signed_sources_without_new_events(conformance):
    w = conformance
    capture = prepare(w); result = dispatch(w, capture)['result']
    refund = prepare(w, 'refund', result['id'], 33, result['revision'], 'sim_conformance_refund')
    dispatch(w, refund)
    before = w.store._db.execute('SELECT COUNT(*) FROM workspace_agreement_events').fetchone()[0]
    reported = w.conformance.run(w.ws, command(w, capture, refund), w.staff[1])
    assert reported['wire_checks']['passed'] and not reported['wire_checks']['network_signature_verified']
    assert not reported['wire_checks']['ap2_credential_verified']
    assert reported['ledger']['balanced'] and reported['ledger']['refunded_units'] == 33
    assert reported['ledger']['remaining_units'] == 68
    assert reported['ledger']['provider_allocation'] == w.agreements.summary(w.ws, w.staff[1])['settlements'][0]['remaining']['provider_units']
    assert reported['states']['settlement'] == 'test_unit_recorded'
    assert reported['states']['refund'] == 'test_unit_recorded'
    assert reported['states']['claim'] == reported['states']['finality'] == 'not_exercised'
    assert reported['states']['payout'] == 'disabled'
    assert reported['historical_observation_only'] and not reported['actual_money']
    assert reported['source_refs']['capture_receipt_sha256'] and reported['source_refs']['refund_receipt_sha256']
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_agreement_events').fetchone()[0] == before
    assert len(w.provider_calls) == 1
    assert '"signature"' not in json.dumps(reported) and 'session_ref' not in json.dumps(reported)


def test_batch_commitment_fixture_is_distinct_from_claim_settle_and_real_finality(conformance):
    w = conformance; capture = prepare(w); dispatch(w, capture)
    result = w.conformance.run(w.ws, command(w, capture, profile=1), w.staff[1])
    assert result['states']['commitment'] == 'synthetic_fixture_only'
    assert result['states']['settlement'] == 'test_unit_recorded'
    assert result['states']['finality'] == 'not_exercised'
    assert not result['wire_checks']['real_escrow_deployed']
    assert not result['wire_checks']['network_binding_implemented']


def test_prepared_without_receipt_is_held_unknown_and_report_does_not_dispatch(conformance):
    w = conformance; capture = prepare(w)
    result = w.conformance.run(w.ws, command(w, capture), w.staff[1])
    assert result['ledger']['receipt_state'] == 'unknown_hold'
    assert result['states']['settlement'] == 'not_observed'
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_agreement_events').fetchone()[0] == 0
    dispatch(w, capture)
    old = w.conformance.report(w.ws, result['id'], w.staff[1])
    assert old['ledger']['receipt_state'] == 'unknown_hold'
    replay = w.conformance.run(w.ws, command(w, capture), w.staff[1])
    assert replay['replayed'] and replay['ledger']['receipt_state'] == 'unknown_hold'
    fresh = w.conformance.run(w.ws, command(w, capture, reference='conformance_fresh'), w.staff[1])
    assert fresh['ledger']['receipt_state'] == 'simulated_recorded'


def test_concurrent_report_event_deduplicates_and_amount_change_conflicts(conformance):
    w = conformance; first = prepare(w); dispatch(w, first)
    body = command(w, first)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: w.conformance.run(w.ws, body, w.staff[1]), range(4)))
    assert sum(not item['replayed'] for item in results) == 1
    assert len({item['id'] for item in results}) == 1
    other = prepare(w, amount=102, reference='sim_other_capture'); dispatch(w, other)
    with pytest.raises(WorkspaceConflict): w.conformance.run(w.ws, command(w, other), w.staff[1])
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_protocol_reports').fetchone()[0] == 1


@pytest.mark.parametrize('change', ['session', 'member', 'claim', 'resource', 'restore', 'withdraw'])
def test_current_authority_before_report_and_no_financial_effect(conformance, change):
    w = conformance; capture = prepare(w)
    if change == 'withdraw':
        from agent_market.workspace_sandbox_payments import WITHDRAW_NOTICE
        w.payments.withdraw(w.ws, {'intent_id': capture['id'], 'authorized': True, 'notice': WITHDRAW_NOTICE}, w.staff[1])
    else:
        with w.store._db as db:
            if change == 'session': db.execute('UPDATE admin_sessions SET expires_at=0 WHERE user_id=1')
            if change == 'member': db.execute('UPDATE workspace_memberships SET revision=revision+1 WHERE workspace_id=? AND user_id=1', (w.ws,))
            if change == 'claim': db.execute('UPDATE provider_control_claims SET revoked=?', (time.time(),))
            if change == 'resource': db.execute('UPDATE resources SET active=0 WHERE id=1')
            if change == 'restore': db.execute('INSERT INTO workspace_sandbox_payment_restore_blocks VALUES(?)', (capture['id'],))
    with pytest.raises((WorkspaceConflict, WorkspaceDenied)):
        w.conformance.run(w.ws, command(w, capture), w.staff[1])
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_protocol_reports').fetchone()[0] == 0
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_agreement_events').fetchone()[0] == 0


def test_wrong_refund_source_tamper_and_restore_never_become_positive_authority(conformance):
    w = conformance; capture = prepare(w); settled = dispatch(w, capture)['result']
    other = prepare(w, reference='sim_other_settlement'); second = dispatch(w, other)['result']
    refund = prepare(w, 'refund', second['id'], 1, second['revision'], 'sim_wrong_refund'); dispatch(w, refund)
    with pytest.raises(WorkspaceDenied): w.conformance.run(w.ws, command(w, capture, refund), w.staff[1])
    reported = w.conformance.run(w.ws, command(w, capture), w.staff[1])
    with w.store._db as db: db.execute('INSERT INTO workspace_protocol_restore_blocks VALUES(?)', (reported['id'],))
    historical = w.conformance.report(w.ws, reported['id'], w.staff[1])
    assert historical['restored'] and historical['current_authority'] == 'restore_blocked'
    with pytest.raises(WorkspaceConflict): w.conformance.run(w.ws, command(w, capture), w.staff[1])
    with w.store._db as db: db.execute("UPDATE workspace_protocol_reports SET payload='{}'")
    with pytest.raises(WorkspaceConflict): w.conformance.status(w.ws, w.staff[1])


@pytest.mark.parametrize('raw', [b'[]', b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}', b'{} '])
def test_header_decoder_rejects_duplicates_nonfinite_noncanonical_or_nonobjects(raw):
    with pytest.raises(WorkspaceInvalid): decode_header(base64.b64encode(raw).decode())


@pytest.mark.parametrize('text', ['', '!!!!', 'Zg', 'e30=\n', 'e30=extra', 'x' * 9000])
def test_header_decoder_rejects_noncanonical_or_unbounded_base64(text):
    with pytest.raises(WorkspaceInvalid): decode_header(text)


@pytest.mark.parametrize('profile', WIRE_PROFILES)
def test_selected_revision_scheme_network_binding_is_closed_and_mandate_is_not_ap2(profile):
    result = wire_suite(profile, 'a' * 64, 101, b'k' * 32)
    assert result['passed'] and len(result['checks']) == 7
    assert not result['ap2_credential_verified'] and not result['upstream_commit_pinned']
    with pytest.raises(WorkspaceDenied):
        validate_fixture_mandate({'profile': 'local-quote-mandate-fixture-v1',
            'checkout_hash': 'b' * 64, 'asset': 'TEST_UNIT', 'amount': 101,
            'audience': 'https://resource.example.invalid/synthetic', 'signature': '0' * 64}, 'a' * 64, 101, b'k' * 32)


@pytest.mark.parametrize('attack', ['float_version', 'float_timeout', 'integer_success', 'forged_signature', 'wrong_quote'])
def test_wire_subset_semantic_types_signature_and_quote_fail_closed(monkeypatch, attack):
    import agent_market.workspace_protocol_conformance as core
    observed = []; original = core.validate_fixture_headers
    def capture(headers, *args):
        if not observed: observed.append(copy.deepcopy(headers))
        return original(headers, *args)
    with monkeypatch.context() as context:
        context.setattr(core, 'validate_fixture_headers', capture)
        wire_suite(WIRE_PROFILES[0], 'a' * 64, 101, b'k' * 32)
    headers = observed[0]
    field = 'PAYMENT-REQUIRED' if attack in ('float_version', 'float_timeout') else 'PAYMENT-RESPONSE' if attack == 'integer_success' else 'PAYMENT-SIGNATURE'
    value = decode_header(headers[field])
    if attack == 'float_version': value['x402Version'] = 2.0
    if attack == 'float_timeout': value['accepts'][0]['maxTimeoutSeconds'] = 60.0
    if attack == 'integer_success': value['success'] = 1
    if attack == 'forged_signature': value['payload']['fixture_signature'] = '0' * 64
    if attack == 'wrong_quote': value['payload']['quote_hash'] = 'b' * 64
    headers[field] = core._encoded(value)
    with pytest.raises((WorkspaceInvalid, WorkspaceDenied)):
        original(headers, WIRE_PROFILES[0], 'a' * 64, 101, b'k' * 32)


@pytest.mark.parametrize('change', [{'actual_money': True}, {'authorized': False},
    {'notice': 'different-purpose'}, {'profile_id': 'x402-live'}, {'event_reference': '<img src=x onerror=alert(1)>'},
    {'capture_intent_id': 'wspi_' + 'a' * 32}])
def test_exact_purpose_and_bounded_source_identifiers(conformance, change):
    w = conformance; capture = prepare(w)
    with pytest.raises((WorkspaceInvalid, WorkspaceDenied)):
        w.conformance.run(w.ws, command(w, capture) | change, w.staff[1])
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_protocol_reports').fetchone()[0] == 0
