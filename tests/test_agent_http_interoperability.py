"""Isolated protocol interoperability and adversarial browser-origin checks."""
# ruff: noqa: F811 -- pytest fixtures imported for dependency injection.
import json

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from agent_market.concierge.agent_http import trusted_origins
from agent_market.concierge.front import create_front_app
from agent_market.concierge.mcp_contract import mcp_tools
from tests.test_fast_single_recommendation import catalog  # noqa: F401


@pytest.mark.parametrize('path', ['/llms.txt', '/llms-full.txt', '/robots.txt', '/sitemap.xml',
    '/.well-known/agent-card.json', '/.well-known/mcp.json', '/.well-known/agent-entry.json', '/skill.md'])
def test_document_head_agrees_with_get_without_body(catalog, path):
    _, _, client, _, _ = catalog
    before = client.get(path)
    head = client.head(path)
    assert before.status_code == head.status_code == 200
    assert head.content == b''
    assert before.headers['content-type'] == head.headers['content-type']
    assert head.headers['x-content-type-options'] == 'nosniff'


def test_sitemap_categories_remain_pages_when_evidence_changes(catalog):
    _, _, client, _, _ = catalog
    from tests.test_sitemap_parts import sitemap_locs
    paths = [x.split('https://agentconcierge.biz', 1)[-1] for x in sitemap_locs(client) if '/agents/category/' in x]
    assert paths
    for path in paths:
        for method in ('get', 'head'):
            response = getattr(client, method)(path)
            assert response.status_code == 200
    assert client.get('/agents/category/not-a-category').status_code == 404


@pytest.mark.parametrize('path', ['/chat', '/mcp', '/a2a', '/'])
def test_browser_agent_preflight_is_explicit_and_exposes_transport_headers(catalog, monkeypatch, path):
    _, front, _, _, _ = catalog
    monkeypatch.setenv('AGENT_BROWSER_ORIGINS', 'https://trusted-agent.example')
    client = TestClient(create_front_app(front))
    headers = {'Origin': 'https://trusted-agent.example', 'Access-Control-Request-Method': 'POST',
        'Access-Control-Request-Headers': 'Content-Type, X-Visitor-Token, Mcp-Session-Id'}
    response = client.options(path, headers=headers)
    assert response.status_code == 204
    assert response.headers['access-control-allow-origin'] == headers['Origin']
    assert 'access-control-allow-credentials' not in response.headers
    # An invalid request exercises actual error responses without creating a visitor.
    body = {'message': ''} if path in ('/chat', '/') else {'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}
    response = client.post(path, json=body, headers={'Origin': headers['Origin']})
    assert response.headers['access-control-allow-origin'] == headers['Origin']
    assert 'Mcp-Session-Id' in response.headers['access-control-expose-headers']
    assert 'origin' in response.headers['vary'].lower()
    assert 'RateLimit-Policy' in response.headers


@pytest.mark.parametrize('origin', ['null', 'https://hostile.example', 'https://agentconcierge.biz.evil.example'])
def test_untrusted_browser_cannot_create_identity_or_invoke(catalog, origin):
    store, _, client, _, _ = catalog
    # /chat and /mcp serve anonymous recommendations to any page (test_public_cross_site_cors.py).
    for path in ('/a2a', '/'):
        response = client.post(path, headers={'Origin': origin}, json={'message': 'hello'})
        assert response.status_code == 403
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert 'access-control-allow-origin' not in response.headers
    assert store.query('SELECT COUNT(*) FROM agent_visitors')[0][0] == 0


def test_trusted_origin_cannot_request_extra_headers_or_private_routes(catalog, monkeypatch):
    _, front, _, _, _ = catalog
    monkeypatch.setenv('AGENT_BROWSER_ORIGINS', 'https://trusted-agent.example')
    client = TestClient(create_front_app(front))
    headers = {'Origin': 'https://trusted-agent.example', 'Access-Control-Request-Method': 'POST',
        'Access-Control-Request-Headers': 'X-Edge-Mcp-Prepare'}
    assert client.options('/mcp', headers=headers).status_code == 403
    for path in ('/api/customer-organizations', '/mcp/compact', '/admin'):
        assert 'access-control-allow-origin' not in client.options(path, headers=headers).headers
    # Downloaded workflow apps retain their separate capability-key CORS policy.
    assert client.options('/api/workflows/run', headers=headers).headers['access-control-allow-origin'] == '*'
    assert client.get('/mcp').status_code == 405
    assert client.head('/mcp').status_code == 405


@pytest.mark.parametrize('value', ['*', 'null', 'https://user:pass@agent.example', 'https://agent.example/path',
    'http://agent.example', 'https://agent.example:bad', 'https://*.example', 'https://agent.\nexample'])
def test_misconfigured_cors_fails_closed(monkeypatch, value):
    monkeypatch.setenv('AGENT_BROWSER_ORIGINS', value)
    with pytest.raises(ValueError):
        trusted_origins('https://agentconcierge.biz')


@pytest.mark.parametrize('path', ['/mcp', '/a2a'])
@pytest.mark.parametrize('body, code', [([], -32600), ({'method': 'ping'}, -32600),
    ({'jsonrpc': '2.0', 'id': True, 'method': 'ping'}, -32600),
    ({'jsonrpc': '2.0', 'id': 1, 'method': 'ping', 'params': []}, -32602)])
def test_rpc_rejects_invalid_envelopes_without_side_effects(catalog, path, body, code):
    store, _, client, _, _ = catalog
    response = client.post(path, json=body)
    assert response.json()['error']['code'] == code
    assert store.query('SELECT COUNT(*) FROM agent_visitors')[0][0] == 0
    assert client.post(path, content='{').json()['error']['code'] == -32700


def test_tool_hints_schemas_and_continuation_are_truthful(catalog):
    _, _, client, _, _ = catalog
    tools = mcp_tools()
    for tool in tools:
        Draft202012Validator.check_schema(tool['outputSchema'])
        assert set(tool['annotations']) == {'readOnlyHint', 'destructiveHint', 'idempotentHint', 'openWorldHint'}
    by_name = {t['name']: t for t in tools}
    assert by_name['search']['annotations']['readOnlyHint']  # Stateless catalog lookup.
    # call relays only tools classified read-only (PM 11-14 04:1x); adapt_rest can send POST/PUT/DELETE.
    assert not by_name['call']['annotations']['destructiveHint'] and by_name['call']['annotations']['openWorldHint']
    assert by_name['adapt_rest']['annotations']['destructiveHint']
    assert by_name['workflow_details']['annotations']['readOnlyHint']
    hello = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
        'params': {'name': 'hello'}}).json()['result']
    Draft202012Validator(by_name['hello']['outputSchema']).validate(hello['structuredContent'])
    assert hello['structuredContent']['text'] == hello['content'][0]['text']
    invalid = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list',
        'params': {'cursor': 'invented'}}).json()
    assert invalid['error']['code'] == -32602


