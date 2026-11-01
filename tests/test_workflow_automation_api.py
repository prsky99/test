"""Private automation HTTP contracts use isolated canonical fixture providers."""
import copy
import secrets
from unittest.mock import patch

import pytest

from agent_market.execution_authority import controls, set_controls
from agent_market.gateway.admin_auth import create_admin_user
from agent_market.workflow_connection_automation import PROFILE, SHARE_NOTICE, GRANT_NOTICE, EVENT_NOTICE
from tests.test_admin_security_audit import login, session_headers
from tests.test_workflow_fallback import routing
from tests.test_workflow_runtime import wait
from tests.test_workflow_typed_flow import typed_routing
from tests.test_workflow_publication_api import publication_api, published, H, ADMIN


@pytest.fixture
def automation_api(publication_api):
    return publication_api


def automation_path(release):
    return ADMIN + '/releases/' + release['id'] + '/automation'


def automation_plan(api, release=None, **changes):
    rt, public, admin, *_ = api; release = release or published(api)[0]
    body = {'trigger': 'event', 'interval_seconds': 0, 'max_runs': 2, 'ttl_seconds': 1800, **changes}
    result = admin.post(automation_path(release) + '/prepare', headers=H, json=body)
    assert result.status_code == 200, result.text
    return release, result.json()


def automation_issue_body(plan, **changes):
    return {key: plan[key] for key in ('proposal', 'signature')} | {
        'sharing_authority': True, 'sharing_notice': SHARE_NOTICE,
        'trigger_authority': True, 'trigger_notice': GRANT_NOTICE, **changes}


def automation_grant(api, release=None, **changes):
    rt, public, admin, *_ = api; release, plan = automation_plan(api, release, **changes)
    response = admin.post(automation_path(release) + '/issue', headers=H, json=automation_issue_body(plan))
    assert response.status_code == 200, response.text
    return response.json()['grant'], release, plan


def event_body(event_id=None, **changes):
    return {'event_id': event_id or secrets.token_hex(16), 'authority': True, 'notice': EVENT_NOTICE, **changes}


def automation_event(api, grant, release, body=None):
    rt, public, admin, *_ = api; body = body or event_body()
    response = admin.post(automation_path(release) + '/grants/' + grant['id'] + '/trigger', headers=H, json=body)
    assert response.status_code == 202, response.text
    return response.json(), body


def test_explicit_automation_grant_is_separate_from_publication_and_manual_runs(automation_api):
    rt, public, admin, calls, modes = automation_api; release = published(automation_api)[0]
    options = admin.get(automation_path(release) + '/options', headers=H)
    assert options.status_code == 200 and options.json()['available'] and options.json()['profile'] == PROFILE
    assert options.headers['cache-control'] == 'no-store'
    history = admin.get(automation_path(release) + '/history', headers=H).json()
    assert history['grants'] == [] and history['runs'] == []
    calls.clear(); release, plan = automation_plan(automation_api, release)
    assert not calls and not plan['executed'] and plan['preview']['fixed_window'] is True
    assert plan['preview']['source']['input']['language'] == 'en'
    assert plan['preview']['connection'] == {'path': ['items', 0, 'title'], 'target_field': 'query'}
    assert 'query' not in plan['preview']['target']['settings']
    assert not admin.get(automation_path(release) + '/history', headers=H).json()['grants']
    grant, release, _ = automation_grant(automation_api, release)
    assert not calls and grant['trigger'] == 'event' and grant['max_runs'] == 2
    job, body = automation_event(automation_api, grant, release)
    assert wait(rt, job)['status'] == 'succeeded' and len(calls) == 2
    history = admin.get(automation_path(release) + '/history', headers=H).json()
    row = next(item for item in history['runs'] if item['event_id'] == body['event_id'])
    assert row['run_id'] == job['run_id'] and row['status'] == 'succeeded'
    assert 'workflow-runtime-v1' not in str(history) and 'composition' not in str(history)


@pytest.mark.parametrize('changes', [{'sharing_authority': False}, {'trigger_authority': False},
    {'sharing_authority': 1}, {'trigger_authority': 1}, {'sharing_notice': 'workflow-public-flow-share-v1'},
    {'trigger_notice': 'workflow-connection-app-v13-grant-v1'}, {'publication_authority': True}, {'input': {}}])
