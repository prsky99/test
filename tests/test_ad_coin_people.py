"""AI AD Coin identity: invited signed-in customers and the agent keys they create."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.ad_coin.api import router_for
from agent_market.ad_coin.config import Settings
from agent_market.ad_coin.db import Database
from agent_market.ad_coin.people import People, PeopleError, user_ref_for_customer
from agent_market.customer_identity_service import COOKIE
from tests.test_customer_typed_authoring import customer_flow  # noqa: F401  (fixture)
from tests.test_workspace_typed_release import typed_release_world  # noqa: F401  (fixture)
from tests.test_workspace_typed_flows import typed_world, routing  # noqa: F401  (fixtures)

SELECTION = {'chosen': 'research-pro'}
TASK = {'provider': 'research-pro', 'task_ref': 'compare', 'price_won': 600, 'category': 'deep_research'}


def test_invites_and_agent_keys_without_http():
    people = People(Database(':memory:'))
    with pytest.raises(PeopleError):
        people.create_key('cus_1', 'helper')            # not invited
    people.invite('cus_1', 'pilot')
    key = people.create_key('cus_1', 'helper')['agent_key']
    assert people.agent_for_key(key) == ('cus_1', 'helper')
    again = people.create_key('cus_1', 'helper')['agent_key']   # a new key replaces the old one
    assert people.agent_for_key(key) is None and people.agent_for_key(again) == ('cus_1', 'helper')
    assert people.agent_for_key('ack_' + 'x' * 43) is None and people.agent_for_key('nope') is None
    people.revoke_invite('cus_1')
    assert people.agent_for_key(again) is None and not people.invited('cus_1')
    with pytest.raises(PeopleError):
        people.invite('bad id with spaces')


def test_signed_in_customer_and_agent_key_share_one_wallet(customer_flow, tmp_path):  # noqa: F811
    x = customer_flow
    identity = x.s.identity
    customer_id = x.s.customer.customer_id
    settings = Settings(enabled=True, db_path=str(tmp_path / 'ad.sqlite3'), receipt_key_path=str(tmp_path / 'k.pem'),
                        admin_token='admin-secret-token')
    app = FastAPI()
    app.include_router(router_for(settings, customer_identity=lambda: identity))
    client = TestClient(app, base_url='https://customer.test')
    origin = {'Origin': 'https://customer.test'}
    assert client.get('/api/ad-coin/v1/account', headers=origin).json()['signed_in'] is False
    client.cookies.set(COOKIE, x.s.raw)
    account = client.get('/api/ad-coin/v1/account', headers=origin).json()
    assert account == {'signed_in': True, 'invited': False, 'account_id': customer_id,
                       'message': 'Ask the operator to invite this account id.'}
    assert client.get('/api/ad-coin/v1/wallets', headers=origin).status_code == 403
    admin = {'Authorization': 'Bearer admin-secret-token'}
    assert client.post('/api/ad-coin/v1/admin/invites', headers=admin,
                       json={'customer_id': customer_id, 'note': 'pilot'}).status_code == 200
    assert client.get('/api/ad-coin/v1/wallets', headers=origin).status_code == 200
    # a write from the session needs the CSRF proof
    assert client.post('/api/ad-coin/v1/agent-keys', headers=origin, json={'agent': 'helper'}).status_code == 403
    csrf = {**origin, 'X-Customer-CSRF': identity.csrf(x.s.raw)}
    created = client.post('/api/ad-coin/v1/agent-keys', headers=csrf, json={'agent': 'helper'}).json()
    key = created['agent_key']
    assert created['shown_once'] and key.startswith('ack_')
    assert client.post('/api/ad-coin/v1/agent-keys', headers={**origin, 'X-Customer-CSRF': '0' * 64},
                       json={'agent': 'other'}).status_code == 403
    # the agent acts without the cookie, as the agent named by its key
    agent = TestClient(app, base_url='https://agent.example')
    hdr = {'X-Ad-Coin-Agent-Key': key, 'X-Agent-Name': 'pretend-to-be-someone-else'}
    quote = agent.post('/api/ad-coin/v1/quotes', headers=hdr, json={'selection': SELECTION, 'task': TASK})
    assert quote.status_code == 200, quote.text
    wallets = agent.get('/api/ad-coin/v1/wallets', headers=hdr).json()['wallets']
    expected = 'wallet:agent:' + user_ref_for_customer(customer_id) + ':helper'
    assert expected in [w['account'] for w in wallets]
    assert agent.get('/api/ad-coin/v1/agent-keys', headers=hdr).status_code == 403   # keys are managed by the person
    mine = client.get('/api/ad-coin/v1/wallets', headers=origin).json()['wallets']
    assert expected in [w['account'] for w in mine]                                  # the same wallet the person sees
    assert client.get('/api/ad-coin/v1/agent-keys', headers=origin).json()['agent_keys'][0]['agent'] == 'helper'
    # the person revokes the agent; its key stops and its coins return
    revoked = client.post('/api/ad-coin/v1/agents/revoke', headers=csrf, json={'agent': 'helper'}).json()
    assert revoked['agent_keys_revoked'] == 1
    assert agent.get('/api/ad-coin/v1/wallets', headers=hdr).status_code == 403
    # revoking the invitation stops the person too
    key2 = client.post('/api/ad-coin/v1/agent-keys', headers=csrf, json={'agent': 'second'}).json()['agent_key']
    client.post('/api/ad-coin/v1/admin/invites/revoke', headers=admin, json={'customer_id': customer_id})
    assert client.get('/api/ad-coin/v1/wallets', headers=origin).status_code == 403
    assert agent.get('/api/ad-coin/v1/wallets', headers={'X-Ad-Coin-Agent-Key': key2}).status_code == 403
    # a cross-site page cannot use the person's cookie
    client.post('/api/ad-coin/v1/admin/invites', headers=admin, json={'customer_id': customer_id})
    cross = client.get('/api/ad-coin/v1/wallets', headers={'Origin': 'https://evil.example'})
    assert cross.status_code == 403
