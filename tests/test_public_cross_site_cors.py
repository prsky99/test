"""Any page may ask for recommendations anonymously; execution and contact stay origin-restricted."""
import pytest

from agent_market.concierge.agent_http import PUBLIC_MCP_TOOLS, OriginLimiter, public_mcp_call
from agent_market.concierge.mcp_contract import mcp_tools
from tests.test_fast_single_recommendation import catalog  # noqa: F401

PAGE = 'https://some-widget.example'


def rpc(name, **arguments):
    return {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': name, 'arguments': arguments}}


@pytest.mark.parametrize('path', ['/chat', '/mcp'])
def test_any_page_gets_a_wildcard_preflight_without_credentials(catalog, path):
    _, _, client, _, _ = catalog
    response = client.options(path, headers={'Origin': PAGE, 'Access-Control-Request-Method': 'POST',
        'Access-Control-Request-Headers': 'Content-Type, X-Visitor-Token, Mcp-Session-Id, Mcp-Protocol-Version'})
    assert response.status_code == 204
    assert response.headers['access-control-allow-origin'] == '*'
    assert 'access-control-allow-credentials' not in response.headers
    # Authorization and execution headers remain for explicitly trusted origins.
    for extra in ('Authorization', 'Idempotency-Key'):
        denied = client.options(path, headers={'Origin': PAGE, 'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'Content-Type, ' + extra})
        assert denied.status_code == 403 and 'access-control-allow-origin' not in denied.headers


def test_any_page_can_ask_chat_and_read_the_reply(catalog):
    _, _, client, add, now = catalog
    add('Weather', report_at=now - 1)
    response = client.post('/chat', headers={'Origin': 'null'}, json={'message': 'weather forecast'})
    assert response.status_code == 200
    assert response.headers['access-control-allow-origin'] == '*'
    assert 'X-Visitor-Token' in response.headers['access-control-expose-headers']
    assert response.json()['data']['recommendations']


def test_cross_site_calls_never_carry_customer_credentials(catalog):
    from agent_market.concierge import agent_http
    seen = []

    async def app(scope, receive, send):
        seen.append(dict(scope['headers']))
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'{}'})
    from fastapi.testclient import TestClient
    client = TestClient(agent_http.AgentHTTP(app, origins=frozenset(), security_headers={}))
    client.post('/chat', headers={'Origin': PAGE, 'Cookie': 'customer_session=x', 'Authorization': 'Bearer y'}, json={})
    assert b'cookie' not in seen[0] and b'authorization' not in seen[0]


def test_mcp_tools_open_to_pages_are_exactly_the_read_only_ones():
    published = {t['name']: t['annotations'] for t in mcp_tools()}
    assert PUBLIC_MCP_TOOLS <= set(published)
    for name in PUBLIC_MCP_TOOLS - {'hello', 'chat'}:
        assert published[name]['readOnlyHint'], name
    for name in ('call', 'adapt_rest', 'subscribe', 'verify_contact', 'report'):
        assert name not in PUBLIC_MCP_TOOLS


@pytest.mark.parametrize('name', ['call', 'adapt_rest', 'subscribe', 'verify_contact', 'report'])
def test_pages_cannot_execute_subscribe_or_report_over_mcp(catalog, name):
    store, _, client, _, _ = catalog
    response = client.post('/mcp', headers={'Origin': PAGE}, json=rpc(name))
    assert response.status_code == 403
    assert response.headers['access-control-allow-origin'] == '*'  # the page can read why
    assert response.json()['error']['code'] == -32001
    # A batch cannot smuggle a restricted call behind a permitted one.
    assert not public_mcp_call(b'[{"jsonrpc":"2.0","id":1,"method":"tools/list"},' +
                               b'{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"' + name.encode() + b'"}}]')


def test_pages_can_list_and_call_read_only_mcp_tools(catalog):
    _, _, client, _, _ = catalog
    listed = client.post('/mcp', headers={'Origin': PAGE}, json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
    assert listed.status_code == 200 and listed.headers['access-control-allow-origin'] == '*'
    hello = client.post('/mcp', headers={'Origin': PAGE}, json=rpc('hello'))
    assert hello.status_code == 200 and 'result' in hello.json()


@pytest.mark.parametrize('path', ['/a2a', '/'])
def test_other_transports_keep_the_explicit_origin_list(catalog, path):
    _, _, client, _, _ = catalog
    response = client.post(path, headers={'Origin': PAGE}, json={'message': 'hello'})
    assert response.status_code == 403 and 'access-control-allow-origin' not in response.headers


def test_one_page_cannot_monopolize_the_service(catalog, monkeypatch):
    limiter = OriginLimiter(limit=2, window=60)
    assert limiter.wait(PAGE) == 0 and limiter.wait(PAGE) == 0
    assert limiter.wait(PAGE) > 0
    assert limiter.wait('https://other.example') == 0
    from fastapi.testclient import TestClient
    from agent_market.concierge import agent_http
    from agent_market.concierge.front import create_front_app
    monkeypatch.setattr(agent_http, 'PUBLIC_LIMIT', 1)
    _, front, _, _, _ = catalog
    client = TestClient(create_front_app(front))
    client.post('/chat', headers={'Origin': PAGE}, json={'message': ''})
    limited = client.post('/chat', headers={'Origin': PAGE}, json={'message': ''})
    assert limited.status_code == 429 and int(limited.headers['retry-after']) >= 1
    assert limited.headers['access-control-allow-origin'] == '*'
