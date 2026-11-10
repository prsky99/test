"""Coin economy ledger rules (docs/AD_COIN_COIN_ECONOMY.md section 4)."""
from uuid import uuid4

import pytest

from agent_market.ad_coin.v2 import points
from agent_market.ad_coin.v2.contracts import ContractError
from agent_market.ad_coin.v2.ledger import KINDS, ModelLedger
from agent_market.ad_coin.v2.schema import VERSION, statements
from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_persistence import store  # noqa: F401

COIN = points.ATOMS_PER_COIN


def uid():
    return str(uuid4())


@pytest.fixture(autouse=True)
def _points_mode(monkeypatch):
    monkeypatch.delenv('AD_COIN_REAL_VALUE_ENABLED', raising=False)


@pytest.fixture
def ledger(store):  # noqa: F811
    store.migrate_model()
    return ModelLedger(store)


def test_caps_are_code_constants_and_kinds_exist():
    assert points.ISSUANCE_MONTHLY_CAP_ATOMS == 100_000 * COIN
    assert points.PROVIDER_REWARD_MONTHLY_CAP_ATOMS == 1_000 * COIN
    assert points.ECONOMY_KINDS <= KINDS


def test_bookings_table_is_part_of_schema_10():
    text = ' '.join(statements())
    assert VERSION == 10 and 'CREATE TABLE IF NOT EXISTS adc2_sponsored_bookings' in text


def test_issuance_goes_only_into_the_growth_budget(ledger):
    points.issue(ledger, 50 * COIN, reason='2026-11-start')
    assert ledger.account(points.GROWTH_ACCOUNT)['balance_atoms'] == str(50 * COIN)
    stranger = ledger.create_account(uid(), 'user_available')
    with pytest.raises(ContractError) as error:
        ledger.post('issue-to-person', [(points.ISSUANCE_ACCOUNT, '-5'), (stranger, '5')], kind='issuance')
    assert error.value.code == 'invalid_issuance'


def test_monthly_issuance_cap_holds(ledger):
    points.issue(ledger, points.ISSUANCE_MONTHLY_CAP_ATOMS - COIN, reason='bulk')
    points.issue(ledger, COIN, reason='last-coin')  # exactly at the cap
    with pytest.raises(ContractError) as error:
        points.issue(ledger, 1, reason='one-atom-over')
    assert error.value.code == 'issuance_monthly_cap_exceeded'


def test_clearing_still_needs_issuance_or_fixture(ledger):
    other = ledger.create_account(uid(), 'external_clearing')
    target = ledger.create_account(uid(), 'platform_revenue')
    with pytest.raises(ContractError) as error:
        ledger.post('sneaky', [(other, '-5'), (target, '5')], kind='grant')
    assert error.value.code == 'clearing_requires_model_fixture'


def test_points_never_move_from_a_person_to_an_advertiser(ledger):
    points.issue(ledger, 10 * COIN, reason='seed')
    person = ledger.create_account(uid(), 'user_available')
    advertiser = ledger.create_account(uid(), 'advertiser_available')
    ledger.post('reward-person', [(points.GROWTH_ACCOUNT, str(-COIN)), (person, str(COIN))], kind='growth_reward')
    ledger.post('grant-advertiser', [(points.GROWTH_ACCOUNT, str(-COIN)), (advertiser, str(COIN))], kind='grant')
    with pytest.raises(ContractError) as error:
        ledger.post('person-to-advertiser', [(person, '-5'), (advertiser, '5')], kind='grant')
    assert error.value.code == 'points_not_transferable'
    with pytest.raises(ContractError):
        ledger.post('advertiser-to-person', [(advertiser, '-5'), (person, '5')], kind='grant')
    # the platform may take Sponsored payment from the advertiser
    ledger.post('sponsored-day', [(advertiser, '-5'), (points.REVENUE_ACCOUNT, '5')], kind='sponsored_purchase')
    assert ledger.account(points.REVENUE_ACCOUNT)['balance_atoms'] == '5'


def test_growth_spending_cannot_exceed_the_budget(ledger):
    points.issue(ledger, COIN, reason='small')
    person = ledger.create_account(uid(), 'user_available')
    with pytest.raises(ContractError) as error:
        ledger.post('too-much', [(points.GROWTH_ACCOUNT, str(-2 * COIN)), (person, str(2 * COIN))], kind='growth_reward')
    assert error.value.code == 'insufficient_balance'


def test_platform_holdings_count_growth_and_revenue_and_issued(ledger):
    empty = points.platform_holdings(ledger)
    assert empty['platform_holdings_atoms'] == '0' and empty['issued_atoms'] == '0'
    points.issue(ledger, 500 * COIN, reason='test-' + uid())
    owner = uid()
    wallet = ledger.create_account(owner, 'user_available')
    ledger.post('reward:' + owner, [(points.GROWTH_ACCOUNT, str(-120 * COIN)), (wallet, str(120 * COIN))],
                kind='growth_reward')
    held = points.platform_holdings(ledger)
    assert held['issued_atoms'] == str(500 * COIN)
    assert held['growth_budget_atoms'] == str(380 * COIN)
    assert held['platform_holdings_atoms'] == str(380 * COIN + int(held['coin_revenue_atoms']))
    assert held['atoms_per_coin'] == COIN
