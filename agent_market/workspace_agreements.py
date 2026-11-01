"""Immutable provider terms and conserved integer-only simulated settlement.

Platform signatures prove record integrity, never legal assent. Every action is
TEST_UNIT simulation; this module cannot enable payment or provider payouts.
"""
import math
import re
import secrets

from .shadow_ledger import SignedWorkspaceModule, clock, exact, units
from .workspace_access import (WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid,
                               _canonical, _hash, _identity, _revision, _rows)

PROFILE = 'workspace-provider-agreement-v1'
NOTICE = 'workspace-agreement-simulation-v1'
MAX_AGREEMENTS = 100
MAX_SETTLEMENTS = 100
MAX_EVENTS = 100
ACCOUNTS = ('simulation_customer', 'simulation_processing', 'simulation_tax',
            'simulation_provider', 'simulation_platform')
FLAGS = {'simulation': True, 'actual_money': False, 'commercial_enabled': False,
         'payment_enabled': False, 'provider_payout_enabled': False,
         'legal_verification': 'unverified', 'operating_contract_proof': False}
SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS workspace_provider_agreements (
       id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,resource_id INTEGER NOT NULL,
       ordinal INTEGER NOT NULL,created REAL NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL,
       UNIQUE(workspace_id,resource_id,ordinal))''',
    '''CREATE TABLE IF NOT EXISTS workspace_provider_agreement_states (
       agreement_id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,revision INTEGER NOT NULL,
       status TEXT NOT NULL,updated REAL NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS workspace_provider_agreement_heads (
       workspace_id TEXT NOT NULL,resource_id INTEGER NOT NULL,agreement_id TEXT NOT NULL,
       revision INTEGER NOT NULL,PRIMARY KEY(workspace_id,resource_id))''',
    '''CREATE TABLE IF NOT EXISTS workspace_agreement_settlements (
       id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,agreement_id TEXT NOT NULL,
       revision INTEGER NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS workspace_agreement_events (
       id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,settlement_id TEXT NOT NULL,event_reference TEXT NOT NULL,
       request_hash TEXT NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL,
       UNIQUE(workspace_id,event_reference))''',
    '''CREATE TABLE IF NOT EXISTS workspace_agreement_entries (
       event_id TEXT NOT NULL,ordinal INTEGER NOT NULL,workspace_id TEXT NOT NULL,settlement_id TEXT NOT NULL,
       payload TEXT NOT NULL,signature TEXT NOT NULL,PRIMARY KEY(event_id,ordinal))''',
    'CREATE TABLE IF NOT EXISTS workspace_agreement_restore_blocks(id TEXT PRIMARY KEY)',
)


def _integer(value, maximum):
    if type(value) is not int or not 0 <= value <= maximum:
        raise WorkspaceInvalid()
    return value


def terms(value):
    exact(value, ('asset', 'scale', 'provider_bps', 'platform_bps', 'base', 'deductions',
                  'refund_responsibility', 'rounding', 'document_reference', 'document_sha256'))
    exact(value['deductions'], ('processing_bps', 'processing_fixed_units', 'tax_bps'))
    if (value['asset'] != 'TEST_UNIT' or type(value['scale']) is not int or value['scale'] != 0
            or type(value['provider_bps']) is not int or value['provider_bps'] != 7000
            or type(value['platform_bps']) is not int or value['platform_bps'] != 3000
            or value['base'] != 'gross_less_processing_then_tax'
            or value['refund_responsibility'] != 'proportional_original_components'
            or value['rounding'] != 'floor_provider_platform_remainder'
            or type(value['document_reference']) is not str
            or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', value['document_reference'])
            or type(value['document_sha256']) is not str or not re.fullmatch(r'[a-f0-9]{64}', value['document_sha256'])):
        raise WorkspaceInvalid()
    _integer(value['deductions']['processing_bps'], 2500)
    _integer(value['deductions']['tax_bps'], 5000)
    _integer(value['deductions']['processing_fixed_units'], 10**12)
    return value


def allocation(gross, contract):
    """Original charge: processing, then tax, then provider-floor/platform-rest."""
    units(gross)
    terms(contract)
    processing = min(gross, gross * contract['deductions']['processing_bps'] // 10000
                     + contract['deductions']['processing_fixed_units'])
    tax = (gross - processing) * contract['deductions']['tax_bps'] // 10000
    base = gross - processing - tax
    provider = base * 7000 // 10000
    return {'gross_units': gross, 'processing_units': processing, 'tax_units': tax,
            'distributable_units': base, 'provider_units': provider,
            'platform_units': base - provider}


def remaining(original, cumulative_refund):
    """Nested original-component proportions ensure monotone refunds.

    Every refund recalculates the cumulative remaining balance. It never applies
    a fresh fixed deduction or independently rounds each partial refund.
    """
    units(cumulative_refund, zero=True)
    gross = original['gross_units']
    if cumulative_refund > gross:
        raise WorkspaceConflict()
    left = gross - cumulative_refund
    processing = original['processing_units'] * left // gross
    after_processing = left - processing
    original_after_processing = gross - original['processing_units']
    tax = original['tax_units'] * after_processing // original_after_processing if original_after_processing else 0
    base = after_processing - tax
    provider = original['provider_units'] * base // original['distributable_units'] if original['distributable_units'] else 0
    return {'gross_units': left, 'processing_units': processing, 'tax_units': tax,
            'distributable_units': base, 'provider_units': provider,
            'platform_units': base - provider}


def _event_reference(value):
    if type(value) is not str or not re.fullmatch(r'sim_[A-Za-z0-9_-]{1,80}', value):
        raise WorkspaceInvalid()
    return value


class WorkspaceAgreements(SignedWorkspaceModule):
    def __init__(self, access, claims):
        if access.store is not claims.store:
            raise WorkspaceInvalid()
        super().__init__(access, PROFILE, SCHEMA)
        self.claims = claims

    def _owner(self, db, ws, actor):
        membership, user = self.scope(ws, actor, write=True, owner=True)
        return {'actor_user_id': actor.user_id,
                'actor_kind': getattr(actor, 'principal_kind', 'admin'),
                'workspace_revision': membership['revision'],
                'member_revision': membership['member_revision'], 'user_role': user['role']}

    def _owner_current(self, db, ws, pin):
        if pin['actor_kind'] == 'admin':
            rows = _rows(db, '''SELECT m.revision,u.role FROM workspace_memberships m JOIN admin_users u ON u.id=m.user_id
                WHERE m.workspace_id=? AND m.user_id=? AND m.active=1 AND m.role='owner' AND u.active=1''', (ws, pin['actor_user_id']))
            return len(rows) == 1 and rows[0]['revision'] == pin['member_revision'] and rows[0]['role'] == pin['user_role'] and rows[0]['role'] in ('admin', 'superadmin')
        if pin['actor_kind'] == 'customer':
            rows = _rows(db, '''SELECT l.revision FROM customer_workspace_links l JOIN customer_identities i ON i.id=l.customer_id
                JOIN customer_organizations o ON o.workspace_id=l.workspace_id
                WHERE l.workspace_id=? AND l.customer_id=? AND l.active=1 AND l.role='owner' AND i.active=1 AND o.active=1''', (ws, pin['actor_user_id']))
            return len(rows) == 1 and rows[0]['revision'] == pin['member_revision']
        return False

    def _proof(self, db, ws, resource_id):
        current = self.claims.current(db, ws, resource_id)
        rows = _rows(db, 'SELECT * FROM provider_control_claims WHERE id=? AND workspace_id=?', (current['id'], ws))
        if len(rows) != 1:
            raise WorkspaceDenied()
        payload = self.claims._open(rows[0])
        owner = {'actor_user_id': payload['actor_user_id'], 'actor_kind': payload.get('actor_kind', 'admin'),
                 'member_revision': payload['member_revision'], 'user_role': payload['user_role']}
        if not self._owner_current(db, ws, owner):
            raise WorkspaceDenied()
        return {'claim_id': current['id'], 'claim_revision': current['revision'],
                'valid_until': current['valid_until'], 'resource': self.claims._resource(db, resource_id),
                'proof_owner': owner}

    def _agreement(self, db, ws, identity):
        _identity(identity, 'wpa')
        rows = _rows(db, 'SELECT * FROM workspace_provider_agreements WHERE id=? AND workspace_id=?', (identity, ws))
        states = _rows(db, 'SELECT * FROM workspace_provider_agreement_states WHERE agreement_id=? AND workspace_id=?', (identity, ws))
        if len(rows) != 1 or len(states) != 1:
            raise WorkspaceDenied()
        row, state = rows[0], states[0]
        value, status = self.opened(row), self.opened(state)
        if (value.get('profile') != PROFILE or any(value.get(key) != row[key] for key in ('id', 'workspace_id', 'resource_id', 'ordinal', 'created'))
                or any(status.get(key) != state[key] for key in ('agreement_id', 'workspace_id', 'revision', 'status', 'updated'))
                or status.get('terms_hash') != _hash(value) or status['status'] not in ('active', 'revoked', 'superseded')):
            raise WorkspaceConflict()
        terms(value['terms'])
        return value, status

    def _current(self, db, ws, identity, actor, *, admission=True):
        self._owner(db, ws, actor)
        value, state = self._agreement(db, ws, identity)
        if db.execute('SELECT 1 FROM workspace_agreement_restore_blocks WHERE id=?', (identity,)).fetchone():
            raise WorkspaceDenied()
        if (value['expires'] <= clock() or value['proof'] != self._proof(db, ws, value['resource_id'])
                or not self._owner_current(db, ws, value['owner'])):
            raise WorkspaceDenied()
        workspace = db.execute('SELECT revision FROM organization_workspaces WHERE id=? AND active=1', (ws,)).fetchone()
        if not workspace or value['owner']['workspace_revision'] != workspace[0]:
            raise WorkspaceDenied()
        if admission:
            head = _rows(db, 'SELECT * FROM workspace_provider_agreement_heads WHERE workspace_id=? AND resource_id=?', (ws, value['resource_id']))
            if state['status'] != 'active' or len(head) != 1 or head[0]['agreement_id'] != identity:
                raise WorkspaceDenied()
        return value, state

    def _state(self, db, value, revision, status):
        payload = {'agreement_id': value['id'], 'workspace_id': value['workspace_id'],
                   'revision': revision, 'status': status, 'updated': clock(), 'terms_hash': _hash(value)}
        db.execute('''INSERT INTO workspace_provider_agreement_states VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(agreement_id) DO UPDATE SET revision=excluded.revision,status=excluded.status,
            updated=excluded.updated,payload=excluded.payload,signature=excluded.signature''',
            (value['id'], value['workspace_id'], revision, status, payload['updated'], _canonical(payload), self.sign(payload)))
        return payload

    def _dto(self, value, state):
        return {key: value[key] for key in ('id', 'resource_id', 'ordinal', 'created', 'expires', 'terms')} | {
            'revision': state['revision'], 'status': state['status'], 'terms_hash': _hash(value),
            'claim_id': value['proof']['claim_id'], 'claim_revision': value['proof']['claim_revision'],
            'signature_kind': 'platform_record_integrity', **FLAGS}

    def options(self, ws, actor):
        with self.access._tx(actor) as (db, _):
            self._owner(db, ws, actor)
            return {'profile': PROFILE, 'notice': NOTICE, 'provider_bps': 7000, 'platform_bps': 3000,
                    'asset': 'TEST_UNIT', 'scale': 0, 'max_units': 10**12,
                    'max_versions': MAX_AGREEMENTS, 'max_settlements': MAX_SETTLEMENTS,
                    'max_events_per_settlement': MAX_EVENTS, **FLAGS}

    def versions(self, ws, actor):
        with self.access._tx(actor) as (db, _):
            self._owner(db, ws, actor)
            rows = _rows(db, 'SELECT id FROM workspace_provider_agreements WHERE workspace_id=? ORDER BY created DESC,id LIMIT 101', (ws,))
            if len(rows) > MAX_AGREEMENTS:
                raise WorkspaceConflict()
            versions = []
            for row in rows:
                value, state = self._agreement(db, ws, row['id'])
                dto = self._dto(value, state)
                try:
                    self._current(db, ws, row['id'], actor)
                    dto['current_control_verified'] = True
                except WorkspaceDenied:
                    dto['current_control_verified'] = False
                versions.append(dto)
            return {'versions': versions, 'heads': _rows(db, 'SELECT resource_id,agreement_id,revision FROM workspace_provider_agreement_heads WHERE workspace_id=? ORDER BY resource_id LIMIT 100', (ws,)), **FLAGS}

    def create(self, ws, body, actor):
        exact(body, ('resource_id', 'claim_id', 'claim_revision', 'revision', 'expires', 'terms', 'authorized', 'notice'))
        terms(body['terms']); _identity(body['claim_id'], 'pc')
        if (not _revision(body['revision'], zero=True) or not _revision(body['claim_revision'])
                or type(body['expires']) not in (int, float) or not math.isfinite(body['expires'])
                or body['authorized'] is not True or body['notice'] != NOTICE):
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            owner = self._owner(db, ws, actor)
            proof = self._proof(db, ws, body['resource_id'])
            if (proof['claim_id'] != body['claim_id'] or proof['claim_revision'] != body['claim_revision']
                    or not clock() < body['expires'] <= min(clock() + 30 * 86400, proof['valid_until'])):
                raise WorkspaceDenied()
            heads = _rows(db, 'SELECT * FROM workspace_provider_agreement_heads WHERE workspace_id=? AND resource_id=?', (ws, body['resource_id']))
            if body['revision'] != (heads[0]['revision'] if heads else 0):
                raise WorkspaceConflict()
            count = db.execute('SELECT COUNT(*) FROM workspace_provider_agreements WHERE workspace_id=?', (ws,)).fetchone()[0]
            if count >= MAX_AGREEMENTS:
                raise WorkspaceConflict()
            ordinal = db.execute('SELECT COUNT(*) FROM workspace_provider_agreements WHERE workspace_id=? AND resource_id=?', (ws, body['resource_id'])).fetchone()[0] + 1
            value = {'profile': PROFILE, 'id': 'wpa_' + secrets.token_hex(16), 'workspace_id': ws,
                     'resource_id': body['resource_id'], 'ordinal': ordinal, 'created': clock(),
                     'expires': body['expires'], 'terms': body['terms'], 'owner': owner, 'proof': proof,
                     'predecessor': heads[0]['agreement_id'] if heads else None, 'legal_verification': 'unverified'}
            if heads:
                old, old_state = self._agreement(db, ws, heads[0]['agreement_id'])
                if old['resource_id'] != body['resource_id']:
                    raise WorkspaceConflict()
                if old_state['status'] == 'active':
                    self._state(db, old, old_state['revision'] + 1, 'superseded')
            db.execute('INSERT INTO workspace_provider_agreements VALUES(?,?,?,?,?,?,?)',
                       (value['id'], ws, value['resource_id'], ordinal, value['created'], _canonical(value), self.sign(value)))
            state = self._state(db, value, 1, 'active')
            db.execute('''INSERT INTO workspace_provider_agreement_heads VALUES(?,?,?,?) ON CONFLICT(workspace_id,resource_id)
                DO UPDATE SET agreement_id=excluded.agreement_id,revision=excluded.revision''',
                (ws, value['resource_id'], value['id'], body['revision'] + 1))
            self.access._audit(db, actor, ws, 'agreement.create', value['id'], 1)
            return self._dto(value, state) | {'head_revision': body['revision'] + 1}

    def revoke(self, ws, identity, body, actor):
        exact(body, ('revision',))
        if not _revision(body['revision']):
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            self._owner(db, ws, actor)
            value, state = self._agreement(db, ws, identity)
            if state['revision'] != body['revision'] or state['status'] != 'active':
                raise WorkspaceConflict()
            state = self._state(db, value, state['revision'] + 1, 'revoked')
            self.access._audit(db, actor, ws, 'agreement.revoke', identity, state['revision'])
            return self._dto(value, state)

    @staticmethod
    def _quote(value, gross):
        result = allocation(gross, value['terms'])
        receipt = {'agreement_id': value['id'], 'terms_hash': _hash(value), 'asset': 'TEST_UNIT', 'allocation': result}
        return {'quote_hash': _hash(receipt), **receipt, **FLAGS}

    def quote(self, ws, identity, body, actor):
        exact(body, ('gross_units',))
        with self.access._tx(actor) as (db, _):
            value, _ = self._current(db, ws, identity, actor)
            return self._quote(value, units(body['gross_units']))

    def _entry_values(self, before, after=None):
        if after is None:
            return [-before['gross_units'], before['processing_units'], before['tax_units'], before['provider_units'], before['platform_units']]
        return [before['gross_units'] - after['gross_units'],
                after['processing_units'] - before['processing_units'], after['tax_units'] - before['tax_units'],
                after['provider_units'] - before['provider_units'], after['platform_units'] - before['platform_units']]

    def _event(self, db, settlement, reference, request_hash, kind, amount, before, after):
        identity = 'wae_' + secrets.token_hex(16)
        numbers = self._entry_values(before, after if kind == 'refund' else None)
        if sum(numbers) != 0:
            raise WorkspaceConflict()
        entries = [{'account': account, 'asset': 'TEST_UNIT', 'units': number} for account, number in zip(ACCOUNTS, numbers)]
        value = {'id': identity, 'workspace_id': settlement['workspace_id'], 'settlement_id': settlement['id'],
                 'event_reference': reference, 'request_hash': request_hash, 'kind': kind, 'units': amount,
                 'sequence': len(settlement['events']) + 1, 'previous': settlement['events'][-1]['sha256'] if settlement['events'] else None,
                 'remaining_after': after, 'entries': entries, 'created': clock()}
        db.execute('INSERT INTO workspace_agreement_events VALUES(?,?,?,?,?,?,?)',
                   (identity, value['workspace_id'], settlement['id'], reference, request_hash, _canonical(value), self.sign(value)))
        for index, entry in enumerate(entries):
            payload = {'event_id': identity, 'ordinal': index, 'workspace_id': value['workspace_id'], 'settlement_id': settlement['id'], **entry}
            db.execute('INSERT INTO workspace_agreement_entries VALUES(?,?,?,?,?,?)',
                       (identity, index, value['workspace_id'], settlement['id'], _canonical(payload), self.sign(payload)))
        settlement['events'].append({'id': identity, 'sha256': _hash(value)})

    def _save_settlement(self, db, value, insert=False):
        if insert:
            db.execute('INSERT INTO workspace_agreement_settlements VALUES(?,?,?,?,?,?,?,?)',
                (value['id'], value['workspace_id'], value['agreement_id'], value['revision'], value['created'], value['updated'], _canonical(value), self.sign(value)))
        else:
            changed = db.execute('UPDATE workspace_agreement_settlements SET revision=?,updated=?,payload=?,signature=? WHERE id=? AND workspace_id=? AND revision=?',
                (value['revision'], value['updated'], _canonical(value), self.sign(value), value['id'], value['workspace_id'], value['revision'] - 1)).rowcount
            if changed != 1:
                raise WorkspaceConflict()

    def _settlement(self, db, ws, identity):
        _identity(identity, 'was')
        rows = _rows(db, 'SELECT * FROM workspace_agreement_settlements WHERE id=? AND workspace_id=?', (identity, ws))
        if len(rows) != 1:
            raise WorkspaceDenied()
        value = self.opened(rows[0])
        if any(value.get(key) != rows[0][key] for key in ('id', 'workspace_id', 'agreement_id', 'revision', 'created', 'updated')):
            raise WorkspaceConflict()
        contract, _ = self._agreement(db, ws, value['agreement_id'])
        original = allocation(value['original']['gross_units'], contract['terms'])
        if original != value['original'] or remaining(original, value['refunded_units']) != value['remaining'] or not 1 <= len(value['events']) <= MAX_EVENTS:
            raise WorkspaceConflict()
        if (value['revision'] != len(value['events']) or db.execute('SELECT COUNT(*) FROM workspace_agreement_events WHERE workspace_id=? AND settlement_id=?', (ws, identity)).fetchone()[0] != len(value['events'])):
            raise WorkspaceConflict()
        running, previous, refunded = original, None, 0
        for sequence, reference in enumerate(value['events'], 1):
            events = _rows(db, 'SELECT * FROM workspace_agreement_events WHERE id=? AND workspace_id=? AND settlement_id=?', (reference['id'], ws, identity))
            if len(events) != 1:
                raise WorkspaceConflict()
            event = self.opened(events[0])
            if (any(event.get(key) != events[0][key] for key in ('id', 'workspace_id', 'settlement_id', 'event_reference', 'request_hash'))
                    or event['sequence'] != sequence or event['previous'] != previous or _hash(event) != reference['sha256']):
                raise WorkspaceConflict()
            if sequence == 1:
                if event['kind'] != 'capture' or event['units'] != original['gross_units']:
                    raise WorkspaceConflict()
                expected = self._entry_values(original)
            else:
                if event['kind'] != 'refund' or type(event['units']) is not int or event['units'] <= 0:
                    raise WorkspaceConflict()
                refunded += event['units']
                after = remaining(original, refunded)
                expected = self._entry_values(running, after)
                running = after
            if event['remaining_after'] != running:
                raise WorkspaceConflict()
            entries = _rows(db, 'SELECT * FROM workspace_agreement_entries WHERE event_id=? ORDER BY ordinal', (event['id'],))
            if len(entries) != len(ACCOUNTS) or len(event['entries']) != len(ACCOUNTS):
                raise WorkspaceConflict()
            for ordinal, row in enumerate(entries):
                entry = self.opened(row)
                if (entry != {'event_id': event['id'], 'ordinal': ordinal, 'workspace_id': ws, 'settlement_id': identity,
                              'account': ACCOUNTS[ordinal], 'asset': 'TEST_UNIT', 'units': expected[ordinal]}
                        or any(entry.get(key) != row[key] for key in ('event_id', 'ordinal', 'workspace_id', 'settlement_id'))
                        or event['entries'][ordinal] != {key: entry[key] for key in ('account', 'asset', 'units')}):
                    raise WorkspaceConflict()
            if sum(expected) != 0:
                raise WorkspaceConflict()
            previous = reference['sha256']
        if refunded != value['refunded_units'] or running != value['remaining']:
            raise WorkspaceConflict()
        return value

    @staticmethod
    def _settlement_dto(value):
        return {key: value[key] for key in ('id', 'agreement_id', 'revision', 'original', 'remaining', 'refunded_units', 'created', 'updated')} | {
            'status': 'refunded' if value['remaining']['gross_units'] == 0 else 'partial_refund' if value['refunded_units'] else 'captured',
            'event_count': len(value['events']), **FLAGS}

    def _replay(self, db, ws, event_reference, request_hash):
        rows = _rows(db, 'SELECT * FROM workspace_agreement_events WHERE workspace_id=? AND event_reference=?', (ws, event_reference))
        if not rows:
            return None
        event = self.opened(rows[0])
        if event['request_hash'] != request_hash or rows[0]['request_hash'] != request_hash:
            raise WorkspaceConflict()
        return self._settlement_dto(self._settlement(db, ws, rows[0]['settlement_id'])) | {'replayed': True}

    def settle(self, ws, identity, body, actor, *, receipt_hook=None):
        # Trusted server adapters may bind a transport receipt to this commit.
        # HTTP request fields never supply callbacks or alter simulation flags.
        if receipt_hook is not None and not callable(receipt_hook):
            raise WorkspaceInvalid()
        exact(body, ('event_reference', 'gross_units', 'quote_hash', 'revision', 'authorized', 'notice'))
        _event_reference(body['event_reference']); units(body['gross_units'])
        if (body['authorized'] is not True or body['notice'] != NOTICE or not _revision(body['revision'])
                or type(body['quote_hash']) is not str or not re.fullmatch(r'[0-9a-f]{64}', body['quote_hash'])):
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            contract, state = self._current(db, ws, identity, actor)
            request_hash = _hash({'action': 'capture', 'agreement_id': identity, 'request': body})
            replay = self._replay(db, ws, body['event_reference'], request_hash)
            if replay:
                if receipt_hook is not None:
                    receipt_hook(db, replay)
                return replay
            quote = self._quote(contract, body['gross_units'])
            if state['revision'] != body['revision'] or quote['quote_hash'] != body['quote_hash']:
                raise WorkspaceConflict()
            if db.execute('SELECT COUNT(*) FROM workspace_agreement_settlements WHERE workspace_id=?', (ws,)).fetchone()[0] >= MAX_SETTLEMENTS:
                raise WorkspaceConflict()
            now = clock()
            value = {'profile': PROFILE, 'id': 'was_' + secrets.token_hex(16), 'workspace_id': ws,
                     'agreement_id': identity, 'revision': 1, 'original': quote['allocation'],
                     'remaining': quote['allocation'], 'refunded_units': 0, 'events': [], 'created': now, 'updated': now}
            self._event(db, value, body['event_reference'], request_hash, 'capture', body['gross_units'], value['original'], value['remaining'])
            self._save_settlement(db, value, insert=True)
            self.access._audit(db, actor, ws, 'agreement.simulate_capture', value['id'], 1)
            result = self._settlement_dto(value)
            if receipt_hook is not None:
                receipt_hook(db, result)
            return result

    def refund(self, ws, identity, body, actor, *, receipt_hook=None):
        if receipt_hook is not None and not callable(receipt_hook):
            raise WorkspaceInvalid()
        exact(body, ('event_reference', 'units', 'revision', 'authorized', 'notice'))
        _event_reference(body['event_reference']); units(body['units'])
        if body['authorized'] is not True or body['notice'] != NOTICE or not _revision(body['revision']):
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            self._owner(db, ws, actor)
            value = self._settlement(db, ws, identity)
            self._current(db, ws, value['agreement_id'], actor, admission=False)
            request_hash = _hash({'action': 'refund', 'settlement_id': identity, 'request': body})
            replay = self._replay(db, ws, body['event_reference'], request_hash)
            if replay:
                if receipt_hook is not None:
                    receipt_hook(db, replay)
                return replay
            if value['revision'] != body['revision'] or len(value['events']) >= MAX_EVENTS:
                raise WorkspaceConflict()
            if len(value['events']) == MAX_EVENTS - 1 and body['units'] != value['remaining']['gross_units']:
                raise WorkspaceConflict()
            after = remaining(value['original'], value['refunded_units'] + body['units'])
            self._event(db, value, body['event_reference'], request_hash, 'refund', body['units'], value['remaining'], after)
            value.update(revision=value['revision'] + 1, refunded_units=value['refunded_units'] + body['units'],
                         remaining=after, updated=clock())
            self._save_settlement(db, value)
            self.access._audit(db, actor, ws, 'agreement.simulate_refund', identity, value['revision'])
            result = self._settlement_dto(value)
            if receipt_hook is not None:
                receipt_hook(db, result)
            return result

    def summary(self, ws, actor):
        with self.access._tx(actor) as (db, _):
            self._owner(db, ws, actor)
            rows = _rows(db, 'SELECT id FROM workspace_agreement_settlements WHERE workspace_id=? ORDER BY created DESC,id LIMIT 101', (ws,))
            if len(rows) > MAX_SETTLEMENTS:
                raise WorkspaceConflict()
            values = [self._settlement(db, ws, row['id']) for row in rows]
            balances = {account: 0 for account in ACCOUNTS}
            for value in values:
                for account, amount in zip(ACCOUNTS, self._entry_values(value['remaining'])):
                    balances[account] += amount
            return {'profile': PROFILE, 'asset': 'TEST_UNIT', 'settlements': [self._settlement_dto(value) for value in values],
                    'balances': balances, 'balanced': sum(balances.values()) == 0, **FLAGS}
