"""PM 11-18: each open necklace is also its own small MCP server at POST /mcp/necklace/<slug> (so the Registry can list it alone)."""
import json
from datetime import datetime, timedelta, timezone

from agent_market.concierge import necklace_surface as ns
from agent_market.concierge.front import MCP_SERVER_VERSION
from agent_market.concierge.traffic import entry_of
from tests.test_necklace_agent_paths import open_topic
from tests.test_necklace_surface import iso, necklace, pearl
from tests.test_pearl_frontend import client  # noqa: F401

PATH = '/mcp/necklace/topic-evidence-brief'


def rpc(site, path, method, **params):
    return site.post(path, json={'jsonrpc': '2.0', 'id': 7, 'method': method, 'params': params})


def test_initialize_names_the_necklace_and_the_list_has_its_one_tool(client, monkeypatch, tmp_path):  # noqa: F811
    open_topic(monkeypatch, tmp_path)
    first = rpc(client, PATH, 'initialize', protocolVersion='2025-06-18', clientInfo={'name': 'my-agent'})
    result = first.json()['result']
    assert first.status_code == 200 and first.headers['mcp-session-id']
    assert result['serverInfo'] == {'name': 'agent-concierge-topic-evidence-brief', 'version': MCP_SERVER_VERSION,
                                    'title': 'Topic Evidence Brief — AgentValCon necklace'}
    assert result['protocolVersion'] == '2025-06-18' and 'necklace_topic_evidence_brief' in result['instructions']
    tools = rpc(client, PATH, 'tools/list').json()['result']['tools']
    assert [t['name'] for t in tools] == ['necklace_topic_evidence_brief']
    full = rpc(client, '/mcp', 'tools/list').json()['result']['tools']
    assert tools[0] == [t for t in full if t['name'] == 'necklace_topic_evidence_brief'][0]       # the same description as the full list
    assert rpc(client, PATH, 'ping').json()['result'] == {}
    assert client.post(PATH, json={'jsonrpc': '2.0', 'method': 'notifications/initialized'}).status_code == 202
    assert rpc(client, PATH, 'resources/list').json()['error']['code'] == -32601
    assert client.get(PATH).status_code == 405


def test_only_its_own_tool_can_be_called_and_it_runs_the_same_path_as_mcp(client, monkeypatch, tmp_path):  # noqa: F811
    calls = open_topic(monkeypatch, tmp_path)
    for other in ('search', 'necklace_details', 'necklace_website_trust', 'chat'):
        refused = rpc(client, PATH, 'tools/call', name=other, arguments={'slug': 'topic-evidence-brief'}).json()
        assert refused['error']['code'] == -32602 and 'necklace_topic_evidence_brief' in refused['error']['message'], other
    assert calls == []                                                                              # nothing ran
    done = rpc(client, PATH, 'tools/call', name='necklace_topic_evidence_brief', arguments={'topic': 'retrieval augmented generation'}).json()
    assert done['result']['isError'] is False and calls == [('topic-evidence-brief', 'mcp')]
    assert rpc(client, PATH, 'tools/call', name='necklace_topic_evidence_brief', arguments='bad').json()['error']['code'] == -32602


def test_a_necklace_that_is_not_open_has_no_endpoint(client, monkeypatch, tmp_path):  # noqa: F811
    open_topic(monkeypatch, tmp_path)
    for path in ('/mcp/necklace/website-trust', '/mcp/necklace/NOT_A_SLUG', '/mcp/necklace/' + 'x' * 80):
        assert rpc(client, path, 'tools/list').status_code in (404, 405, 422), path
    assert rpc(client, '/mcp/necklace/website-trust', 'tools/list').status_code == 404
    snapshot = json.loads((tmp_path / 'root/gateway-data/necklaces/necklaces.json').read_text())
    snapshot['necklaces'][0]['status'] = 'held'
    (tmp_path / 'root/gateway-data/necklaces/necklaces.json').write_text(json.dumps(snapshot))
    ns._CACHE.update(key=None, value=None)
    assert rpc(client, PATH, 'tools/list').status_code == 404                                         # held: no endpoint


def test_a_preview_necklace_has_an_endpoint_whose_tool_text_carries_no_figure(client, monkeypatch, tmp_path):  # noqa: F811
    now = datetime.now(timezone.utc)
    entry = necklace('website-trust', status='preview', gate_passed_at=None, quality={'success_rate': 0.9, 'tested_at': iso(now)},
                     preview={'note': 'Preview — test runs in progress', 'gate_passed': False},
                     comparison={'cases': 30, 'measured_at': '2026-11-17', 'with': {'accuracy': 0.9, 'seconds': 3.2, 'tokens': 1200, 'calls': 4},
                                 'without': {'accuracy': 0.7, 'seconds': 9.1, 'tokens': 5200, 'calls': 9}})
    entry['pearls'] = [pearl(1, 'a'), pearl(2, 'b')]
    root = tmp_path / 'root'
    (root / 'gateway-data/necklaces').mkdir(parents=True)
    (root / 'gateway-data/necklaces/necklaces.json').write_text(json.dumps({'schema': ns.SCHEMA, 'generated_at': iso(now), 'necklaces': [entry], 'events': []}))
    monkeypatch.setenv('AGENTCON_PROJECT_ROOT', str(root))
    ns._CACHE.update(key=None, value=None)
    first = rpc(client, '/mcp/necklace/website-trust', 'initialize', protocolVersion='2025-06-18').json()['result']
    assert 'preview' in first['instructions'] and first['serverInfo']['name'] == 'agent-concierge-website-trust'
    tool = rpc(client, '/mcp/necklace/website-trust', 'tools/list').json()['result']['tools'][0]
    for text in ('1200', '5200', '90%', '3.2', 'Verified 95%', 'Recent tests'):
        assert text not in tool['description'] and text not in first['instructions'], text


def test_the_new_path_counts_as_mcp_traffic():
    assert entry_of('POST', PATH) == 'mcp'
