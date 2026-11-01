"""SDK 1.3 HTTP boundaries use isolated signed connections and fixture agents."""
from io import BytesIO
import copy
import json
import re
import time
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

import pytest

from agent_market.execution_authority import controls, set_controls
from agent_market.gateway.admin_auth import create_admin_user
from agent_market.workflow_connection_deployment import PROFILE, GRANT_NOTICE, SHARE_NOTICE, RUN_NOTICE
from tests.test_admin_security_audit import login, session_headers
from tests.test_workflow_fallback import routing
from tests.test_workflow_runtime import wait
from tests.test_workflow_typed_flow import typed_routing
from tests.test_workflow_publication_api import publication_api, published, H, ADMIN

PUBLIC = '/api/workflow-connection-apps-v13'
ORIGIN = 'https://customer.example'


@pytest.fixture
def connected_api(publication_api):
    return publication_api


def admin_path(release):
    return ADMIN + '/releases/' + release['id'] + '/export-app-v13'


def export_plan(api, release=None, **changes):
    rt, public, admin, *_ = api
    release = release or published(api)[0]
    body = {'allowed_origins': [ORIGIN], 'minute_limit': 10, 'day_limit': 500, 'ttl_seconds': 1800, **changes}
    result = admin.post(admin_path(release) + '/prepare', headers=H, json=body)
    assert result.status_code == 200, result.text
    return release, result.json()


def export_body(plan, **changes):
    return {key: plan[key] for key in ('proposal', 'signature')} | {
        'deployment_authority': True, 'deployment_notice': GRANT_NOTICE, **changes}


def deployed(api, release=None, **changes):
    rt, public, admin, *_ = api
    release, plan = export_plan(api, release, **changes)
    response = admin.post(admin_path(release) + '/package', headers=H, json=export_body(plan))
    assert response.status_code == 200, response.text
    with ZipFile(BytesIO(response.content)) as archive:
        config = json.loads(archive.read('app-manifest.json'))
    records = admin.get(admin_path(release) + '/deployments', headers=H).json()['deployments']
    app = next(row for row in records if row['app_id'] == config['app_id']) | config
    return app, release, plan


def app_headers(app, origin=ORIGIN, **changes):
    return {'Origin': origin, 'X-Publish-Key': app['publish_key'], **changes}


def run_body(prepared, **changes):
    return {key: prepared[key] for key in ('proposal', 'signature')} | {
        'sharing_authority': True, 'sharing_notice': SHARE_NOTICE,
        'run_authority': True, 'run_notice': RUN_NOTICE, **changes}


def app_run(api, app):
    rt, public, *_ = api
    prepared = public.post(PUBLIC + '/' + app['app_id'] + '/prepare', headers=app_headers(app), json={})
    assert prepared.status_code == 200, prepared.text
    body = run_body(prepared.json())
    response = public.post(PUBLIC + '/' + app['app_id'] + '/runs', headers=app_headers(app), json=body)
    assert response.status_code == 202, response.text
    return response.json(), body, prepared.json()


def test_separate_prepare_deployment_and_run_do_not_broaden_publication(connected_api):
    rt, public, admin, calls, modes = connected_api
    release, plan = export_plan(connected_api)
    assert len(calls) == 2 and not rt.store.query('SELECT id FROM workflow_connection_deployments')
    assert plan['profile'] == PROFILE and not plan['executed']
    assert plan['preview']['connection']['path'] == ['items', 0, 'title']
    assert 'query' not in plan['preview']['target']['settings']
    assert admin.post(admin_path(release) + '/package', headers=H,
                      json={key: plan[key] for key in ('proposal', 'signature')}).status_code == 409
    assert not rt.store.query('SELECT id FROM workflow_connection_deployments')
    app, release, _ = deployed(connected_api, release)
    assert not rt.store.query('SELECT id FROM workflow_apps')
    assert public.get('/api/workflow-connections/' + release['id']).status_code == 200
    calls.clear(); job, body, preview = app_run(connected_api, app)
    assert wait(rt, job)['status'] == 'succeeded' and len(calls) == 2
    assert job['run_key'] and preview['profile'] == PROFILE
    assert preview['preview']['source']['input'] == plan['preview']['source']['input']
    path = PUBLIC + '/' + app['app_id'] + '/runs/' + job['run_id']
    response = public.get(path, headers=app_headers(app, **{'X-Workflow-Key': job['run_key']}))
    assert response.status_code == 200 and response.json()['status'] == 'succeeded'
    assert job['run_key'] not in response.text and app['publish_key'] not in response.text
    for old in ('/api/workflows/runs/' + job['run_id'],
                '/api/workflow-connections/' + release['id'] + '/runs/' + job['run_id'],
                '/api/workflow-apps/' + app['app_id'] + '/runs/' + job['run_id'],
                '/api/workflow-apps-v12/' + app['app_id'] + '/runs/' + job['run_id']):
        assert public.get(old, headers={'X-Publish-Key': app['publish_key'], 'X-Workflow-Key': job['run_key']}).status_code == 404
    assert rt.store.query('SELECT access_hash FROM workflow_runs WHERE id=?', (job['run_id'],))[0]['access_hash'] is None


