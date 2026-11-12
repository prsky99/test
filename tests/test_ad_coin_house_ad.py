"""House ad (PM 11-11): issuance, application, review, approval, activation and one booking, idempotent."""
import time

from agent_market.ad_coin.v2 import points
from agent_market.ad_coin.v2.commercial import Commercial
from agent_market.ad_coin.v2.sponsored import SponsoredSlots
from agent_market.ad_coin.v2.sponsored_booking import DAY_MS
from scripts import ad_coin_house_ad as house
from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_persistence import store  # noqa: F401


def _commercial(store):  # noqa: F811
    store.migrate_model()
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    return Commercial(store, taxonomy=frozenset({'research', 'coding'}), regions=frozenset({'US', 'KR'}),
                      fresh_key=b'k' * 32, receipt_keys={'kid-house': Ed25519PrivateKey.generate()})


def test_house_ad_runs_once_and_shows_on_its_day(store):  # noqa: F811
    commercial = _commercial(store)
    now_ms = int(time.time() * 1000)
    tomorrow = time.strftime('%Y-%m-%d', time.gmtime((now_ms - now_ms % DAY_MS + DAY_MS) / 1000))
    month = time.strftime('%Y-%m', time.gmtime())
    with store.atomic():
        assert not store.one('commercial_control', ())['model_activation_enabled']
    first = house.run(commercial, month=month, issue_atoms=10_000 * points.ATOMS_PER_COIN, day=tomorrow, now_ms=now_ms)
    assert first['issuance']['replayed'] is False
    assert first['application']['status'] == 'approved'
    assert first['review']['state'] == 'eligible'
    assert first['campaign'] == {'id': first['campaign']['id'], 'state': 'active', 'approval_status': 'approved'}
    assert first['booking']['paid_by'] == 'growth_support' and first['booking']['replayed'] is False
    assert first['other_active_campaigns'] == []
    with store.atomic():
        assert store.one('commercial_control', ())['model_activation_enabled']
        events = {r['event_type'] for r in store.all('audit_for_target', (first['advertiser_id'],))}
    assert {'advertiser_applied', 'advertiser_approved'} <= events
    again = house.run(commercial, month=month, issue_atoms=10_000 * points.ATOMS_PER_COIN, day=tomorrow, now_ms=now_ms)
    assert again['issuance']['replayed'] and again['booking']['replayed'] and 'application' not in again
    assert again['campaign']['id'] == first['campaign']['id'] and 'review' not in again
    # the booked day shows the house card in the Sponsored area, never in rewarded-view offers
    slots = SponsoredSlots(store, taxonomy={'research', 'coding'}, regions={'US', 'KR'},
                           clock=lambda: (now_ms - now_ms % DAY_MS + DAY_MS + 3_600_000) / 1000)
    cards = slots.response('research', 'US', 'explore', 2)['cards']
    assert [c['advertiser'] for c in cards] == [house.HOUSE_NAME] and cards[0]['text'] == house.HOUSE_TEXT


def test_run_needs_the_approval_flag():
    import pytest
    with pytest.raises(SystemExit):
        house.main(['run', '--issue-coins', '10000', '--day', '2026-11-12', '--dsn-file', 'x', '--key-file', 'y',
                    '--key-dir', '/k'])


def test_daily_ledger_check_is_clean_after_the_house_ad(store):  # noqa: F811
    from scripts.ad_coin_daily_ledger_check import check
    commercial = _commercial(store)
    now_ms = int(time.time() * 1000)
    tomorrow = time.strftime('%Y-%m-%d', time.gmtime((now_ms - now_ms % DAY_MS + DAY_MS) / 1000))
    house.run(commercial, month=time.strftime('%Y-%m', time.gmtime()), issue_atoms=10_000 * points.ATOMS_PER_COIN,
              day=tomorrow, now_ms=now_ms)
    result = check(store)
    assert result['ok'] and result['status'] == 'clean' and result['issues'] == []


def test_house_ad_books_more_regions_with_free_coins_and_can_be_cancelled(store):  # noqa: F811
    """11-12 PM: add KR, JP, GB, DE for the house ad (free coins only), check first, cancel to free a slot."""
    commercial = _commercial(store)
    commercial.regions = frozenset({'US', 'KR', 'JP', 'GB', 'DE'})
    now_ms = int(time.time() * 1000)
    tomorrow = time.strftime('%Y-%m-%d', time.gmtime((now_ms - now_ms % DAY_MS + DAY_MS) / 1000))
    house.run(commercial, month=time.strftime('%Y-%m', time.gmtime()), issue_atoms=10_000 * points.ATOMS_PER_COIN,
              day=tomorrow, now_ms=now_ms)
    regions = ['KR', 'JP', 'GB', 'DE']
    plan = house.book_regions(commercial, day=tomorrow, regions=regions, check=True, now_ms=now_ms)
    assert not plan['written'] and [p['state'] for p in plan['plan']] == ['to_book'] * 4
    assert plan['top_up_atoms'] == str(4 * 50 * points.ATOMS_PER_COIN - int(plan['balance_atoms']))
    with store.atomic():
        assert int(store.one('sponsored_booking_day_count', (now_ms - now_ms % DAY_MS + DAY_MS, 'research', 'KR'))['n']) == 0
    done = house.book_regions(commercial, day=tomorrow, regions=regions, now_ms=now_ms)
    assert done['written'] and [b['region'] for b in done['bookings']] == regions
    assert all(b['state'] == 'booked' and b['paid_by'] == 'advertiser' for b in done['bookings'])
    again = house.book_regions(commercial, day=tomorrow, regions=regions, now_ms=now_ms)
    assert [p['state'] for p in again['plan']] == ['booked'] * 4 and not again['written']
    _, row, _ = house._house(store)
    with store.atomic():
        assert int(store.one('account_get', (row['available_account'],))['balance_atoms']) == 0
    day_clock = (now_ms - now_ms % DAY_MS + DAY_MS + 3_600_000) / 1000
    slots = SponsoredSlots(store, taxonomy={'research', 'coding'}, regions=set(regions) | {'US'}, clock=lambda: day_clock)
    for region in regions + ['US']:
        for placement in ('explore', 'chat'):
            assert [c['advertiser'] for c in slots.response('research', region, placement, 2, False)['cards']] == [house.HOUSE_NAME]
    undone = house.cancel_regions(commercial, day=tomorrow, regions=['GB'], now_ms=now_ms)
    assert [c['region'] for c in undone['cancelled']] == ['GB'] and undone['cancelled'][0]['state'] == 'refunded'
    with store.atomic():
        assert int(store.one('sponsored_booking_day_count', (now_ms - now_ms % DAY_MS + DAY_MS, 'research', 'GB'))['n']) == 0
        assert int(store.one('account_get', (row['available_account'],))['balance_atoms']) == 50 * points.ATOMS_PER_COIN
    from scripts.ad_coin_daily_ledger_check import check
    assert check(store)['ok']
