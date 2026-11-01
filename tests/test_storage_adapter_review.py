"""Independent adapter boundaries and unchanged legacy transaction semantics."""
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
import math
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.fixture
def adapter_db():
    from agent_market.storage_adapter import SQLiteAdapter
    db = sqlite3.connect(':memory:', check_same_thread=False)
    db.execute('CREATE TABLE sample(id INTEGER PRIMARY KEY, value TEXT UNIQUE)')
    db.commit()
    adapter = SQLiteAdapter(db)
    try:
        yield adapter, db
    finally:
        db.close()


def statement(name, sql, *, readonly=False):
    from agent_market.storage_adapter import Statement
    return Statement(name, sql, sql, readonly=readonly)


def test_caller_owned_connection_commits_explicit_returning_and_rolls_back_on_exception(adapter_db):
    adapter, db = adapter_db
    with adapter.transaction() as session:
        result = session.execute(statement('insert_value', 'INSERT INTO sample(value) VALUES (?) RETURNING id,value'), ('committed',))
        assert len(result.rows) == 1
        row = result.rows[0]
        assert row[0] == row['id'] == 1 and row[1] == row['value'] == 'committed'
        assert row[:] == (1, 'committed')
        assert dict(row) == {'id': 1, 'value': 'committed'}
        assert not hasattr(result, 'lastrowid')
    with pytest.raises(RuntimeError, match='Synthetic caller failure'):
        with adapter.transaction() as session:
            session.execute(statement('insert_value', 'INSERT INTO sample(value) VALUES (?)'), ('rolled-back',))
            raise RuntimeError('Synthetic caller failure')
    assert db.execute('SELECT value FROM sample').fetchall() == [('committed',)]
    assert db.execute('SELECT 1').fetchone() == (1,)  # The adapter does not close its caller's connection.


def test_values_remain_bound_data_without_sql_interpolation(adapter_db):
    adapter, db = adapter_db
    payload = "synthetic'); DROP TABLE sample; --"
    with adapter.transaction() as session:
        session.execute(statement('bound_insert', 'INSERT INTO sample(value) VALUES (?)'), (payload,))
    assert db.execute('SELECT value FROM sample').fetchone()[0] == payload


@pytest.mark.parametrize('params', [
    ['value'], {'value': 'value'}, 'value', iter(('value',)),
    (True,), (False,), (2**63,), (-2**63-1,), (math.inf,), (-math.inf,), (math.nan,),
    ({'secret': 'synthetic-parameter-secret'},), (['value'],), (object(),),
    ('nul\0value',), ('unpaired\ud800',), ('x' * 16385,), (b'x' * 16385,),
    tuple(range(65)), ('x' * 16384,) * 5,
])
def test_invalid_parameters_are_fixed_errors_and_cannot_commit_prior_work(adapter_db, params):
    from agent_market.storage_adapter import StorageError
    adapter, db = adapter_db
    with pytest.raises(StorageError) as outer:
        with adapter.transaction() as session:
            session.execute(statement('earlier_write', 'INSERT INTO sample(value) VALUES (?)'), ('must-rollback',))
            try:
                session.execute(statement('invalid_parameter', 'SELECT ?'), params)
            except StorageError as error:
                assert error.code == 'invalid_parameters'
                assert 'synthetic-parameter-secret' not in str(error)
                assert 'SELECT' not in str(error)
    assert outer.value.code == 'transaction_failed'
    assert db.execute('SELECT COUNT(*) FROM sample').fetchone()[0] == 0


def test_native_read_only_rejects_dishonest_statement_hint_and_restores_connection(adapter_db):
    from agent_market.storage_adapter import StorageError
    adapter, db = adapter_db
    assert db.execute('PRAGMA query_only').fetchone()[0] == 0
    with pytest.raises(StorageError) as error:
        with adapter.transaction(readonly=True) as session:
            session.execute(statement('dishonest_read_hint', 'INSERT INTO sample(value) VALUES (?)', readonly=True), ('forbidden',))
    assert error.value.code in {'read_only', 'statement_failed'}
    assert db.execute('PRAGMA query_only').fetchone()[0] == 0
    assert not db.in_transaction
    with adapter.transaction() as session:
        session.execute(statement('later_write', 'INSERT INTO sample(value) VALUES (?)'), ('allowed',))
    assert db.execute('SELECT value FROM sample').fetchone()[0] == 'allowed'


