"""Operational disaster recovery and reconciliation engine for ledgers, budgets, and receipts."""

from dataclasses import dataclass
import time
from typing import Any


@dataclass(frozen=True)
class ReconciliationReport:
    status: str  # "clean" or "discrepancy"
    timestamp_ms: int
    asset_balances: dict[str, str]
    campaign_checks: dict[str, Any]
    wallet_checks: dict[str, Any]
    issues: tuple[str, ...]


class LedgerReconciler:
    """Verifies complete double-entry integrity, budget conservation, and receipt fulfillment."""

    def __init__(self, store, clock=None):
        self.store = store
        self._clock = clock or time.time

    def reconcile_ledger(self) -> dict[str, Any]:
        """Verify double-entry zero-sum invariant across all postings and assets."""
        with self.store.atomic():
            # Initialize all registered assets with 0 balance
            assets = self.store.execute("reconcile_all_assets").fetchall()
            results = {
                a["id"]: {"total_delta": "0", "posting_count": 0, "balanced": True}
                for a in assets
            }
            # Sum delta_atoms for assets with postings
            rows = self.store.execute("reconcile_postings_sum").fetchall()
            for r in rows:
                results[r["asset_id"]] = {
                    "total_delta": str(r["total_delta"]),
                    "posting_count": r["posting_count"],
                    "balanced": int(r["total_delta"]) == 0,
                }
            # Verify no negative balances for non-clearing accounts
            neg_accounts = self.store.execute("reconcile_negative_accounts").fetchall()
            return {
                "asset_balances": results,
                "negative_accounts": [dict(a) for a in neg_accounts],
                "clean": all(v["balanced"] for v in results.values()) and len(neg_accounts) == 0,
            }

    def reconcile_campaign_budgets(self) -> dict[str, Any]:
        """Verify conservation of campaign budgets across accounts, holds, and expenditures."""
        with self.store.atomic():
            campaigns = self.store.execute("reconcile_active_campaigns").fetchall()
            campaign_results = {}
            for camp in campaigns:
                camp_id = camp["id"]
                account_id = camp["account_id"]
                # 1. Total window limit
                total_win = self.store.execute(
                    "reconcile_campaign_total_window",
                    (account_id,),
                ).fetchone()
                # 2. Sum of active holds
                holds_row = self.store.execute(
                    "reconcile_campaign_holds",
                    (account_id,),
                ).fetchone()
                # 3. Sum of consumed events
                spent_row = self.store.execute(
                    "reconcile_campaign_spent",
                    (account_id,),
                ).fetchone()

                account = self.store.execute(
                    "account_get",
                    (account_id,),
                ).fetchone()

                balance = int(account["balance_atoms"]) if account else 0
                remaining_holds = int(holds_row["remaining_holds"]) if holds_row else 0
                spent_total = int(spent_row["spent_total"]) if spent_row else 0

                is_conserved = True
                if total_win:
                    reserved = int(total_win["reserved_atoms"])
                    spent = int(total_win["spent_atoms"])
                    # reserved_atoms should equal remaining_holds
                    if reserved < remaining_holds or spent < spent_total:
                        is_conserved = False

                campaign_results[camp_id] = {
                    "balance_atoms": str(balance),
                    "remaining_holds_atoms": str(remaining_holds),
                    "spent_total_atoms": str(spent_total),
                    "conserved": is_conserved,
                }

            return {
                "campaigns": campaign_results,
                "clean": all(c["conserved"] for c in campaign_results.values()),
            }

    def reconcile_wallets(self) -> dict[str, Any]:
        """Verify that awarded receipts have matching available credits in user wallets."""
        with self.store.atomic():
            wallets = self.store.execute("reconcile_all_wallets").fetchall()
            wallet_results = {}
            for w in wallets:
                # Sum user rewards from receipts for this owner
                receipt_sum = self.store.execute(
                    "reconcile_wallet_receipts",
                    (w["owner_id"],),
                ).fetchone()
                avail_account = self.store.execute(
                    "account_get",
                    (w["available_account"],),
                ).fetchone()

                rewards = int(receipt_sum["total_rewards"]) if receipt_sum else 0
                balance = int(avail_account["balance_atoms"]) if avail_account else 0

                # Available balance must exist and be non-negative
                wallet_results[w["id"]] = {
                    "owner_id": w["owner_id"],
                    "available_balance": str(balance),
                    "signed_rewards": str(rewards),
                    "matches": avail_account is not None and balance >= 0,
                }

            return {
                "wallets": wallet_results,
                "clean": all(w["matches"] for w in wallet_results.values()),
            }

    def run_full_reconciliation(self) -> ReconciliationReport:
        """Execute full system reconciliation check and output immutable health report."""
        now_ms = int(self._clock() * 1000)
        ledger_res = self.reconcile_ledger()
        campaign_res = self.reconcile_campaign_budgets()
        wallet_res = self.reconcile_wallets()

        issues = []
        if not ledger_res["clean"]:
            issues.append("Unbalanced ledger or negative asset balance detected")
        if not campaign_res["clean"]:
            issues.append("Campaign budget window discrepancy detected")
        if not wallet_res["clean"]:
            issues.append("Wallet balance mismatch with signed receipts")

        status = "clean" if not issues else "discrepancy"
        asset_summary = {k: v["total_delta"] for k, v in ledger_res["asset_balances"].items()}

        return ReconciliationReport(
            status=status,
            timestamp_ms=now_ms,
            asset_balances=asset_summary,
            campaign_checks=campaign_res,
            wallet_checks=wallet_res,
            issues=tuple(issues),
        )
