"""Closed public auth must not echo stale one-use callback query into access logs."""
import logging
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
import pytest
from uvicorn.logging import AccessFormatter
from uvicorn.protocols.utils import get_client_addr, get_path_with_query_string

from agent_market.concierge.front import create_front_app
from tests.test_front_about import about_client
from tests.test_customer_identity import customer, github_world


@pytest.mark.parametrize('path', ['/api/customer-auth/callback', '/api/customer-auth/github/callback', '/api/customer-auth/callback/typo'])
def test_closed_callback_scrubs_response_time_uvicorn_access_scope(about_client, path):
    observed = []
    formatter = AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False)
    async def app(scope, receive, send):
        async def record(message):
            if message['type'] == 'http.response.start':
                arguments = (get_client_addr(scope), scope['method'], get_path_with_query_string(scope),
                             scope['http_version'], message['status'])
                entry = logging.LogRecord('isolated.access', logging.INFO, '', 0,
                    '%s - "%s %s HTTP/%s" %d', arguments, None)
                observed.append((scope.get('query_string'), formatter.format(entry)))
            await send(message)
        await about_client.app(scope, receive, record)
    with TestClient(app, base_url='https://customer.test') as client:
        result = client.get(path, params={'code': 'synthetic-oneuse-private-code', 'state': 'synthetic-private-state'})
    assert result.status_code == 404 and len(observed) == 1
    assert observed[0][0] == b''
    assert 'synthetic-oneuse-private-code' not in observed[0][1] and 'synthetic-private-state' not in observed[0][1]


@pytest.mark.parametrize('path', ['/api/customer-auth/callback', '/api/customer-auth/github/callback'])
def test_enabled_callback_rejected_before_router_still_scrubs_access_scope(about_client, monkeypatch, path):
    front = about_client.app.state.front
    monkeypatch.setattr(front.security, 'try_acquire_request_slot', lambda: False)
    application = create_front_app(front, workspace_access_enabled=True)
    observed = []
    async def app(scope, receive, send):
        async def record(message):
            if message['type'] == 'http.response.start':
                observed.append((scope.get('query_string'), get_path_with_query_string(scope)))
            await send(message)
        await application(scope, receive, record)
    with TestClient(app, base_url='https://customer.test') as client:
        result = client.get(path, params={'code': 'synthetic-private-code', 'state': 'synthetic-private-state'})
    assert result.status_code == 503 and len(observed) == 1
    assert observed[0][0] == b'' and 'synthetic-private' not in observed[0][1]


@pytest.mark.parametrize('provider', ['google', 'github'])
@pytest.mark.parametrize('outcome', ['badcode', 'oversized', 'wrong_method'])
def test_enabled_refused_callback_leaves_no_oneuse_query_in_access_scope(about_client, provider, outcome):
    application = create_front_app(about_client.app.state.front, workspace_access_enabled=True)
    path = '/api/customer-auth/' + ('github/' if provider == 'github' else '') + 'callback'
    observed = []
    async def app(scope, receive, send):
        async def record(message):
            if message['type'] == 'http.response.start':
                observed.append((scope.get('query_string'), get_path_with_query_string(scope), '_customer_auth_callback_query' in scope))
            await send(message)
        await application(scope, receive, record)
    parameters = {'code': 'synthetic-private-code', 'state': 'synthetic-private-state'}
    if outcome == 'oversized': parameters['scope'] = 'x' * 9000
    with TestClient(app, base_url='https://customer.test') as client:
        result = client.request('POST' if outcome == 'wrong_method' else 'GET', path, params=parameters)
    assert result.status_code == {'badcode': 401, 'oversized': 400, 'wrong_method': 405}[outcome]
    assert observed == [(b'', path, False)]


@pytest.mark.parametrize('provider', ['google', 'github'])
def test_enabled_actual_front_callback_parses_private_query_and_completes_mock_provider(about_client, customer, provider):
    from agent_market.customer_identity import CustomerIdentity
    from agent_market.workspace_platform import platform_for
    w = customer
    if provider == 'github': github_world(w)
    front = about_client.app.state.front; platform = platform_for(front)
    identity = CustomerIdentity(front.store, platform.key, w.core.config, w.core.http, github_config=w.core.github_config)
    platform.identity = identity
    application = create_front_app(front, workspace_access_enabled=True)
    observed = []
    async def app(scope, receive, send):
        async def record(message):
            if message['type'] == 'http.response.start' and scope['path'].endswith('/callback'):
                observed.append((scope.get('query_string'), get_path_with_query_string(scope), '_customer_auth_callback_query' in scope))
            await send(message)
        await application(scope, receive, record)
    with TestClient(app, base_url='https://agentconcierge.biz') as client:
        prepared = client.post('/api/customer-auth/begin', json={'provider': provider})
        assert prepared.status_code == 200, prepared.text
        query = parse_qs(urlsplit(prepared.json()['authorization_url']).query)
        if provider == 'google': w.state['nonce'] = query['nonce'][0]
        path = '/api/customer-auth/' + ('github/' if provider == 'github' else '') + 'callback'
        result = client.get(path, params={'code': 'synthetic-private-code', 'state': query['state'][0]})
    assert result.status_code == 200 and result.json()['authenticated'], result.text
    assert observed == [(b'', path, False)]
