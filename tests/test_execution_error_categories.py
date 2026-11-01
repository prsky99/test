"""Failure references describe safe categories without leaking provider details."""
import json
import logging
import re

import pytest

from agent_market.concierge.execution_errors import fields, record_failure, reference
from tests.test_fast_single_recommendation import catalog
from tests.test_managed_agent_gateway import managed, rpc


def test_diagnostics_are_metadata_only_and_public_fields_are_allowlisted(caplog):
    trace = reference()
    with caplog.at_level(logging.WARNING, logger='agent_market.execution'):
        record_failure(trace, 7, 'mcp', 'UPSTREAM_NETWORK',
                       exception=ValueError('Bearer private-token https://private.example/api?key=secret'))
    assert trace in caplog.text and 'UPSTREAM_NETWORK' in caplog.text
    assert 'private-token' not in caplog.text and 'private.example' not in caplog.text and 'key=secret' not in caplog.text
    assert fields('https://private.example/api', 'Bearer secret') == {
        'error_code': 'EXECUTION_FAILED',
        'error_message': 'The agent execution failed. Review its connection and registered tool.'}


@pytest.mark.parametrize('code', ['SCHEMA_CHANGED', 'UPSTREAM_NETWORK', 'UPSTREAM_TIMEOUT',
                                  'UPSTREAM_PROTOCOL', 'UPSTREAM_TOOL_ERROR'])
def test_managed_failures_keep_safe_code_and_private_support_reference(managed, monkeypatch, code):
    _, front, client, _, rid, _, _ = managed
    monkeypatch.setattr(front.proxy, 'execute', lambda *a, **kw: {
        'ok': False, 'error_code': code,
        'error': 'Bearer private-token https://provider.example/private?key=secret'})
    response = client.post('/api/test/execute', json={
        'resource_id': rid, 'tool': 'get_weather', 'arguments': {'city': 'Tokyo'}})
    body = response.json()
    assert body['error_code'] == code and not body['execution_succeeded']
    assert re.fullmatch(r'ex_[0-9a-f]{24}', body['correlation_id'])
    assert 'private-token' not in response.text and 'key=secret' not in response.text
    wire = rpc(client, f'/api/gateway/mcp/{rid}', 'tools/call',
               {'name': 'get_weather', 'arguments': {'city': 'Tokyo'}}).json()
    assert wire['error']['data']['error_code'] == code
    assert re.fullmatch(r'ex_[0-9a-f]{24}', wire['error']['data']['correlation_id'])


def test_policy_refusal_preserves_http_status_and_has_safe_reference(managed):
    _, _, client, _, rid, calls, _ = managed
    response = client.post('/api/test/execute', json={
        'resource_id': rid, 'tool': 'delete_database', 'arguments': {}})
    assert response.status_code == 400
    body = response.json()
    assert body['error_code'] == 'TOOL_UNAVAILABLE'
    assert re.fullmatch(r'ex_[0-9a-f]{24}', body['correlation_id'])
    assert not calls


def test_invalid_provider_category_cannot_become_public_diagnostics(managed, monkeypatch):
    _, front, client, _, rid, _, _ = managed
    monkeypatch.setattr(front.proxy, 'execute', lambda *a, **kw: {
        'ok': False, 'error_code': 'Bearer secret', 'error': '<script>private diagnostic</script>'})
    response = client.post('/api/test/execute', json={
        'resource_id': rid, 'tool': 'get_weather', 'arguments': {'city': 'Tokyo'}})
    assert response.json()['error_code'] == 'EXECUTION_FAILED'
    assert 'private diagnostic' not in response.text and 'Bearer secret' not in response.text


def test_workflow_failure_uses_the_same_safe_category(managed,monkeypatch):
    from agent_market.workflows import WorkflowError
    _,front,_,_,rid,_,_=managed
    front.workflows.proxy=front.proxy
    monkeypatch.setattr(front.proxy,'execute',lambda *a,**kw:{
        'ok':False,'error_code':'SCHEMA_CHANGED','error':'Bearer secret https://provider.example/private'})
    with pytest.raises(WorkflowError) as result:
        front.workflows._call({'resource_id':rid,'kind':'mcp','data':{'tool':'get_weather'}},{'city':'Tokyo'})
    assert result.value.error_code=='SCHEMA_CHANGED'
    assert 'Bearer secret' not in str(result.value) and 'provider.example' not in str(result.value)
