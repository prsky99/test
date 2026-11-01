"""Synthetic current-customer organization lifecycle, without live providers."""
import json
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from agent_market.customer_identity import CustomerActor
from agent_market.customer_identity_service import COOKIE, router_for
from agent_market.customer_organizations import CustomerOrganizations
from agent_market.workspace_access import WorkspaceDenied, WorkspaceConflict, WorkspaceInvalid
from tests.test_customer_identity import customer_world, login
from tests.test_customer_workspace_runtime import customer_run
from tests.test_workspace_access import draft_body, definition


@pytest.fixture
def orgs():
    w = customer_world()
    w.orgs = CustomerOrganizations(w.core, w.access)
    w.auths, w.customers = [], []
    for index in range(4):
        w.state['claims'] = {'sub': 'synthetic-customer-' + str(index)}
        auth = login(w)
        w.auths.append(auth)
        w.customers.append(w.core.actor(auth['session_token']))
    w.organization = w.orgs.create({'name': 'Synthetic customer team'}, w.customers[0])
    try:
        yield w
    finally:
        w.http.close()
        w.store._db.close()


def invite(w, index=1, role='viewer'):
    current = w.orgs.detail(w.organization['id'], w.customers[0])
    return w.orgs.invite(current['id'], {'customer_id': w.customers[index].customer_id,
        'role': role, 'revision': current['organization_revision']}, w.customers[0])


def accept(w, index=1, role='viewer'):
    ticket = invite(w, index, role)
    w.orgs.resolve_invitation(ticket['id'], {'decision': 'accept', 'revision': ticket['revision']}, w.customers[index])
    return w.orgs.detail(w.organization['id'], w.customers[index])


def test_customer_creation_never_creates_staff_membership_or_global_staff_access(orgs):
    w = orgs; ws = w.organization['id']
    assert w.organization['role'] == 'owner' and w.organization['can_manage']
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_memberships WHERE workspace_id=?', (ws,)).fetchone()[0] == 0
    assert w.store._db.execute('SELECT created_by FROM organization_workspaces WHERE id=?', (ws,)).fetchone()[0] == 0
    with pytest.raises(WorkspaceDenied): w.access.workspace(ws, w.staff[1])
    with pytest.raises(WorkspaceDenied): w.orgs.detail(ws, w.staff[1])
    assert w.orgs.list(w.customers[1])['organizations'] == []
    assert w.orgs.audit(ws, w.customers[0])[0]['action'] == 'organization.create'


@pytest.mark.parametrize('role,edit,run,manage', [('viewer', False, False, False), ('runner', False, True, False), ('editor', True, True, False), ('owner', True, True, True)])
def test_roles_are_distinct_and_fresh_in_current_transaction(orgs, role, edit, run, manage):
    w = orgs; ws = w.organization['id']; current = accept(w, role=role)
    assert (current['can_edit'], current['can_run'], current['can_manage']) == (edit, run, manage)
    with w.core.tx() as db:
        for purpose, allowed in [('read', True), ('edit', edit), ('execute', run), ('manage', manage)]:
            if allowed: assert w.core.authorize(db, w.customers[1], ws, purpose)['role'] == role
            else:
                with pytest.raises(WorkspaceDenied): w.core.authorize(db, w.customers[1], ws, purpose)
    actor = w.orgs.runtime_actor(ws, w.customers[1])
    if edit:
        draft = w.orgs.drafts.save_draft(ws, draft_body(definition()), actor)
        snapshot = w.orgs.drafts.create_snapshot(ws, draft['id'], {'draft_revision': 1}, actor)
        assert snapshot['snapshot']['definition'] == definition()
        assert snapshot['snapshot']['name'] == draft['name']
        assert w.store._db.execute('SELECT created_by FROM workspace_drafts WHERE id=?', (draft['id'],)).fetchone()[0] == w.customers[1].customer_id
    else:
        with pytest.raises(WorkspaceDenied): w.orgs.drafts.save_draft(ws, draft_body(), actor)
    if manage: assert len(w.orgs.members(ws, w.customers[1])) == 2
    else:
        with pytest.raises(WorkspaceDenied): w.orgs.members(ws, w.customers[1])


