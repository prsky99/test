"""The larger schema-check memo returns exactly the original results, keyed by schema content (11-11)."""
import json

import pytest

from agent_market.concierge import execution_policy as ep, schema_cache


SCHEMAS = [
    {'type': 'object', 'properties': {'q': {'type': 'string'}}},
    {'type': 'object', 'properties': {'n': {'type': 'integer', 'minimum': 1}}, 'required': ['n']},
    {'type': 'object', 'properties': {'q': {'type': 'string', 'pattern': '(a+)+$'}}},  # refused
    {'type': 'object', 'properties': {'q': {'type': 7}}},  # malformed
]


def _encoded(schema):
    return json.dumps(schema, sort_keys=True, separators=(',', ':'), allow_nan=False)


def test_cached_results_equal_the_original_check():
    cache = schema_cache.ContentCache(ep._checked_validator.__wrapped__, size=8)
    original = ep._checked_validator.__wrapped__
    for schema in SCHEMAS:
        mine, theirs = cache(_encoded(schema)), original(_encoded(schema))
        assert (mine[0] is None) == (theirs[0] is None) and mine[1] == theirs[1]
        if mine[0] is not None:
            for value in ({'q': 'x'}, {'q': 1}, {'n': 0}, {'n': 2}, {}):
                assert mine[0].is_valid(value) == theirs[0].is_valid(value)
        again = cache(''.join(list(_encoded(schema))))  # a different string object, the same content
        assert again is mine
    assert cache.cache_info().misses == len(SCHEMAS) and cache.cache_info().hits == len(SCHEMAS)


def test_the_memo_stays_within_its_size_and_installs_once():
    cache = schema_cache.ContentCache(lambda encoded: (encoded, None), size=3)
    for n in range(10):
        cache('{"n":%d}' % n)
    assert cache.cache_info().currsize == 3
    installed = schema_cache.install()
    assert schema_cache.install() is installed and ep._checked_validator is installed
    assert installed.cache_info().maxsize == schema_cache.SIZE
    with pytest.raises(ep.ExecutionDenied):
        ep.supported_schema({'inputSchema': SCHEMAS[2]})
