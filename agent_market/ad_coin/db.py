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
CREATE TABLE IF NOT EXISTS journals (
    id TEXT PRIMARY KEY, created_at REAL NOT NULL, kind TEXT NOT NULL,
    idem TEXT NOT NULL UNIQUE, detail TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS postings (
    journal_id TEXT NOT NULL REFERENCES journals(id), account TEXT NOT NULL, amount INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS postings_account ON postings(account);
CREATE TABLE IF NOT EXISTS balances (account TEXT PRIMARY KEY, amount INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS circuit (id INTEGER PRIMARY KEY CHECK (id = 1), open INTEGER NOT NULL,
    reason TEXT NOT NULL, changed_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS campaigns (
    id TEXT PRIMARY KEY, advertiser TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
    public_url TEXT NOT NULL, categories TEXT NOT NULL, product TEXT NOT NULL, bid_won INTEGER NOT NULL,
    question TEXT NOT NULL, answer TEXT NOT NULL, status TEXT NOT NULL, test INTEGER NOT NULL,
    created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS quotes (
    id TEXT PRIMARY KEY, user_ref TEXT NOT NULL, agent_ref TEXT NOT NULL, selection_digest TEXT NOT NULL,
    task TEXT NOT NULL, options TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS reservations (
    id TEXT PRIMARY KEY, quote_id TEXT NOT NULL, campaign_id TEXT NOT NULL, product TEXT NOT NULL,
    user_ref TEXT NOT NULL, agent_ref TEXT NOT NULL, operator_ref TEXT NOT NULL, amount_won INTEGER NOT NULL,
    task_price_won INTEGER NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS consents (
    id TEXT PRIMARY KEY, reservation_id TEXT NOT NULL UNIQUE, user_ref TEXT NOT NULL,
    created_at REAL NOT NULL, used_at REAL);
CREATE TABLE IF NOT EXISTS exposures (
    reservation_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, user_ref TEXT NOT NULL, day TEXT NOT NULL,
    displayed_ms INTEGER NOT NULL, human_check TEXT NOT NULL, created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS exposures_cap ON exposures(user_ref, campaign_id, day);
CREATE TABLE IF NOT EXISTS vouchers (
    id TEXT PRIMARY KEY, reservation_id TEXT NOT NULL UNIQUE, user_ref TEXT NOT NULL, provider TEXT NOT NULL,
    task_ref TEXT NOT NULL, price_won INTEGER NOT NULL, status TEXT NOT NULL,
    created_at REAL NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS wallets (
    account TEXT PRIMARY KEY, user_ref TEXT NOT NULL, kind TEXT NOT NULL, agent_ref TEXT NOT NULL,
    created_at REAL NOT NULL, last_active_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS mandates (
    id TEXT PRIMARY KEY, user_ref TEXT NOT NULL, agent_ref TEXT NOT NULL, total_won INTEGER NOT NULL,
    per_task_won INTEGER NOT NULL, providers TEXT NOT NULL, spent_won INTEGER NOT NULL,
    created_at REAL NOT NULL, expires_at REAL NOT NULL, revoked_at REAL);
CREATE TABLE IF NOT EXISTS executions (
    id TEXT PRIMARY KEY, user_ref TEXT NOT NULL, provider TEXT NOT NULL, task_ref TEXT NOT NULL,
    price_won INTEGER NOT NULL, source TEXT NOT NULL, source_ref TEXT NOT NULL, status TEXT NOT NULL,
    result_digest TEXT, created_at REAL NOT NULL, finished_at REAL);
CREATE TABLE IF NOT EXISTS execution_lines (
    execution_id TEXT NOT NULL, position INTEGER NOT NULL, provider TEXT NOT NULL, calls INTEGER NOT NULL,
    won INTEGER NOT NULL, status TEXT NOT NULL, PRIMARY KEY (execution_id, position));
CREATE TABLE IF NOT EXISTS receipts (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, user_ref TEXT NOT NULL, body TEXT NOT NULL, created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS receipts_user ON receipts(user_ref, created_at);
CREATE TABLE IF NOT EXISTS offer_acks (
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
