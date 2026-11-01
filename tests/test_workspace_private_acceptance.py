"""Full dashboard mount acceptance uses named staff and disposable state only.

These checks bind the feature transports together. Individual modules retain
their detailed consent, payload, concurrency and provider boundary tests.
"""
from pathlib import Path
import re

from agent_market.gateway import admin_auth
from agent_market.workspace_app_factory import SDK_NOTICE
from agent_market.workspace_service import BASE
from tests.test_workspace_platform_integration import surfaces  # noqa: F401
from tests.test_workspace_execution_api import private_api  # noqa: F401


READS = (
    '/reliability/options', '/reliability/objects', '/reliability/inventory',
    '/reliability/evaluation/options', '/reliability/evaluation/status',
    '/reliability/routing/status', '/app-factory/options', '/sdk-lifecycle',
    '/support-outcomes', '/machine-updates/status', '/advancement/operating-preparation',
    '/reliability/evaluation/worker/status', '/machine-updates/receivers/status',
)
ASSETS = (
    'workspace-reliability-admin.js', 'workspace-reliability-controls-admin.js',
    'workspace-growth-admin.js', 'workspace-machine-updates-admin.js',
)


def read_all(w, staff, person):
    return [staff.get(BASE + '/' + w.ws['id'] + suffix, headers=w.headers[person])
            for suffix in READS]


def test_current_member_roles_read_all_mounted_features_and_nonmembers_cannot(surfaces):
    w, _, _, staff = surfaces
    for person in ('owner', 'editor', 'viewer', 'operator'):
        responses = read_all(w, staff, person)
        assert [item.status_code for item in responses] == [200] * len(READS)
        assert all('no-store' in item.headers['cache-control'] for item in responses)
        values = [item.json()['result'] for item in responses]
        assert values[0]['can_manage'] is (person == 'owner')
        assert values[3]['can_write'] is (person == 'owner')
        assert values[6]['can_edit'] is (person in ('owner', 'editor'))
        assert values[8]['can_withdraw'] is (person == 'owner')
        assert values[9]['can_manage'] is (person == 'owner')
    assert [item.status_code for item in read_all(w, staff, 'outsider')] == [404] * len(READS)
    assert not w.calls


def test_customer_cookie_machine_token_and_missing_dashboard_header_never_become_staff(surfaces):
    w, _, _, staff = surfaces
    staff.cookies.set('__Host-ac_customer_session', 'synthetic-customer-session')
    for headers in ({}, {'X-Dashboard': '1', 'Authorization': 'Bearer synthetic-machine-token'},
                    {'Authorization': w.headers['owner']['Authorization']}):
        responses = [staff.get(BASE + '/' + w.ws['id'] + suffix, headers=headers) for suffix in READS]
        assert [item.status_code for item in responses] == [401] * len(READS)
        assert all('no-store' in item.headers['cache-control'] for item in responses)
    assert not w.calls


def test_membership_withdrawal_immediately_removes_all_feature_reads_and_is_audited(surfaces):
    w, _, _, staff = surfaces
    assert all(item.status_code == 200 for item in read_all(w, staff, 'editor'))
    response = staff.post(BASE + '/' + w.ws['id'] + '/members', headers=w.headers['owner'],
        json={'user_id': w.users['editor'], 'role': 'editor', 'active': False, 'revision': 1})
    assert response.status_code == 200, response.text
    assert [item.status_code for item in read_all(w, staff, 'editor')] == [404] * len(READS)
    events = staff.get(BASE + '/' + w.ws['id'] + '/audit', headers=w.headers['owner']).json()['events']
    assert any(item['action'] == 'member.update' and item['object_id'] == 'user:' + str(w.users['editor'])
               and item['revision'] == 2 for item in events)
    assert not w.calls


def test_session_revocation_immediately_removes_all_feature_reads(surfaces):
    w, _, _, staff = surfaces
    assert all(item.status_code == 200 for item in read_all(w, staff, 'viewer'))
    with w.store.tx() as db:
        assert admin_auth.delete_session(db, w.headers['viewer']['Authorization'][7:])
    assert [item.status_code for item in read_all(w, staff, 'viewer')] == [401] * len(READS)
    assert all(item.status_code == 200 for item in read_all(w, staff, 'owner'))
    assert not w.calls


