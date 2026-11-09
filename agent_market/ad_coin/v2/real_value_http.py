"""HTTP endpoints for AI AD Coin v2 real-value deposits, proof-of-reserves, and blockchain redemptions."""

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .contracts import ContractError
from .http import _error
from .real_value import RealValueGateway, is_real_value_enabled


def _real_value_switch() -> None:
    if not is_real_value_enabled():
        raise HTTPException(status_code=404, detail="Not found")


def router_for(
    gateway: RealValueGateway,
    clearing_account_id: str,
    *,
    resolve_auth: Any | None = None,
) -> APIRouter:
    """Create FastAPI router for real-value issuance and blockchain operations."""
    router = APIRouter(prefix="/api/ad-coin/v2/real", dependencies=[Depends(_real_value_switch)])

    async def get_context(request: Request):
        if resolve_auth is None:
            raise ContractError("auth_resolver_not_configured", 503)
        return await run_in_threadpool(resolve_auth, request)

    @router.post("/deposits")
    async def record_deposit(request: Request):
        try:
            body = await request.json()
            dep_id = body.get("deposit_id") or str(uuid4())
            wallet_id = body.get("wallet_id")
            payer_owner_id = body.get("payer_owner_id")
            amount_atoms = int(body.get("amount_atoms", 0))
            currency = body.get("currency", "USD")
            external_tx_ref = body.get("external_tx_ref")

            if not all([wallet_id, payer_owner_id, external_tx_ref]):
                raise ContractError("missing_required_deposit_fields", 422)

            res = await run_in_threadpool(
                gateway.record_fiat_deposit,
                dep_id,
                wallet_id,
                payer_owner_id,
                amount_atoms,
                currency,
                external_tx_ref,
            )
            return JSONResponse({"deposit": res}, status_code=201)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    @router.post("/deposits/{deposit_id}/confirm")
    async def confirm_deposit(deposit_id: str, request: Request):
        try:
            await get_context(request)
            res = await run_in_threadpool(
                gateway.confirm_fiat_deposit,
                deposit_id,
                clearing_account_id,
            )
            return JSONResponse({"deposit": res}, status_code=200)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    @router.post("/reserves/checkpoints")
    async def record_reserve(request: Request):
        try:
            await get_context(request)
            body = await request.json()
            checkpoint_id = body.get("checkpoint_id") or str(uuid4())
            custodian_name = body.get("custodian_name")
            vault_address = body.get("vault_address")
            reported_atoms = int(body.get("reported_atoms", 0))
            attestation_hash = body.get("attestation_hash")
            reported_at = float(body.get("reported_at", 0))

            if not all([custodian_name, vault_address, attestation_hash, reported_at]):
                raise ContractError("missing_required_reserve_fields", 422)

            res = await run_in_threadpool(
                gateway.record_custody_reserve_checkpoint,
                checkpoint_id,
                custodian_name,
                vault_address,
                reported_atoms,
                attestation_hash,
                reported_at,
            )
            return JSONResponse({"checkpoint": res}, status_code=201)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    @router.get("/reserves/proof")
    async def get_proof_of_reserves(request: Request):
        try:
            res = await run_in_threadpool(gateway.reconcile_proof_of_reserves)
            return JSONResponse(res, status_code=200)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    @router.post("/withdrawals")
    async def request_withdrawal(request: Request):
        try:
            ctx = await get_context(request)
            body = await request.json()
            withdrawal_id = body.get("withdrawal_id") or str(uuid4())
            wallet_id = body.get("wallet_id")
            dest_chain = body.get("destination_chain")
            chain_id = int(body.get("chain_id", 0))
            dest_addr = body.get("destination_address")
            amount_atoms = int(body.get("amount_atoms", 0))
            fee_atoms = int(body.get("fee_atoms", 0))

            if not all([wallet_id, dest_chain, chain_id, dest_addr]):
                raise ContractError("missing_required_withdrawal_fields", 422)

            res = await run_in_threadpool(
                gateway.request_onchain_withdrawal,
                withdrawal_id,
                wallet_id,
                str(ctx.principal.owner_id),
                dest_chain,
                chain_id,
                dest_addr,
                amount_atoms,
                fee_atoms,
            )
            return JSONResponse({"withdrawal": res}, status_code=201)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    @router.post("/withdrawals/{withdrawal_id}/confirm")
    async def confirm_withdrawal(withdrawal_id: str, request: Request):
        try:
            await get_context(request)
            body = await request.json()
            tx_hash = body.get("tx_hash")
            if not tx_hash:
                raise ContractError("missing_tx_hash", 422)

            res = await run_in_threadpool(
                gateway.confirm_onchain_withdrawal,
                withdrawal_id,
                tx_hash,
            )
            return JSONResponse({"withdrawal": res}, status_code=200)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    @router.post("/webhooks/stripe")
    async def stripe_webhook(request: Request):
        try:
            handler = getattr(request.app.state, "fiat_handler", None)
            if handler is None:
                raise ContractError("fiat_webhook_handler_not_configured", 503)
            raw_body = await request.body()
            sig = request.headers.get("stripe-signature", "")
            res = await run_in_threadpool(handler.handle_stripe_event, raw_body, sig)
            return JSONResponse({"status": "success", "result": res}, status_code=200)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    @router.post("/webhooks/circle")
    async def circle_webhook(request: Request):
        try:
            handler = getattr(request.app.state, "fiat_handler", None)
            if handler is None:
                raise ContractError("fiat_webhook_handler_not_configured", 503)
            raw_body = await request.body()
            sig = request.headers.get("x-circle-signature", "")
            res = await run_in_threadpool(handler.handle_circle_event, raw_body, sig)
            return JSONResponse({"status": "success", "result": res}, status_code=200)
        except ContractError as exc:
            return JSONResponse(_error(exc.code, exc.status, str(uuid4())), status_code=exc.status)

    return router
