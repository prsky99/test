"""Disposable customer recovery: independent offline keys, no live identities."""
import copy
import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agent_market.customer_identity import _b64
from agent_market.customer_recovery import CustomerRecovery, RecoveryAuthority, NOTICE, WAIT_SECONDS
from agent_market.workspace_access import _canonical, WorkspaceDenied, WorkspaceConflict
from tests.test_customer_organizations import orgs  # noqa: F401


def keypair():
    private = Ed25519PrivateKey.generate()
    return private, _b64(private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))


@pytest.fixture
def recovery(orgs):
    w = orgs
    w.offline, w.public = keypair()
    w.reviewer, reviewer_public = keypair()
    w.recovery = CustomerRecovery(w.orgs, (RecoveryAuthority('independent-review', reviewer_public),))
    w.recovery.enroll(w.organization['id'], {'public_key': w.public,
        'authority_id': 'independent-review', 'revision': 0, 'authorized': True, 'notice': NOTICE}, w.customers[0])
    return w


def prepare(w):
    return w.recovery.challenge(w.organization['id'], {'evidence_sha256': 'a' * 64}, w.customers[1])['claim']


def submit(w, claim, **overrides):
    body = {'owner_signature': _b64(w.offline.sign(_canonical(claim).encode())),
            'authority_signature': _b64(w.reviewer.sign(_canonical(claim).encode()))}
    return w.recovery.submit(w.organization['id'], claim['id'], body | overrides, w.customers[1])


def test_dual_proof_wait_and_finalization_revoke_old_authority(recovery, monkeypatch):
    w = recovery; ws = w.organization['id']; claim = prepare(w)
    pending = submit(w, claim)
    assert pending['access_granted'] is False
    with pytest.raises(WorkspaceDenied):
        w.recovery.finalize(ws, claim['id'], w.customers[1])
    monkeypatch.setattr('agent_market.customer_recovery._time', lambda: pending['eligible_after'] + 1)
    result = w.recovery.finalize(ws, claim['id'], w.customers[1])
    assert result['old_sessions_revoked'] and result['new_recovery_enrollment_required']
    assert w.orgs.detail(ws, w.customers[1])['role'] == 'owner'
    with pytest.raises(WorkspaceDenied):
        w.orgs.detail(ws, w.customers[0])
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_memberships WHERE workspace_id=?', (ws,)).fetchone()[0] == 0
    with pytest.raises(WorkspaceDenied):
        w.recovery.challenge(ws, {'evidence_sha256': 'b' * 64}, w.customers[2])
    with pytest.raises(WorkspaceDenied):
        w.recovery.finalize(ws, claim['id'], w.customers[2])


def test_reviewer_alone_and_wrong_identity_or_modified_claim_cannot_recover(recovery):
    w = recovery; claim = prepare(w)
    with pytest.raises(WorkspaceDenied):
        submit(w, claim, owner_signature=_b64(w.reviewer.sign(_canonical(claim).encode())))
    changed = copy.deepcopy(claim); changed['target_id'] = w.customers[2].customer_id
    with pytest.raises(WorkspaceDenied):
        submit(w, changed)
    assert w.recovery.status(w.organization['id'], claim['id'], w.customers[1])['status'] == 'challenge'


@pytest.mark.parametrize('action', ['contest', 'withdraw'])
def test_dispute_or_withdrawal_prevents_later_finalization(recovery, monkeypatch, action):
    w = recovery; ws = w.organization['id']; claim = prepare(w); pending = submit(w, claim)
    actor = w.customers[0] if action == 'contest' else w.customers[1]
    assert not getattr(w.recovery, action)(ws, claim['id'], actor)['access_granted']
    monkeypatch.setattr('agent_market.customer_recovery._time', lambda: pending['eligible_after'] + 1)
    with pytest.raises(WorkspaceDenied):
        w.recovery.finalize(ws, claim['id'], w.customers[1])


def test_fresh_workspace_revision_and_key_custody_are_required(recovery):
    w = recovery; ws = w.organization['id']; claim = prepare(w)
    w.orgs.rename(ws, {'name': 'Changed team', 'revision': 1}, w.customers[0])
    with pytest.raises(WorkspaceDenied):
        submit(w, claim)
    with pytest.raises(WorkspaceDenied):
        CustomerRecovery(w.orgs).challenge(ws, {'evidence_sha256': 'b' * 64}, w.customers[1])
    review = w.recovery.review(ws, w.customers[0])
    assert not review['enrolled'] and review['reenrollment_required']


