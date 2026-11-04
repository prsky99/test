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

SCHEMA_VERSION = 1
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
    return {'schema_version': schema_version(database), 'tables': sorted(
        _re.findall(r'CREATE TABLE IF NOT EXISTS (ad_coin_\w+)', SCHEMA))}
