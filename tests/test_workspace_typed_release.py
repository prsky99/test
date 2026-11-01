"""Private typed SDK releases use isolated customer identity and synthetic MCP."""
import base64
import hashlib
import json
from io import BytesIO
from pathlib import Path
import secrets
import time
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlsplit
from zipfile import ZipFile

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from agent_market.customer_identity import CustomerIdentity, CustomerActor, OIDCConfig
from agent_market.customer_workspace_runtime import CustomerWorkspaceAccess
from agent_market.workspace_access import WorkspaceDenied, WorkspaceInvalid, WorkspaceConflict
from agent_market.workspace_execution import WorkspaceExecution
from agent_market.workspace_release import DEPLOY_NOTICE
from agent_market.workspace_release_service import build_package
from agent_market.workspace_sdk_bff import create_app
from agent_market.workspace_typed_release import WorkspaceTypedReleases, CustomerTypedFlows, RUN_NOTICE, SDK_PROFILE
from agent_market.workspace_typed_release_service import router_for
from tests.test_workspace_typed_flows import typed_world, routing, save, run, graph

ORIGIN = 'https://customer.example'


@pytest.fixture
def typed_release_world(typed_world, tmp_path):
    w = typed_world
    config = OIDCConfig('https://accounts.google.com', 'synthetic-client.apps.googleusercontent.com',
        'https://accounts.google.com/o/oauth2/v2/auth', 'https://oauth2.googleapis.com/token',
        'https://www.googleapis.com/oauth2/v3/certs', 'https://agentconcierge.biz/api/customer-auth/callback', 'synthetic-secret')
    identity = CustomerIdentity(w.store, w.rt.key, config)
    customer = 'cu_' + secrets.token_hex(16); raw = 'cst_' + secrets.token_urlsafe(32); ref = identity._mac('session', raw)
    with identity.tx() as db:
        db.execute('INSERT INTO customer_identities VALUES(?,?,?,1,1,?,?)',
            (customer, config.issuer, identity._mac('subject', 'synthetic-typed-customer'), time.time(), time.time()))
        db.execute('INSERT INTO customer_sessions VALUES(?,?,?,?,?,NULL)',
            (ref, customer, identity._issuer_configuration(config.issuer), time.time(), time.time()+86400))
        db.execute('INSERT INTO customer_workspace_links VALUES(?,?,?,1,1,?)', (w.ws, customer, 'runner', time.time()))
    customer_access = CustomerWorkspaceAccess(w.access, identity)
    customer_execution = WorkspaceExecution(customer_access, w.execution.proxy)
    customer_flows = CustomerTypedFlows(customer_execution)
    releases = WorkspaceTypedReleases(w.core, customer_identity=identity, customer_flows=customer_flows)
    flow = save(w); result, _ = run(w, flow)
    assert result['run']['status'] == 'succeeded'
    args = (w.ws, flow['id'], flow['version_id'])
    release = releases.create(*args, {'run_id': result['run']['id'], 'ttl_seconds': 3600}, w.actor)
    deployment = releases.deploy(*args, release['id'], {'allowed_origins': [ORIGIN], 'ttl_seconds': 1800,
        'minute_limit': 5, 'day_limit': 20, 'authorized': True, 'notice': DEPLOY_NOTICE}, w.actor)
    app_config = releases.package_config(*args, deployment['app_id'], w.actor)
    package, name = build_package(app_config)
    with ZipFile(BytesIO(package)) as archive:
        archive.extractall(tmp_path)
    gateway_app = FastAPI(); gateway_app.include_router(router_for(releases))
    from agent_market.workspace_typed_flow_service import router_for as typed_router
    gateway_app.include_router(typed_router(w.core))
    from agent_market.customer_identity_service import router_for as identity_router
    gateway_app.include_router(identity_router(w.store, w.rt.key, identity=identity, admin=False))
    gateway = TestClient(gateway_app, base_url='https://agentconcierge.biz', raise_server_exceptions=False)
    def forward(request):
        response = gateway.request(request.method, request.url.path, headers=dict(request.headers), content=request.content)
        return httpx.Response(response.status_code, headers={k: v for k, v in response.headers.items()
            if k not in ('content-length', 'content-encoding', 'transfer-encoding')}, content=response.content)
    transport = httpx.Client(transport=httpx.MockTransport(forward))
    bff = TestClient(create_app(app_config, app_origin=ORIGIN, http=transport, root=tmp_path),
        base_url=ORIGIN, raise_server_exceptions=False)
    yield SimpleNamespace(w=w, identity=identity, customer=CustomerActor(customer, ref), raw=raw, flow=flow,
        result=result['run'], args=args, releases=releases, customer_flows=customer_flows, release=release,
        deployment=deployment, config=app_config, package=package, root=tmp_path, gateway=gateway, bff=bff)
    bff.close(); transport.close(); gateway.close()


