"""Explicit discovery options must survive routing without changing authority."""
from unittest.mock import Mock

import pytest

from agent_market.concierge.selection import QualityRecommender
from tests.test_fast_single_recommendation import catalog  # noqa: F401


@pytest.mark.parametrize('protocol', [None, 'auto', 'any', 'mcp', 'a2a'])
def test_options_reach_every_protocol_without_mutation(protocol):
    rec = object.__new__(QualityRecommender)
    rec._search_protocol = Mock(return_value=[])
    search = QualityRecommender.search.__wrapped__
    search(rec, 'weather forecast', kind=protocol, category='travel_maps_weather',
           auth_pref='none', hint='weather', exclude={17})
    assert rec._search_protocol.called
    for call in rec._search_protocol.call_args_list:
        if call.kwargs:
            assert call.kwargs['category'] == 'travel_maps_weather'
            assert call.kwargs['auth_pref'] == 'none'
            assert call.kwargs['hint'] == 'weather'
            assert call.kwargs['exclude'] == {17}
        else:
            assert call.args[2] == 'none'
            assert call.args[-2:] == ('weather', 'travel_maps_weather')


@pytest.mark.parametrize('options', [
    {'auth_pref': 'invented'}, {'auth_pref': {}}, {'hint': []},
    {'hint': 'x' * 501}, {'hint': 'weather\x00forecast'},
    {'category': []}, {'category': ' '}, {'category': 'x' * 257},
])
def test_invalid_options_never_reach_a_candidate_provider(options):
    rec = object.__new__(QualityRecommender)
    rec._search_protocol = Mock()
    assert QualityRecommender.search.__wrapped__(rec, 'weather', **options) == []
    rec._search_protocol.assert_not_called()


@pytest.mark.parametrize('protocol', ['any', 'auto', 'mcp'])
def test_category_filters_newer_irrelevant_category_before_pagination(catalog, protocol):
    _, front, _, add, now = catalog
    add('Other Category', report_at=now-1, category='web_search')
    chosen = add('Correct Category', report_at=now-30, category='travel_maps_weather')
    found = front.rec.search('weather forecast', kind=protocol, category='travel_maps_weather', limit=1)
    assert [r['id'] for r in found] == [chosen]


def test_authentication_preference_is_not_an_execution_grant(catalog):
    _, front, _, add, now = catalog
    add('Requires Key', kind='x402', report_at=now-1, auth_observed=1)
    public = add('No Key', kind='x402', report_at=now-20, auth_observed=0)
    assert [r['id'] for r in front.rec.search('weather forecast', kind='x402', auth_pref='none')] == [public]


def test_hint_cannot_turn_an_original_weather_goal_into_translation(catalog):
    _, front, _, add, now = catalog
    correct = add('Forecast', report_at=now-20)
    add('Translate', description='Text translation English Japanese', report_at=now-1)
    found = front.rec.search('weather forecast', kind='mcp', hint='text translation')
    assert [r['id'] for r in found] == [correct]


@pytest.mark.parametrize('value,usable', [
    ({'status': 'completed', 'message': 'processed'}, False),
    ({'ok': True, 'request_id': 'example'}, False),
    ({'status': 'done', 'message': 'Request completed.'}, False),
    ({'status': 'done', 'message': 'The temperature is 18 degrees.'}, True),
    ({'results': [], 'total': 0}, True),
])
def test_canned_completion_is_not_a_task_result_but_zero_results_remain_valid(value, usable):
    from agent_market.concierge.result_quality import _useful
    assert _useful(value, 'Find weather forecasts') is usable


def test_status_queries_keep_a_legitimate_status_response():
    from agent_market.concierge.result_quality import _useful
    assert _useful({'status': 'running'}, 'Check task status')


def test_every_literal_workflow_step_must_keep_the_named_subject():
    from agent_market.workflow_model_proposer import compile_proposal
    from agent_market.workflow_goal_policy import validate_goal
    from agent_market.workspace_access import WorkspaceInvalid
    from scripts.benchmark_macmini_model import envelope
    context = envelope('Find Python documentation using two steps')
    nodes = compile_proposal(context, {'query': 'Python documentation'})['nodes']
    nodes[1]['bindings'] = {}
    nodes[1]['input']['query'] = 'Rust documentation'
    with pytest.raises(WorkspaceInvalid):
        validate_goal(context, nodes)
    nodes[1]['input']['query'] = 'Python documentation'
    validate_goal(context, nodes)


@pytest.mark.parametrize('expiry,status,soon', [(99,'expired',False),(101,'oauth_authorized',True),(500,'oauth_authorized',False)])
def test_saved_oauth_expiry_never_claims_execution_authority(monkeypatch, expiry, status, soon):
    from agent_market.workspace_provider_connections import ProviderConnections, profile
    monkeypatch.setattr('agent_market.workspace_provider_connections.time.time', lambda: 100)
    resource = {'id': 1, 'name': 'Example', 'url': 'https://provider.example/mcp',
                'kind': 'mcp', 'active': 1, 'auth_method': 'oauth2', 'auth_observed': 1}
    record = {'resource_id': 1, 'fingerprint': profile(resource)['fingerprint'], 'method': 'oauth',
              'status': 'oauth_authorized', 'updated': 90, 'expires': expiry, 'revision': 1}
    core = object.__new__(ProviderConnections)
    dto = core._dto(record, resource)
    assert dto['status'] == status and dto['readiness']['expires_soon'] is soon
    assert dto['readiness']['requires_reconnect'] is (status == 'expired')
    assert dto['readiness']['execution_authorized'] is False
    assert dto['readiness']['automatic_refresh_supported'] is False
    assert dto['readiness']['authentication_checked'] is False


def test_explicit_name_lookup_does_not_depend_on_a_recency_shortlist(catalog, monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from agent_market.concierge.discovery import candidates
    from agent_market.legacy_vector_index import ModelDescriptor
    store, _, _, add, now = catalog
    rid = add('Unique Observatory', report_at=now-60)
    resource = dict(store.resource(rid))
    native = SimpleNamespace(backend='postgresql',_native_lexical=True,tx=lambda **kw:nullcontext())
    executed = []
    def execute(statement, params):
        assert 'LOWER(r.name)=LOWER(%s)' in statement
        assert 'LIMIT 300' not in statement
        assert params[1] == 'Unique Observatory' and 'Unique Observatory' not in statement
        executed.append(statement)
        return SimpleNamespace(fetchall=lambda:[(rid,)])
    native._execute = execute
    def resources(source, ids, *args):
        assert source is native and ids == [rid]
        return [resource]
    monkeypatch.setattr('agent_market.application_store_resource_batches.resources',resources)
    checks = []
    class Registry:
        def __init__(self, source):
            assert source is native
        def current(self, row, **kw):
            checks.append(row['id'])
            return {'id':'current-fixture-version'}
        def projection(self, row, **kw):
            return {'connection_readiness':{'verified_callable':True}}
    monkeypatch.setattr('agent_market.capability_registry.Registry',Registry)
    engine = SimpleNamespace(embeddings_enabled=True,
        model_descriptor=lambda:ModelDescriptor('synthetic-fixture',revision='v1'),
        discovery_embedding=Mock(side_effect=AssertionError('Exact lookup must not call an embedding model')))
    found = candidates(native,engine,'Find agent named Unique Observatory',kind='mcp')
    assert [row['id'] for row in found] == [rid] and executed and checks == [rid]
    engine.discovery_embedding.assert_not_called()