def test_automation_does_not_inherit_old_publication_sdk_or_per_run_declarations(automation_api, changes):
    rt, public, admin, calls, modes = automation_api; release, plan = automation_plan(automation_api); calls.clear()
    response = admin.post(automation_path(release) + '/issue', headers=H, json=automation_issue_body(plan, **changes))
    assert response.status_code == 409 and not calls
    assert admin.get(automation_path(release) + '/history', headers=H).json()['grants'] == []


@pytest.mark.parametrize('role', ['operator', 'admin'])
def test_every_automation_route_requires_current_highest_admin(automation_api, role):
    rt, public, admin, calls, modes = automation_api; release = published(automation_api)[0]; calls.clear()
    with rt.store.tx() as db: create_admin_user(db, 'automation-viewer', 'viewer-password-long', 'Viewer', role)
    token = login(admin, 'automation-viewer', 'viewer-password-long').json()['token']; headers = session_headers(token)
    for route in ('options', 'history'):
        result = admin.get(automation_path(release) + '/' + route, headers=headers)
        assert result.status_code == 403 and result.headers['cache-control'] == 'no-store'
        assert admin.get(automation_path(release) + '/' + route).status_code in (401, 403)
    for route in ('prepare', 'issue', 'grants/aut_' + '0' * 32 + '/revoke', 'grants/aut_' + '0' * 32 + '/trigger'):
        result = admin.post(automation_path(release) + '/' + route, headers=headers, json={})
        assert result.status_code == 403 and result.headers['cache-control'] == 'no-store'
    assert not calls


@pytest.mark.parametrize('raw', ['[]', 'null', '{"ttl_seconds":NaN}', '{"ttl_seconds":1e999}',
    '{"ttl_seconds":300,"ttl_seconds":600}', 'x' * 64001])
def test_duplicate_nonfinite_or_unbounded_automation_json_is_rejected(automation_api, raw):
    rt, public, admin, calls, modes = automation_api; release = published(automation_api)[0]; calls.clear()
    result = admin.post(automation_path(release) + '/prepare', headers=H, content=raw)
    assert result.status_code == 400 and result.headers['cache-control'] == 'no-store' and not calls
    assert admin.get(automation_path(release) + '/history', headers=H).json()['grants'] == []


@pytest.mark.parametrize('headers', [{'Origin': 'null'}, {'Origin': 'https://attacker.example'}, {'Sec-Fetch-Site': 'cross-site'}])
def test_cross_origin_automation_writes_are_denied_before_grant_creation(automation_api, headers):
    rt, public, admin, calls, modes = automation_api; release = published(automation_api)[0]; calls.clear()
    result = admin.post(automation_path(release) + '/prepare', headers=H | headers, json={})
    assert result.status_code == 403 and result.headers['cache-control'] == 'no-store' and not calls


@pytest.mark.parametrize('changes', [{'trigger': 'webhook'}, {'trigger': 'event', 'interval_seconds': 300},
    {'trigger': 'scheduled', 'interval_seconds': 299}, {'max_runs': 101}, {'max_runs': True},
    {'ttl_seconds': 299}, {'input': {'query': 'unreviewed'}}, {'destination': 'https://recipient.example'}])
def test_exact_frequency_limits_and_no_arbitrary_input_or_delivery(automation_api, changes):
    rt, public, admin, calls, modes = automation_api; release = published(automation_api)[0]; calls.clear()
    body = {'trigger': 'event', 'interval_seconds': 0, 'max_runs': 2, 'ttl_seconds': 1800, **changes}
    result = admin.post(automation_path(release) + '/prepare', headers=H, json=body)
    assert result.status_code == 409 and not calls


