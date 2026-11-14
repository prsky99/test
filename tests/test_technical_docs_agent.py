"""Technical Documentation (QA 19): MDN for web topics, Context7 otherwise, kept outside the research/news digest."""
from datetime import datetime, timezone
import json
from types import SimpleNamespace

import httpx
import pytest

from agent_market.capability_contracts import validate
from agent_market.owned_data_agents import docs
from agent_market.owned_data_agents.engine import DataUnavailable

NOW = datetime(2026, 10, 31, 8, 0, tzinfo=timezone.utc)


def agent(handler, **kwargs):
    http = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    return docs.DocsAgent(http=http, utc_now=lambda: NOW, **kwargs), http


def mdn(request):
    assert request.url.host == 'developer.mozilla.org' and request.url.params['q'] == 'CSS grid layout'
    return httpx.Response(200, json={'documents': [
        {'mdn_url': '/en-US/docs/Web/CSS/Guides/Grid_layout', 'title': 'CSS grid layout', 'summary': 'A two-dimensional grid.'},
        {'mdn_url': 'https://evil.example/x', 'title': 'Off-site', 'summary': 'dropped'}]})


def context7(calls):
    def handle(request):
        calls.append(request.url.path)
        assert request.url.host == 'context7.com'
        if request.url.path == '/api/v1/search':
            return httpx.Response(200, json={'results': [
                {'id': '/grafana/rollout-operator', 'title': 'Rollout Operator', 'state': 'finalized', 'totalSnippets': 900},
                {'id': '/kubernetes/website', 'title': 'Kubernetes', 'state': 'finalized', 'totalSnippets': 25000},
                {'id': '/websites/kubernetes_io', 'title': 'Kubernetes', 'state': 'finalized', 'totalSnippets': 30000}]})
        calls.append(request.url.params['topic'])
        return httpx.Response(200, json={'snippets': [
            {'codeTitle': 'Check rollout status', 'codeDescription': 'Watch a Deployment rollout.',
             'websiteUrl': 'https://kubernetes.io/docs/concepts/workloads/controllers/deployment/', 'generationDate': '2026-10-20T04:18:14Z'},
            {'codeTitle': 'Unknown', 'websiteUrl': 'https://kubernetes.io/x'},
            {'codeTitle': 'Repo fixture', 'codeId': 'https://github.com/kubernetes/website/blob/main/a.md#_snippet_1'}]})
    return handle


def test_web_topics_use_mdn_and_keep_only_mdn_links():
    core, http = agent(mdn)
    with http:
        data = core.execute({'query': 'CSS grid layout', 'limit': 3})['data']
    assert data['source'] == 'MDN Web Docs'
    assert [item['url'] for item in data['items']] == ['https://developer.mozilla.org/en-US/docs/Web/CSS/Guides/Grid_layout']


def test_other_topics_use_the_named_context7_documentation_site():
    calls = []
    core, http = agent(context7(calls))
    with http:
        data = core.execute({'query': 'Kubernetes deployment rollout', 'limit': 3})['data']
        again = core.execute({'query': 'kubernetes  deployment rollout', 'limit': 3})
    assert data['source'] == 'Context7' and data['items'][0]['library'] == 'Kubernetes'
    assert data['items'][0]['indexed_at'] == '2026-10-20'
    # Titles keep their product so a follow-up step that searches a title still names Kubernetes.
    assert [item['title'] for item in data['items']] == ['Kubernetes: Check rollout status', 'Kubernetes: Repo fixture']
    assert data['items'][1]['url'] == 'https://github.com/kubernetes/website/blob/main/a.md'
    # Kubernetes has a pinned official site: no library search call at all.
    assert calls == ['/api/v1/websites/kubernetes_io', 'Kubernetes deployment rollout']
    assert again['cache']['status'] == 'fresh_cache'


def test_unpinned_topics_search_and_prefer_the_named_documentation_site(monkeypatch):
    monkeypatch.setattr(docs, 'official_library', lambda query: None)
    calls = []
    core, http = agent(context7(calls))
    with http:
        data = core.execute({'query': 'Kubernetes deployment rollout', 'limit': 3})['data']
    assert data['items'][0]['library'] == 'Kubernetes'
    # The query names Kubernetes, so the Kubernetes documentation site is read, not the first search hit.
    assert calls == ['/api/v1/search', '/api/v1/websites/kubernetes_io', 'Kubernetes deployment rollout']


