"""Explicit dialect contracts and conservative local transaction certainty."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from agent_market.storage_adapter import SQLiteAdapter, Statement, StorageError


CREATE = Statement('create_records',
    'CREATE TABLE records(id INTEGER PRIMARY KEY AUTOINCREMENT,label TEXT UNIQUE,quantity INTEGER,observed REAL,amount TEXT,payload BLOB)',
    'CREATE TABLE records(id BIGSERIAL PRIMARY KEY,label TEXT UNIQUE,quantity BIGINT,observed DOUBLE PRECISION,amount TEXT,payload BYTEA)')
INSERT = Statement('insert_record',
    'INSERT INTO records(label,quantity,observed,amount,payload) VALUES (?,?,?,?,?) RETURNING id',
    'INSERT INTO records(label,quantity,observed,amount,payload) VALUES (%s,%s,%s,%s,%s) RETURNING id')
GET = Statement('get_record', 'SELECT * FROM records WHERE id=?', 'SELECT * FROM records WHERE id=%s', True)


@pytest.fixture
def database():
    db = sqlite3.connect(':memory:'); adapter = SQLiteAdapter(db)
    with adapter.transaction() as session: session.execute(CREATE)
    try: yield adapter, db
    finally: db.close()


@pytest.mark.parametrize('values', [
    ('Unicode \u03a9 \U0001f30d quotes\' ; -- %s ?', None, 0.0, '123.000001', b'\0\x01'),
    ('largest integer', 2**63-1, 1735689600.125, '-0.000001', b'fixture'),
    ('smallest integer', -(2**63), -0.125, None, None),
])
def test_declared_scalar_types_round_trip_without_timestamp_or_decimal_coercion(database, values):
    adapter, _db = database
    with adapter.transaction() as session:
        identity = session.execute(INSERT, values).rows[0][0]
    with adapter.transaction(readonly=True) as session:
        row = session.execute(GET, (identity,)).rows[0]
    assert row.values == (identity, *values)
    assert dict(row)['amount'] == values[3]
    assert dict(row)['observed'] == values[2]


def test_explicit_variants_do_not_replace_literal_placeholder_characters(database):
    adapter, _db = database
    statement = Statement('literal_tokens', "SELECT '?' AS q, '%s' AS p", "SELECT '?' AS q, '%%s' AS p", True)
    with adapter.transaction(readonly=True) as session:
        assert session.execute(statement).rows[0].values == ('?', '%s')


def test_result_rowcount_remains_native_and_ids_are_explicit_returning(database):
    adapter, _db = database
    with adapter.transaction() as session:
        inserted = session.execute(INSERT, ('one', 1, 1.0, '1', b''))
        assert len(inserted.rows) == 1 and inserted.rows[0][0] == 1
    with adapter.transaction(readonly=True) as session:
        selected = session.execute(GET, (1,))
        assert selected.rowcount == -1  # SQLite SELECT, not a fabricated PostgreSQL count.
        assert not hasattr(selected, 'lastrowid')


def test_transaction_refuses_preexisting_caller_work_without_rolling_it_back(database):
    adapter, db = database
    db.execute("INSERT INTO records(label) VALUES ('caller-owned')")
    with pytest.raises(StorageError, match='connection_busy'):
        with adapter.transaction(): pass
    assert db.in_transaction
    db.commit()
    assert db.execute('SELECT COUNT(*) FROM records').fetchone()[0] == 1


def test_file_backed_concurrent_adapters_have_one_cas_winner(tmp_path):
    path = tmp_path / 'synthetic.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE claim(id INTEGER PRIMARY KEY, fence INTEGER NOT NULL, owner TEXT)')
        db.execute('INSERT INTO claim VALUES (1,0,NULL)')
    claim = Statement('claim_once',
        'UPDATE claim SET fence=fence+1,owner=? WHERE id=1 AND owner IS NULL RETURNING fence',
        'UPDATE claim SET fence=fence+1,owner=%s WHERE id=1 AND owner IS NULL RETURNING fence')
    def attempt(index):
        db = sqlite3.connect(path, timeout=2)
        try:
            with SQLiteAdapter(db).transaction() as session:
                return session.execute(claim, ('synthetic-'+str(index),)).rows
        finally: db.close()
    with ThreadPoolExecutor(max_workers=4) as pool: rows = list(pool.map(attempt, range(4)))
    assert sum(bool(value) for value in rows) == 1
    with sqlite3.connect(path) as db: assert db.execute('SELECT fence FROM claim').fetchone()[0] == 1


class CommitAcknowledgementLost(sqlite3.Connection):
    fail_commit = False
    def commit(self):
        super().commit()
        if self.fail_commit: raise OSError('synthetic-private-driver-detail')


def test_commit_acceptance_followed_by_error_is_unknown_and_connection_cannot_be_reused():
    db = sqlite3.connect(':memory:', factory=CommitAcknowledgementLost)
    db.execute('CREATE TABLE sample(value TEXT)'); db.commit(); adapter = SQLiteAdapter(db)
    db.fail_commit = True
    try:
        with pytest.raises(StorageError) as error:
            with adapter.transaction() as session:
                session.execute(Statement('accepted_write', 'INSERT INTO sample VALUES (?)', 'INSERT INTO sample VALUES (%s)'), ('once',))
        assert error.value.code == 'commit_unknown' and 'synthetic-private' not in str(error.value)
        assert db.execute('SELECT COUNT(*) FROM sample').fetchone()[0] == 1
        with pytest.raises(StorageError, match='connection_unusable'):
            with adapter.transaction(): pass
    finally: db.close()


class CommitInterrupted(sqlite3.Connection):
    def commit(self): raise KeyboardInterrupt()


def test_commit_cancellation_propagates_and_disables_connection():
    db = sqlite3.connect(':memory:', factory=CommitInterrupted); adapter = SQLiteAdapter(db)
    try:
        with pytest.raises(KeyboardInterrupt):
            with adapter.transaction() as session:
                session.execute(Statement('read_one', 'SELECT 1 AS n', 'SELECT 1 AS n', True))
        with pytest.raises(StorageError, match='connection_unusable'):
            with adapter.transaction(): pass
    finally: db.close()


@pytest.mark.parametrize('value', ['BEGIN', 'COMMIT', 'ROLLBACK', 'SAVEPOINT one', 'PRAGMA query_only=OFF',
    "ATTACH DATABASE 'private' AS outside", '-- comment\nSELECT 1', '/* comment */ SELECT 1', 'VACUUM', ''])
def test_unsupported_command_fails_before_any_driver_execution(value):
    with pytest.raises(StorageError, match='invalid_statement'):
        Statement('invalid_command', value, value)


def test_detach_keeps_caller_connection_open_and_prevents_adapter_reuse(database):
    adapter, db = database; adapter.detach()
    assert db.execute('SELECT 1').fetchone() == (1,)
    with pytest.raises(StorageError, match='connection_unusable'):
        with adapter.transaction(): pass


def test_cancellation_during_rollback_is_not_replaced_with_an_ordinary_error():
    class InterruptedRollback(sqlite3.Connection):
        def rollback(self): raise KeyboardInterrupt()
    db = sqlite3.connect(':memory:', factory=InterruptedRollback); adapter = SQLiteAdapter(db)
    try:
        with pytest.raises(KeyboardInterrupt):
            with adapter.transaction(): raise RuntimeError('Synthetic caller error')
        with pytest.raises(StorageError, match='connection_unusable'):
            with adapter.transaction(): pass
    finally: db.close()


@pytest.mark.parametrize('caller_error', [False, True])
def test_cancellation_during_readonly_setting_restore_remains_cancellation(caller_error):
    class InterruptedRestore(sqlite3.Cursor):
        def execute(self, sql, *args, **kwargs):
            if sql == 'PRAGMA query_only=OFF': raise KeyboardInterrupt()
            return super().execute(sql, *args, **kwargs)
    class Connection(sqlite3.Connection):
        def cursor(self, *args, **kwargs):
            return super().cursor(*args, factory=InterruptedRestore, **kwargs)
    db = sqlite3.connect(':memory:', factory=Connection); adapter = SQLiteAdapter(db)
    try:
        with pytest.raises(KeyboardInterrupt):
            with adapter.transaction(readonly=True) as session:
                session.execute(Statement('read_once', 'SELECT 1 AS n', 'SELECT 1 AS n', True))
                if caller_error: raise RuntimeError('Synthetic caller error')
        assert not db.in_transaction
        with pytest.raises(StorageError, match='connection_unusable'):
            with adapter.transaction(): pass
    finally: db.close()
