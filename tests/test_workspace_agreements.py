"""Provider term integrity and conserved TEST_UNIT simulation, never payments."""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import random
import time

import pytest

from agent_market.workspace_agreements import WorkspaceAgreements, NOTICE, allocation, remaining
from agent_market.workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid
from tests.test_provider_claims import provider, prepare, verify
from tests.test_workspace_access import provision, member


def contract():
    return {'asset': 'TEST_UNIT', 'scale': 0, 'provider_bps': 7000, 'platform_bps': 3000,
        'base': 'gross_less_processing_then_tax',
        'deductions': {'processing_bps': 250, 'processing_fixed_units': 2, 'tax_bps': 1000},
        'refund_responsibility': 'proportional_original_components',
        'rounding': 'floor_provider_platform_remainder',
        'document_reference': 'synthetic-terms-v1', 'document_sha256': 'a' * 64}


@pytest.fixture
def agreement(provider):
    w = provider
    w.agreements = WorkspaceAgreements(w.access, w.claims)
    w.verified = verify(w, prepare(w))
    w.body = {'resource_id': 1, 'claim_id': w.verified['id'], 'claim_revision': w.verified['revision'],
              'revision': 0, 'expires': time.time() + 3600, 'terms': contract(),
              'authorized': True, 'notice': NOTICE}
    w.agreement = w.agreements.create(w.ws, w.body, w.staff[1])
    return w


def settle(w, amount=101, event='sim_capture'):
    quote = w.agreements.quote(w.ws, w.agreement['id'], {'gross_units': amount}, w.staff[1])
    body = {'event_reference': event, 'gross_units': amount, 'quote_hash': quote['quote_hash'],
            'revision': w.agreement['revision'], 'authorized': True, 'notice': NOTICE}
    return w.agreements.settle(w.ws, w.agreement['id'], body, w.staff[1]), body


def refund(w, current, amount, event):
    body = {'event_reference': event, 'units': amount, 'revision': current['revision'],
            'authorized': True, 'notice': NOTICE}
    return w.agreements.refund(w.ws, current['id'], body, w.staff[1]), body


def test_immutable_terms_exact_endpoint_pin_platform_signature_never_legal_assent(agreement):
    w = agreement
    assert len(w.provider_calls) == 1
    dto = w.agreement
    assert dto['legal_verification'] == 'unverified'
    assert dto['signature_kind'] == 'platform_record_integrity'
    assert dto['terms']['provider_bps'] == 7000 and dto['terms']['platform_bps'] == 3000
    assert all(dto[name] is False for name in ('actual_money', 'commercial_enabled', 'payment_enabled', 'provider_payout_enabled', 'operating_contract_proof'))
    serialized = json.dumps(w.agreements.versions(w.ws, w.staff[1]))
    assert all(secret not in serialized for secret in ('session_ref', 'binding_hash', 'synthetic.invalid', 'nonce', 'signature"'))
    assert len(w.provider_calls) == 1


def test_version_change_is_cas_immutable_and_supersedes_only_admission(agreement):
    w = agreement; before = tuple(w.store._db.execute('SELECT * FROM workspace_provider_agreements WHERE id=?', (w.agreement['id'],)).fetchone())
    captured, _ = settle(w)
    request = copy.deepcopy(w.body); request['revision'] = 1; request['terms']['document_sha256'] = 'b' * 64
    second = w.agreements.create(w.ws, request, w.staff[1])
    assert second['ordinal'] == 2 and second['head_revision'] == 2
    assert tuple(w.store._db.execute('SELECT * FROM workspace_provider_agreements WHERE id=?', (w.agreement['id'],)).fetchone()) == before
    with pytest.raises(WorkspaceDenied): w.agreements.quote(w.ws, w.agreement['id'], {'gross_units': 10}, w.staff[1])
    refunded, _ = refund(w, captured, 1, 'sim_old_obligation')
    assert refunded['refunded_units'] == 1
    with pytest.raises(WorkspaceConflict): w.agreements.create(w.ws, request, w.staff[1])


def test_deterministic_quote_deductions_and_integer_remainder(agreement):
    w = agreement; quote = w.agreements.quote(w.ws, w.agreement['id'], {'gross_units': 101}, w.staff[1])
    assert quote['allocation'] == {'gross_units': 101, 'processing_units': 4, 'tax_units': 9,
        'distributable_units': 88, 'provider_units': 61, 'platform_units': 27}
    assert quote['quote_hash'] == w.agreements.quote(w.ws, w.agreement['id'], {'gross_units': 101}, w.staff[1])['quote_hash']
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_agreement_settlements').fetchone()[0] == 0
    assert len(w.provider_calls) == 1