def test_official_sites_win_for_names_search_ranks_poorly():
    """QA 19: "Django" found django-filter; the earliest named product picks its official site."""
    assert docs.official_library('Django model forms validation')['id'] == '/websites/djangoproject_en'
    assert docs.official_library('docker compose healthcheck')['id'] == '/websites/docker_compose'
    assert docs.official_library('Docker build cache')['id'] == '/websites/docker_reference'
    assert docs.official_library('Deploy React on Kubernetes')['id'] == '/websites/react_dev'
    assert docs.official_library('Kubernetes: Check rollout status')['id'] == '/websites/kubernetes_io'
    # Other packages that merely contain a pinned name keep the search path.
    assert docs.official_library('react-router loaders') is None
    assert docs.official_library('django-filter FilterSet') is None
    assert docs.official_library('pandas merge') is None


def test_context7_daily_allowance_fails_closed(monkeypatch, caplog):
    monkeypatch.setattr(docs, 'CONTEXT7_DAILY_CALLS', 1)
    core, http = agent(context7([]))
    with http, caplog.at_level('WARNING', logger=docs.__name__):
        core.execute({'query': 'Kubernetes deployment rollout', 'limit': 3})
        for query in ('Kubernetes rollback history', 'Kubernetes pod probes'):
            with pytest.raises(DataUnavailable):
                core.execute({'query': query, 'limit': 3})
    # One warning a day for operators watching the shared anonymous allowance, not one per refusal.
    assert [r.getMessage() for r in caplog.records].count('Context7 daily allowance used up: 1 calls on 2026-10-31') == 1


def test_private_text_is_rejected_before_networking():
    core, http = agent(lambda request: pytest.fail('no network'))
    with http:
        for query in ('token=abc123 docs', 'see https://example.com', 'mail me@example.com'):
            with pytest.raises(ValueError):
                core.execute({'query': query, 'limit': 1})


def resource():
    tool = docs.tool_spec()
    return {'id': 7, 'key': docs.KEY, 'source': 'agentconcierge-owned', 'kind': 'mcp',
            'url': 'https://agentconcierge.biz/api/owned-data-agents/technical-docs/mcp',
            'usage_full_tools': json.dumps([tool])}


def test_adapter_projects_into_docs_contract():
    from agent_market import capability_adapter_dispatch as adapters
    from agent_market.docs_capability_adapter import PROFILE
    res = resource()
    current = adapters.profile(res, 'docs.search.v1', 'search_technical_docs')
    assert current['id'] == PROFILE
    supplied = {'query': 'Kubernetes deployment rollout', 'language': 'en', 'limit': 2}
    assert adapters.arguments(res, 'docs.search.v1', 'search_technical_docs', supplied, expected=current) == \
        {'query': 'Kubernetes deployment rollout', 'limit': 2}
    retrieved = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    output = {'agent': docs.ID, 'source': {'name': 'MDN Web Docs and Context7', 'url': 'https://developer.mozilla.org/'},
              'retrieved_at': retrieved, 'cache': {'status': 'live', 'age_seconds': 0},
              'data': {'query': supplied['query'], 'source': 'Context7', 'partial': False, 'items': [
                  {'title': 'Check rollout status', 'url': 'https://kubernetes.io/docs/a/', 'summary': 'Watch it.',
                   'library': 'Kubernetes', 'indexed_at': '2026-10-20'},
                  {'title': 'Second', 'url': 'https://kubernetes.io/docs/b/', 'summary': '', 'library': 'Kubernetes', 'indexed_at': ''}]}}
    value = adapters.normalize(res, 'docs.search.v1', 'search_technical_docs', supplied, output, expected=current)
    validate('docs.search.v1', supplied, value)
    assert value['items'][0]['version'] == 'Indexed 2026-10-20'
    assert value['items'][1]['excerpt'] == 'Documentation page from Kubernetes.'
    assert value['items'][1]['version'] == 'Current Kubernetes page'
    with pytest.raises(ValueError):
        adapters.arguments(res, 'docs.search.v1', 'search_technical_docs', supplied, expected={**current, 'implementation_hash': 'x'})


def test_research_and_news_digest_is_unchanged():
    """Saved workflows pin this digest; adding Technical Documentation must not move it.

    11-14 (948d26df): the package-advisories (OSV) path now names each record's database and license and drops
    non-commercial databases. That moved this digest because engine.py and catalog.py are hashed whole; the
    research-papers and technology-news tool specs and code paths are unchanged (same schema digests), so saved
    research and news digests keep their contracts and need only ``scripts.approve_model_contracts`` after the
    frontend deploy."""
    from agent_market import owned_capability_adapter
    assert owned_capability_adapter.IMPLEMENTATION == '9afacb80d53ee3c53d59cfc12bd58719716e6c07a1421656e35f9e81afedd1f8'


