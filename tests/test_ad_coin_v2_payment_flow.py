"""USDC paid Sponsored bookings, end to end and every failure case (PM 11-14: switch on by the payment stability rule).

quote -> pay -> confirm -> shown -> advertiser report -> receipt -> monthly export -> settle, then underpay, overpay,
other token, late payment, the same payment twice and a sanctioned payer. Each case records the booking state and
the refund guidance the advertiser sees. Refunds are sent by the user by hand; the server only records them.

With PAYMENT_FLOW_REPORT=<path> the results are also written as JSON for operations (the fixed path is
reports/ad-realign-2026-11-14/payment-flow-tests.json).
"""
import json
import os
import time

import pytest

from agent_market.ad_coin.v2 import paid_bookings as paid
from agent_market.ad_coin.v2.advertiser_history import PAID_STATES, sponsored_report, updates
from agent_market.ad_coin.v2.contracts import ContractError
from agent_market.ad_coin.v2.sponsored import SponsoredSlots
from agent_market.ad_coin.v2.sponsored_booking import DAY_MS
from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_paid_bookings import (NO_FILE, NOW, PAY_TO, PAYER, operator, quote,  # noqa: F401
                                                 world)
from tests.test_ad_coin_v2_persistence import store  # noqa: F401
from tests.test_ad_coin_v2_p1 import p1_suite  # noqa: F401

RESULTS = []


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv('AD_COIN_PAID_PAY_TO_FILE', NO_FILE)
    monkeypatch.setenv(paid.ENABLED_ENV, '1')              # the switch is on inside these tests only


@pytest.fixture(scope='module', autouse=True)
def _report():
    yield
    target = os.environ.get('PAYMENT_FLOW_REPORT')
    if target:
        with open(target, 'w') as handle:
            json.dump({'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                       'source': 'tests/test_ad_coin_v2_payment_flow.py', 'chain': 'Base (8453), fake RPC receipts',
                       'all_passed': all(r['passed'] for r in RESULTS), 'cases': RESULTS}, handle, indent=1)


def _record(case, expected, got, row=None, advertiser_text=None, refund=None):
    RESULTS.append({'case': case, 'expected': expected, 'got': got, 'passed': expected == got,
                    'booking_state': row['state'] if row else None, 'note': row['note'] if row else None,
                    'advertiser_sees': advertiser_text, 'refund': refund})
    assert expected == got, (case, expected, got)


def _row(suite, booking_id):
    return suite.service.store.one('paid_booking_get', (booking_id,))


def test_full_flow_quote_pay_show_report_receipt_export_settle(world):
    suite, service, rpc, campaign = world
    store, access, op = suite.service.store, suite.service.access, operator(suite)
    from scripts.ad_coin_v2_migrate import migrate_impressions
    migrate_impressions(store)                            # production has it since 11-11 (migrate-usdc)
    q = quote(world)
    assert q['state'] == 'quoted' and q['pay_to'] == PAY_TO and q['token_symbol'] == 'USDC'
    tx = rpc.send(int(q['amount_units']))
    done = service.submit(suite.advertiser, q['id'], tx, now_ms=NOW + 60_000)
    _record('exact payment confirms the booking', 'confirmed', done['state'], _row(suite, q['id']),
            PAID_STATES['confirmed'])
    day_clock = (int(_row(suite, q['id'])['day_ms']) + 3_600_000) / 1000
    slots = SponsoredSlots(store, taxonomy={'research', 'coding'}, regions={'US', 'KR'}, clock=lambda: day_clock)
    cards = slots.response('research', 'US', 'explore', 2)['cards']
    _record('the paid card is shown on its day', [campaign['id']], [c['id'] for c in cards])
    slots.flush_now()
    report = sponsored_report(store, suite.advertiser, now_ms=int(day_clock * 1000))
    _record('the advertiser report counts it', {'explore': 1, 'chat': 0}, report['totals'])
    listed = service.list_for(suite.advertiser)['items'][0]
    _record('the receipt carries the transaction hash and amount', (tx, q['amount_units']),
            (listed['tx_hash'], str(listed['amount_units'])))
    month = time.strftime('%Y-%m', time.gmtime((NOW + 60_000) / 1000))
    csv = service.monthly_csv(access, op, month)
    _record('the monthly export has the KRW rate and hash', True, tx in csv and ',1380.5,' in csv)
    service.settle_due(now_ms=int(_row(suite, q['id'])['day_ms']) + DAY_MS + 11 * 60_000)   # 10 min after the day
    _record('after the day the booking is settled as served', 'served', _row(suite, q['id'])['state'],
            _row(suite, q['id']), PAID_STATES['served'])


