"""AI AD Coin quotes a customer's own saved typed flow through the real workspace boundary."""
import hashlib

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.ad_coin.api import router_for
from agent_market.ad_coin.config import Settings
from agent_market.ad_coin.private_workflows import reader_for
from agent_market.customer_identity_service import COOKIE
from agent_market.workspace_app_factory import NOTICE
from tests.test_customer_typed_authoring import customer_flow  # noqa: F401  (fixture)
from tests.test_workspace_typed_release import typed_release_world  # noqa: F401  (fixture)
from tests.test_workspace_typed_flows import typed_world, routing, graph  # noqa: F401  (fixtures)


def test_own_saved_flow_is_priced_and_others_are_refused(customer_flow, tmp_path):  # noqa: F811
    x = customer_flow
    review = x.core.factory.prepare_plan(x.ws, {'name': 'Reviewed customer graph', 'definition': graph(x.w),
                                                'base_flow_id': None, 'base_revision': None}, x.actor)
    flow = x.core.factory.commit(x.ws, {'review_id': review['review_id'], 'authorized': True, 'notice': NOTICE},
                                 x.actor)
    detail = x.core.typed.detail(x.ws, flow['id'], x.actor)
    resource_ids = sorted({n['resource_id'] for n in detail['definition']['nodes']})
    priced = {rid: {'id': rid, 'name': 'Agent %d' % rid, 'kind': 'x402', 'price_usdc': 100_000, 'eval_grade': 'A',
                    'health_status': 'healthy', 'category': 'Research', 'active': 1} for rid in resource_ids}

    class Store:
        def resource(self, rid):
            return priced.get(rid)
    token = 'invited-visitor-token'
    settings = Settings(enabled=True, db_path=str(tmp_path / 'ad.sqlite3'), receipt_key_path=str(tmp_path / 'k.pem'),
                        admin_token='admin-secret-token', invited=frozenset({hashlib.sha256(token.encode()).hexdigest()}))
    app = FastAPI()
    app.include_router(router_for(settings, store=Store(),
                                  private_flow_reader=reader_for(None, True, core_factory=lambda: x.core)))
    client = TestClient(app, base_url='https://customer.test')
    headers = {'X-Visitor-Token': token, 'Origin': 'https://customer.test'}
    body = {'private_workflow': {'workspace_id': x.ws, 'flow_id': flow['id'], 'runs': 5}}
    assert client.post('/api/ad-coin/v1/upgrade-check', headers=headers, json=body).status_code == 401
    client.cookies.set(COOKIE, x.s.raw)
    ok = client.post('/api/ad-coin/v1/upgrade-check', headers=headers, json=body)
    assert ok.status_code == 200, ok.text
    value = ok.json()
    assert value['upgrade_available'] and value['workflow']['kind'] == 'private_workflow'
    assert {line['resource_id'] for line in value['lines']} == set(resource_ids)
    assert 'Reviewed customer graph' not in ok.text  # the private flow's name and inputs stay private
    other = {'private_workflow': {'workspace_id': 'ws_' + '0' * 32, 'flow_id': flow['id'], 'runs': 1}}
    assert client.post('/api/ad-coin/v1/upgrade-check', headers=headers, json=other).status_code == 403
    missing = {'private_workflow': {'workspace_id': x.ws, 'flow_id': 'wtf_' + '0' * 32, 'runs': 1}}
    assert client.post('/api/ad-coin/v1/upgrade-check', headers=headers, json=missing).status_code == 403
    cross = client.post('/api/ad-coin/v1/upgrade-check', json=body,
                        headers={'X-Visitor-Token': token, 'Origin': 'https://evil.example'})
    assert cross.status_code in (401, 403)
