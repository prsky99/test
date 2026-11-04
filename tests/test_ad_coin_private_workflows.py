"""AI AD Coin quotes a customer's own saved typed flow through the real workspace boundary."""
import hashlib

import pytest
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


def test_own_flow_run_settles_the_coins_spent_on_it(customer_flow, tmp_path):  # noqa: F811
    from agent_market.ad_coin import ledger as L
    from agent_market.ad_coin.private_workflows import project, run_reader_for
    from agent_market.ad_coin.upgrade import check_definition
    from agent_market.workspace_typed_flows import NOTICE as RUN_NOTICE
    x = customer_flow
    review = x.core.factory.prepare_plan(x.ws, {'name': 'Reviewed customer graph', 'definition': graph(x.w),
                                                'base_flow_id': None, 'base_revision': None}, x.actor)
    flow = x.core.factory.commit(x.ws, {'review_id': review['review_id'], 'authorized': True, 'notice': NOTICE},
                                 x.actor)
    detail = x.core.typed.detail(x.ws, flow['id'], x.actor)
    ids = sorted({n['resource_id'] for n in detail['definition']['nodes']})
    priced = {rid: {'id': rid, 'name': 'Agent %d' % rid, 'kind': 'x402', 'price_usdc': 100_000, 'eval_grade': 'A',
                    'health_status': 'healthy', 'category': 'Research', 'active': 1} for rid in ids}

    class Store:
        def resource(self, rid):
            return priced.get(rid)
    token = 'invited-visitor-token'
    settings = Settings(enabled=True, db_path=str(tmp_path / 'ad.sqlite3'), receipt_key_path=str(tmp_path / 'k.pem'),
                        admin_token='admin-secret-token', invited=frozenset({hashlib.sha256(token.encode()).hexdigest()}))
    router = router_for(settings, store=Store(),
                        private_flow_reader=reader_for(None, True, core_factory=lambda: x.core),
                        private_run_reader=run_reader_for(None, True, core_factory=lambda: x.core))
    app = FastAPI()
    app.include_router(router)
    svc = router.ad_coin_service
    check = check_definition(project(detail), Store().resource, 1, 'private_workflow', flow['id'])
    task = check['quote_request']['task']
    from agent_market.ad_coin.api import user_ref_of
    who = user_ref_of(token)
    wallet = svc._ensure_wallet(who, 'helper')
    svc.ledger.post('promo', 'p', [(L.EXTERNAL_FUNDING, -100000), (wallet, 100000)])
    spent = svc.spend(user_ref=who, wallet=wallet, provider='bundle', task_ref=task['task_ref'],
                      price_coins=task['price_won'] // 10, idem='run1', lines=task['lines'])
    plan = x.core.typed.prepare(x.ws, flow['id'], {'revision': 1}, x.actor)
    run = x.core.typed.execute(x.ws, flow['id'], {'ticket_id': plan['ticket_id'], 'authorized': True,
                                                  'notice': RUN_NOTICE}, x.actor)['run']
    client = TestClient(app, base_url='https://customer.test')
    headers = {'X-Visitor-Token': token, 'Origin': 'https://customer.test'}
    body = {'execution_id': spent['execution_id'], 'workspace_id': x.ws, 'run_ids': [run['id']]}
    assert client.post('/api/ad-coin/v1/executions/settle-from-runs', headers=headers, json=body).status_code == 401
    client.cookies.set(COOKIE, x.s.raw)
    settled = client.post('/api/ad-coin/v1/executions/settle-from-runs', headers=headers, json=body)
    assert settled.status_code == 200, settled.text
    value = settled.json()
    if value.get('status') == 'waiting':
        pytest.skip('the fixture run did not finish synchronously')
    steps = {s['node_id']: s['status'] for s in x.core.typed.get(x.ws, flow['id'], run['id'], x.actor)['steps']}
    expected_ok = sum(1 for n in detail['definition']['nodes'] if steps.get(n['id']) == 'succeeded')
    assert sum(value['line_calls_succeeded']) == expected_ok
    assert value['paid_won'] + value['refunded_won'] == task['price_won'] and svc.ledger.invariant()['ok']
    admin = client.post('/api/ad-coin/v1/admin/executions/settle-from-runs', json=body,
                        headers={'Authorization': 'Bearer admin-secret-token'})
    assert admin.status_code == 403   # operators never settle a customer's private runs
