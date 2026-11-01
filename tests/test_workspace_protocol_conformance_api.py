"""Named-session synthetic reports reject IDOR, CSRF, stale and malformed input."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from agent_market.workspace_protocol_conformance_service import router_for
from tests.test_workspace_protocol_conformance import conformance, command
from tests.test_workspace_sandbox_payments import sandbox, prepare, dispatch
from tests.test_workspace_agreements import agreement
from tests.test_provider_claims import provider


@pytest.fixture
def conformance_api(conformance):
    w = conformance
    app = FastAPI(); app.include_router(router_for(w.conformance))
    w.api = TestClient(app, base_url='https://private.test')
    w.base = '/admin/api/workflow-workspaces/' + w.ws + '/protocol-conformance'
    w.headers = {'X-Dashboard': '1', 'Authorization': 'Bearer ' + w.raw_staff}
    yield w
    w.api.close()


def test_actual_api_records_one_report_over_existing_capture_refund_and_keeps_no_store(conformance_api):
    w = conformance_api; capture = prepare(w); dispatch(w, capture)
    response = w.api.post(w.base + '/runs', headers=w.headers, json=command(w, capture))
    assert response.status_code == 200, response.text
    value = response.json()['result']
    assert value['wire_checks']['passed'] and value['ledger']['receipt_state'] == 'simulated_recorded'
    assert w.api.post(w.base + '/runs', headers=w.headers, json=command(w, capture)).json()['result']['replayed']
    detail = w.api.get(w.base + '/reports/' + value['id'], headers=w.headers)
    assert detail.status_code == 200 and detail.headers['cache-control'] == 'no-store'
    status = w.api.get(w.base, headers=w.headers)
    assert len(status.json()['result']['reports']) == 1
    products={item['product'] for item in status.json()['result']['compatibility']}
    assert products == {'Public workflow SDK 1','Admin managed SDK 1','Private SDK 2',
        'Private typed SDK 2','Bounded MCP execution','Bounded A2A execution',
        'Private asynchronous A2A sessions'}
    assert 'session_ref' not in status.text and w.raw_staff not in status.text
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_agreement_events').fetchone()[0] == 1
    assert w.api.post('/api/protocol-conformance/runs', json={}).status_code == 404


@pytest.mark.parametrize('extra', [{'Origin': 'null'}, {'Origin': 'https://outside.invalid'}, {'Sec-Fetch-Site': 'cross-site'}])
def test_cross_origin_read_and_write_are_denied(conformance_api, extra):
    w = conformance_api; capture = prepare(w)
    assert w.api.get(w.base, headers=w.headers | extra).status_code == 403
    assert w.api.post(w.base + '/runs', headers=w.headers | extra, json=command(w, capture)).status_code == 403
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_protocol_reports').fetchone()[0] == 0


@pytest.mark.parametrize('raw', ['[]', '{"profile_id":"x","profile_id":"y"}', '{"amount":NaN}', '{"x":1e999}', 'x' * 4097])
def test_strict_bounded_object_never_creates_report(conformance_api, raw):
    w = conformance_api
    response = w.api.post(w.base + '/runs', headers=w.headers | {'Content-Type': 'application/json'}, content=raw)
    assert response.status_code == 400
    assert response.headers['cache-control'] == 'no-store'
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_protocol_reports').fetchone()[0] == 0


def test_unauthenticated_or_foreign_workspace_cannot_read_retained_source(conformance_api):
    w = conformance_api; capture = prepare(w)
    report = w.conformance.run(w.ws, command(w, capture), w.staff[1])
    assert w.api.get(w.base).status_code == 401
    foreign = w.base.replace(w.ws, 'ws_' + 'a' * 32)
    assert w.api.get(foreign + '/reports/' + report['id'], headers=w.headers).status_code == 404
    assert w.api.get(w.base + '/reports/wpcr_' + 'b' * 32, headers=w.headers).status_code == 404
    assert w.api.get(w.base + '?raw=true', headers=w.headers).status_code == 400


def test_offline_signature_failure_is_structured_and_never_claims_settlement(conformance_api, monkeypatch):
    from unittest.mock import Mock
    from agent_market.workspace_x402_eip3009 import EIP3009Invalid
    w = conformance_api
    monkeypatch.setattr(w.conformance, 'cryptographic_check', Mock(side_effect=
        EIP3009Invalid('invalid_signature')))
    response = w.api.post(w.base + '/cryptographic-check', headers=w.headers, json={})
    assert response.status_code == 400
    value = response.json()
    assert value['error_code'] == 'invalid_exact_evm_payload_signature'
    assert value['validation_stage'] == 'signature'
    assert value['verified_payment'] is False and value['settlement_authorized'] is False
    assert response.headers['cache-control'] == 'no-store'
