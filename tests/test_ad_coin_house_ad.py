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


# ---- daily D+1/D+2 booking (docs/AD_COIN_HOUSE_AD_DAILY.md, user approval 11-12): D1-D7 and the stop rules ----

def _clean(store):  # noqa: F811
    from scripts.ad_coin_daily_ledger_check import check
    return check(store)


def _daily_world(store, issue_coins=10_000):  # noqa: F811
    commercial = _commercial(store)
    commercial.regions = frozenset(house.DAILY_REGIONS)
    now_ms = int(time.time() * 1000)
    tomorrow = time.strftime('%Y-%m-%d', time.gmtime((now_ms - now_ms % DAY_MS + DAY_MS) / 1000))
    house.run(commercial, month=time.strftime('%Y-%m', time.gmtime()), issue_atoms=issue_coins * points.ATOMS_PER_COIN,
              day=tomorrow, now_ms=now_ms)
    return commercial, now_ms


def _count_booked(store, day):  # noqa: F811
    from agent_market.ad_coin.v2.sponsored_booking import day_ms_of
    with store.atomic():
        return sum(int(store.one('sponsored_booking_day_count', (day_ms_of(day), 'research', r))['n'])
                   for r in house.DAILY_REGIONS)


def test_daily_fills_both_days_once_and_keeps_the_ledger_clean(store):  # noqa: F811  D1, D7
    commercial, now_ms = _daily_world(store)
    first = house.daily(commercial, enabled=True, ledger_check=_clean, now_ms=now_ms)
    assert first['stopped'] is None and not first['alert'] and first['ledger_after']
    for day in first['days']:
        assert _count_booked(store, day) == 5
    for result in first['results']:
        assert int(result.get('top_up', {}).get('atoms', '0')) <= 1_000 * points.ATOMS_PER_COIN   # grant cap
    again = house.daily(commercial, enabled=True, ledger_check=_clean, now_ms=now_ms)
    assert all(not r['written'] for r in again['results'])                                     # nothing written
    assert again['growth_atoms_after'] == first['growth_atoms_after']


def test_daily_closes_a_missed_day(store):  # noqa: F811  D2
    commercial, now_ms = _daily_world(store)
    house.daily(commercial, enabled=True, ledger_check=_clean, now_ms=now_ms)               # books D+1, D+2
    later = now_ms + 2 * DAY_MS                                                              # one run missed
    result = house.daily(commercial, enabled=True, ledger_check=_clean, now_ms=later)
    for day in result['days']:                                                              # D+3, D+4 from the start
        assert _count_booked(store, day) == 5


def test_daily_stops_when_the_growth_budget_is_low(store):  # noqa: F811  D3
    commercial, now_ms = _daily_world(store, issue_coins=1_800)       # 1800 - 100 welcome - 50 support = 1650
    result = house.daily(commercial, enabled=True, ledger_check=_clean, now_ms=now_ms)
    assert result['stopped'] == 'growth_budget_low' and result['alert']
    assert all(not r['written'] for r in result['results'])
    assert _count_booked(store, result['days'][1]) == 0


def test_daily_stops_when_the_ledger_is_not_clean(store):  # noqa: F811  D4
    commercial, now_ms = _daily_world(store)
    result = house.daily(commercial, enabled=True, ledger_check=lambda s: {'ok': False}, now_ms=now_ms)
    assert result['stopped'] == 'ledger_not_clean' and result['alert']
    assert _count_booked(store, result['days'][1]) == 0


def test_daily_with_the_switch_off_only_plans(store):  # noqa: F811  D5
    commercial, now_ms = _daily_world(store)
    result = house.daily(commercial, enabled=False, ledger_check=_clean, now_ms=now_ms)
    assert result['stopped'] == 'switch_off' and not result['alert']
    assert [len(r['plan']) for r in result['results']] == [5, 5] and _count_booked(store, result['days'][1]) == 0


