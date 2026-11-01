"""Stripe Connect TEST-only gross-USD manual capture and conserved accounting.

The profile uses separate charges/transfers. Processor fees are borne by the
platform and separately reported by reconciliation. No live credential works.
"""
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import re
import secrets
import time
from urllib.parse import quote

from .concierge.http_security import bounded_client, outbound_operation
from .shadow_ledger import SignedWorkspaceModule, exact, clock
from .workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid, _canonical, _identity, _rows, _tree

PROFILE = 'stripe-connect-test-usd-gross-v1'
NOTICE = 'stripe-sandbox-no-live-money-v1'
API_VERSION = '2025-06-30.basil'
SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS stripe_sandbox_orders (
       id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS stripe_sandbox_commands (
       id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,order_id TEXT NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS stripe_sandbox_events (
       id TEXT PRIMARY KEY,event_hash TEXT NOT NULL,created REAL NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS stripe_sandbox_restore_blocks (order_id TEXT PRIMARY KEY)''',
    '''CREATE TABLE IF NOT EXISTS stripe_sandbox_reservations (
       run_id TEXT PRIMARY KEY,order_id TEXT NOT NULL,workspace_id TEXT NOT NULL)''',
)


def money(value, zero=False):
    if type(value) is not int or not (0 if zero else 1) <= value <= 99999999:
        raise WorkspaceInvalid()
    return value


def provider_id(value, prefix):
    if type(value) is not str or not re.fullmatch(prefix+r'_[A-Za-z0-9]{1,100}', value):
        raise WorkspaceInvalid()
    return value


def strict_object(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise WorkspaceInvalid()
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(WorkspaceInvalid()))
    _tree(value)
    if type(value) is not dict:
        raise WorkspaceInvalid()
    return value


def allocate(amount, weights):
    """Largest-remainder allocation with stable ties and exact conservation."""
    total = sum(weights)
    if total <= 0 or any(type(w) is not int or w < 0 for w in weights):
        raise WorkspaceInvalid()
    result = [amount*w//total for w in weights]
    order = sorted(range(len(weights)), key=lambda i: (-(amount*weights[i] % total), i))
    for i in order[:amount-sum(result)]:
        result[i] += 1
    return result


def refund_targets(order, refunded):
    # Cumulative floor per original provider component is monotone. The platform
    # absorbs cent remainders; later refunds never undo a completed reversal.
    providers = [c['allocation']*refunded//order['amount'] for c in order['contributors']]
    return providers+[refunded-sum(providers)]


@dataclass(frozen=True, repr=False)
class StripeTestConfig:
    secret_key: str = field(repr=False)
    webhook_secret: str = field(repr=False)
    accounts: tuple = ()

    def __post_init__(self):
        if (type(self.secret_key) is not str or not re.fullmatch(r'sk_test_[A-Za-z0-9]{16,200}', self.secret_key)
                or type(self.webhook_secret) is not str or not re.fullmatch(r'whsec_[A-Za-z0-9]{16,200}', self.webhook_secret)
                or type(self.accounts) is not tuple or not 1 <= len(self.accounts) <= 20):
            raise WorkspaceInvalid()
        seen = set()
        for item in self.accounts:
            if type(item) is not tuple or len(item) != 2 or type(item[0]) is not int or item[0] <= 0 or item[0] in seen:
                raise WorkspaceInvalid()
            provider_id(item[1], 'acct'); seen.add(item[0])


class StripeTestClient:
    def __init__(self, config, *, http=None):
        if type(config) is not StripeTestConfig:
            raise WorkspaceInvalid()
        self.config, self.http = config, http

    def request(self, method, path, *, data=None, key=None, guard=None):
        if (method not in ('GET', 'POST') or type(path) is not str
                or not re.fullmatch(r'/v1/(?:payment_intents(?:/pi_[A-Za-z0-9]+(?:/(?:confirm|capture|cancel))?)?'
                    r'|transfers(?:/tr_[A-Za-z0-9]+(?:/reversals(?:/trr_[A-Za-z0-9]+)?)?)?'
                    r'|refunds(?:/re_[A-Za-z0-9]+)?|charges/ch_[A-Za-z0-9]+)', path)):
            raise WorkspaceInvalid()
        if method == 'POST' and (type(key) is not str or not re.fullmatch(r'ac-test-[a-f0-9]{64}', key)):
            raise WorkspaceInvalid()
        if guard is not None:
            guard()
        headers = {'Authorization': 'Bearer '+self.config.secret_key, 'Stripe-Version': API_VERSION,
                   'Accept': 'application/json'}
        if key is not None:
            headers['Idempotency-Key'] = key
        with outbound_operation(8):
            client = bounded_client(self.http, limit=65536, timeout=8)
            try:
                result = client.request(method, 'https://api.stripe.com'+path, headers=headers,
                                        **({'data': data} if method == 'POST' else {'params': data}))
            finally:
                client.close()
        if result.status_code != 200:
            raise WorkspaceConflict()
        value = strict_object(result.content)
        if (type(value) is not dict or value.get('livemode') is True
                or value.get('object') in ('payment_intent', 'transfer', 'charge') and value.get('livemode') is not False):
            raise WorkspaceConflict()
        return value

    def event(self, raw, signature):
        if type(raw) is not bytes or len(raw) > 65536 or type(signature) is not str or len(signature) > 2048:
            raise WorkspaceInvalid()
        parts = signature.split(','); timestamps = [v[2:] for v in parts if v.startswith('t=')]
        signatures = [v[3:] for v in parts if v.startswith('v1=')]
        if (len(timestamps) != 1 or not re.fullmatch(r'[0-9]{1,12}', timestamps[0])
                or not 1 <= len(signatures) <= 5 or any(not re.fullmatch(r'[a-f0-9]{64}', s) for s in signatures)
                or abs(time.time()-int(timestamps[0])) > 300):
            raise WorkspaceDenied()
        expected = hmac.new(self.config.webhook_secret.encode(), timestamps[0].encode()+b'.'+raw, hashlib.sha256).hexdigest()
        if not any(hmac.compare_digest(expected, s) for s in signatures):
            raise WorkspaceDenied()
        value = strict_object(raw)
        if (type(value) is not dict or value.get('object') != 'event' or value.get('livemode') is not False
                or value.get('api_version') != API_VERSION):
            raise WorkspaceDenied()
        provider_id(value.get('id'), 'evt')
        return value


class StripeSandbox(SignedWorkspaceModule):
    def __init__(self, access, execution, *, client=None):
        if execution.access is not access or client is not None and type(client) is not StripeTestClient:
            raise WorkspaceInvalid()
        super().__init__(access, PROFILE, SCHEMA)
        self.execution, self.client = execution, client

    def _enabled(self):
        if self.client is None:
            raise WorkspaceDenied()

    @staticmethod
    def _authorize(body, fields):
        exact(body, (*fields, 'authorized', 'notice'))
        if body['authorized'] is not True or body['notice'] != NOTICE:
            raise WorkspaceInvalid()

    def _load(self, db, ws, identity):
        _identity(identity, 'spo')
        rows = _rows(db, 'SELECT * FROM stripe_sandbox_orders WHERE id=? AND workspace_id=?', (identity, ws))
        if len(rows) != 1:
            raise WorkspaceDenied()
        value = self.opened(rows[0])
        if value.get('id') != identity or value.get('workspace_id') != ws:
            raise WorkspaceConflict()
        return value

    @staticmethod
    def _restore_guard(db, identity):
        if db.execute('SELECT 1 FROM stripe_sandbox_restore_blocks WHERE order_id=?', (identity,)).fetchone():
            raise WorkspaceConflict()

    def _save(self, db, value):
        db.execute('''INSERT INTO stripe_sandbox_orders VALUES(?,?,?,?) ON CONFLICT(id)
            DO UPDATE SET payload=excluded.payload,signature=excluded.signature''',
            (value['id'], value['workspace_id'], _canonical(value), self.sign(value)))

    def _command(self, db, ws, identity):
        _identity(identity, 'spc')
        rows = _rows(db, 'SELECT * FROM stripe_sandbox_commands WHERE id=? AND workspace_id=?', (identity, ws))
        if not rows:
            return None
        value = self.opened(rows[0])
        if any(value.get(k) != rows[0][k] for k in ('id', 'workspace_id', 'order_id')):
            raise WorkspaceConflict()
        return value

    def _save_command(self, db, value):
        db.execute('''INSERT INTO stripe_sandbox_commands VALUES(?,?,?,?,?) ON CONFLICT(id)
            DO UPDATE SET payload=excluded.payload,signature=excluded.signature''',
            (value['id'], value['workspace_id'], value['order_id'], _canonical(value), self.sign(value)))

    def quote(self, ws, body, actor):
        self._enabled(); self._authorize(body, ('amount', 'attempts'))
        amount = money(body['amount'])
        if amount < 50 or type(body['attempts']) is not list or not 1 <= len(body['attempts']) <= 6:
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            self.scope(ws, actor, write=True, owner=True)
            prior_orders = _rows(db, 'SELECT id FROM stripe_sandbox_orders WHERE workspace_id=? ORDER BY id LIMIT 101', (ws,))
            if len(prior_orders) >= 100:
                raise WorkspaceConflict()
            # Signed orders remain the independent anti-replay proof if an
            # unsigned reservation locator is removed or restored incorrectly.
            reserved = {c['run_id'] for row in prior_orders for c in self._load(db, ws, row['id'])['contributors']}
            contributors, seen = [], set(); accounts = dict(self.client.config.accounts)
            for item in body['attempts']:
                exact(item, ('run_id', 'weight')); _identity(item['run_id'], 'wpr')
                if item['run_id'] in seen or type(item['weight']) is not int or not 1 <= item['weight'] <= 10000:
                    raise WorkspaceInvalid()
                seen.add(item['run_id'])
                if item['run_id'] in reserved or db.execute('SELECT 1 FROM stripe_sandbox_reservations WHERE run_id=?', (item['run_id'],)).fetchone():
                    raise WorkspaceConflict()
                rows = _rows(db, 'SELECT draft_id,snapshot_id FROM workspace_private_runs WHERE id=? AND workspace_id=?', (item['run_id'], ws))
                if len(rows) != 1:
                    raise WorkspaceDenied()
                row = rows[0]
                _, ticket, claims, run = self.execution._load_run(db, item['run_id'], ws, row['draft_id'], row['snapshot_id'], decrypt_output=False)
                if (run['status'] != 'succeeded' or run['dispatched'] is None or ticket['revoked'] is not None
                        or claims['resource_id'] not in accounts):
                    raise WorkspaceConflict()
                contributors.append({'run_id': item['run_id'], 'weight': item['weight'], 'account': accounts[claims['resource_id']],
                    'resource_id': claims['resource_id'], 'proof': hashlib.sha256(_canonical(run).encode()).hexdigest(),
                    'transfer_id': None, 'transferred': 0, 'reversed': 0})
            contributors.sort(key=lambda c: c['run_id'])
            pool = amount*70//100
            for item, share in zip(contributors, allocate(pool, [c['weight'] for c in contributors])):
                item['allocation'] = share
            if db.execute('SELECT COUNT(*) FROM stripe_sandbox_orders WHERE workspace_id=?', (ws,)).fetchone()[0] >= 100:
                raise WorkspaceConflict()
            value = {'id': 'spo_'+secrets.token_hex(16), 'workspace_id': ws, 'created': clock(),
                'amount': amount, 'currency': 'usd', 'state': 'quoted', 'payment_intent': None, 'charge': None,
                'captured': 0, 'refunded': 0, 'contributors': contributors, 'platform_allocation': amount-pool,
                'processor_fee': None, 'entries': [], 'revision': 1}
            self._save(db, value)
            for contributor in contributors:
                db.execute('INSERT INTO stripe_sandbox_reservations VALUES(?,?,?)', (contributor['run_id'], value['id'], ws))
            self.access._audit(db, actor, ws, 'stripe.sandbox.quote', value['id'], 1)
            return self.dto(value)

    @staticmethod
    def dto(value):
        return {k: value[k] for k in ('id', 'revision', 'state', 'amount', 'currency', 'captured', 'refunded',
            'platform_allocation', 'processor_fee')} | {'profile': PROFILE, 'test_only': True, 'actual_money': False,
            'provider_allocations': [{'resource_id': c['resource_id'], 'allocation': c['allocation'],
                'transferred': c['transferred'], 'reversed': c['reversed']} for c in value['contributors']],
            'ledger_conserved': sum(e['units'] for e in value['entries']) == 0,
            'processor_balance_reconciled': value['processor_fee'] is not None}

    def status(self, ws, identity, actor):
        with self.access._tx(actor) as (db, _):
            self.scope(ws, actor)
            value = self._load(db, ws, identity)
            commands = _rows(db, 'SELECT id FROM stripe_sandbox_commands WHERE workspace_id=? AND order_id=? ORDER BY id', (ws, identity))
            return self.dto(value) | {'commands': [self.command_dto(self._command(db, ws, r['id'])) for r in commands]}

    @staticmethod
    def command_dto(value):
        return {k: value[k] for k in ('id', 'action', 'state', 'order_id')} | {'test_only': True, 'actual_money': False}

    def _request_for(self, order, body):
        action, pi = body['action'], order['payment_intent']
        if action == 'create' and pi is None and order['state'] == 'quoted':
            return '/v1/payment_intents', {'amount': order['amount'], 'currency': 'usd', 'capture_method': 'manual',
                'payment_method_types[]': 'card', 'metadata[order_id]': order['id'], 'transfer_group': order['id']}
        if action in ('confirm', 'capture', 'cancel') and pi:
            if action == 'capture' and order['state'] != 'requires_capture':
                raise WorkspaceConflict()
            if action == 'confirm' and order['state'] != 'requires_payment_method':
                raise WorkspaceConflict()
            if action == 'cancel' and order['captured']:
                raise WorkspaceConflict()
            return '/v1/payment_intents/'+pi+'/'+action, ({'payment_method': 'pm_card_visa'} if action == 'confirm' else {})
        if action == 'transfer' and order['captured'] == order['amount'] and not order['refunded']:
            index = body['index']
            if type(index) is not int or not 0 <= index < len(order['contributors']):
                raise WorkspaceInvalid()
            c = order['contributors'][index]
            if c['transferred'] or not c['allocation'] or not order['charge']:
                raise WorkspaceConflict()
            return '/v1/transfers', {'amount': c['allocation'], 'currency': 'usd', 'destination': c['account'],
                'source_transaction': order['charge'], 'transfer_group': order['id'], 'metadata[order_id]': order['id']}
        if action == 'refund' and order['captured'] == order['amount']:
            amount = money(body['amount'])
            if (amount > order['captured']-order['refunded']
                    or any(c['allocation'] != c['transferred'] for c in order['contributors'])):
                raise WorkspaceConflict()
            return '/v1/refunds', {'payment_intent': pi, 'amount': amount, 'metadata[order_id]': order['id']}
        if action == 'reverse' and order['refunded']:
            index = body['index']
            if type(index) is not int or not 0 <= index < len(order['contributors']):
                raise WorkspaceInvalid()
            c = order['contributors'][index]
            targets = refund_targets(order, order['refunded'])
            delta = targets[index]-c['reversed']
            if delta <= 0 or not c['transfer_id']:
                raise WorkspaceConflict()
            return '/v1/transfers/'+c['transfer_id']+'/reversals', {'amount': delta, 'metadata[order_id]': order['id']}
        raise WorkspaceConflict()

    def execute(self, ws, identity, body, actor):
        self._enabled()
        action = body.get('action') if type(body) is dict else None
        fields = ('command_id', 'action', 'revision') + (('amount',) if action == 'refund' else ('index',) if action in ('transfer', 'reverse') else ())
        self._authorize(body, fields); _identity(body['command_id'], 'spc')
        if type(body['revision']) is not int or body['revision'] < 1:
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            self.scope(ws, actor, write=True, owner=True); order = self._load(db, ws, identity)
            self._restore_guard(db, identity)
            old = self._command(db, ws, body['command_id'])
            fingerprint = hashlib.sha256(_canonical(body).encode()).hexdigest()
            if old:
                if old['order_id'] != identity or old['fingerprint'] != fingerprint:
                    raise WorkspaceConflict()
                return self.command_dto(old)
            if body['revision'] != order['revision']:
                raise WorkspaceConflict()
            active = _rows(db, 'SELECT id FROM stripe_sandbox_commands WHERE workspace_id=? AND order_id=?', (ws, identity))
            if len(active) >= 100:
                raise WorkspaceConflict()
            if any(self._command(db, ws, row['id'])['state'] in ('dispatched', 'unknown') for row in active):
                raise WorkspaceConflict()
            path, data = self._request_for(order, body)
            # Confirm/cancel do not accept metadata parameters. Their existing
            # original PI id is sufficient for read reconciliation.
            if action not in ('confirm', 'cancel'):
                data = dict(data, **{'metadata[command_id]': body['command_id']})
            command = {'id': body['command_id'], 'workspace_id': ws, 'order_id': identity, 'action': action,
                'fingerprint': fingerprint, 'state': 'dispatched', 'path': path, 'data': data,
                'index': body.get('index'), 'created': clock(), 'provider_id': None,
                'key': 'ac-test-'+hashlib.sha256((ws+identity+body['command_id']).encode()).hexdigest()}
            if action in ('confirm', 'capture', 'cancel'):
                command['provider_id'] = order['payment_intent']
            self._save_command(db, command)
            self.access._audit(db, actor, ws, 'stripe.sandbox.dispatch', command['id'], order['revision'])
        def guard():
            with self.access._tx(actor) as (db, _):
                self.scope(ws, actor, write=True, owner=True)
                self._restore_guard(db, identity)
                if self._command(db, ws, command['id']) != command or self._load(db, ws, identity) != order:
                    raise WorkspaceConflict()
        try:
            response = self.client.request('POST', path, data=data, key=command['key'], guard=guard)
        except Exception:
            response = None
        return self._complete(ws, order, command, response, actor)

    @staticmethod
    def _entry(order, command, accounts):
        if sum(v for _, v in accounts) != 0:
            raise WorkspaceConflict()
        order['entries'].extend({'command': command['id'], 'account': k, 'units': v} for k, v in accounts if v)

    def _apply(self, order, command, response):
        action = command['action']; amount = order['amount']; data = command['data']
        if command['provider_id'] is not None and response.get('id') != command['provider_id']:
            raise WorkspaceConflict()
        money(response.get('amount'))
        if (response.get('livemode') is True
                or action in ('create', 'confirm', 'capture', 'cancel', 'transfer') and response.get('livemode') is not False):
            raise WorkspaceConflict()
        if action in ('create', 'confirm', 'capture', 'cancel'):
            pi = provider_id(response.get('id'), 'pi')
            if (response.get('object') != 'payment_intent' or response.get('currency') != 'usd'
                    or response.get('amount') != amount or response.get('capture_method') != 'manual'
                    or response.get('metadata', {}).get('order_id') != order['id']
                    or order['payment_intent'] is not None and pi != order['payment_intent']):
                raise WorkspaceConflict()
            state = response.get('status')
            if state not in ('requires_payment_method', 'requires_confirmation', 'requires_capture', 'requires_action', 'processing', 'succeeded', 'canceled'):
                raise WorkspaceConflict()
            if action == 'capture' and state != 'succeeded' or action == 'cancel' and state != 'canceled':
                raise WorkspaceConflict()
            if state == 'succeeded':
                charge = response.get('latest_charge')
                if type(charge) is dict:
                    charge = charge.get('id')
                provider_id(charge, 'ch')
                if response.get('amount_received') != amount:
                    raise WorkspaceConflict()
                if not order['captured']:
                    self._entry(order, command, [('processor_cash', amount), ('provider_payable', -(amount-order['platform_allocation'])),
                                                ('platform_revenue', -order['platform_allocation'])])
                order.update(captured=amount, charge=charge)
            order.update(payment_intent=pi, state=state)
        elif action == 'transfer':
            c = order['contributors'][command['index']]
            provider_id(response.get('id'), 'tr')
            if (response.get('object') != 'transfer' or response.get('amount') != c['allocation']
                    or response.get('currency') != 'usd' or response.get('destination') != c['account']
                    or response.get('source_transaction') != order['charge']):
                raise WorkspaceConflict()
            c.update(transfer_id=response['id'], transferred=c['allocation'])
            self._entry(order, command, [('processor_cash', -c['allocation']), ('provider_payable', c['allocation'])])
        elif action == 'refund':
            provider_id(response.get('id'), 're')
            if (response.get('object') != 'refund' or response.get('status') != 'succeeded'
                    or response.get('amount') != data['amount'] or response.get('currency') != 'usd'
                    or response.get('payment_intent') != order['payment_intent']):
                raise WorkspaceConflict()
            before, after = refund_targets(order, order['refunded']), refund_targets(order, order['refunded']+data['amount'])
            platform = after[-1]-before[-1]
            self._entry(order, command, [('processor_cash', -data['amount']),
                ('provider_recoverable', data['amount']-platform), ('platform_revenue', platform)])
            order['refunded'] += data['amount']
        elif action == 'reverse':
            c = order['contributors'][command['index']]; provider_id(response.get('id'), 'trr')
            if response.get('object') != 'transfer_reversal' or response.get('amount') != data['amount'] or response.get('transfer') != c['transfer_id']:
                raise WorkspaceConflict()
            c['reversed'] += data['amount']
            self._entry(order, command, [('processor_cash', data['amount']), ('provider_recoverable', -data['amount'])])
        command.update(provider_id=response['id'], state='accepted')
        order['revision'] += 1

    def _complete(self, ws, previous, command, response, actor):
        with self.access._tx(actor, write=True) as (db, _):
            self.scope(ws, actor, write=True, owner=True)
            self._restore_guard(db, previous['id'])
            current = self._command(db, ws, command['id']); order = self._load(db, ws, previous['id'])
            if current['state'] == 'accepted':
                return self.command_dto(current)
            if order != previous or current != command:
                raise WorkspaceConflict()
            try:
                if response is None:
                    raise WorkspaceConflict()
                if current['provider_id'] is not None and response.get('id') != current['provider_id']:
                    raise WorkspaceConflict()
                if (command['action'] == 'refund' and response.get('object') == 'refund'
                        and response.get('status') in ('failed', 'canceled')
                        and response.get('livemode') is not True and response.get('currency') == 'usd'
                        and type(response.get('amount')) is int and response['amount'] == command['data']['amount']
                        and response.get('payment_intent') == order['payment_intent']):
                    current.update(state='failed', provider_id=provider_id(response.get('id'), 're'))
                else:
                    self._apply(order, current, response)
            except (WorkspaceConflict, WorkspaceInvalid, KeyError, TypeError, ValueError):
                # Never persist partially applied accounting from a bad envelope.
                order = previous; current = dict(command, state='unknown')
            self._save(db, order); self._save_command(db, current)
            return self.command_dto(current)

    def webhook(self, raw, signature):
        self._enabled(); event = self.client.event(raw, signature)
        body = event.get('data', {}).get('object', {}); order_id = body.get('metadata', {}).get('order_id')
        _identity(order_id, 'spo')
        with self.store.tx() as db:
            old = db.execute('SELECT event_hash FROM stripe_sandbox_events WHERE id=?', (event['id'],)).fetchone()
            fingerprint = hashlib.sha256(raw).hexdigest()
            if old:
                if old[0] != fingerprint:
                    raise WorkspaceConflict()
                return {'accepted': True, 'replayed': True}
            rows = _rows(db, 'SELECT workspace_id FROM stripe_sandbox_orders WHERE id=?', (order_id,))
            if len(rows) != 1:
                raise WorkspaceDenied()
            ws = rows[0]['workspace_id']; order = self._load(db, ws, order_id)
            commands = _rows(db, 'SELECT id FROM stripe_sandbox_commands WHERE workspace_id=? AND order_id=?', (ws, order_id))
            request_info = event.get('request')
            key = request_info.get('idempotency_key') if type(request_info) is dict else None
            metadata_command = body.get('metadata', {}).get('command_id')
            candidates = [self._command(db, ws, row['id']) for row in commands]
            matches = [c for c in candidates if c['key'] == key or key is None and c['id'] == metadata_command]
            selected = matches[0] if len(matches) == 1 else None
            if selected is None or selected['state'] not in ('dispatched', 'unknown', 'accepted'):
                raise WorkspaceDenied()
            expected = 'pi' if selected['action'] in ('create', 'confirm', 'capture', 'cancel') else {
                'transfer': 'tr', 'refund': 're', 'reverse': 'trr'}[selected['action']]
            identity = provider_id(body.get('id'), expected)
            if selected['provider_id'] is not None and selected['provider_id'] != identity:
                raise WorkspaceConflict()
            selected['provider_id'] = identity
            self._save_command(db, selected)
            db.execute('INSERT INTO stripe_sandbox_events VALUES(?,?,?)', (event['id'], fingerprint, clock()))
            return {'accepted': True, 'replayed': False, 'reconciliation_required': selected['state'] != 'accepted'}

    def reconcile(self, ws, identity, body, actor):
        self._enabled(); self._authorize(body, ('command_id',)); _identity(body['command_id'], 'spc')
        with self.access._tx(actor) as (db, _):
            self.scope(ws, actor, write=True, owner=True); order = self._load(db, ws, identity)
            self._restore_guard(db, identity)
            command = self._command(db, ws, body['command_id'])
            if command is None or command['order_id'] != identity:
                raise WorkspaceDenied()
            if command['state'] == 'accepted':
                return self.command_dto(command)
            rid = command['provider_id']
            if rid is None:
                return self.command_dto(command) | {'original_id_required': True}
            action = command['action']
            path = ('/v1/payment_intents/'+rid if action in ('create', 'confirm', 'capture', 'cancel') else
                '/v1/transfers/'+rid if action == 'transfer' else '/v1/refunds/'+rid if action == 'refund' else command['path']+'/'+rid)
        try:
            response = self.client.request('GET', path)
        except Exception:
            response = None
        return self._complete(ws, order, command, response, actor)

    def reconcile_balance(self, ws, identity, body, actor):
        """Read the original charge/fee/net; never create or capture a payment."""
        self._enabled(); self._authorize(body, ())
        with self.access._tx(actor) as (db, _):
            self.scope(ws, actor, write=True, owner=True); order = self._load(db, ws, identity)
            self._restore_guard(db, identity)
            if not order['charge'] or order['captured'] != order['amount']:
                raise WorkspaceConflict()
        response = self.client.request('GET', '/v1/charges/'+order['charge'], data={'expand[]': 'balance_transaction'})
        transaction = response.get('balance_transaction')
        if (response.get('id') != order['charge'] or response.get('object') != 'charge'
                or response.get('livemode') is not False or response.get('payment_intent') != order['payment_intent']
                or response.get('amount') != order['captured'] or response.get('amount_refunded') != order['refunded']
                or response.get('currency') != 'usd' or response.get('paid') is not True
                or type(transaction) is not dict or transaction.get('object') != 'balance_transaction'
                or transaction.get('source') != order['charge'] or transaction.get('currency') != 'usd'
                or transaction.get('amount') != order['captured']):
            raise WorkspaceConflict()
        fee = money(transaction.get('fee'), zero=True)
        if type(transaction.get('net')) is not int or transaction['net'] != order['captured']-fee:
            raise WorkspaceConflict()
        with self.access._tx(actor, write=True) as (db, _):
            self.scope(ws, actor, write=True, owner=True); self._restore_guard(db, identity)
            current = self._load(db, ws, identity)
            if current != order or current['processor_fee'] is not None and current['processor_fee'] != fee:
                raise WorkspaceConflict()
            if current['processor_fee'] is None:
                self._entry(current, {'id': 'original-charge-fee'}, [('processor_fee_expense', fee), ('processor_cash', -fee)])
                current['processor_fee'] = fee; current['revision'] += 1
                self._save(db, current)
            return self.dto(current)
