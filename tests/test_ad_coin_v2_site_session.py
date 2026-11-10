"""Site sign-in bridge for AI AD Coin v2 (PM decision 11-10) and the points exchange route.

A site customer session opens v2 for that customer only: ids come from a server-secret HMAC, the
first use creates an ordinary person (no advertiser or operator authority), every request re-checks
the site session (sign-out is immediate), other origins are refused and writes need the site CSRF.
"""
import json
import secrets
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.ad_coin.v2 import points
from agent_market.ad_coin.v2.access import HUMAN_CAPABILITIES
from agent_market.ad_coin.v2.key_vault import KeyVault
from agent_market.ad_coin.v2.ledger import ModelLedger
from agent_market.ad_coin.v2.live_service import create_live_ad_coin_v2_router
from agent_market.workspace_access import WorkspaceDenied
from tests.test_ad_coin_postgres import cluster  # noqa: F401
from tests.test_ad_coin_v2_persistence import store  # noqa: F401

COOKIE = '__Host-ac_customer_session'


class Actor:
    def __init__(self, customer_id):
        self.customer_id = customer_id


class FakeIdentity:
    """Stands in for customer_identity.CustomerIdentity: sessions can be signed out or expire."""

    def __init__(self):
        self.sessions = {}

    def sign_in(self, customer_id):
        token = 'cst_' + secrets.token_urlsafe(32)[:43]
        self.sessions[token] = customer_id
        return token

    def sign_out(self, token):
        self.sessions.pop(token, None)

    def actor(self, token):
        if token not in self.sessions:
            raise WorkspaceDenied()
        return Actor(self.sessions[token])

    def csrf(self, token):
        return 'csrf-' + token[-12:]


@pytest.fixture(autouse=True)
def _points_mode(monkeypatch):
    monkeypatch.delenv('AD_COIN_REAL_VALUE_ENABLED', raising=False)


@pytest.fixture
def site(store):  # noqa: F811
    store.migrate_model()
    identity = FakeIdentity()
    vault = KeyVault(owner_link_key=b'L' * 32)
    app = FastAPI()
    app.include_router(create_live_ad_coin_v2_router(store, key_vault=vault, customer_identity=lambda: identity))
    client = TestClient(app)
    client.identity, client.store = identity, store
    return client


def headers(token, **extra):
    return {'Cookie': COOKIE + '=' + token, **extra}


def principal_rows(store):
    from agent_market.ad_coin.sql_registry import unchecked
    with unchecked(), store.atomic():
        return store.database.all("SELECT id,owner_id,kind,capabilities_json FROM adc2_principals")


def test_a_signed_in_customer_opens_v2_as_an_ordinary_person(site):
    token = site.identity.sign_in('cu_' + 'a' * 32)
    response = site.get('/ad-coin/v2/ui/session', headers=headers(token))
    assert response.status_code == 200, response.text
    assert response.json()['advertisers'] == []
    rows = principal_rows(site.store)
    assert len(rows) == 1 and rows[0]['kind'] == 'human'
    assert set(json.loads(rows[0]['capabilities_json'])) == set(HUMAN_CAPABILITIES)  # nothing more


def test_forged_expired_and_signed_out_sessions_are_refused(site):
    assert site.get('/ad-coin/v2/ui/session', headers=headers('cst_' + 'x' * 43)).status_code == 401
    assert site.get('/ad-coin/v2/ui/session', headers=headers('not-a-token')).status_code == 401
    token = site.identity.sign_in('cu_' + 'b' * 32)
    assert site.get('/ad-coin/v2/ui/session', headers=headers(token)).status_code == 200
    site.identity.sign_out(token)  # sign-out, revocation and expiry all end the site session
    assert site.get('/ad-coin/v2/ui/session', headers=headers(token)).status_code == 401
    assert site.post('/api/ad-coin/v2/points-exchanges', json={'credits': 1},
                     headers=headers(token, **{'Idempotency-Key': str(uuid4()),
                                               'X-CSRF-Token': site.identity.csrf(token)})).status_code == 401


def test_other_origins_are_refused(site):
    token = site.identity.sign_in('cu_' + 'c' * 32)
    assert site.get('/ad-coin/v2/ui/session', headers=headers(token, Origin='https://evil.example')).status_code == 403
    assert site.get('/ad-coin/v2/ui/session', headers=headers(token, **{'Sec-Fetch-Site': 'cross-site'})).status_code == 403
    assert site.get('/ad-coin/v2/ui/session', headers=headers(token, Origin='http://testserver')).status_code == 200


def test_one_customer_is_one_principal_with_secret_derived_ids(site):
    customer = 'cu_' + 'd' * 32
    first, second = site.identity.sign_in(customer), site.identity.sign_in(customer)
    for token in (first, second, first):
        assert site.get('/ad-coin/v2/ui/session', headers=headers(token)).status_code == 200
    rows = principal_rows(site.store)
    assert len(rows) == 1
    owner = rows[0]['owner_id']
    assert owner != str(uuid5(NAMESPACE_URL, customer)) and customer not in owner
    assert site.get('/ad-coin/v2/ui/session', headers=headers(site.identity.sign_in('cu_' + 'e' * 32))).status_code == 200
    assert len(principal_rows(site.store)) == 2
    from agent_market.ad_coin.v2.live_auth import PersistentCredentialResolver
    other_key = PersistentCredentialResolver(site.store, customer_identity=lambda: None, owner_link_key=b'M' * 32)
    assert other_key._linked_id('adc2-owner:', customer) != owner  # the server secret decides the id


