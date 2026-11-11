"""The worker daemon gets the paid-booking settings from gateway-data/sponsored.env and follows later changes (11-11)."""
import logging
import os

from scripts.ad_coin_worker_daemon import WorkerDaemon
from scripts.adcoin_worker_env import daemon_environment, paid_settings

ENV = """# runtime settings
APPLICATION_POSTGRES_DSN_FILE=/secret/dsn
AD_COIN_V2_KEY_DIR=/keys
AD_COIN_PAID_PRICE_USDC="5"
export AD_COIN_PAID_RPC_URL='https://mainnet.base.org'
AD_COIN_OFAC_LIST=/data/ofac.txt
"""


def test_only_paid_settings_are_copied_and_the_switch_stays_off_unless_written():
    assert paid_settings(ENV) == {'AD_COIN_PAID_PRICE_USDC': '5', 'AD_COIN_PAID_RPC_URL': 'https://mainnet.base.org',
                                  'AD_COIN_OFAC_LIST': '/data/ofac.txt'}
    env = daemon_environment('/rel/r1', ENV, '/proj/gateway-data/sponsored.env')
    assert 'AD_COIN_PAID_BOOKING_ENABLED' not in env and 'APPLICATION_POSTGRES_DSN_FILE' not in env
    assert env['PYTHONPATH'] == '/rel/r1' and env['AD_COIN_V2_ENABLED'] == '1'
    assert env['AD_COIN_RUNTIME_ENV_FILE'] == '/proj/gateway-data/sponsored.env'
    assert paid_settings('AD_COIN_PAID_BOOKING_ENABLED=1\n')['AD_COIN_PAID_BOOKING_ENABLED'] == '1'


def _daemon():
    daemon = object.__new__(WorkerDaemon)   # paid_cycle needs no other worker
    daemon.store = None
    return daemon


def test_daemon_follows_the_switch_in_the_env_file_without_a_reinstall(tmp_path, monkeypatch, caplog):
    path = tmp_path / 'agentcon.env'
    base = ENV + 'AD_COIN_PAID_PAY_TO_FILE=%s\n' % (tmp_path / 'missing.txt')      # no receive address
    path.write_text(base)
    keys = {k for k in os.environ if k.startswith('AD_COIN_PAID_') or k == 'AD_COIN_OFAC_LIST'}
    for key in keys | set(paid_settings(base)) | {'AD_COIN_PAID_BOOKING_ENABLED'}:
        monkeypatch.delenv(key, raising=False)      # restored after the test even though the daemon edits os.environ
    monkeypatch.setenv('AD_COIN_RUNTIME_ENV_FILE', str(path))
    daemon = _daemon()
    assert daemon.paid_cycle(0) == 0 and os.environ['AD_COIN_PAID_PRICE_USDC'] == '5'
    # switched on in the file, but no receive address: the daemon logs and keeps going, never raises
    path.write_text(base + 'AD_COIN_PAID_BOOKING_ENABLED=1\n')
    os.utime(path, (1, 1))
    with caplog.at_level(logging.INFO):
        assert daemon.paid_cycle(0) == 0
        assert daemon.paid_cycle(0) == 0
    assert os.environ['AD_COIN_PAID_BOOKING_ENABLED'] == '1' and daemon._paid_config_error
    assert 'mainnet.base.org' not in caplog.text and 'AD_COIN_PAID_BOOKING_ENABLED' in caplog.text
    # switched off again: the key leaves the environment
    path.write_text(base)
    os.utime(path, (2, 2))
    assert daemon.paid_cycle(0) == 0
    assert 'AD_COIN_PAID_BOOKING_ENABLED' not in os.environ and daemon.paid is None
