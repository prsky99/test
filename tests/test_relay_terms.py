"""PM 11-18 (다)+rank: a provider whose terms prohibit our relay stays listed, ranks after the relayable ones, and is
never run through our gateway; the card gives its direct address. L: slow or often-failing listings rank lower."""
import json
from types import SimpleNamespace

import pytest
from tests.test_edge_gateway import edge, catalog  # noqa: F401  (fixtures)

from agent_market.concierge import relay_terms


@pytest.fixture
def terms(tmp_path, monkeypatch):
    path = tmp_path / 'member_terms.json'
    path.write_text(json.dumps({'members': {
        '143970': {'status': 'prohibits'}, '241601': {'status': 'allowed'}, '39577': {'status': 'silent'},
        '43775': {'status': 'prohibits'}}}))
    monkeypatch.setattr(relay_terms, '_path', lambda: path)
    relay_terms.reset()
    yield path
    relay_terms.reset()


def test_only_prohibits_blocks(terms):
    assert relay_terms.restricted(143970) and relay_terms.restricted('143970')
    assert not relay_terms.restricted(241601)          # allowed
    assert not relay_terms.restricted(39577)           # silent
    assert not relay_terms.restricted(1)               # no verdict
    assert not relay_terms.restricted(None)


def test_an_unreadable_verdict_file_blocks_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(relay_terms, '_path', lambda: tmp_path / 'missing.json')
    relay_terms.reset()
    assert not relay_terms.restricted(143970)
    (tmp_path / 'missing.json').write_text('{not json')
    relay_terms.reset()
    assert not relay_terms.restricted(143970)
    relay_terms.reset()


def test_the_card_stays_listed_but_says_connect_directly(terms):
    from agent_market.concierge.connections import DIRECT_NOTE, public_agent
    card = public_agent({'id': 43775, 'kind': 'mcp', 'name': 'x711', 'url': 'https://x711.io/mcp', 'tools': ['lookup']})
    assert card['connection_available'] is False and card['connection_reason'] == 'terms_restricted'
    assert card['direct_endpoint'] == 'https://x711.io/mcp'
    assert card['connection_note'] == relay_terms.NOTE + DIRECT_NOTE
    assert 'Connect from your own client' in card['connection_note'] and 'connect_steps' not in card
    other = public_agent({'id': 241601, 'kind': 'mcp', 'name': 'wiki', 'url': 'https://x.example/mcp', 'tools': ['s']})
    assert other['connection_available'] is True and 'connection_reason' not in other


def test_a_card_without_a_public_address_names_the_provider(terms):
    from agent_market.concierge.connections import public_agent
    card = public_agent({'id': 143970, 'kind': 'mcp', 'name': 'f', 'url': 'http://127.0.0.1/mcp', 'tools': ['s']})
    assert card['connection_reason'] == 'terms_restricted' and 'direct_endpoint' not in card
    assert card['connection_note'].endswith('Connect through the provider.')


def test_the_managed_gateway_refuses_with_terms_restricted(terms, monkeypatch):
    from agent_market import capability_registry
    from agent_market.concierge import managed_gateway
    from agent_market.concierge.execution_policy import ExecutionDenied
    monkeypatch.setattr(capability_registry, 'known_schema_failure', lambda store, resource: False)
    monkeypatch.setattr(managed_gateway, 'admit', lambda *a, **k: None)
    rows = {143970: {'id': 143970, 'kind': 'mcp', 'url': 'https://faceabot.com/tools-mcp/x'},
            241601: {'id': 241601, 'kind': 'mcp', 'url': 'https://x.example/mcp'}}
    gateway = object.__new__(managed_gateway.ManagedGateway)
    gateway.front = SimpleNamespace(store=SimpleNamespace(resource=rows.get))
    with pytest.raises(ExecutionDenied) as refused:
        gateway.resource(143970, 'mcp')
    assert refused.value.error_code == 'TERMS_RESTRICTED'
    assert 'https://faceabot.com/tools-mcp/x' in str(refused.value) and 'own client' in str(refused.value)
    assert gateway.resource(241601, 'mcp')['id'] == 241601


def test_order_puts_relayable_first_and_keeps_the_free_test(terms):
    from agent_market.concierge.gateway_exposure import order_key
    items = [{'id': 143970, 'task_standing': 1}, {'id': 241601, 'task_standing': 0},
             {'id': 5, 'task_standing': 0, 'slow_member': True}, {'id': 6, 'task_standing': 0}]
    assert [i['id'] for i in sorted(items, key=order_key)] == [241601, 6, 5, 143970]
    # search() keeps an item as 'free' when its first two places are (False, False): a slow one stays, a
    # terms-restricted one does not.
    assert order_key(items[2])[:2] == (False, False) and order_key(items[0])[:2] == (True, False)


@pytest.mark.parametrize('entry,slow', [
    (None, False), ((5, 0, 7350.0, 1), True), ((5, 0, 5900.0, 1), False),
    ((1, 0, 6100.0, 1), False), ((2, 0, 9000.0, 1), False), ((3, 0, 6000.0, 1), True),   # needs >= 3 runs for the ms test too
    ((3, 10, 2000.0, 2), True), ((2, 1, 1000.0, 1), True), ((1, 1, 1000.0, 1), False), ((7, 2, 1000.0, 1), False)])
