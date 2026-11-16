"""Custom Sponsored plans paid in USDC (user decision 11-15, PM 11:3x): a budget becomes 2-3 proposed plans, one
plan is paid once, its placements are ordinary paid placements and the payment is one line in the tax export."""
import time

import pytest

from agent_market.ad_coin.v2 import paid_plans as plans_mod
from agent_market.ad_coin.v2.contracts import ContractError
from agent_market.ad_coin.v2.sponsored_booking import DAY_MS
from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_persistence import store  # noqa: F401
from tests.test_ad_coin_v2_p1 import NOW, p1_suite  # noqa: F401
from tests.test_ad_coin_v2_paid_bookings import PAYER, _no_operator_file, operator, quote, world  # noqa: F401

TODAY = NOW - NOW % DAY_MS


def day(offset):
    return time.strftime('%Y-%m-%d', time.gmtime((TODAY + offset * DAY_MS) / 1000))


@pytest.fixture
def planned(world):  # noqa: F811
    from scripts.ad_coin_v2_migrate import migrate_paid_plans
    suite, service, rpc, campaign = world
    assert migrate_paid_plans(suite.service.store) == {'paid_plans_tables': True}
    return suite, plans_mod.PaidPlans(service), rpc, campaign


def test_pricing_rounds_down_and_discount_steps_are_a_setting():
    assert plans_mod.affordable(23_000_000, 5_000_000) == (4, 5_000_000, 0)        # 3 USDC left over is not charged
    steps = ((10, 500), (30, 1000))
    assert plans_mod.affordable(48_000_000, 5_000_000, steps) == (10, 4_750_000, 500)
    assert plans_mod.affordable(150_000_000, 5_000_000, steps)[0] == 33
    with pytest.raises(ContractError):
        plans_mod._units('12.345')
    assert plans_mod._units('12.5') == 12_500_000 and plans_mod._units(20) == 20_000_000


def test_options_fit_the_budget_and_work_before_the_tables_exist(world):  # noqa: F811
    suite, service, _, campaign = world
    plans = plans_mod.PaidPlans(service)
    found = plans.options(suite.advertiser, campaign_id=campaign['id'], budget_usdc='23', categories=['research', 'coding'],
                          regions=['US'], now_ms=NOW)
    assert found['budget_usdc'] == '23' and found['unit_usdc'] == '5' and 2 <= len(found['plans']) <= 3
    for plan in found['plans']:
        assert plan['placements'] == 4 and plan['total_usdc'] == '20' and len(plan['items']) == 4
        assert len({(i['day'], i['task_category'], i['region']) for i in plan['items']}) == 4
    kinds = {p['plan']: p for p in found['plans']}
    assert {i['task_category'] for i in kinds['focus']['items']} == {'research'}      # one audience, every day
    assert {i['task_category'] for i in kinds['spread']['items']} == {'research', 'coding'}
    with pytest.raises(ContractError) as low:
        plans.options(suite.advertiser, campaign_id=campaign['id'], budget_usdc='9', categories=['research'],
                      regions=['US'], now_ms=NOW)
    assert low.value.code == 'budget_below_minimum'
    with pytest.raises(ContractError) as closed:                      # quoting waits for migrate-paid-plans
        plans.quote(suite.advertiser, campaign_id=campaign['id'], items=found['plans'][0]['items'], now_ms=NOW)
    assert closed.value.code == 'plans_not_open'


