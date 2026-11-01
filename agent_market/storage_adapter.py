"""Explicit low-level SQL dialect boundary, not a PostgreSQL application Store.

Statements are trusted application source, never user-supplied SQL. Connections
must be used exclusively through their adapter until detached; the caller owns
their lifetime. No connection, driver, environment, schema or server is opened
at import. Existing Store transactions and raw SQLite APIs remain unchanged.
Read-only transactions are native database controls, not a SQL/function sandbox.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import math
import re
import sqlite3
import threading

PROFILE = 'explicit-storage-adapter-v1'
MAX_PARAMETERS = 64
MAX_VALUE_BYTES = 16384
MAX_PARAMETER_BYTES = 65536
MAX_ROWS = 1000
MAX_RESULT_BYTES = 1048576
ERRORS = frozenset(('invalid_statement', 'invalid_parameters', 'invalid_configuration',
    'unsupported_backend', 'nested_transaction', 'connection_busy', 'session_required',
    'session_closed', 'thread_violation', 'read_only', 'statement_failed', 'result_limit',
    'transaction_failed', 'connection_unusable', 'commit_unknown'))
COMMANDS = frozenset(('SELECT', 'WITH', 'VALUES', 'EXPLAIN', 'INSERT', 'UPDATE',
                      'DELETE', 'CREATE', 'ALTER', 'DROP'))


class StorageError(ValueError):
    def __init__(self, code='statement_failed'):
        self.code = code if code in ERRORS else 'statement_failed'
        super().__init__(self.code)


@dataclass(frozen=True)
class Statement:
    name: str
    sqlite: str
    postgres: str
    readonly: bool = False

    def __post_init__(self):
        if (type(self.name) is not str or not re.fullmatch(r'[a-z][a-z0-9_.]{0,79}', self.name)
                or type(self.readonly) is not bool):
            raise StorageError('invalid_statement')
        for sql in (self.sqlite, self.postgres):
            if type(sql) is not str or '\0' in sql:
                raise StorageError('invalid_statement')
            try: bounded = len(sql.encode('utf-8')) <= 32768
            except UnicodeError: bounded = False
            word = re.match(r'\s*([A-Za-z]+)\b', sql)
            if not bounded or not word or word[1].upper() not in COMMANDS:
                raise StorageError('invalid_statement')


def _parameters(values):
    if type(values) is not tuple or len(values) > MAX_PARAMETERS:
        raise StorageError('invalid_parameters')
    size = 0
    for value in values:
        if value is None: size += 1
        elif type(value) is int and -(2**63) <= value < 2**63: size += 8
        elif type(value) is float and math.isfinite(value): size += 8
        elif type(value) in (str, bytes):
            try: count = len(value.encode('utf-8')) if type(value) is str else len(value)
            except UnicodeError: raise StorageError('invalid_parameters') from None
            if count > MAX_VALUE_BYTES or type(value) is str and '\0' in value:
                raise StorageError('invalid_parameters')
            size += count
        else: raise StorageError('invalid_parameters')
    if size > MAX_PARAMETER_BYTES: raise StorageError('invalid_parameters')
    return values


@dataclass(frozen=True)
class Row:
    """Snapshot values with positional/named access; no live driver cursor."""
    columns: tuple
    values: tuple

    def keys(self): return self.columns
    def __len__(self): return len(self.values)
    def __iter__(self): return iter(self.values)
    def __getitem__(self, key):
        if type(key) is str:
            try: return self.values[self.columns.index(key)]
            except ValueError: raise KeyError(key) from None
        if type(key) is int or type(key) is slice: return self.values[key]
        raise TypeError('Use a column name or position.')


@dataclass(frozen=True)
class Result:
    rows: tuple
    rowcount: int


class Session:
    def __init__(self, adapter, readonly):
        self._adapter, self._readonly = adapter, readonly
        self._owner = threading.get_ident()
        self._active, self._failed = True, False

    def execute(self, statement, params=()):
        if not self._active: raise StorageError('session_closed')
        if self._owner != threading.get_ident(): raise StorageError('thread_violation')
        if self._failed: raise StorageError('transaction_failed')
        try:
            if type(statement) is not Statement: raise StorageError('invalid_statement')
            values = _parameters(params)
            if self._readonly and not statement.readonly: raise StorageError('read_only')
            return self._adapter._execute(statement, values)
        except BaseException:
            self._failed = True
            raise


class _Adapter:
    def __init__(self, connection, dialect):
        self._connection, self.dialect = connection, dialect
        self._lock = threading.Lock()
        self._owner, self._unusable, self._detached = None, False, False

    def execute(self, *_args, **_kwargs):
        raise StorageError('session_required')

    def detach(self):
        """Stop using the adapter without closing the caller's connection."""
        if not self._lock.acquire(blocking=False): raise StorageError('connection_busy')
        try: self._detached = True
        finally: self._lock.release()

    def _idle(self):
        try:
            if self.dialect == 'sqlite': return not self._connection.in_transaction
            return self._connection.autocommit is True and int(self._connection.info.transaction_status) == 0
        except Exception: raise StorageError('connection_unusable') from None

    def _control(self, sql):
        cursor = None; primary = None
        try:
            cursor = self._connection.cursor()
            cursor.execute(sql)
        except BaseException as exc:
            primary = StorageError('transaction_failed') if isinstance(exc, Exception) else exc
            if primary is exc: raise
            raise primary from None
        finally:
            self._close_cursor(cursor, primary, 'transaction_failed')

    def _close_cursor(self, cursor, primary, code):
        if cursor is None: return
        try: cursor.close()
        except BaseException as exc:
            self._unusable = True
            if primary is not None and not isinstance(primary, Exception): return
            if not isinstance(exc, Exception): raise
            if primary is None: raise StorageError(code) from None

    def _query_only(self):
        cursor = None; primary = None
        try:
            cursor = self._connection.cursor()
            cursor.row_factory = None
            value = cursor.execute('PRAGMA query_only').fetchone()[0]
            if type(value) is not int or value not in (0, 1): raise StorageError('invalid_configuration')
            return value
        except BaseException as exc:
            primary = exc if isinstance(exc, StorageError) or not isinstance(exc, Exception) else StorageError('transaction_failed')
            if primary is exc: raise
            raise primary from None
        finally: self._close_cursor(cursor, primary, 'transaction_failed')

    def _finish(self, commit):
        try:
            if commit: self._connection.commit()
            else: self._connection.rollback()
        except BaseException as exc:
            self._unusable = True
            if not isinstance(exc, Exception): raise
            raise StorageError('commit_unknown' if commit else 'transaction_failed') from None

    @contextmanager
    def transaction(self, *, readonly=False):
        if type(readonly) is not bool: raise StorageError('invalid_configuration')
        owner = threading.get_ident()
        if self._owner == owner: raise StorageError('nested_transaction')
        if not self._lock.acquire(blocking=False): raise StorageError('connection_busy')
        session = None; changed_query_only = False; begun = False; yielded = False; primary = None
        try:
            if self._unusable or self._detached: raise StorageError('connection_unusable')
            if not self._idle(): raise StorageError('connection_busy')
            self._owner = owner
            if self.dialect == 'sqlite' and readonly:
                previous = self._query_only()
                if previous == 0:
                    changed_query_only = True
                    self._control('PRAGMA query_only=ON')
            # BEGIN may be accepted even if the control cursor acknowledgement
            # fails. The previously idle exclusive connection then needs one
            # best-effort rollback rather than leaving a writer lock behind.
            begun = True
            self._control('BEGIN' if readonly or self.dialect == 'postgresql' else 'BEGIN IMMEDIATE')
            if readonly and self.dialect == 'postgresql': self._control('SET TRANSACTION READ ONLY')
            session = Session(self, readonly)
            yielded = True
            yield session
            if session._failed: raise StorageError('transaction_failed')
            self._finish(True); begun = False
        except BaseException as exc:
            primary = exc if isinstance(exc, StorageError) or yielded or not isinstance(exc, Exception) else StorageError('transaction_failed')
            if begun:
                try: self._finish(False)
                except BaseException as cleanup:
                    # Failed rollback cannot turn a possibly committed result
                    # into a known failure or hide cancellation. No retry occurs.
                    self._unusable = True
                    if isinstance(primary, Exception):
                        if not isinstance(cleanup, Exception): primary = cleanup
                        elif not (isinstance(primary, StorageError) and primary.code == 'commit_unknown'):
                            primary = StorageError('transaction_failed')
                finally: begun = False
            if primary is exc: raise
            raise primary from None
        finally:
            if session is not None: session._active = False
            try:
                if changed_query_only:
                    try: self._control('PRAGMA query_only=OFF')
                    except BaseException as cleanup:
                        self._unusable = True
                        if (isinstance(primary, Exception) or primary is None) and not isinstance(cleanup, Exception): raise
                        if primary is None: raise StorageError('connection_unusable') from None
            finally:
                self._owner = None
                self._lock.release()

    def _execute(self, statement, values):
        cursor = None; primary = None
        try:
            if self.dialect == 'sqlite':
                cursor = self._connection.cursor(); cursor.row_factory = None
                cursor.execute(statement.sqlite, values)
            else:
                cursor = self._connection.cursor(row_factory=lambda _cursor: tuple)
                cursor.execute(statement.postgres, values, prepare=True)
            count = cursor.rowcount
            description = cursor.description
            if description is None: return Result((), count)
            columns = tuple(item[0] for item in description)
            if (len(columns) != len(set(columns)) or any(type(name) is not str or not name or len(name) > 128 for name in columns)):
                raise StorageError('statement_failed')
            rows = cursor.fetchmany(MAX_ROWS + 1)
            if len(rows) > MAX_ROWS: raise StorageError('result_limit')
            total = 0; result = []
            for raw in rows:
                if len(raw) != len(columns): raise StorageError('statement_failed')
                for value in raw:
                    if value is None: total += 1
                    elif type(value) in (str, bytes): total += len(value.encode('utf-8')) if type(value) is str else len(value)
                    elif type(value) in (int, float, bool):
                        if type(value) is float and not math.isfinite(value): raise StorageError('statement_failed')
                        total += 8
                    else: raise StorageError('statement_failed')
                    if total > MAX_RESULT_BYTES: raise StorageError('result_limit')
                result.append(Row(columns, tuple(raw)))
            return Result(tuple(result), count)
        except StorageError as exc:
            primary = exc
            raise
        except Exception as exc:
            read_only = ((getattr(exc, 'sqlite_errorcode', -1) & 255) == sqlite3.SQLITE_READONLY
                         or getattr(exc, 'sqlstate', None) == '25006')
            primary = StorageError('read_only' if read_only else 'statement_failed')
            raise primary from None
        except BaseException as exc:
            primary = exc
            raise
        finally:
            self._close_cursor(cursor, primary, 'statement_failed')


