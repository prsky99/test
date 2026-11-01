"""Explicit private artifact signing rotation and authenticated encryption.

The optional local keyring is operator configuration, never a public API. No key
is created, rotated, copied into a backup, or retired automatically.
"""
import base64
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import stat
import time

PROFILE = 'private-artifact-keys-v1'
ENV = 'AGENT_PRIVATE_ARTIFACT_KEYRING'


class ArtifactKeyError(ValueError):
    pass


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ArtifactKeyError('Invalid private artifact key configuration.')
        result[key] = value
    return result


class ArtifactKeys:
    def __init__(self, config=None):
        if config is None:
            path = os.environ.get(ENV)
            if not path:
                self.config = None
                return
            descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
            with os.fdopen(descriptor, 'rb') as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
                    raise ArtifactKeyError('Private artifact keys require an owner-only regular file.')
                raw = source.read(32769)
            if len(raw) > 32768:
                raise ArtifactKeyError('Invalid private artifact key configuration.')
            try:
                config = json.loads(raw, object_pairs_hook=_object, parse_constant=lambda _: (_ for _ in ()).throw(ArtifactKeyError()))
            except (ValueError, UnicodeError):
                raise ArtifactKeyError('Invalid private artifact key configuration.') from None
        self.config = self._validate(config)

    @staticmethod
    def _validate(config):
        if (type(config) is not dict or set(config) != {'profile', 'active_signing', 'active_encryption', 'allow_legacy', 'keys'}
                or config['profile'] != PROFILE or type(config['allow_legacy']) is not bool
                or type(config['keys']) is not list or not 1 <= len(config['keys']) <= 16):
            raise ArtifactKeyError('Invalid private artifact key configuration.')
        keys = {}
        for item in config['keys']:
            if (type(item) is not dict or set(item) != {'id', 'key', 'verify_until', 'revoked'}
                    or type(item['id']) is not str or not re.fullmatch('[A-Za-z0-9_-]{1,32}', item['id'])
                    or item['id'] in keys or type(item['revoked']) is not bool
                    or type(item['verify_until']) not in (int, float) or not math.isfinite(item['verify_until'])
                    or item['verify_until'] <= 0 or type(item['key']) is not str):
                raise ArtifactKeyError('Invalid private artifact key configuration.')
            try:
                raw = base64.b64decode(item['key'], validate=True)
            except (ValueError, TypeError):
                raise ArtifactKeyError('Invalid private artifact key configuration.') from None
            if len(raw) != 32:
                raise ArtifactKeyError('Private artifact keys must contain 32 bytes.')
            keys[item['id']] = {**item, 'material': raw}
        for name in ('active_signing', 'active_encryption'):
            identity = config[name]
            if identity is None and name == 'active_encryption':
                continue
            if type(identity) is not str or identity not in keys or keys[identity]['revoked'] or keys[identity]['verify_until'] <= time.time():
                raise ArtifactKeyError('The configured active private artifact key is unavailable.')
        return {**config, 'keys': keys}

    def key(self, identity, purpose):
        if self.config is None:
            raise ArtifactKeyError('Private artifact keys are not configured.')
        item = self.config['keys'].get(identity)
        if not item or item['revoked'] or item['verify_until'] <= time.time():
            raise ArtifactKeyError('The private artifact key is unavailable.')
        return hmac.new(item['material'], purpose.encode('ascii'), hashlib.sha256).digest()

    def summary(self):
        return {'profile': PROFILE, 'configured': self.config is not None,
                'authenticated_encryption': bool(self.config and self.config['active_encryption']),
                'legacy_verification': self.config is None or self.config['allow_legacy'],
                'keys_included_in_backup': False}


class ArtifactSigner:
    def __init__(self, legacy_key, purpose, keys=None):
        self.legacy_key, self.purpose = legacy_key, purpose
        self.keys = keys if keys is not None else ArtifactKeys()

    def sign(self, value):
        payload = _json(value)
        if self.keys.config is None:
            return hmac.new(self.legacy_key, payload, hashlib.sha256).hexdigest()
        identity = self.keys.config['active_signing']
        mac = hmac.new(self.keys.key(identity, self.purpose + ':sign'), payload, hashlib.sha256).hexdigest()
        return 'ak1.' + identity + '.' + mac

    def verify(self, value, signature):
        if type(signature) is not str:
            return False
        if re.fullmatch('[0-9a-f]{64}', signature):
            return (self.keys.config is None or self.keys.config['allow_legacy']) and hmac.compare_digest(
                signature, hmac.new(self.legacy_key, _json(value), hashlib.sha256).hexdigest())
        match = re.fullmatch(r'ak1\.([A-Za-z0-9_-]{1,32})\.([0-9a-f]{64})', signature)
        if not match:
            return False
        try:
            key = self.keys.key(match[1], self.purpose + ':sign')
            return hmac.compare_digest(match[2], hmac.new(key, _json(value), hashlib.sha256).hexdigest())
        except ArtifactKeyError:
            return False


class ArtifactCipher:
    def __init__(self, purpose, keys=None):
        self.keys = keys if keys is not None else ArtifactKeys()
        self.purpose = purpose

    @property
    def configured(self):
        return bool(self.keys.config and self.keys.config['active_encryption'])

    def seal(self, value, context):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        if not self.configured or type(value) is not bytes or len(value) > 134217728:
            raise ArtifactKeyError('Authenticated private artifact encryption is unavailable.')
        identity = self.keys.config['active_encryption']
        nonce = secrets.token_bytes(12)
        encrypted = AESGCM(self.keys.key(identity, self.purpose + ':encrypt')).encrypt(nonce, value, _json(context))
        return _json({'profile': 'private-aes256gcm-v1', 'key_id': identity,
                      'nonce': base64.b64encode(nonce).decode('ascii'), 'ciphertext': base64.b64encode(encrypted).decode('ascii')})

    def open(self, envelope, context):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.exceptions import InvalidTag
        try:
            if type(envelope) is not bytes or len(envelope) > 180000000:
                raise ArtifactKeyError()
            value = json.loads(envelope, object_pairs_hook=_object)
            if type(value) is not dict or set(value) != {'profile', 'key_id', 'nonce', 'ciphertext'} or value['profile'] != 'private-aes256gcm-v1':
                raise ArtifactKeyError()
            nonce = base64.b64decode(value['nonce'], validate=True)
            encrypted = base64.b64decode(value['ciphertext'], validate=True)
            if len(nonce) != 12:
                raise ArtifactKeyError()
            return AESGCM(self.keys.key(value['key_id'], self.purpose + ':encrypt')).decrypt(nonce, encrypted, _json(context))
        except (ValueError, TypeError, KeyError, InvalidTag, UnicodeError):
            raise ArtifactKeyError('The private artifact could not be authenticated.') from None
