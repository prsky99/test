"""Opt-in portable metadata signatures; no public route or payment authority.

An offline verifier checks signature, scope and time only. It cannot establish
current revocation, independent quality or business completion. A trusted server
must inject the current sanitized projection source and signing configuration.
This module never creates, persists or exports a private signing key.
"""
import base64
import binascii
from dataclasses import dataclass
import json
import math
import re
import time
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

PROFILE = 'portable-reliability-metadata-receipt-v1'
PURPOSE = 'reliability-metadata-only'
MAX_BYTES = 4096
MAX_TTL = 300
FIELDS = frozenset(('profile', 'algorithm', 'key_id', 'issuer', 'audience', 'purpose',
                    'issued_at', 'expires_at', 'projection'))
PROJECTION_FIELDS = frozenset(('subject_ref', 'contract_id', 'version_digest',
    'evidence_digest', 'verdict', 'observed_at', 'expires_at'))
CONTRACTS = frozenset(('news.search.v1', 'docs.search.v1', 'products.compare.v1'))


class ReceiptInvalid(ValueError):
    pass


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode('ascii')


def _origin(value):
    if type(value) is not str or not 1 <= len(value) <= 200:
        raise ReceiptInvalid('Invalid receipt configuration.')
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment
                or value != 'https://' + parsed.netloc
                or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,251}', parsed.hostname)
                or parsed.netloc != parsed.netloc.lower()):
            raise ValueError()
        parsed.port
    except ValueError:
        raise ReceiptInvalid('Invalid receipt configuration.') from None
    return value


def _label(value):
    if type(value) is not str or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', value):
        raise ReceiptInvalid('Invalid receipt scope.')
    return value


def _clock(value=None):
    current = time.time() if value is None else value
    if type(current) not in (int, float) or not math.isfinite(current) or not 0 < current < 2**53:
        raise ReceiptInvalid('Invalid receipt time.')
    return current


def _projection(value, now):
    if type(value) is not dict or set(value) != PROJECTION_FIELDS:
        raise ReceiptInvalid('Only the fixed sanitized projection is permitted.')
    if (type(value['subject_ref']) is not str or not re.fullmatch(r'public_[0-9a-f]{32}', value['subject_ref'])
            or type(value['contract_id']) is not str or value['contract_id'] not in CONTRACTS
            or type(value['verdict']) is not str or value['verdict'] not in ('qualified', 'neutral', 'unassessed')
            or any(type(value[name]) is not str or not re.fullmatch(r'[0-9a-f]{64}', value[name])
                   for name in ('version_digest', 'evidence_digest'))
            or any(type(value[name]) is not int or not 0 <= value[name] < 2**53
                   for name in ('observed_at', 'expires_at'))
            or not value['observed_at'] <= now < value['expires_at']):
        raise ReceiptInvalid('Invalid or expired sanitized projection.')
    return dict(value)


@dataclass(frozen=True, repr=False)
class SigningConfig:
    issuer: str
    key_id: str
    private_key: Ed25519PrivateKey
    audiences: tuple

    def __post_init__(self):
        _origin(self.issuer); _label(self.key_id)
        if (not isinstance(self.private_key, Ed25519PrivateKey)
                or type(self.audiences) is not tuple or not 1 <= len(self.audiences) <= 20
                or any(type(audience) is not str for audience in self.audiences)
                or len(set(self.audiences)) != len(self.audiences)):
            raise ReceiptInvalid('Invalid receipt signing configuration.')
        for audience in self.audiences:
            _label(audience)


