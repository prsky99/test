"""Headless Agent-role audit: real API routes, disposable DB, mocked Providers.

No operating visitor, Provider execution, payment or server restart is used.
"""
import json
import time
from urllib.parse import urlsplit

import httpx
import pytest

from agent_market.collector import usage
from agent_market.workspace_integrations import PrivateIntegrations
from tests.report_fixtures import execution_report
from tests.test_fast_single_recommendation import catalog  # noqa: F401
from tests.test_managed_agent_gateway import managed, setup_a2a  # noqa: F401
from tests.test_mcp_proxy import WEATHER_TOOL
from tests.test_workflow_fallback import routing  # noqa: F401


@pytest.fixture(autouse=True)
def no_operating_connections(monkeypatch):
    monkeypatch.delenv('AGENT_EDGE_GATEWAY_CONFIG', raising=False)
    attempts = []
    def deny_network(self, request):
        attempts.append(request.url.host)
        raise AssertionError('Agent audit requires injected transports only')
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', deny_network)
    yield
    assert not attempts, 'Unexpected live HTTP transport in the isolated Agent audit'


class HeadlessAgent:
    """Choose fields from advertised schemas; keep visitor authority in transport."""
    def __init__(self, client):
        self.client, self.sequence, self.token = client, 0, None
        self.endpoint = urlsplit(client.get('/.well-known/mcp.json').json()['endpoints'][0]['url']).path
        initialized = self.rpc('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                            'clientInfo': {'name': 'SyntheticAutonomousResearchAgent', 'version': '1.0'}})
        assert initialized['result']['serverInfo']['name'] == 'agent-concierge'  # identifier kept (11-14 brand AgentValCon)
        assert self.client.post(self.endpoint, json={'jsonrpc': '2.0', 'method': 'notifications/initialized'}).status_code == 202
        self.tools = {t['name']: t for t in self.rpc('tools/list')['result']['tools']}

    def rpc(self, method, params=None):
        self.sequence += 1
        response = self.client.post(self.endpoint, json={'jsonrpc': '2.0', 'id': self.sequence,
                                    'method': method, 'params': params or {}},
                                    headers={'X-Visitor-Token': self.token} if self.token else {})
        assert response.status_code == 200
        value = response.json()
        visitor = value.get('result', {}).get('structuredContent', {}).get('visitor') or {}
        self.token = visitor.get('token') or self.token
        return value

    def tool(self, name, arguments):
        assert name in self.tools
        required = self.tools[name]['inputSchema'].get('required', [])
        assert all(key in arguments for key in required)
        return self.rpc('tools/call', {'name': name, 'arguments': arguments})['result']

    def find(self, task, protocol='mcp', *, advertised=None):
        schema = advertised or self.tools['search']['inputSchema']
        properties = schema['properties']
        arguments = {('task' if 'task' in properties else 'query'): task,
                     ('kind' if 'kind' in properties else 'protocol'): protocol}
        # Advertised manifest fields deliberately go directly to the API. No insider repair.
        return self.rpc('tools/call', {'name': 'search', 'arguments': arguments})['result']['structuredContent']

    def execute(self, candidate):
        schema = candidate['tools_schema'][0]
        assert schema['inputSchema']['required'] == ['city']
        return self.tool('call', {'resource_id': candidate['id'], 'tool': schema['name'],
                                 'arguments': {'city': 'Tokyo'}, 'task': 'weather forecast'})


@pytest.fixture
def agent_world(managed):
    store, front, client, add, primary, calls, remote = managed
    remote.confirmed_tool_error = True
    tools = [{**WEATHER_TOOL, 'description': 'Get current weather and weather forecast for a city'}]
    remote.tools = tools
    compact = usage.compact_tools(tools)
    store.record_usage(primary, tools=compact, digest=usage.tools_hash(compact),
                       guide={'tools': tools}, changes=None, trial={'ok': True}, full_tools=tools)
    now = __import__('time').time()
    execution_report(store, primary, now, title='Synthetic primary proof', slug='agent-primary-proof',
                     eval_grade='A', is_success=1, created_at=now, status_code=200)
    standby = add('Standby Weather', report_at=now-30)
    store.record_usage(standby, tools=compact, digest=usage.tools_hash(compact),
                       guide={'tools': tools}, changes=None, trial={'ok': True}, full_tools=tools)
    execution_report(store, standby, now-10, title='Synthetic standby proof', slug='agent-standby-proof',
                     eval_grade='A', is_success=1, created_at=now-10, status_code=200)
    return managed, HeadlessAgent(client), standby


def test_agent_discovers_service_and_machine_interfaces_without_browser(agent_world):
    world, agent, _ = agent_world
    client = world[2]
    welcome = client.get('/', headers={'Accept': 'application/json'}).json()
    assert welcome['audience'] == 'ai-agents-only'
    assert set(welcome['how_to_reply']) == {'rest', 'a2a', 'mcp'}
    assert {'search', 'call', 'report', 'whats_new'} <= set(agent.tools)
    assert '/mcp' in client.get('/llms.txt').text


def test_agent_reads_runtime_schema_finds_and_executes_a_tool(agent_world):
    world, agent, _ = agent_world
    selected = agent.find('weather forecast')['recommendations']
    assert len(selected) == 2 and {item['id'] for item in selected} == {world[4], agent_world[2]}
    result = agent.execute(selected[0])
    assert result['structuredContent']['ok'] is True
    assert result['structuredContent']['execution']['hash_verified'] is True
    assert sum(json.loads(r.content or b'{}').get('method') == 'tools/call' for r in world[5]) == 1
    assert not any(agent.token in part.get('text', '') for part in result['content'])


def test_agent_retains_memory_across_mcp_and_rest(agent_world):
    world, agent, _ = agent_world
    # `search` is a read-only lookup; an agent that wants to be remembered saves the task with `chat`.
    assert agent.find('weather forecast').get('visitor') is None
    first = agent.rpc('tools/call', {'name': 'chat', 'arguments': {'message': 'MCP weather forecast'}})['result'][
        'structuredContent']['recommendations'][0]
    assert agent.token
    follow = world[2].post('/chat', json={'message': 'details 1'},
                          headers={'X-Visitor-Token': agent.token}).json()
    assert follow['data']['recommendations'][0]['id'] == first['id']
    assert follow['data']['protocol'] == 'mcp'


def test_agent_follows_a2a_recommendation_to_its_managed_gateway(agent_world):
    world, _, _ = agent_world
    rid = setup_a2a(world, 'completed')
    # A2A admission requires current execution proof, not just a healthy card.
    verified = world[2].post('/api/test/execute', json={
        'resource_id': rid, 'message': 'Summarize weather research.'}).json()
    assert verified['execution_succeeded'] is True
    response = world[2].post('/a2a', json={'jsonrpc': '2.0', 'id': 1, 'method': 'message/send',
        'params': {'message': {'role': 'user', 'messageId': 'synthetic-agent-request',
                               'parts': [{'kind': 'text', 'text': 'weather forecast'}]}}}).json()
    payload = next(p['data'] for p in response['result']['parts'] if p.get('kind') == 'data')
    candidate = payload['recommendations'][0]
    assert candidate['id'] == rid and candidate['kind'] == 'a2a'
    path = urlsplit(candidate['url']).path
    card = world[2].get(path).json()
    assert card['capabilities']['streaming'] is False
    answer = world[2].post(path, json={'jsonrpc': '2.0', 'id': 2, 'method': 'message/send',
        'params': {'message': {'parts': [{'kind': 'text', 'text': 'Summarize weather research.'}]}}}).json()
    assert 'result' in answer and 'upstream-private-task' not in json.dumps(answer)


def test_agent_uses_structured_failure_and_alternative_to_recover(agent_world):
    world, agent, _ = agent_world
    selected = agent.find('weather forecast')['recommendations'][0]
    world[6].fail_call = True
    failed = agent.execute(selected)['structuredContent']
    assert failed['ok'] is False and failed['alternative']['id'] != selected['id']
    world[6].fail_call = False
    recovered = agent.execute(failed['alternative'])['structuredContent']
    assert recovered['ok'] is True and recovered['resource_id'] == failed['alternative']['id']


def test_agent_cannot_invent_tool_authority(agent_world):
    world, agent, _ = agent_world
    result = agent.tool('call', {'resource_id': world[4], 'tool': 'delete_database', 'arguments': {}})
    assert result['structuredContent']['ok'] is False
    assert not world[5]


def test_agent_cannot_spend_another_visitors_account(agent_world):
    world, agent, _ = agent_world
    agent.find('weather forecast')
    denied = agent.rpc('tools/call', {'name': 'call', 'arguments': {
        'resource_id': world[4], 'tool': 'get_weather', 'arguments': {'city': 'Tokyo'},
        'account_id': 'some-other-agent-account'}})
    assert denied['error']['code'] == -32602 and not world[5]


def test_public_agent_does_not_inherit_private_workspace_automation(agent_world):
    world, agent, _ = agent_world
    policy = PrivateIntegrations()
    assert not policy.machine_updates_worker_enabled and not policy.receiver_enabled
    assert not policy.single_admission_enabled and not policy.circuit_automation_enabled
    assert all('workspace' not in name for name in agent.tools)
    denied = world[2].get('/admin/api/workflow-workspaces')
    assert denied.status_code in (401, 403, 404)


def test_agent_discovers_published_workflow_runs_and_polls_with_its_run_key(routing):
    from fastapi.testclient import TestClient
    from agent_market.concierge.front import Front, create_front_app
    from tests.test_workflow_products import published
    from agent_market.workflow_fallback import NOTICE as FALLBACK_NOTICE
    runtime, workflow, _ = published(routing)
    proxy = runtime.proxy
    front = Front(runtime.store, allow_private=True)
    front.proxy = front.workflows.proxy = proxy
    with TestClient(create_front_app(front), base_url='https://agentconcierge.biz') as client:
        template = next(t for t in client.get('/api/workflows/templates').json()['templates']
                        if t['id'] == workflow['id'])
        body = {'template_id': template['id'], 'definition_hash': template['definition_hash'],
                'input': {'query': 'ocean monitoring'}}
        assert client.post('/api/workflows/run', json=body | {'nodes': []}).status_code == 400
        assert client.post('/api/workflows/run', json=body).status_code == 400
        # Test owner grants this exact read-only sharing purpose, not arbitrary execution.
        body |= {'allow_fallback': True, 'fallback_notice': FALLBACK_NOTICE}
        response = client.post('/api/workflows/run', json=body)
        assert response.status_code == 202, response.text
        grant = response.json()
        path = '/api/workflows/runs/' + grant['run_id']
        assert client.get(path).status_code == 404
        for _ in range(100):
            status = client.get(path, headers={'X-Workflow-Key': grant['run_key']})
            assert status.status_code == 200
            if status.json()['status'] not in ('queued', 'running'):
                break
            time.sleep(.02)
        assert status.json()['status'] == 'succeeded'
        assert 'product_context' not in status.text


def test_gap_manifest_only_agent_can_find_the_requested_mcp_agent(agent_world):
    """Desired behavior; current manifest advertises query/protocol, not task/kind."""
    _, agent, _ = agent_world
    manifest = agent.client.get('/.well-known/mcp.json').json()
    schema = next(t['inputSchema'] for t in manifest['tools'] if t['name'] == 'search')
    result = agent.find('weather forecast', advertised=schema)
    assert result.get('recommendations'), 'Manifest-only client cannot discover using advertised fields'
    assert result['recommendations'][0]['kind'] == 'mcp'


def test_gap_failed_execution_signals_mcp_tool_error(agent_world):
    """Desired MCP signal, independent of the service-specific structured ok field."""
    world, agent, _ = agent_world
    candidate = agent.find('weather forecast')['recommendations'][0]
    world[6].fail_call = True
    result = agent.execute(candidate)
    assert result['structuredContent']['ok'] is False
    assert result['isError'] is True, 'Generic MCP clients can misclassify the failed execution as success'


def test_failure_alternative_retains_the_gateway_address(agent_world):
    world, agent, _ = agent_world
    candidate = agent.find('weather forecast')['recommendations'][0]
    world[6].fail_call = True
    alternative = agent.execute(candidate)['structuredContent']['alternative']
    assert alternative and alternative['url'].startswith('https://agentconcierge.biz/api/gateway/'), \
        'Recovery alternative bypasses the advertised managed gateway address'
