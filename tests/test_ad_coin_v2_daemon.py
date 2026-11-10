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


def test_daemon_refuses_a_relative_key_folder():
    import pytest
    from scripts.ad_coin_worker_daemon import build
    with pytest.raises(SystemExit):
        build('dsn', 'key', 'gateway-data/ad_coin_v2_keys')
    with pytest.raises(SystemExit):
        build('dsn', 'key', '')


def test_daemon_passes_the_credit_grant_to_the_workers(store):  # noqa: F811
    from scripts.ad_coin_worker_daemon import WorkerDaemon
    store.migrate_model()
    def grant(*_):
        return None
    assert WorkerDaemon(store, credit_grant=grant).workers.credit_grant is grant


def test_daemon_command_needs_the_production_settings_files():
    import pytest
    from scripts.ad_coin_worker_daemon import main
    with pytest.raises(SystemExit):
        main(['--once'])
