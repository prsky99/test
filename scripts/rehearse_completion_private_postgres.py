"""Completion paths inside the parent-owned native PostgreSQL fixture only.

No DSN, operating principal, real provider or activation switch is accepted.
The parent supplies its existing Unix-only Store, actors and controlled proxy.
"""
from io import BytesIO
import copy
import hashlib
import json
from pathlib import Path
import re
import time
from types import SimpleNamespace
from zipfile import ZipFile


def _require(value, label):
    if value is not True:
        raise AssertionError(label)


def run_completion_private_contracts(store, graph, identity, login, workspace, staff,
                                     resource_id, session_token):
    from agent_market.gateway.admin_auth import session_reference
    from agent_market.workspace_access import SessionActor

    connection = getattr(store, '_connection', None)
    host = getattr(getattr(connection, 'info', None), 'host', '')
    from agent_market.postgres_schema_rehearsal import is_owned_store
    owned_cluster = (type(host) is str and Path(host).name == 'socket'
        and Path(host).parent.parent == Path('/private/tmp')
        and Path(host).parent.name.startswith('a2a-adapter-pg-'))
    _require(getattr(store, 'backend', None) == 'postgresql'
        and type(host) is str and (owned_cluster or is_owned_store(store))
        and connection.autocommit is True and int(connection.info.transaction_status) == 0
        and graph.access.store is store and identity.store is store
        and type(staff) is SessionActor and type(session_token) is str
        and bool(re.fullmatch('[a-f0-9]{64}', session_token))
        and staff.session_ref == session_reference(session_token)
        and store.workflow_key == b'k'*32, 'Owned completion fixture required')
    resource = store.resource(resource_id)
    _require(resource['url'] == 'https://typed-0.example/mcp', 'Selected synthetic reference required')
    checks = {}
    checks.update(_customer(store, graph, identity, login, resource_id))
    checks.update(_automation(store, graph, workspace['id'], staff, resource_id))
    checks.update(_remote(store, graph, workspace['id'], staff, session_token))
    _require(bool(checks) and all(value is True for value in checks.values()), 'Completion private contracts')
    return checks


