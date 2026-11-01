"""Authenticated TEST_UNIT event ingress with atomic simulated ledger receipts.

The built-in transport is an in-process sandbox. It has no payment client,
network destination, live webhook route, legal assent or payout capability.
"""
import hashlib
import hmac
import json
import math
import re
import secrets

from .shadow_ledger import SignedWorkspaceModule, clock, exact, units
from .workspace_access import (_canonical, _hash, _identity, _rows,
    WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid)
from .workspace_agreements import NOTICE as AGREEMENT_NOTICE

PROFILE = 'workspace-sandbox-payment-events-v1'
PREPARE_NOTICE = 'workspace-sandbox-payment-prepare-v1'
EXECUTE_NOTICE = 'workspace-sandbox-payment-dispatch-v1'
WITHDRAW_NOTICE = 'workspace-sandbox-payment-withdraw-v1'
MAX_EVENTS = 100
TTL = 300
FLAGS = {'environment': 'sandbox', 'simulation': True, 'actual_money': False,
         'payment_enabled': False, 'provider_payout_enabled': False,
         'commercial_enabled': False, 'operating_acceptance': False}
SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS workspace_sandbox_payment_intents (
       id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,event_reference TEXT NOT NULL,
       created REAL NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL,
       UNIQUE(workspace_id,event_reference))''',
    '''CREATE TABLE IF NOT EXISTS workspace_sandbox_payment_receipts (
       intent_id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,event_reference TEXT NOT NULL,
       payload TEXT NOT NULL,signature TEXT NOT NULL,UNIQUE(workspace_id,event_reference))''',
    '''CREATE TABLE IF NOT EXISTS workspace_sandbox_payment_withdrawals (
       intent_id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    'CREATE TABLE IF NOT EXISTS workspace_sandbox_payment_restore_blocks(id TEXT PRIMARY KEY)',
)


def _object(raw):
    if type(raw) is not bytes or not 1 <= len(raw) <= 32768:
        raise WorkspaceInvalid()
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError()
            value[key] = item
        return value
    try:
        result = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        exact(result, ('profile', 'provider', 'environment', 'intent_id', 'workspace_id',
                       'event_reference', 'issued_at', 'expires', 'command'))
        return result
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise WorkspaceInvalid() from None


