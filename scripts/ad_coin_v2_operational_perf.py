"""Comprehensive operational load and performance benchmark under realistic production conditions.

Evaluates end-to-end HTTP pipeline, session authentication, cryptographic JWS receipt signing,
agent payment escrow holds and settlements, and multi-region load concurrency against a disposable
isolated PostgreSQL instance. Verifies zero-sum ledger conservation upon completion.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import threading
import time
from uuid import uuid4

from fastapi import FastAPI
import psycopg
from starlette.testclient import TestClient

from agent_market.ad_coin.v2.access import HUMAN_CAPABILITIES, Kind
from agent_market.ad_coin.v2.key_vault import KeyVault
from agent_market.ad_coin.v2.live_service import (
    DEFAULT_LANGUAGES,
    DEFAULT_REGIONS,
    DEFAULT_TAXONOMY,
    build_live_service,
    create_live_ad_coin_v2_router,
)
from agent_market.ad_coin.v2.reconcile import LedgerReconciler
from agent_market.ad_coin.v2.store import ModelStore
from scripts.rehearse_storage_adapter_postgres import PORT, _private_cluster, _tools

REGIONS = ("US", "KR", "JP", "GB", "DE")
SIMULATED_REGION_LATENCY_MS = {
    "KR": 2.0,
    "JP": 15.0,
    "US": 60.0,
    "GB": 80.0,
    "DE": 85.0,
}


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


def quantile(values: list[float], fraction: float) -> float | None:
    ordered = sorted(values)
    return (
        round(ordered[max(0, math.ceil(len(ordered) * fraction) - 1)], 3)
        if ordered
        else None
    )


def run_benchmark(
    *,
    workers: int = 8,
    total_operations: int = 400,
    preseed_history: int = 1000,
) -> dict:
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

        store = ModelStore.postgres(factory, maximum=workers + 4)
        try:
            store.migrate_model()

            vault = KeyVault()
            now_ms = 1_800_000_000_000
            clock = lambda: now_ms  # noqa: E731

            router = create_live_ad_coin_v2_router(
                store,
                key_vault=vault,
                taxonomy=DEFAULT_TAXONOMY,
                regions=DEFAULT_REGIONS,
                languages=DEFAULT_LANGUAGES,
                clock_ms=clock,
                include_workspace=True,
            )
            app = FastAPI()
            app.include_router(router)
            client = TestClient(app)

            commercial, resolver, _ = build_live_service(
                store,
                key_vault=vault,
                taxonomy=DEFAULT_TAXONOMY,
                regions=DEFAULT_REGIONS,
                languages=DEFAULT_LANGUAGES,
                clock_ms=clock,
            )

            # Preseed realistic history
            clearing_id = commercial.ledger.create_account(str(uuid4()), "external_clearing")
            lanes = []
            for _ in range(workers):
                owner = str(uuid4())
                source = commercial.ledger.create_account(owner, "user_available")
                target = commercial.ledger.create_account(owner, "user_available")
                commercial.ledger.post(
                    f"seed:{owner}",
                    [(clearing_id, "-10000000"), (source, "10000000")],
                    kind="model_seed",
                )
                lanes.append((owner, source, target))

            seed_start = time.perf_counter()
            with store.atomic():
                for i in range(preseed_history):
                    owner, s, t = lanes[i % workers]
                    commercial.ledger.post(
                        f"preseed:{i}",
                        [(s, "-10"), (t, "10")],
                        kind="transfer",
                    )
            preseed_duration = time.perf_counter() - seed_start

            # Prepare client accounts, sessions, and mandates for operational load
            user_fixtures = []
            expires_at = (now_ms // 1000) + 86400
            num_fixtures = max(workers * 4, 32)

            for i in range(num_fixtures):
                user_owner = str(uuid4())
                user_principal = str(uuid4())
                agent_principal = str(uuid4())
                provider_id = str(uuid4())
                binding_id = str(uuid4())
                token = f"sess_{uuid4().hex}"
                csrf = f"csrf_{uuid4().hex}"

                commercial.access.provision_principal(
                    user_principal, Kind.HUMAN, owner_id=user_owner, capabilities=HUMAN_CAPABILITIES
                )
                commercial.access.provision_agent_binding(
                    binding_id,
                    user_owner,
                    agent_principal,
                    str(uuid4()),
                    capabilities=HUMAN_CAPABILITIES,
                )
                commercial.access.provision_wallet(user_owner)

                user_acc = store.one("account_by_owner_purpose", (user_owner, "user_available"))
                commercial.ledger.post(
                    f"fund:{user_owner}",
                    [(clearing_id, "-5000000"), (user_acc["id"], "5000000")],
                    kind="model_seed",
                )

                resolver.register_human_session(
                    token, csrf, principal_id=user_principal, owner_id=user_owner, epoch=1, expires_at=expires_at
                )

                headers = {
                    "Cookie": f"__Host-ac_customer_session={token}",
                    "X-CSRF-Token": csrf,
                    "X-AIAC-Contract": "v6.2",
                }

                # Create initial mandate
                resp = client.post(
                    "/api/ad-coin/v2/agent-payments/mandates",
                    headers=headers,
                    json={
                        "agent_principal_id": agent_principal,
                        "total_atoms": 500000,
                        "per_task_atoms": 50000,
                        "providers": [provider_id],
                    },
                )
                assert resp.status_code == 201, resp.text
                mandate_id = resp.json()["id"]

                user_fixtures.append({
                    "owner": user_owner,
                    "principal": user_principal,
                    "agent": agent_principal,
                    "provider": provider_id,
                    "headers": headers,
                    "mandate_id": mandate_id,
                    "region": REGIONS[i % len(REGIONS)],
                })

            initial_audit = commercial.ledger.audit()
            assert int(initial_audit["beneficial_atoms"]) + int(initial_audit["clearing_atoms"]) == 0

            # Execute concurrent operational requests
            metrics_lock = threading.Lock()
            op_latencies: dict[str, list[float]] = {
                "mandate_list": [],
                "execution_hold": [],
                "execution_settle": [],
                "execution_refund": [],
                "workspace_session": [],
            }
            regional_latencies: dict[str, list[float]] = {r: [] for r in REGIONS}
            errors: list[str] = []

            def worker_task(index: int):
                fixture = user_fixtures[index % len(user_fixtures)]
                region = REGIONS[index % len(REGIONS)]
                headers = {**fixture["headers"], "CF-IPCountry": region}
                simulated_net_delay = SIMULATED_REGION_LATENCY_MS[region] / 1000.0

                action_type = index % 5
                start = time.perf_counter()
                try:
                    if simulated_net_delay > 0:
                        time.sleep(simulated_net_delay)

                    if action_type == 0:
                        # 1. Workspace Session BFF
                        r = client.get("/ad-coin/v2/ui/session", headers=headers)
                        if r.status_code != 200:
                            raise RuntimeError(f"session_failed: {r.status_code}")
                        key = "workspace_session"

                    elif action_type == 1:
                        # 2. List Mandates
                        r = client.get("/api/ad-coin/v2/agent-payments/mandates", headers=headers)
                        if r.status_code != 200:
                            raise RuntimeError(f"list_mandates_failed: {r.status_code}")
                        key = "mandate_list"

                    elif action_type in (2, 3):
                        # 3. Execution Hold -> Settle
                        t_hold_start = time.perf_counter()
                        hold_resp = client.post(
                            "/api/ad-coin/v2/agent-payments/executions/hold",
                            headers={**headers, "Idempotency-Key": str(uuid4())},
                            json={
                                "provider_id": fixture["provider"],
                                "task_ref": f"task:perf:{index}",
                                "price_atoms": 1000,
                                "mandate_id": fixture["mandate_id"],
                            },
                        )
                        t_hold_elapsed = (time.perf_counter() - t_hold_start) * 1000.0
                        if hold_resp.status_code != 202:
                            raise RuntimeError(f"hold_failed: {hold_resp.status_code} {hold_resp.text}")
                        exec_id = hold_resp.json()["id"]

                        with metrics_lock:
                            op_latencies["execution_hold"].append(t_hold_elapsed)

                        settle_resp = client.post(
                            f"/api/ad-coin/v2/agent-payments/executions/{exec_id}/settle",
                            headers=headers,
                            json={
                                "ok": True,
                                "result_digest": "sha256:" + "a" * 64,
                            },
                        )
                        if settle_resp.status_code != 200:
                            raise RuntimeError(f"settle_failed: {settle_resp.status_code} {settle_resp.text}")
                        key = "execution_settle"

                    else:
                        # 4. Execution Hold -> Refund
                        t_hold_start = time.perf_counter()
                        hold_resp = client.post(
                            "/api/ad-coin/v2/agent-payments/executions/hold",
                            headers={**headers, "Idempotency-Key": str(uuid4())},
                            json={
                                "provider_id": fixture["provider"],
                                "task_ref": f"task:perf-refund:{index}",
                                "price_atoms": 500,
                                "mandate_id": fixture["mandate_id"],
                            },
                        )
                        t_hold_elapsed = (time.perf_counter() - t_hold_start) * 1000.0
                        if hold_resp.status_code != 202:
                            raise RuntimeError(f"hold_refund_failed: {hold_resp.status_code}")
                        exec_id = hold_resp.json()["id"]

                        with metrics_lock:
                            op_latencies["execution_hold"].append(t_hold_elapsed)

                        refund_resp = client.post(
                            f"/api/ad-coin/v2/agent-payments/executions/{exec_id}/settle",
                            headers=headers,
                            json={"ok": False},
                        )
                        if refund_resp.status_code != 200:
                            raise RuntimeError(f"refund_failed: {refund_resp.status_code}")
                        key = "execution_refund"

                    elapsed_ms = (time.perf_counter() - start) * 1000.0
                    with metrics_lock:
                        op_latencies[key].append(elapsed_ms)
                        regional_latencies[region].append(elapsed_ms)

                except Exception as ex:
                    with metrics_lock:
                        errors.append(str(ex))

            bench_start = time.perf_counter()
            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(worker_task, range(total_operations)))
            total_duration = time.perf_counter() - bench_start

            # Post-load verification: double-entry ledger reconciliation
            reconciler = LedgerReconciler(store)
            rec_report = reconciler.run_full_reconciliation()
            final_audit = commercial.ledger.audit()

            assert rec_report.status == "clean", f"Reconciliation issues: {rec_report.issues}"
            assert int(final_audit["beneficial_atoms"]) + int(final_audit["clearing_atoms"]) == 0

            successful_ops = total_operations - len(errors)
            throughput = round(successful_ops / total_duration, 2)

            all_latencies = [lat for lats in op_latencies.values() for lat in lats]

            return {
                "profile": "ad_coin_v2_operational_performance_production",
                "workers": workers,
                "total_operations": total_operations,
                "successful_operations": successful_ops,
                "failed_operations": len(errors),
                "error_rate_percent": round((len(errors) / total_operations) * 100, 2),
                "total_duration_seconds": round(total_duration, 3),
                "throughput_ops_per_second": throughput,
                "preseeded_history_records": preseed_history,
                "preseed_duration_seconds": round(preseed_duration, 3),
                "latency_overall_ms": {
                    "min": round(min(all_latencies), 2) if all_latencies else 0,
                    "p50": quantile(all_latencies, 0.50),
                    "p95": quantile(all_latencies, 0.95),
                    "p99": quantile(all_latencies, 0.99),
                    "max": round(max(all_latencies), 2) if all_latencies else 0,
                },
                "latency_by_operation_ms": {
                    op: {
                        "count": len(lats),
                        "p50": quantile(lats, 0.50),
                        "p95": quantile(lats, 0.95),
                        "p99": quantile(lats, 0.99),
                    }
                    for op, lats in op_latencies.items()
                },
                "latency_by_region_ms": {
                    reg: {
                        "count": len(lats),
                        "p50": quantile(lats, 0.50),
                        "p95": quantile(lats, 0.95),
                        "p99": quantile(lats, 0.99),
                    }
                    for reg, lats in regional_latencies.items()
                },
                "ledger_conservation_verified": True,
                "reconciliation_status": rec_report.status,
                "reconciliation_issues_count": len(rec_report.issues),
                "audit": {
                    "beneficial_atoms": final_audit["beneficial_atoms"],
                    "clearing_atoms": final_audit["clearing_atoms"],
                    "zero_sum_balance": int(final_audit["beneficial_atoms"]) + int(final_audit["clearing_atoms"]),
                },
                "errors": errors[:5],
            }
        finally:
            store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("reports/ad-coin-v6.2-operational-performance-2026-11-09/operational_perf_report.json"))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--operations", type=int, default=250)
    parser.add_argument("--preseed", type=int, default=1000)
    args = parser.parse_args()

    result = run_benchmark(
        workers=args.workers,
        total_operations=args.operations,
        preseed_history=args.preseed,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return int(result["failed_operations"] != 0 or not result["ledger_conservation_verified"])


if __name__ == "__main__":
    raise SystemExit(main())
