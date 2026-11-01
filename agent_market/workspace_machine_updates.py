"""Private, purpose-bound evidence notices with explicit one-shot dispatch.

Trusted code supplies current destination verification and delivery adapters.
No visitor permission, advertising permission, public ingress or retry worker is
created here. A receipt confirms delivery only, never business-task completion.
"""

from dataclasses import dataclass
import hashlib
import hmac
import json
import math
import re
import secrets
from typing import Callable

from .shadow_ledger import SignedWorkspaceModule, clock, exact
from .workspace_access import (_canonical, _hash, _identity, _positive, _rows, SessionActor,
    WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid)

PROFILE = 'workspace-machine-evidence-updates-v1'
ENVELOPE_PROFILE = 'machine-evidence-update-envelope-v1'
RECEIPT_PROFILE = 'machine-evidence-delivery-receipt-v1'
PURPOSE = 'evidence_update'
SUBSCRIBE_NOTICE = 'workspace-machine-update-subscribe-v1'
PREPARE_NOTICE = 'workspace-machine-update-prepare-v1'
DISPATCH_NOTICE = 'workspace-machine-update-dispatch-v1'
WITHDRAW_NOTICE = 'workspace-machine-update-withdraw-v1'
PROTOCOLS = ('webhook', 'a2a_inbox')
MAX_SUBSCRIPTIONS, MAX_EVENTS, TTL = 50, 100, 300
SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS workspace_machine_subscriptions (
       id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,created REAL NOT NULL,
       payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS workspace_machine_update_events (
       id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,subscription_id TEXT NOT NULL,
       dedupe_hash TEXT NOT NULL,state TEXT NOT NULL,created REAL NOT NULL,
       payload TEXT NOT NULL,signature TEXT NOT NULL,
       UNIQUE(workspace_id,subscription_id,dedupe_hash))''',
    '''CREATE TABLE IF NOT EXISTS workspace_machine_update_withdrawals (
       subscription_id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,
       payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    'CREATE TABLE IF NOT EXISTS workspace_machine_update_restore_blocks(id TEXT PRIMARY KEY)',
)


@dataclass(frozen=True, repr=False)
class VerifiedDestination:
    """A server adapter's current proof for an already verified destination."""
    workspace_id: str
    destination_ref: str
    audience: str
    protocol: str
    purpose: str
    revision: int
    observed_at: float
    expires_at: float
    receipt_key: bytes
    environment: str


@dataclass(frozen=True, repr=False)
class DeliveryReceipt:
    raw: bytes
    signature: str


@dataclass(frozen=True, repr=False)
class ConfiguredSender:
    """Trusted bounded adapter; callers must implement their own I/O timeout."""
    send: Callable


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _opaque(value):
    return type(value) is str and re.fullmatch(r'[a-z][a-z0-9_]{0,79}', value) is not None


def _digest(value):
    return type(value) is str and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _subject_valid(value):
    neutral = all(value[key] is None for key in ('contract_ref', 'contract_revision', 'contract_hash'))
    return (type(value['agent_ref']) is str and re.fullmatch(r'resource:[1-9][0-9]{0,18}', value['agent_ref'])
            and type(value['version_ref']) is str and re.fullmatch(r'cv_[0-9a-f]{32}', value['version_ref'])
            and _digest(value['schema_hash']) and (neutral or type(value['contract_ref']) is str
                and re.fullmatch(r'[a-z][a-z0-9._-]{0,79}', value['contract_ref'])
                and _positive(value['contract_revision']) and _digest(value['contract_hash'])))


def _evidence_valid(value):
    return (_digest(value['hash']) and value['quality_status'] in ('assessed', 'unassessed')
            and type(value['independent_qualified']) is bool
            and value['source_fidelity'] in ('verified', 'unassessable')
            and value['environment'] in (None, 'synthetic', 'isolated', 'approved_external', 'operating')
            and all(value[key] is None or _finite(value[key]) for key in ('observed_at', 'expires_at')))


def _signature(key, raw):
    return 'v1.' + hmac.new(key, raw, hashlib.sha256).hexdigest()


def _decode(raw, fields):
    if type(raw) is not bytes or not 1 <= len(raw) <= 8192:
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
        exact(result, fields)
        if raw != _canonical(result).encode('ascii'):
            raise WorkspaceInvalid()
        return result
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise WorkspaceInvalid() from None


WIRE_FIELDS = ('profile', 'workspace_ref', 'event_id', 'subscription_ref', 'subject', 'evidence',
               'reason', 'purpose', 'dedupe_key', 'nonce', 'audience', 'protocol', 'issued_at', 'expires_at')
RECEIPT_FIELDS = ('profile', 'event_id', 'audience', 'nonce', 'envelope_hash', 'received_at', 'status')


def verify_envelope(raw, signature, *, key, audience, protocol,
                    seen_events, seen_nonces, seen_dedupes, purpose=PURPOSE, now=None):
    """Pure receiver validation; the receiver atomically records replay keys.

    The returned object contains metadata only. Callers must durably claim its
    event/nonce/dedupe before acknowledging; an in-memory set is only a test fixture.
    """
    if (any(type(value) not in (set, frozenset) or len(value) > 10000
            for value in (seen_events, seen_nonces, seen_dedupes))
            or type(key) is not bytes or len(key) < 32 or type(signature) is not str
            or type(raw) is not bytes or not 1 <= len(raw) <= 8192
            or not hmac.compare_digest(signature, _signature(key, raw))):
        raise WorkspaceDenied()
    value = _decode(raw, WIRE_FIELDS)
    at = clock() if now is None else now
    if (not _finite(at) or value['profile'] != ENVELOPE_PROFILE or value['audience'] != audience
            or value['protocol'] != protocol or protocol not in PROTOCOLS
            or value['purpose'] != purpose or purpose != PURPOSE
            or not _finite(value['issued_at']) or not _finite(value['expires_at'])
            or not value['issued_at'] <= at < value['expires_at'] <= value['issued_at'] + TTL
            or value['event_id'] in seen_events or value['nonce'] in seen_nonces
            or value['dedupe_key'] in seen_dedupes):
        raise WorkspaceDenied()
    _identity(value['workspace_ref'], 'ws'); _identity(value['event_id'], 'wme')
    _identity(value['subscription_ref'], 'wms'); _identity(value['nonce'], 'wmn')
    exact(value['subject'], ('agent_ref', 'version_ref', 'schema_hash', 'contract_ref', 'contract_revision', 'contract_hash'))
    exact(value['evidence'], ('hash', 'observed_at', 'expires_at', 'quality_status',
                              'independent_qualified', 'source_fidelity', 'environment'))
    if (not _opaque(value['audience']) or not _digest(value['dedupe_key'])
            or not _subject_valid(value['subject']) or not _evidence_valid(value['evidence'])
            or value['reason'] not in ('evidence_current', 'evidence_unassessed', 'evidence_expired', 'evidence_revoked')):
        raise WorkspaceInvalid()
    if value['reason'] == 'evidence_current' and (
            value['evidence']['quality_status'] != 'assessed' or not value['evidence']['independent_qualified']
            or value['evidence']['source_fidelity'] != 'verified' or value['subject']['contract_ref'] is None
            or not _finite(value['evidence']['observed_at']) or not _finite(value['evidence']['expires_at'])
            or not value['evidence']['observed_at'] <= at < value['evidence']['expires_at']):
        raise WorkspaceDenied()
    return value


class MachineUpdates(SignedWorkspaceModule):
    def __init__(self, access, evidence_source, *, destination_verifier=None, sender=None, provider_claims=None):
        source = getattr(evidence_source, 'get_agent_projection', evidence_source)
        source_owner = getattr(source, '__self__', None)
        if (not callable(source) or getattr(source_owner, 'access', None) is not access
                or destination_verifier is not None and not callable(destination_verifier)
                or sender is not None and (type(sender) is not ConfiguredSender or not callable(sender.send))
                or provider_claims is not None and (getattr(provider_claims, 'store', None) is not access.store
                    or not callable(getattr(provider_claims, 'current', None)))):
            raise WorkspaceInvalid()
        super().__init__(access, PROFILE, SCHEMA)
        self.evidence_source, self.destination_verifier, self.sender = source, destination_verifier, sender
        self.provider_claims = provider_claims
        self._event_key = hmac.new(self.key, b'envelope-v1', hashlib.sha256).digest()

    def envelope_key(self, destination):
        """Trusted provisioning only: share an exact destination key, never root.

        A receiver holding this symmetric key can authenticate notices only in
        the configured workspace/destination/audience/protocol/revision scope.
        There is no legacy master-key signature fallback on the wire.
        """
        if (type(destination) is not VerifiedDestination or not _opaque(destination.destination_ref)
                or not _opaque(destination.audience) or destination.protocol not in PROTOCOLS
                or destination.purpose != PURPOSE or not _positive(destination.revision)):
            raise WorkspaceInvalid()
        _identity(destination.workspace_id, 'ws')
        context = {'profile': 'machine-evidence-destination-key-v1', 'workspace_id': destination.workspace_id,
                   'destination_ref': destination.destination_ref, 'audience': destination.audience,
                   'protocol': destination.protocol, 'purpose': PURPOSE, 'revision': destination.revision}
        return hmac.new(self._event_key, _canonical(context).encode('ascii'), hashlib.sha256).digest()

    def _owner(self, ws, actor):
        member, user = self.scope(ws, actor, write=True, owner=True)
        return {'actor_user_id': actor.user_id, 'session_ref': actor.session_ref,
                'workspace_revision': member['revision'], 'member_revision': member['member_revision'],
                'user_role': user['role']}

    def _scope_snapshot(self, ws, actor):
        with self.access._tx(actor) as (_, _user):
            return self._owner(ws, actor)

    def _provider(self, db, ws, rid):
        if self.provider_claims is None:
            raise WorkspaceDenied()
        value = self.provider_claims.current(db, ws, rid)
        if (type(value) is not dict or not _positive(value.get('revision'))
                or not _finite(value.get('valid_until')) or value['valid_until'] <= clock()):
            raise WorkspaceDenied()
        _identity(value.get('id'), 'pc')
        return {key: value[key] for key in ('id', 'revision', 'valid_until')}

    def _destination(self, ws, value, actor):
        if self.destination_verifier is None:
            raise WorkspaceDenied()
        try:
            destination = self.destination_verifier(ws, value['destination_ref'], value['audience'],
                                                    value['protocol'], PURPOSE, actor)
        except Exception:
            raise WorkspaceDenied() from None
        now = clock()
        if (type(destination) is not VerifiedDestination or destination.workspace_id != ws
                or destination.destination_ref != value['destination_ref'] or destination.audience != value['audience']
                or destination.protocol != value['protocol'] or destination.purpose != PURPOSE
                or not _positive(destination.revision) or not _finite(destination.observed_at)
                or not _finite(destination.expires_at)
                or not destination.observed_at <= now < destination.expires_at <= destination.observed_at + TTL
                or type(destination.receipt_key) is not bytes or not 32 <= len(destination.receipt_key) <= 64
                or destination.environment not in ('isolated', 'sandbox', 'operating')):
            raise WorkspaceDenied()
        binding = {'destination_ref': destination.destination_ref, 'audience': destination.audience,
                   'protocol': destination.protocol, 'purpose': destination.purpose, 'revision': destination.revision,
                   'environment': destination.environment, 'receipt_key_hash': hashlib.sha256(destination.receipt_key).hexdigest()}
        return destination, binding

    def _evidence(self, ws, rid, actor):
        value = self.evidence_source(ws, rid, actor)
        neutral_contract = (type(value) is dict and value.get('contract_id') is None
                            and value.get('contract_revision') is None and value.get('contract_hash') is None)
        if (type(value) is not dict or value.get('profile') != 'bounded-reliability-evidence-v1'
                or value.get('scope') != 'workspace' or value.get('resource_id') != rid
                or value.get('agent_ref') != 'resource:' + str(rid)
                or type(value.get('agent_version')) is not str
                or not re.fullmatch(r'cv_[0-9a-f]{32}', value['agent_version'])
                or not all(_digest(value.get(key)) for key in ('schema_hash', 'source_revision'))
                or not neutral_contract and (not _digest(value.get('contract_hash'))
                    or type(value.get('contract_revision')) is not int or not 1 <= value['contract_revision'] < 2**63
                    or type(value.get('contract_id')) is not str
                    or not re.fullmatch(r'[a-z][a-z0-9._-]{0,79}', value['contract_id']))
                or value.get('quality_status') not in ('assessed', 'unassessed')
                or value.get('source_fidelity') not in ('verified', 'unassessable')
                or type(value.get('independent_qualified')) is not bool or type(value.get('revoked')) is not bool
                or value.get('environment') not in (None, 'synthetic', 'isolated', 'approved_external', 'operating')
                or any(value.get(key) is not None and not _finite(value[key]) for key in ('latest_observed_at', 'expires_at'))):
            raise WorkspaceDenied()
        if value.get('environment') == 'operating' and value.get('qualified_operating_evidence') is not True:
            raise WorkspaceDenied()
        if value['quality_status'] == 'assessed' and (neutral_contract or not value['independent_qualified']
                or value['source_fidelity'] != 'verified' or not _finite(value['latest_observed_at'])
                or not _finite(value['expires_at'])):
            raise WorkspaceDenied()
        subject = {'agent_ref': value['agent_ref'], 'version_ref': value['agent_version'],
                   'schema_hash': value['schema_hash'], 'contract_ref': value['contract_id'],
                   'contract_revision': value['contract_revision'], 'contract_hash': value['contract_hash']}
        evidence = {'hash': value['source_revision'], 'observed_at': value['latest_observed_at'],
                    'expires_at': value['expires_at'], 'quality_status': value['quality_status'],
                    'independent_qualified': value['independent_qualified'], 'source_fidelity': value['source_fidelity'],
                    'environment': value['environment']}
        reason = ('evidence_expired' if value['expires_at'] is not None and value['expires_at'] <= clock()
                  else 'evidence_unassessed' if value['quality_status'] != 'assessed'
                  else 'evidence_revoked' if value['revoked'] else 'evidence_current')
        return {'subject': subject, 'evidence': evidence, 'reason': reason}

    @staticmethod
    def _authorized_subject(authorized, current):
        # Negative current projections do not erase the separately authorized
        # contract scope. A newly concrete contract requires a new subscription.
        fixed = ('agent_ref', 'version_ref', 'schema_hash')
        contract = ('contract_ref', 'contract_revision', 'contract_hash')
        return (all(authorized[key] == current[key] for key in fixed)
                and (all(authorized[key] == current[key] for key in contract)
                     or all(current[key] is None for key in contract)))

    def _blocked(self, db, identity):
        if db.execute('SELECT 1 FROM workspace_machine_update_restore_blocks WHERE id=?', (identity,)).fetchone():
            raise WorkspaceDenied()

    def _subscription(self, db, ws, identity, *, withdrawn=False):
        _identity(identity, 'wms')
        rows = _rows(db, 'SELECT * FROM workspace_machine_subscriptions WHERE id=? AND workspace_id=?', (identity, ws))
        if len(rows) != 1:
            raise WorkspaceDenied()
        row, value = rows[0], self.opened(rows[0])
        if (value.get('profile') != PROFILE or any(value.get(key) != row[key] for key in ('id', 'workspace_id', 'created'))):
            raise WorkspaceConflict()
        self._blocked(db, identity)
        withdrawals = _rows(db, 'SELECT * FROM workspace_machine_update_withdrawals WHERE subscription_id=?', (identity,))
        if withdrawals:
            tombstone = self.opened(withdrawals[0])
            if (withdrawals[0]['workspace_id'] != ws or tombstone.get('workspace_id') != ws
                    or tombstone.get('subscription_id') != identity):
                raise WorkspaceConflict()
            if not withdrawn:
                raise WorkspaceDenied()
        return value, bool(withdrawals)

    def _event(self, db, ws, identity):
        _identity(identity, 'wme')
        rows = _rows(db, 'SELECT * FROM workspace_machine_update_events WHERE id=? AND workspace_id=?', (identity, ws))
        if len(rows) != 1:
            raise WorkspaceDenied()
        row, value = rows[0], self.opened(rows[0])
        if (value.get('profile') != PROFILE or any(value.get(key) != row[key]
                for key in ('id', 'workspace_id', 'subscription_id', 'dedupe_hash', 'state', 'created'))
                or value['state'] not in ('prepared', 'dispatched', 'accepted', 'unknown', 'superseded')
                or not _positive(value.get('sequence')) or value['sequence'] > MAX_EVENTS):
            raise WorkspaceConflict()
        self._blocked(db, identity)
        return value

    @staticmethod
    def _event_dto(value):
        wire = value['envelope']
        state = 'unknown' if value['state'] == 'dispatched' else value['state']
        if state == 'prepared' and clock() >= wire['expires_at']:
            state = 'expired'
        return {'id': value['id'], 'subscription_id': value['subscription_id'],
                'state': state,
                'created': value['created'], 'expires_at': wire['expires_at'],
                'agent_ref': wire['subject']['agent_ref'], 'agent_version': wire['subject']['version_ref'],
                'reason': wire['reason'], 'quality_status': wire['evidence']['quality_status'],
                'delivery_receipt_only': True, 'task_completed': False,
                'receipt_recorded': value['state'] == 'accepted'}

    def subscribe(self, ws, body, actor):
        exact(body, ('resource_id', 'destination_ref', 'audience', 'protocol', 'authorized', 'notice'))
        if (not _positive(body['resource_id']) or not _opaque(body['destination_ref']) or not _opaque(body['audience'])
                or body['protocol'] not in PROTOCOLS or body['authorized'] is not True or body['notice'] != SUBSCRIBE_NOTICE):
            raise WorkspaceInvalid()
        with self.store._lock:
            owner = self._scope_snapshot(ws, actor)
            _destination, binding = self._destination(ws, body, actor)
            current = self._evidence(ws, body['resource_id'], actor)
            with self.access._tx(actor, write=True) as (db, _user):
                if owner != self._owner(ws, actor):
                    raise WorkspaceConflict()
                provider = self._provider(db, ws, body['resource_id'])
                if db.execute('SELECT COUNT(*) FROM workspace_machine_subscriptions WHERE workspace_id=?', (ws,)).fetchone()[0] >= MAX_SUBSCRIPTIONS:
                    raise WorkspaceConflict()
                now = clock()
                value = {'profile': PROFILE, 'id': 'wms_' + secrets.token_hex(16), 'workspace_id': ws,
                         'resource_id': body['resource_id'], 'destination_ref': body['destination_ref'],
                         'audience': body['audience'], 'protocol': body['protocol'], 'purpose': PURPOSE,
                         'owner': owner, 'destination': binding, 'subject': current['subject'],
                         'provider': provider, 'created': now}
                db.execute('INSERT INTO workspace_machine_subscriptions VALUES(?,?,?,?,?)',
                           (value['id'], ws, now, _canonical(value), self.sign(value)))
                self.access._audit(db, actor, ws, 'machine_updates.subscribe', value['id'], 1)
                return {'id': value['id'], 'destination_ref': value['destination_ref'], 'state': 'active', 'purpose': PURPOSE}

    def prepare(self, ws, body, actor):
        exact(body, ('subscription_id', 'authorized', 'notice'))
        if body['authorized'] is not True or body['notice'] != PREPARE_NOTICE:
            raise WorkspaceInvalid()
        with self.store._lock:
            with self.access._tx(actor) as (db, _user):
                owner = self._owner(ws, actor)
                subscription, _ = self._subscription(db, ws, body['subscription_id'])
                if subscription['owner'] != owner:
                    raise WorkspaceDenied()
            destination, binding = self._destination(ws, subscription, actor)
            current = self._evidence(ws, subscription['resource_id'], actor)
            if binding != subscription['destination'] or not self._authorized_subject(subscription['subject'], current['subject']):
                raise WorkspaceDenied()
            with self.access._tx(actor, write=True) as (db, _user):
                latest, _ = self._subscription(db, ws, subscription['id'])
                if latest != subscription or owner != self._owner(ws, actor):
                    raise WorkspaceConflict()
                provider = self._provider(db, ws, subscription['resource_id'])
                if provider != subscription['provider']:
                    raise WorkspaceDenied()
                events = _rows(db, 'SELECT id FROM workspace_machine_update_events WHERE workspace_id=? ORDER BY created,id LIMIT 101', (ws,))
                if len(events) >= MAX_EVENTS:
                    raise WorkspaceConflict()
                scoped_events = []
                for row in events:
                    try:
                        prior = self._event(db, ws, row['id'])
                    except WorkspaceDenied:
                        continue
                    if prior['subscription_id'] != subscription['id']:
                        continue
                    scoped_events.append(prior)
                    if prior['state'] == 'prepared':
                        if clock() < prior['envelope']['expires_at'] and prior['current_evidence'] == current:
                            raise WorkspaceConflict()
                        prior['state'] = 'superseded'
                        self._save_event(db, prior)
                previous = max(scoped_events, key=lambda value: value['sequence']) if scoped_events else None
                if previous is not None and previous['current_evidence'] == current:
                    raise WorkspaceConflict()
                dedupe = _hash({'subscription_id': subscription['id'], 'destination': binding,
                                'previous_event': previous['id'] if previous else None, **current})
                if db.execute('SELECT 1 FROM workspace_machine_update_events WHERE workspace_id=? AND subscription_id=? AND dedupe_hash=?',
                              (ws, subscription['id'], dedupe)).fetchone():
                    raise WorkspaceConflict()
                now, identity = clock(), 'wme_' + secrets.token_hex(16)
                expires = min(now + TTL, destination.expires_at, provider['valid_until'])
                if current['reason'] == 'evidence_current':
                    expires = min(expires, current['evidence']['expires_at'])
                if now >= expires:
                    raise WorkspaceDenied()
                wire = {'profile': ENVELOPE_PROFILE, 'workspace_ref': ws, 'event_id': identity,
                        'subscription_ref': subscription['id'], **current, 'purpose': PURPOSE,
                        'dedupe_key': dedupe, 'nonce': 'wmn_' + secrets.token_hex(16),
                        'audience': subscription['audience'], 'protocol': subscription['protocol'],
                        'issued_at': now, 'expires_at': expires}
                value = {'profile': PROFILE, 'id': identity, 'workspace_id': ws,
                         'subscription_id': subscription['id'], 'dedupe_hash': dedupe, 'state': 'prepared',
                         'created': now, 'owner': owner, 'destination': binding, 'provider': provider,
                         'sequence': (previous['sequence'] + 1) if previous else 1,
                         'current_evidence': current, 'envelope': wire, 'receipt': None}
                db.execute('INSERT INTO workspace_machine_update_events VALUES(?,?,?,?,?,?,?,?)',
                           (identity, ws, subscription['id'], dedupe, 'prepared', now, _canonical(value), self.sign(value)))
                self.access._audit(db, actor, ws, 'machine_updates.prepare', identity, 1)
                return self._event_dto(value)

    def _save_event(self, db, value):
        db.execute('UPDATE workspace_machine_update_events SET state=?,payload=?,signature=? WHERE id=? AND workspace_id=?',
                   (value['state'], _canonical(value), self.sign(value), value['id'], value['workspace_id']))

    def _receipt(self, destination, event, receipt):
        if (type(receipt) is not DeliveryReceipt or type(receipt.signature) is not str
                or type(receipt.raw) is not bytes or not 1 <= len(receipt.raw) <= 8192
                or not hmac.compare_digest(receipt.signature, _signature(destination.receipt_key, receipt.raw))):
            raise WorkspaceDenied()
        value = _decode(receipt.raw, RECEIPT_FIELDS)
        wire = event['envelope']
        if (value['profile'] != RECEIPT_PROFILE or value['event_id'] != event['id']
                or value['audience'] != wire['audience'] or value['nonce'] != wire['nonce']
                or value['envelope_hash'] != _hash(wire) or value['status'] != 'accepted'
                or not _finite(value['received_at'])
                or not wire['issued_at'] <= value['received_at'] < wire['expires_at']
                or not value['received_at'] <= clock() + 5 or clock() >= wire['expires_at']):
            raise WorkspaceDenied()
        return value

    def dispatch(self, ws, body, actor):
        exact(body, ('event_id', 'authorized', 'notice'))
        if body['authorized'] is not True or body['notice'] != DISPATCH_NOTICE or self.sender is None:
            raise WorkspaceDenied()
        with self.store._lock:
            with self.access._tx(actor) as (db, _user):
                owner = self._owner(ws, actor)
                event = self._event(db, ws, body['event_id'])
                subscription, _ = self._subscription(db, ws, event['subscription_id'])
                if (event['owner'] != owner or subscription['owner'] != owner or event['state'] != 'prepared'
                        or clock() >= event['envelope']['expires_at']):
                    raise WorkspaceDenied()
            destination, binding = self._destination(ws, subscription, actor)
            current = self._evidence(ws, subscription['resource_id'], actor)
            if (binding != event['destination'] or current != event['current_evidence']
                    or not self._authorized_subject(subscription['subject'], current['subject'])
                    or destination.expires_at < event['envelope']['expires_at']):
                raise WorkspaceDenied()
            with self.access._tx(actor, write=True) as (db, _user):
                latest = self._event(db, ws, event['id'])
                self._subscription(db, ws, event['subscription_id'])
                if (latest != event or self._owner(ws, actor) != owner
                        or clock() >= min(event['envelope']['expires_at'], destination.expires_at)):
                    raise WorkspaceConflict()
                provider = self._provider(db, ws, subscription['resource_id'])
                if provider != event['provider'] or provider != subscription['provider']:
                    raise WorkspaceDenied()
                if clock() >= min(event['envelope']['expires_at'], destination.expires_at):
                    raise WorkspaceDenied()
                event['state'] = 'dispatched'
                self._save_event(db, event)
                self.access._audit(db, actor, ws, 'machine_updates.dispatch', event['id'], 1)
        # This committed state is the dispatch boundary. Revocation before it
        # blocks sending; revocation after it cannot recall a notice in flight.
        raw = _canonical(event['envelope']).encode('ascii')
        receipt = None
        try:
            receipt = self._receipt(destination, event,
                self.sender.send(destination, raw, _signature(self.envelope_key(destination), raw)))
        except Exception:
            receipt = None
        try:
            with self.access._tx(actor, write=True) as (db, _user):
                latest = self._event(db, ws, event['id'])
                if latest != event:
                    raise WorkspaceConflict()
                event['state'], event['receipt'] = ('accepted', receipt) if receipt is not None else ('unknown', None)
                self._save_event(db, event)
                self.access._audit(db, actor, ws, 'machine_updates.delivery_receipt' if receipt else 'machine_updates.unknown', event['id'], 1)
        except Exception:
            # A lost DB acknowledgement cannot justify a second network send.
            event['state'], event['receipt'] = 'unknown', None
        return self._event_dto(event)

    def withdraw(self, ws, body, actor):
        exact(body, ('subscription_id', 'authorized', 'notice'))
        if body['authorized'] is not True or body['notice'] != WITHDRAW_NOTICE:
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _user):
            self._owner(ws, actor)
            value, withdrawn = self._subscription(db, ws, body['subscription_id'], withdrawn=True)
            if not withdrawn:
                tombstone = {'profile': PROFILE, 'subscription_id': value['id'], 'workspace_id': ws,
                             'created': clock(), 'actor_user_id': actor.user_id}
                db.execute('INSERT INTO workspace_machine_update_withdrawals VALUES(?,?,?,?)',
                           (value['id'], ws, _canonical(tombstone), self.sign(tombstone)))
                self.access._audit(db, actor, ws, 'machine_updates.withdraw', value['id'], 1)
            return {'id': value['id'], 'state': 'withdrawn', 'future_dispatch_enabled': False}

    def status(self, ws, actor):
        with self.access._tx(actor) as (db, user):
            member, _ = self.scope(ws, actor)
            subscriptions = _rows(db, 'SELECT id FROM workspace_machine_subscriptions WHERE workspace_id=? ORDER BY created DESC,id LIMIT 51', (ws,))
            events = _rows(db, 'SELECT id FROM workspace_machine_update_events WHERE workspace_id=? ORDER BY created DESC,id LIMIT 101', (ws,))
            if len(subscriptions) > MAX_SUBSCRIPTIONS or len(events) > MAX_EVENTS:
                raise WorkspaceConflict()
            items, history = [], []
            for row in subscriptions:
                try:
                    value, withdrawn = self._subscription(db, ws, row['id'], withdrawn=True)
                    state = 'withdrawn' if withdrawn else 'active'
                    if not withdrawn:
                        try:
                            if value.get('automation') is not None:
                                automation = getattr(self, 'automation', None)
                                if automation is None:
                                    raise WorkspaceDenied()
                                automation.current(db, ws, value['id'])
                            else:
                                original_actor = SessionActor(value['owner']['actor_user_id'], value['owner']['session_ref'])
                                if value['owner'] != self._owner(ws, original_actor):
                                    state = 'authorization_changed'
                        except WorkspaceDenied:
                            state = 'authorization_changed'
                    items.append({'id': value['id'], 'resource_id': value['resource_id'],
                                  'destination_ref': value['destination_ref'], 'audience': value['audience'],
                                  'protocol': value['protocol'], 'purpose': PURPOSE,
                                  'authorized_agent_version': value['subject']['version_ref'],
                                  'authorized_contract': {key: value['subject'][key] for key in ('contract_ref', 'contract_revision', 'contract_hash')},
                                  'state': state, 'automatic_grant': value.get('automation')})
                except WorkspaceDenied:
                    items.append({'id': row['id'], 'state': 'restore_blocked'})
            for row in events:
                try:
                    history.append(self._event_dto(self._event(db, ws, row['id'])))
                except WorkspaceDenied:
                    history.append({'id': row['id'], 'state': 'restore_blocked', 'receipt_recorded': False,
                                    'task_completed': False})
            return {'profile': PROFILE, 'subscriptions': items, 'events': history,
                    'can_manage': member['member_role'] == 'owner' and user['role'] != 'operator',
                    'destination_verifier_configured': self.destination_verifier is not None,
                    'provider_claims_configured': self.provider_claims is not None,
                    'sender_configured': self.sender is not None, 'actual_target_acceptance': False,
                    'automatic_dispatch': bool(getattr(getattr(self, 'automation', None), 'enabled', False)),
                    'automatic_grant_notice': 'workspace-evidence-change-delivery-grant-v1',
                    'automatic_worker_failed_ticks': getattr(getattr(self, 'automation', None), 'failed_ticks', 0),
                    'automatic_retry': False, 'advertising_enabled': False,
                    'public_ingress_enabled': False, 'delivery_receipt_only': True, 'task_completed': False,
                    'subscribe_notice': SUBSCRIBE_NOTICE, 'prepare_notice': PREPARE_NOTICE,
                    'dispatch_notice': DISPATCH_NOTICE, 'withdraw_notice': WITHDRAW_NOTICE,
                    'protocols': list(PROTOCOLS), 'admin_usage': 'desktop_only'}
