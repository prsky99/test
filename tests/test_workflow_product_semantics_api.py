"""Offline product API bounds and authority use isolated databases only."""
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import patch

import pytest

from agent_market.gateway.admin_auth import create_admin_user
from agent_market.workflow_product_semantics import PROFILE, CONTRACT_ID
from tests.test_admin_security_audit import login, session_headers
from tests.test_workflow_fallback import routing
from tests.test_workflow_typed_flow import typed_routing
from tests.test_workflow_publication_api import publication_api, H

BASE = '/admin/api/workflow-product-semantics'


@pytest.fixture
def product_semantics_api(publication_api):
    return publication_api


def product_body():
    stamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    inputs = {'query': 'Compare two example devices', 'language': 'en', 'limit': 2,
              'criteria': [{'criterion_id': 'weight', 'dimension': 'mass'}]}
    items = []
    for suffix, value, unit, amount in [('a', '1', 'kg', '12.00'), ('b', '1000', 'g', '14.00')]:
        url = 'https://evidence.example/product-' + suffix
        items.append({'identity': {'brand': 'Example', 'model': 'Device ' + suffix, 'variant': 'Standard',
                      'identifier': {'scheme': 'manufacturer_sku', 'value': 'SKU-' + suffix}},
                      'name': 'Example device ' + suffix, 'url': url, 'retrieved_at': stamp,
                      'measurements': [{'criterion_id': 'weight', 'dimension': 'mass', 'status': 'reported',
                          'quantity': {'value': value, 'unit': unit}, 'source_url': url, 'observed_at': stamp}],
                      'price': {'status': 'reported', 'amount': amount, 'currency': 'USD',
                          'basis': {'unit': 'item', 'quantity': '1', 'pack_count': None},
                          'source_url': url, 'observed_at': stamp}})
    return {'input': inputs, 'output': {'items': items, 'partial': False}}


def test_schema_options_and_validation_are_private_offline_without_quality_or_execution_effects(product_semantics_api):
    rt, public, admin, calls, modes = product_semantics_api
    before = rt.store._db.total_changes
    with (patch.object(rt, 'submit', side_effect=AssertionError('No workflow execution')),
          patch.object(rt.proxy, 'execute', side_effect=AssertionError('No provider invocation'))):
        schema = admin.get(BASE + '/schema', headers=H)
        assert schema.status_code == 200 and schema.headers['cache-control'] == 'no-store'
        assert schema.json()['profile'] == PROFILE and schema.json()['contract_id'] == CONTRACT_ID
        assert schema.json()['contract']['version'] == 2
        options = admin.get(BASE + '/options', headers=H)
        assert options.status_code == 200 and not options.json()['compiler_enabled'] and not options.json()['fallback_enabled']
        catalog = options.json()['catalog']
        assert catalog['eligible_provider_count'] is None and catalog['readiness'] == 'not-evaluated'
        assert catalog['live_execution_integration_enabled'] is False
        assert set(catalog['recorded_approval_rows']) == {'products.compare.v1', 'products.compare.v2'}
        response = admin.post(BASE + '/validate', headers=H, json=product_body())
        assert response.status_code == 200, response.text
    value = response.json()
    assert value['assessment'] == 'offline_structure_valid' and value['origin'] == 'user_supplied'
    assert all(flag is False for flag in value['claims'].values())
    assert value['normalized'][0]['measurements'][0]['normalized_quantity'] == {'value': '1', 'unit': 'kg'}
    assert value['normalized'][1]['measurements'][0]['normalized_quantity'] == {'value': '1', 'unit': 'kg'}
    assert value['comparisons'][0]['measurements'][0]['status'] == 'comparable'
    assert not calls and rt.store._db.total_changes == before
    assert not rt.store.query('SELECT id FROM workflow_runs')


