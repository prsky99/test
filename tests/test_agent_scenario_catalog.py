"""Reconstructed audit inventory and optional protocol feature classification."""
import json
from types import SimpleNamespace

import httpx
import pytest

from scripts.agent_scenario_catalog import scenarios
from scripts.agent_scenarios import Audit, main


def test_catalog_has_76_unique_cases_for_12_roles_with_explicit_boundaries():
    values = scenarios()
    assert len(values) == len({v['id'] for v in values}) == 76
    assert len({v['agent_type'] for v in values}) == 12
    assert {v['mode'] for v in values} == {'live', 'isolated', 'source', 'manual'}
    assert next(v for v in values if v['id'] == 'x402:real-settlement')['mode'] == 'manual'


def test_listing_catalog_never_constructs_a_network_client(monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['agent_scenarios', '--list-scenarios'])
    monkeypatch.setattr(httpx, 'Client', lambda *a, **kw: pytest.fail('Listing must be offline.'))
    assert main() == 0
    assert len(json.loads(capsys.readouterr().out)) == 76


@pytest.mark.parametrize('tool,expected', [
    ({'name': 'read'}, {'mcp:hints:read': 'WARN', 'mcp:output-schema:read': 'WARN'}),
    ({'name': 'read', 'annotations': {'readOnlyHint': 'yes'}, 'outputSchema': {'type': 'invalid'}},
        {'mcp:hints:read': 'FAIL', 'mcp:output-schema:read': 'FAIL'}),
])
def test_optional_absence_is_warning_but_invalid_metadata_is_failure(tool, expected):
    audit = Audit(SimpleNamespace(base_url='https://agentconcierge.biz'))
    def rpc(method, params=None):
        return httpx.Response(200, json={'result': {'protocolVersion': '2025-11-25'} if method == 'initialize' else {'tools': [tool]}})
    def request(method, path, **kwargs):
        if method == 'OPTIONS':
            return httpx.Response(204, headers={'Access-Control-Allow-Origin': 'https://agentconcierge.biz'})
        return httpx.Response(403 if method == 'POST' else 405)
    audit.rpc, audit.request, audit.recommend = rpc, request, lambda *a, **kw: None
    audit.mcp()
    actual = {v['scenario']: v['status'] for v in audit.results}
    assert all(actual[name] == status for name, status in expected.items())
