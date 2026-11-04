"""Close every observed warning/failure and validate real MCP result contracts."""
# ruff: noqa: F811 -- pytest fixtures imported for dependency injection.
import json
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft202012Validator

from agent_market.concierge.mcp_contract import mcp_tools
from scripts.agent_scenarios import Audit
from tests.test_fast_single_recommendation import catalog  # noqa: F401


@pytest.fixture(autouse=True)
def no_external_provider_calls(monkeypatch):
    def refuse(self, request):
        pytest.fail('Resolution verification permits only the isolated ASGI app.')
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', refuse)


def test_every_observed_26_warning_and_11_failure_has_passing_candidate_evidence(catalog):
    _, _, client, add, now = catalog
    add('Synthetic Forecast', report_at=now)
    client.base_url = 'https://agentconcierge.biz'
    audit = Audit(client)
    audit.documents()
    audit.mcp()
    audit.recommend('a2a')
    audit.recommend('rest')
    values = {row['scenario']: row for row in audit.results}
    heads = ['/robots.txt', '/llms.txt', '/llms-full.txt', '/sitemap.xml',
        '/.well-known/agent-card.json', '/.well-known/mcp.json', '/.well-known/agent-entry.json', '/skill.md']
    targets = ['documents:head:' + path for path in heads]
    targets += ['documents:category:/agents/category/social', 'mcp:browser-preflight', 'mcp:origin-denial']
    targets += [prefix + tool['name'] for tool in mcp_tools() for prefix in ('mcp:hints:', 'mcp:output-schema:')]
    assert len(targets) == len(set(targets)) == 39  # 11-04: run_workflow (MCP tasks)
    assert all(values[key]['status'] == 'PASS' for key in targets)
    assert all(row['status'] == 'PASS' for row in audit.results)
    output = Path('reports/agent-warnings-failures-2026-10-27')
    output.mkdir(parents=True, exist_ok=True)
    report = {'scope': 'Isolated ASGI app with synthetic forecast data; no operating accounts or provider calls.',
        'assertions': len(audit.results), 'counts': {'PASS': len(audit.results), 'WARN': 0, 'FAIL': 0},
        'resolved_observations': [values[key] for key in targets], 'results': audit.results}
    (output / 'candidate-audit.json').write_text(json.dumps(report, indent=2) + '\n')


@pytest.mark.parametrize('tool_name', [tool['name'] for tool in mcp_tools()])
def test_every_declared_tool_schema_matches_its_actual_result(catalog, tool_name):
    _, _, client, add, now = catalog
    rid = add('Synthetic Forecast', report_at=now)
    first = client.post('/chat', json={'message': 'weather forecast'}).json()
    token = first['visitor']['token']
    arguments = {
        'hello': {}, 'chat': {'message': 'details 1'},
        'search': {'task': 'weather forecast'}, 'find_agents': {'task': 'weather forecast'},
        'whats_new': {}, 'subscribe': {'contact_url': 'https://callback.example/inbox'},
        'verify_contact': {'code': '000000'},
        'call': {'resource_id': rid, 'tool': 'unregistered_tool', 'arguments': {}},
        'report': {'resource_id': rid, 'ok': True}, 'credit': {'action': 'balance'},
        'adapt_rest': {'action': 'list_tools', 'spec': {'openapi': '3.0.0',
            'info': {'title': 'Synthetic schema only', 'version': '1'},
            'servers': [{'url': 'https://public-api.example'}],
            'paths': {'/status': {'get': {'operationId': 'read_status', 'responses': {'200': {'description': 'Status'}}}}}}},
        'search_workflows': {'task': 'documentation search'}, 'workflow_details': {'template_id': 2147483647},
        'run_workflow': {'template_id': 2147483647, 'definition_hash': 'a' * 64},
    }
    response = client.post('/mcp', headers={'X-Visitor-Token': token}, json={
        'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
        'params': {'name': tool_name, 'arguments': arguments[tool_name]}})
    value = response.json()
    assert 'result' in value, value
    result = value['result']
    schema = next(t['outputSchema'] for t in mcp_tools() if t['name'] == tool_name)
    Draft202012Validator(schema).validate(result['structuredContent'])
    assert result['structuredContent']['text'] == '\n'.join(p['text'] for p in result['content'] if p['type'] == 'text')
    assert token not in result['structuredContent']['text']
