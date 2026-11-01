"""Signed notice dispatch uses isolated actual claims and an in-process receiver."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import copy
import hashlib
import json
import threading
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from agent_market.workspace_access import _canonical, WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid
from agent_market.workspace_machine_updates import (ConfiguredSender, DeliveryReceipt, MachineUpdates,
    VerifiedDestination, PURPOSE, SUBSCRIBE_NOTICE, PREPARE_NOTICE, DISPATCH_NOTICE, WITHDRAW_NOTICE,
    RECEIPT_PROFILE, _signature, verify_envelope)
from agent_market.workspace_machine_update_service import router_for
from tests.test_provider_claims import provider, prepare as claim_prepare, verify as claim_verify


class Evidence:
    def __init__(self, access):
        self.access = access
        self.value = {'profile': 'bounded-reliability-evidence-v1', 'scope': 'workspace', 'resource_id': 1,
            'agent_ref': 'resource:1', 'agent_version': 'cv_' + '1'*32,
            'schema_hash': '2'*64, 'source_revision': '3'*64,
            'contract_id': None, 'contract_revision': None, 'contract_hash': None,
            'quality_status': 'unassessed', 'source_fidelity': 'unassessable', 'independent_qualified': False,
            'latest_observed_at': None, 'expires_at': None, 'revoked': True, 'environment': None}

    def get_agent_projection(self, ws, rid, actor):
        with self.access._tx(actor):
            self.access._access(ws, actor)
            row = self.access.store._db.execute('SELECT active FROM resources WHERE id=?', (rid,)).fetchone()
            if rid != self.value['resource_id'] or row is None or row['active'] != 1:
                raise WorkspaceDenied()
        return copy.deepcopy(self.value)


class Receiver:
    def __init__(self, core):
        self.core, self.events, self.nonces, self.dedupes, self.calls = core, set(), set(), set(), []
        self.lock = threading.Lock()
        self.fault = None

    def send(self, destination, raw, signature):
        assert not self.core.store._db.in_transaction
        value = verify_envelope(raw, signature, key=self.core.envelope_key(destination),
            audience=destination.audience, protocol=destination.protocol,
            seen_events=self.events, seen_nonces=self.nonces, seen_dedupes=self.dedupes)
        with self.lock:
            assert value['event_id'] not in self.events and value['nonce'] not in self.nonces
            self.events.add(value['event_id']); self.nonces.add(value['nonce'])
            self.dedupes.add(value['dedupe_key'])
            row = self.core.store._db.execute('SELECT state FROM workspace_machine_update_events WHERE id=?', (value['event_id'],)).fetchone()
            assert row['state'] == 'dispatched'
            self.calls.append((raw, signature))
        if self.fault == 'exception':
            raise OSError('Synthetic private transport data must never enter the response')
        if self.fault == 'boolean':
            return True
        receipt = {'profile': RECEIPT_PROFILE, 'event_id': value['event_id'], 'audience': destination.audience,
            'nonce': value['nonce'], 'envelope_hash': hashlib.sha256(raw).hexdigest(),
            'received_at': time.time(), 'status': 'accepted'}
        if self.fault in ('event_id', 'audience', 'nonce', 'envelope_hash'):
            receipt[self.fault] = 'invalid_binding'
        if self.fault == 'time':
            receipt['received_at'] = time.time()+1000
        encoded = _canonical(receipt).encode('ascii')
        signed = _signature(destination.receipt_key, encoded)
        if self.fault == 'signature':
            signed = 'v1.' + '0'*64
        return DeliveryReceipt(encoded, signed)


@pytest.fixture
def machine(provider):
    w = provider
    w.claim = claim_verify(w, claim_prepare(w))
    w.evidence_source = Evidence(w.access)
    observed = time.time()
    w.destination = VerifiedDestination(w.ws, 'configured_inbox', 'audience_fixture', 'a2a_inbox', PURPOSE,
                                       1, observed, observed+300, b'r'*32, 'isolated')
    w.destination_checks = []

    def checker(ws, ref, audience, protocol, purpose, actor):
        w.destination_checks.append((ws, ref, audience, protocol, purpose))
        return w.destination

    w.checker = checker
    w.machine = MachineUpdates(w.access, w.evidence_source, destination_verifier=checker, provider_claims=w.claims)
    w.receiver = Receiver(w.machine)
    w.machine.sender = ConfiguredSender(w.receiver.send)
    app = FastAPI(); app.include_router(router_for(w.machine))
    w.machine_http = TestClient(app, base_url='https://private.test', raise_server_exceptions=False)
    w.machine_base = '/admin/api/workflow-workspaces/' + w.ws + '/machine-updates'
    w.machine_headers = {'X-Dashboard': '1', 'Authorization': 'Bearer ' + w.raw_staff}
    try:
        yield w
    finally:
        w.machine_http.close()


def subscribe(w, **changes):
    return w.machine.subscribe(w.ws, {'resource_id': 1, 'destination_ref': 'configured_inbox',
        'audience': 'audience_fixture', 'protocol': 'a2a_inbox', 'authorized': True, 'notice': SUBSCRIBE_NOTICE,
        **changes}, w.staff[1])


def prepare(w, subscription=None, **changes):
    value = subscription or subscribe(w)
    return w.machine.prepare(w.ws, {'subscription_id': value['id'], 'authorized': True,
                                    'notice': PREPARE_NOTICE, **changes}, w.staff[1])


def dispatch(w, event, **changes):
    return w.machine.dispatch(w.ws, {'event_id': event['id'], 'authorized': True,
                                    'notice': DISPATCH_NOTICE, **changes}, w.staff[1])


def test_neutral_evidence_signed_envelope_receipt_is_delivery_only_and_no_provider_call(machine):
    w = machine; before = len(w.provider_calls)
    sub = subscribe(w); event = prepare(w, sub)
    assert not w.receiver.calls
    result = dispatch(w, event)
    assert result['state'] == 'accepted' and result['receipt_recorded']
    assert result['delivery_receipt_only'] and not result['task_completed']
    raw, signature = w.receiver.calls[0]
    wire = json.loads(raw)
    assert wire['subject']['contract_ref'] is wire['subject']['contract_revision'] is wire['subject']['contract_hash'] is None
    assert wire['evidence']['quality_status'] == 'unassessed' and not wire['evidence']['independent_qualified']
    assert len(w.provider_calls) == before and len(w.destination_checks) == 3
    for marker in ('synthetic.invalid', 'Synthetic member', 'session_ref', 'receipt_key', 'prompt', 'output'):
        assert marker not in raw.decode()
    with pytest.raises(WorkspaceDenied):
        verify_envelope(raw, signature, key=w.machine.envelope_key(w.destination), audience=w.destination.audience,
                        protocol=w.destination.protocol, seen_events=w.receiver.events, seen_nonces=w.receiver.nonces,
                        seen_dedupes=w.receiver.dedupes)
    with pytest.raises(WorkspaceDenied): dispatch(w, event)
    with pytest.raises(WorkspaceConflict): prepare(w, sub)
    assert len(w.receiver.calls) == 1


@pytest.mark.parametrize('missing', ['destination', 'sender', 'provider'])
def test_missing_real_adapters_are_explicit_and_never_created_by_http_authorization(machine, missing):
    w = machine
    if missing == 'destination': w.machine.destination_verifier = None
    elif missing == 'sender': w.machine.sender = None
    else: w.machine.provider_claims = None
    state = w.machine.status(w.ws, w.staff[1])
    key = {'destination': 'destination_verifier_configured', 'sender': 'sender_configured', 'provider': 'provider_claims_configured'}[missing]
    assert not state[key] and not state['actual_target_acceptance']
    if missing == 'sender':
        event = prepare(w)
        with pytest.raises(WorkspaceDenied): dispatch(w, event)
    else:
        with pytest.raises(WorkspaceDenied): subscribe(w)
    assert not w.receiver.calls


@pytest.mark.parametrize('fault', ['dict', 'workspace', 'reference', 'audience', 'protocol', 'purpose', 'expired', 'revision', 'key'])
def test_only_current_typed_purpose_and_destination_bound_proofs_are_eligible(machine, fault):
    w = machine
    updates = {'workspace': {'workspace_id': 'ws_'+'f'*32}, 'reference': {'destination_ref': 'different_ref'},
        'audience': {'audience': 'different_audience'}, 'protocol': {'protocol': 'webhook'},
        'purpose': {'purpose': 'marketing'}, 'expired': {'expires_at': time.time()-1},
        'revision': {'revision': True}, 'key': {'receipt_key': b'short'}}
    w.destination = {} if fault == 'dict' else replace(w.destination, **updates[fault])
    with pytest.raises(WorkspaceDenied): subscribe(w)
    assert not w.receiver.calls


@pytest.mark.parametrize('change', ['session', 'member', 'workspace', 'resource', 'provider', 'provider_expired',
    'agent_version', 'schema', 'contract', 'evidence', 'destination_revision', 'destination_expiry', 'destination_key', 'withdraw', 'restore_subscription', 'restore_event'])
def test_current_pinned_authority_provider_version_evidence_and_destination_rechecked_before_sending(machine, change):
    w = machine; sub = subscribe(w); event = prepare(w, sub)
    with w.store.tx() as db:
        if change == 'session': db.execute('UPDATE admin_sessions SET expires_at=0 WHERE user_id=1')
        elif change == 'member': db.execute('UPDATE workspace_memberships SET revision=revision+1 WHERE workspace_id=?', (w.ws,))
        elif change == 'workspace': db.execute('UPDATE organization_workspaces SET revision=revision+1 WHERE id=?', (w.ws,))
        elif change == 'resource': db.execute('UPDATE resources SET active=0 WHERE id=1')
        elif change == 'provider': db.execute('UPDATE provider_control_claims SET revoked=1 WHERE id=?', (w.claim['id'],))
        elif change == 'provider_expired': db.execute('UPDATE provider_control_claims SET valid_until=0 WHERE id=?', (w.claim['id'],))
        elif change.startswith('restore_'):
            db.execute('INSERT INTO workspace_machine_update_restore_blocks VALUES(?)',
                       (sub['id'] if change == 'restore_subscription' else event['id'],))
    if change == 'agent_version': w.evidence_source.value['agent_version'] = 'cv_'+'4'*32
    elif change == 'schema': w.evidence_source.value['schema_hash'] = '4'*64
    elif change == 'contract': w.evidence_source.value.update(contract_id='docs.search.v1', contract_revision=1, contract_hash='4'*64)
    elif change == 'evidence': w.evidence_source.value['source_revision'] = '4'*64
    elif change == 'destination_revision': w.destination = replace(w.destination, revision=2)
    elif change == 'destination_expiry': w.destination = replace(w.destination, expires_at=time.time()-1)
    elif change == 'destination_key': w.destination = replace(w.destination, receipt_key=b'k'*32)
    elif change == 'withdraw':
        w.machine.withdraw(w.ws, {'subscription_id': sub['id'], 'authorized': True, 'notice': WITHDRAW_NOTICE}, w.staff[1])
    with pytest.raises((WorkspaceDenied, WorkspaceConflict)):
        dispatch(w, event)
    assert not w.receiver.calls


@pytest.mark.parametrize('fault', ['exception', 'boolean', 'signature', 'event_id', 'audience', 'nonce', 'envelope_hash', 'time'])
def test_send_loss_or_unbound_receipt_is_unknown_and_never_automatically_resent(machine, fault):
    w = machine; event = prepare(w); w.receiver.fault = fault
    result = dispatch(w, event)
    assert result['state'] == 'unknown' and not result['receipt_recorded'] and not result['task_completed']
    with pytest.raises(WorkspaceDenied): dispatch(w, event)
    assert len(w.receiver.calls) == 1
    text = json.dumps(w.machine.status(w.ws, w.staff[1]))
    assert 'Synthetic private transport' not in text and 'signature' not in text


def test_final_receipt_persistence_failure_remains_unknown_and_cannot_resend(machine, monkeypatch):
    w = machine; event = prepare(w); save = w.machine._save_event

    def fail_receipt(db, value):
        if value['state'] == 'accepted': raise WorkspaceConflict()
        save(db, value)

    monkeypatch.setattr(w.machine, '_save_event', fail_receipt)
    assert dispatch(w, event)['state'] == 'unknown'
    state = w.machine.status(w.ws, w.staff[1])
    assert state['events'][0]['state'] == 'unknown' and not state['events'][0]['receipt_recorded']
    with pytest.raises(WorkspaceDenied): dispatch(w, event)
    assert len(w.receiver.calls) == 1


def test_destination_proof_expiry_contraction_cannot_extend_a_prepared_notice(machine):
    w = machine; event = prepare(w)
    w.destination = replace(w.destination, expires_at=time.time()+1)
    with pytest.raises(WorkspaceDenied): dispatch(w, event)
    assert not w.receiver.calls


def test_truthful_expired_unassessed_notice_has_fresh_delivery_ttl_without_positive_claim(machine):
    w = machine
    w.evidence_source.value.update(latest_observed_at=time.time()-20, expires_at=time.time()-10)
    event = prepare(w)
    result = dispatch(w, event)
    assert result['state'] == 'accepted' and result['quality_status'] == 'unassessed'
    wire = json.loads(w.receiver.calls[0][0])
    assert wire['reason'] == 'evidence_expired' and wire['expires_at'] > time.time()
    assert wire['evidence']['expires_at'] < time.time() and not wire['evidence']['independent_qualified']


def test_concurrent_fresh_dispatch_commands_have_one_committed_sender(machine):
    w = machine; event = prepare(w)
    def attempt(_):
        try: return dispatch(w, event)['state']
        except (WorkspaceConflict, WorkspaceDenied): return 'blocked'
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(attempt, range(4)))
    assert outcomes.count('accepted') == 1 and outcomes.count('blocked') == 3
    assert len(w.receiver.calls) == 1


def test_receiver_rejects_tamper_audience_nonce_replay_and_expiry_without_mutating_sets(machine):
    w = machine; event = prepare(w)
    with w.access._tx(w.staff[1]) as (db, _):
        wire = w.machine._event(db, w.ws, event['id'])['envelope']
    raw = _canonical(wire).encode(); signed = _signature(w.machine.envelope_key(w.destination), raw)
    base = {'key': w.machine.envelope_key(w.destination), 'audience': w.destination.audience, 'protocol': w.destination.protocol,
            'seen_events': frozenset(), 'seen_nonces': frozenset(), 'seen_dedupes': frozenset()}
    assert verify_envelope(raw, signed, **base)['event_id'] == event['id']
    for changes in ({'audience': 'another_audience'}, {'seen_events': {event['id']}},
                    {'seen_nonces': {wire['nonce']}}, {'seen_dedupes': {wire['dedupe_key']}}, {'now': wire['expires_at']}):
        with pytest.raises(WorkspaceDenied): verify_envelope(raw, signed, **(base | changes))
    altered = raw.replace(wire['nonce'].encode(), ('wmn_'+'0'*32).encode())
    with pytest.raises(WorkspaceDenied): verify_envelope(altered, signed, **base)
    duplicate = b'{"profile":"duplicate",' + raw[1:]
    with pytest.raises(WorkspaceInvalid): verify_envelope(duplicate, _signature(w.machine.envelope_key(w.destination), duplicate), **base)


def test_independent_withdrawal_and_restore_tombstones_allow_only_new_subscriptions(machine):
    w = machine; sub = subscribe(w); event = prepare(w, sub)
    command = {'subscription_id': sub['id'], 'authorized': True, 'notice': WITHDRAW_NOTICE}
    assert w.machine.withdraw(w.ws, command, w.staff[1])['state'] == 'withdrawn'
    assert w.machine.withdraw(w.ws, command, w.staff[1])['state'] == 'withdrawn'
    with pytest.raises(WorkspaceDenied): dispatch(w, event)
    with w.store.tx() as db:
        db.execute('INSERT INTO workspace_machine_update_restore_blocks VALUES(?)', (sub['id'],))
        db.execute('INSERT INTO workspace_machine_update_restore_blocks VALUES(?)', (event['id'],))
    state = w.machine.status(w.ws, w.staff[1])
    assert state['subscriptions'][0]['state'] == state['events'][0]['state'] == 'restore_blocked'
    fresh = subscribe(w)
    assert fresh['id'] != sub['id'] and prepare(w, fresh)['state'] == 'prepared'
    assert not w.receiver.calls


@pytest.mark.parametrize('fields', [{'authorized': False}, {'notice': 'visitor-consent'}, {'protocol': 'mcp'},
    {'destination_ref': 'https://unverified.invalid/inbox'}, {'audience': 'audience@example.test'}, {'resource_id': True}])
def test_exact_subscription_fields_do_not_inherit_visit_watch_or_marketing_permission(machine, fields):
    with pytest.raises(WorkspaceInvalid): subscribe(machine, **fields)
    assert not machine.receiver.calls


def test_api_named_session_csrf_exact_json_and_private_failure_projection(machine):
    w = machine; client, base, headers = w.machine_http, w.machine_base, w.machine_headers
    assert client.get(base+'/status').status_code in (401, 403)
    assert client.get(base+'/status', headers={'X-Dashboard': '1', 'Authorization': 'Bearer machine-token'}).status_code == 401
    result = client.get(base+'/status', headers=headers)
    assert result.status_code == 200 and 'no-store' in result.headers['cache-control']
    assert result.json()['result']['actual_target_acceptance'] is False
    assert client.get(base+'/status?verified=true', headers=headers).status_code == 400
    assert client.post(base+'/subscriptions', headers=headers | {'Origin': 'https://untrusted.invalid'}, json={}).status_code == 403
    duplicate = b'{"resource_id":1,"resource_id":2}'
    assert client.post(base+'/subscriptions', headers=headers | {'Content-Type': 'application/json'}, content=duplicate).status_code == 400
    response = client.post(base+'/subscriptions', headers=headers, json={'resource_id':1,'destination_ref':'configured_inbox',
        'audience':'audience_fixture','protocol':'a2a_inbox','authorized':True,'notice':SUBSCRIBE_NOTICE,'verified':True})
    assert response.status_code == 400
    text = client.get(base+'/status', headers=headers).text
    for marker in ('synthetic.invalid', 'session_ref', 'receipt_key', 'signature', 'Synthetic member'):
        assert marker not in text
    assert not w.receiver.calls


def test_bound_method_source_is_supported_without_weakening_constructor(machine):
    w = machine
    core = MachineUpdates(w.access, w.evidence_source.get_agent_projection, provider_claims=w.claims)
    assert core.status(w.ws, w.staff[1])['destination_verifier_configured'] is False
    with pytest.raises(WorkspaceInvalid): MachineUpdates(w.access, lambda *_: w.evidence_source.value)
    with pytest.raises(WorkspaceInvalid): MachineUpdates(w.access, w.evidence_source, sender=lambda *_: True)
