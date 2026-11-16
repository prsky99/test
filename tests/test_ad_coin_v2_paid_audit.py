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


def paid(world, *, amount_delta=0, late=False, **send):  # noqa: F811
    suite, service, rpc, _ = world
    q = quote(world)
    tx = rpc.send(int(q['amount_units']) + amount_delta, **send)
    return q, tx, service.submit(suite.advertiser, q['id'], tx, now_ms=NOW + 31 * 60_000 if late else LATER)


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
    # 11-16 source review: a second miss seconds later is not evidence; the advert keeps running
    assert paid_audit.watch(service, now_ms=LATER + 6000)['reorg'] == 0
    assert row(store, q['id'])['state'] == 'confirmed'
    assert paid_audit.watch(service, now_ms=LATER + 5000 + paid_audit.MISSING_GAP_MS)['reorg'] == 1
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
    rpc.down = False
    tx2 = rpc.send(int(q2['amount_units']))
    rpc.down = True
    service._network_ok = False
    with pytest.raises(ContractError) as error:                       # not attached while the chain cannot be read
        service.submit(suite.advertiser, q2['id'], tx2, now_ms=LATER)
    assert error.value.code == 'payment_not_seen_yet' and error.value.status < 500
    assert row(store, q2['id'])['tx_hash'] is None and service.recheck(now_ms=LATER) == 0
    rpc.down = False
    service._network_ok = False
    assert service.submit(suite.advertiser, q2['id'], tx2, now_ms=LATER)['state'] == 'confirmed'
    assert events(store, q2['id'])[0]['kind'] == 'receipt'


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
    with pytest.raises(ContractError) as error:                       # R32: another amount is never attached
        service.submit(suite.advertiser, wrong['id'], wrong_tx, now_ms=LATER)
    assert error.value.code == 'amount_mismatch' and row(store, wrong['id'])['tx_hash'] is None
    assert events(store, wrong['id']) == []
    another = quote(audited, region='US', day=NOW - NOW % 86_400_000 + 2 * 86_400_000)
    with pytest.raises(ContractError) as error:
        service.submit(suite.advertiser, another['id'], tx, now_ms=LATER)      # the same payment for a second booking
    assert error.value.code == 'payment_already_used'


