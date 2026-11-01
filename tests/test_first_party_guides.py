"""The owned public-guidance agent is useful without catalog quality priority."""
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from agent_market.capability_contracts import validate
from agent_market.first_party_guides import PlatformGuideAgent, TOOL, router_for


def test_guides_are_contract_compatible_and_contain_only_the_fixed_public_corpus():
    agent = PlatformGuideAgent()
    arguments = {'query': 'private snapshot workflow review', 'language': 'en', 'limit': 4}
    result = agent.search(arguments)
    validate('docs.search.v1', arguments, result)
    assert result['items'] and all(item['url'].startswith('https://agentconcierge.biz/api/platform-guides/') for item in result['items'])
    tool = agent.tools()[0]
    assert tool['annotations']['readOnlyHint'] and not tool['annotations']['destructiveHint']


def test_default_router_is_closed_and_no_own_agent_quality_is_granted():
    assert not router_for().routes
    assert 'quality' not in json.dumps(PlatformGuideAgent().tools()).lower()


def test_actual_mcp_initialization_list_and_call_with_resolvable_sources():
    app = FastAPI(); app.include_router(router_for(enabled=True))
    with TestClient(app, base_url='https://guides.test') as client:
        def call(method, params):
            return client.post('/api/platform-guides/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}).json()
        assert call('initialize', {'protocolVersion': '2025-06-18'})['result']['capabilities'] == {'tools': {}}
        assert call('tools/list', {})['result']['tools'][0]['name'] == TOOL
        result = call('tools/call', {'name': TOOL, 'arguments': {'query': 'review snapshot', 'language': 'en', 'limit': 3}})
        assert result['result']['structuredContent']['items'] and result['result']['isError'] is False
        for item in result['result']['structuredContent']['items']:
            path = item['url'].split('agentconcierge.biz', 1)[1]
            assert client.get(path).json()['guide']['title'] == item['title']
        assert call('tools/call', {'name': 'execute_command', 'arguments': {}})['error']['code'] == -32602


@pytest.mark.parametrize('query', ['https://private.example', '<script>alert(1)</script>', 'token=synthetic'])
def test_guide_agent_never_fetches_addresses_or_accepts_secret_payloads(query):
    with pytest.raises(ValueError):
        PlatformGuideAgent().search({'query': query, 'language': 'en', 'limit': 2})