def _customer(store, graph, identity, login, resource_id):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agent_market.customer_authoring import authoring_for
    from agent_market.customer_authoring_service import router_for
    from agent_market.customer_identity_service import COOKIE
    from agent_market.customer_workspace_runtime import CustomerWorkspaceAccess
    from agent_market.workspace_execution import WorkspaceExecution, NOTICE
    from agent_market.workspace_release import DEPLOY_NOTICE

    # This is the existing synthetic login, never an integer staff conversion.
    customer = identity.actor(login['session_token'])
    adapter = CustomerWorkspaceAccess(graph.access, identity)
    platform = SimpleNamespace(access=graph.access, identity=identity, execution=graph.execution,
        app_execution=WorkspaceExecution(adapter, graph.execution.proxy), releases=graph.releases)
    core = authoring_for(platform)
    from agent_market.customer_credits import VERSION as CREDIT_VERSION, DIGEST as CREDIT_DIGEST
    # Explicit acceptance belongs only to this disposable synthetic customer.
    core.organizations.drafts.credits.enroll({'version': CREDIT_VERSION, 'digest': CREDIT_DIGEST,
        'terms_accepted': True, 'privacy_acknowledged': True, 'adult_authority': True}, customer)
    workspace = core.organizations.create({'name': 'Native customer authoring'}, customer)
    ws = workspace['id']
    actor = core.actor(ws, customer)
    draft = core.organizations.drafts.save_draft(ws, {'name': 'Native customer documentation',
        'description': 'Synthetic private authoring contract.', 'definition': {'nodes': [
            {'id': 'start', 'name': 'Manual start', 'type': 'trigger', 'kind': 'trigger', 'data': {}},
            {'id': 'lookup', 'name': 'Public documentation', 'type': 'agent', 'kind': 'mcp',
             'resource_id': resource_id, 'data': {'tool': 'search_docs',
                 'input': {'query': 'documentation', 'language': 'en', 'limit': 2}}},
        ], 'edges': [{'source': 'start', 'target': 'lookup'}]}}, actor)
    snapshot = core.organizations.drafts.create_snapshot(ws, draft['id'], {'draft_revision': 1}, actor)
    base = '/api/customer-organizations/'+ws+'/authoring/drafts/'+draft['id']+'/snapshots/'+snapshot['id']
    origin = 'https://agentconcierge.biz'
    csrf = {'Origin': origin, 'X-Customer-CSRF': identity.csrf(login['session_token'])}
    app = FastAPI(); app.include_router(router_for(platform))
    with TestClient(app, base_url=origin, raise_server_exceptions=False) as api:
        api.cookies.set(COOKIE, login['session_token'])
        options = api.get(base+'/options')
        _require(options.status_code == 200, 'Native customer authoring options: '+options.text)
        refused = api.post(base+'/prepare', json={'snapshot_revision': 1})
        _require(refused.status_code == 403, 'Native authoring CSRF boundary')
        prepared = api.post(base+'/prepare', json={'snapshot_revision': 1}, headers=csrf)
        _require(prepared.status_code == 200, 'Native authoring prepare: '+prepared.text)
        command = {'ticket_id': prepared.json()['review']['ticket_id'], 'authorized': True, 'notice': NOTICE}
        executed = api.post(base+'/runs', json=command, headers=csrf)
        _require(executed.status_code == 200 and executed.json()['run']['status'] == 'succeeded',
                 'Native authoring run: '+executed.text)
        replay = api.post(base+'/runs', json=command, headers=csrf)
        _require(replay.status_code == 200 and replay.json()['run']['replayed'] is True,
                 'Native customer authoring idempotent ticket')
        run = executed.json()['run']
        retained = api.get(base+'/runs/'+run['id'])
        released = api.post(base+'/releases', json={'run_id': run['id'], 'ttl_seconds': 600}, headers=csrf)
        _require(released.status_code == 200, 'Native customer authoring release: '+released.text)
        release = released.json()['release']
        deployed = api.post(base+'/releases/'+release['id']+'/deployments', json={
            'allowed_origins': ['https://native-authoring-app.example'], 'ttl_seconds': 600,
            'minute_limit': 2, 'day_limit': 3, 'authorized': True, 'notice': DEPLOY_NOTICE}, headers=csrf)
        _require(deployed.status_code == 200, 'Native customer authoring deployment: '+deployed.text)
        deployment = deployed.json()['deployment']
        exported = api.get(base+'/deployments/'+deployment['app_id']+'/package')
        _require(exported.status_code == 200 and exported.content.startswith(b'PK'), 'Native authoring export')
        with ZipFile(BytesIO(exported.content)) as archive:
            manifest = json.loads(archive.read('app-manifest.json'))
            combined = b'\n'.join(archive.read(name) for name in archive.namelist()).decode()
            _require(manifest['app_id'] == deployment['app_id'] and login['session_token'] not in combined
                and actor.session_ref not in combined and 'access_token' not in archive.read('app-manifest.json').decode(),
                'Native customer package authority isolation')
        _require(retained.status_code == 200 and retained.json()['run']['id'] == run['id']
            and 'no-store' in retained.headers.get('cache-control', ''), 'Native customer retained read')
        revoked = api.post(base+'/releases/'+release['id']+'/revoke', json={'revision': 1}, headers=csrf)
        _require(revoked.status_code == 200 and api.get(base+'/deployments/'+deployment['app_id']+'/package').status_code == 403,
                 'Native customer current release withdrawal')
    with store.tx(readonly=True):
        membership = store._execute('SELECT COUNT(*) FROM workspace_memberships WHERE workspace_id=%s', (ws,)).fetchone()[0]
    _require(membership == 0, 'Customer authoring created staff membership')
    return {'native_customer_authoring_org_draft_snapshot_and_http_consent': True,
        'native_customer_authoring_shared_execution_release_deploy_and_export': True,
        'native_customer_authoring_current_withdrawal_and_no_staff_membership': True}


