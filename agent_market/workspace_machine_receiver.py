"""Private durable receipt boundary for a narrowly provisioned machine inbox.

Keys and destinations are server configuration, never request fields. Receipts
acknowledge persisted metadata only. No callback, task execution or retry occurs.
"""

from dataclasses import dataclass
import hashlib
import secrets

from .shadow_ledger import SignedWorkspaceModule, clock, exact
from .workspace_access import (_canonical, _identity, _positive, _rows, SessionActor,
    WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid)
from .workspace_machine_updates import (DeliveryReceipt, PURPOSE, PROTOCOLS, RECEIPT_PROFILE,
    _finite, _opaque, _signature, verify_envelope)

PROFILE = 'workspace-machine-durable-receiver-v1'
ACTIVATE_NOTICE = 'workspace-machine-receiver-activate-v1'
REVOKE_NOTICE = 'workspace-machine-receiver-revoke-v1'
MAX_AUTHORITIES, MAX_CLAIMS, MAX_AUTHORITY_SECONDS = 50, 1000, 86400
SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS workspace_machine_receivers (
       id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,created REAL NOT NULL,
       payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS workspace_machine_receiver_claims (
       event_id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,destination_ref TEXT NOT NULL,
       nonce TEXT NOT NULL,dedupe_key TEXT NOT NULL,received_at REAL NOT NULL,
       payload TEXT NOT NULL,signature TEXT NOT NULL,
       UNIQUE(workspace_id,destination_ref,nonce),UNIQUE(workspace_id,destination_ref,dedupe_key))''',
    'CREATE TABLE IF NOT EXISTS workspace_machine_receiver_restore_blocks(id TEXT PRIMARY KEY)',
)


@dataclass(frozen=True, repr=False)
class ReceiverBinding:
    """Provision an exact issuer/key pair and purpose at a private destination."""
    workspace_id: str
    destination_ref: str
    audience: str
    protocol: str
    purpose: str
    revision: int
    expires_at: float
    environment: str
    envelope_key: bytes
    receipt_key: bytes


def _binding(value):
    if (type(value) is not ReceiverBinding or not _opaque(value.destination_ref)
            or not _opaque(value.audience) or value.protocol not in PROTOCOLS or value.purpose != PURPOSE
            or not _positive(value.revision) or not _finite(value.expires_at)
            or value.environment not in ('isolated', 'sandbox', 'operating')
            or any(type(key) is not bytes or not 32 <= len(key) <= 64
                   for key in (value.envelope_key, value.receipt_key))):
        raise WorkspaceInvalid()
    _identity(value.workspace_id, 'ws')
    return {'workspace_id': value.workspace_id, 'destination_ref': value.destination_ref,
            'audience': value.audience, 'protocol': value.protocol, 'purpose': value.purpose,
            'revision': value.revision, 'expires_at': value.expires_at, 'environment': value.environment,
            'envelope_key_hash': hashlib.sha256(value.envelope_key).hexdigest(),
            'receipt_key_hash': hashlib.sha256(value.receipt_key).hexdigest()}


class MachineReceiver(SignedWorkspaceModule):
    def __init__(self, access, *, bindings=(), enabled=False):
        if type(enabled) is not bool or type(bindings) is not tuple or len(bindings) > MAX_AUTHORITIES:
            raise WorkspaceInvalid()
        self.bindings = {}
        for binding in bindings:
            _binding(binding)
            identity = (binding.workspace_id, binding.destination_ref)
            if identity in self.bindings:
                raise WorkspaceInvalid()
            self.bindings[identity] = binding
        self.enabled = enabled
        super().__init__(access, PROFILE, SCHEMA)

    def _owner(self, ws, actor):
        member, user = self.scope(ws, actor, write=True, owner=True)
        return {'actor_user_id': actor.user_id, 'session_ref': actor.session_ref,
                'workspace_revision': member['revision'], 'member_revision': member['member_revision'],
                'user_role': user['role']}

    def _configured(self, ws, ref):
        value = self.bindings.get((ws, ref))
        if not self.enabled or value is None or clock() >= value.expires_at:
            raise WorkspaceDenied()
        return value

    def _authority(self, db, identity, ws=None):
        _identity(identity, 'wmr')
        rows = _rows(db, 'SELECT * FROM workspace_machine_receivers WHERE id=?', (identity,))
        if len(rows) != 1 or ws is not None and rows[0]['workspace_id'] != ws:
            raise WorkspaceDenied()
        row, value = rows[0], self.opened(rows[0])
        if (value.get('profile') != PROFILE or any(value.get(key) != row[key]
                for key in ('id', 'workspace_id', 'created')) or type(value.get('revoked')) is not bool):
            raise WorkspaceConflict()
        return value

    @staticmethod
    def _dto(value, *, blocked=False):
        return {'id': value['id'], 'destination_ref': value['destination_ref'],
                'audience': value['audience'], 'protocol': value['protocol'], 'purpose': PURPOSE,
                'expires_at': value['expires_at'],
                'state': 'restore_blocked' if blocked else 'revoked' if value['revoked']
                         else 'expired' if clock() >= value['expires_at'] else 'active'}

    def activate(self, ws, body, actor):
        exact(body, ('destination_ref', 'audience', 'protocol', 'ttl_seconds', 'authorized', 'notice'))
        if (body['authorized'] is not True or body['notice'] != ACTIVATE_NOTICE
                or not _opaque(body['destination_ref']) or not _opaque(body['audience'])
                or body['protocol'] not in PROTOCOLS or type(body['ttl_seconds']) is not int
                or not 1 <= body['ttl_seconds'] <= MAX_AUTHORITY_SECONDS):
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _user):
            owner = self._owner(ws, actor)
            binding = self._configured(ws, body['destination_ref'])
            if body['audience'] != binding.audience or body['protocol'] != binding.protocol:
                raise WorkspaceDenied()
            if db.execute('SELECT COUNT(*) FROM workspace_machine_receivers WHERE workspace_id=?', (ws,)).fetchone()[0] >= MAX_AUTHORITIES:
                raise WorkspaceConflict()
            now = clock()
            value = {'profile': PROFILE, 'id': 'wmr_' + secrets.token_hex(16), 'workspace_id': ws,
                     'destination_ref': binding.destination_ref, 'audience': binding.audience,
                     'protocol': binding.protocol, 'purpose': PURPOSE, 'binding': _binding(binding),
                     'owner': owner, 'created': now, 'expires_at': min(now + body['ttl_seconds'], binding.expires_at),
                     'revoked': False}
            db.execute('INSERT INTO workspace_machine_receivers VALUES(?,?,?,?,?)',
                       (value['id'], ws, now, _canonical(value), self.sign(value)))
            self.access._audit(db, actor, ws, 'machine_receiver.activate', value['id'], binding.revision)
            return self._dto(value)

    def receive(self, identity, raw, signature, *, transport_protocol=None):
        """Persist all replay claims in one transaction before returning a receipt.

        An ambiguous commit or a response lost after this method returns never
        permits another acceptance. The sender must retain its unknown outcome.
        """
        if transport_protocol is not None and transport_protocol not in PROTOCOLS:
            raise WorkspaceInvalid()
        with self.store._lock:
            # This preliminary read selects the original principal only. Every
            # authority field is reopened and checked inside the write transaction.
            initial = self._authority(self.store._db, identity)
            actor = SessionActor(initial['owner']['actor_user_id'], initial['owner']['session_ref'])
            with self.access._tx(actor, write=True) as (db, _user):
                authority = self._authority(db, identity)
                ws = authority['workspace_id']
                binding = self._configured(ws, authority['destination_ref'])
                if (authority['revoked'] or clock() >= authority['expires_at']
                        or transport_protocol is not None and transport_protocol != binding.protocol
                        or authority['owner'] != self._owner(ws, actor)
                        or authority['binding'] != _binding(binding)
                        or db.execute('SELECT 1 FROM workspace_machine_receiver_restore_blocks WHERE id=?', (identity,)).fetchone()):
                    raise WorkspaceDenied()
                value = verify_envelope(raw, signature, key=binding.envelope_key,
                    audience=binding.audience, protocol=binding.protocol,
                    seen_events=frozenset(), seen_nonces=frozenset(), seen_dedupes=frozenset())
                if (value['workspace_ref'] != ws or value['issued_at'] < authority['created']):
                    raise WorkspaceDenied()
                # Fixed unique constraints independently protect all three keys,
                # including different receiver authorities and process restarts.
                if (db.execute('SELECT 1 FROM workspace_machine_receiver_claims WHERE event_id=?', (value['event_id'],)).fetchone()
                        or db.execute('SELECT 1 FROM workspace_machine_receiver_claims WHERE workspace_id=? AND destination_ref=? AND nonce=?',
                            (ws, binding.destination_ref, value['nonce'])).fetchone()
                        or db.execute('SELECT 1 FROM workspace_machine_receiver_claims WHERE workspace_id=? AND destination_ref=? AND dedupe_key=?',
                            (ws, binding.destination_ref, value['dedupe_key'])).fetchone()):
                    raise WorkspaceDenied()
                if db.execute('SELECT COUNT(*) FROM workspace_machine_receiver_claims WHERE workspace_id=?', (ws,)).fetchone()[0] >= MAX_CLAIMS:
                    raise WorkspaceConflict()
                now = clock()
                # No callback or I/O exists between this final expiry check and
                # the durable insert. Native receipt time is the claim time.
                if now >= min(value['expires_at'], authority['expires_at'], binding.expires_at):
                    raise WorkspaceDenied()
                receipt = {'profile': RECEIPT_PROFILE, 'event_id': value['event_id'],
                           'audience': binding.audience, 'nonce': value['nonce'],
                           'envelope_hash': hashlib.sha256(raw).hexdigest(), 'received_at': now, 'status': 'accepted'}
                claim = {'profile': PROFILE, 'receiver_id': identity, 'workspace_id': ws,
                         'destination_ref': binding.destination_ref, 'event_id': value['event_id'],
                         'nonce': value['nonce'], 'dedupe_key': value['dedupe_key'], 'received_at': now,
                         'receipt': receipt}
                db.execute('INSERT INTO workspace_machine_receiver_claims VALUES(?,?,?,?,?,?,?,?)',
                    (value['event_id'], ws, binding.destination_ref, value['nonce'], value['dedupe_key'],
                     now, _canonical(claim), self.sign(claim)))
                self.access._audit(db, actor, ws, 'machine_receiver.accept', value['event_id'], binding.revision)
        encoded = _canonical(receipt).encode('ascii')
        return DeliveryReceipt(encoded, _signature(binding.receipt_key, encoded))

    def revoke(self, ws, body, actor):
        exact(body, ('receiver_id', 'authorized', 'notice'))
        if body['authorized'] is not True or body['notice'] != REVOKE_NOTICE:
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _user):
            self._owner(ws, actor)
            value = self._authority(db, body['receiver_id'], ws)
            value['revoked'] = True
            db.execute('UPDATE workspace_machine_receivers SET payload=?,signature=? WHERE id=? AND workspace_id=?',
                       (_canonical(value), self.sign(value), value['id'], ws))
            self.access._audit(db, actor, ws, 'machine_receiver.revoke', value['id'], None)
            return self._dto(value)

    def status(self, ws, actor):
        with self.access._tx(actor) as (db, _user):
            self.scope(ws, actor)
            rows = _rows(db, 'SELECT id FROM workspace_machine_receivers WHERE workspace_id=? ORDER BY created DESC,id LIMIT 51', (ws,))
            claims = _rows(db, 'SELECT * FROM workspace_machine_receiver_claims WHERE workspace_id=? ORDER BY received_at DESC,event_id LIMIT 1001', (ws,))
            if len(rows) > MAX_AUTHORITIES or len(claims) > MAX_CLAIMS:
                raise WorkspaceConflict()
            history = []
            for row in claims:
                value = self.opened(row)
                if (value.get('profile') != PROFILE or any(value.get(key) != row[key] for key in
                        ('workspace_id', 'destination_ref', 'event_id', 'nonce', 'dedupe_key', 'received_at'))):
                    raise WorkspaceConflict()
                history.append({'event_id': value['event_id'], 'receiver_id': value['receiver_id'],
                                'received_at': value['received_at'], 'state': 'accepted',
                                'delivery_receipt_only': True, 'task_completed': False})
            authorities = []
            for row in rows:
                value = self._authority(db, row['id'], ws)
                blocked = bool(db.execute('SELECT 1 FROM workspace_machine_receiver_restore_blocks WHERE id=?', (row['id'],)).fetchone())
                dto = self._dto(value, blocked=blocked)
                if dto['state'] == 'active':
                    try:
                        original = SessionActor(value['owner']['actor_user_id'], value['owner']['session_ref'])
                        if value['owner'] != self._owner(ws, original):
                            dto['state'] = 'authorization_changed'
                        if value['binding'] != _binding(self._configured(ws, value['destination_ref'])):
                            dto['state'] = 'configuration_changed'
                    except WorkspaceDenied:
                        dto['state'] = 'authorization_changed'
                authorities.append(dto)
            current_bindings = sum(binding.workspace_id == ws and clock() < binding.expires_at
                                   for binding in self.bindings.values())
            return {'profile': PROFILE, 'receiver_enabled': self.enabled, 'configured_destinations': current_bindings,
                    'authorities': authorities, 'receipts': history, 'durable_replay_claims': True,
                    'automatic_retry': False, 'public_ingress_enabled': False, 'task_completed': False,
                    'actual_target_acceptance': False, 'activate_notice': ACTIVATE_NOTICE, 'revoke_notice': REVOKE_NOTICE}
