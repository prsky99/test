"""One-click feedback (11-10): anonymous storage, abuse limits, form and JSON paths, MCP limiter, daily aggregate."""
import json

import pytest

from agent_market.concierge import feedback as fb
from tests.test_concierge import w  # noqa: F401 (fixture)


def first_resource(world):
    return world.store.query("SELECT id FROM resources ORDER BY id LIMIT 1")[0]['id']


def rows(world):
    return [dict(r) for r in world.store.query("SELECT * FROM feedback")]


def test_parse_accepts_forms_and_json_shapes():
    assert fb.parse({'resource_id': '7', 'worked': '1', 'source': 'agent_page'}) == (7, True, 'agent_page', None)
    assert fb.parse({'resource_id': 7, 'worked': False, 'reason': 'connection_failed'}) == (7, False, 'api', 'connection_failed')
    for bad in ({}, {'resource_id': 0, 'worked': True}, {'resource_id': 1, 'worked': 'maybe'},
                {'resource_id': 1, 'worked': True, 'source': 'email'}, {'resource_id': 1, 'worked': True, 'reason': 'x'}):
        with pytest.raises(ValueError):
            fb.parse(bad)


def test_limiter_per_client_hour_pair_and_resource():
    now = [1_000_000.0]
    limiter = fb.Limiter(clock=lambda: now[0])
    assert limiter.allow('198.51.100.1', 5) and not limiter.allow('198.51.100.1', 5)  # once per agent a day
    assert all(limiter.allow('198.51.100.1', rid) for rid in range(10, 10 + fb.PER_CLIENT_HOUR - 1))
    assert not limiter.allow('198.51.100.1', 99)  # 20 an hour
    now[0] += 3601
    assert limiter.allow('198.51.100.1', 99)
    assert '198.51.100.1' not in json.dumps([list(k) for k in limiter.pairs])  # only salted digests are kept
    now[0] += 86400  # a new day resets everything with a new salt
    assert limiter.allow('198.51.100.1', 5)


def test_web_feedback_json_form_origin_and_limits(w, monkeypatch):  # noqa: F811
    world, c, _ = w
    monkeypatch.setattr(fb, 'LIMITER', fb.Limiter())
    rid = first_resource(world)
    before = len(rows(world))
    r = c.post('/api/feedback', json={'resource_id': rid, 'worked': True, 'source': 'explore'})
    assert r.status_code == 200 and r.json()['recorded'] is True and r.headers['cache-control'] == 'no-store'
    stored = rows(world)[-1]
    assert len(rows(world)) == before + 1 and stored['need_id'].startswith('web_explore_') and stored['success'] == 1
    assert set(stored) == {'need_id', 'resource_id', 'success', 'rating', 'created'}  # nothing about the sender
    again = c.post('/api/feedback', json={'resource_id': rid, 'worked': False})
    assert again.status_code == 429 and len(rows(world)) == before + 1
    monkeypatch.setattr(fb, 'LIMITER', fb.Limiter())
    form = c.post('/api/feedback', data={'resource_id': str(rid), 'worked': '0', 'source': 'agent_page'}, follow_redirects=False)
    assert form.status_code == 303 and form.headers['location'] == f'/agent/{rid}/reported?r=recorded'
    assert rows(world)[-1]['success'] == 0 and rows(world)[-1]['need_id'].startswith('web_agent_page_')
    cross = c.post('/api/feedback', json={'resource_id': rid, 'worked': True}, headers={'Origin': 'https://evil.example'})
    assert cross.status_code == 403
    assert c.post('/api/feedback', json={'resource_id': 2**31 - 1, 'worked': True}).status_code == 404
    assert c.post('/api/feedback', json={'resource_id': 'x', 'worked': True}).status_code == 400
    page = c.get(f'/agent/{rid}/reported?r=recorded')
    assert page.status_code == 200 and page.headers['cache-control'] == 'no-store' and 'noindex' in page.text


def test_mcp_report_uses_the_same_limiter(w, monkeypatch):  # noqa: F811
    world, c, _ = w
    monkeypatch.setattr(fb, 'LIMITER', fb.Limiter())
    rid = first_resource(world)
    call = lambda: c.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                        'params': {'name': 'report', 'arguments': {'resource_id': rid, 'ok': True}}}).json()
    monkeypatch.setattr(fb, 'MCP_PER_HOUR', 2)
    import agent_market.concierge.front  # noqa: F401  (the handler reads MCP_PER_HOUR at call time)
    assert 'result' in call() and 'result' in call()  # success then failure reports for one agent are both allowed
    limited = call()
    assert limited['error']['code'] == -32029


