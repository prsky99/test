"""Explicit read-only source capture and disposable PostgreSQL A0/A1 comparison.

No raw corpus file is written. Production connections are read-only. Both paths
use identical fixed candidate IDs/ranks; this measures the post-retrieval stage,
not complete HTTP or embedding latency. Run explicitly with --run.
"""

import argparse
import json
import time
import statistics
from pathlib import Path
from unittest.mock import patch
import psycopg
from psycopg import sql
from scripts.rehearse_storage_adapter_postgres import _private_cluster, PORT
from scripts.agentcon_config import read_settings
from agent_market.application_runtime import _connect, _private_bytes
from agent_market.storage_adapter import open_store
from agent_market.gateway.rag import RagEngine
from agent_market.concierge.discovery import candidates
from agent_market.concierge.hybrid_explore import scoped_explore
from agent_market.concierge import discovery_contracts
from agent_market.admin_postgres_pool import AdminReaderPool
from agent_market import explore_documents, search_quality


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", required=True)
    parser.parse_args()
    out = Path("reports/explore-postgres-a1-2026-10-30")
    settings = read_settings("gateway-data/agentcon.env")
    live = _connect(
        _private_bytes(settings["APPLICATION_POSTGRES_DSN_FILE"], 16384)
        .decode()
        .strip()
    )
    live.execute("SET default_transaction_read_only=on")
    live.execute("SET statement_timeout='15s'")
    source = open_store(
        "postgresql",
        connection=live,
        workflow_key=_private_bytes(settings["APPLICATION_WORKFLOW_KEY_FILE"], 32),
    )
    engine = RagEngine(
        ollama_url=settings.get("EMBEDDING_OLLAMA_URL")
        or settings.get("OLLAMA_URL")
        or "http://127.0.0.1:11434"
    )
    queries = ("weather forecast seoul", "translate", "github issues")
    rankings = {}
    ids = set()
    samples = []
    measurements = []

    class Recorder:
        def record(self, surface, status, elapsed, measured, repairs=0):
            measurements.append(
                {
                    "elapsed_ms": round(elapsed, 2),
                    "stages_ms": {
                        k: round(v, 2) for k, v in measured["stages_ms"].items()
                    },
                    "counts": measured["counts"],
                }
            )

    search_quality.recorder = lambda s: Recorder()
    try:
        for q in queries:
            for kind in ("a2a", "mcp"):
                ranking = candidates(
                    source, engine, q, kind=kind, maximum=600, ranking_only=True
                )
                rankings[(q, kind)] = ranking
                ids.update(r["id"] for r in ranking)
        print(json.dumps({"snapshot_candidates": len(ids)}), flush=True)
        binary = Path("/opt/homebrew/opt/postgresql@18/bin")
        with _private_cluster(
            {name: str(binary / name) for name in ("initdb", "pg_ctl")}
        ) as cluster:

            def connect():
                return psycopg.connect(
                    host=cluster["socket"],
                    port=PORT,
                    dbname="postgres",
                    user="postgres",
                    autocommit=True,
                )

            pg = connect()
            target = open_store(
                "postgresql", connection=pg, initialize=True, workflow_key=b"t" * 32
            )
            copied = {}
            ids = sorted(ids)

            # Copy selected source rows straight into the disposable database; no raw corpus file/log.
            def copy_table(table, predicate, values):
                n = 0
                with source.tx(readonly=True), live.cursor() as reader:
                    reader.execute(
                        sql.SQL("SELECT * FROM {} WHERE " + predicate).format(
                            sql.Identifier(table)
                        ),
                        (values,),
                    )
                    columns = [c.name for c in reader.description]
                    insert = sql.SQL(
                        "INSERT INTO {}({}) VALUES({}) ON CONFLICT DO NOTHING"
                    ).format(
                        sql.Identifier(table),
                        sql.SQL(",").join(map(sql.Identifier, columns)),
                        sql.SQL(",").join(sql.Placeholder() for _ in columns),
                    )
                    with pg.transaction(), pg.cursor() as writer:
                        while True:
                            rows = reader.fetchmany(25)
                            if not rows:
                                break
                            writer.executemany(insert, rows)
                            n += len(rows)
                copied[table] = n

            copy_table("resources", "id=ANY(%s::bigint[])", ids)
            for table in (
                "connection_agents",
                "connection_versions",
                "capability_eligibility",
            ):
                copy_table(table, "resource_id=ANY(%s::bigint[])", ids)
            with pg.cursor() as c:
                c.execute("SELECT id FROM connection_versions")
                versions = [r[0] for r in c.fetchall()]
            for table in ("capability_evidence", "capability_approvals"):
                copy_table(table, "version_id=ANY(%s::text[])", versions)
            from agent_market.postgres_capability_text import (
                install as install_capability_text,
            )

            install_capability_text(target)
            explore_documents.install(target)
            worker = explore_documents.Refresher(target, batch=50, interval=0)
            rounds = 0
            while True:
                row = worker.run()
                rounds += 1
                if row["checked"] == 0:
                    break
                assert rounds < 100, "Document build did not converge"
            print(json.dumps({"copied": copied, "build_rounds": rounds}), flush=True)

            def factory():
                c = connect()
                return open_store("postgresql", connection=c, workflow_key=b"t" * 32), c

            pool = AdminReaderPool(factory, maximum=3)
            target._admin_read_pool = pool

            def fixed(store, e, q, **kw):
                return rankings[(q, kw["kind"])]

            read = explore_documents.read
            try:
                with patch(
                    "agent_market.concierge.hybrid_explore.candidates",
                    side_effect=fixed,
                ):
                    for mode in ("A0", "A1", "A1", "A0", "A0", "A1"):
                        for q in queries:
                            discovery_contracts._facts = discovery_contracts.FactCache()
                            discovery_contracts._tasks = discovery_contracts.TaskFacts()
                            measurements.clear()
                            with patch.object(
                                explore_documents,
                                "read",
                                read if mode == "A1" else lambda *_: {},
                            ):
                                began = time.perf_counter()
                                result = scoped_explore(
                                    target, None, q, None, None, False, False, 46
                                )
                                elapsed = (time.perf_counter() - began) * 1000
                            item = {
                                "mode": mode,
                                "query": q,
                                "ms": round(elapsed, 2),
                                "ids": [r["id"] for r in result["items"]],
                                "measurements": list(measurements),
                            }
                            samples.append(item)
                            print(
                                json.dumps(
                                    {
                                        "mode": mode,
                                        "query": q,
                                        "ms": item["ms"],
                                        "count": len(item["ids"]),
                                    }
                                ),
                                flush=True,
                            )
                            value = {
                                "scope": "Disposable native PostgreSQL18; read-only selected live catalog copied privately; identical frozen candidate IDs/ranks; cold contract caches; post-retrieval path only, embedding/ANN/candidate retrieval excluded",
                                "resource_count": len(ids),
                                "copied": copied,
                                "samples": samples,
                                "production_writes": 0,
                                "corpus_files_written": False,
                                "historical_reports_copied": False,
                            }
                            (out / "snapshot-benchmark.json").write_text(
                                json.dumps(value, indent=2) + "\n"
                            )
            finally:
                pool.close()
                target.close()
                pg.close()
    finally:
        source.close()
        live.close()
        engine.http.close()
    for q in queries:
        cases = [r for r in samples if r["query"] == q]
        assert all(r["ids"] == cases[0]["ids"] for r in cases), q
    print(
        json.dumps(
            {
                "ordered_results_equal": True,
                "median_ms": {
                    mode: statistics.median(
                        r["ms"] for r in samples if r["mode"] == mode
                    )
                    for mode in ("A0", "A1")
                },
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