def test_preexisting_read_only_setting_and_authorizer_survive_adapter_sessions():
    from agent_market.storage_adapter import SQLiteAdapter
    db = sqlite3.connect(':memory:')
    seen = []
    def authorizer(action, *_args):
        seen.append(action)
        return sqlite3.SQLITE_OK
    db.set_authorizer(authorizer)
    db.row_factory = lambda _cursor, row: {'original': tuple(row)}
    original_factory = db.row_factory
    db.execute('PRAGMA query_only=ON')
    try:
        adapter = SQLiteAdapter(db)
        with adapter.transaction(readonly=True) as session:
            assert dict(session.execute(statement('one_value', 'SELECT 7 AS value', readonly=True)).rows[0]) == {'value': 7}
        assert db.row_factory is original_factory
        assert db.execute('PRAGMA query_only').fetchone() == {'original': (1,)}
        seen.clear()
        db.execute('SELECT 12345 AS retained_policy').fetchall()
        assert sqlite3.SQLITE_SELECT in seen
    finally:
        db.close()


def test_duplicate_result_names_refuse_ambiguous_mapping_and_rollback_prior_write(adapter_db):
    from agent_market.storage_adapter import StorageError
    adapter, db = adapter_db
    with pytest.raises(StorageError) as captured:
        with adapter.transaction() as session:
            session.execute(statement('write_before_result', 'INSERT INTO sample(value) VALUES (?)'), ('rollback',))
            session.execute(statement('duplicate_names', 'SELECT 1 AS value,2 AS value', readonly=True))
    assert captured.value.code in {'statement_failed', 'result_limit'}
    assert db.execute('SELECT COUNT(*) FROM sample').fetchone()[0] == 0


def test_caught_database_error_poisoned_transaction_cannot_commit(adapter_db):
    from agent_market.storage_adapter import StorageError
    adapter, db = adapter_db
    with pytest.raises(StorageError) as captured:
        with adapter.transaction() as session:
            session.execute(statement('insert_once', 'INSERT INTO sample(value) VALUES (?)'), ('same',))
            try:
                session.execute(statement('duplicate_insert', 'INSERT INTO sample(value) VALUES (?)'), ('same',))
            except StorageError as error:
                assert error.code == 'statement_failed'
                assert 'UNIQUE' not in str(error) and 'sample' not in str(error)
    assert captured.value.code == 'transaction_failed'
    assert db.execute('SELECT COUNT(*) FROM sample').fetchone()[0] == 0


def test_session_expires_after_commit_and_cannot_be_reused(adapter_db):
    from agent_market.storage_adapter import StorageError
    adapter, _db = adapter_db
    with adapter.transaction() as session:
        session.execute(statement('active_query', 'SELECT 1', readonly=True))
    with pytest.raises(StorageError) as captured:
        session.execute(statement('stale_query', 'SELECT 1', readonly=True))
    assert captured.value.code == 'session_closed'


def test_adapter_refuses_nested_transaction_without_opening_a_savepoint(adapter_db):
    from agent_market.storage_adapter import StorageError
    adapter, _db = adapter_db
    with adapter.transaction() as session:
        with pytest.raises(StorageError) as captured:
            with adapter.transaction():
                pytest.fail('Nested adapter transaction was admitted')
        assert captured.value.code == 'nested_transaction'
        assert session.execute(statement('original_session', 'SELECT 1', readonly=True)).rows[0][0] == 1


def test_active_session_cannot_be_used_from_another_thread(adapter_db):
    from agent_market.storage_adapter import StorageError
    adapter, _db = adapter_db
    with adapter.transaction() as session:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with pytest.raises(StorageError) as captured:
                pool.submit(session.execute, statement('wrong_thread', 'SELECT 1', readonly=True)).result(timeout=3)
        assert captured.value.code == 'thread_violation'
        assert session.execute(statement('correct_thread', 'SELECT 2', readonly=True)).rows[0][0] == 2


def test_concurrent_transaction_cannot_share_an_active_connection(adapter_db):
    from agent_market.storage_adapter import StorageError
    adapter, _db = adapter_db
    def competing():
        with adapter.transaction():
            pytest.fail('Concurrent transaction was admitted')
    with adapter.transaction() as session:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with pytest.raises(StorageError) as captured:
                pool.submit(competing).result(timeout=3)
        assert captured.value.code == 'connection_busy'
        assert session.execute(statement('original_owner', 'SELECT 3', readonly=True)).rows[0][0] == 3