def test_invitation_has_no_bearer_authority_is_exact_identity_one_use_and_cas(orgs):
    w = orgs; invitation = invite(w, role='editor'); ws = w.organization['id']
    assert 'token' not in json.dumps(invitation)
    with pytest.raises(WorkspaceDenied): w.orgs.resolve_invitation(invitation['id'], {'decision': 'accept', 'revision': 1}, w.customers[2])
    with pytest.raises(WorkspaceDenied): w.orgs.detail(ws, w.customers[1])
    with pytest.raises(WorkspaceConflict): w.orgs.resolve_invitation(invitation['id'], {'decision': 'accept', 'revision': 2}, w.customers[1])
    accepted = w.orgs.resolve_invitation(invitation['id'], {'decision': 'accept', 'revision': 1}, w.customers[1])
    assert accepted['status'] == 'accepted'
    with pytest.raises(WorkspaceConflict): w.orgs.resolve_invitation(invitation['id'], {'decision': 'accept', 'revision': 1}, w.customers[1])
    assert len(w.orgs.list(w.customers[1])['organizations']) == 1


@pytest.mark.parametrize('decision,expected', [('decline', 'declined'), ('revoke', 'revoked')])
def test_invitation_decline_or_owner_revocation_does_not_create_access(orgs, decision, expected):
    w = orgs; ticket = invite(w)
    actor = w.customers[0] if decision == 'revoke' else w.customers[1]
    assert w.orgs.resolve_invitation(ticket['id'], {'decision': decision, 'revision': 1}, actor)['status'] == expected
    assert not w.orgs.list(w.customers[1])['organizations']


def test_invitation_expires_and_issuer_role_generation_cannot_be_replayed(orgs):
    w = orgs; ticket = invite(w)
    with w.core.tx() as db: db.execute('UPDATE customer_organization_invitations SET expires=0 WHERE id=?', (ticket['id'],))
    with pytest.raises(WorkspaceConflict): w.orgs.resolve_invitation(ticket['id'], {'decision': 'accept', 'revision': 1}, w.customers[1])
    assert w.orgs.invitations(w.customers[1])[0]['status'] == 'expired'
    second = invite(w)
    accept(w, index=2, role='owner')
    current = w.orgs.detail(w.organization['id'], w.customers[0])
    w.orgs.transfer(current['id'], {'customer_id': w.customers[2].customer_id, 'revision': current['organization_revision'],
        'target_revision': w.orgs.detail(current['id'], w.customers[2])['link_revision']}, w.customers[0])
    with pytest.raises(WorkspaceDenied): w.orgs.resolve_invitation(second['id'], {'decision': 'accept', 'revision': 1}, w.customers[1])


def test_last_owner_cannot_leave_or_be_removed_and_transfer_requires_accepted_owner(orgs):
    w = orgs; ws = w.organization['id']; actor = w.customers[0]
    with pytest.raises(WorkspaceConflict): w.orgs.leave(ws, {'revision': 1}, actor)
    with pytest.raises(WorkspaceConflict): w.orgs.set_member(ws, {'customer_id': actor.customer_id, 'role': 'editor', 'active': True, 'revision': 1}, actor)
    target = accept(w, role='editor')
    current = w.orgs.detail(ws, actor)
    with pytest.raises(WorkspaceDenied): w.orgs.transfer(ws, {'customer_id': w.customers[1].customer_id, 'revision': current['organization_revision'], 'target_revision': target['link_revision']}, actor)
    with pytest.raises(WorkspaceInvalid): w.orgs.set_member(ws, {'customer_id': w.customers[1].customer_id, 'role': 'owner', 'active': True, 'revision': target['link_revision']}, actor)
    owner = accept(w, index=2, role='owner'); current = w.orgs.detail(ws, actor)
    moved = w.orgs.transfer(ws, {'customer_id': w.customers[2].customer_id, 'revision': current['organization_revision'], 'target_revision': owner['link_revision']}, actor)
    assert moved['role'] == 'editor' and not moved['can_manage']
    assert w.orgs.leave(ws, {'revision': moved['link_revision']}, actor)['left']
    with pytest.raises(WorkspaceDenied): w.orgs.detail(ws, actor)


def test_two_owner_leave_race_keeps_one_current_owner(orgs):
    from concurrent.futures import ThreadPoolExecutor
    w = orgs; accept(w, role='owner'); ws = w.organization['id']
    revisions = [w.orgs.detail(ws, actor)['link_revision'] for actor in w.customers[:2]]
    def leave(index):
        try:
            w.orgs.leave(ws, {'revision': revisions[index]}, w.customers[index])
            return 'left'
        except WorkspaceConflict:
            return 'retained'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(leave, (0, 1))) == ['left', 'retained']
    assert w.store._db.execute("SELECT COUNT(*) FROM customer_workspace_links WHERE workspace_id=? AND role='owner' AND active=1", (ws,)).fetchone()[0] == 1


