"""11-11 check before you call: GET /api/agent/v1/check and MCP check_agent answer from recorded evidence only."""
import pytest
from fastapi.testclient import TestClient

from agent_market.concierge import agent_check as ac
from agent_market.concierge.front import Front, clear_front_caches, create_front_app
from agent_market.gateway.store import Store

CARD = 'https://agent-one.example/.well-known/agent-card.json'


class FixedSnapshot:
    def __init__(self, value):
        self.value = value

    def read(self):
        return self.value


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / 'check.db'))
    ids = []
    for i, (key, url) in enumerate([('a2a:https://agent-one.example', 'https://agent-one.example'),
                                    ('mcp:registry-name', 'https://mcp-two.example/mcp'),
                                    ('a2a:https://agent-three.example', 'https://agent-three.example')]):
        rid = s.upsert_resource({'key': key, 'name': 'Agent %d' % i, 'kind': key.split(':')[0], 'source': 'isolated',
                                 'url': url, 'description': 'Weather forecasts', 'category': 'weather'})
        with s.tx() as db:
            db.execute("UPDATE resources SET health_status='healthy',last_check_at=1 WHERE id=?", (rid,))
        s.record_health(rid, 'healthy', 200, 120, None, 9e9)
        ids.append(rid)
    yield s, ids
    s._db.close()


def snapshot_for(store, ids):
    catalog = {}
    for rid in ids:
        r = store.resource(rid)
        catalog[rid] = {'id': rid, 'kind': r['kind'], 'name': r['name'], 'category': 'weather', 'health_status': 'healthy',
                        'eval_grade': 'B', 'probe_latency_ms': 150, 'verified_at': None, 'last_check_at': 1}
    value = {'catalog': list(catalog.values()), 'tasks': []}
    assert ac.add_url_keys(store, value) == len(ids)
    return {'catalog': {a['id']: a for a in value['catalog']}}


@pytest.mark.parametrize('bad', ['', 'ftp://a.example', 'http://127.0.0.1/x', 'http://10.0.0.5', 'http://[::1]/',
                                 'http://169.254.169.254/latest', 'http://localhost:8080', 'https://printer.local/',
                                 'https://intranet/', 'https://user:pw@a.example/', 'https://a.example/' + 'x' * 2100,
                                 'https://a.example/ space'])
def test_only_public_urls_are_looked_up(bad):
    with pytest.raises(ac.CheckError):
        ac.normalize(bad)


def test_normalize_and_card_variants():
    assert ac.normalize('HTTPS://Agent-One.Example:443/a2a#x') == ('https://agent-one.example/a2a', 'agent-one.example')
    assert 'https://agent-one.example' in ac.variants(ac.normalize(CARD)[0])
    assert ac.url_key('https://agent-one.example/') == ac.url_key('https://AGENT-one.example')


def test_card_url_matches_the_listing_through_the_snapshot(store):
    s, ids = store
    index = ac.Index(FixedSnapshot(snapshot_for(s, ids)))
    found = ac.check(s, CARD, index)
    assert found['found'] and found['agent']['id'] == ids[0] and found['matched_by'] == 'snapshot'
    assert found['status'] == 'healthy' and found['grade'] == 'B' and found['latency_ms'] == 150
    assert found['recent']['checks'] == 1 and found['recent']['success_rate'] == 1.0
    assert [e['type'] for e in found['evidence_sources']] == ['connection_check', 'gateway_call', 'real_task_score']
    assert {a['id'] for a in found['alternatives']} == {ids[1], ids[2]}  # same category, never itself


def test_without_a_snapshot_match_indexed_keys_answer(store):
    s, ids = store
    index = ac.Index(FixedSnapshot({'catalog': {}}))
    found = ac.check(s, 'https://agent-three.example/', index)
    assert found['found'] and found['agent']['id'] == ids[2] and found['matched_by'] == 'catalog'
    missing = ac.check(s, 'https://never-seen.example/agent', index)
    assert missing == {**missing, 'found': False, 'match': 'none'} and missing['register_url'].endswith('list-agent.html')


def test_public_route_and_mcp_tool(store):
    s, ids = store
    clear_front_caches()
    front = Front(s)
    client = TestClient(create_front_app(front, manage_book_lifecycle=False))
    try:
        r = client.get('/api/agent/v1/check', params={'url': 'https://agent-one.example'})
        assert r.status_code == 200 and r.json()['agent']['id'] == ids[0]
        assert r.headers['cache-control'].startswith('public') and 'etag' in r.headers and r.headers['access-control-allow-origin'] == '*'
        bad = client.get('/api/agent/v1/check', params={'url': 'http://192.168.0.1/'})
        assert bad.status_code == 400 and 'private' in bad.text.lower() and bad.headers['cache-control'] == 'no-store'
        headers = {'Accept': 'application/json, text/event-stream', 'Content-Type': 'application/json'}
        tools = client.post('/mcp', headers=headers, json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}).json()
        tool = next(t for t in tools['result']['tools'] if t['name'] == 'check_agent')
        assert tool['annotations']['readOnlyHint'] and not tool['annotations']['openWorldHint']
        call = client.post('/mcp', headers=headers, json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                                                          'params': {'name': 'check_agent', 'arguments': {'url': 'https://agent-one.example'}}}).json()
        assert call['result']['structuredContent']['agent']['id'] == ids[0] and not call['result']['isError']
        refused = client.post('/mcp', headers=headers, json={'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                                                             'params': {'name': 'check_agent', 'arguments': {'url': 'http://localhost/'}}}).json()
        assert refused['error']['code'] == -32602
    finally:
        client.close()
        front.book.close()
