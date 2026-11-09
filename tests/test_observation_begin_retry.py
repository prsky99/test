"""A busy writer lock at BEGIN is tried once more, and a rollback after a failed BEGIN does not
hide the error (2026-11-10 05:24, jobs health check: statement_failed then session_required)."""
import pytest

from agent_market import application_store_postgres as aspg
from agent_market.application_store_postgres import ApplicationStoreError, WriterBusy, _LegacyConnection


class Store:
    def __init__(self, busy=0, error=WriterBusy):
        self.busy, self.error, self.begins, self.finished = busy, error, 0, []
        self._direct, self._depth = False, 0

    def _begin_direct(self):
        self.begins += 1
        if self.begins <= self.busy:
            raise self.error()
        self._direct, self._depth = True, 1

    def _finish_direct(self, commit):
        if not self._direct:
            raise ApplicationStoreError('session_required')
        self.finished.append(commit)
        self._direct, self._depth = False, 0


def test_one_busy_writer_lock_is_requested_again(monkeypatch):
    pauses = []
    monkeypatch.setattr(aspg.time, 'sleep', pauses.append)
    store = Store(busy=1)
    _LegacyConnection(store).execute('BEGIN IMMEDIATE')
    assert store.begins == 2 and store._direct and pauses == [aspg.WRITER_RETRY_SECONDS]


def test_a_second_busy_lock_or_another_error_is_raised(monkeypatch):
    monkeypatch.setattr(aspg.time, 'sleep', lambda seconds: None)
    store = Store(busy=2)
    with pytest.raises(WriterBusy):
        _LegacyConnection(store).execute('BEGIN IMMEDIATE')
    assert store.begins == 2
    other = Store(busy=1, error=lambda: ApplicationStoreError('connection_busy'))
    with pytest.raises(ApplicationStoreError) as raised:
        _LegacyConnection(other).execute('BEGIN IMMEDIATE')
    assert raised.value.code == 'connection_busy' and other.begins == 1


def test_rollback_after_a_failed_begin_keeps_the_original_error(monkeypatch):
    monkeypatch.setattr(aspg.time, 'sleep', lambda seconds: None)
    store = Store(busy=2)
    db = _LegacyConnection(store)
    with pytest.raises(WriterBusy):
        try:
            db.execute('BEGIN IMMEDIATE')
        except BaseException:
            db.rollback()  # what Store.observation_guard does
            raise
    assert store.finished == []


def test_rollback_inside_a_session_still_ends_it():
    store = Store()
    db = _LegacyConnection(store)
    db.execute('BEGIN IMMEDIATE')
    db.rollback()
    assert store.finished == [False] and not store._direct


def test_postgresql_tx_waits_once_more_for_a_briefly_held_writer_lock():
    from pathlib import Path
    import threading
    import time
    import psycopg
    from scripts.rehearse_storage_adapter_postgres import _private_cluster, PORT
    from agent_market.storage_adapter import open_store
    from agent_market.application_store_postgres import WRITER_LOCK
    binary = Path('/opt/homebrew/opt/postgresql@18/bin')
    if not (binary / 'initdb').is_file():
        pytest.skip('PostgreSQL 18 fixture tools unavailable')
    with _private_cluster({name: str(binary / name) for name in ('initdb', 'pg_ctl')}) as cluster:
        with psycopg.connect(host=cluster['socket'], port=PORT, dbname='postgres', user='postgres', autocommit=True) as conn, \
                psycopg.connect(host=cluster['socket'], port=PORT, dbname='postgres', user='postgres') as holder:
            store = open_store('postgresql', connection=conn, initialize=True, workflow_key=b'a' * 32)
            # Held for longer than one lock_timeout, released before the second try ends.
            holder.execute('SELECT pg_advisory_xact_lock(%s)', (WRITER_LOCK,))
            threading.Timer(1.5, holder.rollback).start()
            started, ran = time.monotonic(), []
            with store.tx():
                ran.append(1)
            assert ran == [1] and 1.0 < time.monotonic() - started < 3.0
            # Held throughout: both tries time out and the caller still sees WriterBusy.
            holder.execute('SELECT pg_advisory_xact_lock(%s)', (WRITER_LOCK,))
            with pytest.raises(WriterBusy):
                with store.tx():
                    ran.append(2)
            assert ran == [1]
            holder.rollback()
            with store.tx():
                pass  # the session is usable again


def test_an_unexpected_edge_failure_logs_its_class_and_store_code(caplog):
    import asyncio
    from agent_market.edge_gateway.router import errors

    @errors
    async def output_observation():
        raise WriterBusy()
    with caplog.at_level('WARNING'):
        response = asyncio.run(output_observation())
    assert response.status_code == 503
    assert 'output_observation unavailable: WriterBusy statement_failed' in caplog.text