@pytest.mark.parametrize('single', [False, True])
def test_package_contains_only_gateway_public_identity_and_local_assets(connected_api, single):
    rt, public, admin, calls, modes = connected_api
    release, plan = export_plan(connected_api)
    response = admin.post(admin_path(release) + ('/html' if single else '/package'), headers=H, json=export_body(plan))
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    if single:
        index = response.text
        assert 'src="assets/' not in index and '<style nonce=' in index
        assert 'AgentConciergeWorkflow' in index
    else:
        with ZipFile(BytesIO(response.content)) as archive:
            assert set(archive.namelist()) == {'index.html', 'assets/styles.css', 'assets/agentconcierge-sdk.js', 'assets/app.js', 'app-manifest.json', 'README.md'}
            index = archive.read('index.html').decode()
            config = json.loads(archive.read('app-manifest.json'))
            assert config['profile'] == PROFILE and config['sdk_version'] == '1.3.0'
            assert 'workflow_id' not in config and 'grant_id' not in config
            assert all(not info.filename.startswith('/') and info.external_attr >> 16 == 0o100644 for info in archive.infolist())
    config = json.loads(re.search(r'id="wfData" nonce="[^"]+">(.*?)</script>', index)[1])
    assert set(config) == {'app_id', 'publish_key', 'release_id', 'profile', 'sdk_version'}
    assert 'connect-src https://agentconcierge.biz' in index and 'form-action &#x27;none&#x27;' in index
    assert 'lang="en"' in index and 'name="description"' in index and 'lucide lucide-' in index
    assert '<input id="shareAppAuthority" type="checkbox" disabled>' in index
    assert '<input id="liveAppAuthority" type="checkbox" disabled>' in index
    assert 'prefers-reduced-motion' in (index if single else archive_css(response.content))
    for forbidden in ('composition', 'source_binding_hash', 'credential_refs', 'workflow-runtime-v1', 'mcp.test', 'docs.test', 'news.test'):
        assert forbidden not in index
    assert not re.search(r'[\uac00-\ud7af]', index)


def archive_css(data):
    with ZipFile(BytesIO(data)) as archive: return archive.read('assets/styles.css').decode()


@pytest.mark.parametrize('role', ['operator', 'admin'])
def test_current_highest_admin_is_required_for_every_deployment_action(connected_api, role):
    rt, public, admin, calls, modes = connected_api; release = published(connected_api)[0]
    with rt.store.tx() as db: create_admin_user(db, 'sdk-viewer', 'viewer-password-long', 'Viewer', role)
    token = login(admin, 'sdk-viewer', 'viewer-password-long').json()['token']; headers = session_headers(token)
    for route in ('options', 'deployments'):
        assert admin.get(admin_path(release) + '/' + route, headers=headers).status_code == 403
        assert admin.get(admin_path(release) + '/' + route).status_code in (401, 403)
    for route in ('prepare', 'package', 'html', 'deployments/capp_' + '0' * 32 + '/revoke'):
        assert admin.post(admin_path(release) + '/' + route, headers=headers, json={}).status_code == 403
    assert not rt.store.query('SELECT id FROM workflow_connection_deployments')


