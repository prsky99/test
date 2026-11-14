"""Checks before switching USDC ad payments on (PM 11-14, checklist 5): fresh OFAC list, receive address, settings."""
import json
import os
import time

from scripts import ad_coin_paid_switch_check as check


def _root(tmp_path, *, ofac_age_h=1, pay_to='0x' + '1' * 40, listed=None, env='MAIN_SPONSORED=1\n'):
    data = tmp_path / 'gateway-data'
    (data / 'ofac').mkdir(parents=True)
    ofac = data / 'ofac/eth_addresses.txt'
    ofac.write_text(''.join('0x%040x\n' % i for i in range(1, 61)) + ''.join(a + '\n' for a in (listed or [])))
    old = time.time() - ofac_age_h * 3600
    os.utime(ofac, (old, old))
    (data / 'usdc-receive-address.txt').write_text('# receive only\n%s\n' % pay_to)
    (data / 'sponsored.env').write_text(env)
    (data / 'sponsored.env').chmod(0o600)
    reports = tmp_path / 'reports/ad-realign-2026-11-14'
    reports.mkdir(parents=True)
    stamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    for name in ('payment-flow-tests.json', 'payment-chain-check.json'):
        (reports / name).write_text(json.dumps({'all_passed': True, 'generated_utc': stamp}))
    return tmp_path


RUNNING = lambda: 'state = running\n\t\tAD_COIN_RUNTIME_ENV_FILE => /p/gateway-data/sponsored.env\n'  # noqa: E731


def _by_name(items):
    return {i['check']: i['ok'] for i in items}


def test_everything_ready_passes(tmp_path):
    items = _by_name(check.before(root=_root(tmp_path), launchctl=RUNNING))
    assert all(items[k] for k in ('ofac_fresh_24h', 'receive_address_file', 'sponsored_env_valid',
                                  'payment-flow-tests.json', 'payment-chain-check.json',
                                  'worker_daemon_reads_sponsored_env'))


def test_old_ofac_list_sanctioned_receiver_and_bad_settings_fail(tmp_path):
    items = _by_name(check.before(root=_root(tmp_path, ofac_age_h=30, pay_to='0x' + 'a' * 40,
                                             listed=['0x' + 'a' * 40], env='AGENTCON_UNKNOWN=1\n'),
                                  launchctl=lambda: 'state = waiting\n'))
    assert not items['ofac_fresh_24h'] and not items['receive_address_file']
    assert not items['sponsored_env_valid'] and not items['worker_daemon_reads_sponsored_env']
