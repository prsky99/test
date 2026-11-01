"""Explicit evidence-update bindings over existing verified workflow inboxes.

The original inbox challenge proves endpoint control only. A separate immutable
server binding and current workspace owner consent authorize this new purpose.
"""

from dataclasses import dataclass
import hashlib
import json
import re

import httpx

from .concierge.http_security import bounded_client, outbound_operation
from .concierge.task_updates import TaskUpdates, UpdateError
from .shadow_ledger import clock, exact
from .workspace_access import (_canonical, _identity, _positive, _rows,
    WorkspaceDenied, WorkspaceInvalid)
from .workspace_machine_updates import (ConfiguredSender, DeliveryReceipt, PURPOSE, PROTOCOLS, TTL,
    VerifiedDestination, _decode, _finite, _opaque)

TRANSPORT_PROFILE = 'machine-evidence-inbox-data-v1'
TRANSPORT_RECEIPT_PROFILE = 'machine-evidence-inbox-receipt-v1'
SIGNATURE_HEADER = 'X-Agent-Evidence-Signature'
RECEIPT_SIGNATURE_HEADER = 'X-Agent-Evidence-Receipt-Signature'
MAX_TRANSPORT_BYTES = 16384


@dataclass(frozen=True, repr=False)
class DestinationBinding:
    workspace_id: str
    destination_ref: str
    audience: str
    protocol: str
    purpose: str
    revision: int
    workflow_id: int
    destination_id: str
    sealed_hash: str
    expires_at: float
    receipt_key: bytes
    environment: str


def _valid_binding(binding):
    if (type(binding) is not DestinationBinding or not _opaque(binding.destination_ref)
            or not _opaque(binding.audience) or binding.protocol not in PROTOCOLS or binding.purpose != PURPOSE
            or not _positive(binding.revision) or not _positive(binding.workflow_id)
            or type(binding.sealed_hash) is not str or not re.fullmatch(r'[a-f0-9]{64}', binding.sealed_hash)
            or not _finite(binding.expires_at) or type(binding.receipt_key) is not bytes
            or not 32 <= len(binding.receipt_key) <= 64
            or binding.environment not in ('isolated', 'sandbox', 'operating')):
        raise WorkspaceInvalid()
    _identity(binding.workspace_id, 'ws'); _identity(binding.destination_id, 'wd')