def test_restored_request_and_enrollment_blocks_fail_closed(recovery):
    w = recovery; ws = w.organization['id']; claim = prepare(w)
    with w.core.tx() as db:
        db.execute('INSERT INTO customer_recovery_blocks VALUES(?)', (claim['id'],))
    with pytest.raises(WorkspaceDenied):
        submit(w, claim)
    with w.core.tx() as db:
        db.execute('INSERT INTO customer_recovery_blocks VALUES(?)', (ws + ':1',))
    with pytest.raises(WorkspaceDenied):
        prepare(w)


def test_claim_cap_and_signature_tamper_do_not_grant_access(recovery):
    w = recovery; ws = w.organization['id']; claim = prepare(w)
    with w.core.tx() as db:
        db.execute('UPDATE customer_recovery_requests SET payload=? WHERE id=?', ('{}', claim['id']))
    with pytest.raises(WorkspaceConflict):
        w.recovery.status(ws, claim['id'], w.customers[1])
    for _ in range(4):
        prepare(w)
    with pytest.raises(WorkspaceConflict):
        prepare(w)


def test_private_api_requires_customer_cookie_csrf_and_exact_body(recovery):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agent_market.customer_identity_service import COOKIE
    from agent_market.customer_recovery_service import router_for
    w = recovery; app = FastAPI(); app.include_router(router_for(w.recovery))
    path = '/api/customer-auth/organizations/' + w.organization['id'] + '/recovery/challenges'
    with TestClient(app, base_url='https://customer.test') as client:
        # No session cookie is an authentication failure (401); a session without CSRF is refused below.
        assert client.post(path, json={'evidence_sha256': 'a' * 64}).status_code == 401
        token = w.auths[1]['session_token']
        client.cookies.set(COOKIE, token)
        headers = {'Origin': 'https://customer.test', 'X-Customer-CSRF': w.core.csrf(token)}
        assert client.post(path, headers=headers, json={'evidence_sha256': 'a' * 64}).status_code == 200
        assert client.post(path, headers=headers | {'Origin': 'https://other.test'}, json={'evidence_sha256': 'a' * 64}).status_code == 403
        assert client.post(path, headers=headers | {'X-Customer-CSRF': '0' * 64}, json={'evidence_sha256': 'a' * 64}).status_code == 403
        response = client.post(path, headers=headers, json={'evidence_sha256': 'a' * 64, 'role': 'superadmin'})
        assert response.status_code == 400 and 'superadmin' not in response.text


def test_no_authority_means_no_recovery_transport(orgs):
    from agent_market.customer_recovery_service import router_for
    assert router_for(CustomerRecovery(orgs.orgs)).routes == []
    assert router_for(None).routes == []


@pytest.mark.parametrize('action', ['contest', 'withdraw'])
def test_unsigned_status_mutation_cannot_reactivate_a_resolved_claim(recovery, monkeypatch, action):
    w = recovery; ws = w.organization['id']; claim = prepare(w); pending = submit(w, claim)
    getattr(w.recovery, action)(ws, claim['id'], w.customers[0] if action == 'contest' else w.customers[1])
    with w.core.tx() as db:
        db.execute("UPDATE customer_recovery_requests SET status='pending' WHERE id=?", (claim['id'],))
    monkeypatch.setattr('agent_market.customer_recovery._time', lambda: pending['eligible_after'] + 1)
    with pytest.raises(WorkspaceConflict):
        w.recovery.finalize(ws, claim['id'], w.customers[1])
    assert w.orgs.detail(ws, w.customers[0])['role'] == 'owner'


def test_challenge_budget_is_per_target_and_unsigned_challenges_expire(recovery, monkeypatch):
    w = recovery; ws = w.organization['id']; claim = prepare(w)
    for _ in range(4):
        prepare(w)
    other = w.recovery.challenge(ws, {'evidence_sha256': 'b' * 64}, w.customers[2])
    assert other['claim']['target_id'] == w.customers[2].customer_id
    monkeypatch.setattr('agent_market.customer_recovery._time', lambda: claim['created'] + 3601)
    with pytest.raises(WorkspaceDenied):
        submit(w, claim)
    assert prepare(w)['target_id'] == w.customers[1].customer_id
