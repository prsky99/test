"""One private SQLite file for AI AD Coin. It is separate from the catalog and the
production PostgreSQL store, so test-mode sponsorship never touches them."""
from contextlib import contextmanager
import json
import os
import sqlite3
import threading
import time

from ..storage_security import private_sqlite_file

SCHEMA = """
CREATE TABLE IF NOT EXISTS ad_coin_journals (
    id TEXT PRIMARY KEY, created_at REAL NOT NULL, kind TEXT NOT NULL,
    idem TEXT NOT NULL UNIQUE, detail TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ad_coin_postings (
    journal_id TEXT NOT NULL REFERENCES ad_coin_journals(id), account TEXT NOT NULL, amount INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS ad_coin_postings_account ON ad_coin_postings(account);
CREATE TABLE IF NOT EXISTS ad_coin_balances (account TEXT PRIMARY KEY, amount INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS ad_coin_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS ad_coin_circuit (id INTEGER PRIMARY KEY CHECK (id = 1), open INTEGER NOT NULL,
    reason TEXT NOT NULL, changed_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS ad_coin_campaigns (
    id TEXT PRIMARY KEY, advertiser TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
    public_url TEXT NOT NULL, categories TEXT NOT NULL, product TEXT NOT NULL, bid_won INTEGER NOT NULL,
    question TEXT NOT NULL, answer TEXT NOT NULL, status TEXT NOT NULL, test INTEGER NOT NULL,
    created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS ad_coin_quotes (
    id TEXT PRIMARY KEY, user_ref TEXT NOT NULL, agent_ref TEXT NOT NULL, selection_digest TEXT NOT NULL,
    task TEXT NOT NULL, options TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS ad_coin_reservations (
    id TEXT PRIMARY KEY, quote_id TEXT NOT NULL, campaign_id TEXT NOT NULL, product TEXT NOT NULL,
    user_ref TEXT NOT NULL, agent_ref TEXT NOT NULL, operator_ref TEXT NOT NULL, amount_won INTEGER NOT NULL,
    task_price_won INTEGER NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS ad_coin_consents (
    id TEXT PRIMARY KEY, reservation_id TEXT NOT NULL UNIQUE, user_ref TEXT NOT NULL,
    created_at REAL NOT NULL, used_at REAL);
CREATE TABLE IF NOT EXISTS ad_coin_exposures (
    reservation_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, user_ref TEXT NOT NULL, day TEXT NOT NULL,
    displayed_ms INTEGER NOT NULL, human_check TEXT NOT NULL, created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS ad_coin_exposures_cap ON ad_coin_exposures(user_ref, campaign_id, day);
CREATE TABLE IF NOT EXISTS ad_coin_vouchers (
    id TEXT PRIMARY KEY, reservation_id TEXT NOT NULL UNIQUE, user_ref TEXT NOT NULL, provider TEXT NOT NULL,
    task_ref TEXT NOT NULL, price_won INTEGER NOT NULL, status TEXT NOT NULL,
    created_at REAL NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS ad_coin_wallets (
    account TEXT PRIMARY KEY, user_ref TEXT NOT NULL, kind TEXT NOT NULL, agent_ref TEXT NOT NULL,
    created_at REAL NOT NULL, last_active_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS ad_coin_mandates (
    id TEXT PRIMARY KEY, user_ref TEXT NOT NULL, agent_ref TEXT NOT NULL, total_won INTEGER NOT NULL,
    per_task_won INTEGER NOT NULL, providers TEXT NOT NULL, spent_won INTEGER NOT NULL,
    created_at REAL NOT NULL, expires_at REAL NOT NULL, revoked_at REAL);
CREATE TABLE IF NOT EXISTS ad_coin_executions (
    id TEXT PRIMARY KEY, user_ref TEXT NOT NULL, provider TEXT NOT NULL, task_ref TEXT NOT NULL,
    price_won INTEGER NOT NULL, source TEXT NOT NULL, source_ref TEXT NOT NULL, status TEXT NOT NULL,
    result_digest TEXT, created_at REAL NOT NULL, finished_at REAL);
CREATE TABLE IF NOT EXISTS ad_coin_execution_lines (
    execution_id TEXT NOT NULL, position INTEGER NOT NULL, provider TEXT NOT NULL, calls INTEGER NOT NULL,
    won INTEGER NOT NULL, status TEXT NOT NULL, PRIMARY KEY (execution_id, position));
CREATE TABLE IF NOT EXISTS ad_coin_test_products (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL, definition TEXT NOT NULL,
    status TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS ad_coin_invites (
    customer_id TEXT PRIMARY KEY, note TEXT NOT NULL, created_at REAL NOT NULL, revoked_at REAL);
CREATE TABLE IF NOT EXISTS ad_coin_agent_keys (
    key_hash TEXT PRIMARY KEY, customer_id TEXT NOT NULL, agent_ref TEXT NOT NULL, created_at REAL NOT NULL,
    last_used_at REAL, revoked_at REAL);
CREATE INDEX IF NOT EXISTS ad_coin_agent_keys_owner ON ad_coin_agent_keys(customer_id, agent_ref);
CREATE TABLE IF NOT EXISTS ad_coin_run_claims (
    run_key TEXT PRIMARY KEY, execution_id TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS ad_coin_audits (
    id TEXT PRIMARY KEY, created_at REAL NOT NULL, passed INTEGER NOT NULL, summary TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ad_coin_campaign_categories (
    campaign_id TEXT NOT NULL, category TEXT NOT NULL, parent TEXT NOT NULL, PRIMARY KEY (campaign_id, category));
CREATE INDEX IF NOT EXISTS ad_coin_campaign_categories_lookup ON ad_coin_campaign_categories(category, parent);
CREATE INDEX IF NOT EXISTS ad_coin_campaign_categories_parent ON ad_coin_campaign_categories(parent);
CREATE INDEX IF NOT EXISTS ad_coin_reservations_campaign_day ON ad_coin_reservations(campaign_id, created_at);
CREATE INDEX IF NOT EXISTS ad_coin_reservations_user ON ad_coin_reservations(user_ref, status);
CREATE INDEX IF NOT EXISTS ad_coin_reservations_expiry ON ad_coin_reservations(status, expires_at);
CREATE INDEX IF NOT EXISTS ad_coin_exposures_user_day ON ad_coin_exposures(user_ref, day);
CREATE INDEX IF NOT EXISTS ad_coin_vouchers_expiry ON ad_coin_vouchers(status, expires_at);
CREATE INDEX IF NOT EXISTS ad_coin_vouchers_user ON ad_coin_vouchers(user_ref, status);
CREATE INDEX IF NOT EXISTS ad_coin_campaigns_product ON ad_coin_campaigns(product, status);
CREATE TABLE IF NOT EXISTS ad_coin_advertisers (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, website TEXT NOT NULL, status TEXT NOT NULL,
    verification TEXT NOT NULL, created_by TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS ad_coin_advertiser_members (
    advertiser_id TEXT NOT NULL, customer_id TEXT NOT NULL, role TEXT NOT NULL, created_at REAL NOT NULL,
    revoked_at REAL, PRIMARY KEY (advertiser_id, customer_id));
CREATE INDEX IF NOT EXISTS ad_coin_advertiser_members_customer ON ad_coin_advertiser_members(customer_id);
CREATE TABLE IF NOT EXISTS ad_coin_campaign_meta (
    campaign_id TEXT PRIMARY KEY, advertiser_id TEXT NOT NULL, name TEXT NOT NULL, daily_budget_won INTEGER NOT NULL,
    starts_at REAL NOT NULL, ends_at REAL, frequency_cap INTEGER NOT NULL, excluded TEXT NOT NULL,
    review_status TEXT NOT NULL, review_note TEXT NOT NULL, user_status TEXT NOT NULL,
    created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS ad_coin_campaign_meta_advertiser ON ad_coin_campaign_meta(advertiser_id);
CREATE TABLE IF NOT EXISTS ad_coin_creatives (
    id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL, question TEXT NOT NULL,
    answer TEXT NOT NULL, public_url TEXT NOT NULL, review_status TEXT NOT NULL, review_note TEXT NOT NULL,
    weight INTEGER NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL, removed_at REAL);
CREATE INDEX IF NOT EXISTS ad_coin_creatives_campaign ON ad_coin_creatives(campaign_id, review_status);
CREATE TABLE IF NOT EXISTS ad_coin_reservation_creatives (
    reservation_id TEXT PRIMARY KEY, creative_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ad_coin_appeals (
    id TEXT PRIMARY KEY, advertiser_id TEXT NOT NULL, object_ref TEXT NOT NULL, reason TEXT NOT NULL,
    status TEXT NOT NULL, resolution TEXT NOT NULL, created_at REAL NOT NULL, resolved_at REAL);
CREATE TABLE IF NOT EXISTS ad_coin_change_log (
    id TEXT PRIMARY KEY, advertiser_id TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL,
    object_ref TEXT NOT NULL, detail TEXT NOT NULL, created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS ad_coin_change_log_advertiser ON ad_coin_change_log(advertiser_id, created_at);
CREATE TABLE IF NOT EXISTS ad_coin_invalid_activity (
    reservation_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, reason TEXT NOT NULL, refunded_won INTEGER NOT NULL,
    created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS ad_coin_totals (bucket TEXT PRIMARY KEY, amount INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS ad_coin_campaign_daily (
    campaign_id TEXT NOT NULL, day TEXT NOT NULL, offers INTEGER NOT NULL, views INTEGER NOT NULL,
    spend_won INTEGER NOT NULL, invalid_refunded_won INTEGER NOT NULL, runs_started INTEGER NOT NULL,
    runs_succeeded INTEGER NOT NULL, PRIMARY KEY (campaign_id, day));
CREATE INDEX IF NOT EXISTS ad_coin_exposures_campaign_day ON ad_coin_exposures(campaign_id, day);
CREATE INDEX IF NOT EXISTS ad_coin_campaigns_bid ON ad_coin_campaigns(product, status, bid_won);
CREATE INDEX IF NOT EXISTS ad_coin_wallets_dormant ON ad_coin_wallets(kind, last_active_at);
CREATE TABLE IF NOT EXISTS ad_coin_receipts (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, user_ref TEXT NOT NULL, body TEXT NOT NULL, created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS ad_coin_receipts_user ON ad_coin_receipts(user_ref, created_at);
CREATE TABLE IF NOT EXISTS ad_coin_offer_acks (
    token_digest TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, operator_ref TEXT NOT NULL, day TEXT NOT NULL,
    created_at REAL NOT NULL);
"""


