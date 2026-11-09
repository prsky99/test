"""Coin economy step 2: growth budget issuance, welcome grant, provider reward, operator grants."""
import secrets
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.ad_coin.v2 import points
from agent_market.ad_coin.v2.access import HUMAN_CAPABILITIES, OPERATOR_CAPABILITY, Access
from agent_market.ad_coin.v2.contracts import ContractError
from agent_market.ad_coin.v2.economy import CoinEconomy
from agent_market.ad_coin.v2.identity import Kind, Principal
from agent_market.ad_coin.v2.ledger import ModelLedger
from agent_market.ad_coin.v2.security_guards import AuditLogger
from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_persistence import store  # noqa: F401

COIN = points.ATOMS_PER_COIN


def uid():
    return str(uuid4())


@pytest.fixture(autouse=True)
def _points_mode(monkeypatch):
    monkeypatch.delenv('AD_COIN_REAL_VALUE_ENABLED', raising=False)


@pytest.fixture
def world(store):  # noqa: F811
    store.migrate_model()
    ledger, access = ModelLedger(store), Access(store)
    economy = CoinEconomy(store, ledger, access)
    economy.issue_monthly('2026-11', 10_000 * COIN)
    advertiser = uid()
    with store.atomic():
        account = access.provision_advertiser(advertiser, uid())
    return store, ledger, access, economy, advertiser, account


def principal(access, *, operator):
    pid, owner = uid(), uid()
    caps = HUMAN_CAPABILITIES | ({OPERATOR_CAPABILITY} if operator else set())
    access.provision_principal(pid, Kind.HUMAN, owner_id=owner, capabilities=caps)
    return Principal(__import__('uuid').UUID(pid), Kind.HUMAN, 1, 4_000_000_000, owner_id=__import__('uuid').UUID(owner),
                     csrf_verified=True, audience='aiac-v2-model')


def test_issuance_fills_the_growth_budget_once_per_month(world):
    store, ledger, access, economy, *_ = world
    assert ledger.account(points.GROWTH_ACCOUNT)['balance_atoms'] == str(10_000 * COIN)
    assert economy.issue_monthly('2026-11', 10_000 * COIN)['replayed']
    with pytest.raises(ContractError):
        economy.issue_monthly('2026-11', 20_000 * COIN)  # same month, different amount
    with pytest.raises(ContractError):
        economy.issue_monthly('november', 1)


def test_welcome_grant_once_and_only_for_active_advertisers(world):
    store, ledger, access, economy, advertiser, account = world
    first, again = economy.welcome_grant(advertiser), economy.welcome_grant(advertiser)
    assert not first['replayed'] and again['replayed']
    assert ledger.account(account)['balance_atoms'] == str(points.WELCOME_GRANT_ATOMS)
    with store.atomic():
        store.execute('advertiser_status', ('suspended', advertiser))
    other = economy  # suspended advertisers get nothing new
    with pytest.raises(ContractError) as error:
        other.provider_reward(advertiser, '2026-11', COIN)
    assert error.value.code == 'advertiser_not_active'


def test_provider_reward_is_capped_and_once_per_month(world):
    store, ledger, access, economy, advertiser, account = world
    with pytest.raises(ContractError):
        economy.provider_reward(advertiser, '2026-11', points.PROVIDER_REWARD_MONTHLY_CAP_ATOMS + 1)
    economy.provider_reward(advertiser, '2026-11', points.PROVIDER_REWARD_MONTHLY_CAP_ATOMS)
    with pytest.raises(ContractError):  # a second, different reward in the same month
        economy.provider_reward(advertiser, '2026-11', COIN)
    economy.provider_reward(advertiser, '2026-12', COIN)
    assert ledger.account(account)['balance_atoms'] == str(points.PROVIDER_REWARD_MONTHLY_CAP_ATOMS + COIN)


def test_operator_grants_need_the_operator_capability_and_leave_an_audit_entry(world):
    store, ledger, access, economy, advertiser, account = world
    person = ledger.create_account(uid(), 'user_available')
    staff, member = principal(access, operator=True), principal(access, operator=False)
    with pytest.raises(ContractError) as error:
        economy.operator_grant(member, account_id=person, amount_atoms=COIN, reason='feedback reward',
                               request_id=secrets.token_hex(16))
    assert error.value.code == 'operator_required'
    request = secrets.token_hex(16)
    economy.operator_grant(staff, account_id=person, amount_atoms=5 * COIN, reason='feedback reward',
                           request_id=request)
    assert economy.operator_grant(staff, account_id=person, amount_atoms=5 * COIN, reason='feedback reward',
                                  request_id=request)['replayed']
    assert ledger.account(person)['balance_atoms'] == str(5 * COIN)
    entries = AuditLogger.recent(store, limit=20)
    assert any('feedback reward' in entry['details_json'] for entry in entries)
    with pytest.raises(ContractError) as error:
        economy.operator_grant(staff, account_id=points.REVENUE_ACCOUNT, amount_atoms=COIN, reason='move revenue',
                               request_id=secrets.token_hex(16))
    assert error.value.code == 'grant_target_not_allowed'
    with pytest.raises(ContractError):
        economy.operator_grant(staff, account_id=person, amount_atoms=points.OPERATOR_GRANT_MAX_ATOMS + 1,
                               reason='too much', request_id=secrets.token_hex(16))


def test_admin_coin_routes_need_operator_and_csrf(world):
    from agent_market.ad_coin.v2.admin_http import router_for
    from agent_market.ad_coin.v2.live_service import build_live_service
    store, ledger, access, economy, advertiser, account = world
    commercial, resolver, _ = build_live_service(store)
    staff_pid, staff_owner, plain_pid, plain_owner = uid(), uid(), uid(), uid()
    commercial.access.provision_principal(staff_pid, Kind.HUMAN, owner_id=staff_owner,
                                          capabilities=HUMAN_CAPABILITIES | {OPERATOR_CAPABILITY})
    commercial.access.provision_principal(plain_pid, Kind.HUMAN, owner_id=plain_owner, capabilities=HUMAN_CAPABILITIES)
    resolver.register_human_session('staff-session', 'staff-csrf', principal_id=staff_pid, owner_id=staff_owner)
    resolver.register_human_session('plain-session', 'plain-csrf', principal_id=plain_pid, owner_id=plain_owner)
    app = FastAPI()
    app.include_router(router_for(commercial, resolve_auth=resolver))
    client = TestClient(app)
    path = '/api/ad-coin/v2/admin/advertisers/%s/welcome-grant' % advertiser
    plain = client.post(path, json={}, cookies={'aiac_session': 'plain-session'}, headers={'X-CSRF-Token': 'plain-csrf'})
    assert plain.status_code == 403
    no_csrf = client.post(path, json={}, cookies={'aiac_session': 'staff-session'})
    assert no_csrf.status_code == 403
    ok = client.post(path, json={}, cookies={'aiac_session': 'staff-session'}, headers={'X-CSRF-Token': 'staff-csrf'})
    assert ok.status_code == 200, ok.text
    assert ledger.account(account)['balance_atoms'] == str(points.WELCOME_GRANT_ATOMS)