def test_a_plan_is_paid_once_and_its_placements_confirm_together(planned):
    suite, plans, rpc, campaign = planned
    items = [{'day': day(1), 'task_category': 'research', 'region': 'US'},
             {'day': day(2), 'task_category': 'research', 'region': 'US'},
             {'day': day(2), 'task_category': 'coding', 'region': 'KR'}]
    q = plans.quote(suite.advertiser, campaign_id=campaign['id'], items=items, now_ms=NOW)
    amount = int(q['amount_units'])
    assert q['state'] == 'quoted' and q['placements'] == 3 and 15_000_001 <= amount <= 15_009_999
    assert [i['state'] for i in q['items']] == ['quoted'] * 3
    store = suite.service.store
    with store.atomic():                                              # the days are held like any quote
        assert int(store.one('paid_bookings_day_count', (TODAY + DAY_MS, 'research', 'US'))['n']) == 1
    with pytest.raises(ContractError) as short:
        plans.submit(suite.advertiser, q['id'], rpc.send(15_000_000), now_ms=NOW + 60_000)
    assert short.value.code == 'amount_mismatch'
    tx = rpc.send(amount)
    done = plans.submit(suite.advertiser, q['id'], tx, now_ms=NOW + 60_000)
    assert done['state'] == 'confirmed' and done['tx_hash'] == tx
    assert [i['state'] for i in done['items']] == ['confirmed'] * 3
    with store.atomic():
        rows = store.all('paid_plan_items', (q['id'],))
        assert {r['payer'] for r in rows} == {PAYER} and all(r['tx_hash'] is None for r in rows)
        assert {int(r['amount_units']) for r in rows} == {5_000_000}
    with pytest.raises(ContractError) as reused:                      # the plan's tx pays nothing else
        plans._refuse_used(tx, 'another-plan')
    assert reused.value.code == 'payment_already_used'


def test_a_full_day_or_a_repeated_placement_is_refused(planned, world):  # noqa: F811
    suite, plans, rpc, campaign = planned
    for region in ('US', 'US'):
        quote(world, region=region)                                    # two single quotes fill day 1 research/US
    items = [{'day': day(1), 'task_category': 'research', 'region': 'US'},
             {'day': day(3), 'task_category': 'research', 'region': 'US'}]
    with pytest.raises(ContractError) as full:
        plans.quote(suite.advertiser, campaign_id=campaign['id'], items=items, now_ms=NOW)
    assert full.value.code == 'sponsored_day_full'
    with pytest.raises(ContractError) as twice:
        plans.quote(suite.advertiser, campaign_id=campaign['id'], items=[items[1], items[1]], now_ms=NOW)
    assert twice.value.code == 'invalid_plan'


def test_waiting_for_confirmations_keeps_the_days_and_the_worker_confirms(planned):
    suite, plans, rpc, campaign = planned
    items = [{'day': day(4), 'task_category': 'research', 'region': 'US'},
             {'day': day(5), 'task_category': 'research', 'region': 'US'}]
    q = plans.quote(suite.advertiser, campaign_id=campaign['id'], items=items, now_ms=NOW)
    tx = rpc.send(int(q['amount_units']), block=99)                    # head 100: two confirmations of three
    waiting = plans.submit(suite.advertiser, q['id'], tx, now_ms=NOW + 60_000)
    assert waiting['state'] == 'confirming' and [i['state'] for i in waiting['items']] == ['quoted'] * 2
    later = NOW + plans_mod.QUOTE_TTL_MS + 30 * 60_000                 # past the quote, inside the hold
    rpc.head = 105
    assert plans.recheck(now_ms=later) == 1
    assert plans.get(suite.advertiser, q['id'])['state'] == 'confirmed'


def test_the_tax_export_has_one_line_per_payment(planned, world):  # noqa: F811
    suite, plans, rpc, campaign = planned
    service = world[1]
    single = quote(world, region='KR')
    service.submit(suite.advertiser, single['id'], rpc.send(int(single['amount_units'])), now_ms=NOW + 60_000)
    items = [{'day': day(6), 'task_category': 'research', 'region': 'US'},
             {'day': day(7), 'task_category': 'research', 'region': 'US'}]
    q = plans.quote(suite.advertiser, campaign_id=campaign['id'], items=items, now_ms=NOW)
    plans.submit(suite.advertiser, q['id'], rpc.send(int(q['amount_units'])), now_ms=NOW + 60_000)
    month = time.strftime('%Y-%m', time.gmtime((NOW + 60_000) / 1000))
    lines = service.monthly_csv(suite.service.access, operator(suite), month).splitlines()
    assert lines[0].endswith(',kind') and len(lines) == 3
    kinds = sorted(line.split(',')[-1] for line in lines[1:])
    assert kinds == ['booking', 'plan']
    plan_line = [line for line in lines[1:] if line.endswith(',plan')][0]
    assert q['amount_usdc'] in plan_line and '1380.5' in plan_line


