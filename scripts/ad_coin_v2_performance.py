"""Disposable PostgreSQL fixed-arrival ledger benchmark; never accepts a service DSN."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import math
import os
import threading
from pathlib import Path
import time
from uuid import uuid4

import psycopg

from agent_market.ad_coin.db import take_db_calls
from agent_market.ad_coin.sql_registry import unchecked
from agent_market.ad_coin.v2.commands import Commands
from agent_market.ad_coin.v2.contracts import digest
from agent_market.ad_coin.v2.ledger import ModelLedger
from agent_market.ad_coin.v2.performance_schema import INDEXES
from agent_market.ad_coin.v2.sql import SQL
from agent_market.ad_coin.v2.store import ModelStore
from scripts.rehearse_storage_adapter_postgres import PORT, _private_cluster, _tools


@contextmanager
def isolated_libpq_environment():
    saved = {key: value for key, value in os.environ.items() if key.startswith("PG")}
    for key in saved:
        os.environ.pop(key)
    try:
        yield
    finally:
        for key in tuple(os.environ):
            if key.startswith("PG"):
                os.environ.pop(key)
        os.environ.update(saved)


def quantile(values, fraction):
    ordered = sorted(values)
    return (
        round(ordered[max(0, math.ceil(len(ordered) * fraction) - 1)], 3)
        if ordered
        else None
    )


def plan(factory, statement):
    with factory() as connection:
        connection.execute("ANALYZE adc2_journals")
        connection.execute("ANALYZE adc2_idempotency_records")
        root = connection.execute(
            "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + statement
        ).fetchone()[0][0]
    return {
        "plan": root["Plan"],
        "planning_ms": root["Planning Time"],
        "execution_ms": root["Execution Time"],
    }


def phase(store, ledger, commands, lanes, name, rate, duration, workers):
    count = int(rate * duration)
    results = []
    started = time.perf_counter() + 0.05

    def command(number, scheduled):
        principal, source, target = lanes[number % len(lanes)]
        begin = time.perf_counter()
        take_db_calls()
        try:
            fingerprint = digest(
                {"source": source, "target": target, "amount_atoms": "1"}
            )

            def action(_operation):
                posted = ledger.post(
                    "performance:" + name + ":" + str(number),
                    [(source, "-1"), (target, "1")],
                    kind="transfer",
                )
                return {"journal_id": posted.journal_id}

            commands.run(
                principal,
                "POST",
                "/benchmark/transfers",
                "performance-" + name + "-" + str(number).zfill(8),
                fingerprint,
                action,
            )
            return {
                "ok": True,
                "latency_ms": (time.perf_counter() - scheduled) * 1000,
                "service_ms": (time.perf_counter() - begin) * 1000,
                "db_calls": take_db_calls(),
            }
        except Exception as exc:
            return {"ok": False, "error_type": type(exc).__name__}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = set()
        for number in range(count):
            scheduled = started + number / rate
            delay = scheduled - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            done = {future for future in pending if future.done()}
            results.extend(f.result() for f in done)
            pending -= done
            if len(pending) >= workers * 4:
                results.append({"ok": False, "error_type": "load_shed"})
            else:
                pending.add(pool.submit(command, number, scheduled))
        results.extend(future.result(timeout=10) for future in pending)
    elapsed = max(duration, time.perf_counter() - started)
    successes = [result for result in results if result["ok"]]
    with unchecked(), store.database.read():
        committed = store.database.one(
            "SELECT count(*) AS n FROM adc2_journals WHERE economic_key LIKE ?",
            ("performance:" + name + ":%",),
        )["n"]
    assert committed == len(successes)
    return {
        "offered_commands_per_second": rate,
        "duration_seconds": duration,
        "workers": workers,
        "requested": count,
        "successful": len(successes),
        "failed": count - len(successes),
        "elapsed_seconds": round(elapsed, 4),
        "completed_commands_per_second": round(len(successes) / elapsed, 2),
        "latency_including_arrival_lag_ms": {
            key: quantile([r["latency_ms"] for r in successes], q)
            for key, q in [("p50", 0.5), ("p95", 0.95), ("p99", 0.99)]
        },
        "service_ms": {
            key: quantile([r["service_ms"] for r in successes], q)
            for key, q in [("p50", 0.5), ("p95", 0.95), ("p99", 0.99)]
        },
        "db_calls_p50": quantile([r["db_calls"] for r in successes], 0.5),
        "committed_economic_events": committed,
        "errors": sorted({r["error_type"] for r in results if not r["ok"]}),
    }


def run(*, history=6000, rate=200, duration=3, workers=8):
    if (
        not 100 <= history <= 20000
        or not 1 <= rate <= 1000
        or not 1 <= duration <= 10
        or not 1 <= workers <= 8
    ):
        raise ValueError("benchmark_limits")
    result = {}
    with isolated_libpq_environment(), _private_cluster(_tools()) as ready:

        def factory():
            return psycopg.connect(
                host=ready["socket"],
                port=PORT,
                user="postgres",
                dbname="postgres",
                autocommit=True,
                connect_timeout=2,
            )

        with factory() as connection:
            assert connection.execute(
                "SELECT current_setting('listen_addresses'),inet_server_addr()"
            ).fetchone() == ("", None)
        store = ModelStore.postgres(factory, maximum=workers)
        try:
            store.migrate_model()
            ledger, commands = ModelLedger(store), Commands(store)
            lanes = []
            for _ in range(workers):
                owner = str(uuid4())
                source = ledger.create_account(owner, "user_available")
                target = ledger.create_account(owner, "user_available")
                clearing = ledger.create_account(str(uuid4()), "external_clearing")
                ledger.post(
                    "seed:" + owner,
                    [(clearing, "-1000000"), (source, "1000000")],
                    kind="model_seed",
                )
                lanes.append((owner, source, target))
            # Seed is excluded from measurement. All history uses real balanced commands.
            seed_started = time.perf_counter()
            with store.atomic():
                for number in range(history):
                    owner, source, target = lanes[number % workers]

                    def action(_operation, number=number, source=source, target=target):
                        posted = ledger.post(
                            "history:" + str(number),
                            [(source, "-1"), (target, "1")],
                            kind="transfer",
                        )
                        return {"journal_id": posted.journal_id}

                    commands.run(
                        owner,
                        "POST",
                        "/benchmark/history",
                        "history-command-" + str(number).zfill(8),
                        digest({"n": number}),
                        action,
                    )
            seed_seconds = time.perf_counter() - seed_started
            baseline = ledger.audit()
            barrier = threading.Barrier(workers)

            def warm(_):
                with store.database.read():
                    store.one("schema_get")
                    barrier.wait(timeout=5)

            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(warm, range(workers)))
            names = [sql.split()[5] for sql in INDEXES]
            # Controlled index ablation on this owned, disposable cluster only.
            with factory() as connection:
                for name in names:
                    connection.execute(
                        psycopg.sql.SQL("DROP INDEX {}").format(
                            psycopg.sql.Identifier(name)
                        )
                    )
            result = {
                "profile": "aiac-v2-local-postgres-index-ablation",
                "date_kst": "2026-11-09",
                "history_commands": history,
                "seed_seconds_excluded": round(seed_seconds, 3),
                "mode": "model",
                "connection_pool_warmed": True,
                "transport": "private_unix_socket",
                "before_plans": {
                    key: plan(factory, SQL[key])
                    for key in ("pending_journal", "pending_idem")
                },
            }
            result["before"] = phase(
                store, ledger, commands, lanes, "before", rate, duration, workers
            )
            with store.atomic():
                for sql in INDEXES:
                    store._connection().execute(sql)
            result["after_plans"] = {
                key: plan(factory, SQL[key])
                for key in ("pending_journal", "pending_idem")
            }
            result["after"] = phase(
                store, ledger, commands, lanes, "after", rate, duration, workers
            )
            audited = ledger.audit()
            assert audited["beneficial_atoms"] == baseline["beneficial_atoms"]
            assert result["before"]["db_calls_p50"] == result["after"]["db_calls_p50"]
            result.update(
                {
                    "ledger_conservation": True,
                    "checks_disabled": False,
                    "production_access": False,
                    "global_capacity_claim": False,
                    "audit": audited,
                    "limits": "Single local process, eight lanes, warm data, no WAN/TLS/signing/AI calls; fixed arrival is not maximum capacity.",
                }
            )
        finally:
            store.close()
    result["temporary_cluster_removed"] = not Path(ready["root"]).exists()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--history", type=int, default=6000)
    parser.add_argument("--rate", type=int, default=200)
    parser.add_argument("--duration", type=int, default=3)
    args = parser.parse_args()
    result = run(history=args.history, rate=args.rate, duration=args.duration)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                name: result[name]
                for name in (
                    "before",
                    "after",
                    "ledger_conservation",
                    "temporary_cluster_removed",
                )
            }
        )
    )
    return int(result["before"]["failed"] != 0 or result["after"]["failed"] != 0)


if __name__ == "__main__":
    raise SystemExit(main())