def test_cumulative_refund_is_split_independent_monotone_and_exact():
    rng = random.Random(73)
    for _ in range(300):
        terms = contract(); terms['deductions'] = {'processing_bps': rng.randrange(2501),
            'processing_fixed_units': rng.randrange(150), 'tax_bps': rng.randrange(5001)}
        gross = rng.randrange(1, 250)
        original = allocation(gross, terms)
        previous = original
        for total in range(gross + 1):
            residual = remaining(original, total)
            assert residual['gross_units'] == gross - total
            assert sum(residual[key] for key in ('processing_units', 'tax_units', 'provider_units', 'platform_units')) == gross - total
            assert all(0 <= residual[key] <= previous[key] for key in ('processing_units', 'tax_units', 'provider_units', 'platform_units'))
            previous = residual
        assert all(value == 0 for value in remaining(original, gross).values())


def test_capture_and_partial_full_refund_entries_conserve_and_replay_deduplicates(agreement):
    w = agreement; current, body = settle(w)
    replay = w.agreements.settle(w.ws, w.agreement['id'], body, w.staff[1])
    assert replay['replayed'] and replay['id'] == current['id']
    first, refund_body = refund(w, current, 33, 'sim_refund_first')
    same = w.agreements.refund(w.ws, first['id'], refund_body, w.staff[1])
    assert same['replayed'] and same['revision'] == first['revision']
    second, _ = refund(w, first, 20, 'sim_refund_second')
    assert second['remaining'] == remaining(current['original'], 53)
    final, _ = refund(w, second, 48, 'sim_refund_final')
    assert final['status'] == 'refunded' and all(value == 0 for value in final['remaining'].values())
    summary = w.agreements.summary(w.ws, w.staff[1])
    assert summary['balanced'] and all(value == 0 for value in summary['balances'].values())
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_agreement_events').fetchone()[0] == 4
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_agreement_entries').fetchone()[0] == 20


def test_event_reuse_with_different_command_is_denied_without_new_entries(agreement):
    w = agreement; current, body = settle(w)
    with pytest.raises(WorkspaceConflict): w.agreements.settle(w.ws, w.agreement['id'], body | {'gross_units': 99}, w.staff[1])
    with pytest.raises(WorkspaceConflict): refund(w, current, 1, 'sim_capture')
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_agreement_events').fetchone()[0] == 1


def test_concurrent_refunds_cas_prevents_over_refund_and_duplicate_responsibility(agreement):
    w = agreement; current, _ = settle(w, 100)
    def run(index):
        try:
            return refund(w, current, 80, 'sim_race_' + str(index))[0]
        except WorkspaceConflict:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(run, (1, 2)))
    successful = [value for value in outcomes if value]
    assert len(successful) == 1 and successful[0]['remaining']['gross_units'] == 20
    with pytest.raises(WorkspaceConflict): refund(w, successful[0], 80, 'sim_over_refund')
    summary = w.agreements.summary(w.ws, w.staff[1])
    assert summary['balanced'] and summary['settlements'][0]['refunded_units'] == 80
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_agreement_events').fetchone()[0] == 2


def test_final_event_slot_requires_full_refund_to_leave_no_stranded_balance(agreement, monkeypatch):
    w = agreement
    monkeypatch.setattr('agent_market.workspace_agreements.MAX_EVENTS', 3)
    current, _ = settle(w, 100)
    current, _ = refund(w, current, 10, 'sim_slot_first')
    with pytest.raises(WorkspaceConflict): refund(w, current, 10, 'sim_slot_blocked')
    assert refund(w, current, 90, 'sim_slot_final')[0]['status'] == 'refunded'


def test_same_external_refund_event_race_is_one_post_and_one_exact_replay(agreement):
    w = agreement; current, _ = settle(w, 100)
    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(lambda _: refund(w, current, 25, 'sim_duplicate_race')[0], (1, 2)))
    assert sum(value.get('replayed', False) is True for value in values) == 1
    assert all(value['refunded_units'] == 25 for value in values)
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_agreement_events').fetchone()[0] == 2
    assert w.agreements.summary(w.ws, w.staff[1])['balanced']