def test_review_is_resolved_only_by_an_operator_with_a_reason_and_leaves_an_audit_trail(audited):
    from agent_market.ad_coin.sql_registry import unchecked
    suite, service, rpc, _ = audited
    store, access, op = suite.service.store, suite.service.access, operator(suite)
    q, tx, got = paid(audited, sender='0x' + '9' * 40)                                  # on the sanctions list
    assert got['state'] == 'review' and row(store, q['id'])['note'] == 'sanctions_match'
    assert events(store, q['id'], 'receipt')[0]['detail'].count('"sanctions": "match"') == 1
    queued = service.operator_queue(access, op)['items'][0]
    assert (queued['received_usdc'], queued['quoted_usdc'], queued['sanctions']) == (q['amount_usdc'], q['amount_usdc'], 'match')
    with pytest.raises(ContractError) as error:
        service.operator_decide(access, op, q['id'], action='clear')                    # no reason
    assert error.value.code == 'invalid_reason'
    with pytest.raises(ContractError):
        service.operator_decide(access, op, q['id'], action='clear', reason='  x ')
    stranger = suite.principal('user') if hasattr(suite, 'principal') else None
    if stranger is not None:
        with pytest.raises(ContractError):
            service.operator_decide(access, stranger, q['id'], action='clear', reason='looks fine')
    with pytest.raises(ContractError) as error:                       # R35: screened again, needs an explicit ack
        service.operator_decide(access, op, q['id'], action='clear', reason='looks fine to me')
    assert error.value.code == 'sanctions_review_required'
    with pytest.raises(ContractError) as error:
        service.operator_decide(access, op, q['id'], action='clear', reason='short', sanctions_ack=True)
    assert error.value.code == 'sanctions_review_required'
    why = 'false match: address checked by hand, accepted'
    assert service.operator_decide(access, op, q['id'], action='clear', reason=why, sanctions_ack=True)['state'] == 'confirmed'
    decided = events(store, q['id'], 'operator')[-1]
    assert (decided['kind'], decided['from_state'], decided['to_state'], decided['reason']) == (
        'operator', 'review', 'confirmed', why) and '"sanctions": "match"' in decided['detail']
    assert decided['actor'] == 'operator:' + str(op.id)
    with unchecked(), store.atomic():
        audit = store.database.all("SELECT event_type, actor_principal_id, details_json FROM adc2_audit_log "
                                   "WHERE target_id=? AND event_type='paid_booking_clear'", (q['id'],))
    assert len(audit) == 1 and 'false match' in audit[0]['details_json']
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
    ('from another wallet', 'refund_not_from_receiving_wallet'),
    ('before the payment', 'refund_before_payment'),
])
def test_a_wrong_refund_record_is_refused_and_the_booking_stays_refund_due(audited, case, code):
    suite, service, rpc, _ = audited
    store, access, op = suite.service.store, suite.service.access, operator(suite)
    q, tx, _ = paid(audited, late=True)                                   # late: review
    cap = service.operator_decide(access, op, q['id'], action='refund', reason='the day was taken, return it')
    amount = int(q['amount_units'])
    assert cap['refund_cap_usdc'] == q['amount_usdc']                     # R31: the cap is what arrived
    refund = {'the payment itself': lambda: tx,
              'to another wallet': lambda: rpc.send(amount, sender=PAY_TO, to='0x' + '7' * 40, block=95),
              'more than paid': lambda: rpc.send(amount + 1, sender=PAY_TO, to=PAYER, block=95),
              'not on chain': lambda: '0x' + 'c' * 64,
              'failed transaction': lambda: rpc.send(amount, sender=PAY_TO, to=PAYER, status='0x0', block=95),
              'rpc down': lambda: rpc.send(amount, sender=PAY_TO, to=PAYER, block=95),
              'from another wallet': lambda: rpc.send(amount, sender='0x' + '6' * 40, to=PAYER, block=95),
              'before the payment': lambda: rpc.send(amount, sender=PAY_TO, to=PAYER, block=80)}[case]()
    service._network_ok = False
    rpc.down = case == 'rpc down'
    with pytest.raises(ContractError) as error:
        service.operator_decide(access, op, q['id'], action='refunded', refund_tx_hash=refund, reason='refund sent')
    assert error.value.code == code and error.value.status < 500
    rpc.down = False
    assert row(store, q['id'])['state'] == 'refund_due'
    good = rpc.send(amount, sender=PAY_TO, to=PAYER, block=95)
    assert service.operator_decide(access, op, q['id'], action='refunded', refund_tx_hash=good,
                                   reason='refund sent by the owner')['state'] == 'refunded'
    other = quote(audited, region='KR')
    rpc_tx = rpc.send(int(other['amount_units']))
    service.submit(suite.advertiser, other['id'], rpc_tx, now_ms=NOW + 31 * 60_000)
    service.operator_decide(access, op, other['id'], action='refund', reason='the day was taken, return it')
    with pytest.raises(ContractError) as error:                          # one refund transaction, one booking
        service.operator_decide(access, op, other['id'], action='refunded', refund_tx_hash=good, reason='refund sent')
    assert error.value.code == 'refund_tx_already_used'
    assert '{"action": "refunded", "refund_units": %d}' % amount in [e['detail'] for e in events(store, q['id'], 'operator')]


def test_before_the_events_table_payments_and_decisions_still_work(world):  # noqa: F811
    suite, service, rpc, _ = world
    store, access, op = suite.service.store, suite.service.access, operator(suite)
    q, tx, got = paid(world, late=True)
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