@pytest.mark.parametrize('sql', [
    'PRAGMA query_only=OFF', 'ATTACH DATABASE ? AS alternate', 'BEGIN IMMEDIATE',
    'COMMIT', 'ROLLBACK', 'SAVEPOINT nested', '-- hidden\nSELECT 1', '/* hidden */ SELECT 1',
])
def test_disallowed_statement_channels_are_rejected_before_execution(sql):
    from agent_market.storage_adapter import StorageError
    with pytest.raises(StorageError) as captured:
        statement('forbidden_channel', sql)
    assert captured.value.code == 'invalid_statement'
    assert sql not in str(captured.value)


def test_multiple_sql_statements_cannot_execute_a_prefix_write(adapter_db):
    from agent_market.storage_adapter import StorageError
    adapter, db = adapter_db
    with pytest.raises(StorageError):
        with adapter.transaction() as session:
            session.execute(statement('multiple_statements', "INSERT INTO sample(value) VALUES ('not-committed'); DELETE FROM sample"))
    assert db.execute('SELECT COUNT(*) FROM sample').fetchone()[0] == 0


def test_native_read_only_rejects_with_prefixed_write(adapter_db):
    from agent_market.storage_adapter import StorageError
    adapter, db = adapter_db
    with pytest.raises(StorageError) as captured:
        with adapter.transaction(readonly=True) as session:
            session.execute(statement('with_prefixed_write', "WITH input(value) AS (SELECT ?) INSERT INTO sample(value) SELECT value FROM input", readonly=True), ('forbidden',))
    assert captured.value.code in {'read_only', 'statement_failed'}
    assert db.execute('SELECT COUNT(*) FROM sample').fetchone()[0] == 0


@pytest.mark.parametrize('sql', [
    'WITH RECURSIVE items(n) AS (SELECT 0 UNION ALL SELECT n+1 FROM items WHERE n<1000) SELECT n FROM items',
    'SELECT zeroblob(1048577) AS payload',
])
def test_output_limits_fail_closed_and_rollback_prior_work(adapter_db, sql):
    from agent_market.storage_adapter import StorageError
    adapter, db = adapter_db
    with pytest.raises(StorageError) as captured:
        with adapter.transaction() as session:
            session.execute(statement('write_before_limit', 'INSERT INTO sample(value) VALUES (?)'), ('rollback',))
            session.execute(statement('bounded_result', sql, readonly=True))
    assert captured.value.code == 'result_limit'
    assert db.execute('SELECT COUNT(*) FROM sample').fetchone()[0] == 0


def test_driver_error_text_and_sql_identifiers_do_not_escape(adapter_db):
    from agent_market.storage_adapter import StorageError
    adapter, _db = adapter_db
    with pytest.raises(StorageError) as captured:
        with adapter.transaction(readonly=True) as session:
            session.execute(statement('private_query', 'SELECT synthetic_private_identifier FROM sample', readonly=True))
    assert captured.value.code == 'statement_failed'
    text = str(captured.value)
    for private in ('synthetic_private_identifier', 'sample', 'SELECT', 'no such column', 'Traceback'):
        assert private not in text


@pytest.mark.parametrize('backend', ['postgresql', 'postgres', 'PostgreSQL', 'unknown-synthetic-secret'])
def test_unsupported_operating_backend_refused_before_path_io_or_application_import(backend):
    code = r'''
import builtins,json,os,sqlite3,sys
from agent_market.storage_adapter import open_store,StorageError
assert 'agent_market.gateway.store' not in sys.modules
assert 'agent_market.workflows' not in sys.modules
class PrivatePath:
    def __fspath__(self):raise AssertionError('Private path was inspected')
    def __str__(self):raise AssertionError('Private path was formatted')
    def __repr__(self):raise AssertionError('Private path was represented')
def forbidden(*args,**kwargs):raise AssertionError('Unexpected database or file effect')
original_import=builtins.__import__
def importing(name,*args,**kwargs):
    if name in ('agent_market.gateway.store','gateway.store') or name.startswith(('psycopg','psycopg2')):
        raise AssertionError('Unexpected application or driver import')
    return original_import(name,*args,**kwargs)
builtins.__import__=importing
os.open=forbidden
sqlite3.connect=forbidden
try:open_store(sys.argv[1],sqlite_path=PrivatePath())
except StorageError as error:
    assert error.code=='unsupported_backend'
    assert sys.argv[1] not in str(error)
    print(json.dumps({'code':error.code,'database_effects':0,'application_imports':0}))
else:raise AssertionError('Unsupported backend was accepted')
assert 'agent_market.gateway.store' not in sys.modules
'''
    result = subprocess.run([sys.executable, '-B', '-c', code, backend], cwd=Path(__file__).resolve().parents[1],
                            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}, text=True,
                            capture_output=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ''
    assert json.loads(result.stdout) == {'code': 'unsupported_backend', 'database_effects': 0, 'application_imports': 0}