class SandboxPayments(SignedWorkspaceModule):
    def __init__(self, access, agreements):
        if agreements.access is not access:
            raise WorkspaceInvalid()
        super().__init__(access, PROFILE, SCHEMA)
        self.agreements = agreements
        self._event_key = hmac.new(access.key, (PROFILE + ':wire').encode(), hashlib.sha256).digest()

    def _owner(self, ws, actor):
        member, user = self.scope(ws, actor, write=True, owner=True)
        return {'actor_user_id': actor.user_id, 'session_ref': actor.session_ref,
                'workspace_revision': member['revision'], 'member_revision': member['member_revision'],
                'user_role': user['role']}

    def _intent(self, db, ws, identity):
        _identity(identity, 'wspi')
        rows = _rows(db, 'SELECT * FROM workspace_sandbox_payment_intents WHERE id=? AND workspace_id=?', (identity, ws))
        if len(rows) != 1:
            raise WorkspaceDenied()
        row, value = rows[0], self.opened(rows[0])
        if (value.get('profile') != PROFILE or any(value.get(key) != row[key]
                for key in ('id', 'workspace_id', 'event_reference', 'created'))):
            raise WorkspaceConflict()
        if db.execute('SELECT 1 FROM workspace_sandbox_payment_restore_blocks WHERE id=?', (identity,)).fetchone():
            raise WorkspaceDenied()
        withdrawn = _rows(db, 'SELECT * FROM workspace_sandbox_payment_withdrawals WHERE intent_id=?', (identity,))
        if withdrawn:
            tombstone = self.opened(withdrawn[0])
            if (tombstone.get('intent_id') != identity or tombstone.get('workspace_id') != ws
                    or withdrawn[0]['workspace_id'] != ws):
                raise WorkspaceConflict()
            raise WorkspaceDenied()
        return value

    def _current(self, db, ws, identity, actor):
        value = self._intent(db, ws, identity)
        if value['owner'] != self._owner(ws, actor):
            raise WorkspaceDenied()
        if not clock() < value['expires']:
            raise WorkspaceDenied()
        return value

    def _receipt(self, db, ws, value):
        rows = _rows(db, 'SELECT * FROM workspace_sandbox_payment_receipts WHERE intent_id=?', (value['id'],))
        if not rows:
            return None
        row, receipt = rows[0], self.opened(rows[0])
        if (receipt.get('profile') != PROFILE or receipt.get('intent_id') != value['id']
                or receipt.get('workspace_id') != ws or row['workspace_id'] != ws
                or receipt.get('event_reference') != value['event_reference']
                or row['event_reference'] != value['event_reference']
                or receipt.get('wire_sha256') != hashlib.sha256(self._wire(value)).hexdigest()):
            raise WorkspaceConflict()
        result = receipt.get('result')
        if (type(result) is not dict or any(result.get(key) is not False for key in
                ('actual_money', 'commercial_enabled', 'payment_enabled', 'provider_payout_enabled'))):
            raise WorkspaceConflict()
        current = self.agreements._settlement(db, ws, result['id'])
        events = _rows(db, 'SELECT * FROM workspace_agreement_events WHERE workspace_id=? AND event_reference=?',
                      (ws, value['event_reference']))
        if len(events) != 1 or events[0]['settlement_id'] != result['id']:
            raise WorkspaceConflict()
        event = self.agreements.opened(events[0])
        if (event['kind'] != value['action'] or event['units'] != value['units']
                or result['original'] != current['original'] or result['remaining'] != event['remaining_after']
                or result['agreement_id'] != current['agreement_id']):
            raise WorkspaceConflict()
        return receipt

    @staticmethod
    def _dto(value):
        return {key: value[key] for key in ('id', 'event_reference', 'action', 'target_id',
                'units', 'created', 'expires')} | FLAGS

    def prepare(self, ws, body, actor):
        exact(body, ('action', 'target_id', 'event_reference', 'units', 'revision', 'authorized', 'notice'))
        if (body['action'] not in ('capture', 'refund') or type(body['event_reference']) is not str
                or not re.fullmatch(r'sim_[A-Za-z0-9_-]{1,64}', body['event_reference'])
                or type(body['revision']) is not int or not 1 <= body['revision'] < 2**53
                or body['authorized'] is not True or body['notice'] != PREPARE_NOTICE):
            raise WorkspaceInvalid()
        units(body['units']); _identity(body['target_id'], 'wpa' if body['action'] == 'capture' else 'was')
        with self.access._tx(actor, write=True) as (db, _):
            owner = self._owner(ws, actor)
            request_hash = _hash(body)
            previous = _rows(db, 'SELECT id FROM workspace_sandbox_payment_intents WHERE workspace_id=? AND event_reference=?', (ws, body['event_reference']))
            if previous:
                value = self._current(db, ws, previous[0]['id'], actor)
                if value['request_hash'] != request_hash:
                    raise WorkspaceConflict()
                return self._dto(value) | {'replayed': True}
            if db.execute('SELECT COUNT(*) FROM workspace_sandbox_payment_intents WHERE workspace_id=?', (ws,)).fetchone()[0] >= MAX_EVENTS:
                raise WorkspaceConflict()
            if body['action'] == 'capture':
                contract, state = self.agreements._current(db, ws, body['target_id'], actor)
                if state['revision'] != body['revision']:
                    raise WorkspaceConflict()
                quote = self.agreements._quote(contract, body['units'])
                command = {'event_reference': body['event_reference'], 'gross_units': body['units'],
                           'quote_hash': quote['quote_hash'], 'revision': body['revision'],
                           'authorized': True, 'notice': AGREEMENT_NOTICE}
            else:
                settlement = self.agreements._settlement(db, ws, body['target_id'])
                self.agreements._current(db, ws, settlement['agreement_id'], actor, admission=False)
                if settlement['revision'] != body['revision'] or body['units'] > settlement['remaining']['gross_units']:
                    raise WorkspaceConflict()
                command = {'event_reference': body['event_reference'], 'units': body['units'],
                           'revision': body['revision'], 'authorized': True, 'notice': AGREEMENT_NOTICE}
            now = clock()
            value = {'profile': PROFILE, 'id': 'wspi_' + secrets.token_hex(16), 'workspace_id': ws,
                     'event_reference': body['event_reference'], 'action': body['action'],
                     'target_id': body['target_id'], 'units': body['units'], 'created': now,
                     'expires': now + TTL, 'owner': owner, 'request_hash': request_hash, 'command': command}
            db.execute('INSERT INTO workspace_sandbox_payment_intents VALUES(?,?,?,?,?,?)',
                (value['id'], ws, value['event_reference'], now, _canonical(value), self.sign(value)))
            self.access._audit(db, actor, ws, 'sandbox_payment.prepare', value['id'], None)
            return self._dto(value) | {'replayed': False}

    def _wire(self, value):
        wire = {'profile': PROFILE, 'provider': 'agent-concierge-sandbox', 'environment': 'sandbox',
                'intent_id': value['id'], 'workspace_id': value['workspace_id'],
                'event_reference': value['event_reference'], 'issued_at': value['created'],
                'expires': value['expires'], 'command': value['command']}
        return _canonical(wire).encode()

    def _signature(self, raw):
        return 'v1.' + hmac.new(self._event_key, raw, hashlib.sha256).hexdigest()

    def ingest(self, raw, signature, actor):
        """Trusted transport entry point; never mounted as a public webhook."""
        if (type(signature) is not str or not re.fullmatch(r'v1\.[0-9a-f]{64}', signature)
                or type(raw) is not bytes or not 1 <= len(raw) <= 32768
                or not hmac.compare_digest(signature, self._signature(raw))):
            raise WorkspaceDenied()
        wire = _object(raw); now = clock()
        if (wire['profile'] != PROFILE or wire['provider'] != 'agent-concierge-sandbox'
                or wire['environment'] != 'sandbox'
                or any(type(wire[key]) not in (int, float) or not math.isfinite(wire[key]) for key in ('issued_at', 'expires'))
                or not 0 < wire['issued_at'] <= now + 5 or not now < wire['expires'] <= wire['issued_at'] + TTL):
            raise WorkspaceDenied()
        ws, identity = wire['workspace_id'], wire['intent_id']
        with self.access._tx(actor) as (db, _):
            value = self._current(db, ws, identity, actor)
            if self._wire(value) != raw:
                raise WorkspaceDenied()
        wire_hash, captured = hashlib.sha256(raw).hexdigest(), []
        def receipt(db, result):
            current = self._current(db, ws, identity, actor)
            if self._wire(current) != raw:
                raise WorkspaceDenied()
            old = self._receipt(db, ws, current)
            if old:
                captured.append(old['result'] | {'replayed': True})
                return
            stored = {'profile': PROFILE, 'intent_id': identity, 'workspace_id': ws,
                      'event_reference': wire['event_reference'], 'wire_sha256': wire_hash,
                      'recorded': clock(), 'result': {k:v for k,v in result.items() if k != 'replayed'}}
            db.execute('INSERT INTO workspace_sandbox_payment_receipts VALUES(?,?,?,?,?)',
                (identity, ws, wire['event_reference'], _canonical(stored), self.sign(stored)))
            self.access._audit(db, actor, ws, 'sandbox_payment.receive', identity, None)
            captured.append(stored['result'] | {'replayed': False})
        action = self.agreements.settle if value['action'] == 'capture' else self.agreements.refund
        action(ws, value['target_id'], value['command'], actor, receipt_hook=receipt)
        if len(captured) != 1:
            raise WorkspaceConflict()
        return {'intent_id': identity, 'event_reference': value['event_reference'],
                'result': captured[0], 'receipt_recorded': True, **FLAGS}

    def dispatch(self, ws, body, actor):
        exact(body, ('intent_id', 'authorized', 'notice'))
        if body['authorized'] is not True or body['notice'] != EXECUTE_NOTICE:
            raise WorkspaceInvalid()
        with self.access._tx(actor) as (db, _):
            value = self._current(db, ws, body['intent_id'], actor)
            raw = self._wire(value)
        return self.ingest(raw, self._signature(raw), actor)

    def withdraw(self, ws, body, actor):
        exact(body, ('intent_id', 'authorized', 'notice'))
        if body['authorized'] is not True or body['notice'] != WITHDRAW_NOTICE:
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            self._owner(ws, actor)
            value = self._intent(db, ws, body['intent_id'])
            if db.execute('SELECT 1 FROM workspace_sandbox_payment_receipts WHERE intent_id=?', (value['id'],)).fetchone():
                raise WorkspaceConflict()
            tombstone = {'intent_id': value['id'], 'workspace_id': ws, 'created': clock(),
                         'actor_user_id': actor.user_id, 'reason': 'administrator_withdrawal'}
            db.execute('INSERT INTO workspace_sandbox_payment_withdrawals VALUES(?,?,?,?)',
                (value['id'], ws, _canonical(tombstone), self.sign(tombstone)))
            self.access._audit(db, actor, ws, 'sandbox_payment.withdraw', value['id'], None)
            return {'intent_id': value['id'], 'withdrawn': True, **FLAGS}

    def status(self, ws, actor):
        with self.access._tx(actor) as (db, _):
            member, user = self.scope(ws, actor)
            can_write = member['member_role'] == 'owner' and user['role'] != 'operator'
            owner = self._owner(ws, actor) if can_write else None
            rows = _rows(db, 'SELECT * FROM workspace_sandbox_payment_intents WHERE workspace_id=? ORDER BY created DESC,id LIMIT 101', (ws,))
            if len(rows) > MAX_EVENTS:
                raise WorkspaceConflict()
            items = []
            for row in rows:
                value = self.opened(row)
                if value.get('profile') != PROFILE or any(value.get(key) != row[key] for key in ('id', 'workspace_id', 'event_reference', 'created')):
                    raise WorkspaceConflict()
                receipt = self._receipt(db, ws, value)
                withdrawals = _rows(db, 'SELECT * FROM workspace_sandbox_payment_withdrawals WHERE intent_id=?', (value['id'],))
                if withdrawals:
                    withdrawal = self.opened(withdrawals[0])
                    if (withdrawal.get('intent_id') != value['id'] or withdrawal.get('workspace_id') != ws
                            or withdrawals[0]['workspace_id'] != ws or receipt):
                        raise WorkspaceConflict()
                if db.execute('SELECT 1 FROM workspace_sandbox_payment_restore_blocks WHERE id=?', (value['id'],)).fetchone():
                    state = 'restore_blocked'
                elif withdrawals:
                    state = 'withdrawn'
                elif receipt:
                    state = 'recorded'
                else:
                    state = 'expired' if value['expires'] <= clock() else 'prepared'
                items.append(self._dto(value) | {'state': state,
                    'can_dispatch': state == 'prepared' and value['owner'] == owner})
            intent_ids = {value['id'] for value in items}
            linked_queries = (
                'SELECT intent_id FROM workspace_sandbox_payment_receipts WHERE workspace_id=? LIMIT 101',
                'SELECT intent_id FROM workspace_sandbox_payment_withdrawals WHERE workspace_id=? LIMIT 101',
            )
            for query in linked_queries:
                linked = _rows(db, query, (ws,))
                if len(linked) > MAX_EVENTS or any(item['intent_id'] not in intent_ids for item in linked):
                    raise WorkspaceConflict()
            return {'profile': PROFILE, 'prepare_notice': PREPARE_NOTICE, 'execute_notice': EXECUTE_NOTICE,
                    'withdraw_notice': WITHDRAW_NOTICE, 'max_events': MAX_EVENTS, 'ttl_seconds': TTL,
                    'can_write': can_write,
                    'intents': items, 'external_provider_configured': False, **FLAGS}
