"""Workflow team 11-18 (PM decision: the necklace gate becomes a connection test): a live entry with entry['connect'] is offered when the last
daily connection run passed and is recent; delta and a retest are not asked of it. Without 'connect' the old live rule stands."""
from datetime import datetime, timedelta, timezone

from agent_market.concierge import necklace_surface as ns
from tests.test_necklace_surface import iso, necklace

NOW = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)


def live(connect=None, **extra):
    entry = necklace('topic-evidence-brief', gate_passed_at=iso(NOW - timedelta(hours=5)), quality=None, **extra)
    if connect is not None:
        entry['connect'] = connect
    return entry


def block(hours_ago=3, ok=True):
    return {'passed_at': iso(NOW - timedelta(hours=30)), 'last_at': iso(NOW - timedelta(hours=hours_ago)), 'last_ok': ok}


def test_a_connection_gated_live_necklace_runs_without_a_delta_or_a_retest():
    assert ns.offered(live(block()), NOW)
    assert not ns.offered(live(), NOW)                                       # no connect block and no quality: the old rule refuses it
    assert not ns.offered(live(block(ok=False)), NOW)                        # the last daily run failed
    assert not ns.offered(live(block(hours_ago=ns.FRESH_HOURS + 1)), NOW)    # the daily run is too old
    assert not ns.offered(live({'passed_at': iso(NOW), 'last_ok': True}), NOW)   # no last run time
    assert not ns.offered(live({'passed_at': iso(NOW), 'last_at': 'soon', 'last_ok': True}), NOW)
    assert not ns.offered(live({**block(), 'last_ok': 'yes'}), NOW)          # only True counts
    entry = live(block()); entry['gate_passed_at'] = None
    assert not ns.offered(entry, NOW)                                        # the gate time is still required
    held = live(block()); held['status'] = 'held'
    assert not ns.offered(held, NOW)
    one = live(block()); one['pearls'] = one['pearls'][:1]
    assert not ns.offered(one, NOW)                                          # two members are still required


def test_the_old_live_rule_is_unchanged_without_a_connect_block():
    old = necklace('topic-evidence-brief', gate_passed_at=iso(NOW - timedelta(hours=5)),
                   quality={'delta_pp': 10, 'tested_at': iso(NOW - timedelta(hours=1))})
    assert ns.offered(old, NOW)
    assert not ns.offered({**old, 'quality': {'delta_pp': 0, 'tested_at': iso(NOW - timedelta(hours=1))}}, NOW)
    assert not ns.offered({**old, 'quality': {'delta_pp': 10, 'tested_at': iso(NOW - timedelta(hours=60))}}, NOW)
    # a connect block beside a good delta does not turn a failed daily run into a pass
    assert not ns.offered({**old, 'connect': block(ok=False)}, NOW)


def test_the_page_says_what_is_checked_and_makes_no_accuracy_claim():
    entry = live(block())
    assert ns.standing_line(entry, NOW) == 'Standing: running · connected end to end and checked every day (last check 2026-11-20).'
    status, page = ns.page('topic-evidence-brief', snapshot={'necklaces': [entry]}, now=NOW)
    assert status == 200 and 'connected end to end and checked every day' in page
    assert 'Verified 95%' not in page and 'retests with at most one failure' not in page and 'Recent test success' not in page
    assert ns.live_count({'necklaces': [entry]}, NOW) == 1 and ns.live({'necklaces': [entry]}, NOW) == [entry]