def _automation(store, graph, ws, staff, resource_id):
    from agent_market.workspace_access import _canonical, WorkspaceDenied
    from agent_market.workspace_machine_updates import MachineUpdates, VerifiedDestination, ConfiguredSender, PURPOSE, SUBSCRIBE_NOTICE
    from agent_market.workspace_machine_receiver import MachineReceiver, ReceiverBinding, ACTIVATE_NOTICE
    from agent_market.workspace_machine_automation import MachineUpdateAutomation, NOTICE

    with graph.access._tx(staff) as (db, _):
        graph.claims.current(db, ws, resource_id)
    base = graph.reliability_evidence.get_agent_projection(ws, resource_id, staff)

    class LocalEvidence:
        """Current local neutral fixture metadata, never operating qualification."""
        def __init__(self):
            self.access = graph.access
            self.value = {**base, 'quality_status': 'unassessed', 'source_fidelity': 'unassessable',
                'independent_qualified': False, 'latest_observed_at': None, 'expires_at': None,
                'revoked': True, 'environment': 'isolated'}

        def current_projection_in_transaction(self, db, actual_ws, rid, actor):
            _require(db.in_transaction, 'Local evidence requires current transaction')
            self.access._access(actual_ws, actor)
            if actual_ws != ws or rid != resource_id:
                raise WorkspaceDenied()
            return copy.deepcopy(self.value)

        def get_agent_projection(self, actual_ws, rid, actor):
            with self.access._tx(actor) as (db, _):
                return self.current_projection_in_transaction(db, actual_ws, rid, actor)

    source = LocalEvidence()
    now = time.time()
    proof = VerifiedDestination(ws, 'native_automatic_metadata', 'native_metadata_audience', 'a2a_inbox',
                                PURPOSE, 1, now, now+300, b'c'*32, 'isolated')
    def destination(actual_ws, ref, audience, protocol, purpose, actor):
        if (actual_ws, ref, audience, protocol, purpose) != (ws, proof.destination_ref, proof.audience, proof.protocol, PURPOSE):
            raise WorkspaceDenied()
        return proof
    core = MachineUpdates(graph.access, source.get_agent_projection, destination_verifier=destination,
                          provider_claims=graph.claims)
    receiver = MachineReceiver(graph.access, bindings=(ReceiverBinding(ws, proof.destination_ref, proof.audience,
        proof.protocol, PURPOSE, 1, now+300, 'isolated', core.envelope_key(proof), proof.receipt_key),), enabled=True)
    authority = receiver.activate(ws, {'destination_ref': proof.destination_ref, 'audience': proof.audience,
        'protocol': proof.protocol, 'ttl_seconds': 300, 'authorized': True, 'notice': ACTIVATE_NOTICE}, staff)
    calls = []
    def sender(actual, raw, signature):
        _require(actual == proof and not store._db.in_transaction, 'Committed controlled metadata dispatch')
        calls.append(raw)
        return receiver.receive(authority['id'], raw, signature)
    core.sender = ConfiguredSender(sender)
    subscription = core.subscribe(ws, {'resource_id': resource_id, 'destination_ref': proof.destination_ref,
        'audience': proof.audience, 'protocol': proof.protocol, 'authorized': True, 'notice': SUBSCRIBE_NOTICE}, staff)
    automatic = MachineUpdateAutomation(core, enabled=True)
    automatic.authorize(ws, {'subscription_id': subscription['id'], 'ttl_seconds': 600,
        'max_events': 2, 'authorized': True, 'notice': NOTICE}, staff)
    first, same = automatic.tick(), automatic.tick()
    _require(first['accepted'] == 1 and same['accepted'] == 0 and len(calls) == 1,
             'Native metadata grant first and unchanged revision')
    source.value['source_revision'] = hashlib.sha256(_canonical([base['source_revision'], 'synthetic-local-change']).encode()).hexdigest()
    changed = automatic.tick()
    _require(changed['accepted'] == 1 and len(calls) == 2, 'Native changed metadata grant')
    source.value['source_revision'] = hashlib.sha256(b'synthetic-next-revision').hexdigest()
    _require(automatic.tick()['accepted'] == 0 and len(calls) == 2, 'Native metadata grant event ceiling')
    for raw in calls:
        wire = json.loads(raw)
        _require(wire['evidence']['independent_qualified'] is False, 'Fixture metadata is not qualification')
    return {'native_machine_automatic_grant_current_local_metadata_and_change': True,
        'native_machine_automatic_receipt_and_revision_dedupe_quota': True,
        'native_machine_automatic_fixture_not_operating_quality_or_external_delivery': True}


