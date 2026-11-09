"""One explicit persistent backend for service, collector and workflow workers.

The default remains SQLite. PostgreSQL requires private, owner-readable DSN and
stable key files and attaches an existing reviewed schema. This module never
initializes a PostgreSQL database, migrates data, changes ingress or enables a
customer portal. Configuration and driver failures expose fixed codes only.
"""
from dataclasses import dataclass, field
import os
import stat

# libpq warns on every connection when the passfile exists but is not a plain file
# ("/dev/null"). A path under /dev/null can never exist or be created by anyone,
# so libpq skips it silently and no password file is ever read.
_ABSENT_PASSFILE = os.path.join(os.devnull, 'no-password-file')

# Pooled sessions unused this long are closed. A busy active slot keeps its sessions;
# a retained standby slot releases them within about five minutes.
IDLE_SESSION_SECONDS = 300


class RuntimeStorageError(ValueError):
    pass


def _private_bytes(path, maximum):
    if type(path) is not str or not path or '\0' in path:
        raise RuntimeStorageError('private_backend_settings_required')
    descriptor = None
    try:
        before = os.lstat(path)
        if stat.S_ISLNK(before.st_mode):
            raise ValueError()
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        actual = os.fstat(descriptor)
        if (not stat.S_ISREG(actual.st_mode) or actual.st_uid != os.getuid()
                or stat.S_IMODE(actual.st_mode) not in (0o400, 0o600)
                or (before.st_dev, before.st_ino) != (actual.st_dev, actual.st_ino)):
            raise ValueError()
        with os.fdopen(descriptor, 'rb') as stream:
            descriptor = None
            value = stream.read(maximum + 1)
        if not 1 <= len(value) <= maximum:
            raise ValueError()
        return value
    except (OSError, ValueError):
        raise RuntimeStorageError('invalid_private_backend_settings') from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


@dataclass(repr=False)
class RuntimeStorage:
    store: object = field(repr=False)
    connection: object | None = field(default=None, repr=False)
    owned: bool = True
    closed: bool = False

    def close(self):
        """Close only after callers have stopped and drained their workers."""
        if self.closed or not self.owned:
            return
        store = self.store
        with store._lock:
            if store._db.in_transaction:
                raise RuntimeStorageError('storage_workers_not_drained')
            for name in ('_admin_read_pool','_interactive_pool'):
                pool = getattr(store, name, None)
                if pool is not None: pool.close()
            journal = getattr(store, '_observation_journal', None)
            if journal is not None:
                journal.close()
            if self.connection is None:
                store._db.close()
            else:
                store.close()
                self.connection.close()
                # The store may have replaced its session after a database restart.
                if getattr(store, '_connection', self.connection) is not self.connection:
                    store._connection.close()
            self.closed = True


def _connect(dsn):
    if any(os.environ.get(name) for name in ('PGSERVICE','PGHOST','PGHOSTADDR','PGPORT','PGDATABASE',
            'PGUSER','PGPASSWORD','PGOPTIONS','PGSSLMODE','PGSSLROOTCERT','PGSSLCERT','PGSSLKEY',
            'PGTARGETSESSIONATTRS','PGREQUIREAUTH','PGCHANNELBINDING','PGGSSENCMODE','PGAPPNAME')):
        raise RuntimeStorageError('inherited_postgres_configuration_refused')
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    options = conninfo_to_dict(dsn)
    allowed = {'host', 'hostaddr', 'port', 'dbname', 'user', 'password', 'sslrootcert', 'sslcert', 'sslkey'}
    if (set(options) - allowed or not all(options.get(name) for name in ('host', 'dbname', 'user'))
            or any(type(value) is not str or '\0' in value for value in options.values())):
        raise RuntimeStorageError('invalid_postgres_connection_profile')
    # Override inherited libpq options explicitly. A service/passfile or shell
    # environment must not silently redirect the selected persistent database.
    options.setdefault('password', '')
    options.setdefault('port', '5432')
    options.setdefault('hostaddr', '')
    options.setdefault('sslrootcert', 'system')
    options.setdefault('sslcert', '')
    options.setdefault('sslkey', '')
    return psycopg.connect(**options, passfile=_ABSENT_PASSFILE,
        options='', application_name='agent-concierge', connect_timeout=5,
        sslmode='verify-full', gssencmode='disable', target_session_attrs='read-write', autocommit=True)


