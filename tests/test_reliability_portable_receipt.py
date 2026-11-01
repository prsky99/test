"""Ephemeral fixture keys sign metadata only; no key files or public service."""
import base64
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from agent_market.reliability_portable_receipt import (
    PortableReceiptIssuer, ReceiptInvalid, SigningConfig, verify)

ISSUER = 'https://agentconcierge.biz'
AUDIENCE = 'reliability-preview'
NOW = 1802851200
SUBJECT = 'public_' + 'a' * 32


def projection(**change):
    return {'subject_ref': SUBJECT, 'contract_id': 'docs.search.v1',
        'version_digest': 'b' * 64, 'evidence_digest': 'c' * 64,
        'verdict': 'qualified', 'observed_at': NOW - 10, 'expires_at': NOW + 100, **change}


def issuer(source=None, identity='fixture-key-1'):
    private = Ed25519PrivateKey.generate()
    config = SigningConfig(ISSUER, identity, private, (AUDIENCE,))
    return PortableReceiptIssuer(config, projection_source=source or (lambda subject: projection())), private


def test_disabled_by_default_and_metadata_signature_never_means_current_quality_payment_or_delivery():
    disabled = PortableReceiptIssuer()
    assert not disabled.status()['enabled'] and not disabled.status()['public_route_registered']
    with pytest.raises(ReceiptInvalid): disabled.issue(SUBJECT, AUDIENCE, now=NOW)
    core, key = issuer(); raw, signature = core.issue(SUBJECT, AUDIENCE, now=NOW)
    result = verify(raw, signature, trusted_keys={'fixture-key-1': key.public_key()},
        issuer=ISSUER, audience=AUDIENCE, now=NOW)
    assert result['signature_verified'] and result['time_verified']
    assert not any(result[field] for field in ('offline_revocation_checked', 'current_quality_verified',
        'business_completion_verified', 'payment_authorized', 'legal_settlement_verified'))
    body = json.loads(raw)
    assert body['expires_at'] == NOW + 100
    assert set(body['projection']) == set(projection())
    assert all(text not in raw.decode() for text in ('workspace_id', 'ws_', 'destination', 'prompt', 'email', 'session', 'private_key'))
    assert 'Ed25519PrivateKey' not in repr(core._config)


@pytest.mark.parametrize('attack', ['signature', 'wrong_key', 'retired_key', 'audience', 'issuer',
    'expired', 'future', 'hmac_receipt', 'noncanonical', 'duplicate', 'extra', 'algorithm', 'nonfinite'])
def test_wrong_scope_keys_rotation_expiry_and_tamper_fail_closed(attack):
    core, key = issuer(); raw, signature = core.issue(SUBJECT, AUDIENCE, now=NOW)
    keys = {'fixture-key-1': key.public_key()}; audience = AUDIENCE; current = NOW; selected_issuer = ISSUER
    if attack == 'signature': signature = signature[:-1] + ('A' if signature[-1] != 'A' else 'B')
    if attack == 'wrong_key': keys = {'fixture-key-1': Ed25519PrivateKey.generate().public_key()}
    if attack == 'retired_key': keys = {'fixture-key-2': Ed25519PrivateKey.generate().public_key()}
    if attack == 'audience': audience = 'different-preview'
    if attack == 'issuer': selected_issuer = 'https://different.example'
    if attack == 'expired': current = NOW + 100
    if attack == 'future': current = NOW - 1
    if attack == 'hmac_receipt': signature = 'v1.' + 'a' * 64
    if attack == 'noncanonical': raw += b' '
    if attack == 'duplicate': raw = b'{"profile":"duplicate",' + raw[1:]
    if attack in ('extra', 'algorithm', 'nonfinite'):
        value = json.loads(raw)
        if attack == 'extra': value['workspace_id'] = 'ws_' + 'a' * 32
        if attack == 'algorithm': value['algorithm'] = 'none'
        if attack == 'nonfinite': value['issued_at'] = float('nan')
        raw = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
    with pytest.raises(ReceiptInvalid):
        verify(raw, signature, trusted_keys=keys, issuer=selected_issuer, audience=audience, now=current)


@pytest.mark.parametrize('change', [{'prompt': 'private'}, {'workspace_id': 'ws_' + 'd' * 32},
    {'destination': 'https://receiver.example/private'}, {'subject_ref': 'ag_' + 'a' * 32},
    {'contract_id': 'arbitrary.contract'}, {'verdict': 'business_success'},
    {'observed_at': NOW + 1}, {'expires_at': NOW}, {'observed_at': True}, {'version_digest': 'email@example.invalid'}])
def test_source_projection_has_fixed_minimal_public_fields_and_current_time(change):
    core, _ = issuer(lambda subject: projection(**change))
    with pytest.raises(ReceiptInvalid): core.issue(SUBJECT, AUDIENCE, now=NOW)


def test_key_rotation_is_explicit_and_old_key_trust_must_be_removed_to_revoke_offline():
    old, old_key = issuer(identity='fixture-key-old')
    new, new_key = issuer(identity='fixture-key-new')
    first = old.issue(SUBJECT, AUDIENCE, now=NOW)
    second = new.issue(SUBJECT, AUDIENCE, now=NOW)
    keys = {'fixture-key-old': old_key.public_key(), 'fixture-key-new': new_key.public_key()}
    for raw, signature in (first, second):
        assert verify(raw, signature, trusted_keys=keys, issuer=ISSUER, audience=AUDIENCE, now=NOW)['signature_verified']
    with pytest.raises(ReceiptInvalid):
        verify(*first, trusted_keys={'fixture-key-new': new_key.public_key()}, issuer=ISSUER, audience=AUDIENCE, now=NOW)
    assert verify(*second, trusted_keys={'fixture-key-new': new_key.public_key()}, issuer=ISSUER, audience=AUDIENCE, now=NOW)['signature_verified']


def test_signed_but_invalid_policy_is_rejected_independently_of_a_valid_signature():
    core, key = issuer(); raw, _ = core.issue(SUBJECT, AUDIENCE, now=NOW)
    value = json.loads(raw); value['expires_at'] = NOW + 301
    raw = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
    signature = 'ed25519.' + base64.urlsafe_b64encode(key.sign(raw)).rstrip(b'=').decode()
    with pytest.raises(ReceiptInvalid):
        verify(raw, signature, trusted_keys={'fixture-key-1': key.public_key()}, issuer=ISSUER, audience=AUDIENCE, now=NOW)


def test_old_offline_signature_cannot_claim_current_revocation_after_source_withdrawal():
    state = {'active': True}
    def source(subject):
        if not state['active']: raise ReceiptInvalid('Source withdrawn.')
        return projection()
    core, key = issuer(source)
    raw, signature = core.issue(SUBJECT, AUDIENCE, now=NOW)
    state['active'] = False
    with pytest.raises(ReceiptInvalid): core.issue(SUBJECT, AUDIENCE, now=NOW + 1)
    retained = verify(raw, signature, trusted_keys={'fixture-key-1': key.public_key()}, issuer=ISSUER, audience=AUDIENCE, now=NOW + 1)
    assert retained['signature_verified'] and not retained['offline_revocation_checked']
    assert not retained['current_quality_verified']
