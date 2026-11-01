"""Durable inbox verification uses isolated stores and no external transport."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import copy
import hashlib
import json
import sqlite3
import threading
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from agent_market.workspace_access import WorkspaceAccess, WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid, _canonical
from agent_market.workspace_machine_receiver import (MachineReceiver, ReceiverBinding, ACTIVATE_NOTICE, REVOKE_NOTICE)
from agent_market.workspace_machine_receiver_service import router_for
from agent_market.workspace_machine_adapters import (SIGNATURE_HEADER, RECEIPT_SIGNATURE_HEADER,
    decode_transport_receipt, transport_object)
from agent_market.workspace_machine_updates import ENVELOPE_PROFILE, PURPOSE, _signature
from tests.test_workspace_access import workspace_world, provision


def encoded(value):
    return _canonical(value).encode('ascii')


@pytest.fixture
def inbox(tmp_path):
    path = tmp_path / 'durable-inbox.sqlite3'
    store, access, actors = workspace_world(path)
    ws = provision((store, access, actors))['id']
    binding = ReceiverBinding(ws, 'configured_inbox', 'audience_fixture', 'webhook', PURPOSE,
                              1, time.time() + 3600, 'isolated', b'e'*32, b'r'*32)
    core = MachineReceiver(access, bindings=(binding,), enabled=True)
    grant = core.activate(ws, {'destination_ref': binding.destination_ref, 'audience': binding.audience,
        'protocol': binding.protocol, 'ttl_seconds': 600, 'authorized': True, 'notice': ACTIVATE_NOTICE}, actors[1])
    at = time.time()
    wire = {'profile': ENVELOPE_PROFILE, 'workspace_ref': ws, 'event_id': 'wme_'+'1'*32,
            'subscription_ref': 'wms_'+'2'*32,
            'subject': {'agent_ref': 'resource:1', 'version_ref': 'cv_'+'3'*32, 'schema_hash': '4'*64,
                        'contract_ref': None, 'contract_revision': None, 'contract_hash': None},
            'evidence': {'hash': '5'*64, 'observed_at': None, 'expires_at': None,
                'quality_status': 'unassessed', 'independent_qualified': False,
                'source_fidelity': 'unassessable', 'environment': None},
            'reason': 'evidence_unassessed', 'purpose': PURPOSE, 'dedupe_key': '6'*64,
            'nonce': 'wmn_'+'7'*32, 'audience': binding.audience, 'protocol': binding.protocol,
            'issued_at': at, 'expires_at': at+300}
    result = SimpleNamespace(path=path, store=store, access=access, actors=actors, ws=ws,
                             binding=binding, core=core, grant=grant, wire=wire)
    try:
        yield result
    finally:
        store._db.close()


def receive(w, value=None, **kw):
    raw = encoded(value or w.wire)
    return w.core.receive(w.grant['id'], raw, _signature(w.binding.envelope_key, raw), **kw)


def test_receipt_only_after_durable_commit_and_restart_rejects_replay(inbox):
    w = inbox
    receipt = receive(w)
    assert not w.store._db.in_transaction
    assert receipt.signature == _signature(w.binding.receipt_key, receipt.raw)
    value = json.loads(receipt.raw)
    assert value['event_id'] == w.wire['event_id'] and value['status'] == 'accepted'
    assert value['envelope_hash'] == hashlib.sha256(encoded(w.wire)).hexdigest()
    restarted = MachineReceiver(w.access, bindings=(w.binding,), enabled=True)
    with pytest.raises(WorkspaceDenied):
        restarted.receive(w.grant['id'], encoded(w.wire), _signature(w.binding.envelope_key, encoded(w.wire)))
    state = restarted.status(w.ws, w.actors[1])
    assert len(state['receipts']) == 1 and state['receipts'][0]['delivery_receipt_only']
    assert not state['actual_target_acceptance'] and not state['task_completed']
    data = _canonical(state)
    for secret in ('session_ref', 'receipt_key', 'envelope_key', 'signature', 'dedupe_key', 'nonce', 'prompt', 'output'):
        assert secret not in data


def test_cross_connection_concurrent_receivers_have_one_durable_winner(inbox):
    w = inbox
    other_db = sqlite3.connect(w.path, check_same_thread=False)
    other_db.row_factory = sqlite3.Row
    other_store = SimpleNamespace(_db=other_db, _lock=threading.RLock())
    other_access = WorkspaceAccess(other_store, b'synthetic-workspace-key-32-bytes!!')
    other = MachineReceiver(other_access, bindings=(w.binding,), enabled=True)
    barrier = threading.Barrier(8)
    raw = encoded(w.wire)
    def attempt(index):
        barrier.wait()
        try:
            (w.core if index % 2 else other).receive(w.grant['id'], raw, _signature(w.binding.envelope_key, raw))
            return 'accepted'
        except WorkspaceDenied:
            return 'replay'
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            result = list(pool.map(attempt, range(8)))
        assert result.count('accepted') == 1 and result.count('replay') == 7
        assert w.store._db.execute('SELECT COUNT(*) FROM workspace_machine_receiver_claims').fetchone()[0] == 1
    finally:
        other_db.close()


@pytest.mark.parametrize('reuse', ['event', 'nonce', 'dedupe'])
def test_all_replay_keys_survive_new_authority(inbox, reuse):
    w = inbox; receive(w)
    value = copy.deepcopy(w.wire)
    value.update(event_id='wme_'+'8'*32, nonce='wmn_'+'9'*32, dedupe_key='a'*64)
    key = {'event': 'event_id', 'nonce': 'nonce', 'dedupe': 'dedupe_key'}[reuse]
    value[key] = w.wire[key]
    w.grant = w.core.activate(w.ws, {'destination_ref': w.binding.destination_ref, 'audience': w.binding.audience,
        'protocol': w.binding.protocol, 'ttl_seconds': 600, 'authorized': True, 'notice': ACTIVATE_NOTICE}, w.actors[1])
    value['issued_at'] = time.time()
    value['expires_at'] = value['issued_at'] + 300
    with pytest.raises(WorkspaceDenied): receive(w, value)
    assert len(w.core.status(w.ws, w.actors[1])['receipts']) == 1


@pytest.mark.parametrize('change', ['disabled', 'config', 'receiver_revoke', 'restore', 'member', 'session', 'expiry', 'issuer', 'workspace', 'protocol'])
def test_current_authority_configuration_withdrawal_and_restore_block_before_claim(inbox, change):
    w = inbox
    if change == 'disabled': w.core.enabled = False
    elif change == 'config': w.core.bindings[(w.ws, w.binding.destination_ref)] = replace(w.binding, revision=2)
    elif change == 'receiver_revoke':
        w.core.revoke(w.ws, {'receiver_id': w.grant['id'], 'authorized': True, 'notice': REVOKE_NOTICE}, w.actors[1])
    elif change == 'restore':
        with w.store._db: w.store._db.execute('INSERT INTO workspace_machine_receiver_restore_blocks VALUES(?)', (w.grant['id'],))
    elif change == 'member':
        with w.store._db: w.store._db.execute('UPDATE workspace_memberships SET revision=revision+1 WHERE workspace_id=?', (w.ws,))
    elif change == 'session':
        with w.store._db: w.store._db.execute('DELETE FROM admin_sessions WHERE user_id=1')
    elif change == 'expiry': w.wire['expires_at'] = time.time()-1
    elif change == 'issuer': w.binding = replace(w.binding, envelope_key=b'x'*32)
    elif change == 'workspace': w.wire['workspace_ref'] = 'ws_'+'8'*32
    elif change == 'protocol': w.wire['protocol'] = 'a2a_inbox'
    with pytest.raises(WorkspaceDenied): receive(w)
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_machine_receiver_claims').fetchone()[0] == 0


def test_claim_body_tamper_fails_closed_and_caps_preserve_history(inbox):
    w = inbox; receive(w)
    with w.store._db:
        w.store._db.execute("UPDATE workspace_machine_receiver_claims SET payload='{}'")
    with pytest.raises(WorkspaceConflict): w.core.status(w.ws, w.actors[1])
    with pytest.raises(WorkspaceDenied): receive(w)


def test_fresh_grant_cannot_accept_an_old_unclaimed_packet_after_restore(inbox):
    w = inbox
    old_raw = encoded(w.wire)
    with w.store._db:
        w.store._db.execute('INSERT INTO workspace_machine_receiver_restore_blocks VALUES(?)', (w.grant['id'],))
    w.grant = w.core.activate(w.ws, {'destination_ref': w.binding.destination_ref, 'audience': w.binding.audience,
        'protocol': w.binding.protocol, 'ttl_seconds': 600, 'authorized': True, 'notice': ACTIVATE_NOTICE}, w.actors[1])
    with pytest.raises(WorkspaceDenied):
        w.core.receive(w.grant['id'], old_raw, _signature(w.binding.envelope_key, old_raw))
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_machine_receiver_claims').fetchone()[0] == 0
    w.wire['issued_at'] = time.time(); w.wire['expires_at'] = w.wire['issued_at'] + 300
    assert json.loads(receive(w).raw)['status'] == 'accepted'


def test_disabled_factory_and_missing_configuration_never_enable_ingress(inbox):
    w = inbox
    disabled = MachineReceiver(w.access)
    assert disabled.status(w.ws, w.actors[1])['receiver_enabled'] is False
    assert router_for(disabled).routes == []
    with pytest.raises(WorkspaceInvalid): router_for(disabled, enabled=True, allowed_hosts=('private.test',))
    with pytest.raises(WorkspaceInvalid): MachineReceiver(w.access, enabled='true')
    with pytest.raises(WorkspaceInvalid): MachineReceiver(w.access, bindings=(w.binding, w.binding), enabled=True)
    with pytest.raises(WorkspaceInvalid): MachineReceiver(w.access, bindings=(replace(w.binding, purpose='marketing'),), enabled=True)


def client_for(w):
    app = FastAPI(); app.include_router(router_for(w.core, enabled=True, allowed_hosts=('private.test',)))
    return TestClient(app, base_url='https://private.test', raise_server_exceptions=False)


def test_private_http_signature_transport_no_store_and_replay(inbox):
    w = inbox; raw = encoded(w.wire)
    headers = {'Content-Type': 'application/json', SIGNATURE_HEADER: _signature(w.binding.envelope_key, raw)}
    with client_for(w) as client:
        path = '/private/machine-inbox/' + w.grant['id']
        result = client.post(path, content=raw, headers=headers)
        assert result.status_code == 200, result.text
        assert result.headers[RECEIPT_SIGNATURE_HEADER] == _signature(w.binding.receipt_key, result.content)
        assert 'no-store' in result.headers['cache-control'] and result.headers['x-content-type-options'] == 'nosniff'
        assert client.post(path, content=raw, headers=headers).status_code == 409
        assert client.get(path).status_code == 405
        assert client.get(path + '/status').status_code == 404
        assert not w.core.status(w.ws, w.actors[1])['public_ingress_enabled']


@pytest.mark.parametrize('fault', ['signature', 'origin', 'cookie', 'auth', 'http', 'host', 'query', 'compression', 'type', 'oversize', 'duplicates', 'protocol_wrapper'])
def test_private_http_rejects_untrusted_browser_and_bounded_malformed_inputs(inbox, fault):
    w = inbox; raw = encoded(w.wire)
    headers = {'Content-Type': 'application/json', SIGNATURE_HEADER: _signature(w.binding.envelope_key, raw)}
    path = '/private/machine-inbox/' + w.grant['id']
    if fault == 'signature': headers[SIGNATURE_HEADER] = 'v1.'+'0'*64
    elif fault == 'origin': headers['Origin'] = 'https://private.test'
    elif fault == 'cookie': headers['Cookie'] = 'session=unrelated'
    elif fault == 'auth': headers['Authorization'] = 'Bearer unrelated'
    elif fault == 'http': path = 'http://private.test' + path
    elif fault == 'host': path = 'https://other.test' + path
    elif fault == 'query': path += '?token=unrelated'
    elif fault == 'compression': headers['Content-Encoding'] = 'gzip'
    elif fault == 'type': headers['Content-Type'] = 'text/plain'
    elif fault == 'oversize': raw = b' '*16385
    elif fault == 'duplicates': raw = b'{"profile":1,"profile":2}'
    elif fault == 'protocol_wrapper': raw = encoded(transport_object(raw, headers[SIGNATURE_HEADER]))
    with client_for(w) as client:
        result = client.post(path, content=raw, headers=headers)
        assert 400 <= result.status_code < 500, result.text
        assert 'no-store' in result.headers['cache-control']
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_machine_receiver_claims').fetchone()[0] == 0


def test_a2a_exact_data_message_receipt_and_direct_webhook_mismatch(inbox):
    w = inbox
    w.binding = replace(w.binding, protocol='a2a_inbox')
    w.core = MachineReceiver(w.access, bindings=(w.binding,), enabled=True)
    w.grant = w.core.activate(w.ws, {'destination_ref': w.binding.destination_ref, 'audience': w.binding.audience,
        'protocol': w.binding.protocol, 'ttl_seconds': 600, 'authorized': True, 'notice': ACTIVATE_NOTICE}, w.actors[1])
    w.wire['protocol'] = 'a2a_inbox'
    w.wire['issued_at'] = time.time(); w.wire['expires_at'] = w.wire['issued_at'] + 300
    raw = encoded(w.wire); signed = _signature(w.binding.envelope_key, raw)
    headers = {'Content-Type': 'application/json', SIGNATURE_HEADER: signed}
    with client_for(w) as client:
        path = '/private/machine-inbox/' + w.grant['id']
        assert client.post(path, content=raw, headers=headers).status_code == 409
        result = client.post(path, content=encoded(transport_object(raw, signed)), headers=headers)
        assert result.status_code == 200, result.text
        receipt = decode_transport_receipt(result.content, w.wire['event_id'])
        assert receipt.signature == _signature(w.binding.receipt_key, receipt.raw)
