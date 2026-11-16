"""The daily USDC reconcile reads Base through a paced RPC (11-16 09:20: mainnet.base.org answered eth_getLogs with
429, the run ended chain_unreadable): a 429 or 5xx waits and tries again, other errors are not retried."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ad_coin_paid_reconcile as r  # noqa: E402
from agent_market.chain import RPCError  # noqa: E402


class Flaky:
    def __init__(self, failures):
        self.failures, self.calls = list(failures), []

    def call(self, method, *params):
        self.calls.append(method)
        if self.failures:
            raise RPCError(self.failures.pop(0))
        return '0x10'


def paced(inner, slept):
    now = [0.0]
    def sleep(s):
        slept.append(s); now[0] += s
    return r.PacedRPC(inner, spacing=0.35, waits=(2, 5), sleep=sleep, clock=lambda: now[0])


def test_rate_limits_wait_and_retry():
    slept = []
    rpc = paced(Flaky(['All RPC endpoints failed for eth_getLogs: HTTP 429 from x', 'HTTP 503 from x']), slept)
    assert rpc.block_number() == 16
    assert 2 in slept and 5 in slept


def test_spacing_between_calls_and_other_errors_are_not_retried():
    slept = []
    inner = Flaky([])
    rpc = paced(inner, slept)
    rpc.chain_id(); rpc.chain_id()
    assert slept == [0.35]
    bad = paced(Flaky(['eth_call: {"code": -32000, "message": "execution reverted"}']), [])
    with pytest.raises(RPCError):
        bad.call('eth_call')


def test_gives_up_after_the_last_wait():
    rpc = paced(Flaky(['HTTP 429 from x'] * 5), [])
    with pytest.raises(RPCError):
        rpc.call('eth_getLogs', {})


def test_due_days_rerun_missed_and_unreadable_days_but_not_findings(tmp_path):
    """11-16 PM source review: the daily job only ran yesterday, so a missed day stayed unreconciled."""
    import datetime
    import json
    (tmp_path / '2026-11-16.json').write_text(json.dumps({'ok': True, 'findings': []}))
    (tmp_path / '2026-11-17.json').write_text(json.dumps({'ok': False, 'findings': [{'kind': 'chain_unreadable'}]}))
    (tmp_path / '2026-11-18.json').write_text(json.dumps({'ok': False, 'findings': [{'kind': 'money_without_booking'}]}))
    (tmp_path / '2026-11-19.json').write_text('{not json')
    (tmp_path / '2026-11-21.json').write_text(json.dumps({'ok': True, 'findings': []}))
    days = r.due_days(tmp_path, datetime.date(2026, 11, 22), first_day='2026-11-14')
    # 11-15 missing, 11-17 chain unreadable, 11-19 unreadable file, 11-20 missing, 11-21 yesterday (always)
    assert days == ['2026-11-15', '2026-11-17', '2026-11-19', '2026-11-20', '2026-11-21']


def test_due_days_start_at_the_first_payment_day(tmp_path):
    import datetime
    assert r.due_days(tmp_path, datetime.date(2026, 11, 16)) == ['2026-11-14', '2026-11-15']