def test_a_failing_finality_watch_is_logged_and_never_stops_confirmations(audited, monkeypatch, caplog):
    import logging
    suite, service, rpc, _ = audited
    q = quote(audited)
    tx = rpc.send(int(q['amount_units']))
    rpc.head = 91
    service.submit(suite.advertiser, q['id'], tx, now_ms=LATER)
    rpc.head = 100
    monkeypatch.setattr(paid_audit, 'watch', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')))
    caplog.set_level(logging.INFO)
    assert service.recheck(now_ms=LATER) == 1                                 # confirmed anyway
    assert any('Paid finality watch failed' in r.getMessage() for r in caplog.records)


def test_tail_amounts_are_not_reused_within_seven_days_and_open_bookings_are_capped(audited, monkeypatch):
    """R32/R34: a tail any booking of the last 7 days used is never quoted again; five open bookings per advertiser."""
    from agent_market.ad_coin.v2 import paid_bookings as pb
    suite, service, rpc, _ = audited
    first = quote(audited)
    tails = iter([int(first['amount_units']) - service.config.price_units - 1, 4242])
    monkeypatch.setattr(pb.secrets, 'randbelow', lambda n: next(tails))
    second = quote(audited, region='KR')
    assert second['amount_units'] != first['amount_units'] and int(second['amount_units']) == service.config.price_units + 4243
    monkeypatch.undo()
    today = NOW - NOW % 86_400_000
    for days in (2, 3, 4):                                    # five open quotes in all, on days with room
        quote(audited, region='US', day=today + days * 86_400_000)
    with pytest.raises(ContractError) as error:
        quote(audited, region='KR', day=today + 5 * 86_400_000)
    assert (error.value.code, error.value.status) == ('too_many_open_bookings', 409)


def test_a_confirming_booking_whose_sender_never_appeared_is_released_after_an_hour(audited):
    from agent_market.ad_coin.sql_registry import unchecked
    suite, service, rpc, _ = audited
    store = suite.service.store
    q = quote(audited)
    ghost = '0x' + 'e' * 64
    with unchecked(), store.atomic():                        # a confirming row from before R32 with no sender seen
        store._connection().execute("UPDATE adc2_paid_bookings SET state='confirming', tx_hash=? WHERE id=?", (ghost, q['id']))
    service.recheck(now_ms=int(q['expires_ms']) + 30 * 60_000)
    assert row(store, q['id'])['state'] == 'confirming'
    service.recheck(now_ms=int(q['expires_ms']) + 61 * 60_000)
    released = row(store, q['id'])
    assert (released['state'], released['tx_hash'], released['note']) == ('expired', None, 'no_payment_seen')


def test_a_confirming_payment_the_chain_never_showed_can_be_replaced(audited):
    from agent_market.ad_coin.sql_registry import unchecked
    suite, service, rpc, _ = audited
    store = suite.service.store
    q = quote(audited)
    ghost = '0x' + 'f' * 64
    with unchecked(), store.atomic():
        store._connection().execute("UPDATE adc2_paid_bookings SET state='confirming', tx_hash=? WHERE id=?", (ghost, q['id']))
    real = rpc.send(int(q['amount_units']))
    assert service.submit(suite.advertiser, q['id'], real, now_ms=LATER)['state'] == 'confirmed'
    assert row(store, q['id'])['tx_hash'] == real
    q2 = quote(audited, region='KR')
    shown = rpc.send(int(q2['amount_units']))
    rpc.head = 91
    service.submit(suite.advertiser, q2['id'], shown, now_ms=LATER)                 # confirming, sender seen
    with pytest.raises(ContractError) as error:
        service.submit(suite.advertiser, q2['id'], rpc.send(int(q2['amount_units'])), now_ms=LATER)
    assert error.value.code == 'payment_already_submitted'


def test_a_receipt_counts_only_when_two_public_nodes_agree():
    from agent_market.ad_coin.v2.paid_bookings import AgreeingRPC

    class Node:
        def __init__(self, block_hash=None, fail=False):
            self.block_hash, self.fail = block_hash, fail

        def receipt(self, tx):
            if self.fail:
                raise RuntimeError('down')
            return None if self.block_hash is None else {'blockHash': self.block_hash, 'status': '0x1'}

        def block_number(self):
            return 7
    assert AgreeingRPC(Node('0xaa'), Node('0xAA')).receipt('t')['blockHash'] == '0xaa'
    assert AgreeingRPC(Node('0xaa'), Node('0xbb')).receipt('t') is None
    assert AgreeingRPC(Node('0xaa'), Node(None)).receipt('t') is None
    assert AgreeingRPC(Node(None), Node('0xaa')).receipt('t') is None
    with pytest.raises(RuntimeError):
        AgreeingRPC(Node('0xaa'), Node(fail=True)).receipt('t')     # verify_transfer reads this as 'not yet'
    assert AgreeingRPC(Node(), Node()).block_number() == 7


def test_clearing_fills_a_missing_krw_rate_or_refuses(audited):
    suite, service, rpc, _ = audited
    store, access, op = suite.service.store, suite.service.access, operator(suite)
    service.krw_rate = lambda: None
    q, tx, got = paid(audited)
    assert got['state'] == 'review' and row(store, q['id'])['note'] == 'krw_rate_unavailable'
    with pytest.raises(ContractError) as error:
        service.operator_decide(access, op, q['id'], action='clear', reason='rate came back')
    assert error.value.code == 'krw_rate_unavailable'
    service.krw_rate = lambda: '1391.0'
    assert service.operator_decide(access, op, q['id'], action='clear', reason='rate came back')['state'] == 'confirmed'
    assert row(store, q['id'])['krw_rate'] == '1391.0'


def test_reconciliation_notices_a_changed_receive_address_without_writing_it(tmp_path):
    from scripts.ad_coin_paid_reconcile import address_change, reconcile
    state = tmp_path / 'receive-address.json'
    finding, first = address_change(PAY_TO, state)
    assert finding is None and PAY_TO[2:] not in str(first)                  # a short hash, never the address
    state.write_text(__import__('json').dumps(first))
    assert address_change(PAY_TO, state)[0] is None
    finding, _ = address_change('0x' + '5' * 40, state)
    assert finding['kind'] == 'receive_address_changed' and finding['from'] == first['sha']
    booking = {'id': 'b1', 'state': 'confirmed', 'confirmed_ms': NOW, 'tx_hash': None, 'amount_units': 1,
               'pay_to': '0x' + '5' * 40, 'krw_rate': '1', 'day_ms': 0, 'token': '0x' + '3' * 40, 'payer': PAYER,
               'campaign_id': 'c', 'task_category': 'research', 'region': 'US'}
    _, findings = reconcile([booking], receipts={}, transfers=[], impressions={}, last_blocks={},
                            export_rows=[{'booking_id': 'b1', 'amount_usdc': '0.000001', 'tx_hash': ''}],
                            day_ms=NOW - NOW % 86_400_000, pay_to=PAY_TO)
    assert 'booking_to_other_receive_address' in [f['kind'] for f in findings]


def test_a_receipt_that_comes_back_within_the_gap_keeps_the_booking(audited):
    """11-16 source review: a public node answering null for a moment never stops a paid advert."""
    suite, service, rpc, _ = audited
    store = suite.service.store
    q, tx, _ = paid(audited)
    kept = rpc.txs.pop(tx)
    assert paid_audit.watch(service, now_ms=LATER + 5000)['missing_once'] == 1
    assert paid_audit.watch(service, now_ms=LATER + 10_000)['reorg'] == 0
    rpc.txs[tx] = kept                                     # the node answers again
    paid_audit.watch(service, now_ms=LATER + 15_000)
    assert paid_audit.watch(service, now_ms=LATER + 5000 + paid_audit.MISSING_GAP_MS + 1)['reorg'] == 0
    assert row(store, q['id'])['state'] == 'confirmed'
