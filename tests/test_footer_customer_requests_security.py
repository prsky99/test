"""Withdrawal evidence, permission fences and search use isolated databases."""
import json
import sqlite3
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.gateway.dashboard import dashboard_router
from tests.test_task_updates_security import updates  # noqa: F401
from tests.test_fast_single_recommendation import catalog, ask  # noqa: F401
from tests.test_customer_requests_hub import env, H  # noqa: F401
from tests.conftest import staff_session


@pytest.mark.parametrize('action', ['stop','delete','capability'])
@pytest.mark.parametrize('channel', ['poll','webhook'])
def test_task_withdrawal_is_minimal_idempotent_and_cannot_be_reactivated(updates, tmp_path, action, channel):
    store, front, client, _, headers, courier, data, visitor_id = updates
    body = {**data, 'channel':channel}
    destination = 'https://inbox.example/private-synthetic-destination'
    if channel == 'webhook':
        body['url'] = destination
    row = client.post('/api/task-updates', headers=headers, json=body).json()
    watch_id = row['id']
    if channel == 'webhook':
        front.updates.verify(visitor_id, watch_id, courier.challenges[-1]['verification_code'])
    if action == 'capability':
        cap = front.updates.capability(watch_id)
        submit = lambda: client.post('/api/task-updates/stop', json={'capability':cap})
    else:
        submit = lambda: client.post(f'/api/task-updates/{watch_id}/action', headers=headers, json={'action':action})
    assert submit().status_code == 200
    assert submit().status_code == 200
    rows, total = store.list_cancellation_requests()
    assert total == 1
    evidence = rows[0]
    assert evidence['source'] == 'task_updates' and evidence['status'] == 'cancelled'
    assert evidence['visitor_id'] == visitor_id
    assert all(evidence[key] is None for key in ('visitor_token_hash','token_masked','ip','user_agent'))
    serialized = json.dumps(evidence)
    assert destination not in serialized and headers['X-Visitor-Token'] not in serialized
    assert watch_id not in serialized
    assert store.list_cancellation_requests(search=evidence['request_id'])[1] == 1
    assert store.reactivate_cancellation(evidence['request_id']) is False
    app = FastAPI()
    app.include_router(dashboard_router(store, store._path, 'secret', None,
        front=front, ssl_manager=Mock(get_status=lambda:{})))
    staff_session(store)
    with TestClient(app) as admin:
        response = admin.post('/admin/api/needs/cancellations/'+evidence['request_id']+'/reactivate', headers=H, json={})
        assert response.status_code == 409
    assert front.updates._get(watch_id)['state'] == 'revoked'
    assert not courier.events


def test_cross_visitor_stop_and_invalid_capability_create_no_cancellation(updates):
    store, front, client, _, headers, _, data, visitor_id = updates
    row = client.post('/api/task-updates', headers=headers, json=data).json()
    other = ask(client, 'hello')['visitor']['token']
    response = client.post('/api/task-updates/'+row['id']+'/action',
        headers={'X-Visitor-Token':other}, json={'action':'stop'})
    assert response.status_code == 400
    assert client.post('/api/task-updates/stop', json={'capability':'invalid'}).status_code == 400
    assert store.list_cancellation_requests()[1] == 0
    assert front.updates._get(row['id'])['state'] == 'active'


def test_withdrawal_and_customer_evidence_commit_atomically(updates):
    store, front, client, _, headers, _, data, visitor_id = updates
    row = client.post('/api/task-updates', headers=headers, json=data).json()
    with store.tx() as db:
        db.execute("""CREATE TRIGGER fail_cancellation BEFORE INSERT ON cancellation_requests
            BEGIN SELECT RAISE(ABORT, 'synthetic storage failure'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        front.updates.action(visitor_id, row['id'], 'stop')
    assert front.updates._get(row['id'])['state'] == 'active'
    assert store.list_cancellation_requests()[1] == 0


def test_reference_search_filters_across_more_than_one_page(env):
    world, public, admin = env
    first = None
    for number in range(55):
        inquiry_id = world.store.record_customer_inquiry(category='technical', name='Synthetic Agent',
            email='footer@example.test', subject=f'Pagination request {number}', message='Synthetic support message')
        if first is None:
            first = inquiry_id
    assert admin.get('/admin/api/needs/inquiries', headers=H).json()['total'] == 55
    response = admin.get('/admin/api/needs/inquiries', headers=H, params={'q':first,'category':'technical'})
    assert response.json()['total'] == 1 and response.json()['items'][0]['inquiry_id'] == first
    request_id = public.post('/api/privacy/opt-out', json={'request_type':'ccpa_opt_out'}).json()['request_id']
    response = admin.get('/admin/api/needs/privacy', headers=H, params={'q':request_id})
    assert response.json()['total'] == 1 and response.json()['items'][0]['request_id'] == request_id
    assert admin.get('/admin/api/needs/inquiries', headers=H, params={'q':"' OR 1=1 --"}).json()['total'] == 0
