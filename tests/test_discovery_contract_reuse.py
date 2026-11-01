"""Immutable parsing facts never replace current source or execution authority."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import json
from unittest.mock import Mock

import pytest

from agent_market.concierge import discovery_contracts as cache
from agent_market.concierge import execution_policy as policy


@pytest.fixture(autouse=True)
def isolated_immutable_caches(monkeypatch):
    monkeypatch.setattr(cache, '_schemas', OrderedDict())
    monkeypatch.setattr(cache, '_facts', cache.FactCache())


def resource(name='forecast'):
    tools = [{'name': name, 'description': 'Weather forecast', 'inputSchema': {
        'type': 'object', 'properties': {'city': {'type': 'string'}}, 'required': ['city']}}]
    return {'usage_tools': json.dumps(tools), 'usage_full_tools': json.dumps(tools)}


def test_contract_parsing_reuses_exact_public_content_and_returns_fresh_values(monkeypatch):
    build = Mock(wraps=policy._tools_for_uncached)
    monkeypatch.setattr(policy, '_tools_for_uncached', build)
    current = resource()

    @cache.contract_reads
    def request():
        first = policy.tools_for(current)
        first[0]['inputSchema']['properties']['city']['type'] = 'integer'
        again = policy.tools_for(current)
        assert again[0]['inputSchema']['properties']['city']['type'] == 'string'
        return again

    assert request()[0]['name'] == 'forecast'
    assert build.call_count == 1
    request()
    assert build.call_count == 1
    # Other execution/workspace consumers do not opt into this public cache.
    policy.tools_for(current)
    assert build.call_count == 2
    assert cache._request.get() is None


def test_changed_full_or_compact_content_and_hash_are_never_reused():
    current = resource()

    @cache.contract_reads
    def request():
        assert policy.tools_for(current)
        current['usage_full_hash'] = 'forged-or-stale-hash'
        assert not policy.tools_for(current)
        current.pop('usage_full_hash')
        current['usage_tools'] = json.dumps([{'name': 'other'}])
        assert not policy.tools_for(current)
    request()


def test_cache_key_and_parser_share_the_same_observation(monkeypatch):
    current = resource()
    original = policy._tools_for_uncached
    def changing_source(observed):
        current.update(resource('get_news'))
        return original(observed)
    monkeypatch.setattr(policy, '_tools_for_uncached', changing_source)

    @cache.contract_reads
    def request():
        assert policy.tools_for(current)[0]['name'] == 'forecast'
        assert policy.tools_for(current)[0]['name'] == 'get_news'
    request()


def test_mutable_sources_follow_original_validation_and_exception_cleans_request():
    current = resource()
    current = {k: json.loads(v) for k, v in current.items()}

    @cache.contract_reads
    def request():
        assert policy.tools_for(current)
        current['usage_full_tools'][0]['name'] = 'changed'
        assert not policy.tools_for(current)
        raise RuntimeError('Synthetic caller failure')
    with pytest.raises(RuntimeError): request()
    assert cache._request.get() is None


def test_request_cache_limits_and_independent_threads(monkeypatch):
    monkeypatch.setattr(cache, 'MAX_ENTRIES', 2)
    monkeypatch.setattr(cache, 'MAX_BYTES', 500)

    @cache.contract_reads
    def request(number):
        for item in range(8): policy.tools_for(resource('forecast_' + str(number) + '_' + str(item)))
        memo = cache._request.get()
        assert len(memo['items']) <= 2 and memo['bytes'] <= 500
        return policy.tools_for(resource('forecast_' + str(number)))[0]['name']
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(request, range(2))) == ['forecast_0', 'forecast_1']
    assert cache._request.get() is None


def test_schema_support_facts_include_denials_and_do_not_replace_argument_validation(monkeypatch):
    monkeypatch.setattr(cache, '_schemas', OrderedDict())
    original = policy.supported_schema
    called = Mock(wraps=original)
    monkeypatch.setattr(policy, 'supported_schema', called)
    allowed = {'inputSchema': {'type': 'object', 'properties': {'city': {'type': 'string'}}, 'required': ['city']}}
    denied = {'inputSchema': {'type': 'object', 'properties': {'city': {'$ref': 'https://untrusted.example/schema'}}}}
    for _ in range(2):
        assert policy.discovery_schema_supported(allowed)
        assert not policy.discovery_schema_supported(denied)
    assert called.call_count == 2
    # Actual execution still validates this invocation's arguments.
    with pytest.raises(policy.ExecutionDenied): policy.validate_arguments(allowed, {'city': 42})
    policy.validate_arguments(allowed, {'city': 'London'})
    changed = {'inputSchema': {**allowed['inputSchema'], 'type': 'string'}}
    assert not policy.discovery_schema_supported(changed)
    assert not policy.discovery_schema_supported({'inputSchema': True})


def test_schema_fact_cache_is_bounded_and_keeps_no_source_or_query(monkeypatch):
    monkeypatch.setattr(cache, '_schemas', OrderedDict())
    monkeypatch.setattr(cache, 'MAX_SCHEMAS', 3)
    for number in range(8):
        assert policy.discovery_schema_supported({'inputSchema': {'type': 'object', 'title': 'schema-' + str(number)}})
    assert len(cache._schemas) == 3
    assert all(type(key) is bytes and len(key) == 32 and type(value) is bool for key, value in cache._schemas.items())


def test_live_authority_is_not_part_of_contract_memoization():
    current = {**resource(), 'active': 1, 'kind': 'mcp', 'url': 'https://weather.example/mcp',
               'health_status': 'healthy', 'auth_observed': 0, 'eval_security': 'ok'}

    @cache.contract_reads
    def request():
        assert policy.tools_for(current)
        policy.admit(current, public=True)
        current['active'] = 0
        assert policy.tools_for(current)
        with pytest.raises(policy.ExecutionDenied): policy.admit(current, public=True)
    request()
