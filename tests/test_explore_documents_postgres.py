"""Native PostgreSQL 18 only; disposable database and no public providers."""

from pathlib import Path
from unittest.mock import patch
import pytest
import psycopg

from agent_market import explore_documents as doc
from agent_market.storage_adapter import open_store
from scripts.rehearse_storage_adapter_postgres import _private_cluster, PORT
from tests.explore_a1_cases import listing


def test_native_documents_invalidation_current_read_and_fallback():
    binary = Path("/opt/homebrew/opt/postgresql@18/bin")
    if not (binary / "initdb").is_file():
        pytest.skip("PostgreSQL 18 fixture tools unavailable")
    with _private_cluster(
        {name: str(binary / name) for name in ("initdb", "pg_ctl")}
    ) as cluster:
        with psycopg.connect(
            host=cluster["socket"],
            port=PORT,
            dbname="postgres",
            user="postgres",
            autocommit=True,
        ) as pg:
            store = open_store(
                "postgresql", connection=pg, initialize=True, workflow_key=b"s" * 32
            )
            assert pg.info.server_version >= 180000
            assert not doc.available(store)
            doc.install(store)
            source = listing(0, large=True)
            rid = store.upsert_resource(
                {"key": "a1-native", "source": "fixture", **source}
            )
            with store.tx():
                store._execute(
                    "UPDATE resources SET active=1,health_status=%s WHERE id=%s",
                    ("healthy", rid),
                )
                for field in (
                    "usage_tools",
                    "usage_full_tools",
                    "usage_full_hash",
                    "usage_guide",
                ):
                    store._execute(
                        "UPDATE resources SET " + field + "=%s WHERE id=%s",
                        (source[field], rid),
                    )
            worker = doc.Refresher(store, interval=0)
            assert worker.run() == {"checked": 1, "written": 1, "deferred": 0}
            with store.tx(readonly=True):
                rows = doc.read(store, [rid])
            assert rows[rid]["id"] == rid and doc.tools_for_search(rows[rid])
            from agent_market.concierge.execution_policy import tools_for

            assert tools_for(rows[rid]) == []
            assert "_explore_document" not in store.resource(rid)

            with store.tx():
                store._execute(
                    "UPDATE resources SET description=%s WHERE id=%s",
                    ("Global weather forecast. \u00e9\U0001f30e", rid),
                )
            with store.tx(readonly=True):
                assert not doc.read(store, [rid])
                assert (
                    store._execute(
                        "SELECT count(*) FROM agentcon_search.explore_document_queue"
                    ).fetchone()[0]
                    == 0
                )
            assert worker.run()["written"] == 1
            with store.tx(readonly=True):
                assert doc.read(store, [rid])
                sql_digest = store._execute(
                    "SELECT " + doc.SOURCE_SQL + " FROM resources r WHERE r.id=%s",
                    (rid,),
                ).fetchone()[0]
            assert sql_digest == doc.source_digest(store.resource(rid))

            with store.tx():
                store._execute("UPDATE resources SET active=0 WHERE id=%s", (rid,))
            with store.tx(readonly=True):
                assert not doc.read(store, [rid])
            with store.tx():
                store._execute(
                    "UPDATE resources SET active=1,eval_security='review' WHERE id=%s",
                    (rid,),
                )
            with store.tx(readonly=True):
                assert not doc.read(store, [rid])
            with store.tx():
                store._execute(
                    "UPDATE resources SET eval_security='ok' WHERE id=%s", (rid,)
                )
            with patch.object(doc, "policy_hash", return_value="0" * 64), store.tx(
                readonly=True
            ):
                assert not doc.read(store, [rid])

            # A corrupt projection cannot replace a full source read.
            with store.tx():
                store._execute(
                    "UPDATE agentcon_search.explore_documents SET document='{}' WHERE resource_id=%s",
                    (rid,),
                )
            with store.tx(readonly=True):
                assert not doc.read(store, [rid])
            with store.tx():
                store._execute(
                    "INSERT INTO agentcon_search.explore_document_queue VALUES(%s,%s,0) ON CONFLICT(resource_id) DO UPDATE SET queued_at=excluded.queued_at",
                    (rid, 0),
                )
            assert worker.run()["written"] == 1

            # Mutation between build and publish leaves the newer source queued.
            original = doc.build

            def mutate(row):
                value = original(row)
                with store.tx():
                    store._execute(
                        "UPDATE resources SET name=%s WHERE id=%s",
                        ("Updated weather name", rid),
                    )
                return value

            with store.tx():
                store._execute(
                    "UPDATE resources SET name=%s WHERE id=%s", ("Before race", rid)
                )
            with patch.object(doc, "build", side_effect=mutate):
                assert worker.run()["written"] == 0
            with store.tx(readonly=True):
                assert not doc.read(store, [rid])
            assert worker.run()["written"] == 1
            assert worker.run() == {"checked": 0, "written": 0, "deferred": 0}
            store.close()


