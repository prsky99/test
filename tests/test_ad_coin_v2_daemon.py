"""Test suite for AI AD Coin v2 background worker daemon."""

import time

from agent_market.ad_coin.v2.key_vault import KeyVault
from scripts.ad_coin_worker_daemon import WorkerDaemon
from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_persistence import store  # noqa: F401


def test_worker_daemon_cycle(store):  # noqa: F811
    store.migrate_model()
    vault = KeyVault()
    daemon = WorkerDaemon(store, vault=vault)

    # 1. Run cycle on clean DB
    now_ms = int(time.time() * 1000)
    summary = daemon.run_cycle(now_ms=now_ms)
    assert summary["timestamp_ms"] == now_ms
    assert summary["reclaimed_leases"] == 0
    assert summary["processed_outbox"] == 0
    assert summary["signed_receipts"] == 0
    assert summary["stale_attention"] == 0
