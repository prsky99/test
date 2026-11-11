"""Catalog routing preserves current execution authority and pinned schemas."""
import base64
from copy import deepcopy
from dataclasses import replace

import pytest

from agent_market.collector import usage
from agent_market.edge_gateway.config import Config, EdgeError, PROFILE
from agent_market.edge_gateway.state import host_control, transaction
from tests.test_edge_gateway import edge, catalog, service_request, ORIGIN
from tests.test_mcp_proxy import WEATHER_TOOL, DESTRUCTIVE_TOOL


def enable(edge, monkeypatch):
    edge.service.config = replace(edge.config, providers=(), catalog_protocols=('a2a', 'mcp', 'x402'))
    monkeypatch.setattr('agent_market.edge_gateway.catalog.validate_public_url', lambda url: edge.checks.append(url))
    edge.front.courier.resolve = lambda _kind, url, **kw: {'url': url, 'v1': True}


def bridge(edge, rid, value, **extra):
    return service_request(edge, 'public-prepare', {'resource_id': rid, 'input': value,
        'origin': ORIGIN, 'idempotency_key': 'catalog-test-' + str(rid), **extra})


def mcp_resource(edge, catalog, tools=None):
    tools = tools or [WEATHER_TOOL]
    rid = catalog[3]('Public MCP', kind='mcp')
    compact = usage.compact_tools(tools)
    edge.store.record_usage(rid, tools=compact, digest=usage.tools_hash(compact), guide={'tools': tools},
                           changes=None, trial={'ok': True}, full_tools=tools)
    return rid


def test_catalog_configuration_is_explicit_and_protocol_bounded():
    value = {'profile': PROFILE, 'shared_secret': base64.b64encode(b'e' * 32).decode(),
             'public_origin': ORIGIN, 'providers': [], 'worker_ready': True}
    with pytest.raises(EdgeError): Config.from_dict(value)
    assert Config.from_dict({**value, 'catalog_protocols': ['a2a', 'mcp', 'x402']}).catalog_protocols == ('a2a', 'mcp', 'x402')
    for bad in ('a2a', ['a2a', 'a2a'], ['http'], [True]):
        with pytest.raises(EdgeError): Config.from_dict({**value, 'catalog_protocols': bad})
    with pytest.raises(EdgeError): Config.from_dict({**value, 'catalog_protocols': ['a2a'], 'canary_principal': 'a' * 64})


@pytest.mark.parametrize('guide,expected', [
    ({'protocol_version': '2025-06-18'}, '2025-06-18'),
    ('{"protocol_version":"2025-11-25"}', '2025-11-25'),
    ({'protocol_version': '2026-07-28'}, None),
    ({'protocol_version': {'untrusted': True}}, None),
    ('invalid json', None), (None, None),
])
def test_only_known_registered_mcp_revisions_select_handshake(guide, expected):
    from agent_market.edge_gateway.catalog import mcp_revision
    assert mcp_revision({'usage_guide': guide}) == expected


def test_registered_mcp_revision_is_in_private_claim_binding(edge, catalog, monkeypatch):
    import json
    enable(edge, monkeypatch); rid = mcp_resource(edge, catalog)
    with edge.store.tx() as db:
        db.execute('UPDATE resources SET usage_guide=? WHERE id=?', (json.dumps({'protocol_version': '2025-06-18'}), rid))
    prepared = {'protocol_version': '2025-06-18', 'session_id': None, 'deadline_ms': 1}
    monkeypatch.setattr('agent_market.edge_gateway.mcp_control.prepare', lambda *a: prepared)
    response = bridge(edge, rid, {'tool': 'get_weather', 'arguments': {'city': 'Tokyo'}})
    assert response.status_code == 200
    assert response.json()['binding']['mcp_protocol_version'] == '2025-06-18'
    assert response.json()['binding']['mcp_prepared'] == prepared


def test_dynamic_a2a_1_binding_and_changed_input_are_pinned(edge, monkeypatch):
    enable(edge, monkeypatch)
    result = bridge(edge, edge.rid, {'message': 'What can you help with?'})
    assert result.status_code == 200, result.text
    grant = result.json()
    assert grant['backend'] == 'worker'
    assert grant['binding']['protocol'] == 'a2a' and grant['binding']['spec_version'] == '1.0'
    assert grant['binding']['request']['method'] == 'SendMessage'
    assert grant['binding']['profile'] == 'catalog-public-v1'
    assert edge.service.summary()['catalog_protocols'] == ['a2a', 'mcp', 'x402']
    changed = bridge(edge, edge.rid, {'message': 'A different question'})
    assert changed.status_code == 409 and changed.json()['error_code'] == 'IDEMPOTENCY_CONFLICT'
    assert not edge.calls


def test_mcp_live_schema_approval_and_argument_pin(edge, catalog, monkeypatch):
    enable(edge, monkeypatch); rid = mcp_resource(edge, catalog)
    value = {'tool': 'get_weather', 'arguments': {'city': 'Tokyo'}}
    result = bridge(edge, rid, value)
    assert result.status_code == 200, result.text
    grant = result.json(); binding = grant['binding']
    assert binding['protocol'] == 'mcp' and binding['request']['params'] == {'name': 'get_weather', 'arguments': {'city': 'Tokyo'}}
    assert binding['mcp_schema_hash'] == edge.store.resource(rid)['usage_full_hash']
    review = {'run_id': grant['run_id'], 'attempt_id': binding['attempt_id'], 'tools': [WEATHER_TOOL], 'input': value}
    assert service_request(edge, 'mcp-schema', review).json() == {'approved': True}
    assert service_request(edge, 'mcp-schema', {**review, 'input': {**value, 'arguments': {'city': 'London'}}}).status_code == 409
    changed = deepcopy(WEATHER_TOOL); changed['inputSchema']['properties']['city']['maxLength'] = 8
    assert service_request(edge, 'mcp-schema', {**review, 'tools': [changed]}).status_code == 409
    assert bridge(edge, rid, value).status_code == 403
    assert not edge.calls