def test_supported_protocol_negotiation_does_not_claim_unimplemented_revision(catalog):
    _, _, client, _, _ = catalog
    for endpoint in ('/mcp', '/mcp/compact'):
        reply = client.post(endpoint, json={'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
            'params': {'protocolVersion': '2026-07-28'}}).json()
        assert reply['result']['protocolVersion'] == '2025-11-25'


def test_invalid_visitor_session_reset_is_explicit_without_echo(catalog):
    _, _, client, _, _ = catalog
    token = 'vt_unknown_session'
    reply = client.post('/chat', headers={'X-Visitor-Token': token}, json={'message': 'hello'}).json()
    assert reply['visitor']['session_status'] == 'reset'
    assert token not in json.dumps(reply)


def test_a2a_context_rejects_conflicting_authority_and_retains_structured_history(catalog):
    _, _, client, add, now = catalog
    rid = add('Seoul Forecast', report_at=now)
    def send(text, ctx=None, token=None, ua='synthetic-agent/1'):
        message = {'role': 'user', 'messageId': 'fixture', 'parts': [{'kind': 'text', 'text': text}]}
        if ctx is not None:
            message['contextId'] = ctx
        return client.post('/a2a', headers={'User-Agent': ua, **({'X-Visitor-Token': token} if token else {})},
            json={'jsonrpc': '2.0', 'id': 1, 'method': 'message/send', 'params': {'message': message}}).json()
    def data(value):
        return next(p['data'] for p in value['result']['parts'] if p.get('kind') == 'data')
    first = send('weather forecast for Seoul')
    ctx = first['result']['contextId']
    assert data(first)['recommendations'][0]['id'] == rid
    assert data(send('details 1', ctx, ua='another-runtime/2'))['recommendations'][0]['id'] == rid
    other = client.post('/chat', json={'message': 'hello'}).json()['visitor']['token']
    assert send('details 1', ctx, other)['error']['code'] == -32602
    assert send('hello', 'ctx_missing')['error']['code'] == -32602


def test_discovery_only_runner_completes_without_credentials_or_provider_execution(catalog):
    from scripts.agent_scenarios import Runner,rest_agent
    _, _, client, add, now = catalog
    add('Seoul Forecast', report_at=now)
    client.base_url = 'https://agentconcierge.biz'
    audit = Runner(str(client.base_url),client)
    rest_agent(audit)
    # The broader runner reports both observations and policy warnings.
    assert all(r['status'] != 'FAIL' for r in audit.results), audit.results
    assert 'vt_' not in json.dumps(audit.results)


def test_category_checks_later_publications_instead_of_only_first_six_listings(catalog):
    import time
    from agent_market.agent_access.storage import migrate
    store, _, client, add, now = catalog
    migrate(store)
    for number in range(97):
        rid = add('Unavailable ' + str(number)) if number < 96 else add('Verified Later', report_at=now)
        with store.tx() as db:
            db.execute('INSERT INTO adoption_publications(resource_id,signature,expires,version_id,verified,updated,state) VALUES (?,?,?,?,?,?,?)',
                (rid, 'synthetic', time.time()+3600, 'old-version', 1, time.time(), '{}'))
    response = client.get('/agents/category/travel_maps_weather')
    assert response.status_code == 200
    assert 'Verified Later' in response.text and 'Unavailable 0' not in response.text
    assert 'verified-later.example' not in response.text
