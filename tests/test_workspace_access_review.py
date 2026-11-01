"""Independent private-workspace scope, withdrawal and native transaction checks."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import sqlite3
from threading import Barrier, RLock
import time
from types import SimpleNamespace

import pytest

from agent_market.gateway.admin_auth import ADMIN_SCHEMA
from agent_market.workspace_access import (
    SessionActor, WorkspaceAccess, WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid,
)


@pytest.fixture
def world(tmp_path):
    path = tmp_path / 'synthetic-private-workspaces.sqlite3'
    db = sqlite3.connect(path, check_same_thread=False, timeout=.1)
    db.row_factory = sqlite3.Row
    db.executescript(ADMIN_SCHEMA)
    now = time.time()
    actors = {}
    for user_id, role in ((1, 'superadmin'), (2, 'admin'), (3, 'admin'), (4, 'operator'),
                          (5, 'superadmin'), (6, 'admin'), (7, 'admin'), (8, 'admin')):
        db.execute('''INSERT INTO admin_users
            (id,username,password_hash,salt,role,name,active,created_at,updated_at)
            VALUES(?,?,?,?,?,?,1,?,?)''',
            (user_id, 'synthetic-' + str(user_id), 'synthetic-not-a-login-hash', 'synthetic',
             role, 'Synthetic fixture ' + str(user_id), now, now))
        reference = 'sha256:' + hashlib.sha256(('synthetic-session-' + str(user_id)).encode()).hexdigest()
        db.execute('''INSERT INTO admin_sessions
            (token,user_id,username,role,name,created_at,expires_at) VALUES(?,?,?,?,?,?,?)''',
            (reference, user_id, 'synthetic-' + str(user_id), role, 'Synthetic fixture', now, now+3600))
        actors[user_id] = SessionActor(user_id, reference)
    db.commit()
    store = SimpleNamespace(_db=db, _lock=RLock())
    access = WorkspaceAccess(store, b'synthetic-private-workspace-key-42')
    a = access.provision({'name': 'Workspace Alpha', 'owner_id': 2}, actors[1])['id']
    b = access.provision({'name': 'Workspace Beta', 'owner_id': 6}, actors[1])['id']
    access.set_member(a, {'user_id': 3, 'role': 'editor', 'active': True, 'revision': 0}, actors[2])
    access.set_member(a, {'user_id': 4, 'role': 'viewer', 'active': True, 'revision': 0}, actors[2])
    try:
        yield SimpleNamespace(path=path, db=db, store=store, access=access, actors=actors, a=a, b=b)
    finally:
        db.close()


def draft(world, *, workspace=None, actor=None, name='Private research draft'):
    return world.access.save_draft(workspace or world.a,
        {'name': name, 'description': 'Synthetic private content', 'definition': {'nodes': [], 'edges': []}},
        actor or world.actors[2])


def test_revoked_snapshot_body_cannot_be_recovered_from_history_list(world):
    item = draft(world)
    version = world.access.create_snapshot(world.a, item['id'], {'draft_revision': item['revision']}, world.actors[2])
    world.access.revoke_version(world.a, item['id'], version['id'], {'revision': version['revision']}, world.actors[2])
    with pytest.raises(WorkspaceDenied):
        world.access.version(world.a, item['id'], version['id'], world.actors[4])
    history = world.access.versions(world.a, item['id'], world.actors[4])
    assert len(history) == 1 and history[0]['active'] is False
    assert 'snapshot' not in history[0]


@pytest.mark.parametrize('actor_id', [1, 5, 6, 8])
def test_platform_superadmin_and_other_workspace_owners_have_no_content_override(world, actor_id):
    item = draft(world)
    actor = world.actors[actor_id]
    assert world.a not in [entry['id'] for entry in world.access.workspaces(actor)]
    for operation in (
        lambda: world.access.workspace(world.a, actor),
        lambda: world.access.drafts(world.a, actor),
        lambda: world.access.draft(world.a, item['id'], actor),
        lambda: world.access.audit(world.a, actor),
    ):
        with pytest.raises(WorkspaceDenied):
            operation()


@pytest.mark.parametrize('action', ['draft', 'snapshot', 'members', 'audit', 'update', 'revoke'])
def test_valid_objects_from_another_workspace_cannot_be_rebound_by_path(world, action):
    item = draft(world)
    version = world.access.create_snapshot(world.a, item['id'], {'draft_revision': 1}, world.actors[2])
    actor = world.actors[6]
    operations = {
        'draft': lambda: world.access.draft(world.b, item['id'], actor),
        'snapshot': lambda: world.access.version(world.b, item['id'], version['id'], actor),
        'members': lambda: world.access.members(world.a, actor),
        'audit': lambda: world.access.audit(world.a, actor),
        'update': lambda: world.access.save_draft(world.b, {**{k: item[k] for k in ('id','name','description','definition','revision')}}, actor),
        'revoke': lambda: world.access.revoke_version(world.b, item['id'], version['id'], {'revision': 1}, actor),
    }
    with pytest.raises(WorkspaceDenied):
        operations[action]()
    assert world.access.draft(world.a, item['id'], world.actors[2]) == item


def test_current_role_operator_ceiling_overrides_an_existing_editor_membership(world):
    item = draft(world, actor=world.actors[3])
    world.db.execute("UPDATE admin_users SET role='operator' WHERE id=3")
    world.db.commit()
    state = world.access.workspace(world.a, world.actors[3])
    assert not state['can_edit'] and not state['can_manage']
    assert world.access.draft(world.a, item['id'], world.actors[3]) == item
    with pytest.raises(WorkspaceDenied):
        draft(world, actor=world.actors[3])


@pytest.mark.parametrize('action', ['owner_promotion', 'membership_write', 'snapshot_revoke'])
def test_editor_cannot_escalate_or_withdraw_owner_controlled_permissions(world, action):
    item = draft(world)
    version = world.access.create_snapshot(world.a, item['id'], {'draft_revision': 1}, world.actors[2])
    actor = world.actors[3]
    operation = (lambda: world.access.revoke_version(world.a, item['id'], version['id'], {'revision': 1}, actor)) if action == 'snapshot_revoke' else lambda: world.access.set_member(
        world.a, {'user_id': 3 if action == 'owner_promotion' else 8,
                  'role': 'owner', 'active': True, 'revision': 1 if action == 'owner_promotion' else 0}, actor)
    with pytest.raises(WorkspaceDenied):
        operation()
    assert next(row for row in world.access.members(world.a, world.actors[2]) if row['user_id'] == 3)['role'] == 'editor'


@pytest.mark.parametrize('change', ['session_deleted', 'expired', 'user_deactivated', 'membership_removed'])
def test_current_identity_and_membership_withdrawal_invalidates_previously_read_draft(world, change):
    item = draft(world)
    actor = world.actors[3]
    assert world.access.draft(world.a, item['id'], actor)['id'] == item['id']
    if change == 'session_deleted':
        world.db.execute('DELETE FROM admin_sessions WHERE token=?', (actor.session_ref,))
    elif change == 'expired':
        world.db.execute('UPDATE admin_sessions SET expires_at=? WHERE token=?', (time.time()-1, actor.session_ref))
    elif change == 'user_deactivated':
        world.db.execute('UPDATE admin_users SET active=0 WHERE id=3')
    else:
        world.db.execute('UPDATE workspace_memberships SET active=0,revision=revision+1 WHERE workspace_id=? AND user_id=3', (world.a,))
    world.db.commit()
    with pytest.raises(WorkspaceDenied):
        world.access.draft(world.a, item['id'], actor)


def test_native_writer_reservation_precedes_authorization_and_draft_insert(world, monkeypatch):
    original = world.access._access
    blocked = []
    def checked(*args, **kwargs):
        result = original(*args, **kwargs)
        with sqlite3.connect(world.path, timeout=.01) as competing:
            try:
                competing.execute('DELETE FROM admin_sessions WHERE token=?', (world.actors[2].session_ref,))
            except sqlite3.OperationalError as error:
                assert 'locked' in str(error).lower()
                blocked.append(True)
            else:
                pytest.fail('A second writer changed authorization inside the accepted transaction.')
        return result
    monkeypatch.setattr(world.access, '_access', checked)
    assert draft(world)['revision'] == 1
    assert blocked == [True]
    with sqlite3.connect(world.path) as competing:
        competing.execute('DELETE FROM admin_sessions WHERE token=?', (world.actors[2].session_ref,))
    with pytest.raises(WorkspaceDenied):
        draft(world)


def test_session_disappearing_inside_accepted_bundle_rolls_back_content_and_audit(world, monkeypatch):
    original = world.access._audit
    before = world.db.execute('SELECT COUNT(*) FROM workspace_access_audit').fetchone()[0]
    def withdrawn(db, actor, *args, **kwargs):
        original(db, actor, *args, **kwargs)
        db.execute('DELETE FROM admin_sessions WHERE token=?', (actor.session_ref,))
    monkeypatch.setattr(world.access, '_audit', withdrawn)
    with pytest.raises(WorkspaceDenied):
        draft(world)
    assert world.db.execute('SELECT COUNT(*) FROM workspace_drafts').fetchone()[0] == 0
    assert world.db.execute('SELECT COUNT(*) FROM workspace_access_audit').fetchone()[0] == before
    assert world.db.execute('SELECT 1 FROM admin_sessions WHERE token=?', (world.actors[2].session_ref,)).fetchone()


def test_actual_accepted_snapshot_and_audit_sql_failure_rolls_back_whole_bundle(world, monkeypatch):
    item = draft(world)
    before = world.db.execute('SELECT COUNT(*) FROM workspace_access_audit').fetchone()[0]
    original = world.access._audit
    def accepted_then_failed(*args, **kwargs):
        original(*args, **kwargs)
        raise sqlite3.OperationalError('synthetic accepted audit failure')
    monkeypatch.setattr(world.access, '_audit', accepted_then_failed)
    with pytest.raises(WorkspaceConflict):
        world.access.create_snapshot(world.a, item['id'], {'draft_revision': 1}, world.actors[2])
    assert world.db.execute('SELECT COUNT(*) FROM workspace_versions').fetchone()[0] == 0
    assert world.db.execute('SELECT COUNT(*) FROM workspace_access_audit').fetchone()[0] == before


def test_parallel_last_owner_self_removal_keeps_one_effective_owner(world):
    world.access.set_member(world.a, {'user_id': 7, 'role': 'owner', 'active': True, 'revision': 0}, world.actors[2])
    barrier = Barrier(2)
    def remove(user_id):
        db = sqlite3.connect(world.path, timeout=1)
        db.row_factory = sqlite3.Row
        try:
            access = WorkspaceAccess(SimpleNamespace(_db=db, _lock=RLock()), b'synthetic-private-workspace-key-42')
            barrier.wait(timeout=2)
            try:
                access.set_member(world.a, {'user_id': user_id, 'role': 'owner', 'active': False, 'revision': 1}, world.actors[user_id])
                return 'committed'
            except WorkspaceConflict:
                return 'conflict'
        finally:
            db.close()
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(remove, [2, 7]))
    assert sorted(results) == ['committed', 'conflict']
    assert world.db.execute("SELECT COUNT(*) FROM workspace_memberships WHERE workspace_id=? AND active=1 AND role='owner'", (world.a,)).fetchone()[0] == 1


def test_operator_membership_does_not_count_as_an_effective_last_owner(world):
    world.access.set_member(world.a, {'user_id': 7, 'role': 'owner', 'active': True, 'revision': 0}, world.actors[2])
    world.db.execute("UPDATE admin_users SET role='operator' WHERE id=7")
    world.db.commit()
    with pytest.raises(WorkspaceConflict):
        world.access.set_member(world.a, {'user_id': 2, 'role': 'viewer', 'active': True, 'revision': 1}, world.actors[2])


def test_saved_content_is_immutable_across_edits_and_read_returns_no_authority(world):
    item = draft(world)
    version = world.access.create_snapshot(world.a, item['id'], {'draft_revision': 1}, world.actors[2])
    changed = world.access.save_draft(world.a, {**{key: item[key] for key in ('id','name','description','definition','revision')},
                                              'name': 'Updated private draft'}, world.actors[3])
    assert changed['revision'] == 2
    saved = world.access.version(world.a, item['id'], version['id'], world.actors[4])
    assert saved['snapshot']['name'] == item['name']
    assert saved['snapshot']['definition'] == {'nodes': [], 'edges': []}
    assert saved['saved_snapshot'] is True
    assert all(saved[key] is False for key in ('executable', 'deployable', 'published'))
    assert not {'signature', 'state_signature', 'key', 'principal', 'created_by'} & saved.keys()
    tables = {row[0] for row in world.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not {'agent_workflows', 'workflow_runs', 'workflow_apps', 'workflow_publication_grants'} & tables


def test_editor_cannot_archive_draft_and_withdraw_its_saved_content(world):
    item = draft(world)
    with pytest.raises(WorkspaceDenied):
        world.access.revoke_draft(world.a, item['id'], {'revision': 1}, world.actors[3])
    assert world.access.draft(world.a, item['id'], world.actors[4]) == item


def test_archived_parent_blocks_active_snapshot_content_without_rewriting_saved_bytes(world):
    item = draft(world)
    version = world.access.create_snapshot(world.a, item['id'], {'draft_revision': 1}, world.actors[2])
    before = tuple(world.db.execute('SELECT payload,payload_hash,signature FROM workspace_versions WHERE id=?', (version['id'],)).fetchone())
    world.access.revoke_draft(world.a, item['id'], {'revision': 1}, world.actors[2])
    with pytest.raises(WorkspaceDenied):
        world.access.version(world.a, item['id'], version['id'], world.actors[4])
    history = world.access.versions(world.a, item['id'], world.actors[4])
    assert len(history) == 1 and 'snapshot' not in history[0]
    assert tuple(world.db.execute('SELECT payload,payload_hash,signature FROM workspace_versions WHERE id=?', (version['id'],)).fetchone()) == before


@pytest.mark.parametrize('field,value', [('workspace_id', 'ws_'+'f'*32), ('created_by', 1), ('owner_id', 1), ('published', True)])
def test_draft_mass_assignment_cannot_create_or_move_private_scope(world, field, value):
    body = {'name': 'Private draft', 'description': '', 'definition': {'nodes': [], 'edges': []}, field: value}
    with pytest.raises(WorkspaceInvalid):
        world.access.save_draft(world.a, body, world.actors[3])
    assert world.db.execute('SELECT COUNT(*) FROM workspace_drafts').fetchone()[0] == 0