class Database:
    def __init__(self, path=':memory:'):
        path = os.fspath(path)
        if path != ':memory:':
            directory = os.path.dirname(os.path.abspath(path))
            os.makedirs(directory, exist_ok=True)
            private_sqlite_file(path)
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self._depth = 0
        with self.lock:
            self.db.execute('PRAGMA foreign_keys=ON')
            if path != ':memory:':
                self.db.execute('PRAGMA journal_mode=WAL')
            self.db.executescript(SCHEMA)

    @contextmanager
    def transaction(self):
        """Re-entrant: nested calls join the outer transaction."""
        with self.lock:
            outer = self._depth == 0
            if outer:
                self.db.execute('BEGIN IMMEDIATE')
            self._depth += 1
            try:
                yield self.db
            except BaseException:
                self._depth -= 1
                if outer:
                    self.db.execute('ROLLBACK')
                raise
            else:
                self._depth -= 1
                if outer:
                    self.db.execute('COMMIT')

    def lock_key(self, key):
        """Row-level concurrency hooks; SQLite already serializes every write."""

    def lock_rows(self, table, ids):
        pass

    @contextmanager
    def read(self):
        """One consistent read scope for a whole request (a no-op lock on SQLite)."""
        with self.lock:
            yield self

    def one(self, sql, args=()):
        with self.lock:
            return self.db.execute(sql, args).fetchone()

    def all(self, sql, args=()):
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    def close(self):
        with self.lock:
            self.db.close()


