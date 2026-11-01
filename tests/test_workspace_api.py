"""Private object transport and restore regressions use isolated stores only."""
import hashlib
import json
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.gateway import admin_auth
from agent_market.gateway.dashboard import dashboard_router
from agent_market.gateway.store import Store
from agent_market.workspace_service import BASE

pytestmark = pytest.mark.usefixtures('rotated_bootstrap_admin')


@pytest.fixture
def workspace_api(tmp_path):
    store = Store(str(tmp_path / 'workspace.sqlite3'))
    system_token = 'e' * 64
    users = {'owner': 1}
    headers = {}
    with store.tx() as db:
        for name, role in (('editor', 'admin'), ('viewer', 'operator'), ('outsider', 'admin')):
            user = admin_auth.create_admin_user(db, name, 'isolated-workspace-password', name, role)
            users[name] = user['id']
        for name, identity in users.items():
            row = db.execute('SELECT username,role,name FROM admin_users WHERE id=?', (identity,)).fetchone()
            token = admin_auth.create_session(db, identity, row['username'], row['role'], row['name'])
            headers[name] = {'X-Dashboard': '1', 'Authorization': 'Bearer ' + token}
    app = FastAPI()
    app.include_router(dashboard_router(store, store._path, system_token, None, ssl_manager=Mock()))
    with TestClient(app, raise_server_exceptions=False) as client:
        yield store, client, headers, users, tmp_path, system_token
    store._db.close()


def create_space(api, owner='owner', name='Private planning'):
    _, client, headers, users, *_ = api
    response = client.post(BASE, headers=headers['owner'], json={'name': name, 'owner_id': users[owner]})
    assert response.status_code == 200, response.text
    return response.json()['workspace']


def draft(api, workspace, name='Draft <untrusted>'):
    response = api[1].post(f'{BASE}/{workspace}/drafts', headers=api[2]['owner'],
                          json={'name': name, 'description': 'Private review only', 'definition': {'nodes': [], 'edges': []}})
    assert response.status_code == 200, response.text
    return response.json()['draft']


def snapshot(api, workspace, saved):
    response = api[1].post(f'{BASE}/{workspace}/drafts/{saved["id"]}/snapshots', headers=api[2]['owner'],
                          json={'draft_revision': saved['revision']})
    assert response.status_code == 200, response.text
    return response.json()['snapshot']


def add_member(api, workspace, person, role):
    response = api[1].post(f'{BASE}/{workspace}/members', headers=api[2]['owner'],
                          json={'user_id': api[3][person], 'role': role, 'active': True, 'revision': 0})
    assert response.status_code == 200, response.text
    return response.json()['member']


@pytest.mark.parametrize('credential', ['missing', 'system', 'visitor', 'query', 'cookie'])
def test_only_a_real_individual_database_session_authenticates(workspace_api, credential):
    _, client, headers, _, _, system_token = workspace_api
    options = {}
    if credential == 'system': options['headers'] = {'X-Dashboard': '1', 'Authorization': 'Bearer ' + system_token}
    elif credential == 'visitor': options['headers'] = {'X-Dashboard': '1', 'Authorization': 'Bearer visitor-token'}
    elif credential == 'query': options['params'] = {'token': headers['owner']['Authorization'][7:]}
    elif credential == 'cookie': client.cookies.set('token', headers['owner']['Authorization'][7:])
    response = client.get(BASE, **options)
    assert response.status_code == 401
    assert response.headers['cache-control'] == 'no-store'


def test_authenticated_nonmember_cannot_read_metadata_content_or_artifacts(workspace_api):
    _, client, headers, *_ = workspace_api
    workspace = create_space(workspace_api)['id']; saved = draft(workspace_api, workspace); version = snapshot(workspace_api, workspace, saved)
    root = f'{BASE}/{workspace}'
    paths = [root, root+'/members', root+'/drafts', root+'/audit', root+f'/drafts/{saved["id"]}',
             root+f'/drafts/{saved["id"]}/snapshots', root+f'/drafts/{saved["id"]}/snapshots/{version["id"]}',
             root+f'/drafts/{saved["id"]}/snapshots/{version["id"]}/artifact']
    for path in paths:
        response = client.get(path, headers=headers['outsider'])
        assert response.status_code == 404 and response.headers['cache-control'] == 'no-store'
        assert saved['name'] not in response.text
    assert client.get(BASE, headers=headers['outsider']).json()['workspaces'] == []


