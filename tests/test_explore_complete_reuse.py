"""Load More reuses a search that already examined every candidate; nothing else changes."""
import hashlib
import hmac
import json

from agent_market.concierge import discovery_contracts as dc
from agent_market.concierge.front import _ExploreResultCache
from agent_market.concierge.protocols import merge_discovery_results


def _group(ids, *, complete, total=None):
    return {'query': '', 'items': [{'id': i, 'name': f'n{i}'} for i in ids],
            'total': len(ids) if total is None else total, 'total_is_estimate': True, 'complete': complete}


def test_complete_result_answers_a_wider_window_of_the_same_search():
    cache = _ExploreResultCache()
    first = ('store', 'sentiment analysis', None, None, False, False, 46)
    cache.put(first, {'items': [{'id': 1}], 'complete': True})
    wider = first[:-1] + (91,)
    assert cache.complete(wider) == {'items': [{'id': 1}], 'complete': True}
    # Another search, filter or protocol never borrows it.
    assert cache.complete(('store', 'sentiment', None, None, False, False, 91)) is None
    assert cache.complete(('store', 'sentiment analysis', 'mcp', None, False, False, 91)) is None
    assert cache.complete(('store', 'sentiment analysis', None, None, True, False, 91)) is None


def test_a_window_limited_result_is_not_reused_and_expiry_applies():
    cache = _ExploreResultCache(ttl=0.0)
    key = ('store', 'dns record check', None, None, False, False, 46)
    cache.put(key, {'items': [{'id': 1}], 'complete': False})
    assert cache.complete(key[:-1] + (91,)) is None
    cache.put(key, {'items': [{'id': 1}], 'complete': True})
    assert cache.complete(key[:-1] + (91,)) is None  # expired at once with ttl=0
    cache = _ExploreResultCache()
    cache.put(key, {'items': [], 'complete': True})
    cache.clear()
    assert cache.complete(key[:-1] + (91,)) is None


def test_merged_result_is_complete_only_when_every_protocol_is_and_nothing_is_cut():
    assert merge_discovery_results([_group([1, 2], complete=True), _group([3], complete=True)], 46)['complete'] is True
    assert merge_discovery_results([_group([1, 2], complete=True), _group([3], complete=False)], 46)['complete'] is False
    assert merge_discovery_results([_group([1, 2], complete=True), _group([3], complete=True)], 2)['complete'] is False
    assert merge_discovery_results([_group([1], complete=True), {**_group([2], complete=True), 'complete': None}], 46)['complete'] is False


def _reference_fingerprint(facts, query, resource, terms, core):
    from agent_market.explore_documents import cache_view
    resource = cache_view(resource)
    digest = hmac.new(facts.key, digestmod=hashlib.sha256)
    for name, value in [('query', query), ('terms', terms), ('core', core), *sorted(resource.items())]:
        kind = type(value).__name__.encode()
        encoded = (value.encode('utf-8', 'surrogatepass') if type(value) is str else
                   json.dumps(value, sort_keys=True, allow_nan=False, ensure_ascii=True).encode())
        label = str(name).encode('utf-8', 'surrogatepass')
        for part in (kind, label, encoded):
            digest.update(len(part).to_bytes(8, 'big')); digest.update(part)
    return digest.digest()


def test_task_fact_keys_are_unchanged_by_the_single_pass_encoding():
    facts = dc.TaskFacts()
    values = [None, True, False, 0, 1, -7, 10 ** 30, 1.5, -0.0, '', 'weather', '한글\ud800', [1, None, 'a'],
              {'b': 1, 'a': [True]}]
    for index in range(len(values)):
        resource = {f'f{j}': values[(index + j) % len(values)] for j in range(len(values))}
        for terms, core in ((None, None), (['weather'], ['forecast'])):
            assert facts.fingerprint('weather', resource, terms, core) == _reference_fingerprint(
                facts, 'weather', resource, terms, core)
    # True and 1 stay distinct keys, as their type names differ.
    assert facts.fingerprint('q', {'x': True}, None, None) != facts.fingerprint('q', {'x': 1}, None, None)
