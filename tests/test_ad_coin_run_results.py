"""AI AD Coin settles workflow executions from the runs that actually happened."""
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.ad_coin import ledger as L
from agent_market.ad_coin.api import router_for
from agent_market.ad_coin.config import Settings
from agent_market.ad_coin.run_results import SQL_RUN, SQL_STEPS, parse_task_ref, public_run
from agent_market.ad_coin.upgrade import workflow_check
from agent_market.gateway.store import Store
from agent_market.workflows import runtime_for
from tests.test_ad_coin import MICRO, WORKFLOW, campaign, option, view  # noqa: F401
from tests.test_ad_coin import svc  # noqa: F401  (fixture)

ADMIN = {'Authorization': 'Bearer admin-secret-token'}


def test_run_queries_are_registered_for_the_production_store():
    registered = json.load(open('agent_market/application_store_sql.json'))
    texts = set()

    def walk(value):
        if isinstance(value, dict):
            if isinstance(value.get('sqlite'), str):
                texts.add(value['sqlite'])
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(registered)
    assert SQL_RUN in texts and SQL_STEPS in texts


def test_task_refs_name_what_to_settle_from():
    assert parse_task_ref('workflow-39-ffffffffffff-x10') == {'kind': 'workflow', 'id': 39, 'runs': 10}
    assert parse_task_ref('workflow-39-x2') == {'kind': 'workflow', 'id': 39, 'runs': 2}
    assert parse_task_ref('private-wtf_' + 'a' * 32 + '-0123456789ab-x5')['kind'] == 'private_workflow'
    assert parse_task_ref('compare-5-papers') is None and parse_task_ref('workflow-x-x1') is None


def _store():
    store = Store(':memory:')
    runtime_for(store)  # creates the run tables
    return store


def _add_run(store, run_id, workflow_id, steps, status='succeeded', created=None):
    with store.tx() as db:
        db.execute('INSERT INTO workflow_runs (id,workflow_id,digest,snapshot,actor,source,status,created) '
                   'VALUES (?,?,?,?,?,?,?,?)', (run_id, workflow_id, 'd', '{}', 'public', 'public', status,
                                               created or time.time()))
        for node_id, state in steps.items():
            db.execute('INSERT INTO workflow_node_runs (run_id,node_id,status) VALUES (?,?,?)', (run_id, node_id, state))


def _client(tmp_path, store, workflows):
    settings = Settings(enabled=True, db_path=str(tmp_path / 'ad.sqlite3'), receipt_key_path=str(tmp_path / 'k.pem'),
                        admin_token='admin-secret-token')

    class Catalog:
        def resource(self, rid):
            return MICRO.get(rid)

        def query(self, sql, args=()):
            return store.query(sql, args)
    router = router_for(settings, store=Catalog(), workflow_reader=workflows.get)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), router.ad_coin_service