@pytest.mark.parametrize('origin', [None, 'null', 'https://attacker.example', ORIGIN + '/path', 'https://user:pass@customer.example'])
def test_missing_null_or_unregistered_origin_rejects_all_app_operations(connected_api, origin):
    rt, public, admin, calls, modes = connected_api; app, release, _ = deployed(connected_api); calls.clear()
    headers = app_headers(app)
    if origin is None: headers.pop('Origin')
    else: headers['Origin'] = origin
    path = PUBLIC + '/' + app['app_id']
    assert public.post(path + '/prepare', headers=headers, json={}).status_code == 403
    assert public.post(path + '/runs', headers=headers, json={}).status_code == 403
    assert public.get(path + '/runs/wr_' + '0' * 32, headers=headers).status_code == 404
    assert not calls and not rt.store.query('SELECT n FROM workflow_app_usage WHERE app_id=?', (app['app_id'],))


def test_exact_preflight_uses_registered_origin_without_needing_private_keys(connected_api):
    rt, public, admin, calls, modes = connected_api; app, _, _ = deployed(connected_api); calls.clear()
    path = PUBLIC + '/' + app['app_id'] + '/runs'
    headers = {'Origin': ORIGIN, 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'content-type,x-publish-key'}
    good = public.options(path, headers=headers)
    assert good.status_code == 204 and good.headers['access-control-allow-origin'] == '*'
    for changes in ({'Origin': 'null'}, {'Origin': 'https://other.example'}, {'Access-Control-Request-Headers': 'authorization'}, {'Access-Control-Request-Method': 'DELETE'}):
        assert public.options(path, headers=headers | changes).status_code == 403
    assert not calls


@pytest.mark.parametrize('changes', [{'sharing_authority': False}, {'run_authority': 1}, {'sharing_notice': 'old'},
                                     {'run_notice': 'old'}, {'input': {}}, {'workflow_id': 1}])
def test_every_run_requires_exact_fresh_sharing_and_execution_declarations(connected_api, changes):
    rt, public, admin, calls, modes = connected_api; app, _, _ = deployed(connected_api); calls.clear()
    path = PUBLIC + '/' + app['app_id']; prepared = public.post(path + '/prepare', headers=app_headers(app), json={}).json()
    before = len(rt.store.query('SELECT id FROM workflow_runs'))
    response = public.post(path + '/runs', headers=app_headers(app), json=run_body(prepared, **changes))
    assert response.status_code == 400 and not calls
    assert len(rt.store.query('SELECT id FROM workflow_runs')) == before


def test_prepare_and_nonce_replay_do_not_consume_an_extra_start_slot(connected_api):
    rt, public, admin, calls, modes = connected_api; app, _, _ = deployed(connected_api, minute_limit=1); calls.clear()
    # Freeze only the quota module's bucket clock, without changing runtime
    # checkpoint chronology, to avoid crossing a real minute boundary.
    with patch('agent_market.workflow_apps.time', SimpleNamespace(time=lambda: time.time())) as clock:
        anchor = time.time(); clock.time = lambda: anchor
        job, body, _ = app_run(connected_api, app); assert wait(rt, job)['status'] == 'succeeded'
        again = public.post(PUBLIC + '/' + app['app_id'] + '/runs', headers=app_headers(app), json=body)
        assert again.status_code == 202 and again.json()['run_id'] == job['run_id']
        assert again.json()['run_key'] == job['run_key'] and again.json()['replayed'] and len(calls) == 2
        rows = rt.store.query("SELECT n FROM workflow_app_usage WHERE app_id=? AND identity='app' AND operation='start'", (app['app_id'],))
        assert rows[0]['n'] == 1
        prepared = public.post(PUBLIC + '/' + app['app_id'] + '/prepare', headers=app_headers(app), json={})
        assert prepared.status_code == 200
        denied = public.post(PUBLIC + '/' + app['app_id'] + '/runs', headers=app_headers(app), json=run_body(prepared.json()))
        assert denied.status_code == 429 and denied.headers['retry-after'] == '60' and len(calls) == 2


