"""Backend selection never opens operating data or a public listener."""
from concurrent.futures import Future
import os
import sqlite3
import threading
from types import SimpleNamespace

import pytest

from agent_market.application_runtime import RuntimeStorageError, open_runtime_storage
from agent_market.application_writer_fence import install, remove, assert_sqlite_writer_allowed
from agent_market.gateway.store import Store
from agent_market.ledger import Ledger
from agent_market.workflow_worker import drain_worker


def test_selected_sqlite_ledger_shares_application_transaction_and_replay_guard(tmp_path):
    storage = open_runtime_storage(str(tmp_path/'selected.sqlite3'), values={})
    ledger = Ledger(store=storage.store)
    try:
        assert ledger._db is storage.store._db
        assert ledger.claim('0xAbCd', 'synthetic-payer', 'weather', 9)
        assert not ledger.claim('0xabcd', 'synthetic-other', 'weather', 99)
        ledger.settle('0xABCD')
        assert ledger.list_payments(service='weath')[1] == 1
        assert ledger.list_payments(status='pending')[1] == 0
        assert ledger.stats()['total_revenue'] == 9
        ledger.close()
        assert storage.store.query('SELECT COUNT(*) FROM payments')[0][0] == 1
    finally:
        storage.close()
    assert storage.closed


@pytest.mark.parametrize('values', [
    {'APPLICATION_STORE_BACKEND':'invalid'},
    {'APPLICATION_POSTGRES_DSN_FILE':'synthetic-private-path'},
    {'APPLICATION_STORE_BACKEND':'postgresql'},
])
def test_invalid_selection_fails_without_creating_a_sqlite_fallback(tmp_path, values):
    destination = tmp_path/'must-not-exist.sqlite3'
    with pytest.raises(RuntimeStorageError):
        open_runtime_storage(str(destination), values=values)
    assert not destination.exists()


def test_pg_secrets_validate_before_any_connection_and_errors_never_include_values(tmp_path):
    dsn = tmp_path/'private.dsn'; dsn.write_text('password=never-print-this-secret')
    key = tmp_path/'private.key'; key.write_bytes(b'k'*32)
    dsn.chmod(0o600); key.chmod(0o644)
    values = {'APPLICATION_STORE_BACKEND':'postgresql', 'APPLICATION_POSTGRES_DSN_FILE':str(dsn),
              'APPLICATION_WORKFLOW_KEY_FILE':str(key)}
    calls = []
    with pytest.raises(RuntimeStorageError) as error:
        open_runtime_storage(None, values=values, connector=lambda value:calls.append(value))
    assert calls == [] and 'never-print' not in str(error.value)
    key.chmod(0o600)
    def refused(_dsn):
        raise RuntimeError('password=never-print-this-secret')
    with pytest.raises(RuntimeStorageError, match='postgres_application_attach_failed') as error:
        open_runtime_storage(None, values=values, connector=refused)
    assert 'never-print' not in str(error.value)


def test_pg_key_symlink_is_refused_before_read_or_connection(tmp_path):
    dsn = tmp_path/'private.dsn'; dsn.write_text('synthetic'); dsn.chmod(0o600)
    key = tmp_path/'key'; key.write_bytes(b'k'*32); key.chmod(0o600)
    alias = tmp_path/'alias'; alias.symlink_to(key)
    with pytest.raises(RuntimeStorageError):
        open_runtime_storage(None, values={'APPLICATION_STORE_BACKEND':'postgresql',
            'APPLICATION_POSTGRES_DSN_FILE':str(dsn),'APPLICATION_WORKFLOW_KEY_FILE':str(alias)},
            connector=lambda _:pytest.fail('Invalid custody reached transport'))


def test_libpq_service_environment_cannot_redirect_explicit_runtime_configuration(monkeypatch):
    from agent_market.application_runtime import _connect
    monkeypatch.setenv('PGSERVICE','synthetic-unapproved-service')
    with pytest.raises(RuntimeStorageError,match='inherited_postgres_configuration_refused'):
        _connect('never-forward-this-private-value')


