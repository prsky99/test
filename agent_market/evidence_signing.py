"""Signed evidence: DSSE envelopes with Ed25519 over JCS-canonical JSON (super-gap strategy, PM 11-14).

What is signed is the evidence itself (a test report version, a necklace gate result, a stop or replacement event),
never only a grade. Anyone can verify with the public key document /.well-known/agentvalcon-keys.json.

- Canonical form: RFC 8785 (JCS). Keys sorted by UTF-16 code units, minimal string escapes, numbers in the ECMAScript
  form. Integers beyond 2^53 and non-finite numbers are refused rather than silently rounded.
- Envelope: DSSE v1 {payloadType, payload (base64 of the JCS bytes), signatures: [{keyid, sig}]}; the signature
  covers PAE(payloadType, payload) = "DSSEv1 <len> <type> <len> <payload>".
- Keys: Ed25519. keyid = "avc-ed25519-" + first 16 hex of sha256(raw public key). The private key is read from a
  PKCS#8 PEM file that must be a regular file owned by this user with mode 600 or 400; its value is never logged.
- Key document: {"keys": [{keyid, alg, public_key, not_before, not_after}], "revoked": [{keyid, revoked_at, reason}]}.
  A signature verifies when its key is listed, the payload's signed_at falls inside the key's validity, and the key
  was not revoked before signed_at. Old signatures stay verifiable after a key is retired.

Command line (public verification example):
    python -m agent_market.evidence_signing verify envelope.json --keys agentvalcon-keys.json
"""
import base64
import hashlib
import json
import math
import os
import stat
from datetime import datetime, timezone

PAYLOAD_TYPE = 'application/vnd.agentvalcon.evidence+json'
MAX_SAFE = 2 ** 53


class SigningError(ValueError):
    """A refused value, key or envelope; the message never contains key material."""


# ---------------- RFC 8785 (JCS) ----------------
def _number(value):
    """ECMAScript Number::toString of the shortest round-trip digits (RFC 8785 section 3.2.2.3)."""
    from decimal import Decimal
    if isinstance(value, bool):
        raise SigningError('booleans are not numbers')
    if isinstance(value, int):
        if abs(value) > MAX_SAFE:
            raise SigningError('integer outside the IEEE 754 safe range')
        return str(value)
    if not math.isfinite(value):
        raise SigningError('non-finite number')
    if value == 0:
        return '0'
    sign_, digit_tuple, exponent = Decimal(repr(float(value))).normalize().as_tuple()
    digits = ''.join(map(str, digit_tuple))
    k = len(digits)
    n = k + exponent                      # value = 0.digits x 10^n
    if k <= n <= 21:
        out = digits + '0' * (n - k)
    elif 0 < n <= 21:
        out = digits[:n] + '.' + digits[n:]
    elif -6 < n <= 0:
        out = '0.' + '0' * (-n) + digits
    else:
        e = n - 1
        out = digits[0] + ('.' + digits[1:] if k > 1 else '') + 'e' + ('+' if e >= 0 else '-') + str(abs(e))
    return ('-' if sign_ else '') + out


def _string(value):
    out = ['"']
    for ch in value:
        code = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == '\\':
            out.append('\\\\')
        elif ch == '\b':
            out.append('\\b')
        elif ch == '\f':
            out.append('\\f')
        elif ch == '\n':
            out.append('\\n')
        elif ch == '\r':
            out.append('\\r')
        elif ch == '\t':
            out.append('\\t')
        elif code < 0x20:
            out.append('\\u%04x' % code)
        else:
            out.append(ch)
    out.append('"')
    return ''.join(out)


def _utf16_key(text):
    return text.encode('utf-16-be')


def jcs(value):
    """RFC 8785 canonical JSON as text."""
    if value is None:
        return 'null'
    if value is True:
        return 'true'
    if value is False:
        return 'false'
    if isinstance(value, (int, float)):
        return _number(value)
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, (list, tuple)):
        return '[' + ','.join(jcs(v) for v in value) + ']'
    if isinstance(value, dict):
        if not all(isinstance(k, str) for k in value):
            raise SigningError('object keys must be strings')
        return '{' + ','.join(_string(k) + ':' + jcs(value[k]) for k in sorted(value, key=_utf16_key)) + '}'
    raise SigningError(f'unsupported JSON type {type(value).__name__}')


def canonical_bytes(value):
    return jcs(value).encode('utf-8')


# ---------------- DSSE ----------------
def pae(payload_type, payload):
    t = payload_type.encode('utf-8')
    return b'DSSEv1 %d %s %d %s' % (len(t), t, len(payload), payload)


def keyid_for(public_raw):
    return 'avc-ed25519-' + hashlib.sha256(public_raw).hexdigest()[:16]


def _b64(data):
    return base64.b64encode(data).decode('ascii')


def _unb64(text):
    try:
        return base64.b64decode(text, validate=True)
    except Exception:
        raise SigningError('invalid base64') from None


