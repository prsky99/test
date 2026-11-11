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


def test_client_side_refusal_stays_quiet(caplog):
    with caplog.at_level(logging.WARNING, logger='agent_market.edge_gateway.router'):
        response = _call('POLICY_DENIED', 403)
    assert response.status_code == 403
    assert 'refused' not in caplog.text
