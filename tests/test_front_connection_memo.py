"""Request-local badge memoization must not alias mutable public cards."""

import copy

from agent_market.capability_registry import Registry
from agent_market.concierge.front import refresh_connection_states


class Resources:
    def __init__(self, prefix):
        self.prefix = prefix
        self.calls = []
        self.report_queries = 0

    def resource(self, rid):
        self.calls.append(rid)
        return {'id': rid, 'name': self.prefix, 'kind': 'mcp'} if rid != 3 else None

    def query(self, sql, params=()):
        self.report_queries += 1
        return []


def test_duplicate_cards_reuse_one_lookup_but_own_independent_projection_values(monkeypatch):
    store = Resources('First request')
    projections = []

    def project(registry, resource, version=None):
        projections.append(resource['id'])
        return {'connection_readiness': {'verified_callable': True, 'reason': resource['name']},
                'capability_contracts': [{'id': 'docs.search.v1', 'verified': True}]}

    monkeypatch.setattr(Registry, 'projection', project)
    # 11-11: the refresh reads the recorded version without creating one (a public read writes nothing).
    monkeypatch.setattr(Registry, 'current', lambda registry, resource, create=True: {'id': 'cv_fixture'})
    card = {'id': 1, 'agent_ref': 'agent_1', 'connection_readiness': {'verified_callable': False}}
    cached = {'overview': [card, copy.deepcopy(card)], 'explore': {'items': [copy.deepcopy(card)]}}
    before = copy.deepcopy(cached)
    result = refresh_connection_states(store, cached)
    assert store.calls == projections == [1]
    assert store.report_queries == 1
    result['overview'][0]['connection_readiness']['verified_callable'] = False
    result['overview'][0]['capability_contracts'][0]['verified'] = False
    for other in (result['overview'][1], result['explore']['items'][0]):
        assert other['connection_readiness']['verified_callable']
        assert other['capability_contracts'][0]['verified']
    assert cached == before


def test_memo_is_reset_for_next_request_and_different_store(monkeypatch):
    monkeypatch.setattr(Registry, 'projection', lambda registry, resource, version=None: {
        'connection_readiness': {'verified_callable': True, 'reason': resource['name']}})
    monkeypatch.setattr(Registry, 'current', lambda registry, resource, create=True: {'id': 'cv_fixture'})
    first, second = Resources('Current'), Resources('Other store')
    card = {'id': 1, 'agent_ref': 'agent_1'}
    assert refresh_connection_states(first, [card, card])[0]['connection_readiness']['reason'] == 'Current'
    first.prefix = 'Changed after first request'
    assert refresh_connection_states(first, [card, card])[1]['connection_readiness']['reason'] == 'Changed after first request'
    assert refresh_connection_states(second, card)['connection_readiness']['reason'] == 'Other store'
    assert first.calls == [1, 1] and second.calls == [1]


def test_missing_resource_is_memoized_once_and_clears_every_cached_verification(monkeypatch):
    monkeypatch.setattr(Registry, 'projection', lambda *_: (_ for _ in ()).throw(AssertionError('Missing resource projected')))
    store = Resources('Fixture')
    card = {'id': 3, 'agent_ref': 'agent_3', 'capability_contracts': [{'id': 'docs.search.v1', 'verified': True}],
            'connection_readiness': {'verified_callable': True}}
    result = refresh_connection_states(store, [card, card])
    assert store.calls == [3]
    assert store.report_queries == 0
    for item in result:
        assert item['connection_readiness']['verified_callable'] is False
        assert item['capability_contracts'][0]['verified'] is False
    result[0]['capability_contracts'][0]['verified'] = True
    assert result[1]['capability_contracts'][0]['verified'] is False
    assert card['capability_contracts'][0]['verified'] is True