class PortableReceiptIssuer:
    def __init__(self, config=None, *, projection_source=None):
        if config is not None and type(config) is not SigningConfig:
            raise ReceiptInvalid('Invalid receipt signing configuration.')
        if projection_source is not None and not callable(projection_source):
            raise ReceiptInvalid('Invalid sanitized projection source.')
        self._config, self._source = config, projection_source

    def status(self):
        return {'profile': PROFILE, 'enabled': self._config is not None and self._source is not None,
            'algorithm': 'Ed25519', 'public_route_registered': False,
            'public_release_authorized': False, 'actual_money': False,
            'offline_revocation_check': False, 'independent_quality_certification': False}

    def issue(self, subject_ref, audience, *, ttl_seconds=MAX_TTL, now=None):
        if not self.status()['enabled']:
            raise ReceiptInvalid('Portable metadata signing is disabled.')
        if (type(subject_ref) is not str or not re.fullmatch(r'public_[0-9a-f]{32}', subject_ref)
                or _label(audience) not in self._config.audiences
                or type(ttl_seconds) is not int or not 1 <= ttl_seconds <= MAX_TTL):
            raise ReceiptInvalid('Invalid receipt scope.')
        current = _clock(now)
        projection = _projection(self._source(subject_ref), current)
        if projection['subject_ref'] != subject_ref:
            raise ReceiptInvalid('The sanitized projection subject changed.')
        issued = int(current)
        value = {'profile': PROFILE, 'algorithm': 'Ed25519', 'key_id': self._config.key_id,
            'issuer': self._config.issuer, 'audience': audience, 'purpose': PURPOSE,
            'issued_at': issued, 'expires_at': min(issued + ttl_seconds, projection['expires_at']),
            'projection': projection}
        raw = _canonical(value)
        if len(raw) > MAX_BYTES or not current < value['expires_at']:
            raise ReceiptInvalid('The receipt lifetime is unavailable.')
        signature = base64.urlsafe_b64encode(self._config.private_key.sign(raw)).rstrip(b'=').decode('ascii')
        return raw, 'ed25519.' + signature


def verify(raw, signature, *, trusted_keys, issuer, audience, now=None):
    """No online freshness, revocation or business outcome is inferred."""
    _origin(issuer); _label(audience); current = _clock(now)
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_BYTES:
        raise ReceiptInvalid('Invalid receipt envelope.')
    if type(signature) is not str or not re.fullmatch(r'ed25519\.[A-Za-z0-9_-]{86}', signature):
        raise ReceiptInvalid('Invalid receipt signature.')
    if type(trusted_keys) is not dict or not 1 <= len(trusted_keys) <= 20:
        raise ReceiptInvalid('Configure a bounded trusted key map.')
    def pairs(items):
        value = {}
        for name, item in items:
            if name in value: raise ValueError()
            value[name] = item
        return value
    try:
        value = json.loads(raw.decode('ascii'), object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if type(value) is not dict or set(value) != FIELDS or _canonical(value) != raw:
            raise ValueError()
        key = trusted_keys.get(_label(value['key_id']))
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError()
        proof = base64.b64decode(signature[8:].encode('ascii') + b'==', altchars=b'-_', validate=True)
        if base64.urlsafe_b64encode(proof).rstrip(b'=').decode('ascii') != signature[8:]:
            raise ValueError()
        key.verify(proof, raw)
        if (value['profile'] != PROFILE or value['algorithm'] != 'Ed25519'
                or value['issuer'] != issuer or value['audience'] != audience or value['purpose'] != PURPOSE
                or any(type(value[name]) is not int for name in ('issued_at', 'expires_at'))
                or not 0 < value['issued_at'] <= current < value['expires_at'] <= value['issued_at'] + MAX_TTL):
            raise ValueError()
        projection = _projection(value['projection'], current)
        if value['expires_at'] > projection['expires_at'] or projection['observed_at'] > value['issued_at']:
            raise ValueError()
        return {'receipt': value, 'signature_verified': True, 'time_verified': True,
            'offline_revocation_checked': False, 'current_quality_verified': False,
            'business_completion_verified': False, 'payment_authorized': False,
            'legal_settlement_verified': False}
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, InvalidSignature, binascii.Error):
        raise ReceiptInvalid('The receipt could not be verified.') from None
