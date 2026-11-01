"""Actual private advancement routes with isolated current owner authority."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pathlib import Path
import re
import pytest

from agent_market.advancement_service import router_for
from agent_market.gateway.admin_auth import session_reference
from agent_market.workspace_agreements import NOTICE
from tests.test_workspace_agreements import agreement
from tests.test_provider_claims import provider
from tests.test_workspace_access import provision
from tests.test_workspace_execution_api import private_api


@pytest.fixture
def agreements_api(agreement):
    w = agreement
    app = FastAPI(); app.include_router(router_for(w.access, agreements=w.agreements)); w.app = app
    w.api = TestClient(app, base_url='https://private.test')
    w.base = '/admin/api/workflow-workspaces/' + w.ws + '/advancement'
    w.header = {'X-Dashboard': '1', 'Authorization': 'Bearer ' + w.raw_staff}
    try:
        yield w
    finally:
        w.api.close()


def capture_api(w, amount=101):
    quote = w.api.post(w.base + '/agreements/' + w.agreement['id'] + '/quote', headers=w.header, json={'gross_units': amount})
    assert quote.status_code == 200, quote.text
    command = {'event_reference': 'sim_api_capture', 'gross_units': amount,
        'quote_hash': quote.json()['result']['quote_hash'], 'revision': 1,
        'authorized': True, 'notice': NOTICE}
    captured = w.api.post(w.base + '/agreements/' + w.agreement['id'] + '/settle', headers=w.header, json=command)
    assert captured.status_code == 200, captured.text
    return captured.json()['result'], command


def test_actual_agreement_routes_create_quote_capture_refund_and_balance(agreements_api):
    w = agreements_api
    for path in ('/agreements/options', '/agreements', '/agreements/summary'):
        result = w.api.get(w.base + path, headers=w.header)
        assert result.status_code == 200 and result.headers['cache-control'] == 'no-store'
        assert result.json()['result']['commercial_enabled'] is False
    created = w.api.post(w.base + '/agreements', headers=w.header, json=w.body | {'revision': 1})
    assert created.status_code == 200, created.text
    w.agreement = created.json()['result']
    current, command = capture_api(w)
    duplicate = w.api.post(w.base + '/agreements/' + w.agreement['id'] + '/settle', headers=w.header, json=command)
    assert duplicate.status_code == 200 and duplicate.json()['result']['replayed']
    refund = {'event_reference': 'sim_api_refund', 'units': 30, 'revision': 1, 'authorized': True, 'notice': NOTICE}
    path = w.base + '/agreement-settlements/' + current['id'] + '/refund'
    result = w.api.post(path, headers=w.header, json=refund)
    assert result.status_code == 200 and result.json()['result']['refunded_units'] == 30, result.text
    stale = w.api.post(path, headers=w.header, json=refund | {'event_reference': 'sim_api_stale'})
    assert stale.status_code == 409
    summary = w.api.get(w.base + '/agreements/summary', headers=w.header)
    assert summary.json()['result']['balanced'] and len(w.provider_calls) == 1
    revoked = w.api.post(w.base + '/agreements/' + w.agreement['id'] + '/revoke', headers=w.header, json={'revision': 1})
    assert revoked.status_code == 200 and revoked.json()['result']['status'] == 'revoked'
    assert w.api.post(w.base + '/agreements/' + w.agreement['id'] + '/quote', headers=w.header, json={'gross_units': 1}).status_code == 404


@pytest.mark.parametrize('headers', [{}, {'X-Dashboard': '1', 'Authorization': 'Bearer machine-token'}, {'X-Dashboard': '1', 'Authorization': 'Bearer ' + 'f' * 64}])
def test_staff_session_is_required_and_customer_cookie_is_not_staff_authority(agreements_api, headers):
    w = agreements_api
    w.api.cookies.set('__Host-ac_customer_session', 'synthetic-customer-cookie')
    result = w.api.get(w.base + '/agreements', headers=headers)
    assert result.status_code in (401, 403)
    assert result.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('raw', ['{"gross_units":1,"gross_units":2}', '{"gross_units":NaN}', '{"gross_units":1e999}', '[]', 'x' * 65537], ids=['duplicate','nonfinite','overflow','array','oversize'])
def test_raw_request_security_has_no_settlement_or_event_side_effect(agreements_api, raw):
    w = agreements_api
    path = w.base + '/agreements/' + w.agreement['id'] + '/quote'
    result = w.api.post(path, headers=w.header, content=raw)
    assert result.status_code == 400 and result.headers['cache-control'] == 'no-store'
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_agreement_events').fetchone()[0] == 0


@pytest.mark.parametrize('headers', [{'Origin': 'https://outside.invalid'}, {'Origin': 'null'}, {'Sec-Fetch-Site': 'cross-site'}])
def test_cross_origin_is_denied_for_read_and_write(agreements_api, headers):
    w = agreements_api; header = w.header | headers
    assert w.api.get(w.base + '/agreements', headers=header).status_code == 403
    assert w.api.post(w.base + '/agreements/' + w.agreement['id'] + '/quote', headers=header, json={'gross_units': 1}).status_code == 403


def test_other_workspace_or_global_staff_nonmember_cannot_read_and_current_proof_revocation_stops_changes(agreements_api):
    w = agreements_api
    other = provision((w.store, w.access, w.staff))['id']
    crossed = w.base.replace(w.ws, other) + '/agreements/' + w.agreement['id'] + '/quote'
    assert w.api.post(crossed, headers=w.header, json={'gross_units': 1}).status_code == 404
    with w.store.tx() as db:
        db.execute('UPDATE admin_sessions SET token=? WHERE user_id=5', (session_reference('b' * 64),))
    outsider = w.header | {'Authorization': 'Bearer ' + 'b' * 64}
    assert w.api.get(w.base + '/agreements', headers=outsider).status_code == 404
    current, _ = capture_api(w)
    with w.store.tx() as db:
        db.execute('UPDATE provider_control_claims SET revoked=1 WHERE id=?', (w.verified['id'],))
    refund = {'event_reference': 'sim_revoked_control', 'units': 1, 'revision': 1, 'authorized': True, 'notice': NOTICE}
    result = w.api.post(w.base + '/agreement-settlements/' + current['id'] + '/refund', headers=w.header, json=refund)
    assert result.status_code == 404 and len(w.provider_calls) == 1
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_agreement_events').fetchone()[0] == 1


def test_no_request_can_promote_simulation_into_actual_commerce(agreements_api):
    w = agreements_api
    request = w.body | {'revision': 1, 'commercial_enabled': True, 'legal_verification': 'verified'}
    result = w.api.post(w.base + '/agreements', headers=w.header, json=request)
    assert result.status_code == 400
    assert all(key not in w.api.get(w.base + '/agreements', headers=w.header).text for key in ('session_ref', 'binding_hash', 'nonce_hash', 'synthetic.invalid'))


def test_actual_dashboard_fixed_asset_has_exact_response_nonce_and_source_bytes(private_api):
    w = private_api
    page = w.client.get('/admin/ui')
    nonce = re.search(r"script-src 'nonce-([^']+)'", page.headers['content-security-policy']).group(1)
    assert f'<script nonce="{nonce}" src="/admin/assets/workspace-agreement-admin.js"></script>' in page.text
    asset = w.client.get('/admin/assets/workspace-agreement-admin.js')
    assert asset.status_code == 200 and asset.headers['cache-control'] == 'no-store'
    assert asset.content == Path('agent_market/gateway/workspace-agreement-admin.js').read_bytes()
    assert w.client.get('/admin/assets/workspace_agreements.py').status_code == 404