def test_writes_need_the_site_csrf_and_exchange_points_once(site):
    customer = 'cu_' + 'f' * 32
    token = site.identity.sign_in(customer)
    assert site.get('/ad-coin/v2/ui/session', headers=headers(token)).status_code == 200
    owner = principal_rows(site.store)[0]['owner_id']
    ledger = ModelLedger(site.store)
    points.issue(ledger, 1000 * points.ATOMS_PER_COIN, reason='test-' + uuid4().hex)
    wallet = site.store.one('account_by_owner_purpose', (owner, 'user_available'))['id']
    ledger.post('reward:' + owner, [(points.GROWTH_ACCOUNT, str(-100 * points.ATOMS_PER_COIN)),
                                    (wallet, str(100 * points.ATOMS_PER_COIN))], kind='growth_reward')
    path, key = '/api/ad-coin/v2/points-exchanges', str(uuid4())
    body = {'credits': 2, 'customer_id': 'cu_' + '0' * 32}  # a body customer id is ignored
    assert site.post(path, json=body, headers=headers(token, **{'Idempotency-Key': key})).status_code == 403
    assert site.post(path, json=body, headers=headers(token, **{'Idempotency-Key': key,
                                                                'X-CSRF-Token': 'wrong'})).status_code == 403
    assert site.post(path, json=body, headers=headers(token, **{'X-CSRF-Token': site.identity.csrf(token)})).status_code == 428
    good = headers(token, **{'Idempotency-Key': key, 'X-CSRF-Token': site.identity.csrf(token)})
    done = site.post(path, json=body, headers=good)
    assert done.status_code == 200 and done.json()['points'] == 20 and done.json()['state'] == 'pending'
    again = site.post(path, json=body, headers=good)
    assert again.status_code == 200
    assert int(ledger.account(wallet)['balance_atoms']) == 80 * points.ATOMS_PER_COIN  # debited once
    from agent_market.ad_coin.sql_registry import unchecked
    with unchecked(), site.store.atomic():
        jobs = site.store.database.all("SELECT payload_json FROM adc2_outbox")
    payloads = [json.loads(row['payload_json']) for row in jobs if 'points_exchange' in row['payload_json']]
    assert len(payloads) == 1 and payloads[0]['customer_id'] == customer  # the session's customer, not the body's
    assert site.post(path, json={'credits': 11}, headers=headers(token, **{
        'Idempotency-Key': str(uuid4()), 'X-CSRF-Token': site.identity.csrf(token)})).status_code == 422


def test_without_the_bridge_the_site_cookie_opens_nothing(store):  # noqa: F811
    store.migrate_model()
    app = FastAPI()
    app.include_router(create_live_ad_coin_v2_router(store, key_vault=KeyVault()))
    client = TestClient(app)
    assert client.get('/ad-coin/v2/ui/session', headers=headers('cst_' + 'y' * 43)).status_code == 401
    assert client.post('/api/ad-coin/v2/points-exchanges', json={'credits': 1},
                       headers=headers('cst_' + 'y' * 43, **{'Idempotency-Key': str(uuid4())})).status_code == 401


def test_owner_link_key_is_kept_in_an_owner_only_file(tmp_path):
    import os
    import stat
    first, second = KeyVault.from_directory(str(tmp_path)), KeyVault.from_directory(str(tmp_path))
    assert first.get_owner_link_key() == second.get_owner_link_key() and len(first.get_owner_link_key()) == 32
    assert stat.S_IMODE(os.stat(tmp_path / 'owner-link.key').st_mode) == 0o600


def test_two_session_cookies_are_refused(site):
    first, second = site.identity.sign_in('cu_' + '1' * 32), site.identity.sign_in('cu_' + '2' * 32)
    both = {'Cookie': COOKIE + '=' + first + '; ' + COOKIE + '=' + second}
    assert site.get('/ad-coin/v2/ui/session', headers=both).status_code == 401


def test_the_bridge_refuses_a_random_link_key(store, monkeypatch):  # noqa: F811
    monkeypatch.delenv('AIAC_OWNER_LINK_KEY_HEX', raising=False)
    store.migrate_model()
    with pytest.raises(RuntimeError):
        create_live_ad_coin_v2_router(store, key_vault=KeyVault(), customer_identity=lambda: FakeIdentity())
    monkeypatch.setenv('AIAC_OWNER_LINK_KEY_HEX', '11' * 32)
    assert KeyVault().owner_link_persistent and KeyVault().get_owner_link_key() == b'\x11' * 32


def test_a_retried_exchange_reports_the_refund(store):  # noqa: F811
    from agent_market.ad_coin.v2.points_exchange import PointsExchange
    from agent_market.ad_coin.v2.workers import ModelWorkers
    from agent_market.workspace_access import WorkspaceConflict
    store.migrate_model()
    ledger = ModelLedger(store)
    points.issue(ledger, 1000 * points.ATOMS_PER_COIN, reason='test-' + uuid4().hex)
    owner = str(uuid4())
    wallet = ledger.create_account(owner, 'user_available')
    ledger.post('reward:' + owner, [(points.GROWTH_ACCOUNT, str(-50 * points.ATOMS_PER_COIN)),
                                    (wallet, str(50 * points.ATOMS_PER_COIN))], kind='growth_reward')
    args = dict(owner_id=owner, customer_id='cu_' + '3' * 32, credits=2, exchange_id=uuid4().hex, now_ms=1)

    def refuse(*_):
        raise WorkspaceConflict()

    assert PointsExchange(store).request(**args)['state'] == 'pending'
    ModelWorkers(store, credit_grant=refuse).process_outbox(now_ms=2)
    assert PointsExchange(store).request(**args)['state'] == 'refunded'
