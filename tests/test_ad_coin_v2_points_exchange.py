"""Points -> workspace credits: debit with an outbox job, grant by the worker, refund on refusal."""
import secrets
import time
from uuid import uuid4

import pytest

from agent_market.ad_coin.v2 import points
from agent_market.ad_coin.v2.contracts import ContractError
from agent_market.ad_coin.v2.ledger import ModelLedger
from agent_market.ad_coin.v2.points_exchange import PointsExchange, cost_atoms
from agent_market.ad_coin.v2.workers import ModelWorkers
from agent_market.workspace_access import WorkspaceConflict
from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_persistence import store  # noqa: F401

COIN = points.ATOMS_PER_COIN


@pytest.fixture(autouse=True)
def _points_mode(monkeypatch):
    monkeypatch.delenv('AD_COIN_REAL_VALUE_ENABLED', raising=False)


@pytest.fixture
def setup(store):  # noqa: F811
    store.migrate_model()
    ledger = ModelLedger(store)
    points.issue(ledger, 1000 * COIN, reason='test-' + uuid4().hex)
    owner = str(uuid4())
    wallet = ledger.create_account(owner, 'user_available')
    ledger.post('reward:' + owner, [(points.GROWTH_ACCOUNT, str(-100 * COIN)), (wallet, str(100 * COIN))],
                kind='growth_reward')
    return store, ledger, owner, wallet


def now_ms():
    return int(time.time() * 1000)


def request(store, owner, credits=3, exchange_id=None):
    return PointsExchange(store).request(owner_id=owner, customer_id='cu_' + secrets.token_hex(16), credits=credits,
                                         exchange_id=exchange_id or secrets.token_hex(16), now_ms=now_ms())


def test_request_debits_points_and_the_worker_grants_credits(setup):
    store, ledger, owner, wallet = setup
    granted = []
    result = request(store, owner, credits=3)
    assert result['points'] == 30 and ledger.account(wallet)['balance_atoms'] == str(70 * COIN)
    done = ModelWorkers(store, credit_grant=lambda *args: granted.append(args)).process_outbox(now_ms=now_ms())
    assert done == 1 and granted[0][1] == 3 and granted[0][2] == result['exchange_id']
    assert ledger.account(wallet)['balance_atoms'] == str(70 * COIN)


def test_refused_grant_refunds_the_points(setup):
    store, ledger, owner, wallet = setup
    request(store, owner, credits=5)

    def refuse(*_):
        raise WorkspaceConflict()
    assert ModelWorkers(store, credit_grant=refuse).process_outbox(now_ms=now_ms()) == 1
    assert ledger.account(wallet)['balance_atoms'] == str(100 * COIN)


def test_temporary_failure_keeps_the_job_for_a_retry(setup):
    store, ledger, owner, wallet = setup
    request(store, owner, credits=2)

    def broken(*_):
        raise ConnectionError('credits store down')
    with pytest.raises(ConnectionError):
        ModelWorkers(store, credit_grant=broken).process_outbox(now_ms=now_ms())
    granted = []
    later = now_ms() + 60_000  # after the lease expires
    ModelWorkers(store).reclaim_stale_leases(now_ms=later)
    assert ModelWorkers(store, credit_grant=lambda *a: granted.append(a)).process_outbox(now_ms=later) == 1
    assert len(granted) == 1 and ledger.account(wallet)['balance_atoms'] == str(80 * COIN)


def test_same_exchange_id_debits_once_and_limits_hold(setup):
    store, ledger, owner, wallet = setup
    ref = secrets.token_hex(16)
    customer = 'cu_' + secrets.token_hex(16)
    for _ in range(2):
        PointsExchange(store).request(owner_id=owner, customer_id=customer, credits=1, exchange_id=ref, now_ms=1)
    assert ledger.account(wallet)['balance_atoms'] == str(90 * COIN)
    for bad in (0, points.MAX_CREDITS_PER_EXCHANGE + 1):
        with pytest.raises(ContractError):
            request(store, owner, credits=bad)
    with pytest.raises(ContractError) as error:
        request(store, owner, credits=points.MAX_CREDITS_PER_EXCHANGE)  # 100 points > 90 left
    assert error.value.code == 'insufficient_balance'
    assert cost_atoms(1) == points.POINTS_PER_WORKSPACE_CREDIT * COIN


def test_worker_without_a_grant_function_retries_later(setup):
    store, ledger, owner, wallet = setup
    request(store, owner, credits=1)
    with pytest.raises(ContractError) as error:
        ModelWorkers(store).process_outbox(now_ms=now_ms())
    assert error.value.code == 'credit_grant_unavailable'


from tests.test_customer_credits import acceptance, credits  # noqa: E402,F401
from tests.test_customer_organizations import orgs  # noqa: E402,F401


def test_end_to_end_with_the_real_credit_entry_point(setup, credits):  # noqa: F811
    from agent_market.customer_credits import WELCOME_CREDITS
    store, ledger, owner, wallet = setup
    c, person = credits.credits, credits.customers[0]
    c.enroll(acceptance(), person)
    PointsExchange(store).request(owner_id=owner, customer_id=person.customer_id, credits=4,
                                  exchange_id=secrets.token_hex(16), now_ms=now_ms())
    assert ModelWorkers(store, credit_grant=c.exchange_points).process_outbox(now_ms=now_ms()) == 1
    assert c.status(person)['balance'] == WELCOME_CREDITS + 4
    assert ledger.account(wallet)['balance_atoms'] == str(60 * COIN)
    # A person who never enrolled is refused by the credit side and gets the points back.
    other = credits.customers[1]
    PointsExchange(store).request(owner_id=owner, customer_id=other.customer_id, credits=2,
                                  exchange_id=secrets.token_hex(16), now_ms=now_ms())
    ModelWorkers(store, credit_grant=c.exchange_points).process_outbox(now_ms=now_ms())
    assert ledger.account(wallet)['balance_atoms'] == str(60 * COIN)
