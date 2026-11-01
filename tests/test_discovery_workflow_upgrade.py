"""Quality and security checks use isolated catalogs and no provider network IO."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent_market.concierge.query_intent import interpret, explicit_name, missing_subjects
from agent_market.concierge.retrieval_metrics import capture, stage, count
from agent_market.concierge.discovery import candidates, normalize_task
from agent_market.concierge.hybrid_explore import explore
from agent_market.concierge.selection import search_terms
from agent_market.concierge.workflow_discovery import relevance
from agent_market.workflow_goal_policy import validate_query, validate_goal, search_topic
from agent_market.workflow_model_proposer import compile_proposal
from agent_market.workspace_access import WorkspaceInvalid
from scripts.benchmark_macmini_model import envelope
from tests.test_fast_single_recommendation import catalog, ask  # noqa: F401
from tests.test_workspace_growth import growth  # noqa: F401
from tests.test_workspace_typed_flows import typed_world, routing  # noqa: F401
from tests.test_workspace_model_proposal import request, response


@pytest.mark.parametrize('phrase', ['no translation', 'without translation', 'not translation',
    'exclude translation', 'excluding translation', 'avoid translation', 'do not translate'])
def test_negative_capabilities_are_separate_from_requested_terms(phrase):
    intent = interpret('Audio transcription with timestamps; ' + phrase)
    assert intent.original.endswith(phrase)
    assert 'audio' in intent.positive.casefold() and 'timestamps' in intent.positive
    assert intent.excluded
    assert not {'translation', 'translate'} & set(search_terms(intent.original))


def test_original_language_format_and_version_survive_capability_normalization():
    raw = 'Transcribe Korean audio version 2.1 to SRT subtitles with timestamps; no translation'
    intent = interpret(raw)
    text = intent.retrieval_text(normalize_task(raw))
    assert all(word in text for word in ('Korean', '2.1', 'SRT', 'timestamps'))
    assert 'translation' not in text
    assert intent.original == raw
    # Requests up to 2,000 characters are kept whole; conditions after 500 characters are never dropped.
    assert len(interpret('x' * 1000).original) == 1000


def test_korean_exclusions_are_preserved_without_literal_product_copy():
    intent = interpret('뉴스와 논문을 찾아줘. 번역은 제외하고 using two steps')
    assert '번역' in intent.excluded
    assert '번역' not in intent.positive and 'two steps' in intent.positive


@pytest.mark.parametrize('raw,expected', [('NimbusDocs', 'NimbusDocs'),
    ('Find the agent named Nimbus Docs', 'Nimbus Docs'), ('"Nimbus Observatory"', 'Nimbus Observatory'),
    ('find weather for Seoul', None), ('Find Nimbus', None)])
def test_exact_shortcut_is_restricted_to_explicit_names(raw, expected):
    assert explicit_name(raw) == expected


@pytest.mark.parametrize('topic,proposed,missing', [
    ('Python and PostgreSQL documentation', 'Python documentation', ('postgresql',)),
    ('FastAPI 0.115 documentation', 'fastapi reference 0.115', ()),
    ('파이썬 documentation', 'Python documentation', ()),
    ('Find news about Python; exclude Terraform', 'Python news', ()),
])
def test_all_named_subjects_are_preserved(topic, proposed, missing):
    assert missing_subjects(topic, proposed) == missing


def template(*names):
    return {'name': 'Public sources', 'description': 'Reviewed source collection',
            'nodes': [{'id': str(i), 'type': 'agent', 'name': n, 'data': {'tool': n}}
                      for i, n in enumerate(names)]}


@pytest.mark.parametrize('prohibition', ['exclude GDP', 'without economic indicators', '경제지표 제외'])
def test_templates_never_execute_an_explicitly_excluded_capability(prohibition):
    query = 'Find news and research papers; ' + prohibition
    assert relevance(template('News Search', 'Research Papers'), query) > 0
    assert relevance(template('News Search', 'Research Papers', 'GDP Indicator'), query) == 0


def test_negative_subtype_does_not_discard_all_news():
    assert relevance(template('Sports News'), 'Find news; exclude financial news') > 0


def test_topic_omission_is_rejected_even_when_one_name_matches():
    with pytest.raises(WorkspaceInvalid):
        validate_query({'objective': 'Find API documentation about FastAPI and PostgreSQL'}, 'FastAPI reference')
    validate_query({'objective': 'Find API documentation about FastAPI and PostgreSQL'}, 'FastAPI PostgreSQL reference')


def test_declared_returned_title_needs_an_actual_output_binding():
    ctx = envelope('Find news about robotics then search documentation using the first returned title')
    good = compile_proposal(ctx, {'query': 'robotics'})
    validate_goal(ctx, good['nodes'])
    for change in ('literal', 'wrong_path', 'missing_after'):
        bad = copy.deepcopy(good['nodes'])
        if change == 'literal':
            bad[1]['bindings'] = {}; bad[1]['input']['query'] = 'robotics'
        elif change == 'wrong_path': bad[1]['bindings']['query']['path'] = ['items', 0, 'url']
        else: bad[1]['after'] = []
        with pytest.raises(WorkspaceInvalid): validate_goal(ctx, bad)


def test_independent_named_subjects_keep_their_own_queries():
    ctx = envelope('Find documentation for 3 topics: Docker, Kubernetes and Terraform')
    value = compile_proposal(ctx, {'query': search_topic(ctx['objective'])})
    assert [n['input']['query'] for n in value['nodes']] == ['Docker documentation', 'Kubernetes documentation', 'Terraform documentation']
    assert all(not n['bindings'] and not n['after'] for n in value['nodes'])


def native_shortcut_fixture(monkeypatch, *, ready=True, url='https://nimbus.example/mcp'):
    row = {'id': 1, 'name': 'NimbusDocs', 'description': 'Search documentation', 'kind': 'mcp', 'url': url}
    cursor = SimpleNamespace(fetchall=lambda: [(1,)])
    store = SimpleNamespace(backend='postgresql', tx=lambda **_: nullcontext(),
                            _execute=lambda *args: cursor, _vector_index=None)
    monkeypatch.setattr('agent_market.application_store_resource_batches.resources', lambda *args, **kwargs: [row])
    monkeypatch.setattr('agent_market.concierge.task_requirements.supported_discovery_connection', lambda r: True)
    registry = SimpleNamespace(current=lambda *a, **kw: {'id': 'current'},
        projection=lambda *a, **kw: {'connection_readiness': {'verified_callable': ready}})
    monkeypatch.setattr('agent_market.capability_registry.Registry', lambda store: registry)
    engine = SimpleNamespace(embeddings_enabled=True, model_descriptor=lambda: SimpleNamespace(digest='model-v1'),
                             discovery_embedding=Mock(return_value=None))
    return store, engine


def test_verified_native_exact_lookup_skips_embedding_and_records_only_numbers(monkeypatch):
    store, engine = native_shortcut_fixture(monkeypatch)
    with capture() as measured:
        result = candidates(store, engine, 'Find the agent named NimbusDocs', kind='mcp')
    assert [r['id'] for r in result] == [1]
    engine.discovery_embedding.assert_not_called()
    assert measured['counts']['exact_shortcuts'] == 1
    assert 'NimbusDocs' not in json.dumps(measured)


@pytest.mark.parametrize('ready,url', [(False, 'https://nimbus.example/mcp'), (True, 'http://127.0.0.1/private')])
def test_unverified_or_unsafe_name_does_not_bypass_normal_retrieval(monkeypatch, ready, url):
    store, engine = native_shortcut_fixture(monkeypatch, ready=ready, url=url)
    with capture() as measured: candidates(store, engine, 'NimbusDocs', kind='mcp')
    engine.discovery_embedding.assert_called_once()
    assert not measured['counts'].get('exact_shortcuts')


def test_spans_are_request_local_and_never_accept_arbitrary_query_labels():
    def one(n):
        with capture() as data:
            with stage('lexical'): count('lexical_candidates', n)
        return data
    with ThreadPoolExecutor(max_workers=4) as pool:
        values = list(pool.map(one, range(8)))
    assert [v['counts']['lexical_candidates'] for v in values] == list(range(8))
    with pytest.raises(ValueError):
        with stage('private customer query'): pass


def test_explicit_name_explore_keeps_gate_and_does_not_write_registry(catalog, monkeypatch):
    store, _, _, add, _ = catalog
    rid = add('Nimbus Observatory', description='Weather forecasts and temperature data')
    monkeypatch.setattr('agent_market.concierge.hybrid_explore.candidates', lambda *a, **kw: [dict(store.resource(rid))])
    before = store.query('SELECT COUNT(*) FROM connection_versions')[0][0]
    result = explore(store, None, 'Find the agent named Nimbus Observatory', 'mcp', None, False, False, 45)
    assert [r['id'] for r in result['items']] == [rid]
    assert store.query('SELECT COUNT(*) FROM connection_versions')[0][0] == before


def test_chat_negated_capability_is_not_used_as_a_recommendation(catalog):
    _, _, client, add, now = catalog
    # Chat admits MCP listings through a callable tool contract.
    good = add('Python documentation', description='Python API documentation and references', report_at=now-30,
        category='docs_knowledge',usage_guide=json.dumps({'tools':[{'name':'search_documentation',
            'description':'Search Python API documentation and references',
            'inputSchema':{'type':'object','properties':{'query':{'type':'string'}},'required':['query']}}]}))
    bad = add('News source', description='News headlines and stories', report_at=now-1)
    value = ask(client, 'Find Python API documentation; exclude news', data={'protocol':'mcp'})
    ids = [r['id'] for r in value['data']['recommendations']]
    assert good in ids and bad not in ids


@pytest.mark.parametrize('from_adapter', [False, True])
def test_missing_title_binding_explains_needed_change_without_creating_review(growth, from_adapter):
    from agent_market.workflow_goal_policy import GoalNeedsDetails
    g = growth
    def propose(ctx):
        if from_adapter:
            raise GoalNeedsDetails('Connect the next search to the returned title using a reviewed input binding.')
        value = response(ctx)
        for node in value['nodes']: node['input']['query'] = 'Python documentation'
        return value
    g.factory.model_proposer = propose
    value = g.factory.prepare_model_proposal(g.w.ws, request(
        objective='Find Python documentation then search documentation using the first returned title'), g.w.actor)
    assert value['state'] == 'needs_details'
    assert 'binding' in value['missing_requirements'][0]
    assert value['model_calls'] == 1 and value['agent_calls'] == 0
    assert not g.w.calls and not g.w.store.query('SELECT id FROM workspace_factory_reviews')


@pytest.mark.parametrize('query', ['Find not only news but documentation', 'Find no more than three news results'])
def test_idioms_and_numeric_bounds_are_not_removed_as_capability_exclusions(query):
    assert not interpret(query).excluded


def test_offline_runner_reports_failed_meaning_check_without_query_or_runtime_io():
    from tools.evaluate_discovery_workflow import run
    result = run([{'profile': 'topic', 'name': 'Missing database product',
        'input': 'Find documentation about FastAPI and PostgreSQL',
        'query': 'FastAPI reference', 'expected': 'accepted'}])
    assert result['cases'] == 1 and result['passed'] == 0
    assert not result['provider_calls'] and not result['model_calls']
    assert not result['production_slo_measured'] and 'FastAPI' not in json.dumps(result)
