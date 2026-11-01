"""Explicit short-lived PostgreSQL archive credentials and database identity.

This boundary never reads a DSN, discovers passwords, or opens a connection.
The caller supplies an authenticated native connection and a purpose-specific
credential provider. Tool passwords use a temporary owner-only passfile.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import stat
import tempfile
import threading
import time

from .workflow_backup import exclusive

PROFILE = 'explicit-postgres-archive-credential-v1'


class ArchiveProviderDenied(ValueError):
    def __init__(self, code='explicit_archive_credentials_required'):
        self.code = code
        super().__init__(code)


def _name(value):
    return type(value) is str and re.fullmatch('[a-z_][a-z0-9_]{0,62}', value) is not None


@dataclass(frozen=True)
class DatabaseIdentity:
    host: str
    port: int
    database: str
    user: str
    system_identifier: str
    database_oid: int
    host_address: str | None = None
    root_certificate: str | None = None

    def validate(self):
        if (type(self.host) is not str or not self.host or len(self.host) > 1024 or any(c in self.host for c in ('\0', '\r', '\n'))
                or type(self.port) is not int or not 1 <= self.port <= 65535 or not _name(self.database) or not _name(self.user)
                or type(self.system_identifier) is not str or not re.fullmatch('[0-9]{1,24}', self.system_identifier)
                or type(self.database_oid) is not int or not 0 < self.database_oid < 2**32):
            raise ArchiveProviderDenied('invalid_explicit_database_identity')
        if self.host.startswith('/'):
            if self.host_address is not None or self.root_certificate is not None or not Path(self.host).is_absolute():
                raise ArchiveProviderDenied('invalid_explicit_database_identity')
        else:
            if not re.fullmatch('[A-Za-z0-9.-]{1,253}', self.host):
                raise ArchiveProviderDenied('invalid_explicit_database_identity')
            try: ipaddress.ip_address(self.host_address)
            except (ValueError, TypeError): raise ArchiveProviderDenied('explicit_host_address_required') from None
            if type(self.root_certificate) is not str or not Path(self.root_certificate).is_absolute():
                raise ArchiveProviderDenied('explicit_tls_root_required')
            info = Path(self.root_certificate).stat()
            if not stat.S_ISREG(info.st_mode) or Path(self.root_certificate).is_symlink():
                raise ArchiveProviderDenied('explicit_tls_root_required')
        return self

    def fingerprint(self):
        self.validate()
        certificate_hash = hashlib.sha256(Path(self.root_certificate).read_bytes()).hexdigest() if self.root_certificate else None
        return hashlib.sha256(json.dumps({'host': self.host, 'port': self.port, 'database': self.database,
            'user': self.user, 'system_identifier': self.system_identifier, 'database_oid': self.database_oid,
            'host_address': self.host_address, 'certificate_hash': certificate_hash}, sort_keys=True).encode()).hexdigest()


@dataclass
class ArchiveCredential:
    identity: DatabaseIdentity
    purpose: str
    expires: float
    password: str | None = field(default=None, repr=False)
    _used: bool = field(default=False, init=False, repr=False)
    _tool_used: bool = field(default=False, init=False, repr=False)
    _lock: object = field(default_factory=threading.Lock, init=False, repr=False)

    def consume(self, identity, purpose):
        with self._lock:
            return self._consume(identity, purpose)

    def _consume(self, identity, purpose):
        if (self._used or type(self.identity) is not DatabaseIdentity or self.identity != identity or self.purpose != purpose
                or purpose not in ('backup', 'restore', 'approve') or type(self.expires) not in (int, float)
                or not time.time() + 3 < self.expires <= time.time() + 900
                or self.password is not None and (type(self.password) is not str or not 1 <= len(self.password) <= 4096
                    or any(c in self.password for c in ('\0', '\r', '\n')))
                or not identity.host.startswith('/') and self.password is None):
            raise ArchiveProviderDenied('archive_credential_unavailable')
        self.identity.validate(); self._used = True
        return self

    def current(self):
        if not self._used or self.expires <= time.time(): raise ArchiveProviderDenied('archive_credential_expired')

    def tool_once(self):
        with self._lock:
            self.current()
            if self._tool_used: raise ArchiveProviderDenied('archive_credential_replayed')
            self._tool_used = True


class ExplicitArchiveCredentialProvider:
    def __init__(self, factory):
        if not callable(factory): raise ArchiveProviderDenied()
        self.factory = factory

    def obtain(self, identity, purpose):
        if type(identity) is not DatabaseIdentity: raise ArchiveProviderDenied('invalid_explicit_database_identity')
        identity.validate()
        try: value = self.factory(identity, purpose)
        except Exception: raise ArchiveProviderDenied() from None
        if type(value) is not ArchiveCredential: raise ArchiveProviderDenied()
        return value.consume(identity, purpose)


def verify_connection(connection, identity):
    if type(identity) is not DatabaseIdentity: raise ArchiveProviderDenied('invalid_explicit_database_identity')
    identity.validate()
    try:
        if connection.autocommit is not True or int(connection.info.transaction_status) != 0:
            raise ArchiveProviderDenied('connection_busy')
        if (connection.info.host, connection.info.port, connection.info.dbname, connection.info.user) != (
                identity.host, identity.port, identity.database, identity.user):
            raise ArchiveProviderDenied('archive_connection_identity_mismatch')
        with connection.cursor(row_factory=lambda _: tuple) as cursor:
            cursor.execute('''SELECT (SELECT system_identifier::text FROM pg_catalog.pg_control_system()),
                (SELECT oid::bigint FROM pg_catalog.pg_database WHERE datname=pg_catalog.current_database()),
                pg_catalog.current_database(),current_user,pg_catalog.inet_server_addr()::text,pg_catalog.inet_server_port()''')
            row = cursor.fetchone()
        if row[:4] != (identity.system_identifier, identity.database_oid, identity.database, identity.user):
            raise ArchiveProviderDenied('archive_connection_identity_mismatch')
        if identity.host.startswith('/'):
            if row[4:] != (None, None): raise ArchiveProviderDenied('archive_connection_identity_mismatch')
        else:
            parameters = connection.info.get_parameters()
            if (row[4:] != (identity.host_address, identity.port) or not connection.pgconn.ssl_in_use
                    or connection.info.hostaddr != identity.host_address or parameters.get('sslmode') != 'verify-full'
                    or parameters.get('sslrootcert') != identity.root_certificate):
                raise ArchiveProviderDenied('archive_connection_identity_mismatch')
        return identity.fingerprint()
    except ArchiveProviderDenied:
        raise
    except Exception:
        raise ArchiveProviderDenied('archive_connection_identity_unverified') from None


@contextmanager
def tool_environment(credential):
    credential.tool_once()
    identity = credential.identity
    with tempfile.TemporaryDirectory(prefix='a2a-archive-credentials-') as temporary:
        root = Path(temporary); root.chmod(0o700)
        password_file = root / 'one-use-password'
        def escaped(value): return value.replace('\\', '\\\\').replace(':', '\\:')
        if credential.password is not None:
            hosts = (identity.host, 'localhost') if identity.host.startswith('/') else (identity.host,)
            lines = [':'.join((escaped(host), str(identity.port), escaped(identity.database), escaped(identity.user), escaped(credential.password))) for host in hosts]
            exclusive(password_file, ('\n'.join(lines) + '\n').encode())
        environment = {'PATH': '/usr/bin:/bin', 'HOME': str(root), 'TMPDIR': str(root), 'LC_ALL': 'C', 'LANG': 'C',
            'PGPASSFILE': str(password_file), 'PGSERVICEFILE': str(root / 'no-service-file'), 'PGSYSCONFDIR': str(root),
            'PGCONNECT_TIMEOUT': '5', 'PGAPPNAME': 'explicit-archive-v1', 'PGGSSENCMODE': 'disable'}
        if identity.host.startswith('/'):
            environment['PGSSLMODE'] = 'disable'
        else:
            environment.update(PGSSLMODE='verify-full', PGSSLROOTCERT=identity.root_certificate, PGHOSTADDR=identity.host_address)
        try:
            yield environment, root
            credential.current()
        finally:
            credential.password = None
