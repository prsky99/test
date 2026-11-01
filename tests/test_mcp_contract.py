"""Public metadata, legacy aliases and runtime MCP agree on one contract."""
import pytest

from agent_market.concierge.front import mcp_manifest
from agent_market.concierge.mcp_contract import mcp_tools, discovery_arguments
from tests.test_fast_single_recommendation import catalog  # noqa: F401
from tests.test_managed_agent_gateway import managed  # noqa: F401


def test_manifest_and_runtime_publish_identical_fresh_tool_definitions(catalog):
    _, _, client, _, _ = catalog
    manifest = client.get('/.well-known/mcp.json').json()
    runtime = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}).json()['result']
    assert manifest['tools'] == runtime['tools'] == mcp_tools()
    assert 'any' in next(t for t in manifest['tools'] if t['name'] == 'search')['inputSchema']['properties']['kind']['enum']
    assert manifest['endpoints'][0]['type'] == 'streamable-http'
    manifest['tools'][0]['inputSchema']['properties'].clear()
    assert mcp_tools()[0]['inputSchema']['properties']


@pytest.mark.parametrize('name', ['search', 'find_agents'])
@pytest.mark.parametrize('args', [
    {'task': 'weather forecast', 'kind': 'mcp'},
    {'query': 'weather forecast', 'protocol': 'mcp'},
    {'task': 'weather forecast', 'protocol': 'any'},
])
def test_cached_manifest_arguments_remain_compatible(catalog, name, args):
    _, _, client, add, now = catalog
    rid = add('MCP Weather', kind='mcp', report_at=now)
    result = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
        'params': {'name': name, 'arguments': args}}).json()['result']['structuredContent']
    assert result['recommendations'][0]['id'] == rid


@pytest.mark.parametrize('args', [{}, {'task': ''}, {'query': []}, {'task': True},
    {'task': 'weather', 'query': 'different request'}, {'task': 'weather', 'kind': 'mcp', 'protocol': 'a2a'},
    {'task': 'weather', 'protocol': {}}, {'task': 'weather', 'protocol': 'sql'}])
def test_ambiguous_or_malformed_legacy_fields_are_rejected(args):
    with pytest.raises(ValueError):
        discovery_arguments(args)


def test_unconfirmed_transport_failure_pauses_without_false_feedback_or_automatic_alternative(managed):
    store, _, client, _, rid, calls, remote = managed
    remote.fail_call = True
    remote.confirmed_tool_error = False
    before = store.query('SELECT COUNT(*) AS n FROM feedback')[0]['n']
    result = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
        'name': 'call', 'arguments': {'resource_id': rid, 'tool': 'get_weather', 'arguments': {'city': 'Tokyo'}}}}).json()['result']
    assert result['isError'] is True
    assert result['structuredContent']['execution']['retry_safe'] is False
    assert result['structuredContent']['alternative'] is None
    assert 'unconfirmed' in result['content'][0]['text']
    assert store.query('SELECT COUNT(*) AS n FROM feedback')[0]['n'] == before


def test_public_mcp_legacy_path_cannot_inherit_private_network_opt_in(managed, monkeypatch):
    import httpcore
    from agent_market.concierge.proxy import McpProxy
    _, front, client, _, rid, _, _ = managed
    front.proxy = McpProxy(front.store, allow_private=True)
    monkeypatch.setattr('agent_market.concierge.http_security._resolve_addresses', lambda *a: ['127.0.0.1'])
    monkeypatch.setattr(httpcore.SyncBackend, 'connect_tcp', lambda *a, **k: pytest.fail('Private TCP prohibited'))
    result = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
        'name': 'call', 'arguments': {'resource_id': rid, 'tool': 'get_weather', 'arguments': {'city': 'Tokyo'}}}}).json()['result']
    assert result['isError'] is True and not result['structuredContent']['ok']


def test_prefetched_tools_keep_managed_gateway_addresses(managed):
    import json
    from agent_market.collector import usage
    from tests.test_mcp_proxy import WEATHER_TOOL
    store, _, client, _, rid, _, remote = managed
    tools = [WEATHER_TOOL, {**WEATHER_TOOL, 'name': 'read_forecast'}]
    compact = usage.compact_tools(tools)
    store.record_usage(rid, tools=compact, digest=usage.tools_hash(compact), guide={'tools': tools},
                       changes=None, trial={'ok': True}, full_tools=tools)
    remote.tools = tools
    result = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
        'name': 'call', 'arguments': {'resource_id': rid, 'tool': 'get_weather', 'arguments': {'city': 'Tokyo'}}}}).json()['result']
    assert result['structuredContent']['ok']
    hints = result['structuredContent']['prefetched_tools']
    assert hints and all(h['url'].startswith('https://agentconcierge.biz/api/gateway/') for h in hints)
    assert store.resource(rid)['url'] not in json.dumps(result)