def test_daily_aggregate_and_agent_page_counts(w, tmp_path, monkeypatch):  # noqa: F811
    world, _, _ = w
    rid = first_resource(world)
    fb.record(world.store, rid, True, 'api')
    fb.record(world.store, rid, False, 'api')
    stats = fb.aggregate(world.store, [rid, 2**31 - 2])
    assert stats[rid]['reports'] >= 2 and stats[rid]['worked'] >= 1 and 2**31 - 2 not in stats
    value = fb.write_stats(tmp_path, stats)
    assert value['totals']['agents'] == 1 and fb.resource_stats(tmp_path, rid) == stats[rid]
    from agent_market.concierge import growth_catalog, growth_pages
    monkeypatch.setenv('LOG_DIR', str(tmp_path.parent))
    (tmp_path.parent/'public-pages').mkdir(exist_ok=True)
    fb.write_stats(tmp_path.parent/'public-pages', stats)
    section = growth_catalog.outcome_section(rid)
    assert 'action="/api/feedback"' in section and 'name="worked" value="1"' in section and 'did not' in section
    assert growth_pages.data_dir() == tmp_path.parent/'public-pages'


def test_protocol_first_call_fixes(w):  # noqa: F811
    """11-10: trailing-slash posts and start-up list probes no longer fail."""
    _, c, _ = w
    init = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
            'params': {'protocolVersion': '2025-06-18', 'clientInfo': {'name': 'Probe'}, 'capabilities': {}}}
    assert c.post('/mcp/', json=init, follow_redirects=False).json()['result']['protocolVersion'] == '2025-06-18'
    for method, key in (('resources/list', 'resources'), ('resources/templates/list', 'resourceTemplates'), ('prompts/list', 'prompts')):
        assert c.post('/mcp', json={'jsonrpc': '2.0', 'id': 2, 'method': method}).json()['result'] == {key: []}
    message = {'jsonrpc': '2.0', 'id': 1, 'method': 'message/send', 'params': {'message': {
        'kind': 'message', 'role': 'user', 'messageId': 'm1', 'parts': [{'kind': 'text', 'text': 'find a weather API'}]}}}
    r = c.post('/a2a/', json=message, follow_redirects=False)
    assert r.status_code == 200 and r.json()['result']['kind'] == 'message'


def test_newer_protocol_header_still_negotiates(w):  # noqa: F811
    """11-11: a client on a newer MCP revision can still discover and initialize; other calls get 400 with the list."""
    _, c, _ = w
    head = {'MCP-Protocol-Version': '2026-06-30', 'Accept': 'application/json, text/event-stream'}
    found = c.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'server/discover', 'params': {}}, headers=head)
    assert found.status_code == 200
    assert found.json()['result']['supportedVersions'][0] == found.json()['result']['protocolVersion']
    init = c.post('/mcp', headers=head, json={'jsonrpc': '2.0', 'id': 2, 'method': 'initialize', 'params': {
        'protocolVersion': '2026-06-30', 'clientInfo': {'name': 'Next'}, 'capabilities': {}}})
    assert init.status_code == 200 and init.json()['result']['protocolVersion'] in ('2025-11-25', '2025-06-18')
    listed = c.post('/mcp', json={'jsonrpc': '2.0', 'id': 3, 'method': 'tools/list'}, headers=head)
    assert listed.status_code == 400 and listed.json()['id'] == 3
    assert listed.json()['error']['data'] == {'supported': ['2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05'],
                                              'requested': '2026-06-30'}
    ok = c.post('/mcp', json={'jsonrpc': '2.0', 'id': 4, 'method': 'tools/list'},
                headers={'MCP-Protocol-Version': '2025-06-18'})
    assert ok.status_code == 200 and ok.json()['result']['tools']


def test_well_known_aliases_point_at_the_real_files(w):  # noqa: F811
    _, c, _ = w
    for alias, target in (('/.well-known/llms.txt', '/llms.txt'),
                          ('/.well-known/mcp/server-card.json', '/.well-known/mcp/server.json')):
        r = c.get(alias, follow_redirects=False)
        assert r.status_code == 301 and r.headers['location'] == target
        assert c.get(alias).status_code == 200
    assert c.get('/.well-known/oauth-protected-resource').status_code == 404  # no OAuth: 404 is the spec answer