def token(s):
    verifier = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    value = s.releases.authorize(s.deployment['app_id'], {'origin': ORIGIN, 'redirect_uri': ORIGIN+'/bff/callback',
        'challenge': challenge, 'state': secrets.token_urlsafe(32)}, s.customer)
    return s.releases.exchange(s.deployment['app_id'], {'code': value['code'], 'verifier': verifier,
        'redirect_uri': ORIGIN+'/bff/callback'}, ORIGIN)['access_token']


def test_admission_registry_preserves_typed_release_scope_and_rejects_corruption(typed_release_world):
    from agent_market.reliability_admission import SCHEMA
    s = typed_release_world
    with s.w.store.tx() as db:
        for statement in SCHEMA:
            db.execute(statement)
    before = len(s.w.calls)
    created = s.releases.create(*s.args, {'run_id': s.result['id'], 'ttl_seconds': 3600}, s.w.actor)
    assert created['id'] != s.release['id']
    assert s.releases.package_config(*s.args, s.deployment['app_id'], s.w.actor) == s.config
    assert token(s) and len(s.w.calls) == before
    with s.w.store.tx() as db:
        db.execute('INSERT INTO reliability_admissions VALUES(?,?,?,?,?,?,?)',
            ('rad_'+'1'*32, s.w.ws, '1'*64, None, None, '{}', 'corrupt'))
    with pytest.raises((WorkspaceDenied, WorkspaceConflict)):
        s.releases.create(*s.args, {'run_id': s.result['id'], 'ttl_seconds': 3600}, s.w.actor)
    with pytest.raises((WorkspaceDenied, WorkspaceConflict)):
        s.releases.package_config(*s.args, s.deployment['app_id'], s.w.actor)
    assert len(s.w.calls) == before


def sign_in(s):
    started = s.bff.post('/bff/login', json={}, headers={'Origin': ORIGIN}); assert started.status_code == 200
    url = started.json()['authorization_url']; assert '/workspace-flow-apps-v2/' in url
    params = dict(parse_qsl(urlsplit(url).query))
    result = s.gateway.post('/api/workspace-flow-apps-v2/'+s.deployment['app_id']+'/authorize', json=params,
        headers={'Origin': 'https://agentconcierge.biz', 'X-Customer-CSRF': s.identity.csrf(s.raw),
                 'Cookie': '__Host-ac_customer_session='+s.raw})
    assert result.status_code == 200, result.text
    callback = s.bff.get('/bff/callback', params={'code': result.json()['code'], 'state': params['state']}, follow_redirects=False)
    assert callback.status_code == 303, callback.text
    return {'Origin': ORIGIN, 'X-App-CSRF': s.bff.get('/bff/session').json()['csrf_token']}


def test_typed_package_has_no_authority_and_separate_profile(typed_release_world):
    s = typed_release_world
    assert s.config['profile'] == SDK_PROFILE and set(s.config) == {'app_id', 'profile', 'sdk_version', 'allowed_origins', 'release_id'}
    with ZipFile(BytesIO(s.package)) as archive:
        combined = b'\n'.join(archive.read(name) for name in archive.namelist()).decode()
        assert len(archive.namelist()) == 8 and all('/' not in name and '..' not in name for name in archive.namelist())
        assert 'workspace-sdk-whole-graph-run-v2' in combined and 'Selected prior-output bindings' in combined
        assert s.raw not in combined and s.w.raw not in combined and 'primary.example' not in combined
        assert 'two to ten' in archive.read('README.txt').decode()
    before = len(s.w.calls)
    assert s.releases.releases(*s.args, s.w.actor)[0]['id'] == s.release['id']
    assert len(s.w.calls) == before


