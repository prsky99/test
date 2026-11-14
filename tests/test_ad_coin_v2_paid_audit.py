"""F12 (PM 11-14): USDC payments after confirmation, without sending anything. Receipt block identifiers, the finality
watch (unsafe -> safe -> finalized), chain reorganisation, RPC outage, concurrent confirmation, late and wrong
payments, duplicate transactions, review resolution with reasons and an audit trail, and wrong refund records."""
import threading

import pytest

from agent_market.ad_coin.v2 import paid_audit
from agent_market.ad_coin.v2.contracts import ContractError
from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_paid_bookings import NOW, PAY_TO, PAYER, operator, quote, world  # noqa: F401
from tests.test_ad_coin_v2_persistence import store  # noqa: F401
from tests.test_ad_coin_v2_p1 import p1_suite  # noqa: F401

LATER = NOW + 60_000


@pytest.fixture
def audited(world):  # noqa: F811
    from scripts.ad_coin_v2_migrate import migrate_paid_events
    assert migrate_paid_events(world[0].service.store) == {'paid_events_table': True}
    return world


def events(store, booking_id, kind=None):
    with store.atomic():
        found = [dict(r) for r in store.all('paid_events_for', (booking_id,))]
    return [e for e in found if kind is None or e['kind'] == kind]


def row(store, booking_id):
    with store.atomic():
        return store.one('paid_booking_get', (booking_id,))


def paid(world, *, amount_delta=0, **send):  # noqa: F811
    suite, service, rpc, _ = world
    q = quote(world)
    tx = rpc.send(int(q['amount_units']) + amount_delta, **send)
    return q, tx, service.submit(suite.advertiser, q['id'], tx, now_ms=LATER)


def test_a_confirmed_payment_records_its_block_and_the_watch_follows_it_to_finalized(audited):
    suite, service, rpc, _ = audited
    store = suite.service.store
    q, tx, got = paid(audited)
    assert got['state'] == 'confirmed'
    [receipt] = events(store, q['id'])
    assert (receipt['kind'], int(receipt['block_number']), receipt['finality'], receipt['tx_hash']) == ('receipt', 90, 'unsafe', tx)
    assert receipt['block_hash'] == '0x%064x' % 90000
    rpc.safe = 95
    assert paid_audit.watch(service, now_ms=LATER + 1000)['checked'] == 1
    assert events(store, q['id'])[-1]['finality'] == 'safe'
    assert paid_audit.watch(service, now_ms=LATER + 2000)['checked'] == 1 and len(events(store, q['id'])) == 2   # no change, no row
    rpc.finalized = 92
    assert paid_audit.watch(service, now_ms=LATER + 3000)['finalized'] == 1
    assert events(store, q['id'])[-1]['finality'] == 'finalized'
    assert paid_audit.watch(service, now_ms=LATER + 4000)['checked'] == 0                         # finalized: no longer watched
    assert row(store, q['id'])['state'] == 'confirmed'


def test_reorg_that_drops_the_payment_sends_the_booking_to_review_and_off_the_slot(audited):
    suite, service, rpc, _ = audited
    store = suite.service.store
    q, tx, _ = paid(audited)
    del rpc.txs[tx]                                       # the block with the payment was reorganised away
    assert paid_audit.watch(service, now_ms=LATER + 5000)['missing_once'] == 1
    assert row(store, q['id'])['state'] == 'confirmed'    # one miss can be a lagging node: wait for a second read
    assert paid_audit.watch(service, now_ms=LATER + 6000)['reorg'] == 1
    booking = row(store, q['id'])
    assert (booking['state'], booking['note']) == ('review', 'reorg')
    assert events(store, q['id'])[-1]['kind'] == 'reorg' and events(store, q['id'])[-1]['to_state'] == 'review'
    with store.atomic():                                   # the paid slot shows only confirmed or served bookings
        shown = store.all('campaigns_sponsored_paid', (int(booking['day_ms']), int(booking['day_ms']), 10))
    assert [r for r in shown if r['id'] == booking['campaign_id']] == []


def test_a_payment_reincluded_in_another_block_keeps_its_state_and_records_the_new_block(audited):
    suite, service, rpc, _ = audited
    store = suite.service.store
    q, tx, _ = paid(audited)
    rpc.fork = 7                                           # same transaction, same transfer, another block hash
    assert paid_audit.watch(service, now_ms=LATER + 7000)['moved'] == 1
    last = events(store, q['id'])[-1]
    assert last['kind'] == 'reorg' and last['block_hash'] == '0x%064x' % 90007 and 'reincluded_from' in last['detail']
    assert row(store, q['id'])['state'] == 'confirmed'


