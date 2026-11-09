"""Background worker daemon for AI AD Coin v2 outbox processing, lease reclamation, and reporting."""

import argparse
import json
import logging
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_market.ad_coin.v2.key_vault import KeyVault  # noqa: E402
from agent_market.ad_coin.v2.receipts import ReceiptSigner  # noqa: E402
from agent_market.ad_coin.v2.store import ModelStore  # noqa: E402
from agent_market.ad_coin.v2.workers import ModelWorkers  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] ad_coin_daemon: %(message)s",
)
logger = logging.getLogger("ad_coin_daemon")


class WorkerDaemon:
    def __init__(self, store: ModelStore, vault: KeyVault | None = None):
        self.store = store
        self.vault = vault or KeyVault()
        signer = ReceiptSigner(self.store, {self.vault.kid: self.vault.get_signing_key()})
        self.workers = ModelWorkers(self.store, receipt_signer=signer)
        self.running = False

    def run_cycle(self, now_ms: int | None = None) -> dict:
        now_ms = now_ms or int(time.time() * 1000)
        reclaimed_leases = self.workers.reclaim_stale_leases(now_ms=now_ms)
        processed_outbox = self.workers.process_outbox(now_ms=now_ms)
        signed_receipts = self.workers.reconcile_pending_receipts(now_ms=now_ms)
        stale_attention = self.workers.reconcile_stale_attention(now_ms=now_ms)
        pruned = self.prune_if_due(now_ms)

        cycle_summary = {
            "timestamp_ms": now_ms,
            "reclaimed_leases": reclaimed_leases,
            "processed_outbox": processed_outbox,
            "signed_receipts": signed_receipts,
            "stale_attention": stale_attention,
            "pruned": pruned,
        }
        if any([reclaimed_leases, processed_outbox, signed_receipts, stale_attention, pruned]):
            logger.info("Cycle completed with activity: %s", cycle_summary)
        return cycle_summary

    PRUNE_INTERVAL_MS = 3_600_000  # retention deletes run at most once an hour

    def prune_if_due(self, now_ms: int) -> int:
        """Apply the retention periods (audit log 90 days, ended credentials 30 days)."""
        from agent_market.ad_coin.v2.security_guards import AuditLogger, prune_credentials

        if now_ms - getattr(self, "_last_prune_ms", 0) < self.PRUNE_INTERVAL_MS:
            return 0
        self._last_prune_ms = now_ms
        return AuditLogger.prune(self.store, now_ms=now_ms) + prune_credentials(self.store, now_ms=now_ms)

    def run_forever(self, interval_seconds: float = 5.0):
        self.running = True

        def _handle_exit(sig, frame):
            logger.info("Received exit signal (%s). Shutting down daemon...", sig)
            self.running = False

        signal.signal(signal.SIGINT, _handle_exit)
        signal.signal(signal.SIGTERM, _handle_exit)

        logger.info("Worker daemon started (interval=%.1fs)", interval_seconds)
        while self.running:
            try:
                self.run_cycle()
            except Exception as exc:
                logger.error("Error in daemon worker cycle: %s", exc, exc_info=True)
            time.sleep(interval_seconds)
        logger.info("Worker daemon stopped cleanly.")


def main():
    parser = argparse.ArgumentParser(description="AI AD Coin v2 Worker Daemon.")
    parser.add_argument("--once", action="store_true", help="Run a single worker cycle and exit")
    parser.add_argument("--interval", type=float, default=5.0, help="Loop interval in seconds")
    parser.add_argument("--health", action="store_true", help="Check database readiness and exit")
    args = parser.parse_args()

    store = ModelStore()
    if args.health:
        is_ready = store.is_ready() if hasattr(store, "is_ready") else True
        print(json.dumps({"status": "ready" if is_ready else "unready"}))
        return

    daemon = WorkerDaemon(store)
    if args.once:
        summary = daemon.run_cycle()
        print(json.dumps(summary, indent=2))
    else:
        daemon.run_forever(interval_seconds=args.interval)


if __name__ == "__main__":
    main()