def now():
    return time.time()


def dumps(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


# ---------------- application PostgreSQL store ----------------
import re as _re

SCHEMA_VERSION = 3
_OR_IGNORE = _re.compile(r'^\s*INSERT OR IGNORE INTO\s+(.*)$', _re.S)


def postgres_sql(sql):
    """The few SQLite spellings AI AD Coin uses, in PostgreSQL. Values stay parameters."""
    text = sql.replace('%', '%%').replace('?', '%s')
    match = _OR_IGNORE.match(text)
    if match:
        text = 'INSERT INTO ' + match.group(1).rstrip() + ' ON CONFLICT DO NOTHING'
    return text


def postgres_schema():
    statements = []
    for part in SCHEMA.split(';'):
        part = part.strip()
        if not part:
            continue
        part = _re.sub(r'\bREAL\b', 'DOUBLE PRECISION', part)
        part = _re.sub(r'\bINTEGER\b', 'BIGINT', part)
        statements.append(part)
    return statements


class _PostgresCursor:
    def __init__(self, cursor):
        self._cursor = cursor
        self.rowcount = cursor.rowcount

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()


class _PostgresConnection:
    def __init__(self, store):
        self._store = store

    def execute(self, sql, args=()):
        return _PostgresCursor(self._store._execute(postgres_sql(sql), tuple(args)))


class ApplicationStoreDatabase:
    """AI AD Coin tables inside the application PostgreSQL store.

    Uses the store's own connection and transactions, so it adds no database
    connection and every write is serialized with the store's writer lock. The
    tables are separate (`ad_coin_*`); the catalog statement list and schema
    profile are untouched. Create the tables once with `migrate()` (operator CLI
    `scripts.ad_coin_migrate_postgres`); startup refuses an unmigrated store."""

    def __init__(self, store, *, require_migrated=True):
        if getattr(store, 'backend', '') != 'postgresql':
            raise ValueError('ApplicationStoreDatabase needs the application PostgreSQL store.')
        self.store = store
        self.lock = threading.RLock()
        if require_migrated and schema_version(self) != SCHEMA_VERSION:
            raise RuntimeError('AI AD Coin tables are missing; run scripts.ad_coin_migrate_postgres first.')

    @contextmanager
    def transaction(self):
        with self.store.tx():
            yield _PostgresConnection(self.store)

    @contextmanager
    def read(self):
        """One read-only transaction for a whole request, joined by every read inside it."""
        if getattr(self.store, '_depth', 0) and getattr(self.store, '_owner', None) == threading.get_ident():
            yield self
            return
        with self.store.tx(readonly=True):
            yield self

    def lock_key(self, key):
        """The application store serializes every write behind its writer lock already."""

    def lock_rows(self, table, ids):
        pass

    def _read(self, sql, args):
        owner = getattr(self.store, '_owner', None)
        if getattr(self.store, '_depth', 0) and owner == threading.get_ident():
            return _PostgresConnection(self.store).execute(sql, args)
        with self.store.tx(readonly=True):
            return _PostgresConnection(self.store).execute(sql, args)

    def one(self, sql, args=()):
        return self._read(sql, args).fetchone()

    def all(self, sql, args=()):
        return self._read(sql, args).fetchall()

    def close(self):
        pass  # the application store owns the connection


def schema_version(database):
    try:
        row = database.one("SELECT value FROM ad_coin_settings WHERE key='schema_version'")
    except Exception:
        return None
    return json.loads(row['value']) if row else None


def migrate(store):
    """Additive and idempotent: creates the ad_coin_* tables and indexes, then records the version."""
    database = ApplicationStoreDatabase(store, require_migrated=False)
    with store.tx():
        for statement in postgres_schema():
            store._execute(statement, ())
        store._execute(postgres_sql("INSERT INTO ad_coin_settings VALUES ('schema_version',?,?) "
                                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value"),
                       (json.dumps(SCHEMA_VERSION), now()))
        # Planner statistics for the ad_coin_* tables only (the rehearsal showed a 10x slower
        # campaign plan without them); autovacuum keeps them fresh afterwards.
        for table in sorted(set(_re.findall(r'CREATE TABLE IF NOT EXISTS (ad_coin_\w+)', SCHEMA))):
            store._execute('ANALYZE ' + table, ())
    return {'schema_version': schema_version(database), 'tables': sorted(
        _re.findall(r'CREATE TABLE IF NOT EXISTS (ad_coin_\w+)', SCHEMA))}


# ---------------- dedicated sessions on the application PostgreSQL database ----------------
from decimal import Decimal as _Decimal

POOL_MAXIMUM = 6
WRITER_LOCK_KEY = 0x0AD0C011      # AI AD Coin's own advisory lock, separate from the store's writer lock
POOL_MAX_ROWS = 2000


class FairLock:
    """A first-come, first-served lock. threading.Lock lets a newly arriving thread (already holding
    the GIL) barge past a woken waiter, so under steady load a few waiters wait many turns; here a
    release hands the lock straight to the oldest waiter."""

    def __init__(self):
        import collections
        self._mutex, self._held, self._waiters = threading.Lock(), False, collections.deque()

    def acquire(self, timeout=None):
        with self._mutex:
            if not self._held and not self._waiters:
                self._held = True
                return True
            turn = threading.Event()
            _spent.ahead = max(getattr(_spent, 'ahead', 0), len(self._waiters) + 1)
            self._waiters.append(turn)
        if turn.wait(timeout):
            return True
        with self._mutex:
            if turn in self._waiters:
                self._waiters.remove(turn)
                return False
        return True            # handed over just as the wait timed out

    def release(self):
        with self._mutex:
            if self._waiters:
                self._waiters.popleft().set()    # ownership passes directly; _held stays True
            else:
                self._held = False


class PoolBusy(RuntimeError):
    """No AI AD Coin session was free within the wait; nothing was read or written."""


class _PooledCursor:
    def __init__(self, rows, rowcount):
        self._rows, self.rowcount = rows, rowcount

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


_clock = time.perf_counter
_spent = threading.local()      # database wall time on this thread, for Server-Timing


def take_db_ms():
    """Database time spent on this thread since the last call, in ms (dedicated pool only)."""
    value = getattr(_spent, 'ms', 0.0)
    _spent.ms = 0.0
    return value


def take_waits():
    """(session pool wait, writer lock wait) on this thread since the last call, in ms."""
    value = (getattr(_spent, 'pool', 0.0), getattr(_spent, 'lock', 0.0), getattr(_spent, 'hold', 0.0),
             getattr(_spent, 'ahead', 0))
    _spent.pool = _spent.lock = _spent.hold = 0.0
    _spent.ahead = 0
    return value


def take_db_calls():
    """Database round trips on this thread since the last call (dedicated pool only)."""
    value = getattr(_spent, 'n', 0)
    _spent.n = 0
    return value


def _timed(connection, sql, params=None):
    started = _clock()
    try:
        return connection.execute(sql, params) if params is not None else connection.execute(sql)
    finally:
        _spent.ms = getattr(_spent, 'ms', 0.0) + (_clock() - started) * 1000
        _spent.n = getattr(_spent, 'n', 0) + 1


class _PooledConnection:
    def __init__(self, connection):
        self._connection = connection

    def execute(self, sql, args=()):
        started = _clock()
        try:
            return self._execute(sql, args)
        finally:
            _spent.ms = getattr(_spent, 'ms', 0.0) + (_clock() - started) * 1000
            _spent.n = getattr(_spent, 'n', 0) + 1

    def _execute(self, sql, args):
        from ..storage_adapter import Row
        values = tuple(str(v) if type(v) is int else v for v in args)
        with self._connection.cursor() as cursor:
            cursor.execute(postgres_sql(sql), values)
            rows = []
            if cursor.description:
                names = tuple(item[0] for item in cursor.description)
                while True:
                    batch = cursor.fetchmany(256)
                    if not batch:
                        break
                    if len(rows) + len(batch) > POOL_MAX_ROWS:
                        raise RuntimeError('result_limit')
                    for record in batch:
                        rows.append(Row(names, tuple(
                            (int(v) if v == v.to_integral_value() else float(v))
                            if isinstance(v, _Decimal) and v.is_finite() else v for v in record)))
            return _PooledCursor(rows, cursor.rowcount)


class PooledPostgresDatabase:
    """AI AD Coin on its own small pool of sessions to the application PostgreSQL database.

    The application store keeps one session per process behind one Python lock,
    so AI AD Coin requests would queue behind Explore and Chat (and each other).
    Here reads run in parallel (REPEATABLE READ READ ONLY) and writes take AI AD
    Coin's own transaction-scoped advisory lock, so money moves stay serialized
    exactly as before while touching only the ad_coin_* tables. At most `maximum`
    sessions are opened per process (POOL_MAXIMUM, one kept idle); a request that
    cannot get one within `wait_seconds` is refused with PoolBusy (HTTP 503)."""

    def __init__(self, factory, *, maximum=POOL_MAXIMUM, wait_seconds=2.0, statement_timeout_ms=2000,
                 require_migrated=True):
        self.factory, self.maximum, self.wait_seconds = factory, maximum, wait_seconds
        self.statement_timeout_ms = int(statement_timeout_ms)
        self.lock = threading.RLock()
        self._condition = threading.Condition()
        self._idle, self._total, self._closed = [], 0, False
        self._local = threading.local()
        # Writers run concurrently: money is protected by row locks and atomic balance updates, a
        # person by lock_key, a campaign's budget by lock_rows. Every writer also holds AI AD Coin's
        # advisory lock in shared mode, so an exclusive maintenance step can still stop them all.
        self.background_checks = True     # full recounts run on their own snapshot, off the writer lock
        self.savepoints = True            # a nested write that fails is undone alone
        if require_migrated and schema_version(self) != SCHEMA_VERSION:
            raise RuntimeError('AI AD Coin tables are missing; run scripts.ad_coin_migrate_postgres first.')

    # -- sessions
    def _lease(self):
        import time as _time
        deadline = _time.monotonic() + self.wait_seconds
        with self._condition:
            while True:
                if self._closed:
                    raise PoolBusy('closed')
                while self._idle:
                    connection = self._idle.pop()
                    if not (connection.closed or getattr(connection, 'broken', False)):
                        return connection
                    self._total -= 1
                if self._total < self.maximum:
                    self._total += 1
                    break
                remaining = deadline - _time.monotonic()
                if remaining <= 0:
                    raise PoolBusy('busy')
                self._condition.wait(remaining)
        try:
            connection = self.factory()
            if connection.autocommit is not True:
                connection.autocommit = True
            return connection
        except BaseException:
            with self._condition:
                self._total -= 1
                self._condition.notify()
            raise

    def _release(self, connection, discard=False):
        with self._condition:
            healthy = not discard and not connection.closed and int(connection.info.transaction_status) == 0
            if healthy and not self._closed and len(self._idle) < self.maximum:   # opening one costs tens of ms
                self._idle.append(connection)
            else:
                self._total -= 1
                try:
                    connection.close()
                except Exception:
                    pass
            self._condition.notify()

    @contextmanager
    def _session(self, mode):
        current = getattr(self._local, 'current', None)
        if current is not None:
            if mode == 'write' and current[1] == 'read':
                raise RuntimeError('A write cannot join a read-only AI AD Coin transaction.')
            if mode == 'write':
                # A nested write is a savepoint: if it fails, only its own statements are undone and
                # the caller may handle the error and go on (on SQLite the whole write is serialized).
                depth = getattr(self._local, 'savepoints', 0) + 1
                self._local.savepoints = depth
                name = 'adc_sp_%d' % depth
                _timed(current[0]._connection, 'SAVEPOINT ' + name)
                try:
                    yield current[0]
                except BaseException:
                    _timed(current[0]._connection, 'ROLLBACK TO SAVEPOINT ' + name)
                    raise
                else:
                    _timed(current[0]._connection, 'RELEASE SAVEPOINT ' + name)
                finally:
                    self._local.savepoints = depth - 1
                return
            yield current[0]
            return
        writer = _clock() if mode == 'write' else None
        waited = _clock()
        connection = self._lease()
        _spent.pool = getattr(_spent, 'pool', 0.0) + (_clock() - waited) * 1000
        wrapped, ok = _PooledConnection(connection), False
        try:
            if mode == 'write':
                _timed(connection, 'BEGIN; SET LOCAL statement_timeout = %d; SET LOCAL lock_timeout = %d'
                       % (self.statement_timeout_ms, self.statement_timeout_ms))
                waited = _clock()
                _timed(connection, 'SELECT pg_advisory_xact_lock_shared(%s)', (WRITER_LOCK_KEY,))
                _spent.lock = getattr(_spent, 'lock', 0.0) + (_clock() - waited) * 1000
            else:
                _timed(connection, 'BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; SET LOCAL statement_timeout = %d'
                       % self.statement_timeout_ms)
            self._local.current = (wrapped, mode)
            try:
                yield wrapped
            finally:
                self._local.current = None
            _timed(connection, 'COMMIT')
            ok = True
        finally:
            if not ok:
                try:
                    connection.execute('ROLLBACK')
                except Exception:
                    self._release(connection, discard=True)
                    connection = None
            if connection is not None:
                self._release(connection)
            if writer:
                _spent.hold = getattr(_spent, 'hold', 0.0) + (_clock() - writer) * 1000

    @contextmanager
    def transaction(self):
        with self._session('write') as connection:
            yield connection

    def in_transaction(self):
        return getattr(self._local, 'current', None) is not None

    def _write_connection(self):
        current = getattr(self._local, 'current', None)
        if current is None or current[1] != 'write':
            raise RuntimeError('Row locks are taken inside an AI AD Coin write transaction.')
        return current[0]._connection

    def lock_key(self, key):
        """Serialize writers on one logical key (a person, an advertiser) until this transaction ends."""
        waited = _clock()
        _timed(self._write_connection(), 'SELECT pg_advisory_xact_lock(%s::int4, hashtext(%s))',
               (WRITER_LOCK_KEY & 0x7FFFFFFF, str(key)))
        _spent.lock = getattr(_spent, 'lock', 0.0) + (_clock() - waited) * 1000

    def lock_rows(self, table, ids):
        """Lock these rows (in id order, so writers never deadlock on them) until this transaction ends."""
        if table not in ('ad_coin_campaigns',):
            raise ValueError('lock_rows is for campaign rows.')
        ids = sorted(set(ids))
        if not ids:
            return
        waited = _clock()
        _timed(self._write_connection(), 'SELECT id FROM ' + table + ' WHERE id = ANY(%s) ORDER BY id FOR UPDATE',
               (ids,))
        _spent.lock = getattr(_spent, 'lock', 0.0) + (_clock() - waited) * 1000

    @contextmanager
    def exclusive(self):
        """A write that no other AI AD Coin writer runs beside (rebuilding running totals)."""
        with self._session('write') as connection:
            _timed(connection._connection, 'SELECT pg_advisory_xact_lock(%s)', (WRITER_LOCK_KEY,))
            yield connection

    @contextmanager
    def read(self):
        with self._session('read'):
            yield self

    def _query(self, sql, args):
        current = getattr(self._local, 'current', None)
        if current is not None:
            return current[0].execute(sql, args)
        with self._session('read') as connection:
            return connection.execute(sql, args)

    def one(self, sql, args=()):
        return self._query(sql, args).fetchone()

    def all(self, sql, args=()):
        return self._query(sql, args).fetchall()

    def stats(self):
        with self._condition:
            return {'open': self._total, 'idle': len(self._idle), 'maximum': self.maximum}

    def close(self):
        with self._condition:
            self._closed = True
            for connection in self._idle:
                self._total -= 1
                try:
                    connection.close()
                except Exception:
                    pass
            self._idle = []
            self._condition.notify_all()
