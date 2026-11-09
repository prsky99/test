"""Ed25519-signed receipts for exposure, reward, transfer, execution and settlement.

A receipt states what this ledger recorded. It does not prove that a person paid
attention, that an advertiser's goal was met or that money moved outside the
ledger; in test mode every amount is virtual and the body says so.
"""
import base64
import hashlib
import json
import os
import uuid

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from . import db as _db
from .config import require_test_mode
from .db import dumps


def now():
    return _db.now()

PROFILE = 'ai-ad-coin-receipt-v1'
KINDS = frozenset(('exposure', 'reward', 'voucher', 'transfer', 'execution', 'refund', 'settlement',
                   'sweep', 'offer_ack', 'mandate'))


class ReceiptInvalid(ValueError):
    pass


def _b64(value):
    return base64.urlsafe_b64encode(value).decode().rstrip('=')


def _unb64(value):
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode('ascii')


def load_or_create_key(path):
    """The key file is created once with owner-only permissions and never exported."""
    if path == ':memory:':
        return Ed25519PrivateKey.generate()
    try:
        with open(path, 'rb') as handle:
            return serialization.load_pem_private_key(handle.read(), password=None)
    except FileNotFoundError:
        key = Ed25519PrivateKey.generate()
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(pem)
        return key


def key_id(public_key):
    raw = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return 'ed25519:' + hashlib.sha256(raw).hexdigest()[:16]


def public_jwk(public_key):
    raw = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return {'kty': 'OKP', 'crv': 'Ed25519', 'x': _b64(raw), 'kid': key_id(public_key), 'use': 'sig'}


class Signer:
    def __init__(self, private_key, issuer, test_mode=True):
        require_test_mode(test_mode)
        self.key = private_key
        self.public = private_key.public_key()
        self.kid = key_id(self.public)
        self.issuer = issuer
        self.test_mode = test_mode

    def sign_payload(self, payload):
        return _b64(self.key.sign(canonical(payload)))

    def issue(self, database, kind, user_ref, facts):
        if kind not in KINDS:
            raise ReceiptInvalid('Unknown receipt kind.')
        body = {'profile': PROFILE, 'id': 'r_' + uuid.uuid4().hex, 'kind': kind, 'issuer': self.issuer,
                'key_id': self.kid, 'issued_at': int(now()), 'test_mode': self.test_mode,
                'virtual_amounts': self.test_mode, 'subject': user_ref, 'facts': facts}
        receipt = {**body, 'signature': self.sign_payload(body)}
        with database.transaction() as db:
            db.execute('INSERT INTO ad_coin_receipts VALUES (?,?,?,?,?)',
                       (body['id'], kind, user_ref, dumps(receipt), body['issued_at']))
        return receipt


def verify(receipt, public_key):
    if not isinstance(receipt, dict) or receipt.get('profile') != PROFILE or 'signature' not in receipt:
        raise ReceiptInvalid('Not an AI AD Coin receipt.')
    if not isinstance(public_key, Ed25519PublicKey):
        raise ReceiptInvalid('An Ed25519 public key is required.')
    body = {key: value for key, value in receipt.items() if key != 'signature'}
    try:
        public_key.verify(_unb64(receipt['signature']), canonical(body))
    except (InvalidSignature, ValueError, TypeError):
        raise ReceiptInvalid('The receipt signature does not verify.') from None
    if body.get('key_id') != key_id(public_key):
        raise ReceiptInvalid('The receipt was signed by another key.')
    return body
