"""Isolated API publication with a fixed public fixture key; no deployed route."""
import base64
from dataclasses import replace
import hashlib
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient
import pytest

from agent_market.reliability_portable_receipt import ReceiptInvalid, SigningConfig, verify
from agent_market.reliability_public_receipt import (
    DisclosureApproval, HEADERS, KeyPublicationApproval, create_trust_app)

NOW = 1802851200
REF = 'public_' + 'a' * 32
AUD = 'reliability-preview'
ORIGIN = 'https://trust.example'
PATH = '/v1/receipts/' + REF + '?audience=' + AUD


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')


def fixture(**options):
    # A published deterministic test vector, never generated or persisted.
    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex('01' * 32))
    config = SigningConfig(ORIGIN, 'fixture-receipt', private, (AUD,))
    state = {'projection': {'subject_ref': REF, 'contract_id': 'docs.search.v1',
        'version_digest': 'b' * 64, 'evidence_digest': 'c' * 64, 'verdict': 'qualified',
        'observed_at': NOW - 10, 'expires_at': NOW + 100}, 'calls': [], 'revoked': False,
        'authorized': True, 'now': NOW}
    def source(subject):
        state['calls'].append(('projection', subject))
        return dict(state['projection'])
    def approve(subject, audience, projection_hash):
        state['calls'].append(('disclosure', subject, audience, projection_hash))
        return DisclosureApproval(subject, audience, projection_hash, NOW + 90, 1, 2, 3, state['authorized'])
    def key_source(issuer, identity, public_hash):
        state['calls'].append(('key', issuer, identity, public_hash))
        return KeyPublicationApproval(issuer, identity, public_hash, NOW + 90, 4, state['revoked'])
    arguments = {'projection_source': source, 'disclosure_authorizer': approve,
        'key_status_source': key_source, 'allowed_hosts': ('trust.example',), 'clock': lambda: state['now'], **options}
    app = create_trust_app(config, **arguments)
    return TestClient(app, base_url=ORIGIN), state, config


def security(response):
    for key, value in HEADERS.items():
        assert response.headers[key] == value
    assert 'access-control-allow-origin' not in response.headers


def test_default_app_has_no_public_routes_or_callback_side_effects():
    def fail(*_):
        pytest.fail('A disabled factory invoked a callback.')
    with TestClient(create_trust_app(projection_source=fail, disclosure_authorizer=fail,
                                   key_status_source=fail), base_url=ORIGIN) as client:
        for path in (PATH, '/.well-known/jwks.json', '/robots.txt', '/openapi.json', '/docs', '/'):
            response = client.get(path)
            assert response.status_code == 404
            security(response)


def test_receipt_uses_existing_ed25519_offline_verifier_and_only_fixed_public_fields():
    client, state, config = fixture()
    response = client.get(PATH)
    assert response.status_code == 200
    security(response)
    body = response.json()
    assert set(body) == {'profile', 'receipt', 'signature', 'key_status'}
    assert body['receipt']['projection'] == state['projection']
    assert body['receipt']['expires_at'] == NOW + 60
    result = verify(canonical(body['receipt']), body['signature'], trusted_keys={config.key_id: config.private_key.public_key()},
                    issuer=ORIGIN, audience=AUD, now=NOW)
    assert result['signature_verified']
    assert not any(result[name] for name in ('current_quality_verified', 'business_completion_verified',
        'payment_authorized', 'legal_settlement_verified', 'offline_revocation_checked'))
    assert [item[0] for item in state['calls']] == ['key', 'projection', 'disclosure', 'key', 'projection', 'disclosure']
    for secret in ('workspace_id', 'ws_', 'session', 'email', 'private_key', 'destination', 'prompt', 'SLA'):
        assert secret not in response.text