def test_sqlite_retirement_blocks_old_raw_writer_and_restarted_store_until_explicit_rollback(tmp_path):
    destination = str(tmp_path/'retired.sqlite3')
    store = Store(destination)
    try:
        with store._lock:
            store._db.execute('BEGIN IMMEDIATE')
            install(store._db, {'operation_id':'synthetic-retirement'}, b'k'*32)
            store._db.commit()
        with pytest.raises(sqlite3.OperationalError, match='application_source_writer_retired'):
            store.set_meta('forbidden','value')
        with pytest.raises(sqlite3.IntegrityError, match='application_source_writer_retired'):
            store._db.execute("INSERT INTO meta VALUES('forbidden','value')")
        store._db.rollback()
        with pytest.raises(sqlite3.OperationalError, match='application_source_writer_retired'):
            Store(destination)
        store._db.execute('BEGIN IMMEDIATE')
        remove(store._db)
        store._db.commit()
        assert_sqlite_writer_allowed(store._db)
        store.set_meta('resumed', True)
        assert store.get_meta('resumed') is True
    finally:
        store._db.close()


def test_drain_never_closes_store_while_a_worker_is_still_running():
    future = Future()
    runtime = SimpleNamespace(lock=threading.RLock(), futures={'synthetic':future})
    assert not drain_worker(runtime, timeout=0)
    future.set_exception(RuntimeError('Synthetic recorded terminal failure'))
    assert drain_worker(runtime, timeout=0)


def test_retirement_materializes_and_fences_a_missing_supported_optional_domain(tmp_path):
    destination = tmp_path/'optional-retired.sqlite3'
    db = sqlite3.connect(destination)
    stale = sqlite3.connect(destination)
    definition = 'CREATE TABLE optional_effects(id TEXT PRIMARY KEY,payload TEXT NOT NULL)'
    try:
        db.execute('BEGIN IMMEDIATE')
        install(db, {'materialized_tables':['optional_effects']}, b'k'*32,
            schema_definitions={'optional_effects':definition})
        db.commit()
        # This reproduces a stale raw schema constructor rather than a Store.tx
        # writer. Its subsequent business insert must still be rejected.
        stale.execute('CREATE TABLE IF NOT EXISTS optional_effects(id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
        with pytest.raises(sqlite3.IntegrityError,match='application_source_writer_retired'):
            stale.execute("INSERT INTO optional_effects VALUES('late','uncertain effect')")
        stale.rollback()
        assert db.execute('SELECT COUNT(*) FROM optional_effects').fetchone()[0]==0
        db.execute('BEGIN IMMEDIATE');remove(db);db.commit()
        stale.execute("INSERT INTO optional_effects VALUES('approved','after explicit rollback')")
        stale.commit()
    finally:
        stale.close();db.close()


def test_owned_storage_refuses_close_during_transaction(tmp_path):
    storage = open_runtime_storage(str(tmp_path/'busy.sqlite3'), values={})
    storage.store._db.execute('BEGIN IMMEDIATE')
    try:
        with pytest.raises(RuntimeStorageError, match='storage_workers_not_drained'):
            storage.close()
        assert not storage.closed
    finally:
        storage.store._db.rollback()
        storage.close()


def test_failed_gateway_construction_closes_only_its_owned_selected_store(monkeypatch):
    import agent_market.application_runtime as storage_module
    import agent_market.gateway.server as gateway
    calls=[]
    owned=SimpleNamespace(store=object(),close=lambda:calls.append('owned-close'))
    monkeypatch.setattr(storage_module,'open_runtime_storage',lambda _:owned)
    def failed(*_args,**_kwargs):
        raise RuntimeError('Synthetic construction failure')
    monkeypatch.setattr(gateway,'_compose_app',failed)
    with pytest.raises(RuntimeError,match='Synthetic construction failure'):
        gateway.create_app(SimpleNamespace(db_path='synthetic'))
    assert calls==['owned-close']
    with pytest.raises(RuntimeError,match='Synthetic construction failure'):
        gateway.create_app(SimpleNamespace(db_path='synthetic'),store=object())
    assert calls==['owned-close']


def test_actual_native_service_backend_and_persistent_writer_rollback():
    from scripts.rehearse_application_runtime_postgres import rehearse
    result = rehearse()
    assert len(result['checks']) >= 28 and all(result['checks'].values())
    assert result['temporary_cluster_removed']
    assert not result['provisional_catalog']
    assert result['operating_database_writes'] == result['external_provider_calls'] == 0
    assert not result['operating_cutover'] and not result['external_ha_dr_acceptance']
