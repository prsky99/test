"""Footer customer requests in the renewed console: reasons, handler identity, audit and role limits."""
# ruff: noqa: F811 -- shared isolated fixtures
from agent_market.gateway import admin_auth
from tests.test_admin_next import login
from tests.test_dashboard import dash  # noqa: F401

D = {'X-Dashboard': '1'}
PROOF = 'a' * 64


def seed(store):
    inquiry = store.record_customer_inquiry('general', 'Synthetic Person', 'person@example.invalid', 'Workflow question',
                                            'How do I share a workflow?', ip='192.0.2.10', user_agent='synthetic-agent')
    privacy = store.record_privacy_request('data_erasure', email='person@example.invalid', details='Delete my data', ip='192.0.2.11')
    cancel = store.record_cancellation_request(token_masked='vt_…abcd', reason='Too many updates', ip='192.0.2.12')
    return inquiry, privacy, cancel


def user_headers(client, store, role):
    with store.tx() as db:
        admin_auth.create_admin_user(db, role + '-requests', 'Requests-' + role + '-password', role, role)
    token = client.post('/admin/api/auth/login', headers=D, json={'username': role + '-requests', 'password': 'Requests-' + role + '-password'}).json()['token']
    return {**D, 'authorization': 'Bearer ' + token}


def test_lists_hide_network_identifiers_and_respect_roles(dash):
    world, client = dash
    inquiry, privacy, cancel = seed(world.store)
    staff = login(client)
    listed = client.get('/admin/api/v2/requests/inquiries', headers=staff).json()
    row = [item for item in listed['items'] if item['inquiry_id'] == inquiry][0]
    assert row['email'] == 'person@example.invalid' and 'ip' not in row and 'user_agent' not in row and 'visitor_token' not in row
    assert [i['request_id'] for i in client.get('/admin/api/v2/requests/privacy?status=pending_verification', headers=staff).json()['items']] == [privacy]
    assert 'ip' not in client.get('/admin/api/v2/requests/cancellations', headers=staff).json()['items'][0]
    assert client.get('/admin/api/v2/requests/summary', headers=staff).json()['inquiries']['total'] >= 1
    assert client.get('/admin/api/v2/requests/privacy?status=bogus', headers=staff).status_code == 400
    assert client.get('/admin/api/v2/requests/other', headers=staff).status_code == 400
    operator = user_headers(client, world.store, 'operator')
    assert client.get('/admin/api/v2/requests/inquiries', headers=operator).status_code == 403
    assert client.get('/admin/api/v2/requests/summary', headers=D).status_code == 401


def test_inquiry_reply_records_the_individual_handler_and_reason(dash):
    world, client = dash
    inquiry, _, _ = seed(world.store)
    admin = user_headers(client, world.store, 'admin')
    route = '/admin/api/v2/requests/inquiries/' + inquiry
    assert client.post(route, headers=admin, json={'status': 'resolved', 'response': 'Use the Share button.'}).status_code == 400  # reason
    assert client.post(route, headers=admin, json={'status': 'done', 'reason': '고객 문의 답변'}).status_code == 400
    saved = client.post(route, headers=admin, json={'status': 'resolved', 'response': 'Use the Share button.', 'reason': '고객 문의 답변'})
    assert saved.status_code == 200, saved.text
    stored = world.store.get_customer_inquiry(inquiry)
    assert stored['status'] == 'resolved' and stored['resolved_by'] == 'admin-requests' and stored['admin_response'] == 'Use the Share button.'
    logs = client.get('/admin/api/audit/logs?action=INQUIRY_UPDATE', headers=login(client)).json()['logs']
    assert logs and '고객 문의 답변' in logs[0]['details'] and logs[0]['username'] == 'admin-requests'


def test_privacy_completion_needs_evidence_and_cannot_reopen(dash):
    world, client = dash
    _, privacy, _ = seed(world.store)
    staff = login(client)
    route = '/admin/api/v2/requests/privacy/' + privacy
    assert client.post(route, headers=staff, json={'status': 'completed', 'reason': '삭제 완료 처리'}).status_code == 400
    assert client.post(route, headers=staff, json={'status': 'processing', 'reason': '처리 시작'}).status_code == 200
    done = client.post(route, headers=staff, json={'status': 'completed', 'notes': 'Deleted all synthetic records.', 'proof_hash': PROOF, 'reason': '삭제 완료 처리'})
    assert done.status_code == 200, done.text
    assert client.post(route, headers=staff, json={'status': 'processing', 'reason': '다시 열기 시도'}).status_code == 400
    assert client.post('/admin/api/v2/requests/cancellations/' + privacy, headers=staff, json={'status': 'x', 'reason': '해지 변경 시도'}).status_code == 404


def test_legacy_inquiry_route_validates_status_and_records_handler(dash):
    world, client = dash
    inquiry, _, _ = seed(world.store)
    staff = login(client)
    assert client.patch('/admin/api/needs/inquiries/' + inquiry, headers=staff, json={'status': 'anything'}).status_code == 422
    assert client.patch('/admin/api/needs/inquiries/' + inquiry, headers=staff, json={'status': 'in_progress'}).status_code == 200
    assert world.store.get_customer_inquiry(inquiry)['resolved_by'] == 'sadmin'
    assert client.get('/admin/api/audit/logs?action=INQUIRY_UPDATE', headers=staff).json()['count'] == 1