def test_jwks_is_current_and_revoked_key_is_removed_without_offline_freshness_claim():
    client, state, config = fixture()
    response = client.get('/.well-known/jwks.json')
    assert response.status_code == 200
    security(response)
    body = response.json()
    assert len(body['keys']) == 1
    key = body['keys'][0]
    assert key == {'kty': 'OKP', 'crv': 'Ed25519', 'use': 'sig', 'alg': 'EdDSA', 'kid': config.key_id,
                   'x': base64.urlsafe_b64encode(config.private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).rstrip(b'=').decode()}
    public = Ed25519PublicKey.from_public_bytes(base64.urlsafe_b64decode(key['x'] + '='))
    receipt = client.get(PATH).json()
    assert verify(canonical(receipt['receipt']), receipt['signature'], trusted_keys={key['kid']: public},
                  issuer=ORIGIN, audience=AUD, now=NOW)['signature_verified']
    state['revoked'] = True
    assert client.get(PATH).status_code == 404
    revoked = client.get('/.well-known/jwks.json').json()
    assert revoked['keys'] == [] and revoked['key_status']['revoked'] is True
    assert not verify(canonical(receipt['receipt']), receipt['signature'], trusted_keys={key['kid']: public},
                      issuer=ORIGIN, audience=AUD, now=NOW)['offline_revocation_checked']


@pytest.mark.parametrize('path', [PATH + '&audience=' + AUD, PATH + '&extra=1',
    '/v1/receipts/' + REF, '/v1/receipts/' + REF + '?audience=other',
    '/v1/receipts/ws_' + 'a' * 32 + '?audience=' + AUD,
    '/.well-known/jwks.json?extra=1', '/docs', '/openapi.json'])
def test_unknown_scope_query_and_documentation_do_not_reach_sources(path):
    client, state, _ = fixture()
    response = client.get(path)
    assert response.status_code == 404
    assert not state['calls']
    security(response)


@pytest.mark.parametrize('change', [
    {'authorized': False}, {'authorized': 1}, {'public_ref': 'public_' + 'd' * 32},
    {'audience': 'other'}, {'projection_sha256': '0' * 64}, {'expires_at': NOW},
    {'expires_at': NOW + 301}, {'expires_at': float(NOW + 20)}, {'authority_revision': 0},
    {'disclosure_revision': True}, {'revocation_revision': -1},
])
def test_typed_explicit_disclosure_approval_scope_time_and_revisions_fail_closed(change):
    def approve(subject, audience, projection_hash):
        return replace(DisclosureApproval(subject, audience, projection_hash, NOW + 90, 1, 2, 3, True), **change)
    client, _, _ = fixture(disclosure_authorizer=approve)
    response = client.get(PATH)
    assert response.status_code == 404 and response.json() == {'detail': 'Not found.'}
    security(response)


@pytest.mark.parametrize('value', [True, {'authorized': True}, None, 'approved'])
def test_truthy_legacy_or_untyped_disclosure_is_not_authorization(value):
    client, _, _ = fixture(disclosure_authorizer=lambda *_: value)
    assert client.get(PATH).status_code == 404


@pytest.mark.parametrize('change', [{'issuer': 'https://other.example'}, {'key_id': 'different'},
    {'public_key_sha256': '0' * 64}, {'expires_at': NOW}, {'expires_at': NOW + 301},
    {'revision': True}, {'revoked': 0}, {'revoked': True}])
def test_current_key_binding_and_revocation_must_be_explicit(change):
    def key_source(issuer, identity, public_hash):
        return replace(KeyPublicationApproval(issuer, identity, public_hash, NOW + 90, 1, False), **change)
    client, _, _ = fixture(key_status_source=key_source)
    assert client.get(PATH).status_code == 404


@pytest.mark.parametrize('change', [{'email': 'private@example.invalid'}, {'workspace_id': 'ws_' + 'a' * 32},
    {'observed_at': NOW + 1}, {'expires_at': NOW}, {'verdict': 'certified_business_success'},
    {'evidence_digest': 'not-a-digest'}, {'contract_id': 'arbitrary'}])
def test_source_cannot_publish_private_extra_stale_or_nonfixed_projection(change):
    client, state, _ = fixture()
    state['projection'].update(change)
    response = client.get(PATH)
    assert response.status_code == 404 and 'private@example' not in response.text