def test_sdk_admission_change_roundtrips_through_actual_mounted_routes_and_audit(surfaces):
    w, _, _, staff = surfaces
    path = BASE + '/' + w.ws['id'] + '/sdk-lifecycle'
    body = {'sdk_profile': 'workspace-typed-sdk-v2', 'revision': 0, 'accepting_runs': False,
            'minimum_sdk_version': '2.1.0', 'sunset_seconds': 600, 'authorized': True, 'notice': SDK_NOTICE}
    assert staff.post(path, headers=w.headers['editor'], json=body).status_code == 404
    written = staff.post(path, headers=w.headers['owner'], json=body)
    assert written.status_code == 200, written.text
    result = staff.get(path, headers=w.headers['viewer']).json()['result']
    policies = {value['sdk_profile']: value for value in result['policies']}
    assert policies['workspace-typed-sdk-v2']['revision'] == 1
    assert policies['workspace-typed-sdk-v2']['accepting_runs'] is False
    assert policies['workspace-sdk-v2']['revision'] == 0
    assert policies['workspace-sdk-v2']['accepting_runs'] is True
    assert result['releases'] == [] and result['public_sdk1_unchanged']
    assert staff.post(path, headers=w.headers['owner'], json=body).status_code == 409
    events = staff.get(BASE + '/' + w.ws['id'] + '/audit', headers=w.headers['owner']).json()['events']
    assert sum(item['action'] == 'sdk_policy.configure' for item in events) == 1
    assert not w.calls


def test_new_desktop_assets_match_current_bytes_and_each_uses_the_dashboard_nonce(surfaces):
    _, _, _, staff = surfaces
    page = staff.get('/admin/ui')
    nonce = re.search(r"script-src 'nonce-([^']+)'", page.headers['content-security-policy']).group(1)
    for name in ASSETS:
        assert page.text.count(f'<script nonce="{nonce}" src="/admin/assets/{name}"></script>') == 1
        response = staff.get('/admin/assets/' + name)
        assert response.status_code == 200
        assert response.content == (Path('agent_market/gateway') / name).read_bytes()
        assert 'no-store' in response.headers['cache-control']


def test_default_configuration_is_not_mistaken_for_actual_environment_acceptance(surfaces):
    w, _, customer, staff = surfaces
    preparation = staff.get(BASE + '/' + w.ws['id'] + '/advancement/operating-preparation',
                            headers=w.headers['owner']).json()['result']
    assert {item['id'] for item in preparation['identity_providers']} == {'google', 'github'}
    assert all(not item['configured'] and not item['operating_verified'] for item in preparation['identity_providers'])
    assert all(item['state'] == 'missing_configuration' for item in preparation['configuration'])
    assert all(not item['verified'] for item in preparation['operating_evidence'])
    assert not preparation['operating_evidence_complete']
    assert not preparation['configuration_is_operating_evidence']
    assert not preparation['sandbox_is_operating_acceptance']
    assert not preparation['public_workspace_access_enabled']
    assert not preparation['commercial_enabled'] and not preparation['payment_enabled']
    assert not preparation['provider_payout_enabled'] and not preparation['automatic_gate_promotion']
    worker = staff.get(BASE + '/' + w.ws['id'] + '/reliability/evaluation/worker/status',
                       headers=w.headers['owner']).json()['result']
    receiver = staff.get(BASE + '/' + w.ws['id'] + '/machine-updates/receivers/status',
                         headers=w.headers['owner']).json()['result']
    assert not worker['configured'] and not worker['running'] and not worker['active']
    assert not receiver['receiver_enabled'] and receiver['configured_destinations'] == 0
    assert not receiver['public_ingress_enabled'] and receiver['receipts'] == []
    assert customer.get(BASE + '/' + w.ws['id'] + '/machine-updates/status', headers=w.headers['owner']).status_code == 404
    assert not w.calls