def test_duplicate_event_is_one_run_and_does_not_consume_second_grant_slot(automation_api):
    rt, public, admin, calls, modes = automation_api; grant, release, _ = automation_grant(automation_api, max_runs=1); calls.clear()
    job, body = automation_event(automation_api, grant, release); assert wait(rt, job)['status'] == 'succeeded'
    repeated, _ = automation_event(automation_api, grant, release, body)
    assert repeated['run_id'] == job['run_id'] and len(calls) == 2
    history = admin.get(automation_path(release) + '/history', headers=H).json()
    assert len(history['runs']) == 1 and history['grants'][0]['used'] == 1
    denied = admin.post(automation_path(release) + '/grants/' + grant['id'] + '/trigger', headers=H, json=event_body())
    assert denied.status_code == 409 and len(calls) == 2


@pytest.mark.parametrize('changes', [{'authority': False}, {'authority': 1}, {'notice': 'old'},
    {'event_id': '../event'}, {'event_id': 'x' * 33}, {'payload': {}}, {'input': {}}])
def test_authenticated_event_requires_exact_current_notice_and_opaque_event_id(automation_api, changes):
    rt, public, admin, calls, modes = automation_api; grant, release, _ = automation_grant(automation_api); calls.clear()
    result = admin.post(automation_path(release) + '/grants/' + grant['id'] + '/trigger', headers=H, json=event_body(**changes))
    assert result.status_code == 409 and not calls
    assert admin.get(automation_path(release) + '/history', headers=H).json()['runs'] == []


def test_revocation_is_cas_and_history_never_drains_schedules(automation_api):
    rt, public, admin, calls, modes = automation_api; grant, release, _ = automation_grant(automation_api); calls.clear()
    base = automation_path(release); path = base + '/grants/' + grant['id']
    assert admin.post(path + '/revoke', headers=H, json={'revision': 0}).status_code == 409
    assert admin.post(path + '/revoke', headers=H, json={'revision': grant['revision']}).status_code == 200
    assert admin.post(path + '/revoke', headers=H, json={'revision': grant['revision']}).status_code == 409
    assert admin.post(path + '/trigger', headers=H, json=event_body()).status_code == 409
    with patch.object(rt.automation, 'run_due', side_effect=AssertionError('History must never advance schedules')):
        history = admin.get(base + '/history', headers=H)
        assert history.status_code == 200 and history.json()['grants'][0]['active'] is False
    assert not calls


def test_publication_withdrawal_and_control_change_deny_future_automation_events(automation_api):
    rt, public, admin, calls, modes = automation_api; grant, release, _ = automation_grant(automation_api); calls.clear()
    state = controls(rt.store)
    set_controls(rt.store, {'revision': state['revision'], 'invoke_enabled': False, 'workflow_enabled': False, 'delivery_enabled': False}, 1)
    path = automation_path(release) + '/grants/' + grant['id'] + '/trigger'
    assert admin.post(path, headers=H, json=event_body()).status_code == 409
    state = controls(rt.store)
    set_controls(rt.store, {'revision': state['revision'], 'invoke_enabled': True, 'workflow_enabled': True, 'delivery_enabled': True}, 1)
    assert admin.post(path, headers=H, json=event_body()).status_code == 409
    assert admin.post(ADMIN + '/releases/' + release['id'] + '/revoke', headers=H, json={'revision': release['revision']}).status_code == 200
    assert admin.post(path, headers=H, json=event_body()).status_code == 409 and not calls


def test_unknown_automation_result_remains_visible_without_replay_or_current_provider_gate(automation_api):
    rt, public, admin, calls, modes = automation_api; grant, release, _ = automation_grant(automation_api); calls.clear()
    workflow = rt.publication.metadata(release['id'])['workflow']
    host = rt.store.resource(workflow['nodes'][2]['resource_id'])['url'].split('/')[2]; modes[host] = 'unknown'
    job, body = automation_event(automation_api, grant, release)
    assert wait(rt, job)['execution_outcome'] == 'unknown' and len(calls) == 2
    with patch.object(rt.publication, 'current', side_effect=AssertionError('History is not fresh invocation readiness')):
        history = admin.get(automation_path(release) + '/history', headers=H)
        assert history.status_code == 200
        row = next(item for item in history.json()['runs'] if item['event_id'] == body['event_id'])
        assert row['run_id'] == job['run_id'] and row['outcome'] == 'unknown'
    assert len(calls) == 2