@pytest.mark.parametrize('kind', ['projection', 'disclosure', 'key', 'time', 'exception'])
def test_final_current_recheck_denies_changes_and_private_callback_exceptions(kind):
    calls = {'source': 0, 'approval': 0, 'key': 0}
    def source(subject):
        calls['source'] += 1
        value = {'subject_ref': REF, 'contract_id': 'docs.search.v1', 'version_digest': 'b' * 64,
            'evidence_digest': 'c' * 64, 'verdict': 'qualified', 'observed_at': NOW - 10, 'expires_at': NOW + 100}
        if kind == 'projection' and calls['source'] == 2:
            value['evidence_digest'] = 'd' * 64
        if kind == 'exception':
            raise RuntimeError('/private/deployment/secret')
        return value
    def approval(subject, audience, projection_hash):
        calls['approval'] += 1
        return DisclosureApproval(subject, audience, projection_hash, NOW + 90, 1,
            2 if calls['approval'] == 1 or kind != 'disclosure' else 3, 1, True)
    def key_source(issuer, identity, public_hash):
        calls['key'] += 1
        return KeyPublicationApproval(issuer, identity, public_hash, NOW + 90,
            1 if calls['key'] == 1 or kind != 'key' else 2, False)
    clock_calls = []
    def clock():
        clock_calls.append(1)
        return NOW if len(clock_calls) == 1 or kind != 'time' else NOW + 60
    client, _, _ = fixture(projection_source=source, disclosure_authorizer=approval,
                           key_status_source=key_source, clock=clock)
    response = client.get(PATH)
    assert response.status_code == 404
    assert response.json() == {'detail': 'Not found.'}
    assert '/private/' not in response.text


def test_authority_and_projection_are_not_cached_or_bypassed_by_conditional_headers():
    client, state, _ = fixture()
    assert client.get(PATH).status_code == 200
    state['authorized'] = False
    response = client.get(PATH, headers={'If-None-Match': '*', 'If-Modified-Since': 'tomorrow'})
    assert response.status_code == 404
    security(response)


@pytest.mark.parametrize('headers', [{'Host': 'evil.example'}, {'Host': 'TRUST.EXAMPLE'},
    {'Host': 'trust.example:443'}, {'Host': 'evil.example', 'X-Forwarded-Host': 'trust.example'}])
def test_host_allowlist_is_exact_and_ignores_forwarding_headers(headers):
    client, state, _ = fixture()
    response = client.get(PATH, headers=headers)
    assert response.status_code == 404 and not state['calls']
    security(response)


def test_http_duplicate_hosts_rate_limit_and_unknown_methods_keep_security_headers():
    client, state, _ = fixture(requests_per_minute=2)
    assert client.get('http://trust.example' + PATH).status_code == 404
    assert client.get(PATH, headers=[('Host', 'trust.example'), ('Host', 'trust.example')]).status_code == 404
    response = client.post(PATH)
    assert response.status_code == 405
    security(response)
    assert client.get(PATH).status_code == 200
    before = len(state['calls'])
    response = client.get(PATH, headers={'X-Forwarded-For': '192.0.2.44'})
    assert response.status_code == 429 and response.headers['Retry-After'] == '60'
    assert len(state['calls']) == before
    security(response)


def test_enabled_robots_disallows_indexing_without_source_reads():
    client, state, _ = fixture()
    response = client.get('/robots.txt')
    assert response.status_code == 200 and response.text == 'User-agent: *\nDisallow: /\n'
    assert not state['calls']
    security(response)


@pytest.mark.parametrize('change', [{'projection_source': None}, {'disclosure_authorizer': None},
    {'key_status_source': None}, {'allowed_hosts': ()}, {'allowed_hosts': ['trust.example']},
    {'allowed_hosts': ('*.example',)}, {'allowed_hosts': ('trust.example', 'trust.example')},
    {'allowed_hosts': ('trust.example/path',)}, {'allowed_hosts': ('user@trust.example',)},
    {'requests_per_minute': True}, {'requests_per_minute': 0}, {'requests_per_minute': 601},
    {'clock': None}])
def test_missing_explicit_configuration_is_rejected_without_default_publication(change):
    with pytest.raises(ReceiptInvalid):
        fixture(**change)