@pytest.mark.parametrize('role', ['operator', 'admin'])
def test_all_product_inspection_routes_require_highest_current_admin(product_semantics_api, role):
    rt, public, admin, calls, modes = product_semantics_api
    with rt.store.tx() as db: create_admin_user(db, 'product-viewer', 'viewer-password-long', 'Viewer', role)
    token = login(admin, 'product-viewer', 'viewer-password-long').json()['token']; headers = session_headers(token)
    for route in ('schema', 'options'):
        response = admin.get(BASE + '/' + route, headers=headers)
        assert response.status_code == 403 and response.headers['cache-control'] == 'no-store'
        assert admin.get(BASE + '/' + route).status_code in (401, 403)
    response = admin.post(BASE + '/validate', headers=headers, json=product_body())
    assert response.status_code == 403 and response.headers['cache-control'] == 'no-store'
    assert not calls


@pytest.mark.parametrize('change', ["role='admin'", 'active=0'])
def test_legacy_admin_token_cannot_override_a_current_database_role_or_deactivation(product_semantics_api, change):
    rt, public, admin, calls, modes = product_semantics_api
    with rt.store.tx() as db: db.execute('UPDATE admin_users SET ' + change + " WHERE username='synthetic-staff'")
    refused = 401 if change == 'active=0' else 403  # a deactivated account's session is gone
    for route in ('schema', 'options'):
        assert admin.get(BASE + '/' + route, headers=H).status_code == refused
    assert admin.post(BASE + '/validate', headers=H, json=product_body()).status_code == refused
    assert not calls


@pytest.mark.parametrize('headers', [{'Origin': 'null'}, {'Origin': 'https://attacker.example'}, {'Sec-Fetch-Site': 'cross-site'}])
def test_cross_origin_or_csrf_product_sample_is_denied(product_semantics_api, headers):
    rt, public, admin, calls, modes = product_semantics_api
    response = admin.post(BASE + '/validate', headers=H | headers, json=product_body())
    assert response.status_code == 403 and response.headers['cache-control'] == 'no-store' and not calls


@pytest.mark.parametrize('raw', ['[]', 'null', '{"input":NaN,"output":{}}', '{"input":1e999,"output":{}}',
    '{"input":{},"input":{},"output":{}}', '{"input":{"x":1,"x":2},"output":{}}', 'x' * 131073])
def test_duplicate_nonfinite_or_oversize_json_is_refused_before_validation(product_semantics_api, raw):
    rt, public, admin, calls, modes = product_semantics_api; before = rt.store._db.total_changes
    response = admin.post(BASE + '/validate', headers=H, content=raw)
    assert response.status_code == 400 and response.headers['cache-control'] == 'no-store'
    assert rt.store._db.total_changes == before and not calls


@pytest.mark.parametrize('kind', ['depth', 'nodes', 'utf8_bytes'])
def test_explicit_tree_and_utf8_body_limits_are_enforced(product_semantics_api, kind):
    rt, public, admin, calls, modes = product_semantics_api
    value = {}
    if kind == 'depth':
        for _ in range(20): value = {'nested': value}
    elif kind == 'nodes': value = {'items': [0] * 3001}
    else: value = {'text': '\u00e9' * 70000}
    response = admin.post(BASE + '/validate', headers=H,
                          content=json.dumps({'input': value, 'output': {}}, ensure_ascii=False))
    assert response.status_code == 400 and response.headers['cache-control'] == 'no-store' and not calls


@pytest.mark.parametrize('change', ['extra', 'null_output', 'bool_limit', 'untyped_quantity', 'numeric_price', 'wrong_dimension', 'missing_unmarked', 'unsafe_url', 'gateway_source', 'legacy_criterion', 'stale'])
def test_untyped_ambiguous_or_unsafe_product_evidence_is_not_promoted(product_semantics_api, change):
    rt, public, admin, calls, modes = product_semantics_api; body = product_body()
    if change == 'extra': body['execute'] = True
    elif change == 'null_output': body['output'] = None
    elif change == 'bool_limit': body['input']['limit'] = True
    elif change == 'untyped_quantity': body['output']['items'][0]['measurements'][0]['quantity'] = 'one kilogram'
    elif change == 'numeric_price': body['output']['items'][0]['price']['amount'] = 12.0
    elif change == 'wrong_dimension': body['output']['items'][0]['measurements'][0]['dimension'] = 'length'
    elif change == 'missing_unmarked': body['output']['items'][0]['price']['amount'] = None
    elif change == 'unsafe_url': body['output']['items'][0]['url'] = 'https://user:secret@evidence.example/item'
    elif change == 'gateway_source': body['output']['items'][0]['price']['source_url'] = 'https://agentconcierge.biz/api/gateway/mcp/1'
    elif change == 'legacy_criterion': body['input']['criteria'][0]['key'] = body['input']['criteria'][0].pop('criterion_id')
    else: body['output']['items'][0]['retrieved_at'] = '2000-01-01T00:00:00Z'
    before = rt.store._db.total_changes
    response = admin.post(BASE + '/validate', headers=H, json=body)
    assert response.status_code == 409 and response.headers['cache-control'] == 'no-store'
    assert 'user:secret' not in response.text and rt.store._db.total_changes == before and not calls


