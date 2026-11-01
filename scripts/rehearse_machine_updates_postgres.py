"""Guarded contracts for the parent-owned synthetic native PostgreSQL fixture.

This helper does not accept a DSN, open a connection, initialize a cluster or
perform provider verification. Its only sender is the in-process receiver below.
"""

import hashlib
from pathlib import Path
import re
import time
from urllib.parse import urlsplit


def run_machine_update_contracts(store, graph, workspace, staff, resource_id, session_token):
    from agent_market.gateway.admin_auth import session_reference
    from agent_market.workspace_access import _canonical, SessionActor, WorkspaceDenied, WorkspaceConflict
    from agent_market.workspace_machine_updates import (MachineUpdates, ConfiguredSender, DeliveryReceipt,
        VerifiedDestination, PURPOSE, SUBSCRIBE_NOTICE, PREPARE_NOTICE, DISPATCH_NOTICE, WITHDRAW_NOTICE,
        RECEIPT_PROFILE, verify_envelope, _signature)
    from agent_market.workspace_machine_receiver import MachineReceiver, ReceiverBinding, ACTIVATE_NOTICE

    connection = getattr(store, '_connection', None)
    host = getattr(getattr(connection, 'info', None), 'host', '')
    from agent_market.postgres_schema_rehearsal import is_owned_store
    owned_cluster = (type(host) is str and Path(host).parent.parent == Path('/private/tmp')
        and Path(host).parent.name.startswith('a2a-adapter-pg-') and Path(host).name == 'socket')
    if (getattr(store, 'backend', None) != 'postgresql' or type(host) is not str
            or not (owned_cluster or is_owned_store(store))
            or connection.autocommit is not True or int(connection.info.transaction_status) != 0
            or graph.access.store is not store or graph.claims.store is not store
            or type(staff) is not SessionActor or type(session_token) is not str
            or not re.fullmatch(r'[0-9a-f]{64}', session_token)
            or staff.session_ref != session_reference(session_token)):
        raise AssertionError('Owned native machine-update fixture required')
    ws = workspace['id']
    resource = store.resource(resource_id)
    parsed = urlsplit(resource['url']) if resource else None
    if (parsed is None or parsed.scheme != 'https' or parsed.hostname != 'typed-0.example'
            or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment):
        raise AssertionError('Exact synthetic provider binding required')
    with graph.access._tx(staff) as (db, _user):
        graph.claims.current(db, ws, resource_id)

    now = time.time()
    proof = VerifiedDestination(ws, 'synthetic_machine_inbox', 'synthetic_machine_audience', 'a2a_inbox',
                                PURPOSE, 1, now, now+300, b'm'*32, 'isolated')

    def check_destination(actual_ws, ref, audience, protocol, purpose, actor):
        if (actual_ws, ref, audience, protocol, purpose, actor) != (
                ws, proof.destination_ref, proof.audience, proof.protocol, PURPOSE, staff):
            raise WorkspaceDenied()
        return proof

    core = MachineUpdates(graph.access, graph.reliability_evidence.get_agent_projection,
                          destination_verifier=check_destination, provider_claims=graph.claims)
    binding = ReceiverBinding(ws, proof.destination_ref, proof.audience, proof.protocol, PURPOSE,
                              1, proof.expires_at, 'isolated', core.envelope_key(proof), proof.receipt_key)
    receiver = MachineReceiver(graph.access, bindings=(binding,), enabled=True)
    authority = receiver.activate(ws, {'destination_ref': proof.destination_ref, 'audience': proof.audience,
        'protocol': proof.protocol, 'ttl_seconds': 300, 'authorized': True, 'notice': ACTIVATE_NOTICE}, staff)
    seen_events, seen_nonces, seen_dedupes, calls = set(), set(), set(), []

    def in_process(destination, raw, signature):
        value = verify_envelope(raw, signature, key=core.envelope_key(destination), audience=destination.audience,
            protocol=destination.protocol, seen_events=seen_events, seen_nonces=seen_nonces, seen_dedupes=seen_dedupes)
        # The public DTO maps a committed in-flight dispatch to unknown; it
        # never exposes a prepared event as already delivered.
        event = next(item for item in core.status(ws, staff)['events'] if item['id'] == value['event_id'])
        if event['state'] != 'unknown' or event['receipt_recorded']:
            raise AssertionError('Dispatch must commit before the fixture sender')
        seen_events.add(value['event_id']); seen_nonces.add(value['nonce']); seen_dedupes.add(value['dedupe_key'])
        calls.append((raw, signature))
        return receiver.receive(authority['id'], raw, signature)

    core.sender = ConfiguredSender(in_process)

    def subscribe():
        return core.subscribe(ws, {'resource_id': resource_id, 'destination_ref': proof.destination_ref,
            'audience': proof.audience, 'protocol': proof.protocol, 'authorized': True, 'notice': SUBSCRIBE_NOTICE}, staff)

    def prepare(subscription):
        return core.prepare(ws, {'subscription_id': subscription['id'], 'authorized': True, 'notice': PREPARE_NOTICE}, staff)

    first = subscribe()
    event = prepare(first)
    command = {'event_id': event['id'], 'authorized': True, 'notice': DISPATCH_NOTICE}
    result = core.dispatch(ws, command, staff)
    if result['state'] != 'accepted' or not result['receipt_recorded'] or result['task_completed']:
        raise AssertionError('Synthetic signed delivery receipt required')
    try:
        core.dispatch(ws, command, staff)
    except (WorkspaceDenied, WorkspaceConflict):
        replay_blocked = True
    else:
        replay_blocked = False
    second = subscribe()
    waiting = prepare(second)
    core.withdraw(ws, {'subscription_id': second['id'], 'authorized': True, 'notice': WITHDRAW_NOTICE}, staff)
    try:
        core.dispatch(ws, {'event_id': waiting['id'], 'authorized': True, 'notice': DISPATCH_NOTICE}, staff)
    except (WorkspaceDenied, WorkspaceConflict):
        withdrawal_blocked = True
    else:
        withdrawal_blocked = False
    if not replay_blocked or not withdrawal_blocked or len(calls) != 1:
        raise AssertionError('Replay and withdrawal must not dispatch another notice')
    raw, signature = calls[0]
    try:
        verify_envelope(raw, signature, key=core.envelope_key(proof), audience=proof.audience, protocol=proof.protocol,
                        seen_events=seen_events, seen_nonces=seen_nonces, seen_dedupes=seen_dedupes)
    except WorkspaceDenied:
        receiver_replay_blocked = True
    else:
        receiver_replay_blocked = False
    if not receiver_replay_blocked:
        raise AssertionError('Receiver replay rejected')
    reopened = MachineReceiver(graph.access, bindings=(binding,), enabled=True)
    try:
        reopened.receive(authority['id'], raw, signature)
    except WorkspaceDenied:
        durable_replay_blocked = True
    else:
        durable_replay_blocked = False
    retained = reopened.status(ws, staff)['receipts']
    if not durable_replay_blocked or len(retained) != 1 or retained[0]['event_id'] != event['id']:
        raise AssertionError('Native receipt was not durably claimed before acknowledgement')
    with store.tx() as db:
        store._execute('INSERT INTO workspace_machine_receiver_restore_blocks VALUES(%s) ON CONFLICT(id) DO NOTHING', (authority['id'],))
    if reopened.status(ws, staff)['authorities'][0]['state'] != 'restore_blocked':
        raise AssertionError('Native receiver restore tombstone failed')

    # Exercise the concrete verified-proof adapter and the HTTPS protocol wrapper
    # against the explicitly mounted private ASGI receiver, with TCP forbidden by
    # the parent harness. No fixture receipt is fabricated by this transport.
    import httpx
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agent_market.workspace_machine_adapters import DestinationBinding, VerifiedWorkflowDestinations, SecureMachineSender
    from agent_market.workspace_machine_receiver_service import router_for
    now = time.time()
    target_proof = VerifiedDestination(ws, 'native_verified_destination', 'native_verified_audience',
        'a2a_inbox', PURPOSE, 1, now, now+300, b'n'*32, 'isolated')
    target_core = MachineUpdates(graph.access, graph.reliability_evidence.get_agent_projection, provider_claims=graph.claims)
    target_receiver = MachineReceiver(graph.access, bindings=(ReceiverBinding(ws, target_proof.destination_ref,
        target_proof.audience, target_proof.protocol, PURPOSE, 1, now+300, 'isolated',
        target_core.envelope_key(target_proof), target_proof.receipt_key),), enabled=True)
    target_authority = target_receiver.activate(ws, {'destination_ref': target_proof.destination_ref,
        'audience': target_proof.audience, 'protocol': target_proof.protocol, 'ttl_seconds': 300,
        'authorized': True, 'notice': ACTIVATE_NOTICE}, staff)
    workflow_id = store.create_workflow({'name': 'Synthetic native verified inbox', 'nodes': [], 'edges': []})
    destination_id = 'wd_'+'9'*32
    target_url = 'https://native-machine-inbox.invalid/private/machine-inbox/'+target_authority['id']
    sealed = graph.runtime._seal({'target': {'url': target_url, 'v1': False}}, destination_id)
    with store.tx():
        store._execute('INSERT INTO workflow_destinations VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (destination_id, workflow_id, 'a2a', sealed, 'verified', None, now+300, 0, now, now, 'workflow-results-v1'))
    destinations = VerifiedWorkflowDestinations(graph.access, graph.runtime, bindings=(DestinationBinding(ws,
        target_proof.destination_ref, target_proof.audience, target_proof.protocol, PURPOSE, 1, workflow_id,
        destination_id, hashlib.sha256(sealed.encode()).hexdigest(), now+300, target_proof.receipt_key, 'isolated'),))
    app = FastAPI()
    app.include_router(router_for(target_receiver, enabled=True, allowed_hosts=('native-machine-inbox.invalid',)))
    transported = []
    with TestClient(app, base_url='https://native-machine-inbox.invalid', raise_server_exceptions=False) as api:
        def transport(request):
            if request.method != 'POST' or str(request.url) != target_url or request.headers.get('cookie') or request.headers.get('authorization'):
                raise AssertionError('Only the exact synthetic proof target may receive this notice')
            transported.append(str(request.url))
            response = api.post(str(request.url), content=request.content, headers=dict(request.headers))
            return httpx.Response(response.status_code, content=response.content, headers=dict(response.headers))
        target_core.destination_verifier = destinations
        target_core.sender = SecureMachineSender(destinations, transport=httpx.MockTransport(transport)).configured()
        target_subscription = target_core.subscribe(ws, {'resource_id': resource_id,
            'destination_ref': target_proof.destination_ref, 'audience': target_proof.audience,
            'protocol': target_proof.protocol, 'authorized': True, 'notice': SUBSCRIBE_NOTICE}, staff)
        target_event = target_core.prepare(ws, {'subscription_id': target_subscription['id'],
            'authorized': True, 'notice': PREPARE_NOTICE}, staff)
        delivered = target_core.dispatch(ws, {'event_id': target_event['id'],
            'authorized': True, 'notice': DISPATCH_NOTICE}, staff)
        if delivered['state'] != 'accepted' or len(transported) != 1:
            raise AssertionError('Concrete native verified proof and signed A2A receipt roundtrip failed')
        if target_receiver.status(ws, staff)['receipts'][0]['event_id'] != target_event['id']:
            raise AssertionError('Native concrete receiver receipt was not persisted')
    return {'machine_current_provider_and_genuine_reliability_source_native': True,
            'machine_commit_before_controlled_signed_delivery_native': True,
            'machine_signed_receipt_confirms_delivery_only_native': True,
            'machine_event_and_receiver_replay_never_resend_native': replay_blocked and receiver_replay_blocked,
            'machine_independent_withdrawal_blocks_prepared_dispatch_native': withdrawal_blocked,
            'machine_external_targets_and_actual_delivery_absent': True,
            'native_machine_receiver_atomic_receipt_and_reopen_replay_blocked': durable_replay_blocked,
            'native_machine_receiver_restore_retains_claim_and_retires_authority': True,
            'native_machine_concrete_verified_proof_secure_a2a_http_roundtrip': True}