def test_superadmin_provisioning_does_not_create_implicit_content_membership(workspace_api):
    _, client, headers, *_ = workspace_api
    workspace = create_space(workspace_api, owner='outsider')['id']
    assert client.get(BASE, headers=headers['owner']).json()['workspaces'] == []
    assert client.get(f'{BASE}/{workspace}/drafts', headers=headers['owner']).status_code == 404
    assert client.get(f'{BASE}/{workspace}', headers=headers['outsider']).status_code == 200


def test_editor_viewer_and_operator_ceiling_are_enforced(workspace_api):
    _, client, headers, *_ = workspace_api
    workspace = create_space(workspace_api)['id']; add_member(workspace_api, workspace, 'editor', 'editor'); add_member(workspace_api, workspace, 'viewer', 'viewer')
    payload = {'name': 'Private empty graph', 'description': '', 'definition': {'nodes': [], 'edges': []}}
    response = client.post(f'{BASE}/{workspace}/drafts', headers=headers['editor'], json=payload)
    assert response.status_code == 200
    for path, body in [(f'{BASE}/{workspace}/drafts', payload), (f'{BASE}/{workspace}/members', {'user_id': 1, 'role': 'owner', 'active': True, 'revision': 1})]:
        assert client.post(path, headers=headers['viewer'], json=body).status_code == 404
    assert client.get(f'{BASE}/{workspace}/drafts', headers=headers['viewer']).status_code == 200
    assert client.get(f'{BASE}/{workspace}/members', headers=headers['editor']).status_code == 404


def test_snapshot_artifact_is_immutable_authorized_and_not_an_executable_package(workspace_api):
    store, client, headers, *_ = workspace_api
    before = store.query('SELECT COUNT(*) FROM agent_workflows')[0][0]
    workspace = create_space(workspace_api)['id']; saved = draft(workspace_api, workspace); version = snapshot(workspace_api, workspace, saved)
    path = f'{BASE}/{workspace}/drafts/{saved["id"]}/snapshots/{version["id"]}'
    response = client.get(path+'/artifact', headers=headers['owner'])
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    assert response.headers['content-type'].startswith('application/json')
    assert response.headers['content-disposition'] == f'attachment; filename="private-snapshot-{version["id"]}.json"'
    result = response.json()
    assert result['snapshot']['name'] == saved['name'] and result['saved_snapshot']
    assert not any(result[key] for key in ('executable', 'deployable', 'published'))
    assert not {'signature', 'session_ref', 'token', 'run_key', 'publish_key'} & set(result)
    payload = {key: saved[key] for key in ('id', 'name', 'description', 'definition', 'revision')}; payload['name'] = 'Later draft'
    assert client.post(f'{BASE}/{workspace}/drafts', headers=headers['owner'], json=payload).status_code == 200
    assert client.get(path, headers=headers['owner']).json()['snapshot']['snapshot']['name'] == saved['name']
    assert store.query('SELECT COUNT(*) FROM agent_workflows')[0][0] == before
    assert store.query('SELECT COUNT(*) FROM workflow_runs')[0][0] == 0
    for suffix in ('run', 'export', 'webapp'):
        assert client.post(f'{BASE}/{workspace}/drafts/{saved["id"]}/{suffix}', headers=headers['owner'], json={}).status_code in (404, 405)