def test_owner_with_unconfigured_identity_provider_does_not_satisfy_last_owner(orgs):
    w = orgs; accept(w, role='owner')
    with w.core.tx() as db:
        db.execute("UPDATE customer_identities SET issuer='https://github.com' WHERE id=?", (w.customers[1].customer_id,))
    with pytest.raises(WorkspaceConflict): w.orgs.leave(w.organization['id'], {'revision': 1}, w.customers[0])


def test_member_role_change_revokes_bff_tokens_and_old_role_ticket_claims(orgs):
    w = orgs; ws = w.organization['id']; runner = accept(w, role='runner')
    capability = w.core.issue_token(w.auths[1]['session_token'], ws, 'execute')
    assert w.core.validate_token(capability['access_token'], ws, 'execute')['role'] == 'runner'
    w.orgs.set_member(ws, {'customer_id': w.customers[1].customer_id, 'role': 'viewer', 'active': True, 'revision': runner['link_revision']}, w.customers[0])
    with pytest.raises(WorkspaceDenied): w.core.validate_token(capability['access_token'], ws, 'execute')
    with pytest.raises(WorkspaceDenied): w.core.issue_token(w.auths[1]['session_token'], ws, 'execute')
    with pytest.raises(WorkspaceDenied): w.core.issue_token(w.auths[0]['session_token'], ws, 'manage')


def test_execute_bff_capability_cannot_be_broadened_into_customer_owner_control(orgs):
    from agent_market.customer_workspace_runtime import CustomerWorkspaceAccess
    w = orgs; ws = w.organization['id']
    adapter = CustomerWorkspaceAccess(w.access, w.core)
    token = w.core.issue_token(w.auths[0]['session_token'], ws, 'execute')
    scoped = adapter.from_scope(w.core.validate_token(token['access_token'], ws, 'execute'))
    with w.core.tx() as db:
        assert adapter._access(ws, scoped, write=True)[0]['member_role'] == 'owner'
        with pytest.raises(WorkspaceDenied): adapter._access(ws, scoped, write=True, owner=True)


def test_account_deletion_requires_explicit_sole_owner_archival_and_revokes_all_sessions(orgs):
    w = orgs; actor = w.customers[0]; ws = w.organization['id']; ticket = invite(w)
    request = {'revision': 1, 'confirm': 'DELETE', 'archive_owned': False}
    with pytest.raises(WorkspaceConflict): w.orgs.delete_account(request, actor)
    assert w.orgs.detail(ws, actor)['can_manage']
    receipt = w.orgs.delete_account(request | {'archive_owned': True}, actor)
    assert receipt['account_deleted'] and receipt['safety_evidence_retained']
    assert receipt['archived_organizations'] == 1
    assert w.store._db.execute('SELECT active FROM organization_workspaces WHERE id=?', (ws,)).fetchone()[0] == 0
    assert w.store._db.execute('SELECT status FROM customer_organization_invitations WHERE id=?', (ticket['id'],)).fetchone()[0] == 'revoked'
    with pytest.raises(WorkspaceDenied): w.core.actor(w.auths[0]['session_token'])
    w.state['claims'] = {'sub': 'synthetic-customer-0'}
    with pytest.raises(WorkspaceDenied): login(w)
    assert w.store._db.execute('SELECT COUNT(*) FROM customer_organization_audit WHERE workspace_id=?', (ws,)).fetchone()[0] >= 3


def test_deletion_preserves_actual_signed_unknown_run_and_stops_replay(customer_run):
    source, _, identity, _, actor, executor, auth = customer_run
    store, access, _, _, proxy, ws, draft, snapshot = source
    core = CustomerOrganizations(identity, access)
    proxy.result = {'ok': False, 'error_code': 'UPSTREAM_TIMEOUT'}
    prepared = executor.prepare(ws, draft, snapshot, {'snapshot_revision': 1}, actor)
    from agent_market.workspace_execution import NOTICE
    request = {'ticket_id': prepared['ticket_id'], 'authorized': True, 'notice': NOTICE}
    run = executor.execute(ws, draft, snapshot, request, actor)
    assert run['status'] == 'unknown' and proxy.calls == 1
    before = tuple(store._db.execute('SELECT * FROM workspace_private_runs WHERE id=?', (run['id'],)).fetchone())
    core.delete_account({'revision': 1, 'confirm': 'DELETE', 'archive_owned': False}, identity.actor(auth['session_token']))
    after = tuple(store._db.execute('SELECT * FROM workspace_private_runs WHERE id=?', (run['id'],)).fetchone())
    assert before == after
    with pytest.raises(WorkspaceDenied): executor.execute(ws, draft, snapshot, request, actor)
    assert proxy.calls == 1


