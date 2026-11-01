"""A busy catalog writer lock is reported apart from other failures and retried by visitor writes (2026-11-01)."""
from contextlib import contextmanager

import pytest

from agent_market.application_store_postgres import ApplicationStoreError, WriterBusy
from agent_market.concierge import memory


class Store:
    def __init__(self, failures, error=WriterBusy):
        self.failures, self.error, self.calls, self.bodies = failures, error, 0, 0

    @contextmanager
    def tx(self):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error()
        yield self
        self.bodies += 1


def test_a_busy_lock_is_requested_again_and_the_body_runs_once(monkeypatch):
    pauses = []
    monkeypatch.setattr(memory.time, 'sleep', pauses.append)
    store = Store(2)
    with memory._write(store) as db:
        assert db is store
    assert store.calls == 3 and store.bodies == 1 and pauses == list(memory.WRITER_RETRY_PAUSES)


def test_three_busy_locks_or_other_errors_are_raised(monkeypatch):
    monkeypatch.setattr(memory.time, 'sleep', lambda seconds: None)
    with pytest.raises(WriterBusy):
        with memory._write(Store(3)):
            pass
    other = Store(1, lambda: ApplicationStoreError('statement_failed'))
    with pytest.raises(ApplicationStoreError):
        with memory._write(other):
            pass
    assert other.calls == 1  # a failure that may have written something is never retried


def test_an_error_inside_the_body_is_not_retried():
    store = Store(0)
    with pytest.raises(RuntimeError):
        with memory._write(store):
            raise RuntimeError('body')
    assert store.calls == 1


def test_postgresql_reports_the_held_writer_lock_as_writer_busy():
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
            holder.execute('SELECT pg_advisory_xact_lock(%s)', (WRITER_LOCK,))
            with pytest.raises(WriterBusy):
                with store.tx():
                    pass
            # Released during the retry pauses: the visitor write then succeeds.
            threading.Timer(0.5, holder.rollback).start()
            book = memory.VisitorBook(store)
            started = time.monotonic()
            visitor = book.create('rest', 'pytest', 'fp-writer-busy')
            assert visitor.id and time.monotonic() - started < 4