def open_runtime_storage(sqlite_path, *, values=None, connector=None):
    """Read named process settings once; never fall back after a selected failure.

    A supplied connector is a fixture/embedding seam receiving the private DSN;
    it does not change Store validation or accept an unreviewed SQL schema.
    """
    values = os.environ if values is None else values
    backend = values.get('APPLICATION_STORE_BACKEND', 'sqlite')
    if backend not in ('sqlite', 'postgresql'):
        raise RuntimeStorageError('unsupported_application_backend')
    if backend == 'sqlite':
        if values.get('APPLICATION_POSTGRES_DSN_FILE') or values.get('APPLICATION_WORKFLOW_KEY_FILE'):
            raise RuntimeStorageError('ambiguous_application_backend')
        from pathlib import Path
        from .gateway.store import Store
        if sqlite_path != ':memory:':
            Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)
        return RuntimeStorage(Store(sqlite_path))
    connection = None
    try:
        dsn_raw = _private_bytes(values.get('APPLICATION_POSTGRES_DSN_FILE'), 16384)
        key = _private_bytes(values.get('APPLICATION_WORKFLOW_KEY_FILE'), 32)
        dsn = dsn_raw.decode('utf-8').strip()
        if len(key) != 32 or not dsn or any(ord(char) < 32 for char in dsn):
            raise RuntimeStorageError('invalid_private_backend_settings')
        def open_session():
            return (connector or _connect)(dsn)
        def read_only_session():
            reader = open_session()
            try:
                reader.execute('SET default_transaction_read_only=on')
                return reader
            except BaseException:
                reader.close()
                raise
        connection = open_session()
        from .storage_adapter import open_store
        store = open_store('postgresql', connection=connection, workflow_key=key,
            required_capabilities=('full_application', 'service_runtime', 'payment_replay', 'collector_scheduling',
                                   'durable_workflow_runtime', 'persistent_writer_lifecycle'))
        # A database restart must not leave the process with a dead session.
        store._connection_factory = open_session
        from .admin_postgres_pool import AdminReaderPool
        def create_admin_reader():
            reader_connection = (connector or _connect)(dsn)
            try:
                reader_store = open_store('postgresql', connection=reader_connection, workflow_key=key,
                    required_capabilities=('full_application',))
                # Native session enforcement adds defense beyond the GET hint.
                reader_connection.execute('SET default_transaction_read_only=on')
                reader_store._connection_factory = read_only_session
                return reader_store, reader_connection
            except BaseException:
                reader_connection.close()
                raise
        def create_interactive_session():
            session = open_session()
            try:
                scoped = open_store('postgresql', connection=session, workflow_key=key,
                    required_capabilities=('full_application',))
                scoped._connection_factory = open_session
                return scoped, session
            except BaseException:
                session.close()
                raise
        store._admin_read_pool = AdminReaderPool(create_admin_reader,max_idle=1,idle_seconds=IDLE_SESSION_SECONDS)
        # Chat has visitor writes, so it uses separate bounded sessions rather
        # than borrowing read-only metrics sessions or a collector's Python lock.
        store._interactive_pool = AdminReaderPool(create_interactive_session,maximum=4,wait_seconds=8,max_idle=1,
            idle_seconds=IDLE_SESSION_SECONDS)
        return RuntimeStorage(store, connection)
    except BaseException as error:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
        if not isinstance(error, Exception):
            raise
        if isinstance(error, RuntimeStorageError):
            raise
        raise RuntimeStorageError('postgres_application_attach_failed') from None
