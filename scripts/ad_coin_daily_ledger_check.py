"""Daily AI AD Coin v2 ledger conservation check on the production database (read only, PM 11-11 ③).

  .venv/bin/python -m scripts.ad_coin_daily_ledger_check --dsn-file <dsn> --key-file <workflow key>

Runs LedgerReconciler (double-entry zero sum per asset, no negative non-clearing account, campaign budget
conservation, wallets and receipts) plus the platform holdings, and writes
logs/ops/ad-coin-ledger/<UTC day>.json. Exit 1 when anything is off, so a scheduler can alert.
One database connection, no writes.
"""
import argparse
import json
import os
import sys
import time
import types
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dsn-file", required=True)
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--out-dir", default=str(OUT))
    args = parser.parse_args(argv)
    os.environ["AD_COIN_V2_POOL_MAXIMUM"] = "1"
    from agent_market.ad_coin.v2.live_service import store_from_application
    from scripts.ad_coin_v2_migrate import _connect
    runtime = _connect(types.SimpleNamespace(dsn_file=args.dsn_file, key_file=args.key_file))
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
