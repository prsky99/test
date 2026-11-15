import asyncio
import json
import logging

from agent_market.edge_gateway.config import EdgeError
from agent_market.edge_gateway.router import errors


def _call(code, status):
    @errors
    async def public_prepare():
        raise EdgeError(code, status)
    return asyncio.run(public_prepare())


def test_server_side_refusal_logs_its_code(caplog):
    with caplog.at_level(logging.WARNING, logger='agent_market.edge_gateway.router'):
        response = _call('CAPACITY_EXCEEDED', 503)
    assert response.status_code == 503
    assert json.loads(response.body)['error_code'] == 'CAPACITY_EXCEEDED'
    assert 'public_prepare refused: CAPACITY_EXCEEDED 503' in caplog.text


def test_client_side_refusal_is_logged_with_its_reason_and_reference(caplog):
    # 11-15 (PM 10:40): a 403 left no reason anywhere; 4xx refusals are logged and carry a reference now.
    @errors
    async def public_prepare():
        error = EdgeError('POLICY_DENIED', 403)
        error.denied = 'UNSAFE_TOOL'
        raise error
    with caplog.at_level(logging.WARNING, logger='agent_market.edge_gateway.router'):
        response = asyncio.run(public_prepare())
    body = json.loads(response.body)
    assert response.status_code == 403 and body['error_code'] == 'POLICY_DENIED' and body['reason_code'] == 'UNSAFE_TOOL'
    assert body['reference'].startswith('ex_') and 'public_prepare refused: POLICY_DENIED 403 reason=UNSAFE_TOOL reference=' + body['reference'] in caplog.text


def test_a_refusal_without_an_inner_reason_has_no_reason_code(caplog):
    with caplog.at_level(logging.WARNING, logger='agent_market.edge_gateway.router'):
        response = _call('AUTH_REQUIRED', 401)
    body = json.loads(response.body)
    assert 'reason_code' not in body and 'refused: AUTH_REQUIRED 401 reference=' + body['reference'] in caplog.text