def test_no_public_webhook_or_old_sdk_route_can_trigger_an_automation_grant(automation_api):
    rt, public, admin, calls, modes = automation_api; grant, release, _ = automation_grant(automation_api); calls.clear()
    for path in ('/api/workflow-automations/' + grant['id'] + '/trigger',
                 '/api/workflow-connections/' + release['id'] + '/automation/grants/' + grant['id'] + '/trigger'):
        assert public.post(path, json=event_body()).status_code == 404
    assert admin.post(automation_path(release) + '/grants/' + grant['id'] + '/trigger', json=event_body()).status_code in (401, 403)
    assert not calls


def test_automation_rollout_marker_is_private_and_current(automation_api):
    rt, public, admin, calls, modes = automation_api
    assert admin.get(ADMIN + '/options', headers=H).json()['connected_automation_profile'] == PROFILE
    assert admin.get('/admin/api/workflows', headers=H).json()['connected_automation_profile'] == PROFILE
    assert 'connected_automation_profile' not in public.get('/api/workflow-connections').text
    assert not calls


def test_schedule_review_preserves_the_absolute_window_without_running_on_issue_or_history(automation_api):
    rt, public, admin, calls, modes = automation_api
    grant, release, plan = automation_grant(automation_api, trigger='scheduled', interval_seconds=300)
    assert grant['trigger'] == 'scheduled' and grant['interval_seconds'] == 300
    assert plan['preview']['fixed_window'] is True
    assert plan['preview']['source']['input']['from_utc']
    calls.clear()
    with patch.object(rt.automation, 'run_due', side_effect=AssertionError('History must never advance schedules')):
        assert admin.get(automation_path(release) + '/history', headers=H).status_code == 200
    assert not calls


def test_storage_fixed_route_is_registered_before_workflow_id_and_requires_auth(automation_api):
    rt, public, admin, calls, modes = automation_api
    result = admin.get('/admin/api/workflows/storage', headers=H)
    assert result.status_code == 200, result.text
    assert result.headers['cache-control'] == 'no-store'
    assert rt.store._path not in result.text
    assert admin.get('/admin/api/workflows/storage').status_code in (401, 403)
    assert not calls


@pytest.mark.parametrize('mutation', ['grant', 'owner', 'control'])
def test_late_authority_loss_after_source_dispatch_never_calls_documentation(automation_api, typed_routing, mutation):
    rt, public, admin, calls, modes = automation_api; grant, release, _ = automation_grant(automation_api); calls.clear()
    hooks = typed_routing[5]
    def withdraw(_):
        if mutation == 'grant':
            rt.automation.revoke(release['id'], grant['id'], grant['revision'], 1)
        elif mutation == 'owner':
            with rt.store.tx() as db: db.execute("UPDATE admin_users SET role='admin' WHERE username='synthetic-staff'")
        else:
            for enabled in (False, True):
                state = controls(rt.store)
                set_controls(rt.store, {'revision': state['revision'], 'invoke_enabled': enabled,
                    'workflow_enabled': enabled, 'delivery_enabled': enabled}, 1)
    hooks['primary.example'] = withdraw
    job, _ = automation_event(automation_api, grant, release)
    assert wait(rt, job)['status'] in ('failed', 'cancelled')
    assert calls == ['primary.example']
    if mutation == 'owner':
        with rt.store.tx() as db: db.execute("UPDATE admin_users SET role='superadmin' WHERE id=1")


def test_signed_review_is_single_use_and_cannot_change_the_fixed_contract(automation_api):
    rt, public, admin, calls, modes = automation_api; release, plan = automation_plan(automation_api); calls.clear()
    tampered = automation_issue_body(plan); tampered['proposal'] = copy.deepcopy(tampered['proposal'])
    tampered['proposal']['max_runs'] = 100
    assert admin.post(automation_path(release) + '/issue', headers=H, json=tampered).status_code == 409
    assert admin.get(automation_path(release) + '/history', headers=H).json()['grants'] == []
    body = automation_issue_body(plan)
    assert admin.post(automation_path(release) + '/issue', headers=H, json=body).status_code == 200
    assert admin.post(automation_path(release) + '/issue', headers=H, json=body).status_code == 409
    assert len(admin.get(automation_path(release) + '/history', headers=H).json()['grants']) == 1
    assert not calls