def test_slow_member_thresholds(entry, slow):
    from agent_market.concierge.gateway_exposure import slow_member
    assert slow_member(entry) is slow


def test_the_edge_worker_hands_a_restricted_listing_to_origin(monkeypatch, tmp_path, request):
    from tests.test_edge_gateway_catalog import bridge, enable, mcp_resource
    edge, catalog = request.getfixturevalue('edge'), request.getfixturevalue('catalog')
    enable(edge, monkeypatch)
    rid = mcp_resource(edge, catalog)
    path = tmp_path / 'terms.json'
    path.write_text(json.dumps({'members': {str(rid): {'status': 'prohibits'}}}))
    monkeypatch.setattr(relay_terms, '_path', lambda: path)
    relay_terms.reset()
    before = edge.store.query('SELECT COUNT(*) FROM edge_gateway_runs')[0][0]
    monkeypatch.setattr(edge.service, 'prepare', lambda *a: pytest.fail('a restricted listing gets no Worker grant'))
    result = bridge(edge, rid, {'tool': 'get_weather', 'arguments': {'city': 'Tokyo'}}, testbench=True)
    assert result.status_code == 200 and result.json() == {'backend': 'origin'}
    assert not edge.calls and edge.store.query('SELECT COUNT(*) FROM edge_gateway_runs')[0][0] == before
    relay_terms.reset()


def test_a_restricted_listing_in_chat_has_no_run_here_or_call_lines(terms):
    """The Chat answer of a listing we do not relay says so first and gives no way to run it through us (검색과 RAG
    review, PM 11-18); a relayable listing keeps its lines."""
    from agent_market.concierge.fast_chat import FastConcierge
    base = {'kind': 'mcp', 'name': 'Mail', 'description': 'Mail tools', 'tools': ['lookup'], 'active_checked_at': 1794400000,
            'tools_schema': [{'name': 'lookup', 'inputSchema': {'type': 'object', 'properties': {}}}]}
    blocked = FastConcierge._brief({**base, 'id': 43775, 'url': 'https://x711.io/mcp',
                                    'usage_endpoint': 'https://agentconcierge.biz/api/gateway/mcp/43775'})
    assert blocked.splitlines()[1].startswith('Connection: ' + relay_terms.NOTE)
    assert 'Run here:' not in blocked and 'MCP config:' not in blocked and 'one POST' not in blocked
    assert 'Direct endpoint: https://x711.io/mcp' not in blocked or 'own client' in blocked
    open_ = FastConcierge._brief({**base, 'id': 241601, 'url': 'https://x.example/mcp',
                                  'usage_endpoint': 'https://agentconcierge.biz/api/gateway/mcp/241601'})
    assert not open_.splitlines()[1].startswith('Connection:') and 'Call:' in open_


def test_auto_run_reads_the_same_verdicts(terms):
    from agent_market.concierge import auto_run
    assert auto_run._terms_prohibit(143970) and not auto_run._terms_prohibit(241601) and not auto_run._terms_prohibit(1)


def test_a_verdict_changed_a_moment_ago_applies_to_the_next_request(tmp_path, monkeypatch):
    path = tmp_path / 'member_terms.json'
    path.write_text(json.dumps({'members': {}}))
    monkeypatch.setattr(relay_terms, '_path', lambda: path)
    relay_terms.reset()
    assert not relay_terms.restricted(7)
    path.write_text(json.dumps({'members': {'7': {'status': 'prohibits'}}}))
    assert relay_terms.restricted(7)       # no waiting interval: the new file is read at once
    path.write_text(json.dumps({'members': {'7': {'status': 'allowed'}}}))
    assert not relay_terms.restricted(7)
    relay_terms.reset()


def test_a_restricted_listing_that_is_also_a_pearl_carries_both(terms, tmp_path, monkeypatch):
    """The card of a pearl whose terms prohibit our relay says so twice, consistently (검색과 RAG bbe4e5b1 + T): the
    pearl field with relayed False, and the connection fields that send the caller to the provider (reason, note,
    direct_endpoint, no gateway steps)."""
    from agent_market import pearls_public
    from agent_market.concierge.connections import DIRECT_NOTE, public_agent
    listed = tmp_path / 'p.json'
    listed.write_text(json.dumps({'schema': pearls_public.SCHEMA, 'by_resource': {}, 'pearls': [
        {'resource_id': 43775, 'role': 'sec.filings.v1', 'level': 'final', 'terms': 'prohibits'}]}))
    monkeypatch.setenv('PEARLS_PUBLIC_PATH', str(listed))
    card = public_agent({'id': 43775, 'kind': 'mcp', 'name': 'x711', 'url': 'https://x711.io/mcp', 'tools': ['lookup']})
    assert card['pearl'] == {'level': 'final', 'roles': ['sec.filings.v1'], 'relayed': False}
    assert card['connection_available'] is False and card['connection_reason'] == 'terms_restricted'
    assert card['direct_endpoint'] == 'https://x711.io/mcp' and card['connection_note'].endswith(DIRECT_NOTE)
    assert 'connect_steps' not in card