def test_visible_listings_load_first_and_unreadable_rows_never_stall_the_queue():
    binary = Path("/opt/homebrew/opt/postgresql@18/bin")
    if not (binary / "initdb").is_file():
        pytest.skip("PostgreSQL 18 fixture tools unavailable")
    with _private_cluster({name: str(binary / name) for name in ("initdb", "pg_ctl")}) as cluster:
        with psycopg.connect(host=cluster["socket"], port=PORT, dbname="postgres", user="postgres", autocommit=True) as pg:
            store = open_store("postgresql", connection=pg, initialize=True, workflow_key=b"s" * 32)
            ids = [store.upsert_resource({"key": "a1-order-%d" % n, "source": "fixture", **listing(n)}) for n in range(4)]
            with store.tx():
                store._execute("UPDATE resources SET active=0,health_status='down'")
                store._execute("UPDATE resources SET active=1,health_status='healthy' WHERE id=%s", (ids[3],))
            doc.install(store)
            # The visible listing is queued last but is written first.
            worker = doc.Refresher(store, batch=1, interval=0)
            assert worker.run()["written"] == 1
            with store.tx(readonly=True):
                assert set(doc.read(store, ids)) == {ids[3]}
            # A row the bounded read cannot return is deferred, not retried at the front.
            worker = doc.Refresher(store, batch=10, interval=0)
            import agent_market.application_store_resource_batches as batches
            original = batches.resources
            batches.resources = lambda s, chosen, *a, **k: [r for r in original(s, chosen, *a, **k) if r["id"] != ids[0]]
            try:
                result = worker.run()
            finally:
                batches.resources = original
            assert result["deferred"] == 1 and result["written"] == 2
            with store.tx(readonly=True):
                due, tries = store._execute(
                    "SELECT queued_at,attempts FROM agentcon_search.explore_document_queue WHERE resource_id=%s", (ids[0],)).fetchone()
            assert tries == 1 and due > __import__("time").time() + 60
            from agent_market.explore_document_refresher import load_status
            status = load_status(store)
            assert status["installed"] and status["retrying"] == 1 and status["parked"] == 0
            assert status["documents"] == status["current_policy_documents"] == 3 and status["queued"] == 1


def test_generation_bound_reader_matches_and_never_serves_changed_sources():
    binary = Path("/opt/homebrew/opt/postgresql@18/bin")
    if not (binary / "initdb").is_file():
        pytest.skip("PostgreSQL 18 fixture tools unavailable")
    from agent_market import explore_document_reader as reader
    with _private_cluster({name: str(binary / name) for name in ("initdb", "pg_ctl")}) as cluster:
        with psycopg.connect(host=cluster["socket"], port=PORT, dbname="postgres", user="postgres", autocommit=True) as pg:
            store = open_store("postgresql", connection=pg, initialize=True, workflow_key=b"s" * 32)
            doc.install(store)
            source = listing(0, large=True)
            rid = store.upsert_resource({"key": "a1-reader", "source": "fixture", **source})
            with store.tx():
                store._execute("UPDATE resources SET active=1,health_status='healthy' WHERE id=%s", (rid,))
                for field in ("usage_tools", "usage_full_tools", "usage_full_hash", "usage_guide"):
                    store._execute("UPDATE resources SET " + field + "=%s WHERE id=%s", (source[field], rid))
            worker = doc.Refresher(store, interval=0)
            assert worker.run()["written"] == 1

            def both():
                with store.tx(readonly=True):
                    return doc.read(store, [rid]), reader.read(store, [rid])

            old, new = both()
            assert set(old) == set(new) == {rid}
            assert doc.tools_for_search(new[rid]) == doc.tools_for_search(old[rid])
            assert new[rid]["_capability_text"] == old[rid]["_capability_text"]
            assert doc.is_search_row(new[rid])
            # A source change is never served, and a rebuild restores the document.
            with store.tx():
                store._execute("UPDATE resources SET description=%s WHERE id=%s", ("Changed forecast text.", rid))
            assert both() == ({}, {})
            assert worker.run()["written"] == 1
            assert set(both()[1]) == {rid}
            # Any observed change bumps the generation: the reader falls back until jobs rebuilds.
            with store.tx():
                store._execute("UPDATE resources SET health_status='reachable' WHERE id=%s", (rid,))
            assert not both()[1]
            assert worker.run()["written"] == 1
            assert set(both()[1]) == {rid}
            # Corrupt documents, another policy and hidden listings are never read.
            with patch.object(doc, "policy_hash", return_value="0" * 64):
                assert not both()[1]
            with store.tx():
                store._execute("UPDATE agentcon_search.explore_documents SET document=document||' ' WHERE resource_id=%s", (rid,))
            assert not both()[1]
            with store.tx():
                store._execute("INSERT INTO agentcon_search.explore_document_queue VALUES(%s,0,0) ON CONFLICT(resource_id) DO UPDATE SET queued_at=0", (rid,))
            assert worker.run()["written"] == 1
            with store.tx():
                store._execute("UPDATE resources SET eval_security='quarantine' WHERE id=%s", (rid,))
            assert not both()[1]
            store.close()
