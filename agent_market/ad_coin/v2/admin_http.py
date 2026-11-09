"""Admin portal HTTP endpoints for AI AD Coin v2: ledger reconciliation,

platform overview, relay partner management, and execution dispute resolution.
"""

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .commercial import Commercial
from .contracts import ContractError
from .http import _error
from .reconcile import LedgerReconciler


def router_for(
    commercial: Commercial,
    *,
    resolve_auth: Any | None = None,
) -> APIRouter:
    """Create FastAPI router for AI AD Coin v2 admin operations."""
    router = APIRouter(prefix="/api/ad-coin/v2/admin")
    reconciler = LedgerReconciler(commercial.store)

    async def get_admin_context(request: Request):
        if resolve_auth is None:
            raise ContractError("auth_resolver_not_configured", 503)
        ctx = await run_in_threadpool(resolve_auth, request)
        await run_in_threadpool(commercial.access.require_operator, ctx.principal)
        return ctx

    @router.get("/reconcile")
    async def reconcile_full(request: Request):
        """Run complete double-entry ledger, campaign budget, and wallet reconciliation."""
        try:
            await get_admin_context(request)
            report = await run_in_threadpool(reconciler.run_full_reconciliation)
            audit_res = await run_in_threadpool(commercial.ledger.audit)
            beneficial = int(audit_res["beneficial_atoms"])
            clearing = int(audit_res["clearing_atoms"])
            zero_sum = (beneficial + clearing) == 0

            return JSONResponse({
                "reconciliation": {
                    "status": report.status,
                    "timestamp_ms": report.timestamp_ms,
                    "asset_balances": report.asset_balances,
                    "issues": list(report.issues),
                    "balanced": report.status == "clean",
                },
                "audit": {
                    "accounts_checked": audit_res["accounts_checked"],
                    "beneficial_atoms": audit_res["beneficial_atoms"],
                    "clearing_atoms": audit_res["clearing_atoms"],
                    "zero_sum_balanced": zero_sum,
                },
                "status": "balanced" if (report.status == "clean" and zero_sum) else "imbalanced",
            }, status_code=200)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    @router.get("/overview")
    async def platform_overview(request: Request):
        """Fetch platform-wide aggregate counts for campaigns, relays, and executions."""
        try:
            await get_admin_context(request)
            store = commercial.store

            # Active campaigns
            camp_rows = store.all("reconcile_active_campaigns") or []
            # Relay partners
            partner_rows = store.all("relay_partner_list") or []
            # Wallets
            wallet_rows = store.all("reconcile_all_wallets") or []

            audit_res = await run_in_threadpool(commercial.ledger.audit)

            return JSONResponse({
                "active_campaigns_count": len(camp_rows),
                "active_relay_partners_count": len(partner_rows),
                "total_wallets_count": len(wallet_rows),
                "ledger_accounts_checked": audit_res["accounts_checked"],
                "total_beneficial_atoms": audit_res["beneficial_atoms"],
                "total_clearing_atoms": audit_res["clearing_atoms"],
            }, status_code=200)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    return router