def test_currency_and_price_basis_mismatch_are_explicit_without_fx_or_ranking(product_semantics_api):
    rt, public, admin, calls, modes = product_semantics_api; body = product_body()
    body['output']['items'][1]['price']['currency'] = 'EUR'
    response = admin.post(BASE + '/validate', headers=H, json=body)
    assert response.status_code == 200 and response.json()['comparisons'][0]['price']['status'] == 'currency_mismatch'
    assert response.json()['comparisons'][0]['price']['left_amount'] is None
    body['output']['items'][1]['price']['currency'] = 'USD'
    body['output']['items'][1]['price']['basis'] = {'unit': 'pack', 'quantity': '1', 'pack_count': 2}
    response = admin.post(BASE + '/validate', headers=H, json=body)
    assert response.status_code == 200 and response.json()['comparisons'][0]['price']['status'] == 'basis_mismatch'
    assert not response.json()['claims']['fx_applied'] and not response.json()['claims']['ranking'] and not calls


def test_missing_and_partial_evidence_remain_explicit_without_inferred_values(product_semantics_api):
    rt, public, admin, calls, modes = product_semantics_api; body = product_body()
    body['output']['partial'] = True
    body['output']['items'][1]['measurements'][0].update(status='missing', quantity=None, source_url=None, observed_at=None)
    body['output']['items'][1]['price'].update(status='missing', amount=None, currency=None, basis=None, source_url=None, observed_at=None)
    response = admin.post(BASE + '/validate', headers=H, json=body)
    assert response.status_code == 200, response.text
    value = response.json(); assert value['partial'] is True
    assert value['comparisons'][0]['measurements'][0]['status'] == 'missing_evidence'
    assert value['comparisons'][0]['price']['status'] == 'missing_evidence'
    assert value['normalized'][1]['measurements'][0]['normalized_quantity'] is None and not calls


def test_rollout_marker_is_private_and_no_execution_approval_or_public_routes_are_added(product_semantics_api):
    rt, public, admin, calls, modes = product_semantics_api
    assert admin.get('/admin/api/workflows', headers=H).json()['product_semantics_profile'] == PROFILE
    assert 'product_semantics_profile' not in public.get('/api/workflow-connections').text
    for path in ('/api/workflow-product-semantics/validate', BASE + '/execute', BASE + '/approve', BASE + '/publish'):
        target = public if path.startswith('/api/') else admin
        assert target.post(path, headers=H, json=product_body()).status_code == 404
    assert not calls


def test_unexpected_validator_failure_does_not_echo_private_diagnostics(product_semantics_api):
    rt, public, admin, calls, modes = product_semantics_api
    with patch('agent_market.workflow_product_semantics.ProductSemantics.validate', side_effect=RuntimeError('/private/internal synthetic-secret')):
        response = admin.post(BASE + '/validate', headers=H, json=product_body())
    assert response.status_code == 500 and response.headers['cache-control'] == 'no-store'
    assert '/private/' not in response.text and 'synthetic-secret' not in response.text and not calls


