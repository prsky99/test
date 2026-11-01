"""A402 Virtual Escrow & M2M Micropayment Clearinghouse.

Provides zero-trust escrow and micropayment settlement for autonomous AI agents.
Enforces SLA verification before funds are settled, protecting agents against
malicious, broken, or rug-pulled upstream paid MCP/x402 endpoints.
"""

import hashlib
import json
import logging
import time
from typing import Any

from ..gateway.store import Store

log = logging.getLogger("agent_market.concierge.clearinghouse")


class ClearinghouseError(Exception):
    """Base exception for clearinghouse errors."""
    pass


class InsufficientCreditsError(ClearinghouseError):
    """Raised when an account does not have enough available credits."""
    pass


class SlaViolationError(ClearinghouseError):
    """Raised when an upstream service fails SLA verification."""
    pass


class Clearinghouse:
    def __init__(self, store: Store, max_latency_ms: int = 30000):
        self.store = store
        self.max_latency_ms = max_latency_ms

    def deposit(self, account_id: str, amount: int, tx_hash: str | None = None) -> dict[str, Any]:
        """Deposits credits into an agent's virtual account (amount in micro-USDC)."""
        if amount <= 0:
            raise ClearinghouseError("Deposit amount must be positive.")
        res = self.store.deposit_credit(account_id, amount)
        log.info("Agent %s deposited %d micro-USDC (new balance: %d)", account_id, amount, res["balance"])
        return res

    def balance(self, account_id: str) -> dict[str, Any]:
        """Returns the current credit balance, escrow-held amount, and available credits."""
        return self.store.get_credit(account_id)

    def escrow_hold(self, account_id: str, amount: int, resource_id: int, tool_name: str) -> str:
        """Reserves funds in virtual escrow prior to remote execution."""
        try:
            tx_id = self.store.hold_credit(account_id, amount, resource_id, tool_name)
            log.info("Escrow hold %s: %d micro-USDC reserved for %s (res: %s, tool: %s)",
                     tx_id, amount, account_id, resource_id, tool_name)
            return tx_id
        except ValueError as exc:
            raise InsufficientCreditsError(str(exc)) from exc

    def verify_sla(self, result: dict[str, Any]) -> tuple[bool, str]:
        """Verifies if the execution result meets SLA requirements.
        
        Checks:
        1. Execution status (ok == True)
        2. No error flags (isError != True)
        3. Latency within acceptable bounds
        4. Valid, non-empty response content
        """
        if not result.get("ok"):
            err = result.get("error") or "Execution indicated failure (ok=False)"
            return False, f"SLA Violation: {err}"

        res_obj = result.get("result")
        if isinstance(res_obj, dict) and res_obj.get("isError"):
            return False, "SLA Violation: Tool response flagged isError=True"

        latency = result.get("latency_ms", 0)
        if latency > self.max_latency_ms:
            return False, f"SLA Violation: Latency {latency}ms exceeded maximum {self.max_latency_ms}ms"

        # Check for empty response
        res_data = result.get("result")
        sample = result.get("sample_output")
        if res_data is None and not sample:
            return False, "SLA Violation: Upstream tool returned empty response"

        return True, "SLA Verified"

    def escrow_settle(self, tx_id: str, result: dict[str, Any]) -> dict[str, Any]:
        """Settles escrowed funds after SLA verification succeeds."""
        sla_ok, sla_reason = self.verify_sla(result)
        if not sla_ok:
            # Automatic refund if SLA fails
            return self.escrow_refund(tx_id, reason=sla_reason)

        tx = self.store.get_clearing_tx(tx_id)
        if not tx:
            raise ClearinghouseError(f"Transaction {tx_id} not found.")

        latency = result.get("latency_ms", 0)
        receipt = self.create_receipt(
            tx_id=tx_id,
            account_id=tx["account_id"],
            resource_id=tx["resource_id"],
            tool_name=tx["tool_name"],
            amount=tx["amount"],
            status="settled",
            latency_ms=latency,
            sla_note=sla_reason,
        )

        settled = self.store.settle_credit(tx_id, receipt)
        log.info("Escrow settled %s: %d micro-USDC finalized for %s", tx_id, tx["amount"], tx["account_id"])
        return settled

    def escrow_refund(self, tx_id: str, reason: str = "") -> dict[str, Any]:
        """Releases escrow hold and refunds funds back to the caller's available balance."""
        refunded = self.store.refund_credit(tx_id, reason=reason)
        log.warning("Escrow refunded %s: %d micro-USDC returned to %s (reason: %s)",
                    tx_id, refunded["amount"], refunded["account_id"], reason)
        return refunded

    def create_receipt(self, tx_id: str, account_id: str, resource_id: int, tool_name: str,
                       amount: int, status: str, latency_ms: int = 0, sla_note: str = "") -> dict[str, Any]:
        """Generates a cryptographically sealed settlement receipt."""
        now = time.time()
        payload = {
            "receipt_id": tx_id,
            "account_id": account_id,
            "resource_id": resource_id,
            "tool": tool_name,
            "amount_micro_usdc": amount,
            "status": status,
            "sla_verified": True if status == "settled" else False,
            "sla_note": sla_note,
            "latency_ms": latency_ms,
            "timestamp": now,
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
        payload["integrity_seal"] = digest
        return payload

    def withdraw(self, account_id: str, amount: int, to_address: str) -> dict[str, Any]:
        """Withdraws available credits from an agent's account to an on-chain address."""
        if amount <= 0:
            raise ClearinghouseError("Withdrawal amount must be positive.")
        if not to_address or not to_address.startswith("0x") or len(to_address) != 42:
            raise ClearinghouseError("Invalid recipient Ethereum/Base address.")
        try:
            res = self.store.withdraw_credit(account_id, amount, to_address)
            log.info("Agent %s withdrew %d micro-USDC to %s", account_id, amount, to_address)
            return res
        except ValueError as exc:
            raise InsufficientCreditsError(str(exc)) from exc

    def sweep_orphaned_holds(self, ttl_seconds: float = 900) -> list[str]:
        """Sweeps orphaned virtual escrow holds older than TTL."""
        refunded = self.store.sweep_orphaned_holds(ttl_seconds)
        if refunded:
            log.info("Swept %d orphaned virtual escrow holds (refunded to agents)", len(refunded))
        return refunded

    def reserve_audit(self) -> dict[str, Any]:
        """Provides Proof-of-Reserve audit metrics for Clearinghouse virtual balances."""
        overview = self.store.get_clearing_overview()
        accounts = overview.get("accounts", {})
        total_balance = accounts.get("total_balance", 0)
        total_held = accounts.get("total_held", 0)
        total_deposited = accounts.get("total_deposited", 0)
        total_spent = accounts.get("total_spent", 0)

        reconciliation_delta = total_deposited - (total_spent + total_balance)
        return {
            "total_user_balance_micro_usdc": total_balance,
            "total_held_in_escrow_micro_usdc": total_held,
            "total_available_micro_usdc": accounts.get("available_balance", 0),
            "total_deposited_micro_usdc": total_deposited,
            "total_settled_spent_micro_usdc": total_spent,
            "reconciliation_delta": reconciliation_delta,
            "is_fully_backed": reconciliation_delta == 0,
            "overview": overview,
        }

    def stats(self) -> dict[str, Any]:
        """Returns aggregate clearinghouse statistics."""
        return self.store.get_clearing_overview()
