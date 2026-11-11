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