def test_daily_skips_a_full_region_and_books_the_rest(store, monkeypatch):  # noqa: F811  D6
    commercial, now_ms = _daily_world(store)
    real = commercial.store.one

    def one(name, args=(), **kw):
        if name == 'sponsored_booking_day_count' and args[2] == 'KR':
            return {'n': 2}                                        # KR already holds both placements
        return real(name, args, **kw)
    monkeypatch.setattr(commercial.store, 'one', one)
    result = house.daily(commercial, enabled=True, ledger_check=lambda s: {'ok': True}, now_ms=now_ms)
    day2 = result['results'][1]
    assert {p['region']: p['state'] for p in day2['plan']}['KR'] == 'full'
    assert sorted(b['region'] for b in day2['bookings']) == ['DE', 'GB', 'JP', 'US']


def test_daily_stops_without_exactly_one_active_house_campaign(store):  # noqa: F811
    commercial = _commercial(store)                                # no house advertiser at all
    result = house.daily(commercial, enabled=True, ledger_check=_clean)
    assert result['stopped'] == 'house_campaign_not_single' and result['alert'] and result['results'] == []


def test_daily_switch_is_its_own_file_not_read_by_the_services(tmp_path):
    (tmp_path / 'gateway-data').mkdir()
    env = tmp_path / 'gateway-data/house-ad.env'
    assert house._switch_on(str(tmp_path)) is False                # no file: off
    env.write_text('# daily house ad\nAD_COIN_HOUSE_AD_DAILY=0\n')
    assert house._switch_on(str(tmp_path)) is False
    env.write_text('# daily house ad\nAD_COIN_HOUSE_AD_DAILY=1\n')
    assert house._switch_on(str(tmp_path)) is True
    from scripts.agentcon_config import SPONSORED_KEYS, ALLOWED_KEYS
    assert 'AD_COIN_HOUSE_AD_DAILY' not in SPONSORED_KEYS | ALLOWED_KEYS   # services never see this name


def test_rebrand_moves_future_bookings_to_an_agentvalcon_campaign(store, monkeypatch):  # noqa: F811
    """11-14 PM: approved campaigns cannot be revised, so rebrand launches a new campaign, moves every future
    house booking to it and pauses the old one; no placement is held twice and the ledger stays clean."""
    monkeypatch.setattr(house, 'HOUSE_NAME', house.LEGACY_HOUSE_NAME)
    commercial, now_ms = _daily_world(store)                          # legacy-named house ad, D+1 booked (US)
    house.daily(commercial, enabled=True, ledger_check=_clean, now_ms=now_ms)   # D+1, D+2 in 5 regions
    monkeypatch.undo()
    plan = house.rebrand(commercial, check=True, now_ms=now_ms)
    assert not plan['written'] and len(plan['future_bookings']) == 10
    done = house.rebrand(commercial, now_ms=now_ms)
    assert done['written'] and done['new_campaign']['name'] == 'AgentValCon' and done['old_campaign']['state'] == 'paused'
    assert len(done['moved']) == 10 and all(m['state'] == 'booked' for m in done['moved'])
    advertiser, _, active = house._house(store)
    assert active == done['new_campaign']['id']
    for day in {m['day'] for m in done['moved']}:
        assert _count_booked(store, day) == 5                           # one placement per region, not two
    day_clock = (now_ms - now_ms % DAY_MS + DAY_MS + 3_600_000) / 1000
    slots = SponsoredSlots(store, taxonomy={'research', 'coding'}, regions=set(house.DAILY_REGIONS), clock=lambda: day_clock)
    cards = slots.response('research', 'KR', 'explore', 2, False)['cards']
    assert [c['advertiser'] for c in cards] == ['AgentValCon'] and 'real tasks' in cards[0]['text']
    assert _clean(store)['ok']
    assert house.rebrand(commercial, now_ms=now_ms)['stopped'] == 'already_AgentValCon'
    again = house.daily(commercial, enabled=True, ledger_check=_clean, now_ms=now_ms)
    assert again['stopped'] is None and all(not r['written'] for r in again['results'])