def test_app_origin_and_run_keys_cannot_cross_deployments(connected_api):
    rt, public, admin, calls, modes = connected_api; first, release, _ = deployed(connected_api)
    second, _, _ = deployed(connected_api, release, allowed_origins=['https://second.example'])
    job, _, _ = app_run(connected_api, first); assert wait(rt, job)['status'] == 'succeeded'
    path = PUBLIC + '/' + second['app_id'] + '/runs/' + job['run_id']
    headers = app_headers(second, 'https://second.example', **{'X-Workflow-Key': job['run_key']})
    assert public.get(path, headers=headers).status_code == 404
    assert public.post(path + '/cancel', headers=headers, json={}).status_code == 404
    assert public.post(PUBLIC + '/' + first['app_id'] + '/prepare', headers=app_headers(second), json={}).status_code == 403


def test_deployment_revocation_is_cas_and_independent_from_publication(connected_api):
    rt, public, admin, calls, modes = connected_api; app, release, _ = deployed(connected_api)
    job, _, _ = app_run(connected_api, app); assert wait(rt, job)['status'] == 'succeeded'
    path = admin_path(release) + '/deployments/' + app['app_id'] + '/revoke'
    assert admin.post(path, headers=H, json={'revision': 0}).status_code == 409
    assert admin.post(path, headers=H, json={'revision': app['revision']}).status_code == 200
    assert admin.post(path, headers=H, json={'revision': app['revision']}).status_code == 409
    assert public.get('/api/workflow-connections/' + release['id']).status_code == 200
    assert public.post(PUBLIC + '/' + app['app_id'] + '/prepare', headers=app_headers(app), json={}).status_code == 403
    assert public.get(PUBLIC + '/' + app['app_id'] + '/runs/' + job['run_id'], headers=app_headers(app, **{'X-Workflow-Key': job['run_key']})).status_code == 404
    records = admin.get(admin_path(release) + '/deployments', headers=H).json()['deployments']
    assert records[0]['active'] is False and records[0]['revision'] == app['revision'] + 1


def test_publication_revocation_also_denies_its_independent_deployment(connected_api):
    rt, public, admin, calls, modes = connected_api; app, release, _ = deployed(connected_api)
    response = admin.post(ADMIN + '/releases/' + release['id'] + '/revoke', headers=H, json={'revision': release['revision']})
    assert response.status_code == 200
    calls.clear()
    assert public.post(PUBLIC + '/' + app['app_id'] + '/prepare', headers=app_headers(app), json={}).status_code == 403
    assert not calls


@pytest.mark.parametrize('failure', ['invalid', 'unknown'])
def test_failed_unknown_runs_keep_metadata_read_access_after_current_readiness_changes(connected_api, failure):
    rt, public, admin, calls, modes = connected_api; app, release, _ = deployed(connected_api); calls.clear()
    workflow = rt.publication.metadata(release['id'])['workflow']
    host = rt.store.resource(workflow['nodes'][2]['resource_id'])['url'].split('/')[2]; modes[host] = failure
    job, _, _ = app_run(connected_api, app)
    result = wait(rt, job); assert result['status'] == 'failed' and len(calls) == 2
    state = controls(rt.store)
    set_controls(rt.store, {'revision': state['revision'], 'invoke_enabled': False, 'workflow_enabled': False, 'delivery_enabled': False}, 1)
    with patch.object(rt.publication, 'current', side_effect=AssertionError('Reading does not invoke current provider gates')):
        path = PUBLIC + '/' + app['app_id'] + '/runs/' + job['run_id']; headers = app_headers(app, **{'X-Workflow-Key': job['run_key']})
        response = public.get(path, headers=headers)
        assert response.status_code == 200 and response.json()['status'] == 'failed'
        if failure == 'unknown': assert response.json()['execution_outcome'] == 'unknown'
        assert public.post(path + '/cancel', headers=headers, json={}).status_code == 200
    assert len(calls) == 2


