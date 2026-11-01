"""Endpoint proof lifecycle and transfer never inherit quality or old authority."""
import json
import time

import pytest

from agent_market.provider_claims import NOTICE
from agent_market.workspace_access import WorkspaceDenied, WorkspaceConflict
from agent_market.workflow_backup import quarantine
from tests.test_provider_claims import provider, prepare, verify


def test_rechallenge_invalidates_old_proof_and_requires_new_nonce(provider):
    w = provider; first = prepare(w); result = verify(w, first)
    fresh = w.claims.rechallenge(w.ws, result['id'], {'revision': result['revision']}, w.staff[1])
    assert fresh['claim']['id'] != result['id'] and fresh['challenge']['nonce'] != first['challenge']['nonce']
    assert len(w.provider_calls) == 1
    with w.store.tx() as db:
        with pytest.raises(WorkspaceDenied): w.claims.current(db, w.ws, 1)
    w.proof = fresh['challenge']; assert verify(w, fresh)['status'] == 'verified'
    with pytest.raises(WorkspaceConflict): w.claims.rechallenge(w.ws, result['id'], {'revision': result['revision']}, w.staff[1])


def test_domain_binding_change_requires_fresh_challenge(provider):
    w = provider; result = verify(w, prepare(w))
    with w.store.tx() as db:
        db.execute("UPDATE resources SET url='https://different.invalid/mcp' WHERE id=1")
        db.execute('UPDATE resource_observation_generations SET generation=generation+1 WHERE resource_id=1')
    fresh = w.claims.rechallenge(w.ws, result['id'], {'revision': result['revision']}, w.staff[1])
    assert fresh['claim']['challenge_url'] == 'https://different.invalid/.well-known/agent-concierge-claim.json'
    with w.store.tx() as db:
        with pytest.raises(WorkspaceDenied): w.claims.current(db, w.ws, 1)
    assert len(w.provider_calls) == 1


def test_bounded_expiry_persists_audited_terminal_status(provider, monkeypatch):
    w = provider; result = verify(w, prepare(w))
    import agent_market.provider_claims as module
    monkeypatch.setattr(module, '_time', lambda: time.time() + 31 * 86400)
    assert w.claims.expire(w.ws, {'limit': 1}, w.staff[1])['expired'] == 1
    row = w.claims.claims(w.ws, w.staff[1])[0]
    assert row['status'] == 'expired' and row['revision'] == result['revision'] + 1
    assert w.claims.expire(w.ws, {'limit': 1}, w.staff[1])['expired'] == 0
    assert len(w.provider_calls) == 1


def transfer(w):
    result = verify(w, prepare(w))
    target = w.access.provision({'name': 'New owner workspace', 'owner_id': 4}, w.staff[1])['id']
    offer = w.claims.transfer(w.ws, result['id'], {'revision': result['revision'], 'target_workspace_id': target}, w.staff[1])
    return target, offer


def test_transfer_requires_target_owner_and_fresh_domain_nonce(provider):
    w = provider; target, offer = transfer(w)
    assert offer['fresh_challenge_required'] and len(w.provider_calls) == 1
    with w.store.tx() as db:
        with pytest.raises(WorkspaceDenied): w.claims.current(db, w.ws, 1)
    with pytest.raises(WorkspaceDenied): w.claims.accept_transfer(target, offer['transfer_id'], {'revision': 1}, w.staff[1])
    fresh = w.claims.accept_transfer(target, offer['transfer_id'], {'revision': 1}, w.staff[4])
    assert len(w.provider_calls) == 1
    with w.store.tx() as db:
        with pytest.raises(WorkspaceDenied): w.claims.current(db, target, 1)
    w.proof = fresh['challenge']
    result = w.claims.verify(target, {'claim_id': fresh['claim']['id'], 'revision': 1, 'authorized': True, 'notice': NOTICE}, w.staff[4])
    assert result['status'] == 'verified' and not result['quality_certified']
    with pytest.raises(WorkspaceDenied): w.claims.accept_transfer(target, offer['transfer_id'], {'revision': 1}, w.staff[4])


@pytest.mark.parametrize('fault', ['revision', 'binding', 'tamper', 'restore'])
def test_transfer_stale_changed_tampered_or_restored_offer_is_never_redeemed(provider, fault):
    w = provider; target, offer = transfer(w)
    with w.store.tx() as db:
        if fault == 'revision': db.execute('UPDATE organization_workspaces SET revision=revision+1 WHERE id=?', (target,))
        elif fault == 'binding': db.execute('UPDATE resource_observation_generations SET generation=generation+1 WHERE resource_id=1')
        elif fault == 'tamper': db.execute("UPDATE provider_claim_transfers SET signature='bad' WHERE id=?", (offer['transfer_id'],))
        else: db.execute('INSERT INTO provider_claim_transfer_restore_blocks VALUES(?)', (offer['transfer_id'],))
    with pytest.raises(WorkspaceDenied): w.claims.accept_transfer(target, offer['transfer_id'], {'revision': 1}, w.staff[4])
    assert w.store._db.execute('SELECT COUNT(*) FROM provider_control_claims WHERE workspace_id=?', (target,)).fetchone()[0] == 0
    assert len(w.provider_calls) == 1


def test_restore_blocks_transfer_ids_without_editing_signed_offer(provider):
    w = provider; target, offer = transfer(w)
    before = tuple(w.store._db.execute('SELECT payload,signature FROM provider_claim_transfers').fetchone())
    with w.store.tx() as db: quarantine(db)
    after = tuple(w.store._db.execute('SELECT payload,signature FROM provider_claim_transfers').fetchone())
    assert before == after
    assert w.store._db.execute('SELECT id FROM provider_claim_transfer_restore_blocks').fetchone()[0] == offer['transfer_id']
