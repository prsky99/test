"""HTTP regressions for human-only actions and server-derived spend authority."""
import hashlib
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.ad_coin.api import router_for
from agent_market.ad_coin.config import Settings
from agent_market.ad_coin.ledger import EXTERNAL_FUNDING
from agent_market.ad_coin.people import user_ref_for_customer
from agent_market.customer_identity_service import COOKIE

PREFIX = '/api/ad-coin/v1'


class Identity:
    def actor(self, token):
        if token != 'owner-test-session':
            raise ValueError('invalid test session')
        return SimpleNamespace(customer_id='cus_authority_owner')

    def csrf(self, token):
        return hashlib.sha256(('authority-csrf:' + token).encode()).hexdigest()


@pytest.fixture
def authority_world(tmp_path):
    identity = Identity()
    legacy = 'legacy-visitor-for-read-only-test'
    settings = Settings(enabled=True, db_path=str(tmp_path / 'authority.sqlite3'),
                        receipt_key_path=str(tmp_path / 'receipt.pem'),
                        admin_token='authority-test-admin',
                        invited=frozenset({hashlib.sha256(legacy.encode()).hexdigest()}))
    router = router_for(settings, customer_identity=lambda: identity)
    people, service = router.ad_coin_console.people, router.ad_coin_service
    people.invite('cus_authority_owner')
    key = people.create_key('cus_authority_owner', 'helper')['agent_key']
    owner_ref = user_ref_for_customer('cus_authority_owner')
    wallet = service._ensure_wallet(owner_ref, 'helper')
    service.ledger.post('test_funding', 'authority-fixture', [(EXTERNAL_FUNDING, -1000), (wallet, 1000)])
    app = FastAPI(); app.include_router(router)
    owner = TestClient(app, base_url='https://authority.test')
    owner.cookies.set(COOKIE, 'owner-test-session')
    human_headers = {'Origin': 'https://authority.test',
                     'X-Customer-CSRF': identity.csrf('owner-test-session')}
    agent = TestClient(app, base_url='https://authority.test')
    return SimpleNamespace(owner=owner, human_headers=human_headers, agent=agent,
                           agent_headers={'X-Ad-Coin-Agent-Key': key}, service=service,
                           people=people, wallet=wallet, legacy=legacy, owner_ref=owner_ref)


@pytest.mark.parametrize('path', ['/consents', '/exposures', '/transfers', '/agents/revoke',
                                  '/mandates', '/mandates/revoke', '/vouchers/redeem'])
def test_agent_cannot_perform_human_only_action(authority_world, path):
    w = authority_world
    response = w.agent.post(PREFIX + path, headers=w.agent_headers, json={})
    assert response.status_code == 403
    assert response.json()['error'] == 'customer_session_required'
    assert w.service.ledger.balance(w.wallet) == 1000


@pytest.mark.parametrize('body_actor', [None, 'user', 'admin'])
def test_omitting_mandate_never_turns_agent_into_user(authority_world, body_actor):
    w = authority_world
    body = {'wallet': w.wallet, 'provider': 'research-pro', 'task_ref': 'research',
            'price_coins': 1, 'idempotency_key': 'no-mandate-' + str(body_actor)}
    if body_actor is not None:
        body['actor'] = body_actor
    result = w.agent.post(PREFIX + '/spends', headers=w.agent_headers, json=body)
    assert result.status_code == 409
    assert result.json()['error'] == 'mandate_required'
    assert w.service.ledger.balance(w.wallet) == 1000


def test_valid_mandate_allows_agent_but_revocation_stops_it(authority_world):
    w = authority_world
    mandate = w.owner.post(PREFIX + '/mandates', headers=w.human_headers, json={
        'agent': 'helper', 'total_coins': 5, 'per_task_coins': 2,
        'providers': ['research-pro'], 'days': 1})
    assert mandate.status_code == 200, mandate.text
    body = {'wallet': w.wallet, 'provider': 'research-pro', 'task_ref': 'research',
            'price_coins': 1, 'idempotency_key': 'delegated-payment', 'mandate_id': mandate.json()['id']}
    paid = w.agent.post(PREFIX + '/spends', headers=w.agent_headers, json=body)
    assert paid.status_code == 200, paid.text
    assert w.service.ledger.balance(w.wallet) == 990
    assert w.owner.post(PREFIX + '/mandates/revoke', headers=w.human_headers,
                        json={'id': body['mandate_id']}).status_code == 200
    refused = w.agent.post(PREFIX + '/spends', headers=w.agent_headers,
                           json={**body, 'idempotency_key': 'after-revocation'})
    assert refused.status_code == 409 and refused.json()['error'] == 'mandate_invalid'
    assert w.service.ledger.balance(w.wallet) == 990


def test_human_actor_is_not_inferred_from_mandate_field(authority_world):
    w = authority_world
    result = w.owner.post(PREFIX + '/spends', headers=w.human_headers, json={
        'wallet': w.wallet, 'provider': 'research-pro', 'task_ref': 'research',
        'price_coins': 1, 'idempotency_key': 'human-payment', 'mandate_id': 'not-a-real-mandate'})
    assert result.status_code == 200, result.text
    assert w.service.ledger.balance(w.wallet) == 990


def test_mixed_credentials_and_legacy_csrf_fallback_are_refused(authority_world):
    w = authority_world
    mixed = w.owner.get(PREFIX + '/wallets', headers=w.agent_headers)
    assert mixed.status_code == 403 and mixed.json()['error'] == 'mixed_credentials'
    fallback = w.owner.post(PREFIX + '/quotes', headers={'X-Visitor-Token': w.legacy}, json={})
    assert fallback.status_code == 403
    legacy = w.agent.post(PREFIX + '/spends', headers={'X-Visitor-Token': w.legacy}, json={})
    assert legacy.status_code == 403 and legacy.json()['error'] == 'customer_session_required'


def test_key_is_rechecked_inside_the_write_transaction(authority_world, monkeypatch):
    w = authority_world
    original = w.people.agent_for_key
    calls = 0
    def racing_lookup(key):
        nonlocal calls
        calls += 1
        if calls == 2:
            w.people.revoke_keys('cus_authority_owner', 'helper')
        return original(key)
    monkeypatch.setattr(w.people, 'agent_for_key', racing_lookup)
    response = w.agent.post(PREFIX + '/spends', headers=w.agent_headers, json={
        'wallet': w.wallet, 'provider': 'research-pro', 'task_ref': 'research',
        'price_coins': 1, 'idempotency_key': 'racing-revocation'})
    assert response.status_code == 403 and response.json()['error'] == 'agent_key_revoked'
    assert w.service.ledger.balance(w.wallet) == 1000
