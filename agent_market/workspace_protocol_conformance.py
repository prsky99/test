"""Private synthetic wire-subset checks and existing TEST_UNIT reconciliation.

This module never calls a provider, moves funds, creates capture/refund events,
or issues payment authority. Reports reference the existing signed sandbox
receipts and ledger. Local fixture signatures are not network payment proofs.
"""
import base64
import binascii
import copy
import hashlib
import hmac
import json
import re
import secrets

from .shadow_ledger import SignedWorkspaceModule, clock, exact
from .workspace_access import (WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid,
                               _canonical, _hash, _identity, _rows)

PROFILE = 'workspace-protocol-conformance-v1'
NOTICE = 'synthetic-protocol-existing-ledger-review-v1'
CRYPTO_NOTICE = 'offline-eip3009-signature-inspection-v1'
MAX_REPORTS = 50
FLAGS = {'simulation': True, 'asset': 'TEST_UNIT', 'actual_money': False,
         'payment_enabled': False, 'provider_payout_enabled': False,
         'commercial_enabled': False, 'operating_acceptance': False,
         'official_protocol_certification': False, 'external_provider_calls': 0}
SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS workspace_protocol_reports (
       id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,event_reference TEXT NOT NULL,
       created REAL NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL,
       UNIQUE(workspace_id,event_reference))''',
    'CREATE TABLE IF NOT EXISTS workspace_protocol_restore_blocks(id TEXT PRIMARY KEY)',
)
WIRE_PROFILES = (
    {'id': 'x402-v2-http-exact-fixture-v1', 'protocol_revision': '2',
     'transport': 'HTTP', 'scheme': 'exact', 'network': 'eip155:84532',
     'binding': 'local-test-unit-fixture-v1',
     'source': 'https://github.com/x402-foundation/x402/blob/main/specs/transports-v2/http.md'},
    {'id': 'x402-v2-http-batch-fixture-v1', 'protocol_revision': '2',
     'transport': 'HTTP', 'scheme': 'batch-settlement', 'network': 'eip155:84532',
     'binding': 'local-test-unit-fixture-v1',
     'source': 'https://github.com/x402-foundation/x402/blob/main/specs/schemes/batch-settlement/scheme_batch_settlement.md'},
)
FIXTURE_RESOURCE = 'https://resource.example.invalid/synthetic'
FIXTURE_ASSET = '0x0000000000000000000000000000000000000001'
FIXTURE_PAYEE = '0x0000000000000000000000000000000000000002'


def compatibility_matrix():
    """Product SDK versions never assert upstream protocol certification."""
    from .workspace_remote_a2a import SESSION_PROFILE
    return [
        {'product': 'Public workflow SDK 1', 'product_version': '1.0.0',
         'gateway_profile': 'existing-public-gateway', 'migration': 'unchanged',
         'deployment': 'existing public download', 'customer_bff': False},
        {'product': 'Admin managed SDK 1', 'product_version': '1.1.0',
         'gateway_profile': 'existing-admin-managed-export', 'migration': 'unchanged',
         'deployment': 'existing reviewed admin export', 'customer_bff': False},
        {'product': 'Private SDK 2', 'product_version': '2.0.0',
         'gateway_profile': 'workspace-sdk-v2', 'migration': 'explicit deployment',
         'deployment': 'approved HTTPS origin and BFF', 'customer_bff': True},
        {'product': 'Private typed SDK 2', 'product_version': '2.1.0',
         'gateway_profile': 'workspace-typed-sdk-v2', 'migration': 'explicit deployment',
         'deployment': 'approved HTTPS origin and BFF', 'customer_bff': True},
        {'product': 'Bounded MCP execution', 'gateway_profile': 'mcp-stateless-v1',
         'protocol_revision': 'connection-negotiated', 'migration': 'no forced revision change',
         'latest_upstream_documentation': '2026-07-28', 'latest_support_asserted': False},
        {'product': 'Bounded A2A execution', 'gateway_profile': 'a2a-sync-v1',
         'protocol_revision': 'existing connection profile', 'migration': 'no forced revision change',
         'latest_upstream_documentation': '1.0', 'latest_support_asserted': False},
        {'product': 'Private asynchronous A2A sessions',
         'gateway_profile': SESSION_PROFILE, 'protocol_revision': '0.3',
         'deployment': 'explicit private task bindings and current organization authority',
         'migration': 'separate asynchronous task API; existing polling retained',
         'customer_bff': True, 'typed_dag_node': False, 'sdk_profile': False,
         'stream_slice_seconds': 45, 'absolute_task_seconds': 900,
         'latest_support_asserted': False},
    ]


def decode_header(value):
    """Strict bounded canonical Base64 JSON, not a network payment verifier."""
    if type(value) is not str or not 1 <= len(value) <= 8192:
        raise WorkspaceInvalid()
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError()
            result[key] = item
        return result
    try:
        raw = base64.b64decode(value.encode('ascii'), validate=True)
        if base64.b64encode(raw).decode('ascii') != value or len(raw) > 4096:
            raise ValueError()
        result = json.loads(raw.decode('ascii'), object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        exact(result, result.keys() if type(result) is dict else ())
        if _canonical(result).encode('ascii') != raw:
            raise ValueError()
        return result
    except (ValueError, TypeError, UnicodeError, RecursionError, binascii.Error):
        raise WorkspaceInvalid() from None


def _encoded(value):
    return base64.b64encode(_canonical(value).encode('ascii')).decode('ascii')


def validate_fixture_headers(headers, selected, quote_hash, amount, key):
    """Verify this exact synthetic binding, never arbitrary EVM signatures."""
    exact(headers, ('PAYMENT-REQUIRED', 'PAYMENT-SIGNATURE', 'PAYMENT-RESPONSE'))
    required, payload, response = (decode_header(headers[name]) for name in
        ('PAYMENT-REQUIRED', 'PAYMENT-SIGNATURE', 'PAYMENT-RESPONSE'))
    expected = {'scheme': selected['scheme'], 'network': selected['network'],
        'amount': str(amount), 'asset': FIXTURE_ASSET, 'payTo': FIXTURE_PAYEE,
        'maxTimeoutSeconds': 60}
    if (required != {'x402Version': 2, 'resource': {'url': FIXTURE_RESOURCE}, 'accepts': [expected]}
            or type(required.get('x402Version')) is not int
            or type(required['accepts'][0]['maxTimeoutSeconds']) is not int):
        raise WorkspaceInvalid()
    exact(payload, ('x402Version', 'accepted', 'payload'))
    fixture = {'profile': 'local-test-unit-fixture-v1', 'quote_hash': quote_hash,
               'amount': str(amount), 'audience': FIXTURE_RESOURCE}
    signature = hmac.new(key, _canonical(fixture).encode('ascii'), hashlib.sha256).hexdigest()
    exact(payload['payload'], tuple(fixture) + ('fixture_signature',))
    supplied_signature = payload['payload']['fixture_signature']
    if (type(payload['x402Version']) is not int or payload['x402Version'] != 2
            or payload['accepted'] != expected
            or {name: payload['payload'][name] for name in fixture} != fixture
            or type(supplied_signature) is not str
            or not hmac.compare_digest(supplied_signature, signature)):
        raise WorkspaceDenied()
    expected_response = {'success': True, 'payer': 'synthetic-payer',
                         'transaction': '', 'network': selected['network']}
    if selected['scheme'] == 'batch-settlement':
        expected_response['extensions'] = {'local-fixture': {'commitment_id': quote_hash}}
    if response != expected_response or response.get('success') is not True:
        raise WorkspaceInvalid()
    return True


def validate_fixture_mandate(value, quote_hash, amount, key):
    """Internal quote-bound mandate fixture; not an AP2 SD-JWT verifier."""
    exact(value, ('profile', 'checkout_hash', 'asset', 'amount', 'audience', 'signature'))
    expected = {'profile': 'local-quote-mandate-fixture-v1', 'checkout_hash': quote_hash,
                'asset': 'TEST_UNIT', 'amount': amount, 'audience': FIXTURE_RESOURCE}
    if ({name: value[name] for name in expected} != expected
            or type(value['amount']) is not int
            or type(value['signature']) is not str
            or not hmac.compare_digest(value['signature'], hmac.new(
                key, _canonical(expected).encode('ascii'), hashlib.sha256).hexdigest())):
        raise WorkspaceDenied()
    return True


def wire_suite(selected, quote_hash, amount, key):
    required = {'scheme': selected['scheme'], 'network': selected['network'],
        'amount': str(amount), 'asset': FIXTURE_ASSET, 'payTo': FIXTURE_PAYEE,
        'maxTimeoutSeconds': 60}
    fixture = {'profile': 'local-test-unit-fixture-v1', 'quote_hash': quote_hash,
               'amount': str(amount), 'audience': FIXTURE_RESOURCE}
    fixture['fixture_signature'] = hmac.new(key, _canonical(fixture).encode('ascii'), hashlib.sha256).hexdigest()
    response = {'success': True, 'payer': 'synthetic-payer', 'transaction': '', 'network': selected['network']}
    if selected['scheme'] == 'batch-settlement':
        response['extensions'] = {'local-fixture': {'commitment_id': quote_hash}}
    headers = {'PAYMENT-REQUIRED': _encoded({'x402Version': 2,
        'resource': {'url': FIXTURE_RESOURCE}, 'accepts': [required]}),
        'PAYMENT-SIGNATURE': _encoded({'x402Version': 2, 'accepted': required, 'payload': fixture}),
        'PAYMENT-RESPONSE': _encoded(response)}
    validate_fixture_headers(headers, selected, quote_hash, amount, key)
    mandate = {'profile': 'local-quote-mandate-fixture-v1', 'checkout_hash': quote_hash,
               'asset': 'TEST_UNIT', 'amount': amount, 'audience': FIXTURE_RESOURCE}
    mandate['signature'] = hmac.new(key, _canonical(mandate).encode('ascii'), hashlib.sha256).hexdigest()
    validate_fixture_mandate(mandate, quote_hash, amount, key)
    checks = ['canonical_headers', 'requirements_binding', 'fixture_authorization', 'quote_mandate_binding']
    for name, mutation in (('wrong_amount', {'amount': str(amount + 1)}),
                           ('wrong_network', {'network': 'eip155:1'}),
                           ('wrong_payee', {'payTo': FIXTURE_ASSET})):
        bad = copy.deepcopy(headers)
        changed = decode_header(bad['PAYMENT-SIGNATURE'])
        changed['accepted'].update(mutation)
        bad['PAYMENT-SIGNATURE'] = _encoded(changed)
        try:
            validate_fixture_headers(bad, selected, quote_hash, amount, key)
        except (WorkspaceInvalid, WorkspaceDenied):
            checks.append('reject_' + name)
        else:
            raise WorkspaceConflict()
    return {'passed': True, 'checks': checks,
            'scope': 'synthetic HTTP wire and local quote-bound mandate subset',
            'network_signature_verified': False, 'ap2_credential_verified': False,
            'upstream_commit_pinned': False, 'network_binding_implemented': False,
            'real_escrow_deployed': False}


class ProtocolConformance(SignedWorkspaceModule):
    def __init__(self, access, sandbox_payments):
        if sandbox_payments.access is not access:
            raise WorkspaceInvalid()
        super().__init__(access, PROFILE, SCHEMA)
        self.payments = sandbox_payments
        self.agreements = sandbox_payments.agreements

    def cryptographic_check(self, ws, body, actor):
        """Inspect a caller-pinned public proof; this grants no payment authority."""
        from .workspace_x402_eip3009 import verify_authorization
        exact(body, ('payment', 'requirements', 'expected_from', 'expected_nonce',
                     'resource_url', 'authorized', 'notice'))
        if body['authorized'] is not True or body['notice'] != CRYPTO_NOTICE:
            raise WorkspaceInvalid()
        with self.access._tx(actor) as (db, _):
            owner = self.payments._owner(ws, actor)
        result = verify_authorization(body['payment'], body['requirements'],
            expected_from=body['expected_from'], expected_nonce=body['expected_nonce'],
            resource_url=body['resource_url'])
        with self.access._tx(actor, write=True) as (db, _):
            if self.payments._owner(ws, actor) != owner:
                raise WorkspaceConflict()
            self.access._audit(db, actor, ws, 'protocol_conformance.offline_signature',
                result['requirements_sha256'], None)
        # Do not retain supplied wire, sender addresses or nonce in the report.
        return {k:v for k,v in result.items() if k not in ('recovered_from', 'nonce_reference')}

    def _read(self, db, ws, identity):
        _identity(identity, 'wpcr')
        rows = _rows(db, 'SELECT * FROM workspace_protocol_reports WHERE id=? AND workspace_id=?', (identity, ws))
        if len(rows) != 1:
            raise WorkspaceDenied()
        row, value = rows[0], self.opened(rows[0])
        if (value.get('profile') != PROFILE or any(value.get(name) != row[name] for name in
                ('id', 'workspace_id', 'event_reference', 'created'))):
            raise WorkspaceConflict()
        restored = bool(db.execute('SELECT 1 FROM workspace_protocol_restore_blocks WHERE id=?', (identity,)).fetchone())
        return value, restored

    @staticmethod
    def _dto(value, restored=False):
        result = {name: value[name] for name in ('id', 'event_reference', 'created', 'profile_id',
            'wire_checks', 'ledger', 'states', 'source_refs')}
        result['restored'] = restored
        result['historical_observation_only'] = True
        result['current_authority'] = 'restore_blocked' if restored else 'not_revalidated_for_execution'
        if restored:
            result['states'] = dict(result['states'], source_use='restore_blocked')
        return result | FLAGS

    def _source(self, db, ws, capture_id, refund_id, actor):
        owner = self.payments._owner(ws, actor)
        capture = self.payments._intent(db, ws, capture_id)
        if capture['owner'] != owner or capture['action'] != 'capture':
            raise WorkspaceDenied()
        contract, state = self.agreements._current(db, ws, capture['target_id'], actor, admission=False)
        quote = self.agreements._quote(contract, capture['units'])
        if capture['command']['quote_hash'] != quote['quote_hash']:
            raise WorkspaceConflict()
        receipt = self.payments._receipt(db, ws, capture)
        refs = {'capture_intent_id': capture_id, 'capture_receipt_sha256': _hash(receipt) if receipt else None,
                'refund_intent_id': refund_id, 'refund_receipt_sha256': None,
                'agreement_id': contract['id'], 'agreement_revision': state['revision'],
                'quote_hash': quote['quote_hash'], 'settlement_id': None}
        states = {'authority_at_observation': 'checked', 'authorization': 'local_fixture_valid',
            'commitment': 'not_observed', 'claim': 'not_exercised',
            'settlement': 'not_observed', 'finality': 'not_exercised',
            'refund': 'not_requested', 'payout': 'disabled', 'business_outcome': 'unassessed'}
        ledger = {'balanced': True, 'capture_units': capture['units'], 'refunded_units': 0,
            'remaining_units': 0, 'event_count': 0, 'receipt_state': 'unknown_hold',
            'provider_allocation': None, 'allocation_is_payout': False}
        if not receipt:
            if refund_id is not None:
                raise WorkspaceInvalid()
            return quote, refs, states, ledger
        settled = self.agreements._settlement(db, ws, receipt['result']['id'])
        refs['settlement_id'] = settled['id']
        ledger.update(refunded_units=settled['refunded_units'],
            remaining_units=settled['remaining']['gross_units'], event_count=len(settled['events']),
            receipt_state='simulated_recorded', provider_allocation=settled['remaining']['provider_units'])
        states['settlement'] = 'test_unit_recorded'
        if refund_id is not None:
            refund = self.payments._intent(db, ws, refund_id)
            if (refund['owner'] != owner or refund['action'] != 'refund'
                    or refund['target_id'] != settled['id']):
                raise WorkspaceDenied()
            refund_receipt = self.payments._receipt(db, ws, refund)
            refs['refund_receipt_sha256'] = _hash(refund_receipt) if refund_receipt else None
            states['refund'] = 'test_unit_recorded' if refund_receipt else 'unknown_hold'
        elif settled['refunded_units']:
            states['refund'] = 'existing_ledger_refund'
        return quote, refs, states, ledger

    def run(self, ws, body, actor):
        exact(body, ('profile_id', 'capture_intent_id', 'refund_intent_id',
                     'event_reference', 'authorized', 'notice'))
        selected = next((value for value in WIRE_PROFILES if value['id'] == body['profile_id']), None)
        if (selected is None or body['authorized'] is not True or body['notice'] != NOTICE
                or type(body['event_reference']) is not str
                or not re.fullmatch(r'conformance_[a-zA-Z0-9_-]{1,48}', body['event_reference'])):
            raise WorkspaceInvalid()
        _identity(body['capture_intent_id'], 'wspi')
        if body['refund_intent_id'] is not None:
            _identity(body['refund_intent_id'], 'wspi')
        with self.access._tx(actor, write=True) as (db, _):
            self.scope(ws, actor, write=True, owner=True)
            quote, refs, states, ledger = self._source(db, ws, body['capture_intent_id'], body['refund_intent_id'], actor)
            previous = _rows(db, 'SELECT id FROM workspace_protocol_reports WHERE workspace_id=? AND event_reference=?', (ws, body['event_reference']))
            if previous:
                value, restored = self._read(db, ws, previous[0]['id'])
                if restored or value['request_hash'] != _hash(body):
                    raise WorkspaceConflict()
                return self._dto(value) | {'replayed': True}
            if db.execute('SELECT COUNT(*) FROM workspace_protocol_reports WHERE workspace_id=?', (ws,)).fetchone()[0] >= MAX_REPORTS:
                raise WorkspaceConflict()
            checks = wire_suite(selected, quote['quote_hash'], quote['allocation']['gross_units'], self.key)
            if selected['scheme'] == 'batch-settlement':
                states['commitment'] = 'synthetic_fixture_only'
            value = {'profile': PROFILE, 'id': 'wpcr_' + secrets.token_hex(16), 'workspace_id': ws,
                'event_reference': body['event_reference'], 'request_hash': _hash(body),
                'created': clock(), 'profile_id': selected['id'], 'source_refs': refs,
                'wire_checks': checks, 'states': states, 'ledger': ledger}
            db.execute('INSERT INTO workspace_protocol_reports VALUES(?,?,?,?,?,?)',
                (value['id'], ws, value['event_reference'], value['created'], _canonical(value), self.sign(value)))
            self.access._audit(db, actor, ws, 'protocol_conformance.record', value['id'], None)
            return self._dto(value) | {'replayed': False}

    def report(self, ws, identity, actor):
        with self.access._tx(actor) as (db, _):
            self.scope(ws, actor, owner=True)
            value, restored = self._read(db, ws, identity)
            return self._dto(value, restored)

    def status(self, ws, actor):
        with self.access._tx(actor) as (db, user):
            member, _ = self.scope(ws, actor, owner=True)
            rows = _rows(db, 'SELECT id FROM workspace_protocol_reports WHERE workspace_id=? ORDER BY created DESC,id LIMIT 51', (ws,))
            if len(rows) > MAX_REPORTS:
                raise WorkspaceConflict()
            reports = [self._dto(*self._read(db, ws, row['id'])) for row in rows]
            intents = _rows(db, 'SELECT * FROM workspace_sandbox_payment_intents WHERE workspace_id=? ORDER BY created DESC,id LIMIT 101', (ws,))
            sources = []
            for row in intents:
                try:
                    value = self.payments._intent(db, ws, row['id'])
                    sources.append({key: value[key] for key in ('id', 'action', 'target_id', 'units', 'event_reference')})
                except WorkspaceDenied:
                    continue
            return {'profile': PROFILE, 'notice': NOTICE, 'profiles': copy.deepcopy(WIRE_PROFILES),
                'cryptographic_profile': {'id':'x402-v2-exact-eip3009-base-sepolia-usdc-v1',
                    'notice':CRYPTO_NOTICE, 'signature_inspection_only':True,
                    'independent_context_required':True, 'verified_payment':False,
                    'settlement_authorized':False},
                'reports': reports, 'sources': sources, 'compatibility': compatibility_matrix(),
                'can_write': user['role'] != 'operator' and member['member_role'] == 'owner',
                'max_reports': MAX_REPORTS,
                'security_boundary': 'Browser encapsulation is not secret storage; current BFF and server authorization remain authoritative.',
                'ap2_support': 'local quote-bound fixture only; no AP2 credential or payment mandate acceptance',
                'implementation_pin': 'local-test-unit-fixture-v1; upstream commit pin required before a network adapter', **FLAGS}
