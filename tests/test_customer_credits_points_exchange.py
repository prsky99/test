"""AI AD Coin points -> workspace credits entry point (docs/AD_COIN_BENEFITS.md, approved 11-10)."""
import secrets

import pytest

from agent_market import customer_credits as module
from agent_market.ad_coin.v2 import points
from agent_market.customer_credits import WELCOME_CREDITS, CreditRequired
from agent_market.workspace_access import WorkspaceConflict, WorkspaceInvalid
from tests.test_customer_credits import acceptance, credits  # noqa: F401
from tests.test_customer_organizations import orgs  # noqa: F401


def exchange_id():
    return secrets.token_hex(16)


def test_enrolled_customer_receives_exchanged_credits_once(credits):  # noqa: F811
    c, a = credits.credits, credits.customers[0]
    c.enroll(acceptance(), a)
    ref = exchange_id()
    c.exchange_points(a.customer_id, 5, ref)
    c.exchange_points(a.customer_id, 5, ref)  # replay: the AD Coin side retried
    assert c.status(a)['balance'] == WELCOME_CREDITS + 5


def test_exchange_needs_an_active_enrollment(credits):  # noqa: F811
    c, a = credits.credits, credits.customers[0]
    with pytest.raises(CreditRequired):
        c.exchange_points(a.customer_id, 1, exchange_id())


def test_exchange_caps_match_the_terms(credits):  # noqa: F811
    c, a = credits.credits, credits.customers[0]
    c.enroll(acceptance(), a)
    with pytest.raises(WorkspaceInvalid):
        c.exchange_points(a.customer_id, points.MAX_CREDITS_PER_EXCHANGE + 1, exchange_id())
    with pytest.raises(WorkspaceInvalid):
        c.exchange_points(a.customer_id, 0, exchange_id())
    with pytest.raises(WorkspaceInvalid):
        c.exchange_points(a.customer_id, 1, 'not-an-id')
    for _ in range(points.MAX_CREDITS_PER_MONTH // points.MAX_CREDITS_PER_EXCHANGE):
        c.exchange_points(a.customer_id, points.MAX_CREDITS_PER_EXCHANGE, exchange_id())
    with pytest.raises(WorkspaceConflict):
        c.exchange_points(a.customer_id, 1, exchange_id())
    assert c.status(a)['balance'] == WELCOME_CREDITS + points.MAX_CREDITS_PER_MONTH


def test_terms_state_the_exchange_and_earlier_enrollments_stay_valid(credits):  # noqa: F811
    assert ('%d points for 1 credit, up to %d credits at a time and %d credits a month' % (
        points.POINTS_PER_WORKSPACE_CREDIT, points.MAX_CREDITS_PER_EXCHANGE, points.MAX_CREDITS_PER_MONTH)) in module.TERMS
    assert (module.POINTS_PER_CREDIT, module.MAX_CREDITS_PER_EXCHANGE, module.MAX_CREDITS_PER_MONTH) == (
        points.POINTS_PER_WORKSPACE_CREDIT, points.MAX_CREDITS_PER_EXCHANGE, points.MAX_CREDITS_PER_MONTH)
    assert module.VERSION == 'workspace-free-2026-11-10-v3'
    previous = ('workspace-free-2026-10-24-v2', '29ef63d133d0641d8f5d9b0b2e12c59c7ff4a95c19b1f03a52fd69a0e4578594')
    assert previous in module.LEGACY_ACCEPTANCES