def test_two_node_customer_bff_run_whole_graph_and_retained_status(typed_release_world):
    s = typed_release_world; headers = sign_in(s); before = len(s.w.calls)
    prepared = s.bff.post('/bff/prepare', json={}, headers=headers)
    assert prepared.status_code == 200, prepared.text
    plan = prepared.json(); assert plan['notice'] == RUN_NOTICE and plan['review']['max_calls'] == 2
    assert plan['review']['prior_output_sharing'] and len(s.w.calls) == before
    response = s.bff.post('/bff/runs', json={'ticket_id': plan['ticket_id'], 'authorized': True, 'notice': RUN_NOTICE}, headers=headers)
    assert response.status_code == 200, response.text
    run_value = response.json()['run']; assert run_value['status'] == 'succeeded' and len(s.w.calls) == before+2
    assert all(step['status'] == 'succeeded' for step in run_value['steps'])
    assert 'access_token' not in response.text and 'session_ref' not in response.text
    history = s.bff.get('/bff/history'); assert history.status_code == 200 and history.json()['runs'][0]['id'] == run_value['id']
    status = s.bff.post('/bff/status', json={'run_id': run_value['id']}, headers=headers)
    assert status.status_code == 200 and status.json()['run']['status'] == 'succeeded'
    with s.w.store.tx() as db:
        claims = json.loads(db.execute('SELECT payload FROM workspace_typed_flow_tickets WHERE id=?', (plan['ticket_id'],)).fetchone()[0])
    assert claims['actor_user_id'] == s.customer.customer_id and claims['actor_kind'] == 'customer'
    again = s.bff.post('/bff/runs', json={'ticket_id': plan['ticket_id'], 'authorized': True, 'notice': RUN_NOTICE}, headers=headers)
    assert again.status_code == 200 and len(s.w.calls) == before+2


@pytest.mark.parametrize('change', ['release', 'deployment', 'member', 'session', 'control', 'flow', 'approval', 'binding', 'restore'])
def test_current_authority_change_prevents_dispatch(typed_release_world, change):
    s = typed_release_world; access_token = token(s); app = s.deployment['app_id']
    plan = s.releases.prepare(app, access_token, ORIGIN); before = len(s.w.calls)
    with s.w.store.tx() as db:
        if change == 'release':
            s.releases.revoke(*s.args, s.release['id'], {'revision': 1}, s.w.actor)
        elif change == 'deployment':
            s.releases.revoke_deployment(*s.args, app, {'revision': 1}, s.w.actor)
        elif change == 'member': db.execute('UPDATE customer_workspace_links SET active=0,revision=revision+1 WHERE customer_id=?', (s.customer.customer_id,))
        elif change == 'session': db.execute('UPDATE customer_sessions SET revoked=? WHERE id=?', (time.time(), s.customer.session_ref))
        elif change == 'control': db.execute('UPDATE execution_controls SET invoke_enabled=0')
        elif change == 'flow': db.execute('INSERT INTO workspace_typed_flow_restore_blocks VALUES(?)', (s.flow['id'],))
        elif change == 'approval': db.execute('DELETE FROM capability_approvals WHERE version_id IN (SELECT id FROM connection_versions WHERE resource_id=?)', (s.w.ids[1],))
        elif change == 'binding': db.execute("UPDATE resources SET url='https://changed.example/mcp' WHERE id=?", (s.w.ids[0],))
        else: db.execute('INSERT INTO workspace_release_restore_blocks VALUES(?)', (app,))
    with pytest.raises((WorkspaceDenied, WorkspaceConflict)):
        s.releases.execute(app, access_token, {'ticket_id': plan['ticket_id'], 'authorized': True, 'notice': RUN_NOTICE}, ORIGIN)
    assert len(s.w.calls) == before


