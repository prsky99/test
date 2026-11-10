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
    def __init__(self, store: ModelStore, vault: KeyVault | None = None, credit_grant=None):
        self.store = store
        self.vault = vault or KeyVault()
        signer = ReceiptSigner(self.store, {self.vault.kid: self.vault.get_signing_key()})
        self.workers = ModelWorkers(self.store, receipt_signer=signer, credit_grant=credit_grant)
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
        """Apply point expiry (365 days idle) and retention (audit log 90 days, ended credentials 30 days)."""
        from agent_market.ad_coin.v2.security_guards import AuditLogger, prune_credentials

        if now_ms - getattr(self, "_last_prune_ms", 0) < self.PRUNE_INTERVAL_MS:
            return 0
        self._last_prune_ms = now_ms
        from agent_market.ad_coin.v2.points import expire_inactive_points

        expired = expire_inactive_points(self.store, self.workers.ledger, now_ms=now_ms)
        return expired + AuditLogger.prune(self.store, now_ms=now_ms) + prune_credentials(self.store, now_ms=now_ms)

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


def build(dsn_file: str, key_file: str, key_dir: str):
    """Production wiring: the application PostgreSQL database (one v2 session), the shared persistent
    keys the frontend uses, and the real workspace credit grant for points exchanges."""
    import os

    if not key_dir or not os.path.isabs(key_dir):
        raise SystemExit("--key-dir (or AD_COIN_V2_KEY_DIR) must be the absolute key folder the frontend uses")
    from agent_market.application_runtime import open_runtime_storage
    from agent_market.ad_coin.v2.live_service import store_from_application
    from agent_market.customer_credits import CustomerCredits
    from agent_market.customer_identity import customer_identity_for
    from agent_market.workflows import runtime_for

    runtime = open_runtime_storage(":memory:", values={
        "APPLICATION_STORE_BACKEND": "postgresql", "APPLICATION_POSTGRES_DSN_FILE": dsn_file,
        "APPLICATION_WORKFLOW_KEY_FILE": key_file})
    app_store = runtime.store
    app_store._admin_read_pool = None  # keep the connection budget small
    os.environ["AD_COIN_V2_POOL_MAXIMUM"] = "1"
    store = store_from_application(app_store)
    credits = CustomerCredits(customer_identity_for(app_store, runtime_for(app_store).key))
    return runtime, store, KeyVault.from_directory(key_dir), credits.exchange_points


def main(argv=None):
    import os

    parser = argparse.ArgumentParser(description="AI AD Coin v2 Worker Daemon.")
    parser.add_argument("--dsn-file", required=True)
    parser.add_argument("--key-file", required=True, help="the application workflow key file")
    parser.add_argument("--key-dir", default=os.environ.get("AD_COIN_V2_KEY_DIR", ""))
    parser.add_argument("--once", action="store_true", help="Run a single worker cycle and exit")
    parser.add_argument("--interval", type=float, default=5.0, help="Loop interval in seconds")
    parser.add_argument("--health", action="store_true", help="Check that the migrated v2 schema is reachable and exit")
    args = parser.parse_args(argv)

    runtime, store, vault, grant = build(args.dsn_file, args.key_file, args.key_dir)
    try:
        if args.health:
            print(json.dumps({"status": "ready" if store.attach() else "unready"}))
            return 0
        daemon = WorkerDaemon(store, vault, credit_grant=grant)
        if args.once:
            print(json.dumps(daemon.run_cycle(), indent=2))
        else:
            daemon.run_forever(interval_seconds=args.interval)
    finally:
        store.close()
        runtime.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
