"""Reviewed (two-person) commands in the renewed console: kill switch release (design 4.3)."""
# ruff: noqa: F811 -- shared isolated fixtures
import time

import pytest

from agent_market.gateway import admin_auth
from agent_market.workspace_admin_events import migrate
from tests.test_dashboard import dash  # noqa: F401
from tests.test_admin_next import login

D = {'X-Dashboard': '1'}
CONTROLS = '/admin/api/v2/gateway/controls'


@pytest.fixture
def reviewed(dash):
    world, client = dash
    migrate(world.store, b'synthetic-reviewed-command-key-32')
    with world.store.tx() as db:
        # A single active superadmin unless a test adds another.
        db.execute("UPDATE admin_users SET active=0 WHERE role='superadmin' AND username!='sadmin'")
    return world, client, login(client)


def state(client, staff):
    return client.get(CONTROLS, headers=staff).json()['execution']


def stop_then_request(client, staff):
    current = state(client, staff)
    stop = {'target': 'execution', 'reason': '점검을 위한 일시 중지', 'state': {
        'invoke_enabled': False, 'workflow_enabled': current['workflow_enabled'],
        'delivery_enabled': current['delivery_enabled'], 'revision': current['revision']}}
    assert client.post(CONTROLS, json=stop, headers=staff).status_code == 200
    stopped = state(client, staff)
    release = {**stop, 'reason': '점검 완료 후 재개', 'state': {**stop['state'], 'invoke_enabled': True, 'revision': stopped['revision']}}
    response = client.post(CONTROLS, json=release, headers=staff)
    assert response.status_code == 202, response.text
    review = response.json()['review']
    assert review['status'] == 'pending' and review['expires'] - review['created'] == 15 * 60
    assert state(client, staff)['invoke_enabled'] is False  # nothing applied yet
    return review, release


def act(client, staff, review, action='approve', **body):
    return client.post(f"/admin/api/v2/reviews/{review['id']}/{action}", headers=staff,
                       json={'revision': review['revision'], 'reason': '검토 후 적용합니다', **body})


def test_sole_superadmin_applies_own_release_only_with_acknowledgment(reviewed):
    _, client, staff = reviewed
    review, release = stop_then_request(client, staff)
    assert client.post(CONTROLS, json=release, headers=staff).status_code == 409  # one open request per target
    assert act(client, staff, review).status_code == 403
    applied = act(client, staff, review, acknowledge=True)
    assert applied.status_code == 200, applied.text
    item = applied.json()['item']
    assert item['status'] == 'applied' and item['same_person_review'] and item['approved_by'] is not None
    assert state(client, staff)['invoke_enabled'] is True
    assert act(client, staff, review, acknowledge=True).status_code == 409  # no replay
    listed = client.get('/admin/api/v2/reviews', headers=staff).json()
    assert listed['items'][0]['id'] == review['id'] and listed['can_approve']
    logs = client.get('/admin/api/audit/logs?limit=20', headers=staff).json()['logs']
    actions = [row['action'] for row in logs]
    assert 'REVIEWED_REQUEST' in actions and 'REVIEWED_APPLY' in actions


def test_second_superadmin_must_review_when_one_exists(reviewed):
    world, client, staff = reviewed
    with world.store.tx() as db:
        admin_auth.create_admin_user(db, 'second-reviewer', 'Second-reviewer-password', 'Reviewer', 'superadmin')
    review, _ = stop_then_request(client, staff)
    assert act(client, staff, review, acknowledge=True).status_code == 403
    other = client.post('/admin/api/auth/login', headers=D, json={'username': 'second-reviewer', 'password': 'Second-reviewer-password'})
    reviewer = {**D, 'authorization': 'Bearer ' + other.json()['token']}
    applied = act(client, reviewer, review)
    assert applied.status_code == 200 and applied.json()['item']['status'] == 'applied'
    assert applied.json()['item']['same_person_review'] is False


def test_expired_and_drifted_requests_never_apply(reviewed, monkeypatch):
    world, client, staff = reviewed
    review, _ = stop_then_request(client, staff)
    later = time.time() + 901
    monkeypatch.setattr('agent_market.admin_risk.clock', lambda: later)
    assert client.get('/admin/api/v2/reviews', headers=staff).json()['items'][0]['status'] == 'expired'
    assert act(client, staff, review, acknowledge=True).status_code == 409
    assert state(client, staff)['invoke_enabled'] is False
    monkeypatch.undo()
    with world.store.tx() as db:  # moving the signed creation time is tampering, not expiry
        db.execute('UPDATE admin_reviewed_commands SET created=created-901 WHERE id=?', (review['id'],))
    assert client.get('/admin/api/v2/reviews', headers=staff).json()['items'][0]['status'] == 'integrity_review_required'
    # A new request is allowed after expiry; a control change in between makes it fail, not overwrite.
    current = state(client, staff)
    release = {'target': 'execution', 'reason': '다시 재개 요청', 'state': {'invoke_enabled': True,
               'workflow_enabled': current['workflow_enabled'], 'delivery_enabled': current['delivery_enabled'], 'revision': current['revision']}}
    second = client.post(CONTROLS, json=release, headers=staff).json()['review']
    stop = {**release, 'reason': '전달도 함께 중지', 'state': {**release['state'], 'invoke_enabled': False, 'delivery_enabled': False}}
    assert client.post(CONTROLS, json=stop, headers=staff).status_code == 200
    failed = act(client, staff, second, acknowledge=True)
    assert failed.status_code == 200 and failed.json()['item']['status'] == 'failed'
    assert state(client, staff)['invoke_enabled'] is False


def test_cancel_tamper_and_role_boundaries(reviewed):
    world, client, staff = reviewed
    review, _ = stop_then_request(client, staff)
    with world.store.tx() as db:
        original = db.execute('SELECT payload FROM admin_reviewed_commands WHERE id=?', (review['id'],)).fetchone()[0]
        db.execute("UPDATE admin_reviewed_commands SET payload=replace(payload,'true','false') WHERE id=?", (review['id'],))
    assert act(client, staff, review, acknowledge=True).status_code == 409  # signature no longer matches
    assert state(client, staff)['invoke_enabled'] is False
    with world.store.tx() as db:
        db.execute('UPDATE admin_reviewed_commands SET payload=? WHERE id=?', (original, review['id']))
    cancelled = act(client, staff, review, action='cancel')
    assert cancelled.status_code == 200 and cancelled.json()['item']['status'] == 'cancelled'
    with world.store.tx() as db:
        admin_auth.create_admin_user(db, 'operator-one', 'Operator-one-password', 'Operator', 'operator')
    token = client.post('/admin/api/auth/login', headers=D, json={'username': 'operator-one', 'password': 'Operator-one-password'}).json()['token']
    operator = {**D, 'authorization': 'Bearer ' + token}
    assert client.get('/admin/api/v2/reviews', headers=operator).status_code == 403
    assert act(client, operator, review).status_code == 403
    assert client.post(f"/admin/api/v2/reviews/{review['id']}/delete", headers=staff, json={'revision': 1}).status_code == 404
    assert client.post('/admin/api/v2/reviews/not-an-id/approve', headers=staff, json={'revision': 1}).status_code == 404


def test_fresh_login_is_required_for_single_approver(reviewed):
    world, client, staff = reviewed
    review, _ = stop_then_request(client, staff)
    with world.store.tx() as db:
        db.execute("UPDATE admin_sessions SET created_at=? WHERE username='sadmin'", (time.time() - 601,))
    assert act(client, staff, review, acknowledge=True).status_code == 403
