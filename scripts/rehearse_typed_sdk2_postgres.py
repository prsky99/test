"""Typed customer SDK 2 contracts for the owned native Unix PG rehearsal only.

No standalone address, credentials, environment activation or external provider
is accepted. The fixed native application harness supplies isolated state.
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


def run_typed_customer_contracts(store, graph, identity, login, workspace, staff, flow, typed_result):
    from agent_market.concierge.proxy import McpProxy
    from agent_market.customer_workspace_runtime import CustomerWorkspaceAccess
    from agent_market.workspace_execution import WorkspaceExecution
    from agent_market.workspace_typed_release import CustomerTypedFlows, WorkspaceTypedReleases, SDK_PROFILE, RUN_NOTICE
    from agent_market.workspace_typed_release_service import router_for
    from agent_market.workspace_release import DEPLOY_NOTICE
    from agent_market.workspace_release_service import build_package
    from agent_market.workspace_sdk_bff import create_app
    from agent_market.customer_identity_service import router_for as identity_router
    from tests.test_workflow_fallback import tool, output
    from tests.test_mcp_proxy import MockRemoteMcp

    if (store.backend != 'postgresql' or store.workflow_key != b'k'*32
            or graph.typed_flows.store is not store or typed_result['run']['status'] != 'succeeded'):
        raise AssertionError('Only the synthetic native application fixture is accepted.')
    checks, calls = {}, []
    def require(value, message):
        if not value: raise AssertionError(message)
    remote = MockRemoteMcp([tool()], call_result=output())
    def provider(request):
        calls.append(json.loads(request.content or b'{}').get('method'))
        return remote.handle_request(request)
    with httpx.Client(transport=httpx.MockTransport(provider)) as provider_http:
        proxy = McpProxy(store, allow_private=True, http=provider_http)
        adapter = CustomerWorkspaceAccess(graph.access, identity)
        executor = WorkspaceExecution(adapter, proxy)
        customer_flows = CustomerTypedFlows(executor)
        releases = WorkspaceTypedReleases(graph.typed_flows, customer_identity=identity, customer_flows=customer_flows)
        customer = identity.actor(login['session_token']); ws = workspace['id']
        # The preceding single-tool helper grants the current exact runner link.
        with identity.tx() as db:
            scope = identity.authorize(db, customer, ws, 'execute')
        require(scope['role'] == 'runner', 'A current exact customer runner link is required.')
        args = (ws, flow['id'], flow['version_id'])
        release = releases.create(*args, {'run_id': typed_result['run']['id'], 'ttl_seconds': 3600}, staff)
        origin = 'https://native-typed-app.example'
        deployment = releases.deploy(*args, release['id'], {'allowed_origins': [origin], 'ttl_seconds': 1800,
            'minute_limit': 5, 'day_limit': 20, 'authorized': True, 'notice': DEPLOY_NOTICE}, staff)
        configuration = releases.package_config(*args, deployment['app_id'], staff)
        require(configuration['profile'] == SDK_PROFILE, 'Typed manifest profile mismatch.')
        package, name = build_package(configuration)
        app = FastAPI(); app.include_router(router_for(releases, admin=False))
        app.include_router(identity_router(store, store.workflow_key, identity=identity, admin=False))
        with tempfile.TemporaryDirectory(prefix='a2a-native-typed-sdk-', dir='/private/tmp') as folder:
            with ZipFile(BytesIO(package)) as archive:
                require(len(archive.namelist()) == 8 and all('/' not in item and '..' not in item for item in archive.namelist()), 'Only a flat bounded ZIP is accepted.')
                combined = b'\n'.join(archive.read(item) for item in archive.namelist()).decode()
                require(login['session_token'] not in combined and staff.session_ref not in combined, 'Customer or staff authority leaked into ZIP.')
                require('Selected prior-output bindings' in archive.read('app-v2.js').decode(), 'Whole-graph review asset is missing.')
                for item in archive.namelist(): (Path(folder)/item).write_bytes(archive.read(item))
            require('typed-sdk-v2' in name, 'Typed download name mismatch.')
            checks['native_typed_sdk2_generated_zip_has_separate_profile_no_embedded_authority'] = True
            with TestClient(app, base_url='https://agentconcierge.biz', raise_server_exceptions=False) as gateway:
                def forward(request):
                    require(request.url.scheme == 'https' and request.url.host == 'agentconcierge.biz', 'Unconfigured gateway destination.')
                    response = gateway.request(request.method, request.url.path, headers=request.headers, content=request.content)
                    return httpx.Response(response.status_code, content=response.content, headers={key: value
                        for key, value in response.headers.items() if key not in ('content-length','content-encoding','transfer-encoding')})
                with httpx.Client(transport=httpx.MockTransport(forward)) as transport, \
                     TestClient(create_app(configuration, app_origin=origin, http=transport, root=folder),
                                base_url=origin, raise_server_exceptions=False) as bff:
                    started = bff.post('/bff/login', headers={'Origin': origin}, json={})
                    require(started.status_code == 200, 'Native typed BFF sign-in preparation failed.')
                    authorization_url = urlsplit(started.json()['authorization_url'])
                    require(authorization_url.path == '/workspace-flow-apps-v2/'+deployment['app_id']+'/authorize', 'Wrong typed authorization namespace.')
                    parameters = dict(parse_qsl(authorization_url.query))
                    authorized = gateway.post('/api/workspace-flow-apps-v2/'+deployment['app_id']+'/authorize',
                        headers={'Origin': 'https://agentconcierge.biz', 'X-Customer-CSRF': identity.csrf(login['session_token']),
                            'Cookie': '__Host-ac_customer_session='+login['session_token']}, json=parameters)
                    require(authorized.status_code == 200, 'Native typed customer authorization failed: '+authorized.text)
                    callback = bff.get('/bff/callback', params={'code': authorized.json()['code'], 'state': parameters['state']}, follow_redirects=False)
                    require(callback.status_code == 303, 'Native typed PKCE exchange failed: '+callback.text)
                    session = bff.get('/bff/session'); headers = {'Origin': origin, 'X-App-CSRF': session.json()['csrf_token']}
                    require('access_token' not in session.text and 'session_ref' not in session.text, 'BFF exposed capabilities.')
                    checks['native_typed_sdk2_customer_code_exchange_and_cookie_session'] = True
                    before = calls.count('tools/call')
                    prepared = bff.post('/bff/prepare', headers=headers, json={})
                    require(prepared.status_code == 200, 'Native typed review failed: '+prepared.text)
                    plan = prepared.json(); review = plan['review']
                    require(plan['profile'] == SDK_PROFILE and plan['notice'] == RUN_NOTICE and review['max_calls'] == 2
                        and review['prior_output_sharing'] and len(review['nodes']) == len(review['destinations']) == 2
                        and calls.count('tools/call') == before, 'Whole-graph review or no-call preparation failed.')
                    body = {'ticket_id': plan['ticket_id'], 'authorized': True, 'notice': RUN_NOTICE}
                    denied = bff.post('/bff/runs', headers=headers, json={**body, 'authorized': False})
                    require(denied.status_code >= 400 and calls.count('tools/call') == before, 'Missing consent called a provider.')
                    checks['native_typed_sdk2_whole_graph_review_and_exact_consent_no_prepare_calls'] = True
                    executed = bff.post('/bff/runs', headers=headers, json=body)
                    require(executed.status_code == 200, 'Native typed execution failed: '+executed.text)
                    run = executed.json()['run']; replayed = bff.post('/bff/runs', headers=headers, json=body)
                    require(run['status'] == 'succeeded' and len(run['steps']) == 2
                        and all(step['status'] == 'succeeded' for step in run['steps'])
                        and replayed.status_code == 200 and replayed.json()['run']['id'] == run['id']
                        and calls.count('tools/call') == before+2, 'Native typed execution duplicated or failed a call.')
                    require('access_token' not in executed.text and 'status_capability' not in executed.text, 'Browser response leaked a capability.')
                    with store.tx(readonly=True) as db:
                        _, claims = customer_flows._ticket(db, ws, flow['id'], plan['ticket_id'])
                    require(claims['actor_kind'] == 'customer' and claims['actor_user_id'] == login['customer_id'], 'Opaque customer attribution changed type.')
                    checks['native_typed_sdk2_two_node_execution_replay_and_opaque_customer_attribution'] = True
                    history = bff.get('/bff/history'); retained = bff.post('/bff/status', headers=headers, json={'run_id': run['id']})
                    require(history.status_code == retained.status_code == 200 and history.json()['runs'][0]['id'] == run['id']
                        and retained.json()['run']['status'] == 'succeeded' and calls.count('tools/call') == before+2,
                        'Native typed retained history/status failed.')
                    checks['native_typed_sdk2_run_scoped_retained_history_and_status'] = True
                    releases.revoke_deployment(*args, deployment['app_id'], {'revision': 1}, staff)
                    denied = bff.post('/bff/prepare', headers=headers, json={})
                    require(denied.status_code >= 400 and calls.count('tools/call') == before+2, 'Revoked typed deployment dispatched a call.')
                    checks['native_typed_sdk2_deployment_revocation_denies_new_calls'] = True
    return checks