class VerifiedWorkflowDestinations:
    """Read current existing proof; never send another challenge or infer consent."""
    def __init__(self, access, runtime, *, bindings=()):
        if (runtime.store is not access.store or not callable(getattr(runtime, '_open', None))
                or type(bindings) is not tuple or len(bindings) > 50):
            raise WorkspaceInvalid()
        self.access, self.store, self.runtime, self.bindings = access, access.store, runtime, {}
        for binding in bindings:
            _valid_binding(binding)
            identity = (binding.workspace_id, binding.destination_ref)
            if identity in self.bindings:
                raise WorkspaceInvalid()
            self.bindings[identity] = binding

    def _target(self, binding, db):
        if clock() >= binding.expires_at:
            raise WorkspaceDenied()
        rows = _rows(db, 'SELECT * FROM workflow_destinations WHERE id=? AND workflow_id=?',
                     (binding.destination_id, binding.workflow_id))
        if len(rows) != 1:
            raise WorkspaceDenied()
        row = rows[0]
        expected_channel = 'webhook' if binding.protocol == 'webhook' else 'a2a'
        if (row['state'] != 'verified' or row['channel'] != expected_channel or not row['confirmed']
                or row['notice'] != 'workflow-results-v1' or type(row['sealed']) is not str
                or hashlib.sha256(row['sealed'].encode()).hexdigest() != binding.sealed_hash):
            raise WorkspaceDenied()
        try:
            secret = self.runtime._open(row['sealed'], row['id'])
            target = secret['target']
            if type(target) is not dict or set(target) != {'url', 'v1'} or type(target['v1']) is not bool:
                raise WorkspaceDenied()
            # This profile deliberately supports one synchronous JSON-RPC 0.3
            # data message, not unreviewed streaming, long tasks or A2A 1.0.
            if binding.protocol == 'a2a_inbox' and target['v1']:
                raise WorkspaceDenied()
            TaskUpdates.validate_destination(target['url'])
            return target['url']
        except (KeyError, TypeError, ValueError, UpdateError):
            raise WorkspaceDenied() from None

    def __call__(self, ws, ref, audience, protocol, purpose, actor):
        binding = self.bindings.get((ws, ref))
        if (binding is None or audience != binding.audience or protocol != binding.protocol or purpose != PURPOSE):
            raise WorkspaceDenied()
        with self.access._tx(actor) as (db, _user):
            self.access._access(ws, actor, write=True, owner=True)
            self._target(binding, db)
            now = clock()
            return VerifiedDestination(ws, ref, audience, protocol, PURPOSE, binding.revision, now,
                min(now + TTL, binding.expires_at), binding.receipt_key, binding.environment)

    def resolve(self, destination):
        if type(destination) is not VerifiedDestination:
            raise WorkspaceDenied()
        binding = self.bindings.get((destination.workspace_id, destination.destination_ref))
        now = clock()
        if (binding is None or destination.audience != binding.audience or destination.protocol != binding.protocol
                or destination.purpose != PURPOSE or destination.revision != binding.revision
                or destination.receipt_key != binding.receipt_key or destination.environment != binding.environment
                or not destination.observed_at <= now < destination.expires_at <= min(destination.observed_at + TTL, binding.expires_at)):
            raise WorkspaceDenied()
        with self.store._lock:
            return self._target(binding, self.store._db)


def transport_object(raw, signature):
    envelope = _decode(raw, ('profile', 'workspace_ref', 'event_id', 'subscription_ref', 'subject', 'evidence',
        'reason', 'purpose', 'dedupe_key', 'nonce', 'audience', 'protocol', 'issued_at', 'expires_at'))
    return {'jsonrpc': '2.0', 'id': envelope['event_id'], 'method': 'message/send',
            'params': {'message': {'kind': 'message', 'role': 'user', 'messageId': envelope['event_id'],
                'parts': [{'kind': 'data', 'data': {'profile': TRANSPORT_PROFILE,
                    'envelope': envelope, 'signature': signature}}]}}}


def decode_transport(raw):
    """Strict data-only subset of A2A 0.3 message/send; no task invocation."""
    body = decode_object(raw)
    exact(body, ('jsonrpc', 'id', 'method', 'params'))
    exact(body['params'], ('message',)); message = body['params']['message']
    exact(message, ('kind', 'role', 'messageId', 'parts'))
    if (body['jsonrpc'] != '2.0' or body['method'] != 'message/send' or message['kind'] != 'message'
            or message['role'] != 'user' or type(message['parts']) is not list or len(message['parts']) != 1):
        raise WorkspaceInvalid()
    part = message['parts'][0]; exact(part, ('kind', 'data'))
    exact(part['data'], ('profile', 'envelope', 'signature')); data = part['data']
    if part['kind'] != 'data' or data['profile'] != TRANSPORT_PROFILE:
        raise WorkspaceInvalid()
    encoded = _canonical(data['envelope']).encode('ascii')
    envelope = _decode(encoded, ('profile', 'workspace_ref', 'event_id', 'subscription_ref', 'subject', 'evidence',
        'reason', 'purpose', 'dedupe_key', 'nonce', 'audience', 'protocol', 'issued_at', 'expires_at'))
    if body['id'] != envelope['event_id'] or message['messageId'] != body['id']:
        raise WorkspaceInvalid()
    return encoded, data['signature'], body['id']


