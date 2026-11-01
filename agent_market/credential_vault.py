"""Authenticated encryption for stored platform credentials, bound to each key name."""
import base64
import os
import secrets
import stat
import tempfile
from pathlib import Path

# PyCryptodome supplies this namespace; the deprecated PyCrypto package is not used.
from Crypto.Cipher import AES  # nosec B413

PREFIX = 'enc:v1:'


class CredentialVault:
    def __init__(self, database_path):
        self.key = secrets.token_bytes(32) if not database_path else self._load_key(Path(database_path + '.credentials-key'))

    @classmethod
    def from_key(cls, key):
        """Use an explicit stable key without filesystem or random-key fallback."""
        if type(key) is not bytes or len(key) != 32:
            raise ValueError('Credential encryption requires an explicit 32-byte key')
        vault = cls.__new__(cls)
        vault.key = key
        return vault

    @staticmethod
    def _load_key(path):
        # Publish a complete key atomically. Concurrent workers never read a partial file.
        if not path.exists():
            fd, temporary = tempfile.mkstemp(prefix='.credential-key-', dir=path.parent)
            try:
                with os.fdopen(fd, 'wb') as target:
                    os.fchmod(target.fileno(), 0o600)
                    target.write(secrets.token_bytes(32))
                    target.flush()
                    os.fsync(target.fileno())
                try:
                    os.link(temporary, path, follow_symlinks=False)
                except FileExistsError:
                    pass
            finally:
                os.unlink(temporary)
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or hasattr(os, 'geteuid') and info.st_uid != os.geteuid():
                raise ValueError('Credential key requires private owner permissions')
            key = source.read(33)
        if len(key) != 32:
            raise ValueError('Invalid credential encryption key')
        return key

    def seal(self, name, value):
        cipher = AES.new(self.key, AES.MODE_GCM, nonce=secrets.token_bytes(12))
        cipher.update(('platform-credential:v1:' + name).encode())
        ciphertext, tag = cipher.encrypt_and_digest(value.encode())
        return PREFIX + base64.urlsafe_b64encode(cipher.nonce + tag + ciphertext).decode()

    def open(self, name, value):
        if not value.startswith(PREFIX):
            raise ValueError('Unencrypted credential storage is not accepted')
        try:
            raw = base64.b64decode(value[len(PREFIX):], altchars=b'-_', validate=True)
            cipher = AES.new(self.key, AES.MODE_GCM, nonce=raw[:12])
            cipher.update(('platform-credential:v1:' + name).encode())
            return cipher.decrypt_and_verify(raw[28:], raw[12:28]).decode()
        except (ValueError, UnicodeError, KeyError) as exc:
            raise ValueError('Credential could not be decrypted; restore its original encryption key') from exc
