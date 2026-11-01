"""Explicit private v2 approval/live testing has separate current authority."""
import asyncio
import json
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.capability_registry import Registry
from agent_market.gateway.admin_auth import init_admin_auth_db
from agent_market.gateway.dashboard import dashboard_router
from tests.test_fast_single_recommendation import catalog
from tests.test_managed_agent_gateway import managed
from tests.test_workflow_product_semantics import install_v2, product_fixture
from tests.test_workflow_publication_api import H
from tests.conftest import staff_session

CONTRACT = 'products.compare.v2'


@pytest.fixture
def live_product_api(managed):
    store, front, rid, calls, remote, registry = install_v2(managed)
    with store._lock: init_admin_auth_db(store._db)
    app = FastAPI(); app.include_router(dashboard_router(store, store._path, 'publication-admin', None, front=front))
    staff_session(store)
    client = TestClient(app, base_url='https://admin.example')
    yield store, front, client, rid, calls, remote, registry
    client.close()


def path(rid, suffix=''):
    return '/admin/api/connections/' + str(rid) + '/contracts/' + CONTRACT + suffix


def tool_calls(calls):
    return sum(json.loads(request.content).get('method') == 'tools/call' for request in calls)


def test_current_role_loss_immediately_before_approval_cannot_leave_a_new_approval(live_product_api):
    store, front, client, rid, calls, remote, registry = live_product_api
    original = Registry.approve
    def demote(instance, resource, contract_id, tool, **kwargs):
        with store.tx() as db: db.execute("UPDATE admin_users SET role='admin' WHERE username='synthetic-staff'")
        return original(instance, resource, contract_id, tool, **kwargs)
    with patch.object(Registry, 'approve', demote):
        response = client.post(path(rid), headers=H, json={'tool': 'compare_products'})
    assert response.status_code == 403 and response.headers['cache-control'] == 'no-store'
    assert not store.query('SELECT 1 FROM capability_approvals WHERE contract_id=?', (CONTRACT,))
    assert not calls


def test_real_private_v2_approval_and_guarded_contract_test_remain_explicit(live_product_api):
    store, front, client, rid, calls, remote, registry = live_product_api
    response = client.post(path(rid), headers=H, json={'tool': 'compare_products'})
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store' and not calls
    inputs, output, _ = product_fixture(); remote.call_result = {'structuredContent': output}
    denied = client.post(path(rid, '/test'), headers=H, json={'input': inputs})
    assert denied.status_code == 409 and not calls
    first = asyncio.run(front.managed_gateway.execute(rid, tool='compare_products', arguments=inputs))
    assert first['execution_succeeded']; calls.clear()
    tested = client.post(path(rid, '/test'), headers=H, json={'input': inputs})
    assert tested.status_code == 200 and tested.json()['ok'] is True, tested.text
    assert tested.headers['cache-control'] == 'no-store' and tool_calls(calls) == 1
    rows = store.query('SELECT outcome FROM capability_evidence WHERE contract_id=?', (CONTRACT,))
    assert len(rows) == 1 and rows[0]['outcome'] == 'succeeded'


def test_role_loss_during_live_response_does_not_certify_the_contract(live_product_api):
    store, front, client, rid, calls, remote, registry = live_product_api
    registry.approve(store.resource(rid), CONTRACT, 'compare_products')
    inputs, output, _ = product_fixture(); remote.call_result = {'structuredContent': output}
    first = asyncio.run(front.managed_gateway.execute(rid, tool='compare_products', arguments=inputs))
    assert first['execution_succeeded']; calls.clear()
    gateway = front.managed_gateway
    original = gateway.execute

    async def demote_after_response(*args, **kwargs):
        result = await original(*args, **kwargs)
        with store.tx() as db: db.execute("UPDATE admin_users SET role='admin' WHERE username='synthetic-staff'")
        return result

    with patch.object(gateway, 'execute', demote_after_response):
        response = client.post(path(rid, '/test'), headers=H, json={'input': inputs})
    assert response.status_code == 403 and response.headers['cache-control'] == 'no-store'
    assert tool_calls(calls) == 1
    assert not store.query('SELECT 1 FROM capability_evidence WHERE contract_id=?', (CONTRACT,))


@pytest.mark.parametrize('suffix', ['', '/test'])
@pytest.mark.parametrize('change', ["role='admin'", 'active=0'])
def test_legacy_token_does_not_override_current_role_for_private_v2(live_product_api, suffix, change):
    store, front, client, rid, calls, remote, registry = live_product_api
    with store.tx() as db: db.execute('UPDATE admin_users SET ' + change + " WHERE username='synthetic-staff'")
    inputs, _, _ = product_fixture(); body = {'input': inputs} if suffix else {'tool': 'compare_products'}
    response = client.post(path(rid, suffix), headers=H, json=body)
    # A deactivated account's individual session is gone (401); a demoted one is refused (403).
    assert response.status_code == (401 if change == 'active=0' else 403) and response.headers['cache-control'] == 'no-store' and not calls
    assert not store.query('SELECT 1 FROM capability_approvals WHERE contract_id=?', (CONTRACT,))


@pytest.mark.parametrize('suffix,raw', [('', '{"tool":"compare_products","tool":"other"}'),
    ('', '{"tool":NaN}'), ('', '{"tool":1e999}'), ('', 'x' * 131073),
    ('/test', '{"input":{},"input":{}}'), ('/test', '{"input":{"limit":1e999}}')])
def test_private_live_v2_uses_strict_bounded_json(live_product_api, suffix, raw):
    store, front, client, rid, calls, remote, registry = live_product_api
    response = client.post(path(rid, suffix), headers=H, content=raw)
    assert response.status_code == 400 and response.headers['cache-control'] == 'no-store' and not calls


@pytest.mark.parametrize('suffix', ['', '/test'])
def test_v2_auth_origin_and_path_errors_are_no_store_without_raw_input(live_product_api, suffix):
    store, front, client, rid, calls, remote, registry = live_product_api
    assert client.post(path(rid, suffix), json={}).headers['cache-control'] == 'no-store'
    crossed = client.post(path(rid, suffix), headers=H | {'Origin': 'https://attacker.example'}, json={})
    assert crossed.status_code == 403 and crossed.headers['cache-control'] == 'no-store'
    invalid = client.post(path('not-an-id', suffix), headers=H, json={})
    assert invalid.status_code == 422 and invalid.headers['cache-control'] == 'no-store'
    assert 'not-an-id' not in invalid.text and not calls


def test_unexpected_v2_approval_errors_are_fixed_and_not_cached(live_product_api):
    store, front, client, rid, calls, remote, registry = live_product_api
    with patch.object(Registry, 'approve', side_effect=RuntimeError('/private/internal synthetic-secret')):
        response = client.post(path(rid), headers=H, json={'tool': 'compare_products'})
    assert response.status_code == 500 and response.headers['cache-control'] == 'no-store'
    assert '/private/' not in response.text and 'synthetic-secret' not in response.text and not calls
