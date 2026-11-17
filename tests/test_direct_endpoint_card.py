"""PM 11-18 option A: a card our gateway does not relay (an action tool, provider authorization, terms-restricted)
gives the provider's own public MCP address as direct_endpoint, with a notice that we do not relay the tool.
A relayed card keeps our gateway address only. No DNS lookup in the answer path."""
import pytest

from agent_market.concierge.connections import DIRECT_NOTE, direct_endpoint, public_agent


@pytest.mark.parametrize('url', ['https://x711.io/mcp', 'https://mcp.example.com/v1/mcp?format=json'])
def test_a_public_https_address_is_given(url):
    assert direct_endpoint({'kind': 'mcp', 'url': url}) == url


@pytest.mark.parametrize('url', [
    'http://x711.io/mcp',                         # not https
    'https://10.0.0.5/mcp', 'https://127.0.0.1/mcp', 'https://[::1]/mcp',   # not a global address
    'https://localhost/mcp', 'https://mcp.internal/mcp', 'https://printer.local/mcp', 'https://intranet/mcp',
    'https://user:pass@x711.io/mcp',              # user info
    'https://x711.io/mcp?api_key=abc', 'https://x711.io/mcp?token=abc', 'https://x711.io/mcp?Authorization=x',
    'https://x711.io/mcp?sig=1', 'https://x711.io/mcp#frag', None, 'not a url',
])
def test_an_address_that_is_not_public_or_carries_a_credential_is_not_given(url):
    assert direct_endpoint({'kind': 'mcp', 'url': url}) is None


def test_only_mcp_addresses():
    assert direct_endpoint({'kind': 'a2a', 'url': 'https://agent.example/.well-known/agent-card.json'}) is None


def test_no_dns_lookup_in_the_answer_path(monkeypatch):
    import socket

    def refuse(*args, **kwargs):
        raise AssertionError('direct_endpoint resolved a name')
    monkeypatch.setattr(socket, 'getaddrinfo', refuse)
    assert direct_endpoint({'kind': 'mcp', 'url': 'https://x711.io/mcp'}) == 'https://x711.io/mcp'


def _card(**value):
    base = {'id': 43775, 'kind': 'mcp', 'name': 'x711', 'url': 'https://x711.io/mcp', 'tools': ['x711_email_send']}
    return public_agent({**base, **value})


def test_an_unrelayed_action_tool_card_gives_the_direct_endpoint_and_says_we_do_not_relay():
    note = "This tool performs an action. Connect through the provider's own documentation: https://x711.io"
    card = _card(tool_unlisted=True, connection_note=note, connection_reason='action_tool')
    assert card['connection_available'] is False and card['direct_endpoint'] == 'https://x711.io/mcp'
    assert card['connection_note'] == note + DIRECT_NOTE and 'we do not relay this tool' in card['connection_note']
    assert '/api/gateway/mcp/43775' in card['usage_endpoint'] and card.get('host', 'agentconcierge.biz') == 'agentconcierge.biz'


def test_a_provider_authorization_card_gives_it_too():
    card = _card(auth_required=1)
    assert card['connection_reason'] == 'provider_authorization' and card['direct_endpoint'] == 'https://x711.io/mcp'
    assert card['connection_note'].endswith(DIRECT_NOTE)


def test_a_relayed_card_never_shows_the_provider_address():
    card = _card()
    assert card['connection_available'] is True and 'direct_endpoint' not in card
    assert 'x711.io' not in str({k: v for k, v in card.items() if k in ('url', 'usage_endpoint', 'agent_url', 'host')})


def test_a_card_with_a_credential_in_its_address_gets_no_direct_endpoint():
    card = _card(url='https://x711.io/mcp?key=secret', tool_unlisted=True, connection_note='Not relayed.')
    assert 'direct_endpoint' not in card and card['connection_note'] == 'Not relayed.'
    assert 'secret' not in str(card)


@pytest.mark.parametrize('url', [
    'https://mcp.example.com/sse/9f86d081884c7d659a2feaa0c55ad015a3bf4f1b',     # hex key
    'https://mcp.example.com/mcp/aGVsbG8td29ybGQtc2VjcmV0LXRva2VuLTEyMw',       # base64 run
    'https://mcp.example.com/u/sk_live_51HbXyZ2eKj4Lm9QwErTy0',                 # mixed token
])
def test_an_address_with_a_key_in_its_path_is_not_given(url):
    """PM 11-18: a key in the path is a credential too; a public registry listing it is no reason to repeat it."""
    assert direct_endpoint({'kind': 'mcp', 'url': url}) is None


@pytest.mark.parametrize('url', [
    'https://x402-bazaar-rank.x402-bazaar-rank-worker.workers.dev/mcp',
    'https://mcp.example.com/my-weather-forecast-mcp-server/v1/mcp',          # a readable slug of 30 characters
    'https://server.smithery.ai/@acme/weather/mcp',
])
def test_a_readable_path_is_still_given(url):
    assert direct_endpoint({'kind': 'mcp', 'url': url}) == url
