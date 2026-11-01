"""Secure one-shot adapters roundtrip through the explicit private ASGI inbox."""

from dataclasses import replace
import hashlib
import json
import time
from types import MethodType, SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from agent_market.workflows import WorkflowRuntime
from agent_market.workspace_access import WorkspaceDenied, WorkspaceInvalid
from agent_market.workspace_machine_adapters import (DestinationBinding, VerifiedWorkflowDestinations,
    SecureMachineSender, SIGNATURE_HEADER, TRANSPORT_PROFILE)
from agent_market.workspace_machine_receiver import MachineReceiver, ReceiverBinding, ACTIVATE_NOTICE
from agent_market.workspace_machine_receiver_service import router_for
from agent_market.workspace_machine_updates import PURPOSE, PREPARE_NOTICE
from agent_market.workspace_machine_updates import _signature
from tests.test_workspace_machine_updates import machine, subscribe, prepare, dispatch
from tests.test_provider_claims import provider


@pytest.fixture(params=['webhook', 'a2a_inbox'])
def integrated(machine, request):
    w = machine; w.protocol = request.param
    w.receipt_key = b'd'*32
    rb = ReceiverBinding(w.ws, 'configured_inbox', 'audience_fixture', w.protocol, PURPOSE,
                         1, time.time()+3600, 'isolated', w.machine.envelope_key(replace(w.destination, protocol=w.protocol)), w.receipt_key)
    w.durable_receiver = MachineReceiver(w.access, bindings=(rb,), enabled=True)
    w.receiver_authority = w.durable_receiver.activate(w.ws, {'destination_ref': rb.destination_ref,
        'audience': rb.audience, 'protocol': rb.protocol, 'ttl_seconds': 600,
        'authorized': True, 'notice': ACTIVATE_NOTICE}, w.staff[1])
    app = FastAPI(); app.include_router(router_for(w.durable_receiver, enabled=True, allowed_hosts=('delivery.synthetic.invalid',)))
    w.inbox_http = TestClient(app, base_url='https://delivery.synthetic.invalid', raise_server_exceptions=False)
    w.runtime = SimpleNamespace(store=w.store, key=b'w'*32)
    w.runtime._seal = MethodType(WorkflowRuntime._seal, w.runtime)
    w.runtime._open = MethodType(WorkflowRuntime._open, w.runtime)
    w.destination_id = 'wd_'+'a'*32
    w.destination_url = 'https://delivery.synthetic.invalid/private/machine-inbox/' + w.receiver_authority['id']
    secret = {'target': {'url': w.destination_url, 'v1': False}, 'secret': 'existing-verified-proof-secret'}
    sealed = w.runtime._seal(secret, w.destination_id)
    with w.store._db:
        w.store._db.execute('''CREATE TABLE workflow_destinations (
          id TEXT PRIMARY KEY,workflow_id INTEGER NOT NULL,channel TEXT NOT NULL,sealed TEXT,
          state TEXT NOT NULL,code_hash TEXT,expires REAL NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,
          confirmed REAL,created REAL NOT NULL,notice TEXT NOT NULL)''')
        w.store._db.execute('INSERT INTO workflow_destinations VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (w.destination_id, 1, 'webhook' if w.protocol == 'webhook' else 'a2a', sealed, 'verified', None,
             time.time()+300, 0, time.time(), time.time(), 'workflow-results-v1'))
    w.binding = DestinationBinding(w.ws, 'configured_inbox', 'audience_fixture', w.protocol, PURPOSE,
         1, 1, w.destination_id, hashlib.sha256(sealed.encode()).hexdigest(), time.time()+3600, w.receipt_key, 'isolated')
    w.destinations = VerifiedWorkflowDestinations(w.access, w.runtime, bindings=(w.binding,))
    w.transport_calls, w.fault = [], None
    def handler(req):
        assert not w.store._db.in_transaction
        assert req.method == 'POST' and str(req.url) == w.destination_url
        assert not req.headers.get('authorization') and not req.headers.get('cookie')
        assert req.headers.get('accept-encoding') == 'identity'
        w.transport_calls.append(req)
        if w.fault == 'redirect': return httpx.Response(302, headers={'Location': 'https://other.invalid/inbox'})
        response = w.inbox_http.post(str(req.url), content=req.content, headers=dict(req.headers))
        if w.fault == 'lost_ack': raise httpx.ReadTimeout('Synthetic acknowledgement loss after commit')
        if w.fault == 'bad_receipt': return httpx.Response(200, json={'ok': True})
        return httpx.Response(response.status_code, content=response.content, headers=dict(response.headers))
    w.transport = httpx.MockTransport(handler)
    w.sender = SecureMachineSender(w.destinations, transport=w.transport)
    w.machine.destination_verifier = w.destinations
    w.machine.sender = w.sender.configured()
    try:
        yield w
    finally:
        w.inbox_http.close()


def new_event(w):
    subscription = subscribe(w, protocol=w.protocol)
    return subscription, prepare(w, subscription)