class SQLiteAdapter(_Adapter):
    def __init__(self, connection):
        if not isinstance(connection, sqlite3.Connection): raise StorageError('invalid_configuration')
        super().__init__(connection, 'sqlite')
        if not self._idle(): raise StorageError('connection_busy')


class PostgresAdapter(_Adapter):
    """Explicit psycopg3 connection only; no driver import, DSN or connect API."""
    def __init__(self, connection):
        super().__init__(connection, 'postgresql')
        if not self._idle(): raise StorageError('invalid_configuration')


def open_store(backend='sqlite', *, sqlite_path=':memory:', connection=None,
               initialize=False, required_capabilities=(), workflow_key=None):
    """Explicit application factory; caller-owned PostgreSQL connection only.

    The service, collector and worker can explicitly attach this native Store
    through application_runtime. Choosing a backend does not migrate a source,
    approve its writer gate or open public features. Unknown SQL still fails
    closed; the finite capabilities must be requested by the caller.
    """
    if type(backend) is str and backend == 'postgresql' and connection is not None:
        from .application_store_postgres import PostgresApplicationStore, ApplicationStoreError
        if (not isinstance(required_capabilities, (tuple, frozenset))
                or any(type(item) is not str or item not in PostgresApplicationStore.capabilities for item in required_capabilities)):
            raise ApplicationStoreError('unsupported_application_capability')
        if 'full_application' in required_capabilities and (type(workflow_key) is not bytes or len(workflow_key) != 32):
            raise ApplicationStoreError('explicit_workflow_key_required')
        return PostgresApplicationStore(connection, initialize=initialize,
            workflow_key=workflow_key).require_capabilities(required_capabilities)
    if type(backend) is not str or backend != 'sqlite': raise StorageError('unsupported_backend')
    if connection is not None or initialize is not False or required_capabilities != () or workflow_key is not None:
        raise StorageError('invalid_configuration')
    if (type(sqlite_path) is not str or not sqlite_path or len(sqlite_path) > 4096
            or '\0' in sqlite_path or re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', sqlite_path) and sqlite_path != ':memory:'):
        raise StorageError('invalid_configuration')
    try:
        from .gateway.store import Store
        return Store(sqlite_path)
    except Exception: raise StorageError('connection_unusable') from None
