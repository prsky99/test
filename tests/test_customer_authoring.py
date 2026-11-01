"""Customer authoring reuses signed private rows and an isolated MCP transport."""
from io import BytesIO
import json
from types import SimpleNamespace
from zipfile import ZipFile

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from agent_market.customer_authoring import authoring_for
from agent_market.customer_authoring_service import router_for
from agent_market.customer_identity_service import COOKIE, router_for as identity_router
from agent_market.workspace_access import WorkspaceDenied
from agent_market.workspace_execution import NOTICE
from agent_market.workspace_release import DEPLOY_NOTICE
from agent_market.workflows import runtime_for
from tests.test_workspace_access import draft_body, definition
from tests.test_workspace_execution_api import private_api  # noqa: F401
from tests.test_workspace_release_v2 import release_world, app_token, run_app, ORIGIN  # noqa: F401


@pytest.fixture
def authoring(release_world):
    x = release_world
    graph = SimpleNamespace(key=runtime_for(x.w.store).key, access=x.access, identity=x.identity, execution=x.staff,
        app_execution=x.runner, releases=x.releases, lifecycle=x.lifecycle)
    core = authoring_for(graph)
    from tests.test_customer_credits import acceptance
    core.credits.enroll(acceptance(),x.customer)
    ws = core.organizations.create({'name': 'Customer task studio'}, x.customer)['id']
    actor = core.actor(ws, x.customer)
    draft = core.organizations.drafts.save_draft(ws, draft_body(definition()), actor)
    snapshot = core.organizations.drafts.create_snapshot(ws, draft['id'], {'draft_revision': 1}, actor)
    app = FastAPI(); app.include_router(identity_router(x.w.store, graph.key, identity=x.identity, admin=False))
    app.include_router(router_for(graph))
    client = TestClient(app, base_url='https://customer.test', raise_server_exceptions=False)
    client.cookies.set(COOKIE, x.raw_cookie)
    x.authoring, x.graph, x.customer_ws, x.customer_principal = core, graph, ws, actor
    x.customer_args = (ws, draft['id'], snapshot['id'])
    x.customer_base = '/api/customer-organizations/' + ws + '/authoring/drafts/' + draft['id'] + '/snapshots/' + snapshot['id']
    x.customer_client = client
    x.csrf = {'Origin': 'https://customer.test', 'X-Customer-CSRF': x.identity.csrf(x.raw_cookie)}
    yield x
    client.close()


def execute_test(x):
    core = x.authoring
    plan = core.execution.prepare(*x.customer_args, {'snapshot_revision': 1}, x.customer_principal)
    return core.execution.execute(*x.customer_args, {'ticket_id': plan['ticket_id'],
        'authorized': True, 'notice': NOTICE}, x.customer_principal)


def test_customer_owned_test_release_deploy_export_and_common_sdk_roundtrip(authoring):
    x = authoring; core = x.authoring; before = x.calls.count('tools/call')
    run = execute_test(x); assert run['status'] == 'succeeded'
    release = core.releases.create(*x.customer_args, {'run_id': run['id'], 'ttl_seconds': 3600}, x.customer_principal)
    app = core.releases.deploy(*x.customer_args, release['id'], {'allowed_origins': [ORIGIN], 'ttl_seconds': 600,
        'minute_limit': 2, 'day_limit': 3, 'authorized': True, 'notice': DEPLOY_NOTICE}, x.customer_principal)
    # The existing admin-issued SDK gateway reads the same signed customer-owned
    # release; no new run engine or customer-to-staff conversion is introduced.
    result, _ = run_app(x, app['app_id'], app_token(x, app['app_id']))
    assert result['run']['status'] == 'succeeded' and x.calls.count('tools/call') == before + 2
    response = x.customer_client.get(x.customer_base + '/deployments/' + app['app_id'] + '/package')
    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read('app-manifest.json'))
        assert manifest['app_id'] == app['app_id']
        assert 'access_token' not in archive.read('app-manifest.json').decode()
    assert x.w.store.query('SELECT COUNT(*) FROM workspace_memberships WHERE workspace_id=?', (x.customer_ws,))[0][0] == 0
    core.releases.revoke(*x.customer_args, release['id'], {'revision': 1}, x.customer_principal)
    with pytest.raises(WorkspaceDenied):
        core.releases.package_config(*x.customer_args, app['app_id'], x.customer_principal)