def test_explicit_sqlite_factory_returns_legacy_store_without_replacing_its_contract(monkeypatch):
    from agent_market.storage_adapter import open_store
    from agent_market.gateway.store import Store
    monkeypatch.setenv('ADMIN_BOOTSTRAP_PASSWORD', 'Synthetic-adapter-review-password-42')
    monkeypatch.setenv('DEPLOYMENT_MODE', 'test')
    store = open_store('sqlite', sqlite_path=':memory:')
    try:
        assert type(store) is Store and store._path == ':memory:'
        assert store.query('SELECT 7 AS value')[0]['value'] == 7
        assert isinstance(store._db, sqlite3.Connection)
    finally:
        store._db.close()


@pytest.mark.parametrize('path', ['', 'bad\0path', 'file::memory:?cache=shared',
                                  'postgresql://synthetic:private@db.example/catalog',
                                  'https://db.example/catalog', b'bytes.sqlite3', Path('path.sqlite3')])
def test_invalid_sqlite_factory_configuration_fails_before_any_file_or_database_access(monkeypatch, path):
    from agent_market.storage_adapter import open_store, StorageError
    def forbidden(*_args, **_kwargs):
        pytest.fail('Invalid configuration reached database/file creation')
    monkeypatch.setattr(sqlite3, 'connect', forbidden)
    monkeypatch.setattr(os, 'open', forbidden)
    with pytest.raises(StorageError) as captured:
        open_store('sqlite', sqlite_path=path)
    assert captured.value.code == 'invalid_configuration'
    assert 'private' not in str(captured.value) and 'db.example' not in str(captured.value)


def test_commit_uncertainty_survives_a_second_rollback_failure():
    from agent_market.storage_adapter import SQLiteAdapter, StorageError
    class LostAcknowledgement(sqlite3.Connection):
        armed = False
        def commit(self):
            super().commit()
            if self.armed:
                raise RuntimeError('Synthetic commit acknowledgement unavailable')
        def rollback(self):
            if self.armed:
                raise RuntimeError('Synthetic rollback unavailable')
            return super().rollback()
    db = sqlite3.connect(':memory:', factory=LostAcknowledgement)
    try:
        db.execute('CREATE TABLE sample(value INTEGER)')
        db.commit()
        adapter = SQLiteAdapter(db)
        db.armed = True
        with pytest.raises(StorageError) as captured:
            with adapter.transaction() as session:
                session.execute(statement('uncertain_commit', 'INSERT INTO sample VALUES (?)'), (1,))
        assert db.execute('SELECT COUNT(*) FROM sample').fetchone()[0] == 1
        assert captured.value.code == 'commit_unknown'
        with pytest.raises(StorageError) as unusable:
            with adapter.transaction():
                pytest.fail('An uncertain connection was reused')
        assert unusable.value.code == 'connection_unusable'
    finally:
        db.close()


def test_successful_begin_with_failed_control_cursor_close_is_rolled_back():
    from agent_market.storage_adapter import SQLiteAdapter, StorageError
    class FailedClose(sqlite3.Cursor):
        def execute(self, sql, *args, **kwargs):
            self.begin_control = sql.startswith('BEGIN')
            return super().execute(sql, *args, **kwargs)
        def close(self):
            super().close()
            if getattr(self, 'begin_control', False):
                raise RuntimeError('Synthetic begin cursor close failure')
    class FailedControlConnection(sqlite3.Connection):
        def cursor(self, *args, **kwargs):
            kwargs.setdefault('factory', FailedClose)
            return super().cursor(*args, **kwargs)
    db = sqlite3.connect(':memory:', factory=FailedControlConnection)
    try:
        adapter = SQLiteAdapter(db)
        with pytest.raises(StorageError) as captured:
            with adapter.transaction():
                pytest.fail('A failed BEGIN control yielded a session')
        assert captured.value.code == 'transaction_failed'
        assert db.in_transaction is False
        with pytest.raises(StorageError) as unusable:
            with adapter.transaction():
                pytest.fail('A connection with failed control cleanup was reused')
        assert unusable.value.code == 'connection_unusable'
    finally:
        db.close()