def test_reconciliation_checks_the_plan_payment_not_its_placements():
    from scripts.ad_coin_paid_reconcile import reconcile
    pay_to, token, tx = '0x' + '1' * 40, '0x' + '3' * 40, '0x' + 'ab' * 32
    day_ms = TODAY + DAY_MS
    plan = {'id': 'p1', 'state': 'confirmed', 'confirmed_ms': day_ms + 1000, 'tx_hash': tx, 'amount_units': 10_004_321,
            'pay_to': pay_to, 'krw_rate': '1380', 'token': token, 'payer': PAYER}
    item = {'id': 'b1', 'state': 'confirmed', 'confirmed_ms': day_ms + 1000, 'tx_hash': None, 'amount_units': 5_000_000,
            'pay_to': pay_to, 'krw_rate': '1380', 'day_ms': day_ms + DAY_MS, 'token': token, 'payer': PAYER,
            'campaign_id': 'c', 'task_category': 'research', 'region': 'US'}
    receipt = {'status': '0x1', 'blockHash': '0x01', 'logs': [{'address': token, 'topics': [
        '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef', '0x' + PAYER[2:].rjust(64, '0'),
        '0x' + pay_to[2:].rjust(64, '0')], 'data': hex(10_004_321)}]}
    counts, findings = reconcile([item], receipts={tx: receipt}, transfers=[(tx, PAYER, 10_004_321)], impressions={},
                                 last_blocks={}, export_rows=[{'booking_id': 'p1', 'amount_usdc': '10.004321', 'tx_hash': tx}],
                                 day_ms=day_ms, pay_to=pay_to, plans=[plan])
    assert findings == [] and counts['received'] == 1 and counts['received_units'] == 10_004_321


# ---- 11-16 source review ---------------------------------------------------------------------------------------
def _two_days(start=8):
    return [{'day': day(start), 'task_category': 'research', 'region': 'US'},
            {'day': day(start + 1), 'task_category': 'research', 'region': 'US'}]


def test_a_missing_krw_rate_is_retried_by_the_worker_and_the_plan_confirms(planned):
    suite, plans, rpc, campaign = planned
    q = plans.quote(suite.advertiser, campaign_id=campaign['id'], items=_two_days(), now_ms=NOW)
    plans.bookings.krw_rate = lambda: None
    held = plans.submit(suite.advertiser, q['id'], rpc.send(int(q['amount_units'])), now_ms=NOW + 60_000)
    assert held['state'] == 'review' and [i['state'] for i in held['items']] == ['quoted'] * 2   # days still held
    assert plans.retry_krw(now_ms=NOW + 120_000) == 0
    plans.bookings.krw_rate = lambda: '1380.5'
    assert plans.retry_krw(now_ms=NOW + 180_000) == 1
    done = plans.get(suite.advertiser, q['id'])
    assert done['state'] == 'confirmed' and [i['state'] for i in done['items']] == ['confirmed'] * 2


def test_a_missing_krw_rate_on_a_booking_is_retried_too(world):  # noqa: F811
    suite, service, rpc, _ = world
    q = quote(world)
    service.krw_rate = lambda: None
    assert service.submit(suite.advertiser, q['id'], rpc.send(int(q['amount_units'])), now_ms=NOW + 60_000)['state'] == 'review'
    service.krw_rate = lambda: '1380.5'
    assert service.retry_krw(now_ms=NOW + 120_000) == 1
    with suite.service.store.atomic():
        row = suite.service.store.one('paid_booking_get', (q['id'],))
    assert row['state'] == 'confirmed' and row['krw_rate'] == '1380.5'