def test_sponsored_workflow_run_settles_per_successful_call(tmp_path):
    store = _store()
    client, svc = _client(tmp_path, store, {39: WORKFLOW})
    c = campaign(svc, categories=('research',))
    check = workflow_check({39: WORKFLOW}.get, MICRO.get, 39, 10)
    packet = svc.quote(user_ref='u_admin', agent_ref='helper', operator_ref='agent:helper', **check['quote_request'])
    award = view(svc, option(packet, 'sponsored_run')['reservation_id'], user='u_admin')
    started = svc.redeem_voucher(user_ref='u_admin', voucher_id=award['voucher_id'])
    execution = started['execution_id']
    escrow_before = svc.campaign(c['id'])['escrow_won']
    # ten quoted runs; in three of them the routed step b (agent 8) did not run
    runs = []
    for i in range(10):
        steps = {'a': 'succeeded', 'c': 'succeeded', 'b': 'skipped' if i < 3 else 'succeeded', 'free': 'succeeded'}
        _add_run(store, 'run_%02d_abcdef' % i, 39, steps)
        runs.append('run_%02d_abcdef' % i)
    _add_run(store, 'old_run_abcdef', 39, {'a': 'succeeded'}, created=time.time() - 3600)
    _add_run(store, 'other_wf_abcdef', 40, {'a': 'succeeded'})
    _add_run(store, 'busy_run_abcdef', 39, {'a': 'running'}, status='running')
    path = '/api/ad-coin/v1/admin/executions/settle-from-runs'
    for bad, code in ((runs[:9], 'invalid_runs'), (runs[:9] + ['old_run_abcdef'], 'run_before_payment'),
                      (runs[:9] + ['other_wf_abcdef'], 'run_of_another_workflow'),
                      (runs[:9] + ['missing_abcdef'], 'unknown_run')):
        response = client.post(path, headers=ADMIN, json={'execution_id': execution, 'run_ids': bad})
        assert response.status_code == 409 and response.json()['error'] == code
    waiting = client.post(path, headers=ADMIN, json={'execution_id': execution, 'run_ids': runs[:9] + ['busy_run_abcdef']})
    assert waiting.json()['status'] == 'waiting'
    done = client.post(path, headers=ADMIN, json={'execution_id': execution, 'run_ids': runs}).json()
    # lines: agent 7 x20 calls (two nodes a and c per run) all succeeded; agent 8 x10, 7 succeeded; free x10
    assert done['line_calls_succeeded'] == [20, 7, 10]
    assert done['status'] == 'partial' and done['refunded_won'] == check['lines'][1]['won'] - check['lines'][1]['won'] * 7 // 10
    assert svc.ledger.balance(L.provider_payable('r7')) == check['lines'][0]['won']
    assert svc.ledger.balance(L.provider_payable('r8')) == check['lines'][1]['won'] * 7 // 10
    assert svc.campaign(c['id'])['escrow_won'] == escrow_before + done['refunded_won']
    assert svc.ledger.invariant()['ok']
    again = client.post(path, headers=ADMIN, json={'execution_id': execution, 'run_ids': runs})
    assert again.json()['error'] == 'execution_closed'


def test_a_run_settles_only_one_execution(tmp_path):
    store = _store()
    client, svc = _client(tmp_path, store, {39: WORKFLOW})
    wallet = svc._ensure_wallet('u_admin', 'helper')
    svc.ledger.post('promo', 'p', [(L.EXTERNAL_FUNDING, -1000), (wallet, 1000)])
    check = workflow_check({39: WORKFLOW}.get, MICRO.get, 39, 1)
    task = check['quote_request']['task']
    first = svc.spend(user_ref='u_admin', wallet=wallet, provider='bundle', task_ref=task['task_ref'],
                      price_coins=task['price_won'] // 10, idem='a', lines=task['lines'])
    second = svc.spend(user_ref='u_admin', wallet=wallet, provider='bundle', task_ref=task['task_ref'],
                       price_coins=task['price_won'] // 10, idem='b', lines=task['lines'])
    _add_run(store, 'run_one_abcdef', 39, {'a': 'succeeded', 'b': 'failed', 'c': 'succeeded'})
    path = '/api/ad-coin/v1/admin/executions/settle-from-runs'
    ok = client.post(path, headers=ADMIN, json={'execution_id': first['execution_id'], 'run_ids': ['run_one_abcdef']})
    assert ok.json()['line_calls_succeeded'] == [2, 0, 0]       # b failed; the free step did not run
    reuse = client.post(path, headers=ADMIN, json={'execution_id': second['execution_id'], 'run_ids': ['run_one_abcdef']})
    assert reuse.json()['error'] == 'run_already_used'
    assert svc.ledger.balance(wallet) == 1000 - 2 * task['price_won'] + ok.json()['refunded_won']
    assert public_run(store, 'run_one_abcdef')['workflow_id'] == 39


def test_test_products_are_not_settled_from_runs(svc):  # noqa: F811
    from agent_market.ad_coin.run_results import RunMismatch, reconcile
    wallet = svc._ensure_wallet('u_alice', 'helper')
    svc.ledger.post('promo', 'p', [(L.EXTERNAL_FUNDING, -1000), (wallet, 1000)])
    run = svc.spend(user_ref='u_alice', wallet=wallet, provider='bundle', task_ref='product-tp_0123456789abcdef-x1',
                    price_coins=10, idem='z', lines=[{'provider': 'r7', 'calls': 1, 'won': 100}])
    with pytest.raises(RunMismatch) as exc:
        reconcile(svc, execution_id=run['execution_id'], user_ref='u_alice', run_ids=['abcdef1'],
                  load_run=lambda r: None, definition={})
    assert exc.value.code == 'not_a_workflow_execution'
    with pytest.raises(RunMismatch):
        reconcile(svc, execution_id=run['execution_id'], user_ref='u_bob', run_ids=['abcdef1'],
                  load_run=lambda r: None, definition={})
