"""Real-value fiat deposits, 100% full-reserve proof-of-reserves, and on-chain withdrawal engine."""

import time
from typing import Any

from .contracts import ContractError, MAX_ATOMS
from .ledger import identifier



from .points import REAL_VALUE_ENV, real_value_enabled as is_real_value_enabled  # noqa: E402,F401


def require_real_value() -> None:
    if not is_real_value_enabled():
        raise ContractError("real_value_disabled", 403)


class RealValueGateway:
    """Manages real fiat/USDC deposit webhooks, full-reserve proof reconciliation, and on-chain redemptions."""

    def __init__(self, store, ledger, access, clock=None):
        self.store = store
        self.ledger = ledger
        self.access = access
        self._clock = clock or time.time

    def record_fiat_deposit(
        self,
        deposit_id: str,
        wallet_id: str,
        payer_owner_id: str,
        amount_atoms: int,
        currency: str,
        external_tx_ref: str,
    ) -> dict[str, Any]:
        """Record an inbound fiat/stablecoin deposit event."""
        require_real_value()
        if amount_atoms <= 0 or amount_atoms > MAX_ATOMS:
            raise ContractError("invalid_deposit_amount", 422)
        if currency not in ("USD", "EUR", "KRW", "USDC"):
            raise ContractError("unsupported_deposit_currency", 422)
        deposit_id = identifier(deposit_id)
        wallet_id = identifier(wallet_id)
        payer_owner_id = identifier(payer_owner_id)
        now = self._clock()

        with self.store.atomic():
            existing = self.store.one("fiat_deposit_get_by_ref", (external_tx_ref,))
            if existing is not None:
                raise ContractError("duplicate_external_tx_ref", 409)
            wallet = self.store.one("wallet_get", (wallet_id,))
            if wallet is None:
                raise ContractError("wallet_not_found", 404)

            self.store.execute(
                "fiat_deposit_insert",
                (
                    deposit_id,
                    wallet_id,
                    payer_owner_id,
                    amount_atoms,
                    currency,
                    external_tx_ref,
                    "pending",
                    now,
                    None,
                ),
            )
            return dict(self.store.one("fiat_deposit_get", (deposit_id,)))

    def confirm_fiat_deposit(
        self,
        deposit_id: str,
        clearing_account_id: str,
    ) -> dict[str, Any]:
        """Confirm a verified deposit webhook and credit wallet available balance 1:1."""
        require_real_value()
        deposit_id = identifier(deposit_id)
        clearing_account_id = identifier(clearing_account_id)
        now = self._clock()

        with self.store.atomic():
            dep = self.store.one("fiat_deposit_get", (deposit_id,))
            if dep is None:
                raise ContractError("deposit_not_found", 404)
            if dep["status"] != "pending":
                raise ContractError("deposit_already_processed", 409)

            wallet = self.store.one("wallet_get", (dep["wallet_id"],))
            if wallet is None:
                raise ContractError("wallet_not_found", 404)

            # Double-entry ledger posting: Debit clearing (-amount), Credit wallet available (+amount)
            amount = int(dep["amount_atoms"])
            postings = [
                (clearing_account_id, str(-amount)),
                (wallet["available_account"], str(amount)),
            ]
            self.ledger.post(f"real_deposit:{deposit_id}", postings, kind="model_seed")

            self.store.execute("fiat_deposit_confirm", (now, deposit_id))
            return dict(self.store.one("fiat_deposit_get", (deposit_id,)))

    def record_custody_reserve_checkpoint(
        self,
        checkpoint_id: str,
        custodian_name: str,
        vault_address: str,
        reported_atoms: int,
        attestation_hash: str,
        reported_at: float,
    ) -> dict[str, Any]:
        """Record an external custodian reserve balance attestation."""
        require_real_value()
        if reported_atoms < 0 or reported_atoms > MAX_ATOMS:
            raise ContractError("invalid_reserve_amount", 422)
        checkpoint_id = identifier(checkpoint_id)
        now = self._clock()

        with self.store.atomic():
            self.store.execute(
                "custody_reserve_insert",
                (
                    checkpoint_id,
                    custodian_name,
                    vault_address,
                    reported_atoms,
                    attestation_hash,
                    reported_at,
                    now,
                ),
            )
            return dict(self.store.one("custody_reserve_latest"))

    def reconcile_proof_of_reserves(self) -> dict[str, Any]:
        """Perform Proof-of-Reserves verification comparing external custody against circulating ledger supply."""
        require_real_value()
        with self.store.atomic():
            latest_res = self.store.one("custody_reserve_latest")
            reported_atoms = int(latest_res["reported_atoms"]) if latest_res else 0

            # Compute sum of all available and locked balances across all wallets
            wallets = self.store.all("reconcile_all_wallets") or []
            circulating_atoms = 0
            for w in wallets:
                avail = self.store.one("account_get", (w["available_account"],))
                locked = self.store.one("account_get", (w["locked_account"],))
                circulating_atoms += int(avail["balance_atoms"]) if avail else 0
                circulating_atoms += int(locked["balance_atoms"]) if locked else 0

            is_solvent = reported_atoms >= circulating_atoms
            coverage_bps = (
                (reported_atoms * 10000) // circulating_atoms
                if circulating_atoms > 0
                else 10000
            )

            status = "solvent_full_reserve" if is_solvent else "reserve_deficit"
            return {
                "status": status,
                "clean": is_solvent,
                "reported_custody_atoms": str(reported_atoms),
                "circulating_supply_atoms": str(circulating_atoms),
                "coverage_bps": coverage_bps,
                "coverage_percentage": f"{coverage_bps / 100:.2f}%",
                "attestation_timestamp": latest_res["reported_at"] if latest_res else None,
            }

    def request_onchain_withdrawal(
        self,
        withdrawal_id: str,
        wallet_id: str,
        owner_id: str,
        destination_chain: str,
        chain_id: int,
        destination_address: str,
        amount_atoms: int,
        fee_atoms: int,
    ) -> dict[str, Any]:
        """Initiate an on-chain withdrawal and atomically lock wallet available balance."""
        require_real_value()
        if amount_atoms <= 0 or fee_atoms < 0:
            raise ContractError("invalid_withdrawal_amount", 422)
        if destination_chain not in ("ethereum", "base", "polygon", "arbitrum"):
            raise ContractError("unsupported_destination_chain", 422)
        withdrawal_id = identifier(withdrawal_id)
        wallet_id = identifier(wallet_id)
        owner_id = identifier(owner_id)
        now = self._clock()

        with self.store.atomic():
            wallet = self.store.one("wallet_get", (wallet_id,))
            if wallet is None:
                raise ContractError("wallet_not_found", 404)
            if wallet["owner_id"] != owner_id:
                raise ContractError("wallet_owner_mismatch", 403)

            avail_acc = self.store.one("account_get", (wallet["available_account"],))
            total_required = amount_atoms + fee_atoms
            if int(avail_acc["balance_atoms"]) < total_required:
                raise ContractError("insufficient_wallet_balance", 422)

            # Atomic lock from wallet available to wallet locked account
            postings = [
                (wallet["available_account"], str(-total_required)),
                (wallet["locked_account"], str(total_required)),
            ]
            self.ledger.post(f"real_withdraw:{withdrawal_id}", postings, kind="reserve")

            self.store.execute(
                "onchain_withdrawal_insert",
                (
                    withdrawal_id,
                    wallet_id,
                    owner_id,
                    destination_chain,
                    chain_id,
                    destination_address,
                    amount_atoms,
                    fee_atoms,
                    "pending",
                    now,
                ),
            )
            return dict(self.store.one("onchain_withdrawal_get", (withdrawal_id,)))

    def confirm_onchain_withdrawal(
        self,
        withdrawal_id: str,
        tx_hash: str,
        redemption_account_id: str | None = None,
    ) -> dict[str, Any]:
        """Confirm on-chain broadcast completion with transaction hash and settle locked hold."""
        require_real_value()
        withdrawal_id = identifier(withdrawal_id)
        now = self._clock()

        with self.store.atomic():
            rec = self.store.one("onchain_withdrawal_get", (withdrawal_id,))
            if rec is None:
                raise ContractError("withdrawal_not_found", 404)
            if rec["status"] != "pending":
                raise ContractError("withdrawal_already_processed", 409)

            if redemption_account_id:
                wallet = self.store.one("wallet_get", (rec["wallet_id"],))
                total_settle = int(rec["amount_atoms"]) + int(rec["fee_atoms"])
                postings = [
                    (wallet["locked_account"], str(-total_settle)),
                    (redemption_account_id, str(total_settle)),
                ]
                self.ledger.post(f"real_withdraw_settle:{withdrawal_id}", postings, kind="release")

            self.store.execute(
                "onchain_withdrawal_update_status",
                ("confirmed", tx_hash, now, withdrawal_id),
            )
            return dict(self.store.one("onchain_withdrawal_get", (withdrawal_id,)))

    def cancel_onchain_withdrawal(
        self,
        withdrawal_id: str,
    ) -> dict[str, Any]:
        """Cancel on-chain withdrawal and refund locked hold back to user wallet available balance."""
        require_real_value()
        withdrawal_id = identifier(withdrawal_id)
        now = self._clock()

        with self.store.atomic():
            rec = self.store.one("onchain_withdrawal_get", (withdrawal_id,))
            if rec is None:
                raise ContractError("withdrawal_not_found", 404)
            if rec["status"] != "pending":
                raise ContractError("withdrawal_already_processed", 409)

            wallet = self.store.one("wallet_get", (rec["wallet_id"],))
            total_refund = int(rec["amount_atoms"]) + int(rec["fee_atoms"])

            postings = [
                (wallet["locked_account"], str(-total_refund)),
                (wallet["available_account"], str(total_refund)),
            ]
            self.ledger.post(f"real_withdraw_refund:{withdrawal_id}", postings, kind="release")

            self.store.execute(
                "onchain_withdrawal_update_status",
                ("cancelled", None, now, withdrawal_id),
            )
            return dict(self.store.one("onchain_withdrawal_get", (withdrawal_id,)))