def test_actual_secure_adapter_http_roundtrip_claims_before_receipt_for_both_protocols(integrated):
    w = integrated; before = len(w.provider_calls)
    _subscription, event = new_event(w)
    assert not w.transport_calls
    result = dispatch(w, event)
    assert result['state'] == 'accepted' and result['receipt_recorded'], result
    assert len(w.transport_calls) == 1 and len(w.provider_calls) == before
    claims = w.durable_receiver.status(w.ws, w.staff[1])['receipts']
    assert [value['event_id'] for value in claims] == [event['id']]
    request = w.transport_calls[0]
    wire = json.loads(request.content)
    if w.protocol == 'a2a_inbox':
        assert wire['jsonrpc'] == '2.0' and wire['method'] == 'message/send'
        data = wire['params']['message']['parts'][0]['data']
        assert data['profile'] == TRANSPORT_PROFILE and data['signature'] == request.headers[SIGNATURE_HEADER]
    else:
        assert wire['event_id'] == event['id']
    with pytest.raises(WorkspaceDenied): dispatch(w, event)
    assert len(w.transport_calls) == 1


@pytest.mark.parametrize('fault', ['lost_ack', 'bad_receipt', 'redirect'])
def test_ambiguous_or_invalid_ack_remains_unknown_without_automatic_resend(integrated, fault):
    w = integrated; subscription, event = new_event(w); w.fault = fault
    result = dispatch(w, event)
    assert result['state'] == 'unknown' and not result['receipt_recorded']
    assert len(w.transport_calls) == 1
    receipts = w.durable_receiver.status(w.ws, w.staff[1])['receipts']
    assert len(receipts) == (0 if fault == 'redirect' else 1)
    with pytest.raises(WorkspaceDenied): dispatch(w, event)
    with pytest.raises(Exception) as blocked:
        w.machine.prepare(w.ws, {'subscription_id': subscription['id'], 'authorized': True,
                                'notice': PREPARE_NOTICE}, w.staff[1])
    from agent_market.workspace_access import WorkspaceConflict
    assert isinstance(blocked.value, WorkspaceConflict)
    assert len(w.transport_calls) == 1


@pytest.mark.parametrize('change', ['pending', 'revoked', 'sealed', 'notice', 'channel', 'expiry'])
def test_reused_address_proof_needs_exact_current_binding_and_new_purpose_consent(integrated, change):
    w = integrated
    if change == 'expiry':
        w.destinations.bindings[(w.ws, 'configured_inbox')] = replace(w.binding, expires_at=time.time()-1)
    else:
        field, value = {'pending': ('state', 'pending'), 'revoked': ('state', 'revoked'),
                        'sealed': ('sealed', 'tampered'), 'notice': ('notice', 'marketing'),
                        'channel': ('channel', 'browser')}[change]
        sql = {'state': 'UPDATE workflow_destinations SET state=? WHERE id=?',
               'sealed': 'UPDATE workflow_destinations SET sealed=? WHERE id=?',
               'notice': 'UPDATE workflow_destinations SET notice=? WHERE id=?',
               'channel': 'UPDATE workflow_destinations SET channel=? WHERE id=?'}[field]
        with w.store._db: w.store._db.execute(sql, (value, w.destination_id))
    with pytest.raises(WorkspaceDenied): subscribe(w, protocol=w.protocol)
    assert not w.transport_calls


def test_old_a2a_task_or_v1_profile_and_real_transport_injection_are_not_inferred(integrated):
    w = integrated
    with pytest.raises(WorkspaceInvalid):
        VerifiedWorkflowDestinations(w.access, w.runtime, bindings=(replace(w.binding, purpose='workflow_results'),))
    with pytest.raises(WorkspaceInvalid):
        SecureMachineSender(w.destinations, transport=httpx.HTTPTransport())
    operating = VerifiedWorkflowDestinations(w.access, w.runtime, bindings=(replace(w.binding, environment='operating'),))
    with pytest.raises(WorkspaceInvalid): SecureMachineSender(operating, transport=w.transport)
    assert not w.transport_calls


@pytest.mark.parametrize('component', ['workspace', 'destination', 'audience', 'protocol', 'revision', 'master'])
def test_receiver_key_cannot_authenticate_other_workspace_or_destination_scope(integrated, component):
    w = integrated; _subscription, event = new_event(w)
    with w.access._tx(w.staff[1]) as (db, _):
        value = w.machine._event(db, w.ws, event['id'])
    from agent_market.workspace_access import _canonical
    raw = _canonical(value['envelope']).encode('ascii')
    destination = w.destinations(w.ws, 'configured_inbox', 'audience_fixture', w.protocol, PURPOSE, w.staff[1])
    altered = {'workspace': {'workspace_id': 'ws_'+'9'*32}, 'destination': {'destination_ref': 'other_inbox'},
               'audience': {'audience': 'other_audience'},
               'protocol': {'protocol': 'a2a_inbox' if w.protocol == 'webhook' else 'webhook'},
               'revision': {'revision': 2}}
    key = w.machine._event_key if component == 'master' else w.machine.envelope_key(replace(destination, **altered[component]))
    assert key != w.machine.envelope_key(destination)
    with pytest.raises(WorkspaceDenied):
        w.durable_receiver.receive(w.receiver_authority['id'], raw, _signature(key, raw))
    assert not w.durable_receiver.status(w.ws, w.staff[1])['receipts']
    assert not w.transport_calls