def test_full_mcp_input_constraints_are_checked_before_hash_approval(edge, catalog, monkeypatch):
    enable(edge, monkeypatch)
    spec = deepcopy(WEATHER_TOOL); spec['inputSchema']['properties']['city']['maxLength'] = 3
    rid = mcp_resource(edge, catalog, [spec])
    denied = bridge(edge, rid, {'tool': 'get_weather', 'arguments': {'city': 'Tokyo'}})
    # An argument outside the schema goes to the Origin gateway, which answers -32602 (11-11).
    assert denied.status_code == 200 and denied.json() == {'backend': 'origin'} and not edge.calls


def test_inconsistent_full_and_compact_safety_metadata_cannot_get_hash_approval(edge, catalog, monkeypatch):
    import json
    from agent_market.capability_registry import digest, full_tools
    enable(edge, monkeypatch); rid = mcp_resource(edge, catalog)
    changed = deepcopy(WEATHER_TOOL); changed['annotations'] = {'destructiveHint': True}
    full = full_tools([changed])
    with edge.store.tx() as db:
        db.execute('UPDATE resources SET usage_full_tools=?,usage_full_hash=? WHERE id=?', (json.dumps(full), digest(full), rid))
    response = bridge(edge, rid, {'tool': 'get_weather', 'arguments': {'city': 'Tokyo'}})
    # Inconsistent complete contracts may be refused during admission, before
    # the later schema-approval boundary. Neither path may contact the provider.
    assert response.status_code in (403, 409) and not edge.calls


def test_full_schema_normalization_preserves_remote_compact_tool_order(edge, catalog, monkeypatch):
    enable(edge, monkeypatch)
    second = deepcopy(WEATHER_TOOL); second['name'] = 'get_status'
    rid = mcp_resource(edge, catalog, [WEATHER_TOOL, second])
    response = bridge(edge, rid, {'tool': 'get_weather', 'arguments': {'city': 'Tokyo'}})
    assert response.status_code == 200 and response.json()['binding']['mcp_schema_hash']
    assert not edge.calls


@pytest.mark.parametrize('case', ['auth', 'paid', 'unsafe-tool', 'bad-args', 'quarantine'])
def test_mcp_admission_denies_before_dispatch(edge, catalog, monkeypatch, case):
    enable(edge, monkeypatch)
    tools = [DESTRUCTIVE_TOOL] if case == 'unsafe-tool' else [WEATHER_TOOL]
    rid = mcp_resource(edge, catalog, tools)
    field, value = ('auth_observed', 1) if case == 'auth' else ('price_usdc', 1) if case == 'paid' else ('health_status', 'quarantined')
    if case in ('auth', 'paid', 'quarantine'):
        with edge.store.tx() as db: db.execute('UPDATE resources SET ' + field + '=? WHERE id=?', (value, rid))
    response = bridge(edge, rid, {'tool': tools[0]['name'], 'arguments': {} if case == 'bad-args' else {'city': 'Tokyo'}})
    if case == 'bad-args':
        # 11-11 real tasks p02/p05/a05: a schema mismatch is not a key or policy refusal. The Origin
        # gateway repeats the check and answers -32602; nothing is prepared or dispatched here.
        assert response.status_code == 200 and response.json() == {'backend': 'origin'}, response.text
        with transaction(edge.store, readonly=True) as db:
            assert db.execute("SELECT count(*) FROM edge_gateway_runs").fetchone()[0] == 0
    else:
        assert response.status_code == 403, response.text
    assert not edge.calls


def test_x402_probe_allows_challenge_but_never_payment(edge, catalog, monkeypatch):
    enable(edge, monkeypatch)
    rid = catalog[3]('Public Challenge', kind='x402', price=100, auth_observed=1)
    bad = bridge(edge, rid, {'action': 'pay', 'payment': 'secret'})
    assert bad.status_code == 400
    response = bridge(edge, rid, {'action': 'probe'})
    assert response.status_code == 200, response.text
    assert response.json()['binding']['protocol'] == 'x402'
    assert response.json()['binding']['request']['method'] == 'probe'
    assert not edge.calls


def test_testbench_normalizes_by_protocol_and_origin_policy_precedes_admission(edge, catalog, monkeypatch):
    enable(edge, monkeypatch); rid = mcp_resource(edge, catalog)
    result = bridge(edge, rid, {'message': '', 'tool': 'get_weather', 'arguments': {'city': 'Tokyo'}}, testbench=True)
    assert result.status_code == 200 and result.json()['input'] == {'tool': 'get_weather', 'arguments': {'city': 'Tokyo'}}
    current = edge.service.summary()
    host_control(edge.store, 'origin', current['revision'], 'Isolated Origin policy test')
    assert bridge(edge, rid + 50000, {}).json() == {'backend': 'origin'}
    assert not edge.calls


def test_unsupported_http_profile_falls_back_before_claim(edge, catalog, monkeypatch):
    enable(edge, monkeypatch)
    rid = catalog[3]('HTTP Resource', kind='mcp')
    with edge.store.tx() as db: db.execute('UPDATE resources SET url=? WHERE id=?', ('http://public.example/mcp', rid))
    assert bridge(edge, rid, {'tool': 'get_weather', 'arguments': {'city': 'Tokyo'}}).json() == {'backend': 'origin'}
    assert not edge.calls
