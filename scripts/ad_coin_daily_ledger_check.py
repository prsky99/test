"""Daily AI AD Coin v2 ledger conservation check on the production database (read only, PM 11-11 ③).

  .venv/bin/python -m scripts.ad_coin_daily_ledger_check --dsn-file <dsn> --key-file <workflow key>

Runs LedgerReconciler (double-entry zero sum per asset, no negative non-clearing account, campaign budget
conservation, wallets and receipts) plus the platform holdings, and writes
logs/ops/ad-coin-ledger/<UTC day>.json. Exit 1 when anything is off, so a scheduler can alert.
One database connection, no writes: every connection is made by the application's own validated connector and then
set to default_transaction_read_only=on (PM 12:4x audit), so even a write the code did not mean to make is refused by
PostgreSQL. (Inherited PGOPTIONS is refused by the application runtime, so the setting is applied per connection.)
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "logs/ops/ad-coin-ledger"


def check(store):
    from agent_market.ad_coin.v2.reconcile import LedgerReconciler
    report = LedgerReconciler(store).run_full_reconciliation()
    return {"status": report.status, "timestamp_ms": report.timestamp_ms, "asset_balances": report.asset_balances,
            "campaigns_clean": report.campaign_checks["clean"], "wallets_clean": report.wallet_checks["clean"],
            "issues": list(report.issues),
            "ok": report.status == "clean" and not report.issues}


def read_only_connector(connect=None):
    """The application's connector, then a read-only session on each connection it opens."""
    if connect is None:
        from agent_market.application_runtime import _connect as connect

    def opened(dsn):
        connection = connect(dsn)
        connection.execute("SET default_transaction_read_only = on")
        return connection
    return opened


def main(argv=None, connect=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dsn-file", required=True)
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--out-dir", default=str(OUT))
    args = parser.parse_args(argv)
    os.environ["AD_COIN_V2_POOL_MAXIMUM"] = "1"
    from agent_market.ad_coin.v2.live_service import store_from_application
    from agent_market.application_runtime import open_runtime_storage
    runtime = open_runtime_storage(":memory:", values={
        "APPLICATION_STORE_BACKEND": "postgresql", "APPLICATION_POSTGRES_DSN_FILE": args.dsn_file,
        "APPLICATION_WORKFLOW_KEY_FILE": args.key_file}, connector=read_only_connector(connect))
    runtime.store._admin_read_pool = None  # one connection only (prod connection budget)
    try:
        result = check(store_from_application(runtime.store))
    except Exception as error:  # report, never hide
        result = {"ok": False, "status": "error", "issues": [type(error).__name__ + ": " + str(error)[:300]]}
    finally:
        runtime.close()
    day = time.strftime("%Y-%m-%d", time.gmtime())
    Path(args.out_dir).mkdir(parents=True, exist_ok=True)
    (Path(args.out_dir) / (day + ".json")).write_text(json.dumps(result, indent=1, sort_keys=True, default=str))
    print(json.dumps({"ok": result["ok"], "status": result["status"], "issues": result["issues"][:5]}))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
