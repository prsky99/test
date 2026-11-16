"""운영·SRE via PM 11-17 01:0x: Explore document writes go in short transactions, never one over a second.

During the 11-16 policy rebuild one 100-document publication transaction held the global writer lock
(store.tx's pg_advisory_xact_lock) past the 1 s lock_timeout of other writers.
"""

import contextlib
import time
from pathlib import Path

import psycopg
import pytest

from agent_market import explore_documents as doc
from agent_market.explore_document_refresher import Refresher


class _Store:
    def __init__(self):
        self.transactions = 0

    @contextlib.contextmanager
    def tx(self, readonly=False):
        self.transactions += 1
        yield


def test_writes_go_in_chunks_and_a_slow_transaction_halves_the_next(monkeypatch):
    monkeypatch.setattr(Refresher, "WRITE_PAUSE", 0)
    store = _Store()
    worker = Refresher(store)
    parts = []
    worker._write(list(range(45)), parts.append)
    assert [len(p) for p in parts] == [20, 20, 5] and store.transactions == 3
    assert sum(parts, []) == list(range(45)) and worker.write_chunk == 20

    monkeypatch.setattr(Refresher, "WRITE_SLOW", 0.01)
    parts = []

    def slow(part):
        parts.append(part)
        if len(parts) == 1:
            time.sleep(0.03)

    worker._write(list(range(30)), slow)
    assert [len(p) for p in parts] == [20, 10] and worker.write_chunk == 10
    assert worker.longest_write >= 0.03
    worker._write(list(range(5)), lambda part: None)
    assert worker.write_chunk == 20  # a fast round lets the size recover
    worker._write([], lambda part: pytest.fail("no transaction for nothing"))


def test_on_postgres_no_write_transaction_reaches_a_second():
    binary = Path("/opt/homebrew/opt/postgresql@18/bin")
    if not (binary / "initdb").is_file():
        pytest.skip("PostgreSQL 18 fixture tools unavailable")
    from agent_market.storage_adapter import open_store
    from scripts.rehearse_storage_adapter_postgres import _private_cluster, PORT
    from tests.explore_a1_cases import listing

    with _private_cluster({name: str(binary / name) for name in ("initdb", "pg_ctl")}) as cluster:
        with psycopg.connect(host=cluster["socket"], port=PORT, dbname="postgres", user="postgres", autocommit=True) as pg:
            store = open_store("postgresql", connection=pg, initialize=True, workflow_key=b"s" * 32)
            doc.install(store)
            from tests.explore_a1_cases import TASKS

            ids = [
                store.upsert_resource(
                    {"key": "chunk-%d" % n, "source": "fixture",
                     **dict(listing(n % len(TASKS)), url="https://chunk-%d.example/mcp" % n)}
                )
                for n in range(60)
            ]
            with store.tx():
                store._execute("UPDATE resources SET active=1,health_status='healthy'")
            tx, spans = store.tx, []

            @contextlib.contextmanager
            def timed(*args, **kwargs):
                started = time.monotonic()
                with tx(*args, **kwargs) as inner:
                    yield inner
                if not kwargs.get("readonly"):
                    spans.append(time.monotonic() - started)

            store.tx = timed
            worker = Refresher(store, batch=60, interval=0)
            assert worker.run()["written"] == 60
            store.tx = tx
            # queue insert (60 → 3) and publication (60 → 3): six short write transactions, none near a second
            assert len(spans) >= 6 and max(spans) < 1.0 and worker.longest_write < 1.0
            with store.tx(readonly=True):
                assert len(doc.read(store, ids)) == 60
            store.close()