def load_private_key(path):
    """An Ed25519 private key from a PKCS#8 PEM file (regular file, owned by this user, mode 600 or 400)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) not in (0o600, 0o400):
        raise SigningError('the signing key must be a regular file owned by this user with mode 600 or 400')
    with open(path, 'rb') as stream:
        key = serialization.load_pem_private_key(stream.read(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SigningError('the signing key is not Ed25519')
    return key


def public_raw(private_key):
    from cryptography.hazmat.primitives import serialization
    return private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def sign(evidence, private_key, payload_type=PAYLOAD_TYPE, signed_at=None):
    """A DSSE envelope over the JCS form of EVIDENCE (a dict); signed_at (UTC) is added to the signed payload."""
    if not isinstance(evidence, dict):
        raise SigningError('evidence must be a JSON object')
    body = dict(evidence)
    body.setdefault('signed_at', signed_at or now_iso())
    payload = canonical_bytes(body)
    signature = private_key.sign(pae(payload_type, payload))
    return {'payloadType': payload_type, 'payload': _b64(payload),
            'signatures': [{'keyid': keyid_for(public_raw(private_key)), 'sig': _b64(signature)}]}


def _parse_time(text):
    try:
        return datetime.strptime(text, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        raise SigningError('invalid time') from None


def verify(envelope, keys_doc):
    """The verified evidence dict, or SigningError with the reason."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    if not isinstance(envelope, dict) or set(envelope) != {'payloadType', 'payload', 'signatures'}:
        raise SigningError('not a DSSE envelope')
    payload = _unb64(envelope['payload'])
    try:
        body = json.loads(payload)
    except ValueError:
        raise SigningError('payload is not JSON') from None
    if canonical_bytes(body) != payload:
        raise SigningError('payload is not in canonical (JCS) form')
    signed_at = _parse_time(body.get('signed_at'))
    keys = {k['keyid']: k for k in keys_doc.get('keys', []) if isinstance(k, dict) and k.get('alg') == 'ed25519'}
    revoked = {r['keyid']: r for r in keys_doc.get('revoked', []) if isinstance(r, dict)}
    reasons = []
    for item in envelope['signatures'] or []:
        key = keys.get(item.get('keyid'))
        if key is None:
            reasons.append('unknown key'); continue
        if not (_parse_time(key['not_before']) <= signed_at <= _parse_time(key['not_after'])):
            reasons.append('signed outside the key validity'); continue
        gone = revoked.get(item['keyid'])
        if gone and _parse_time(gone['revoked_at']) <= signed_at:
            reasons.append('key revoked before signing'); continue
        raw = _unb64(key['public_key'])
        if keyid_for(raw) != item['keyid']:
            reasons.append('keyid does not match the key'); continue
        try:
            Ed25519PublicKey.from_public_bytes(raw).verify(_unb64(item['sig']), pae(envelope['payloadType'], payload))
        except InvalidSignature:
            reasons.append('bad signature'); continue
        return body
    raise SigningError('no valid signature: ' + (', '.join(reasons) or 'no signatures'))


# ---------------- tamper evidence (PM 11-14) ----------------
def envelope_digest(envelope):
    """sha256 (hex) of the JCS form of a whole envelope: the link the next envelope of the same chain names as prev."""
    return hashlib.sha256(canonical_bytes(envelope)).hexdigest()


def sign_chained(evidence, private_key, previous=None, **kwargs):
    """Sign EVIDENCE as the next link of a chain (one chain per resource and role, or per necklace): the payload carries
    prev = the digest of the previous envelope (None for the first). Dropping a version breaks the chain."""
    body = dict(evidence)
    body['prev'] = envelope_digest(previous) if previous is not None else None
    return sign(body, private_key, **kwargs)


def verify_chain(envelopes, keys_doc):
    """Verify every envelope of a chain in order and that each names the one before it. Returns the evidence list."""
    bodies, previous = [], None
    for index, envelope in enumerate(envelopes):
        body = verify(envelope, keys_doc)
        want = envelope_digest(previous) if previous is not None else None
        if body.get('prev') != want:
            raise SigningError(f'chain broken at position {index}')
        bodies.append(body)
        previous = envelope
    return bodies


def merkle_root(digests):
    """RFC 6962-style Merkle tree head over hex digests in the given order (leaf = sha256(0x00 || d),
    node = sha256(0x01 || left || right); an odd node is carried up). Empty list: sha256 of nothing."""
    level = [hashlib.sha256(b'\x00' + bytes.fromhex(d)).digest() for d in digests]
    if not level:
        return hashlib.sha256(b'').hexdigest()
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            nxt.append(hashlib.sha256(b'\x01' + level[i] + level[i + 1]).digest() if i + 1 < len(level) else level[i])
        level = nxt
    return level[0].hex()


def daily_root(day, envelopes, private_key, previous_root=None, **kwargs):
    """The signed transparency record of a day: every envelope digest of the day, their Merkle root, and the previous
    day's root envelope digest (so days also form a chain). Published as /signing/roots/<day>.json."""
    digests = sorted(envelope_digest(e) for e in envelopes)
    return sign({'kind': 'transparency_root', 'day': day, 'count': len(digests), 'root': merkle_root(digests),
                 'leaves': digests, 'prev': envelope_digest(previous_root) if previous_root is not None else None},
                private_key, **kwargs)


def verify_daily_root(root_envelope, envelopes, keys_doc):
    """True when the signed day record lists exactly these envelopes and its root matches them."""
    body = verify(root_envelope, keys_doc)
    digests = sorted(envelope_digest(e) for e in envelopes)
    if body.get('leaves') != digests or body.get('count') != len(digests) or body.get('root') != merkle_root(digests):
        raise SigningError('the day record does not match these envelopes')
    return body


def key_entry(private_key, not_before, not_after):
    raw = public_raw(private_key)
    return {'keyid': keyid_for(raw), 'alg': 'ed25519', 'public_key': _b64(raw), 'not_before': not_before, 'not_after': not_after}


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='Verify an AgentValCon evidence envelope.')
    sub = parser.add_subparsers(dest='command', required=True)
    v = sub.add_parser('verify')
    v.add_argument('envelope')
    v.add_argument('--keys', required=True, help='the public key document (agentvalcon-keys.json)')
    args = parser.parse_args(argv)
    try:
        body = verify(json.load(open(args.envelope)), json.load(open(args.keys)))
    except (SigningError, OSError, ValueError) as error:
        print(json.dumps({'valid': False, 'reason': str(error)}))
        return 1
    print(json.dumps({'valid': True, 'evidence': body}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