def test_nested_workspace_draft_and_snapshot_ids_cannot_be_mixed(workspace_api):
    _, client, headers, *_ = workspace_api
    first = create_space(workspace_api, name='First')['id']; second = create_space(workspace_api, name='Second')['id']
    saved = draft(workspace_api, first); other = draft(workspace_api, second); version = snapshot(workspace_api, first, saved)
    for path in (f'{BASE}/{second}/drafts/{saved["id"]}',
                 f'{BASE}/{second}/drafts/{other["id"]}/snapshots/{version["id"]}',
                 f'{BASE}/{first}/drafts/{other["id"]}/snapshots/{version["id"]}/artifact'):
        assert client.get(path, headers=headers['owner']).status_code == 404


@pytest.mark.parametrize('headers', [{'Origin': 'null'}, {'Origin': 'https://outside.invalid'}, {'Sec-Fetch-Site': 'cross-site'}])
def test_cross_origin_reads_and_writes_are_denied_without_cached_private_data(workspace_api, headers):
    _, client, auth, *_ = workspace_api
    for method in ('GET', 'POST'):
        response = client.request(method, BASE, headers={**auth['owner'], **headers})
        assert response.status_code == 403 and response.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('raw', ['[]', 'null', '{"name":"x","name":"y","owner_id":1}',
    '{"name":"x","owner_id":NaN}', '{"name":"x","owner_id":1e999}', 'x'*65537,
    r'{"name":"\ud800","owner_id":1}', r'{"name":"\udfff","owner_id":1}'])
def test_strict_raw_json_bounds_and_duplicate_rejection(workspace_api, raw):
    store, client, headers, *_ = workspace_api
    before = store.query('SELECT COUNT(*) FROM organization_workspaces')[0][0]
    response = client.post(BASE, headers=headers['owner'], content=raw)
    assert response.status_code == 400 and response.headers['cache-control'] == 'no-store'
    assert store.query('SELECT COUNT(*) FROM organization_workspaces')[0][0] == before


def test_stale_revision_and_mass_assignment_leave_private_draft_unchanged(workspace_api):
    _, client, headers, *_ = workspace_api
    workspace = create_space(workspace_api)['id']; saved = draft(workspace_api, workspace)
    payload = {key: saved[key] for key in ('id', 'name', 'description', 'definition', 'revision')}
    response = client.post(f'{BASE}/{workspace}/drafts', headers=headers['owner'], json=payload)
    assert response.status_code == 200
    assert client.post(f'{BASE}/{workspace}/drafts', headers=headers['owner'], json=payload).status_code == 409
    payload['revision'] = response.json()['draft']['revision']; payload['workspace_id'] = 'ws_'+'f'*32
    assert client.post(f'{BASE}/{workspace}/drafts', headers=headers['owner'], json=payload).status_code == 400


def test_snapshot_revocation_does_not_leave_content_in_history(workspace_api):
    _, client, headers, *_ = workspace_api
    workspace = create_space(workspace_api)['id']; saved = draft(workspace_api, workspace)
    version = snapshot(workspace_api, workspace, saved)
    path = f'{BASE}/{workspace}/drafts/{saved["id"]}/snapshots'
    assert client.post(path+f'/{version["id"]}/revoke', headers=headers['owner'], json={'revision': version['revision']}).status_code == 200
    history = client.get(path, headers=headers['owner']).json()['snapshots']
    assert len(history) == 1 and not history[0]['active'] and 'snapshot' not in history[0]
    assert saved['name'] not in json.dumps(history)
    assert client.get(path+f'/{version["id"]}/artifact', headers=headers['owner']).status_code == 404


def test_only_owner_can_archive_draft_and_parent_archive_blocks_child_artifact(workspace_api):
    _, client, headers, *_ = workspace_api
    workspace = create_space(workspace_api)['id']; add_member(workspace_api, workspace, 'editor', 'editor')
    saved = draft(workspace_api, workspace); version = snapshot(workspace_api, workspace, saved)
    root = f'{BASE}/{workspace}/drafts/{saved["id"]}'
    assert client.post(root+'/archive', headers=headers['editor'], json={'revision': saved['revision']}).status_code == 404
    assert client.post(root+'/archive', headers=headers['owner'], json={'revision': saved['revision']}).status_code == 200
    for suffix in (f'/snapshots/{version["id"]}', f'/snapshots/{version["id"]}/artifact'):
        assert client.get(root+suffix, headers=headers['owner']).status_code == 404


