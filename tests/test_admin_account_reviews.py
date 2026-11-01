"""Isolated API security contracts for reviewed administrator identity changes."""
# ruff: noqa: F811
import json

import pytest

from agent_market.gateway import admin_auth
from tests.test_admin_reviewed_commands import reviewed, act  # noqa: F401
from tests.test_dashboard import dash  # noqa: F401

PASSWORD = 'Synthetic-account-password-123'


def request_change(client, staff, method='post', path='/admin/api/users', **body):
    return client.request(method, path, headers=staff, json={'reason': 'Synthetic staff change validation', **body})


def create(client, staff, username='review-user', role='operator'):
    response = request_change(client, staff, username=username, password=PASSWORD, role=role)
    assert response.status_code == 202, response.text
    item = response.json()['item']
    approved = act(client, staff, item, acknowledge=True)
    assert approved.status_code == 200, approved.text
    assert approved.json()['item']['status'] == 'applied', approved.text
    return json.loads(approved.json()['item']['result'])['user_id']


def test_create_requires_review_and_never_projects_credential_verifiers(reviewed):
    world, client, staff = reviewed
    res = request_change(client, staff, username='review-user', password=PASSWORD, role='operator')
    assert res.status_code == 202 and res.headers['cache-control'] == 'no-store'
    item = res.json()['item']
    assert not any(u['username'] == 'review-user' for u in client.get('/admin/api/users', headers=staff).json()['users'])
    for path in ('/admin/api/v2/reviews', '/admin/api/v2/reviews/' + item['id']):
        content = client.get(path, headers=staff).text
        assert all(secret not in content for secret in (PASSWORD, '_credentials', '_expected', 'pbkdf2_', 'salt'))
    with world.store.tx() as db:
        stored = db.execute('SELECT payload FROM admin_reviewed_commands WHERE id=?', (item['id'],)).fetchone()[0]
        assert PASSWORD not in stored and 'pbkdf2_' in stored
    assert act(client, staff, item).status_code == 403
    done = act(client, staff, item, acknowledge=True)
    assert done.json()['item']['status'] == 'applied'
    assert act(client, staff, item, acknowledge=True).status_code == 409
    login = client.post('/admin/api/auth/login', headers={'X-Dashboard': '1'}, json={'username': 'review-user', 'password': PASSWORD})
    assert login.status_code == 200


@pytest.mark.parametrize('change', [{'role': 'viewer'}, {'active': 0}, {'new_password': 'Replacement-fixture-password'}])
def test_approval_revokes_target_sessions_only_when_applied(reviewed, change):
    world, client, staff = reviewed
    uid = create(client, staff)
    token = client.post('/admin/api/auth/login', headers={'X-Dashboard': '1'}, json={'username': 'review-user', 'password': PASSWORD}).json()['token']
    target = {'X-Dashboard': '1', 'Authorization': 'Bearer ' + token}
    res = request_change(client, staff, 'put', '/admin/api/users/' + str(uid), **change)
    assert res.status_code == 202
    assert client.get('/admin/api/auth/me', headers=target).status_code == 200
    assert act(client, staff, res.json()['item'], acknowledge=True).json()['item']['status'] == 'applied'
    assert client.get('/admin/api/auth/me', headers=target).status_code == 401


def test_delete_and_duplicate_requests_are_reviewed(reviewed):
    _, client, staff = reviewed
    uid = create(client, staff)
    path = '/admin/api/users/' + str(uid)
    res = request_change(client, staff, 'delete', path)
    assert res.status_code == 202
    assert request_change(client, staff, 'put', path, role='admin').status_code == 409
    assert act(client, staff, res.json()['item'], acknowledge=True).json()['item']['status'] == 'applied'
    assert uid not in [u['id'] for u in client.get('/admin/api/users', headers=staff).json()['users']]


def test_target_password_drift_invalidates_request(reviewed):
    world, client, staff = reviewed
    uid = create(client, staff)
    item = request_change(client, staff, 'put', '/admin/api/users/' + str(uid), role='admin').json()['item']
    with world.store.tx() as db:
        admin_auth.update_admin_user(db, uid, new_password='Another-fixture-password')
    done = act(client, staff, item, acknowledge=True)
    assert done.json()['item']['status'] == 'failed'
    assert next(u for u in client.get('/admin/api/users', headers=staff).json()['users'] if u['id'] == uid)['role'] == 'operator'


def test_second_superadmin_required_and_requester_rechecked(reviewed):
    world, client, staff = reviewed
    uid = create(client, staff, 'second-owner', 'superadmin')
    item = request_change(client, staff, username='third-owner', password=PASSWORD, role='superadmin').json()['item']
    assert act(client, staff, item, acknowledge=True).status_code == 403
    token = client.post('/admin/api/auth/login', headers={'X-Dashboard': '1'}, json={'username': 'second-owner', 'password': PASSWORD}).json()['token']
    other = {'X-Dashboard': '1', 'Authorization': 'Bearer ' + token}
    with world.store.tx() as db:
        admin_auth.update_admin_user(db, item['requested_by'], active=0)
    done = act(client, other, item)
    assert done.json()['item']['status'] == 'failed'
    assert uid


@pytest.mark.parametrize('body', [None, [], {'role': []}, {'active': True}, {'active': 2}, {'name': []}, {'password_hash': 'forged'}, {'new_password': ''}, {'reason': ''}])
def test_malformed_account_updates_fail_closed(reviewed, body):
    _, client, staff = reviewed
    data = {'reason': 'Synthetic validation', **body} if isinstance(body, dict) else body
    assert client.put('/admin/api/users/1', headers=staff, content=json.dumps(data)).status_code == 400


def test_missing_store_blocks_legacy_mutations(dash):
    from tests.test_admin_next import login
    _, client = dash
    staff = login(client)
    assert request_change(client, staff, username='blocked', password=PASSWORD).status_code == 409


def test_protected_last_owner_and_readonly_role(reviewed):
    _, client, staff = reviewed
    users = client.get('/admin/api/users', headers=staff).json()['users']
    owner = next(u for u in users if u['username'] == 'sadmin')['id']
    for method, body in [('delete', {}), ('put', {'active': 0}), ('put', {'role': 'viewer'})]:
        assert request_change(client, staff, method, '/admin/api/users/' + str(owner), **body).status_code == 400
    create(client, staff, 'viewer-test', 'viewer')
    token = client.post('/admin/api/auth/login', headers={'X-Dashboard': '1'}, json={'username': 'viewer-test', 'password': PASSWORD}).json()['token']
    viewer = {'X-Dashboard': '1', 'Authorization': 'Bearer ' + token}
    assert request_change(client, viewer, username='denied', password=PASSWORD).status_code == 403