def decode_object(raw):
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_TRANSPORT_BYTES:
        raise WorkspaceInvalid()
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError()
            result[key] = value
        return result
    try:
        result = json.loads(raw.decode('ascii'), object_pairs_hook=pairs,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if type(result) is not dict or _canonical(result).encode('ascii') != raw:
            raise WorkspaceInvalid()
        return result
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise WorkspaceInvalid() from None


def transport_receipt(receipt, identity):
    return {'jsonrpc': '2.0', 'id': identity, 'result': {'kind': 'message', 'role': 'agent',
        'messageId': identity, 'parts': [{'kind': 'data', 'data': {'profile': TRANSPORT_RECEIPT_PROFILE,
            'receipt': json.loads(receipt.raw), 'signature': receipt.signature}}]}}


def decode_transport_receipt(raw, identity):
    body = decode_object(raw); exact(body, ('jsonrpc', 'id', 'result'))
    result = body['result']; exact(result, ('kind', 'role', 'messageId', 'parts'))
    if (body['jsonrpc'] != '2.0' or body['id'] != identity or result['messageId'] != identity
            or result['kind'] != 'message' or result['role'] != 'agent'
            or type(result['parts']) is not list or len(result['parts']) != 1):
        raise WorkspaceDenied()
    part = result['parts'][0]; exact(part, ('kind', 'data'))
    exact(part['data'], ('profile', 'receipt', 'signature')); data = part['data']
    if part['kind'] != 'data' or data['profile'] != TRANSPORT_RECEIPT_PROFILE:
        raise WorkspaceDenied()
    return DeliveryReceipt(_canonical(data['receipt']).encode('ascii'), data['signature'])


class SecureMachineSender:
    """One bounded HTTPS request, no redirect, proxy/auth inheritance or retries."""
    def __init__(self, destinations, *, transport=None):
        if (type(destinations) is not VerifiedWorkflowDestinations
                or transport is not None and type(transport) is not httpx.MockTransport):
            raise WorkspaceInvalid()
        if transport is not None and any(value.environment != 'isolated' for value in destinations.bindings.values()):
            raise WorkspaceInvalid()
        self.destinations, self.transport = destinations, transport

    def configured(self):
        return ConfiguredSender(self.send)

    def send(self, destination, raw, signature):
        url = self.destinations.resolve(destination)
        envelope = _decode(raw, ('profile', 'workspace_ref', 'event_id', 'subscription_ref', 'subject', 'evidence',
            'reason', 'purpose', 'dedupe_key', 'nonce', 'audience', 'protocol', 'issued_at', 'expires_at'))
        if (envelope['workspace_ref'] != destination.workspace_id or envelope['audience'] != destination.audience
                or envelope['protocol'] != destination.protocol or envelope['purpose'] != PURPOSE
                or type(signature) is not str or not re.fullmatch(r'v1\.[a-f0-9]{64}', signature)):
            raise WorkspaceDenied()
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json',
                   'Cookie': '', 'Authorization': '', SIGNATURE_HEADER: signature}
        content = raw if destination.protocol == 'webhook' else _canonical(transport_object(raw, signature)).encode('ascii')
        # Test transports are explicitly accepted only for isolated bindings.
        fixture = httpx.Client(transport=self.transport, trust_env=False, follow_redirects=False) if self.transport is not None else None
        client = bounded_client(fixture, timeout=httpx.Timeout(5.0, connect=3.0), limit=MAX_TRANSPORT_BYTES)
        try:
            with outbound_operation(seconds=5):
                response = client.post(url, content=content, headers=headers, auth=None)
            if response.status_code != 200 or response.headers.get('content-type', '').split(';')[0].lower() != 'application/json':
                raise WorkspaceDenied()
            if destination.protocol == 'a2a_inbox':
                return decode_transport_receipt(response.content, envelope['event_id'])
            signatures = response.headers.get_list(RECEIPT_SIGNATURE_HEADER)
            if len(signatures) != 1:
                raise WorkspaceDenied()
            return DeliveryReceipt(response.content, signatures[0])
        finally:
            client.close()
            if fixture is not None:
                fixture.close()
