"""Workspace-scoped simulated usage accounting. No payment or provider transfer."""
import hashlib
import hmac
import json
import math
import re
import secrets
import time

from .workspace_access import (WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid,
    _canonical, _hash, _identity, _rows, _tree)

PROFILE = 'workspace-shadow-ledger-v1'
NOTICE = 'workspace-shadow-accounting-v1'
ASSETS = ('TEST_UNIT', 'USD_CENT', 'EUR_CENT')
MAX_UNITS = 10**12
MAX_OPERATIONS = 200
SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS workspace_shadow_operations (
       id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS workspace_shadow_events (
       id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,operation_id TEXT NOT NULL,sequence INTEGER NOT NULL,
       payload TEXT NOT NULL,signature TEXT NOT NULL,UNIQUE(workspace_id,sequence))''',
    '''CREATE TABLE IF NOT EXISTS workspace_shadow_entries (
       event_id TEXT NOT NULL,ordinal INTEGER NOT NULL,workspace_id TEXT NOT NULL,operation_id TEXT NOT NULL,
       payload TEXT NOT NULL,signature TEXT NOT NULL,PRIMARY KEY(event_id,ordinal))''',
)


def clock():
    value = time.time()
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise WorkspaceConflict()
    return value


def exact(body, fields):
    _tree(body)
    if type(body) is not dict or set(body) != set(fields):
        raise WorkspaceInvalid()


def identifier(value, prefix):
    return _identity(value, prefix)


def units(value, *, zero=False):
    if type(value) is not int or not (0 if zero else 1) <= value <= MAX_UNITS:
        raise WorkspaceInvalid()
    return value


class SignedWorkspaceModule:
    """Trusted constructors initialize only new private tables; callers own Store."""
    def __init__(self, access, profile, schema):
        self.access, self.store = access, access.store
        self.key = hmac.new(access.key, profile.encode('ascii'), hashlib.sha256).digest()
        from .private_artifact_keys import ArtifactSigner
        self._artifact_signer = ArtifactSigner(self.key, profile)
        with self.store._lock:
            db = self.store._db
            if db.in_transaction:
                raise WorkspaceConflict()
            try:
                db.execute('BEGIN IMMEDIATE')
                for statement in schema:
                    db.execute(statement)
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def sign(self, value):
        return self._artifact_signer.sign(value)

    def opened(self, row):
        try:
            value = json.loads(row['payload'])
            _tree(value)
            if not self._artifact_signer.verify(value, row['signature']):
                raise WorkspaceConflict()
            return value
        except (ValueError, TypeError, KeyError):
            raise WorkspaceConflict() from None

    def scope(self, ws, actor, *, write=False, owner=False):
        return self.access._access(ws, actor, write=write, owner=owner)


class ShadowLedger(SignedWorkspaceModule):
    def __init__(self, access):
        super().__init__(access, PROFILE, SCHEMA)

    @staticmethod
    def dto(value):
        return {key: value[key] for key in ('id', 'asset', 'approved_units', 'settled_units',
            'status', 'revision', 'created', 'updated')} | {'simulation': True, 'actual_money': False}

    def _history(self, db, ws):
        rows = _rows(db, 'SELECT * FROM workspace_shadow_events WHERE workspace_id=? ORDER BY sequence LIMIT 802', (ws,))
        if len(rows) > 800:
            raise WorkspaceConflict()
        previous, events = None, {}
        for sequence, row in enumerate(rows, 1):
            event = self.opened(row)
            if (event['id'] != row['id'] or event['workspace_id'] != ws
                    or event['operation_id'] != row['operation_id'] or row['sequence'] != sequence
                    or event['sequence'] != sequence or event['previous'] != previous):
                raise WorkspaceConflict()
            entries = _rows(db, 'SELECT * FROM workspace_shadow_entries WHERE event_id=? ORDER BY ordinal', (row['id'],))
            if len(entries) != len(event['entries']):
                raise WorkspaceConflict()
            for ordinal, entry in enumerate(entries):
                value = self.opened(entry)
                if (entry['ordinal'] != ordinal or entry['workspace_id'] != ws
                        or entry['operation_id'] != event['operation_id'] or value != event['entries'][ordinal]):
                    raise WorkspaceConflict()
            if sum(item['units'] for item in event['entries']) != 0:
                raise WorkspaceConflict()
            previous, events[event['id']] = _hash(event), event
        if db.execute('SELECT COUNT(*) FROM workspace_shadow_entries WHERE workspace_id=?', (ws,)).fetchone()[0] != sum(len(event['entries']) for event in events.values()):
            raise WorkspaceConflict()
        return events

    def _operation(self, db, ws, identity, events=None):
        identifier(identity, 'slop')
        rows = _rows(db, 'SELECT * FROM workspace_shadow_operations WHERE id=? AND workspace_id=?', (identity, ws))
        if len(rows) != 1:
            raise WorkspaceDenied()
        value = self.opened(rows[0])
        history = self._history(db, ws) if events is None else events
        if (value['id'] != identity or value['workspace_id'] != ws or not value['events']
                or any(event not in history or history[event]['operation_id'] != identity for event in value['events'])
                or history[value['events'][-1]]['state_hash'] != _hash(value)):
            raise WorkspaceConflict()
        return value

    def _record(self, db, ws, actor, operation, event_id, command, entries, history):
        operation['events'].append(event_id)
        operation['updated'] = clock()
        event = {'id': event_id, 'workspace_id': ws, 'operation_id': operation['id'],
            'sequence': len(history)+1, 'previous': _hash(next(reversed(history.values()))) if history else None,
            'actor_user_id': actor.user_id, 'created': operation['updated'], 'command': command,
            'entries': entries, 'state_hash': _hash(operation)}
        db.execute('''INSERT INTO workspace_shadow_operations VALUES(?,?,?,?) ON CONFLICT(id)
            DO UPDATE SET payload=excluded.payload,signature=excluded.signature''',
            (operation['id'], ws, _canonical(operation), self.sign(operation)))
        db.execute('INSERT INTO workspace_shadow_events VALUES(?,?,?,?,?,?)',
            (event_id, ws, operation['id'], event['sequence'], _canonical(event), self.sign(event)))
        for ordinal, entry in enumerate(entries):
            db.execute('INSERT INTO workspace_shadow_entries VALUES(?,?,?,?,?,?)',
                (event_id, ordinal, ws, operation['id'], _canonical(entry), self.sign(entry)))
        self.access._audit(db, actor, ws, 'shadow.' + command['action'], operation['id'], operation['revision'])
        return self.dto(operation)

    def options(self, ws, actor):
        with self.access._tx(actor) as (db, user):
            member, _ = self.scope(ws, actor)
            return {'profile': PROFILE, 'notice': NOTICE, 'assets': list(ASSETS),
                'max_units': MAX_UNITS, 'max_operations': MAX_OPERATIONS,
                'can_write': user['role'] != 'operator' and member['member_role'] == 'owner',
                'simulation': True, 'actual_money': False, 'provider_payout_enabled': False}

    def approve(self, ws, body, actor):
        exact(body, ('operation_id', 'asset', 'units', 'authorized', 'notice'))
        identifier(body['operation_id'], 'slop'); units(body['units'])
        if body['asset'] not in ASSETS or body['authorized'] is not True or body['notice'] != NOTICE:
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, user):
            member, _ = self.scope(ws, actor, write=True, owner=True)
            history = self._history(db, ws)
            existing = _rows(db, 'SELECT id FROM workspace_shadow_operations WHERE id=?', (body['operation_id'],))
            if existing:
                value = self._operation(db, ws, body['operation_id'], history)
                if value['approved_units'] != body['units'] or value['asset'] != body['asset']:
                    raise WorkspaceConflict()
                return self.dto(value) | {'replayed': True}
            if db.execute('SELECT COUNT(*) FROM workspace_shadow_operations WHERE workspace_id=?', (ws,)).fetchone()[0] >= MAX_OPERATIONS:
                raise WorkspaceConflict()
            now = clock()
            value = {'id': body['operation_id'], 'workspace_id': ws, 'asset': body['asset'],
                'approved_units': body['units'], 'settled_units': 0, 'status': 'approved', 'revision': 1,
                'created': now, 'updated': now, 'expires': now+3600, 'events': [],
                'actor_user_id': actor.user_id, 'session_ref': actor.session_ref,
                'workspace_revision': member['revision'], 'member_revision': member['member_revision'],
                'user_role': user['role']}
            return self._record(db, ws, actor, value, 'slev_'+secrets.token_hex(16), {'action': 'approve'}, [], history)

    def _change(self, ws, body, actor, action):
        fields = {'operation_id', 'event_id', 'revision', 'authorized', 'notice'}
        if action != 'reverse': fields |= {'outcome', 'settled_units'}
        exact(body, fields); identifier(body['operation_id'], 'slop'); identifier(body['event_id'], 'slev')
        if body['authorized'] is not True or body['notice'] != NOTICE or type(body['revision']) is not int:
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, user):
            member, _ = self.scope(ws, actor, write=True, owner=True)
            history = self._history(db, ws)
            operation = self._operation(db, ws, body['operation_id'], history)
            command = {'action': action, 'request': body}
            if body['event_id'] in history:
                if history[body['event_id']]['command'] != command or history[body['event_id']]['operation_id'] != operation['id']:
                    raise WorkspaceConflict()
                return self.dto(operation) | {'replayed': True}
            if db.execute('SELECT 1 FROM workspace_shadow_events WHERE id=?', (body['event_id'],)).fetchone():
                raise WorkspaceConflict()
            if operation['revision'] != body['revision']:
                raise WorkspaceConflict()
            if action == 'post' and (operation['actor_user_id'] != actor.user_id
                    or operation['session_ref'] != actor.session_ref or operation['expires'] <= clock()
                    or operation['workspace_revision'] != member['revision']
                    or operation['member_revision'] != member['member_revision'] or operation['user_role'] != user['role']):
                raise WorkspaceConflict()
            if action == 'reverse':
                if operation['status'] not in ('completed', 'partial'):
                    raise WorkspaceConflict()
                amount = -operation['settled_units']; operation['status'] = 'reversed'
            else:
                if operation['status'] != ('approved' if action == 'post' else 'unknown'):
                    raise WorkspaceConflict()
                amount = units(body['settled_units'], zero=True)
                outcome = body['outcome']
                if (outcome not in ('completed', 'partial', 'unknown', 'not_received')
                        or outcome == 'completed' and amount != operation['approved_units']
                        or outcome == 'partial' and not 0 < amount < operation['approved_units']
                        or outcome in ('unknown', 'not_received') and amount != 0
                        or action == 'post' and outcome == 'not_received'
                        or action == 'reconcile' and outcome == 'unknown'):
                    raise WorkspaceInvalid()
                operation['settled_units'], operation['status'] = amount, outcome
            entries = [] if amount == 0 else [
                {'asset': operation['asset'], 'account': 'simulation_usage', 'units': amount},
                {'asset': operation['asset'], 'account': 'simulation_clearing', 'units': -amount}]
            operation['revision'] += 1
            return self._record(db, ws, actor, operation, body['event_id'], command, entries, history)

    def post(self, ws, body, actor): return self._change(ws, body, actor, 'post')
    def reconcile(self, ws, body, actor): return self._change(ws, body, actor, 'reconcile')
    def reverse(self, ws, body, actor): return self._change(ws, body, actor, 'reverse')

    def summary(self, ws, actor):
        with self.access._tx(actor) as (db, _):
            self.scope(ws, actor)
            history = self._history(db, ws)
            rows = _rows(db, 'SELECT id FROM workspace_shadow_operations WHERE workspace_id=? ORDER BY id LIMIT 201', (ws,))
            if len(rows) > MAX_OPERATIONS: raise WorkspaceConflict()
            operations = [self._operation(db, ws, row['id'], history) for row in rows]
            balances = {asset: 0 for asset in ASSETS}
            accounts = {asset: {'simulation_usage': 0, 'simulation_clearing': 0} for asset in ASSETS}
            for event in history.values():
                for entry in event['entries']:
                    balances[entry['asset']] += entry['units']
                    accounts[entry['asset']][entry['account']] += entry['units']
            return {'profile': PROFILE, 'operations': [self.dto(value) for value in operations],
                'events': len(history), 'entries': sum(len(event['entries']) for event in history.values()),
                'asset_balances': balances, 'balanced': all(value == 0 for value in balances.values()),
                'account_balances': accounts,
                'has_posted_evidence': any(value['status'] in ('completed', 'partial', 'reversed') for value in operations),
                'simulation': True, 'actual_money': False, 'commercial_enabled': False}