def test_an_operator_can_refund_a_plan_and_record_the_refund(planned):
    from tests.test_ad_coin_v2_paid_bookings import PAY_TO
    suite, plans, rpc, campaign = planned
    q = plans.quote(suite.advertiser, campaign_id=campaign['id'], items=_two_days(10), now_ms=NOW)
    plans.submit(suite.advertiser, q['id'], rpc.send(int(q['amount_units'])), now_ms=NOW + 60_000)
    op, access = operator(suite), suite.service.access
    refund = plans.operator_decide(access, op, q['id'], action='refund', reason='campaign withdrawn', now_ms=NOW + 70_000)
    assert refund['state'] == 'refund_due' and {i['state'] for i in refund['items']} == {'refund_due'}
    assert [p['id'] for p in plans.operator_queue(access, op)['items']] == [q['id']]
    back = rpc.send(int(q['amount_units']), sender=PAY_TO, to=PAYER, block=95)
    with pytest.raises(ContractError) as wrong:
        plans.operator_decide(access, op, q['id'], action='refunded', refund_tx_hash='0x' + '0' * 64, reason='sent back')
    assert wrong.value.code in ('refund_not_found', 'refund_unverifiable')
    done = plans.operator_decide(access, op, q['id'], action='refunded', refund_tx_hash=back, reason='sent back')
    assert done['state'] == 'refunded' and {i['state'] for i in done['items']} == {'refunded'}
    assert plans.operator_queue(access, op)['items'] == []


def test_a_plan_payment_is_watched_until_final_and_two_misses_need_ten_minutes(planned):
    from agent_market.ad_coin.v2 import paid_audit
    from scripts.ad_coin_v2_migrate import migrate_paid_events
    suite, plans, rpc, campaign = planned
    migrate_paid_events(suite.service.store)
    q = plans.quote(suite.advertiser, campaign_id=campaign['id'], items=_two_days(12), now_ms=NOW)
    tx = rpc.send(int(q['amount_units']))
    plans.submit(suite.advertiser, q['id'], tx, now_ms=NOW + 60_000)
    assert plans.watch(now_ms=NOW + 70_000)['checked'] == 1
    del rpc.txs[tx]
    plans.watch(now_ms=NOW + 80_000)
    assert plans.watch(now_ms=NOW + 85_000)['reorg'] == 0                          # seconds apart: not evidence
    assert plans.get(suite.advertiser, q['id'])['state'] == 'confirmed'
    assert plans.watch(now_ms=NOW + 80_000 + paid_audit.MISSING_GAP_MS)['reorg'] == 1
    gone = plans.get(suite.advertiser, q['id'])
    assert gone['state'] == 'review' and {i['state'] for i in gone['items']} == {'review'}


def test_one_transaction_pays_one_thing_across_bookings_and_plans(planned, world):  # noqa: F811
    from agent_market.ad_coin.v2.paid_bookings import tx_used_elsewhere
    suite, plans, rpc, campaign = planned
    service = world[1]
    single = quote(world, region='KR')
    booking_tx = rpc.send(int(single['amount_units']))
    service.submit(suite.advertiser, single['id'], booking_tx, now_ms=NOW + 60_000)
    q = plans.quote(suite.advertiser, campaign_id=campaign['id'], items=_two_days(14), now_ms=NOW)
    with pytest.raises(ContractError) as reused:
        plans.submit(suite.advertiser, q['id'], booking_tx, now_ms=NOW + 60_000)
    assert reused.value.code == 'payment_already_used'
    plan_tx = rpc.send(int(q['amount_units']))
    plans.submit(suite.advertiser, q['id'], plan_tx, now_ms=NOW + 60_000)
    with suite.service.store.atomic():
        assert tx_used_elsewhere(suite.service.store, plan_tx) and tx_used_elsewhere(suite.service.store, booking_tx)
        assert not tx_used_elsewhere(suite.service.store, plan_tx, plan_id=q['id'])


def test_krw_is_exact_decimal_arithmetic():
    from agent_market.ad_coin.v2.paid_bookings import krw_value
    assert krw_value('1380.5', 5_004_217) == '6908'            # 6908.32: no float drift
    assert krw_value('1391.05', 10_000_001) == '13911'          # 13910.51 rounds half up
    assert krw_value('1000', 500_000) == '500'
