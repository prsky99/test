"""Privacy receipts never claim completion of an unreviewed data action."""
import pytest

from tests.test_customer_requests_hub import env, H  # noqa: F401


@pytest.mark.parametrize('kind,status', [('ccpa_opt_out', 'received'), ('gpc_signal', 'received'),
    ('data_access', 'pending_verification'), ('data_erasure', 'pending_verification')])
def test_receipt_is_not_completion(env, kind, status):
    world, public, admin = env
    payload = {'request_type': kind, 'email': 'review@example.test'}
    result = public.post('/api/privacy/opt-out', json=payload)
    assert result.status_code == 200
    receipt = result.json()
    assert receipt['status'] == status and 'enforced' not in receipt['message']
    rows = admin.get('/admin/api/needs/privacy', headers=H).json()['items']
    stored = next(r for r in rows if r['request_id'] == receipt['request_id'])
    assert stored['status'] == status and stored['completed_at'] is None


@pytest.mark.parametrize('raw', [b'', b'{', b'[]', b'null', b'{"request_type":"data_access","request_type":"ccpa_opt_out"}',
    b'{"gpc":NaN}'])
def test_malformed_body_does_not_create_a_receipt(env, raw):
    world, public, _ = env
    result = public.post('/api/privacy/opt-out', content=raw, headers={'Content-Type': 'application/json'})
    assert result.status_code == 400
    assert world.store.list_privacy_requests()[1] == 0


@pytest.mark.parametrize('payload', [{'request_type': 'anything'}, {'request_type': []}, {'email': '<bad@value>'},
    {'gpc': 'false'}, {'details': []}, {'request_type': 'data_erasure'}, {'completed': True}])
def test_unsupported_request_does_not_create_receipt(env, payload):
    world, public, _ = env
    assert public.post('/api/privacy/opt-out', json=payload).status_code == 422
    assert world.store.list_privacy_requests()[1] == 0


def test_completion_requires_reviewed_evidence_and_cannot_reopen(env):
    _, public, admin = env
    receipt = public.post('/api/privacy/opt-out', json={'request_type':'ccpa_opt_out'}).json()
    path = '/admin/api/needs/privacy/' + receipt['request_id']
    for payload in [{'status': 'completed'}, {'status': []}, {'status': 'anything'},
                    {'status': 'completed', 'notes': 'Synthetic reviewed preference evidence'}]:
        assert admin.patch(path, json=payload, headers=H).status_code in (400, 422)
    assert admin.patch(path, json={'status': 'processing'}, headers=H).status_code == 200
    assert admin.patch(path, json={'status': 'completed', 'notes': 'Synthetic reviewed preference evidence',
        'proof_hash': 'a' * 64}, headers=H).status_code == 200
    assert admin.patch(path, json={'status': 'received'}, headers=H).status_code == 422
    assert admin.patch(path, json={'status': 'completed'}, headers={}).status_code in (401, 403)


@pytest.mark.parametrize('raw', [b'{"status":"received","status":"processing"}', b'{"status":NaN}'])
def test_admin_ambiguous_review_does_not_update_status(env,raw):
    world, public, admin = env
    receipt=public.post('/api/privacy/opt-out',json={'request_type':'ccpa_opt_out'}).json()
    result=admin.patch('/admin/api/needs/privacy/'+receipt['request_id'],content=raw,
        headers={**H,'Content-Type':'application/json'})
    assert result.status_code in (400,422)
    assert world.store.list_privacy_requests()[0][0]['status']=='received'