@pytest.mark.parametrize('raw', ['[]', 'null', '{"limit":NaN}', '{"limit":1e999}', '{"input":{}}', '{"input":{},"input":{}}', 'x' * 16001])
def test_public_prepare_rejects_unbounded_duplicate_or_nonfinite_json(connected_api, raw):
    rt, public, admin, calls, modes = connected_api; app, _, _ = deployed(connected_api); calls.clear()
    response = public.post(PUBLIC + '/' + app['app_id'] + '/prepare', headers=app_headers(app), content=raw)
    assert response.status_code == 400 and response.headers['cache-control'] == 'no-store' and not calls


def test_admin_csrf_and_strict_body_do_not_issue_grants(connected_api):
    rt, public, admin, calls, modes = connected_api; release = published(connected_api)[0]; calls.clear()
    path = admin_path(release) + '/prepare'
    assert admin.post(path, headers=H | {'Origin': 'https://attacker.example'}, json={}).status_code == 403
    for raw in ('{"ttl_seconds":NaN}', '{"ttl_seconds":1e999}', '{"ttl_seconds":300,"ttl_seconds":600}', '[]', 'x' * 64001):
        assert admin.post(path, headers=H, content=raw).status_code == 400
    assert not calls and not rt.store.query('SELECT id FROM workflow_connection_deployments')


def test_failed_artifact_build_revokes_its_new_grant(connected_api):
    rt, public, admin, calls, modes = connected_api; release, plan = export_plan(connected_api)
    with patch('agent_market.admin_workflow_webapp_v13.build_admin_package_v13', side_effect=OSError('private location')):
        response = admin.post(admin_path(release) + '/package', headers=H, json=export_body(plan))
    assert response.status_code == 500 and 'private location' not in response.text
    records = rt.store.query('SELECT active,revision FROM workflow_connection_deployments')
    assert len(records) == 1 and records[0]['active'] == 0 and records[0]['revision'] == 2
    assert not rt.store.query('SELECT id FROM workflow_apps')


def test_signed_admin_review_survives_browser_json_number_roundtrip(connected_api):
    rt, public, admin, calls, modes = connected_api; release, plan = export_plan(connected_api)
    def browser_numbers(value):
        if isinstance(value, dict): return {key: browser_numbers(item) for key, item in value.items()}
        if isinstance(value, list): return [browser_numbers(item) for item in value]
        if type(value) is float and value.is_integer(): return int(value)
        return value
    result = admin.post(admin_path(release) + '/package', headers=H, json=browser_numbers(export_body(plan)))
    assert result.status_code == 200, result.text


def test_expired_independent_deployment_denies_preparation_and_retained_run_access(connected_api):
    rt, public, admin, calls, modes = connected_api; app, release, _ = deployed(connected_api)
    job, _, _ = app_run(connected_api, app); assert wait(rt, job)['status'] == 'succeeded'; calls.clear()
    path = PUBLIC + '/' + app['app_id']; headers = app_headers(app, **{'X-Workflow-Key': job['run_key']})
    with patch('agent_market.workflow_connection_deployment.time.time', return_value=app['expires'] + 1):
        assert public.post(path + '/prepare', headers=headers, json={}).status_code == 403
        assert public.get(path + '/runs/' + job['run_id'], headers=headers).status_code == 404
        assert public.post(path + '/runs/' + job['run_id'] + '/cancel', headers=headers, json={}).status_code == 404
    assert not calls


def test_export_proposal_is_one_use_and_cancellation_cannot_accept_extra_fields(connected_api):
    rt, public, admin, calls, modes = connected_api; app, release, plan = deployed(connected_api)
    assert admin.post(admin_path(release) + '/package', headers=H, json=export_body(plan)).status_code == 409
    assert len(rt.store.query('SELECT id FROM workflow_connection_deployments')) == 1
    job, _, _ = app_run(connected_api, app); assert wait(rt, job)['status'] == 'succeeded'; calls.clear()
    path = PUBLIC + '/' + app['app_id'] + '/runs/' + job['run_id'] + '/cancel'
    response = public.post(path, headers=app_headers(app, **{'X-Workflow-Key': job['run_key']}), json={'run_id': job['run_id']})
    assert response.status_code == 404 and not calls