@pytest.mark.parametrize('fault', ['claim_revoke', 'resource_generation_aba', 'member_aba', 'workspace_revision', 'claim_expiry', 'agreement_expiry', 'restore_block', 'proof_owner_disabled'])
def test_current_endpoint_owner_expiry_epochs_and_restore_fail_closed(agreement, fault, monkeypatch):
    w = agreement; current, _ = settle(w)
    with w.store.tx() as db:
        if fault == 'claim_revoke': db.execute('UPDATE provider_control_claims SET revoked=1 WHERE id=?', (w.verified['id'],))
        elif fault == 'resource_generation_aba': db.execute('UPDATE resource_observation_generations SET generation=generation+2 WHERE resource_id=1')
        elif fault == 'member_aba': db.execute('UPDATE workspace_memberships SET revision=revision+2 WHERE workspace_id=? AND user_id=1', (w.ws,))
        elif fault == 'workspace_revision': db.execute('UPDATE organization_workspaces SET revision=revision+1 WHERE id=?', (w.ws,))
        elif fault == 'restore_block': db.execute('INSERT INTO workspace_agreement_restore_blocks VALUES(?)', (w.agreement['id'],))
        elif fault == 'proof_owner_disabled': db.execute('UPDATE admin_users SET active=0 WHERE id=1')
    if fault == 'claim_expiry':
        monkeypatch.setattr('agent_market.provider_claims._time', lambda: time.time() + 31 * 86400)
    if fault == 'agreement_expiry':
        monkeypatch.setattr('agent_market.workspace_agreements.clock', lambda: time.time() + 3601)
    with pytest.raises(WorkspaceDenied): w.agreements.quote(w.ws, w.agreement['id'], {'gross_units': 10}, w.staff[1])
    with pytest.raises(WorkspaceDenied): refund(w, current, 1, 'sim_after_withdrawal')
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_agreement_events').fetchone()[0] == 1


def test_revocation_stops_new_capture_but_permits_old_simulated_obligation_refund(agreement):
    w = agreement; current, _ = settle(w)
    state = w.agreements.revoke(w.ws, w.agreement['id'], {'revision': 1}, w.staff[1])
    assert state['status'] == 'revoked' and state['revision'] == 2
    with pytest.raises(WorkspaceDenied): w.agreements.quote(w.ws, w.agreement['id'], {'gross_units': 10}, w.staff[1])
    with pytest.raises(WorkspaceConflict): w.agreements.revoke(w.ws, w.agreement['id'], {'revision': 1}, w.staff[1])
    assert refund(w, current, 101, 'sim_revoked_refund')[0]['status'] == 'refunded'


@pytest.mark.parametrize('change', [{'asset': 'USD_CENT'}, {'provider_bps': 7000.0}, {'provider_bps': 6000}, {'platform_bps': 4000}, {'scale': True}, {'document_reference': 'https://outside.invalid'}, {'document_sha256': 'not-proof'}, {'refund_responsibility': 'provider_pays_all'}])
def test_terms_require_exact_simulation_integer_and_unverified_document_contract(agreement, change):
    w = agreement; request = copy.deepcopy(w.body); request['revision'] = 1; request['terms'].update(change)
    with pytest.raises(WorkspaceInvalid): w.agreements.create(w.ws, request, w.staff[1])


@pytest.mark.parametrize('value', [True, 1.5, 0, -1, 10**12 + 1, '100'])
def test_quote_units_are_bounded_integers(agreement, value):
    with pytest.raises(WorkspaceInvalid): agreement.agreements.quote(agreement.ws, agreement.agreement['id'], {'gross_units': value}, agreement.staff[1])


def test_owner_and_workspace_isolation_and_signature_tamper(agreement):
    w = agreement; other = provision((w.store, w.access, w.staff))['id']
    with pytest.raises(WorkspaceDenied): w.agreements.quote(other, w.agreement['id'], {'gross_units': 1}, w.staff[1])
    with pytest.raises(WorkspaceDenied): w.agreements.options(w.ws, w.staff[5])
    with w.store.tx() as db:
        payload = json.loads(db.execute('SELECT payload FROM workspace_provider_agreements WHERE id=?', (w.agreement['id'],)).fetchone()[0])
        payload['terms']['document_sha256'] = 'f' * 64
        db.execute('UPDATE workspace_provider_agreements SET payload=? WHERE id=?', (json.dumps(payload), w.agreement['id']))
    with pytest.raises(WorkspaceConflict): w.agreements.quote(w.ws, w.agreement['id'], {'gross_units': 1}, w.staff[1])


def test_missing_or_tampered_ledger_entry_cannot_produce_a_balanced_summary(agreement):
    w = agreement; current, _ = settle(w)
    with w.store.tx() as db:
        db.execute('DELETE FROM workspace_agreement_entries WHERE event_id=(SELECT id FROM workspace_agreement_events LIMIT 1) AND ordinal=4')
    with pytest.raises(WorkspaceConflict): w.agreements.summary(w.ws, w.staff[1])
    with pytest.raises(WorkspaceConflict): refund(w, current, 1, 'sim_missing_entry')
