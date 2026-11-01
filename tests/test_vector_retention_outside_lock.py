"""Expired vector jobs are found in a read snapshot and deleted by id under the writer lock (2026-11-01)."""
from contextlib import contextmanager
import time

import agent_market.application_store_vector as vector
import agent_market.legacy_vector_index as legacy
from agent_market.legacy_vector_index import ModelDescriptor


def test_claim_searches_before_its_writer_transaction_and_pauses_when_nothing_expired(monkeypatch):
    clock = [10 ** 6]
    monkeypatch.setattr(legacy, '_now', lambda: clock[0])
    item = object.__new__(vector.PostgresVectorIndex)
    events, found = [], [[], ['a', 'b']]
    in_tx = [False]

    def expired(cutoff):
        events.append(('search', in_tx[0], cutoff))
        return found.pop(0) if found else []

    def delete(ids, cutoff):
        events.append(('delete', in_tx[0], tuple(ids)))
        return len(ids)

    @contextmanager
    def tx():
        in_tx[0] = True
        try:
            yield
        finally:
            in_tx[0] = False

    class DB:
        def execute(self, sql, params=()):
            if sql.lstrip().startswith('DELETE FROM legacy_vector_jobs WHERE job_id IN'):
                events.append(('in-transaction sweep', True, None))

            class Cursor:
                rowcount = 0

                def fetchall(self):
                    return []
            return Cursor()
    item.db, item._tx, item._expired_jobs, item._delete_expired = DB(), tx, expired, delete
    item._pin, item._bootstrap = (lambda descriptor, bind=True: None), (lambda limit: None)
    monkeypatch.setattr(legacy, '_rows', lambda db, sql, params=(): [])
    model = ModelDescriptor('synthetic-embedding')
    item._retention_after = 0.0
    item.claim_batch(model, 1)
    assert events == [('search', False, clock[0] - 7 * 86400)]  # nothing expired: no delete, no in-lock scan
    clock[0] += legacy.RETENTION_PAUSE - 1
    item.claim_batch(model, 1)
    assert len(events) == 1  # paused
    clock[0] += 2
    item.claim_batch(model, 1)
    assert events[1:] == [('search', False, clock[0] - 7 * 86400), ('delete', True, ('a', 'b'))]


def test_a_pause_ending_during_the_claim_never_runs_the_in_lock_sweep(monkeypatch):
    times = iter([999.0, 1001.0, 1001.0])  # before the transaction: paused; inside it: due
    monkeypatch.setattr(legacy, '_now', lambda: next(times, 1001.0))
    item = object.__new__(vector.PostgresVectorIndex)
    swept = []

    @contextmanager
    def tx():
        yield

    class DB:
        def execute(self, sql, params=()):
            if sql.lstrip().startswith('DELETE FROM legacy_vector_jobs WHERE job_id IN'):
                swept.append(sql)

            class Cursor:
                rowcount = 0

                def fetchall(self):
                    return []
            return Cursor()
    item.db, item._tx = DB(), tx
    item._expired_jobs = lambda cutoff: swept.append('search') or []
    item._pin, item._bootstrap = (lambda descriptor, bind=True: None), (lambda limit: None)
    monkeypatch.setattr(legacy, '_rows', lambda db, sql, params=(): [])
    item._retention_after = 1000.0
    item.claim_batch(ModelDescriptor('synthetic-embedding'), 1)
    assert swept == []


def test_snapshot_search_and_rechecked_delete_on_postgresql():
    from pathlib import Path
    import pytest
    import psycopg
    from scripts.rehearse_storage_adapter_postgres import _private_cluster, PORT
    binary = Path('/opt/homebrew/opt/postgresql@18/bin')
    if not (binary / 'initdb').is_file():
        pytest.skip('PostgreSQL 18 fixture tools unavailable')
    old, recent = time.time() - 30 * 86400, time.time()
    with _private_cluster({name: str(binary / name) for name in ('initdb', 'pg_ctl')}) as cluster:
        with psycopg.connect(host=cluster['socket'], port=PORT, dbname='postgres', user='postgres', autocommit=True) as conn:
            conn.execute('CREATE TABLE legacy_vector_jobs(job_id text PRIMARY KEY,status text,finished double precision)')
            conn.execute('CREATE TABLE legacy_vector_heads(resource_id bigint PRIMARY KEY,job_id text)')
            conn.execute('CREATE TABLE legacy_vector_provenance(resource_id bigint PRIMARY KEY,job_id text)')
            for job, status, finished in (('gone1', 'indexed', old), ('gone2', 'superseded', old), ('head', 'indexed', old),
                                          ('prov', 'failed', old), ('fresh', 'indexed', recent), ('pending', 'pending', old)):
                conn.execute('INSERT INTO legacy_vector_jobs VALUES(%s,%s,%s)', (job, status, finished))
            conn.execute("INSERT INTO legacy_vector_heads VALUES(1,'head')")
            conn.execute("INSERT INTO legacy_vector_provenance VALUES(2,'prov')")

            class Store:
                def _execute(self, sql, params=(), max_rows=None):
                    return conn.execute(sql, params)
            item = object.__new__(vector.PostgresVectorIndex)
            item.store = Store()

            @contextmanager
            def snapshot():
                yield None
            item.read_snapshot = snapshot
            cutoff = time.time() - 7 * 86400
            found = item._expired_jobs(cutoff)
            assert sorted(found) == ['gone1', 'gone2']
            # A job that became a head after the snapshot is kept by the re-check.
            conn.execute("INSERT INTO legacy_vector_heads VALUES(3,'gone2')")
            assert item._delete_expired(found, cutoff) == 1
            left = {row[0] for row in conn.execute('SELECT job_id FROM legacy_vector_jobs').fetchall()}
            assert left == {'gone2', 'head', 'prov', 'fresh', 'pending'}