@pytest.mark.parametrize('phase', ['execution', 'begin', 'readonly_setup'])
def test_cursor_cleanup_failure_does_not_hide_primary_cancellation(phase):
    from agent_market.storage_adapter import SQLiteAdapter, StorageError
    class InterruptedCursor(sqlite3.Cursor):
        interrupted = False
        def execute(self, sql, *args, **kwargs):
            result = super().execute(sql, *args, **kwargs)
            if ((phase == 'execution' and sql.startswith('INSERT'))
                    or (phase == 'begin' and sql.startswith('BEGIN'))
                    or (phase == 'readonly_setup' and sql == 'PRAGMA query_only')):
                self.interrupted = True
                raise KeyboardInterrupt()
            return result
        def close(self):
            super().close()
            if self.interrupted:
                raise RuntimeError('Synthetic cursor-close failure during cancellation')
    class InterruptedConnection(sqlite3.Connection):
        def cursor(self, *args, **kwargs):
            kwargs.setdefault('factory', InterruptedCursor)
            return super().cursor(*args, **kwargs)
    db = sqlite3.connect(':memory:', factory=InterruptedConnection)
    try:
        db.execute('CREATE TABLE sample(value INTEGER)')
        db.commit()
        adapter = SQLiteAdapter(db)
        with pytest.raises(KeyboardInterrupt):
            with adapter.transaction(readonly=phase == 'readonly_setup') as session:
                session.execute(statement('cancelled_insert', 'INSERT INTO sample VALUES (?)'), (1,))
        assert db.in_transaction is False
        assert db.execute('SELECT COUNT(*) FROM sample').fetchone()[0] == 0
        with pytest.raises(StorageError) as unusable:
            with adapter.transaction():
                pytest.fail('A connection with failed cursor cleanup was reused')
        assert unusable.value.code == 'connection_unusable'
    finally:
        db.close()


def legacy_store():
    """Borrow only Store's existing methods, without catalog/bootstrap effects."""
    from agent_market.gateway.store import Store
    store = Store.__new__(Store)
    store._path = ':memory:'
    store._lock = threading.RLock()
    store._db = sqlite3.connect(':memory:', check_same_thread=False)
    store._db.row_factory = sqlite3.Row
    store._db.execute('CREATE TABLE sample(value INTEGER)')
    store._db.commit()
    return store


def test_legacy_nested_success_still_commits_before_outer_failure():
    store = legacy_store()
    try:
        with pytest.raises(RuntimeError):
            with store.tx() as outer:
                outer.execute('INSERT INTO sample VALUES (1)')
                with store.tx() as inner:
                    assert inner is outer
                    inner.execute('INSERT INTO sample VALUES (2)')
                raise RuntimeError('Synthetic outer rollback')
        assert [row['value'] for row in store.query('SELECT value FROM sample ORDER BY value')] == [1, 2]
    finally:
        store._db.close()


def test_legacy_caught_inner_failure_still_rolls_back_shared_transaction():
    store = legacy_store()
    try:
        with store.tx() as outer:
            outer.execute('INSERT INTO sample VALUES (1)')
            try:
                with store.tx() as inner:
                    inner.execute('INSERT INTO sample VALUES (2)')
                    raise RuntimeError('Synthetic inner rollback')
            except RuntimeError:
                pass
            outer.execute('INSERT INTO sample VALUES (3)')
        assert [row[0] for row in store.query('SELECT value FROM sample')] == [3]
    finally:
        store._db.close()


def test_legacy_query_mutation_remains_uncommitted_until_existing_context_commits():
    store = legacy_store()
    try:
        assert store.query('INSERT INTO sample VALUES (?)', (4,)) == []
        assert store._db.in_transaction is True
        store._db.rollback()
        assert store.query('SELECT value FROM sample') == []
    finally:
        store._db.close()
