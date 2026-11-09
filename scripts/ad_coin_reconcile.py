#!/usr/bin/env python3
"""CLI utility to execute non-intrusive database reconciliation on AI AD Coin v2."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_market.ad_coin.v2.reconcile import LedgerReconciler  # noqa: E402
from agent_market.ad_coin.v2.store import ModelStore  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="AI AD Coin v2 Reconciliation Tool")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    store = ModelStore()
    reconciler = LedgerReconciler(store)
    report = reconciler.run_full_reconciliation()

    data = {
        "status": report.status,
        "timestamp_ms": report.timestamp_ms,
        "asset_balances": report.asset_balances,
        "campaigns_clean": report.campaign_checks["clean"],
        "wallets_clean": report.wallet_checks["clean"],
        "issues": list(report.issues),
    }

    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(f"Reconciliation Status: {report.status.upper()}")
        print(f"Asset Balances Delta: {report.asset_balances}")
        print(f"Campaign Budgets: {'PASS' if report.campaign_checks['clean'] else 'FAIL'}")
        print(f"Wallets & Receipts: {'PASS' if report.wallet_checks['clean'] else 'FAIL'}")
        if report.issues:
            print("Issues detected:")
            for issue in report.issues:
                print(f" - {issue}")
            sys.exit(1)
        print("All double-entry, budget conservation, and wallet integrity checks PASSED.")


if __name__ == "__main__":
    main()
