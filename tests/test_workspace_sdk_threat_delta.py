"""BFF response hardening preserves server tokens and current execution authority."""
import json
import time
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlsplit

from fastapi.testclient import TestClient
import httpx
import pytest

from agent_market.workspace_sdk_bff import create_app, _bounded_object
from tests.test_workspace_sdk_v2 import sdk_world, sign_in
from tests.test_workspace_release_v2 import release_world, ORIGIN
from tests.test_workspace_execution_api import private_api


@pytest.mark.parametrize('raw', [b'{"ok":false,"ok":true}', b'{"x":NaN}', b'{"x":1e999}',
    b'{"x":' + b'[' * 15 + b'0' + b']' * 15 + b'}',
    b'{"x":' + b'[' * 1100 + b'0' + b']' * 1100 + b'}',
    json.dumps({'x': list(range(2100))}).encode()])
def test_gateway_json_rejects_duplicate_nonfinite_deep_or_oversized_tree(raw):
    with pytest.raises(ValueError): _bounded_object(raw, 131072)


@pytest.mark.parametrize('attack', ['duplicate', 'nonfinite', 'deep', 'many', 'wrong_profile'])
def test_malformed_gateway_response_fails_closed_after_real_customer_exchange(sdk_world, attack):
    s = sdk_world; mutate = {'enabled': False}; seen = []
    def forward(request):
        seen.append((request.method, request.url.path))
        result = s.gateway.request(request.method, request.url.path,
            headers=dict(request.headers), content=request.content)
        raw = result.content
        if mutate['enabled'] and request.url.path.endswith('/prepare'):
            body = result.json()
            if attack == 'duplicate': raw = b'{"ok":false,' + raw[1:]
            if attack == 'nonfinite': raw = b'{"unexpected":1e999,' + raw[1:]
            if attack == 'deep': body['unexpected'] = [[[[[[[[[[[[[0]]]]]]]]]]]]]; raw = json.dumps(body).encode()
            if attack == 'many': body['unexpected'] = list(range(2100)); raw = json.dumps(body).encode()
            if attack == 'wrong_profile': body['profile'] = 'workspace-typed-sdk-v2'; raw = json.dumps(body).encode()
        return httpx.Response(result.status_code, headers={'Content-Type': 'application/json'}, content=raw)
    transport = httpx.Client(transport=httpx.MockTransport(forward))
    bff = TestClient(create_app(s.config, app_origin=ORIGIN, http=transport, root=s.root), base_url=ORIGIN)
    current = SimpleNamespace(**(vars(s) | {'bff': bff}))
    try:
        headers = sign_in(current); before = s.x.calls.count('tools/call'); mutate['enabled'] = True
        response = bff.post('/bff/prepare', headers=headers, json={})
        assert response.status_code == 403
        assert all(text not in response.text for text in ('access_token', 'Traceback', 'unexpected', 'ticket_id'))
        assert s.x.calls.count('tools/call') == before
        assert sum(path.endswith('/prepare') for _, path in seen) == 1
        assert bff.get('/bff/session').json()['authenticated']
    finally:
        bff.close(); transport.close()


def test_existing_sdk_script_exposes_only_same_origin_bff_actions_not_master_authority():
    from pathlib import Path
    raw = Path('agent_market/gateway/webapp/sdk-v2.js').read_text()
    assert "fetch('/bff'+path" in raw
    assert all(value not in raw for value in ('publishKey', 'run_key', 'localStorage', 'sessionStorage', 'PAYMENT-SIGNATURE'))
    assert _bounded_object(b'{"ok":true,"profile":"workspace-sdk-v2"}', 4096)['ok'] is True


def test_parallel_pending_logins_cannot_exceed_final_session_capacity():
    """Accepted flows are bounded again when an exchanged token is committed."""
    config = {'profile': 'workspace-sdk-v2', 'app_id': 'wap_' + 'a' * 32, 'allowed_origins': [ORIGIN]}
    def exchange(request):
        assert request.url.path.endswith('/exchange')
        return httpx.Response(200, json={'ok': True, 'profile': 'workspace-sdk-v2',
            'access_token': 't' * 43, 'audience': 'app-run', 'expires': time.time() + 299})
    transport = httpx.Client(transport=httpx.MockTransport(exchange))
    client = TestClient(create_app(config, app_origin=ORIGIN, http=transport), base_url=ORIGIN)
    def login():
        result = client.post('/bff/login', headers={'Origin': ORIGIN}, json={})
        assert result.status_code == 200
        return dict(parse_qsl(urlsplit(result.json()['authorization_url']).query))['state'], client.cookies.get('ac_workspace_flow')
    def callback(flow):
        return client.get('/bff/callback', params={'code': 'synthetic-one-use-code', 'state': flow[0]},
            headers={'Cookie': 'ac_workspace_flow=' + flow[1]}, follow_redirects=False)
    try:
        pending = [login() for _ in range(100)]
        for flow in pending[:-1]: assert callback(flow).status_code == 303
        last = login()
        assert callback(pending[-1]).status_code == 303
        rejected = callback(last)
        assert rejected.status_code == 403
        assert 'access_token' not in rejected.text
    finally:
        client.close(); transport.close()