@pytest.mark.parametrize('at', ['first', 'last'])
def test_revocation_during_provider_response_blocks_followup_or_late_success(typed_release_world, at):
    s = typed_release_world; raw = token(s); app = s.deployment['app_id']
    plan = s.releases.prepare(app, raw, ORIGIN); before = len(s.w.calls)
    def revoke(_):
        s.releases.revoke_deployment(*s.args, app, {'revision': 1}, s.w.actor)
    s.w.hooks['primary.example' if at == 'first' else 'alternate.example'] = revoke
    result = s.releases.execute(app, raw, {'ticket_id': plan['ticket_id'], 'authorized': True, 'notice': RUN_NOTICE}, ORIGIN)
    assert result['run']['status'] == 'unknown'
    assert len(s.w.calls) == before+(1 if at == 'first' else 2)
    assert all(step['output'] is None for step in result['run']['steps'])
    with pytest.raises(WorkspaceDenied):
        s.releases.execute(app, raw, {'ticket_id': plan['ticket_id'], 'authorized': True, 'notice': RUN_NOTICE}, ORIGIN)
    assert len(s.w.calls) == before+(1 if at == 'first' else 2)


def test_unknown_submission_is_retained_and_never_replayed_or_given_other_app(typed_release_world):
    s = typed_release_world; raw = token(s); app = s.deployment['app_id']; before = len(s.w.calls)
    other = s.releases.deploy(*s.args, s.release['id'], {'allowed_origins': [ORIGIN], 'ttl_seconds': 600,
        'minute_limit': 5, 'day_limit': 20, 'authorized': True, 'notice': DEPLOY_NOTICE}, s.w.actor)
    plan = s.releases.prepare(app, raw, ORIGIN); s.w.modes['primary.example'] = 'unknown'
    body = {'ticket_id': plan['ticket_id'], 'authorized': True, 'notice': RUN_NOTICE}
    first = s.releases.execute(app, raw, body, ORIGIN)
    # Resubmitting the same ticket returns the retained run; it never calls the provider again.
    again = s.releases.execute(app, raw, body, ORIGIN)
    assert again['run']['id'] == first['run']['id'] and again['run']['status'] == 'unknown'
    history = s.releases.history(app, raw, ORIGIN)
    assert first['run']['status'] == history[0]['status'] == 'unknown' and first['run']['id'] == history[0]['id']
    assert len(s.w.calls) == before+1 and all(step['output'] is None for step in first['run']['steps'])
    with pytest.raises(WorkspaceDenied): s.releases.status(other['app_id'], first['status_capability']['access_token'], first['run']['id'], ORIGIN)
    with pytest.raises(WorkspaceDenied): s.releases.prepare(app, raw, 'https://other.example')


@pytest.mark.parametrize('attack', ['missing_consent', 'single_notice', 'mutable_input', 'other_ticket', 'wrong_version'])
def test_exact_whole_graph_consent_and_scope_before_provider_call(typed_release_world, attack):
    s = typed_release_world; raw = token(s); app = s.deployment['app_id']; before = len(s.w.calls)
    plan = s.releases.prepare(app, raw, ORIGIN)
    body = {'ticket_id': plan['ticket_id'], 'authorized': True, 'notice': RUN_NOTICE}
    if attack == 'missing_consent': body['authorized'] = False
    elif attack == 'single_notice': body['notice'] = 'workspace-sdk-run-v2'
    elif attack == 'mutable_input': body['input'] = {'query': 'Unreviewed query'}
    elif attack == 'other_ticket': body['ticket_id'] = 'wtt_'+'1'*32
    else:
        changed = s.w.core.save(s.w.ws, {'flow_id': s.flow['id'], 'revision': s.flow['revision'], 'name': 'Changed graph', 'definition': graph(s.w)}, s.w.actor)
        assert changed['version_id'] != s.flow['version_id']
    with pytest.raises((WorkspaceInvalid, WorkspaceDenied)):
        s.releases.execute(app, raw, body, ORIGIN)
    assert len(s.w.calls) == before


