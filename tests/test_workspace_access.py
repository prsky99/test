"""Explicit sessions and private saved drafts use synthetic SQLite only."""
import copy
import hashlib
import json
import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest
from starlette.responses import JSONResponse

import agent_market.workspace_access as workspace_module

from agent_market.gateway.admin_auth import ADMIN_SCHEMA
from agent_market.workspace_access import (
    LIMITS, PROFILE, SessionActor, WorkspaceAccess, WorkspaceConflict,
    WorkspaceDenied, WorkspaceInvalid,
)


def workspace_world(path=':memory:'):
    db = sqlite3.connect(path, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(ADMIN_SCHEMA)
    db.execute('''CREATE TABLE resources(id INTEGER PRIMARY KEY,kind TEXT,active INTEGER,
        name TEXT,url TEXT,usage_tools TEXT)''')
    actors = {}
    with db:
        for uid, role in ((1, 'superadmin'), (2, 'admin'), (3, 'operator'), (4, 'admin'), (5, 'superadmin')):
            ref = 'sha256:' + hashlib.sha256(('synthetic-session-' + str(uid)).encode()).hexdigest()
            db.execute('INSERT INTO admin_users VALUES(?,?,?,?,?,?,1,?,?,NULL)',
                       (uid, 'synthetic-' + str(uid), 'unused-fixture-hash', 'synthetic-salt', role,
                        'Synthetic member', time.time(), time.time()))
            db.execute('INSERT INTO admin_sessions VALUES(?,?,?,?,?,?,?,?,?)',
                       (ref, uid, 'synthetic-' + str(uid), role, 'Synthetic member', time.time(),
                        time.time() + 3600, None, None))
            actors[uid] = SessionActor(uid, ref)
        spec = {'name': 'search_news', 'description': 'Search public news',
                'inputSchema': {'type': 'object', 'properties': {'query': {'type': 'string'}},
                                'required': ['query'], 'additionalProperties': False},
                'annotations': {'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True}}
        db.execute('INSERT INTO resources VALUES(1,?,1,?,?,?)',
                   ('mcp', 'Synthetic news', 'https://synthetic.invalid/mcp', json.dumps([spec])))
        db.execute('INSERT INTO resources VALUES(2,?,1,?,?,?)',
                   ('a2a', 'Synthetic card', 'https://synthetic.invalid/a2a', None))
        db.execute('INSERT INTO resources VALUES(3,?,1,?,?,?)',
                   ('x402', 'Synthetic probe', 'https://synthetic.invalid/probe', None))
    store = SimpleNamespace(_db=db, _lock=threading.RLock())
    return store, WorkspaceAccess(store, b'synthetic-workspace-key-32-bytes!!'), actors


@pytest.fixture
def world():
    result = workspace_world()
    try:
        yield result
    finally:
        result[0]._db.close()


def provision(world, owner=1):
    _, access, actors = world
    return access.provision({'name': 'Synthetic private workspace', 'owner_id': owner}, actors[1])


def member(world, ws, uid, role='viewer', active=True, revision=0):
    _, access, actors = world
    return access.set_member(ws, {'user_id': uid, 'role': role, 'active': active, 'revision': revision}, actors[1])


def definition(kind='mcp'):
    rid = {'mcp': 1, 'a2a': 2, 'x402': 3}[kind]
    data = {'mcp': {'tool': 'search_news', 'input': {'query': 'Storage research'}},
            'a2a': {'message': 'Describe public documentation'}, 'x402': {'action': 'probe'}}[kind]
    return {'nodes': [{'id': 'start', 'name': 'Manual start', 'type': 'trigger', 'kind': 'trigger', 'data': {}},
                      {'id': 'search', 'name': 'Public reference', 'type': 'agent', 'kind': kind,
                       'resource_id': rid, 'data': data}], 'edges': [{'source': 'start', 'target': 'search'}]}


def draft_body(graph=None):
    return {'name': 'Private research draft', 'description': 'Saved for a small named team',
            'definition': {'nodes': [], 'edges': []} if graph is None else graph}


def test_named_current_sessions_and_explicit_membership_are_separate_from_global_superadmin(world):
    _, access, actors = world
    workspace = provision(world, owner=2)
    assert workspace['role'] is None and not workspace['can_manage']
    assert access.workspaces(actors[1]) == []
    with pytest.raises(WorkspaceDenied):
        access.workspace(workspace['id'], actors[1])
    actual = access.workspace(workspace['id'], actors[2])
    assert actual['role'] == 'owner' and actual['can_manage']
    assert access.options(actors[1])['profile'] == PROFILE
    assert access.options(actors[3])['user']['role'] == 'operator'
    assert 'synthetic-session' not in repr(actors[1])


@pytest.mark.parametrize('actor', [1, '1', None, {}, SessionActor(1, 'raw-token'),
    SessionActor(True, 'sha256:' + '1' * 64), SessionActor(99, 'sha256:' + '2' * 64)])
def test_no_bare_id_or_implied_system_loopback_visitor_or_capability_identity(world, actor):
    with pytest.raises(WorkspaceDenied):
        world[1].options(actor)


@pytest.mark.parametrize('kind', ['mcp', 'a2a', 'x402'])
def test_offline_registered_literal_definitions_are_saved_but_never_callable(world, kind):
    store, access, actors = world
    ws = provision(world)['id']
    draft = access.save_draft(ws, draft_body(definition(kind)), actors[1])
    version = access.create_snapshot(ws, draft['id'], {'draft_revision': draft['revision']}, actors[1])
    assert version['snapshot']['definition'] == definition(kind)
    assert version['saved_snapshot'] and not version['executable'] and not version['deployable'] and not version['published']
    assert not store._db.execute("SELECT name FROM sqlite_schema WHERE name='agent_workflows'").fetchall()
    assert not store._db.execute("SELECT name FROM sqlite_schema WHERE name='workflow_runs'").fetchall()
    assert 'https://' not in json.dumps(version)


def test_draft_cas_preserves_immutable_snapshot_and_version_history_is_metadata_only(world):
    _, access, actors = world
    ws = provision(world)['id']
    original = access.save_draft(ws, draft_body(), actors[1])
    version = access.create_snapshot(ws, original['id'], {'draft_revision': 1}, actors[1])
    updated = access.save_draft(ws, draft_body() | {'id': original['id'], 'revision': 1, 'name': 'Edited private draft'}, actors[1])
    assert updated['revision'] == 2
    assert access.version(ws, original['id'], version['id'], actors[1])['snapshot']['name'] == original['name']
    with pytest.raises(WorkspaceConflict):
        access.save_draft(ws, draft_body() | {'id': original['id'], 'revision': 1}, actors[1])
    listed = access.versions(ws, original['id'], actors[1])
    assert len(listed) == 1 and listed[0]['id'] == version['id'] and 'snapshot' not in listed[0]


def test_membership_tombstone_revision_survives_remove_readd_and_operator_ceiling(world):
    _, access, actors = world
    ws = provision(world)['id']
    first = member(world, ws, 2, 'editor')
    draft = access.save_draft(ws, draft_body(), actors[2])
    removed = member(world, ws, 2, 'editor', False, first['revision'])
    with pytest.raises(WorkspaceDenied):
        access.draft(ws, draft['id'], actors[2])
    added = member(world, ws, 2, 'editor', True, removed['revision'])
    assert added['revision'] == 3
    with pytest.raises(WorkspaceConflict):
        member(world, ws, 2, 'viewer', False, first['revision'])
    assert access.draft(ws, draft['id'], actors[2])['id'] == draft['id']
    member(world, ws, 3, 'editor')
    assert access.workspace(ws, actors[3])['can_edit'] is False
    assert access.draft(ws, draft['id'], actors[3])['id'] == draft['id']
    with pytest.raises(WorkspaceDenied):
        access.save_draft(ws, draft_body(), actors[3])


def test_last_usable_owner_cannot_be_removed_even_with_nominal_operator_owner(world):
    store, access, actors = world
    ws = provision(world)['id']
    member(world, ws, 2, 'owner')
    with store._db:
        store._db.execute("UPDATE admin_users SET role='operator' WHERE id=2")
    with pytest.raises(WorkspaceConflict):
        member(world, ws, 1, 'editor', revision=1)
    with pytest.raises(WorkspaceInvalid):
        member(world, ws, 3, 'owner')


@pytest.mark.parametrize('state', ['inactive_user', 'expired', 'missing_session', 'infinite_expiry', 'global_demotion'])
def test_current_account_and_session_changes_apply_to_each_operation(world, state):
    store, access, actors = world
    ws = provision(world)['id']
    draft = access.save_draft(ws, draft_body(), actors[1])
    with store._db:
        if state == 'inactive_user':
            store._db.execute('UPDATE admin_users SET active=0 WHERE id=1')
        elif state == 'expired':
            store._db.execute('UPDATE admin_sessions SET expires_at=0 WHERE user_id=1')
        elif state == 'missing_session':
            store._db.execute('DELETE FROM admin_sessions WHERE user_id=1')
        elif state == 'infinite_expiry':
            store._db.execute('UPDATE admin_sessions SET expires_at=? WHERE user_id=1', (float('inf'),))
        else:
            store._db.execute("UPDATE admin_users SET role='operator' WHERE id=1")
    if state == 'global_demotion':
        assert not access.workspace(ws, actors[1])['can_manage']
        with pytest.raises(WorkspaceDenied):
            access.save_draft(ws, draft_body(), actors[1])
    else:
        with pytest.raises(WorkspaceDenied):
            access.draft(ws, draft['id'], actors[1])


@pytest.mark.parametrize('value', ['token=synthetic-secret', '{"password":"synthetic-secret"}',
    'https://synthetic.invalid', 'https%253A%252F%252Fsynthetic.invalid', '/Users/synthetic/private',
    'Bearer synthetic-secret', '{{ $prev.output }}', 'bad\nname'])
def test_known_sensitive_or_dynamic_values_are_rejected_without_silent_rewrite(world, value):
    store, access, actors = world
    ws = provision(world)['id']
    with pytest.raises(WorkspaceInvalid):
        access.save_draft(ws, draft_body() | {'description': value}, actors[1])
    assert store._db.execute('SELECT COUNT(*) FROM workspace_drafts').fetchone()[0] == 0


@pytest.mark.parametrize('mutation', ['unregistered', 'wrong_kind', 'unsafe_tool', 'credential_refs',
    'composition', 'url', 'dynamic', 'cycle', 'disconnected', 'router', 'too_many', 'extra_edge'])
def test_definition_is_exact_bounded_registered_literal_and_never_a_runtime_import(world, mutation):
    _, access, actors = world
    ws = provision(world)['id']
    graph = definition()
    target = graph['nodes'][1]
    if mutation == 'unregistered': target['resource_id'] = 999
    elif mutation == 'wrong_kind': target['kind'] = 'a2a'
    elif mutation == 'unsafe_tool': target['data']['tool'] = 'delete_records'
    elif mutation in ('credential_refs', 'composition', 'url'): target['data'][mutation] = 'synthetic-private'
    elif mutation == 'dynamic': target['data']['input']['query'] = '{{ $prev.output }}'
    elif mutation == 'cycle': graph['edges'].append({'source': 'search', 'target': 'start'})
    elif mutation == 'disconnected': graph['edges'] = []
    elif mutation == 'router': target['type'] = 'router'
    elif mutation == 'too_many': graph['nodes'] *= 4
    else: graph['edges'][0]['condition'] = True
    with pytest.raises(WorkspaceInvalid):
        access.save_draft(ws, draft_body(graph), actors[1])


def test_owner_only_version_withdrawal_and_one_way_workspace_archive(world):
    _, access, actors = world
    ws = provision(world)['id']
    member(world, ws, 2, 'editor')
    draft = access.save_draft(ws, draft_body(), actors[2])
    version = access.create_snapshot(ws, draft['id'], {'draft_revision': 1}, actors[2])
    with pytest.raises(WorkspaceDenied):
        access.revoke_version(ws, draft['id'], version['id'], {'revision': 1}, actors[2])
    access.revoke_version(ws, draft['id'], version['id'], {'revision': 1}, actors[1])
    with pytest.raises(WorkspaceDenied):
        access.version(ws, draft['id'], version['id'], actors[2])
    revision = access.workspace(ws, actors[1])['revision']
    access.set_active(ws, {'active': False, 'revision': revision}, actors[1])
    assert access.workspaces(actors[1]) == []
    with pytest.raises(WorkspaceDenied):
        access.draft(ws, draft['id'], actors[1])
    with pytest.raises(WorkspaceInvalid):
        access.set_active(ws, {'active': True, 'revision': revision + 1}, actors[1])


def test_editor_cannot_archive_draft_while_owner_can(world):
    _, access, actors = world
    ws = provision(world)['id']
    member(world, ws, 2, 'editor')
    draft = access.save_draft(ws, draft_body(), actors[2])
    assert access.create_snapshot(ws, draft['id'], {'draft_revision': 1}, actors[2])['saved_snapshot']
    with pytest.raises(WorkspaceDenied):
        access.revoke_draft(ws, draft['id'], {'revision': 1}, actors[2])
    access.revoke_draft(ws, draft['id'], {'revision': 1}, actors[1])


def test_archived_parent_blocks_saved_content_but_retains_metadata_and_signed_bytes(world):
    store, access, actors = world
    ws = provision(world)['id']
    draft = access.save_draft(ws, draft_body(), actors[1])
    version = access.create_snapshot(ws, draft['id'], {'draft_revision': 1}, actors[1])
    before = tuple(store._db.execute('SELECT payload,payload_hash,signature FROM workspace_versions WHERE id=?', (version['id'],)).fetchone())
    access.revoke_draft(ws, draft['id'], {'revision': 1}, actors[1])
    with pytest.raises(WorkspaceDenied):
        access.version(ws, draft['id'], version['id'], actors[1])
    history = access.versions(ws, draft['id'], actors[1])
    assert history[0]['id'] == version['id'] and 'snapshot' not in history[0]
    assert tuple(store._db.execute('SELECT payload,payload_hash,signature FROM workspace_versions WHERE id=?', (version['id'],)).fetchone()) == before


@pytest.mark.parametrize('target', ['draft', 'snapshot', 'snapshot_state'])
def test_private_hash_and_hmac_tamper_is_refused_without_mutating_history(world, target):
    store, access, actors = world
    ws = provision(world)['id']
    draft = access.save_draft(ws, draft_body(), actors[1])
    version = access.create_snapshot(ws, draft['id'], {'draft_revision': 1}, actors[1])
    with store._db:
        if target == 'draft': store._db.execute("UPDATE workspace_drafts SET name='Tampered' WHERE id=?", (draft['id'],))
        elif target == 'snapshot': store._db.execute("UPDATE workspace_versions SET payload_hash=? WHERE id=?", ('a' * 64, version['id']))
        else: store._db.execute('UPDATE workspace_versions SET revision=revision+1 WHERE id=?', (version['id'],))
    with pytest.raises(WorkspaceConflict):
        (access.draft(ws, draft['id'], actors[1]) if target == 'draft'
         else access.version(ws, draft['id'], version['id'], actors[1]))


def test_core_refuses_caller_transaction_without_committing_unrelated_data(world):
    store, access, actors = world
    store._db.execute("UPDATE admin_users SET name='Uncommitted private fixture' WHERE id=1")
    with pytest.raises(WorkspaceConflict):
        access.options(actors[1])
    assert store._db.in_transaction
    store._db.rollback()
    assert store._db.execute('SELECT name FROM admin_users WHERE id=1').fetchone()[0] == 'Synthetic member'


def test_audit_contains_fixed_actions_and_references_but_no_session_or_snapshot_body(world):
    _, access, actors = world
    ws = provision(world)['id']
    draft = access.save_draft(ws, draft_body(), actors[1])
    access.create_snapshot(ws, draft['id'], {'draft_revision': 1}, actors[1])
    records = access.audit(ws, actors[1])
    assert {r['action'] for r in records} == {'workspace.provision', 'draft.save', 'snapshot.create'}
    encoded = json.dumps(records)
    assert 'sha256:' not in encoded and 'definition' not in encoded and 'Saved for' not in encoded
    assert len(records) <= LIMITS['audit']


def test_fresh_draft_id_collision_cannot_overwrite_another_workspace(world, monkeypatch):
    _, access, actors = world
    first = provision(world)['id']
    second = provision(world, owner=2)['id']
    original = access.save_draft(first, draft_body(), actors[1])
    monkeypatch.setattr(workspace_module.secrets, 'token_hex', lambda _size: original['id'][3:])
    with pytest.raises(WorkspaceConflict):
        access.save_draft(second, draft_body() | {'name': 'Different workspace draft'}, actors[2])
    assert access.draft(first, original['id'], actors[1]) == original
    assert access.drafts(second, actors[2]) == []


def test_lifetime_quotas_do_not_reuse_archived_slots_or_break_existing_saved_content(world):
    _, access, actors = world
    ws = provision(world)['id']
    for _ in range(99):
        provision(world)
    with pytest.raises(WorkspaceConflict):
        provision(world)
    first = access.save_draft(ws, draft_body(), actors[1])
    last = first
    for _ in range(99):
        last = access.save_draft(ws, draft_body(), actors[1])
    access.revoke_draft(ws, last['id'], {'revision': last['revision']}, actors[1])
    with pytest.raises(WorkspaceConflict):
        access.save_draft(ws, draft_body(), actors[1])
    snapshots = [access.create_snapshot(ws, first['id'], {'draft_revision': 1}, actors[1]) for _ in range(50)]
    access.revoke_version(ws, first['id'], snapshots[-1]['id'], {'revision': 1}, actors[1])
    with pytest.raises(WorkspaceConflict):
        access.create_snapshot(ws, first['id'], {'draft_revision': 1}, actors[1])
    assert access.version(ws, first['id'], snapshots[0]['id'], actors[1]) == snapshots[0]
    assert len(access.versions(ws, first['id'], actors[1])) == 50


@pytest.mark.parametrize('surface', ['workspace_name', 'draft_name', 'literal_key', 'literal_string'])
def test_invalid_surrogates_are_refused_before_a_response_or_private_write(world, surface):
    store, access, actors = world
    ws = provision(world)['id']
    before = tuple(store._db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                   for table in ('organization_workspaces', 'workspace_drafts', 'workspace_versions', 'workspace_access_audit'))
    body = draft_body()
    if surface == 'draft_name': body['name'] = '\ud800'
    elif surface in ('literal_key', 'literal_string'):
        body['definition'] = definition('mcp')
        if surface == 'literal_key':
            body['definition']['nodes'][1]['data']['input']['\udc00'] = 'Synthetic value'
        else:
            body['definition']['nodes'][1]['data']['input']['query'] = '\udc00'
    with pytest.raises(WorkspaceInvalid):
        result = (access.provision({'name': '\ud800', 'owner_id': 1}, actors[1]) if surface == 'workspace_name'
                  else access.save_draft(ws, body, actors[1]))
        JSONResponse(result)
    after = tuple(store._db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                  for table in ('organization_workspaces', 'workspace_drafts', 'workspace_versions', 'workspace_access_audit'))
    assert after == before


def test_valid_supplementary_unicode_survives_json_response_and_saved_snapshot(world):
    _, access, actors = world
    value = json.loads('"Supplementary \\ud83d\\ude42"')
    assert '\U0001f642' in value
    ws = access.provision({'name': value, 'owner_id': 1}, actors[1])['id']
    draft = access.save_draft(ws, draft_body() | {'name': value, 'description': value}, actors[1])
    version = access.create_snapshot(ws, draft['id'], {'draft_revision': 1}, actors[1])
    assert json.loads(JSONResponse(version).body)['snapshot']['name'] == value
