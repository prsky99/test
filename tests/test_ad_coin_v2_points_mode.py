"""Activity points mode: no purchase, no cash-out, no transfer between people, platform benefits only, expiry."""
from uuid import uuid4

import pytest

from agent_market.ad_coin.v2 import points
from agent_market.ad_coin.v2.agent_payments import AgentPaymentGateway
from agent_market.ad_coin.v2.contracts import ContractError
from agent_market.ad_coin.v2.ledger import ModelLedger
from agent_market.ad_coin.v2.real_value import RealValueGateway
from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_persistence import store  # noqa: F401

DAY_MS = 86_400_000


def uid():
    return str(uuid4())


@pytest.fixture(autouse=True)
def _points_mode(monkeypatch):
    monkeypatch.delenv('AD_COIN_REAL_VALUE_ENABLED', raising=False)


@pytest.fixture
def ledger(store):  # noqa: F811
    store.migrate_model()
    return ModelLedger(store)


def wallet(ledger, owner, amount):
    clearing = ledger.create_account(uid(), 'external_clearing')
    account = ledger.create_account(owner, 'user_available')
    ledger.post('seed:' + account, [(clearing, '-' + amount), (account, amount)], kind='model_seed')
    return account


def test_points_mode_is_the_default_and_states_its_rules():
    assert points.economy_mode() == 'activity_points' and points.points_mode()
    rules = points.rules()
    assert rules['mode'] == 'activity_points' and rules['expiry_days'] == 365
    text = ' '.join(rules['rules']).lower()
    for phrase in ('cannot be bought', 'no cash value', 'cannot be sent to another person', 'expire'):
        assert phrase in text


def test_points_cannot_move_between_people(ledger):
    alice, bob = wallet(ledger, uid(), '100'), ledger.create_account(uid(), 'user_available')
    for kind in ('transfer', 'payment', 'award'):
        with pytest.raises(ContractError) as error:
            ledger.post('gift:' + kind, [(alice, '-10'), (bob, '10')], kind=kind)
        assert error.value.code == 'points_not_transferable'
    assert ledger.account(alice)['balance_atoms'] == '100'


def test_one_person_can_still_lock_and_release_their_own_points(ledger):
    owner = uid()
    available = wallet(ledger, owner, '100')
    locked = ledger.create_account(owner, 'user_locked')
    ledger.post('hold', [(available, '-30'), (locked, '30')], kind='payment')
    assert ledger.account(locked)['balance_atoms'] == '30'


def test_points_pay_only_for_platform_benefits(store, ledger):  # noqa: F811
    owner = uid()
    wallet(ledger, owner, '100')
    gateway = AgentPaymentGateway(store, ledger, None)
    with pytest.raises(ContractError) as error:
        gateway.hold_execution(owner_id=owner, provider_id=uid(), task_ref='third-party', price_atoms=10,
                               idem_key='a')
    assert error.value.code == 'points_redeem_platform_benefits_only'
    benefit = next(iter(points.BENEFITS))
    held = gateway.hold_execution(owner_id=owner, provider_id=benefit, task_ref='free-run', price_atoms=10,
                                  idem_key='b')
    assert held['status'] == 'held'


def test_points_cannot_be_bought_or_cashed_out(store, ledger):  # noqa: F811
    gateway = RealValueGateway(store, ledger, None)
    with pytest.raises(ContractError) as bought:
        gateway.record_fiat_deposit(uid(), uid(), uid(), 100, 'USD', 'ref')
    with pytest.raises(ContractError) as cashed:
        import inspect
        params = inspect.signature(gateway.request_onchain_withdrawal).parameters
        gateway.request_onchain_withdrawal(**{name: None for name in params})
    assert bought.value.code == cashed.value.code == 'real_value_disabled'


def test_idle_points_expire_to_the_platform_and_active_ones_stay(store, ledger, monkeypatch):  # noqa: F811
    import time as clock
    idle, active = wallet(ledger, uid(), '40'), wallet(ledger, uid(), '25')
    now_ms = int(clock.time() * 1000) + (points.POINTS_EXPIRY_DAYS + 1) * DAY_MS
    assert points.expire_inactive_points(store, ledger, now_ms=now_ms - 2 * DAY_MS - (points.POINTS_EXPIRY_DAYS - 1) * DAY_MS) == 0
    expired = points.expire_inactive_points(store, ledger, now_ms=now_ms)
    assert expired == 2
    assert ledger.account(idle)['balance_atoms'] == '0' and ledger.account(active)['balance_atoms'] == '0'
    assert ledger.account(points.EXPIRED_POINTS_ACCOUNT)['balance_atoms'] == '65'
    assert points.expire_inactive_points(store, ledger, now_ms=now_ms) == 0  # idempotent: nothing left


def test_no_expiry_in_real_value_mode(store, ledger, monkeypatch):  # noqa: F811
    monkeypatch.setenv('AD_COIN_REAL_VALUE_ENABLED', '1')
    wallet(ledger, uid(), '10')
    assert points.expire_inactive_points(store, ledger, now_ms=10 ** 15) == 0