def test_documentation_objectives_use_the_docs_agent_and_research_keeps_papers():
    from agent_market.workspace_app_factory import AppFactory
    keys = {1: 'mcp:app.openkrill/papers', 2: 'agentconcierge-owned:research-papers', 3: docs.KEY, 4: 'news'}
    factory = AppFactory.__new__(AppFactory)
    factory.store = SimpleNamespace(resource=lambda rid: {'key': keys[rid]})
    candidates = [{'resource_id': rid, 'contract_id': 'docs.search.v1'} for rid in (1, 2, 3)] + \
        [{'resource_id': 4, 'contract_id': 'news.search.v1'}]
    ids = lambda objective: [item['resource_id'] for item in factory._route_docs(objective, candidates)]
    assert ids('Find Kubernetes documentation then Docker documentation') == [3, 4]
    assert ids('Find recent research papers about battery recycling') == [1, 2, 4]
    assert ids('Find recent AI news') == [1, 2, 4]
    assert ids('Find research papers and the reference documentation for PyTorch') == [1, 2, 3, 4]


def test_mcp_route_serves_the_docs_tool(monkeypatch):
    from fastapi.testclient import TestClient
    from agent_market.owned_data_agents.service import create_app
    calls = []
    monkeypatch.setattr(docs, 'engine', lambda: SimpleNamespace(execute=lambda arguments: calls.append(arguments) or {
        'agent': docs.ID, 'source': {'name': 'MDN Web Docs and Context7', 'url': 'https://developer.mozilla.org/'},
        'retrieved_at': '2026-10-31T08:00:00Z', 'cache': {'status': 'live', 'age_seconds': 0},
        'data': {'query': arguments['query'], 'source': 'MDN Web Docs', 'items': [], 'partial': False}}))
    with TestClient(create_app(enabled=True)) as client:
        path = '/api/owned-data-agents/technical-docs/mcp'
        listed = client.post(path, json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {}}).json()
        assert listed['result']['tools'] == [docs.tool_spec()]
        called = client.post(path, json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {
            'name': 'search_technical_docs', 'arguments': {'query': 'CSS grid', 'limit': 1}}}).json()
        assert called['result']['structuredContent']['agent'] == docs.ID and calls == [{'query': 'CSS grid', 'limit': 1}]
        assert client.post('/api/owned-data-agents/no-such/mcp', json={'jsonrpc': '2.0', 'id': 3, 'method': 'tools/list', 'params': {}}).status_code == 404


def test_local_execution_refuses_a_changed_registration():
    store = SimpleNamespace(resource=lambda rid: {'active': True})
    result = docs.execute_local(store, resource(), 'search_technical_docs', {'query': 'CSS grid', 'limit': 1}, None)
    assert result == {'ok': False, 'error_code': 'SCHEMA_CHANGED', 'error': 'The registered capability needs review.'}


from tests.test_owned_data_agents import engine  # noqa: F401,E402
from tests.test_customer_typed_authoring import customer_flow, typed_release_world, typed_world, routing  # noqa: F401,E402


def test_saved_documentation_workflow_runs_through_local_execution(customer_flow, monkeypatch):  # noqa: F811
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from agent_market.capability_contracts import run_test
    from agent_market.capability_registry import Registry
    from agent_market.owned_data_agents.activation import install
    from agent_market.workspace_app_factory import NOTICE
    from agent_market.workspace_typed_flows import NOTICE as RUN_NOTICE
    from tests.test_customer_ten_workflows import definition
    x = customer_flow; calls = []; docs_site = context7(calls)
    core, http = agent(lambda request: httpx.Response(200, json={'documents': [{'mdn_url': '/en-US/docs/Web/API/AbortController',
        'title': 'AbortController', 'summary': 'Aborts requests.'}]}) if request.url.host == 'developer.mozilla.org' else docs_site(request))
    core.utc_now = lambda: datetime.now(timezone.utc)
    monkeypatch.setattr(docs, 'engine', lambda: core)
    install(x.w.store, 'https://agentconcierge.biz')
    rid = x.w.store.query('SELECT id FROM resources WHERE key=?', (docs.KEY,))[0]['id']
    assert docs.check_source(x.w.store, rid) and x.w.store.resource(rid)['health_status'] == 'healthy'
    resource = x.w.store.resource(rid); registry = Registry(x.w.store)
    registry.approve(resource, 'docs.search.v1', 'search_technical_docs')

    async def runner(identity, **kwargs):
        result = x.w.rt.proxy.execute(identity, kwargs['tool'], kwargs['arguments'], public=True)
        return {'execution_succeeded': result.get('ok') is True, 'simulated': False, 'output': result.get('result')}
    with ThreadPoolExecutor(1) as pool:
        checked = pool.submit(lambda: asyncio.run(run_test(registry, resource, 'docs.search.v1',
            {'query': 'Kubernetes deployment rollout', 'language': 'en', 'limit': 1}, runner))).result(timeout=5)
    assert checked['ok'], checked
    graph = definition([rid, rid], 'Kubernetes deployment rollout', 2)
    for node in graph['nodes']:
        node['contract_id'] = 'docs.search.v1'
    body = {'name': 'Kubernetes documentation', 'definition': graph, 'base_flow_id': None, 'base_revision': None}
    review = x.core.factory.prepare_plan(x.ws, body, x.actor)
    flow = x.core.factory.commit(x.ws, {'review_id': review['review_id'], 'authorized': True, 'notice': NOTICE}, x.actor)
    ticket = x.core.typed.prepare(x.ws, flow['id'], {'revision': 1}, x.actor)
    run = x.core.typed.execute(x.ws, flow['id'], {'ticket_id': ticket['ticket_id'], 'authorized': True, 'notice': RUN_NOTICE}, x.actor)['run']
    http.close()
    assert run['status'] == 'succeeded', [(s.get('status'), s.get('error_code'), s.get('error'), s.get('input')) for s in run['steps']]
    first = run['steps'][0]['output']['items'][0]
    assert first['url'].startswith('https://kubernetes.io/docs/') and first['version'] == 'Indexed 2026-10-20'
    assert calls[:2] == ['/api/v1/websites/kubernetes_io', 'Kubernetes deployment rollout']