def test_rpc_outage_never_confirms_never_reorgs_and_never_raises(audited):
    suite, service, rpc, _ = audited
    store = suite.service.store
    q, tx, _ = paid(audited)
    rpc.down = True
    assert paid_audit.watch(service, now_ms=LATER + 8000)['rpc_unavailable'] == 1
    assert row(store, q['id'])['state'] == 'confirmed' and len(events(store, q['id'])) == 1
    q2 = quote(audited, region='KR')
    tx2 = rpc.txs and None
    rpc.down = False
    tx2 = rpc.send(int(q2['amount_units']))
    rpc.down = True
    assert service.submit(suite.advertiser, q2['id'], tx2, now_ms=LATER)['state'] == 'confirming'   # waits, no error
    assert service.recheck(now_ms=LATER) == 0
    rpc.down = False
    service.recheck(now_ms=LATER)
    assert row(store, q2['id'])['state'] == 'confirmed' and events(store, q2['id'])[0]['kind'] == 'receipt'


def test_concurrent_confirmations_write_once_and_never_overwrite_an_operator(audited):
    suite, service, rpc, _ = audited
    store = suite.service.store
    q = quote(audited)
    tx = rpc.send(int(q['amount_units']))
    rpc.head = 91                                          # 2 confirmations: waits in confirming
    assert service.submit(suite.advertiser, q['id'], tx, now_ms=LATER)['state'] == 'confirming'
    rpc.head = 100
    results, start = [], threading.Barrier(4)

    def confirm():
        start.wait()
        results.append(service._check(q['id'], LATER)['state'])
    threads = [threading.Thread(target=confirm) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results == ['confirmed'] * 4
    assert [e['kind'] for e in events(store, q['id'])] == ['receipt']          # one confirmation, one receipt
    access, op = suite.service.access, operator(suite)
    service.operator_decide(access, op, q['id'], action='refund', reason='advertiser cancelled the day')
    assert service._check(q['id'], LATER)['state'] == 'refund_due'              # a late check cannot undo it


def test_late_payment_mismatch_and_duplicate_transactions(audited):
    suite, service, rpc, _ = audited
    store = suite.service.store
    late = quote(audited)
    tx = rpc.send(int(late['amount_units']))
    got = service.submit(suite.advertiser, late['id'], tx, now_ms=NOW + 31 * 60_000)     # after the 30 min quote
    assert got['state'] == 'review' and row(store, late['id'])['note'] == 'late_payment'
    assert events(store, late['id'])[0]['kind'] == 'receipt'
    wrong = quote(audited, region='KR')
    wrong_tx = rpc.send(int(wrong['amount_units']) - 1)
    assert service.submit(suite.advertiser, wrong['id'], wrong_tx, now_ms=LATER)['state'] == 'review'
    assert row(store, wrong['id'])['note'] == 'amount_mismatch' and events(store, wrong['id'])[0]['kind'] == 'receipt'
    another = quote(audited, region='US', day=NOW - NOW % 86_400_000 + 2 * 86_400_000)
    with pytest.raises(ContractError) as error:
        service.submit(suite.advertiser, another['id'], tx, now_ms=LATER)      # the same payment for a second booking
    assert error.value.code == 'payment_already_used'


def test_review_is_resolved_only_by_an_operator_with_a_reason_and_leaves_an_audit_trail(audited):
    from agent_market.ad_coin.sql_registry import unchecked
    suite, service, rpc, _ = audited
    store, access, op = suite.service.store, suite.service.access, operator(suite)
    q, tx, got = paid(audited, amount_delta=+1)
    assert got['state'] == 'review'
    with pytest.raises(ContractError) as error:
        service.operator_decide(access, op, q['id'], action='clear')                    # no reason
    assert error.value.code == 'invalid_reason'
    with pytest.raises(ContractError):
        service.operator_decide(access, op, q['id'], action='clear', reason='  x ')
    stranger = suite.principal('user') if hasattr(suite, 'principal') else None
    if stranger is not None:
        with pytest.raises(ContractError):
            service.operator_decide(access, stranger, q['id'], action='clear', reason='looks fine')
    assert service.operator_decide(access, op, q['id'], action='clear', reason='overpaid by 1 unit, accepted')['state'] == 'confirmed'
    decided = events(store, q['id'], 'operator')[-1]
    assert (decided['kind'], decided['from_state'], decided['to_state'], decided['reason']) == (
        'operator', 'review', 'confirmed', 'overpaid by 1 unit, accepted')
    assert decided['actor'] == 'operator:' + str(op.id)
    with unchecked(), store.atomic():
        audit = store.database.all("SELECT event_type, actor_principal_id, details_json FROM adc2_audit_log "
                                   "WHERE target_id=? AND event_type='paid_booking_clear'", (q['id'],))
    assert len(audit) == 1 and 'overpaid by 1 unit' in audit[0]['details_json']
    with pytest.raises(ContractError) as error:                                         # already decided
        service.operator_decide(access, op, q['id'], action='clear', reason='again')
    assert error.value.code == 'paid_booking_state_changed'


@pytest.mark.parametrize('case,code', [
    ('the payment itself', 'refund_is_the_payment'),
    ('to another wallet', 'refund_not_to_payer'),
    ('more than paid', 'refund_more_than_paid'),
    ('not on chain', 'refund_not_found'),
    ('failed transaction', 'refund_failed'),
    ('rpc down', 'refund_unverifiable'),
])
def test_a_wrong_refund_record_is_refused_and_the_booking_stays_refund_due(audited, case, code):
    suite, service, rpc, _ = audited
    store, access, op = suite.service.store, suite.service.access, operator(suite)
    q, tx, _ = paid(audited, amount_delta=-1)
    service.operator_decide(access, op, q['id'], action='refund', reason='underpaid, return it')
    amount = int(q['amount_units']) - 1
    refund = {'the payment itself': lambda: tx,
              'to another wallet': lambda: rpc.send(amount, sender=PAY_TO, to='0x' + '7' * 40),
              'more than paid': lambda: rpc.send(amount + 1, sender=PAY_TO, to=PAYER),
              'not on chain': lambda: '0x' + 'c' * 64,
              'failed transaction': lambda: rpc.send(amount, sender=PAY_TO, to=PAYER, status='0x0'),
              'rpc down': lambda: rpc.send(amount, sender=PAY_TO, to=PAYER)}[case]()
    service._network_ok = False
    rpc.down = case == 'rpc down'
    with pytest.raises(ContractError) as error:
        service.operator_decide(access, op, q['id'], action='refunded', refund_tx_hash=refund, reason='refund sent')
    assert error.value.code == code and error.value.status < 500
    rpc.down = False
    assert row(store, q['id'])['state'] == 'refund_due'
    good = rpc.send(amount, sender=PAY_TO, to=PAYER)
    assert service.operator_decide(access, op, q['id'], action='refunded', refund_tx_hash=good,
                                   reason='refund sent by the owner')['state'] == 'refunded'
    assert events(store, q['id'], 'operator')[-1]['detail'] in (
        '{"action": "refunded", "refund_units": %d}' % amount, '{"action": "refund"}')
    assert '{"action": "refunded", "refund_units": %d}' % amount in [e['detail'] for e in events(store, q['id'], 'operator')]


def test_before_the_events_table_payments_and_decisions_still_work(world):  # noqa: F811
    suite, service, rpc, _ = world
    store, access, op = suite.service.store, suite.service.access, operator(suite)
    q, tx, got = paid(world, amount_delta=+2)
    assert got['state'] == 'review'
    assert paid_audit.watch(service, now_ms=LATER + 9000)['checked'] == 0
    assert service.recheck(now_ms=LATER) == 0
    assert service.operator_decide(access, op, q['id'], action='clear', reason='accepted before migration')['state'] == 'confirmed'


def test_daily_reconciliation_matches_bookings_chain_receipts_impressions_and_the_export(audited):
    """scripts.ad_coin_paid_reconcile.reconcile on real rows: a clean day has no finding; each broken record is named."""
    from scripts.ad_coin_paid_reconcile import _export, reconcile
    suite, service, rpc, _ = audited
    store = suite.service.store
    good, good_tx, _ = paid(audited)
    day_ms = LATER - LATER % 86_400_000

    def rows():
        with store.atomic():
            return [dict(store.one('paid_booking_get', (i,))) for i in (good['id'],)]

    def run(**over):
        bookings = over.pop('bookings', None) or rows()
        with store.atomic():
            month = [dict(r) for r in store.all('paid_bookings_month', (day_ms - 40 * 86_400_000, day_ms + 40 * 86_400_000))]
            last = {b['id']: store.one('paid_event_last_block', (b['id'],))['block_hash'] for b in bookings}
        args = dict(receipts={t: rpc.receipt(t) for t in rpc.txs}, transfers=[(good_tx, PAYER, int(good['amount_units']))],
                    impressions={}, last_blocks=last, export_rows=_export(month), day_ms=day_ms)
        args.update(over)
        return reconcile(bookings, **args)

    counts, findings = run()
    assert findings == [] and counts['received'] == 1 and counts['transfers_in'] == 1
    stray = rpc.send(4_000_000)                                          # money in without any booking
    _, findings = run(transfers=[(good_tx, PAYER, int(good['amount_units'])), (stray, PAYER, 4_000_000)])
    assert [f['kind'] for f in findings] == ['receipt_without_booking'] and findings[0]['amount'] == '4.000000'
    _, findings = run(receipts={good_tx: None})
    assert [f['kind'] for f in findings] == ['payment_missing_on_chain']
    rpc.fork = 3
    _, findings = run()
    assert [f['kind'] for f in findings] == ['block_differs_from_record']
    rpc.fork = 0
    _, findings = run(export_rows=[])
    assert [f['kind'] for f in findings] == ['missing_from_monthly_export']
    _, findings = run(bookings=[{**rows()[0], 'krw_rate': None}])
    assert [f['kind'] for f in findings] == ['krw_rate_missing']
    placed = {**rows()[0], 'state': 'served', 'day_ms': day_ms}
    _, findings = run(bookings=[placed])
    assert [f['kind'] for f in findings] == ['served_without_impressions']
    _, findings = run(bookings=[placed], impressions={(day_ms, placed['campaign_id'], placed['task_category'],
                                                       placed['region']): 12})
    assert findings == []


def test_reconcile_finds_the_day_blocks_and_reads_transfers_in_chunks():
    from agent_market.chain import TRANSFER_TOPIC
    from scripts import ad_coin_paid_reconcile as rec

    class Chain:
        calls = []

        def block_number(self):
            return 1000

        def call(self, method, *params):
            self.calls.append(method)
            if method == 'eth_getBlockByNumber':
                return {'timestamp': hex(10_000 + 2 * int(params[0], 16))}     # one block every 2 s
            query = params[0]
            start, end = int(query['fromBlock'], 16), int(query['toBlock'], 16)
            return [{'transactionHash': '0x%064x' % n, 'topics': [TRANSFER_TOPIC, '0x' + '2' * 64, query['topics'][2]],
                     'data': hex(5_000_000)} for n in (start, end)]
    chain = Chain()
    assert rec.block_at(chain, 10_000 + 2 * 300) == 300 and rec.block_at(chain, 10_000 + 2 * 301 - 1) == 301
    old = rec.LOG_CHUNK
    rec.LOG_CHUNK = 100
    try:
        found = rec.transfers_to(chain, '0x' + '3' * 40, PAY_TO, 0, 249)
    finally:
        rec.LOG_CHUNK = old
    assert chain.calls.count('eth_getLogs') == 3 and len(found) == 6 and found[0][2] == 5_000_000


def test_night_rehearsal_checks_both_rollbacks_and_leaves_the_copy_migrated(store):  # noqa: F811
    """PM 11-14: the copy rehearsal also proves the paid-events rollback stops when the table holds rows."""
    from scripts.ad_coin_night_1115_rehearse import check_rollbacks
    from scripts.ad_coin_v2_migrate import migrate_agent_ads, migrate_impressions, migrate_paid, migrate_paid_events
    store.migrate_model()
    migrate_paid(store)
    migrate_impressions(store)
    migrate_agent_ads(store)
    assert migrate_paid_events(store) == {'paid_events_table': True}
    checks = check_rollbacks(store)
    assert checks == {'paid_events_rollback_stops_with_rows': True, 'paid_events_table_kept': True,
                      'paid_events_foreign_key_kept': True, 'paid_events_rollback_drops_when_empty': True,
                      'agent_ads_rollback_drops_tables': True, 'agent_ads_rollback_restores_check': True,
                      'left_migrated': True}