def _refund_path(world, booking_id):
    suite, service, _, _ = world
    access, op = suite.service.access, operator(suite)
    service.operator_decide(access, op, booking_id, action='refund')
    refund_tx = '0x' + 'b' * 64
    service.operator_decide(access, op, booking_id, action='refunded', refund_tx_hash=refund_tx)
    texts = [i['text'] for i in updates(suite.service.store, suite.advertiser)['items'] if i['kind'] == 'payment']
    return {'operator': 'refund -> refund_due -> refunded (user sends USDC by hand, records the hash)',
            'final_state': _row(suite, booking_id)['state'], 'advertiser_sees': texts[0] if texts else None}


@pytest.mark.parametrize('case,amount_delta,note', [('underpaid', -1, 'amount_mismatch'), ('overpaid', +1, 'amount_mismatch')])
def test_wrong_amount_goes_to_review_and_can_be_refunded(world, case, amount_delta, note):
    suite, service, rpc, _ = world
    q = quote(world)
    got = service.submit(suite.advertiser, q['id'], rpc.send(int(q['amount_units']) + amount_delta), now_ms=NOW + 60_000)
    row = _row(suite, q['id'])
    refund = _refund_path(world, q['id'])
    _record(case + ' payment goes to review', ('review', note, 'refunded'), (got['state'], row['note'], refund['final_state']),
            row, PAID_STATES['review'], refund)


def test_other_token_is_not_a_payment(world):
    suite, service, rpc, _ = world
    q = quote(world)
    with pytest.raises(ContractError) as error:
        service.submit(suite.advertiser, q['id'], rpc.send(int(q['amount_units']), token='0x' + '3' * 40),
                       now_ms=NOW + 60_000)
    row = _row(suite, q['id'])
    _record('another token is refused and the quote stays open', ('payment_not_found', 'quoted', None),
            (error.value.code, row['state'], row['tx_hash']), row,
            'The transfer is not USDC to the quoted address: no booking. Send the exact USDC amount before the quote '
            'expires; a token sent by mistake is returned by hand on request.')


def test_late_payment_goes_to_review_instead_of_an_error(world):
    suite, service, rpc, _ = world
    q = quote(world)
    after = int(q['expires_ms']) + 60_000
    got = service.submit(suite.advertiser, q['id'], rpc.send(int(q['amount_units'])), now_ms=after)
    row = _row(suite, q['id'])
    refund = _refund_path(world, q['id'])
    _record('payment after the quote expired is kept for review', ('review', 'late_payment', 'refunded'),
            (got['state'], row['note'], refund['final_state']), row, PAID_STATES['review'], refund)
    q2 = quote(world, region='KR')
    with pytest.raises(ContractError) as error:      # no money behind it: still an expired quote
        service.submit(suite.advertiser, q2['id'], '0x' + 'c' * 64, now_ms=int(q2['expires_ms']) + 60_000)
    _record('late submission without a payment stays expired', 'quote_expired', error.value.code)


def test_the_same_payment_cannot_book_twice(world):
    suite, service, rpc, _ = world
    q = quote(world)
    tx = rpc.send(int(q['amount_units']))
    service.submit(suite.advertiser, q['id'], tx, now_ms=NOW + 60_000)
    other = quote(world, region='KR')
    with pytest.raises(ContractError) as error:
        service.submit(suite.advertiser, other['id'], tx, now_ms=NOW + 60_000)
    again = service.submit(suite.advertiser, q['id'], tx, now_ms=NOW + 61_000)
    _record('one transaction pays one booking', ('payment_already_used', 'confirmed', 'quoted'),
            (error.value.code, again['state'], _row(suite, other['id'])['state']))


def test_sanctioned_payer_is_held_for_review_and_refunded_by_hand(world):
    suite, service, rpc, _ = world
    q = quote(world)
    got = service.submit(suite.advertiser, q['id'], rpc.send(int(q['amount_units']), sender='0x' + '9' * 40),
                         now_ms=NOW + 60_000)
    row = _row(suite, q['id'])
    _record('a payer on the sanctions list is held for review', ('review', 'sanctions_match'), (got['state'], row['note']),
            row, PAID_STATES['review'],
            {'operator': 'do not confirm; follow the sanctions procedure before any refund (docs runbook)'})