def test_reverifier_keeps_docs_execution_evidence_current(customer_flow, monkeypatch):  # noqa: F811
    """The approval-driven contract loop, not _refresh_owned (SPECS only), keeps docs evidence current."""
    import time as clock
    from agent_market.capability_registry import Registry
    from agent_market.model_contract_reverify import ContractReverifier, INTERVAL
    from agent_market.owned_data_agents.activation import install
    x = customer_flow; calls = []; docs_site = context7(calls)
    core, http = agent(lambda request: httpx.Response(200, json={'documents': []}) if request.url.host == 'developer.mozilla.org' else docs_site(request))
    core.utc_now = lambda: datetime.now(timezone.utc)
    monkeypatch.setattr(docs, 'engine', lambda: core)
    install(x.w.store, 'https://agentconcierge.biz')
    rid = x.w.store.query('SELECT id FROM resources WHERE key=?', (docs.KEY,))[0]['id']
    assert docs.check_source(x.w.store, rid)
    registry = Registry(x.w.store)
    registry.approve(x.w.store.resource(rid), 'docs.search.v1', 'search_technical_docs')
    before = len(calls)
    later = clock.time() + INTERVAL + 60
    report = ContractReverifier(x.w.store, x.w.rt.proxy, clock=lambda: later).run()
    http.close()
    assert report['succeeded'] >= 1 and len(calls) > before
    ready = registry.projection(x.w.store.resource(rid))['connection_readiness']
    assert ready['verified_callable'] and ready['verified_at'] > later - INTERVAL - 120


def test_reverifier_recovers_docs_after_a_failed_health_read(customer_flow, monkeypatch):  # noqa: F811
    """QA 19: one failed read left the docs agent "failing"; health changes clear eligibility and
    execution refuses failing listings, so only a real source read can restore it."""
    import time as clock
    from agent_market.capability_registry import Registry
    from agent_market.model_contract_reverify import ContractReverifier, INTERVAL
    from agent_market.owned_data_agents.activation import install
    x = customer_flow; calls = []; docs_site = context7(calls)
    core, http = agent(lambda request: httpx.Response(200, json={'documents': []}) if request.url.host == 'developer.mozilla.org' else docs_site(request))
    core.utc_now = lambda: datetime.now(timezone.utc)
    monkeypatch.setattr(docs, 'engine', lambda: core)
    install(x.w.store, 'https://agentconcierge.biz')
    rid = x.w.store.query('SELECT id FROM resources WHERE key=?', (docs.KEY,))[0]['id']
    assert docs.check_source(x.w.store, rid)
    registry = Registry(x.w.store)
    registry.approve(x.w.store.resource(rid), 'docs.search.v1', 'search_technical_docs')
    x.w.store.record_health(rid, 'failing', None, None, 'Public data source unavailable.', clock.time() + 120)
    report = ContractReverifier(x.w.store, x.w.rt.proxy, clock=lambda: clock.time() + INTERVAL + 60).run()
    http.close()
    assert x.w.store.resource(rid)['health_status'] == 'healthy' and report['succeeded'] >= 1
    assert registry.projection(x.w.store.resource(rid))['connection_readiness']['verified_callable']