def test_different_observation_instants_are_explicitly_incomparable_without_losing_reported_values(product_semantics_api):
    rt, public, admin, calls, modes = product_semantics_api; body = product_body()
    earlier = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat().replace('+00:00', 'Z')
    right = body['output']['items'][1]; right['measurements'][0]['observed_at'] = earlier; right['price']['observed_at'] = earlier
    response = admin.post(BASE + '/validate', headers=H, json=body)
    assert response.status_code == 200, response.text
    pair = response.json()['comparisons'][0]
    assert pair['measurements'][0]['status'] == pair['price']['status'] == 'observation_time_mismatch'
    assert pair['price']['observation']['temporal_relation'] == 'different_instants'
    assert pair['price']['left_amount'] is None and pair['measurements'][0]['left_value'] is None
    assert response.json()['normalized'][1]['measurements'][0]['original_quantity'] == {'value': '1000', 'unit': 'g'}
    assert not response.json()['claims']['ranking'] and not calls


def test_equivalent_utc_notations_preserve_same_instant_comparability(product_semantics_api):
    rt, public, admin, calls, modes = product_semantics_api; body = product_body()
    for row in body['output']['items'][1]['measurements'] + [body['output']['items'][1]['price']]:
        row['observed_at'] = row['observed_at'].replace('Z', '+00:00')
    response = admin.post(BASE + '/validate', headers=H, json=body)
    assert response.status_code == 200, response.text
    pair = response.json()['comparisons'][0]
    assert pair['measurements'][0]['status'] == pair['price']['status'] == 'comparable'
    assert pair['price']['observation']['temporal_relation'] == 'same_instant' and not calls


def test_decimal_and_binary_storage_units_are_normalized_exactly_without_ranking(product_semantics_api):
    rt, public, admin, calls, modes = product_semantics_api; body = product_body()
    body['input']['criteria'] = [{'criterion_id': 'capacity', 'dimension': 'storage'}]
    for row, unit in zip(body['output']['items'], ('GB', 'GiB')):
        row['measurements'][0].update(criterion_id='capacity', dimension='storage', quantity={'value': '1', 'unit': unit})
    response = admin.post(BASE + '/validate', headers=H, json=body)
    assert response.status_code == 200, response.text
    normalized = response.json()['normalized']
    assert normalized[0]['measurements'][0]['normalized_quantity'] == {'value': '1000000000', 'unit': 'byte'}
    assert normalized[1]['measurements'][0]['normalized_quantity'] == {'value': '1073741824', 'unit': 'byte'}
    assert not response.json()['claims']['ranking'] and not calls


def test_catalog_diagnostics_do_not_refresh_registry_or_invent_unknown_counts(product_semantics_api):
    import sqlite3
    rt, public, admin, calls, modes = product_semantics_api; before = rt.store._db.total_changes
    with patch('agent_market.capability_registry.Registry.current', side_effect=AssertionError('No version refresh')):
        assert admin.get(BASE + '/options', headers=H).status_code == 200
    original = rt.store.query
    def unavailable(sql, params=()):
        if 'FROM capability_approvals' in sql: raise sqlite3.OperationalError('synthetic catalog unavailable')
        return original(sql, params)
    with patch.object(rt.store, 'query', side_effect=unavailable):
        response = admin.get(BASE + '/options', headers=H)
    assert response.status_code == 200 and response.json()['catalog']['available'] is False
    assert all(value is None for value in response.json()['catalog']['recorded_approval_rows'].values())
    assert response.json()['catalog']['eligible_provider_count'] is None
    assert rt.store._db.total_changes == before and not calls


def test_role_withdrawal_while_processing_blocks_the_late_offline_result(product_semantics_api):
    from agent_market.workflow_product_semantics import ProductSemantics
    rt, public, admin, calls, modes = product_semantics_api; original = ProductSemantics.validate
    def withdraw(instance, body):
        value = original(instance, body)
        with rt.store.tx() as db: db.execute("UPDATE admin_users SET role='admin' WHERE username='synthetic-staff'")
        return value
    with patch.object(ProductSemantics, 'validate', withdraw):
        response = admin.post(BASE + '/validate', headers=H, json=product_body())
    assert response.status_code == 403 and response.headers['cache-control'] == 'no-store'
    assert 'normalized' not in response.text and not calls