@pytest.mark.parametrize('role,can_run,can_release', [('viewer', False, False), ('runner', True, False), ('editor', True, False), ('owner', True, True)])
def test_current_customer_roles_and_no_staff_workspace_entry(authoring, role, can_run, can_release):
    x = authoring; core = x.authoring
    with x.identity.tx() as db:
        db.execute('UPDATE customer_workspace_links SET role=?,revision=revision+1 WHERE workspace_id=? AND customer_id=?',
                   (role, x.customer_ws, x.customer.customer_id))
    if can_run:
        run = execute_test(x)
        assert run['status'] == 'succeeded'
        if can_release:
            assert core.releases.create(*x.customer_args, {'run_id': run['id'], 'ttl_seconds': 600}, x.customer_principal)['active']
        else:
            with pytest.raises(WorkspaceDenied):
                core.releases.create(*x.customer_args, {'run_id': run['id'], 'ttl_seconds': 600}, x.customer_principal)
    else:
        with pytest.raises(WorkspaceDenied):
            core.execution.prepare(*x.customer_args, {'snapshot_revision': 1}, x.customer_principal)
    with pytest.raises(WorkspaceDenied):
        core.execution.options(*x.args, core.actor(x.args[0], x.customer))


def test_customer_transport_csrf_idor_exact_review_and_no_implicit_run(authoring):
    x = authoring; client = x.customer_client; before = x.calls.count('tools/call')
    assert client.get('/customer/organizations/' + x.customer_ws + '/build').status_code == 200
    assert client.post(x.customer_base + '/prepare', json={'snapshot_revision': 1}).status_code == 403
    assert client.post(x.customer_base + '/prepare', json={'snapshot_revision': 1, 'url': 'https://evil.invalid'}, headers=x.csrf).status_code == 400
    response = client.post(x.customer_base + '/prepare', json={'snapshot_revision': 1}, headers=x.csrf)
    assert response.status_code == 200 and x.calls.count('tools/call') == before
    review = response.json()['review']
    request = {'ticket_id': review['ticket_id'], 'authorized': True, 'notice': review['notice']}
    response = client.post(x.customer_base + '/runs', json=request, headers=x.csrf)
    assert response.status_code == 200 and response.json()['run']['status'] == 'succeeded'
    replay = client.post(x.customer_base + '/runs', json=request, headers=x.csrf)
    assert replay.status_code == 200 and x.calls.count('tools/call') == before + 1
    assert client.get(x.customer_base + '/runs').status_code == 200
    assert client.get(x.customer_base.replace(x.customer_ws, 'ws_' + 'f'*32) + '/options').status_code == 403
    x.identity.logout(x.raw_cookie)
    assert client.get(x.customer_base + '/runs').status_code == 401


def test_current_session_withdrawal_between_review_and_dispatch_prevents_call(authoring):
    x = authoring; core = x.authoring
    plan = core.execution.prepare(*x.customer_args, {'snapshot_revision': 1}, x.customer_principal)
    before = x.calls.count('tools/call')
    x.control['before_call'] = lambda: x.identity.logout(x.raw_cookie)
    run = core.execution.execute(*x.customer_args, {'ticket_id': plan['ticket_id'], 'authorized': True, 'notice': NOTICE}, x.customer_principal)
    assert run['status'] == 'denied' and x.calls.count('tools/call') == before


def test_shared_meter_consumes_customer_owner_policy_and_keeps_staff_authority_separate(authoring):
    from agent_market.workspace_metering import WorkspaceMetering, NOTICE as METER_NOTICE
    x = authoring; core = x.authoring
    common = WorkspaceMetering(x.access, x.staff)
    common.customer_access = core.access
    x.runner.meter = common
    core.meter.configure(x.customer_ws, {'revision': 0, 'enabled': True, 'units_per_success': 2,
        'max_runs': 5, 'ttl_seconds': 600, 'authorized': True, 'notice': METER_NOTICE}, x.customer_principal)
    run = execute_test(x)
    release = core.releases.create(*x.customer_args, {'run_id': run['id'], 'ttl_seconds': 600}, x.customer_principal)
    app = core.releases.deploy(*x.customer_args, release['id'], {'allowed_origins': [ORIGIN], 'ttl_seconds': 600,
        'minute_limit': 2, 'day_limit': 3, 'authorized': True, 'notice': DEPLOY_NOTICE}, x.customer_principal)
    result, _ = run_app(x, app['app_id'], app_token(x, app['app_id']))
    assert result['run']['status'] == 'succeeded'
    with core.execution._internal() as db:
        operation = common._operation(db, result['run']['id'])
        assert operation['settled_units'] == 2 and operation['actor_kind'] == 'customer'
        value = core.meter._policy(db, x.customer_ws)
        common._owner(value)
        invalid = dict(value, owner_kind='admin')
        with pytest.raises(WorkspaceDenied): common._owner(invalid)


@pytest.mark.parametrize('section',['flows','build','connections'])
def test_oauth_landing_document_accepts_navigation_but_api_remains_same_origin(authoring,section):
    x=authoring
    navigation={'Sec-Fetch-Site':'cross-site','Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document','Accept':'text/html'}
    response=x.customer_client.get('/customer/organizations/'+x.customer_ws+'/'+section,headers=navigation)
    assert response.status_code==200 and 'text/html' in response.headers['content-type']
    assert response.headers['cache-control']=='no-store'
    assert x.customer_client.get('/api/customer-organizations',headers=navigation).status_code==403
    assert x.customer_client.post('/api/customer-organizations',headers=navigation,json={}).status_code==403