def test_shared_ownership_survives_account_deletion(orgs):
    w = orgs; accept(w, role='owner')
    w.orgs.delete_account({'revision': 1, 'confirm': 'DELETE', 'archive_owned': False}, w.customers[0])
    assert w.orgs.detail(w.organization['id'], w.customers[1])['can_manage']


@pytest.mark.parametrize('body', [{}, {'name': '<script>alert(1)</script>', 'owner': 1}, {'name': 'https://private.invalid'}, {'name': '/Users/private/config'}, {'name': 'x' * 121}])
def test_bounded_customer_inputs_reject_private_paths_and_extra_authority_fields(orgs, body):
    with pytest.raises(WorkspaceInvalid): orgs.orgs.create(body, orgs.customers[0])


def test_customer_namespace_does_not_claim_staff_owned_workspace_and_rename_is_cas(orgs):
    w = orgs
    with pytest.raises(WorkspaceDenied): w.orgs.detail(w.ws, w.customers[0])
    with pytest.raises(WorkspaceConflict): w.orgs.rename(w.organization['id'], {'name': 'Changed', 'revision': 99}, w.customers[0])
    result = w.orgs.rename(w.organization['id'], {'name': 'Changed', 'revision': 1}, w.customers[0])
    assert result['name'] == 'Changed' and result['revision'] == 2


def test_real_customer_routes_csrf_idor_duplicate_fields_noindex_and_admin_separation(orgs):
    w = orgs; app = FastAPI(); app.include_router(router_for(w.store, b'synthetic-customer-key-32bytes!!!', identity=w.core, admin=False))
    with TestClient(app, base_url='https://customer.test') as client:
        page = client.get('/customer/organizations')
        assert page.status_code == 200 and '<html lang="en">' in page.text
        assert 'lucide lucide-' in page.text and 'noindex' in page.headers['x-robots-tag']
        assert "frame-ancestors 'none'" in page.headers['content-security-policy']
        assert client.get('/api/customer-organizations').status_code == 401
        client.cookies.set(COOKIE, w.auths[0]['session_token'])
        csrf = w.core.csrf(w.auths[0]['session_token']); headers = {'X-Customer-CSRF': csrf}
        assert client.post('/api/customer-organizations', json={'name': 'Blocked'}).status_code == 403
        assert client.post('/api/customer-organizations', headers=headers | {'Origin': 'https://outside.invalid'}, json={'name': 'Blocked'}).status_code == 403
        assert client.post('/api/customer-organizations', headers={'X-Customer-CSRF': '0' * 65}, json={'name': 'Blocked'}).status_code == 403
        assert client.post('/api/customer-organizations', headers=headers, content='{"name":"One","name":"Two"}').status_code == 400
        current = client.get('/api/customer-organizations').json()['account']
        assert len(current['organizations']) == 1
        assert client.post('/api/customer-organizations', headers=headers, json={'name': 'API team'}).status_code == 200
        assert client.get('/admin/api/workflow-workspaces/' + w.organization['id'] + '/customers').status_code == 404
        client.cookies.set(COOKIE, w.auths[1]['session_token'])
        assert client.get('/api/customer-organizations/' + w.organization['id']).status_code == 403
        assert client.get('/api/customer-organizations/' + w.organization['id'] + '/members').status_code == 403
        assert client.get('/api/customer-organizations').headers['cache-control'] == 'no-store'
    staff_only = FastAPI(); staff_only.include_router(router_for(w.store, b'synthetic-customer-key-32bytes!!!', identity=w.core, public=False))
    assert not any(getattr(route, 'path', '').startswith('/customer/') or getattr(route, 'path', '').startswith('/api/customer-organizations') for route in staff_only.routes)


def test_stale_recipient_account_or_archived_organization_cannot_accept(orgs):
    w = orgs; ticket = invite(w)
    with w.core.tx() as db: db.execute('UPDATE customer_identities SET revision=revision+1 WHERE id=?', (w.customers[1].customer_id,))
    with pytest.raises(WorkspaceDenied): w.orgs.resolve_invitation(ticket['id'], {'decision': 'accept', 'revision': 1}, w.customers[1])
    current = w.orgs.detail(w.organization['id'], w.customers[0])
    w.orgs.archive(current['id'], {'revision': current['organization_revision'], 'confirm': 'ARCHIVE'}, w.customers[0])
    assert w.orgs.list(w.customers[0])['organizations'] == []
    with pytest.raises(WorkspaceConflict): w.orgs.resolve_invitation(ticket['id'], {'decision': 'accept', 'revision': 1}, w.customers[1])
