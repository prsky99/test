"""Synthetic customer runner and SDK2 contracts for the owned Unix PG harness.

This module has no standalone database address, service, or activation command.
The fixed private application rehearsal supplies its isolated Store and actors.
"""
from io import BytesIO
import json
from pathlib import Path
import tempfile
from urllib.parse import parse_qsl, urlsplit
from zipfile import ZipFile

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient


def run_private_customer_contracts(store, graph, identity, login, workspace, staff, resource_id):
    from agent_market.concierge.proxy import McpProxy
    from agent_market.customer_workspace_runtime import CustomerWorkspaceAccess
    from agent_market.workspace_execution import WorkspaceExecution, NOTICE
    from agent_market.workspace_access import WorkspaceDenied
    from agent_market.workspace_lifecycle import WorkspaceLifecycle
    from agent_market.workspace_release import WorkspaceReleases, DEPLOY_NOTICE
    from agent_market.workspace_release_service import build_package, router_for
    from agent_market.customer_identity_service import router_for as identity_router
    from agent_market.workspace_sdk_bff import create_app
    from agent_market.workspace_metering import NOTICE as METER_NOTICE
    from tests.test_workflow_fallback import tool, output
    from tests.test_mcp_proxy import MockRemoteMcp

    if store.backend != 'postgresql' or store.workflow_key != b'k' * 32:
        raise AssertionError('Only the synthetic private Store may run this contract.')
    checks, calls = {}, []
    remote = MockRemoteMcp([tool()], call_result=output())
    def provider(request):
        calls.append(json.loads(request.content or b'{}').get('method'))
        return remote.handle_request(request)
    http = httpx.Client(transport=httpx.MockTransport(provider))
    proxy = McpProxy(store, allow_private=True, http=http)
    access, ws = graph.access, workspace['id']
    identity.set_link(access, ws, {'customer_id': login['customer_id'], 'role': 'runner',
        'active': True, 'revision': 0}, staff)
    policy = graph.meter.summary(ws, staff)['policy']
    graph.meter.configure(ws, {'revision': policy['revision'] if policy else 0,
        'enabled': False, 'units_per_success': 7, 'max_runs': 10, 'ttl_seconds': 3600,
        'authorized': True, 'notice': METER_NOTICE}, staff)
    draft = access.save_draft(ws, {'name': 'Synthetic native customer task',
        'description': 'Public documentation lookup with separate customer execution authority.',
        'definition': {'nodes': [
            {'id': 'start', 'name': 'Manual start', 'type': 'trigger', 'kind': 'trigger', 'data': {}},
            {'id': 'lookup', 'name': 'Public documentation', 'type': 'agent', 'kind': 'mcp',
             'resource_id': resource_id, 'data': {'tool': 'search_docs',
                 'input': {'query': 'documentation', 'language': 'en', 'limit': 2}}},
        ], 'edges': [{'source': 'start', 'target': 'lookup'}]}}, staff)
    snapshot = access.create_snapshot(ws, draft['id'], {'draft_revision': 1}, staff)
    args = (ws, draft['id'], snapshot['id'])
    customer = identity.actor(login['session_token'])
    adapter = CustomerWorkspaceAccess(access, identity)
    with identity.tx() as db:
        actor = adapter.from_scope(identity.authorize(db, customer, ws, 'execute'))
    executor, staff_executor = WorkspaceExecution(adapter, proxy), WorkspaceExecution(access, proxy)
    try:
        before = calls.count('tools/call')
        plan = executor.prepare(*args, {'snapshot_revision': 1}, actor)
        if calls.count('tools/call') != before:
            raise AssertionError('Preparation must remain offline.')
        result = executor.execute(*args, {'ticket_id': plan['ticket_id'], 'authorized': True, 'notice': NOTICE}, actor)
        replay = executor.execute(*args, {'ticket_id': plan['ticket_id'], 'authorized': True, 'notice': NOTICE}, actor)
        if result['status'] != 'succeeded' or not replay['replayed'] or calls.count('tools/call') != before + 1:
            raise AssertionError('Native customer execution or replay failed.')
        with store.tx(readonly=True):
            row = store._execute('SELECT payload FROM workspace_private_tickets WHERE id=%s',
                                 (plan['ticket_id'],)).fetchone()
        claims = json.loads(row[0])
        checks['native_customer_runner_retains_opaque_identity_and_one_call'] = (
            claims['actor_kind'] == 'customer' and claims['actor_user_id'] == login['customer_id']
            and executor.run(*args, result['id'], actor)['output'] == result['output'])
        try:
            staff_executor.execute(*args, {'ticket_id': plan['ticket_id'], 'authorized': True, 'notice': NOTICE}, staff)
        except WorkspaceDenied:
            checks['native_staff_cannot_reuse_customer_execution_ticket'] = True
        else:
            raise AssertionError('Customer ticket entered the staff executor.')

        staff_plan = staff_executor.prepare(*args, {'snapshot_revision': 1}, staff)
        staff_run = staff_executor.execute(*args,
            {'ticket_id': staff_plan['ticket_id'], 'authorized': True, 'notice': NOTICE}, staff)
        if staff_run['status'] != 'succeeded':
            raise AssertionError('Native staff reference run failed.')
        releases = WorkspaceReleases(staff_executor, customer_identity=identity, customer_executor=executor)
        executor.authority_guard = releases.guard_ticket
        release = releases.create(*args, {'run_id': staff_run['id'], 'ttl_seconds': 3600}, staff)
        origin = 'https://native-workspace-app.example'
        deployment = releases.deploy(*args, release['id'], {'allowed_origins': [origin], 'ttl_seconds': 1800,
            'minute_limit': 5, 'day_limit': 20, 'authorized': True, 'notice': DEPLOY_NOTICE}, staff)
        configuration = releases.package_config(*args, deployment['app_id'], staff)
        package, _ = build_package(configuration)
        gateway_app = FastAPI()
        gateway_app.include_router(router_for(releases, WorkspaceLifecycle(staff_executor), admin=False))
        gateway_app.include_router(identity_router(store, store.workflow_key, identity=identity, admin=False))
        with tempfile.TemporaryDirectory(prefix='a2a-native-customer-sdk-', dir='/private/tmp') as folder:
            with ZipFile(BytesIO(package)) as archive:
                if len(archive.namelist()) != 8 or any('/' in name or '..' in name for name in archive.namelist()):
                    raise AssertionError('Only generated flat SDK package files are accepted.')
                for name in archive.namelist():
                    (Path(folder) / name).write_bytes(archive.read(name))
            with TestClient(gateway_app, base_url='https://agentconcierge.biz', raise_server_exceptions=False) as gateway:
                def forward(request):
                    if request.url.scheme != 'https' or request.url.host != 'agentconcierge.biz':
                        raise AssertionError('An unconfigured synthetic gateway was requested.')
                    path = request.url.path + ('?' + request.url.query.decode() if request.url.query else '')
                    response = gateway.request(request.method, path, headers=request.headers, content=request.content)
                    return httpx.Response(response.status_code, content=response.content,
                        headers={key:value for key,value in response.headers.items()
                                 if key not in ('content-length', 'content-encoding', 'transfer-encoding')})
                with httpx.Client(transport=httpx.MockTransport(forward)) as transport:
                    with TestClient(create_app(configuration, app_origin=origin, http=transport, root=folder),
                            base_url=origin, raise_server_exceptions=False) as bff:
                        started = bff.post('/bff/login', headers={'Origin': origin}, json={})
                        if started.status_code != 200:
                            raise AssertionError('Native SDK sign-in preparation failed.')
                        parameters = dict(parse_qsl(urlsplit(started.json()['authorization_url']).query))
                        authorized = gateway.post('/api/workspace-apps-v2/' + deployment['app_id'] + '/authorize',
                            headers={'Origin': 'https://agentconcierge.biz', 'X-Customer-CSRF': identity.csrf(login['session_token']),
                                     'Cookie': '__Host-ac_customer_session=' + login['session_token']}, json=parameters)
                        if authorized.status_code != 200:
                            raise AssertionError('Native SDK customer authorization failed: ' + authorized.text)
                        callback = bff.get('/bff/callback', params={'code': authorized.json()['code'], 'state': parameters['state']}, follow_redirects=False)
                        if callback.status_code != 303:
                            raise AssertionError('Native SDK code exchange failed.')
                        session = bff.get('/bff/session')
                        headers = {'Origin': origin, 'X-App-CSRF': session.json()['csrf_token']}
                        prepared = bff.post('/bff/prepare', headers=headers, json={})
                        if prepared.status_code != 200:
                            raise AssertionError('Native SDK reviewed preparation failed: ' + prepared.text)
                        payload = {'ticket_id': prepared.json()['ticket_id'], 'authorized': True, 'notice': 'workspace-sdk-run-v2'}
                        before = calls.count('tools/call')
                        executed = bff.post('/bff/runs', headers=headers, json=payload)
                        replayed = bff.post('/bff/runs', headers=headers, json=payload)
                        if executed.status_code != 200 or replayed.status_code != 200:
                            raise AssertionError('Native SDK execution failed: ' + executed.text)
                        run = executed.json()['run']
                        if run['status'] != 'succeeded' or calls.count('tools/call') != before + 1:
                            raise AssertionError('Native SDK repeated or failed a provider call.')
                        retained = bff.post('/bff/status', headers=headers, json={'run_id': run['id']})
                        checks['native_sdk2_real_bff_exchange_consent_replay_and_retained_status'] = (
                            retained.status_code == 200 and retained.json()['run']['status'] == 'succeeded'
                            and 'access_token' not in executed.text and 'status_capability' not in executed.text)
                        releases.revoke_deployment(*args, deployment['app_id'], {'revision': 1}, staff)
                        denied = bff.post('/bff/prepare', headers=headers, json={})
                        checks['native_sdk2_deployment_revocation_denies_new_provider_calls'] = (
                            denied.status_code in (400, 403, 404, 409) and calls.count('tools/call') == before + 1)
        if not checks or not all(value is True for value in checks.values()):
            raise AssertionError('A native private customer contract failed.')
        return checks
    finally:
        http.close()
