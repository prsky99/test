"""Signed evidence: JCS canonical JSON, DSSE envelopes, Ed25519 and the public key document (PM 11-14)."""
import base64
import json
import os

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agent_market import evidence_signing as es


def keys_doc(*keys, revoked=()):
    return {'keys': list(keys), 'revoked': list(revoked)}


def test_jcs_matches_rfc_8785():
    assert es.jcs({'b': 1, 'a': [True, None, 'x']}) == '{"a":[true,null,"x"],"b":1}'
    # RFC 8785 3.2.3: UTF-16 code unit order; € sorts after \r and before the emoji's surrogates
    value = {'€': 'Euro Sign', '\r': 'Carriage Return', 'דּ': 'Hebrew Letter Dalet With Dagesh',
             '1': 'One', '\U0001f600': 'Emoji: Grinning Face', '\u0080': 'Control', 'ö': 'Latin Small Letter O With Diaeresis'}
    assert [k for k in json.loads(es.jcs(value))] == ['\r', '1', '\u0080', 'ö', '€', '\U0001f600', 'דּ']
    assert es.jcs({'n': [333333333.33333329, 1e30, 4.50, 2e-3, 1e-7, 1e21, 100.0]}) == \
        '{"n":[333333333.3333333,1e+30,4.5,0.002,1e-7,1e+21,100]}'
    assert es.jcs('\u0000\n"\\\u007f') == '"\\u0000\\n\\"\\\\\u007f"'
    for bad in (float('nan'), float('inf'), 2 ** 60, {1: 'x'}, b'bytes'):
        with pytest.raises(es.SigningError):
            es.jcs(bad)


def test_sign_and_verify_round_trip_and_every_refusal():
    key = Ed25519PrivateKey.generate()
    entry = es.key_entry(key, '2026-11-01T00:00:00Z', '2027-11-01T00:00:00Z')
    evidence = {'kind': 'test_report', 'resource_id': 47161, 'score': 88.5, 'response_sha256': 'ab' * 32}
    envelope = es.sign(evidence, key, signed_at='2026-11-14T05:00:00Z')
    assert envelope['signatures'][0]['keyid'] == entry['keyid'] and entry['keyid'].startswith('avc-ed25519-')
    body = es.verify(envelope, keys_doc(entry))
    assert body == {**evidence, 'signed_at': '2026-11-14T05:00:00Z'}

    tampered = dict(envelope, payload=base64.b64encode(es.canonical_bytes({**body, 'score': 99})).decode())
    with pytest.raises(es.SigningError, match='bad signature'):
        es.verify(tampered, keys_doc(entry))
    with pytest.raises(es.SigningError, match='unknown key'):
        es.verify(envelope, keys_doc())
    with pytest.raises(es.SigningError, match='revoked'):
        es.verify(envelope, keys_doc(entry, revoked=[{'keyid': entry['keyid'], 'revoked_at': '2026-11-10T00:00:00Z'}]))
    # revoked after signing: the old signature still verifies
    assert es.verify(envelope, keys_doc(entry, revoked=[{'keyid': entry['keyid'], 'revoked_at': '2026-12-01T00:00:00Z'}]))
    with pytest.raises(es.SigningError, match='outside the key validity'):
        es.verify(es.sign(evidence, key, signed_at='2028-01-01T00:00:00Z'), keys_doc(entry))
    other = Ed25519PrivateKey.generate()
    forged = dict(envelope, signatures=[{'keyid': entry['keyid'], 'sig': es.sign(evidence, other)['signatures'][0]['sig']}])
    with pytest.raises(es.SigningError):
        es.verify(forged, keys_doc(entry))
    noncanonical = dict(envelope, payload=base64.b64encode(json.dumps(body, indent=1).encode()).decode())
    with pytest.raises(es.SigningError, match='canonical'):
        es.verify(noncanonical, keys_doc(entry))


def test_the_private_key_file_must_be_private(tmp_path):
    key = Ed25519PrivateKey.generate()
    path = tmp_path / 'signing.pem'
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    os.chmod(path, 0o644)
    with pytest.raises(es.SigningError, match='mode 600'):
        es.load_private_key(path)
    os.chmod(path, 0o600)
    assert es.public_raw(es.load_private_key(path)) == es.public_raw(key)


def test_command_line_verification(tmp_path, capsys):
    key = Ed25519PrivateKey.generate()
    (tmp_path / 'env.json').write_text(json.dumps(es.sign({'kind': 'gate'}, key, signed_at='2026-11-14T05:00:00Z')))
    (tmp_path / 'keys.json').write_text(json.dumps(keys_doc(es.key_entry(key, '2026-11-01T00:00:00Z', '2027-11-01T00:00:00Z'))))
    assert es.main(['verify', str(tmp_path / 'env.json'), '--keys', str(tmp_path / 'keys.json')]) == 0
    assert json.loads(capsys.readouterr().out)['valid'] is True
    (tmp_path / 'keys.json').write_text(json.dumps(keys_doc()))
    assert es.main(['verify', str(tmp_path / 'env.json'), '--keys', str(tmp_path / 'keys.json')]) == 1