def _remote(store, graph, ws, staff, session_token):
    import httpx
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agent_market.capability_registry import Registry
    from agent_market.private_artifact_keys import ArtifactKeys, ArtifactCipher
    from agent_market.workspace_access import WorkspaceDenied
    from agent_market.workspace_remote_a2a import RemoteTasks, TaskBinding, TaskClient, NOTICE, PROFILE
    from agent_market.workspace_remote_a2a_service import router_for
    from tests.test_private_artifact_keys import config

    rid = store.upsert_resource({'key': 'synthetic:completion:remote-a2a', 'source': 'fixture', 'kind': 'a2a',
        'url': 'https://native-task.example/a2a', 'name': 'Native isolated task', 'description': 'Synthetic task lifecycle',
        'category': 'news_media', 'networks': [], 'price_usdc': 0, 'details': {}})
    store.record_health(rid, 'healthy', 200, 1, None, time.time()+3600)
    with store.tx():
        store._execute('UPDATE resources SET auth_observed=%s WHERE id=%s', (0, rid))
    version = Registry(store).current(rid)
    control, calls = {'state': 'working', 'timeout': False}, []
    def provider(request):
        _require(str(request.url) == 'https://native-task.example/a2a' and request.method == 'POST', 'Selected task endpoint')
        body = json.loads(request.content); calls.append(body)
        if control['timeout']:
            raise httpx.ReadTimeout('Synthetic uncertainty', request=request)
        result = {'kind': 'task', 'id': 'native-private-remote-task', 'contextId': 'native-private-context',
                  'status': {'state': control['state']}}
        if control['state'] == 'completed':
            result['artifacts'] = [{'artifactId': 'fixture', 'parts': [{'kind': 'text', 'text': 'Synthetic retained task output'}]}]
        return httpx.Response(200, json={'jsonrpc': '2.0', 'id': body['id'], 'result': result})
    with httpx.Client(transport=httpx.MockTransport(provider)) as http:
        core = RemoteTasks(graph.access, bindings=(TaskBinding(rid, version['id'], TaskClient('https://native-task.example/a2a', http=http)),),
            cipher=ArtifactCipher(PROFILE, ArtifactKeys(config(legacy=True))))
        command = {'logical_id': 'rat_'+'a'*32, 'resource_id': rid, 'version_id': version['id'],
                   'text': 'Synthetic public documentation task', 'authorized': True, 'notice': NOTICE}
        task = core.send(ws, command, staff)
        _require(task['state'] == 'working' and core.send(ws, command, staff)['replayed'] is True and len(calls) == 1,
                 'Native task send logical idempotency')
        control['state'] = 'completed'
        task = core.command(ws, task['id'], {'revision': task['revision'], 'action': 'poll', 'authorized': True, 'notice': NOTICE}, staff)
        _require(task['state'] == 'completed' and task['remote_output_retained'] is True
            and calls[-1]['method'] == 'tasks/get' and calls[-1]['params'] == {'id': 'native-private-remote-task', 'historyLength': 0},
            'Native selected task poll')
        app = FastAPI(); app.include_router(router_for(core))
        headers = {'Authorization': 'Bearer '+session_token, 'X-Dashboard': '1'}
        base = '/admin/api/workflow-workspaces/'+ws+'/remote-a2a/tasks'
        with TestClient(app, base_url='https://agentconcierge.biz', raise_server_exceptions=False) as api:
            retained = api.get(base+'/'+task['id'], headers=headers)
            _require(retained.status_code == 200 and retained.json()['task']['output_preview'] == 'Synthetic retained task output'
                and 'native-private-remote-task' not in retained.text and len(calls) == 2, 'Native task retained HTTP read')
        with store.tx(readonly=True):
            payload = store._execute('SELECT payload FROM workspace_remote_tasks WHERE id=%s', (task['id'],)).fetchone()[0]
        _require('Synthetic public documentation task' not in payload and 'native-private-remote-task' not in payload
            and 'Synthetic retained task output' not in payload, 'Native task private data encryption')
        control['timeout'] = True
        uncertain = core.send(ws, {**command, 'logical_id': 'rat_'+'b'*32}, staff)
        replay = core.send(ws, {**command, 'logical_id': 'rat_'+'b'*32}, staff)
        _require(uncertain['state'] == replay['state'] == 'unknown' and len(calls) == 3, 'Native unknown task no replay')
        with store.tx():
            store._execute('INSERT INTO workspace_remote_task_restore_blocks VALUES(%s)', (task['id'],))
        try:
            core.status(ws, task['id'], staff)
        except WorkspaceDenied:
            pass
        else:
            raise AssertionError('Native restored remote task remained actionable')
        _require(len(calls) == 3, 'Native restore read never sends')
    return {'native_remote_a2a_selected_send_poll_retained_http_and_encryption': True,
        'native_remote_a2a_unknown_logical_replay_never_resends': True,
        'native_remote_a2a_restore_tombstone_blocks_current_access': True}
