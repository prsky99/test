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


def test_production_wiring_on_a_real_application_database(cluster, tmp_path, monkeypatch):  # noqa: F811
    """build() opens the application store the production way (all runtime capabilities), the v2 store
    on it, the persistent keys and the real credit entry point; a refused grant refunds the points."""
    import os
    import secrets
    import psycopg
    from uuid import uuid4
    from agent_market.ad_coin.v2 import points
    from agent_market.ad_coin.v2.ledger import ModelLedger
    from agent_market.ad_coin.v2.points_exchange import PointsExchange
    from scripts.ad_coin_worker_daemon import build
    from tests.test_ad_coin_postgres import PORT, _store

    monkeypatch.delenv('AD_COIN_REAL_VALUE_ENABLED', raising=False)
    _store(cluster, 'daemon_wiring')._connection.close()  # an initialized application database
    dsn_file, key_file, key_dir = tmp_path / 'dsn', tmp_path / 'key', tmp_path / 'keys'
    dsn_file.write_text('host=' + cluster['socket'] + ' port=' + str(PORT) + ' dbname=daemon_wiring user=postgres')
    key_file.write_bytes(b'p' * 32)
    for path in (dsn_file, key_file):
        os.chmod(path, 0o600)
    runtime, store, vault, grant = build(str(dsn_file), str(key_file), str(key_dir),
                                         connector=lambda dsn: psycopg.connect(dsn, autocommit=True))
    try:
        store.migrate_model()
        assert store.attach()
        again = build(str(dsn_file), str(key_file), str(key_dir),
                      connector=lambda dsn: psycopg.connect(dsn, autocommit=True))
        assert again[2].kid == vault.kid  # a second process reads the same signing key
        again[1].close()
        again[0].close()
        ledger = ModelLedger(store)
        points.issue(ledger, 100 * points.ATOMS_PER_COIN, reason='test-' + uuid4().hex)
        owner = str(uuid4())
        wallet = ledger.create_account(owner, 'user_available')
        ledger.post('reward:' + owner, [(points.GROWTH_ACCOUNT, str(-50 * points.ATOMS_PER_COIN)),
                                         (wallet, str(50 * points.ATOMS_PER_COIN))], kind='growth_reward')
        PointsExchange(store).request(owner_id=owner, customer_id='cu_' + secrets.token_hex(16), credits=2,
                                      exchange_id=secrets.token_hex(16), now_ms=int(time.time() * 1000))
        assert ledger.account(wallet)['balance_atoms'] == str(30 * points.ATOMS_PER_COIN)
        summary = WorkerDaemon(store, vault, credit_grant=grant).run_cycle()
        assert summary['processed_outbox'] == 1
        # The application refuses an unknown customer, so the worker refunds the points.
        assert ledger.account(wallet)['balance_atoms'] == str(50 * points.ATOMS_PER_COIN)
    finally:
        store.close()
        runtime.close()