@pytest.mark.parametrize('change', ['logout', 'expiry', 'inactive', 'operator'])
def test_session_and_account_changes_take_effect_on_the_next_request(workspace_api, change):
    store, client, headers, *_ = workspace_api
    workspace = create_space(workspace_api)['id']; saved = draft(workspace_api, workspace)
    token = headers['owner']['Authorization'][7:]
    with store.tx() as db:
        if change == 'logout': admin_auth.delete_session(db, token)
        elif change == 'expiry': db.execute('UPDATE admin_sessions SET expires_at=0 WHERE token=?', (admin_auth.session_reference(token),))
        elif change == 'inactive': db.execute('UPDATE admin_users SET active=0 WHERE id=1')
        else: db.execute("UPDATE admin_users SET role='operator' WHERE id=1")
    path = f'{BASE}/{workspace}/drafts/{saved["id"]}'
    if change == 'operator':
        assert client.get(path, headers=headers['owner']).status_code == 200
        assert client.post(f'{BASE}/{workspace}/drafts/{saved["id"]}/snapshots', headers=headers['owner'], json={'draft_revision': saved['revision']}).status_code == 404
    else: assert client.get(path, headers=headers['owner']).status_code == 401


def test_admin_asset_gets_the_existing_nonce_policy_and_contains_no_private_bootstrap(workspace_api):
    _, client, headers, *_ = workspace_api
    response = client.get('/admin/ui')
    import re
    nonce = re.search(r"script-src 'nonce-([^']+)'", response.headers['content-security-policy'])[1]
    assert f'<script nonce="{nonce}" src="/admin/assets/workspace-admin.js"></script>' in response.text
    asset = client.get('/admin/assets/workspace-admin.js')
    assert asset.status_code == 200 and asset.headers['cache-control'] == 'no-store'
    assert headers['owner']['Authorization'][7:] not in asset.text
    assert 'script-src-attr \'none\'' in response.headers['content-security-policy']


def test_restoration_pauses_private_memberships_before_a_new_login(workspace_api):
    from agent_market.workflow_backup import backup, restore
    from agent_market.workflows import runtime_for
    from agent_market.workspace_access import WorkspaceAccess, WorkspaceDenied, SessionActor
    store, _, _, _, directory, _ = workspace_api
    workspace = create_space(workspace_api)['id']; saved = draft(workspace_api, workspace)
    snapshot(workspace_api, workspace, saved)
    key = runtime_for(store).key
    backup(store._path, directory / 'backup')
    restored_path = directory / 'restored.sqlite3'
    restore(directory / 'backup', restored_path)
    restored = Store(str(restored_path))
    try:
        core = WorkspaceAccess(restored, key)
        assert restored.query('SELECT COUNT(*) FROM organization_workspaces WHERE active=1')[0][0] == 0
        assert restored.query('SELECT COUNT(*) FROM workspace_memberships WHERE active=1')[0][0] == 0
        with restored.tx() as db:
            token = admin_auth.create_session(db, 1, 'sadmin', 'superadmin', 'Administrator')
        actor = SessionActor(1, admin_auth.session_reference(token))
        assert core.workspaces(actor) == []
        with pytest.raises(WorkspaceDenied): core.draft(workspace, saved['id'], actor)
        inventory = json.loads(Path(str(restored_path)+'.restored-inventory.json').read_text())
        item = inventory['items']['organization_workspaces']
        assert item['count'] == 1 and item['records'][0]['id'] == workspace
        assert set(item['records'][0]) == {'id', 'revision', 'active'}
        assert not inventory['automatic_reactivation']
    finally:
        restored._db.close()
