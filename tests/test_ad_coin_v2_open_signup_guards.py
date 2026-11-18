"""Guards for open advertiser sign-up (PM 11:5x ①): free coins follow a first confirmed USDC payment, never approval,
and the free first coin booking goes only to an advertiser that received them."""
import time

from agent_market.ad_coin.v2 import points
from agent_market.ad_coin.v2.advertiser_applications import APPLIED, AuditLogger, welcome_after_payment
from agent_market.ad_coin.v2.economy import CoinEconomy
from agent_market.ad_coin.v2.sponsored_booking import SponsoredBookings
from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_persistence import store  # noqa: F401
from tests.test_ad_coin_v2_p1 import NOW, p1_suite  # noqa: F401
from tests.test_ad_coin_v2_paid_bookings import _no_operator_file, quote, world  # noqa: F401


def test_welcome_coins_and_first_booking_support_follow_a_confirmed_usdc_payment(world):  # noqa: F811
    suite, service, rpc, _ = world
    commercial = suite.service
    economy = CoinEconomy(commercial.store, commercial.ledger, commercial.access)
    points.issue(commercial.ledger, 1000 * points.ATOMS_PER_COIN, reason="guards-%d" % time.time_ns())
    coin = SponsoredBookings(commercial.store, commercial.ledger, taxonomy=commercial.taxonomy,
                             regions=commercial.regions, access=commercial.access)
    # the fixture advertiser is set up by an operator (no application, so no free-day guard); mark it as one that came through the
    # open application, the case this guard is about (night test 11-18: without this line the first assertion failed since 11-15)
    with commercial.store.atomic():
        AuditLogger.log(commercial.store, APPLIED, "succeeded", actor_principal_id=str(suite.advertiser),
                        target_id=suite.advertiser, details={"display_name": "Guard test", "flags": []})
    with commercial.store.atomic():
        assert not coin._support_allowed(suite.advertiser, NOW)            # a bare sign-up gets no free day
    assert welcome_after_payment(commercial.store, economy, suite.advertiser) is None   # nothing paid yet
    q = quote(world)
    assert welcome_after_payment(commercial.store, economy, suite.advertiser) is None   # a quote is not a payment
    service.submit(suite.advertiser, q['id'], rpc.send(int(q['amount_units'])), now_ms=NOW + 60_000)
    granted = welcome_after_payment(commercial.store, economy, suite.advertiser)
    assert granted is not None and int(granted['atoms']) > 0
    assert welcome_after_payment(commercial.store, economy, suite.advertiser) is None   # once
    with commercial.store.atomic():
        assert coin._support_allowed(suite.advertiser, NOW)