def test_customer_run_metadata_history_does_not_decrypt_retained_outputs(typed_release_world, monkeypatch):
    s = typed_release_world; raw = token(s); app = s.deployment['app_id']; plan = s.releases.prepare(app, raw, ORIGIN)
    result = s.releases.execute(app, raw, {'ticket_id': plan['ticket_id'], 'authorized': True, 'notice': RUN_NOTICE}, ORIGIN)
    original = s.customer_flows._step
    def checked(row, *, version_id=None, decrypt=True):
        assert not decrypt, 'History must not decrypt private output.'
        return original(row, version_id=version_id, decrypt=False)
    monkeypatch.setattr(s.customer_flows, '_step', checked)
    history = s.releases.history(app, raw, ORIGIN)
    assert history[0]['id'] == result['run']['id'] and history[0]['steps'] == []


@pytest.mark.parametrize('attack', ['origin', 'csrf', 'duplicate', 'nonfinite', 'oversize'])
def test_typed_admin_api_csrf_bounded_input_and_no_write(typed_release_world, attack):
    s = typed_release_world
    path = '/admin/api/workflow-workspaces/'+s.w.ws+'/typed-flows/'+s.flow['id']+'/versions/'+s.flow['version_id']+'/release-v2/releases'
    headers = {'Authorization': 'Bearer '+s.w.raw, 'X-Dashboard': '1', 'Origin': 'https://agentconcierge.biz', 'Content-Type': 'application/json'}
    content = json.dumps({'run_id': s.result['id'], 'ttl_seconds': 3600})
    if attack == 'origin': headers['Origin'] = 'https://other.example'
    elif attack == 'csrf': headers.pop('X-Dashboard')
    elif attack == 'duplicate': content = '{"run_id":"x","run_id":"y","ttl_seconds":3600}'
    elif attack == 'nonfinite': content = '{"run_id":"x","ttl_seconds":1e999}'
    else: content = '{"run_id":"'+'x'*65536+'","ttl_seconds":3600}'
    before = s.w.store.query('SELECT COUNT(*) FROM workspace_executable_releases')[0][0]
    response = s.gateway.post(path, headers=headers, content=content)
    assert response.status_code in (400,401,403), response.text
    assert response.headers['cache-control'] == 'no-store'
    assert s.w.store.query('SELECT COUNT(*) FROM workspace_executable_releases')[0][0] == before


def test_customer_execution_adapter_cannot_edit_or_disable_graph(typed_release_world):
    s = typed_release_world
    with s.identity.tx() as db:
        scope = s.identity.authorize(db, s.customer, s.w.ws, 'execute')
    actor = s.customer_flows.access.from_scope(scope)
    with pytest.raises(WorkspaceDenied):
        s.customer_flows.save(s.w.ws, {'flow_id': s.flow['id'], 'revision': 1, 'name': 'Unauthorized edit', 'definition': graph(s.w)}, actor)
    with pytest.raises(WorkspaceDenied): s.customer_flows.disable(s.w.ws, s.flow['id'], {'revision': 1}, actor)
    assert s.w.core.detail(s.w.ws, s.flow['id'], s.w.actor)['revision'] == 1


def test_existing_single_profile_cannot_authorize_typed_release(typed_release_world):
    from agent_market.workspace_release import WorkspaceReleases
    s = typed_release_world
    single = WorkspaceReleases(s.w.execution, customer_identity=s.identity, customer_executor=s.customer_flows)
    verifier = secrets.token_urlsafe(32); challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    with pytest.raises((WorkspaceDenied, KeyError)):
        single.authorize(s.deployment['app_id'], {'origin': ORIGIN, 'redirect_uri': ORIGIN+'/bff/callback',
            'challenge': challenge, 'state': secrets.token_urlsafe(32)}, s.customer)


def test_no_typed_customer_routes_on_default_public_frontend(about_client):
    app = 'wap_'+'1'*32
    assert about_client.get('/workspace-flow-apps-v2/'+app+'/authorize').status_code == 404
    for action in ('authorize','exchange','prepare','runs','status-capability'):
        assert about_client.post('/api/workspace-flow-apps-v2/'+app+'/'+action, json={}).status_code == 404
    assert about_client.get('/api/workspace-flow-apps-v2/'+app+'/history').status_code == 404


from tests.test_front_about import about_client
