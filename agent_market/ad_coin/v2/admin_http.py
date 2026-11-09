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

    from .economy import CoinEconomy

    economy = CoinEconomy(commercial.store, commercial.ledger, commercial.access)

    async def operator_write(request: Request):
        ctx = await get_admin_context(request)
        if not ctx.principal.csrf_verified:
            raise ContractError("csrf_required", 403)
        try:
            body = await request.json()
        except ValueError:
            raise ContractError("invalid_json", 400) from None
        if not isinstance(body, dict):
            raise ContractError("invalid_json", 400)
        return ctx, body

    def atoms_field(body, name):
        value = body.get(name)
        if type(value) is not str or not value.isdigit() or len(value) > 30:
            raise ContractError("invalid_amount", 422)
        return int(value)

    async def respond(call):
        try:
            return JSONResponse(await call(), status_code=200)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    @router.post("/coins/issuance")
    async def issue_coins(request: Request):
        async def call():
            _, body = await operator_write(request)
            return await run_in_threadpool(economy.issue_monthly, str(body.get("month", "")),
                                           atoms_field(body, "amount_atoms"))
        return await respond(call)

    @router.post("/coins/grants")
    async def grant_coins(request: Request):
        async def call():
            ctx, body = await operator_write(request)
            return await run_in_threadpool(
                lambda: economy.operator_grant(ctx.principal, account_id=str(body.get("account_id", "")),
                                               amount_atoms=atoms_field(body, "amount_atoms"),
                                               reason=body.get("reason"), request_id=body.get("request_id")))
        return await respond(call)

    @router.post("/advertisers/{advertiser_id}/welcome-grant")
    async def welcome_grant(request: Request, advertiser_id: str):
        async def call():
            await operator_write(request)
            return await run_in_threadpool(economy.welcome_grant, advertiser_id)
        return await respond(call)

    @router.post("/advertisers/{advertiser_id}/provider-reward")
    async def provider_reward(request: Request, advertiser_id: str):
        async def call():
            _, body = await operator_write(request)
            return await run_in_threadpool(economy.provider_reward, advertiser_id, str(body.get("month", "")),
                                           atoms_field(body, "amount_atoms"))
        return await respond(call)

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
